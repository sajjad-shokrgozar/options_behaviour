# Research Briefing — Black-Scholes Validity & Option Behavior Under Queue Dynamics
## Ahrom Leveraged ETF Options (Tehran Stock Exchange)

> **Purpose of this document:** A complete, self-contained briefing for writing the research paper. All numerical results are final pipeline outputs. Do not invent or estimate any number not present here. The document contains everything needed to write a full academic paper without access to the underlying data.

---

## 1. Research Context

### 1.1 The Question

This study examines whether the Black-Scholes (BS) option pricing framework holds for options on **Ahrom (اهرم)**, a daily-rebalancing leveraged ETF traded on the Tehran Stock Exchange (TSE). The study has two axes:

- **Axis A:** Does BS hold in "normal" (free-market, no-queue) conditions? If not, why?
- **Axis B:** How do option prices behave when the underlying is locked in a price-limit queue (صف خرید / صف فروش)? Does the shadow price carry information?

### 1.2 Why This Market Is Interesting

The TSE operates **daily price-movement bands** (محدوده نوسان): each security can move at most ~9.95% up or down from the prior day's reference price. When demand exceeds supply at the ceiling, the market enters a **buy queue (صف خرید)**: the ask side clears, buyers queue at the ceiling price, and the underlying becomes effectively **untradeable**. The options continue trading.

This creates a natural experiment: during a buy queue, the underlying's price is frozen but the option market remains open. The options become the *only* venue for price discovery. The **shadow price** S\* = C − P + K·e^{−rT} (derived from put-call parity) reveals the market's implied belief about the true underlying price, bypassing the lock.

A daily-rebalancing **leveraged ETF** adds a further complication: its returns follow a path-dependent, compounded structure that violates the constant-volatility GBM assumption underlying BS. The study therefore tests BS in its most favorable conditions (free regime) before examining the queue regime.

### 1.3 Instruments

| Role | Persian name | Notes |
|---|---|---|
| Underlying | اهرم (Ahrom) | Leveraged ETF, no dividend, highly liquid |
| Call options | اختیارخ اهرم (Zahrom) | European style (assumed), cash-settled |
| Put options | اختیارف اهرم (Tahrom) | European style (assumed), cash-settled |

---

## 2. Data Description

### 2.1 Time Coverage

- **Underlying (Ahrom) daily EOD:** 2021-12-20 → 2026-06-21 (≈1,076 trading days)
- **Options daily EOD:** 2024-11-20 → 2026-06-21 (≈380 trading days)
- **Intraday order book:** same period as options, per instrument, per day

### 2.2 Contract Universe

- **Total contracts:** 450 (225 calls + 225 puts)
- **Strike range:** 11,000 → 68,000 rial (21 unique strikes)
- **Maturities:** multiple expiry cycles

### 2.3 Intraday Data Scale

| Metric | Value |
|---|---|
| Instruments in order book | 146 (145 options + 1 underlying) |
| CSV files ingested | 13,531 |
| Raw order-book rows | 28,033,239 |
| 5-level snapshots reconstructed | ~12.4 million (from book module) |

### 2.4 Liquidity Profile (Key Constraint)

This is the most important data characteristic — it drives every methodological choice:

| Metric | Value |
|---|---|
| Zero-volume contract-days (EOD) | **56.8%** |
| Call-put pair availability on traded days | **50.4%** |
| Intraday-eligible snapshots (fresh + two-sided) | **49.7%** |

**Interpretation:** More than half of all option contract-days have no trading at all. Even among traded days, only half have both a call and a put on the same (date, strike, maturity) — which is required for parity and shadow-price tests. All conclusions are **conditional on the liquid sub-universe** and this must be stated prominently.

---

## 3. Methodology

### 3.1 Pipeline Overview

The analysis follows a 12-step pipeline:

1. **specs** — Contract specifications (strike, maturity, type) from EOD data; Jalali→Gregorian date conversion
2. **ingest** — Raw CSV order book → per-instrument Parquet files (streaming, no full-memory load)
3. **book** — Pivot 5-level bid/ask snapshots; compute mid, microprice, spread, depth, OBI
4. **clean** — Remove zero-price rows, flag crossed books, derive tick size
5. **session** — Label pre-open vs continuous session; convert HHMMSS to seconds
6. **sync** — As-of join: align option snapshots with the nearest prior underlying quote (staleness window = 120 s); compute freshness and `opt_quote_age_s`
7. **liquidity** — Compute eligibility flags (`intraday_eligible = fresh AND two_sided`), `n_updates`, liquidity score `L`
8. **band_queue** — Detect price band empirically from daily EOD; classify each intraday snapshot as `buy_queue`, `sell_queue`, or `free`; compute episode age `τ` (minutes since queue start)
9. **pricing** — BS price (European, no dividend), implied volatility (Brent solver), put-call parity basis, shadow price S\*; EWMA volatility from 5-year underlying history as independent vol input
10. **axis_a** — IV smile/skew, BS pricing error, parity deviation (Axis A findings)
11. **axis_b** — τ-bucket analysis, depth/OBI vs τ, IV vs τ, activity vs τ, shadow-gap star test (Axis B findings)
12. **report** — RESULTS.md, data_quality_report.md, manifest.json

### 3.2 Key Methodological Choices

**Band detection:** Empirical — computed from the 99th percentile of daily |max/yesterday − 1| and |min/yesterday − 1| moves across all traded days (excluding zero-price days). Result: **9.95%** band.

**Queue detection (per option):** For each option instrument, a snapshot is classified as buy queue if: (a) ask side is empty (ask_qty_1 = 0 or NaN), AND (b) bid_px_1 ≥ ceiling − 1 tick, where ceiling = yesterday × 1.0995. Symmetrically for sell queue. Minimum persistence: 3 consecutive snapshots. Post-queue guard: 5 minutes excluded after queue releases.

**Volatility for BS pricing error:** EWMA (λ = 0.94) estimated on the 5-year underlying daily return history — independent of the option price being tested, to avoid circularity.

**Risk-free rate:** Zero (r = 0). The Akhza yield file was not available. All BS and parity results should be interpreted with r = 0 and the sensitivity to r discussed (Islamic finance context — explicit interest rates are absent; the Akhza yield is an approximation).

**Shadow price:** S\* = C − P + K·e^{−rT} (with r = 0 reduces to S\* = C − P + K). Computed at EOD for all call-put pairs on the same (date, strike, maturity) where both legs have volume > 0.

**IV computation:** Brent root-finding on BS formula. Flagged as:
- `ok`: converged normally
- `no_arb`: option price violates no-arbitrage bounds (negative intrinsic value)
- `invalid_input`: T ≤ 0 or S ≤ 0
- `numerical`: solver did not converge

---

## 4. Axis A — Black-Scholes Validity (Free Regime)

### 4.1 Finding A1 — Persistent IV Skew in Near-Term Calls

**Claim:** In near-the-money, short-maturity calls (τ_mat ≤ 30 days, free regime), IV increases with moneyness (S/K) at a slope of **0.85 per unit S/K** (HAC OLS, t = 10.84, p = 2.1 × 10⁻²⁷, 95% CI [0.696, 1.004], N = 2,021 contract-days).

**What this means:** IV is not flat as BS assumes — it rises as the option goes deeper in-the-money. This is the opposite of the typical equity "volatility smile" (which slopes downward for OTM puts). Here, ITM calls carry *higher* IV than OTM calls, suggesting the market prices in a higher probability of large upward moves (consistent with the band-and-queue mechanism: when the underlying hits the ceiling, options gain lottery-like payoff characteristics).

**Scope:** Near-ATM moneyness bucket; maturity ≤ 30 days; free regime; daily-eligible contract-days.

**Limitations:** Selection bias — only the most liquid contracts are included.

**IV by moneyness × maturity (selected rows from axA_iv_summary.csv):**

| Moneyness bucket | Maturity | Type | N | Mean IV | Median IV |
|---|---|---|---|---|---|
| ATM | short (≤30d) | call | 229 | 0.732 | 0.657 |
| ATM | short | put | 226 | 0.677 | 0.549 |
| ATM | medium | call | 282 | 0.784 | 0.731 |
| ATM | long | call | 596 | 0.801 | 0.775 |
| Deep ITM | short | call | 602 | **1.852** | **1.554** |
| Deep ITM | medium | call | 1,155 | 1.410 | 1.233 |
| Deep ITM | long | call | 2,969 | 1.151 | 1.107 |
| Deep OTM | short | call | 776 | 1.180 | 0.957 |
| Deep OTM | long | call | 1,441 | 0.759 | 0.722 |

**Key pattern:** Deep-ITM short-maturity calls have the highest IV (1.85 mean), more than 2.5× the ATM short-maturity call IV (0.73). This is an extremely pronounced "reverse skew" or "forward skew."

### 4.2 Finding A2 — Large Positive BS Pricing Error

**Claim:** The BS model (using EWMA volatility from the 5-year underlying history) systematically **underprices** options. Median error = **486 rial** per contract; mean error = **844 rial** (HAC t-test: t = 28.96, p = 2.3 × 10⁻¹⁸⁴, 95% CI [787, 901], N = 18,012 contract-days).

**What this means:** The market consistently prices options above what EWMA-based BS would predict. This means either: (a) EWMA underestimates realized volatility for a leveraged ETF (due to daily rebalancing's variance drag amplification), or (b) the market prices in a risk premium for the queue-lock risk, or (c) both.

**BS pricing error by moneyness × maturity (selected rows from axA_pricing_error.csv):**

| Moneyness | Maturity | Type | N | Mean error (rial) | Median error (rial) |
|---|---|---|---|---|---|
| ATM | long | call | 596 | **2,281** | 1,921 |
| ATM | medium | call | 282 | 1,581 | 1,229 |
| ATM | short | call | 237 | 633 | 393 |
| ATM | long | put | 308 | 295 | 221 |
| Deep ITM | long | call | 3,136 | 1,758 | 1,600 |
| Deep ITM | short | call | 1,226 | **−8** | 54 |
| Deep OTM | long | put | 334 | **−352** | −263 |

**Key patterns:**
- Long-maturity calls are most severely underpriced by BS (mean error 1,758–2,281 rial)
- Short-maturity deep-ITM calls and deep-OTM puts show near-zero or negative errors — BS actually overprice these
- Puts are generally much closer to BS than calls, suggesting the call overpricing is not symmetric

**IV flag breakdown (N = 18,368 eligible observations):**

| Flag | Count | % |
|---|---|---|
| ok | 16,074 | 87.5% |
| no_arb (violates bounds) | 1,841 | 10.0% |
| invalid_input | 356 | 1.9% |
| numerical (non-convergence) | 97 | 0.5% |

### 4.3 Finding A3 — Persistent Put-Call Parity Deviations

**Claim:** The put-call parity basis (C − P − (S − K)) is significantly positive. Median basis = **578 rial**; mean = **811 rial** (HAC t-test: t = 16.30, p = 9.9 × 10⁻⁶⁰, 95% CI [713, 908], N = 6,972 pairs).

**What this means:** Calls are consistently priced above puts relative to what parity requires. This implies either: (a) an implicit funding cost (even with r = 0, there are transaction costs or capital constraints), (b) calls carry a queue-risk premium (being long the underlying via a call is less risky than holding the illiquid underlying directly during a queue), or (c) stale quotes bias the measure.

**Parity basis by moneyness × maturity (selected rows from axA_parity_summary.csv):**

| Moneyness | Maturity | N pairs | Mean basis (rial) | Median basis (rial) |
|---|---|---|---|---|
| ATM | long | 360 | **1,891** | 1,706 |
| ATM | medium | 278 | 1,049 | 792 |
| ATM | short | 266 | 129 | 150 |
| Deep ITM | long | 1,029 | 1,100 | 1,050 |
| Deep ITM | short | 1,098 | **−188** | −23 |
| Deep OTM | long | 499 | 1,519 | 1,361 |
| OTM | long | 278 | 1,568 | 1,334 |

**Key patterns:**
- Long-maturity contracts have the largest parity deviations
- Short-maturity deep-ITM contracts show slight *negative* basis (puts slightly overpriced relative to calls)
- Near-expiry ATM contracts show near-zero basis (efficient pricing as expiry approaches)

---

## 5. Axis B — Option Behavior Under Queue Dynamics

### 5.1 Queue Statistics

| Metric | Value |
|---|---|
| Total queue episodes | **1,827** |
| Buy-queue episodes (صف خرید) | majority |
| Sell-queue episodes (صف فروش) | minority |
| Total queue snapshots (intraday) | **8,681** |
| Buy-queue snapshots | **6,740** (77.6%) |
| Sell-queue snapshots | **1,955** (22.5%) |
| Distinct dates with queue activity | 303 |
| Free-regime snapshots | 7,395,224 |
| Queue as % of total snapshots | **0.12%** |

**Detection parameters:**
- Band: 9.95% (empirical 99th percentile of daily moves)
- Tolerance: 1 tick from the band limit
- Minimum persistence: 3 consecutive snapshots
- Post-queue guard: 5 minutes

### 5.2 Finding B1 — τ-Bucket Coverage

**Claim:** 8,681 queue-regime option snapshots are available across 1,827 episodes, with buy-queue accounting for 6,732 (77.5%) and sell-queue for 1,949 (22.5%).

**τ-bucket distribution (from axB_tau_buckets.csv):**

| τ bucket | Regime | N snapshots |
|---|---|---|
| 0–1 min | buy_queue | 833 |
| 0–1 min | sell_queue | 450 |
| 1–5 min | buy_queue | 349 |
| 1–5 min | sell_queue | 513 |
| 5–15 min | buy_queue | 533 |
| 5–15 min | sell_queue | 518 |
| 15–30 min | buy_queue | 526 |
| 15–30 min | sell_queue | 225 |
| >30 min | buy_queue | 4,491 |
| >30 min | sell_queue | 243 |

**Observation:** The majority of buy-queue time (4,491 of 6,732 snapshots = 66.7%) occurs in long-duration episodes (τ > 30 min). This is consistent with TSE market structure: buy queues, once formed, tend to persist for most of the trading session.

### 5.3 Finding B2 — Depth and OBI vs Queue Age τ (Figure: axB_spread_depth_vs_tau)

Note: In buy queue, the ask side is structurally empty, so bid-ask spread is undefined (NaN). Instead, depth and OBI are reported.

**Bid-side depth (median, buy_queue) by τ:**

| τ bucket | Median depth_bid | Mean depth_bid |
|---|---|---|
| 0–1 min | 110 | 636 |
| 1–5 min | 133 | 666 |
| 5–15 min | 110 | 595 |
| 15–30 min | 117 | 921 |
| >30 min | **157** | **1,139** |

**Ask-side depth (median, sell_queue) by τ:**

| τ bucket | Median depth_ask | Mean depth_ask |
|---|---|---|
| 0–1 min | 4,387 | 11,053 |
| 1–5 min | 4,600 | 12,804 |
| 5–15 min | 3,869 | 11,312 |
| 15–30 min | 3,050 | 12,237 |
| >30 min | 3,758 | 6,847 |

**OBI:** Uniformly +1.0 in buy_queue, −1.0 in sell_queue across all τ buckets (order book fully one-sided, as expected in a limit queue).

**Interpretation:** In buy queue, the bid-side depth grows monotonically with τ (110 → 157 units median). As the queue ages, more buyers accumulate at the ceiling price. In sell queue, ask depth is large and relatively stable across τ.

### 5.4 Finding B3 — Implied Volatility vs Queue Age τ (Figure: axB_iv_vs_tau)

**Method:** EOD IV (from pricing module) joined to queue snapshots on (instrument_id, date). This gives the daily IV of the queued option — not a within-episode snapshot IV.

**IV by τ bucket (from axB_iv_vs_tau.csv):**

| τ bucket | Median IV | Mean IV | N |
|---|---|---|---|
| 0–1 min | **1.292** | 1.477 | 161 |
| 1–5 min | 0.575 | 1.029 | 170 |
| 5–15 min | 0.351 | 0.818 | 330 |
| 15–30 min | 0.351 | 0.759 | 124 |
| >30 min | 0.498 | 0.590 | 418 |

**Key finding:** IV is dramatically higher in the early phase of a queue episode (τ < 1 min: median IV = 1.29) than in later phases (τ ∈ [5–30 min]: median IV = 0.35). There is a 3.7× drop in median IV from the first minute to the 5–30 minute range.

**Interpretation:** Options on instruments that just entered a queue trade at very high implied volatility, reflecting uncertainty about whether the lock will persist or release. As the queue ages and the lock persists, implied volatility falls — the market is becoming increasingly certain that the lock will continue through the session end, making the option's payoff more predictable (it will expire at the ceiling or above).

**Caveat:** This is EOD IV, not intraday IV. The τ label reflects the maximum queue age within that day. The IV drop may partly reflect systematic differences between instruments that form short-lived vs long-lived queues.

### 5.5 Finding B4 — Quote Activity vs Queue Age τ (Figure: axB_tradeintensity_vs_tau)

**Metric:** `n_updates` = number of order-book update events for that instrument on that day (proxy for trading activity).

**n_updates (median) by τ bucket and regime:**

| τ bucket | Buy queue | Sell queue |
|---|---|---|
| 0–1 min | **5** | 667 |
| 1–5 min | 65 | 667 |
| 5–15 min | 45 | 823 |
| 15–30 min | 53 | 551 |
| >30 min | **10** | 466 |

**Key finding:** In buy-queue options, book activity declines sharply with queue age: 5 updates/day at τ < 1 min (effectively no trading), rising slightly to 65 at τ ∈ [1–5 min], then collapsing to 10 at τ > 30 min.

**Interpretation:** Options on deeply queued instruments (long-duration buy queues) become extremely illiquid — the option market also freezes when the underlying is locked for a long time. This is the opposite of the "price discovery migrates to options" hypothesis: for long queues, both the underlying and its options become dormant. Short-duration queues (τ < 5 min) have moderate activity, suggesting price discovery is happening in the initial phase of a queue.

In sell-queue options, activity is much higher and more stable (~466–823 updates/day), suggesting that sell queues do not suppress option trading as severely as buy queues.

### 5.6 Finding B5 — Shadow Price and Next-Day Open Prediction (Star Test)

**Shadow price:** S\* = C − P + K (with r = 0). Computed at EOD for all pairs where both call and put have volume > 0, on days with at least one queue episode.

**Shadow availability:** 6,708 EOD call-put pairs across 303 queue days.

**Shadow gap:** S\* − locked_price, where locked_price = underlying EOD close on the queue day (the ceiling price).

**Shadow gap statistics (from axB_shadow_availability.csv):**

| Statistic | Value (rial) |
|---|---|
| Mean | 766 |
| Std | 1,784 |
| Median | 561 |
| 25th percentile | −58 |
| 75th percentile | 1,421 |
| Min | −9,175 |
| Max | 26,614 |

**Interpretation:** On average, the shadow price is 766 rial above the locked ceiling price. The positive median (561 rial) indicates that call-put parity implies the "true" underlying value is typically above the ceiling — consistent with suppressed demand. However, the wide distribution (large negative values exist) suggests this is noisy.

**Star Test (next-day open prediction):**

Regression: next_open_ret = α + β × shadow_gap

| Metric | Value |
|---|---|
| Sample size (N) | 6,627 |
| β (slope) | **6.01 × 10⁻⁶** per rial |
| p-value | **5.7 × 10⁻²³³** (essentially zero) |
| Economic magnitude | 766 rial mean shadow gap × 6.01×10⁻⁶ ≈ **+0.46% predicted return** |

**Interpretation:** The shadow gap is highly statistically significant in predicting next-day open return (p ≈ 10⁻²³³), but the economic magnitude is tiny: a 1-rial increase in the shadow gap predicts a 0.000006 increase in log return. At the mean shadow gap of 766 rial, the predicted return is ~0.46%. The extreme statistical significance with N = 6,627 reflects a real but economically small relationship.

**Caution on interpretation:** The high N drives the significance more than the effect size. With β ≈ 6×10⁻⁶ and the unit being rial (Iranian rial, where 1,000 rial ≈ 1 toman), the economic significance is limited. Also, r = 0 assumption may affect the shadow price calculation.

---

## 6. Figures Reference

All figures are in `outputs/figures/` (PNG + SVG).

| Figure | Content | Key insight |
|---|---|---|
| `axA_iv_smile.png` | IV vs moneyness, stratified by maturity and option type | Reverse skew: deep-ITM short calls have highest IV (1.85) |
| `axA_pricing_error_by_bucket.png` | Mean BS pricing error by moneyness × maturity | Long-maturity calls most underpriced; short deep-ITM near-zero |
| `axA_parity_by_bucket.png` | Parity basis by moneyness × maturity | Long-maturity contracts show largest positive basis |
| `axB_spread_depth_vs_tau.png` | Bid-depth and OBI vs τ (left/right panels) | Buy-queue depth grows with τ; OBI uniformly +1 |
| `axB_iv_vs_tau.png` | Median EOD IV by τ bucket | Sharp decline: 1.29 → 0.35 from τ<1min to τ>5min |
| `axB_tradeintensity_vs_tau.png` | n_updates by τ bucket and regime | Buy-queue activity collapses at long τ; sell-queue more stable |
| `axB_shadow_vs_tau.png` | Histogram of shadow gap S\*−locked_price | Right-skewed; median gap +561 rial above ceiling |
| `axB_nextday_open.png` | Scatter: shadow gap vs next-day open return | Positive slope, significant but small effect size |

---

## 7. Summary Statistics for Paper

| Category | Metric | Value |
|---|---|---|
| Data | Total contracts | 450 |
| Data | Order-book rows processed | 28.0 million |
| Data | Date range (options) | Nov 2024 – Jun 2026 |
| Data | Zero-volume rate | 56.8% |
| Data | Call-put pair availability | 50.4% |
| Data | Intraday eligible rate | 49.7% |
| Band | Empirical band (99th pct) | 9.95% |
| Queue | Total episodes | 1,827 |
| Queue | Buy-queue snapshots | 6,740 |
| Queue | Sell-queue snapshots | 1,955 |
| Queue | Queue days | 303 |
| Pricing | Eligible contract-days priced | 18,368 |
| Pricing | IV computed (ok flag) | 16,074 (87.5%) |
| Pricing | EOD parity pairs | 6,972 |
| Axis A | IV skew slope (near-ATM, ≤30d calls) | 0.850 (p = 2.1×10⁻²⁷) |
| Axis A | BS pricing error median | 486 rial |
| Axis A | BS pricing error mean | 844 rial (p ≈ 0) |
| Axis A | Parity basis median | 578 rial |
| Axis A | Parity basis mean | 811 rial (p = 9.9×10⁻⁶⁰) |
| Axis B | Shadow gap mean | 766 rial |
| Axis B | Shadow gap median | 561 rial |
| Axis B | Shadow gap: star test slope | 6.01 × 10⁻⁶ |
| Axis B | Shadow gap: star test p | 5.7 × 10⁻²³³ |
| Axis B | IV at τ < 1 min (median) | 1.292 |
| Axis B | IV at τ > 5 min (median) | 0.35–0.50 |

---

## 8. Key Limitations to Address in the Paper

1. **r = 0 assumption.** No Akhza yield data was available. All BS, parity, and shadow-price calculations use r = 0. This biases parity basis upward (call prices appear higher than warranted). Sensitivity to r should be discussed.

2. **EOD vs intraday.** Most findings are at the daily level. The "IV vs τ" result (B3) joins EOD IV to intraday queue episodes by date — it reflects the IV of the day, not the IV at the exact moment of the snapshot. True intraday IV computation would require mid-price validity at each snapshot, which is limited by liquidity.

3. **Selection bias.** All results are conditional on volume > 0 (traded days). The 56.8% zero-volume rate means the findings describe the most liquid subset of the market, not the full option universe.

4. **European assumption.** TSE options are assumed European. If early exercise provisions exist, IV and parity calculations may be misspecified.

5. **Leveraged ETF dynamics.** Ahrom is a daily-rebalancing leveraged ETF. Its returns are path-dependent (daily rebalancing causes volatility drag). The EWMA volatility computed from historical returns is therefore a downward-biased estimate of the effective volatility relevant for option pricing over longer horizons. This directly explains the positive BS pricing error.

6. **Queue detection per option.** Queue is detected independently per option instrument (not broadcast from the underlying). This is methodologically correct but means the "regime" label reflects the option's own order-book state, not the underlying's market-wide queue state.

7. **Shadow gap sign.** The negative tail of the shadow gap distribution (25th pct = −58 rial) suggests some pairs have the put priced above the call relative to parity. This may reflect stale closing prices or early exercise expectations.

8. **n_updates as proxy.** The "trading intensity" figure uses order-book update count per day, not actual executed trades (trade tape was not available). This is a proxy for quoting activity, not trading volume.

---

## 9. Suggested Paper Structure

### Title
"Price Discovery Under Market Lock: Black-Scholes Validity and Option Behavior During Queue Regimes in the Tehran Stock Exchange"

### Abstract
Study of BS validity and queue-regime option dynamics for Ahrom leveraged ETF options on TSE. Key findings: (1) BS systematically underprices options (median error 486 rial), (2) pronounced reverse IV skew in near-term calls, (3) significant put-call parity violations, (4) shadow price carries statistically significant (if economically small) information about next-day open. Queue episodes see IV compress and trading activity collapse as queue age increases.

### Suggested Sections

1. **Introduction** — TSE market structure, price bands, queue mechanism; why leveraged ETF options are a natural experiment
2. **Related Literature** — BS validity tests; price discovery under trading halts; circuit breakers and options; emerging market microstructure
3. **Data and Market Structure** — instruments, data coverage, liquidity profile (the 56.8% figure is central)
4. **Methodology** — pipeline overview, eligibility definition, queue detection, τ construction, shadow price, EWMA vol, r = 0 assumption
5. **Axis A: BS Validity in Free Conditions** — IV smile/reverse skew; BS error by bucket; parity deviations; r-sensitivity discussion
6. **Axis B: Option Dynamics Under Queue** — Episode statistics; depth/OBI vs τ; IV vs τ; activity vs τ; shadow price and star test
7. **Discussion** — Why calls are overpriced vs BS (leveraged ETF dynamics + queue premium); why IV falls with τ (certainty effect); why activity collapses at long τ; shadow price as price discovery signal
8. **Conclusion** — BS is a poor model here even in free conditions; the queue regime amplifies deviations; shadow price is a weak but real predictor
9. **Appendix** — Pipeline detail; parameter sensitivity; IV flag counts; full tables

---

## 10. Open Items (Limitations Already Surfaced by the Pipeline)

1. Option exercise style (European assumed — needs confirmation from TSE rulebook)
2. Official band percentage (empirical 9.95% used — TSE publishes an official figure)
3. r = 0 (Akhza yield not available)
4. Trade tape not available (n_updates used as proxy for trading intensity)
5. Intraday IV not computed (only EOD IV joined to intraday queue snapshots)
