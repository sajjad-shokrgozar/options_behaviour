"""Tests for src/book.py — snapshot reconstruction and metrics."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.book import compute_metrics, _pivot_day


def _make_raw_group(levels: list[int]) -> pd.DataFrame:
    """Create a fake raw group with given level numbers."""
    rows = []
    for lvl in levels:
        rows.append({
            "instrument_id": "TEST",
            "date": "20240101",
            "refID": 1234,
            "hEven": 94500,
            "number": lvl,
            "pMeDem": 100.0 - lvl,  # bid decreasing
            "qTitMeDem": 1000,
            "pMeOf": 101.0 + lvl,  # ask increasing
            "qTitMeOf": 1000,
        })
    return pd.DataFrame(rows)


def test_pivot_all_5_levels():
    grp = _make_raw_group([1, 2, 3, 4, 5])
    snaps = _pivot_day(grp)
    assert len(snaps) > 0
    row = snaps.iloc[0]
    for i in range(1, 6):
        assert f"bid_px_{i}" in snaps.columns
        assert f"ask_px_{i}" in snaps.columns
        assert pd.notna(row[f"bid_px_{i}"])


def test_pivot_missing_levels_gives_nan():
    grp = _make_raw_group([1, 3, 5])
    snaps = _pivot_day(grp)
    assert len(snaps) > 0
    row = snaps.iloc[0]
    assert pd.isna(row.get("bid_px_2", np.nan))
    assert pd.isna(row.get("bid_px_4", np.nan))
    assert pd.notna(row["bid_px_1"])


def test_compute_metrics_mid_nan_when_one_side_missing():
    """mid should be NaN when ask is missing."""
    df = pd.DataFrame([{
        "instrument_id": "X", "date": "20240101", "refID": 1,
        "hEven": 94500,
        "bid_px_1": 100.0, "bid_qty_1": 1000.0,
        "ask_px_1": np.nan, "ask_qty_1": np.nan,
        **{f"bid_px_{i}": np.nan for i in range(2, 6)},
        **{f"bid_qty_{i}": np.nan for i in range(2, 6)},
        **{f"ask_px_{i}": np.nan for i in range(2, 6)},
        **{f"ask_qty_{i}": np.nan for i in range(2, 6)},
    }])
    result = compute_metrics(df)
    assert pd.isna(result["mid"].iloc[0])


def test_compute_metrics_obi_bounds():
    """OBI must be in [-1, 1]."""
    row = {
        "instrument_id": "X", "date": "20240101", "refID": 1, "hEven": 94500,
    }
    for i in range(1, 6):
        row[f"bid_px_{i}"] = 100.0 - i
        row[f"bid_qty_{i}"] = 500.0
        row[f"ask_px_{i}"] = 101.0 + i
        row[f"ask_qty_{i}"] = 200.0

    df = pd.DataFrame([row])
    result = compute_metrics(df)
    obi = result["OBI"].iloc[0]
    assert pd.notna(obi)
    assert -1 <= obi <= 1


def test_compute_metrics_spread_positive():
    row = {
        "instrument_id": "X", "date": "20240101", "refID": 1, "hEven": 94500,
    }
    for i in range(1, 6):
        row[f"bid_px_{i}"] = 100.0 - i
        row[f"bid_qty_{i}"] = 500.0
        row[f"ask_px_{i}"] = 101.0 + i
        row[f"ask_qty_{i}"] = 500.0

    df = pd.DataFrame([row])
    result = compute_metrics(df)
    assert result["spread"].iloc[0] > 0
    assert result["rel_spread"].iloc[0] > 0
