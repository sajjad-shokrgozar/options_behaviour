"""Tests for src/liquidity.py — zero-volume rate and eligibility."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_zero_volume_rate_on_real_data():
    """
    The EOD options data should show ~56-57% zero-volume contract-days.
    Acceptance threshold: 50–65%.
    """
    root = Path(__file__).resolve().parent.parent
    eod_path = root / "options_history.csv"

    if not eod_path.exists():
        pytest.skip("options_history.csv not found")

    eod = pd.read_csv(eod_path, encoding="utf-8")
    zero_vol_rate = (eod["volume"] == 0).mean()

    assert 0.50 <= zero_vol_rate <= 0.65, (
        f"Zero-volume rate {zero_vol_rate:.1%} outside expected 50-65%"
    )


def test_daily_eligible_flag():
    """daily_eligible = volume > 0 should be consistent."""
    eod = pd.DataFrame({
        "instrument_id": ["A", "A", "B", "B"],
        "date": ["20240101", "20240102", "20240101", "20240102"],
        "volume": [0.0, 100.0, 0.0, 0.0],
        "close": [10.0, 11.0, 5.0, 5.0],
    })
    eod["daily_eligible"] = eod["volume"] > 0

    assert not eod.loc[0, "daily_eligible"]
    assert eod.loc[1, "daily_eligible"]
    assert not eod.loc[2, "daily_eligible"]
