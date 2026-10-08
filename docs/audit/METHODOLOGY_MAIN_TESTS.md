# METHODOLOGY_MAIN_TESTS.md — APAC Alpha-to-Portfolio, Main Empirical Tests

**Status:** FROZEN BEFORE EMPIRICAL CALCULATION. No alpha tests had been run at the
time this specification was written. This document and `SPECIFICATION_REGISTRY.csv`
were written first; `scripts/run_main_tests.py` executes exactly the specifications
recorded here. Any later change is an amendment and must be logged, not silently
applied.

**Model:** OpenCode `opencode-go/deepseek-v4.1-flash`. **Network:** none. All inputs
are prior Prompt 1–2 artifacts; none are modified.

---

## 0. Scope, inputs and provenance

Inputs (read-only):

| File | Role |
|------|------|
| `data/processed/monthly_research_panel.parquet` | monthly security panel, signals, target |
| `data/processed/factors_jkp.parquet` | JKP country factor returns (external validation) |
| `data/processed/factors_french.parquet` | French regional factors (limited external check) |
| `data/processed/benchmarks.parquet` | local broad market indices |
| `data/processed/fx.parquet` | `fx_direction = local_per_usd` |
| `data/processed/riskfree.parquet` | `^IRX`, `units = percent` |
| `reports/source_crosscheck.csv` | CN/HK two-source audit |
| `reports/historical_universe_audit.csv` | universe provenance / delisting coverage |
| `data/reference/transaction_costs.csv` | current-only tax rows (dated subset usable) |

The study period is the monthly panel **2010-01 → latest** (panel max 2026-10).
Signals are formed at the end of formation month `t`; the dependent target
`next_month_return` is the security's return in the **subsequent local calendar
month** `t+1`. Signal coverage with a valid target begins 2011-02 and ends
2026-08/09 (market-dependent). **Partial 2026 is labelled incomplete throughout.**

### 0.1 Universe and survivorship (limitations, not hidden)

- Portfolio and factor tests use **only `eligible_universe == True`** rows; sample
  attrition is reported (`results/robustness/sample_attrition.csv`).
- Survivorship: **current-universe survivorship is flagged for all seven markets.**
  CN/HK carry `SURVIVOR_BIAS_LABEL_QUESTIONABLE_DELISTING_COVERAGE_ZERO` (0/34 and
  0/38 delisted coverage); IN/JP/KR/SG/TW carry `CURRENT_SURVIVOR_BIAS`. No
  market is bias-free. Results are phrased as **survivor-biased exploratory tests.**
- Only **210 current/curated securities** exist in the provider panels — not
  exhaustive historical listings. OOS claims are conditional on this.
- Two-provider cross-check exists only for CN/HK; other markets are single-source.

### 0.2 Signal availability constraints

- `vol_60` is the **primary** low-risk signal; `vol_252` is robustness.
- `beta` and `ivol` are **secondary robustness only**, never primary discovery.
- **CN has no market-model signals**: the CN benchmark has a single daily row
  (2026-09-30), so `beta`, `dimson_beta` and `ivol` are undefined for CN. CN is
  **excluded from beta/IVOL tests only**, with a reason recorded as `NA_CN_NO_BENCHMARK`.
- Historical Value/Quality/Size are **not analysed**.

---

## 1. Return, FX and cash conventions

**FX.** `fx.parquet` gives `local_per_usd`. Month-end rate = last observation per
market-month. For local asset return `r_loc` in month `m`:

```
r_usd(m) = (1 + r_loc(m)) * ( fx(m-1) / fx(m) ) - 1
```

because the USD price of a local asset is `P / fx`. Units verified in
`tests/test_main_empirical.py`.

**Cash.** `^IRX` is a discount yield in **percent**. Monthly USD cash is
approximated as `close/100/12` at month-end. This is a deliberate approximation
(not a compounding money-market return) and is labelled as such in every table and
figure that uses it.

**Benchmark.** Country benchmark monthly returns are computed from
`benchmarks.parquet` `adj_close` (month-end to month-end), converted to USD with
the same FX rule. The **APAC benchmark is equal-country-weighted across the AVAILABLE
markets**; CN has no benchmark history, so the aggregate is a **6-market APAC
benchmark** (HK, IN, JP, KR, SG, TW). No synthetic China is created. Country-specific
performance uses USD stock and USD benchmark returns.

---

## 2. Standalone signal tests

Primary signals: **MOM = `mom_12_1`** (12-1 momentum, month `t-1` excluded by
construction) and **LOWRISK = `-vol_60`** (higher score = lower volatility).
Secondary robustness: **`beta_rank`**, **`ivol_rank`** (higher = lower beta / lower
IVOL), computed only where non-null; CN is NA.

For each (market, formation month) on the eligible sample with non-null signal and
non-null `next_month_return`:

- **Rank IC** = Spearman rank correlation between the signal and
  `next_month_return` within the market-month.
- Report per market: average IC, std IC, **ICIR = mean/std (monthly, not
  annualized)**, positive-frequency, number of months, average cross-section N.
- **Pooled APAC only after country results**: country-equal-weighted IC series
  (equal-country, not pooled-security).

**Quintiles.** Within (market, formation month) on the eligible sample, assign
Q1..Q5 by signal, with deterministic tie-break on `security_id`. Q5 is the
highest-expected-return bucket for every signal orientation. Report Q1..Q5
equal-weight USD returns, Q5−Q1, monotonicity (Spearman of bucket order vs mean
return), annualized geometric/compound mean, volatility, Sharpe using the USD cash
approximation, maximum drawdown, and one-way turnover. The **long-short Q5−Q1
spread is distinguished from the implementable long-only Q5 sleeve** at all times.
Spreads are indexed by realisation month `t+1` for external comparison and labelled.

---

## 3. Fama–MacBeth (primary)

Monthly cross-sections, dependent variable `next_month_return` (local). Regressors,
**standardised within market-month**:

- `MOM_z` = z(`mom_12_1`)
- `LOWRISK_z` = z(`-vol_60`)
- `lag_ret_z` = z(`monthly_total_return` at formation month `t`) — one lagged month
- `logliq_z` = z(log median daily traded value)

**Pooled** regression includes **market fixed-effect dummies**; the coefficients of
interest are the within-market standardised signal slopes. **Per-country** models
are fit separately for MOM and LOWRISK (with the two controls).

Estimation: each month contributes one cross-sectional OLS; the time series of
monthly slopes is averaged. Standard error uses a **Newey–West HAC t-statistic, lag
6**, from a regression of the slope series on a constant. Months with too few
observations are **skipped and logged** (`min named obs` gate, `results/fama_macbeth/
fm_skipped_months.csv`). Report mean slope, HAC(6) t, economic effect per 1 SD
(equals the slope because regressors are z-scored), valid months, average N.
**No opportunistic controls; no future returns in factors or controls.**

---

## 4. External validation

### 4.1 JKP (primary external)
Filter the seven JKP country codes; use country-level **`momentum`** and
**`low_risk`**, which are **decimal excess returns in USD** (value-weighted long–short
country factors). Compare to our own monthly **Q5−Q1 USD spread** on **exact common
dates only** (inner join on calendar month-end). Report paired n, correlation,
sign agreement, cumulative return, mean, volatility, Sharpe, max drawdown, and
**pre-2020 vs post-2020** sub-samples. Explicitly label the **methodology
difference** (JKP: value-weighted long–short factor; ours: equal-weight Q5−Q1 on a
survivor-biased 210-name panel) and the **unit difference** (JKP already excess USD;
ours converted from local via our FX rule).

### 4.2 French (secondary/limited)
French factors exist for **Japan**, **Developed** and **Asia-Pacific ex Japan** and
contain only `Mkt-RF`, `SMB`, `HML`, `RF` (no momentum / low-risk). They are
therefore used **only as a market-return cross-check**: French Japan `Mkt-RF` vs our
Japan benchmark excess USD return; French `Asia_Pacific_ex_Japan` `Mkt-RF` vs our
6-market APAC benchmark excess USD return. It is explicitly **not** claimed that
the French ex-Japan aggregate equals HK/SG, and this is **not** a signal
validation.

### 4.3 AQR
AQR data is **NOT AVAILABLE** in the approved Prompt 1–2 inputs. The network is
not accessed. Reported as `NOT_AVAILABLE`. No downloaded substitute is used.

---

## 5. OOS portfolios

**Expanding-window OOS.** Training window starts 2010 through **December of year
Y−1**; the entire calendar year **Y** is test/OOS for **Y = 2016 … last available**.
2016–2025 are complete; **2026 is partial and labelled incomplete**. No sample
optimisation, no re-selection.

Portfolios (country sleeves built monthly from eligible securities, then combined
**equal-country** — never pooled security equal-weight):

| ID | Portfolio | Sleeve rule |
|----|-----------|-------------|
| A | **1/N** | equal-weight all eligible names |
| B | **Momentum** | top quintile `mom_12_1`, equal-weight |
| C | **Low Risk** | top quintile `-vol_60`, equal-weight |
| D | **Composite** | top quintile of `0.5·z(MOM)+0.5·z(LOWRISK)`, equal-weight — **fixed, transparent primary combined signal** |
| E | **Optimized** | long-only, fully invested mean–variance |

Rules for every quintile/sleeve: deterministic tie-break on `security_id`;
**minimum 5 names else the month is missing**; scores/ranks/z-scores computed **only
from the current cross-section** (non-parametric).

### 5.1 Optimized sleeve (declared before run)

- Forecast expected monthly USD returns from **expanding Fama–MacBeth coefficients**
  trained **only on past formation months whose next-month return is realised by the
  current formation month** (formation months `≤ t−1`). Forecast = `slopes · z_i(t)`
  (the market intercept is constant within a country and does not change a
  fully-invested long-only optimum). If history is inadequate to estimate the
  coefficients, **do not trade that sleeve-month**; mark `NA` (the 50/50 score is
  never substituted as a return-unit forecast).
- Covariance: trailing **36 monthly USD** stock returns ending at the formation
  month, **minimum 24 observations per security** and a **common-asset sample**;
  **Ledoit–Wolf (sklearn) is primary**, sample covariance only robustness.
- Objective: maximise `w·μ − λ·wᵀΣw − η·c·Σ|w − w_prev|`, `λ = 5` (fixed),
  `η = 1`, `c` = base friction **15 bps** per traded notional (the mid scenario).
  Subject to `Σw = 1`, `w ≥ 0` (**no arbitrary hard name cap**) via
  `scipy.optimize.minimize` SLSQP. On numeric non-convergence, **fall back to equal
  weight**, increment a counter, and **record** it; the return series is never
  silently altered.
- Timing: weights formed at end of month `t` earn the realised USD return of month
  `t+1` (verified in tests). Timing lag logic is asserted.

**Turnover.** One-way turnover = `0.5·Σ|w_t − w_prev|`; the initial entry has
`w_prev = 0`, so initial one-way turnover = `0.5`. The alternative investor entry
convention (count the first purchase as full one-way) is noted and reported in
robustness.

---

## 6. Transaction costs and taxes

Gross returns are always retained. Costs are **pre-specified friction scenarios of
5 / 15 / 30 bps per one-way traded notional** — an **explicit illustrative range,
not a claimed official figure**.

Taxes from `data/reference/transaction_costs.csv` are current-status-only;
only rows with a supplied **verified effective date** are implemented:

- **CN seller stamp duty 5 bps, applied to sell-side notional only, for months
  ≥ 2023-08-28.**
- **HK stamp duty 10 bps per side, both buy and sell, for months ≥ 2023-11-17.**
- All other jurisdictions: tax status unavailable/unverified → **no invented tax**.
  A tax-coverage table states the limitation.

`Net = Gross − turnover·scenario_friction − dated documented per-side tax`
(using `Σ|Δw|` for buy+sell notional and side-specific rates). Factor-only and
portfolio gross/net are both reported; a sensitivity table spans all three cost
scenarios. **No cherry-picking** of the best scenario.

---

## 7. Multiple testing

Every requested specification has a row in `SPECIFICATION_REGISTRY.csv` labelled
**PRIMARY / ROBUSTNESS / EXPLORATORY**. The set is small and fixed. This project
tests **pre-specified signals**; it is not a factor-zoo mining exercise. We discuss
Harvey–Liu–Zhu (2016), Feng–Giglio–Xiu and Hou–Xue–Zhang (2020) and the

> fact that a nominal t-statistic is **not** a discovery claim.

A multiplicity sensitivity (Bonferroni/Šidák across the small primary family) is
reported for discussion; conclusions rest on economic significance and OOS net, not
on nominal significance.

---

## 8. Outputs

Directories: `results/signal_tests/`, `results/fama_macbeth/`, `results/jkp_validation/`,
`results/oos/`, `results/portfolio/`, `results/transaction_costs/`,
`results/robustness/`, `figures/`, `tables/`, `reports/`.

Reports: `METHODOLOGY_MAIN_TESTS.md` (this file), `LITERATURE_MAPPING.md`,
`SPECIFICATION_REGISTRY.csv`,
`reports/APAC_Alpha_to_Portfolio_Final_Report.md`,
`reports/APAC_Alpha_to_Portfolio_Executive_Summary.md`.
Code: `scripts/run_main_tests.py`, `tests/test_main_empirical.py`,
`requirements_analysis.txt`.

**Figures (exactly 20 PNG).** Each figure states a conclusion in the title, the
sample/method in the subtitle, readable axes, and a footer with source + units + a
one-sentence investment takeaway. Constrained layout; no overlap.

**Final APAC table** (Benchmark / 1N / Momentum / Low Risk / Composite / Optimized)
reports exactly: CAGR, Volatility, Sharpe, Max drawdown, Turnover, Net return,
Worst year, Best year, Country concentration. Country risk contribution is derived
from the country-sleeve return covariance; concentration uses weights and HHI.
Optimized is compared directly to 1/N and a claim is made **only if OOS net improves
economic metrics**.
