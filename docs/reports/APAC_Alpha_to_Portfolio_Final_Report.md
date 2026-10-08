# APAC Alpha-to-Portfolio — Final Report

Model: `opencode-go/deepseek-v4.1-flash`. Frozen spec: `METHODOLOGY_MAIN_TESTS.md`,
`SPECIFICATION_REGISTRY.csv`. No network; no Prompt 1-2 input modified.

## 1. Sample and coverage
- Panel rows: **40,782**; months **202**
  (2010-01..2026-10); eligible rows **30,266**.
- Markets: CN, HK, IN, JP, KR, SG, TW. OOS: 2016-01..2026-09
  (129 months);
  2026 partial and labelled incomplete.
- **CN beta/ivol = NA** (CN benchmark has one daily row). Non-null CN beta rows:
  0.
- Survivorship: current-universe survivorship all markets; CN/HK questionable.

## 2. Standalone signal tests
Pooled country-equal IC (monthly, not annualised):
```
 signal   avg_ic   std_ic     icir  pos_freq  months     avg_n
    mom 0.033128 0.164631 0.201227  0.601064     188 22.888678
lowrisk 0.002163 0.158176 0.013676  0.500000     188 22.888678
 vol252 0.006112 0.164568 0.037138  0.515957     188 22.888678
   beta 0.005288 0.199253 0.026541  0.515957     188 22.481383
   ivol 0.006189 0.136192 0.045442  0.494681     188 22.481383
```
By-market detail in `results/signal_tests/ic_by_country.csv`; quintile stats in
`quintiles_mom.csv` / `quintiles_lowrisk.csv`; beta/ivol (secondary, CN NA) in
`quintiles_beta.csv` / `quintiles_ivol.csv`.

**Low-risk premium is inverted in this panel.** Country-equal LOWRISK Q5-Q1 is
negative in **all seven markets** (mean -0.0087/month);
MOM Q5-Q1 is positive in six of seven (mean 0.0083/month;
India marginally negative). Quintile sleeves skip a market-month when its top
quintile has fewer than five names, so some markets (often SG) appear only in 1/N.

## 3. Fama-MacBeth (primary)
- mom_z: mean slope 0.0031 (NW HAC(6) t=3.30), valid months 188, avg N 160.1
- lowrisk_z: mean slope -0.0026 (NW HAC(6) t=-2.31), valid months 188, avg N 160.1
- lagret_z: mean slope 0.0002 (NW HAC(6) t=0.24), valid months 188, avg N 160.1
- logliq_z: mean slope -0.0010 (NW HAC(6) t=-1.46), valid months 188, avg N 160.1
Per-country MOM/LOWRISK in `results/fama_macbeth/fm_by_country.csv`. Skipped months
logged in `fm_skipped_months.csv`.

## 4. External validation
JKP (momentum / low_risk), exact common dates:
```
  signal market   n     corr  sign_agree   own_cum   jkp_cum  own_mean  jkp_mean  own_vol  jkp_vol  own_sharpe  jkp_sharpe  own_maxdd  jkp_maxdd  pre2020_n  pre2020_corr  post2020_n  post2020_corr
momentum     CN 178 0.519614    0.640449  0.305461 -0.124791  0.003737 -0.000234 0.232492 0.111239    0.192887   -0.025236  -0.732830  -0.404503        106      0.313014          72       0.721687
momentum     HK 178 0.647037    0.724719  1.771313  1.020254  0.008628  0.004721 0.258921 0.133343    0.399888    0.424828  -0.512763  -0.309096        106      0.442016          72       0.796020
momentum     IN 178 0.627064    0.674157 -0.464263  0.443490 -0.001002  0.002580 0.238752 0.109907   -0.050386    0.281684  -0.696645  -0.241911        106      0.593641          72       0.688497
momentum     JP 178 0.701094    0.730337  0.390194  0.054275  0.003199  0.000580 0.179945 0.082354    0.213363    0.084542  -0.422483  -0.155120        106      0.643148          72       0.779587
momentum     KR 178 0.550185    0.674157  1.111462  0.730159  0.006891  0.003760 0.253480 0.128019    0.326228    0.352461  -0.348850  -0.253995        106      0.552446          72       0.548339
momentum     SG 178 0.111009    0.584270 14.428015  0.592861  0.018423  0.002914 0.282840 0.083883    0.781610    0.416798  -0.296336  -0.176237        106      0.078508          72       0.165912
momentum     TW 178 0.522974    0.707865  2.404821  2.962453  0.010342  0.008244 0.308841 0.107722    0.401826    0.918397  -0.529898  -0.137898        106      0.564678          72       0.519950
low_risk     CN 178 0.403961    0.646067 -0.825154  0.939385 -0.006348  0.004356 0.274022 0.122834   -0.278011    0.425537  -0.910173  -0.236132        106      0.268118          72       0.522846
low_risk     HK 178 0.743265    0.780899 -0.829068  0.140942 -0.007019  0.001454 0.258672 0.130354   -0.325600    0.133844  -0.904468  -0.364692        106      0.624518          72       0.838977
low_risk     IN 178 0.561443    0.713483 -0.576943  0.027941 -0.002999  0.000688 0.205717 0.112783   -0.174964    0.073163  -0.749484  -0.388509        106      0.581853          72       0.534664
low_risk     JP 178 0.629155    0.707865 -0.940680 -0.112233 -0.014262 -0.000434 0.188661 0.075006   -0.907152   -0.069508  -0.950008  -0.293804        106      0.504740          72       0.725535
low_risk     KR 178 0.624254    0.713483 -0.696095  0.319434 -0.003300  0.002052 0.281071 0.109191   -0.140891    0.225554  -0.911943  -0.269170        106      0.620029          72       0.638285
low_risk     SG 178 0.296889    0.657303 -0.861240  0.520908 -0.008464  0.002479 0.251242 0.053790   -0.404271    0.553059  -0.876068  -0.101698        106      0.285337          72       0.317733
low_risk     TW 178 0.597180    0.702247 -0.968009  0.040833 -0.013063  0.000744 0.334768 0.111723   -0.468249    0.079884  -0.977573  -0.359598        106      0.576217          72       0.655246
```
Methodology and units differ (JKP value-weighted long-short excess USD vs our
equal-weight, survivor-biased, FX-converted Q5-Q1). French cross-check (market
return only):
```
        comparison   n     corr  our_mean  french_mean                                                                                                          note
             Japan 199 0.889290  0.006503     0.006417 French Mkt-RF vs own benchmark excess USD; market-return cross-check only, NOT a momentum/low-risk validation
APAC_ex_Japan_6mkt 199 0.388515  0.011233     0.005432 French Mkt-RF vs own benchmark excess USD; market-return cross-check only, NOT a momentum/low-risk validation
         Developed   0      NaN       NaN          NaN                        French Developed aggregate has no matching own series in the 7 markets; NOT comparable
```
AQR: **NOT_AVAILABLE**.

## 5. OOS portfolios and the optimizer
Expanding training (2010..Dec Y-1), test year Y, 2016..; forecast from
expanding Fama-MacBeth coefficients; covariance = trailing 36m USD,
min 24 obs, Ledoit-Wolf; lambda=5.0; SLSQP simplex.
Turnover one-way = 0.5*sum|dw|, initial 0.5. The optimizer transaction penalty uses
the **same per-one-way** convention, `eta*base_cost_rate*0.5*sum|w-w0|` (3.0 bps
one-way, eta=1.0), so the in-objective charge and the realised cost scenarios
are measured identically.
- Optimizer numeric fallback to equal weight: **0** (recorded, series not silently altered).
- Sleeve-months skipped for inadequate FM training history: 168; for insufficient covariance history: 0 (marked NA, not traded).

### Final APAC table (CAGR = gross; NetReturn = net of 15 bps + dated taxes)
```
Portfolio     CAGR  Volatility   Sharpe  MaxDrawdown  Turnover  NetReturn  WorstYear  BestYear  CountryConcentration
Benchmark 0.096942    0.164451 0.509319    -0.286636       NaN   0.096942  -0.120360  0.307852              0.166667
      1/N 0.159745    0.155244 0.886969    -0.205323  0.026651   0.159163  -0.107234  0.452107              0.142857
 Momentum 0.231434    0.186774 1.066764    -0.256421  0.241645   0.225746  -0.163774  0.672502              0.166667
 Low Risk 0.120309    0.129185 0.735310    -0.263293  0.256331   0.114892  -0.069413  0.338874              0.166667
Composite 0.147295    0.139584 0.853298    -0.243038  0.309862   0.140593  -0.145340  0.500241              0.166667
Optimized 0.128536    0.138795 0.761706    -0.215960  0.143430   0.125470  -0.098628  0.381015              0.142857
```
Optimized vs 1/N:
```
     metric  one_over_n  optimized  optimized_better
  NetReturn    0.159163   0.125470             False
     Sharpe    0.886969   0.761706             False
MaxDrawdown   -0.205323  -0.215960             False
 Volatility    0.155244   0.138795              True
```
Decision: **no robust improvement from optimization versus 1/N**.

## 6. Costs and taxes
Friction scenarios 5/15/30 bps per one-way traded notional (illustrative, not
official). Dated taxes: CN seller stamp 5 bps (>=2023-08-28), HK 10 bps/side
(>=2023-11-17). Other jurisdictions unverified -> not applied.
```
portfolio   gross       5bps        15bps       30bps       
1/N         16.0%       16.0%       15.9%       15.9%       
Momentum    23.1%       22.9%       22.6%       22.1%       
Low Risk    12.0%       11.8%       11.5%       11.0%       
Composite   14.7%       14.5%       14.1%       13.4%       
Optimized   12.9%       12.7%       12.5%       12.3%       
```
A country sleeve's dated tax enters the equal-country portfolio as
`rate_market * sleeve_turnover / K_active`, where `K_active` is the number of
active country sleeves that realisation month (the portfolio return is the
equal-weight mean of active sleeves). `K_active` is therefore **not** a fixed 7:
when a top-quintile sleeve is absent in a market, the denominator is the actual
active count. The benchmark carries no frictions or tax. Keep CN/HK effective
dates unchanged. Tax coverage in `results/transaction_costs/tax_coverage.csv`.

### Annual returns (canonical = net 15 bps + dated taxes; Benchmark uncharged)
```
           1/N  Momentum  Low Risk Composite  Optimized  Benchmark
year                                                              
2016  0.098928   0.07012  0.024372  0.045166   0.032794   0.029964
2017  0.452107  0.672502  0.338874  0.500241   0.381015   0.277283
2018 -0.107234 -0.163774  -0.06643  -0.14534  -0.098628  -0.083734
2019  0.247920  0.188336  0.079902  0.151665   0.146653   0.051795
2020  0.292881  0.579711  0.130361  0.296229   0.181172   0.121619
2021  0.155485  0.400542  0.110863  0.170987   0.105925   0.081646
2022 -0.069397 -0.142142 -0.069413 -0.098596  -0.071082  -0.120360
2023  0.159341   0.23983  0.139303  0.171241   0.189313   0.050463
2024  0.090497  0.173927  0.186775  0.189014   0.136474   0.129186
2025  0.292467  0.286004  0.286008  0.198469   0.255068   0.288166
2026  0.211484  0.411597   0.14588  0.167017   0.174227   0.307852
```
Gross counterpart in `results/oos/oos_annual_returns_gross.csv`; the canonical
`results/oos/oos_annual_returns.csv` is byte-identical to
`results/oos/oos_annual_returns_net15bps.csv`. **2026 is a partial calendar year
(9 months) and is labelled incomplete.**

## 7. Risk, concentration, multiple testing
Risk contribution, HHI and correlation in `results/portfolio/`. Multiplicity
(Bonferroni/Sidak over the small primary FM family):
```
        test  p_two_sided         t  n_tests  bonferroni_alpha  sidak_alpha
    FM_mom_z     0.000953  3.304078        4            0.0125     0.012741
FM_lowrisk_z     0.020790 -2.311783        4            0.0125     0.012741
 FM_lagret_z     0.806793  0.244565        4            0.0125     0.012741
 FM_logliq_z     0.144766 -1.458270        4            0.0125     0.012741
```
Corrected significance status (two-sided p vs family-wise thresholds Sidak=0.0127, Bonferroni=0.0125, k=4): FM_mom_z survive; FM_lowrisk_z, FM_lagret_z, FM_logliq_z do not. No Sidak alpha exceeds 0.05.
Following Harvey-Liu-Zhu (2016), Feng-Giglio-Xiu (2020), Hou-Xue-Zhang (2020):
**nominal t-stats are not discovery**; conclusions rest on economic significance and
OOS net, and the survivor-biased panel prevents any bias-free claim.

## 8. Robustness suite (eight predeclared families)
No specification in this section was selected on Sharpe. Each family maps to a
`family`/`variation`/`status` row in `results/robustness/robustness_summary.csv`;
`status='na'` marks an explicit non-result (never a silent skip). Windows in
`results/robustness/robustness_windows.csv`.

| family | variation | factor | metric | value | status | note |
|---|---|---|---|---|---|---|
| momentum_window_6_1 | MOM_6_1 | MOM | avg_ic | 0.0170 | ok |  |
| momentum_window_6_1 | MOM_6_1 | MOM | q5_q1_mean | 0.0052 | ok |  |
| lowrisk_vol_252 | vol_252 | LOWRISK | avg_ic | 0.0061 | ok |  |
| lowrisk_vol_252 | vol_252 | LOWRISK | q5_q1_mean | -0.0092 | ok |  |
| liquidity_cutoff | liq_bottom10 | MOM | avg_ic | 0.0339 | ok |  |
| liquidity_cutoff | liq_bottom10 | MOM | q5_q1_mean | 0.0093 | ok |  |
| liquidity_cutoff | liq_bottom10 | LOWRISK | avg_ic | 0.0047 | ok |  |
| liquidity_cutoff | liq_bottom10 | LOWRISK | q5_q1_mean | -0.0094 | ok |  |
| liquidity_cutoff | liq_bottom20_primary | MOM | avg_ic | 0.0331 | ok |  |
| liquidity_cutoff | liq_bottom20_primary | MOM | q5_q1_mean | 0.0083 | ok |  |
| liquidity_cutoff | liq_bottom20_primary | LOWRISK | avg_ic | 0.0022 | ok |  |
| liquidity_cutoff | liq_bottom20_primary | LOWRISK | q5_q1_mean | -0.0087 | ok |  |
| liquidity_cutoff | liq_bottom40 | MOM | avg_ic | 0.0303 | ok |  |
| liquidity_cutoff | liq_bottom40 | MOM | q5_q1_mean | 0.0077 | ok |  |
| liquidity_cutoff | liq_bottom40 | LOWRISK | avg_ic | 0.0046 | ok |  |
| liquidity_cutoff | liq_bottom40 | LOWRISK | q5_q1_mean | -0.0085 | ok |  |
| quintile_weighting | weight_equal | MOM | gross_cagr | 0.3713 | ok | equal-weight benchmark within top quintile |
| quintile_weighting | weight_equal | MOM | net15_cagr | 0.3652 | ok | equal-weight benchmark within top quintile |
| quintile_weighting | weight_liquidity | MOM | gross_cagr | 0.3023 | ok | liquidity-aware weighting is a SENSITIVITY, not a recommended factor |
| quintile_weighting | weight_liquidity | MOM | net15_cagr | 0.2951 | ok | liquidity-aware weighting is a SENSITIVITY, not a recommended factor |
| quintile_weighting | weight_equal | LOWRISK | gross_cagr | 0.1282 | ok | equal-weight benchmark within top quintile |
| quintile_weighting | weight_equal | LOWRISK | net15_cagr | 0.1228 | ok | equal-weight benchmark within top quintile |
| quintile_weighting | weight_liquidity | LOWRISK | gross_cagr | 0.1383 | ok | liquidity-aware weighting is a SENSITIVITY, not a recommended factor |
| quintile_weighting | weight_liquidity | LOWRISK | net15_cagr | 0.1318 | ok | liquidity-aware weighting is a SENSITIVITY, not a recommended factor |
| developed_emerging | developed | MOM | avg_ic | 0.0358 | ok |  |
| developed_emerging | developed | MOM | q5_q1_mean | 0.0100 | ok |  |
| developed_emerging | developed | LOWRISK | avg_ic | 0.0041 | ok |  |
| developed_emerging | developed | LOWRISK | q5_q1_mean | -0.0089 | ok |  |
| developed_emerging | developed | - | market_coverage | 3.0000 | ok | markets: JP/HK/SG |
| developed_emerging | emerging | MOM | avg_ic | 0.0312 | ok |  |
| developed_emerging | emerging | MOM | q5_q1_mean | 0.0071 | ok |  |
| developed_emerging | emerging | LOWRISK | avg_ic | 0.0005 | ok |  |
| developed_emerging | emerging | LOWRISK | q5_q1_mean | -0.0086 | ok |  |
| developed_emerging | emerging | - | market_coverage | 4.0000 | ok | markets: CN/IN/KR/TW |
| period_split | period_2016_2019 | MOM | avg_ic | -0.0028 | ok |  |
| period_split | period_2016_2019 | MOM | q5_q1_mean | -0.0003 | ok |  |
| period_split | period_2016_2019 | LOWRISK | avg_ic | -0.0407 | ok |  |
| period_split | period_2016_2019 | LOWRISK | q5_q1_mean | -0.0106 | ok |  |
| period_split | period_2020_2025 | MOM | avg_ic | 0.0558 | ok |  |
| period_split | period_2020_2025 | MOM | q5_q1_mean | 0.0154 | ok |  |
| period_split | period_2020_2025 | LOWRISK | avg_ic | 0.0160 | ok |  |
| period_split | period_2020_2025 | LOWRISK | q5_q1_mean | -0.0093 | ok |  |
| survivor_sensitivity | full_7mkt | Composite | avg_ic | 0.0234 | ok | full 7-market sample |
| survivor_sensitivity | full_7mkt | Composite | q5_q1_mean | 0.0012 | ok | full 7-market sample |
| survivor_sensitivity | ex_survivor_CN_HK | Composite | avg_ic | 0.0430 | ok | retains only CN/HK; both have 0/N delisting coverage so this does NOT cure survivorship |
| survivor_sensitivity | ex_survivor_CN_HK | Composite | q5_q1_mean | 0.0009 | ok | retains only CN/HK; both have 0/N delisting coverage so this does NOT cure survivorship |
| country_leave_one_out | leaveout_none | Composite | net15_cagr | 0.1406 | ok | all markets; CN benchmark missing (one-row) |
| country_leave_one_out | leaveout_CN | Composite | net15_cagr | 0.1403 | ok | excludes CN; CN benchmark missing (one-row) |
| country_leave_one_out | leaveout_HK | Composite | net15_cagr | 0.1497 | ok | excludes HK |
| country_leave_one_out | leaveout_IN | Composite | net15_cagr | 0.1489 | ok | excludes IN |
| country_leave_one_out | leaveout_JP | Composite | net15_cagr | 0.1503 | ok | excludes JP |
| country_leave_one_out | leaveout_KR | Composite | net15_cagr | 0.1235 | ok | excludes KR |
| country_leave_one_out | leaveout_SG | Composite | net15_cagr | 0.1406 | ok | excludes SG |
| country_leave_one_out | leaveout_TW | Composite | net15_cagr | 0.1282 | ok | excludes TW |
| country_leave_one_out | leaveout_none | 1/N | net15_cagr | 0.1592 | ok | all markets; CN benchmark missing (one-row) |
| country_leave_one_out | leaveout_CN | 1/N | net15_cagr | 0.1641 | ok | excludes CN; CN benchmark missing (one-row) |
| country_leave_one_out | leaveout_HK | 1/N | net15_cagr | 0.1692 | ok | excludes HK |
| country_leave_one_out | leaveout_IN | 1/N | net15_cagr | 0.1648 | ok | excludes IN |
| country_leave_one_out | leaveout_JP | 1/N | net15_cagr | 0.1587 | ok | excludes JP |
| country_leave_one_out | leaveout_KR | 1/N | net15_cagr | 0.1569 | ok | excludes KR |
| country_leave_one_out | leaveout_SG | 1/N | net15_cagr | 0.1532 | ok | excludes SG |
| country_leave_one_out | leaveout_TW | 1/N | net15_cagr | 0.1454 | ok | excludes TW |
| country_leave_one_out | leaveout_none | Optimized | net15_cagr | 0.1255 | ok | all markets; CN benchmark missing (one-row) |
| country_leave_one_out | leaveout_CN | Optimized | net15_cagr | 0.1258 | ok | excludes CN; CN benchmark missing (one-row) |
| country_leave_one_out | leaveout_HK | Optimized | net15_cagr | 0.1327 | ok | excludes HK |
| country_leave_one_out | leaveout_IN | Optimized | net15_cagr | 0.1305 | ok | excludes IN |
| country_leave_one_out | leaveout_JP | Optimized | net15_cagr | 0.1271 | ok | excludes JP |
| country_leave_one_out | leaveout_KR | Optimized | net15_cagr | 0.1184 | ok | excludes KR |
| country_leave_one_out | leaveout_SG | Optimized | net15_cagr | 0.1197 | ok | excludes SG |
| country_leave_one_out | leaveout_TW | Optimized | net15_cagr | 0.1223 | ok | excludes TW |

**RF1 MOM 6-1** compounds exactly t-6..t-2 (gap-aware, t-1 excluded).
**RF2** repeats LOWRISK as `-vol_252` instead of `-vol_60`.
**RF3** fixes the investable cutoff at bottom 10%, 20% (primary) and 40%; no
Sharpe tuning.
**RF4** compares equal vs liquidity-aware weighting in the top quintile; the
liquidity-weighted variant is a **sensitivity only, not a recommended factor**.
**RF5** predeclares Developed (JP/HK/SG) and Emerging (CN/IN/KR/TW); CN beta/IVOL
remains NA.
**RF6** splits 2016-2019 vs 2020-2025 for the primary factors, excluding the
incomplete 2026.
**RF7** contrasts the full 7-market sample with CN/HK only; CN and HK both have
0/N delisting coverage, so this **does NOT cure survivorship**.
**RF8** leaves out each country in turn for the equal-country Composite, 1/N and
Optimized portfolios; CN benchmark is missing (one-row), recorded as such.

## 9. Unresolved blockers
1. Current-universe survivorship in all seven markets; CN/HK delisting coverage 0.
2. Only 210 names, not exhaustive historical listings.
3. CN market-model signals unavailable (one-row benchmark); CN excluded from
   beta/IVOL only.
4. Tax data current-only; most jurisdictions not historically verified -> not applied.
5. AQR data not in approved inputs and network prohibited -> NOT_AVAILABLE.
6. 2026 partial; results for 2026 are incomplete.
