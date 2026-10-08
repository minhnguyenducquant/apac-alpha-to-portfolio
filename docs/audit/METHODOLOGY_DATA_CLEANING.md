# METHODOLOGY_DATA_CLEANING.md

APAC Alpha-to-Portfolio - monthly research panel cleaning methodology.
This document is **frozen before tests** (`tests/test_cleaning.py`) and governs
`scripts/clean_and_build_panel.py`.

## 0. Scope and inputs (read-only)

This stage consumes only Prompt 1 artifacts and never writes under `data/raw/`
and never overwrites Prompt 1 outputs:

- `data/processed/prices.parquet` (primary yfinance + secondary BaoStock/AKShare)
- `data/processed/benchmarks.parquet`
- `data/processed/security_master.parquet` / `data/security_master_raw.parquet`
- `reports/source_crosscheck.csv`, `reports/historical_universe_audit.csv`,
  `reports/corporate_action_audit.csv`

Extraction snapshots under `data/raw/**/YYYYMMDD_extraction/` are preserved
untouched; their manifests remain the provenance source of record.

## 1. Source hierarchy - no overwrite

- **Primary source is yfinance.** The research monthly panel and all return
  columns are built from yfinance rows only.
- BaoStock and AKShare rows for China/Hong Kong exist for cross-validation
  only. The A-share (`CN`) secondary price series **do not automatically
  overwrite or supersede** the yfinance raw series. Every daily row carries
  `source_role` (`primary` / `secondary`); secondary rows keep their raw
  fields and are retained in `daily_prices_clean.parquet` and in the Prompt 1
  cross-check, but never enter the panel's return computation.

## 2. Daily cleaning

Applied to `prices.parquet` (all providers), producing
`daily_prices_clean.parquet`:

- Dates normalised to day precision.
- Numeric coercion of `open/high/low/close/adj_close/volume/dividends/stock_splits`.
- `close_valid = close > 0 and close is not null`.
- `adj_close_valid = adj_close > 0 and adj_close is not null` (false for
  secondary sources, which carry no adjusted close).
- **Invalid prices (`close <= 0` or null) are flagged, never imputed.** A
  return pair touching an invalid price is excluded (Section 3).
- `return_eligible = primary AND close_valid AND adj_close_valid`.
- **No price forward fill**, anywhere, for any reason.
- Duplicate keys `(provider, internal_security_id, date)`:
  - a **non-exact** duplicate (same key, different values) **blocks
    processing** - the script aborts rather than silently choose a row;
  - **exact** duplicates (identical values on all OHLCV/action columns) may be
    de-duplicated keeping the first, and the action is logged. Prompt 1 data
    contains zero duplicate keys, so the branch is a guard, not an edit.
- Per-security daily `total_return_1d` is `adj_close.pct_change()` where
  `return_eligible`, else missing.
- **True trade/suspension distinction** (`trading_state`):
  `TRADED` (positive volume, no provider halt flag), `STALE` (provider flagged a
  >=5-day unchanged quote), `SUSPENDED` (halt flag or zero/null volume). Boolean
  mirrors `is_traded`, `is_stale`, `is_suspended`. These are never inferred from
  returns.
- Each local row is mapped to its market's **actual primary yfinance benchmark**
  on **actual overlapping dates**, carrying `benchmark_ticker`,
  `benchmark_source_label` and the decimal `benchmark_return_1d`.
- Constant warning columns:
  - `ohlc_vendor_split_adjusted = True` - vendor OHLC history is historically
    split-adjusted even with `auto_adjust=False`;
  - `corporate_events_applied_again = False` - dividends/splits are **not**
    re-applied to raw close (Adj Close already embeds them).

## 3. Monthly total returns (the named model)

Built from primary yfinance rows with `date >= 2010-01-01` (earlier daily
history is preserved in `daily_prices_clean.parquet`, flagged
`in_study_period = False`).

1. Month-end observation per security = the **last actual trading observation**
   in each calendar month (no resampling fill, no forward fill).
2. A return pair is `(month t, month t-1)` only when the prior observation is
   in the **immediately preceding calendar month** (no cross-gap "monthly"
   returns).
3. `monthly_total_return = adj_close_t / adj_close_{t-1} - 1`, computed **only
   where both endpoint `adj_close` are positive and non-null** throughout the
   observation pair.
4. Otherwise the return is **missing** and the reason is logged:
   `first_observation`, `gap_no_prior_month`, or `invalid_price_pair`.
5. Raw `close`, `dividends` and `stock_splits` are retained: the panel carries
   `monthly_raw_close`, `monthly_adj_close`, `monthly_dividend_sum` and
   `monthly_split_sum` so the total-return construction is auditable.

Because return construction uses Adj Close, **no corporate action is applied a
second time**.

## 3b. Point-in-time signals and the forward target

All signals are trailing, inclusive of the observation date, and use only
information available at that date (no lookahead). Windows are counted in the
market's trading sessions; each security's series is reindexed to its market's
session calendar so session counts are correct when a provider omits a row.

- `mom_12_1` - 12-1 momentum is the **compounded product of exactly 11 monthly
  return cells keyed `t-12 .. t-2`**, i.e. `prod_{m=t-12}^{t-2} (1 + r_m) - 1`,
  excluding month `t-1`. It is built on a gap-aware monthly grid; **all 11 cells
  must be non-missing**. On a complete grid the product telescopes to
  `P_{t-2} / P_{t-13} - 1`. It is never the simple price ratio
  `P_{t-1}/P_{t-12}`, and it does not use any information from `t-1` or `t`.
- `vol_60`, `vol_252` - annualised (`sqrt(252)`) std of daily total returns over
  60 / 252 **traded** sessions with `min_periods` 40 / 126. `vol_60` is the
  **primary** low-risk signal; `vol_252` is a longer-window **robustness** check.
  Zero-volume, stale and suspended sessions are masked; a genuine traded **zero
  return is a valid observation** and is retained.
- `beta`, `ivol` - market model vs the market benchmark on actual overlapping
  traded dates: `beta = cov(r_i, r_m)/var(r_m)`; `ivol = sqrt(var(r_i) -
  beta*cov) * sqrt(252)`, clipped at zero; minimum 126 valid observations.
- `dimson_beta` - Dimson (1979) sum of OLS betas on contemporaneous and one
  lagged benchmark return, correcting for infrequent trading; same 126 minimum
  and traded-session masking.
- `median_daily_traded_value` - trailing median of `close*volume` (the local
  turnover estimate) over **60 market-session rows**, requiring **>= 40 valid
  traded observations**. Kept in local-currency units.
- `amihud` - trailing mean of `|r_i| / traded_value` over the same 60-session
  window with >= 40 valid traded observations (Amihud 2002); local-currency.
- `trading_frequency` - trailing count of valid `TRADED` observations divided by
  60 sessions.
- `next_month_return` - the security's `monthly_total_return` in calendar month
  `t+1`; it is the **future target** and is deliberately kept out of every signal
  and out of `eligible_universe`.
- `eligible_universe` - point-in-time investability. A security-month is eligible
  only if ALL hold:
  1. **listing-date proxy gate** - formation month-end `>= listing_date_proxy`,
     and not after a genuinely parseable delisting date. Source `listing_date`
     values are **first-observed-price proxies, not true IPO dates**; where the
     field is blank the security's first observed primary price date is used.
     Prompt 1 stores delisting **statuses** (`active`/`delisted`/`inactive`)
     without dates, so the delisting gate is inert in this dataset.
  2. **signal/risk availability** - `return_pair_valid`, positive month-end
     close, non-null `mom_12_1`, non-null `vol_252`.
  3. **liquidity availability** - non-null `median_daily_traded_value` and
     non-null `trading_frequency`.
  4. **lagged investability control** - drop the bottom 20th percentile of
     trailing `median_daily_traded_value` within `(market, formation month)`,
     computed among otherwise-eligible securities. This quintile cut is a
     **fixed control, never optimized** for performance.
  Every failing reason is preserved in `eligible_reason` (`pre_listing`,
  `post_delisting`, `no_valid_return`, `bad_price`, `no_mom_12_1`,
  `no_vol_252`, `no_liquidity`, `no_trading_frequency`,
  `below_liquidity_cutoff`).
- Cross-sectional ranks are percentiles within `(market, month)`. Orientation is
  uniform: **higher rank means the higher expected-return / lower-risk direction.**
  `mom_rank` increases with momentum; `lowrisk_rank` is the descending rank of
  `vol_60` (low volatility -> high rank); `beta_rank` is the descending rank of
  `beta` (low beta -> high rank); `ivol_rank` is the descending rank of `ivol`
  (low idiosyncratic volatility -> high rank). `liquidity_rank` is a **control**,
  not an alpha signal: higher score means more liquid (ascending rank of
  `median_daily_traded_value`).
- Consumer aliases `security_id` (= `internal_security_id`), `ticker`
  (= `provider_ticker`), `country` and `data_quality_flag`
  (`OK` / `NO_RETURN_PAIR` / `INVALID_PRICE`) are added; internal ids are
  retained. **No sector neutralization** is applied.
- Benchmark mapping preserves `benchmark_ticker`, `benchmark_source_label` and
  `benchmark_monthly_return`. The CN `000300.SS` series has a single daily row in
  Prompt 1, so CN `beta`/`dimson_beta`/`ivol` are genuinely missing and reported,
  never imputed. This is a real CN local-benchmark data blocker, not a completed
  requirement.
- **No alpha or performance tests are conducted at this stage**, and
  **US-specific sample filters are not transplanted to APAC**; thresholds and
  windows are stated here and applied uniformly to the APAC sample.

## 4. Security-type exclusion (investment vehicles)

Exclusion uses **only stored provider master fields** (`security_type` and
`company_name`); no external classification is invented. Matched tokens
(word-bounded, case-insensitive), retained in full in the log:

`ETF`, `FUND`, `REIT`, `PREFERRED`, `WARRANT`, `RIGHT`, `ADR`, `DR`/`GDR`,
`DEPOSITARY RECEIPT`, `UNITS`, `TRUST`, `CEF`/`CLOSED-END`.

- `instrument_class` = `COMMON_EQUITY`, `INVESTMENT_VEHICLE` (REIT/trust/units)
  or `FUND` (ETF/fund/CEF).
- `excluded_from_core = instrument_class != COMMON_EQUITY`.
- SG/HK REITs and trusts are genuinely exchange-listed, investable securities,
  but the user instruction excludes **investment vehicles, not operating-company
  common equity**. They are therefore excluded from the core panel **and
  retained, with reason, in `security_master_clean.parquet` and
  `reports/data_cleaning_log.csv`** - raw metadata is never deleted.
- This is a **name heuristic**, explicitly marked
  `name_heuristic_limitation = True`; word boundaries prevent false positives
  (e.g. "Mahindra" is not `DR`).
- A `secondary_share_class_audit` field records
  `primary_or_secondary_listing`, `share_class` and name-heuristic token
  matches (`SECOND_LINE`, `H_SHARE`, `A_SHARE`, `ADR`); raw columns stay intact.

## 5. Survivorship - labelled, not cured

The Prompt 1 `historical_universe_audit.csv` says `CURRENT_SURVIVOR_BIAS` for
IN, JP, KR, SG, TW and `HISTORICAL_UNIVERSE_RELIABLE` for CN, HK - but the
CN/HK label is **questionable because `delisting_coverage = 0/N`** despite
two-source prices. This pipeline therefore:

- carries the source audit's `classification` through unchanged as
  `source_audit_classification`;
- sets `survivorship_flag`:
  - IN/JP/KR/SG/TW -> `CURRENT_SURVIVOR_BIAS`;
  - CN/HK -> `SURVIVOR_BIAS_LABEL_QUESTIONABLE_DELISTING_COVERAGE_ZERO`;
- sets `survivorship_bias_cured = False` everywhere;
- records `delisting_coverage` (`n_delisted_or_inactive / n_securities`) and
  per-security `delisting_date_or_status`.

No reconstruction is attempted and no market is described as survivorship-free.

## 6. Outputs

- `data/processed/daily_prices_clean.parquet`
- `data/processed/monthly_research_panel.parquet`
- `data/processed/security_master_clean.parquet`
- `reports/data_cleaning_log.csv`
- `reports/universe_qc.csv`
- `reports/signal_qc.csv`
- `reports/cleaning_report.md`
- `reports/charts/cleaning/01..12_*.png` (12 figures, each with
  source/period/units/interpretation captions)

## 7. References (DOI)

- Ince, O. S., & Porter, R. B. (2006). "Individual Equity Return Data from
  Thomson Datastream: Handle with Care." *Journal of Financial Research*.
  https://doi.org/10.1111/j.1475-6803.2006.00189.x
- Shumway, T. (1997). "The Delisting Bias in CRSP Data." *Journal of Finance*.
  https://doi.org/10.1111/j.1540-6261.1997.tb03818.x
- Dimson, E. (1979). "Risk Measurement When Shares are Subject to Infrequent
  Trading." *Journal of Financial Economics*.
  https://doi.org/10.1016/0304-405X(79)90013-8
- Hou, K., Xue, C., & Zhang, L. (2020). "Replicating Anomalies." *Review of
  Financial Studies*. https://doi.org/10.1093/rfs/hhy131
- Novy-Marx, R., & Velikov, M. (2016). "A Taxonomy of Anomalies and Their
  Trading Costs." *Review of Financial Studies*.
  https://doi.org/10.1093/rfs/hhv063
- Jegadeesh, N., & Titman, S. (1993). "Returns to Buying Winners and Selling
  Losers." *Journal of Finance*.
  https://doi.org/10.1111/j.1540-6261.1993.tb04702.x
- Fama, E. F., & French, K. R. (2012). "Size, Value, and Momentum in
  International Stock Returns." *Journal of Financial Economics*.
  https://doi.org/10.1016/j.jfineco.2011.09.004
- Asness, C. S., Moskowitz, T. J., & Pedersen, L. H. (2013). "Value and
  Momentum Everywhere." *Journal of Finance*.
  https://doi.org/10.1111/jofi.12021
- Frazzini, A., & Pedersen, L. H. (2014). "Betting Against Beta." *Journal of
  Financial Economics*. https://doi.org/10.1111/jofi.12234
- Ang, A., Hodrick, R. J., Xing, Y., & Zhang, X. (2009). "The Cross-Section of
  Volatility and Expected Returns." *Journal of Finance*.
  https://doi.org/10.1111/j.1540-6261.2009.01483.x
- Hou, K., Karolyi, G. A., & Kho, B.-C. (2011). "What Factors Drive Global
  Stock Returns?" *Journal of Finance*.
  https://doi.org/10.1111/j.1540-6261.2011.01671.x

These works motivate QC and signal-construction principles only. Their
US-specific sample filters and thresholds are **not** transplanted to APAC, and
no alpha/performance tests are run here.

## 8. Limitations

- Only two markets (CN, HK) have any independent price cross-check, and even
  there, delisting coverage is zero: survivorship bias is flagged, not solved.
- The CN local benchmark (`000300.SS`) has one row in Prompt 1, so CN
  `beta`/`dimson_beta`/`ivol` remain missing; this blocker is reported, not
  worked around.
- Source listing dates are first-observed-price proxies, not true IPOs;
  delisting statuses carry no parseable dates, so the delisting gate is inert.
- Historical metadata (sector/industry) is a current snapshot only.
- Security-type exclusion is name-heuristic and may miss unlabelled vehicles or
  flag unlisted share classes; the full exclusion list is logged for review.
- Monthly returns are missing (not interpolated) at listing edges, gaps and
  invalid-price pairs.
