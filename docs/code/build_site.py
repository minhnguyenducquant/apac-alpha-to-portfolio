#!/usr/bin/env python3
"""Deterministic static-site builder for the APAC Alpha-to-Portfolio microsite.

Reads existing canonical outputs ONLY. Never re-runs or imports any empirical
script, and never writes under data/, results/, reports/, figures/ or tables/.

Emits (all under docs/):
  assets/js/site-data.js    window.SITE_DATA = {...};   (precomputed presentation data)
  assets/js/plotly.min.js   bundled from the installed Python Plotly, no CDN
  assets/figures/*.png      4 selected data-cleaning QC images (copied)
  methodology/methodology.md, methodology/literature.md  (public faithful copies)

Run:  .venv/bin/python scripts/build_site.py
"""
from __future__ import annotations

import json
import math
import re
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ASSETS = DOCS / "assets"

OOS = pd.period_range("2016-01", "2026-09", freq="M")
OOS_MONTHS = [str(p) for p in OOS]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _isfinite(x) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def jsonable(o):
    """Recursively convert numpy/pandas scalars and NaN -> JSON-safe values."""
    if o is None:
        return None
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (int,)):
        return o
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, str):
        return o
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    try:
        if pd.isna(o):
            return None
    except (TypeError, ValueError):
        pass
    return str(o)


def r6(x):
    return round(float(x), 6) if _isfinite(x) else None


def read(rel: str) -> pd.DataFrame:
    return pd.read_csv(ROOT / rel)


def period_csv(rel: str) -> pd.DataFrame:
    df = pd.read_csv(ROOT / rel, index_col=0)
    df.index = pd.PeriodIndex(df.index, freq="M")
    return df


def records(df: pd.DataFrame, round_cols=()) -> list:
    out = []
    for row in df.to_dict(orient="records"):
        row = {k: (r6(v) if k in round_cols else v) for k, v in row.items()}
        out.append(jsonable(row))
    return out


def series_map(df: pd.DataFrame, cols, index=None, roundv=True):
    res = {}
    for c in cols:
        s = df[c]
        if index is not None:
            s = s.reindex(index)
        res[c] = [r6(v) if roundv else jsonable(v) for v in s.tolist()]
    return res


def cumulative_wealth(returns):
    w, out = 1.0, []
    for r in returns:
        if r is None:
            out.append(None)
            continue
        w *= (1.0 + r)
        out.append(r6(w))
    return out


def drawdown(wealth):
    out, peak = [], None
    for w in wealth:
        if w is None:
            out.append(None)
            continue
        peak = w if peak is None else max(peak, w)
        out.append(r6(w / peak - 1.0))
    return out


def rolling_product(returns, window=12):
    out = []
    for i in range(len(returns)):
        if i < window - 1 or any(returns[j] is None for j in range(i - window + 1, i + 1)):
            out.append(None)
            continue
        p = 1.0
        for j in range(i - window + 1, i + 1):
            p *= (1.0 + returns[j])
        out.append(r6(p - 1.0))
    return out


# --------------------------------------------------------------------------- #
# literature: parse LITERATURE_MAPPING.md (no invented references)
# --------------------------------------------------------------------------- #
RECORDED_DOI = {
    "Ince, O. S., & Porter, R. B. (2006)": "https://doi.org/10.1111/j.1475-6803.2006.00189.x",
    "Shumway, T. (1997)": "https://doi.org/10.1111/j.1540-6261.1997.tb03818.x",
    "Dimson, E. (1979)": "https://doi.org/10.1016/0304-405X(79)90013-8",
    "Hou, K., Xue, C., & Zhang, L. (2020)": "https://doi.org/10.1093/rfs/hhy131",
    "Novy-Marx, R., & Velikov, M. (2016)": "https://doi.org/10.1093/rfs/hhv063",
    "Jegadeesh, N., & Titman, S. (1993)": "https://doi.org/10.1111/j.1540-6261.1993.tb04702.x",
    "Fama, E. F., & French, K. R. (2012)": "https://doi.org/10.1016/j.jfineco.2011.09.004",
    "Asness, C. S., Moskowitz, T. J., & Pedersen, L. H. (2013)": "https://doi.org/10.1111/jofi.12021",
    "Frazzini, A., & Pedersen, L. H. (2014)": "https://doi.org/10.1111/jofi.12234",
    "Ang, A., Hodrick, R. J., Xing, Y., & Zhang, X. (2009)": "https://doi.org/10.1111/j.1540-6261.2009.01483.x",
    "Hou, K., Karolyi, G. A., & Kho, B.-C. (2011)": "https://doi.org/10.1111/j.1540-6261.2011.01671.x",
    "Jensen, T. I., Kelly, B., & Pedersen, L. H. (2023)": "https://doi.org/10.1111/jofi.13249",
}


_MD_TOKENS = re.compile(r"\*\*|__|`")


def sanitize_presentation(value):
    """Strip inline Markdown emphasis/backtick markers from rendered strings.

    Presentation only: words, en dashes, minus signs, formulas and DOI links are
    preserved. Source-of-record methodology files are never modified.
    """
    if not isinstance(value, str):
        return value
    return _MD_TOKENS.sub("", value)


def parse_literature() -> dict:
    text = (ROOT / "LITERATURE_MAPPING.md").read_text(encoding="utf-8")
    sections, signals = [], []
    cur_title = None
    cur_items: list = []
    in_signals = False

    def flush():
        nonlocal cur_items
        if cur_title and cur_items:
            sections.append({"title": sanitize_presentation(cur_title),
                             "items": [sanitize_presentation(it) for it in cur_items]})
        cur_items = []

    for line in text.splitlines():
        line = line.rstrip()
        if line.startswith("## "):
            flush()
            cur_title = line[3:].strip()
            in_signals = cur_title.lower().startswith("signals")
            continue
        if in_signals and line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 3 and not set("".join(cells)) <= set("-: "):
                if cells[0].lower() == "signal":
                    continue
                signals.append({
                    "signal": sanitize_presentation(cells[0]).strip(),
                    "implementation": sanitize_presentation(cells[1]).strip(),
                    "anchor": sanitize_presentation(cells[2]).strip(),
                })
            continue
        if line.strip().startswith("- "):
            cur_items.append(line.strip()[2:].strip())
    flush()

    references = []
    for cite, url in RECORDED_DOI.items():
        references.append({"cite": cite, "url": url})
    return {"signals": signals, "sections": sections, "references": references}


# --------------------------------------------------------------------------- #
# data assembly
# --------------------------------------------------------------------------- #
def build_data() -> dict:
    ft = read("tables/final_apac_table.csv").set_index("Portfolio")

    headline = {}
    for name, row in ft.iterrows():
        headline[name] = jsonable({
            "CAGR": row["CAGR"], "Volatility": row["Volatility"], "Sharpe": row["Sharpe"],
            "MaxDrawdown": row["MaxDrawdown"], "Turnover": row["Turnover"],
            "NetReturn": row["NetReturn"], "WorstYear": row["WorstYear"],
            "BestYear": row["BestYear"], "CountryConcentration": row["CountryConcentration"],
        })

    # --- coverage ---------------------------------------------------------
    sqc = read("reports/signal_qc.csv")
    coverage = records(sqc[[
        "market", "n_securities", "n_obs_months", "n_return_valid", "return_valid_pct",
        "n_eligible", "eligible_pct", "n_below_liquidity_cutoff", "n_mom_12_1",
        "n_vol_60", "n_vol_252", "n_beta", "n_ivol"]],
        round_cols={"return_valid_pct", "eligible_pct"})

    # --- IC ---------------------------------------------------------------
    icc = read("results/signal_tests/ic_by_country.csv")
    icp = read("results/signal_tests/ic_pooled_apac.csv")
    ic_by_country = records(icc, round_cols={"avg_ic", "std_ic", "icir", "pos_freq", "avg_n"})
    ic_pooled = records(icp, round_cols={"avg_ic", "std_ic", "icir", "pos_freq", "avg_n"})

    # --- Fama-MacBeth -----------------------------------------------------
    fmp = read("results/fama_macbeth/fm_pooled.csv")
    fmc = read("results/fama_macbeth/fm_by_country.csv")
    fm_pooled = records(fmp, round_cols={"mean_slope", "nw_t", "econ_per_1sd", "avg_n"})
    fm_by_country = records(fmc, round_cols={"mean_slope", "nw_t", "econ_per_1sd", "avg_n"})

    # --- quintiles --------------------------------------------------------
    def quint(rel):
        df = read(rel)
        return records(df, round_cols={"ann_geom", "vol", "mean", "n_avg",
                                       "monotonicity", "q5_minus_q1_mean"})
    quintiles = {
        "mom": quint("results/signal_tests/quintiles_mom.csv"),
        "lowrisk": quint("results/signal_tests/quintiles_lowrisk.csv"),
        "vol252": quint("results/robustness/vol252_quintiles.csv"),
    }

    # --- external validation ---------------------------------------------
    jkp_cols = ["signal", "market", "n", "corr", "sign_agree", "own_mean", "jkp_mean",
                "own_vol", "jkp_vol", "own_sharpe", "jkp_sharpe", "own_maxdd", "jkp_maxdd",
                "pre2020_n", "pre2020_corr", "post2020_n", "post2020_corr"]
    jkp = {
        "momentum": records(read("results/jkp_validation/jkp_momentum.csv")[jkp_cols],
                            round_cols=set(jkp_cols) - {"signal", "market", "n", "pre2020_n", "post2020_n"}),
        "low_risk": records(read("results/jkp_validation/jkp_lowrisk.csv")[jkp_cols],
                            round_cols=set(jkp_cols) - {"signal", "market", "n", "pre2020_n", "post2020_n"}),
    }
    french = records(read("results/jkp_validation/french_crosscheck.csv"),
                     round_cols={"corr", "our_mean", "french_mean"})
    aqr = records(read("results/jkp_validation/aqr_status.csv"))[0]

    # --- OOS net series (canonical 129 months) ---------------------------
    net = period_csv("results/oos/oos_portfolio_returns_net15bps.csv")
    net = net.reindex(OOS)
    bench = read("results/portfolio/benchmark_returns.csv")
    bench["ym"] = pd.PeriodIndex(bench["ym"], freq="M")
    bench = bench.set_index("ym")["Benchmark"].reindex(OOS)
    bser = [r6(v) for v in bench.tolist()]

    net_series = series_map(net, list(net.columns), index=OOS)
    wealth = {c: cumulative_wealth(net_series[c]) for c in net_series}
    dd = {c: drawdown(wealth[c]) for c in wealth}
    roll = {c: rolling_product(net_series[c], 12) for c in net_series}

    bwealth = cumulative_wealth(bser)
    oos = {
        "months": OOS_MONTHS,
        "net": net_series,
        "benchmark": bser,
        "wealth": wealth,
        "wealth_benchmark": bwealth,
        "drawdown": dd,
        "drawdown_benchmark": drawdown(bwealth),
        "rolling12": roll,
        "rolling12_benchmark": rolling_product(bser, 12),
    }

    # --- annual (canonical net) + gross + partial flag -------------------
    ann_net = read("results/oos/oos_annual_returns.csv").set_index("year")
    ann_gross = read("results/oos/oos_annual_returns_gross.csv").set_index("year")
    ann_meta = read("results/oos/oos_annual_returns_meta.csv").set_index("year")
    years = [int(y) for y in ann_net.index]
    annual = {
        "years": years,
        "partial_year": int(ann_meta.index[ann_meta["partial"].astype(bool)][0]),
        "partial_months": int(ann_meta.loc[ann_meta["partial"].astype(bool), "n_months"].iloc[0]),
        "net": {c: [r6(v) for v in ann_net[c].tolist()] for c in ann_net.columns},
        "gross": {c: [r6(v) for v in ann_gross[c].tolist()] for c in ann_gross.columns},
    }

    # --- costs, turnover, weights, risk ----------------------------------
    cost = records(read("results/transaction_costs/cost_sensitivity.csv"),
                   round_cols={"cagr", "vol", "sharpe", "max_dd", "mean_turnover", "tax_cagr"})
    tax = records(read("results/transaction_costs/tax_coverage.csv"))

    to = period_csv("results/portfolio/turnover.csv").reindex(OOS)
    turnover = {"months": OOS_MONTHS, "series": series_map(to, list(to.columns), index=OOS)}

    weights = records(read("results/portfolio/weights_summary.csv"), round_cols={"avg_weight"})
    risk = records(read("results/portfolio/risk_contribution.csv"),
                   round_cols={"risk_share", "sleeve_vol"})
    conc = records(read("results/portfolio/concentration.csv"),
                   round_cols={"country_hhi", "max_country_weight", "name_hhi"})

    # --- robustness (all 210 recorded rows) ------------------------------
    rob = read("results/robustness/robustness_summary.csv")[
        ["family", "variation", "factor", "group", "metric", "value", "label", "status", "note"]]
    robustness = records(rob, round_cols={"value"})
    rob_manifest = records(read("results/robustness/robustness_manifest.csv"))

    # --- spec registry ----------------------------------------------------
    reg = read("SPECIFICATION_REGISTRY.csv")
    registry = {
        "total": int(len(reg)),
        "categories": {k: int(v) for k, v in reg["category"].value_counts().items()},
        "classifications": {k: int(v) for k, v in reg["classification"].value_counts().items()},
    }

    lit = parse_literature()

    sources = {
        "coverage": "reports/signal_qc.csv",
        "ic": "results/signal_tests/ic_by_country.csv; results/signal_tests/ic_pooled_apac.csv",
        "quintiles": "results/signal_tests/quintiles_mom.csv; quintiles_lowrisk.csv; results/robustness/vol252_quintiles.csv",
        "fm": "results/fama_macbeth/fm_pooled.csv; results/fama_macbeth/fm_by_country.csv",
        "jkp": "results/jkp_validation/jkp_momentum.csv; results/jkp_validation/jkp_lowrisk.csv",
        "wealth": "results/oos/oos_portfolio_returns_net15bps.csv; results/portfolio/benchmark_returns.csv",
        "drawdown": "results/oos/oos_portfolio_returns_net15bps.csv; results/portfolio/benchmark_returns.csv",
        "metrics": "tables/final_apac_table.csv",
        "cost": "results/transaction_costs/cost_sensitivity.csv",
        "turnover": "results/portfolio/turnover.csv",
        "exposure": "results/portfolio/weights_summary.csv; results/portfolio/risk_contribution.csv",
        "robustness": "results/robustness/robustness_summary.csv; results/robustness/robustness_manifest.csv",
        "annual": "results/oos/oos_annual_returns.csv; results/oos/oos_annual_returns_meta.csv",
        "rolling": "results/oos/oos_portfolio_returns_net15bps.csv",
        "grossnet": "results/oos/oos_annual_returns_gross.csv; results/oos/oos_annual_returns.csv",
    }

    data = {
        "meta": {
            "question": ("Do Momentum and Low-Risk signals generalize across APAC equities, "
                         "and can they be translated into an economically useful OOS portfolio?"),
            "badges": [
                "7 markets", "210 stocks", "2010-2026 research",
                "2016-2026 OOS / 2026 partial", "Momentum + Low Risk",
                "Survivor-biased exploratory sample",
            ],
            "model": "opencode-go/deepseek-v4-flash",
            "research_window": "2010-01..2026-10 monthly panel",
            "oos": {"start": "2016-01", "end": "2026-09", "months": len(OOS), "partial_year": 2026},
            "sharpe_note": "Rolling 36m Sharpe omitted (no safe canonical risk-free merge); a recorded gross-vs-net comparison is shown instead.",
        },
        "coverage": coverage,
        "ic": {"pooled": ic_pooled, "by_country": ic_by_country},
        "fm": {"pooled": fm_pooled, "by_country": fm_by_country},
        "quintiles": quintiles,
        "jkp": jkp,
        "french": french,
        "aqr": aqr,
        "oos": oos,
        "annual": annual,
        "cost": cost,
        "tax": tax,
        "turnover": turnover,
        "weights": weights,
        "risk_contribution": risk,
        "concentration": conc,
        "robustness": robustness,
        "robustness_manifest": rob_manifest,
        "registry": registry,
        "headline_table": headline,
        "literature": lit,
        "sources": sources,
    }
    return jsonable(data)


# --------------------------------------------------------------------------- #
# writers
# --------------------------------------------------------------------------- #
def write_data_js(data: dict):
    out = ASSETS / "js" / "site-data.js"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    out.write_text("window.SITE_DATA = " + payload + ";\n", encoding="utf-8")
    return out


def write_plotly():
    from plotly.offline import get_plotlyjs
    out = ASSETS / "js" / "plotly.min.js"
    out.write_text(get_plotlyjs(), encoding="utf-8")
    return out


QC_FIGURES = [
    "01_price_validity_by_market.png",
    "05_return_coverage_by_month.png",
    "09_survivorship_flags.png",
    "12_signal_coverage_by_market.png",
]


def copy_figures():
    dest = ASSETS / "figures"
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in QC_FIGURES:
        src = ROOT / "reports" / "charts" / "cleaning" / name
        if not src.exists():
            raise FileNotFoundError(src)
        shutil.copy2(src, dest / name)
        copied.append(name)
    return copied


def write_methodology_docs():
    mdir = DOCS / "methodology"
    mdir.mkdir(parents=True, exist_ok=True)
    header = (
        "<!-- Public copy generated by scripts/build_site.py. Source of record: "
        "`{src}`. Content is an unmodified copy; paths inside refer to the repository root. -->\n\n"
    )
    meth = (ROOT / "METHODOLOGY_MAIN_TESTS.md").read_text(encoding="utf-8")
    (mdir / "methodology.md").write_text(
        header.format(src="METHODOLOGY_MAIN_TESTS.md") + meth, encoding="utf-8")
    lit = (ROOT / "LITERATURE_MAPPING.md").read_text(encoding="utf-8")
    (mdir / "literature.md").write_text(
        header.format(src="LITERATURE_MAPPING.md") + lit, encoding="utf-8")
    return [mdir / "methodology.md", mdir / "literature.md"]


def self_check(data: dict, data_js: Path, plotly: Path, figs: list, docs: list):
    assert data_js.exists() and data_js.stat().st_size > 0
    assert plotly.exists() and plotly.stat().st_size > 1_000_000, plotly.stat().st_size
    assert len(figs) == 4, figs
    assert all(p.exists() for p in docs)
    assert len(data["robustness"]) == 210, len(data["robustness"])
    assert len(data["registry"]["categories"]) >= 5
    assert data["registry"]["total"] == 40
    assert data["oos"]["months"][0] == "2016-01" and data["oos"]["months"][-1] == "2026-09"
    assert len(data["oos"]["months"]) == 129
    assert data["annual"]["partial_year"] == 2026
    assert data["literature"]["signals"], "literature signals table not parsed"
    assert data["headline_table"]["Momentum"]["NetReturn"] is not None
    lit = data["literature"]
    for s in lit["signals"]:
        for v in s.values():
            assert not _MD_TOKENS.search(v), v
    for sec in lit["sections"]:
        assert not _MD_TOKENS.search(sec["title"]), sec["title"]
        for item in sec["items"]:
            assert not _MD_TOKENS.search(item), item


def main():
    data = build_data()
    data_js = write_data_js(data)
    plotly = write_plotly()
    figs = copy_figures()
    docs = write_methodology_docs()
    self_check(data, data_js, plotly, figs, docs)
    print(f"wrote {data_js.relative_to(ROOT)}")
    print(f"wrote {plotly.relative_to(ROOT)} ({plotly.stat().st_size} bytes)")
    print(f"copied {len(figs)} QC figures -> {(ASSETS / 'figures').relative_to(ROOT)}")
    print(f"wrote {docs[0].relative_to(ROOT)}, {docs[1].relative_to(ROOT)}")
    print("build_site OK")


if __name__ == "__main__":
    main()
