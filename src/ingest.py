"""Module 4.2 — Raw order book CSV → per-instrument parquet.

Writes panels/book_raw/{instrument_id}.parquet (one file per instrument).
Also writes panels/book_raw_index.parquet listing all available instruments.
This avoids loading all data into RAM simultaneously.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd

from .utils import (
    load_config,
    panels_dir,
    project_root,
    save_manifest,
    setup_logging,
)

logger = logging.getLogger(__name__)

REAL_COLS = [
    "symbol",
    "instrument_id",
    "date",
    "hEven",
    "refID",
    "number",
    "qTitMeDem",
    "pMeDem",
    "pMeOf",
    "qTitMeOf",
]

DTYPE_MAP = {
    "hEven": "Int64",
    "refID": "Int64",
    "number": "Int64",
    "qTitMeDem": float,
    "pMeDem": float,
    "pMeOf": float,
    "qTitMeOf": float,
}


def read_single_file(path: Path, iid: str) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(path, encoding="utf-8", low_memory=False)
        df = df[[c for c in df.columns if not c.startswith("sample_")]]
        present = [c for c in REAL_COLS if c in df.columns]
        df = df[present].copy()
        for col, dtype in DTYPE_MAP.items():
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df["instrument_id"] = iid
        return df
    except Exception as e:
        logger.warning("Failed reading %s: %s", path, e)
        return None


def raw_dir(cfg: dict) -> Path:
    d = panels_dir(cfg) / "book_raw"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_instrument_raw_path(cfg: dict, iid: str) -> Path:
    return raw_dir(cfg) / f"{iid}.parquet"


def list_available_instruments(cfg: dict) -> list[str]:
    d = raw_dir(cfg)
    return [p.stem for p in d.glob("*.parquet")]


def run(cfg: dict, instrument_ids: list[str] | None = None) -> list[str]:
    """
    Ingest order book data. Returns list of instrument IDs that were processed.
    """
    root = project_root()
    book_dir = root / cfg["paths"]["order_book_dir"]
    rdir = raw_dir(cfg)

    if instrument_ids is None:
        try:
            instrument_ids = [
                d for d in os.listdir(book_dir) if (book_dir / d).is_dir()
            ]
        except FileNotFoundError:
            logger.error("Order book directory not found: %s", book_dir)
            return []

    logger.info("Ingesting %d instruments from %s", len(instrument_ids), book_dir)

    processed = []
    total_files = 0
    total_rows = 0

    for iid in instrument_ids:
        iid_dir = book_dir / str(iid)
        if not iid_dir.is_dir():
            continue

        out_path = rdir / f"{iid}.parquet"

        csv_files = sorted(iid_dir.glob("*.csv"))
        if not csv_files:
            continue

        import pyarrow as pa
        import pyarrow.parquet as pq_mod

        writer = None
        n_rows = 0
        n_files_iid = 0
        for csv_path in csv_files:
            df = read_single_file(csv_path, str(iid))
            if df is None or len(df) == 0:
                continue
            table = pa.Table.from_pandas(df, preserve_index=False)
            if writer is None:
                writer = pq_mod.ParquetWriter(out_path, table.schema)
            writer.write_table(table)
            n_rows += len(df)
            n_files_iid += 1
            total_files += 1

        if writer is not None:
            writer.close()

        if n_rows == 0:
            continue

        total_rows += n_rows
        processed.append(str(iid))

        if len(processed) % 50 == 0:
            logger.info("Processed %d/%d instruments …", len(processed), len(instrument_ids))

    logger.info(
        "Ingestion complete: %d instruments, %d files, %d rows",
        len(processed), total_files, total_rows,
    )

    # Spot-check symbol encoding on underlying
    underlying_id = str(cfg["ids"]["underlying_id"])
    under_path = rdir / f"{underlying_id}.parquet"
    if under_path.exists():
        sample = pd.read_parquet(under_path, columns=["symbol"]).dropna()
        logger.info("Underlying symbol sample (mojibake check): %s", sample["symbol"].unique()[:3].tolist())

    # Write index
    index_path = panels_dir(cfg) / "book_raw_index.parquet"
    index_df = pd.DataFrame({"instrument_id": processed})
    index_df.to_parquet(index_path, index=False)

    save_manifest(
        cfg,
        {
            "ingest": {
                "n_instruments": len(processed),
                "n_files": total_files,
                "n_rows": total_rows,
            }
        },
    )
    return processed


if __name__ == "__main__":
    setup_logging()
    cfg = load_config()
    run(cfg)
