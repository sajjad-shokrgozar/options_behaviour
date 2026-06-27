"""Tests for src/band_queue.py — queue detection predicates and episode logic."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.band_queue import detect_band_pct, classify_queue_snapshots


def _make_underlying_snap(
    date: str,
    ts_list: list[float],
    bid_px: list[float],
    ask_px: list[float],
    bid_qty: list[float],
    ask_qty: list[float],
    yesterday_ref: float,
    tick_size: float = 1.0,
) -> pd.DataFrame:
    rows = []
    for i, ts in enumerate(ts_list):
        rows.append({
            "instrument_id": "UNDER",
            "date": date,
            "ts": ts,
            "bid_px_1": bid_px[i],
            "ask_px_1": ask_px[i],
            "bid_qty_1": bid_qty[i],
            "ask_qty_1": ask_qty[i],
            "yesterday_ref": yesterday_ref,
            "tick_size": tick_size,
            "mid": (bid_px[i] + ask_px[i]) / 2.0 if ask_qty[i] > 0 and bid_qty[i] > 0 else np.nan,
        })
    return pd.DataFrame(rows)


def test_detect_band_pct_official():
    """official_pct overrides empirical estimation."""
    dummy_eod = pd.DataFrame({"yesterday": [100.0], "max": [110.0], "min": [90.0]})
    band = detect_band_pct(dummy_eod, official_pct=0.05)
    assert band == 0.05


def test_detect_band_pct_empirical():
    """Empirical band should be positive."""
    eod = pd.DataFrame({
        "yesterday": [100.0] * 50,
        "max": np.random.uniform(100, 115, 50),
        "min": np.random.uniform(85, 100, 50),
    })
    band = detect_band_pct(eod, quantile=0.99)
    assert 0 < band < 0.5


def test_buy_queue_detection():
    """
    Buy queue: ask side empty + best bid at ceiling.
    yesterday=100, band=0.05 → ceiling=105.
    Bid at 105, ask empty, 3+ consecutive → should detect buy_queue episode.
    """
    yesterday = 100.0
    band_pct = 0.05
    ceil = yesterday * (1 + band_pct)  # 105.0

    # 5 consecutive snapshots: ask empty, bid at 105
    n = 5
    under = _make_underlying_snap(
        date="20240101",
        ts_list=[float(i * 60) for i in range(n)],
        bid_px=[ceil] * n,
        ask_px=[ceil + 1.0] * n,   # present but won't matter — qty is zero
        bid_qty=[1000.0] * n,
        ask_qty=[0.0] * n,          # ask EMPTY
        yesterday_ref=yesterday,
    )

    result, episodes = classify_queue_snapshots(
        under,
        band_pct=band_pct,
        at_limit_tol_ticks=1,
        min_persist=3,
        post_guard_min=0,
    )

    assert len(episodes) >= 1, "Should detect at least one buy_queue episode"
    assert episodes.iloc[0]["side"] == "buy_queue"


def test_free_when_both_sides_present():
    """No queue when both sides present and price not at limit."""
    n = 5
    under = _make_underlying_snap(
        date="20240101",
        ts_list=[float(i * 60) for i in range(n)],
        bid_px=[99.0] * n,
        ask_px=[101.0] * n,
        bid_qty=[1000.0] * n,
        ask_qty=[1000.0] * n,
        yesterday_ref=100.0,
    )

    result, episodes = classify_queue_snapshots(
        under,
        band_pct=0.05,
        at_limit_tol_ticks=1,
        min_persist=3,
        post_guard_min=0,
    )

    assert all(result["regime"] == "free"), "Should all be free"
    assert len(episodes) == 0


def test_regime_exhaustive_and_disjoint():
    """regime column must be one of {free, buy_queue, sell_queue} for every row."""
    n = 10
    under = _make_underlying_snap(
        date="20240101",
        ts_list=[float(i * 60) for i in range(n)],
        bid_px=[99.0] * n,
        ask_px=[101.0] * n,
        bid_qty=[1000.0] * n,
        ask_qty=[1000.0] * n,
        yesterday_ref=100.0,
    )
    result, _ = classify_queue_snapshots(under, 0.05, 1, 3, 5)
    assert result["regime"].isin(["free", "buy_queue", "sell_queue"]).all()
