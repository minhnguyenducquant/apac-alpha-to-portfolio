# LITERATURE_MAPPING.md

Mapping of implemented specifications to the literature. No new alpha is discovered;
this project tests a **small, pre-specified** set of equity return predictors and a
portfolio translation. Citations are to well-known works (no network access used).

## Signals

| Signal | Implementation | Literature anchor |
|--------|----------------|-------------------|
| **MOM** 12-1 | `mom_12_1`: compounded returns `t-12..t-2`, month `t-1` excluded | Jegadeesh & Titman (1993); Asness, Moskowitz & Pedersen (2013) |
| **LOWRISK** | `-vol_60` (higher = lower realised vol); `vol_252` robustness | Ang, Hodrick, Xing & Zhang (2006) low-vol anomaly; Baker, Bradley & Wurgler (2011) |
| **BETA** (secondary) | `beta_rank` (higher = lower market beta) | Frazzini & Pedersen (2014) betting-against-beta |
| **IVOL** (secondary) | `ivol_rank` (higher = lower idiosyncratic vol) | Ang et al. (2006) |
| **Composite** | fixed `0.5·z(MOM)+0.5·z(LOWRISK)` | simple, transparent combination; cf. Asness et al. (2015) style premia |
| Liquidity control | log median daily traded value | Amihud (2002); liquidity screening |

## Cross-sectional method

- **Fama–MacBeth (1973)** two-pass regressions; within-market standardised slopes;
  **Newey–West (1987)** HAC(6) standard errors on the monthly slope series.
- Standardisation within market-month limits currency and market-level artefacts;
  market fixed effects absorb the common (including FX) component within a month.

## Portfolio translation

- **Mean–variance optimisation** Markowitz (1952); long-only simplex solved with
  SLSQP (Kraft 1988).
- **Shrinkage covariance**: Ledoit & Wolf (2004).
- **1/N** benchmark: DeMiguel, Garlappi & Uppal (2009).
- **Transaction costs / turnover**: Frazzini, Israel & Moskowitz (2018) on trading
  costs of factor strategies; our frictions are illustrative, not official.

## External validation

- **JKP Global Factor Data** (Jensen, Kelly & Pedersen 2023) — country-level
  `momentum` and `low_risk`, USD decimal excess returns, value-weighted. Compared on
  exact common dates; **methodology and weighting differ** from our equal-weight,
  survivor-biased Q5−Q1 and this is disclosed.
- **Kenneth R. French Data Library** — `Mkt-RF`, `SMB`, `HML` for Japan, Developed,
  Asia-Pacific ex Japan. Used **only** as a market-return cross-check; French does
  not carry momentum/low-risk, and the ex-Japan aggregate is **not** the same as
  our HK/SG markets.
- **AQR** datasets are not present in the approved Prompt 1–2 inputs and the network
  is not accessed → reported `NOT_AVAILABLE`.

## Multiple testing / factor zoo

- **Harvey, Liu & Zhu (2016)**, “…and the Cross-Section of Expected Returns” —
  multiplicity; t>3 threshold intuition.
- **Feng, Giglio & Xiu (2020)**, “Taming the Factor Zoo” — factor selection.
- **Hou, Xue & Zhang (2020)**, “Replicating Anomalies” — replication fragility.
- **Harvey & Liu (2020)** — multiple-testing corrections (Bonferroni/Šidák/BHY).

Implication adopted here: nominal t-statistics are **not** discovery evidence. We
report a small pre-specified family, a multiplicity sensitivity, and rest the
conclusion on **economic significance and OOS net performance**, while flagging
survivorship bias in all seven markets.
