"""Tests for src/session.py — hEven parsing and session split."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import heven_to_time, to_seconds


def test_heven_standard():
    """094500 → 09:45:00"""
    t = heven_to_time(94500)
    assert t.hour == 9
    assert t.minute == 45
    assert t.second == 0


def test_heven_leading_zero():
    """60125 → 06:01:25"""
    t = heven_to_time(60125)
    assert t.hour == 6
    assert t.minute == 1
    assert t.second == 25


def test_heven_string():
    t = heven_to_time("084517")
    assert t.hour == 8
    assert t.minute == 45
    assert t.second == 17


def test_heven_midnight():
    t = heven_to_time(0)
    assert t.hour == 0
    assert t.minute == 0
    assert t.second == 0


def test_to_seconds_basic():
    s = to_seconds(94500)
    assert s == 9 * 3600 + 45 * 60 + 0


def test_to_seconds_preopen():
    s = to_seconds(60131)
    expected = 6 * 3600 + 1 * 60 + 31
    assert s == expected


def test_session_phase_assignment(tmp_path):
    """Rows before fallback_open should be labeled preopen."""
    import pandas as pd
    import numpy as np
    from pathlib import Path
    from src.utils import load_config, project_root

    cfg = load_config(project_root() / "config.yaml")
    cfg["paths"]["out_dir"] = str(tmp_path)
    cfg["session"]["fallback_open"] = "09:00:00"
    cfg["session"]["fallback_close"] = "12:30:00"

    pdir = Path(tmp_path) / "panels"
    clean_dir = pdir / "book_clean"
    snap_dir = pdir / "book_snap"
    clean_dir.mkdir(parents=True, exist_ok=True)
    snap_dir.mkdir(parents=True, exist_ok=True)

    # Build synthetic book_clean with preopen and continuous rows
    rows = []
    for heven, expected_phase in [(60000, "preopen"), (90000, "continuous"), (120000, "continuous")]:
        rows.append({
            "instrument_id": "INST1",
            "date": "20240101",
            "refID": heven,
            "hEven": heven,
            "ts": to_seconds(heven),
            # Note: no session_phase here — module must add it
            "mid": 100.0,
            "microprice": 100.0,
            "spread": 1.0,
            "rel_spread": 0.01,
            "depth_bid": 1000.0,
            "depth_ask": 1000.0,
            "OBI": 0.0,
            "crossed": False,
            "two_sided": True,
            "tick_size": 1.0,
        })
        for i in range(1, 6):
            rows[-1].update({
                f"bid_px_{i}": 100.0 - i,
                f"bid_qty_{i}": 500.0,
                f"ask_px_{i}": 101.0 + i,
                f"ask_qty_{i}": 500.0,
            })

    df = pd.DataFrame(rows)
    df.to_parquet(clean_dir / "INST1.parquet", index=False)
    # Snap index for session.list_snap_instruments()
    pd.DataFrame({"tmp": []}).to_parquet(snap_dir / "INST1.parquet", index=False)

    from src.session import run, process_instrument
    run(cfg)

    # Read back the updated clean file
    result = pd.read_parquet(pdir / "book_clean" / "INST1.parquet")
    phases = result.set_index("hEven")["session_phase"]
    assert phases.loc[60000] == "preopen"
    assert phases.loc[90000] == "continuous"
    assert phases.loc[120000] == "continuous"
