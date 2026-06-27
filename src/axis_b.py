"""Module 4.12 — Axis B: Option behavior as a function of queue age τ.

Reads synced/{iid}.parquet for all synced instruments, combines queue snapshots,
and runs τ-bucket analysis.

Outputs:
  figures/axB_*.png|svg
  figures_data/axB_*.csv
  tables/axB_*.csv
  findings/axis_b.json
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

from .sync import get_synced_path, list_synced_instruments
from .utils import (
    figures_dir,
    figures_data_dir,
    findings_dir,
    load_config,
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
    with open(tdir / f"{name}.meta.json", "w") as f:
        json.dump({"name": name, "rows": len(df), "columns": list(df.columns)}, f)


def _save_fig_data(df: pd.DataFrame, name: str, cfg: dict) -> None:
    df.to_csv(figures_data_dir(cfg) / f"{name}.csv", index=False)


def tau_bucket_label(tau: float, edges: list) -> str:
    for i, edge in enumerate(edges[1:]):
        if tau < edge:
            return f"{edges[i]}-{edges[i+1]}min"
    return f"{edges[-2]}+min"


_QUEUE_COLS_NEEDED = [
    "instrument_id", "date", "regime", "tau_min", "episode_id",
    "depth_bid", "depth_ask", "OBI", "n_updates", "spread", "rel_spread",
    "bid_qty_1", "ask_qty_1", "two_sided", "fresh",
]


def load_all_queue_snapshots(cfg: dict) -> pd.DataFrame:
    """Load queue-regime rows from synced instruments, reading only needed columns."""
    import gc
    import pyarrow.parquet as pq_r
    import pyarrow.compute as pc_r

    instruments = list_synced_instruments(cfg)
    chunks = []
    for iid in instruments:
        sp = get_synced_path(cfg, iid)
        if not sp.exists():
            continue
        pf = pq_r.ParquetFile(sp, memory_map=True)
        if pf.metadata.num_rows == 0:
            continue
        schema_names = pf.schema_arrow.names
        if "regime" not in schema_names:
            continue
        read_cols = [c for c in _QUEUE_COLS_NEEDED if c in schema_names]
        # Read file, filter to queue rows only
        tbl = pf.read(columns=read_cols)
        regime_col = tbl.column("regime")
        mask = pc_r.or_(pc_r.equal(regime_col, "buy_queue"),
                         pc_r.equal(regime_col, "sell_queue"))
        q_tbl = tbl.filter(mask)
        del tbl
        if q_tbl.num_rows == 0:
            del q_tbl
            continue
        q_df = q_tbl.to_pandas()
        del q_tbl
        q_df["instrument_id"] = str(iid)
        chunks.append(q_df)
        gc.collect()

    if not chunks:
        return pd.DataFrame()
    result = pd.concat(chunks, ignore_index=True)
    del chunks
    gc.collect()
    return result


def run(cfg: dict) -> None:
    root = project_root()
    pdir = panels_dir(cfg)
    ep_path = pdir / "queue_episodes.parquet"
    eod_path = pdir / "eod_pricing.parquet"
    parity_path = pdir / "eod_parity.parquet"
    under_eod_path = root / cfg["paths"]["underlying_history"]
    tau_edges = cfg["tau_buckets_min"]

    findings = []
    episodes = pd.read_parquet(ep_path) if ep_path.exists() else pd.DataFrame()
    eod = pd.read_parquet(eod_path) if eod_path.exists() else pd.DataFrame()
    under_eod = pd.read_csv(under_eod_path, encoding="utf-8")
    under_eod["date"] = under_eod["date"].astype(str)

    logger.info("Loading queue snapshots from all synced instruments …")
    queue_snaps = load_all_queue_snapshots(cfg)
    logger.info("Total queue option snapshots: %d; Episodes: %d", len(queue_snaps), len(episodes))

    if len(queue_snaps) == 0:
        findings.append({
            "id": "axB_no_queue_data",
            "axis": "B",
            "title": "No queue episodes detected in synced data",
            "claim": "No queue episodes found with option snapshots.",
            "scope": {"regime": "queue"},
            "metrics": {"n_queue_snaps": 0},
            "stat_test": {},
            "figure_refs": [],
            "table_refs": [],
            "robustness": "N/A",
            "limitations": "Insufficient queue data",
            "confidence": "low",
        })
        for fig_name in ["axB_shadow_vs_tau", "axB_iv_vs_tau", "axB_spread_depth_vs_tau",
                          "axB_tradeintensity_vs_tau", "axB_nextday_open"]:
            fig, ax = plt.subplots(figsize=(7, 4))
            ax.text(0.5, 0.5, f"{fig_name}\n(no queue data)", ha="center", va="center",
                    transform=ax.transAxes)
            _save_figure(fig, fig_name, cfg)
            pd.DataFrame({"note": ["unavailable"]}).to_csv(
                figures_data_dir(cfg) / f"{fig_name}.csv", index=False
            )
        fdir = findings_dir(cfg)
        with open(fdir / "axis_b.json", "w", encoding="utf-8") as f:
            json.dump(findings, f, indent=2)
        save_manifest(cfg, {"axis_b": {"status": "no_queue_data", "n_findings": len(findings)}})
        return

    # Assign τ bucket
    if "tau_min" in queue_snaps.columns:
        queue_snaps["tau_bucket"] = queue_snaps["tau_min"].apply(
            lambda x: tau_bucket_label(x, tau_edges) if pd.notna(x) else "unknown"
        )

    # ── τ-bucket summary ──────────────────────────────────────────────────────
    agg = {}
    for col in ["spread", "rel_spread", "OBI", "depth_bid", "depth_ask"]:
        if col in queue_snaps.columns:
            agg[f"mean_{col}"] = (col, "mean")
            agg[f"median_{col}"] = (col, "median")
    agg["n_snaps"] = ("tau_bucket", "count") if "tau_bucket" in queue_snaps.columns else ("regime", "count")

    tau_summary = queue_snaps.groupby(["tau_bucket", "regime"] if "tau_bucket" in queue_snaps.columns else ["regime"]).agg(**agg).reset_index()
    _save_table(tau_summary, "axB_tau_buckets", cfg)
    _save_fig_data(tau_summary, "axB_tau_buckets", cfg)

    findings.append({
        "id": "axB_tau_coverage",
        "axis": "B",
        "title": "τ-bucket coverage in queue regime",
        "claim": (
            f"Total queue option snapshots: {len(queue_snaps)}; "
            f"buy_queue: {(queue_snaps['regime']=='buy_queue').sum()}; "
            f"sell_queue: {(queue_snaps['regime']=='sell_queue').sum()}"
        ),
        "scope": {"regime": "queue"},
        "metrics": {
            "n_queue_snaps": int(len(queue_snaps)),
            "n_buy_queue": int((queue_snaps["regime"] == "buy_queue").sum()),
            "n_sell_queue": int((queue_snaps["regime"] == "sell_queue").sum()),
        },
        "stat_test": {},
        "figure_refs": [],
        "table_refs": ["axB_tau_buckets"],
        "robustness": "τ-bucket edges from config",
        "limitations": "N depends on detected episodes",
        "confidence": "high" if len(queue_snaps) > 100 else "medium",
    })

    # ── Depth & OBI vs τ ─────────────────────────────────────────────────────
    # In queue regime, spread is NaN (ask/bid side empty). Use depth and OBI instead.
    if "tau_bucket" in queue_snaps.columns:
        depth_agg = {}
        for col in ["depth_bid", "depth_ask", "OBI"]:
            if col in queue_snaps.columns:
                depth_agg[f"median_{col}"] = (col, "median")
                depth_agg[f"mean_{col}"] = (col, "mean")
        depth_agg["n_snaps"] = ("regime", "count")
        tau_depth = (
            queue_snaps.groupby(["tau_bucket", "regime"])
            .agg(**depth_agg)
            .reset_index()
        )
        _save_fig_data(tau_depth, "axB_spread_depth_vs_tau", cfg)

        fig, axes = plt.subplots(1, 2, figsize=(12, 4))
        for ax_i, (col, label) in enumerate([("median_depth_bid", "Median Bid-Side Depth"),
                                              ("median_OBI", "Median OBI")]):
            ax_sub = axes[ax_i]
            if col in tau_depth.columns:
                for regime_val, grp in tau_depth.groupby("regime"):
                    ax_sub.plot(range(len(grp)), grp[col], marker="o", label=regime_val)
                    ax_sub.set_xticks(range(len(grp)))
                    ax_sub.set_xticklabels(grp["tau_bucket"].tolist(), rotation=30, fontsize=8)
                ax_sub.set_ylabel(label)
                ax_sub.set_title(f"{label} vs Queue Age τ")
                ax_sub.legend(fontsize=8)
            else:
                ax_sub.text(0.5, 0.5, f"{col} N/A", ha="center", va="center", transform=ax_sub.transAxes)
        fig.tight_layout()
        _save_figure(fig, "axB_spread_depth_vs_tau", cfg)
    else:
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.text(0.5, 0.5, "tau_bucket not available", ha="center", va="center", transform=ax.transAxes)
        _save_figure(fig, "axB_spread_depth_vs_tau", cfg)
        pd.DataFrame({"note": ["unavailable"]}).to_csv(
            figures_data_dir(cfg) / "axB_spread_depth_vs_tau.csv", index=False)

    # ── IV vs τ (join with EOD pricing) ──────────────────────────────────────
    if eod_path.exists() and "tau_bucket" in queue_snaps.columns:
        eod_pr = pd.read_parquet(eod_path)
        eod_pr["instrument_id"] = eod_pr["instrument_id"].astype(str)
        eod_pr["date"] = eod_pr["date"].astype(str)
        iv_cols = [c for c in ["instrument_id", "date", "iv", "iv_flag", "option_type",
                                "moneyness_bucket", "maturity_bucket"] if c in eod_pr.columns]
        iv_eod = eod_pr[iv_cols].dropna(subset=["iv"])
        iv_eod = iv_eod[iv_eod["iv"] > 0]

        # Merge queue snaps with EOD IV on (instrument_id, date)
        qs_for_iv = queue_snaps[["instrument_id", "date", "tau_bucket", "regime"]].copy()
        qs_for_iv["instrument_id"] = qs_for_iv["instrument_id"].astype(str)
        qs_for_iv["date"] = qs_for_iv["date"].astype(str)
        # One IV per (instrument_id, date) — take first valid
        iv_day = iv_eod.groupby(["instrument_id", "date"])["iv"].first().reset_index()
        qs_iv = qs_for_iv.merge(iv_day, on=["instrument_id", "date"], how="left")
        qs_iv_valid = qs_iv.dropna(subset=["iv"])

        if len(qs_iv_valid) >= 5:
            tau_iv = (
                qs_iv_valid.groupby("tau_bucket")
                .agg(median_iv=("iv", "median"), mean_iv=("iv", "mean"), n=("iv", "count"))
                .reset_index()
            )
            _save_fig_data(tau_iv, "axB_iv_vs_tau", cfg)
            fig, ax = plt.subplots(figsize=(8, 4))
            ax.bar(range(len(tau_iv)), tau_iv["median_iv"])
            ax.set_xticks(range(len(tau_iv)))
            ax.set_xticklabels(tau_iv["tau_bucket"].tolist(), rotation=30)
            ax.set_ylabel("Median Implied Volatility")
            ax.set_title(f"IV vs Queue Age τ (EOD, N={len(qs_iv_valid)})")
            fig.tight_layout()
            _save_figure(fig, "axB_iv_vs_tau", cfg)
        else:
            fig, ax = plt.subplots(figsize=(7, 4))
            ax.text(0.5, 0.5, f"Insufficient IV data (N={len(qs_iv_valid)})",
                    ha="center", va="center", transform=ax.transAxes)
            _save_figure(fig, "axB_iv_vs_tau", cfg)
            pd.DataFrame({"note": [f"N={len(qs_iv_valid)}"]}).to_csv(
                figures_data_dir(cfg) / "axB_iv_vs_tau.csv", index=False)
    else:
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.text(0.5, 0.5, "EOD pricing not available", ha="center", va="center", transform=ax.transAxes)
        _save_figure(fig, "axB_iv_vs_tau", cfg)
        pd.DataFrame({"note": ["unavailable"]}).to_csv(
            figures_data_dir(cfg) / "axB_iv_vs_tau.csv", index=False)

    # ── Book update intensity vs τ ────────────────────────────────────────────
    # n_updates = daily order book updates; proxy for trading / quote activity
    if "n_updates" in queue_snaps.columns and "tau_bucket" in queue_snaps.columns:
        tau_upd = (
            queue_snaps.groupby(["tau_bucket", "regime"])
            .agg(median_updates=("n_updates", "median"), mean_updates=("n_updates", "mean"),
                 n=("n_updates", "count"))
            .reset_index()
        )
        _save_fig_data(tau_upd, "axB_tradeintensity_vs_tau", cfg)
        fig, ax = plt.subplots(figsize=(8, 4))
        for regime_val, grp in tau_upd.groupby("regime"):
            ax.plot(range(len(grp)), grp["median_updates"], marker="o", label=regime_val)
            ax.set_xticks(range(len(grp)))
            ax.set_xticklabels(grp["tau_bucket"].tolist(), rotation=30, fontsize=8)
        ax.set_ylabel("Median Daily Book Updates (n_updates)")
        ax.set_title("Quote Activity vs Queue Age τ")
        ax.legend()
        fig.tight_layout()
        _save_figure(fig, "axB_tradeintensity_vs_tau", cfg)
    else:
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.text(0.5, 0.5, "n_updates not available", ha="center", va="center", transform=ax.transAxes)
        _save_figure(fig, "axB_tradeintensity_vs_tau", cfg)
        pd.DataFrame({"note": ["unavailable"]}).to_csv(
            figures_data_dir(cfg) / "axB_tradeintensity_vs_tau.csv", index=False)

    # ── Shadow price (EOD pairs during queue days) ────────────────────────────
    shadow_avail = 0
    if parity_path.exists() and len(episodes) > 0:
        pairs = pd.read_parquet(parity_path)
        if "shadow_S" in pairs.columns and "date_str" in pairs.columns:
            ep_dates = set(episodes["date"].astype(str))
            ep_pairs = pairs[pairs["date_str"].isin(ep_dates)].dropna(subset=["shadow_S"])
            shadow_avail = len(ep_pairs)
            under_close_map = under_eod.set_index("date")["close"].to_dict()
            ep_pairs = ep_pairs.copy()
            ep_pairs["locked_price"] = ep_pairs["date_str"].map(under_close_map)
            ep_pairs["shadow_gap"] = ep_pairs["shadow_S"] - ep_pairs["locked_price"]

            _save_table(
                ep_pairs[["date_str", "shadow_S", "shadow_gap"]].dropna(subset=["shadow_S"]),
                "axB_shadow_availability",
                cfg,
            )
            fig, ax = plt.subplots(figsize=(8, 4))
            ep_pairs["shadow_gap"].dropna().hist(bins=30, ax=ax)
            ax.set_xlabel("Shadow Gap (S* - locked_price)")
            ax.set_title(f"Shadow Price Gap (N={shadow_avail} EOD pairs during queue days)")
            _save_figure(fig, "axB_shadow_vs_tau", cfg)
            _save_fig_data(ep_pairs[["shadow_S", "shadow_gap"]].dropna(), "axB_shadow_vs_tau", cfg)

            # Star test
            under_eod["next_first"] = under_eod["first"].shift(-1)
            under_eod["next_open_ret"] = np.log(
                under_eod["next_first"].replace(0, np.nan) / under_eod["close"].replace(0, np.nan)
            ).replace([np.inf, -np.inf], np.nan)
            under_map = under_eod.set_index("date")[["close", "next_open_ret"]]
            ep_pairs = ep_pairs.merge(
                under_map.reset_index().rename(columns={"date": "date_str", "close": "und_close"}),
                on="date_str", how="left",
            )
            star_data = ep_pairs.dropna(subset=["shadow_gap", "next_open_ret"])
            star_n = len(star_data)
            _save_table(star_data[["date_str", "shadow_gap", "next_open_ret"]], "axB_nextday_pred", cfg)

            if star_n >= 5:
                X = sm.add_constant(star_data["shadow_gap"])
                res = sm.OLS(star_data["next_open_ret"], X).fit()
                star_slope = float(res.params.get("shadow_gap", np.nan))
                star_p = float(res.pvalues.get("shadow_gap", np.nan))
                fig, ax = plt.subplots(figsize=(7, 4))
                ax.scatter(star_data["shadow_gap"], star_data["next_open_ret"], alpha=0.6)
                ax.set_xlabel("Shadow Gap")
                ax.set_ylabel("Next-Day Open Return")
                ax.set_title(f"Star Test (N={star_n})")
                _save_figure(fig, "axB_nextday_open", cfg)
                _save_fig_data(star_data[["shadow_gap", "next_open_ret"]], "axB_nextday_open", cfg)
                findings.append({
                    "id": "axB_nextday_open",
                    "axis": "B",
                    "title": "Next-day open predictability from shadow gap",
                    "claim": f"Shadow gap slope={star_slope:.2e}, p={star_p:.4f}, N={star_n}",
                    "scope": {"regime": "queue"},
                    "metrics": {"shadow_gap_slope": star_slope, "n_obs": star_n, "p_value": star_p},
                    "stat_test": {"name": "OLS"},
                    "figure_refs": ["axB_nextday_open"],
                    "table_refs": ["axB_nextday_pred"],
                    "robustness": "low power expected",
                    "limitations": f"N={star_n}; EOD only",
                    "confidence": "low" if star_n < 20 else "medium",
                })
            else:
                fig, ax = plt.subplots(figsize=(7, 4))
                ax.text(0.5, 0.5, f"Star test: N={star_n} — underpowered", ha="center", va="center",
                        transform=ax.transAxes)
                _save_figure(fig, "axB_nextday_open", cfg)
                pd.DataFrame({"note": [f"N={star_n}"]}).to_csv(figures_data_dir(cfg) / "axB_nextday_open.csv", index=False)
    else:
        for fn in ["axB_shadow_vs_tau", "axB_nextday_open"]:
            fig, ax = plt.subplots(figsize=(7, 4))
            ax.text(0.5, 0.5, f"{fn}\n(no parity pairs during queue days)", ha="center", va="center",
                    transform=ax.transAxes)
            _save_figure(fig, fn, cfg)
            pd.DataFrame({"note": ["unavailable"]}).to_csv(figures_data_dir(cfg) / f"{fn}.csv", index=False)

    findings.append({
        "id": "axB_shadow_availability",
        "axis": "B",
        "title": "Shadow price availability during queue episodes",
        "claim": f"Shadow price computable for {shadow_avail} EOD pairs during queue days.",
        "scope": {"regime": "queue"},
        "metrics": {"n_shadow_obs": shadow_avail},
        "stat_test": {},
        "figure_refs": ["axB_shadow_vs_tau"],
        "table_refs": ["axB_shadow_availability"] if shadow_avail > 0 else [],
        "robustness": "limited by pair availability",
        "limitations": "EOD only",
        "confidence": "high" if shadow_avail > 10 else "low",
    })

    fdir = findings_dir(cfg)
    with open(fdir / "axis_b.json", "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2, ensure_ascii=False, default=str)
    logger.info("Wrote findings/axis_b.json: %d findings", len(findings))

    save_manifest(cfg, {
        "axis_b": {
            "n_queue_snaps": int(len(queue_snaps)),
            "n_findings": len(findings),
            "shadow_availability_n": shadow_avail,
        }
    })


if __name__ == "__main__":
    setup_logging()
    cfg = load_config()
    run(cfg)
