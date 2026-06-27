"""Module 4.4 — Cleaning & flags (per-instrument).

Reads panels/book_snap/{iid}.parquet
Writes panels/book_clean/{iid}.parquet

Adds:
  - zero/NaN price+qty levels → NaN
  - crossed flag (bid >= ask)
  - two_sided flag
  - tick_size per instrument
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .book import snap_dir, get_snap_path
from .utils import (
    load_config,
    panels_dir,
    save_manifest,
    setup_logging,
)

logger = logging.getLogger(__name__)

BID_PX = [f"bid_px_{i}" for i in range(1, 6)]
BID_QTY = [f"bid_qty_{i}" for i in range(1, 6)]
ASK_PX = [f"ask_px_{i}" for i in range(1, 6)]
ASK_QTY = [f"ask_qty_{i}" for i in range(1, 6)]


def clean_dir(cfg: dict) -> Path:
    d = panels_dir(cfg) / "book_clean"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_clean_path(cfg: dict, iid: str) -> Path:
    return clean_dir(cfg) / f"{iid}.parquet"


def list_snap_instruments(cfg: dict) -> list[str]:
    d = snap_dir(cfg)
    return [p.stem for p in d.glob("*.parquet")]


def _nan_zero_levels(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for i in range(1, 6):
        bp, bq = f"bid_px_{i}", f"bid_qty_{i}"
        ap, aq = f"ask_px_{i}", f"ask_qty_{i}"
        bad_bid = (df[bp] == 0) | (df[bq] == 0)
        df.loc[bad_bid, [bp, bq]] = np.nan
        bad_ask = (df[ap] == 0) | (df[aq] == 0)
        df.loc[bad_ask, [ap, aq]] = np.nan
    return df


def _derive_tick_size(df: pd.DataFrame) -> float:
    prices = pd.concat([df[c] for c in BID_PX + ASK_PX]).dropna()
    prices = np.sort(prices[prices > 0].unique())
    if len(prices) < 2:
        return np.nan
    diffs = np.diff(prices)
    diffs = diffs[diffs > 0]
    if len(diffs) == 0:
        return np.nan
    rounded = np.round(diffs, 0)
    counts = pd.Series(rounded).value_counts()
    return float(counts.index[0])


def _clean_chunk(df: pd.DataFrame) -> pd.DataFrame:
    """Apply cleaning flags to a DataFrame chunk."""
    df = _nan_zero_levels(df)
    b1, a1 = df["bid_px_1"], df["ask_px_1"]
    bq1, aq1 = df["bid_qty_1"], df["ask_qty_1"]
    both = b1.notna() & a1.notna() & (b1 > 0) & (a1 > 0)
    df["mid"] = np.where(both, (b1 + a1) / 2.0, np.nan)
    denom = bq1.fillna(0) + aq1.fillna(0)
    df["microprice"] = np.where(
        both & (denom > 0), (b1 * aq1.fillna(0) + a1 * bq1.fillna(0)) / denom, np.nan
    )
    df["spread"] = np.where(both, a1 - b1, np.nan)
    df["rel_spread"] = np.where(
        both & df["mid"].notna() & (df["mid"] > 0), df["spread"] / df["mid"], np.nan
    )
    df["crossed"] = (b1 >= a1) & both
    df.loc[df["crossed"], "mid"] = np.nan
    df["two_sided"] = b1.notna() & a1.notna() & (b1 > 0) & (a1 > 0) & ~df["crossed"]
    return df


def process_instrument(cfg: dict, iid: str) -> pd.DataFrame | None:
    snap_path = get_snap_path(cfg, iid)
    out_path = get_clean_path(cfg, iid)

    if not snap_path.exists():
        return None

    # Skip if already cleaned (don't reload large files)
    if out_path.exists():
        return None  # already done

    # Read in date-based chunks to manage memory
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(snap_path)

    day_chunks = []
    all_prices_for_tick: list[pd.Series] = []

    # Read the file in row-groups (one per original day typically)
    for rg_idx in range(pf.metadata.num_row_groups):
        chunk = pf.read_row_group(rg_idx).to_pandas()
        if len(chunk) == 0:
            continue
        chunk = _clean_chunk(chunk)
        all_prices_for_tick.append(
            pd.concat([chunk[c] for c in BID_PX + ASK_PX]).dropna()
        )
        day_chunks.append(chunk)

    if not day_chunks:
        return None

    # Derive tick size from all price data
    all_prices = pd.concat(all_prices_for_tick).values
    all_prices = np.sort(all_prices[all_prices > 0])
    if len(all_prices) >= 2:
        diffs = np.diff(all_prices)
        diffs = diffs[diffs > 0]
        if len(diffs) > 0:
            tick = float(pd.Series(np.round(diffs, 0)).value_counts().index[0])
        else:
            tick = np.nan
    else:
        tick = np.nan

    df = pd.concat(day_chunks, ignore_index=True)
    df["tick_size"] = tick
    df.to_parquet(out_path, index=False)
    return df


def run(cfg: dict) -> dict:
    instruments = list_snap_instruments(cfg)
    logger.info("Cleaning %d instruments …", len(instruments))

    total_crossed = 0
    total_rows = 0
    tick_sizes = {}

    for i, iid in enumerate(instruments):
        df = process_instrument(cfg, iid)
        if df is not None:
            total_rows += len(df)
            total_crossed += int(df["crossed"].sum())
            tick_sizes[iid] = float(df["tick_size"].iloc[0]) if len(df) > 0 else np.nan
        if i % 50 == 0:
            logger.info("Clean: %d/%d done …", i, len(instruments))

    logger.info(
        "Cleaning complete: %d rows, %d crossed", total_rows, total_crossed
    )

    stats = {
        "n_rows_total": total_rows,
        "crossed_rows": total_crossed,
        "n_instruments_with_tick": sum(1 for v in tick_sizes.values() if not np.isnan(v)),
    }
    save_manifest(cfg, {"clean": stats})
    return stats


if __name__ == "__main__":
    setup_logging()
    cfg = load_config()
    run(cfg)
