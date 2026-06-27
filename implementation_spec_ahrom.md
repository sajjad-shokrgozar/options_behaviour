# Implementation Specification — Ahrom Options Study (build-ready)

**Audience:** an AI coding agent that will implement this project end to end.
**How to use this document:** implement strictly in the module order of §4. Each module lists its **inputs, outputs, exact logic, and acceptance checks**. Do not skip acceptance checks. Where a numeric threshold is a policy choice, it lives in `config.yaml` (§3) — never hard-code it. Companion conceptual doc: `study_documentation_ahrom.md` (read it for the *why*; this doc is the *how*).

The study has two research axes:
- **Axis A** — Does Black-Scholes (BS) hold when the underlying is **free** (not in a queue)? Where does it break?
- **Axis B** — How do options behave as a function of **queue age `τ`** when the underlying is locked in a buy/sell queue?

---

## 0. Non-negotiable principles

1. **Sample-first.** Everything must run and pass tests on the 1,000-row order-book sample before touching full data.
2. **No hard-coded market parameters.** Band %, session hours, tick size, staleness window, bucket edges — all from `config.yaml` or derived empirically from data.
3. **Asynchronous data.** Never align two instruments by row index. Use as-of joins (§4.4). Never forward-fill an option quote beyond `staleness_window_s`.
4. **Strike/expiry come from `options_history`** (columns `strike`, `maturity`), never parsed from the symbol.
5. **Two date systems.** `date` is Gregorian `YYYYMMDD`; `jdate`/`maturity` are Jalali `YYYYMMDD`. Convert Jalali→Gregorian for any time-to-maturity math. Use a vetted library (`jdatetime` or `convertdate`).
6. **Log every dropped row with a reason.** Data quality is an output (Axis A depends on it).
7. **Determinism.** Fixed seed; pinned dependencies; every output traceable via `manifest.json`.

---

## 1. Tech stack

- Python ≥ 3.11.
- Data: **polars** or **pandas + pyarrow**; **DuckDB** optional for SQL over parquet.
- Numerics: `numpy`, `scipy` (`scipy.optimize.brentq` for IV).
- Econometrics: `statsmodels`; `arch` optional (volatility).
- Dates: `jdatetime` (Jalali↔Gregorian).
- Plotting: `matplotlib` (static, for the report) + `plotly` (exploration).
- Env: `uv` or `poetry`; pinned lockfile.

---

## 2. Inputs (verified schemas)

### 2.1 `underlying_history.csv` — daily EOD, underlying
`symbol, id, date(YYYYMMDD greg), jdate(Jalali), min, max, yesterday, first, close, last, trades_count, volume, value, ret, cumprod, adj_price`
- ~1,076 rows, 2021-12-20 → 2026-06-21. `yesterday` = prior reference price. `first` = open. `adj_price` = split-adjusted. Underlying is liquid (~6.3% zero-volume days).

### 2.2 `options_history.csv` — daily EOD, options
`symbol, id, date(greg), jdate(Jalali), min, max, yesterday, first, close, last, trades_count, volume, value, title, underlying, strike, maturity(Jalali)`
- ~42,524 rows, 450 contracts (225 call + 225 put), 21 strikes (11,000–68,000), 2024-11-20 → 2026-06-21.
- `underlying == "اختیارخ اهرم"` ⇒ **call**; `underlying == "اختیارف اهرم"` ⇒ **put**.
- **56.8% of contract-days have zero volume** (structured illiquidity: deep-ITM/OTM and far maturities).

### 2.3 Order book — intraday best limits
Path: `best_limits_data/{instrument_id}/{YYYYMMDD}.csv`. Columns (ignore any `sample_*` columns):
`symbol, instrument_id, date(YYYYMMDD), hEven(HHMMSS), refID, number(1..5), qTitMeDem(bid vol), pMeDem(bid px), pMeOf(ask px), qTitMeOf(ask vol)`
- One `refID` = one book update; its 5 `number` rows are the 5 depth levels; `hEven` is its timestamp.

### 2.4 Intraday trades — schema TBD (see §9). Expected: `instrument_id, date, time(HHMMSS), price, volume` (+ optional side flag).

---

## 3. `config.yaml` (all tunables; agent must read, never inline)

```yaml
paths:
  underlying_history: data/raw/underlying_history.csv
  options_history:    data/raw/options_history.csv
  order_book_dir:     data/raw/best_limits_data
  trades_dir:         data/raw/trades
  out_dir:            outputs

ids:
  underlying_id: 17914401175772326

session:
  derive_from_trades: true        # session bounds per day from first/last trade
  fallback_open:  "09:00:00"
  fallback_close: "12:30:00"

liquidity:
  staleness_window_s: 120         # max age of an option quote/trade to be "fresh"
  min_quote_updates_day: 1        # contract-day must have >=1 update to be intraday-eligible

band:
  source: empirical               # empirical | official
  official_pct: null              # set if known
  empirical_quantile: 0.99        # band ~ this quantile of |move/yesterday|
  at_limit_tol_ticks: 1           # "at the band" if within this many ticks

queue:
  min_persist_snapshots: 3        # consecutive snapshots to confirm a queue
  post_queue_guard_min: 5         # minutes excluded after a queue releases

buckets:
  moneyness_edges: [0.0, 0.85, 0.95, 1.05, 1.15, 100.0]   # S/K; calibrate on data
  maturity_days_edges: [0, 30, 60, 100000]

pricing:
  daycount: 365                   # 365 | 252  (fixed once)
  r_source: external              # external | implied
  r_external_series: data/raw/akhza_yield.csv   # date,yield
  iv_brackets: [1.0e-4, 5.0]
  vol_for_bs_error: ewma          # realized | ewma  (independent of tested price)
  ewma_lambda: 0.94

tau_buckets_min: [0, 1, 5, 15, 30, 100000]

run:
  seed: 42
  sample_mode: true               # true => run on the 1000-row sample fixtures
```

---

## 4. Modules (implement in this order)

Each module = one file in `src/`. Signature convention: `run(cfg) -> None`, writing parquet to `outputs/panels/` and logging to `manifest.json`.

### 4.1 `specs.py` — contract specification table
**In:** `options_history.csv`.
**Out:** `panels/contract_specs.parquet` keyed by `instrument_id` with `strike, expiry_greg(date), option_type(call|put), underlying_id`.
**Logic:** dedupe option-days to one row per `instrument_id`; map `underlying` text → `option_type`; convert `maturity` (Jalali) → `expiry_greg` via `jdatetime`.
**Acceptance:** every `instrument_id` has exactly one spec; `option_type` ∈ {call,put}; `expiry_greg` parses for 100% of contracts; call/put counts ≈ equal.

### 4.2 `ingest.py` — raw → parquet
**In:** order book CSVs (+ EOD CSVs).
**Out:** `panels/book_raw.parquet` partitioned by `instrument_id, date`.
**Logic:** read with `encoding="utf-8"`; keep only real columns (§2.3); cast types; do **not** clean yet.
**Acceptance:** row count preserved; no Persian symbol becomes mojibake (spot-check `symbol`).

### 4.3 `book.py` — 5-level snapshot reconstruction
**In:** `book_raw`.
**Out:** `panels/book_snap.parquet`: one row per `(instrument_id, date, refID)` with `ts, bid_px_1..5, bid_qty_1..5, ask_px_1..5, ask_qty_1..5, mid, microprice, spread, rel_spread, depth_bid, depth_ask, OBI`.
**Logic:** pivot on `number` within `(instrument_id, date, refID)`; `ts` from `hEven` (§4.5 helper); compute derived metrics per §5.4 of the conceptual doc. `mid`/`microprice` are NaN when a needed side is missing.
**Acceptance:** report % of `refID`s **not** having all 5 levels (log, don't crash); bid levels descending, ask ascending (flag violations); `OBI ∈ [−1,1]`.
> Note: on the **sample** each `refID` has 1 level (sub-sampled) — so this module's full reconstruction is exercised against full data; on the sample, assert the pivot logic runs and metrics are NaN-safe.

### 4.4 `clean.py` — cleaning & flags
**In:** `book_snap`.
**Out:** `panels/book_clean.parquet` (+ adds boolean flags).
**Logic:** treat `price==0 | qty==0` levels as **NaN** (not zero); flag `crossed = bid_px_1 >= ask_px_1` and set their `mid=NaN` but keep the row; derive `tick_size` per instrument from the modal positive price increment.
**Acceptance:** counts of empty-level rows, crossed rows, and per-instrument `tick_size` written to the data-quality report.

### 4.5 `session.py` — time & session split
**Helpers:** `hEven_to_time(hEven)`; `to_datetime(date, hEven)`.
**Out:** adds `session_phase ∈ {preopen, continuous}` to `book_clean`.
**Logic:** if `derive_from_trades`, set continuous-session bounds per `(instrument_id?/market, date)` from first/last **trade** time; else use fallbacks. Anything before continuous start = `preopen`. Do this **per day** (market hours changed over the period).
**Acceptance:** preopen rows exist and cluster early (sample shows ~06:00 records); continuous window non-empty on traded days.

### 4.6 `trades.py` — trade tape processing *(activate when trades arrive; stub interface now)*
**Out:** `panels/trades_clean.parquet` with `ts, price, volume, side ∈ {buy,sell}`, plus `effective_spread`.
**Logic:** if a native side flag exists, use it; else **Lee-Ready** (compare trade price to synchronized `mid`; tie → tick test). `effective_spread = 2·|price − mid|`.
**Acceptance:** signed-share sanity (not ~100% one side); effective spread ≥ 0.

### 4.7 `sync.py` — cross-instrument synchronization
**In:** `book_clean` (underlying + each option), `trades_clean`.
**Out:** `panels/synced.parquet`: for each **option** snapshot, attach the **as-of latest** underlying state and a freshness age.
**Logic:** `merge_asof(direction="backward")` on `ts`; compute `under_quote_age_s` and `opt_quote_age_s`; mark `fresh = max(ages) <= staleness_window_s`. **Never** carry beyond the window — set stale fields to NaN and `fresh=False`.
**Acceptance:** distribution of quote ages logged; `fresh` rate reported per moneyness×maturity bucket (this is the realized effective-sample size).

### 4.8 `liquidity.py` — eligibility & liquidity metric
**Out:** adds `daily_eligible` (from `options_history.volume>0`), `intraday_eligible` (`fresh & two_sided`), and composite `L` (z-scored blend of update rate, trade frequency, `rel_spread`, freshness).
**Acceptance:** reproduce the headline liquidity facts on EOD data: ~56–57% zero-volume contract-days; traded-rate rising toward the money. Persist a `liquidity_profile` table by moneyness×maturity.

### 4.9 `band_queue.py` — band, queue, episodes, `τ`
**In:** underlying `book_clean` + `underlying_history` (`yesterday`).
**Out:** `panels/queue_episodes.parquet` and a per-snapshot `regime ∈ {buy_queue, sell_queue, free}` on the underlying timeline.
**Logic:**
- **Band:** if `official`, use it; else `band_pct = quantile(|day_extreme/yesterday − 1|, empirical_quantile)` per period. "At limit" = best price within `at_limit_tol_ticks` of the band edge.
- **Queue (underlying only):** one side empty **and** best price at the band edge **and** persists ≥ `min_persist_snapshots`. Buy=ask empty@ceiling; sell=bid empty@floor.
- **Episodes:** maximal runs; record `start, end, side, duration, depth(cum volume on locked side), end_type`.
- **`τ`:** minutes since episode `start`, broadcast to every option observation whose `ts` falls in the episode (join on the synchronized timeline).
- Apply `post_queue_guard_min` exclusion after each release.
**Acceptance:** at least one episode detected on full data; on the sample, assert the detector runs and the empty-side/at-limit predicates fire on the known empty rows; `free + queue` partition is exhaustive and disjoint.

### 4.10 `pricing.py` — BS, IV, parity, shadow, rates
**Functions:** `bs_price(S,K,T,r,sigma,kind)`, `bs_delta(...)`, `iv_from_price(price,...)` (Brent on `iv_brackets`, return NaN + flag if price violates no-arb bounds), `parity_basis(C,P,S,K,T,r)`, `shadow_price(C,P,K,T,r)`.
**Rates:** load external `r(date)` for **tests**; compute parity-implied `r` only as a descriptive series. Provide an `r`-sensitivity wrapper.
**BS error vol input:** use `vol_for_bs_error` (realized/EWMA from the **2021+** underlying history) — **never** the IV implied by the same price.
**Acceptance:** round-trip test `iv_from_price(bs_price(...,σ))≈σ`; parity identity holds on synthetic inputs; IV undefined cases are flagged not faked.

### 4.11 `axis_a.py` — Black-Scholes validity (free regime)
**Tier-A (daily, on `daily_eligible`):** IV per contract-day from `close`/`last`; smile/skew per maturity; IV term structure; parity (external `r`) by moneyness×maturity; BS pricing error (independent vol) by bucket; cross-contract IV dispersion. Define the **free-close subset** = days the underlying did not close at band/queue.
**Tier-B (intraday, `regime==free & intraday_eligible`):** recompute IV/parity/error vs the Tier-A baseline; **model-vs-market inefficiency split** = subtract `effective_spread` from each deviation; **optional delta-hedge replication** P&L over free intervals.
**Outputs:** figures + `figures_data/*.csv` + `tables/*.csv` + `findings/axis_a.json` (see §6).
**Acceptance:** every reported number exists in a CSV/JSON; results carried with `r`-sensitivity and bucket stratification.

### 4.12 `axis_b.py` — option behavior vs queue age `τ` (queue regime)
On `regime ∈ {buy_queue, sell_queue}`, in `tau_buckets_min`, vs a **matched no-queue control** (same time-of-day, same moneyness):
- shadow-price gap `S* − locked_price` vs `τ` **and** the realized availability rate of a fresh pair (report it — expect it to be low);
- IV level & skew vs `τ`; option spread/depth/**trade-intensity** vs `τ`;
- parity deviation vs `τ`;
- **star test:** regress next-day open (`first`) return on end-of-day shadow gap; **first compute and report N** (queued days ∩ days with a fresh closing pair).
**Confounding control:** fix each option's **moneyness at queue onset** and track that fixed cohort through `τ`.
**Acceptance:** control matching documented; `τ`-bucket counts reported; star-test power (N) reported even if small.

### 4.13 `report.py` — assembly
Generate `outputs/RESULTS.md` stitching, per axis: each finding's claim + key metrics + embedded figures + table previews; plus `data_quality_report.md` and `manifest.json`.

---

## 5. Output layout (contract)

```
outputs/
├── manifest.json            # code hash, config snapshot, input hashes, per-stage row counts,
│                            # resolved empirical params (band%, session bounds, tick sizes, r used)
├── data_quality_report.md
├── panels/*.parquet         # contract_specs, book_*, synced, queue_episodes, trades_clean
├── figures/ax{A,B}_*.png + .svg
├── figures_data/ax{A,B}_*.csv      # exact data behind each figure
├── tables/ax{A,B}_*.csv + *.meta.json
├── findings/axis_a.json, axis_b.json
└── RESULTS.md
```
**Golden rule:** every analytical result exists as (figure + figure_data CSV + a findings entry). No number appears only inside a chart.

---

## 6. `findings/*.json` schema (what the write-up is built from)

```json
{
  "id": "axA_skew_persistent",
  "axis": "A",
  "title": "IV skew is present and persistent in free periods",
  "claim": "One plain sentence with the key number.",
  "scope": {"moneyness": "near", "maturity_days": "<=60", "regime": "free"},
  "metrics": {"skew_slope": 0.0, "n_obs": 0},
  "stat_test": {"name": "HAC t-test", "statistic": 0.0, "p_value": 0.0, "ci": [0.0,0.0]},
  "figure_refs": ["axA_iv_smile"],
  "table_refs": ["axA_iv_summary"],
  "robustness": "r-sensitivity, subperiods, bucket variation",
  "limitations": "selection bias from liquidity gate; band truncation always present",
  "confidence": "high|medium|low"
}
```
Rules: numbers stored as numbers; every `*_refs` points to a real produced artifact; every value cited in `claim` appears in `metrics`; every finding carries `scope` (results are conditional).

---

## 7. Required artifacts per axis (minimum)

| Axis | Figures | Tables | Findings (examples) |
|---|---|---|---|
| A | `axA_iv_smile`, `axA_iv_term_structure`, `axA_pricing_error_by_bucket`, `axA_parity_by_bucket`, `axA_iv_dispersion` | `axA_iv_summary`, `axA_pricing_error`, `axA_parity_summary` | where BS holds/breaks; skew shape & persistence; model-vs-market split |
| B | `axB_shadow_vs_tau`, `axB_iv_vs_tau`, `axB_spread_depth_vs_tau`, `axB_tradeintensity_vs_tau`, `axB_nextday_open` | `axB_tau_buckets`, `axB_shadow_availability`, `axB_nextday_pred` | metric paths vs τ; pair-availability rate; next-day-open predictability + N |

---

## 8. Testing (`tests/`, run on the sample)

- `test_specs`: Jalali→Gregorian on known dates; one spec per contract.
- `test_book`: pivot/NaN-safety; ordering checks; OBI bounds.
- `test_clean`: zero→NaN; crossed flagged.
- `test_session`: `hEven` parsing edge cases (e.g. `60125`→06:01:25).
- `test_sync`: no carry beyond `staleness_window_s`.
- `test_pricing`: IV round-trip; parity identity; no-arb flagging.
- `test_queue`: empty-side + at-limit predicates fire on known sample rows; regimes disjoint & exhaustive.
- `test_liquidity`: reproduces ~56–57% zero-volume on EOD.

---

## 9. Open items the agent must surface (do not silently assume)

1. Full order book: does every `refID` carry all 5 `number` levels? (sample can't confirm) — assert and report.
2. Trades schema: exact columns; native side flag? same clock as `hEven`?
3. `hEven` resolution / tied timestamps → finest valid `τ` bucket and event window.
4. Option exercise style/settlement = European cash-settled? margin-driven early-exercise behavior?
5. Official band % available? (preferred over empirical).
If any is unknown at build time, implement the configurable path and log the assumption used.

---

## 10. Definition of done

- Full pipeline runs on the sample (`sample_mode: true`) with all tests green and a `data_quality_report.md` produced.
- The same code runs on full data by changing paths + `sample_mode: false` only.
- `RESULTS.md` reads as a coherent draft results section; every cited number resolves to `findings/` or `tables/`; every empirical parameter resolves from `manifest.json`.
- All conclusions are stated **conditionally** (regime + moneyness + maturity + eligibility) with the liquidity selection-bias caveat attached.
