"""Module 4.8 — Eligibility & liquidity metric.

Reads synced/{iid}.parquet per instrument.
Writes:
  - panels/liquidity_profile.parquet
  - panels/eod_enriched.parquet (EOD with moneyness/maturity/eligibility)
  - Updated synced/{iid}.parquet with intraday_eligible, L
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .sync import get_synced_path, list_synced_instruments, synced_dir
from .utils import (
    load_config,
    panels_dir,
    project_root,
    save_manifest,
    setup_logging,
)

logger = logging.getLogger(__name__)


def moneyness_bucket(s_over_k: float, edges: list) -> str:
    """Moneyness bucket for S/K convention: deep_itm when S >> K (call deep in the money)."""
    labels = ["deep_otm", "otm", "atm", "itm", "deep_itm"]
    for i, edge in enumerate(edges[1:]):
        if s_over_k < edge:
            return labels[min(i, len(labels) - 1)]
    return labels[-1]


def maturity_bucket(days: float, edges: list) -> str:
    labels = ["short", "medium", "long"]
    for i, edge in enumerate(edges[1:]):
        if days < edge:
            return labels[min(i, len(labels) - 1)]
    return labels[-1]


def run(cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    root = project_root()
    pdir = panels_dir(cfg)
    specs_path = pdir / "contract_specs.parquet"
    eod_path = root / cfg["paths"]["options_history"]
    mon_edges = cfg["buckets"]["moneyness_edges"]
    mat_edges = cfg["buckets"]["maturity_days_edges"]

    # ── EOD daily eligibility ─────────────────────────────────────────────────
    logger.info("Loading options EOD history …")
    eod = pd.read_csv(eod_path, encoding="utf-8").rename(columns={"id": "instrument_id"})
    eod["instrument_id"] = eod["instrument_id"].astype(str)
    eod["date"] = eod["date"].astype(str)
    eod["daily_eligible"] = eod["volume"] > 0

    # Raw rate across all rows (includes dates before listing / after expiry)
    zero_vol_rate_raw = float(1 - eod["daily_eligible"].mean())
    logger.info("Zero-volume rate (all rows incl. pre/post-lifetime): %.1f%%", zero_vol_rate_raw * 100)

    # Active-lifetime zero_vol_rate: only count days within [first_date, expiry_date]
    first_date_by_iid = eod.groupby("instrument_id")["date"].min()
    eod["_first_date"] = eod["instrument_id"].map(first_date_by_iid)

    # Attach specs
    specs = pd.read_parquet(specs_path)
    specs["expiry_greg"] = pd.to_datetime(specs["expiry_greg"])
    # Merge specs — strike already exists in eod CSV, so only add expiry_greg and option_type
    eod = eod.merge(
        specs[["instrument_id", "expiry_greg", "option_type"]],
        on="instrument_id", how="left",
    )
    eod["valuation_date"] = pd.to_datetime(eod["date"], format="%Y%m%d", errors="coerce")
    eod["days_to_expiry"] = (eod["expiry_greg"] - eod["valuation_date"]).dt.days
    eod["T"] = eod["days_to_expiry"] / cfg["pricing"]["daycount"]
    eod["K"] = pd.to_numeric(eod["strike"], errors="coerce")

    # Active-lifetime filter: date between first_date and expiry_date (YYYYMMDD strings)
    eod["_expiry_str"] = eod["expiry_greg"].dt.strftime("%Y%m%d")
    eod_active = eod[(eod["date"] >= eod["_first_date"]) & (eod["date"] <= eod["_expiry_str"])]
    zero_vol_rate = float(1 - eod_active["daily_eligible"].mean())
    logger.info(
        "Zero-volume rate within active lifetime: %.1f%% (raw all-rows: %.1f%%)",
        zero_vol_rate * 100, zero_vol_rate_raw * 100,
    )

    # Underlying close as S (from underlying EOD)
    under_eod = pd.read_csv(root / cfg["paths"]["underlying_history"], encoding="utf-8")
    under_eod["date"] = under_eod["date"].astype(str)
    under_close_map = under_eod.set_index("date")["close"].to_dict()
    eod["S"] = eod["date"].map(under_close_map)
    eod["moneyness"] = np.where(eod["K"] > 0, eod["S"] / eod["K"], np.nan)
    eod["moneyness_bucket"] = eod["moneyness"].apply(
        lambda x: moneyness_bucket(x, mon_edges) if pd.notna(x) else "unknown"
    )
    eod["maturity_bucket"] = eod["days_to_expiry"].apply(
        lambda x: maturity_bucket(x, mat_edges) if pd.notna(x) else "unknown"
    )

    # Liquidity profile (daily)
    profile_daily = (
        eod.groupby(["moneyness_bucket", "maturity_bucket"])
        .agg(
            n_contract_days=("instrument_id", "count"),
            n_traded=("daily_eligible", "sum"),
            traded_rate=("daily_eligible", "mean"),
            avg_volume=("volume", "mean"),
        )
        .reset_index()
    )
    logger.info("Liquidity profile:\n%s", profile_daily.to_string(index=False))

    # Call-put pair availability
    eod_traded = eod[eod["daily_eligible"]].copy()
    eod_traded["pair_key"] = (
        eod_traded["date"] + "_" + eod_traded["strike"].astype(str) + "_" + eod_traded["maturity"].astype(str)
    )
    pairs = eod_traded.groupby("pair_key")["option_type"].apply(set)
    pair_rate = float((pairs.apply(lambda s: "call" in s and "put" in s)).mean())
    logger.info("Call-put pair availability (EOD traded): %.1f%%", pair_rate * 100)

    eod.to_parquet(pdir / "eod_enriched.parquet", index=False)
    logger.info("Wrote eod_enriched.parquet: %d rows", len(eod))

    # ── Intraday eligibility and L per synced instrument ──────────────────────
    instruments = list_synced_instruments(cfg)
    logger.info("Adding intraday eligibility to %d synced instruments …", len(instruments))

    total_intraday_el = 0
    total_rows = 0

    for iid in instruments:
        sp = get_synced_path(cfg, iid)
        if not sp.exists():
            continue
        synced = pd.read_parquet(sp)
        if len(synced) == 0:
            continue

        # Drop any columns from a previous partial liquidity run
        synced = synced.drop(columns=["intraday_eligible", "n_updates", "L"], errors="ignore")

        synced["intraday_eligible"] = synced["fresh"] & synced["two_sided"]

        # Update rate per (date)
        n_updates = synced.groupby("date").size().reset_index(name="n_updates")
        synced = synced.merge(n_updates, on="date", how="left")

        def zscore(s: pd.Series) -> pd.Series:
            std = s.std()
            return pd.Series(0.0, index=s.index) if (std == 0 or np.isnan(std)) else (s - s.mean()) / std

        z_update = zscore(np.log1p(synced["n_updates"]))
        z_spread = zscore(-synced["rel_spread"].fillna(synced["rel_spread"].median()))
        z_fresh = zscore(synced["fresh"].astype(float))
        synced["L"] = (z_update + z_spread + z_fresh) / 3.0

        synced.to_parquet(sp, index=False)
        total_intraday_el += int(synced["intraday_eligible"].sum())
        total_rows += len(synced)

    intraday_rate = total_intraday_el / total_rows if total_rows else 0.0
    logger.info("Intraday eligible rate: %.1f%%", 100 * intraday_rate)

    profile_path = pdir / "liquidity_profile.parquet"
    profile_daily.to_parquet(profile_path, index=False)

    save_manifest(
        cfg,
        {
            "liquidity": {
                "zero_vol_rate": round(zero_vol_rate, 4),
                "zero_vol_rate_raw": round(zero_vol_rate_raw, 4),
                "pair_availability_rate": round(pair_rate, 4),
                "intraday_eligible_rate": round(intraday_rate, 4),
            }
        },
    )
    return eod, profile_daily


if __name__ == "__main__":
    setup_logging()
    cfg = load_config()
    run(cfg)
