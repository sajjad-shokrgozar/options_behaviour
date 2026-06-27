"""Module 4.5 — Time & session split (per-instrument).

Adds session_phase ∈ {preopen, continuous} to each instrument's book_clean.
"""
from __future__ import annotations

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
    to_seconds,
)

logger = logging.getLogger(__name__)


def _time_str_to_seconds(t: str) -> float:
    parts = t.split(":")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])


def process_instrument(
    cfg: dict,
    iid: str,
    fallback_open_s: float,
    fallback_close_s: float,
    trade_bounds: dict | None = None,
) -> tuple[int, int] | None:
    """Returns (preopen_count, continuous_count) or None if skipped."""
    path = get_clean_path(cfg, iid)
    if not path.exists():
        return None

    import pyarrow.parquet as pq
    pf = pq.ParquetFile(path)
    schema = pf.schema_arrow

    # Check if session_phase already exists
    if "session_phase" in schema.names:
        return None  # already done

    # Read only the columns needed for session assignment
    light_cols = [c for c in ["date", "hEven", "ts"] if c in schema.names]
    day_chunks = []

    for rg_idx in range(pf.metadata.num_row_groups):
        chunk = pf.read_row_group(rg_idx, columns=light_cols).to_pandas()
        if len(chunk) == 0:
            continue

        if "ts" not in chunk.columns:
            chunk["ts"] = chunk["hEven"].apply(
                lambda x: to_seconds(x) if pd.notna(x) else np.nan
            )

        phases = []
        for dt, grp in chunk.groupby("date", sort=False):
            key = (str(iid), str(dt))
            if trade_bounds and key in trade_bounds:
                open_s, close_s = trade_bounds[key]
            else:
                open_s, close_s = fallback_open_s, fallback_close_s
            ts = grp["ts"]
            phase = pd.Series("continuous", index=grp.index, dtype=object)
            phase[(ts < open_s) | ts.isna()] = "preopen"
            phases.append(phase)

        chunk["session_phase"] = pd.concat(phases).reindex(chunk.index)
        day_chunks.append(chunk[["session_phase"]])

    if not day_chunks:
        return None

    session_col = pd.concat(day_chunks)["session_phase"]

    # Now read the full file in row groups and write with session_phase added
    out_chunks = []
    offset = 0
    for rg_idx in range(pf.metadata.num_row_groups):
        chunk = pf.read_row_group(rg_idx).to_pandas()
        n = len(chunk)
        chunk["session_phase"] = session_col.iloc[offset:offset + n].values
        out_chunks.append(chunk)
        offset += n

    df = pd.concat(out_chunks, ignore_index=True)
    df.to_parquet(path, index=False)

    preopen = int((df["session_phase"] == "preopen").sum())
    continuous = int((df["session_phase"] == "continuous").sum())
    return preopen, continuous


def run(cfg: dict) -> dict:
    instruments = list_snap_instruments(cfg)
    sess_cfg = cfg["session"]
    fallback_open_s = _time_str_to_seconds(sess_cfg["fallback_open"])
    fallback_close_s = _time_str_to_seconds(sess_cfg["fallback_close"])

    logger.info(
        "Applying session splits for %d instruments (open=%s, close=%s) …",
        len(instruments), sess_cfg["fallback_open"], sess_cfg["fallback_close"],
    )

    total_preopen = 0
    total_continuous = 0

    for i, iid in enumerate(instruments):
        result = process_instrument(cfg, iid, fallback_open_s, fallback_close_s)
        if result is not None:
            total_preopen += result[0]
            total_continuous += result[1]
        if i % 50 == 0:
            logger.info("Session: %d/%d done …", i, len(instruments))

    logger.info(
        "Session split done: preopen=%d, continuous=%d", total_preopen, total_continuous
    )

    stats = {
        "fallback_open": sess_cfg["fallback_open"],
        "fallback_close": sess_cfg["fallback_close"],
        "preopen_rows": total_preopen,
        "continuous_rows": total_continuous,
    }
    save_manifest(cfg, {"session": stats})
    return stats


if __name__ == "__main__":
    setup_logging()
    cfg = load_config()
    run(cfg)
