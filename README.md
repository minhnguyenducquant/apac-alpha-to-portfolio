# APAC Alpha-to-Portfolio

Survivor-biased exploratory research microsite: **do Momentum and Low-Risk signals
generalize across APAC equities, and can they be translated into an economically useful
out-of-sample portfolio?** Seven markets (CN, HK, IN, JP, KR, SG, TW), 210 curated names,
monthly research panel 2010-01..2026-10, OOS 2016-01..2026-09 (2026 partial).

> **Survivor-biased exploratory evidence, not a bias-free historical APAC universe.**
> Not investment advice.

## Microsite (GitHub Pages)

- [`docs/index.html`](docs/index.html) — the static interactive microsite.
- [`docs/methodology/methodology.md`](docs/methodology/methodology.md) and
  [`docs/methodology/literature.md`](docs/methodology/literature.md) — method/reference pages.

The site uses only local assets (a bundled `plotly.min.js`, one CSS and one JS file) and a
precomputed presentation payload. No CDN, no external fonts, no network calls. It works from
`file://` as well as over HTTP.

### Publish with GitHub Pages

1. Push this repository to GitHub.
2. In **Settings → Pages**, set **Source** to *Deploy from a branch*.
3. Choose branch **`main`** and folder **`/docs`**, then save.

GitHub publishes at the project Pages URL (typically `https://<owner>.github.io/<repo>/`).
No hosted URL is claimed here.

## Scope and headline results

A small, pre-specified set of equity return predictors is tested on a monthly panel of CN, HK,
IN, JP, KR, SG and TW, then translated into long-only country-sleeve portfolios evaluated
out-of-sample in USD, net of illustrative frictions and dated taxes.

| Portfolio | Net CAGR | Volatility | Sharpe |
|---|---|---|---|
| Benchmark (6-mkt) | 9.7% | 16.4% | 0.51 |
| 1/N | 15.9% | 15.5% | 0.89 |
| Momentum | 22.6% | 18.7% | 1.07 |
| Low Risk | 11.5% | 12.9% | 0.74 |
| Composite | 14.1% | 14.0% | 0.85 |
| Optimized | 12.5% | 13.9% | 0.76 |

- Momentum is the strongest signal and the only member of the primary family to survive the
  project's own Sidak/Bonferroni multiplicity correction (pooled IC 0.0331; FM NW HAC(6)
  t = 3.30).
- Low Risk lowers realised volatility to 12.9% but its premium is **inverted** in this panel
  (Q5−Q1 negative in 7/7 markets).
- The long-only optimizer does **not** beat equal-weight 1/N out-of-sample (12.5% vs 15.9% net
  CAGR; 0.76 vs 0.89 Sharpe); lower volatility is its sole improvement.

## Limitations

- **Current-universe survivorship in all seven markets**, not cured; CN/HK carry 0/N delisting
  coverage. Evidence is exploratory and conditional on a 210-name curated sample.
- Single price source for most markets (independent cross-check only for CN/HK).
- CN beta/IVOL unavailable (one-row benchmark); CN excluded from market-model signals only.
- Historical taxes verified only for CN/HK; other jurisdictions not applied.
- 2026 is partial (9 months) and flagged incomplete throughout.

## Repository contents

| Path | Role |
|------|------|
| `docs/index.html` | interactive microsite (GitHub Pages entry point) |
| `docs/assets/js/site-data.js` | presentation payload derived from the canonical public summary tables |
| `docs/audit/` | frozen data/methodology documents and the 40-spec registry |
| `docs/reports/` | final report, executive summary, cleaning/acquisition reports |
| `docs/results/` | selected canonical summary CSVs backing the site |
| `docs/tables/final_apac_table.csv` | primary OOS result table (net) |
| `docs/code/` | methodology/code references (see below) |

### Code and reproducibility

This public bundle is a **presentation and methodology artifact**, not a reproducible data
pipeline. It ships no raw or processed market data.

- `docs/assets/js/site-data.js` contains the presentation payload derived from the canonical
  public summary tables in `docs/results/`, `docs/tables/` and `docs/audit/`.
- The three pipeline scripts `docs/code/acquire_and_audit.py`,
  `docs/code/clean_and_build_panel.py` and `docs/code/run_main_tests.py` are
  **methodology/code references** documenting how the recorded numbers were produced. Running
  them requires private vendor inputs that are not published here.
- `docs/code/build_site.py` documents how the static payload and assets were generated.
  `docs/code/test_site.py` is the reference static-site contract from the private working tree;
  its paths assume that private layout, so it is included as a code reference, not a runnable
  harness for this bundle.

**Raw reproducibility from this repository is not claimed.**

## Local preview

No build step is needed to serve the site:

```bash
python3 -m http.server --directory docs 8080
# then open http://localhost:8080/
```

## Licence and use

Research artifact provided as-is; not investment advice.
