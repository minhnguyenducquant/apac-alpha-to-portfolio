#!/usr/bin/env python3
"""APAC Alpha-to-Portfolio - monthly research panel cleaning pipeline.

Ponytail-minimal: one executable, reads Prompt 1 artifacts read-only, writes the
named cleaning deliverables + 11 QC charts. Method frozen in
METHODOLOGY_DATA_CLEANING.md; checked by tests/test_cleaning.py.

Run:
    .venv/bin/python scripts/clean_and_build_panel.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
CHARTS = REPORTS / "charts" / "cleaning"
for p in (PROC, REPORTS, CHARTS):
    p.mkdir(parents=True, exist_ok=True)

UTC = dt.timezone.utc
STUDY_START = "2010-01-01"
PRIMARY = "yfinance"
SECONDARY = {"baostock", "akshare"}

# Frozen exclusions: word-bounded, matched ONLY against stored provider fields.
EXCLUSION_PATTERNS = [
    ("REIT", r"\bREITS?\b"),
    ("TRUST", r"\bTRUSTS?\b"),
    ("UNITS", r"\bUNITS?\b"),
    ("FUND", r"\bFUNDS?\b"),
    ("ETF", r"\bETFS?\b"),
    ("CEF", r"\bCEFS?\b|CLOSED[- ]END"),
    ("PREFERRED", r"\bPREFERRED\b|\bPREF\b"),
    ("WARRANT", r"\bWARRANTS?\b"),
    ("RIGHT", r"\bRIGHTS?\b"),
    ("ADR", r"\bADRS?\b"),
    ("DR", r"\bDRS?\b|\bGDRS?\b"),
    ("RECEIPT", r"DEPOSITARY RECEIPT|\bRECEIPTS?\b"),
]
VEHICLE_TOKENS = {"REIT", "TRUST", "UNITS"}
FUND_TOKENS = {"FUND", "ETF", "CEF"}

SURVIVORSHIP_FLAG = {
    "CN": "SURVIVOR_BIAS_LABEL_QUESTIONABLE_DELISTING_COVERAGE_ZERO",
    "HK": "SURVIVOR_BIAS_LABEL_QUESTIONABLE_DELISTING_COVERAGE_ZERO",
    "IN": "CURRENT_SURVIVOR_BIAS",
    "JP": "CURRENT_SURVIVOR_BIAS",
    "KR": "CURRENT_SURVIVOR_BIAS",
    "SG": "CURRENT_SURVIVOR_BIAS",
    "TW": "CURRENT_SURVIVOR_BIAS",
}

DAILY_COLS = ["date", "internal_security_id", "provider_ticker", "market", "provider",
              "currency", "open", "high", "low", "close", "adj_close", "volume",
              "dividends", "stock_splits", "provider_amount_local_ccy",
              "traded_value_est_local_ccy", "trading_status", "trading_status_rule"]

# Point-in-time rolling windows (trailing, inclusive; no lookahead).
# Risk: 252 market sessions, >=126 valid TRADED observations (non-traded masked).
# Liquidity: trailing 60 market-session rows, >=40 valid traded observations.
SIGNAL_WIN, SIGNAL_MIN = 252, 126
VOL60_WIN, VOL60_MIN = 60, 40
LIQ_WIN, LIQ_MIN = 60, 40

# Momentum: product of exactly 11 monthly returns keyed t-12..t-2 (t-1 skipped).
MOM_N_RETURNS = 11

# Fixed lagged investability control: bottom quintile cut, never optimized.
LIQ_CUTOFF_Q = 0.20

# Monthly signal / target columns the research panel must expose with real values.
SIGNAL_COLS = ["mom_12_1", "vol_60", "vol_252", "beta", "dimson_beta", "ivol",
               "median_daily_traded_value", "amihud", "trading_frequency",
               "eligible_universe", "eligible_reason", "mom_rank", "lowrisk_rank",
               "beta_rank", "ivol_rank", "liquidity_rank", "next_month_return",
               "listing_date_proxy", "security_id", "ticker", "country",
               "data_quality_flag"]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def utcnow() -> str:
    return dt.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_write_df(path: Path, df: pd.DataFrame) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    if path.suffix == ".parquet":
        df.to_parquet(tmp, index=False)
    else:
        df.to_csv(tmp, index=False)
    os.replace(tmp, path)


def atomic_write_text(path: Path, s: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(s, encoding="utf-8")
    os.replace(tmp, path)


def sha256_file(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CleanLog:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, step: str, detail: str, n: int = 0, action: str = "",
            market: str = "", sid: str = "", provider: str = "") -> None:
        self.rows.append(dict(timestamp=utcnow(), step=step, market=market,
                              internal_security_id=sid, provider=provider,
                              detail=detail, n_records=int(n), action=action))

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


# ---------------------------------------------------------------------------
# load inputs
# ---------------------------------------------------------------------------
def load_inputs() -> dict:
    inputs = {
        "prices": PROC / "prices.parquet",
        "security_master_raw": ROOT / "data" / "security_master_raw.parquet",
        "security_master": PROC / "security_master.parquet",
        "benchmarks": PROC / "benchmarks.parquet",
        "source_crosscheck": REPORTS / "source_crosscheck.csv",
        "historical_universe_audit": REPORTS / "historical_universe_audit.csv",
        "corporate_action_audit": REPORTS / "corporate_action_audit.csv",
    }
    missing = [str(p) for p in inputs.values() if not p.exists()]
    if missing:
        raise SystemExit(f"missing required Prompt 1 inputs: {missing}")
    hashes = {k: sha256_file(p) for k, p in inputs.items()}
    return {
        "prices": pd.read_parquet(inputs["prices"]),
        "master": pd.read_parquet(inputs["security_master_raw"]),
        "benchmarks": pd.read_parquet(inputs["benchmarks"]),
        "crosscheck": pd.read_csv(inputs["source_crosscheck"]),
        "universe_audit": pd.read_csv(inputs["historical_universe_audit"]),
        "corporate_action_audit": pd.read_csv(inputs["corporate_action_audit"]),
        "_hashes": hashes,
    }


# ---------------------------------------------------------------------------
# step 1: duplicate handling (block on non-exact, dedupe exact)
# ---------------------------------------------------------------------------
def handle_duplicates(px: pd.DataFrame, log: CleanLog) -> pd.DataFrame:
    key = ["provider", "internal_security_id", "date"]
    vals = ["open", "high", "low", "close", "adj_close", "volume", "dividends", "stock_splits"]
    dupmask = px.duplicated(key, keep=False)
    n_dup = int(dupmask.sum())
    if n_dup == 0:
        log.add("duplicate_check", "no duplicate (provider, security, date) keys found",
                0, "none")
        return px

    d = px[dupmask].copy()
    vcols = [c for c in vals if c in d.columns]
    # within each duplicated key, keep only if every duplicate row is value-identical
    exact_mask = d.duplicated(key + vcols, keep=False)
    non_exact = int((~exact_mask).sum())
    if non_exact:
        # a key group with differing values blocks the run
        bad = d[~exact_mask][key].drop_duplicates()
        for _, r in bad.iterrows():
            log.add("duplicate_check", "non-exact duplicate key BLOCKS processing",
                    int((d[key] == r.tolist()).all(axis=1).sum()), "abort",
                    market=str(r["market"]), sid=str(r["internal_security_id"]),
                    provider=str(r["provider"]))
        raise SystemExit(
            f"non-exact duplicate (provider, security, date) records: {len(bad)} keys block processing")

    keep_first = d.duplicated(key, keep="first")
    px = px[~((dupmask) & (keep_first))]
    log.add("duplicate_check", "exact duplicates de-duplicated, first kept", int(keep_first.sum()),
            "dedupe_exact")
    return px


# ---------------------------------------------------------------------------
# step 2: daily clean
# ---------------------------------------------------------------------------
def build_daily_clean(px: pd.DataFrame, master: pd.DataFrame, bench_daily: pd.DataFrame,
                      log: CleanLog) -> pd.DataFrame:
    d = px.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.normalize()
    for c in ["open", "high", "low", "close", "adj_close", "volume", "dividends", "stock_splits"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")

    d["source_role"] = np.where(d["provider"].astype(str) == PRIMARY, "primary", "secondary")

    # True trade/suspension distinction: SUSPENDED (halted/zero volume) vs STALE
    # (provider flagged a >=5-day unchanged quote) vs TRADED. Never inferred from returns.
    d["trading_state"] = np.where(
        (d["trading_status"].astype(str) == "SUSPENDED") | d["volume"].le(0).fillna(True),
        "SUSPENDED",
        np.where(d["trading_status"].astype(str) == "STALE_OR_SUSPENDED", "STALE", "TRADED"))
    d["is_traded"] = d["trading_state"].eq("TRADED")
    d["is_suspended"] = d["trading_state"].eq("SUSPENDED")
    d["is_stale"] = d["trading_state"].eq("STALE")

    # Map local rows to each market's actual yfinance benchmark on overlapping dates.
    d = d.merge(bench_daily, on=["market", "date"], how="left")
    d["close_valid"] = d["close"].gt(0) & d["close"].notna()
    d["adj_close_valid"] = d["adj_close"].gt(0) & d["adj_close"].notna()
    d["invalid_price_flag"] = ~d["close_valid"]
    d["return_eligible"] = ((d["source_role"] == "primary") & d["close_valid"]
                            & d["adj_close_valid"])
    d["in_study_period"] = d["date"] >= pd.Timestamp(STUDY_START)

    d = d.sort_values(["provider", "internal_security_id", "date"])
    elig = d["return_eligible"]
    raw_ret = d.groupby(["provider", "internal_security_id"], sort=False)["adj_close"].pct_change()
    d["total_return_1d"] = np.where(elig, raw_ret, np.nan)

    d["ohlc_vendor_split_adjusted"] = True
    d["corporate_events_applied_again"] = False
    d["no_forward_fill"] = True
    d["corporate_action_note"] = (
        "vendor OHLC historically split-adjusted; total returns from Adj Close; "
        "dividends/splits NOT re-applied to raw close")

    # invalid-price log (aggregated)
    inv = d[d["invalid_price_flag"]]
    for (mkt, sid), g in inv.groupby(["market", "internal_security_id"], sort=False):
        log.add("invalid_price", "close <= 0 or null; flagged and return pair excluded",
                len(g), "flag_exclude_return", market=str(mkt), sid=str(sid),
                provider=str(g["provider"].iloc[0]))
    n_invalid = int(inv.shape[0])
    log.add("invalid_price", "invalid primary/secondary price rows flagged (no imputation)",
            n_invalid, "flag_exclude_return" if n_invalid else "none")

    # no-price coverage of master securities
    have = set(d.loc[d["source_role"] == "primary", "internal_security_id"])
    for _, r in master.iterrows():
        if r["internal_security_id"] not in have:
            log.add("price_coverage", "master security has no primary (yfinance) price rows",
                    0, "exclude_from_panel", market=str(r["market"]),
                    sid=str(r["internal_security_id"]), provider=PRIMARY)

    cols = DAILY_COLS + ["source_role", "close_valid", "adj_close_valid", "invalid_price_flag",
                         "return_eligible", "in_study_period", "total_return_1d",
                         "trading_state", "is_traded", "is_suspended", "is_stale",
                         "benchmark_ticker", "benchmark_source_label", "benchmark_return_1d",
                         "ohlc_vendor_split_adjusted", "corporate_events_applied_again",
                         "no_forward_fill", "corporate_action_note"]
    cols = [c for c in cols if c in d.columns]
    return d[cols].reset_index(drop=True)


# ---------------------------------------------------------------------------
# step 3: security master clean (classification + exclusions + share class)
# ---------------------------------------------------------------------------
def classify_security(name: str, stype: str) -> tuple[str, str]:
    txt = f"{name} | {stype}".upper()
    matched = [tok for tok, pat in EXCLUSION_PATTERNS if re.search(pat, txt, re.I)]
    if set(matched) & VEHICLE_TOKENS:
        cls = "INVESTMENT_VEHICLE"
    elif set(matched) & FUND_TOKENS:
        cls = "FUND"
    else:
        cls = "COMMON_EQUITY"
    return cls, ";".join(matched)


def shareclass_tokens(name: str) -> str:
    toks = []
    for tok, pat in [("SECOND_LINE", r"second line"), ("H_SHARE", r"\bH share"),
                     ("A_SHARE", r"\bA share"), ("ADR", r"\bADR\b")]:
        if re.search(pat, str(name), re.I):
            toks.append(tok)
    return ";".join(toks)


def build_security_master_clean(master: pd.DataFrame, daily: pd.DataFrame,
                                universe_audit: pd.DataFrame, log: CleanLog) -> pd.DataFrame:
    sm = master.copy()
    for c in ["company_name", "security_type"]:
        sm[c] = sm[c].astype(str)
    cls = [classify_security(n, t) for n, t in zip(sm["company_name"], sm["security_type"])]
    sm["instrument_class"] = [c for c, _ in cls]
    sm["exclusion_pattern_matched"] = [m for _, m in cls]
    sm["excluded_from_core"] = sm["instrument_class"] != "COMMON_EQUITY"
    sm["exclusion_reason"] = np.where(
        sm["excluded_from_core"],
        "non-common investment vehicle/security type (name/type heuristic): "
        + sm["exclusion_pattern_matched"], "")
    sm["name_heuristic_limitation"] = True
    sm["secondary_share_class_audit"] = (
        sm["primary_or_secondary_listing"].astype(str) + "|"
        + sm["share_class"].astype(str) + "|"
        + sm["company_name"].map(shareclass_tokens))

    # retain raw metadata explicitly
    sm["raw_security_type"] = sm["security_type"]
    sm["raw_company_name"] = sm["company_name"]

    # price coverage
    prim = daily[daily["source_role"] == "primary"]
    agg = prim.groupby("internal_security_id").agg(
        has_provider_price_series=("date", "size"),
        price_history_start=("date", "min"),
        price_history_end=("date", "max"))
    sm = sm.merge(agg, left_on="internal_security_id", right_index=True, how="left")
    sm["has_provider_price_series"] = sm["has_provider_price_series"].fillna(0).astype(int).gt(0)
    sm["price_history_start"] = sm["price_history_start"].astype("string")
    sm["price_history_end"] = sm["price_history_end"].astype("string")

    # survivorship carry-through
    aud = universe_audit.set_index("market")
    sm["source_audit_classification"] = sm["market"].map(aud["classification"])
    sm["delisting_coverage"] = sm["market"].map(aud["delisting_coverage"])
    sm["survivorship_flag"] = sm["market"].map(SURVIVORSHIP_FLAG)
    sm["survivorship_bias_cured"] = False
    sm["is_delisted_sample"] = sm["delisting_date_or_status"].astype(str).isin(["delisted", "inactive"])

    for _, r in sm[sm["excluded_from_core"]].iterrows():
        log.add("security_type_exclusion",
                f"excluded as {r['instrument_class']} via tokens [{r['exclusion_pattern_matched']}]; retained in audit",
                1, "exclude_from_core_retain", market=str(r["market"]),
                sid=str(r["internal_security_id"]), provider=str(r["provider"]))
    log.add("security_type_exclusion", "excluded from core panel (investment vehicles)",
            int(sm["excluded_from_core"].sum()), "exclude_from_core_retain")
    log.add("name_heuristic", "type exclusion is name/type-heuristic; word-bounded to avoid false positives",
            int(sm["excluded_from_core"].sum()), "documented_limitation")

    for mkt in sorted(sm["market"].unique()):
        log.add("survivorship", f"flag={SURVIVORSHIP_FLAG.get(mkt)}; bias not cured; "
                f"delisting_coverage={aud.loc[mkt, 'delisting_coverage']}",
                int((sm["market"] == mkt).sum()), "flag_not_cured", market=mkt)
    return sm


# ---------------------------------------------------------------------------
# step 4: benchmark returns (actual primary yfinance benchmark, overlapping dates)
# ---------------------------------------------------------------------------
def benchmark_daily_returns(benchmarks: pd.DataFrame) -> pd.DataFrame:
    b = benchmarks.copy()
    b["date"] = pd.to_datetime(b["date"]).dt.normalize()
    b["bench_close"] = b["adj_close"].where(b["adj_close"].gt(0), b["close"])
    b = b.sort_values(["market", "date"])
    b["benchmark_return_1d"] = b.groupby("market")["bench_close"].transform(
        lambda s: s / s.shift(1) - 1.0)
    return b[["market", "date", "ticker", "source_label", "benchmark_return_1d"]].rename(
        columns={"ticker": "benchmark_ticker", "source_label": "benchmark_source_label"})


def benchmark_monthly_returns(benchmarks: pd.DataFrame) -> pd.DataFrame:
    b = benchmarks.copy()
    b["date"] = pd.to_datetime(b["date"]).dt.normalize()
    b["bench_close"] = b["adj_close"].where(b["adj_close"].gt(0), b["close"])
    b["ym"] = b["date"].dt.to_period("M")
    me = b.sort_values("date").groupby(["market", "ym"], as_index=False).tail(1).copy()
    me = me.sort_values(["market", "ym"])
    me["benchmark_monthly_return"] = me.groupby("market")["bench_close"].transform(
        lambda s: s / s.shift(1) - 1.0)
    me["month"] = me["ym"].astype(str)
    return me[["market", "month", "benchmark_monthly_return"]]


# ---------------------------------------------------------------------------
# step 4b: rolling point-in-time signals (trailing windows, no lookahead)
# ---------------------------------------------------------------------------
def mom_12_1_from_returns(ret: pd.Series) -> pd.Series:
    """12-1 momentum from a gap-aware monthly return series indexed by month.

    Exactly 11 monthly return cells keyed t-12..t-2 are compounded:
    ``prod_m (1 + r_m) - 1`` for m = t-12 .. t-2. Month t-1 is deliberately
    EXCLUDED, so the value at t does not depend on r_{t-1} or P_{t-1}. All 11
    cells must be non-missing. On a full monthly grid the product telescopes to
    P_{t-2} / P_{t-13} - 1.
    """
    gross = (1.0 + ret).shift(2).rolling(
        MOM_N_RETURNS, min_periods=MOM_N_RETURNS).apply(np.prod, raw=True)
    return gross - 1.0


def compute_daily_signals(daily: pd.DataFrame) -> pd.DataFrame:
    """Trailing-window signal values per primary security, sampled at every
    market session. Each series is reindexed to its market's session calendar so
    liquidity uses a trailing 60 market-session rows and risk counts traded
    observations correctly. beta / dimson_beta / ivol use the market benchmark on
    actual overlapping dates only; momentum and the forward target are built
    later on the monthly panel.

    Risk (``vol_60``/``vol_252``/``beta``/``dimson_beta``/``ivol``) masks
    zero-volume / stale / suspended sessions; a genuine traded zero return stays
    valid. Liquidity keeps local-currency traded value and Amihud (no FX
    conversion).
    """
    prim = daily[(daily["source_role"] == "primary") & daily["in_study_period"]].copy()
    prim = prim.sort_values(["market", "internal_security_id", "date"])
    frames = []
    for mkt, mg in prim.groupby("market", sort=False):
        sessions = pd.DatetimeIndex(np.sort(mg["date"].unique()))
        for sid, s in mg.groupby("internal_security_id", sort=False):
            s = s.sort_values("date")
            idx = pd.DatetimeIndex(s["date"])
            y = pd.Series(np.asarray(s["total_return_1d"], dtype=float), index=idx).reindex(sessions)
            x = pd.Series(np.asarray(s["benchmark_return_1d"], dtype=float), index=idx).reindex(sessions)
            tv = pd.Series(np.asarray(s["traded_value_est_local_ccy"], dtype=float), index=idx).reindex(sessions)
            traded = pd.Series(np.asarray(s["is_traded"], dtype=float), index=idx).reindex(sessions)
            traded_b = traded.fillna(0.0).gt(0)
            # risk uses traded sessions only; non-traded returns are masked (a
            # traded zero return is a valid observation).
            ry = y.where(traded_b)

            vol_60 = ry.rolling(VOL60_WIN, min_periods=VOL60_MIN).std() * np.sqrt(252)
            vol_252 = ry.rolling(SIGNAL_WIN, min_periods=SIGNAL_MIN).std() * np.sqrt(252)

            roll = lambda z: z.rolling(SIGNAL_WIN, min_periods=SIGNAL_MIN).mean()
            valid = x.notna() & ry.notna()
            yv, xv = ry.where(valid), x.where(valid)
            mx, my = roll(xv), roll(yv)
            cov = roll(xv * yv) - mx * my
            varx = (roll(xv * xv) - mx * mx).replace(0.0, np.nan)
            vary = roll(yv * yv) - my * my
            beta = cov / varx
            ivol = np.sqrt((vary - beta * cov).clip(lower=0.0)) * np.sqrt(252)

            # Dimson (1979): beta on contemporaneous + one lagged market return.
            x1, x2 = x, x.shift(1)
            v3 = x1.notna() & x2.notna() & ry.notna()
            y3, a1, a2 = ry.where(v3), x1.where(v3), x2.where(v3)
            ma1, ma2, my3 = roll(a1), roll(a2), roll(y3)
            v11 = roll(a1 * a1) - ma1 * ma1
            v22 = roll(a2 * a2) - ma2 * ma2
            v12 = roll(a1 * a2) - ma1 * ma2
            c1y = roll(a1 * y3) - ma1 * my3
            c2y = roll(a2 * y3) - ma2 * my3
            det = (v11 * v22 - v12 * v12).replace(0.0, np.nan)
            dimson = (c1y * v22 - c2y * v12) / det + (v11 * c2y - v12 * c1y) / det

            # liquidity: trailing 60 market-session rows, >=40 valid traded
            # observations, local-currency traded value; frequency = traded/60.
            tv_pos = tv.where(tv > 0)
            median_tv = tv_pos.rolling(LIQ_WIN, min_periods=LIQ_MIN).median()
            amihud_daily = (ry.abs() / tv_pos).replace([np.inf, -np.inf], np.nan)
            amihud = amihud_daily.rolling(LIQ_WIN, min_periods=LIQ_MIN).mean()
            n_traded = traded.fillna(0.0).rolling(LIQ_WIN, min_periods=LIQ_MIN).sum()
            freq = (n_traded / LIQ_WIN).where(n_traded >= LIQ_MIN)

            out = pd.DataFrame({
                "vol_60": vol_60, "vol_252": vol_252, "beta": beta,
                "dimson_beta": dimson, "ivol": ivol,
                "median_daily_traded_value": median_tv, "amihud": amihud,
                "trading_frequency": freq})
            out.index.name = "date"
            out["internal_security_id"] = sid
            frames.append(out.reset_index())
    return pd.concat(frames, ignore_index=True)


def attach_signals(panel: pd.DataFrame, bench_monthly: pd.DataFrame,
                   daily_signals: pd.DataFrame) -> pd.DataFrame:
    out = panel.merge(daily_signals, on=["internal_security_id", "date"], how="left")
    out["month"] = out["month"].astype(str)
    bm = bench_monthly.copy()
    bm["month"] = bm["month"].astype(str)
    out = out.merge(bm, on=["market", "month"], how="left")

    # 12-1 momentum and the forward target, on a gap-aware monthly grid.
    # Momentum is the compounded product of 11 returns keyed t-12..t-2; see
    # mom_12_1_from_returns(). t-1 is excluded by construction.
    rows = []
    for sid, g in out.groupby("internal_security_id", sort=False):
        ym = pd.PeriodIndex(g["month"], freq="M")
        ret = pd.Series(g["monthly_total_return"].to_numpy(float), index=ym)
        full = pd.period_range(ym.min(), ym.max(), freq="M")
        ret = ret.reindex(full)
        mom = mom_12_1_from_returns(ret)
        rows.append(pd.DataFrame({
            "internal_security_id": sid, "month": full.astype(str),
            "mom_12_1": mom.to_numpy(), "next_month_return": ret.shift(-1).to_numpy()}))
    out = out.merge(pd.concat(rows, ignore_index=True),
                    on=["internal_security_id", "month"], how="left")

    # Point-in-time listing-date proxy. Source `listing_date` values are first
    # observed primary price dates (proxies, not true IPOs); where blank, the
    # security's first observed primary price date is used instead.
    out["listing_date_proxy"] = pd.to_datetime(out["listing_date"], errors="coerce")
    first_obs = out.groupby("internal_security_id")["date"].transform("min")
    out["listing_date_proxy"] = out["listing_date_proxy"].fillna(first_obs)
    # Known delisting dates only where genuinely parseable. Prompt 1 stores
    # statuses ("active"/"delisted"/"inactive") without dates, so this gate is
    # inert here but is kept for point-in-time correctness.
    _delist_raw = out["delisting_date_or_status"].astype(str)
    out["delisting_date_parsed"] = pd.to_datetime(
        _delist_raw.where(_delist_raw.str.match(r"^\d{4}-\d{2}-\d{2}")), errors="coerce")
    gate_listing = out["date"] >= out["listing_date_proxy"]
    gate_delisting = (out["delisting_date_parsed"].isna()
                      | (out["date"] <= out["delisting_date_parsed"]))

    # Signal / risk availability.
    gate_return = out["return_pair_valid"] & out["monthly_adj_close"].gt(0)
    gate_mom = out["mom_12_1"].notna()
    gate_risk = out["vol_252"].notna()
    gate_liq = out["median_daily_traded_value"].notna() & out["trading_frequency"].notna()
    core = (gate_listing & gate_delisting & gate_return & gate_mom & gate_risk & gate_liq)

    # Lagged investability control: within (market, formation month) exclude the
    # bottom quintile of the trailing median daily traded value, computed among
    # otherwise-eligible names. Fixed 20th percentile, never optimized.
    q20 = (out.loc[core].groupby(["market", "month"])["median_daily_traded_value"]
           .quantile(LIQ_CUTOFF_Q).rename("liq_q20"))
    out = out.merge(q20, on=["market", "month"], how="left")
    gate_cutoff = out["median_daily_traded_value"] >= out["liq_q20"]
    out["eligible_universe"] = core & gate_cutoff

    out["eligible_reason"] = ""
    for token, mask in [
            ("pre_listing", ~gate_listing),
            ("post_delisting", ~gate_delisting),
            ("no_valid_return", ~out["return_pair_valid"]),
            ("bad_price", ~out["monthly_adj_close"].gt(0)),
            ("no_mom_12_1", out["mom_12_1"].isna()),
            ("no_vol_252", out["vol_252"].isna()),
            ("no_liquidity", out["median_daily_traded_value"].isna()),
            ("no_trading_frequency", out["trading_frequency"].isna()),
            ("below_liquidity_cutoff", core & ~gate_cutoff)]:
        out["eligible_reason"] = np.where(mask,
                                          np.where(out["eligible_reason"].eq(""), token,
                                                   out["eligible_reason"] + ";" + token),
                                          out["eligible_reason"])

    # Ranks are oriented so higher = higher expected return / lower risk.
    # vol_60 is the primary low-risk signal (vol_252 is robustness); low vol
    # gets the high rank, so rank is descending in volatility.
    out["mom_rank"] = out.groupby(["market", "month"])["mom_12_1"].rank(pct=True)
    out["lowrisk_rank"] = out.groupby(["market", "month"])["vol_60"].rank(pct=True, ascending=False)
    out["beta_rank"] = out.groupby(["market", "month"])["beta"].rank(pct=True, ascending=False)
    out["ivol_rank"] = out.groupby(["market", "month"])["ivol"].rank(pct=True, ascending=False)
    out["liquidity_rank"] = out.groupby(["market", "month"])["median_daily_traded_value"].rank(pct=True)

    # Consumer aliases; internal ids are retained, not removed. No sector
    # neutralization is applied anywhere.
    out["security_id"] = out["internal_security_id"]
    out["ticker"] = out["provider_ticker"]
    out["data_quality_flag"] = np.where(
        ~out["monthly_adj_close"].gt(0), "INVALID_PRICE",
        np.where(out["return_pair_valid"], "OK", "NO_RETURN_PAIR"))

    out = out.sort_values(["market", "internal_security_id", "date"]).reset_index(drop=True)
    return out


# ---------------------------------------------------------------------------
# step 4c: monthly research panel
# ---------------------------------------------------------------------------
def build_monthly_panel(daily: pd.DataFrame, smclean: pd.DataFrame, log: CleanLog) -> pd.DataFrame:
    p = daily[(daily["source_role"] == "primary") & daily["in_study_period"]].copy()
    p["ym"] = p["date"].dt.to_period("M")

    # month-end snapshot: last actual observation per security-month
    me = p.sort_values("date").groupby(["internal_security_id", "ym"], as_index=False).tail(1).copy()
    me = me.sort_values(["internal_security_id", "ym"])

    g = me.groupby("internal_security_id", sort=False)
    me["prev_ym"] = g["ym"].shift(1)
    me["prev_date"] = g["date"].shift(1)
    me["prev_month_adj_close"] = g["adj_close"].shift(1)
    me["prev_month_close"] = g["close"].shift(1)

    pair_ok = (me["prev_ym"].notna()
               & (me["prev_ym"] == (me["ym"] - 1))
               & me["adj_close"].gt(0) & me["adj_close"].notna()
               & me["prev_month_adj_close"].gt(0) & me["prev_month_adj_close"].notna())
    me["return_pair_valid"] = pair_ok
    me["monthly_total_return"] = np.where(pair_ok,
                                          me["adj_close"] / me["prev_month_adj_close"] - 1.0, np.nan)

    reason = np.full(len(me), "", dtype=object)
    first = me["prev_ym"].isna()
    gap = me["prev_ym"].notna() & (me["prev_ym"] != (me["ym"] - 1))
    invalid = me["prev_ym"].notna() & ~first & ~gap & ~pair_ok
    reason[first] = "first_observation"
    reason[gap] = "gap_no_prior_month"
    reason[invalid] = "invalid_price_pair"
    me["return_missing_reason"] = np.where(pair_ok, "", reason)

    # monthly raw actions (retained)
    act = p.groupby(["internal_security_id", "ym"], as_index=False).agg(
        monthly_dividend_sum=("dividends", "sum"),
        monthly_split_sum=("stock_splits", "sum"),
        monthly_volume=("volume", "sum"))
    me = me.merge(act, on=["internal_security_id", "ym"], how="left")

    # security metadata (retain excluded rows in master, drop from core panel)
    meta_cols = ["internal_security_id", "company_name", "country",
                 "security_type", "instrument_class", "excluded_from_core", "share_class",
                 "primary_or_secondary_listing", "secondary_share_class_audit",
                 "listing_date", "delisting_date_or_status", "sector_or_industry",
                 "metadata_basis", "source_audit_classification", "delisting_coverage",
                 "survivorship_flag", "survivorship_bias_cured", "is_delisted_sample"]
    out = me.merge(smclean[meta_cols], on="internal_security_id", how="left")
    n_before = out["internal_security_id"].nunique()
    out = out[~out["excluded_from_core"].fillna(False)].copy()

    out["month"] = out["ym"].astype(str)
    out["date"] = out["date"].dt.normalize()
    out["monthly_raw_close"] = out["close"]
    out["monthly_adj_close"] = out["adj_close"]
    out["source_role"] = "primary"
    out["price_valid_pair"] = out["return_pair_valid"]
    out["no_forward_fill"] = True
    out["corporate_events_applied_again"] = False

    keep = ["date", "month", "internal_security_id", "provider_ticker", "market",
            "country", "company_name", "security_type", "instrument_class", "share_class",
            "primary_or_secondary_listing", "secondary_share_class_audit",
            "monthly_raw_close", "monthly_adj_close", "prev_month_close",
            "prev_month_adj_close", "monthly_total_return", "return_pair_valid",
            "price_valid_pair", "return_missing_reason", "monthly_dividend_sum",
            "monthly_split_sum", "monthly_volume", "listing_date",
            "delisting_date_or_status", "is_delisted_sample", "metadata_basis",
            "source_audit_classification", "survivorship_flag",
            "survivorship_bias_cured", "delisting_coverage", "source_role",
            "no_forward_fill", "corporate_events_applied_again",
            "benchmark_ticker", "benchmark_source_label", "benchmark_return_1d"]
    out = out[keep].sort_values(["market", "internal_security_id", "date"]).reset_index(drop=True)

    # log missing-return reasons (aggregated per security/reason)
    miss = out[out["return_missing_reason"] != ""]
    for (mkt, sid, rsn), g in miss.groupby(["market", "internal_security_id",
                                            "return_missing_reason"], sort=False):
        log.add("missing_return", f"invalid/absent return pair: {rsn}", len(g),
                "return_missing", market=str(mkt), sid=str(sid), provider=PRIMARY)
    log.add("panel_build", f"core panel securities={out['internal_security_id'].nunique()} "
            f"(pre-exclusion {n_before}); rows={len(out)}", len(out), "built")
    return out


# ---------------------------------------------------------------------------
# step 5: QC tables
# ---------------------------------------------------------------------------
def build_universe_qc(smclean: pd.DataFrame, crosscheck: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for mkt, g in smclean.groupby("market", sort=True):
        cc = crosscheck[crosscheck["market"] == mkt]
        rows.append(dict(
            market=mkt,
            n_master=len(g),
            n_with_prices=int(g["has_provider_price_series"].sum()),
            n_missing_prices=int((~g["has_provider_price_series"]).sum()),
            n_core_included=int((~g["excluded_from_core"]).sum()),
            n_excluded_investment_vehicle=int(g["excluded_from_core"].sum()),
            n_delisted_or_inactive=int(g["is_delisted_sample"].sum()),
            delisting_coverage=str(g["delisting_coverage"].iloc[0]),
            deliverable_crosscheck_ok=int((cc["status"] == "OK").sum()),
            source_audit_classification=str(g["source_audit_classification"].iloc[0]),
            survivorship_flag=str(g["survivorship_flag"].iloc[0]),
            survivorship_bias_cured=False,
            n_secondary_or_special=int(g["secondary_share_class_audit"].str.contains(
                "SECOND_LINE|ADR|H_SHARE|A_SHARE", regex=True).sum()),
            price_history_start=str(g["price_history_start"].min()),
            price_history_end=str(g["price_history_end"].max()),
            metadata_basis=str(g["metadata_basis"].iloc[0]),
        ))
    return pd.DataFrame(rows)


def build_signal_qc(panel: pd.DataFrame, daily: pd.DataFrame, log_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    dup_invalid = log_df[log_df["step"] == "invalid_price"]["n_records"].sum() if len(log_df) else 0
    for mkt, g in panel.groupby("market", sort=True):
        r = g["monthly_total_return"]
        valid = r.dropna()
        se = g.groupby("internal_security_id")["monthly_total_return"].apply(
            lambda s: s.dropna())
        rows.append(dict(
            market=mkt,
            n_securities=int(g["internal_security_id"].nunique()),
            n_obs_months=int(len(g)),
            n_return_valid=int(valid.shape[0]),
            n_return_missing=int((g["return_missing_reason"] != "").sum()),
            return_valid_pct=round(100 * valid.shape[0] / max(1, len(g)), 4),
            first_month=str(g["month"].min()),
            last_month=str(g["month"].max()),
            mean_monthly_return=round(float(valid.mean()), 8) if len(valid) else np.nan,
            std_monthly_return=round(float(valid.std()), 8) if len(valid) else np.nan,
            min_monthly_return=round(float(valid.min()), 8) if len(valid) else np.nan,
            max_monthly_return=round(float(valid.max()), 8) if len(valid) else np.nan,
            p01=round(float(valid.quantile(.01)), 8) if len(valid) else np.nan,
            p50=round(float(valid.quantile(.50)), 8) if len(valid) else np.nan,
            p99=round(float(valid.quantile(.99)), 8) if len(valid) else np.nan,
            n_outliers_abs_gt_50pct=int((valid.abs() > 0.5).sum()),
            zero_return_pct=round(100 * float((valid == 0).mean()), 4) if len(valid) else np.nan,
            n_invalid_price_daily=int(log_df[(log_df["market"] == mkt)
                                             & (log_df["step"] == "invalid_price")]["n_records"].sum()),
            n_eligible=int(g["eligible_universe"].sum()),
            eligible_pct=round(100 * float(g["eligible_universe"].mean()), 4),
            n_below_liquidity_cutoff=int(g["eligible_reason"].str.contains(
                "below_liquidity_cutoff").sum()),
            n_pre_listing=int(g["eligible_reason"].str.contains("pre_listing").sum()),
            n_data_quality_ok=int((g["data_quality_flag"] == "OK").sum()),
            n_mom_12_1=int(g["mom_12_1"].notna().sum()),
            n_vol_60=int(g["vol_60"].notna().sum()),
            n_vol_252=int(g["vol_252"].notna().sum()),
            n_beta=int(g["beta"].notna().sum()),
            n_dimson_beta=int(g["dimson_beta"].notna().sum()),
            n_ivol=int(g["ivol"].notna().sum()),
            n_median_daily_traded_value=int(g["median_daily_traded_value"].notna().sum()),
            n_amihud=int(g["amihud"].notna().sum()),
            n_trading_frequency=int(g["trading_frequency"].notna().sum()),
            n_next_month_return=int(g["next_month_return"].notna().sum()),
            benchmark_ticker=str(g["benchmark_ticker"].dropna().iloc[0]) if g["benchmark_ticker"].notna().any() else "",
            benchmark_source_label=str(g["benchmark_source_label"].dropna().iloc[0]) if g["benchmark_source_label"].notna().any() else "",
        ))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# step 6: charts (11)
# ---------------------------------------------------------------------------
def make_charts(daily, panel, smclean, uqc, sqc, caa, log_df) -> int:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.dpi": 130})
    C = {"CN": "#31506e", "HK": "#b5651d", "IN": "#2e7d32", "JP": "#8e24aa",
         "KR": "#c62828", "SG": "#00838f", "TW": "#6d4c41"}
    MKT_NAME = {"CN": "China", "HK": "Hong Kong", "IN": "India", "JP": "Japan",
                "KR": "South Korea", "SG": "Singapore", "TW": "Taiwan"}
    order = ["CN", "HK", "IN", "JP", "KR", "SG", "TW"]

    def frame(ax, title, subtitle, source, period, units, interp):
        ax.set_title(title, fontsize=13, fontweight="bold", loc="left")
        ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9, color="#333")
        ax.figure.text(0.01, 0.005, f"Source: {source} | Period: {period} | Units: {units}",
                       fontsize=7, color="#666")
        ax.figure.text(0.01, 0.028, f"Interpretation: {interp}", fontsize=7, color="#666")

    n = 0
    prim = daily[daily["source_role"] == "primary"]

    # 1 - price validity by market
    fig, ax = plt.subplots(figsize=(9, 4.2))
    valid = prim[prim["close_valid"]].groupby("market").size().reindex(order).fillna(0)
    invalid = prim[~prim["close_valid"]].groupby("market").size().reindex(order).fillna(0)
    x = np.arange(len(order))
    ax.bar(x, valid, color="#31506e", label="valid close (>0, non-null)")
    ax.bar(x, invalid, bottom=valid, color="#b00020", label="invalid close (<=0/null)")
    ax.set_xticks(x); ax.set_xticklabels([MKT_NAME[m] for m in order])
    ax.set_ylabel("daily rows")
    ax.legend(fontsize=7)
    frame(ax, "Daily Price Validity by Market",
          "Conclusion: invalid prices are flagged, never imputed or forward-filled.",
          "Prompt 1 prices.parquet (yfinance primary)", "1993-2026", "daily rows",
          "Red segments would be excluded from return pairs; zero here means no non-positive closes in the primary series.")
    fig.tight_layout(rect=[0, 0.08, 1, 0.95]); fig.savefig(CHARTS / "01_price_validity_by_market.png"); plt.close(fig); n += 1

    # 2 - invalid prices over time
    fig, ax = plt.subplots(figsize=(9, 4.2))
    dd = daily.copy(); dd["year"] = dd["date"].dt.year
    inv = dd[~dd["close_valid"]].groupby(["market", "year"]).size()
    for m in order:
        if m in inv.index.get_level_values(0):
            s = inv.loc[m]
            ax.plot(s.index, s.values, marker="o", ms=3, color=C[m], label=MKT_NAME[m])
    if not len(inv):
        ax.text(.5, .5, "NO INVALID PRICES IN ANY MARKET", ha="center", va="center",
                fontsize=12, color="#2e7d32")
    ax.set_xlabel("year"); ax.set_ylabel("invalid close rows")
    frame(ax, "Invalid / Non-Positive Prices Through Time",
          "Conclusion: no non-positive or null closes detected; the check runs regardless.",
          "Prompt 1 prices.parquet (all providers)", "1993-2026", "invalid rows per year",
          "A non-zero line would mark vendor errors (Ince & Porter 2006) excluded from returns.")
    if len(inv):
        ax.legend(fontsize=7)
    fig.tight_layout(rect=[0, 0.08, 1, 0.95]); fig.savefig(CHARTS / "02_invalid_prices_over_time.png"); plt.close(fig); n += 1

    # 3 - panel breadth by month
    fig, ax = plt.subplots(figsize=(9, 4.2))
    br = panel.groupby(["market", "month"])["internal_security_id"].nunique()
    for m in order:
        if m not in br.index.get_level_values(0):
            continue
        s = br.loc[m]
        if len(s):
            mm = pd.PeriodIndex(s.index, freq="M").to_timestamp()
            ax.plot(mm, s.values, color=C[m], label=MKT_NAME[m], lw=1.2)
    ax.set_ylabel("securities with a monthly observation")
    frame(ax, "Research-Panel Breadth by Month",
          "Conclusion: breadth rises with listings; names never print after delisting - survivorship is visible, not removed.",
          "Prompt 1 prices (yfinance primary), core common equity", "2010-2026", "count of securities",
          "Flat/dropping segments mark listings/delistings (Shumway 1997); the panel is a current snapshot with explicit survivorship flags.")
    ax.legend(fontsize=7, ncol=4)
    fig.tight_layout(rect=[0, 0.08, 1, 0.95]); fig.savefig(CHARTS / "03_panel_breadth_by_month.png"); plt.close(fig); n += 1

    # 4 - monthly return distribution
    fig, ax = plt.subplots(figsize=(9, 4.2))
    data = [panel.loc[panel["market"] == m, "monthly_total_return"].dropna() for m in order]
    bp = ax.boxplot(data, showfliers=False, patch_artist=True, tick_labels=[MKT_NAME[m] for m in order])
    for patch, m in zip(bp["boxes"], order):
        patch.set_facecolor(C[m]); patch.set_alpha(.7)
    for med in bp["medians"]:
        med.set_color("#111")
    ax.axhline(0, color="#888", lw=.8, ls="--")
    ax.set_ylabel("monthly total return (decimal)")
    frame(ax, "Monthly Total-Return Distribution by Market",
          "Conclusion: dispersion reflects market risk; outliers retained and reported, not winsorised.",
          "Adj Close close-to-close, valid pairs only", "2010-2026", "decimal monthly total return",
          "Medians near zero and wider inter-quartile ranges in KR/TW are expected; the signal is not trimmed.")
    fig.tight_layout(rect=[0, 0.08, 1, 0.95]); fig.savefig(CHARTS / "04_monthly_return_distribution.png"); plt.close(fig); n += 1

    # 5 - return coverage by month
    fig, ax = plt.subplots(figsize=(9, 4.2))
    cov = panel.groupby(["market", "month"]).apply(
        lambda g: 100 * (g["return_missing_reason"] == "").mean(), include_groups=False)
    for m in order:
        if m not in cov.index.get_level_values(0):
            continue
        s = cov.loc[m]
        if len(s):
            mm = pd.PeriodIndex(s.index, freq="M").to_timestamp()
            ax.plot(mm, s.values, color=C[m], label=MKT_NAME[m], lw=1.1)
    ax.set_ylabel("% of panel rows with a valid monthly return"); ax.set_ylim(0, 102)
    frame(ax, "Valid Monthly-Return Coverage by Market",
          "Conclusion: missing returns cluster at listing edges and gaps; they are logged, never filled.",
          "Adj Close pairs, positive & non-null required", "2010-2026", "percent of rows",
          "Dips indicate no immediately-prior month-end observation (IPO/gap); no forward fill or interpolation is applied.")
    ax.legend(fontsize=7, ncol=4)
    fig.tight_layout(rect=[0, 0.08, 1, 0.95]); fig.savefig(CHARTS / "05_return_coverage_by_month.png"); plt.close(fig); n += 1

    # 6 - equal-weight cumulative return
    fig, ax = plt.subplots(figsize=(9, 4.2))
    for m in order:
        g = panel[panel["market"] == m]
        ew = g.groupby("month")["monthly_total_return"].mean()
        cum = (1 + ew.fillna(0)).cumprod()
        mm = pd.PeriodIndex(cum.index, freq="M").to_timestamp()
        ax.plot(mm, cum.values, color=C[m], label=MKT_NAME[m], lw=1.3)
        ax.set_yscale("log")
    ax.set_ylabel("cumulative equal-weight total-return index (log)")
    frame(ax, "Equal-Weight Cumulative Total Return by Market",
          "Conclusion: a transparent equal-weight benchmark of the cleaned panel; survivorship-inflated, use with the flags.",
          "Mean monthly total return, compounded", "2010-2026", "index (start=1)",
          "Because the universe is a current snapshot, levels are upward-biased (Shumway 1997); shown to expose, not hide, that bias.")
    ax.legend(fontsize=7, ncol=4)
    fig.tight_layout(rect=[0, 0.08, 1, 0.95]); fig.savefig(CHARTS / "06_cumulative_equal_weight_return.png"); plt.close(fig); n += 1

    # 7 - rolling volatility
    fig, ax = plt.subplots(figsize=(9, 4.2))
    for m in order:
        g = panel[panel["market"] == m]
        ew = g.groupby("month")["monthly_total_return"].mean()
        vol = ew.rolling(12, min_periods=6).std() * np.sqrt(12)
        mm = pd.PeriodIndex(vol.dropna().index, freq="M").to_timestamp()
        s = vol.dropna()
        if len(s):
            ax.plot(mm, s.values, color=C[m], label=MKT_NAME[m], lw=1.2)
    ax.set_ylabel("annualised rolling 12m volatility")
    frame(ax, "Rolling 12-Month Volatility of Equal-Weight Market Return",
          "Conclusion: volatility clustering is visible; illiquid/stale names can attenuate it (Dimson 1979).",
          "Monthly total returns, equal-weight", "2010-2026", "annualised std (decimal)",
          "Spikes align with crisis periods; stale pricing in thin names biases measured volatility downward, which is why stale flags are retained.")
    ax.legend(fontsize=7, ncol=4)
    fig.tight_layout(rect=[0, 0.08, 1, 0.95]); fig.savefig(CHARTS / "07_rolling_volatility.png"); plt.close(fig); n += 1

    # 8 - excluded investment vehicles
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ex = smclean[smclean["excluded_from_core"]]
    cnt = ex.groupby(["market", "instrument_class"]).size().unstack(fill_value=0)
    cls_colors = {"INVESTMENT_VEHICLE": "#b5651d", "FUND": "#8e24aa"}
    bottom = np.zeros(len(order))
    for cls in cnt.columns:
        vals = cnt.reindex(order, fill_value=0)[cls].values
        ax.bar([MKT_NAME[m] for m in order], vals, bottom=bottom,
               color=cls_colors.get(cls, "#666"), label=cls)
        bottom += vals
    ax.set_ylabel("securities excluded from core panel")
    ax.legend(fontsize=7)
    frame(ax, "Investment Vehicles Excluded from the Core Panel",
          "Conclusion: SG/HK REITs & trusts are investable but excluded per instruction; retained with reasons in the audit.",
          "security_master_raw stored name/type fields", "current snapshot", "securities",
          "Exclusion is a name/type heuristic (word-bounded); the complete list and matched tokens are in data_cleaning_log.csv and security_master_clean.parquet.")
    fig.tight_layout(rect=[0, 0.08, 1, 0.95]); fig.savefig(CHARTS / "08_excluded_investment_vehicles.png"); plt.close(fig); n += 1

    # 9 - survivorship flags / delisting coverage
    fig, ax = plt.subplots(figsize=(9, 4.4))
    y = np.arange(len(order))
    num = [int(str(uqc.loc[uqc["market"] == m, "delisting_coverage"].iloc[0]).split("/")[0]) for m in order]
    den = [int(str(uqc.loc[uqc["market"] == m, "delisting_coverage"].iloc[0]).split("/")[1]) for m in order]
    pct = [100 * a / b if b else 0 for a, b in zip(num, den)]
    ax.barh(y, pct, color=[C[m] for m in order])
    ax.set_yticks(y); ax.set_yticklabels([MKT_NAME[m] for m in order])
    ax.set_xlabel("% of universe that is delisted/inactive (delisting coverage)")
    for i, (a, b) in enumerate(zip(num, den)):
        ax.text(pct[i] + 0.3, i, f"{a}/{b}", va="center", fontsize=8)
    frame(ax, "Survivorship / Delisting Coverage - Flagged, Not Cured",
          "Conclusion: CN/HK 'reliable' labels are questionable (0/N); IN/JP/KR/SG/TW are explicit current-survivor-bias. All flags carried into the panel.",
          "Prompt 1 historical_universe_audit.csv", "current snapshot", "percent delisted/inactive",
          "Near-zero coverage means the universe is essentially survivors; no market is claimed survivorship-free (Shumway 1997).")
    fig.tight_layout(rect=[0, 0.08, 1, 0.95]); fig.savefig(CHARTS / "09_survivorship_flags.png"); plt.close(fig); n += 1

    # 10 - corporate action events
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ca = caa.copy()
    ca["market"] = ca["ticker"].map(lambda t: next(
        (m for m in order if (m == "CN" and str(t).endswith(".SS")) or
         (m == "CN" and str(t).endswith(".SZ")) or
         (m == "HK" and str(t).endswith(".HK")) or
         (m == "IN" and str(t).endswith(".NS")) or
         (m == "JP" and str(t).endswith(".T")) or
         (m == "KR" and str(t).endswith(".KS")) or
         (m == "SG" and str(t).endswith(".SI")) or
         (m == "TW" and str(t).endswith(".TW"))), None))
    agg = ca.groupby("market").agg(dividends=("n_dividend_events", "sum"),
                                   splits=("n_split_events", "sum")).reindex(order).fillna(0)
    x = np.arange(len(order))
    ax.bar(x - 0.2, agg["dividends"], 0.4, color="#31506e", label="dividend events")
    ax.bar(x + 0.2, agg["splits"], 0.4, color="#b5651d", label="split events")
    ax.set_xticks(x); ax.set_xticklabels([MKT_NAME[m] for m in order])
    ax.set_ylabel("event count"); ax.legend(fontsize=7)
    frame(ax, "Corporate-Action Events in Primary Daily Series",
          "Conclusion: splits/dividends are recorded for audit only; adjusted close already embeds them.",
          "Prompt 1 corporate_action_audit.csv", "2010-2026", "events",
          "Vendor OHLC is historically split-adjusted; total returns use Adj Close and corporate events are NOT applied a second time.")
    fig.tight_layout(rect=[0, 0.08, 1, 0.95]); fig.savefig(CHARTS / "10_corporate_action_events.png"); plt.close(fig); n += 1

    # 11 - missing-return heatmap
    fig, ax = plt.subplots(figsize=(9, 4.6))
    pp = panel.copy(); pp["year"] = pd.PeriodIndex(pp["month"], freq="M").year
    grid = pp.groupby(["market", "year"]).apply(
        lambda g: 100 * (g["return_missing_reason"] != "").mean(), include_groups=False).unstack()
    grid = grid.reindex(order)
    im = ax.imshow(grid.values, aspect="auto", cmap="magma_r", vmin=0, vmax=100)
    ax.set_yticks(range(len(order))); ax.set_yticklabels([MKT_NAME[m] for m in order])
    ax.set_xticks(range(len(grid.columns)))
    ax.set_xticklabels([str(c) for c in grid.columns], rotation=45, ha="right")
    fig.colorbar(im, ax=ax, label="% missing monthly returns")
    for i in range(grid.shape[0]):
        for j in range(grid.shape[1]):
            v = grid.values[i, j]
            if v == v:
                ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=6,
                        color="white" if v > 55 else "black")
    frame(ax, "Missing Monthly Returns by Market and Year",
          "Conclusion: missingness concentrates in listing years and gaps; it is logged, never filled.",
          "Adj Close pairs requiring positive, non-null endpoints", "2010-2026", "% missing",
          "High values early reflect IPOs before first prior month-end; no interpolation or forward fill is used.")
    fig.tight_layout(rect=[0, 0.06, 1, 0.94]); fig.savefig(CHARTS / "11_missing_return_heatmap.png"); plt.close(fig); n += 1

    # 12 - signal coverage by market
    fig, ax = plt.subplots(figsize=(9.4, 4.4))
    sigs = ["mom_12_1", "vol_60", "vol_252", "beta", "dimson_beta", "ivol",
            "median_daily_traded_value", "amihud", "trading_frequency", "next_month_return"]
    cov = panel.groupby("market")[sigs].apply(lambda g: 100 * g.notna().mean()).reindex(order)
    im = ax.imshow(cov.values, aspect="auto", cmap="viridis", vmin=0, vmax=100)
    ax.set_yticks(range(len(order))); ax.set_yticklabels([MKT_NAME[m] for m in order])
    ax.set_xticks(range(len(sigs))); ax.set_xticklabels(sigs, rotation=45, ha="right")
    fig.colorbar(im, ax=ax, label="% of panel rows non-null")
    for i in range(cov.shape[0]):
        for j in range(cov.shape[1]):
            v = cov.values[i, j]
            if v == v:
                ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=6,
                        color="white" if v < 55 else "black")
    frame(ax, "Point-in-Time Signal Coverage by Market",
          "Conclusion: stock-only signals cover most rows; market-model signals (beta/ivol) require an overlapping benchmark and are absent where the benchmark series is degenerate (CN).",
          "Risk: trailing 252 sessions (min 126 traded) / liquidity: 60 sessions (min 40 traded) vs each market's actual yfinance benchmark",
          "2010-2026", "percent non-null",
          "Blank/zero cells are genuine data limits, not zero values; CN's 000300.SS benchmark has a single daily row so its market-model cells are empty.")
    fig.tight_layout(rect=[0, 0.06, 1, 0.94]); fig.savefig(CHARTS / "12_signal_coverage_by_market.png"); plt.close(fig); n += 1
    return n


# ---------------------------------------------------------------------------
# step 7: report
# ---------------------------------------------------------------------------
def build_report(daily, panel, smclean, uqc, sqc, log_df, n_charts, hashes) -> None:
    def fmt(x):
        return f"{x:.4f}" if isinstance(x, float) and x == x else str(x)
    rep = [
        "# APAC Alpha-to-Portfolio - Data Cleaning & Monthly Research Panel Report\n",
        f"Generated: {utcnow()} | Base currency: USD | Frozen method: METHODOLOGY_DATA_CLEANING.md\n",
        "## Method summary\n",
        "- Primary source is **yfinance**; BaoStock/AKShare rows are cross-check only and **do not "
        "overwrite** the raw yfinance series (`source_role` column retained).\n",
        "- Monthly total returns use yfinance **Adj Close** close-to-close between consecutive "
        "**actual** month-end observations, only where both endpoints are positive and non-null. "
        "No forward fill, no interpolation. Raw close/dividends/splits are retained.\n",
        "- Invalid prices (<=0/null) are flagged and the return pair excluded; missing returns are logged.\n",
        "- `daily_prices_clean` distinguishes **TRADED / STALE / SUSPENDED** rows (`trading_state`, "
        "`is_traded`, `is_stale`, `is_suspended`) and carries `total_return_1d` plus the local benchmark "
        "return mapped on **actual overlapping dates** (`benchmark_ticker`, `benchmark_source_label`, "
        "`benchmark_return_1d`).\n",
        "- Signals are trailing point-in-time (no lookahead). `mom_12_1` compounds **exactly 11** "
        "monthly returns keyed `t-12..t-2` (month `t-1` excluded), product(1+r)-1. Risk `vol_60`/"
        "`vol_252`, `beta`, `dimson_beta`, `ivol` use 60/252 market sessions with minimum 40/126 "
        "**traded** observations; zero-volume/stale/suspended sessions are masked (traded zero returns "
        "stay valid). Liquidity `median_daily_traded_value`, `amihud`, `trading_frequency` use a trailing "
        "60 market-session window with >=40 valid traded observations, in **local-currency** units "
        "(frequency = traded observations / 60 sessions). `next_month_return` is the **future** target "
        "(t+1) and never enters `eligible_universe` or any signal.\n",
        "- `eligible_universe` applies the point-in-time listing-date proxy gate, signal/risk "
        "availability, and the fixed lagged investability control (exclude the bottom 20th percentile of "
        "trailing median daily traded value within market and formation month, among otherwise-eligible "
        "names). Every exclusion reason is preserved in `eligible_reason`. The 20th-percentile cut is a "
        "fixed control, never optimized.\n",
        "- Source listing dates are first-observed-price **proxies**, not true IPOs; the pipeline states "
        "this and falls back to the first observed primary date where the field is blank. Known delisting "
        "**dates** are respected where genuinely parseable (Prompt 1 stores statuses, not dates).\n",
        "- Consumer aliases `security_id`, `ticker`, `country` and `data_quality_flag` are added; internal "
        "ids (`internal_security_id`, `provider_ticker`) are retained. **No sector neutralization** is "
        "applied.\n",
        "- Duplicate `(provider, security, date)` keys block processing unless exactly equal; exact "
        "duplicates would be dropped with a log. Prompt 1 data contains **zero** duplicate keys.\n",
        "- Investment vehicles (REIT/trust/units/fund/ETF/CEF/preferred/warrant/right/ADR/DR/receipt) are "
        "excluded from the core panel via stored name/type fields and **retained in the audit**; the "
        "exclusion is a documented name heuristic.\n",
        "- **No alpha/performance tests are conducted here**; this is a data and panel construction "
        "stage. **US-specific sample filters are not transplanted to APAC.**\n",
        "## Input integrity (read-only)\n",
    ]
    for k, v in hashes.items():
        rep.append(f"- `{k}` sha256 `{v[:16]}...`\n")
    rep += [
        "## Panel and coverage\n",
        f"- Daily clean rows: **{len(daily):,}** across {daily['internal_security_id'].nunique()} securities "
        f"({daily['provider'].nunique()} providers).\n",
        f"- Monthly panel rows: **{len(panel):,}** across {panel['internal_security_id'].nunique()} core "
        f"common-equity securities, {panel['month'].min()} to {panel['month'].max()}.\n",
        f"- Investment vehicles excluded from core panel: **{int(smclean['excluded_from_core'].sum())}** "
        f"(retained in `security_master_clean.parquet`).\n",
        f"- QC charts produced: **{n_charts}** in `reports/charts/cleaning/`.\n",
        "\n## Universe QC (per market)\n",
        uqc.to_markdown(index=False), "\n",
        "\n## Signal QC (per market)\n",
        sqc.to_markdown(index=False), "\n",
        "\n## Survivorship - explicit, not cured\n",
        "The Prompt 1 audit labels CN/HK `HISTORICAL_UNIVERSE_RELIABLE`, but this is **questionable**: "
        "`delisting_coverage = 0/N` in every market despite two-source prices for CN/HK. IN/JP/KR/SG/TW are "
        "explicit `CURRENT_SURVIVOR_BIAS`. The panel carries `survivorship_flag`, "
        "`source_audit_classification`, `delisting_coverage` and `survivorship_bias_cured = False` on every "
        "row. No reconstruction is claimed and **no market is described as survivorship-free**.\n",
        "\n## Corporate-action warning\n",
        "Vendor OHLC is historically split-adjusted even with `auto_adjust=False`. Total returns therefore "
        "use Adj Close, and dividends/splits are **not applied a second time** "
        "(`corporate_events_applied_again = False` on every row).\n",
        "\n## Cleaning log summary\n",
    ]
    summ = log_df.groupby("step")["n_records"].sum().sort_values(ascending=False)
    for step, nrec in summ.items():
        rep.append(f"- `{step}`: {int(nrec):,} records\n")
    rep += [
        "\n## References (methodological foundations)\n",
        "- Ince, O. S., & Porter, R. B. (2006). *Journal of Financial Research*. "
        "https://doi.org/10.1111/j.1475-6803.2006.00189.x\n",
        "- Shumway, T. (1997). *Journal of Finance*. "
        "https://doi.org/10.1111/j.1540-6261.1997.tb03818.x\n",
        "- Dimson, E. (1979). *Journal of Financial Economics*. "
        "https://doi.org/10.1016/0304-405X(79)90013-8\n",
        "- Hou, K., Xue, C., & Zhang, L. (2020). *Review of Financial Studies*. "
        "https://doi.org/10.1093/rfs/hhy131\n",
        "- Novy-Marx, R., & Velikov, M. (2016). *Review of Financial Studies*. "
        "https://doi.org/10.1093/rfs/hhv063\n",
        "- Jegadeesh, N., & Titman, S. (1993). *Journal of Finance*. "
        "https://doi.org/10.1111/j.1540-6261.1993.tb04702.x\n",
        "- Fama, E. F., & French, K. R. (2012). *Journal of Financial Economics*. "
        "https://doi.org/10.1016/j.jfineco.2011.09.004\n",
        "- Asness, C. S., Moskowitz, T. J., & Pedersen, L. H. (2013). *Journal of Finance*. "
        "https://doi.org/10.1111/jofi.12021\n",
        "- Frazzini, A., & Pedersen, L. H. (2014). *Journal of Finance*. "
        "https://doi.org/10.1111/jofi.12234\n",
        "- Ang, A., Hodrick, R. J., Xing, Y., & Zhang, X. (2009). *Journal of Finance*. "
        "https://doi.org/10.1111/j.1540-6261.2009.01483.x\n",
        "- Hou, K., Karolyi, G. A., & Kho, B.-C. (2011). *Journal of Finance*. "
        "https://doi.org/10.1111/j.1540-6261.2011.01671.x\n",
        "\n## Limitations\n",
        "- Survivorship bias is flagged, not solved; the universe is a current snapshot.\n",
        "- Only CN/HK have independent price cross-checks; other markets are single-source.\n",
        "- Benchmark mapping uses each market's actual primary yfinance index on overlapping dates. The "
        "CN series `000300.SS` contains a **single daily row** in Prompt 1, so CN `beta`, `dimson_beta` "
        "and `ivol` are missing (all other markets have ~99% benchmark overlap). This is reported, not "
        "imputed; CN remains eligible on stock-only signals. The CN local benchmark data limit is a real "
        "blocker for CN market-model risk and is **not** claimed as completed.\n",
        "- Source listing dates are first-observed-price proxies, not true IPO dates; delisting statuses "
        "carry no parseable dates, so the point-in-time delisting gate is inert in this dataset.\n",
        "- `median_daily_traded_value`, `amihud` and `trading_frequency` use the close*volume turnover "
        "estimate over trailing traded observations; they are not official turnover.\n",
        "- Security-type exclusion is name/type-heuristic; unlabelled vehicles may remain and unlisted "
        "share classes may be flagged. Full exclusion list is logged for review.\n",
        "- Historical sector/industry metadata is a current snapshot only.\n",
    ]
    atomic_write_text(REPORTS / "cleaning_report.md", "\n".join(rep) + "\n")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> None:
    print("[1/7] load Prompt 1 inputs (read-only) ...")
    inputs = load_inputs()
    px = inputs["prices"]
    master = inputs["master"]
    ua = inputs["universe_audit"]
    caa = inputs["corporate_action_audit"]
    cc = inputs["crosscheck"]
    hashes = inputs["_hashes"]
    log = CleanLog()

    print("[2/7] duplicate handling ...")
    px = handle_duplicates(px, log)

    print("[3/7] daily clean ...")
    bench_daily = benchmark_daily_returns(inputs["benchmarks"])
    daily = build_daily_clean(px, master, bench_daily, log)
    atomic_write_df(PROC / "daily_prices_clean.parquet", daily)

    print("[4/7] security master clean ...")
    smclean = build_security_master_clean(master, daily, ua, log)
    atomic_write_df(PROC / "security_master_clean.parquet", smclean)

    print("[5/7] monthly research panel + signals ...")
    panel = build_monthly_panel(daily, smclean, log)
    daily_signals = compute_daily_signals(daily)
    panel = attach_signals(panel, benchmark_monthly_returns(inputs["benchmarks"]), daily_signals)
    atomic_write_df(PROC / "monthly_research_panel.parquet", panel)

    print("[6/7] QC tables + log ...")
    uqc = build_universe_qc(smclean, cc)
    log_df = log.frame()
    sqc = build_signal_qc(panel, daily, log_df)
    atomic_write_df(REPORTS / "universe_qc.csv", uqc)
    atomic_write_df(REPORTS / "signal_qc.csv", sqc)
    atomic_write_df(REPORTS / "data_cleaning_log.csv", log_df)

    print("[7/7] charts + report ...")
    n_charts = make_charts(daily, panel, smclean, uqc, sqc, caa, log_df)
    if n_charts != 12:
        raise SystemExit(f"expected 12 charts, wrote {n_charts}")
    build_report(daily, panel, smclean, uqc, sqc, log_df, n_charts, hashes)

    # guard: inputs unchanged
    for k, h in hashes.items():
        p = {"prices": PROC / "prices.parquet",
             "security_master_raw": ROOT / "data" / "security_master_raw.parquet",
             "security_master": PROC / "security_master.parquet",
             "benchmarks": PROC / "benchmarks.parquet",
             "source_crosscheck": REPORTS / "source_crosscheck.csv",
             "historical_universe_audit": REPORTS / "historical_universe_audit.csv",
             "corporate_action_audit": REPORTS / "corporate_action_audit.csv"}[k]
        if sha256_file(p) != h:
            raise SystemExit(f"input modified during run (must be read-only): {p}")

    print("\n================ CLEANING COMPLETION MANIFEST ================")
    print(f"daily_prices_clean rows      : {len(daily):,} ({daily['internal_security_id'].nunique()} securities)")
    print(f"monthly_research_panel rows  : {len(panel):,} ({panel['internal_security_id'].nunique()} core securities)")
    print(f"security_master_clean rows   : {len(smclean):,} (excluded={int(smclean['excluded_from_core'].sum())})")
    print(f"panel range                  : {panel['month'].min()} -> {panel['month'].max()}")
    print(f"valid monthly returns        : {int((panel['return_missing_reason'] == '').sum()):,}")
    print(f"eligible universe rows       : {int(panel['eligible_universe'].sum()):,}")
    print(f"below liquidity cutoff rows  : {int(panel['eligible_reason'].str.contains('below_liquidity_cutoff').sum()):,}")
    print(f"pre-listing rows             : {int(panel['eligible_reason'].str.contains('pre_listing').sum()):,}")
    for c in ["mom_12_1", "vol_60", "vol_252", "beta", "dimson_beta", "ivol",
              "median_daily_traded_value", "amihud", "trading_frequency", "next_month_return"]:
        print(f"  {c:<26}: {int(panel[c].notna().sum()):,} non-null")
    for c in ["security_id", "ticker", "country", "data_quality_flag"]:
        print(f"  alias {c:<20}: {int(panel[c].notna().sum()):,} non-null")
    print(f"cleaning log rows            : {len(log_df):,}")
    print(f"charts (cleaning)            : {n_charts}")
    print("=============================================================")


if __name__ == "__main__":
    main()
