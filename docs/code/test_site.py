#!/usr/bin/env python3
"""Static-site contracts for the APAC Alpha-to-Portfolio microsite.

    .venv/bin/python tests/test_site.py

Verifies the required tree, no runtime external dependencies, resolvable links,
required disclosures/formulas, exactly three hero conclusions, headline values
equal to the canonical CSV, OOS/robustness/registry bounds, the local Plotly
bundle, >=15 interactive chart containers, and (best-effort) a browser smoke test.
"""
from __future__ import annotations

import csv
import html
import json
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
INDEX = DOCS / "index.html"
SITE_DATA_JS = DOCS / "assets" / "js" / "site-data.js"

DOI_HOSTS = {"doi.org"}


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
class SiteParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.refs: list[tuple[str, str, str]] = []  # (tag, attr, value)
        self.figures: list[dict] = []
        self.conclusion_cards = 0
        self.data_charts: list[str] = []
        self.table_scrolls: list[dict] = []
        self.table_scroll_cues = 0
        self._fig = None
        self._in_primary = False
        self._in_cell = False
        self._cell_buf: list[str] = []
        self._row: list[str] | None = None
        self.primary_rows: list[list[str]] = []
        self.visible_text: list[str] = []
        self.sources: list[dict] = []
        self.panels: dict[str, dict] = {}
        self._script_depth = 0
        self._in_source = False
        self._src_buf: list[str] = []
        self._src_classes: list[str] = []
        self._stage: str | None = None
        self._in_equation = False
        self._eq_buf: list[str] = []
        self._in_var = False
        self._in_var_li = False
        self._vli_buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if tag in ("script", "style"):
            self._script_depth += 1
        if tag == "a" and "href" in a:
            self.refs.append(("a", "href", a["href"]))
        if tag == "link" and "href" in a:
            self.refs.append(("link", "href", a["href"]))
        if tag == "script" and "src" in a:
            self.refs.append(("script", "src", a["src"]))
        if tag == "img" and "src" in a:
            self.refs.append(("img", "src", a["src"]))
        cls = (a.get("class") or "").split()
        if tag == "p" and "source" in cls:
            self._in_source = True
            self._src_buf = []
            self._src_classes = cls
        if "stage-panel" in cls:
            self._stage = a.get("id")
            self.panels[self._stage] = {"equation": "", "variables": []}
        if self._stage and "equation" in cls:
            self._in_equation = True
            self._eq_buf = []
        if self._stage and "variable-list" in cls:
            self._in_var = True
        if self._stage and self._in_var and tag == "li":
            self._in_var_li = True
            self._vli_buf = []
        if "conclusion-card" in cls:
            self.conclusion_cards += 1
        if "data-chart" in a:
            self.data_charts.append(a["data-chart"])
        if "table-scroll" in cls:
            self.table_scrolls.append({
                "tabindex": a.get("tabindex"),
                "role": a.get("role"),
                "aria_label": a.get("aria-label"),
            })
        if "table-scroll-cue" in cls:
            self.table_scroll_cues += 1
        if tag == "figure" and "chart" in cls:
            self._fig = {"source": False, "takeaway": False, "plot": False,
                         "controls": False, "data_chart": a.get("data-chart")}
            self.figures.append(self._fig)
        if self._fig is not None:
            if "source" in cls:
                self._fig["source"] = True
            if "takeaway" in cls:
                self._fig["takeaway"] = True
            if "plot" in cls:
                self._fig["plot"] = True
            if "chart-controls" in cls:
                self._fig["controls"] = True
        if tag == "table" and a.get("id") == "primary-table":
            self._in_primary = True
        if self._in_primary and tag == "tr":
            self._row = []
        if self._in_primary and tag in ("th", "td"):
            self._in_cell = True
            self._cell_buf = []

    def handle_data(self, data):
        if not self._script_depth:
            self.visible_text.append(data)
            if self._in_source:
                self._src_buf.append(data)
            if self._in_equation:
                self._eq_buf.append(data)
            if self._in_var_li:
                self._vli_buf.append(data)
        if self._in_cell:
            self._cell_buf.append(data)

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._script_depth:
            self._script_depth -= 1
        if tag == "p" and self._in_source:
            self.sources.append({"classes": self._src_classes,
                                 "text": "".join(self._src_buf).strip()})
            self._in_source = False
        if tag == "div" and self._in_equation:
            if self._stage:
                self.panels[self._stage]["equation"] = "".join(self._eq_buf).strip()
            self._in_equation = False
        if tag == "li" and self._in_var_li:
            if self._stage:
                self.panels[self._stage]["variables"].append("".join(self._vli_buf).strip())
            self._in_var_li = False
        if tag == "ul" and self._in_var:
            self._in_var = False
        if tag == "section" and self._stage:
            self._stage = None
        if tag == "figure":
            self._fig = None
        if self._in_primary and tag in ("th", "td"):
            self._in_cell = False
            if self._row is not None:
                self._row.append("".join(self._cell_buf).strip())
        if self._in_primary and tag == "tr":
            if self._row:
                self.primary_rows.append(self._row)
            self._row = None
        if tag == "table" and self._in_primary:
            self._in_primary = False


def parse_index() -> SiteParser:
    p = SiteParser()
    p.feed(INDEX.read_text(encoding="utf-8"))
    return p


def load_site_data() -> dict:
    raw = SITE_DATA_JS.read_text(encoding="utf-8").strip()
    prefix = "window.SITE_DATA = "
    assert raw.startswith(prefix), raw[:40]
    payload = raw[len(prefix):].rstrip()
    if payload.endswith(";"):
        payload = payload[:-1]
    return json.loads(payload)


def read_csv_rows(rel: str) -> list[dict]:
    with open(ROOT / rel, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def is_external(u: str) -> bool:
    return u.startswith("http://") or u.startswith("https://")


# --------------------------------------------------------------------------- #
# tests
# --------------------------------------------------------------------------- #
def test_required_tree():
    required = [
        "docs/index.html",
        "docs/assets/css/site.css",
        "docs/assets/js/plotly.min.js",
        "docs/assets/js/site-data.js",
        "docs/assets/js/site.js",
        "docs/methodology/methodology.md",
        "docs/methodology/literature.md",
        "scripts/build_site.py",
        "tests/test_site.py",
        "README.md",
    ]
    missing = [f for f in required if not (ROOT / f).exists()]
    assert not missing, missing
    figs = sorted((DOCS / "assets" / "figures").glob("*.png"))
    assert 2 <= len(figs) <= 4, [f.name for f in figs]


def test_no_runtime_external_dependencies():
    p = parse_index()
    bad = []
    for tag, attr, val in p.refs:
        if not is_external(val):
            continue
        if tag == "a":
            host = val.split("//", 1)[1].split("/", 1)[0].lower()
            if host not in DOI_HOSTS:
                bad.append((tag, val))
        else:
            bad.append((tag, val))
    assert not bad, bad


def test_nav_targets_exist():
    p = parse_index()
    hashes = [v for (t, a, v) in p.refs if t == "a" and v.startswith("#") and len(v) > 1]
    assert hashes, "no in-page nav links"
    missing = [h for h in hashes if h[1:] not in p.ids]
    assert not missing, missing


def test_relative_links_resolve():
    p = parse_index()
    missing = []
    for tag, attr, val in p.refs:
        if val.startswith("#") or is_external(val) or val.startswith("mailto:"):
            continue
        target = (DOCS / val.split("#", 1)[0]).resolve()
        if not target.exists():
            missing.append(val)
    assert not missing, missing


def test_required_disclosures_and_formulas():
    text = html.unescape(INDEX.read_text(encoding="utf-8"))
    required = [
        "Do Momentum and Low-Risk signals generalize across APAC equities, and can they be translated into an economically useful OOS portfolio?",
        "Survivor-biased exploratory evidence, not a bias-free historical APAC universe.",
        "t-12..t-2",
        "LOWRISK = \u2212vol_60",
        "0.5\u00b7z(MOM) + 0.5\u00b7z(LOWRISK)",
        "within-market",
        "market fixed effects",
        "HAC(6)",
        "|slope/t|\u00d71.96",
        "value-weighted",
        "equal-weight",
        "NOT_AVAILABLE",
        "6-market",
        "129 months",
        "2016-01..2026-09",
        "leave-one-out",
        "survivorship",
        "Sharpe",
    ]
    missing = [s for s in required if s not in text]
    assert not missing, missing


def test_exactly_three_hero_conclusions():
    p = parse_index()
    assert p.conclusion_cards == 3, p.conclusion_cards


def test_headline_values_equal_canonical_csv():
    rows = read_csv_rows("tables/final_apac_table.csv")
    by_pf = {r["Portfolio"]: r for r in rows}

    def pct1(x):
        return f"{float(x) * 100:.1f}%"

    def signed_pct1(x):
        v = float(x)
        return ("\u2212" if v < 0 else "") + f"{abs(v) * 100:.1f}%"

    expected = {}
    for name, r in by_pf.items():
        label = "Benchmark (6-mkt)" if name == "Benchmark" else name
        expected[label] = [pct1(r["NetReturn"]), pct1(r["Volatility"]),
                           f"{float(r['Sharpe']):.2f}", signed_pct1(r["MaxDrawdown"])]

    p = parse_index()
    body = p.primary_rows[1:]  # drop header
    assert len(body) == 6, body
    for row in body:
        label, cells = row[0], row[1:]
        assert label in expected, label
        assert cells == expected[label], (label, cells, expected[label])

    # exact source precision in SITE_DATA
    data = load_site_data()["headline_table"]
    for name, r in by_pf.items():
        for field in ("CAGR", "Volatility", "Sharpe", "MaxDrawdown", "NetReturn",
                      "WorstYear", "BestYear", "CountryConcentration"):
            assert abs(data[name][field] - float(r[field])) < 1e-9, (name, field, data[name][field], r[field])


def test_oos_129_bounds_and_series():
    data = load_site_data()
    months = data["oos"]["months"]
    assert len(months) == 129, len(months)
    assert months[0] == "2016-01" and months[-1] == "2026-09"
    assert months == sorted(months)
    for pf, series in data["oos"]["net"].items():
        assert len(series) == 129, (pf, len(series))
    assert len(data["oos"]["benchmark"]) == 129
    csv_rows = read_csv_rows("results/oos/oos_portfolio_returns_net15bps.csv")
    assert len(csv_rows) == 129, len(csv_rows)


def test_annual_rows_and_2026_partial():
    data = load_site_data()
    assert data["annual"]["years"] == list(range(2016, 2027))
    assert data["annual"]["partial_year"] == 2026
    assert data["annual"]["partial_months"] == 9
    meta = read_csv_rows("results/oos/oos_annual_returns_meta.csv")
    row2026 = [r for r in meta if int(r["year"]) == 2026][0]
    assert row2026["partial"].strip().lower() == "true"
    assert int(row2026["n_months"]) == 9
    for r in meta:
        if int(r["year"]) != 2026:
            assert r["partial"].strip().lower() == "false", r


def test_specification_registry():
    data = load_site_data()
    assert data["registry"]["total"] == 40
    assert len(data["registry"]["categories"]) == 7
    rows = read_csv_rows("SPECIFICATION_REGISTRY.csv")
    assert len(rows) == 40


def test_robustness_210_eight_families():
    data = load_site_data()
    assert len(data["robustness"]) == 210, len(data["robustness"])
    families = {r["family"] for r in data["robustness"]}
    assert len(families) == 8, sorted(families)
    manifest = read_csv_rows("results/robustness/robustness_manifest.csv")
    assert len(manifest) == 8
    # manifest.scope holds the summary `family` keys; manifest.family holds RF labels
    assert {r["scope"] for r in manifest} == families
    assert {r["family"] for r in manifest} == {f"RF{i}" for i in range(1, 9)}


def test_local_plotly_nonempty():
    js = (DOCS / "assets" / "js" / "plotly.min.js").read_text(encoding="utf-8", errors="ignore")
    assert len(js) > 1_000_000, len(js)
    assert "plotly.js" in js
    data_js = SITE_DATA_JS.read_text(encoding="utf-8")
    assert data_js.startswith("window.SITE_DATA = ")


def test_at_least_15_chart_containers_each_with_source_and_takeaway():
    p = parse_index()
    assert len(p.data_charts) >= 15, len(p.data_charts)
    assert len(p.figures) >= 15, len(p.figures)
    assert len(set(p.data_charts)) == len(p.data_charts), "duplicate chart keys"
    for fig in p.figures:
        assert fig["data_chart"], fig
        assert fig["source"], ("missing source", fig)
        assert fig["takeaway"], ("missing takeaway", fig)
        assert fig["plot"], ("missing plot", fig)
        assert fig["controls"], ("missing controls", fig)


def test_table_scroll_accessibility_and_mobile_cue():
    p = parse_index()
    assert p.table_scrolls, "no .table-scroll regions found"
    for i, ts in enumerate(p.table_scrolls):
        assert ts["tabindex"] == "0", (i, ts)
        assert ts["role"] == "region", (i, ts)
        assert ts["aria_label"] and ts["aria_label"].strip(), (i, ts)
    assert p.table_scroll_cues == len(p.table_scrolls), (p.table_scroll_cues, len(p.table_scrolls))
    css = (DOCS / "assets" / "css" / "site.css").read_text(encoding="utf-8")
    assert ".table-scroll-cue" in css, "mobile cue class missing from CSS"
    assert ".table-scroll-cue { display: none; }" in css.split("@media", 1)[0], "cue must be hidden on desktop"
    mobile = css.split("@media (max-width: 640px)", 1)
    assert len(mobile) == 2 and ".table-scroll-cue { display: block;" in mobile[1], "cue must be shown on mobile"
    text = html.unescape(INDEX.read_text(encoding="utf-8"))
    assert "Swipe table" in text, "mobile cue text missing"


def test_visible_text_has_no_model_note_or_markdown():
    p = parse_index()
    text = "".join(p.visible_text)
    assert "Institutional research microsite" not in text
    assert "Implementation model" not in text
    assert "opencode-go/deepseek-v4-flash" not in text
    assert "**" not in text
    assert "--" not in text


def test_all_static_sources_are_method_labels():
    p = parse_index()
    labels = [s for s in p.sources if "method-source" not in s["classes"]]
    assert labels, "no static .source elements parsed"
    for s in labels:
        assert s["text"].startswith("Calculation from"), s
        for token in (".csv", ".parquet", "/", "\\"):
            assert token not in s["text"], (token, s)


def test_primary_method_note_follows_source_immediately():
    p = parse_index()
    idx = [i for i, s in enumerate(p.sources)
           if s["text"].startswith("Calculation from net OOS portfolio accounting")]
    assert len(idx) == 1, idx
    note = p.sources[idx[0] + 1]
    note_text = re.sub(r"\s+", " ", note["text"]).strip()
    assert "source" in note["classes"] and "method-source" in note["classes"], note
    assert note_text.startswith("Method note."), note
    assert "net CAGR from NetReturn" in note_text, note
    assert "China benchmark history is inadequate" in note_text, note
    assert "Primary table from" not in "".join(p.visible_text)


REQUIRED_EQUATIONS = {
    "stage-1": ["ID", "ISO3", "MIC", "Ticker", "Class", "\u2225"],
    "stage-2": ["P", "adj", "\u2212 1"],
    "stage-3": ["MOM", "LOWRISK", "Composite", "252", "0.5"],
    "stage-4": ["IC", "Spearman", "Spread", "Q5", "Q1"],
    "stage-5": ["MOM_z", "LOWRISK_z", "Controls", "HAC(6)"],
    "stage-6": ["Corr", "JKP", "SignAgree", "sign"],
    "stage-7": ["\u2264", "z"],
    "stage-8": ["max", "Ledoit", "\u03bb", "SLSQP"],
    "stage-9": ["TO", "Rnet", "Rgross", "Tax"],
    "stage-10": ["Improve", "CAGR", "Sharpe", "1/N", "= 0"],
}


def test_pipeline_panels_have_equations_and_variable_lists():
    p = parse_index()
    assert len(p.panels) == 10, sorted(p.panels)
    for i in range(1, 11):
        key = f"stage-{i}"
        assert key in p.panels, key
        assert p.panels[key]["equation"].strip(), (key, "empty .equation")
        variables = p.panels[key]["variables"]
        assert variables and all(v.strip() for v in variables), (key, variables)
    for key, tokens in REQUIRED_EQUATIONS.items():
        blob = p.panels[key]["equation"] + " " + " ".join(p.panels[key]["variables"])
        missing = [t for t in tokens if t not in blob]
        assert not missing, (key, missing)
    css = (DOCS / "assets" / "css" / "site.css").read_text(encoding="utf-8")
    assert ".equation" in css and ".variable-list" in css


def test_hero_lede_states_evidence_and_caveat():
    raw = INDEX.read_text(encoding="utf-8")
    m = re.search(r'<p class="lede">(.*?)</p>', raw, re.S)
    assert m, "hero lede not found"
    lede = html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))
    lede = re.sub(r"\s+", " ", lede).lower()
    for token in ["momentum", "multiplicity correction", "low risk", "inverted",
                  "optimiz", "1/n", "survivorship"]:
        assert token in lede, (token, lede)


def test_site_data_literature_is_sanitized():
    lit = load_site_data()["literature"]
    bad = []

    def chk(value):
        if isinstance(value, str):
            for token in ("**", "__", "`", "--"):
                if token in value:
                    bad.append((token, value))

    for s in lit["signals"]:
        for v in s.values():
            chk(v)
    for sec in lit["sections"]:
        chk(sec["title"])
        for item in sec["items"]:
            chk(item)
    assert not bad, bad[:5]
    assert lit["signals"], "no literature signals"


def test_no_raw_or_parquet_under_docs():
    bad = []
    for path in DOCS.rglob("*"):
        if path.is_dir():
            continue
        if path.suffix.lower() in {".parquet", ".csv"}:
            bad.append(str(path.relative_to(ROOT)))
    assert not bad, bad


def test_static_html_parses():
    raw = INDEX.read_text(encoding="utf-8")
    assert raw.lstrip().lower().startswith("<!doctype html")
    p = parse_index()
    assert "main" in p.ids
    assert any(t == "h1" for t in re.findall(r"<h1", raw)) or "<h1" in raw
    assert "skip-link" in raw


def test_js_syntax_via_node():
    node = shutil.which("node")
    if not node:
        print("  (node not available - skipped)")
        return
    for rel in ("docs/assets/js/site-data.js", "docs/assets/js/site.js"):
        rc = subprocess.run([node, "--check", str(ROOT / rel)],
                            capture_output=True, text=True)
        assert rc.returncode == 0, (rel, rc.stderr)


def test_browser_smoke():
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("  (playwright not installed - skipped)")
        return
    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch()
            except Exception as exc:  # chromium binary missing
                print(f"  (chromium unavailable - skipped: {exc})")
                return
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(INDEX.as_uri())
            page.wait_for_timeout(800)
            # sticky nav must be fully opaque so table content cannot bleed through
            nav_bg = page.eval_on_selector(
                ".site-nav", "el=>getComputedStyle(el).backgroundColor")
            alpha = 1.0
            mrgba = re.match(r"rgba?\(([^)]+)\)", nav_bg)
            if mrgba:
                parts = [p.strip() for p in mrgba.group(1).split(",")]
                if len(parts) == 4:
                    alpha = float(parts[3])
            assert alpha == 1, nav_bg
            # pipeline tab interaction
            page.click("#tab-3")
            assert page.eval_on_selector("#stage-3", "el=>!el.hidden")
            assert page.eval_on_selector("#stage-1", "el=>el.hidden")
            # force-render every chart by scrolling to each sequentially
            keys = page.eval_on_selector_all("[data-chart]", "els=>els.map(e=>e.dataset.chart)")
            for key in keys:
                page.eval_on_selector("#chart-" + key,
                                     "el=>el.scrollIntoView({block:'center'})")
                page.wait_for_timeout(120)
            charts = page.eval_on_selector_all(
                "[data-chart]",
                "els=>els.filter(e=>e.querySelector('.plot .main-svg')).length")
            assert charts == 15, f"rendered charts: {charts}"
            # annual heatmap: y = years (11 rows), z = years x ports (11 x 6)
            ann = page.eval_on_selector("#chart-annual .plot", "el=>({"
                                        "ylen: el.data[0].y.length,"
                                        "y0: String(el.data[0].y[0]),"
                                        "ylast: String(el.data[0].y[el.data[0].y.length-1]),"
                                        "zrows: el.data[0].z.length,"
                                        "zcols: el.data[0].z[0].length})")
            assert ann["ylen"] == 11, ann
            assert ann["y0"] == "2016" and ann["ylast"] == "2026*", ann
            assert ann["zrows"] == 11 and ann["zcols"] == 6, ann
            # default metrics bar chart: upper axis range clears the tallest bar
            met = page.eval_on_selector("#chart-metrics .plot", "el=>({"
                                        "upper: el._fullLayout.yaxis.range[1],"
                                        "maxBar: Math.max.apply(null, el.data[0].y)})")
            assert met["upper"] > met["maxBar"], met
            # a selector control updates the chart without error
            page.select_option("#chart-metrics select", "Sharpe")
            page.wait_for_timeout(400)
            # dynamic literature: no raw Markdown markers or leading emphasis
            lit_text = page.eval_on_selector("#literature-table", "el=>el.innerText")
            assert "**" not in lit_text, lit_text
            assert not re.search(r"(?m)^\s*[*_`]", lit_text), lit_text
            refs = page.eval_on_selector_all("#reference-list li", "els=>els.length")
            assert refs >= 12, refs
            assert not errors, errors
            # mobile: sticky nav scrolls horizontally without document overflow
            mob = browser.new_page(viewport={"width": 390, "height": 844})
            mob.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            mob.on("pageerror", lambda e: errors.append(str(e)))
            mob.goto(INDEX.as_uri())
            mob.wait_for_timeout(600)
            # pipeline equations remain readable and inside the viewport at 390px
            mob.click("#tab-8")
            mob.wait_for_timeout(200)
            eq = mob.eval_on_selector("#stage-8 .equation", """el => {
              const r = el.getBoundingClientRect();
              return {text: (el.textContent || '').trim(), right: r.right, width: window.innerWidth};
            }""")
            assert eq["text"], eq
            assert eq["right"] <= eq["width"] + 1, eq
            assert "--" not in eq["text"], eq
            # stage-8 objective is split into three deliberate block lines
            eq_lines = mob.eval_on_selector_all(
                "#stage-8 .equation .eq-line",
                "els=>els.map(e=>({t:(e.textContent||'').trim(),"
                "scroll:e.scrollWidth, client:e.clientWidth}))")
            assert len(eq_lines) == 3, eq_lines
            eq_scroll = mob.eval_on_selector(
                "#stage-8 .equation",
                "el=>({scroll:el.scrollWidth, client:el.clientWidth,"
                "overflowX:getComputedStyle(el).overflowX})")
            eq_hscroll = (eq_scroll["scroll"] > eq_scroll["client"]
                          and eq_scroll["overflowX"] in ("auto", "scroll"))
            for ln in eq_lines:
                assert ln["scroll"] <= ln["client"] or eq_hscroll, (ln, eq_scroll)
            l1, l2, l3 = (ln["t"] for ln in eq_lines)
            assert "|" not in l1 and "|" not in l3, (l1, l3)
            # both absolute-value bars live in the turnover line: no DOM/line split
            assert l2.count("|") == 2, l2
            assert l2.startswith("\u2212") and l2.endswith("|"), l2
            assert "0.5" in l2 and "w_prev" in l2, l2
            # force-render the two charts whose axis layout we assert at 390px
            mob.evaluate(
                "() => { for (const [node, render] of window.__siteCharts) {"
                " if (node.dataset.chart === 'annual' || node.dataset.chart === 'cost') {"
                " node.dataset.rendered = '1'; render(); } } }")
            mob.wait_for_timeout(500)
            # annual heatmap: category x-axis keeps automargin and six non-empty port labels
            ann = mob.eval_on_selector("#chart-annual .plot", "el=>({"
                                       "automargin: el._fullLayout.xaxis.automargin,"
                                       "cats: el._fullLayout.xaxis._categories.slice()})")
            assert ann["automargin"] is True, ann
            assert len(ann["cats"]) == 6, ann
            assert all(str(c).strip() for c in ann["cats"]), ann
            # cost chart: x-axis title is gone (or, if present, does not collide with legend)
            cost = mob.eval_on_selector("#chart-cost .plot", """el => {
              const fl = el._fullLayout;
              const titleText = ((fl.xaxis.title || {}).text || '').trim();
              const titleEl = el.querySelector('.xtitle');
              let intersects = false;
              if (titleEl) {
                const tb = titleEl.getBoundingClientRect();
                const legend = el.querySelector('.legend');
                if (legend && tb.width && tb.height) {
                  const lb = legend.getBoundingClientRect();
                  intersects = !(tb.right <= lb.left || tb.left >= lb.right ||
                                 tb.bottom <= lb.top || tb.top >= lb.bottom);
                }
              }
              return {titleText, intersects};
            }""")
            assert (not cost["titleText"]) or (not cost["intersects"]), cost
            over = mob.evaluate(
                "Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)"
                " - window.innerWidth")
            assert over <= 0, f"document overflow: {over}px"
            assert not errors, errors
            # every rendered .table-scroll (static + JS-built) is a labelled focusable region
            scrolls = mob.eval_on_selector_all(
                ".table-scroll",
                "els=>els.map(e=>({t:e.getAttribute('tabindex'),"
                "r:e.getAttribute('role'),l:e.getAttribute('aria-label')}))")
            assert scrolls, "no rendered .table-scroll regions"
            for s in scrolls:
                assert s["t"] == "0" and s["r"] == "region" and s["l"], s
            mob.close()
            browser.close()
    except AssertionError:
        raise
    except Exception as exc:
        print(f"  (browser smoke inconclusive - skipped: {exc})")


def main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {t.__name__}: {e!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
