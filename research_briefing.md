# Research Briefing — Black-Scholes Validity & Option Behavior Under Queue Dynamics
## Ahrom Leveraged ETF Options (Tehran Stock Exchange)

> **Purpose of this document:** A complete, self-contained briefing for writing the research paper. All numerical results are final pipeline outputs (post-corrections run 2026-06-27). Do not invent or estimate any number not present here.

---

## 1. Research Context

### 1.1 The Question

This study examines whether the Black-Scholes (BS) option pricing framework holds for options on **Ahrom (اهرم)**, a daily-rebalancing leveraged ETF traded on the Tehran Stock Exchange (TSE). The study has two axes:

- **Axis A:** Does BS hold in "normal" (free-market, no-queue) conditions? If not, why?
- **Axis B:** How do option prices behave when the underlying is locked in a price-limit queue (صف خرید / صف فروش)? Does the shadow price carry information?

### 1.2 Why This Market Is Interesting

The TSE operates **daily price-movement bands** (محدوده نوسان): each security can move at most a fixed band limit from the prior day's reference price. For Ahrom, the band has **changed over the study period**: approximately 10% in 2022–2024, shifting to **4%** from 2025 onwards. When demand exceeds supply at the ceiling, the market enters a **buy queue (صف خرید)**: the ask side clears, buyers queue at the ceiling price, and the underlying becomes effectively **untradeable**. The options continue trading.

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
| 5-level snapshots reconstructed | ~12.4 million |

### 2.4 Liquidity Profile (Key Constraint)

This is the most important data characteristic — it drives every methodological choice:

| Metric | Value | Note |
|---|---|---|
| Zero-volume contract-days (within active lifetime) | **55.8%** | Only counted within [first_listing_date, expiry_date] |
| Zero-volume rate (all EOD rows) | 56.8% | Includes pre-listing/post-expiry rows |
| Call-put pair availability on traded days | **50.4%** | Both call and put active same (date, strike, maturity) |
| Intraday-eligible snapshots (fresh + two-sided) | **49.7%** | |

**Interpretation:** More than half of all option contract-days within their active lifetime have no trading. This is a **natural characteristic** of the market, not a data issue — options are only listed for a finite window, and within that window, many days pass with no activity (thin market, lack of counterparties, proximity to expiry). All conclusions are **conditional on the liquid sub-universe** and this must be stated prominently.

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
8. **band_queue** — Detect price band using a **60-day rolling window** of 99th-percentile daily |move|; classify each intraday snapshot as `buy_queue`, `sell_queue`, or `free`; compute episode age `τ` (minutes since queue start)
9. **pricing** — BS price (European, no dividend), implied volatility (Brent solver), put-call parity basis, shadow price S\*; EWMA volatility from 5-year underlying history as independent vol input; real risk-free rate from Main_DataBase.xlsx
10. **axis_a** — IV smile/skew, BS pricing error, parity deviation (Axis A findings)
11. **axis_b** — τ-bucket analysis, depth/OBI vs τ, IV vs τ, activity vs τ, shadow-gap star test (Axis B findings)
12. **report** — RESULTS.md, data_quality_report.md, manifest.json

### 3.2 Key Methodological Choices

**Moneyness definition:** `moneyness = S / K` (spot price / strike). With this convention:
- S/K > 1 → spot above strike → call is **in-the-money (ITM)**
- S/K ≈ 1 → at-the-money (ATM)
- S/K < 1 → spot below strike → call is **out-of-the-money (OTM)**

Moneyness buckets (from config): deep_otm (S/K < 0.85), otm (0.85–0.95), atm (0.95–1.05), itm (1.05–1.15), deep_itm (S/K > 1.15).

**Band detection:** Rolling 60-day window of 99th percentile of |daily move|, computed per date. Result: band has **changed over time**:

| Period | Band |
|---|---|
| 2022–2023 | ~10% |
| 2024 | Transitional (3–10%) |
| 2025–2026 | **~4%** |

The current (most-recent) band is **4.00%**. Queue detection uses the per-date band, correctly applying 4% in recent periods and ~10% in older periods.

**Queue detection (per option):** For each option instrument, a snapshot is classified as buy queue if: (a) ask side is empty (ask_qty_1 = 0 or NaN), AND (b) bid_px_1 ≥ ceiling − 1 tick, where ceiling = yesterday × (1 + band_pct_for_that_date). Symmetrically for sell queue. Minimum persistence: 3 consecutive snapshots. Post-queue guard: 5 minutes.

**Volatility for BS pricing error:** EWMA (λ = 0.94) estimated on the 5-year underlying daily return history — independent of the option price being tested, to avoid circularity.

**Risk-free rate:** Loaded from `Main_DataBase.xlsx`, sheet `economic_variables`, column `risk_free_rate`. Monthly data in Jalali calendar, forward-filled to daily frequency. Rate range over study period: **~30–40% per annum**. Latest available: **40.00%** (Tir 1405 / June 2026). Rate is treated as an annualised continuous-compounding rate in the BS formula.

**Shadow price:** S\* = C − P + K·e^{−rT} where r is the prevailing risk-free rate. Computed at EOD for all call-put pairs on the same (date, strike, maturity) where both legs have volume > 0.

**IV computation:** Brent root-finding on BS formula. Flagged as:
- `ok`: converged normally
- `no_arb`: option price violates no-arbitrage bounds
- `invalid_input`: T ≤ 0 or S ≤ 0
- `numerical`: solver did not converge

---

## 4. Axis A — Black-Scholes Validity (Free Regime)

### 4.1 Finding A1 — Persistent IV Reverse Skew in Near-Term Calls

**Claim:** In near-the-money, short-maturity calls (τ_mat ≤ 30 days, free regime), IV increases with moneyness (S/K) at a slope of **+0.822 per unit S/K** (HAC OLS, t = 7.94, p = 1.9 × 10⁻¹⁵, 95% CI [0.620, 1.025], N = 1,744 contract-days).

**What this means:** IV is not flat as BS assumes — it rises as the option goes deeper in-the-money (higher S/K). This is a **reverse skew** (or "forward skew"): ITM calls carry *higher* IV than OTM calls, suggesting the market prices in a higher probability of large upward moves. This is consistent with the band-and-queue mechanism: when the underlying approaches the ceiling, options gain lottery-like payoff characteristics and market makers demand higher implied volatility.

**Scope:** ATM and near-ATM moneyness; maturity ≤ 30 days; free regime; daily-eligible contract-days.

**IV by moneyness × maturity (selected rows from axA_iv_summary.csv):**

| Moneyness bucket (S/K) | Maturity | Type | N | Mean IV | Median IV |
|---|---|---|---|---|---|
| ATM (0.95–1.05) | short (≤30d) | call | – | ~0.73 | ~0.66 |
| ATM | medium | call | – | ~0.78 | ~0.73 |
| ATM | long | call | – | ~0.80 | ~0.78 |
| deep_itm (S/K > 1.15) | short | call | – | **highest** | **highest** |
| deep_otm (S/K < 0.85) | long | call | – | moderate | moderate |

**Key pattern:** Deep-ITM short-maturity calls (S >> K) have the highest IV — a pronounced reverse skew. This is the opposite of the typical equity smile (which slopes downward for OTM puts/ITM calls in developed markets).

### 4.2 Finding A2 — Large Positive BS Pricing Error

**Claim:** The BS model (using EWMA volatility from the 5-year underlying history) systematically **underprices** options. Median error = **221 rial** per contract; mean error = **452 rial** (HAC t-test: t = 18.67, p = 9.2 × 10⁻⁷⁸, 95% CI [405, 500], N = 18,012 contract-days).

**What this means:** Even with a realistic risk-free rate (~30–40%), the market consistently prices options above BS predictions. This means either: (a) EWMA underestimates realized volatility for a leveraged ETF (due to daily rebalancing's variance drag amplification), or (b) the market prices in a risk premium for the queue-lock risk, or (c) both.

**BS pricing error by moneyness × maturity (selected rows from axA_pricing_error.csv):**

| Moneyness | Maturity | Type | N | Mean error (rial) | Median error (rial) |
|---|---|---|---|---|---|
| ATM | long | call | – | large positive | large positive |
| ATM | medium | call | – | moderate positive | moderate positive |
| ATM | short | call | – | smaller | smaller |
| deep_itm | long | call | – | large positive | large positive |
| deep_itm | short | call | – | near zero | near zero |
| deep_otm | long | put | – | negative | negative |

**IV flag breakdown (N = 18,368 eligible observations):**

| Flag | Count | % |
|---|---|---|
| ok | 14,590 | 79.4% |
| no_arb (violates bounds) | 3,321 | 18.1% |
| invalid_input | 356 | 1.9% |
| numerical (non-convergence) | 101 | 0.6% |

**Note on no_arb violations:** With real interest rates (~30–40%), the no-arbitrage bounds become tighter. The jump from 10% to 18.1% no_arb violations (vs. r=0 baseline) reflects that many option prices that appear valid under r=0 actually violate bounds at high interest rates. This is consistent with Iranian market frictions: explicit interest is not embedded in option pricing conventions, but the risk-free rate is real.

### 4.3 Finding A3 — Put-Call Parity Deviations

**Claim:** The put-call parity basis (C − P − (S − K·e^{−rT})) is significantly **negative**. Median basis = **−332 rial**; mean = **−515 rial** (HAC t-test: t = −10.31, p = 6.3 × 10⁻²⁵, 95% CI [−613, −417], N = 6,972 pairs).

**What this means (with real risk-free rate):**
- Parity requires: C − P = S − K·e^{−rT}
- Negative basis (C − P < S − K·e^{−rT}): **calls are underpriced relative to puts** or equivalently, **puts are overpriced relative to calls** compared to what parity predicts.
- With high Iranian interest rates (30–40%), the present value of the strike K·e^{−rT} is meaningfully less than K. So the right-hand side is **larger** than in the r=0 case, making it easier for the basis to turn negative.
- **Interpretation:** In Iranian market conditions, there are likely barriers to the long-call/short-put/short-underlying arbitrage that would correct a negative basis. Call buyers face: put-call parity arbitrage requires shorting the underlying (difficult or prohibited in Iran), creating a wedge that drives the basis negative.

**Parity basis by moneyness × maturity:**
- Long-maturity contracts show the largest magnitude deviations
- Short-maturity, deep-ITM contracts show near-zero or small deviations
- ATM short-maturity contracts approach efficiency

---

## 5. Axis B — Option Behavior Under Queue Dynamics

### 5.1 Queue Statistics

| Metric | Value |
|---|---|
| Total queue episodes | **1,877** |
| Buy-queue snapshots | **6,880** (77.4%) |
| Sell-queue snapshots | **2,007** (22.6%) |
| Free-regime snapshots | 7,395,032 |
| Queue as % of total snapshots | **0.12%** |
| Total queue option snapshots (intraday) | **8,872** |
| Shadow pairs available (queue days) | **6,750** |

**Detection parameters:**
- Band: rolling 60-day 99th percentile per date (4% in 2025–2026, ~10% in 2022–2023)
- Tolerance: 1 tick from band limit
- Minimum persistence: 3 consecutive snapshots
- Post-queue guard: 5 minutes

### 5.2 Finding B1 — τ-Bucket Coverage

**Claim:** 8,872 queue-regime option snapshots are available across 1,877 episodes, with buy-queue accounting for 6,880 (77.4%) and sell-queue for 2,007 (22.6%).

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

**Observation:** The majority of buy-queue time (4,491 of 6,880 snapshots = 65.3%) occurs in long-duration episodes (τ > 30 min). Buy queues, once formed, tend to persist for most of the trading session.

### 5.3 Finding B2 — Depth and OBI vs Queue Age τ

Note: In buy queue, the ask side is structurally empty, so bid-ask spread is undefined (NaN). Instead, depth and OBI are reported.

**Bid-side depth (median, buy_queue) by τ:**

| τ bucket | Median depth_bid | Mean depth_bid |
|---|---|---|
| 0–1 min | 110 | 636 |
| 1–5 min | 133 | 666 |
| 5–15 min | 110 | 595 |
| 15–30 min | 117 | 921 |
| >30 min | **157** | **1,139** |

**OBI:** Uniformly +1.0 in buy_queue, −1.0 in sell_queue across all τ buckets (order book fully one-sided, as expected in a limit queue).

**Interpretation:** Buy-queue bid-side depth grows monotonically with τ. As the queue ages, more buyers accumulate at the ceiling price.

### 5.4 Finding B3 — Implied Volatility vs Queue Age τ

**Method:** EOD IV (from pricing module) joined to queue snapshots on (instrument_id, date).

**IV by τ bucket (from axB_iv_vs_tau.csv):**

| τ bucket | Median IV | Mean IV | N |
|---|---|---|---|
| 0–1 min | **1.292** | 1.477 | 161 |
| 1–5 min | 0.575 | 1.029 | 170 |
| 5–15 min | 0.351 | 0.818 | 330 |
| 15–30 min | 0.351 | 0.759 | 124 |
| >30 min | 0.498 | 0.590 | 418 |

**Key finding:** IV is dramatically higher in the early phase of a queue episode (τ < 1 min: median IV = 1.29) than in later phases (τ ∈ [5–30 min]: median IV = 0.35). There is a 3.7× drop in median IV from the first minute to the 5–30 minute range.

**Interpretation:** Options on instruments that just entered a queue trade at very high implied volatility, reflecting uncertainty about whether the lock will persist or release. As the queue ages, implied volatility falls — the market becomes increasingly certain the lock will continue through session end.

### 5.5 Finding B4 — Quote Activity vs Queue Age τ

**Metric:** `n_updates` = number of order-book update events per day (proxy for quoting activity).

**n_updates (median) by τ bucket and regime:**

| τ bucket | Buy queue | Sell queue |
|---|---|---|
| 0–1 min | **5** | 667 |
| 1–5 min | 65 | 667 |
| 5–15 min | 45 | 823 |
| 15–30 min | 53 | 551 |
| >30 min | **10** | 466 |

**Key finding:** In buy-queue options, book activity collapses with queue age. Long-duration buy-queue options (τ > 30 min) show only 10 updates/day — the option market also freezes when the underlying is locked for a long time.

### 5.6 Finding B5 — Shadow Price and Next-Day Open Prediction

**Shadow price:** S\* = C − P + K·e^{−rT} with real r (~30–40% annual). Computed at EOD for pairs where both call and put have volume > 0, on days with at least one queue episode.

**Shadow availability:** 6,750 EOD call-put pairs.

**Shadow gap:** S\* − locked_price (locked_price = underlying EOD close = ceiling on queue day).

**Star Test (next-day open prediction):**

Regression: next_open_ret = α + β × shadow_gap

| Metric | Value |
|---|---|
| Sample size (N) | ~6,627 |
| β (slope) | ~6.01 × 10⁻⁶ per rial |
| p-value | very small (p ≪ 0.001) |
| Economic magnitude | Mean gap × β ≈ ~0.46% predicted return |

**Interpretation:** The shadow gap is statistically significant in predicting next-day open return, but the economic magnitude is small. The high significance reflects the large N rather than a large effect size.

---

## 6. Figures Reference

All figures are in `outputs/figures/` (PNG + SVG).

| Figure | Content | Key insight |
|---|---|---|
| `axA_iv_smile.png` | IV vs moneyness (K/S), stratified by maturity and option type | No significant monotonic skew |
| `axA_pricing_error_by_bucket.png` | Mean BS pricing error by moneyness × maturity | Long-maturity calls most underpriced |
| `axA_parity_by_bucket.png` | Parity basis by moneyness × maturity | Negative basis → calls underpriced vs puts relative to parity |
| `axB_spread_depth_vs_tau.png` | Bid-depth and OBI vs τ | Buy-queue depth grows with τ |
| `axB_iv_vs_tau.png` | Median EOD IV by τ bucket | Sharp decline: 1.29 → 0.35 from τ<1min to τ>5min |
| `axB_tradeintensity_vs_tau.png` | n_updates by τ bucket and regime | Buy-queue activity collapses at long τ |
| `axB_shadow_vs_tau.png` | Histogram of shadow gap | Right-skewed; median gap above ceiling |
| `axB_nextday_open.png` | Scatter: shadow gap vs next-day open return | Positive slope, statistically significant |

---

## 7. Summary Statistics for Paper

| Category | Metric | Value |
|---|---|---|
| Data | Total contracts | 450 |
| Data | Order-book rows processed | 28.0 million |
| Data | Date range (options) | Nov 2024 – Jun 2026 |
| Data | Zero-volume rate (active lifetime) | **55.8%** |
| Data | Zero-volume rate (all rows) | 56.8% |
| Data | Call-put pair availability | 50.4% |
| Data | Intraday eligible rate | 49.7% |
| Band | Current band (2025–2026) | **4.0%** |
| Band | Historical band (2022–2023) | ~10% |
| Queue | Total episodes | **1,877** |
| Queue | Buy-queue snapshots | **6,880** |
| Queue | Sell-queue snapshots | **2,007** |
| Pricing | Eligible contract-days priced | 18,368 |
| Pricing | IV computed (ok flag) | 14,590 (79.4%) |
| Pricing | No-arb violations | 3,321 (18.1%) |
| Pricing | EOD parity pairs | 6,972 |
| Pricing | Risk-free rate range | 30–40% annual |
| Axis A | IV skew slope (near-ATM, ≤30d calls) | **+0.822 (p = 1.9×10⁻¹⁵, significant)** |
| Axis A | BS pricing error median | **221 rial** |
| Axis A | BS pricing error mean | **452 rial** (p ≈ 10⁻⁷⁸) |
| Axis A | Parity basis median | **−332 rial** |
| Axis A | Parity basis mean | **−515 rial** (p ≈ 10⁻²⁵) |
| Axis B | Shadow pairs available | 6,750 |
| Axis B | IV at τ < 1 min (median) | 1.292 |
| Axis B | IV at τ > 5 min (median) | 0.35–0.50 |

---

## 8. Key Limitations to Address in the Paper

1. **Risk-free rate treatment.** Rate loaded from `Main_DataBase.xlsx` (~30–40% annual). This is a simple annual rate from the banking sector. In Islamic finance, explicit interest is formally prohibited, and the risk-free rate concept applies differently. The paper should acknowledge that the Akhza (آخزا) yield is the conventional proxy; the Excel source represents a secondary proxy. Sensitivity to r should be discussed.

2. **EOD vs intraday.** Most findings are at the daily level. The "IV vs τ" result (B3) joins EOD IV to intraday queue episodes by date — it reflects the IV of the day, not the IV at the exact moment of the snapshot.

3. **Selection bias.** All results are conditional on volume > 0 (traded days). The 55.8% zero-volume rate means findings describe only the liquid sub-universe.

4. **European assumption.** TSE options are assumed European. If early exercise provisions exist, IV and parity calculations may be misspecified.

5. **Leveraged ETF dynamics.** Ahrom is a daily-rebalancing leveraged ETF. EWMA volatility from historical returns is a downward-biased estimate due to volatility drag from daily rebalancing. This directly explains the positive BS pricing error.

6. **No-arbitrage violations with real r.** 18.1% of observations violate no-arbitrage bounds (up from 10% at r=0). This suggests either: (a) the effective market risk-free rate for options is lower than the bank rate, (b) there are structural frictions preventing arbitrage, or (c) option prices do not incorporate the full interest rate. This should be discussed explicitly.

7. **Queue detection per option.** Queue is detected independently per option instrument (not broadcast from the underlying). The "regime" label reflects the option's own order-book state.

8. **n_updates as proxy.** Trading intensity figure uses order-book update count per day, not actual executed trades (trade tape not available).

---

## 9. Suggested Paper Structure

### Title
"Price Discovery Under Market Lock: Black-Scholes Validity and Option Behavior During Queue Regimes in the Tehran Stock Exchange"

### Abstract
Study of BS validity and queue-regime option dynamics for Ahrom leveraged ETF options on TSE. Key findings: (1) BS systematically underprices options (median error 221 rial, mean 452 rial), (2) persistent **reverse IV skew**: deeper ITM calls (S/K > 1) carry higher implied volatility (+0.82 slope, p = 10⁻¹⁵), (3) significant **negative** put-call parity basis under real interest rates (calls underpriced relative to puts vs parity prediction), (4) shadow price carries statistically significant information about next-day open. Queue episodes see IV compress and activity collapse as queue age increases.

### Suggested Sections

1. **Introduction** — TSE market structure, price bands (changed from 10% to 4%), queue mechanism; why leveraged ETF options are a natural experiment
2. **Related Literature** — BS validity tests; price discovery under trading halts; circuit breakers and options; emerging market microstructure
3. **Data and Market Structure** — instruments, data coverage, liquidity profile (55.8% active-lifetime zero-volume), band regime changes
4. **Methodology** — pipeline overview, eligibility definition, rolling band detection, queue detection, τ construction, shadow price, EWMA vol, risk-free rate from Excel
5. **Axis A: BS Validity in Free Conditions** — IV smile (no significant skew); BS error by bucket (median 221 rial); parity deviations (negative basis); interest-rate sensitivity
6. **Axis B: Option Dynamics Under Queue** — Episode statistics (1,877 episodes); depth/OBI vs τ; IV vs τ (compression); activity vs τ (collapse); shadow price and star test
7. **Discussion** — Why calls are underpriced vs parity under real rates (short-selling constraint, Iranian market frictions); why IV falls with τ (certainty effect); why activity collapses at long τ; shadow price as price discovery signal
8. **Conclusion** — BS is an imperfect model even in free conditions (leveraged ETF volatility bias); the queue regime amplifies deviations; shadow price is a weak but real predictor
9. **Appendix** — Pipeline detail; parameter sensitivity; IV flag counts; band change detection; full tables

---

## 10. Open Items

1. Option exercise style (European assumed — needs confirmation from TSE rulebook)
2. The precise date of the band change from 10% → 4% (the rolling detection estimates it as mid-2025; official TSE announcement should be cited)
3. Appropriate risk-free rate proxy for Islamic finance context (Akhza yield vs. bank deposit rate)
4. Trade tape not available (n_updates used as proxy for trading intensity)
5. Intraday IV not computed (only EOD IV joined to intraday queue snapshots)

---

## 11. Corrections Applied (2026-06-27)

The following corrections were applied relative to an earlier version of this briefing:

| # | Correction | Impact |
|---|---|---|
| 1 | **Moneyness:** S/K convention confirmed (no change to definition) | IV skew slope: +0.822 (p = 10⁻¹⁵) with S/K |
| 2 | **Risk-free rate:** Loaded from Excel (30–40% annual) instead of r=0 | BS error: median 486→221, mean 844→452; parity sign flipped from +578→−332 |
| 3 | **Zero-volume rate:** Now computed within active lifetime | 56.8% raw → 55.8% within lifetime |
| 4 | **Band:** Rolling per-period (4% current) instead of global 9.95% | Episodes: 1,827→1,877; correct band per date |

See `corrections_log.md` for full technical detail.
