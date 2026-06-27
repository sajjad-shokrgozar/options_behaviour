"""Tests for src/clean.py — cleaning & flags."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.clean import _nan_zero_levels


def _make_snap_row(**overrides) -> pd.DataFrame:
    row = {
        "instrument_id": "X",
        "date": "20240101",
        "refID": 1,
        "hEven": 94500,
        "ts": 34200.0,
        "mid": 100.5,
        "microprice": 100.5,
        "spread": 1.0,
        "rel_spread": 0.01,
        "depth_bid": 5000.0,
        "depth_ask": 5000.0,
        "OBI": 0.0,
        "crossed": False,
        "two_sided": True,
    }
    for i in range(1, 6):
        row[f"bid_px_{i}"] = 101.0 - i
        row[f"bid_qty_{i}"] = 1000.0
        row[f"ask_px_{i}"] = 100.0 + i
        row[f"ask_qty_{i}"] = 1000.0
    row.update(overrides)
    return pd.DataFrame([row])


def test_zero_price_becomes_nan():
    df = _make_snap_row(bid_px_1=0.0, bid_qty_1=500.0)
    result = _nan_zero_levels(df)
    assert pd.isna(result["bid_px_1"].iloc[0])
    assert pd.isna(result["bid_qty_1"].iloc[0])
    assert pd.notna(result["bid_px_2"].iloc[0])


def test_zero_qty_becomes_nan():
    df = _make_snap_row(ask_qty_3=0.0)
    result = _nan_zero_levels(df)
    assert pd.isna(result["ask_px_3"].iloc[0])
    assert pd.isna(result["ask_qty_3"].iloc[0])


def test_non_zero_stays():
    df = _make_snap_row()
    result = _nan_zero_levels(df)
    for i in range(1, 6):
        assert pd.notna(result[f"bid_px_{i}"].iloc[0])
        assert pd.notna(result[f"ask_px_{i}"].iloc[0])


def test_crossed_flagging(tmp_path):
    """Crossed books must have mid=NaN after cleaning."""
    from src.utils import load_config, project_root
    from src.clean import process_instrument
    from src.book import get_snap_path

    cfg = load_config(project_root() / "config.yaml")
    cfg["paths"]["out_dir"] = str(tmp_path)

    pdir = Path(tmp_path) / "panels"
    snap_dir = pdir / "book_snap"
    snap_dir.mkdir(parents=True, exist_ok=True)
    clean_dir = pdir / "book_clean"
    clean_dir.mkdir(parents=True, exist_ok=True)

    # Build synthetic snap with a crossed row
    snap = _make_snap_row(bid_px_1=105.0, ask_px_1=103.0)
    snap["mid"] = 104.0
    snap_path = snap_dir / "TEST_INST.parquet"
    snap.to_parquet(snap_path, index=False)

    result = process_instrument(cfg, "TEST_INST")

    assert result is not None
    crossed_rows = result[result["crossed"]]
    assert len(crossed_rows) == 1
    assert pd.isna(crossed_rows["mid"].iloc[0])
