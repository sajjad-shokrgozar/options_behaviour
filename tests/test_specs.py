"""Tests for src/specs.py — contract specification table."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import jalali_to_gregorian


def test_jalali_to_gregorian_known_dates():
    """Convert known Jalali dates to Gregorian and check."""
    # 1403/08/30 Jalali = 2024/11/20 Gregorian (approx)
    from datetime import date
    g = jalali_to_gregorian(14030830)
    assert isinstance(g, date)
    assert g.year == 2024
    assert g.month == 11

    # 1404/01/27 = April 16, 2025
    g2 = jalali_to_gregorian(14040127)
    assert g2.year == 2025
    assert g2.month == 4
    assert g2.day == 16


def test_jalali_to_gregorian_str_input():
    from datetime import date
    g = jalali_to_gregorian("14040127")
    assert isinstance(g, date)
    assert g.year == 2025


def test_specs_unique_instrument_ids(tmp_path):
    """specs.run() produces one row per instrument_id."""
    import yaml, os
    from src.utils import load_config, project_root

    # Use actual config and real data
    cfg = load_config(project_root() / "config.yaml")
    cfg["paths"]["out_dir"] = str(tmp_path)

    from src.specs import run
    result = run(cfg)

    assert result["instrument_id"].duplicated().sum() == 0, "Duplicate instrument_ids found"
    assert set(result["option_type"]).issubset({"call", "put"}), "Bad option_type values"
    assert result["expiry_greg"].notna().mean() > 0.99, "Too many invalid expiry dates"
    # call/put counts should be approximately equal
    n_call = (result["option_type"] == "call").sum()
    n_put = (result["option_type"] == "put").sum()
    assert abs(n_call - n_put) <= 5, f"Call/put imbalance: {n_call} vs {n_put}"
