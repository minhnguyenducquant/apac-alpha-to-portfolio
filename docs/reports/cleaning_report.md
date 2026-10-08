# APAC Alpha-to-Portfolio - Data Cleaning & Monthly Research Panel Report

Generated: 2026-10-07T08:25:55Z | Base currency: USD | Frozen method: METHODOLOGY_DATA_CLEANING.md

## Method summary

- Primary source is **yfinance**; BaoStock/AKShare rows are cross-check only and **do not overwrite** the raw yfinance series (`source_role` column retained).

- Monthly total returns use yfinance **Adj Close** close-to-close between consecutive **actual** month-end observations, only where both endpoints are positive and non-null. No forward fill, no interpolation. Raw close/dividends/splits are retained.

- Invalid prices (<=0/null) are flagged and the return pair excluded; missing returns are logged.

- `daily_prices_clean` distinguishes **TRADED / STALE / SUSPENDED** rows (`trading_state`, `is_traded`, `is_stale`, `is_suspended`) and carries `total_return_1d` plus the local benchmark return mapped on **actual overlapping dates** (`benchmark_ticker`, `benchmark_source_label`, `benchmark_return_1d`).

- Signals are trailing point-in-time (no lookahead). `mom_12_1` compounds **exactly 11** monthly returns keyed `t-12..t-2` (month `t-1` excluded), product(1+r)-1. Risk `vol_60`/`vol_252`, `beta`, `dimson_beta`, `ivol` use 60/252 market sessions with minimum 40/126 **traded** observations; zero-volume/stale/suspended sessions are masked (traded zero returns stay valid). Liquidity `median_daily_traded_value`, `amihud`, `trading_frequency` use a trailing 60 market-session window with >=40 valid traded observations, in **local-currency** units (frequency = traded observations / 60 sessions). `next_month_return` is the **future** target (t+1) and never enters `eligible_universe` or any signal.

- `eligible_universe` applies the point-in-time listing-date proxy gate, signal/risk availability, and the fixed lagged investability control (exclude the bottom 20th percentile of trailing median daily traded value within market and formation month, among otherwise-eligible names). Every exclusion reason is preserved in `eligible_reason`. The 20th-percentile cut is a fixed control, never optimized.

- Source listing dates are first-observed-price **proxies**, not true IPOs; the pipeline states this and falls back to the first observed primary date where the field is blank. Known delisting **dates** are respected where genuinely parseable (Prompt 1 stores statuses, not dates).

- Consumer aliases `security_id`, `ticker`, `country` and `data_quality_flag` are added; internal ids (`internal_security_id`, `provider_ticker`) are retained. **No sector neutralization** is applied.

- Duplicate `(provider, security, date)` keys block processing unless exactly equal; exact duplicates would be dropped with a log. Prompt 1 data contains **zero** duplicate keys.

- Investment vehicles (REIT/trust/units/fund/ETF/CEF/preferred/warrant/right/ADR/DR/receipt) are excluded from the core panel via stored name/type fields and **retained in the audit**; the exclusion is a documented name heuristic.

- **No alpha/performance tests are conducted here**; this is a data and panel construction stage. **US-specific sample filters are not transplanted to APAC.**

## Input integrity (read-only)

- `prices` sha256 `0548d4d4e071b24c...`

- `security_master_raw` sha256 `0b128a493b5b59ca...`

- `security_master` sha256 `0b128a493b5b59ca...`

- `benchmarks` sha256 `80ff2ab6ac774186...`

- `source_crosscheck` sha256 `ea5ab982f578f7f4...`

- `historical_universe_audit` sha256 `d4c1d213abc49cb8...`

- `corporate_action_audit` sha256 `6327f13e8032d668...`

## Panel and coverage

- Daily clean rows: **1,373,828** across 219 securities (3 providers).

- Monthly panel rows: **40,782** across 210 core common-equity securities, 2010-01 to 2026-10.

- Investment vehicles excluded from core panel: **8** (retained in `security_master_clean.parquet`).

- QC charts produced: **12** in `reports/charts/cleaning/`.


## Universe QC (per market)

| market   |   n_master |   n_with_prices |   n_missing_prices |   n_core_included |   n_excluded_investment_vehicle |   n_delisted_or_inactive | delisting_coverage   |   deliverable_crosscheck_ok | source_audit_classification   | survivorship_flag                                        | survivorship_bias_cured   |   n_secondary_or_special | price_history_start   | price_history_end   | metadata_basis   |
|:---------|-----------:|----------------:|-------------------:|------------------:|--------------------------------:|-------------------------:|:---------------------|----------------------------:|:------------------------------|:---------------------------------------------------------|:--------------------------|-------------------------:|:----------------------|:--------------------|:-----------------|
| CN       |         34 |              34 |                  0 |                34 |                               0 |                        0 | 0/34                 |                          30 | HISTORICAL_UNIVERSE_RELIABLE  | SURVIVOR_BIAS_LABEL_QUESTIONABLE_DELISTING_COVERAGE_ZERO | False                     |                        0 | 2010-01-04            | 2026-09-30          | current_snapshot |
| HK       |         38 |              37 |                  1 |                37 |                               1 |                        0 | 0/38                 |                          10 | HISTORICAL_UNIVERSE_RELIABLE  | SURVIVOR_BIAS_LABEL_QUESTIONABLE_DELISTING_COVERAGE_ZERO | False                     |                        0 | 2010-01-04            | 2026-10-07          | current_snapshot |
| IN       |         30 |              29 |                  1 |                30 |                               0 |                        0 | 0/30                 |                           0 | CURRENT_SURVIVOR_BIAS         | CURRENT_SURVIVOR_BIAS                                    | False                     |                        0 | 2010-01-04            | 2026-10-07          | current_snapshot |
| JP       |         30 |              30 |                  0 |                30 |                               0 |                        0 | 0/30                 |                           0 | CURRENT_SURVIVOR_BIAS         | CURRENT_SURVIVOR_BIAS                                    | False                     |                        0 | 2010-01-04            | 2026-10-07          | current_snapshot |
| KR       |         30 |              30 |                  0 |                30 |                               0 |                        0 | 0/30                 |                           0 | CURRENT_SURVIVOR_BIAS         | CURRENT_SURVIVOR_BIAS                                    | False                     |                        0 | 2010-01-04            | 2026-10-07          | current_snapshot |
| SG       |         30 |              28 |                  2 |                23 |                               7 |                        2 | 2/30                 |                           0 | CURRENT_SURVIVOR_BIAS         | CURRENT_SURVIVOR_BIAS                                    | False                     |                        0 | 2010-01-04            | 2026-10-07          | current_snapshot |
| TW       |         30 |              30 |                  0 |                30 |                               0 |                        0 | 0/30                 |                           0 | CURRENT_SURVIVOR_BIAS         | CURRENT_SURVIVOR_BIAS                                    | False                     |                        0 | 2010-01-04            | 2026-10-07          | current_snapshot |



## Signal QC (per market)

| market   |   n_securities |   n_obs_months |   n_return_valid |   n_return_missing |   return_valid_pct | first_month   | last_month   |   mean_monthly_return |   std_monthly_return |   min_monthly_return |   max_monthly_return |       p01 |        p50 |      p99 |   n_outliers_abs_gt_50pct |   zero_return_pct |   n_invalid_price_daily |   n_eligible |   eligible_pct |   n_below_liquidity_cutoff |   n_pre_listing |   n_data_quality_ok |   n_mom_12_1 |   n_vol_60 |   n_vol_252 |   n_beta |   n_dimson_beta |   n_ivol |   n_median_daily_traded_value |   n_amihud |   n_trading_frequency |   n_next_month_return | benchmark_ticker   | benchmark_source_label   |
|:---------|---------------:|---------------:|-----------------:|-------------------:|-------------------:|:--------------|:-------------|----------------------:|---------------------:|---------------------:|---------------------:|----------:|-----------:|---------:|--------------------------:|------------------:|------------------------:|-------------:|---------------:|---------------------------:|----------------:|--------------------:|-------------:|-----------:|------------:|---------:|----------------:|---------:|------------------------------:|-----------:|----------------------:|----------------------:|:-------------------|:-------------------------|
| CN       |             34 |           6496 |             6462 |                 34 |            99.4766 | 2010-01       | 2026-09      |            0.0119744  |            0.0948783 |            -0.388298 |             0.964078 | -0.196963 | 0.00312687 | 0.303119 |                        11 |            1.1452 |                       0 |         4766 |        73.3682 |                       1227 |               0 |                6462 |         6054 |       6370 |        6279 |        0 |               0 |        0 |                          6370 |       6370 |                  6370 |                  6462 | 000300.SS          | yfinance_fallback        |
| HK       |             36 |           6560 |             6524 |                 36 |            99.4512 | 2010-01       | 2026-10      |            0.00931652 |            0.0920318 |            -0.403491 |             0.585695 | -0.212355 | 0.00491692 | 0.288294 |                        10 |            0.6284 |                       0 |         4871 |        74.253  |                       1221 |               0 |                6524 |         6092 |       6486 |        6340 |     6340 |            6340 |     6340 |                          6488 |       6486 |                  6488 |                  6524 | ^HSI               | yfinance_fallback        |
| IN       |             29 |           5848 |             5819 |                 29 |            99.5041 | 2010-01       | 2026-10      |            0.0142253  |            0.0801004 |            -0.502694 |             0.532394 | -0.170939 | 0.0107427  | 0.235595 |                         2 |            0.0687 |                       0 |         4337 |        74.1621 |                       1134 |               0 |                5819 |         5471 |       5790 |        5674 |     5674 |            5674 |     5674 |                          5790 |       5790 |                  5790 |                  5819 | ^NSEI              | yfinance_fallback        |
| JP       |             30 |           5992 |             5962 |                 30 |            99.4993 | 2010-01       | 2026-10      |            0.0142434  |            0.0779365 |            -0.378348 |             0.47446  | -0.167983 | 0.0114982  | 0.220075 |                         0 |            0.2684 |                       0 |         4468 |        74.5661 |                       1134 |               0 |                5962 |         5602 |       5932 |        5812 |     5812 |            5812 |     5812 |                          5932 |       5932 |                  5932 |                  5962 | ^N225              | yfinance_fallback        |
| KR       |             30 |           5607 |             5577 |                 30 |            99.465  | 2010-01       | 2026-10      |            0.0132485  |            0.109804  |            -0.477106 |             1.55649  | -0.226334 | 0.00453001 | 0.364935 |                        22 |            0.6634 |                       0 |         4138 |        73.8006 |                       1075 |               0 |                5577 |         5217 |       5542 |        5425 |     5425 |            5425 |     5425 |                          5542 |       5542 |                  5542 |                  5577 | ^KS11              | yfinance_fallback        |
| SG       |             21 |           4242 |             4221 |                 21 |            99.505  | 2010-01       | 2026-10      |            0.0134696  |            0.105629  |            -0.5      |             2.17549  | -0.155437 | 0.00492914 | 0.227123 |                        17 |            1.8716 |                       0 |         3173 |        74.7996 |                        756 |               0 |                4221 |         3969 |       4161 |        4101 |     4101 |            4101 |     4101 |                          4169 |       4161 |                  4161 |                  4221 | ^STI               | yfinance_fallback        |
| TW       |             30 |           6037 |             6007 |                 30 |            99.5031 | 2010-01       | 2026-10      |            0.0148411  |            0.090342  |            -0.358904 |             1.21379  | -0.189566 | 0.00874672 | 0.290731 |                        24 |            1.7313 |                       0 |         4513 |        74.7557 |                       1134 |               0 |                6007 |         5647 |       5977 |        5857 |     5857 |            5857 |     5857 |                          5977 |       5977 |                  5977 |                  6007 | ^TWII              | yfinance_fallback        |



## Survivorship - explicit, not cured

The Prompt 1 audit labels CN/HK `HISTORICAL_UNIVERSE_RELIABLE`, but this is **questionable**: `delisting_coverage = 0/N` in every market despite two-source prices for CN/HK. IN/JP/KR/SG/TW are explicit `CURRENT_SURVIVOR_BIAS`. The panel carries `survivorship_flag`, `source_audit_classification`, `delisting_coverage` and `survivorship_bias_cured = False` on every row. No reconstruction is claimed and **no market is described as survivorship-free**.


## Corporate-action warning

Vendor OHLC is historically split-adjusted even with `auto_adjust=False`. Total returns therefore use Adj Close, and dividends/splits are **not applied a second time** (`corporate_events_applied_again = False` on every row).


## Cleaning log summary

- `panel_build`: 40,782 records

- `survivorship`: 222 records

- `missing_return`: 210 records

- `security_type_exclusion`: 16 records

- `name_heuristic`: 8 records

- `invalid_price`: 0 records

- `duplicate_check`: 0 records

- `price_coverage`: 0 records


## References (methodological foundations)

- Ince, O. S., & Porter, R. B. (2006). *Journal of Financial Research*. https://doi.org/10.1111/j.1475-6803.2006.00189.x

- Shumway, T. (1997). *Journal of Finance*. https://doi.org/10.1111/j.1540-6261.1997.tb03818.x

- Dimson, E. (1979). *Journal of Financial Economics*. https://doi.org/10.1016/0304-405X(79)90013-8

- Hou, K., Xue, C., & Zhang, L. (2020). *Review of Financial Studies*. https://doi.org/10.1093/rfs/hhy131

- Novy-Marx, R., & Velikov, M. (2016). *Review of Financial Studies*. https://doi.org/10.1093/rfs/hhv063

- Jegadeesh, N., & Titman, S. (1993). *Journal of Finance*. https://doi.org/10.1111/j.1540-6261.1993.tb04702.x

- Fama, E. F., & French, K. R. (2012). *Journal of Financial Economics*. https://doi.org/10.1016/j.jfineco.2011.09.004

- Asness, C. S., Moskowitz, T. J., & Pedersen, L. H. (2013). *Journal of Finance*. https://doi.org/10.1111/jofi.12021

- Frazzini, A., & Pedersen, L. H. (2014). *Journal of Finance*. https://doi.org/10.1111/jofi.12234

- Ang, A., Hodrick, R. J., Xing, Y., & Zhang, X. (2009). *Journal of Finance*. https://doi.org/10.1111/j.1540-6261.2009.01483.x

- Hou, K., Karolyi, G. A., & Kho, B.-C. (2011). *Journal of Finance*. https://doi.org/10.1111/j.1540-6261.2011.01671.x


## Limitations

- Survivorship bias is flagged, not solved; the universe is a current snapshot.

- Only CN/HK have independent price cross-checks; other markets are single-source.

- Benchmark mapping uses each market's actual primary yfinance index on overlapping dates. The CN series `000300.SS` contains a **single daily row** in Prompt 1, so CN `beta`, `dimson_beta` and `ivol` are missing (all other markets have ~99% benchmark overlap). This is reported, not imputed; CN remains eligible on stock-only signals. The CN local benchmark data limit is a real blocker for CN market-model risk and is **not** claimed as completed.

- Source listing dates are first-observed-price proxies, not true IPO dates; delisting statuses carry no parseable dates, so the point-in-time delisting gate is inert in this dataset.

- `median_daily_traded_value`, `amihud` and `trading_frequency` use the close*volume turnover estimate over trailing traded observations; they are not official turnover.

- Security-type exclusion is name/type-heuristic; unlabelled vehicles may remain and unlisted share classes may be flagged. Full exclusion list is logged for review.

- Historical sector/industry metadata is a current snapshot only.

