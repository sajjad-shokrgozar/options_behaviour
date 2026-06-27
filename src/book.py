"""Module 4.3 — 5-level snapshot reconstruction (per-instrument).

For each instrument, reads panels/book_raw/{iid}.parquet
Writes panels/book_snap/{iid}.parquet

One row per (date, refID) with:
ts, bid_px_1..5, bid_qty_1..5, ask_px_1..5, ask_qty_1..5,
mid, microprice, spread, rel_spread, depth_bid, depth_ask, OBI
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .ingest import get_instrument_raw_path, list_available_instruments, raw_dir
from .utils import (
    load_config,
    panels_dir,
    save_manifest,
    setup_logging,
    to_seconds,
)

logger = logging.getLogger(__name__)

BID_PX = [f"bid_px_{i}" for i in range(1, 6)]
BID_QTY = [f"bid_qty_{i}" for i in range(1, 6)]
ASK_PX = [f"ask_px_{i}" for i in range(1, 6)]
ASK_QTY = [f"ask_qty_{i}" for i in range(1, 6)]


def snap_dir(cfg: dict) -> Path:
    d = panels_dir(cfg) / "book_snap"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_snap_path(cfg: dict, iid: str) -> Path:
    return snap_dir(cfg) / f"{iid}.parquet"


def _pivot_day(day_df: pd.DataFrame) -> pd.DataFrame:
    """
    Pivot one day's raw order book rows into one-row-per-refID snapshot.
    Uses vectorized pandas pivot instead of row-by-row dict accumulation.
    """
    day_df = day_df.copy()
    # Filter valid levels only
    day_df = day_df[day_df["number"].between(1, 5)]

    if len(day_df) == 0:
        return pd.DataFrame()

    # Pivot bid (pMeDem, qTitMeDem) and ask (pMeOf, qTitMeOf) by level
    bid_px = day_df.pivot_table(
        index="refID", columns="number", values="pMeDem", aggfunc="first"
    )
    bid_qty = day_df.pivot_table(
        index="refID", columns="number", values="qTitMeDem", aggfunc="first"
    )
    ask_px = day_df.pivot_table(
        index="refID", columns="number", values="pMeOf", aggfunc="first"
    )
    ask_qty = day_df.pivot_table(
        index="refID", columns="number", values="qTitMeOf", aggfunc="first"
    )

    # Rename columns
    bid_px.columns = [f"bid_px_{int(c)}" for c in bid_px.columns]
    bid_qty.columns = [f"bid_qty_{int(c)}" for c in bid_qty.columns]
    ask_px.columns = [f"ask_px_{int(c)}" for c in ask_px.columns]
    ask_qty.columns = [f"ask_qty_{int(c)}" for c in ask_qty.columns]

    # Ensure all 5 levels exist
    for i in range(1, 6):
        for part, name in [(bid_px, f"bid_px_{i}"), (bid_qty, f"bid_qty_{i}"),
                           (ask_px, f"ask_px_{i}"), (ask_qty, f"ask_qty_{i}")]:
            if name not in part.columns:
                part[name] = np.nan

    # Combine all columns
    snap = pd.concat([bid_px, bid_qty, ask_px, ask_qty], axis=1)

    # Attach metadata (hEven from first row per refID, instrument_id, date)
    meta = day_df.groupby("refID")[["instrument_id", "date", "hEven"]].first()
    snap = meta.join(snap)
    snap = snap.reset_index()  # bring refID back as column
    return snap


def compute_metrics(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ts"] = df["hEven"].apply(lambda x: to_seconds(x) if pd.notna(x) else np.nan)

    b1 = df["bid_px_1"]
    a1 = df["ask_px_1"]
    bq1 = df["bid_qty_1"]
    aq1 = df["ask_qty_1"]
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
    df["depth_bid"] = df[BID_QTY].sum(axis=1, skipna=True)
    df["depth_ask"] = df[ASK_QTY].sum(axis=1, skipna=True)
    tot = df["depth_bid"] + df["depth_ask"]
    df["OBI"] = np.where(tot > 0, (df["depth_bid"] - df["depth_ask"]) / tot, np.nan)
    return df


def process_instrument(cfg: dict, iid: str) -> pd.DataFrame | None:
    raw_path = get_instrument_raw_path(cfg, iid)
    out_path = get_snap_path(cfg, iid)

    if not raw_path.exists():
        return None

    # Skip if already processed
    if out_path.exists():
        return None  # Signal: already done

    raw = pd.read_parquet(raw_path)
    if len(raw) == 0:
        return None

    raw["number"] = pd.to_numeric(raw["number"], errors="coerce")
    raw["refID"] = pd.to_numeric(raw["refID"], errors="coerce")

    # Process day by day to keep memory manageable
    day_snaps = []
    for dt, day_df in raw.groupby("date", sort=False):
        day_snap = _pivot_day(day_df)
        if len(day_snap) > 0:
            day_snap = compute_metrics(day_snap)
            day_snaps.append(day_snap)
        del day_df

    if not day_snaps:
        return None

    snap = pd.concat(day_snaps, ignore_index=True)
    del day_snaps
    snap.to_parquet(out_path, index=False)
    return snap


def run(cfg: dict) -> dict:
    """Process all instruments. Returns summary stats."""
    instruments = list_available_instruments(cfg)
    logger.info("Reconstructing snapshots for %d instruments …", len(instruments))

    total_snaps = 0
    total_incomplete = 0
    total_refs = 0

    for i, iid in enumerate(instruments):
        snap = process_instrument(cfg, iid)
        if snap is not None:
            total_snaps += len(snap)
        if i % 50 == 0:
            logger.info("Book snap: %d/%d instruments done …", i, len(instruments))

    logger.info("Snapshot reconstruction complete: %d total snapshots", total_snaps)

    stats = {
        "n_snapshots_total": total_snaps,
        "n_instruments": len(instruments),
    }
    save_manifest(cfg, {"book": stats})
    return stats


if __name__ == "__main__":
    setup_logging()
    cfg = load_config()
    run(cfg)
