# DATA_METHODOLOGY.md

APAC Alpha-to-Portfolio - data acquisition and audit methodology.
Markets: China, Hong Kong, India, Japan, South Korea, Singapore, Taiwan. Sample: 2010-01-01
(or the maximum reliable start, with earlier history preserved when a provider returns it) to latest.

## 1. Design principles

This is an **acquisition** task. No alpha portfolios are estimated here. The deliverable is a
reproducible, provenance-complete data layer plus an honest readiness assessment. The pipeline is a
single executable (`scripts/acquire_and_audit.py`) with checkpoint/resume, atomic writes for all
processed and report artifacts, and immutable raw files.

The following works drive specific design decisions. They are cited at the point of use and again here.

- **Ince, O. S., & Porter, R. B. (2006). "Individual Equity Return Data from Thomson Datastream:
  Handle with Care."** *Journal of Financial Research*. Vendor errors (stale prices, unadjusted
  splits, duplicate/zero returns, currency unit errors) are common across international equity
  databases. Principle: never assume one vendor's price is correct; cross-check and clean
  quantitatively, and never mechanically transplant another database's thresholds. This motivates the
  two-source comparison in `source_crosscheck.csv` and the raw-vs-adjusted preservation.
- **Shumway, T. (1997). "The Delisting Bias in CRSP Data."** *Journal of Finance*. Restricting a
  universe to currently-listed firms induces survivorship bias and understates risk. Principle:
  measure and label survivorship rather than hide it. This motivates `historical_universe_audit.csv`
  and the explicit `CURRENT_SURVIVOR_BIAS` label where reconstruction is not possible.
- **Dimson, E. (1979). "Risk Measurement When Shares are Subject to Infrequent Trading."**
  *Journal of Financial Economics*. Nonsynchronous/illiquid trading attenuates contemporaneous market
  betas. Principle: flag stale prices, and offer a Dimson-style lead-lag beta option. The pipeline
  emits `trading_status`/`stale_run` flags and documents the Dimson regression option (Section 7);
  it does not estimate final betas here.
- **Hou, K., Xue, C., & Zhang, L. (2020). "Replicating Anomalies."** *Review of Financial Studies*.
  Microcaps drive many anomalies; liquidity/investability controls are essential. Principle: include
  liquidity and investability controls, and do not add Size/Value/Quality signals without
  point-in-time safety. This is why historical Size/Value/Quality factors are deliberately excluded.
- **Jensen, T. I., Kelly, B., & Pedersen, L. H. (2023). "Is There a Replication Crisis in Finance?"**
  *Journal of Finance*. A globally consistent factor protocol across countries. Principle: use a
  common, documented factor library for country comparison. This motivates the JKP country factors
  (chn, hkg, ind, jpn, kor, sgp, twn) with units preserved as documented.

Direct references: Ince & Porter DOI https://doi.org/10.1111/j.1475-6803.2006.00189.x; Shumway DOI
https://doi.org/10.1111/j.1540-6261.1997.tb03818.x; Dimson DOI
https://doi.org/10.1016/S0304-405X(79)90013-8; Hou, Xue & Zhang DOI
https://doi.org/10.1093/rfs/hhy131; Jensen, Kelly & Pedersen DOI
https://doi.org/10.1111/jofi.13249. These references motivate QC principles; their vendor-, market-,
and sample-specific thresholds are not copied mechanically.

## 2. Raw provenance and immutability

Raw data live under `data/raw/{provider}/{market}/{YYYYMMDD_extraction}/`. Each extraction folder
carries a `manifest.json` recording: provider, exact endpoint, extraction timestamp (UTC), query
parameters, usage/license notes, and per-file original columns, provider ticker, internal security ID,
row counts, date range and SHA-256. Raw files are never overwritten: re-running a completed extraction
reuses existing files (resume); if a manifest already exists, a new timestamped manifest is written
rather than clobbering the old one. The extraction folder name is the run date, so same-day re-runs
resume, and cross-day runs create a new folder rather than mutate history.

## 3. Internal security identifiers

`internal_security_id = {ISO3}_{EXCHANGE}_{NORMALIZED_LOCAL_TICKER}_{SHARE_CLASS}`, e.g.
`JPN_XTKS_7203_ORD`. It is derived only from provider-neutral market, exchange, normalised local
ticker and share class - **not** a Python hash, so it is stable across runs and providers. Exchange
codes are ISO 10383 MICs (XSHG, XSHE, XHKG, XNSE, XTKS, XKRX, XSES, XTAI). Provider tickers are
preserved verbatim in both raw manifests and the security master.

## 4. Universe and security master

Target: 200-500 currently-liquid securities, >= 10 per market, spanning large cap, mid cap, old
listings and recent listings, plus delisted/inactive cases where retrievable (e.g. T39.SI Singapore
Press Holdings - delisted; P34.SI - inactive). The universe is a transparent **current** liquid list;
no official historical constituent files were reachable through the available network, so no
point-in-time index reconstruction is claimed.

`data/security_master_raw.parquet` fields: `internal_security_id, provider, provider_ticker,
local_ticker, company_name, exchange, country, market, currency, security_type, listing_date,
delisting_date_or_status, primary_or_secondary_listing, share_class, sector_or_industry,
metadata_basis, extraction_timestamp_utc`. Sector/industry come from a yfinance current snapshot and
are labelled `metadata_basis = current_snapshot`; listings dates are the first/last observed price
dates. **Historical metadata is never back-filled with current values**; where a field is unknown it
is left `UNKNOWN`/`unresolved`.

## 5. Market data

Primary: yfinance `Ticker.history(start=2010-01-01, auto_adjust=False, actions=True)` preserving raw
Open/High/Low/Close, Adj Close, Dividends and Stock Splits. One checkpointed parquet per ticker.
- `traded_value_est_local_ccy = close * volume` is an **estimate only** (named as such; never called
  official turnover). Where BaoStock returns an official `amount`, it is kept separately as
  `provider_amount_local_ccy`.
- `trading_status` is derived only under named rules: `baostock_tradestatus_eq_0` (official BaoStock
  trading-status for China) or `stale_price_ge5d_heuristic` (>= 5 consecutive equal closes).
- **Split treatment caveat:** Yahoo's OHLC history is historically split-adjusted even with
  `auto_adjust=False` (only dividends flow to Adj Close), whereas BaoStock (`adjustflag=3`) and
  AKShare (`adjust=""`) return truly unadjusted prices. Pre-split price-level differences between
  sources are therefore expected and are surfaced explicitly (`corporate_action_discrepancy =
  YES_LEVEL_SHIFT` in the cross-check and `OHLC_ALREADY_SPLIT_ADJUSTED` in the corporate-action audit)
  rather than treated as errors.
- `prices.currency` is the market default; a few SGX names are quoted in USD (e.g. Jardine Matheson,
  Hongkong Land). Join `security_master` for the instrument-level currency.
Secondary supplements: **BaoStock** (`adjustflag=3`, unadjusted) and **AKShare/Sina**
(`stock_zh_a_daily`, `stock_hk_daily`) for China; **AKShare/Sina** for Hong Kong. India, Japan, Korea,
Singapore, Taiwan have no reachable independent free OHLCV source (Section 6).

## 6. Cross-validation and source availability

For each market, 10 representative securities are compared to a second independent source where
available: China = yfinance vs BaoStock and vs AKShare; Hong Kong = yfinance vs AKShare. Dates are
standardised to date-only and both series are clipped to the common study period before comparison.
Metrics: overlap window, rows per source, matching-date %, median/max absolute raw-close discrepancy
(local currency and bps), return-discrepancy p50/p95/p99/max, missing dates each direction, duplicate
dates, stale sequences, and currency consistency. Disagreements are preserved, never overwritten.

Where no second source is reachable, all 10 sample rows are still emitted with
`status = UNAVAILABLE` and an explicit reason, and the market is barred from `READY`.
**Blocker evidence:** Stooq is unreachable through the network proxy; AKShare exposes no free
daily equity OHLCV for India/Japan/Korea/Singapore/Taiwan; keyed APIs (Alpha Vantage, Tiingo, EODHD)
are unavailable without credentials. There is therefore no two-source security-level validation for
those five markets, and none is fabricated.

## 7. Benchmarks, factors, FX, risk-free, calendars

- **Benchmarks** (local broad index, yfinance fallback clearly labelled): CSI 300, Hang Seng, Nifty 50,
  Nikkei 225, KOSPI, Straits Times, TAIEX. All rows carry `source_label = yfinance_fallback`.
- **JKP Global Factor Data** (Jensen, Kelly & Pedersen 2023) country factors for chn/hkg/ind/jpn/kor/
  sgp/twn: `momentum`, `low_risk` and `all_themes`, monthly, value-weighted. Raw zips retained; units
  preserved as `decimal_excess_return_usd` (the values are already decimal, not percent).
- **Kenneth French** `Japan`, `Asia_Pacific_ex_Japan` and `Developed` daily 3-factor files where
  geography overlaps. Units converted from **percent to decimals** (`/100`).
- **FX**: seven pairs (`CNY=X ... TWD=X`); direction explicit as `local_per_usd` (units of local
  currency per 1 USD). To convert a local price to USD, divide by the rate.
- **Risk-free proxy**: `^IRX` (13-week US T-bill discount yield), stored in percent, yfinance fallback.
- **Calendars**: derived from benchmark price dates and labelled `DERIVED_FROM_PRICE_DATES` (not an
  official exchange calendar feed).
- **Transaction costs**: `data/reference/transaction_costs.csv` records current stamp-duty / transfer
  tax schedules with source URLs, all labelled `CURRENT_ONLY_NOT_HISTORICALLY_VERIFIED`. Historical
  effective-date schedules were **not** independently verified and are not invented.

**Dimson lead-lag option (documented, not estimated here):** for illiquid markets, regress security
return on contemporaneous and lagged (and optionally lead) market returns,
`r_i,t = a + b0*rm_t + b1*rm_{t-1} (+ b2*rm_{t+1}) + e`, and sum the betas. This mitigates the Dimson
(1979) attenuation caused by stale prices flagged in `trading_status`. Final alpha portfolios are out
of scope for this acquisition task.

## 8. Units and conventions

Returns are decimals. French returns are converted from percent. JKP units are preserved as
documented. FX direction is explicit. Raw Close and Adj Close are both retained and distinctly named.
No impossible future dates; no duplicate `(provider, internal_security_id, date)` keys within a
provider series.

## 9. Acceptance and safety

Processed masters and reports are written atomically (temp file + `os.replace`). Parquet readability
and schemas are asserted in `tests/test_pipeline.py`, which runs in the same `.venv`. Required outputs,
unique keys, date ranges, units, FX direction and benchmark mapping are checked. Failed downloads are
never silently passed: missing sources become `UNAVAILABLE`/`FAILED` rows and reduce the market's
readiness. `reports/data_acquisition_report.md` ends with the exact readiness table
`Market | Prices | Corporate actions | Historical universe | Benchmark | FX | Status`, assigning only
`READY`, `READY WITH LIMITATIONS` or `NOT READY`. A market cannot be `READY` if its requested
two-source 10-security validation failed.

## 10. Limitations

- Only China and Hong Kong achieve independent two-source validation; the other five markets cannot be
  `READY` and are `READY WITH LIMITATIONS` (single-source prices).
- The universe is current and therefore survivorship-prone outside China/Hong Kong; labelled
  `CURRENT_SURVIVOR_BIAS`.
- Transaction-cost and calendar references are current/derived, not historical/official.
- No historical Size/Value/Quality factors are included (point-in-time safety not proven).
