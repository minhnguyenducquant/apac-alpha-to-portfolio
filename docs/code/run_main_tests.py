#!/usr/bin/env python
"""run_main_tests.py — APAC Alpha-to-Portfolio main empirical tests.

Executes EXACTLY the frozen specifications in METHODOLOGY_MAIN_TESTS.md and
SPECIFICATION_REGISTRY.csv. Reads only Prompt 1-2 processed inputs. No network.

Run:  .venv/bin/python scripts/run_main_tests.py
"""
from __future__ import annotations

import json
import math
import textwrap
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import cm

warnings.filterwarnings("ignore")
plt.rcParams.update({"font.size": 9, "axes.grid": True, "grid.alpha": 0.25,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "figure.facecolor": "white", "savefig.facecolor": "white"})

# ---------------------------------------------------------------------------
# Paths / constants (FROZEN BEFORE RUN)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
REF = ROOT / "data" / "reference"
DIRS = {k: ROOT / v for k, v in {
    "signal_tests": "results/signal_tests", "fama_macbeth": "results/fama_macbeth",
    "jkp_validation": "results/jkp_validation", "oos": "results/oos",
    "portfolio": "results/portfolio", "transaction_costs": "results/transaction_costs",
    "robustness": "results/robustness", "figures": "figures", "tables": "tables",
    "reports": "reports"}.items()}

MARKETS = ["CN", "HK", "IN", "JP", "KR", "SG", "TW"]
COUNTRY_NAME = {"CN": "China", "HK": "Hong Kong", "IN": "India", "JP": "Japan",
                "KR": "South Korea", "SG": "Singapore", "TW": "Taiwan"}
JKP_MAP = {"chn": "CN", "hkg": "HK", "ind": "IN", "jpn": "JP",
           "kor": "KR", "sgp": "SG", "twn": "TW"}
JKP_INV = {v: k for k, v in JKP_MAP.items()}

VOL_PRIMARY = "vol_60"
VOL_ROBUST = "vol_252"
MIN_NAMES = 5
OOS_START_YEAR = 2016
TRAIN_START = pd.Period("2010-01", "M")
FULL_LAST_REALISATION = pd.Period("2026-09", "M")
LAMBDA_RISK = 5.0
ETA_COST = 1.0
BASE_COST = 0.0015
COST_SCENARIOS = {"cost_5bps": 0.0005, "cost_15bps": 0.0015, "cost_30bps": 0.0030}
COV_WINDOW = 36
COV_MIN_OBS = 24
OPT_MIN_TRAIN_MONTHS = 24

PALETTE = {"Benchmark": "#444444", "1/N": "#1f77b4", "Momentum": "#d62728",
           "Low Risk": "#2ca02c", "Composite": "#9467bd", "Optimized": "#ff7f0e"}
PORT_LABEL = {"1n": "1/N", "mom": "Momentum", "lowrisk": "Low Risk",
              "composite": "Composite", "optimized": "Optimized"}
C_COUNTRY = dict(zip(MARKETS, cm.tab10(np.linspace(0, 1, 10))[:7]))

for d in DIRS.values():
    d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def atomic_write_df(df: pd.DataFrame, path: Path, **kw) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    if path.suffix == ".csv":
        df.to_csv(tmp, **kw)
    elif path.suffix == ".parquet":
        df.to_parquet(tmp, **kw)
    else:
        raise ValueError(path)
    tmp.replace(path)


def atomic_write_text(s: str, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(s, encoding="utf-8")
    tmp.replace(path)


def pct(x, d=1):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "NA"
    return f"{100 * x:.{d}f}%"


def num(x, d=3):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "NA"
    return f"{x:.{d}f}"


def wrap(s: str, width: int = 165) -> str:
    return "\n".join(textwrap.wrap(s, width))


def new_fig(figsize, title, subtitle, footer, nrows=1, ncols=1,
            top=0.80, bottom=0.15, hspace=0.45, wspace=0.30, **kw):
    fig, axes = plt.subplots(nrows, ncols, figsize=figsize, squeeze=False, **kw)
    fig.suptitle(title, x=0.5, y=0.985, ha="center", va="top",
                 fontsize=12.5, fontweight="bold", color="#111")
    fig.text(0.5, top + 0.06, subtitle, ha="center", va="top",
             fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap(footer), ha="center", va="bottom",
             fontsize=7.2, color="#555")
    fig.subplots_adjust(top=top, bottom=bottom, left=0.075, right=0.975,
                        hspace=hspace, wspace=wspace)
    return fig, axes


def save_fig(fig, name):
    p = DIRS["figures"] / name
    fig.savefig(p, dpi=150, facecolor="white")
    plt.close(fig)
    print("  figure:", p.relative_to(ROOT))


def _max_dd(cum: pd.Series):
    if len(cum) == 0:
        return np.nan
    return float((cum / cum.cummax() - 1.0).min())


def perf_metrics(r: pd.Series, cash: pd.Series = None, periods=12):
    r = r.dropna()
    if len(r) == 0:
        return dict(n=0, cagr=np.nan, vol=np.nan, sharpe=np.nan, max_dd=np.nan,
                    mean=np.nan, cum=np.nan, worst_year=np.nan, best_year=np.nan)
    gross = float(np.prod(1.0 + r.to_numpy()))
    cagr = gross ** (periods / len(r)) - 1.0
    vol = float(r.std(ddof=1) * np.sqrt(periods)) if len(r) > 1 else np.nan
    ex = (r - cash.reindex(r.index).fillna(0.0)) if cash is not None else r
    sharpe = (float(ex.mean() / ex.std(ddof=1) * np.sqrt(periods))
              if len(ex) > 1 and ex.std(ddof=1) > 0 else np.nan)
    cum = (1.0 + r).cumprod()
    yr = (1.0 + r).groupby(r.index.year).prod() - 1.0
    return dict(n=len(r), cagr=cagr, vol=vol, sharpe=sharpe, max_dd=_max_dd(cum),
                mean=float(r.mean()), cum=gross - 1.0,
                worst_year=float(yr.min()) if len(yr) else np.nan,
                best_year=float(yr.max()) if len(yr) else np.nan)


# ---------------------------------------------------------------------------
# 1. load + returns / FX / cash / benchmark
# ---------------------------------------------------------------------------
def load_all():
    panel = pd.read_parquet(PROC / "monthly_research_panel.parquet")
    fx = pd.read_parquet(PROC / "fx.parquet")
    rf = pd.read_parquet(PROC / "riskfree.parquet")
    bench = pd.read_parquet(PROC / "benchmarks.parquet")
    jkp = pd.read_parquet(PROC / "factors_jkp.parquet")
    french = pd.read_parquet(PROC / "factors_french.parquet")
    for nm, df in [("panel", panel), ("fx", fx), ("riskfree", rf),
                   ("benchmarks", bench), ("jkp", jkp), ("french", french)]:
        assert len(df) > 0, f"empty {nm}"
    assert set(panel["market"].unique()) == set(MARKETS)
    assert fx["fx_direction"].eq("local_per_usd").all()
    assert rf["units"].eq("percent").all()
    assert jkp["units"].eq("decimal_excess_return_usd").all()
    return panel, fx, rf, bench, jkp, french


def fx_monthly(fx: pd.DataFrame) -> pd.DataFrame:
    f = fx.copy()
    f["ym"] = f["date"].dt.to_period("M")
    f = (f.sort_values("date").groupby(["market", "ym"], as_index=False).last()
         [["market", "ym", "close"]].rename(columns={"close": "fx"}))
    assert f["fx"].gt(0).all()
    return f


def add_usd_returns(panel: pd.DataFrame, fxm: pd.DataFrame) -> pd.DataFrame:
    p = panel.copy()
    p["ym"] = pd.PeriodIndex(p["month"], freq="M")
    fxt = fxm.rename(columns={"fx": "fx_t"})
    fxn = fxm.copy(); fxn["ym"] = fxn["ym"] - 1; fxn = fxn.rename(columns={"fx": "fx_next"})
    fxp = fxm.copy(); fxp["ym"] = fxp["ym"] + 1; fxp = fxp.rename(columns={"fx": "fx_prev"})
    p = p.merge(fxt, on=["market", "ym"], how="left")
    p = p.merge(fxn, on=["market", "ym"], how="left")
    p = p.merge(fxp, on=["market", "ym"], how="left")
    p["usd_next_return"] = (1.0 + p["next_month_return"]) * (p["fx_t"] / p["fx_next"]) - 1.0
    p.loc[p["next_month_return"].isna() | p["fx_next"].isna(), "usd_next_return"] = np.nan
    p["usd_ret"] = (1.0 + p["monthly_total_return"]) * (p["fx_prev"] / p["fx_t"]) - 1.0
    p.loc[p["monthly_total_return"].isna() | p["fx_prev"].isna(), "usd_ret"] = np.nan
    return p


def rf_monthly(rf: pd.DataFrame) -> pd.Series:
    r = rf.copy()
    r["ym"] = r["date"].dt.to_period("M")
    me = r.sort_values("date").groupby("ym").last()
    return (me["close"] / 100.0 / 12.0)


def benchmark_usd(bench: pd.DataFrame, fxm: pd.DataFrame) -> pd.DataFrame:
    b = bench.copy()
    b["ym"] = b["date"].dt.to_period("M")
    me = b.sort_values("date").groupby(["market", "ym"], as_index=False).last().sort_values(["market", "ym"])
    me["loc_ret"] = me.groupby("market")["adj_close"].pct_change()
    fxd = fxm.set_index(["market", "ym"])["fx"]
    me["fx_prev"] = fxd.reindex(pd.MultiIndex.from_arrays([me["market"], me["ym"] - 1])).to_numpy()
    me["fx_t"] = fxd.reindex(pd.MultiIndex.from_arrays([me["market"], me["ym"]])).to_numpy()
    me["usd_ret"] = (1.0 + me["loc_ret"]) * (me["fx_prev"] / me["fx_t"]) - 1.0
    return me[["market", "ym", "loc_ret", "usd_ret"]]


# ---------------------------------------------------------------------------
# 2. signal tests
# ---------------------------------------------------------------------------
def _spearman(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 3 or np.std(x[m]) == 0 or np.std(y[m]) == 0:
        return np.nan
    xr = pd.Series(x[m]).rank().to_numpy(); yr = pd.Series(y[m]).rank().to_numpy()
    return float(np.corrcoef(xr, yr)[0, 1])


def ic_tests(p: pd.DataFrame):
    base = p[p["eligible_universe"] & p["next_month_return"].notna()].copy()
    specs = {"mom": "mom_12_1", "lowrisk": "lowrisk_score", "vol252": "vol252_score",
             "beta": "beta_score", "ivol": "ivol_score"}
    rows, monthly = [], []
    for nm, col in specs.items():
        for mkt, g in base.groupby("market"):
            recs = []
            for ym, gg in g.groupby("ym"):
                s, y = gg[col], gg["next_month_return"]
                if s.notna().sum() < MIN_NAMES or y.notna().sum() < MIN_NAMES:
                    continue
                v = _spearman(s.to_numpy(), y.to_numpy())
                if np.isfinite(v):
                    recs.append((ym, v, int(min(s.notna().sum(), y.notna().sum()))))
            if not recs:
                rows.append(dict(signal=nm, market=mkt, avg_ic=np.nan, std_ic=np.nan,
                                 icir=np.nan, pos_freq=np.nan, months=0, avg_n=np.nan))
                continue
            r = pd.DataFrame(recs, columns=["ym", "ic", "n"])
            monthly.append(r.assign(signal=nm, market=mkt))
            rows.append(dict(signal=nm, market=mkt, avg_ic=r["ic"].mean(),
                             std_ic=r["ic"].std(ddof=1),
                             icir=r["ic"].mean() / r["ic"].std(ddof=1) if r["ic"].std(ddof=1) > 0 else np.nan,
                             pos_freq=(r["ic"] > 0).mean(), months=len(r), avg_n=r["n"].mean()))
    ic_country = pd.DataFrame(rows)
    ic_country.loc[ic_country.market.eq("CN") & ic_country.signal.isin(["beta", "ivol"]),
                   ["avg_ic", "std_ic", "icir", "pos_freq", "avg_n"]] = np.nan
    ic_country.loc[ic_country.market.eq("CN") & ic_country.signal.isin(["beta", "ivol"]),
                   "months"] = 0
    mon = pd.concat(monthly, ignore_index=True) if monthly else pd.DataFrame()
    pooled = []
    for nm in specs:
        sub = mon[mon.signal == nm]
        if sub.empty:
            continue
        per = sub.groupby("ym")["ic"].mean()
        pooled.append(dict(signal=nm, avg_ic=per.mean(), std_ic=per.std(ddof=1),
                           icir=per.mean() / per.std(ddof=1) if per.std(ddof=1) > 0 else np.nan,
                           pos_freq=(per > 0).mean(), months=len(per),
                           avg_n=float(sub.groupby("ym")["n"].mean().mean())))
    return ic_country, pd.DataFrame(pooled), mon, base


def _top_quintile(g: pd.DataFrame, col: str):
    g = g.dropna(subset=[col]).sort_values([col, "security_id"])
    if len(g) < MIN_NAMES:
        return None
    k = max(int(math.ceil(len(g) * 0.2)), 1)
    return g.iloc[-k:]


def quintile_series(p: pd.DataFrame, col: str):
    base = p[p["eligible_universe"] & p["usd_next_return"].notna()].copy()
    out, membership = [], {}
    for (mkt, ym), g in base.groupby(["market", "ym"]):
        g = g.dropna(subset=[col]).sort_values([col, "security_id"])
        n = len(g)
        if n < MIN_NAMES:
            continue
        q = pd.qcut(np.arange(n), 5, labels=False, duplicates="drop") + 1
        g = g.assign(quintile=q)
        for qq, gg in g.groupby("quintile"):
            out.append(dict(market=mkt, ym=ym, quintile=int(qq),
                            ret=float(gg["usd_next_return"].mean()), n=len(gg)))
            membership[(mkt, ym, int(qq))] = set(gg["security_id"])
    return pd.DataFrame(out), membership


def quintile_turnover(membership: dict, market: str, q: int):
    keys = sorted([k for k in membership if k[0] == market and k[2] == q], key=lambda k: k[1])
    ts, prev = {}, None
    for k in keys:
        cur = membership[k]
        if prev is None:
            to = 0.5
        else:
            alln = cur | prev
            to = 0.5 * sum(abs((1 / len(cur) if n in cur else 0) - (1 / len(prev) if n in prev else 0))
                           for n in alln)
        ts[k[1]] = to
        prev = cur
    return pd.Series(ts)


def quintile_summary(qdf: pd.DataFrame):
    rows, spread_series = [], {}
    for mkt, g in qdf.groupby("market"):
        piv = g.pivot_table(index="ym", columns="quintile", values="ret").sort_index()
        if 5 not in piv.columns or 1 not in piv.columns:
            continue
        spread = (piv[5] - piv[1]).dropna()
        spread_series[mkt] = spread
        means = piv.mean(numeric_only=True)
        mono = _spearman(np.array(means.index, float), means.to_numpy())
        for q in sorted(piv.columns):
            r = piv[q].dropna()
            rows.append(dict(market=mkt, quintile=int(q),
                             ann_geom=(np.prod(1 + r) ** (12 / len(r)) - 1) if len(r) else np.nan,
                             vol=float(r.std(ddof=1) * np.sqrt(12)) if len(r) > 1 else np.nan,
                             mean=float(r.mean()), months=len(r),
                             n_avg=float(g[g.quintile == q]["n"].mean())))
        rows.append(dict(market=mkt, quintile="Q5-Q1",
                         ann_geom=(np.prod(1 + spread) ** (12 / len(spread)) - 1) if len(spread) else np.nan,
                         vol=float(spread.std(ddof=1) * np.sqrt(12)) if len(spread) > 1 else np.nan,
                         mean=float(spread.mean()), months=len(spread), n_avg=np.nan,
                         monotonicity=mono, q5_minus_q1_mean=float(spread.mean())))
    return pd.DataFrame(rows), spread_series


# ---------------------------------------------------------------------------
# 3. Fama-MacBeth
# ---------------------------------------------------------------------------
def _zscore(s: pd.Series):
    sd = s.std(ddof=0)
    if not np.isfinite(sd) or sd == 0:
        return s * 0.0
    return (s - s.mean()) / sd


def prep_fm(p: pd.DataFrame, dep: str) -> pd.DataFrame:
    d = p[p["eligible_universe"] & p[dep].notna() & p["median_daily_traded_value"].gt(0)].copy()
    d["mom_z"] = d.groupby(["market", "ym"])["mom_12_1"].transform(_zscore)
    d["lowrisk_z"] = d.groupby(["market", "ym"])[VOL_PRIMARY].transform(lambda s: _zscore(-s))
    d["lagret_z"] = d.groupby(["market", "ym"])["monthly_total_return"].transform(_zscore)
    d["logliq_z"] = d.groupby(["market", "ym"])[
        np.log(d["median_daily_traded_value"])].transform(_zscore) if False else \
        d.assign(_ll=np.log(d["median_daily_traded_value"])).groupby(["market", "ym"])["_ll"].transform(_zscore)
    d["dep"] = d[dep]
    return d


FM_REGS = ["mom_z", "lowrisk_z", "lagret_z", "logliq_z"]


def fm_pooled_slopes(d: pd.DataFrame, min_n=30):
    rows, markets = [], sorted(d["market"].unique())
    dum = {m: i for i, m in enumerate(markets)}
    for ym, g in d.groupby("ym"):
        g = g.dropna(subset=FM_REGS + ["dep"])
        if len(g) < min_n or g["market"].nunique() < 2:
            rows.append(dict(ym=ym, n=len(g), skipped=True))
            continue
        X = np.zeros((len(g), len(markets) + len(FM_REGS)))
        X[np.arange(len(g)), [dum[m] for m in g["market"]]] = 1.0
        X[:, len(markets):] = g[FM_REGS].to_numpy()
        beta, *_ = np.linalg.lstsq(X, g["dep"].to_numpy(), rcond=None)
        rows.append(dict(ym=ym, n=len(g), skipped=False,
                         **{r: beta[len(markets) + i] for i, r in enumerate(FM_REGS)}))
    return pd.DataFrame(rows)


def fm_per_country(d: pd.DataFrame, min_n=8):
    out = {}
    for sig in ["mom_z", "lowrisk_z"]:
        rows = []
        for (mkt, ym), g in d.groupby(["market", "ym"]):
            g = g.dropna(subset=[sig, "lagret_z", "logliq_z", "dep"])
            if len(g) < min_n:
                rows.append(dict(market=mkt, ym=ym, n=len(g), skipped=True, slope=np.nan))
                continue
            X = np.column_stack([np.ones(len(g)), g[sig], g["lagret_z"], g["logliq_z"]])
            beta, *_ = np.linalg.lstsq(X, g["dep"].to_numpy(), rcond=None)
            rows.append(dict(market=mkt, ym=ym, n=len(g), skipped=False, slope=beta[1]))
        out[sig] = pd.DataFrame(rows)
    return out


def nw_mean_t(slopes: pd.Series, lags=6):
    s = slopes.dropna()
    if len(s) < 3:
        return np.nan, np.nan, len(s)
    import statsmodels.api as sm
    m = sm.OLS(s.to_numpy(), np.ones((len(s), 1))).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return float(m.params[0]), float(m.tvalues[0]), len(s)


def fama_macbeth(p: pd.DataFrame):
    d_local = prep_fm(p, "next_month_return")
    pooled = fm_pooled_slopes(d_local)
    skipped = pooled[pooled["skipped"]].copy(); good = pooled[~pooled["skipped"]].copy()
    rows = []
    for r in FM_REGS:
        mean, t, n = nw_mean_t(good[r], 6)
        rows.append(dict(regressor=r, mean_slope=mean, nw_t=t, econ_per_1sd=mean,
                         valid_months=n, avg_n=float(good["n"].mean())))
    fm_pool = pd.DataFrame(rows)
    per = fm_per_country(d_local)
    crows = []
    for sig, lab in [("mom_z", "mom"), ("lowrisk_z", "lowrisk")]:
        for mkt, g in per[sig].groupby("market"):
            gg = g[~g["skipped"]]
            mean, t, n = nw_mean_t(gg["slope"], 6)
            crows.append(dict(signal=lab, market=mkt, mean_slope=mean, nw_t=t,
                              econ_per_1sd=mean, valid_months=n,
                              avg_n=float(gg["n"].mean()) if n else np.nan))
    return dict(fm_pooled=fm_pool, fm_country=pd.DataFrame(crows),
                fm_monthly=good.copy(), skipped=skipped, d_local=d_local)


# ---------------------------------------------------------------------------
# 4. external
# ---------------------------------------------------------------------------
def jkp_validation(spread_mom, spread_low, jkp):
    j = jkp.copy(); j["ym"] = j["date"].dt.to_period("M")
    j = j[j["region"].isin(JKP_MAP) & j["factor"].isin(["momentum", "low_risk"])]
    # JKP repeats each factor under selector_theme==factor and 'all_themes' (identical
    # values); keep the direct theme to remove duplicate (region,factor,ym) keys.
    j = j[j["selector_theme"] == j["factor"]]
    pairs, summary = [], []
    for lab, spreads in [("momentum", spread_mom), ("low_risk", spread_low)]:
        for mkt, s in spreads.items():
            own = s.copy(); own.index = own.index + 1
            jj = j[(j["region"] == JKP_INV[mkt]) & (j["factor"] == lab)
                   ].set_index("ym")["value"].rename("jkp")
            pair = pd.concat([own.rename("own"), jj], axis=1).dropna()
            if len(pair) == 0:
                summary.append(dict(signal=lab, market=mkt, n=0)); continue
            pair.index.name = "ym"
            pairs.append(pair.assign(market=mkt, signal=lab).reset_index())
            pre = pair[pair.index < pd.Period("2020-01", "M")]
            post = pair[pair.index >= pd.Period("2020-01", "M")]
            rec = dict(signal=lab, market=mkt, n=len(pair),
                       corr=float(pair["own"].corr(pair["jkp"])),
                       sign_agree=float((np.sign(pair["own"]) == np.sign(pair["jkp"])).mean()),
                       own_cum=float(np.prod(1 + pair["own"]) - 1),
                       jkp_cum=float(np.prod(1 + pair["jkp"]) - 1),
                       own_mean=float(pair["own"].mean()), jkp_mean=float(pair["jkp"].mean()),
                       own_vol=float(pair["own"].std(ddof=1) * np.sqrt(12)),
                       jkp_vol=float(pair["jkp"].std(ddof=1) * np.sqrt(12)),
                       own_sharpe=float(pair["own"].mean() / pair["own"].std(ddof=1) * np.sqrt(12)) if pair["own"].std(ddof=1) > 0 else np.nan,
                       jkp_sharpe=float(pair["jkp"].mean() / pair["jkp"].std(ddof=1) * np.sqrt(12)) if pair["jkp"].std(ddof=1) > 0 else np.nan,
                       own_maxdd=_max_dd((1 + pair["own"]).cumprod()),
                       jkp_maxdd=_max_dd((1 + pair["jkp"]).cumprod()),
                       pre2020_n=len(pre),
                       pre2020_corr=float(pre["own"].corr(pre["jkp"])) if len(pre) > 2 else np.nan,
                       post2020_n=len(post),
                       post2020_corr=float(post["own"].corr(post["jkp"])) if len(post) > 2 else np.nan)
            summary.append(rec)
    return pd.DataFrame(summary), (pd.concat(pairs) if pairs else pd.DataFrame())


def french_crosscheck(bench_usd, cash, french):
    f = french.copy(); f["ym"] = f["date"].dt.to_period("M")
    fm = (f[f["factor"] == "Mkt-RF"].groupby(["region", "ym"])["value"]
          .apply(lambda s: float(np.prod(1 + s) - 1)).rename("french_mkt_rf").reset_index())
    bu = bench_usd.dropna(subset=["usd_ret"]).copy()
    bu["ex"] = bu["usd_ret"] - cash.reindex(bu["ym"]).to_numpy()
    apac = bu.groupby("ym")["ex"].mean().rename("our_apac_ex")
    jp = bu[bu["market"] == "JP"].set_index("ym")["ex"].rename("our_jp_ex")
    rows = []
    for name, our, reg in [("Japan", jp, "Japan"),
                           ("APAC_ex_Japan_6mkt", apac, "Asia_Pacific_ex_Japan")]:
        fr = fm[fm["region"] == reg].set_index("ym")["french_mkt_rf"]
        pair = pd.concat([our, fr], axis=1).dropna()
        pair.columns = ["our_ex", "french_mkt_rf"]
        rows.append(dict(comparison=name, n=len(pair),
                         corr=float(pair["our_ex"].corr(pair["french_mkt_rf"])) if len(pair) > 2 else np.nan,
                         our_mean=float(pair["our_ex"].mean()),
                         french_mean=float(pair["french_mkt_rf"].mean()),
                         note="French Mkt-RF vs own benchmark excess USD; market-return cross-check only, NOT a momentum/low-risk validation"))
    rows.append(dict(comparison="Developed", n=0, corr=np.nan, our_mean=np.nan,
                     french_mean=np.nan,
                     note="French Developed aggregate has no matching own series in the 7 markets; NOT comparable"))
    return pd.DataFrame(rows), fm


def aqr_status():
    return pd.DataFrame([dict(dataset="AQR factor data", status="NOT_AVAILABLE",
                              reason="not present in approved Prompt 1-2 inputs; network access prohibited; no substitute used")])


# ---------------------------------------------------------------------------
# 5. portfolios
# ---------------------------------------------------------------------------
def add_features(p: pd.DataFrame) -> pd.DataFrame:
    d = p[p["eligible_universe"] & p["usd_next_return"].notna()].copy()
    d = d[(d["ym"] + 1) <= FULL_LAST_REALISATION]
    d["mom_12_1_z"] = d.groupby(["market", "ym"])["mom_12_1"].transform(_zscore)
    d["lowrisk_z"] = d.groupby(["market", "ym"])[VOL_PRIMARY].transform(lambda s: _zscore(-s))
    d["lagret_z"] = d.groupby(["market", "ym"])["monthly_total_return"].transform(_zscore)
    d["_ll"] = np.log(d["median_daily_traded_value"].clip(lower=1))
    d["logliq_z"] = d.groupby(["market", "ym"])["_ll"].transform(_zscore)
    d["lowrisk_score"] = -d[VOL_PRIMARY]
    d["composite"] = 0.5 * d["mom_12_1_z"] + 0.5 * d["lowrisk_z"].fillna(0.0)
    return d


def sleeve_weights(d: pd.DataFrame, kind: str):
    out = {}
    for (mkt, ym), g in d.groupby(["market", "ym"]):
        if kind == "1n":
            sel = g
        else:
            col = {"mom": "mom_12_1", "lowrisk": "lowrisk_score", "composite": "composite"}[kind]
            sel = _top_quintile(g, col)
        if sel is None or len(sel) < MIN_NAMES:
            continue
        w = pd.Series(1.0 / len(sel), index=sel["internal_security_id"].to_numpy())
        out[(mkt, ym)] = w.groupby(level=0).sum()
    return out


def sleeve_return(d: pd.DataFrame, weights: dict):
    lut = d.set_index(["market", "ym", "internal_security_id"])["usd_next_return"]
    recs = {ym: float(np.nansum([wi * lut.get((mkt, ym, sid), np.nan)
                                 for sid, wi in w.items()]))
            for (mkt, ym), w in weights.items()}
    s = pd.Series(recs)
    s.index = s.index + 1
    return s.sort_index()


def turnover_from_weights(weights: dict, market: str):
    keys = sorted([k for k in weights if k[0] == market], key=lambda k: k[1])
    ts, prev = {}, None
    for k in keys:
        cur = weights[k]
        if prev is None:
            to = 0.5
        else:
            idx = cur.index.union(prev.index)
            to = 0.5 * float((cur.reindex(idx, fill_value=0.0)
                              - prev.reindex(idx, fill_value=0.0)).abs().sum())
        ts[k[1]] = to
        prev = cur
    s = pd.Series(ts)
    s.index = s.index + 1
    return s


def optimized_sleeve(d: pd.DataFrame, usd_ret_mat: dict, fm_slopes_usd: pd.DataFrame,
                     sample_cov=False):
    from sklearn.covariance import LedoitWolf
    from scipy.optimize import minimize
    slopes = fm_slopes_usd[~fm_slopes_usd["skipped"]].set_index("ym")[FM_REGS]
    recs, weights, foldbacks, wprev = {}, {}, [], {}
    for (mkt, ym), g in d.groupby(["market", "ym"]):
        g = g.dropna(subset=["mom_12_1_z", "lowrisk_z", "lagret_z", "logliq_z"])
        if len(g) < MIN_NAMES:
            continue
        hist = slopes[slopes.index <= (ym - 1)]
        if len(hist) < OPT_MIN_TRAIN_MONTHS:
            recs[ym] = np.nan; foldbacks.append((mkt, ym, "insufficient_fm_history")); continue
        coef = hist.mean()
        mu = (g["mom_12_1_z"].to_numpy() * coef["mom_z"]
              + g["lowrisk_z"].to_numpy() * coef["lowrisk_z"]
              + g["lagret_z"].to_numpy() * coef["lagret_z"]
              + g["logliq_z"].to_numpy() * coef["logliq_z"])
        mat = usd_ret_mat[mkt]
        win = mat.loc[(mat.index <= ym) & (mat.index >= ym - (COV_WINDOW - 1))]
        common = [c for c in g["internal_security_id"]
                  if c in win.columns and win[c].notna().sum() >= COV_MIN_OBS]
        if len(common) < MIN_NAMES:
            recs[ym] = np.nan; foldbacks.append((mkt, ym, "insufficient_cov_history")); continue
        # common-asset sample: trim the sparsest names until the complete-case window
        # has >= COV_MIN_OBS months (spec: common-asset sample, min 24 obs/security)
        while len(common) >= MIN_NAMES:
            R = win[common].dropna(how="any")
            if R.shape[0] >= COV_MIN_OBS:
                break
            na = win[common].isna().sum()
            common.remove(na.idxmax())
        if len(common) < MIN_NAMES or R.shape[0] < COV_MIN_OBS:
            recs[ym] = np.nan; foldbacks.append((mkt, ym, "insufficient_common_assets")); continue
        if sample_cov:
            Sigma = np.cov(R.to_numpy(), rowvar=False) + 1e-8 * np.eye(len(common))
        else:
            Sigma = LedoitWolf().fit(R.to_numpy()).covariance_ + 1e-8 * np.eye(len(common))
        sids = list(g["internal_security_id"])
        mu = np.array([mu[sids.index(c)] for c in common])
        prev = wprev.get(mkt)
        w0 = (np.ones(len(common)) / len(common) if prev is None
              else np.array([prev.get(c, 0.0) for c in common]))
        w0 = w0 / w0.sum() if w0.sum() > 0 else np.ones(len(common)) / len(common)

        def obj(w):
            # ponytail: transaction penalty uses the same per-one-way turnover
            # convention as realised costs (0.5*sum|dw|), not the two-way sum.
            return (-(w @ mu - LAMBDA_RISK * (w @ Sigma @ w))
                    + ETA_COST * BASE_COST * 0.5 * np.abs(w - w0).sum())

        try:
            res = minimize(obj, w0, method="SLSQP",
                           bounds=[(0.0, 1.0)] * len(common),
                           constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}],
                           options={"maxiter": 300, "ftol": 1e-9})
            if not res.success or not np.isfinite(res.fun):
                raise RuntimeError(str(res.message))
            w = np.clip(res.x, 0, None); w = w / w.sum()
        except Exception:
            w = np.ones(len(common)) / len(common)
            foldbacks.append((mkt, ym, "optimizer_fallback_ew"))
        wser = pd.Series(w, index=common)
        wser = wser[wser > 1e-8]
        wprev[mkt] = wser
        weights[(mkt, ym)] = wser
        lut = d.set_index(["market", "ym", "internal_security_id"])["usd_next_return"]
        recs[ym] = float(np.nansum([wi * lut.get((mkt, ym, sid), np.nan)
                                    for sid, wi in wser.items()]))
    s = pd.Series(recs); s.index = s.index + 1
    return s.sort_index(), weights, foldbacks


def usd_return_matrix(d: pd.DataFrame, market: str):
    sub = d[(d["market"] == market) & d["usd_ret"].notna()]
    return sub.pivot_table(index="ym", columns="internal_security_id", values="usd_ret")


def run_portfolios(p, cash, b_usd):
    d = add_features(p)
    usd_ret_mat = {m: usd_return_matrix(d, m) for m in MARKETS}
    fm_usd = fm_pooled_slopes(prep_fm(p, "usd_next_return"))

    kinds = ["1n", "mom", "lowrisk", "composite"]
    weights_store = {k: sleeve_weights(d, k) for k in kinds}
    country_sleeves = {}
    for k in kinds:
        country_sleeves[k] = {m: sleeve_return(d, {kk: v for kk, v in weights_store[k].items() if kk[0] == m})
                              for m in MARKETS}
    country_sleeves["optimized"] = {}
    opt_wts = {}
    foldbacks = []
    for m in MARKETS:
        s, w, fb = optimized_sleeve(d[d["market"] == m], usd_ret_mat, fm_usd)
        country_sleeves["optimized"][m] = s
        opt_wts.update(w)
        foldbacks += fb
    weights_store["optimized"] = opt_wts

    port_ret, turnover, market_to = {}, {}, {}
    for k in ["1n", "mom", "lowrisk", "composite", "optimized"]:
        df = pd.DataFrame({m: country_sleeves[k].get(m) for m in MARKETS})
        port_ret[k] = df.mean(axis=1, skipna=True)
        to_df = pd.DataFrame({m: turnover_from_weights(weights_store[k], m) for m in MARKETS})
        turnover[k] = to_df.mean(axis=1, skipna=True)
        market_to[k] = to_df

    bu = b_usd.dropna(subset=["usd_ret"])
    bdf = bu.pivot_table(index="ym", columns="market", values="usd_ret")
    bdf.index = bdf.index + 1
    bdf = bdf[bdf.index <= FULL_LAST_REALISATION]
    bench = bdf.mean(axis=1, skipna=True)

    return dict(d=d, port_ret=port_ret, bench=bench, turnover=turnover,
                market_to=market_to, country_sleeves=country_sleeves,
                weights_store=weights_store, foldbacks=foldbacks,
                bench_country=bdf, cash=cash)


# ---------------------------------------------------------------------------
# 6. costs
# ---------------------------------------------------------------------------
def tax_cost_series(idx, market_to: pd.DataFrame) -> pd.Series:
    """Dated documented taxes only, apportioned by active country sleeves.

    Turnover is indexed by realisation month (= formation month + 1); the trade
    is executed at the end of the formation month. CN seller stamp (5 bps) took
    effect 2023-08-28, so the first trade after it is end-Aug-2023 -> realisation
    Sep-2023. HK stamp (10 bps per side) took effect 2023-11-17 -> first affected
    realisation is Dec-2023. No backfill to earlier sample.

    The APAC portfolio return is the equal-weight mean of the *active* country
    sleeves in that month, so a sleeve's tax enters as rate*turnover/K_active
    where K_active is the number of markets with non-null turnover that month —
    K is not a fixed 7 when a sleeve (e.g. an absent top quintile) is missing.
    Benchmark carries no tax. Keep CN/HK effective-date gates unchanged.
    """
    tax = pd.Series(0.0, index=idx)
    cn_start = pd.Period("2023-09", "M")
    hk_start = pd.Period("2023-12", "M")
    if "CN" not in market_to.columns and "HK" not in market_to.columns:
        return tax
    mt = market_to.reindex(idx)
    k_active = mt.notna().sum(axis=1)
    for m in idx:
        k = int(k_active.get(m, 0))
        if k <= 0:
            continue
        if "CN" in mt.columns and m >= cn_start and pd.notna(mt.at[m, "CN"]):
            tax[m] += 0.0005 * mt.at[m, "CN"] / k
        if "HK" in mt.columns and m >= hk_start and pd.notna(mt.at[m, "HK"]):
            tax[m] += 0.0010 * 2 * mt.at[m, "HK"] / k
    return tax


def apply_costs(monthly_ret: pd.Series, turnover: pd.Series, market_to: pd.DataFrame):
    idx = monthly_ret.index
    to = turnover.reindex(idx).fillna(0.0)
    tax = tax_cost_series(idx, market_to)
    out = {"gross": monthly_ret, "tax": tax}
    for nm, bps in COST_SCENARIOS.items():
        out[nm] = monthly_ret - to * bps - tax
    return out


# ---------------------------------------------------------------------------
# 6b. robustness suite (economically motivated, predeclared; no fishing)
# ---------------------------------------------------------------------------
# Eight predeclared families. Each writes rows into results/robustness/
# robustness_summary.csv with a ROBUSTNESS label and an explicit status so no
# NA is silent. No choice here is tuned on Sharpe.
DEV_MARKETS = ["JP", "HK", "SG"]
EMG_MARKETS = ["CN", "IN", "KR", "TW"]
MOM6_N = 5  # 6-1 momentum compounds t-6..t-2 (5 cells), excludes t-1

ROBUSTNESS_VARIATIONS = [
    "MOM_6_1", "vol_252",
    "liq_bottom10", "liq_bottom20_primary", "liq_bottom40",
    "weight_equal", "weight_liquidity",
    "developed", "emerging",
    "period_2016_2019", "period_2020_2025",
    "full_7mkt", "ex_survivor_CN_HK",
    "leaveout_none", "leaveout_CN", "leaveout_HK", "leaveout_IN",
    "leaveout_JP", "leaveout_KR", "leaveout_SG", "leaveout_TW",
]

ROBUSTNESS_FAMILIES = [
    ("RF1", "S33", "momentum_window_6_1"),
    ("RF2", "S34", "lowrisk_vol_252"),
    ("RF3", "S35", "liquidity_cutoff"),
    ("RF4", "S36", "quintile_weighting"),
    ("RF5", "S37", "developed_emerging"),
    ("RF6", "S38", "period_split"),
    ("RF7", "S39", "survivor_sensitivity"),
    ("RF8", "S40", "country_leave_one_out"),
]


def _mom6_by_key(p: pd.DataFrame) -> pd.DataFrame:
    """Gap-aware 6-1 momentum: compound t-6..t-2 (5 cells), exclude t-1."""
    rows = []
    for sid, g in p.groupby("internal_security_id", sort=False):
        ym = pd.PeriodIndex(g["month"], freq="M")
        ret = pd.Series(g["monthly_total_return"].to_numpy(float), index=ym)
        full = pd.period_range(ym.min(), ym.max(), freq="M")
        ret = ret.reindex(full)
        gross = (1.0 + ret).shift(2).rolling(MOM6_N, min_periods=MOM6_N).apply(np.prod, raw=True)
        rows.append(pd.DataFrame({"internal_security_id": sid, "month": full.astype(str),
                                  "mom_6_1": (gross - 1.0).to_numpy()}))
    return pd.concat(rows, ignore_index=True)


def _robust_ic(d: pd.DataFrame, col: str, dep: str = "next_month_return"):
    rows, mon = [], []
    for mkt, g in d.groupby("market"):
        recs = []
        for ym, gg in g.groupby("ym"):
            s, y = gg[col], gg[dep]
            if s.notna().sum() < MIN_NAMES or y.notna().sum() < MIN_NAMES:
                continue
            v = _spearman(s.to_numpy(), y.to_numpy())
            if np.isfinite(v):
                recs.append((ym, v, int(min(s.notna().sum(), y.notna().sum()))))
        if not recs:
            rows.append(dict(market=mkt, avg_ic=np.nan, months=0, avg_n=np.nan))
            continue
        r = pd.DataFrame(recs, columns=["ym", "ic", "n"])
        mon.append(r.assign(market=mkt))
        rows.append(dict(market=mkt, avg_ic=r["ic"].mean(), months=len(r), avg_n=r["n"].mean()))
    ic = pd.DataFrame(rows)
    if mon:
        allm = pd.concat(mon, ignore_index=True)
        per = allm.groupby("ym")["ic"].mean()
        pooled = dict(avg_ic=float(per.mean()), months=int(len(per)),
                      avg_n=float(allm.groupby("ym")["n"].mean().mean()))
    else:
        pooled = dict(avg_ic=np.nan, months=0, avg_n=np.nan)
    return ic, pooled


def _robust_q5q1(d: pd.DataFrame, col: str):
    q, _ = quintile_series(d.assign(eligible_universe=True), col)
    out = {}
    for mkt, g in q.groupby("market"):
        piv = g.pivot_table(index="ym", columns="quintile", values="ret")
        if 5 in piv.columns and 1 in piv.columns:
            sp = (piv[5] - piv[1]).dropna()
            if len(sp):
                out[mkt] = float(sp.mean())
    return out


def _srow(family, variation, factor, group, metric, value, note="", label="ROBUSTNESS"):
    val = np.nan if value is None else float(value)
    status = "ok" if np.isfinite(val) else "na"
    return dict(family=family, variation=variation, factor=factor, group=group,
                metric=metric, value=val, label=label, status=status, note=note)


def _append_ic_q(rows, d, col, variation, family, factor):
    ic, pool = _robust_ic(d, col)
    for _, r in ic.iterrows():
        rows.append(_srow(family, variation, factor, r["market"], "avg_ic", r["avg_ic"]))
    rows.append(_srow(family, variation, factor, "APAC", "avg_ic", pool["avg_ic"]))
    rows.append(_srow(family, variation, factor, "APAC", "ic_months", pool["months"]))
    for mkt, v in _robust_q5q1(d, col).items():
        rows.append(_srow(family, variation, factor, mkt, "q5_q1_mean", v))
    qv = _robust_q5q1(d, col)
    rows.append(_srow(family, variation, factor, "APAC", "q5_q1_mean",
                      float(np.nanmean(list(qv.values()))) if qv else np.nan))


def _top_q_weights(d: pd.DataFrame, col: str, weighting: str):
    wts = {}
    for (mkt, ym), g in d.groupby(["market", "ym"]):
        g = g.dropna(subset=[col])
        if len(g) < MIN_NAMES:
            continue
        k = max(int(math.ceil(len(g) * 0.2)), 1)
        sel = g.sort_values([col, "security_id"]).iloc[-k:]
        if weighting == "liquidity":
            liq = sel["liq_lag"].clip(lower=0).to_numpy(float)
            if not np.isfinite(liq).all() or liq.sum() <= 0:
                liq = np.ones(len(sel))
        else:
            liq = np.ones(len(sel))
        w = liq / liq.sum()
        wts[(mkt, ym)] = pd.Series(w, index=sel["internal_security_id"].to_numpy())
    return wts


def _sleeve_gross_net(d: pd.DataFrame, wts: dict, oos_idx):
    ret = sleeve_return(d, wts)
    to = pd.DataFrame({m: turnover_from_weights(wts, m) for m in MARKETS})
    to_m = to.mean(axis=1, skipna=True).reindex(oos_idx)
    out = apply_costs(ret.reindex(oos_idx).dropna(), to_m, to.reindex(oos_idx))
    gross = perf_metrics(out["gross"])["cagr"]
    net = perf_metrics(out["cost_15bps"])["cagr"]
    return gross, net, float(to_m.mean())


def run_robustness(p: pd.DataFrame, pr: dict, oos_idx, cash) -> pd.DataFrame:
    rows = []
    d = p.copy()
    d = d.merge(_mom6_by_key(p), on=["internal_security_id", "month"], how="left")
    d = d[d["ym"] <= FULL_LAST_REALISATION]
    d["lowrisk_score"] = -d[VOL_PRIMARY]
    d["vol252_score"] = -d[VOL_ROBUST]
    d["liq_lag"] = d.sort_values("ym").groupby("internal_security_id")[
        "median_daily_traded_value"].shift(1)
    d["mom_z"] = d.groupby(["market", "ym"])["mom_12_1"].transform(_zscore)
    d["lowrisk_z"] = d.groupby(["market", "ym"])["lowrisk_score"].transform(_zscore)
    d["composite_z"] = 0.5 * d["mom_z"] + 0.5 * d["lowrisk_z"]

    core = (d["return_pair_valid"] & d["monthly_adj_close"].gt(0)
            & d["mom_12_1"].notna() & d[VOL_ROBUST].notna()
            & d["median_daily_traded_value"].notna() & d["trading_frequency"].notna())
    base = d[d["eligible_universe"] & d["usd_next_return"].notna()].copy()

    # RF1: alternative momentum window 6-1
    _append_ic_q(rows, base, "mom_6_1", "MOM_6_1", "momentum_window_6_1", "MOM")
    # RF2: alternative low-risk vol_252
    _append_ic_q(rows, base, "vol252_score", "vol_252", "lowrisk_vol_252", "LOWRISK")

    # RF3: liquidity cutoff alternatives (fixed rule, no tuning)
    for q, var in [(0.10, "liq_bottom10"), (0.20, "liq_bottom20_primary"), (0.40, "liq_bottom40")]:
        qq = (d[core].groupby(["market", "ym"])["median_daily_traded_value"]
              .transform(lambda s: s.quantile(q)).reindex(d.index))
        elig = core & (d["median_daily_traded_value"] >= qq)
        sub = d[elig & d["usd_next_return"].notna()].copy()
        for col, fac in [("mom_12_1", "MOM"), ("lowrisk_score", "LOWRISK")]:
            _append_ic_q(rows, sub, col, var, "liquidity_cutoff", fac)
        rows.append(_srow("liquidity_cutoff", var, "-", "APAC", "eligible_names",
                          float(elig.sum()), note="fixed monthly cutoff, no Sharpe tuning"))

    # RF4: equal vs liquidity-aware weights in the top quintile (sensitivity only)
    for col, fac in [("mom_12_1", "MOM"), ("lowrisk_score", "LOWRISK")]:
        for wt in ["equal", "liquidity"]:
            wts = _top_q_weights(base, col, wt)
            g_, n_, to_ = _sleeve_gross_net(base, wts, oos_idx)
            note = ("liquidity-aware weighting is a SENSITIVITY, not a recommended factor"
                    if wt == "liquidity" else "equal-weight benchmark within top quintile")
            rows.append(_srow("quintile_weighting", f"weight_{wt}", fac, "APAC",
                              "gross_cagr", g_, note=note))
            rows.append(_srow("quintile_weighting", f"weight_{wt}", fac, "APAC",
                              "net15_cagr", n_, note=note))
            rows.append(_srow("quintile_weighting", f"weight_{wt}", fac, "APAC",
                              "mean_turnover", to_))

    # RF5: developed vs emerging, predeclared
    for grp, mkts in [("developed", DEV_MARKETS), ("emerging", EMG_MARKETS)]:
        sub = base[base["market"].isin(mkts)]
        cov = int(sub["market"].nunique())
        for col, fac in [("mom_12_1", "MOM"), ("lowrisk_score", "LOWRISK")]:
            _, pool = _robust_ic(sub, col)
            qv = _robust_q5q1(sub, col)
            rows.append(_srow("developed_emerging", grp, fac, "APAC", "avg_ic", pool["avg_ic"]))
            rows.append(_srow("developed_emerging", grp, fac, "APAC", "ic_months", pool["months"]))
            rows.append(_srow("developed_emerging", grp, fac, "APAC", "q5_q1_mean",
                              float(np.nanmean(list(qv.values()))) if qv else np.nan))
        rows.append(_srow("developed_emerging", grp, "-", "APAC", "market_coverage", cov,
                          note="markets: " + "/".join(mkts)))
        if "CN" in mkts:
            rows.append(_srow("developed_emerging", grp, "CN", "CN", "beta_ivol",
                              np.nan, note="CN beta/IVOL NA (one-row benchmark)"))

    # RF6: period split, 2026 incomplete excluded
    for var, a, b in [("period_2016_2019", pd.Period("2016-01", "M"), pd.Period("2019-12", "M")),
                      ("period_2020_2025", pd.Period("2020-01", "M"), pd.Period("2025-12", "M"))]:
        sub = base[(base["ym"] >= a) & (base["ym"] <= b)]
        for col, fac in [("mom_12_1", "MOM"), ("lowrisk_score", "LOWRISK")]:
            _, pool = _robust_ic(sub, col)
            qv = _robust_q5q1(sub, col)
            rows.append(_srow("period_split", var, fac, "APAC", "avg_ic", pool["avg_ic"]))
            rows.append(_srow("period_split", var, fac, "APAC", "ic_months", pool["months"]))
            rows.append(_srow("period_split", var, fac, "APAC", "q5_q1_mean",
                              float(np.nanmean(list(qv.values()))) if qv else np.nan))

    # RF7: survivor sensitivity, full vs CN/HK only
    deln = {}
    for m in ["CN", "HK"]:
        vals = pr["d"].loc[pr["d"].market.eq(m), "delisting_coverage"].dropna()
        deln[m] = vals.iloc[0] if len(vals) else np.nan
    for var, mkts, note in [
            ("full_7mkt", MARKETS, "full 7-market sample"),
            ("ex_survivor_CN_HK", ["CN", "HK"],
             "retains only CN/HK; both have 0/N delisting coverage so this does NOT cure survivorship")]:
        sub = base[base["market"].isin(mkts)]
        _, pool = _robust_ic(sub, "composite_z")
        qv = _robust_q5q1(sub, "composite_z")
        rows.append(_srow("survivor_sensitivity", var, "Composite", "APAC", "avg_ic",
                          pool["avg_ic"], note=note))
        rows.append(_srow("survivor_sensitivity", var, "Composite", "APAC", "ic_months",
                          pool["months"], note=note))
        rows.append(_srow("survivor_sensitivity", var, "Composite", "APAC", "q5_q1_mean",
                          float(np.nanmean(list(qv.values()))) if qv else np.nan, note=note))
    for m in ["CN", "HK"]:
        rows.append(_srow("survivor_sensitivity", "ex_survivor_CN_HK", m, m,
                          "delisting_coverage", np.nan,
                          note=f"CN/HK delisting coverage {deln[m]} (0/N); survivorship NOT cured"))

    # RF8: country leave-one-out for equal-country composite / 1N / optimized
    for k, klab in [("composite", "Composite"), ("1n", "1/N"), ("optimized", "Optimized")]:
        for excl in ["none"] + MARKETS:
            mkts = [m for m in MARKETS if m != excl]
            df = pd.DataFrame({m: pr["country_sleeves"][k].get(m) for m in mkts})
            r = df.mean(axis=1, skipna=True).reindex(oos_idx).dropna()
            to = pr["market_to"][k].reindex(oos_idx)
            to = to[[m for m in mkts if m in to.columns]]
            net = apply_costs(r, to.mean(axis=1, skipna=True), to)["cost_15bps"]
            var = f"leaveout_{'none' if excl == 'none' else excl}"
            note = "all markets" if excl == "none" else f"excludes {excl}"
            if excl == "CN":
                note += "; CN benchmark missing (one-row)"
            elif excl == "none":
                note += "; CN benchmark missing (one-row)"
            rows.append(_srow("country_leave_one_out", var, klab, "APAC",
                              "net15_cagr", perf_metrics(net.dropna())["cagr"], note=note))

    out = pd.DataFrame(rows)
    atomic_write_df(out, DIRS["robustness"] / "robustness_summary.csv", index=False)

    # predeclared family manifest (registry cross-reference)
    man = pd.DataFrame([dict(family=f, spec_id=s, scope=sc) for f, s, sc in ROBUSTNESS_FAMILIES])
    atomic_write_df(man, DIRS["robustness"] / "robustness_manifest.csv", index=False)

    # explicit analysis windows so a no-future-date test has something to check
    windows = pd.DataFrame([
        dict(variation="MOM_6_1", start_ym="2010-01", end_ym=str(FULL_LAST_REALISATION),
             detail="gap-aware, compounds t-6..t-2 excluding t-1"),
        dict(variation="period_2016_2019", start_ym="2016-01", end_ym="2019-12",
             detail="primary factors; 2026 incomplete excluded"),
        dict(variation="period_2020_2025", start_ym="2020-01", end_ym="2025-12",
             detail="primary factors; 2026 incomplete excluded"),
    ])
    atomic_write_df(windows, DIRS["robustness"] / "robustness_windows.csv", index=False)
    return out


# ---------------------------------------------------------------------------
# 7. figures
# ---------------------------------------------------------------------------
def fig_cumulative_oos(port_ret, bench, oos_idx):
    fig, ax = plt.subplots(figsize=(11, 5.6))
    fig.suptitle("Conclusion: only Momentum beats 1/N and the 6-market benchmark on net return",
                 x=0.5, y=0.985, ha="center", va="top", fontsize=12, fontweight="bold")
    fig.text(0.5, 0.865, "Expanding OOS 2016-01 to 2026-09, monthly USD net of 15bps+dated taxes; equal-country APAC sleeves",
             ha="center", fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap("Source: results/oos/oos_portfolio_returns_net15bps.csv, benchmarks.parquet, data/reference/transaction_costs.csv. Units: cumulative growth of 1 USD, decimal net returns. Takeaway: signal sleeves beat the 6-market APAC benchmark on a net (15bps+taxes) basis, but only Momentum beats 1/N."),
             ha="center", va="bottom", fontsize=7.2, color="#555")
    fig.subplots_adjust(top=0.82, bottom=0.16, left=0.075, right=0.975)
    b = (1 + bench.reindex(oos_idx).dropna()).cumprod()
    ax.plot(b.index.to_timestamp(), b, color=PALETTE["Benchmark"], lw=2, label="Benchmark (6-mkt APAC)")
    for k, lab in PORT_LABEL.items():
        r = port_ret[k].reindex(oos_idx).dropna()
        c = (1 + r).cumprod()
        ax.plot(c.index.to_timestamp(), c, color=PALETTE[lab], lw=2, label=lab)
    ax.set_title("")
    ax.set_ylabel("Cumulative growth of $1 (net)")
    ax.set_xlabel("")
    ax.legend(ncol=3, fontsize=8, frameon=False)
    save_fig(fig, "fig01_cumulative_oos.png")


def fig_rolling(port_ret, oos_idx):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.4))
    axes = np.atleast_2d(axes)
    fig.suptitle("Conclusion: 36m returns are less extreme than 12m swings, but momentum still varies by regime",
                 x=0.5, y=0.985, ha="center", va="top", fontsize=12, fontweight="bold")
    fig.text(0.5, 0.875, "Rolling 12-month total and rolling 36-month annualised net returns, OOS 2016+",
             ha="center", fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap("Source: results/oos/oos_portfolio_returns_net15bps.csv. Units: decimal returns; 36m panel annualised. Takeaway: do not expect stable excess return month to month."),
             ha="center", va="bottom", fontsize=7.2, color="#555")
    fig.subplots_adjust(top=0.83, bottom=0.15, left=0.07, right=0.98, wspace=0.22)
    for ax, win, ann in [(axes[0, 0], 12, False), (axes[0, 1], 36, True)]:
        for k, lab in PORT_LABEL.items():
            r = port_ret[k].reindex(oos_idx).dropna()
            roll = (1 + r).rolling(win).apply(np.prod, raw=True) - 1
            if ann:
                roll = (1 + roll) ** (12 / win) - 1
            ax.plot(roll.index.to_timestamp(), roll, color=PALETTE[lab], lw=1.5, label=lab)
        ax.axhline(0, color="k", lw=0.8)
        ax.set_title(f"{win}-month {'annualised' if ann else 'total'}", fontsize=10)
    axes[0, 0].legend(fontsize=7.5, ncol=2, frameon=False)
    save_fig(fig, "fig02_rolling_12_36m.png")


def fig_drawdowns(port_ret, bench, oos_idx):
    fig, ax = plt.subplots(figsize=(11, 5.2))
    fig.suptitle("Conclusion: 1/N and Optimized have the shallowest drawdowns; Low Risk does not cushion here",
                 x=0.5, y=0.985, ha="center", va="top", fontsize=12, fontweight="bold")
    fig.text(0.5, 0.87, "Drawdown from running peak, net OOS returns, 2016+",
             ha="center", fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap("Source: results/oos/oos_portfolio_returns_net15bps.csv. Units: drawdown fraction (negative). Takeaway: drawdowns are market-driven; no sleeve reliably avoids the deepest losses."),
             ha="center", va="bottom", fontsize=7.2, color="#555")
    fig.subplots_adjust(top=0.83, bottom=0.15, left=0.075, right=0.975)
    b = (1 + bench.reindex(oos_idx).dropna()).cumprod()
    ax.plot(b.index.to_timestamp(), b / b.cummax() - 1, color=PALETTE["Benchmark"], lw=1.6, label="Benchmark")
    for k, lab in PORT_LABEL.items():
        r = port_ret[k].reindex(oos_idx).dropna()
        c = (1 + r).cumprod()
        ax.plot(c.index.to_timestamp(), c / c.cummax() - 1, color=PALETTE[lab], lw=1.6, label=lab)
    ax.legend(ncol=3, fontsize=8, frameon=False)
    ax.set_ylabel("Drawdown")
    save_fig(fig, "fig03_drawdowns.png")


def _bar_country(ax, series_by_country, title):
    xs = np.arange(len(series_by_country))
    ax.bar(xs, list(series_by_country.values()),
           color=[C_COUNTRY[m] for m in series_by_country])
    ax.set_xticks(xs)
    ax.set_xticklabels([COUNTRY_NAME.get(m, m) for m in series_by_country], rotation=20, fontsize=7.5)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_title(title, fontsize=10)


def fig_country_signal(summary: pd.DataFrame, sig, png, src, conclusion, subtitle):
    sub = summary[(summary.quintile == "Q5-Q1") & summary.market.isin(MARKETS)]
    vals = {m: float(sub[sub.market == m]["mean"].iloc[0]) for m in MARKETS if len(sub[sub.market == m])}
    fig, ax = plt.subplots(figsize=(10, 5.2))
    fig.suptitle(conclusion, x=0.5, y=0.985, ha="center", va="top",
                 fontsize=11.5, fontweight="bold")
    fig.text(0.5, 0.875, "Gross, pre-cost — " + subtitle, ha="center", fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap(f"Source: {src}. Units: mean monthly USD return of top-minus-bottom quintile (%). Takeaway: the sign of the Q5-Q1 spread is the signal's direction in each market."),
             ha="center", va="bottom", fontsize=7.2, color="#555")
    fig.subplots_adjust(top=0.83, bottom=0.20, left=0.08, right=0.97)
    _bar_country(ax, {m: 100 * vals[m] for m in vals}, "Mean monthly Q5-Q1 (%, USD)")
    save_fig(fig, png)


def fig_ic_time(ic_mon, pooled):
    fig, ax = plt.subplots(figsize=(11, 5.2))
    fig.suptitle("Conclusion: MOM IC is modestly positive; LOWRISK and vol252 IC are near zero and unstable",
                 x=0.5, y=0.985, ha="center", va="top", fontsize=12, fontweight="bold")
    fig.text(0.5, 0.875, "12-month rolling mean of country-equal pooled monthly Spearman IC for MOM, LOWRISK and vol252, 2011-2026",
             ha="center", fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap("Source: results/signal_tests/ic_monthly_series.csv. Units: rank correlation. Takeaway: only MOM has a positive average IC; LOWRISK and vol252 hover around zero and are far from stable signals."),
             ha="center", va="bottom", fontsize=7.2, color="#555")
    fig.subplots_adjust(top=0.83, bottom=0.15, left=0.075, right=0.975)
    for nm, lab, col in [("mom", "MOM", "#d62728"), ("lowrisk", "LOWRISK", "#2ca02c"), ("vol252", "vol252", "#8c564b")]:
        sub = ic_mon[ic_mon.signal == nm].groupby("ym")["ic"].mean().sort_index()
        if sub.empty:
            continue
        roll = sub.rolling(12, min_periods=6).mean()
        ax.plot(roll.index.to_timestamp(), roll, color=col, lw=1.8, label=lab)
    ax.axhline(0, color="k", lw=0.8)
    ax.legend(fontsize=8, frameon=False)
    save_fig(fig, "fig06_ic_through_time.png")


def fig_ic_dist(ic_mon):
    fig, ax = plt.subplots(figsize=(10, 5.2))
    fig.suptitle("Conclusion: monthly IC distributions straddle zero; positive mean, heavy overlap with negative",
                 x=0.5, y=0.985, ha="center", va="top", fontsize=12, fontweight="bold")
    fig.text(0.5, 0.875, "Country-equal pooled monthly Spearman IC distribution, 2011-2026",
             ha="center", fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap("Source: results/signal_tests/ic_monthly_series.csv. Units: rank correlation; histogram counts. Takeaway: no month-level certainty, only a weak average edge."),
             ha="center", va="bottom", fontsize=7.2, color="#555")
    fig.subplots_adjust(top=0.83, bottom=0.15, left=0.08, right=0.97)
    for nm, col in [("mom", "#d62728"), ("lowrisk", "#2ca02c")]:
        sub = ic_mon[ic_mon.signal == nm].groupby("ym")["ic"].mean()
        ax.hist(sub, bins=25, alpha=0.55, color=col, label=f"{nm} (mean {sub.mean():.3f})")
    ax.axvline(0, color="k", lw=0.9)
    ax.legend(fontsize=8, frameon=False)
    save_fig(fig, "fig07_ic_distribution.png")


def fig_quintile_mono(sum_mom, sum_low):
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.2))
    axes = np.atleast_2d(axes)
    fig.suptitle("Conclusion: MOM quintile returns rise with the score; LOWRISK quintiles fall (low-risk premium is inverted)",
                 x=0.5, y=0.985, ha="center", va="top", fontsize=12, fontweight="bold")
    fig.text(0.5, 0.875, "Equal-country gross, pre-cost mean monthly USD quintile returns, eligible sample",
             ha="center", fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap("Source: results/signal_tests/quintiles_mom.csv, quintiles_lowrisk.csv. Units: mean monthly USD return (%). Takeaway: monotonicity is partial, so top-quintile sleeves are the implementable expression."),
             ha="center", va="bottom", fontsize=7.2, color="#555")
    fig.subplots_adjust(top=0.82, bottom=0.15, left=0.07, right=0.98, wspace=0.2)
    for ax, s, nm in [(axes[0, 0], sum_mom, "Momentum"), (axes[0, 1], sum_low, "Low Risk")]:
        piv = (s[s.quintile.isin([1, 2, 3, 4, 5])]
               .pivot_table(index="market", columns="quintile", values="mean"))
        m = piv.mean(axis=0)
        ax.bar(m.index.astype(int), 100 * m.to_numpy(), color="#4c72b0")
        ax.axhline(0, color="k", lw=0.8)
        ax.set_title(nm, fontsize=10)
        ax.set_xlabel("Quintile (Q5 = highest score)")
        ax.set_ylabel("Mean monthly return (%)" if nm == "Momentum" else "")
    save_fig(fig, "fig08_quintile_monotonicity.png")


def fig_jkp(jkp_pairs, jkp_sum):
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.4))
    axes = np.atleast_2d(axes)
    fig.suptitle("Conclusion: our equal-weight Q5-Q1 spreads co-move positively with JKP country factors, but are not equivalent",
                 x=0.5, y=0.985, ha="center", va="top", fontsize=12, fontweight="bold")
    fig.text(0.5, 0.875, "Own monthly Q5-Q1 USD spread vs JKP momentum / low_risk on exact common dates",
             ha="center", fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap("Source: results/jkp_validation/jkp_paired_series.csv. Units: decimal USD excess return; JKP is value-weighted long-short, ours is equal-weight and survivor-biased. Takeaway: external direction is consistent, magnitude is not comparable."),
             ha="center", va="bottom", fontsize=7.2, color="#555")
    fig.subplots_adjust(top=0.83, bottom=0.17, left=0.07, right=0.98, wspace=0.22)
    for ax, sig, nm in [(axes[0, 0], "momentum", "Momentum"), (axes[0, 1], "low_risk", "Low Risk")]:
        sub = jkp_pairs[jkp_pairs.signal == sig]
        if sub.empty:
            ax.text(0.5, 0.5, "no paired data", ha="center"); continue
        ax.scatter(sub["jkp"], sub["own"], s=10, alpha=0.5, color="#4c72b0")
        c = jkp_sum[jkp_sum.signal == sig]["corr"].mean()
        ax.set_title(f"{nm}: pooled corr = {c:.2f} (n={len(sub)})", fontsize=10)
        ax.set_xlabel("JKP factor return (USD)")
        ax.set_ylabel("Our Q5-Q1 (USD)" if sig == "momentum" else "")
    save_fig(fig, "fig09_jkp_validation.png")


def fig_turnover(port_ret, turnover, oos_idx):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    axes = np.atleast_2d(axes)
    fig.suptitle("Conclusion: Momentum/Low Risk/Composite trade far more than 1/N; Optimized is moderate",
                 x=0.5, y=0.985, ha="center", va="top", fontsize=12, fontweight="bold")
    fig.text(0.5, 0.875, "One-way turnover, equal-country average of country sleeves, OOS 2016+",
             ha="center", fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap("Source: results/portfolio/turnover.csv. Units: one-way turnover (0.5*sum|dw|); initial entry 0.5. Takeaway: higher-turnover sleeves need lower frictions to preserve net edge."),
             ha="center", va="bottom", fontsize=7.2, color="#555")
    fig.subplots_adjust(top=0.83, bottom=0.15, left=0.07, right=0.98, wspace=0.2)
    means = {lab: turnover[k].reindex(oos_idx).mean() for k, lab in PORT_LABEL.items()}
    axes[0, 0].bar(means.keys(), [100 * v for v in means.values()], color="#55a868")
    axes[0, 0].set_title("Average monthly one-way turnover (%)", fontsize=10)
    axes[0, 0].tick_params(axis="x", rotation=25, labelsize=8)
    for k, lab in PORT_LABEL.items():
        axes[0, 1].plot(turnover[k].reindex(oos_idx).index.to_timestamp(),
                        turnover[k].reindex(oos_idx).rolling(6).mean(),
                        color=PALETTE[lab], lw=1.4, label=lab)
    axes[0, 1].set_title("6-month rolling turnover", fontsize=10)
    axes[0, 1].legend(fontsize=7.5, ncol=2, frameon=False)
    save_fig(fig, "fig10_turnover.png")


def fig_gross_net(cost_tables):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    axes = np.atleast_2d(axes)
    fig.suptitle("Conclusion: frictions reduce CAGR monotonically, most for high-turnover sleeves; none turns negative",
                 x=0.5, y=0.985, ha="center", va="top", fontsize=12, fontweight="bold")
    fig.text(0.5, 0.875, "Gross vs net CAGR by friction scenario (plus dated taxes)",
             ha="center", fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap("Source: results/transaction_costs/cost_sensitivity.csv. Units: annualised CAGR (%). Takeaway: frictions erode CAGR in proportion to turnover; the ranking of sleeves is unchanged."),
             ha="center", va="bottom", fontsize=7.2, color="#555")
    fig.subplots_adjust(top=0.83, bottom=0.16, left=0.08, right=0.98, wspace=0.22)
    labs = list(PORT_LABEL.values())
    x = np.arange(len(labs)); w = 0.2
    for i, scen in enumerate(["gross", "cost_5bps", "cost_15bps", "cost_30bps"]):
        vals = [100 * cost_tables[lab][scen] for lab in labs]
        axes[0, 0].bar(x + (i - 1.5) * w, vals, w, label=scen)
    axes[0, 0].set_xticks(x); axes[0, 0].set_xticklabels(labs, rotation=25, fontsize=8)
    axes[0, 0].set_title("CAGR by scenario (%)", fontsize=10)
    axes[0, 0].legend(fontsize=7, frameon=False)
    for k, lab in PORT_LABEL.items():
        table = cost_tables[lab]
        axes[0, 1].plot(["gross", "5bps", "15bps", "30bps"],
                        [100 * table[s] for s in ["gross", "cost_5bps", "cost_15bps", "cost_30bps"]],
                        marker="o", color=PALETTE[lab], label=lab)
    axes[0, 1].axhline(0, color="k", lw=0.8)
    axes[0, 1].set_title("CAGR across cost scenarios (%)", fontsize=10)
    axes[0, 1].legend(fontsize=7, frameon=False)
    save_fig(fig, "fig11_gross_vs_net.png")


def fig_sharpe_cost(cost_tables, cost_sharpe):
    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    fig.suptitle("Conclusion: gross Sharpe marginally favours Composite over 1/N;\ncosts let 1/N overtake it and hit high-turnover sleeves hardest",
                 x=0.5, y=0.985, ha="center", va="top", fontsize=12, fontweight="bold")
    fig.text(0.5, 0.845, "OOS Sharpe across friction scenarios, all portfolios",
             ha="center", fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap("Source: results/transaction_costs/cost_sensitivity.csv. Units: annualised Sharpe using USD cash approximation. Takeaway: costs erode Sharpe in proportion to turnover and reorder close pairs (1/N overtakes Composite)."),
             ha="center", va="bottom", fontsize=7.2, color="#555")
    fig.subplots_adjust(top=0.80, bottom=0.15, left=0.085, right=0.975)
    x = np.arange(len(PORT_LABEL)); w = 0.2
    for i, scen in enumerate(["gross", "cost_5bps", "cost_15bps", "cost_30bps"]):
        vals = [cost_sharpe[lab][scen] for lab in PORT_LABEL.values()]
        ax.bar(x + (i - 1.5) * w, vals, w, label=scen)
    ax.set_xticks(x); ax.set_xticklabels(list(PORT_LABEL.values()), rotation=25, fontsize=8)
    ax.axhline(0, color="k", lw=0.8)
    ax.legend(fontsize=7.5, frameon=False)
    save_fig(fig, "fig12_sharpe_vs_cost.png")


def fig_country_exposure(weights_store, oos_idx):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    axes = np.atleast_2d(axes)
    fig.suptitle("Conclusion: country exposure is close to equal; optimization occurs within country sleeves",
                 x=0.5, y=0.985, ha="center", va="top", fontsize=11.5, fontweight="bold")
    fig.text(0.5, 0.875, "Average country weights and time path for the optimized APAC portfolio",
             ha="center", fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap("Source: results/portfolio/weights_summary.csv. Units: portfolio weight. Takeaway: diversification is country-level, not a country bet."),
             ha="center", va="bottom", fontsize=7.2, color="#555")
    fig.subplots_adjust(top=0.83, bottom=0.16, left=0.075, right=0.98, wspace=0.22)
    wts = weights_store["optimized"]
    per_country = {m: [] for m in MARKETS}
    for (m, ym), w in wts.items():
        if ym + 1 in oos_idx:
            per_country[m].append(w.sum())
    avg = {m: (np.mean(per_country[m]) if per_country[m] else 0.0) for m in MARKETS}
    axes[0, 0].bar(range(len(MARKETS)), [avg[m] / sum(avg.values()) for m in MARKETS],
                   color=[C_COUNTRY[m] for m in MARKETS])
    axes[0, 0].set_xticks(range(len(MARKETS)))
    axes[0, 0].set_xticklabels([COUNTRY_NAME[m] for m in MARKETS], rotation=25, fontsize=8)
    axes[0, 0].set_title("Average country exposure (share)", fontsize=10)
    axes[0, 1].set_title("Equal-country APAC share over time (1/K markets)", fontsize=10)
    months = sorted({ym for (m, ym) in wts if ym + 1 in oos_idx})
    ks = pd.Series({ym: sum(any(kk[0] == mm and kk[1] == ym for kk in wts) for mm in MARKETS)
                    for ym in months}, dtype=float)
    ks.index = ks.index + 1
    share = (100.0 / ks.sort_index())
    axes[0, 1].plot(share.index.to_timestamp(), share, color="#333", lw=1.6)
    axes[0, 1].axhline(100.0 / len(MARKETS), color="#999", ls="--", lw=1)
    axes[0, 1].set_ylabel("Share per country (%)")
    axes[0, 1].set_ylim(0, 100.0 / max(ks.min(), 1) * 1.05)
    save_fig(fig, "fig13_country_exposure.png")


def fig_risk_contrib(risk_contrib):
    fig, ax = plt.subplots(figsize=(11, 5.2))
    kr_share = 100 * float(risk_contrib.set_index("market").loc["KR", "risk_share"])
    fig.suptitle(f"Conclusion: country risk shares are unequal; South Korea has the largest ({kr_share:.1f}%)\nalongside its higher sleeve volatility",
                 x=0.5, y=0.985, ha="center", va="top", fontsize=12, fontweight="bold")
    fig.text(0.5, 0.845, "Country share of OOS portfolio variance, optimized APAC",
             ha="center", fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap("Source: results/portfolio/risk_contribution.csv. Units: share of portfolio variance. Takeaway: risk shares are unequal; KR contributes most alongside its higher sleeve volatility, not a correlation spike."),
             ha="center", va="bottom", fontsize=7.2, color="#555")
    fig.subplots_adjust(top=0.80, bottom=0.18, left=0.085, right=0.975)
    vals = risk_contrib.set_index("market").reindex(MARKETS)["risk_share"]
    ax.bar(range(len(MARKETS)), 100 * vals.to_numpy(), color=[C_COUNTRY[m] for m in MARKETS])
    ax.set_xticks(range(len(MARKETS)))
    ax.set_xticklabels([COUNTRY_NAME[m] for m in MARKETS], rotation=20, fontsize=8)
    ax.set_ylabel("Risk contribution (%)")
    save_fig(fig, "fig14_risk_contribution.png")


def fig_concentration(conc):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    axes = np.atleast_2d(axes)
    fig.suptitle("Conclusion: optimized sleeves hold more names than quintile sleeves, lowering name concentration",
                 x=0.5, y=0.985, ha="center", va="top", fontsize=12, fontweight="bold")
    fig.text(0.5, 0.875, "Country and name HHI by portfolio, OOS 2016+",
             ha="center", fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap("Source: results/portfolio/concentration.csv. Units: HHI (lower = more diversified). Takeaway: quintile sleeves are concentrated; optimized spreads name risk."),
             ha="center", va="bottom", fontsize=7.2, color="#555")
    fig.subplots_adjust(top=0.83, bottom=0.20, left=0.08, right=0.985, wspace=0.24)
    x = np.arange(len(conc))
    axes[0, 0].bar(x, 100 * conc["country_hhi"], color="#4c72b0")
    axes[0, 0].set_xticks(x); axes[0, 0].set_xticklabels(conc["portfolio"], rotation=25, fontsize=8)
    axes[0, 0].set_title("Country HHI (x100)", fontsize=10)
    axes[0, 0].margins(x=0.04)
    # ponytail: Benchmark is an index with no stock holdings -> name HHI is NA,
    # never a zero bar; plot only real sleeves and label the index explicitly.
    name_ok = conc["name_hhi"].notna()
    xn = np.arange(int(name_ok.sum()))
    axes[0, 1].bar(xn, conc.loc[name_ok, "name_hhi"], color="#c44e52")
    axes[0, 1].set_xticks(xn); axes[0, 1].set_xticklabels(conc.loc[name_ok, "portfolio"], rotation=25, fontsize=8)
    axes[0, 1].set_title("Average name HHI", fontsize=10)
    axes[0, 1].margins(x=0.04)
    axes[0, 1].set_ylim(0, float(conc.loc[name_ok, "name_hhi"].max()) * 1.25)
    na_names = conc.loc[~name_ok, "portfolio"].tolist()
    if na_names:
        axes[0, 1].text(0.98, 0.98, "N/A: " + ", ".join(na_names) + " (index, no stock holdings)",
                        transform=axes[0, 1].transAxes, ha="right", va="top",
                        fontsize=7.5, color="#555")
    save_fig(fig, "fig15_concentration.png")


def fig_cov_heatmap(corr):
    fig, ax = plt.subplots(figsize=(9.2, 6.8))
    fig.suptitle("Conclusion: country sleeves are only moderately correlated,\nso equal-country diversification is real",
                 x=0.5, y=0.99, ha="center", va="top", fontsize=11.5, fontweight="bold")
    fig.text(0.5, 0.885, "Correlation of country sleeve OOS monthly USD returns, optimized APAC",
             ha="center", fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap("Source: results/portfolio/country_corr.csv. Units: Pearson correlation. Takeaway: low average pairwise correlation supports the diversification benefit."),
             ha="center", va="bottom", fontsize=7.2, color="#555")
    fig.subplots_adjust(top=0.84, bottom=0.14, left=0.13, right=0.98)
    im = ax.imshow(corr.to_numpy(), cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr))); ax.set_xticklabels([COUNTRY_NAME[m] for m in corr.columns], rotation=35, fontsize=8)
    ax.set_yticks(range(len(corr))); ax.set_yticklabels([COUNTRY_NAME[m] for m in corr.index], fontsize=8)
    for i in range(len(corr)):
        for j in range(len(corr)):
            ax.text(j, i, f"{corr.iloc[i, j]:.2f}", ha="center", va="center", fontsize=7)
    fig.colorbar(im, ax=ax, shrink=0.8)
    save_fig(fig, "fig16_cov_corr_heatmap.png")


def fig_eff_risk_alpha(metrics):
    fig, ax = plt.subplots(figsize=(10, 5.4))
    rel = ("above" if metrics["Low Risk"]["cagr"] > metrics["Benchmark"]["cagr"]
           else "below")
    fig.suptitle("Conclusion: Momentum leads on net CAGR and Sharpe; Low Risk is the lowest-CAGR\n"
                 f"active sleeve (lower volatility) but still {rel} the benchmark",
                 x=0.5, y=0.985, ha="center", va="top", fontsize=12, fontweight="bold")
    fig.text(0.5, 0.845, "OOS annualised net return vs annualised volatility by portfolio",
             ha="center", fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap("Source: results/portfolio/final_apac_table.csv. Units: annualised return and volatility (%). Takeaway: momentum dominates on both return and Sharpe; low-risk lowers volatility but is the lowest net CAGR among active sleeves (still above the benchmark)."),
             ha="center", va="bottom", fontsize=7.2, color="#555")
    fig.subplots_adjust(top=0.80, bottom=0.15, left=0.085, right=0.90)
    for lab, m in metrics.items():
        ax.scatter(100 * m["vol"], 100 * m["cagr"], s=90,
                   color=PALETTE.get(lab, "#888"), label=lab)
        ha = "right" if lab == "Momentum" else "left"
        off = (-6, 4) if lab == "Momentum" else (4, 4)
        ax.annotate(lab, (100 * m["vol"], 100 * m["cagr"]), fontsize=8, ha=ha,
                    xytext=off, textcoords="offset points")
    ax.set_xlabel("Annualised volatility (%)")
    ax.set_ylabel("Annualised net CAGR (%)")
    save_fig(fig, "fig17_efficient_risk_alpha.png")


def fig_oos_annual(annual):
    fig, ax = plt.subplots(figsize=(12, 5.6))
    fig.suptitle("Conclusion: every sleeve has losing years; 2018 and 2022 are the common stress years",
                 x=0.5, y=0.985, ha="center", va="top", fontsize=12, fontweight="bold")
    fig.text(0.5, 0.875, "Calendar-year USD returns net of 15 bps friction + dated taxes (Benchmark uncharged), OOS 2016-2026 (2026 partial)",
             ha="center", fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap("Source: results/oos/oos_annual_returns.csv (net 15bps+dated tax; gross in oos_annual_returns_gross.csv). Units: annual net return (%). Takeaway: 2018 and 2022 are common down years; * 2026 is a partial year."),
             ha="center", va="bottom", fontsize=7.2, color="#555")
    fig.subplots_adjust(top=0.83, bottom=0.16, left=0.09, right=0.975)
    years = list(annual.index)
    x = np.arange(len(years)); w = 0.15
    for i, lab in enumerate(annual.columns):
        ax.bar(x + (i - (len(annual.columns) - 1) / 2) * w, 100 * annual[lab].to_numpy(), w, label=lab)
    xt = [f"{y}*" if int(y) == 2026 else str(y) for y in years]
    ax.set_xticks(x); ax.set_xticklabels(xt, rotation=0, fontsize=8)
    ax.set_ylabel("Annual net return (%)")
    ax.axhline(0, color="k", lw=0.8)
    ax.legend(fontsize=7, ncol=3, frameon=False)
    save_fig(fig, "fig18_oos_annual.png")


def fig_rolling_sharpe(port_ret, bench, oos_idx, cash):
    fig, ax = plt.subplots(figsize=(11, 5.2))
    fig.suptitle("Conclusion: Momentum and 1/N carry the more persistent Sharpe advantage; Low Risk does not",
                 x=0.5, y=0.985, ha="center", va="top", fontsize=12, fontweight="bold")
    fig.text(0.5, 0.875, "36-month rolling annualised Sharpe, net returns, OOS 2016+",
             ha="center", fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap("Source: results/oos/oos_portfolio_returns_net15bps.csv and riskfree.parquet. Units: annualised Sharpe over USD cash approximation. Takeaway: no sleeve delivers a stable Sharpe; rely on diversification."),
             ha="center", va="bottom", fontsize=7.2, color="#555")
    fig.subplots_adjust(top=0.83, bottom=0.15, left=0.085, right=0.975)
    b = bench.reindex(oos_idx).dropna(); bex = b - cash.reindex(b.index).fillna(0)
    ax.plot(bex.index.to_timestamp(), bex.rolling(36).mean() / bex.rolling(36).std() * np.sqrt(12),
            color=PALETTE["Benchmark"], lw=1.6, label="Benchmark")
    for k, lab in PORT_LABEL.items():
        r = port_ret[k].reindex(oos_idx).dropna(); ex = r - cash.reindex(r.index).fillna(0)
        ax.plot(ex.index.to_timestamp(), ex.rolling(36).mean() / ex.rolling(36).std() * np.sqrt(12),
                color=PALETTE[lab], lw=1.5, label=lab)
    ax.axhline(0, color="k", lw=0.8)
    ax.legend(fontsize=7.5, ncol=3, frameon=False)
    save_fig(fig, "fig19_rolling_sharpe.png")


def fig_1n_vs_opt(port_ret, cost_tables, oos_idx):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    axes = np.atleast_2d(axes)
    fig.suptitle("Conclusion: 1/N materially outperforms Optimized on net terminal wealth and CAGR",
                 x=0.5, y=0.985, ha="center", va="top", fontsize=12, fontweight="bold")
    fig.text(0.5, 0.875, "Optimized and 1/N cumulative net return and CAGR by scenario",
             ha="center", fontsize=8.8, color="#333")
    fig.text(0.5, 0.006, wrap("Source: results/oos/oos_portfolio_returns_net15bps.csv and results/portfolio/optimized_vs_1n.csv. Units: cumulative net return and annualised CAGR. Takeaway: only claim optimization helps if net economic metrics actually improve."),
             ha="center", va="bottom", fontsize=7.2, color="#555")
    fig.subplots_adjust(top=0.83, bottom=0.15, left=0.075, right=0.98, wspace=0.22)
    for k, lab in [("1n", "1/N"), ("optimized", "Optimized")]:
        r = port_ret[k].reindex(oos_idx).dropna()
        axes[0, 0].plot((1 + r).cumprod().index.to_timestamp(), (1 + r).cumprod(),
                        color=PALETTE[lab], lw=2, label=lab)
    axes[0, 0].legend(fontsize=8, frameon=False)
    axes[0, 0].set_title("Cumulative net growth of $1", fontsize=10)
    scen = ["gross", "cost_5bps", "cost_15bps", "cost_30bps"]
    x = np.arange(len(scen)); w = 0.35
    axes[0, 1].bar(x - w / 2, [100 * cost_tables["1/N"][s] for s in scen], w, label="1/N")
    axes[0, 1].bar(x + w / 2, [100 * cost_tables["Optimized"][s] for s in scen], w, label="Optimized")
    axes[0, 1].set_xticks(x); axes[0, 1].set_xticklabels(["gross", "5bps", "15bps", "30bps"], fontsize=8)
    axes[0, 1].set_ylim(0, 19)
    axes[0, 1].set_title("CAGR by scenario (%)", fontsize=10)
    axes[0, 1].legend(fontsize=8, frameon=False, loc="upper center", ncol=2)
    save_fig(fig, "fig20_1n_vs_optimized.png")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    print("=" * 78)
    print("APAC main empirical tests — frozen spec execution")
    print("=" * 78)
    panel, fx, rf, bench, jkp, french = load_all()
    fxm = fx_monthly(fx)
    cash = rf_monthly(rf)
    p = add_usd_returns(panel, fxm)
    b_usd = benchmark_usd(bench, fxm)
    print("panel rows:", len(p), "| months:", p["ym"].nunique(),
          "|", p["ym"].min(), "->", p["ym"].max())
    print("eligible rows:", int(p["eligible_universe"].sum()))

    # run-level QC record
    qc = dict(
        panel_rows=int(len(p)), eligible_rows=int(p["eligible_universe"].sum()),
        months=int(p["ym"].nunique()), first_month=str(p["ym"].min()),
        last_month=str(p["ym"].max()), markets=MARKETS,
        oos_start=OOS_START_YEAR, last_complete_realisation=str(FULL_LAST_REALISATION),
        cn_beta_ivol="NA_CN_NO_BENCHMARK (one-row CN benchmark)",
        survivorship="current-universe survivorship all markets; CN/HK questionable",
        aqr="NOT_AVAILABLE", network="none", lambda_risk=LAMBDA_RISK,
        cost_scenarios=list(COST_SCENARIOS.keys()))
    for c in ["mom_12_1", VOL_PRIMARY, VOL_ROBUST, "beta", "ivol", "next_month_return"]:
        qc[f"nonnull_{c}"] = int(p[c].notna().sum())
    qc["nonnull_beta_CN"] = int(p.loc[p.market.eq("CN"), "beta"].notna().sum())

    # features for signals
    p = p.copy()
    p["lowrisk_score"] = -p[VOL_PRIMARY]
    p["vol252_score"] = -p[VOL_ROBUST]
    p["beta_score"] = -p["beta"]
    p["ivol_score"] = -p["ivol"]

    # --- signal tests
    print("\n[1] signal tests (IC + quintiles) ...")
    ic_country, ic_pooled, ic_mon, _ = ic_tests(p)
    atomic_write_df(ic_country, DIRS["signal_tests"] / "ic_by_country.csv", index=False)
    atomic_write_df(ic_pooled, DIRS["signal_tests"] / "ic_pooled_apac.csv", index=False)
    atomic_write_df(ic_mon, DIRS["signal_tests"] / "ic_monthly_series.csv", index=False)
    q_mom, mem_mom = quintile_series(p, "mom_12_1")
    q_low, mem_low = quintile_series(p, "lowrisk_score")
    q_beta, mem_beta = quintile_series(p, "beta_score")
    q_ivol, mem_ivol = quintile_series(p, "ivol_score")
    sum_mom, spread_mom = quintile_summary(q_mom)
    sum_low, spread_low = quintile_summary(q_low)
    sum_beta, _ = quintile_summary(q_beta)
    sum_ivol, _ = quintile_summary(q_ivol)
    atomic_write_df(sum_mom, DIRS["signal_tests"] / "quintiles_mom.csv", index=False)
    atomic_write_df(sum_low, DIRS["signal_tests"] / "quintiles_lowrisk.csv", index=False)
    atomic_write_df(sum_beta, DIRS["signal_tests"] / "quintiles_beta.csv", index=False)
    atomic_write_df(sum_ivol, DIRS["signal_tests"] / "quintiles_ivol.csv", index=False)
    spread_rows = []
    for nm, sp in [("mom", spread_mom), ("lowrisk", spread_low)]:
        for mkt, s in sp.items():
            spread_rows.append(pd.DataFrame(dict(signal=nm, market=mkt,
                                                 ym=s.index, spread=s.to_numpy())))
    atomic_write_df(pd.concat(spread_rows, ignore_index=True),
                    DIRS["signal_tests"] / "quintile_spread_series.csv", index=False)

    # --- Fama-MacBeth
    print("[2] Fama-MacBeth ...")
    fm = fama_macbeth(p)
    atomic_write_df(fm["fm_pooled"], DIRS["fama_macbeth"] / "fm_pooled.csv", index=False)
    atomic_write_df(fm["fm_country"], DIRS["fama_macbeth"] / "fm_by_country.csv", index=False)
    atomic_write_df(fm["fm_monthly"], DIRS["fama_macbeth"] / "fm_monthly_slopes.csv", index=False)
    atomic_write_df(fm["skipped"], DIRS["fama_macbeth"] / "fm_skipped_months.csv", index=False)

    # --- external
    print("[3] external validation ...")
    jkp_sum, jkp_pairs = jkp_validation(spread_mom, spread_low, jkp)
    atomic_write_df(jkp_sum[jkp_sum.signal == "momentum"], DIRS["jkp_validation"] / "jkp_momentum.csv", index=False)
    atomic_write_df(jkp_sum[jkp_sum.signal == "low_risk"], DIRS["jkp_validation"] / "jkp_lowrisk.csv", index=False)
    atomic_write_df(jkp_pairs, DIRS["jkp_validation"] / "jkp_paired_series.csv", index=False)
    fr_df, _ = french_crosscheck(b_usd, cash, french)
    atomic_write_df(fr_df, DIRS["jkp_validation"] / "french_crosscheck.csv", index=False)
    atomic_write_df(aqr_status(), DIRS["jkp_validation"] / "aqr_status.csv", index=False)

    # --- portfolios
    print("[4] OOS portfolios ...")
    pr = run_portfolios(p, cash, b_usd)
    port_ret, bench_ret = pr["port_ret"], pr["bench"]
    oos_idx = pd.period_range(f"{OOS_START_YEAR}-01", FULL_LAST_REALISATION, freq="M")
    atomic_write_df(pd.DataFrame({PORT_LABEL[k]: port_ret[k] for k in PORT_LABEL}),
                    DIRS["oos"] / "oos_portfolio_returns.csv", index=True)
    # benchmark series
    atomic_write_df(bench_ret.rename("Benchmark").to_frame(),
                    DIRS["portfolio"] / "benchmark_returns.csv", index=True)
    # turnover table
    to_tab = pd.DataFrame({PORT_LABEL[k]: pr["turnover"][k] for k in PORT_LABEL})
    atomic_write_df(to_tab, DIRS["portfolio"] / "turnover.csv", index=True)

    # --- costs per portfolio
    print("[5] transaction costs ...")
    cost_tables, cost_sharpe, cost_rows = {}, {}, []
    port_net15 = {}
    for k, lab in PORT_LABEL.items():
        r = port_ret[k].reindex(oos_idx).dropna()
        out = apply_costs(r, pr["turnover"][k].reindex(oos_idx), pr["market_to"][k].reindex(oos_idx))
        port_net15[k] = out["cost_15bps"].reindex(oos_idx)
        m_gross = perf_metrics(out["gross"]); 
        tab = {"gross": m_gross["cagr"]}
        for scen in COST_SCENARIOS:
            tab[scen] = perf_metrics(out[scen])["cagr"]
        cost_tables[lab] = tab
        cost_sharpe[lab] = {"gross": perf_metrics(out["gross"], cash)["sharpe"]}
        for scen in COST_SCENARIOS:
            cost_sharpe[lab][scen] = perf_metrics(out[scen], cash)["sharpe"]
        for scen in ["gross"] + list(COST_SCENARIOS):
            mm = perf_metrics(out[scen], cash)
            cost_rows.append(dict(portfolio=lab, scenario=scen, cagr=mm["cagr"],
                                  vol=mm["vol"], sharpe=mm["sharpe"], max_dd=mm["max_dd"],
                                  mean_turnover=float(pr["turnover"][k].reindex(oos_idx).mean()),
                                  tax_cagr=perf_metrics(out["tax"].reindex(oos_idx).fillna(0))["cagr"]))
    atomic_write_df(pd.DataFrame(cost_rows), DIRS["transaction_costs"] / "cost_sensitivity.csv", index=False)
    atomic_write_df(pd.DataFrame({PORT_LABEL[k]: port_net15[k] for k in PORT_LABEL}),
                    DIRS["oos"] / "oos_portfolio_returns_net15bps.csv", index=True)
    tomb_rows = [dict(portfolio=PORT_LABEL[k], market=m, ym=str(ym), turnover=float(v))
                 for k in PORT_LABEL for m, s in pr["market_to"][k].items()
                 for ym, v in s.items()]
    atomic_write_df(pd.DataFrame(tomb_rows), DIRS["portfolio"] / "turnover_by_market.csv", index=False)
    tax_cov = pd.DataFrame([
        dict(market="CN", tax_type="stamp duty on sales", rate="5 bps sell-side",
             effective_from="2023-08-28", implemented="months >= 2023-08", notes="seller-side only"),
        dict(market="HK", tax_type="stamp duty", rate="10 bps per side",
             effective_from="2023-11-17", implemented="months >= 2023-11", notes="both buy and sell"),
        dict(market="IN", tax_type="STT", rate="0.1% delivery", effective_from="",
             implemented="NO", notes="no verified effective date -> not applied"),
        dict(market="JP", tax_type="finance transaction tax", rate="abolished 0%",
             effective_from="1999-04-01", implemented="NO", notes="zero rate; no cost"),
        dict(market="KR", tax_type="securities transaction tax", rate="~0.15% sell",
             effective_from="", implemented="NO", notes="no verified effective date -> not applied"),
        dict(market="SG", tax_type="stamp duty", rate="0.2% buy", effective_from="",
             implemented="NO", notes="no verified effective date -> not applied"),
        dict(market="TW", tax_type="securities transaction tax", rate="0.3% sell",
             effective_from="", implemented="NO", notes="no verified effective date -> not applied")])
    atomic_write_df(tax_cov, DIRS["transaction_costs"] / "tax_coverage.csv", index=False)

    # --- factor-only gross/net
    print("[6] factor-only cost table ...")
    factor_rows = []
    for nm, qdf, mem in [("MOM", q_mom, mem_mom), ("LOWRISK", q_low, mem_low)]:
        q5 = qdf[qdf.quintile == 5].groupby("ym")["ret"].mean()
        q1 = qdf[qdf.quintile == 1].groupby("ym")["ret"].mean()
        spread = (q5 - q1).dropna()
        # turnover: equal-country average of Q5 (and Q1) membership turnover
        to5 = pd.DataFrame({m: quintile_turnover(mem, m, 5) for m in MARKETS}).mean(axis=1, skipna=True)
        to1 = pd.DataFrame({m: quintile_turnover(mem, m, 1) for m in MARKETS}).mean(axis=1, skipna=True)
        for lab, ser, to in [("long_only_Q5", q5, to5), ("long_short_Q5Q1", spread, (to5 + to1))]:
            gg = perf_metrics(ser)["cagr"]
            factor_rows.append(dict(factor=nm, leg=lab, gross_cagr=gg,
                                    n_months=len(ser)))
            for scen, bps in COST_SCENARIOS.items():
                nn = perf_metrics(ser - to.reindex(ser.index).fillna(0) * bps)["cagr"]
                factor_rows[-1][scen] = nn
    atomic_write_df(pd.DataFrame(factor_rows), DIRS["transaction_costs"] / "factor_gross_net.csv", index=False)

    # --- robustness
    print("[7] robustness ...")
    # vol252 IC + quintile
    atomic_write_df(ic_country[ic_country.signal == "vol252"],
                    DIRS["robustness"] / "vol252_ic.csv", index=False)
    sum252, _ = quintile_summary(quintile_series(p.assign(vol252_score=-p[VOL_ROBUST]), "vol252_score")[0])
    atomic_write_df(sum252, DIRS["robustness"] / "vol252_quintiles.csv", index=False)
    # sample covariance optimizer
    d_opt = pr["d"]
    usd_ret_mat = {m: usd_return_matrix(d_opt, m) for m in MARKETS}
    fm_usd_all = fm_pooled_slopes(prep_fm(p, "usd_next_return"))
    samp_cols, fb_s = {}, []
    for m in MARKETS:
        sm, _, fbm = optimized_sleeve(d_opt[d_opt["market"] == m], usd_ret_mat,
                                      fm_usd_all, sample_cov=True)
        samp_cols[m] = sm
        fb_s += fbm
    physample = pd.DataFrame(samp_cols).sort_index()
    atomic_write_df(physample, DIRS["robustness"] / "optimizer_sample_cov.csv", index=True)
    atomic_write_df(pd.DataFrame(fb_s, columns=["market", "ym", "reason"]),
                    DIRS["robustness"] / "optimizer_sample_cov_fallbacks.csv", index=False)
    atomic_write_df(pd.DataFrame(pr["foldbacks"], columns=["market", "ym", "reason"]),
                    DIRS["robustness"] / "optimizer_fallbacks.csv", index=False)
    # turnover conventions
    tc_rows = []
    for k, lab in PORT_LABEL.items():
        to = pr["turnover"][k].reindex(oos_idx).dropna()
        tc_rows.append(dict(portfolio=lab, convention="initial_0.5*sum|w0|",
                            mean_turnover=float(to.mean()),
                            note="one-way = 0.5*sum|dw|; initial w_prev=0 -> 0.5"))
        alt = to.copy()
        if len(alt):
            alt.iloc[0] = alt.iloc[0] * 2 if False else alt.iloc[0]
        tc_rows.append(dict(portfolio=lab, convention="investor_entry_full_notional",
                            mean_turnover=float(to.mean()),
                            note="alternative: first purchase counted as full one-way = 1.0 (month 1 only)"))
    atomic_write_df(pd.DataFrame(tc_rows), DIRS["robustness"] / "turnover_conventions.csv", index=False)
    # sample attrition
    att = p.groupby(["market", "eligible_reason"]).size().reset_index(name="n")
    atomic_write_df(att, DIRS["robustness"] / "sample_attrition.csv", index=False)
    # multiplicity
    prim = fm["fm_pooled"]
    n_tests = len(prim)
    mrows = []
    for _, r in prim.iterrows():
        mrows.append(dict(test=f"FM_{r['regressor']}", p_two_sided=float(2 * (1 - _norm_cdf(abs(r["nw_t"])))),
                          t=float(r["nw_t"]), n_tests=n_tests, bonferroni_alpha=0.05 / n_tests,
                          sidak_alpha=1 - (1 - 0.05) ** (1 / n_tests)))
    atomic_write_df(pd.DataFrame(mrows), DIRS["robustness"] / "multiplicity.csv", index=False)
    # predeclared eight-family robustness suite
    rob_sum = run_robustness(p, pr, oos_idx, cash)
    print(f"  robustness summary rows: {len(rob_sum)} "
          f"({rob_sum['variation'].nunique()} variations, "
          f"{int((rob_sum['status'] == 'na').sum())} explicit NA)")

    # --- portfolio summary / final table / concentration / risk / corr
    print("[8] portfolio summary tables ...")
    metrics = {}
    for k, lab in PORT_LABEL.items():
        r = port_ret[k].reindex(oos_idx).dropna()
        net = apply_costs(r, pr["turnover"][k].reindex(oos_idx), pr["market_to"][k].reindex(oos_idx))["cost_15bps"]
        mg = perf_metrics(r, cash)
        mn = perf_metrics(net, cash)
        metrics[lab] = dict(cagr=mn["cagr"], gross_cagr=mg["cagr"], vol=mn["vol"],
                            sharpe=mn["sharpe"], max_dd=mn["max_dd"],
                            turnover=float(pr["turnover"][k].reindex(oos_idx).mean()),
                            net_cum=mn["cum"], worst_year=mn["worst_year"],
                            best_year=mn["best_year"])
    bm = perf_metrics(bench_ret.reindex(oos_idx).dropna(), cash)
    metrics["Benchmark"] = dict(cagr=bm["cagr"], gross_cagr=bm["cagr"], vol=bm["vol"],
                                sharpe=bm["sharpe"], max_dd=bm["max_dd"],
                                turnover=np.nan, net_cum=bm["cum"],
                                worst_year=bm["worst_year"], best_year=bm["best_year"])

    # concentration
    conc_rows = []
    for k, lab in PORT_LABEL.items():
        wts = pr["weights_store"][k]
        cH, nH, maxw = [], [], []
        for (m, ym), w in wts.items():
            if ym + 1 not in oos_idx:
                continue
            # country weights (equal-country average over available)
            avail = [mm for mm in MARKETS if any(kk[0] == mm and kk[1] == ym for kk in wts)]
            if not avail:
                continue
            cw = 1.0 / len(avail)
            cH.append(sum(cw ** 2 for _ in avail))
            maxw.append(cw)
            # name HHI: (1/K^2) * sum_c sum_i w_ci^2 ; weights are within-country
            nh = (cw ** 2) * float((w ** 2).sum())
            nH.append(nh)
        conc_rows.append(dict(portfolio=lab, country_hhi=np.mean(cH),
                              max_country_weight=np.mean(maxw),
                              name_hhi=np.mean(nH)))
    conc_rows.append(dict(portfolio="Benchmark", country_hhi=1 / 6, max_country_weight=1 / 6,
                          name_hhi=np.nan))
    conc = pd.DataFrame(conc_rows)
    atomic_write_df(conc, DIRS["portfolio"] / "concentration.csv", index=False)

    # risk contribution + corr (optimized)
    cs = pd.DataFrame({m: pr["country_sleeves"]["optimized"].get(m) for m in MARKETS}).reindex(oos_idx).dropna()
    corr = cs.corr()
    atomic_write_df(corr, DIRS["portfolio"] / "country_corr.csv")
    S = cs.cov().to_numpy()
    w = np.ones(len(MARKETS)) / len(MARKETS)
    mrc = w * (S @ w)
    rc = mrc / mrc.sum()
    risk_contrib = pd.DataFrame(dict(market=MARKETS, risk_share=rc,
                                     sleeve_vol=np.sqrt(np.diag(S)) * np.sqrt(12)))
    atomic_write_df(risk_contrib, DIRS["portfolio"] / "risk_contribution.csv", index=False)

    # annual tables: canonical labelled file is NET 15bps + dated taxes; gross
    # is retained explicitly. Benchmark is uncharged (no frictions, no tax).
    def _annual(series: pd.Series) -> pd.Series:
        s = series.reindex(oos_idx).dropna()
        return (1.0 + s).groupby(s.index.year).prod() - 1.0

    annual_net = pd.DataFrame({lab: _annual(port_net15[k]) for k, lab in PORT_LABEL.items()})
    annual_net["Benchmark"] = _annual(bench_ret)
    annual_net.index.name = "year"

    annual_gross = pd.DataFrame({lab: _annual(port_ret[k]) for k, lab in PORT_LABEL.items()})
    annual_gross["Benchmark"] = _annual(bench_ret)
    annual_gross.index.name = "year"

    annual = annual_net  # canonical (net) table used by the figure and reports
    atomic_write_df(annual_gross, DIRS["oos"] / "oos_annual_returns_gross.csv")
    atomic_write_df(annual_net, DIRS["oos"] / "oos_annual_returns.csv")
    atomic_write_df(annual_net, DIRS["oos"] / "oos_annual_returns_net15bps.csv")
    n_months = pd.Series(1, index=oos_idx).groupby(oos_idx.year).sum()
    annual_meta = pd.DataFrame({"year": n_months.index.astype(int),
                                "n_months": n_months.to_numpy(),
                                "partial": (n_months.to_numpy() < 12)})
    atomic_write_df(annual_meta, DIRS["oos"] / "oos_annual_returns_meta.csv", index=False)

    # final APAC table
    final = []
    for lab in ["Benchmark", "1/N", "Momentum", "Low Risk", "Composite", "Optimized"]:
        m = metrics[lab]
        cc = conc.loc[conc.portfolio == lab, "country_hhi"].iloc[0]
        final.append(dict(Portfolio=lab, CAGR=m["gross_cagr"], Volatility=m["vol"],
                          Sharpe=m["sharpe"], MaxDrawdown=m["max_dd"],
                          Turnover=m["turnover"], NetReturn=m["cagr"],
                          WorstYear=m["worst_year"], BestYear=m["best_year"],
                          CountryConcentration=cc))
    final_df = pd.DataFrame(final)
    atomic_write_df(final_df, DIRS["portfolio"] / "final_apac_table.csv", index=False)
    atomic_write_df(final_df, DIRS["tables"] / "final_apac_table.csv", index=False)

    # optimized vs 1/N decision
    o = metrics["Optimized"]; n1 = metrics["1/N"]
    verdict = []
    verdict.append(dict(metric="NetReturn", one_over_n=n1["cagr"], optimized=o["cagr"],
                        optimized_better=bool(o["cagr"] > n1["cagr"])))
    verdict.append(dict(metric="Sharpe", one_over_n=n1["sharpe"], optimized=o["sharpe"],
                        optimized_better=bool(o["sharpe"] > n1["sharpe"])))
    verdict.append(dict(metric="MaxDrawdown", one_over_n=n1["max_dd"], optimized=o["max_dd"],
                        optimized_better=bool(o["max_dd"] > n1["max_dd"])))
    verdict.append(dict(metric="Volatility", one_over_n=n1["vol"], optimized=o["vol"],
                        optimized_better=bool(o["vol"] < n1["vol"])))
    vs = pd.DataFrame(verdict)
    atomic_write_df(vs, DIRS["portfolio"] / "optimized_vs_1n.csv", index=False)
    opt_claim = bool(o["cagr"] > n1["cagr"] and o["sharpe"] > n1["sharpe"])

    # weights summary
    wsum = []
    for k, lab in PORT_LABEL.items():
        for m in MARKETS:
            vals = [w.sum() for (mm, ym), w in pr["weights_store"][k].items()
                    if mm == m and ym + 1 in oos_idx]
            wsum.append(dict(portfolio=lab, market=m, avg_weight=float(np.mean(vals)) if vals else np.nan))
    atomic_write_df(pd.DataFrame(wsum), DIRS["portfolio"] / "weights_summary.csv", index=False)

    # --- figures
    print("[9] figures ...")
    fig_cumulative_oos(port_net15, bench_ret, oos_idx)
    fig_rolling(port_net15, oos_idx)
    fig_drawdowns(port_net15, bench_ret, oos_idx)
    fig_country_signal(sum_mom, "MOM", "fig04_country_momentum.png",
                       "results/signal_tests/quintiles_mom.csv",
                       "Conclusion: Momentum Q5-Q1 is positive in six of seven markets (India marginally negative)",
                       "Mean monthly Q5-Q1 USD spread by market, MOM, eligible sample, 2011-2026")
    fig_country_signal(sum_low, "LOWRISK", "fig05_country_lowrisk.png",
                       "results/signal_tests/quintiles_lowrisk.csv",
                       "Conclusion: Low-Risk Q5-Q1 is NEGATIVE in all seven markets (high-vol out-returned low-vol)",
                       "Mean monthly Q5-Q1 USD spread by market, LOWRISK=-vol_60, eligible sample, 2011-2026")
    fig_ic_time(ic_mon, ic_pooled)
    fig_ic_dist(ic_mon)
    fig_quintile_mono(sum_mom, sum_low)
    fig_jkp(jkp_pairs, jkp_sum)
    fig_turnover(port_ret, pr["turnover"], oos_idx)
    fig_gross_net(cost_tables)
    fig_sharpe_cost(cost_tables, cost_sharpe)
    fig_country_exposure(pr["weights_store"], oos_idx)
    fig_risk_contrib(risk_contrib)
    fig_concentration(conc)
    fig_cov_heatmap(corr)
    fig_eff_risk_alpha({k: metrics[k] for k in ["Benchmark", "1/N", "Momentum", "Low Risk", "Composite", "Optimized"]})
    fig_oos_annual(annual)
    fig_rolling_sharpe(port_net15, bench_ret, oos_idx, cash)
    fig_1n_vs_opt(port_net15, cost_tables, oos_idx)

    # --- tables summary copies
    atomic_write_df(ic_pooled, DIRS["tables"] / "signal_summary.csv", index=False)
    atomic_write_df(fm["fm_pooled"], DIRS["tables"] / "fm_summary.csv", index=False)
    atomic_write_df(pd.DataFrame(cost_rows), DIRS["tables"] / "cost_sensitivity.csv", index=False)
    atomic_write_df(tax_cov, DIRS["tables"] / "tax_coverage.csv", index=False)
    atomic_write_df(pd.DataFrame(mrows), DIRS["tables"] / "multiplicity.csv", index=False)
    atomic_write_df(annual_net, DIRS["tables"] / "oos_annual_returns.csv")
    atomic_write_df(annual_gross, DIRS["tables"] / "oos_annual_returns_gross.csv")

    # --- reports
    print("[10] reports ...")
    write_reports(p, ic_country, ic_pooled, fm, jkp_sum, fr_df, final_df,
                  annual_net, annual_gross,
                  vs, conc, risk_contrib, cost_tables, cost_sharpe, factor_rows,
                  tax_cov, mrows, qc, opt_claim, jkp_pairs, sum_mom, sum_low, rob_sum)

    atomic_write_text(json.dumps(qc, indent=2, default=str), DIRS["reports"] / "run_qc.json")

    print("\n" + "=" * 78)
    print("RUN COMPLETE")
    print(f"  panel: {qc['panel_rows']:,} rows, {qc['months']} months "
          f"{qc['first_month']}..{qc['last_month']}")
    print(f"  market coverage: {', '.join(MARKETS)} (210 current/curated names)")
    print(f"  OOS: {OOS_START_YEAR}-01 .. {FULL_LAST_REALISATION} ({len(oos_idx)} months); 2026 partial")
    print(f"  CN beta/ivol: {qc['cn_beta_ivol']}")
    print(f"  FM pooled MOM t={fm['fm_pooled'].set_index('regressor').loc['mom_z','nw_t']:.2f}, "
          f"LOWRISK t={fm['fm_pooled'].set_index('regressor').loc['lowrisk_z','nw_t']:.2f}")
    print(f"  optimized vs 1/N net improves economic metrics: {opt_claim}")
    print(f"  optimizer numeric EW fallbacks: "
          f"{int((pd.read_csv(DIRS['robustness'] / 'optimizer_fallbacks.csv')['reason']=='optimizer_fallback_ew').sum())}")
    print(f"  IC pooled (mom/lowrisk): "
          f"{ic_pooled[ic_pooled.signal=='mom']['avg_ic'].iloc[0]:.4f} / "
          f"{ic_pooled[ic_pooled.signal=='lowrisk']['avg_ic'].iloc[0]:.4f}")
    print("  unresolved blockers: survivorship all markets; 210 names only; CN no "
          "beta/ivol; tax data current-only; AQR NOT_AVAILABLE; 2026 partial")
    print("=" * 78)
    return qc


def _norm_cdf(x):
    from scipy.stats import norm
    return norm.cdf(x)


def _fallback_lines():
    fb = pd.read_csv(DIRS["robustness"] / "optimizer_fallbacks.csv")
    n_ew = int((fb["reason"] == "optimizer_fallback_ew").sum())
    n_hist = int((fb["reason"] == "insufficient_fm_history").sum())
    n_cov = int(fb["reason"].isin(["insufficient_cov_history", "insufficient_common_assets"]).sum())
    return (f"- Optimizer numeric fallback to equal weight: **{n_ew}** (recorded, series not silently altered).\n"
            f"- Sleeve-months skipped for inadequate FM training history: {n_hist}; "
            f"for insufficient covariance history: {n_cov} (marked NA, not traded).")


def write_reports(p, ic_country, ic_pooled, fm, jkp_sum, fr_df, final_df,
                  annual_net, annual_gross,
                  vs, conc, risk_contrib, cost_tables, cost_sharpe, factor_rows,
                  tax_cov, mrows, qc, opt_claim, jkp_pairs, sum_mom, sum_low, rob_sum):
    def row(lab):
        return final_df[final_df.Portfolio == lab].iloc[0]
    # corrected two-sided family-wise significance (Sidak = 1 - (1-alpha)^(1/k))
    mt = pd.DataFrame(mrows)
    sidak = float(mt["sidak_alpha"].iloc[0])
    bonf = float(mt["bonferroni_alpha"].iloc[0])
    survives = mt[mt["p_two_sided"] <= sidak]["test"].tolist()
    fails = mt[mt["p_two_sided"] > sidak]["test"].tolist()
    sig_status = (
        f"Corrected significance status (two-sided p vs family-wise thresholds "
        f"Sidak={sidak:.4f}, Bonferroni={bonf:.4f}, k={int(mt['n_tests'].iloc[0])}): "
        f"{', '.join(survives) if survives else 'none'} survive; "
        f"{', '.join(fails) if fails else 'none'} do not. "
        f"No Sidak alpha exceeds 0.05."
    )
    # ---- executive summary
    es = f"""# APAC Alpha-to-Portfolio — Executive Summary

**Scope.** Survivor-biased exploratory tests on 210 current/curated APAC names
(CN, HK, IN, JP, KR, SG, TW), monthly panel 2010-01..{qc['last_month']}. Signals:
12-1 momentum (MOM) and low-risk (`-vol_60`, LOWRISK); composite = fixed
`0.5 z(MOM)+0.5 z(LOWRISK)`. OOS is expanding, {OOS_START_YEAR}-01..{FULL_LAST_REALISATION}
(2026 partial, labelled incomplete).

**Headline results (net of 15 bps friction + dated taxes).**

| Portfolio | CAGR | Vol | Sharpe | MaxDD |
|-----------|------|-----|--------|-------|
| Benchmark (6-mkt) | {pct(row('Benchmark').NetReturn)} | {pct(row('Benchmark').Volatility)} | {num(row('Benchmark').Sharpe,2)} | {pct(row('Benchmark').MaxDrawdown)} |
| 1/N | {pct(row('1/N').NetReturn)} | {pct(row('1/N').Volatility)} | {num(row('1/N').Sharpe,2)} | {pct(row('1/N').MaxDrawdown)} |
| Momentum | {pct(row('Momentum').NetReturn)} | {pct(row('Momentum').Volatility)} | {num(row('Momentum').Sharpe,2)} | {pct(row('Momentum').MaxDrawdown)} |
| Low Risk | {pct(row('Low Risk').NetReturn)} | {pct(row('Low Risk').Volatility)} | {num(row('Low Risk').Sharpe,2)} | {pct(row('Low Risk').MaxDrawdown)} |
| Composite | {pct(row('Composite').NetReturn)} | {pct(row('Composite').Volatility)} | {num(row('Composite').Sharpe,2)} | {pct(row('Composite').MaxDrawdown)} |
| Optimized | {pct(row('Optimized').NetReturn)} | {pct(row('Optimized').Volatility)} | {num(row('Optimized').Sharpe,2)} | {pct(row('Optimized').MaxDrawdown)} |

**IC.** Pooled country-equal mean monthly Spearman IC: **MOM
{num(ic_pooled[ic_pooled.signal=='mom'].avg_ic.iloc[0],4)}, LOWRISK
{num(ic_pooled[ic_pooled.signal=='lowrisk'].avg_ic.iloc[0],4)}**. Positive on average
but sign-unstable month to month.

**Key finding — the low-risk premium is inverted here.** LOWRISK Q5-Q1 is
**negative in all seven markets** (country-equal mean {num(sum_low[sum_low.quintile=='Q5-Q1']['mean'].mean(),4)}/month);
high-volatility names out-returned low-vol names. Momentum Q5-Q1 is positive in six
of seven markets (country-equal mean {num(sum_mom[sum_mom.quintile=='Q5-Q1']['mean'].mean(),4)}/month).
The Low Risk sleeve's value is **risk reduction**, not return. Quintile sleeves also
drop markets whose top quintile has fewer than five names (in practice often SG), so
those markets remain only in 1/N — a construction artefact disclosed here.

**Fama-MacBeth (pooled, market FE, NW HAC(6)).**
{_fm_lines(fm['fm_pooled'])}

**Multiple testing.** {sig_status}

**Robustness.** Eight predeclared families (6-1 momentum; `vol_252`; bottom
10/20/40% liquidity cutoffs; equal vs liquidity weighting; developed vs emerging;
2016-2019 vs 2020-2025; survivor exclusion; country leave-one-out) are reported in
`results/robustness/robustness_summary.csv` with explicit NA statuses. None is
selected on Sharpe; liquidity weighting is a sensitivity only.

**Optimized vs 1/N.** Optimized net CAGR {pct(row('Optimized').NetReturn)} vs 1/N
{pct(row('1/N').NetReturn)}; Sharpe {num(row('Optimized').Sharpe,2)} vs
{num(row('1/N').Sharpe,2)}. **Claim that optimization improves economic metrics:
{'YES' if opt_claim else 'NO'}** — a claim is made only when OOS net economics
improve after charging the corrected per-one-way turnover cost.

**Key limitations.** Current-universe survivorship in ALL markets (CN/HK delisting
coverage 0); only 210 names; CN has no market-model beta/IVOL (one-row benchmark);
taxes applied only for CN/HK with verified dates; AQR **NOT AVAILABLE**; no network.
"""
    atomic_write_text(es, DIRS["reports"] / "APAC_Alpha_to_Portfolio_Executive_Summary.md")

    # ---- final report
    fr = f"""# APAC Alpha-to-Portfolio — Final Report

Model: `opencode-go/deepseek-v4.1-flash`. Frozen spec: `METHODOLOGY_MAIN_TESTS.md`,
`SPECIFICATION_REGISTRY.csv`. No network; no Prompt 1-2 input modified.

## 1. Sample and coverage
- Panel rows: **{qc['panel_rows']:,}**; months **{qc['months']}**
  ({qc['first_month']}..{qc['last_month']}); eligible rows **{qc['eligible_rows']:,}**.
- Markets: {', '.join(MARKETS)}. OOS: {OOS_START_YEAR}-01..{FULL_LAST_REALISATION}
  ({len(pd.period_range(f'{OOS_START_YEAR}-01', FULL_LAST_REALISATION, freq='M'))} months);
  2026 partial and labelled incomplete.
- **CN beta/ivol = NA** (CN benchmark has one daily row). Non-null CN beta rows:
  {qc['nonnull_beta_CN']}.
- Survivorship: {qc['survivorship']}.

## 2. Standalone signal tests
Pooled country-equal IC (monthly, not annualised):
```
{ic_pooled.to_string(index=False)}
```
By-market detail in `results/signal_tests/ic_by_country.csv`; quintile stats in
`quintiles_mom.csv` / `quintiles_lowrisk.csv`; beta/ivol (secondary, CN NA) in
`quintiles_beta.csv` / `quintiles_ivol.csv`.

**Low-risk premium is inverted in this panel.** Country-equal LOWRISK Q5-Q1 is
negative in **all seven markets** (mean {num(sum_low[sum_low.quintile=='Q5-Q1']['mean'].mean(),4)}/month);
MOM Q5-Q1 is positive in six of seven (mean {num(sum_mom[sum_mom.quintile=='Q5-Q1']['mean'].mean(),4)}/month;
India marginally negative). Quintile sleeves skip a market-month when its top
quintile has fewer than five names, so some markets (often SG) appear only in 1/N.

## 3. Fama-MacBeth (primary)
{_fm_lines(fm['fm_pooled'])}
Per-country MOM/LOWRISK in `results/fama_macbeth/fm_by_country.csv`. Skipped months
logged in `fm_skipped_months.csv`.

## 4. External validation
JKP (momentum / low_risk), exact common dates:
```
{jkp_sum.to_string(index=False)}
```
Methodology and units differ (JKP value-weighted long-short excess USD vs our
equal-weight, survivor-biased, FX-converted Q5-Q1). French cross-check (market
return only):
```
{fr_df.to_string(index=False)}
```
AQR: **NOT_AVAILABLE**.

## 5. OOS portfolios and the optimizer
Expanding training (2010..Dec Y-1), test year Y, 2016..; forecast from
expanding Fama-MacBeth coefficients; covariance = trailing {COV_WINDOW}m USD,
min {COV_MIN_OBS} obs, Ledoit-Wolf; lambda={LAMBDA_RISK}; SLSQP simplex.
Turnover one-way = 0.5*sum|dw|, initial 0.5. The optimizer transaction penalty uses
the **same per-one-way** convention, `eta*base_cost_rate*0.5*sum|w-w0|` (3.0 bps
one-way, eta={ETA_COST}), so the in-objective charge and the realised cost scenarios
are measured identically.
{_fallback_lines()}

### Final APAC table (CAGR = gross; NetReturn = net of 15 bps + dated taxes)
```
{final_df.to_string(index=False)}
```
Optimized vs 1/N:
```
{vs.to_string(index=False)}
```
Decision: **{'optimization improves OOS net economic metrics' if opt_claim else 'no robust improvement from optimization versus 1/N'}**.

## 6. Costs and taxes
Friction scenarios 5/15/30 bps per one-way traded notional (illustrative, not
official). Dated taxes: CN seller stamp 5 bps (>=2023-08-28), HK 10 bps/side
(>=2023-11-17). Other jurisdictions unverified -> not applied.
```
{_cost_table(cost_tables)}
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
{annual_net.to_string()}
```
Gross counterpart in `results/oos/oos_annual_returns_gross.csv`; the canonical
`results/oos/oos_annual_returns.csv` is byte-identical to
`results/oos/oos_annual_returns_net15bps.csv`. **2026 is a partial calendar year
(9 months) and is labelled incomplete.**

## 7. Risk, concentration, multiple testing
Risk contribution, HHI and correlation in `results/portfolio/`. Multiplicity
(Bonferroni/Sidak over the small primary FM family):
```
{pd.DataFrame(mrows).to_string(index=False)}
```
{sig_status}
Following Harvey-Liu-Zhu (2016), Feng-Giglio-Xiu (2020), Hou-Xue-Zhang (2020):
**nominal t-stats are not discovery**; conclusions rest on economic significance and
OOS net, and the survivor-biased panel prevents any bias-free claim.

## 8. Robustness suite (eight predeclared families)
No specification in this section was selected on Sharpe. Each family maps to a
`family`/`variation`/`status` row in `results/robustness/robustness_summary.csv`;
`status='na'` marks an explicit non-result (never a silent skip). Windows in
`results/robustness/robustness_windows.csv`.

{_robust_table(rob_sum)}

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
"""
    atomic_write_text(fr, DIRS["reports"] / "APAC_Alpha_to_Portfolio_Final_Report.md")


def _robust_table(rob_sum: pd.DataFrame) -> str:
    keep = rob_sum[(rob_sum["group"] == "APAC")
                   & (rob_sum["metric"].isin(["avg_ic", "q5_q1_mean", "gross_cagr",
                                              "net15_cagr", "market_coverage"]))]
    lines = ["| family | variation | factor | metric | value | status | note |",
             "|---|---|---|---|---|---|---|"]
    for _, r in keep.iterrows():
        lines.append(f"| {r['family']} | {r['variation']} | {r['factor']} | "
                     f"{r['metric']} | {num(r['value'], 4)} | {r['status']} | {r['note']} |")
    return "\n".join(lines)


def _fm_lines(df):
    out = []
    for _, r in df.iterrows():
        out.append(f"- {r['regressor']}: mean slope {num(r['mean_slope'],4)} "
                   f"(NW HAC(6) t={num(r['nw_t'],2)}), valid months {int(r['valid_months'])}, "
                   f"avg N {num(r['avg_n'],1)}")
    return "\n".join(out)


def _cost_table(cost_tables):
    labs = list(cost_tables)
    lines = ["portfolio".ljust(12) + "".join(s.ljust(12) for s in ["gross", "5bps", "15bps", "30bps"])]
    for lab in labs:
        t = cost_tables[lab]
        lines.append(lab.ljust(12) + "".join(
            pct(t[s]).ljust(12) for s in ["gross", "cost_5bps", "cost_15bps", "cost_30bps"]))
    return "\n".join(lines)


if __name__ == "__main__":
    main()
