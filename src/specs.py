"""Module 4.1 — Contract specification table.

Input : options_history.csv
Output: panels/contract_specs.parquet
  Columns: instrument_id, strike, expiry_greg, option_type, underlying_id
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .utils import (
    jalali_to_gregorian,
    load_config,
    panels_dir,
    project_root,
    save_manifest,
    setup_logging,
)

logger = logging.getLogger(__name__)

CALL_TAG = "اختیارخ اهرم"
PUT_TAG = "اختیارف اهرم"


def run(cfg: dict) -> pd.DataFrame:
    root = project_root()
    opt_path = root / cfg["paths"]["options_history"]
    logger.info("Reading options_history from %s", opt_path)

    df = pd.read_csv(opt_path, encoding="utf-8")
    logger.info("options_history: %d rows, %d columns", len(df), df.shape[1])

    # Rename id → instrument_id for clarity
    df = df.rename(columns={"id": "instrument_id"})

    # Map option type from underlying text
    mask_call = df["underlying"].str.strip() == CALL_TAG
    mask_put = df["underlying"].str.strip() == PUT_TAG
    unmapped = ~(mask_call | mask_put)
    if unmapped.any():
        logger.warning(
            "Unmapped underlying values (%d rows): %s",
            unmapped.sum(),
            df.loc[unmapped, "underlying"].unique(),
        )

    df["option_type"] = "unknown"
    df.loc[mask_call, "option_type"] = "call"
    df.loc[mask_put, "option_type"] = "put"

    # Deduplicate to one row per instrument_id (take first occurrence)
    specs = df.drop_duplicates(subset=["instrument_id"]).copy()

    # Convert Jalali maturity → Gregorian expiry
    def safe_convert(jdate):
        try:
            return jalali_to_gregorian(jdate)
        except Exception as e:
            logger.debug("Jalali conversion failed for %s: %s", jdate, e)
            return None

    specs["expiry_greg"] = specs["maturity"].apply(safe_convert)
    n_failed = specs["expiry_greg"].isna().sum()
    if n_failed:
        logger.warning("%d contracts failed Jalali→Gregorian conversion", n_failed)

    # Underlying instrument_id
    specs["underlying_id"] = cfg["ids"]["underlying_id"]

    # Select and cast columns
    out = specs[
        ["instrument_id", "strike", "expiry_greg", "option_type", "underlying_id"]
    ].copy()
    out["instrument_id"] = out["instrument_id"].astype(str)
    out["underlying_id"] = out["underlying_id"].astype(str)
    out["strike"] = pd.to_numeric(out["strike"], errors="coerce")
    out["expiry_greg"] = pd.to_datetime(out["expiry_greg"])

    # Acceptance checks
    dupes = out["instrument_id"].duplicated().sum()
    assert dupes == 0, f"Duplicate instrument_ids after dedup: {dupes}"
    assert set(out["option_type"]).issubset({"call", "put", "unknown"}), "Bad option_type"
    n_valid_expiry = out["expiry_greg"].notna().sum()
    logger.info(
        "Contract specs: %d contracts (%d call, %d put), %d/%d valid expiry",
        len(out),
        (out["option_type"] == "call").sum(),
        (out["option_type"] == "put").sum(),
        n_valid_expiry,
        len(out),
    )

    # Write output
    pdir = panels_dir(cfg)
    out_path = pdir / "contract_specs.parquet"
    out.to_parquet(out_path, index=False)
    logger.info("Wrote %s", out_path)

    save_manifest(
        cfg,
        {
            "specs": {
                "n_contracts": len(out),
                "n_call": int((out["option_type"] == "call").sum()),
                "n_put": int((out["option_type"] == "put").sum()),
                "n_valid_expiry": int(n_valid_expiry),
            }
        },
    )
    return out


if __name__ == "__main__":
    setup_logging()
    cfg = load_config()
    run(cfg)
