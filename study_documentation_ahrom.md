# Research Documentation — Black-Scholes Validity & Option Behavior Under Queue Dynamics for the Ahrom Leveraged ETF

**Scope of this document.** A precise, self-contained specification of the study: data, definitions, design, methodology per part, feasibility figures derived from the real data, parameters, and open items. The study has exactly two research axes:

- **Axis A — Black-Scholes (BS) validity in normal (no-queue) conditions.** When the underlying is freely tradeable (not locked in a queue), does the BS relationship hold, and where does it break?
- **Axis B — Option behavior as a function of queue age.** When the underlying *is* locked in a buy/sell queue, how do the options behave as a function of how long the queue has lasted?

The two are linked by one hypothesis: **the underlying's price band and queue mechanism is the structural reason BS may fail.** Axis A measures BS in the textbook-friendly regime (free underlying) to establish a clean baseline; Axis B measures what happens in the regime where the underlying is untradeable and the options become the only venue of price discovery.

---

## 1. Instrument family

| Role | Symbol family | Persian tag | Notes |
|---|---|---|---|
| Underlying | Ahrom | اهرم | Leveraged ETF; **pays no dividend**; very liquid |
| Call options | Zahrom | اختیارخ اهرم | European (to confirm), cash-relevant |
| Put options | Tahrom | اختیارف اهرم | European (to confirm) |

The option type is read from the data, **not guessed from the symbol**: `underlying = "اختیارخ اهرم"` ⇒ call; `underlying = "اختیارف اهرم"` ⇒ put.

---

## 2. Data sources (verified schemas)

### 2.1 `underlying_history.csv` — daily EOD for the underlying
1,076 daily rows, **2021-12-20 → 2026-06-21**. Columns:

`symbol, id, date (YYYYMMDD Gregorian), jdate (YYYYMMDD Jalali), min, max, yesterday, first, close, last, trades_count, volume, value, ret, cumprod, adj_price`

- `yesterday` = prior-day reference price (basis for band/queue detection).
- `first` = day open (used for the next-day-open test in Axis B).
- `adj_price` = adjustment-corrected price (use for any return/continuity work across capital increases).
- The history is **longer than the options window** — useful for estimating a robust realized-volatility series.
- Underlying is highly liquid: only **6.3%** of days have zero volume.

### 2.2 `options_history.csv` — daily EOD for the options
42,524 contract-day rows, **2024-11-20 → 2026-06-21**; **450 contracts** (225 calls + 225 puts), **21 strikes** (11,000 → 68,000). Columns:

`symbol, id, date (Gregorian), jdate (Jalali), min, max, yesterday, first, close, last, trades_count, volume, value, title, underlying, strike, maturity (YYYYMMDD Jalali)`

- **`strike` and `maturity` are present** ⇒ all pricing inputs (K, T) come directly from here. This removes the single biggest prior risk.
- `title` carries the human-readable contract (e.g. `اختیارخ اهرم-11000-1404/01/27`).
- **`maturity` is a Jalali date** ⇒ must be converted to Gregorian to compute time-to-maturity `T`.

### 2.3 Order book sample (`order_book_ai_sample_1000.csv`) — intraday best limits
A 1,000-row sample of the full intraday order book. Real columns (the `sample_*` columns are sample-only artifacts):

`symbol, instrument_id, date (YYYYMMDD), hEven (HHMMSS), refID, number (1..5), qTitMeDem (bid vol), pMeDem (bid price), pMeOf (ask price), qTitMeOf (ask vol)`

- File path pattern: `best_limits_data/{instrument_id}/{YYYYMMDD}.csv`.
- **Reconstruction:** one `refID` = one order-book update; the five `number` rows (1..5) give the five depth levels at that instant; `hEven` is the timestamp. Pivot on `number` within `(instrument_id, date, refID)`.
- The sample is sub-sampled to one level-row per snapshot, so full books cannot be reconstructed from it — it defines the **schema**, not the contents.

### 2.4 Intraday trades — available, no sample yet
Every executed trade with time/price/volume per instrument per day. Schema to be confirmed on arrival (see §10).

---

## 3. The 55% emptiness — what it is and why it dictates the design

Confirmed directly: **56.8% of option contract-days have zero volume / zero trades.** Emptiness is **structured, not random**:

- It is concentrated in **deep-ITM / deep-OTM** strikes and **far maturities (≳ 60 days)**.
- Traded-rate by call moneyness (S/K): deep-OTM (S/K ≤ 0.7) ≈ **26%**; near-the-money (0.9–1.3) ≈ **48–49%**.
- Even the most liquid (near-the-money) bucket trades only about half of all days.
- **Call-put pair availability:** only **31.4%** of (date, strike, maturity) pairs have *both* legs traded on the same day — and this is the EOD figure; intraday joint freshness is materially lower.

Design consequences (these drive everything below):

1. **The study is, in practice, about the liquid sub-universe** (near-the-money, ≤ 60 days, traded). All conclusions are stated **conditionally**, never as universal claims.
2. **Liquidity is a first-class stratification variable**, not a silent filter.
3. **Forward-filling stale option quotes is prohibited** beyond a strict staleness window; stale observations are dropped, not carried.
4. The **shadow-price construction** (Axis B, §7) is available far less often than naively assumed; its realized availability must be reported as a result, not assumed.

---

## 4. Two-tier analytical design

Because intraday option data is sparse, the analysis is split into two tiers and most claims are anchored at the tier where the sample is largest.

- **Tier A — daily (EOD) backbone.** Uses `options_history` + `underlying_history` only. Robust sample on traded contract-days. Carries most of Axis A and the descriptive option-pricing surface.
- **Tier B — intraday.** Uses the order book + intraday trades. Reserved for what genuinely needs sub-daily resolution: queue detection, the event clock `τ`, the free-vs-queue split, effective-spread / net-of-cost arbitrage tests, and intraday dynamics.

Rule of thumb: do it at the daily level if the daily level can answer it; spend intraday resolution only where it adds something.

---

## 5. Core definitions

### 5.1 Eligibility / liquidity gate
- **Daily-eligible contract-day:** `volume > 0` (the contract actually traded that day).
- **Intraday-eligible observation:** a fresh, two-sided option quote (valid bid and ask) **within the staleness window** `Δ_stale` (a parameter; sensitivity-tested). A recent trade can substitute for a quote.
- **Liquidity metric `L`:** a composite of quote-update rate, trade frequency (from the trade tape), relative spread, and quote/trade freshness. Used both as a gate and as a stratification axis.

### 5.2 Stratification grid (applied everywhere)
- **Moneyness buckets** (call convention S/K): deep-OTM, OTM, near-the-money, ITM, deep-ITM (cut points calibrated to the data; the near-the-money band is where pricing is meaningful).
- **Maturity buckets (days to expiry):** `≤ 30`, `30–60`, `> 60` (the 60-day boundary matches the observed liquidity drop-off).

### 5.3 Time-to-maturity `T`
`maturity` (Jalali) → Gregorian → `T = year_fraction(valuation_date, expiry)` under one fixed day-count convention (e.g. calendar/365 or trading/252), documented once and held constant.

### 5.4 Mid / microprice / spread / depth / OBI (per snapshot)
- `mid = (best_bid + best_ask)/2` (only when both sides exist).
- `microprice = (best_bid·ask_qty₁ + best_ask·bid_qty₁)/(bid_qty₁ + ask_qty₁)`.
- `spread = best_ask − best_bid`; `rel_spread = spread/mid`.
- `depth_side = Σ_{i=1..5} qty_i`; `OBI = (depth_bid − depth_ask)/(depth_bid + depth_ask) ∈ [−1, 1]`.

### 5.5 Price band & queue (underlying)
- **Band:** the empirical daily price-move limit relative to `yesterday`. Derived **per period from the data** (the underlying reaches up-moves of ~6% at the 95th and ~10% at the 99th percentile, so a fixed ±5% is wrong; the band is wider and/or time-varying). If an official band figure is available it is preferred over the empirical one.
- **Queue (saf):** an underlying state in which one side of the book is empty, the best price is locked at the band limit, and this **persists** across several consecutive snapshots. **Buy queue** = ask side empty + price at ceiling; **sell queue** = mirror at the floor. Queue detection is applied **to the underlying only** (the options' empty side reflects illiquidity, not a queue).
- **Regime label** per intraday instant: `queue_state ∈ {buy_queue, sell_queue, free}`. A **post-queue guard window** is excluded right after a queue releases (price is re-equilibrating).

### 5.6 Queue episode & event clock `τ`
- **Episode:** a maximal continuous interval of a queue state, with `start, end, side, duration, depth (cumulative volume on the locked side), end_type (released | lasted to session end)`.
- **`τ` (queue age):** minutes elapsed since `start`, attached to every option observation inside the episode.

### 5.7 Pricing objects
- **Black-Scholes, European, no dividend (`q = 0`):** `d1 = (ln(S/K) + (r + σ²/2)T)/(σ√T)`, `d2 = d1 − σ√T`; `Call = S·N(d1) − K e^{−rT} N(d2)`; `Put = K e^{−rT} N(−d2) − S·N(−d1)`; `Δ_call = N(d1)`, `Δ_put = N(d1) − 1`.
- **Implied volatility (IV):** invert BS for `σ` (Brent on a vega-positive bracket). Computed from mid and separately from bid/ask to form an **IV band**; flagged (not faked) when the price violates no-arbitrage bounds.
- **Put-call parity:** `basis = (C − P) − (S − K e^{−rT})`.
- **Risk-free rate `r`:** an **external** proxy (Islamic treasury / Akhza yield) is used for any *test* of parity. A parity-*implied* rate is computed only as a descriptive cross-check — never both directions at once (avoids circularity). All BS results are reported with an `r`-sensitivity band.
- **Shadow price (Axis B):** `S* = C − P + K e^{−rT}`, the underlying price implied by a same-strike, same-maturity option pair — defined only when both legs are eligible/fresh.

---

## 6. Axis A — Black-Scholes validity in free (no-queue) conditions

Rationale: BS assumes the underlying is continuously tradeable and hedgeable. The fairest test of the model itself is therefore the regime where that assumption holds — **free** periods. If BS fails even here, the fault is the model (skew, leveraged-fund volatility dynamics), not the market lock.

### 6.1 Tier-A daily baseline
On daily-eligible (traded) contract-days, using closing/last prices:

1. **IV extraction** per contract-day; build the **smile/skew** per maturity and the **IV term structure** across maturities.
2. **Put-call parity** close-to-close with the **external `r`**; record sign and magnitude of `basis` by moneyness × maturity.
3. **BS pricing error** = market price − BS price, where the BS price uses an **independent volatility** input (realized / EWMA volatility estimated from the long 2021+ underlying history) — *not* the IV implied by the same price (which would make the error mechanically zero). Stratify by moneyness × maturity.
4. **Cross-contract IV consistency:** dispersion of IV across contracts of the same underlying/maturity — a direct model-adequacy measure.
5. **Define the free-close subset:** days where the underlying did **not** close at the band / in a queue. This is Axis A's clean baseline at the daily level.

### 6.2 Tier-B intraday refinement (free instants only)
On `free` underlying instants with intraday-eligible options:

6. Recompute IV / parity / pricing error intraday and compare to the Tier-A baseline.
7. **Model-inefficiency vs market-inefficiency split:** subtract the **real effective spread** (from the trade tape) from any apparent parity/arbitrage deviation. Survives net of cost ⇒ market inefficiency; vanishes ⇒ the model is simply wrong (no exploitable opportunity).
8. **(Strongest, optional) Delta-hedge replication:** would a BS-delta hedge over free intervals have neutralized the option P&L? This is the most direct efficiency test because it replicates exactly what BS claims is possible.

### 6.3 A caveat that sharpens Axis A
Even in free periods the **band always truncates** the underlying's return distribution, while BS assumes an unbounded log-normal. So "free" is still not textbook-ideal. Any residual BS failure in free periods is attributable to: (i) the ever-present band truncation, (ii) volatility skew, and (iii) the **path-dependent volatility of a daily-rebalanced leveraged ETF** — which violates the constant-vol GBM assumption at the root. The write-up must separate these.

---

## 7. Axis B — Option behavior as a function of queue age `τ`

On `queue` instants only, everything is computed in **`τ` buckets** (e.g. 0–1, 1–5, 5–15, 15–30, 30+ minutes), separately for buy vs sell queues, and against a **matched no-queue control** (same time-of-day, same moneyness).

1. **Shadow-price gap** `S* − locked_price` vs `τ` — the "suppressed demand". **Report the fraction of queue-time where a fresh pair existed** (availability is itself a finding, given the 31% pair figure).
2. **IV level and skew** vs `τ`.
3. **Option spread, depth, and trade intensity** (from the trade tape) vs `τ` — does the option keep trading while the underlying is locked? This is the direct evidence that price discovery migrates to the options.
4. **Parity deviation** vs `τ`.
5. **Star test — next-day-open prediction:** does the end-of-queued-day shadow price predict the underlying's next-day open (`first`)? Regress next-day open return on the end-of-day shadow gap. **Estimate N first** — this test lives on (queued days) ∩ (days with a fresh closing pair) and may be low-powered; report power honestly.

### 7.1 Confounding control (critical)
A queue jump moves the underlying, which can push a near-the-money option deep ITM/OTM, which *itself* reduces that option's liquidity. So a spread-widening-with-`τ` must not be attributed to the queue without controlling moneyness. Therefore **fix each option's moneyness at queue onset** and track that fixed cohort through `τ`, separating "drifted away from the money" from "dried up because of the queue".

---

## 8. Pipeline (build order)

| Step | Module | Produces |
|---|---|---|
| 0 | ingest + specs join | contract specs (K, expiry, type) joined by `id`; Jalali→Gregorian; partitioned parquet |
| 1 | book reconstruction | 5-level snapshots; mid/microprice/spread/depth/OBI |
| 2 | session/time | `hEven`→datetime; pre-open vs continuous split (empirical, per day) |
| 3 | clean | empty levels→NaN; crossed books flagged; tick size |
| 4 | sync + trades | as-of alignment of underlying book / option book / trades; Lee-Ready signing; effective spread; liquidity metric `L`; eligibility flags |
| 5 | band + queue | empirical band; queue detection; episodes; `τ`; regime labels; post-queue guard |
| 6 | pricing | BS, IV (mid + bid/ask band), parity, external & implied `r`, shadow price |
| 7 | Axis A | Tier-A daily baseline → Tier-B free-instant refinement |
| 8 | Axis B | `τ`-bucket analysis + star test |
| 9 | synthesis | baseline-vs-queue contrast; conditional conclusions |

Develop and test the whole pipeline on the 1,000-row sample first; only then run on the full data.

---

## 9. Key parameters (set in config, sensitivity-tested)

| Parameter | Meaning | Note |
|---|---|---|
| `Δ_stale` | max quote/trade staleness for intraday eligibility | sensitivity-tested; central to validity |
| band % (per period) | underlying daily price-move limit | empirical or official |
| queue persistence | min consecutive snapshots to call a queue | guards against transient one-sidedness |
| post-queue guard | excluded window after a queue releases | re-equilibration |
| moneyness cut points | OTM/ATM/ITM bucket edges | calibrated to data |
| maturity cut points | ≤30 / 30–60 / >60 days | matches liquidity drop |
| day-count for `T` | 365 vs 252 | fixed once |
| `r` source | external (Akhza) | implied `r` descriptive only |
| vol input for BS error | realized / EWMA from 2021+ history | independent of the tested price |

---

## 10. Open items (intraday only; do not change the design)

1. In the **full** order book, does every `refID` carry all five `number` levels? (The sample sub-sampled, so unverifiable from it.)
2. **Intraday trade schema:** exact columns; is a buyer/seller flag already present (then Lee-Ready is unnecessary)? Same clock as `hEven`?
3. **`hEven` resolution** and whether updates carry tied timestamps (sets the finest usable `τ` bucket and event window).
4. **Option exercise style / settlement** — confirm European and cash-settled, and that the margin mechanism creates no early-exercise-like behavior.
5. Whether an **official band %** is available (preferred over the empirical estimate for queue detection).

---

## 11. Conditional-conclusion discipline (how results are stated)

Every headline result is reported **with its regime and eligibility scope**, e.g.: *"Within near-the-money contracts at ≤ 60 days to maturity and during free (no-queue) underlying periods, the BS pricing error has median X% and is centered/biased in direction Y; the IV skew has shape Z and persists."* No result is generalized to deep wings, long maturities, illiquid contract-days, or queue periods unless it was measured there. Selection bias from the liquidity gate is acknowledged in every conclusion.
