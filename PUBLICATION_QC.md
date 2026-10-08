# Publication QC — APAC Alpha-to-Portfolio

Packaging-only QC record for this public repository bundle. No git initialization, commit
or push was performed. The bundle was assembled from a private working tree and written
atomically to its destination; the private working tree was not modified.

> **The evidence in this repository is survivor-biased exploratory evidence, not a
> bias-free historical APAC universe, and is not investment advice.**

## Scope

Included:

- `README.md`, `.gitignore`.
- `docs/` — the complete microsite (HTML/CSS/JS, bundled Plotly, four QC figures, method and
  literature pages).
- `docs/audit/` — frozen data/methodology documents and the 40-spec registry.
- `docs/reports/` — final report, executive summary, cleaning/acquisition reports, source matrix.
- `docs/code/` — three pipeline scripts plus the site generator and the reference static-site
  contract test.
- `docs/results/` and `docs/tables/` — the selected canonical public summary CSVs.

Excluded by design: raw and processed market data, Parquet, `.venv`, logs, `.review`,
non-selected full results, figures outside the existing site assets, credentials, `.env`,
other manifests, and Git metadata.

The public bundle cannot regenerate the source data: `docs/assets/js/site-data.js` holds the
presentation payload derived from the canonical public summary tables, and the pipeline
scripts are methodology/code references. **Raw reproducibility from this repository is not
claimed.**

Provenance note: the private working tree path is intentionally omitted and referred to only
as the private working tree.

## Verification results

| # | Check | Result |
|---|-------|--------|
| 1 | `docs/index.html` parsed with Python stdlib; every non-http href/src resolves inside `docs/`; all `#` anchors exist; no `../` links | PASS (64 refs) |
| 2 | No symlinks in the bundle | PASS |
| 3 | No `.parquet/.xlsx/.xls/.env/.key/.pem/.sqlite/.db`, no `auth/token/credential/id_ed25519`, no `.git` | PASS |
| 4 | Secret/token/API-key/Windows-WSL path scan of all text and code | PASS — only benign matches in vendored `plotly.min.js` (see below) |
| 5 | `node --check docs/assets/js/site.js` and `site-data.js` | PASS |
| 6 | Served bundle; Playwright smoke test | PASS — see below |
| 7 | File count/bytes; no individual file ≥ 100 MB | PASS |
| 8 | `PUBLICATION_MANIFEST.txt` (path, bytes, SHA256, count, total) | See manifest |

Check 1 was also confirmed after a one-line `docs/index.html` patch that points `rel="icon"`
at an existing bundled figure, removing the browser's `/favicon.ico` 404.

Check 4 detail: the Windows-path detector flagged three single-letter sequences inside the
vendored third-party `docs/assets/js/plotly.min.js` (e.g. `n:\n`), which are JavaScript escape
sequences, not filesystem paths. No private-key headers, `ghp_`/`github_pat_` tokens, API-key
assignments, `/mnt/...`, `/home/...` or `/Users/...` paths were found in any bundled text or
code. No genuine match was found; nothing was silently skipped.

Check 6 detail (local HTTP server, Chromium):

- `docs/index.html` loads with HTTP 200 and **zero console/page errors**.
- All **15** interactive charts render (keys: coverage, ic, quintiles, fm, jkp, wealth,
  drawdown, rolling, metrics, annual, exposure, cost, turnover, grossnet, robustness).
- Internal pipeline tab control works (tab 3 shows `stage-3`, hides `stage-1`).
- All **25** unique internal links to `audit/`, `code/`, `reports/`, `results/`, `tables/` and
  `methodology/` return HTTP 200 over localhost.
- Mobile viewport 390 px: document horizontal overflow = 0 px.

Check 7 detail: the authoritative file count and total byte size, including this QC file and
the manifest, are recorded in `PUBLICATION_MANIFEST.txt`. No single file reaches 100 MB (the
largest is the bundled `plotly.min.js` at ~4.6 MB).
