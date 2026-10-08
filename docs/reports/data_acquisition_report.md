# APAC Alpha-to-Portfolio - Data Acquisition Report

Run ID: `20261007` | Generated: 2026-10-07T07:21:46Z | Base currency: USD

## Method

Raw OHLCV from yfinance with `auto_adjust=False, actions=True` (raw OHLC, Adj Close, dividends, splits). Independent supplements: BaoStock and AKShare (Sina) for China; AKShare for Hong Kong. Benchmark/factor/FX acquisitions are labeled by source. Processed and report writes are atomic; raw files are immutable and re-runs resume the same extraction folder.

## Cross-validation coverage

- China: 30 OK / 30 tested rows
- Hong Kong: 10 OK / 10 tested rows
- India: 0 OK / 10 tested rows
- Japan: 0 OK / 10 tested rows
- South Korea: 0 OK / 10 tested rows
- Singapore: 0 OK / 10 tested rows
- Taiwan: 0 OK / 10 tested rows

## Chart inventory

- `reports/charts/01_coverage_by_market_source.png`
- `reports/charts/02_missing_observations.png`
- `reports/charts/03_cross_source_discrepancy.png`
- `reports/charts/04_tradable_through_time.png`
- `reports/charts/05_suspension_stale.png`
- `reports/charts/06_corporate_action_conflicts.png`

## Unresolved blockers

- Independent two-source validation achieved only for China and Hong Kong. India, Japan, Korea, Singapore and Taiwan: Stooq blocked by network, AKShare has no free OHLCV for these markets, and no-key APIs (Alpha Vantage/Tiingo/EODHD) unavailable. Rows retained as UNAVAILABLE.
- Transaction-cost schedules are CURRENT_ONLY and not historically verified.
- Trading calendars and listing dates are derived/labeled, not official exchange feeds.

## Status detail

- **China** (READY): two-source validation passed
- **Hong Kong** (READY): two-source validation passed
- **India** (READY WITH LIMITATIONS): requested two-source 10-security cross-validation unavailable: no independent secondary OHLCV source reachable
- **Japan** (READY WITH LIMITATIONS): requested two-source 10-security cross-validation unavailable: no independent secondary OHLCV source reachable
- **South Korea** (READY WITH LIMITATIONS): requested two-source 10-security cross-validation unavailable: no independent secondary OHLCV source reachable
- **Singapore** (READY WITH LIMITATIONS): requested two-source 10-security cross-validation unavailable: no independent secondary OHLCV source reachable
- **Taiwan** (READY WITH LIMITATIONS): requested two-source 10-security cross-validation unavailable: no independent secondary OHLCV source reachable

## Final readiness table

| Market | Prices | Corporate actions | Historical universe | Benchmark | FX | Status |
|---|---|---|---|---|---|---|
| China | OK | OK | RELIABLE | OK | OK | READY |
| Hong Kong | OK | OK | RELIABLE | OK | OK | READY |
| India | OK | OK | SURVIVOR_BIAS | OK | OK | READY WITH LIMITATIONS |
| Japan | OK | OK | SURVIVOR_BIAS | OK | OK | READY WITH LIMITATIONS |
| South Korea | OK | OK | SURVIVOR_BIAS | OK | OK | READY WITH LIMITATIONS |
| Singapore | OK | OK | SURVIVOR_BIAS | OK | OK | READY WITH LIMITATIONS |
| Taiwan | OK | OK | SURVIVOR_BIAS | OK | OK | READY WITH LIMITATIONS |
