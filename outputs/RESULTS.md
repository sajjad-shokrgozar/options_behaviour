# Results — Black-Scholes Validity & Option Behavior Under Queue Dynamics (Ahrom ETF)

*Generated: 2026-06-27 21:05*

---

## Data Overview

- Contracts: 450 (225 call, 225 put)
- Zero-volume rate (within active lifetime): 55.8% (raw incl. pre/post-listing: 56.8%)
- Call-put pair availability (EOD traded): 50.4%
- Intraday eligible rate: 49.7%
- Empirical band: 4.00%
- Queue episodes detected: 1877
- Regime counts: {'free': 7395032, 'buy_queue': 6880, 'sell_queue': 2007}
- Daily-eligible observations priced: 18368
- Parity pairs (EOD): 6972

---

## Axis A — Black-Scholes Validity (Free Regime)

> *All results are conditional on: daily_eligible (volume>0) contract-days, free (no-queue) underlying periods, and the liquidity gate. Selection bias from this gate is acknowledged in every conclusion.*

### axA_skew_persistent — IV skew in near-term calls (free periods)

**Claim:** Near-term call IV slope vs moneyness = -0.1788 (p=0.159)

**Scope:** moneyness=near-atm; maturity_days=<=30; regime=free

**Metrics:**
  - skew_slope: -0.17883308426039807
  - n_obs: 1744
  - p_value: 0.1585544640298091

**Stat test:** HAC OLS
  - t/stat = -1.4099, p = 0.1586

**Figures:** `axA_iv_smile`

**Tables:** `axA_iv_summary`

**Limitations:** selection bias from liquidity gate

**Confidence:** medium

---

### axA_bs_error — BS pricing error magnitude and direction

**Claim:** Median BS pricing error (EWMA vol) = 220.52; mean = 452.38 (p=0.000, n=18012)

**Scope:** regime=daily_eligible; maturity_days=all

**Metrics:**
  - median_bs_error: 220.51880168987918
  - mean_bs_error: 452.3787317350719
  - n_obs: 18012

**Stat test:** HAC t-test
  - t/stat = 18.6671, p = 0.0000

**Figures:** `axA_pricing_error_by_bucket`

**Tables:** `axA_pricing_error`

**Limitations:** uses EWMA vol which may itself be biased for a leveraged ETF

**Confidence:** medium

---

### axA_parity — Put-call parity deviation

**Claim:** Median parity basis = -332.42; mean = -514.95 (p=0.000)

**Scope:** regime=daily_eligible; moneyness=all

**Metrics:**
  - median_parity_basis: -332.41937329276607
  - n_pairs: 6972

**Stat test:** HAC t-test
  - t/stat = -10.3111, p = 0.0000

**Figures:** `axA_parity_by_bucket`

**Tables:** `axA_parity_summary`

**Limitations:** EOD pair availability ~31%; stale quotes possible

**Confidence:** medium

---

## Axis B — Option Behavior vs Queue Age τ

> *Results conditional on: queue regime, τ-bucket, moneyness at queue onset. Sample sizes (N) are reported. The shadow-price test is further limited by call-put pair availability.*

### axB_tau_coverage — τ-bucket coverage in queue regime

**Claim:** Total queue option snapshots: 8872; buy_queue: 6871; sell_queue: 2001

**Scope:** regime=queue

**Metrics:**
  - n_queue_snaps: 8872
  - n_buy_queue: 6871
  - n_sell_queue: 2001

**Tables:** `axB_tau_buckets`

**Limitations:** N depends on detected episodes

**Confidence:** high

---

### axB_nextday_open — Next-day open predictability from shadow gap

**Claim:** Shadow gap slope=7.30e-06, p=0.0000, N=6669

**Scope:** regime=queue

**Metrics:**
  - shadow_gap_slope: 7.30275116680018e-06
  - n_obs: 6669
  - p_value: 0.0

**Stat test:** OLS

**Figures:** `axB_nextday_open`

**Tables:** `axB_nextday_pred`

**Limitations:** N=6669; EOD only

**Confidence:** medium

---

### axB_shadow_availability — Shadow price availability during queue episodes

**Claim:** Shadow price computable for 6750 EOD pairs during queue days.

**Scope:** regime=queue

**Metrics:**
  - n_shadow_obs: 6750

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
