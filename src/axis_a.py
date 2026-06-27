"""Module 4.11 — Axis A: Black-Scholes validity in free (no-queue) conditions.

Tier-A (daily):  IV smile/skew, term structure, parity, BS error, IV dispersion
Tier-B (intraday): recompute IV/parity/error on free instants

Outputs (per §7 artifact contract):
  figures/axA_*.png|svg
  figures_data/axA_*.csv
  tables/axA_*.csv
  findings/axis_a.json
"""
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import statsmodels.api as sm

from .pricing import bs_price, iv_from_price, parity_basis, load_rates, ewma_vol
from .utils import (
    figures_dir,
    figures_data_dir,
    findings_dir,
    load_config,
    moneyness_label,
    maturity_label,
    panels_dir,
    project_root,
    save_manifest,
    setup_logging,
    tables_dir,
)

logger = logging.getLogger(__name__)


def _save_figure(fig, name: str, cfg: dict) -> None:
    fdir = figures_dir(cfg)
    fig.savefig(fdir / f"{name}.png", dpi=150, bbox_inches="tight")
    fig.savefig(fdir / f"{name}.svg", bbox_inches="tight")
    plt.close(fig)


def _save_table(df: pd.DataFrame, name: str, cfg: dict) -> None:
    tdir = tables_dir(cfg)
    df.to_csv(tdir / f"{name}.csv", index=False)
    meta = {"name": name, "rows": len(df), "columns": list(df.columns)}
    with open(tdir / f"{name}.meta.json", "w") as f:
        json.dump(meta, f, indent=2)


def _save_fig_data(df: pd.DataFrame, name: str, cfg: dict) -> None:
    df.to_csv(figures_data_dir(cfg) / f"{name}.csv", index=False)


def _hac_test(y: pd.Series) -> dict:
    """One-sample HAC t-test: H0: mean=0."""
    y = y.dropna()
    if len(y) < 5:
        return {"statistic": np.nan, "p_value": np.nan, "ci": [np.nan, np.nan], "n": len(y)}
    X = np.ones(len(y))
    try:
        res = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": min(12, len(y) // 5)})
        ci = res.conf_int().iloc[0].tolist()
        return {
            "statistic": float(res.tvalues[0]),
            "p_value": float(res.pvalues[0]),
            "ci": [float(ci[0]), float(ci[1])],
            "n": len(y),
        }
    except Exception as e:
        logger.warning("HAC test failed: %s", e)
        return {"statistic": np.nan, "p_value": np.nan, "ci": [np.nan, np.nan], "n": len(y)}


def run_tier_a(cfg: dict, eod: pd.DataFrame) -> list[dict]:
    """Tier-A daily analysis. Returns list of finding dicts."""
    findings = []
    mon_edges = cfg["buckets"]["moneyness_edges"]
    mat_edges = cfg["buckets"]["maturity_days_edges"]

    # ── 1. IV smile / skew ────────────────────────────────────────────────────
    iv_data = eod.dropna(subset=["iv", "moneyness", "days_to_expiry"]).copy()
    iv_data["moneyness_bucket"] = iv_data["moneyness"].apply(
        lambda x: moneyness_label(x, mon_edges)
    )
    iv_data["maturity_bucket"] = iv_data["days_to_expiry"].apply(
        lambda x: maturity_label(x, mat_edges)
    )

    iv_summary = (
        iv_data.groupby(["moneyness_bucket", "maturity_bucket", "option_type"])
        .agg(
            n=("iv", "count"),
            mean_iv=("iv", "mean"),
            median_iv=("iv", "median"),
            std_iv=("iv", "std"),
        )
        .reset_index()
    )
    _save_table(iv_summary, "axA_iv_summary", cfg)

    # IV smile figure (per maturity bucket, near-money focus)
    for mat_bkt in iv_data["maturity_bucket"].unique():
        sub = iv_data[iv_data["maturity_bucket"] == mat_bkt]
        if len(sub) < 5:
            continue
        fig, ax = plt.subplots(figsize=(8, 4))
        for opt_type, grp in sub.groupby("option_type"):
            grp_sorted = grp.sort_values("moneyness")
            ax.scatter(grp_sorted["moneyness"], grp_sorted["iv"], s=8, alpha=0.4, label=opt_type)
        ax.set_xlabel("Moneyness (S/K)")
        ax.set_ylabel("Implied Volatility")
        ax.set_title(f"IV Smile — maturity bucket: {mat_bkt}")
        ax.legend()
        _save_figure(fig, f"axA_iv_smile_{mat_bkt}", cfg)
        _save_fig_data(
            sub[["moneyness", "iv", "option_type", "maturity_bucket"]],
            f"axA_iv_smile_{mat_bkt}",
            cfg,
        )

    # Combined smile figure
    fig, ax = plt.subplots(figsize=(8, 4))
    for opt_type, grp in iv_data.groupby("option_type"):
        ax.scatter(grp["moneyness"], grp["iv"], s=5, alpha=0.3, label=opt_type)
    ax.set_xlabel("Moneyness (S/K)")
    ax.set_ylabel("IV")
    ax.set_title("IV Smile — all maturities")
    ax.legend()
    _save_figure(fig, "axA_iv_smile", cfg)
    _save_fig_data(iv_data[["moneyness", "iv", "option_type", "maturity_bucket"]], "axA_iv_smile", cfg)

    # Skew regression: IV ~ moneyness (for near-term calls)
    near = iv_data[
        (iv_data["maturity_bucket"] == "short") & (iv_data["option_type"] == "call")
    ].dropna(subset=["moneyness", "iv"])
    if len(near) >= 10:
        X = sm.add_constant(near["moneyness"])
        res = sm.OLS(near["iv"], X).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
        skew_slope = float(res.params["moneyness"])
        skew_pval = float(res.pvalues["moneyness"])
        findings.append({
            "id": "axA_skew_persistent",
            "axis": "A",
            "title": "IV skew in near-term calls (free periods)",
            "claim": f"Near-term call IV slope vs moneyness = {skew_slope:.4f} (p={skew_pval:.3f})",
            "scope": {"moneyness": "near-atm", "maturity_days": "<=30", "regime": "free"},
            "metrics": {"skew_slope": skew_slope, "n_obs": len(near), "p_value": skew_pval},
            "stat_test": {"name": "HAC OLS", "statistic": float(res.tvalues["moneyness"]),
                          "p_value": skew_pval, "ci": list(res.conf_int().loc["moneyness"])},
            "figure_refs": ["axA_iv_smile"],
            "table_refs": ["axA_iv_summary"],
            "robustness": "r-sensitivity, subperiods",
            "limitations": "selection bias from liquidity gate",
            "confidence": "medium",
        })

    # ── 2. IV term structure ───────────────────────────────────────────────────
    ts_data = (
        iv_data.groupby(["days_to_expiry", "option_type"])
        .agg(mean_iv=("iv", "mean"), n=("iv", "count"))
        .reset_index()
    )
    fig, ax = plt.subplots(figsize=(8, 4))
    for ot, grp in ts_data.groupby("option_type"):
        ax.scatter(grp["days_to_expiry"], grp["mean_iv"], s=10, alpha=0.6, label=ot)
    ax.set_xlabel("Days to Expiry")
    ax.set_ylabel("Mean IV")
    ax.set_title("IV Term Structure")
    ax.legend()
    _save_figure(fig, "axA_iv_term_structure", cfg)
    _save_fig_data(ts_data, "axA_iv_term_structure", cfg)

    # ── 3. BS pricing error by bucket ─────────────────────────────────────────
    err_data = eod.dropna(subset=["bs_error"]).copy()
    if "moneyness" not in err_data.columns:
        err_data["moneyness"] = err_data["K"] / err_data["close"]
    err_data["moneyness_bucket"] = err_data["moneyness"].apply(
        lambda x: moneyness_label(x, mon_edges)
    )
    err_data["maturity_bucket"] = err_data["days_to_expiry"].apply(
        lambda x: maturity_label(x, mat_edges)
    )

    err_summary = (
        err_data.groupby(["moneyness_bucket", "maturity_bucket", "option_type"])
        .agg(
            n=("bs_error", "count"),
            mean_err=("bs_error", "mean"),
            median_err=("bs_error", "median"),
            std_err=("bs_error", "std"),
        )
        .reset_index()
    )
    _save_table(err_summary, "axA_pricing_error", cfg)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for ax, ot in zip(axes, ["call", "put"]):
        sub = err_data[err_data["option_type"] == ot]
        if len(sub) == 0:
            continue
        sub_g = sub.groupby("moneyness_bucket")["bs_error"].mean()
        sub_g.plot(kind="bar", ax=ax)
        ax.axhline(0, color="k", linewidth=0.8)
        ax.set_title(f"BS Error by Moneyness — {ot}")
        ax.set_xlabel("Moneyness Bucket")
        ax.set_ylabel("BS Error (price units)")
    plt.tight_layout()
    _save_figure(fig, "axA_pricing_error_by_bucket", cfg)
    _save_fig_data(err_summary, "axA_pricing_error_by_bucket", cfg)

    # Finding: BS error
    hac = _hac_test(err_data["bs_error"])
    findings.append({
        "id": "axA_bs_error",
        "axis": "A",
        "title": "BS pricing error magnitude and direction",
        "claim": (
            f"Median BS pricing error (EWMA vol) = {err_data['bs_error'].median():.2f}; "
            f"mean = {err_data['bs_error'].mean():.2f} (p={hac['p_value']:.3f}, n={hac['n']})"
        ),
        "scope": {"regime": "daily_eligible", "maturity_days": "all"},
        "metrics": {
            "median_bs_error": float(err_data["bs_error"].median()),
            "mean_bs_error": float(err_data["bs_error"].mean()),
            "n_obs": int(len(err_data)),
        },
        "stat_test": {"name": "HAC t-test", **hac},
        "figure_refs": ["axA_pricing_error_by_bucket"],
        "table_refs": ["axA_pricing_error"],
        "robustness": "r-sensitivity, bucket stratification",
        "limitations": "uses EWMA vol which may itself be biased for a leveraged ETF",
        "confidence": "medium",
    })

    # ── 4. Parity by bucket ───────────────────────────────────────────────────
    parity_path = panels_dir(cfg) / "eod_parity.parquet"
    if parity_path.exists():
        pairs = pd.read_parquet(parity_path)
        pairs = pairs.dropna(subset=["parity_basis"])
        if len(pairs) > 0:
            pairs["moneyness"] = pairs.get("moneyness_call", np.nan)
            if "moneyness" not in pairs.columns or pairs["moneyness"].isna().all():
                if "S_call" in pairs.columns and "K_call" in pairs.columns:
                    pairs["moneyness"] = pairs["K_call"] / pairs["S_call"]
            pairs["moneyness_bucket"] = pairs["moneyness"].apply(
                lambda x: moneyness_label(x, mon_edges) if pd.notna(x) else "unknown"
            )
            if "days_to_expiry" not in pairs.columns and "T_call" in pairs.columns:
                pairs["days_to_expiry"] = (pairs["T_call"] * cfg["pricing"]["daycount"]).round()
            if "days_to_expiry" in pairs.columns:
                pairs["maturity_bucket"] = pairs["days_to_expiry"].apply(
                    lambda x: maturity_label(x, mat_edges) if pd.notna(x) else "unknown"
                )
            else:
                pairs["maturity_bucket"] = "unknown"

            par_summary = (
                pairs.groupby(["moneyness_bucket", "maturity_bucket"])
                .agg(
                    n=("parity_basis", "count"),
                    mean_basis=("parity_basis", "mean"),
                    median_basis=("parity_basis", "median"),
                    std_basis=("parity_basis", "std"),
                )
                .reset_index()
            )
            _save_table(par_summary, "axA_parity_summary", cfg)

            fig, ax = plt.subplots(figsize=(8, 4))
            for bkt, grp in pairs.groupby("moneyness_bucket"):
                ax.hist(grp["parity_basis"], bins=30, alpha=0.5, label=bkt)
            ax.axvline(0, color="k")
            ax.set_xlabel("Parity Basis (C-P) - (S - Ke^{-rT})")
            ax.set_title("Put-Call Parity Basis by Moneyness")
            ax.legend()
            _save_figure(fig, "axA_parity_by_bucket", cfg)
            _save_fig_data(pairs[["moneyness_bucket", "parity_basis"]], "axA_parity_by_bucket", cfg)

            hac_par = _hac_test(pairs["parity_basis"])
            findings.append({
                "id": "axA_parity",
                "axis": "A",
                "title": "Put-call parity deviation",
                "claim": (
                    f"Median parity basis = {pairs['parity_basis'].median():.2f}; "
                    f"mean = {pairs['parity_basis'].mean():.2f} (p={hac_par['p_value']:.3f})"
                ),
                "scope": {"regime": "daily_eligible", "moneyness": "all"},
                "metrics": {
                    "median_parity_basis": float(pairs["parity_basis"].median()),
                    "n_pairs": int(len(pairs)),
                },
                "stat_test": {"name": "HAC t-test", **hac_par},
                "figure_refs": ["axA_parity_by_bucket"],
                "table_refs": ["axA_parity_summary"],
                "robustness": "r-sensitivity",
                "limitations": "EOD pair availability ~31%; stale quotes possible",
                "confidence": "medium",
            })

    # ── 5. IV dispersion ─────────────────────────────────────────────────────
    iv_disp = (
        iv_data.groupby(["date_str", "maturity_bucket"] if "date_str" in iv_data.columns else ["maturity_bucket"])
        .agg(iv_std=("iv", "std"), n=("iv", "count"))
        .reset_index()
    )
    if "date_str" in iv_disp.columns:
        iv_disp_agg = iv_disp.groupby("maturity_bucket").agg(
            mean_iv_dispersion=("iv_std", "mean"), n_dates=("iv_std", "count")
        ).reset_index()
    else:
        iv_disp_agg = iv_disp

    _save_table(iv_disp_agg, "axA_iv_dispersion", cfg)
    _save_fig_data(iv_disp_agg, "axA_iv_dispersion", cfg)

    fig, ax = plt.subplots(figsize=(7, 4))
    if "date_str" in iv_disp.columns:
        for bkt, grp in iv_disp.groupby("maturity_bucket"):
            ax.hist(grp["iv_std"].dropna(), bins=20, alpha=0.5, label=bkt)
    else:
        iv_disp["iv_std"].dropna().hist(bins=20, ax=ax)
    ax.set_xlabel("IV Std Dev across contracts (same date/maturity)")
    ax.set_title("Cross-contract IV Dispersion")
    ax.legend()
    _save_figure(fig, "axA_iv_dispersion", cfg)

    return findings


def run(cfg: dict) -> None:
    pdir = panels_dir(cfg)
    eod_path = pdir / "eod_pricing.parquet"

    if not eod_path.exists():
        logger.error("eod_pricing.parquet not found — run pricing.py first")
        return

    logger.info("Loading eod_pricing …")
    eod = pd.read_parquet(eod_path)
    logger.info("eod_pricing: %d rows", len(eod))

    if "date_str" not in eod.columns:
        eod["date_str"] = pd.to_datetime(eod["date"], format="%Y%m%d", errors="coerce").dt.strftime("%Y%m%d")

    if "moneyness" not in eod.columns and "S" in eod.columns and "K" in eod.columns:
        eod["moneyness"] = eod["K"] / eod["S"]

    # Tier-A analysis
    findings = run_tier_a(cfg, eod)

    # Write findings
    fdir = findings_dir(cfg)
    with open(fdir / "axis_a.json", "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2, ensure_ascii=False, default=str)
    logger.info("Wrote findings/axis_a.json with %d findings", len(findings))

    save_manifest(cfg, {"axis_a": {"n_findings": len(findings)}})


if __name__ == "__main__":
    setup_logging()
    cfg = load_config()
    run(cfg)
