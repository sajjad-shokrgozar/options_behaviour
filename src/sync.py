"""Module 4.7 — Cross-instrument synchronization (per option instrument).

For each option instrument, attaches as-of latest underlying state.
Writes panels/synced/{iid}.parquet per option instrument.
Also writes panels/synced_index.parquet (list of processed instruments).
"""
from __future__ import annotations

import gc
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .clean import clean_dir, get_clean_path, list_snap_instruments
from .utils import (
    load_config,
    panels_dir,
    save_manifest,
    setup_logging,
)

logger = logging.getLogger(__name__)

UNDER_KEEP_COLS = ["ts", "mid", "microprice", "bid_px_1", "ask_px_1", "OBI", "two_sided"]


def _asof_join(opt_ts: np.ndarray, under_ts: np.ndarray, under_df: pd.DataFrame, under_cols: list[str]) -> dict:
    """
    Lightweight backward as-of join via numpy searchsorted.
    Allocates one column at a time to avoid large contiguous allocation.
    Returns dict of u_col → ndarray (float64).
    """
    # under_ts must be sorted ascending (ensured by caller)
    idx = np.searchsorted(under_ts, opt_ts, side="right") - 1
    valid = idx >= 0
    result = {"u_ts": np.where(valid, under_ts[np.maximum(idx, 0)].astype(float), np.nan)}
    for col in under_cols:
        if col == "ts":
            continue
        vals = under_df[col].to_numpy(dtype=float, na_value=np.nan)
        out = np.empty(len(opt_ts), dtype=float)
        out[:] = np.nan
        if valid.any():
            out[valid] = vals[idx[valid]]
        result[f"u_{col}"] = out
    return result


def synced_dir(cfg: dict) -> Path:
    d = panels_dir(cfg) / "synced"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_synced_path(cfg: dict, iid: str) -> Path:
    return synced_dir(cfg) / f"{iid}.parquet"


def list_synced_instruments(cfg: dict) -> list[str]:
    return [p.stem for p in synced_dir(cfg).glob("*.parquet")]


def run(cfg: dict) -> dict:
    staleness_s = cfg["liquidity"]["staleness_window_s"]
    underlying_id = str(cfg["ids"]["underlying_id"])

    # Load underlying clean data
    under_path = get_clean_path(cfg, underlying_id)
    if not under_path.exists():
        logger.error("Underlying clean data not found: %s", under_path)
        return {}

    logger.info("Building per-date underlying index …")
    import pyarrow.parquet as pq_mod
    under_pf = pq_mod.ParquetFile(under_path, memory_map=True)
    under_schema_names = under_pf.schema_arrow.names
    under_cols_present = [c for c in UNDER_KEEP_COLS if c in under_schema_names]
    load_cols = ["date"] + under_cols_present

    # Build a per-date dict — store only under_cols_present (drop 'date' to save RAM)
    under_by_date: dict[str, pd.DataFrame] = {}
    for rg in range(under_pf.metadata.num_row_groups):
        chunk = under_pf.read_row_group(rg, columns=load_cols).to_pandas()
        chunk["date"] = chunk["date"].astype(str)
        for dt, grp in chunk.groupby("date", sort=False):
            # Keep only the columns needed for merge — drop 'date' from stored values
            grp_cols = grp[under_cols_present].sort_values("ts").reset_index(drop=True)
            if dt not in under_by_date:
                under_by_date[dt] = grp_cols
            else:
                under_by_date[dt] = pd.concat(
                    [under_by_date[dt], grp_cols]
                ).sort_values("ts").reset_index(drop=True)
    gc.collect()
    logger.info("Underlying index built for %d dates", len(under_by_date))

    # Identify option instruments
    all_instruments = list_snap_instruments(cfg)
    option_instruments = [iid for iid in all_instruments if str(iid) != underlying_id]
    logger.info("Syncing %d option instruments to underlying …", len(option_instruments))

    total_rows = 0
    total_fresh = 0
    processed = []

    for i, iid in enumerate(option_instruments):
        opt_path = get_clean_path(cfg, iid)
        if not opt_path.exists():
            continue

        # Skip if already synced and valid
        synced_path = get_synced_path(cfg, iid)
        if synced_path.exists():
            try:
                pq_mod.read_schema(synced_path)
                processed.append(str(iid))
                continue
            except Exception:
                try:
                    synced_path.unlink()
                except PermissionError:
                    logger.warning("Corrupted file locked, skipping: %s", synced_path)
                    continue

        import pyarrow as pa
        import pyarrow.parquet as pq_mod

        # Read option clean file row-group by row-group — memory_map avoids RAM copy
        opt_pf = pq_mod.ParquetFile(opt_path, memory_map=True)
        if opt_pf.metadata.num_row_groups == 0:
            continue

        out_path = get_synced_path(cfg, iid)
        writer = None
        iid_rows = 0
        iid_fresh = 0

        for rg_idx in range(opt_pf.metadata.num_row_groups):
            # split_blocks=True avoids consolidating all float cols into one 2D array
            chunk = opt_pf.read_row_group(rg_idx).to_pandas(split_blocks=True, self_destruct=True)
            if len(chunk) == 0:
                continue
            chunk["date"] = chunk["date"].astype(str)

            for dt, opt_grp in chunk.groupby("date", sort=False):
                opt_grp = opt_grp.sort_values("ts")
                under_day = under_by_date.get(str(dt), pd.DataFrame())
                if len(under_day) == 0:
                    opt_grp = opt_grp.copy()
                    for col in under_cols_present:
                        opt_grp[f"u_{col}"] = np.nan
                    opt_grp["under_quote_age_s"] = np.nan
                    opt_grp["opt_quote_age_s"] = np.nan
                    opt_grp["fresh"] = False
                else:
                    under_day_sorted = under_day.sort_values("ts")
                    under_ts_arr = under_day_sorted["ts"].to_numpy(dtype=float)
                    opt_ts_arr = opt_grp["ts"].to_numpy(dtype=float)

                    joined = _asof_join(opt_ts_arr, under_ts_arr, under_day_sorted, under_cols_present)
                    opt_grp = opt_grp.copy()
                    for k, v in joined.items():
                        opt_grp[k] = v

                    opt_grp["under_quote_age_s"] = opt_ts_arr - joined["u_ts"]
                    opt_grp["opt_quote_age_s"] = np.nan
                    opt_grp["fresh"] = (
                        ~np.isnan(joined["u_ts"])
                        & (opt_grp["under_quote_age_s"] <= staleness_s)
                        & ~np.isnan(joined.get("u_mid", np.array([np.nan])))
                    )
                    stale = ~opt_grp["fresh"]
                    for col in [f"u_{c}" for c in under_cols_present]:
                        if col in opt_grp.columns:
                            opt_grp.loc[stale, col] = np.nan

                # Ensure all u_* columns are float64 for consistent PyArrow schema
                for col in [f"u_{c}" for c in under_cols_present]:
                    if col in opt_grp.columns:
                        opt_grp[col] = opt_grp[col].astype(float)

                table = pa.Table.from_pandas(opt_grp, preserve_index=False)
                if writer is None:
                    writer = pq_mod.ParquetWriter(out_path, table.schema)
                writer.write_table(table)
                iid_rows += len(opt_grp)
                iid_fresh += int(opt_grp["fresh"].sum())

        if writer is None:
            continue
        writer.close()

        total_rows += iid_rows
        total_fresh += iid_fresh
        processed.append(str(iid))
        gc.collect()

        if i % 30 == 0:
            logger.info("Sync: %d/%d option instruments done …", i, len(option_instruments))

    fresh_rate = total_fresh / total_rows if total_rows else 0.0
    logger.info(
        "Sync complete: %d option instruments, %d rows, fresh_rate=%.1f%%",
        len(processed), total_rows, 100 * fresh_rate,
    )

    # Write index
    idx = pd.DataFrame({"instrument_id": processed})
    idx.to_parquet(panels_dir(cfg) / "synced_index.parquet", index=False)

    stats = {
        "n_option_instruments": len(processed),
        "n_rows": total_rows,
        "fresh_rate": round(fresh_rate, 4),
        "staleness_window_s": staleness_s,
    }
    save_manifest(cfg, {"sync": stats})
    return stats


if __name__ == "__main__":
    setup_logging()
    cfg = load_config()
    run(cfg)
