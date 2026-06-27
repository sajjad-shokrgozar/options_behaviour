"""Tests for src/sync.py — as-of join and staleness window enforcement."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _base_row(instrument_id, ts, date="20240101", **kwargs) -> dict:
    row = {
        "instrument_id": str(instrument_id),
        "date": date,
        "hEven": 90000,
        "ts": float(ts),
        "mid": 100.0,
        "microprice": 100.0,
        "bid_px_1": 99.0,
        "ask_px_1": 101.0,
        "bid_qty_1": 1000.0,
        "ask_qty_1": 1000.0,
        "spread": 2.0,
        "rel_spread": 0.02,
        "depth_bid": 5000.0,
        "depth_ask": 5000.0,
        "OBI": 0.0,
        "crossed": False,
        "two_sided": True,
        "tick_size": 1.0,
        "session_phase": "continuous",
        "refID": 1,
    }
    for i in range(2, 6):
        row.update({
            f"bid_px_{i}": 99.0 - i,
            f"bid_qty_{i}": 500.0,
            f"ask_px_{i}": 101.0 + i,
            f"ask_qty_{i}": 500.0,
        })
    row.update(kwargs)
    return row


def _setup_test_env(tmp_path, cfg, underlying_id="UNDERLYING"):
    """Set up directory structure for sync tests."""
    pdir = Path(tmp_path) / "panels"
    raw_dir = pdir / "book_raw"
    snap_dir = pdir / "book_snap"
    clean_dir = pdir / "book_clean"
    synced_dir = pdir / "synced"
    for d in [raw_dir, snap_dir, clean_dir, synced_dir]:
        d.mkdir(parents=True, exist_ok=True)
    # Write index
    pd.DataFrame({"instrument_id": [underlying_id, "OPTION1"]}).to_parquet(
        raw_dir.parent / "book_raw_index.parquet", index=False
    )
    return pdir, clean_dir, synced_dir


def test_no_carry_beyond_staleness_window(tmp_path):
    """
    If the underlying snapshot is older than staleness_window_s,
    fresh must be False and underlying fields must be NaN.
    """
    from src.utils import load_config, project_root

    cfg = load_config(project_root() / "config.yaml")
    cfg["paths"]["out_dir"] = str(tmp_path)
    cfg["ids"]["underlying_id"] = "UNDERLYING"
    cfg["liquidity"]["staleness_window_s"] = 60

    pdir, clean_dir, synced_dir = _setup_test_env(tmp_path, cfg)

    # Underlying at t=0
    under = pd.DataFrame([_base_row("UNDERLYING", ts=0.0)])
    under.to_parquet(clean_dir / "UNDERLYING.parquet", index=False)

    # Option at t=200 → age=200 > 60 → stale
    opt = pd.DataFrame([_base_row("OPTION1", ts=200.0)])
    opt.to_parquet(clean_dir / "OPTION1.parquet", index=False)

    # Write snap index so list_snap_instruments works
    snap_dir = pdir / "book_snap"
    pd.DataFrame({"tmp": []}).to_parquet(snap_dir / "UNDERLYING.parquet", index=False)
    pd.DataFrame({"tmp": []}).to_parquet(snap_dir / "OPTION1.parquet", index=False)

    from src.sync import run
    run(cfg)

    result_path = synced_dir / "OPTION1.parquet"
    assert result_path.exists()
    result = pd.read_parquet(result_path)
    assert len(result) == 1
    assert not result["fresh"].iloc[0]
    assert pd.isna(result["u_mid"].iloc[0])


def test_fresh_within_window(tmp_path):
    """Option snapshot within staleness window should be fresh."""
    from src.utils import load_config, project_root

    cfg = load_config(project_root() / "config.yaml")
    cfg["paths"]["out_dir"] = str(tmp_path)
    cfg["ids"]["underlying_id"] = "UNDERLYING"
    cfg["liquidity"]["staleness_window_s"] = 120

    pdir, clean_dir, synced_dir = _setup_test_env(tmp_path, cfg)

    under = pd.DataFrame([_base_row("UNDERLYING", ts=0.0)])
    under.to_parquet(clean_dir / "UNDERLYING.parquet", index=False)

    opt = pd.DataFrame([_base_row("OPTION1", ts=50.0)])
    opt.to_parquet(clean_dir / "OPTION1.parquet", index=False)

    snap_dir = pdir / "book_snap"
    pd.DataFrame({"tmp": []}).to_parquet(snap_dir / "UNDERLYING.parquet", index=False)
    pd.DataFrame({"tmp": []}).to_parquet(snap_dir / "OPTION1.parquet", index=False)

    from src.sync import run
    run(cfg)

    result = pd.read_parquet(synced_dir / "OPTION1.parquet")
    assert len(result) == 1
    assert result["fresh"].iloc[0]
