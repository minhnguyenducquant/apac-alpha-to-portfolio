# APAC Alpha-to-Portfolio — Executive Summary

**Scope.** Survivor-biased exploratory tests on 210 current/curated APAC names
(CN, HK, IN, JP, KR, SG, TW), monthly panel 2010-01..2026-10. Signals:
12-1 momentum (MOM) and low-risk (`-vol_60`, LOWRISK); composite = fixed
`0.5 z(MOM)+0.5 z(LOWRISK)`. OOS is expanding, 2016-01..2026-09
(2026 partial, labelled incomplete).

**Headline results (net of 15 bps friction + dated taxes).**

| Portfolio | CAGR | Vol | Sharpe | MaxDD |
|-----------|------|-----|--------|-------|
| Benchmark (6-mkt) | 9.7% | 16.4% | 0.51 | -28.7% |
| 1/N | 15.9% | 15.5% | 0.89 | -20.5% |
| Momentum | 22.6% | 18.7% | 1.07 | -25.6% |
| Low Risk | 11.5% | 12.9% | 0.74 | -26.3% |
| Composite | 14.1% | 14.0% | 0.85 | -24.3% |
| Optimized | 12.5% | 13.9% | 0.76 | -21.6% |

**IC.** Pooled country-equal mean monthly Spearman IC: **MOM
0.0331, LOWRISK
0.0022**. Positive on average
but sign-unstable month to month.

**Key finding — the low-risk premium is inverted here.** LOWRISK Q5-Q1 is
**negative in all seven markets** (country-equal mean -0.0087/month);
high-volatility names out-returned low-vol names. Momentum Q5-Q1 is positive in six
of seven markets (country-equal mean 0.0083/month).
The Low Risk sleeve's value is **risk reduction**, not return. Quintile sleeves also
drop markets whose top quintile has fewer than five names (in practice often SG), so
those markets remain only in 1/N — a construction artefact disclosed here.

**Fama-MacBeth (pooled, market FE, NW HAC(6)).**
- mom_z: mean slope 0.0031 (NW HAC(6) t=3.30), valid months 188, avg N 160.1
- lowrisk_z: mean slope -0.0026 (NW HAC(6) t=-2.31), valid months 188, avg N 160.1
- lagret_z: mean slope 0.0002 (NW HAC(6) t=0.24), valid months 188, avg N 160.1
- logliq_z: mean slope -0.0010 (NW HAC(6) t=-1.46), valid months 188, avg N 160.1

**Multiple testing.** Corrected significance status (two-sided p vs family-wise thresholds Sidak=0.0127, Bonferroni=0.0125, k=4): FM_mom_z survive; FM_lowrisk_z, FM_lagret_z, FM_logliq_z do not. No Sidak alpha exceeds 0.05.

**Robustness.** Eight predeclared families (6-1 momentum; `vol_252`; bottom
10/20/40% liquidity cutoffs; equal vs liquidity weighting; developed vs emerging;
2016-2019 vs 2020-2025; survivor exclusion; country leave-one-out) are reported in
`results/robustness/robustness_summary.csv` with explicit NA statuses. None is
selected on Sharpe; liquidity weighting is a sensitivity only.

**Optimized vs 1/N.** Optimized net CAGR 12.5% vs 1/N
15.9%; Sharpe 0.76 vs
0.89. **Claim that optimization improves economic metrics:
NO** — a claim is made only when OOS net economics
improve after charging the corrected per-one-way turnover cost.

**Key limitations.** Current-universe survivorship in ALL markets (CN/HK delisting
coverage 0); only 210 names; CN has no market-model beta/IVOL (one-row benchmark);
taxes applied only for CN/HK with verified dates; AQR **NOT AVAILABLE**; no network.
