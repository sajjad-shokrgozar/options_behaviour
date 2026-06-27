"""Module 4.10 — Black-Scholes pricing, IV, parity, shadow price, rates.

Functions:
  bs_price, bs_delta, iv_from_price, parity_basis, shadow_price
  load_rates, ewma_vol
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm

from .utils import (
    load_config,
    panels_dir,
    project_root,
    save_manifest,
    setup_logging,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Core BS functions
# ──────────────────────────────────────────────────────────────────────────────

def bs_price(S: float, K: float, T: float, r: float, sigma: float, kind: str) -> float:
    """Black-Scholes European, no dividend."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return np.nan
    sqrtT = np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    if kind == "call":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    elif kind == "put":
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    raise ValueError(f"kind must be 'call' or 'put', got {kind!r}")


def bs_price_vec(S, K, T, r, sigma, kind):
    """Vectorized BS price using numpy."""
    S, K, T, r, sigma = map(np.asarray, [S, K, T, r, sigma])
    valid = (T > 0) & (sigma > 0) & (S > 0) & (K > 0)
    out = np.full_like(S, np.nan, dtype=float)
    if not valid.any():
        return out
    Sv, Kv, Tv, rv, sv = S[valid], K[valid], T[valid], r[valid], sigma[valid]
    sqrtT = np.sqrt(Tv)
    d1 = (np.log(Sv / Kv) + (rv + 0.5 * sv**2) * Tv) / (sv * sqrtT)
    d2 = d1 - sv * sqrtT
    if kind == "call":
        out[valid] = Sv * norm.cdf(d1) - Kv * np.exp(-rv * Tv) * norm.cdf(d2)
    else:
        out[valid] = Kv * np.exp(-rv * Tv) * norm.cdf(-d2) - Sv * norm.cdf(-d1)
    return out


def bs_delta(S: float, K: float, T: float, r: float, sigma: float, kind: str) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return np.nan
    sqrtT = np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrtT)
    if kind == "call":
        return norm.cdf(d1)
    return norm.cdf(d1) - 1


def bs_vega(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return np.nan
    sqrtT = np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrtT)
    return S * norm.pdf(d1) * sqrtT


def _no_arb_bounds(S: float, K: float, T: float, r: float, kind: str) -> tuple[float, float]:
    """Compute no-arbitrage price bounds."""
    pv_k = K * np.exp(-r * T)
    if kind == "call":
        lo = max(0.0, S - pv_k)
        hi = S
    else:
        lo = max(0.0, pv_k - S)
        hi = pv_k
    return lo, hi


def iv_from_price(
    price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    kind: str,
    brackets: list[float] | None = None,
) -> tuple[float, str]:
    """
    Implied volatility via Brent's method.
    Returns (iv, flag) where flag ∈ {'ok', 'no_arb', 'numerical', 'invalid_input'}.
    """
    if brackets is None:
        brackets = [1e-4, 5.0]

    if T <= 0 or S <= 0 or K <= 0 or price < 0:
        return np.nan, "invalid_input"

    lo_price, hi_price = _no_arb_bounds(S, K, T, r, kind)
    if price <= lo_price or price >= hi_price * 1.5:
        return np.nan, "no_arb"

    def objective(sigma):
        return bs_price(S, K, T, r, sigma, kind) - price

    try:
        lo_v, hi_v = brackets
        f_lo = objective(lo_v)
        f_hi = objective(hi_v)
        if f_lo * f_hi > 0:
            return np.nan, "numerical"
        iv = brentq(objective, lo_v, hi_v, xtol=1e-8, maxiter=200)
        return float(iv), "ok"
    except Exception:
        return np.nan, "numerical"


def parity_basis(C: float, P: float, S: float, K: float, T: float, r: float) -> float:
    """Put-call parity basis: (C - P) - (S - K e^{-rT})."""
    if any(np.isnan(x) for x in [C, P, S, K, T, r]):
        return np.nan
    return (C - P) - (S - K * np.exp(-r * T))


def shadow_price(C: float, P: float, K: float, T: float, r: float) -> float:
    """Shadow price S* = C - P + K e^{-rT}."""
    if any(np.isnan(x) for x in [C, P, K, T, r]):
        return np.nan
    return C - P + K * np.exp(-r * T)


# ──────────────────────────────────────────────────────────────────────────────
# Rates & volatility
# ──────────────────────────────────────────────────────────────────────────────

def load_rates(cfg: dict) -> pd.Series | None:
    """Load external r(date) series. Returns None if unavailable."""
    root = project_root()
    r_path = root / cfg["pricing"]["r_external_series"]
    if not r_path.exists():
        logger.info("External rate file not found: %s — will use r=0", r_path)
        return None
    try:
        r_df = pd.read_csv(r_path, parse_dates=["date"])
        r_df = r_df.set_index("date")["yield"]
        logger.info("Loaded %d rate observations", len(r_df))
        return r_df
    except Exception as e:
        logger.warning("Failed loading rate file: %s", e)
        return None


def ewma_vol(returns: pd.Series, lam: float = 0.94) -> pd.Series:
    """EWMA volatility (annualized). Returns series of the same index."""
    var = pd.Series(np.nan, index=returns.index)
    valid = returns.dropna()
    if len(valid) < 2:
        return var
    # Initialize with first non-NaN squared return
    v = float(valid.iloc[0] ** 2)
    for idx, ret in valid.items():
        v = lam * v + (1 - lam) * ret**2
        var[idx] = v
    daycount = 252  # annualize from daily
    return np.sqrt(var * daycount)


def compute_realized_vol(returns: pd.Series, window: int = 30) -> pd.Series:
    """Rolling realized volatility (annualized)."""
    return returns.rolling(window).std() * np.sqrt(252)


# ──────────────────────────────────────────────────────────────────────────────
# Apply pricing to EOD data
# ──────────────────────────────────────────────────────────────────────────────

def run(cfg: dict) -> pd.DataFrame:
    """Compute IV, BS error, parity for all eligible EOD observations."""
    root = project_root()
    pdir = panels_dir(cfg)
    eod_path = pdir / "eod_enriched.parquet"
    under_path = root / cfg["paths"]["underlying_history"]
    out_path = pdir / "eod_pricing.parquet"

    if not eod_path.exists():
        logger.error("eod_enriched.parquet not found — run liquidity.py first")
        return pd.DataFrame()

    logger.info("Loading eod_enriched …")
    eod = pd.read_parquet(eod_path)
    logger.info("eod_enriched: %d rows", len(eod))

    # Load underlying history for volatility estimation
    logger.info("Loading underlying history for volatility …")
    under_eod = pd.read_csv(under_path, encoding="utf-8")
    under_eod["date"] = pd.to_datetime(under_eod["date"], format="%Y%m%d")
    under_eod = under_eod.sort_values("date").set_index("date")

    # Compute EWMA vol from daily returns
    under_eod["ret_log"] = np.log(under_eod["close"] / under_eod["close"].shift(1))
    lam = cfg["pricing"]["ewma_lambda"]
    ewma = ewma_vol(under_eod["ret_log"].dropna(), lam=lam)
    ewma.index = ewma.index.map(lambda d: d.strftime("%Y%m%d"))
    logger.info("EWMA vol computed for %d days", ewma.notna().sum())

    # Load or create risk-free rate series
    rates = load_rates(cfg)

    # Work only on daily_eligible rows
    eligible = eod[eod["daily_eligible"]].copy()
    logger.info("Daily-eligible rows: %d", len(eligible))

    if len(eligible) == 0:
        logger.warning("No eligible rows — skipping pricing")
        return pd.DataFrame()

    # Attach σ_ewma per date
    eligible["sigma_ewma"] = eligible["valuation_date"].dt.strftime("%Y%m%d").map(ewma)

    # Attach risk-free rate per date
    if rates is not None:
        eligible["r"] = eligible["valuation_date"].map(rates).fillna(0.0)
    else:
        eligible["r"] = 0.0  # default when no external rate

    # Use closing price as the option price for IV computation
    # Use `close` if non-zero, else `last`
    eligible["opt_price"] = np.where(
        eligible["close"] > 0, eligible["close"], eligible["last"]
    )

    # Use underlying close as S — from EOD history
    under_close = under_eod["close"].reset_index()
    under_close["date_str"] = under_close["date"].dt.strftime("%Y%m%d")
    under_close_map = under_close.set_index("date_str")["close"]

    eligible["S"] = eligible["valuation_date"].dt.strftime("%Y%m%d").map(under_close_map)
    eligible["K"] = pd.to_numeric(eligible["strike"], errors="coerce")

    # Compute IV
    iv_results = []
    bs_error_results = []
    parity_results = []
    iv_flags = []

    price_col = "opt_price"

    for _, row in eligible.iterrows():
        S = row.get("S", np.nan)
        K = row.get("K", np.nan)
        T = row.get("T", np.nan)
        r = row.get("r", 0.0)
        kind = row.get("option_type", "unknown")
        price = row.get(price_col, np.nan)
        sigma_ewma = row.get("sigma_ewma", np.nan)

        # IV
        if kind in ("call", "put") and all(pd.notna([S, K, T, price])) and T > 0 and price > 0:
            iv, flag = iv_from_price(price, S, K, T, r, kind, brackets=cfg["pricing"]["iv_brackets"])
        else:
            iv, flag = np.nan, "invalid_input"
        iv_results.append(iv)
        iv_flags.append(flag)

        # BS error (using EWMA vol — independent of same price)
        if kind in ("call", "put") and all(pd.notna([S, K, T, sigma_ewma])) and T > 0 and sigma_ewma > 0:
            bs = bs_price(S, K, T, r, sigma_ewma, kind)
            err = price - bs if pd.notna(price) else np.nan
        else:
            err = np.nan
        bs_error_results.append(err)

    eligible["iv"] = iv_results
    eligible["iv_flag"] = iv_flags
    eligible["bs_error"] = bs_error_results

    # Parity: need call-put pairs on the same (date, strike, maturity)
    eligible["date_str"] = eligible["valuation_date"].dt.strftime("%Y%m%d")
    calls = eligible[eligible["option_type"] == "call"].copy()
    puts = eligible[eligible["option_type"] == "put"].copy()

    pair_key = ["date_str", "strike", "maturity"]
    if len(calls) and len(puts):
        pairs = calls.merge(
            puts[pair_key + ["opt_price", "S", "K", "T", "r"]],
            on=pair_key,
            suffixes=("_call", "_put"),
        )
        pairs["parity_basis"] = pairs.apply(
            lambda row: parity_basis(
                row["opt_price_call"], row["opt_price_put"],
                row["S_call"], row["K_call"],
                row["T_call"], row["r_call"],
            ),
            axis=1,
        )
        pairs["shadow_S"] = pairs.apply(
            lambda row: shadow_price(
                row["opt_price_call"], row["opt_price_put"],
                row["K_call"], row["T_call"], row["r_call"],
            ),
            axis=1,
        )
        pairs.to_parquet(pdir / "eod_parity.parquet", index=False)
        logger.info("Parity computed for %d call-put pairs", len(pairs))
        n_pairs = len(pairs)
    else:
        n_pairs = 0

    eligible.to_parquet(out_path, index=False)
    logger.info("Wrote eod_pricing.parquet: %d rows", len(eligible))

    iv_ok = eligible["iv_flag"].value_counts().to_dict()
    save_manifest(
        cfg,
        {
            "pricing": {
                "n_eligible": len(eligible),
                "iv_flag_counts": {str(k): int(v) for k, v in iv_ok.items()},
                "n_parity_pairs": n_pairs,
                "r_source": cfg["pricing"]["r_source"],
            }
        },
    )
    return eligible


if __name__ == "__main__":
    setup_logging()
    cfg = load_config()
    run(cfg)
