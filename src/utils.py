"""Shared utilities: config loading, manifest, logging helpers."""
from __future__ import annotations

import json
import hashlib
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

logger = logging.getLogger(__name__)


def load_config(path: str | Path = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def out_dir(cfg: dict) -> Path:
    return project_root() / cfg["paths"]["out_dir"]


def panels_dir(cfg: dict) -> Path:
    d = out_dir(cfg) / "panels"
    d.mkdir(parents=True, exist_ok=True)
    return d


def figures_dir(cfg: dict) -> Path:
    d = out_dir(cfg) / "figures"
    d.mkdir(parents=True, exist_ok=True)
    return d


def figures_data_dir(cfg: dict) -> Path:
    d = out_dir(cfg) / "figures_data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def tables_dir(cfg: dict) -> Path:
    d = out_dir(cfg) / "tables"
    d.mkdir(parents=True, exist_ok=True)
    return d


def findings_dir(cfg: dict) -> Path:
    d = out_dir(cfg) / "findings"
    d.mkdir(parents=True, exist_ok=True)
    return d


def file_hash(path: str | Path, algo: str = "sha256", chunk: int = 1 << 20) -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        while blk := f.read(chunk):
            h.update(blk)
    return h.hexdigest()


def load_manifest(cfg: dict) -> dict:
    p = out_dir(cfg) / "manifest.json"
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {}


def save_manifest(cfg: dict, updates: dict) -> None:
    p = out_dir(cfg) / "manifest.json"
    m = load_manifest(cfg)
    m.update(updates)
    with open(p, "w") as f:
        json.dump(m, f, indent=2, default=str)


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        level=level,
    )


def jalali_to_gregorian(jdate: int | str) -> date:
    """Convert a Jalali YYYYMMDD integer or string to a Python date."""
    import jdatetime
    s = str(jdate).strip()
    y, m, d_ = int(s[:4]), int(s[4:6]), int(s[6:8])
    return jdatetime.date(y, m, d_).togregorian()


def heven_to_time(heven: int | str) -> datetime | None:
    """Convert HHMMSS (possibly without leading zeros) to time components."""
    s = str(int(heven)).zfill(6)
    try:
        h, mi, sec = int(s[:2]), int(s[2:4]), int(s[4:6])
        return datetime(2000, 1, 1, h, mi, sec)  # dummy date, time only
    except (ValueError, OverflowError):
        return None


def to_seconds(heven: int | str) -> float | None:
    """Convert hEven to seconds-since-midnight."""
    t = heven_to_time(heven)
    if t is None:
        return None
    return t.hour * 3600 + t.minute * 60 + t.second


def moneyness_label(k_over_s: float, edges: list[float]) -> str:
    """Moneyness bucket for K/S convention: deep_otm when K >> S (call far OTM)."""
    labels = ["deep_itm", "itm", "atm", "otm", "deep_otm"]
    for i, edge in enumerate(edges[1:]):
        if k_over_s < edge:
            return labels[min(i, len(labels) - 1)]
    return labels[-1]


def maturity_label(days: float, edges: list[int]) -> str:
    labels = ["short", "medium", "long"]
    for i, edge in enumerate(edges[1:]):
        if days < edge:
            return labels[min(i, len(labels) - 1)]
    return labels[-1]


def drop_log(df: pd.DataFrame, reason: str, dropped: pd.DataFrame) -> pd.DataFrame:
    if len(dropped):
        logger.info("DROPPED %d rows: %s", len(dropped), reason)
    return dropped.assign(drop_reason=reason)
