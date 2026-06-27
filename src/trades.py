"""Module 4.6 — Trade tape processing (stub; activate when trades data arrives).

Output: panels/trades_clean.parquet with columns:
  instrument_id, date, ts (seconds), price, volume, side (buy|sell|unknown),
  mid_at_trade, effective_spread
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .utils import (
    load_config,
    panels_dir,
    project_root,
    save_manifest,
    setup_logging,
    to_seconds,
)

logger = logging.getLogger(__name__)


def lee_ready_side(price: float, mid: float, prev_price: float | None) -> str:
    """Lee-Ready rule: compare trade price to mid; tie → tick test."""
    if np.isnan(mid):
        if prev_price is not None and not np.isnan(prev_price):
            if price > prev_price:
                return "buy"
            elif price < prev_price:
                return "sell"
        return "unknown"
    if price > mid:
        return "buy"
    elif price < mid:
        return "sell"
    # Tie → tick test
    if prev_price is not None and not np.isnan(prev_price):
        if price > prev_price:
            return "buy"
        elif price < prev_price:
            return "sell"
    return "unknown"


def process_trades(raw: pd.DataFrame, book_clean: pd.DataFrame) -> pd.DataFrame:
    """
    Process raw trade tape: sign trades, compute effective spread.
    raw must have: instrument_id, date, hEven (or ts), price, volume
    Optional: side_flag column (native side).
    """
    raw = raw.copy()

    if "ts" not in raw.columns:
        raw["ts"] = raw["hEven"].apply(lambda x: to_seconds(x) if pd.notna(x) else np.nan)

    # Synchronize mid from book_clean (as-of join by ts within same instrument/date)
    book_sub = book_clean[["instrument_id", "date", "ts", "mid"]].dropna(subset=["ts"])
    book_sub = book_sub.sort_values(["instrument_id", "date", "ts"])
    raw = raw.sort_values(["instrument_id", "date", "ts"])

    merged = pd.merge_asof(
        raw,
        book_sub,
        on="ts",
        by=["instrument_id", "date"],
        direction="backward",
        suffixes=("", "_book"),
    )
    merged.rename(columns={"mid": "mid_at_trade"}, inplace=True)

    # Assign side
    if "side_flag" in merged.columns:
        merged["side"] = merged["side_flag"].map(
            {1: "buy", -1: "sell", 0: "unknown", "B": "buy", "S": "sell"}
        ).fillna("unknown")
    else:
        sides = []
        prev_prices: dict = {}
        for _, row in merged.iterrows():
            key = (row["instrument_id"], row["date"])
            prev = prev_prices.get(key)
            side = lee_ready_side(row["price"], row.get("mid_at_trade", np.nan), prev)
            sides.append(side)
            prev_prices[key] = row["price"]
        merged["side"] = sides

    merged["effective_spread"] = (merged["price"] - merged["mid_at_trade"]).abs() * 2

    # Sanity check
    side_counts = merged["side"].value_counts()
    logger.info("Trade side counts: %s", side_counts.to_dict())
    if len(merged) > 10:
        pct_one_side = side_counts.max() / len(merged)
        if pct_one_side > 0.95:
            logger.warning("~%.0f%% trades on same side — check Lee-Ready", pct_one_side * 100)

    return merged[["instrument_id", "date", "ts", "price", "volume", "side", "mid_at_trade", "effective_spread"]]


def run(cfg: dict) -> pd.DataFrame | None:
    """Try to process trades; return None if no trades data available."""
    root = project_root()
    trades_dir = root / cfg["paths"]["trades_dir"]

    pdir = panels_dir(cfg)
    out_path = pdir / "trades_clean.parquet"
    clean_path = pdir / "book_clean.parquet"

    if not trades_dir.exists() or not any(trades_dir.iterdir()):
        logger.info(
            "Trades directory %s is empty or missing — trades module stubbed out.",
            trades_dir,
        )
        save_manifest(cfg, {"trades": {"status": "stub_no_data"}})
        return None

    logger.info("Trades directory found: %s", trades_dir)
    book_clean = pd.read_parquet(clean_path) if clean_path.exists() else pd.DataFrame()

    chunks = []
    for csv_path in sorted(trades_dir.glob("**/*.csv")):
        try:
            df = pd.read_csv(csv_path, encoding="utf-8")
            chunks.append(df)
        except Exception as e:
            logger.warning("Failed reading trade file %s: %s", csv_path, e)

    if not chunks:
        logger.info("No trade CSV files found — stubbing out.")
        save_manifest(cfg, {"trades": {"status": "stub_no_csv"}})
        return None

    raw = pd.concat(chunks, ignore_index=True)
    logger.info("Raw trades: %d rows", len(raw))

    if len(book_clean) == 0:
        logger.warning("book_clean empty — skipping Lee-Ready; assigning side=unknown")
        raw["mid_at_trade"] = np.nan
        raw["side"] = "unknown"
        raw["effective_spread"] = np.nan
        result = raw
    else:
        result = process_trades(raw, book_clean)

    result.to_parquet(out_path, index=False)
    logger.info("Wrote trades_clean.parquet: %d rows", len(result))

    save_manifest(
        cfg,
        {
            "trades": {
                "status": "processed",
                "n_rows": len(result),
                "side_counts": result["side"].value_counts().to_dict(),
            }
        },
    )
    return result


if __name__ == "__main__":
    setup_logging()
    cfg = load_config()
    run(cfg)
