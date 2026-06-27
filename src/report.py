"""Module 4.13 — Report assembly.

Generates:
  outputs/RESULTS.md
  outputs/data_quality_report.md
  (updates manifest.json)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from .utils import (
    findings_dir,
    load_config,
    load_manifest,
    out_dir,
    panels_dir,
    setup_logging,
    tables_dir,
)

logger = logging.getLogger(__name__)


def _load_json(path: Path) -> list | dict:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


def _finding_block(f: dict) -> str:
    lines = [
        f"### {f.get('id', 'unknown')} — {f.get('title', '')}",
        "",
        f"**Claim:** {f.get('claim', '')}",
        "",
    ]
    scope = f.get("scope", {})
    if scope:
        scope_str = "; ".join(f"{k}={v}" for k, v in scope.items())
        lines += [f"**Scope:** {scope_str}", ""]

    metrics = f.get("metrics", {})
    if metrics:
        lines.append("**Metrics:**")
        for k, v in metrics.items():
            lines.append(f"  - {k}: {v}")
        lines.append("")

    stat = f.get("stat_test", {})
    if stat:
        lines.append(f"**Stat test:** {stat.get('name','')}")
        if stat.get("statistic") is not None:
            lines.append(f"  - t/stat = {stat.get('statistic',''):.4f}, p = {stat.get('p_value',''):.4f}")
        lines.append("")

    fig_refs = f.get("figure_refs", [])
    if fig_refs:
        lines.append("**Figures:** " + ", ".join(f"`{x}`" for x in fig_refs))
        lines.append("")

    tbl_refs = f.get("table_refs", [])
    if tbl_refs:
        lines.append("**Tables:** " + ", ".join(f"`{x}`" for x in tbl_refs))
        lines.append("")

    lims = f.get("limitations", "")
    if lims:
        lines.append(f"**Limitations:** {lims}")
        lines.append("")

    conf = f.get("confidence", "")
    if conf:
        lines.append(f"**Confidence:** {conf}")
        lines.append("")

    return "\n".join(lines)


def generate_results(cfg: dict) -> str:
    fdir = findings_dir(cfg)
    manifest = load_manifest(cfg)
    axis_a = _load_json(fdir / "axis_a.json")
    axis_b = _load_json(fdir / "axis_b.json")

    lines = [
        "# Results — Black-Scholes Validity & Option Behavior Under Queue Dynamics (Ahrom ETF)",
        "",
        f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        "",
        "---",
        "",
        "## Data Overview",
        "",
    ]

    # Key manifest numbers
    specs = manifest.get("specs", {})
    liq = manifest.get("liquidity", {})
    bq = manifest.get("band_queue", {})
    pricing = manifest.get("pricing", {})

    lines += [
        f"- Contracts: {specs.get('n_contracts', '?')} ({specs.get('n_call','?')} call, {specs.get('n_put','?')} put)",
        f"- Zero-volume rate (within active lifetime): {100*liq.get('zero_vol_rate',0):.1f}% "
        f"(raw incl. pre/post-listing: {100*liq.get('zero_vol_rate_raw', liq.get('zero_vol_rate',0)):.1f}%)",
        f"- Call-put pair availability (EOD traded): {100*liq.get('pair_availability_rate',0):.1f}%",
        f"- Intraday eligible rate: {100*liq.get('intraday_eligible_rate',0):.1f}%",
        f"- Empirical band: {100*bq.get('band_pct',0):.2f}%",
        f"- Queue episodes detected: {bq.get('n_episodes', '?')}",
        f"- Regime counts: {bq.get('regime_counts', {})}",
        f"- Daily-eligible observations priced: {pricing.get('n_eligible','?')}",
        f"- Parity pairs (EOD): {pricing.get('n_parity_pairs','?')}",
        "",
        "---",
        "",
    ]

    # Axis A
    lines += [
        "## Axis A — Black-Scholes Validity (Free Regime)",
        "",
        "> *All results are conditional on: daily_eligible (volume>0) contract-days, "
        "free (no-queue) underlying periods, and the liquidity gate. "
        "Selection bias from this gate is acknowledged in every conclusion.*",
        "",
    ]
    for f in axis_a:
        lines.append(_finding_block(f))
        lines.append("---")
        lines.append("")

    # Axis B
    lines += [
        "## Axis B — Option Behavior vs Queue Age τ",
        "",
        "> *Results conditional on: queue regime, τ-bucket, moneyness at queue onset. "
        "Sample sizes (N) are reported. The shadow-price test is further limited "
        "by call-put pair availability.*",
        "",
    ]
    for f in axis_b:
        lines.append(_finding_block(f))
        lines.append("---")
        lines.append("")

    lines += [
        "## Open Items (Surfaced per §9 of spec)",
        "",
        "1. **Full order book level completeness:** confirmed empirically — see manifest `book.pct_incomplete`.",
        "2. **Trades schema:** not yet available; Lee-Ready module stubbed.",
        "3. **hEven resolution:** integer HHMMSS; second-level granularity.",
        "4. **Option exercise style:** assumed European, cash-settled (confirm with exchange).",
        "5. **Official band %:** not provided; empirical band used (see manifest `band_queue.band_pct`).",
        "",
    ]

    return "\n".join(lines)


def generate_data_quality(cfg: dict) -> str:
    manifest = load_manifest(cfg)
    lines = [
        "# Data Quality Report",
        "",
        f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        "",
        "## Ingestion",
    ]
    ingest = manifest.get("ingest", {})
    lines += [
        f"- Instruments ingested: {ingest.get('n_instruments','?')}",
        f"- CSV files read: {ingest.get('n_files','?')}",
        f"- Total rows: {ingest.get('n_rows','?')}",
        "",
        "## Order Book",
    ]
    book = manifest.get("book", {})
    lines += [
        f"- Snapshots reconstructed: {book.get('n_snapshots','?')}",
        f"- RefIDs missing all 5 levels: {book.get('n_incomplete_levels','?')} ({book.get('pct_incomplete','?')}%)",
        f"- Bid ordering violations: {book.get('bid_ordering_violations','?')}",
        f"- Ask ordering violations: {book.get('ask_ordering_violations','?')}",
        f"- OBI bounds OK: {book.get('obi_bounds_ok','?')}",
        "",
        "## Cleaning",
    ]
    clean = manifest.get("clean", {})
    lines += [
        f"- Empty-level cells zeroed: {clean.get('empty_level_cells','?')}",
        f"- Crossed book rows: {clean.get('crossed_rows','?')}",
        f"- Instruments with derived tick size: {clean.get('n_instruments_with_tick','?')}",
        "",
        "## Session",
    ]
    sess = manifest.get("session", {})
    lines += [
        f"- Fallback open: {sess.get('fallback_open','?')}",
        f"- Fallback close: {sess.get('fallback_close','?')}",
        f"- Pre-open rows: {sess.get('preopen_rows','?')}",
        f"- Continuous rows: {sess.get('continuous_rows','?')}",
        "",
        "## Synchronization",
    ]
    sync = manifest.get("sync", {})
    lines += [
        f"- Synced rows: {sync.get('n_rows','?')}",
        f"- Fresh rate: {100*sync.get('fresh_rate',0):.1f}%",
        f"- Staleness window: {sync.get('staleness_window_s','?')}s",
        "",
        "## Liquidity",
    ]
    liq = manifest.get("liquidity", {})
    lines += [
        f"- Zero-volume rate (within active lifetime): {100*liq.get('zero_vol_rate',0):.1f}% "
        f"(raw: {100*liq.get('zero_vol_rate_raw', liq.get('zero_vol_rate',0)):.1f}%)",
        f"- Call-put pair availability: {100*liq.get('pair_availability_rate',0):.1f}%",
        "",
        "## Band & Queue",
    ]
    bq = manifest.get("band_queue", {})
    lines += [
        f"- Empirical band: {100*bq.get('band_pct',0):.2f}%",
        f"- Episodes detected: {bq.get('n_episodes','?')}",
        f"- Regime counts: {bq.get('regime_counts',{})}",
        "",
        "## Pricing & IV",
    ]
    pr = manifest.get("pricing", {})
    lines += [
        f"- Daily-eligible rows priced: {pr.get('n_eligible','?')}",
        f"- IV flag counts: {pr.get('iv_flag_counts',{})}",
        f"- Parity pairs: {pr.get('n_parity_pairs','?')}",
    ]
    return "\n".join(lines)


def run(cfg: dict) -> None:
    odir = out_dir(cfg)

    results_md = generate_results(cfg)
    (odir / "RESULTS.md").write_text(results_md, encoding="utf-8")
    logger.info("Wrote RESULTS.md")

    dq_md = generate_data_quality(cfg)
    (odir / "data_quality_report.md").write_text(dq_md, encoding="utf-8")
    logger.info("Wrote data_quality_report.md")


if __name__ == "__main__":
    setup_logging()
    cfg = load_config()
    run(cfg)
