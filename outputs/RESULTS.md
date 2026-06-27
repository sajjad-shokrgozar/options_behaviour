# Results — Black-Scholes Validity & Option Behavior Under Queue Dynamics (Ahrom ETF)

*Generated: 2026-06-27 10:41*

---

## Data Overview

- Contracts: 450 (225 call, 225 put)
- Zero-volume contract-day rate (EOD): 56.8%
- Call-put pair availability (EOD traded): 50.4%
- Intraday eligible rate: 49.7%
- Empirical band: 9.95%
- Queue episodes detected: 1827
- Regime counts: {'free': 7395224, 'buy_queue': 6740, 'sell_queue': 1955}
- Daily-eligible observations priced: 18368
- Parity pairs (EOD): 6972

---

## Axis A — Black-Scholes Validity (Free Regime)

> *All results are conditional on: daily_eligible (volume>0) contract-days, free (no-queue) underlying periods, and the liquidity gate. Selection bias from this gate is acknowledged in every conclusion.*

### axA_skew_persistent — IV skew in near-term calls (free periods)

**Claim:** Near-term call IV slope vs moneyness = 0.8500 (p=0.000)

**Scope:** moneyness=near-atm; maturity_days=<=30; regime=free

**Metrics:**
  - skew_slope: 0.8499551552735386
  - n_obs: 2021
  - p_value: 2.117862228715561e-27

**Stat test:** HAC OLS
  - t/stat = 10.8445, p = 0.0000

**Figures:** `axA_iv_smile`

**Tables:** `axA_iv_summary`

**Limitations:** selection bias from liquidity gate

**Confidence:** medium

---

### axA_bs_error — BS pricing error magnitude and direction

**Claim:** Median BS pricing error (EWMA vol) = 486.05; mean = 844.26 (p=0.000, n=18012)

**Scope:** regime=daily_eligible; maturity_days=all

**Metrics:**
  - median_bs_error: 486.04805025376044
  - mean_bs_error: 844.2631340982061
  - n_obs: 18012

**Stat test:** HAC t-test
  - t/stat = 28.9567, p = 0.0000

**Figures:** `axA_pricing_error_by_bucket`

**Tables:** `axA_pricing_error`

**Limitations:** uses EWMA vol which may itself be biased for a leveraged ETF

**Confidence:** medium

---

### axA_parity — Put-call parity deviation

**Claim:** Median parity basis = 578.00; mean = 810.97 (p=0.000)

**Scope:** regime=daily_eligible; moneyness=all

**Metrics:**
  - median_parity_basis: 578.0
  - n_pairs: 6972

**Stat test:** HAC t-test
  - t/stat = 16.2996, p = 0.0000

**Figures:** `axA_parity_by_bucket`

**Tables:** `axA_parity_summary`

**Limitations:** EOD pair availability ~31%; stale quotes possible

**Confidence:** medium

---

## Axis B — Option Behavior vs Queue Age τ

> *Results conditional on: queue regime, τ-bucket, moneyness at queue onset. Sample sizes (N) are reported. The shadow-price test is further limited by call-put pair availability.*

### axB_tau_coverage — τ-bucket coverage in queue regime

**Claim:** Total queue option snapshots: 8681; buy_queue: 6732; sell_queue: 1949

**Scope:** regime=queue

**Metrics:**
  - n_queue_snaps: 8681
  - n_buy_queue: 6732
  - n_sell_queue: 1949

**Tables:** `axB_tau_buckets`

**Limitations:** N depends on detected episodes

**Confidence:** high

---

### axB_nextday_open — Next-day open predictability from shadow gap

**Claim:** Shadow gap slope=6.01e-06, p=0.0000, N=6627

**Scope:** regime=queue

**Metrics:**
  - shadow_gap_slope: 6.014583051051906e-06
  - n_obs: 6627
  - p_value: 5.711776735854973e-233

**Stat test:** OLS

**Figures:** `axB_nextday_open`

**Tables:** `axB_nextday_pred`

**Limitations:** N=6627; EOD only

**Confidence:** medium

---

### axB_shadow_availability — Shadow price availability during queue episodes

**Claim:** Shadow price computable for 6708 EOD pairs during queue days.

**Scope:** regime=queue

**Metrics:**
  - n_shadow_obs: 6708

**Figures:** `axB_shadow_vs_tau`

**Tables:** `axB_shadow_availability`

**Limitations:** EOD only

**Confidence:** high

---

## Open Items (Surfaced per §9 of spec)

1. **Full order book level completeness:** confirmed empirically — see manifest `book.pct_incomplete`.
2. **Trades schema:** not yet available; Lee-Ready module stubbed.
3. **hEven resolution:** integer HHMMSS; second-level granularity.
4. **Option exercise style:** assumed European, cash-settled (confirm with exchange).
5. **Official band %:** not provided; empirical band used (see manifest `band_queue.band_pct`).
