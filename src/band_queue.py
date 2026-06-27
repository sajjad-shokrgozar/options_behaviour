"""Module 4.9 — Band, queue, episodes, and τ.

Detects buy/sell queue regimes per option instrument using the option's own
bid/ask data and its daily band ceiling/floor.

Outputs:
  - panels/queue_episodes.parquet
  - panels/underlying_regime.parquet  (placeholder)
  - Updated synced/{iid}.parquet with regime, tau_min, episode_id
"""
from __future__ import annotations

import gc
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .sync import get_synced_path, list_synced_instruments
from .utils import (
    load_config,
    panels_dir,
    project_root,
    save_manifest,
    setup_logging,
)

logger = logging.getLogger(__name__)


def detect_band_pct(
    underlying_eod: pd.DataFrame,
    quantile: float = 0.99,
    official_pct: float | None = None,
) -> float:
    if official_pct is not None and official_pct > 0:
        logger.info("Using official band pct: %.2f%%", official_pct * 100)
        return float(official_pct)
    df = underlying_eod[
        (underlying_eod["yesterday"] > 0)
        & (underlying_eod["min"] > 0)
        & (underlying_eod["max"] > 0)
    ].copy()
    up_move = (df["max"] / df["yesterday"] - 1).abs()
    dn_move = (df["min"] / df["yesterday"] - 1).abs()
    all_moves = pd.concat([up_move, dn_move]).dropna()
    all_moves = all_moves[all_moves > 0]
    band = float(all_moves.quantile(quantile))
    logger.info("Empirical band (q=%.2f): %.4f (%.2f%%)", quantile, band, band * 100)
    return band


def classify_queue_snapshots(
    opt_by_date: dict,
    band_pct: float,
    at_limit_tol_ticks: int,
    min_persist: int,
    post_guard_min: float,
) -> tuple[dict, pd.DataFrame]:
    """
    Returns (regime_by_date, episodes_df).
    regime_by_date: {date_str -> DataFrame[ts, regime, tau_min, episode_id]}
    opt_by_date: {date_str: dict of numpy arrays (ts, bid_px_1, ask_px_1, ...)}
    Arrays must be sorted by ts.
    """
    episodes: list[dict] = []
    regime_by_date: dict[str, pd.DataFrame] = {}
    ep_id = 0

    for dt, day in sorted(opt_by_date.items()):
        ts_arr = day["ts"]
        n = len(ts_arr)
        bp1 = day.get("bid_px_1", np.zeros(n))
        ap1 = day.get("ask_px_1", np.zeros(n))
        bq1 = day.get("bid_qty_1", np.zeros(n))
        aq1 = day.get("ask_qty_1", np.zeros(n))
        tick = day.get("tick_size", np.ones(n))
        yest = day.get("yesterday_ref", np.full(n, np.nan))

        ceil_arr = np.where(~np.isnan(yest), yest * (1 + band_pct), np.nan)
        floor_arr = np.where(~np.isnan(yest), yest * (1 - band_pct), np.nan)

        regimes = np.full(n, "free", dtype=object)
        tau_min_arr = np.full(n, np.nan)
        episode_id_arr = np.full(n, np.nan)
        post_guard_end_s: float = -1e9
        current_ep: dict | None = None
        queue_run: list[int] = []
        current_side: str | None = None

        def snap_is_buy_queue(i: int) -> bool:
            ask_empty = np.isnan(aq1[i]) or aq1[i] == 0
            if not ask_empty:
                return False
            ceil = ceil_arr[i]
            if np.isnan(ceil):
                return False
            tk = tick[i] if not np.isnan(tick[i]) else 1.0
            b = bp1[i] if not np.isnan(bp1[i]) else 0.0
            return b > 0 and b >= ceil - at_limit_tol_ticks * tk

        def snap_is_sell_queue(i: int) -> bool:
            bid_empty = np.isnan(bq1[i]) or bq1[i] == 0
            if not bid_empty:
                return False
            flr = floor_arr[i]
            if np.isnan(flr):
                return False
            tk = tick[i] if not np.isnan(tick[i]) else 1.0
            a = ap1[i] if not np.isnan(ap1[i]) else 0.0
            return a > 0 and a <= flr + at_limit_tol_ticks * tk

        i = 0
        while i < n:
            t = ts_arr[i]
            if t <= post_guard_end_s:
                i += 1
                continue

            is_bq = snap_is_buy_queue(i)
            is_sq = snap_is_sell_queue(i)
            cand_side = "buy_queue" if is_bq else ("sell_queue" if is_sq else None)

            if cand_side:
                if current_side != cand_side:
                    if current_ep is not None:
                        current_ep["end_ts"] = ts_arr[queue_run[-1]] if queue_run else ts_arr[max(0, i - 1)]
                        current_ep["end_type"] = "released"
                        episodes.append(current_ep)
                        post_guard_end_s = current_ep["end_ts"] + post_guard_min * 60
                        current_ep = None
                    current_side = cand_side
                    queue_run = []

                queue_run.append(i)

                if len(queue_run) >= min_persist and current_ep is None:
                    ep_id += 1
                    current_ep = {
                        "episode_id": ep_id,
                        "side": cand_side,
                        "start_ts": ts_arr[queue_run[0]],
                        "date": str(dt),
                        "end_ts": None,
                        "end_type": "session_end",
                    }

                if current_ep is not None:
                    ep_start = current_ep["start_ts"]
                    regimes[i] = cand_side
                    tau_min_arr[i] = (t - ep_start) / 60.0
                    episode_id_arr[i] = ep_id

            else:
                if current_ep is not None:
                    current_ep["end_ts"] = ts_arr[max(0, i - 1)]
                    current_ep["end_type"] = "released"
                    episodes.append(current_ep)
                    post_guard_end_s = current_ep["end_ts"] + post_guard_min * 60
                    current_ep = None
                current_side = None
                queue_run = []

            i += 1

        if current_ep is not None:
            current_ep["end_ts"] = ts_arr[-1]
            current_ep["end_type"] = "session_end"
            episodes.append(current_ep)
            for j in queue_run:
                regimes[j] = current_ep["side"]
                tau_min_arr[j] = (ts_arr[j] - current_ep["start_ts"]) / 60.0
                episode_id_arr[j] = ep_id

        regime_by_date[str(dt)] = pd.DataFrame({
            "ts": ts_arr,
            "regime": regimes,
            "tau_min": tau_min_arr,
            "episode_id": episode_id_arr,
        })

    ep_df = pd.DataFrame(episodes) if episodes else pd.DataFrame(
        columns=["episode_id", "side", "start_ts", "date", "end_ts", "end_type"]
    )
    return regime_by_date, ep_df


def run(cfg: dict) -> tuple[dict, pd.DataFrame]:
    root = project_root()
    pdir = panels_dir(cfg)
    band_cfg = cfg["band"]
    queue_cfg = cfg["queue"]

    # Band pct from underlying EOD
    under_eod_path = root / cfg["paths"]["underlying_history"]
    under_eod = pd.read_csv(under_eod_path, encoding="utf-8")
    under_eod["date"] = under_eod["date"].astype(str)
    band_pct = detect_band_pct(
        under_eod,
        quantile=band_cfg["empirical_quantile"],
        official_pct=band_cfg.get("official_pct"),
    )
    del under_eod

    # Options EOD yesterday reference per (iid, date)
    opts_eod_path = root / cfg["paths"]["options_history"]
    opts_eod = pd.read_csv(opts_eod_path, encoding="utf-8")
    opts_eod["id"] = opts_eod["id"].astype(str)
    opts_eod["date"] = opts_eod["date"].astype(str)
    # {iid -> {date -> yesterday_close}}
    iid_yesterday: dict[str, dict[str, float]] = {}
    for row in opts_eod.itertuples(index=False):
        iid = str(row.id)
        dt = str(row.date)
        yest = float(row.yesterday) if pd.notna(row.yesterday) else np.nan
        iid_yesterday.setdefault(iid, {})[dt] = yest
    del opts_eod
    gc.collect()

    import pyarrow as pa
    import pyarrow.parquet as pq_opt

    OPT_QUEUE_COLS = ["date", "ts", "bid_px_1", "ask_px_1", "bid_qty_1", "ask_qty_1", "tick_size"]
    SKIP_COLS = {"regime", "tau_min", "episode_id"}

    synced_instruments = list_synced_instruments(cfg)
    logger.info(
        "Detecting queue episodes per option instrument (%d instruments) …",
        len(synced_instruments),
    )
    logger.info(
        "Queue params: band=%.2f%%, tol=%d ticks, min_persist=%d snaps, post_guard=%.0f min",
        band_pct * 100,
        band_cfg["at_limit_tol_ticks"],
        queue_cfg["min_persist_snapshots"],
        queue_cfg["post_queue_guard_min"],
    )

    all_episodes: list[pd.DataFrame] = []
    regime_counts = {"free": 0, "buy_queue": 0, "sell_queue": 0}
    ep_id_global = 0

    for iid in synced_instruments:
        sp = get_synced_path(cfg, iid)
        if not sp.exists():
            continue
        opt_pf = pq_opt.ParquetFile(sp, memory_map=True)
        if opt_pf.metadata.num_rows == 0:
            continue

        opt_schema_names = opt_pf.schema_arrow.names
        # Columns to read for the output (exclude old regime cols)
        read_cols = [c for c in opt_schema_names if c not in SKIP_COLS]
        # Columns needed for queue detection
        queue_read_cols = [c for c in OPT_QUEUE_COLS if c in opt_schema_names]
        float_queue_cols = [c for c in queue_read_cols if c != "date"]

        yesterday_by_iid = iid_yesterday.get(str(iid), {})

        # ── Pass 1: build per-date numpy arrays for queue detection ──────────
        opt_by_date_lists: dict[str, dict[str, list]] = {}

        for rg_idx in range(opt_pf.metadata.num_row_groups):
            batch = opt_pf.read_row_group(rg_idx, columns=queue_read_cols)
            date_np = np.array(batch.column("date").to_pylist())
            unique_dates = np.unique(date_np)
            batch_cols: dict[str, np.ndarray] = {}
            for col in float_queue_cols:
                series = batch.column(col).to_pandas()
                batch_cols[col] = series.to_numpy(dtype=float, na_value=np.nan)
            for dt_g_raw in unique_dates:
                dt_g = str(dt_g_raw)
                mask = date_np == dt_g_raw
                n_sub = int(mask.sum())
                if n_sub == 0:
                    continue
                if dt_g not in opt_by_date_lists:
                    opt_by_date_lists[dt_g] = {col: [] for col in float_queue_cols}
                    opt_by_date_lists[dt_g]["yesterday_ref"] = []
                for col in float_queue_cols:
                    opt_by_date_lists[dt_g][col].append(batch_cols[col][mask])
                yest_val = float(yesterday_by_iid.get(dt_g, np.nan))
                opt_by_date_lists[dt_g]["yesterday_ref"].append(np.full(n_sub, yest_val))
            del batch_cols

        # Concatenate and sort by ts
        opt_by_date_final: dict[str, dict[str, np.ndarray]] = {}
        for dt_g, col_lists in opt_by_date_lists.items():
            arrs = {col: np.concatenate(parts) for col, parts in col_lists.items()}
            order = np.argsort(arrs["ts"], kind="stable")
            opt_by_date_final[dt_g] = {col: arr[order] for col, arr in arrs.items()}
        del opt_by_date_lists
        gc.collect()

        # ── Queue detection ──────────────────────────────────────────────────
        regime_by_date, episodes = classify_queue_snapshots(
            opt_by_date_final,
            band_pct=band_pct,
            at_limit_tol_ticks=band_cfg["at_limit_tol_ticks"],
            min_persist=queue_cfg["min_persist_snapshots"],
            post_guard_min=queue_cfg["post_queue_guard_min"],
        )
        del opt_by_date_final

        n_ep = len(episodes)
        if n_ep > 0:
            episodes["episode_id"] = episodes["episode_id"] + ep_id_global
            for rdf in regime_by_date.values():
                ep_mask = rdf["episode_id"].notna()
                rdf.loc[ep_mask, "episode_id"] = rdf.loc[ep_mask, "episode_id"] + ep_id_global
            ep_id_global += n_ep
            episodes["instrument_id"] = str(iid)
            all_episodes.append(episodes)

        for rdf in regime_by_date.values():
            regime_counts["free"] += int((rdf["regime"] == "free").sum())
            regime_counts["buy_queue"] += int((rdf["regime"] == "buy_queue").sum())
            regime_counts["sell_queue"] += int((rdf["regime"] == "sell_queue").sum())

        if n_ep > 0:
            logger.info("  %s: %d queue episodes", iid, n_ep)

        # ── Pass 2: write updated synced file with regime columns ────────────
        # Pre-build output schema from source to avoid null-type mismatches
        src_schema = opt_pf.schema_arrow
        out_fields = [pa.field(f.name, f.type) for f in src_schema if f.name not in SKIP_COLS]
        out_fields += [
            pa.field("regime", pa.string()),
            pa.field("tau_min", pa.float64()),
            pa.field("episode_id", pa.float64()),
        ]
        output_schema = pa.schema(out_fields)
        schema_types = {f.name: f.type for f in output_schema}

        out_path = sp.with_suffix(".tmp.parquet")
        writer = pq_opt.ParquetWriter(out_path, output_schema)

        for rg_idx in range(opt_pf.metadata.num_row_groups):
            chunk = opt_pf.read_row_group(rg_idx, columns=read_cols).to_pandas(
                split_blocks=True, self_destruct=True
            )
            if len(chunk) == 0:
                continue
            chunk["date"] = chunk["date"].astype(str)

            for dt, grp in chunk.groupby("date", sort=False):
                grp_sorted = grp.sort_values("ts")
                n = len(grp_sorted)
                ur_day = regime_by_date.get(str(dt))
                if ur_day is None or len(ur_day) == 0:
                    regime_col = np.full(n, "free", dtype=object)
                    tau_col = np.full(n, np.nan)
                    ep_col = np.full(n, np.nan)
                else:
                    opt_ts = grp_sorted["ts"].to_numpy(dtype=float)
                    ur_ts = ur_day["ts"].values
                    idx = np.searchsorted(ur_ts, opt_ts, side="right") - 1
                    valid = idx >= 0
                    regime_col = np.where(valid, ur_day["regime"].values[np.maximum(idx, 0)], "free")
                    tau_col = np.full(n, np.nan)
                    ep_col = np.full(n, np.nan)
                    if valid.any():
                        tau_col[valid] = ur_day["tau_min"].values[idx[valid]]
                        ep_col[valid] = ur_day["episode_id"].values[idx[valid]]

                # Build PyArrow arrays column-by-column, coercing to output schema types
                arrays = []
                for col in grp_sorted.columns:
                    arr = pa.array(grp_sorted[col], from_pandas=True)
                    expected = schema_types.get(col)
                    if expected is not None and arr.type != expected:
                        # null type (all-NaN) → cast to expected type
                        arr = pa.nulls(len(arr), type=expected) if arr.type == pa.null() else arr.cast(expected)
                    arrays.append(arr)
                arrays.append(pa.array(regime_col, type=pa.string()))
                arrays.append(pa.array(tau_col, type=pa.float64()))
                arrays.append(pa.array(ep_col, type=pa.float64()))
                tbl = pa.Table.from_arrays(arrays, schema=output_schema)
                writer.write_table(tbl)

        del opt_pf
        gc.collect()

        if writer is not None:
            writer.close()
            try:
                sp.unlink()
                out_path.rename(sp)
            except PermissionError:
                out_path.unlink(missing_ok=True)
                logger.warning("Skipped locked file: %s", sp.name)

        gc.collect()

    # ── Assemble and write outputs ────────────────────────────────────────────
    if all_episodes:
        episodes_df = pd.concat(all_episodes, ignore_index=True)
    else:
        episodes_df = pd.DataFrame(
            columns=["episode_id", "instrument_id", "side", "start_ts", "date", "end_ts", "end_type"]
        )
    episodes_df.to_parquet(pdir / "queue_episodes.parquet", index=False)

    # Placeholder underlying_regime (detection is now per-option)
    pd.DataFrame(columns=["date", "ts", "regime", "tau_min", "episode_id"]).to_parquet(
        pdir / "underlying_regime.parquet", index=False
    )

    n_episodes = len(episodes_df)
    logger.info("Regime counts (all options): %s; Total episodes: %d", regime_counts, n_episodes)

    save_manifest(
        cfg,
        {
            "band_queue": {
                "band_pct": round(band_pct, 6),
                "n_episodes": n_episodes,
                "regime_counts": {k: int(v) for k, v in regime_counts.items()},
                "at_limit_tol_ticks": band_cfg["at_limit_tol_ticks"],
                "min_persist_snapshots": queue_cfg["min_persist_snapshots"],
                "post_queue_guard_min": queue_cfg["post_queue_guard_min"],
            }
        },
    )
    return {}, episodes_df


if __name__ == "__main__":
    setup_logging()
    cfg = load_config()
    run(cfg)
