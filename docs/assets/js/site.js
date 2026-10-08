/* APAC Alpha-to-Portfolio microsite — interactive chart layer.
   Renders ONLY precomputed data from window.SITE_DATA (canonical recorded outputs).
   No network, no new tests/models, no browser recomputation of empirical tests. */
(function () {
  "use strict";

  var DATA = window.SITE_DATA || {};
  var FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
  var PCFG = { responsive: true, displaylogo: false,
    modeBarButtonsToRemove: ["lasso2d", "select2d", "hoverClosestCartesian", "hoverCompareCartesian"] };

  var PORT = {
    "Benchmark": "#8a94a6",
    "1/N": "#0d6ea8",
    "Momentum": "#0b3d5c",
    "Low Risk": "#0f8f86",
    "Composite": "#6b8fb5",
    "Optimized": "#c08a3e"
  };
  var PORT_ORDER = ["Benchmark", "1/N", "Momentum", "Low Risk", "Composite", "Optimized"];
  var STRAT_ORDER = ["1/N", "Momentum", "Low Risk", "Composite", "Optimized"];
  var MARKETS = ["CN", "HK", "IN", "JP", "KR", "SG", "TW"];
  var SIGNAL_LABEL = {
    mom: "MOM 12-1", lowrisk: "LOWRISK (\u2212vol_60)", vol252: "vol_252", beta: "BETA", ivol: "IVOL"
  };
  var SITC = { 1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4", 5: "Q5" };
  var COLORWAY = ["#0d6ea8", "#0b3d5c", "#0f8f86", "#6b8fb5", "#c08a3e", "#8a94a6", "#7a5c9e"];

  // ---------------------------------------------------------------- helpers
  function pct(x, d) { d = d == null ? 1 : d; return x == null ? "\u2014" : (x * 100).toFixed(d) + "%"; }
  function f2(x) { return x == null ? "\u2014" : Number(x).toFixed(2); }
  function f3(x) { return x == null ? "\u2014" : Number(x).toFixed(3); }
  function uniq(arr) { var s = []; arr.forEach(function (v) { if (s.indexOf(v) < 0) s.push(v); }); return s; }

  function makeSelect(container, labelText, options, value, onChange) {
    var label = document.createElement("label");
    label.appendChild(document.createTextNode(labelText));
    var sel = document.createElement("select");
    options.forEach(function (o) {
      var opt = document.createElement("option");
      opt.value = o.value; opt.textContent = o.label;
      if (o.value === value) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.addEventListener("change", function () { onChange(sel.value); });
    label.appendChild(sel);
    container.appendChild(label);
    return sel;
  }

  function baseLayout(extra) {
    var base = {
      margin: { l: 64, r: 20, t: 34, b: 56 },
      paper_bgcolor: "#ffffff", plot_bgcolor: "#ffffff",
      font: { family: FONT, size: 12, color: "#1e2d45" },
      colorway: COLORWAY,
      legend: { orientation: "h", y: -0.28, x: 0, bgcolor: "rgba(0,0,0,0)" },
      xaxis: { automargin: true, gridcolor: "#eef2f7", zerolinecolor: "#dfe5ee" },
      yaxis: { automargin: true, gridcolor: "#eef2f7", zerolinecolor: "#dfe5ee" },
      hoverlabel: { font: { family: FONT, size: 12 } }
    };
    if (extra) for (var k in extra) base[k] = extra[k];
    return base;
  }

  function draw(node, traces, layout, scrollZoom) {
    var plot = node.querySelector(".plot");
    var cfg = Object.assign({}, PCFG, { scrollZoom: !!scrollZoom });
    if (typeof Plotly === "undefined") {
      plot.textContent = "Charts require the bundled Plotly library.";
      return;
    }
    Plotly.newPlot(plot, traces, layout, cfg);
  }

  // ---------------------------------------------------------------- registry
  var CHARTS = {};

  // 1. sample coverage ------------------------------------------------------
  CHARTS.coverage = function (node) {
    var controls = node.querySelector(".chart-controls");
    var metric = "n_eligible";
    var metrics = [
      ["n_eligible", "Eligible names"], ["n_securities", "Core securities"],
      ["n_obs_months", "Observation months"], ["n_below_liquidity_cutoff", "Below liquidity cutoff"],
      ["n_mom_12_1", "MOM coverage"], ["n_vol_60", "vol_60 coverage"]
    ];
    var label = function (m) { for (var i = 0; i < metrics.length; i++) if (metrics[i][0] === m) return metrics[i][1]; return m; };
    makeSelect(controls, "Metric", metrics.map(function (m) { return { value: m[0], label: m[1] }; }), metric, function (v) { metric = v; onChange(); });
    function onChange() { node.dataset.rendered = "1"; render(); }
    function render() {
      var rows = DATA.coverage || [];
      draw(node, [{
        type: "bar", x: rows.map(function (r) { return r.market; }), y: rows.map(function (r) { return r[metric]; }),
        marker: { color: PORT["1/N"] }, text: rows.map(function (r) { return String(r[metric]); }),
        textposition: "outside",
        hovertemplate: "%{x}<br>" + label(metric) + ": %{y}<extra></extra>"
      }], baseLayout({ yaxis: { title: { text: label(metric) }, automargin: true, gridcolor: "#eef2f7" } }));
    }
    return render;
  };

  // 2. IC -------------------------------------------------------------------
  CHARTS.ic = function (node) {
    var controls = node.querySelector(".chart-controls");
    var scope = "Aggregate", signal = "mom", market = "All";
    var sigSel, mktSel;
    makeSelect(controls, "Scope", [{ value: "Aggregate", label: "Aggregate (APAC)" }, { value: "Country", label: "By country" }], scope, function (v) { scope = v; sync(); });
    sigSel = makeSelect(controls, "Signal", ["mom", "lowrisk", "vol252", "beta", "ivol"].map(function (s) { return { value: s, label: SIGNAL_LABEL[s] }; }), signal, function (v) { signal = v; onChange(); });
    mktSel = makeSelect(controls, "Market", [{ value: "All", label: "All markets" }].concat(MARKETS.map(function (m) { return { value: m, label: m }; })), market, function (v) { market = v; onChange(); });
    function sync() { mktSel.disabled = scope === "Aggregate"; onChange(); }
    mktSel.disabled = scope === "Aggregate";
    function onChange() { node.dataset.rendered = "1"; render(); }
    function render() {
      var trace, layout;
      if (scope === "Aggregate") {
        var rows = (DATA.ic.pooled || []).filter(function (r) { return r.signal === signal; });
        trace = {
          type: "bar", x: rows.map(function () { return "APAC (country-equal)"; }), y: rows.map(function (r) { return r.avg_ic; }),
          marker: { color: PORT["1/N"] },
          customdata: rows.map(function (r) { return [r.icir, r.pos_freq, r.months, r.avg_n]; }),
          hovertemplate: "APAC<br>Mean IC: %{y:.4f}<br>ICIR: %{customdata[0]:.3f}<br>Positive months: %{customdata[1]:.1%}<br>Months: %{customdata[2]}<br>Avg N: %{customdata[3]:.1f}<extra></extra>"
        };
      } else {
        var rows2 = (DATA.ic.by_country || []).filter(function (r) { return r.signal === signal && (market === "All" || r.market === market); });
        if (market !== "All") rows2 = rows2.slice(0, 1);
        trace = {
          type: "bar", x: rows2.map(function (r) { return r.market; }), y: rows2.map(function (r) { return r.avg_ic; }),
          marker: { color: PORT["1/N"] },
          customdata: rows2.map(function (r) { return [r.icir, r.pos_freq, r.months, r.avg_n]; }),
          hovertemplate: "%{x}<br>Mean IC: %{y:.4f}<br>ICIR: %{customdata[0]:.3f}<br>Positive months: %{customdata[1]:.1%}<br>Months: %{customdata[2]}<br>Avg N: %{customdata[3]:.1f}<extra></extra>"
        };
      }
      layout = baseLayout({ yaxis: { title: { text: "Mean monthly rank IC" }, automargin: true, gridcolor: "#eef2f7", zeroline: true, zerolinecolor: "#8a94a6" }, showlegend: false });
      draw(node, [trace], layout);
    }
    return render;
  };

  // 3. quintiles ------------------------------------------------------------
  CHARTS.quintiles = function (node) {
    var controls = node.querySelector(".chart-controls");
    var signal = "mom", market = "JP";
    makeSelect(controls, "Signal", ["mom", "lowrisk", "vol252"].map(function (s) { return { value: s, label: SIGNAL_LABEL[s] }; }), signal, function (v) { signal = v; onChange(); });
    makeSelect(controls, "Market", MARKETS.map(function (m) { return { value: m, label: m }; }), market, function (v) { market = v; onChange(); });
    function onChange() { node.dataset.rendered = "1"; render(); }
    function render() {
      var rows = (DATA.quintiles[signal] || []).filter(function (r) { return r.market === market; });
      var q = rows.filter(function (r) { return SITC[r.quintile]; }).sort(function (a, b) { return a.quintile - b.quintile; });
      var spread = rows.filter(function (r) { return r.quintile === "Q5-Q1"; })[0];
      var vals = q.map(function (r) { return r.mean; });
      draw(node, [{
        type: "bar", x: q.map(function (r) { return SITC[r.quintile]; }), y: vals.map(function (v) { return v * 100; }),
        marker: { color: PORT["1/N"] },
        customdata: q.map(function (r) { return [r.mean, r.ann_geom, r.vol]; }),
        hovertemplate: "%{x}<br>Mean monthly: %{customdata[0]:.2%}<br>Annualised geom: %{customdata[1]:.1%}<br>Vol: %{customdata[2]:.1%}<extra></extra>"
      }], baseLayout({
        showlegend: false, yaxis: { title: { text: "Mean monthly USD return (%)" }, automargin: true, gridcolor: "#eef2f7", zeroline: true, zerolinecolor: "#8a94a6" },
        annotations: spread ? [{ x: 0.5, y: 1.02, xref: "paper", yref: "paper", yanchor: "bottom", showarrow: false, font: { size: 12, color: "#5b6b82" },
          text: market + " Q5\u2212Q1 = " + pct(spread.q5_minus_q1_mean, 2) + "/mo" }] : []
      }));
    }
    return render;
  };

  // 4. Fama-MacBeth ---------------------------------------------------------
  CHARTS.fm = function (node) {
    var controls = node.querySelector(".chart-controls");
    var model = "Pooled", reg = "mom_z", signal = "mom", market = "All";
    var regSel, sigSel, mktSel;
    makeSelect(controls, "Model", [{ value: "Pooled", label: "Pooled" }, { value: "Country", label: "By country" }], model, function (v) { model = v; sync(); });
    regSel = makeSelect(controls, "Regressor", ["mom_z", "lowrisk_z", "lagret_z", "logliq_z"].map(function (r) { return { value: r, label: r }; }), reg, function (v) { reg = v; onChange(); });
    sigSel = makeSelect(controls, "Signal", [{ value: "mom", label: "MOM" }, { value: "lowrisk", label: "LOWRISK" }], signal, function (v) { signal = v; onChange(); });
    mktSel = makeSelect(controls, "Market", [{ value: "All", label: "All markets" }].concat(MARKETS.map(function (m) { return { value: m, label: m }; })), market, function (v) { market = v; onChange(); });
    function sync() {
      var pooled = model === "Pooled";
      regSel.disabled = !pooled; sigSel.disabled = pooled; mktSel.disabled = pooled;
      onChange();
    }
    regSel.disabled = false; sigSel.disabled = true; mktSel.disabled = true;
    function onChange() { node.dataset.rendered = "1"; render(); }
    function render() {
      var rows, labels;
      if (model === "Pooled") {
        rows = (DATA.fm.pooled || []).filter(function (r) { return r.regressor === reg; });
        labels = rows.map(function () { return reg; });
      } else {
        rows = (DATA.fm.by_country || []).filter(function (r) { return r.signal === signal && (market === "All" || r.market === market); });
        labels = rows.map(function (r) { return r.market; });
      }
      var coef = rows.map(function (r) { return r.mean_slope; });
      var ci = rows.map(function (r) { return Math.abs(r.mean_slope / r.nw_t) * 1.96; });
      draw(node, [{
        type: "bar", x: labels, y: coef, marker: { color: PORT["1/N"] },
        error_y: { type: "data", array: ci, visible: true, color: "#5b6b82", thickness: 1.2, width: 4 },
        customdata: rows.map(function (r) { return [r.nw_t, r.valid_months, r.avg_n]; }),
        hovertemplate: "%{x}<br>Mean slope: %{y:.4f}<br>NW HAC(6) t: %{customdata[0]:.2f}<br>Valid months: %{customdata[1]}<br>Avg N: %{customdata[2]:.1f}<extra></extra>"
      }], baseLayout({
        showlegend: false,
        yaxis: { title: { text: "Mean monthly slope (per 1 SD)" }, automargin: true, gridcolor: "#eef2f7", zeroline: true, zerolinecolor: "#8a94a6" },
        annotations: [{ x: 0, y: 1.02, xref: "paper", yref: "paper", yanchor: "bottom", xanchor: "left", showarrow: false, font: { size: 11, color: "#5b6b82" },
          text: "Error bars = approx. NW 95% CI" }]
      }));
    }
    return render;
  };

  // 5. JKP ------------------------------------------------------------------
  CHARTS.jkp = function (node) {
    var controls = node.querySelector(".chart-controls");
    var signal = "momentum", metric = "corr", horizon = "Full", market = "All";
    var hzSel, mktSel;
    makeSelect(controls, "Signal", [{ value: "momentum", label: "Momentum" }, { value: "low_risk", label: "Low Risk" }], signal, function (v) { signal = v; onChange(); });
    makeSelect(controls, "Metric", [{ value: "corr", label: "Correlation" }, { value: "sign_agree", label: "Sign agreement" }], metric, function (v) { metric = v; sync(); });
    hzSel = makeSelect(controls, "Horizon", [{ value: "Full", label: "Full (n=178)" }, { value: "Pre", label: "Pre-2020" }, { value: "Post", label: "Post-2020" }], horizon, function (v) { horizon = v; onChange(); });
    mktSel = makeSelect(controls, "Market", [{ value: "All", label: "All markets" }].concat(MARKETS.map(function (m) { return { value: m, label: m }; })), market, function (v) { market = v; onChange(); });
    function sync() { hzSel.disabled = metric === "sign_agree"; onChange(); }
    hzSel.disabled = metric === "sign_agree";
    function onChange() { node.dataset.rendered = "1"; render(); }
    function render() {
      var field = metric === "sign_agree" ? "sign_agree" : (horizon === "Pre" ? "pre2020_corr" : horizon === "Post" ? "post2020_corr" : "corr");
      var rows = (DATA.jkp[signal] || []).filter(function (r) { return market === "All" || r.market === market; });
      draw(node, [{
        type: "bar", x: rows.map(function (r) { return r.market; }), y: rows.map(function (r) { return r[field]; }),
        marker: { color: signal === "momentum" ? PORT["Momentum"] : PORT["Low Risk"] },
        customdata: rows.map(function (r) { return [r.n, r.corr, r.pre2020_corr, r.post2020_corr, r.sign_agree]; }),
        hovertemplate: "%{x}<br>Value: %{y:.3f}<br>Full corr: %{customdata[1]:.3f}<br>Pre-2020: %{customdata[2]:.3f}<br>Post-2020: %{customdata[3]:.3f}<br>Sign agree: %{customdata[4]:.1%}<br>n: %{customdata[0]}<extra></extra>"
      }], baseLayout({
        showlegend: false, yaxis: { title: { text: metric === "sign_agree" ? "Sign agreement" : "Correlation" },
          automargin: true, gridcolor: "#eef2f7", zeroline: true, zerolinecolor: "#8a94a6" }
      }));
    }
    return render;
  };

  // 6. wealth ---------------------------------------------------------------
  CHARTS.wealth = function (node) {
    var controls = node.querySelector(".chart-controls");
    var scale = "Linear";
    makeSelect(controls, "Y scale", [{ value: "Linear", label: "Linear" }, { value: "Log", label: "Log" }], scale, function (v) { scale = v; onChange(); });
    function onChange() { node.dataset.rendered = "1"; render(); }
    function render() {
      var o = DATA.oos, traces = [];
      PORT_ORDER.forEach(function (p) {
        var w, rets, status;
        if (p === "Benchmark") { w = o.wealth_benchmark; rets = o.benchmark; status = "uncharged"; }
        else { w = o.wealth[p]; rets = o.net[p]; status = "net of 15 bps + dated taxes"; }
        if (!w) return;
        traces.push({
          type: "scatter", mode: "lines", name: p, x: o.months, y: w,
          line: { color: PORT[p], width: p === "Benchmark" ? 1.4 : 1.8, dash: p === "Benchmark" ? "dot" : "solid" },
          customdata: rets,
          hovertemplate: "%{x}<br>" + p + "<br>Monthly: %{customdata:.2%}<br>Wealth: %{y:.3f}<br>" + status + "<extra></extra>"
        });
      });
      draw(node, traces, baseLayout({
        yaxis: { title: { text: "Cumulative wealth (start = 1.0)" }, type: scale === "Log" ? "log" : "linear", automargin: true, gridcolor: "#eef2f7" },
        annotations: [{ x: 0, y: 1.02, xref: "paper", yref: "paper", yanchor: "bottom", xanchor: "left", showarrow: false, font: { size: 11, color: "#5b6b82" },
          text: "OOS 2016-01..2026-09; 2026 partial" }]
      }));
    }
    return render;
  };

  // 7. drawdown -------------------------------------------------------------
  CHARTS.drawdown = function (node) {
    var controls = node.querySelector(".chart-controls");
    var includeBench = "Yes";
    makeSelect(controls, "Benchmark", [{ value: "Yes", label: "Include" }, { value: "No", label: "Hide" }], includeBench, function (v) { includeBench = v; onChange(); });
    function onChange() { node.dataset.rendered = "1"; render(); }
    function render() {
      var o = DATA.oos, traces = [];
      STRAT_ORDER.forEach(function (p) {
        traces.push({ type: "scatter", mode: "lines", name: p, x: o.months, y: o.drawdown[p],
          line: { color: PORT[p], width: 1.6 },
          hovertemplate: "%{x}<br>" + p + "<br>Drawdown: %{y:.2%}<extra></extra>" });
      });
      if (includeBench === "Yes") {
        traces.push({ type: "scatter", mode: "lines", name: "Benchmark", x: o.months, y: o.drawdown_benchmark,
          line: { color: PORT["Benchmark"], width: 1.4, dash: "dot" },
          hovertemplate: "%{x}<br>Benchmark (uncharged)<br>Drawdown: %{y:.2%}<extra></extra>" });
      }
      draw(node, traces, baseLayout({
        yaxis: { title: { text: "Drawdown" }, tickformat: ".0%", automargin: true, gridcolor: "#eef2f7" },
        annotations: [{ x: 0, y: 1.02, xref: "paper", yref: "paper", yanchor: "bottom", xanchor: "left", showarrow: false, font: { size: 11, color: "#5b6b82" },
          text: "Strategies net; benchmark uncharged" }]
      }));
    }
    return render;
  };

  // 8. metrics --------------------------------------------------------------
  CHARTS.metrics = function (node) {
    var controls = node.querySelector(".chart-controls");
    var metric = "NetReturn";
    var metrics = [
      ["NetReturn", "Net CAGR (NetReturn)"], ["Volatility", "Volatility"], ["Sharpe", "Sharpe"],
      ["MaxDrawdown", "Max drawdown"], ["Turnover", "Mean turnover"]
    ];
    var label = function (m) { for (var i = 0; i < metrics.length; i++) if (metrics[i][0] === m) return metrics[i][1]; return m; };
    makeSelect(controls, "Metric", metrics.map(function (m) { return { value: m[0], label: m[1] }; }), metric, function (v) { metric = v; onChange(); });
    function onChange() { node.dataset.rendered = "1"; render(); }
    function fmt(v) { return metric === "Sharpe" ? f2(v) : metric === "Turnover" ? f3(v) : pct(v, 1); }
    var isPct = function (m) { return m === "NetReturn" || m === "Volatility" || m === "MaxDrawdown"; };
    function render() {
      var h = DATA.headline_table || {};
      var rows = PORT_ORDER.filter(function (p) { return h[p]; });
      var vals = rows.map(function (p) { return h[p][metric]; });
      var yvals = vals.map(function (v) { return v == null ? null : (isPct(metric) ? v * 100 : v); });
      var finite = yvals.filter(function (v) { return v != null && isFinite(v); });
      var lo = Math.min.apply(null, finite.concat([0]));
      var hi = Math.max.apply(null, finite.concat([0]));
      var span = (hi - lo) || 1;
      // Outside labels need headroom beyond the tallest bar and below the deepest negative bar.
      var range = [lo - (lo < 0 ? span * 0.18 : 0), hi + (hi > 0 ? span * 0.18 : 0)];
      draw(node, [{
        type: "bar", x: rows, y: yvals,
        marker: { color: rows.map(function (p) { return PORT[p]; }) },
        customdata: vals, cliponaxis: false,
        hovertemplate: "%{x}<br>" + label(metric) + ": %{customdata}<extra></extra>",
        text: vals.map(fmt), textposition: "outside"
      }], baseLayout({
        showlegend: false,
        yaxis: { title: { text: label(metric) + (isPct(metric) ? " (%)" : "") }, automargin: true, gridcolor: "#eef2f7",
          rangemode: "tozero", range: range },
        annotations: [{ x: 0, y: 1.02, xref: "paper", yref: "paper", yanchor: "bottom", xanchor: "left", showarrow: false, font: { size: 11, color: "#5b6b82" },
          text: "Net of costs (NetReturn), not gross" }]
      }));
    }
    return render;
  };

  // 9. transaction cost -----------------------------------------------------
  CHARTS.cost = function (node) {
    var controls = node.querySelector(".chart-controls");
    var metric = "cagr";
    var metrics = [["cagr", "Net CAGR"], ["sharpe", "Sharpe"], ["vol", "Volatility"], ["max_dd", "Max drawdown"]];
    var label = function (m) { for (var i = 0; i < metrics.length; i++) if (metrics[i][0] === m) return metrics[i][1]; return m; };
    makeSelect(controls, "Metric", metrics.map(function (m) { return { value: m[0], label: m[1] }; }), metric, function (v) { metric = v; onChange(); });
    function onChange() { node.dataset.rendered = "1"; render(); }
    function render() {
      var rows = DATA.cost || [];
      var scen = ["gross", "cost_5bps", "cost_15bps", "cost_30bps"];
      var scenLabel = ["Gross", "5 bps", "15 bps", "30 bps"];
      var ports = uniq(rows.map(function (r) { return r.portfolio; }));
      var traces = ports.map(function (p) {
        var by = {}; rows.forEach(function (r) { if (r.portfolio === p) by[r.scenario] = r[metric]; });
        return { type: "scatter", mode: "lines+markers", name: p, x: scenLabel,
          y: scen.map(function (s) { return by[s] == null ? null : (metric === "sharpe" ? by[s] : by[s] * 100); }),
          line: { color: PORT[p] || "#555", width: 1.8 }, marker: { size: 7 },
          hovertemplate: "%{x}<br>" + p + "<br>" + label(metric) + ": %{y}<extra></extra>" };
      });
      draw(node, traces, baseLayout({
        xaxis: { automargin: true, gridcolor: "#eef2f7" },
        yaxis: { title: { text: label(metric) + (metric === "sharpe" ? "" : " (%)") }, automargin: true, gridcolor: "#eef2f7" },
        annotations: [{ x: 0, y: 1.02, xref: "paper", yref: "paper", yanchor: "bottom", xanchor: "left", showarrow: false, font: { size: 11, color: "#5b6b82" },
          text: "Illustrative; dated CN/HK taxes in" }]
      }));
    }
    return render;
  };

  // 10. turnover ------------------------------------------------------------
  CHARTS.turnover = function (node) {
    var controls = node.querySelector(".chart-controls");
    var pf = "Momentum";
    makeSelect(controls, "Portfolio", STRAT_ORDER.map(function (p) { return { value: p, label: p }; }), pf, function (v) { pf = v; onChange(); });
    function onChange() { node.dataset.rendered = "1"; render(); }
    function render() {
      var t = DATA.turnover || {};
      draw(node, [{
        type: "scatter", mode: "lines", name: pf, x: t.months, y: (t.series || {})[pf],
        line: { color: PORT[pf] || "#0d6ea8", width: 1.6 },
        hovertemplate: "%{x}<br>" + pf + "<br>One-way turnover: %{y:.1%}<extra></extra>"
      }], baseLayout({
        showlegend: false, yaxis: { title: { text: "One-way turnover (0.5\u00b7\u03a3|\u0394w|)" }, tickformat: ".0%", automargin: true, gridcolor: "#eef2f7" },
        annotations: [{ x: 0, y: 1.02, xref: "paper", yref: "paper", yanchor: "bottom", xanchor: "left", showarrow: false, font: { size: 11, color: "#5b6b82" },
          text: "Initial entry = 0.5; 2026 partial" }]
      }));
    }
    return render;
  };

  // 11. exposure / risk -----------------------------------------------------
  CHARTS.exposure = function (node) {
    var controls = node.querySelector(".chart-controls");
    var view = "weight";
    makeSelect(controls, "View", [{ value: "weight", label: "Average country weight" }, { value: "risk", label: "Risk contribution" }], view, function (v) { view = v; onChange(); });
    function onChange() { node.dataset.rendered = "1"; render(); }
    function render() {
      if (view === "risk") {
        var rc = DATA.risk_contribution || [];
        draw(node, [{
          type: "bar", x: rc.map(function (r) { return r.market; }), y: rc.map(function (r) { return r.risk_share * 100; }),
          marker: { color: PORT["1/N"] }, customdata: rc.map(function (r) { return r.sleeve_vol; }),
          hovertemplate: "%{x}<br>Risk share: %{y:.1f}%<br>Sleeve vol: %{customdata:.1%}<extra></extra>"
        }], baseLayout({
          showlegend: false, yaxis: { title: { text: "Risk share (%)" }, automargin: true, gridcolor: "#eef2f7" },
          annotations: [{ x: 0, y: 1.02, xref: "paper", yref: "paper", yanchor: "bottom", xanchor: "left", showarrow: false, font: { size: 11, color: "#5b6b82" },
            text: "From equal-country sleeve covariance" }]
        }));
      } else {
        var w = DATA.weights || [];
        var ports = uniq(w.map(function (r) { return r.portfolio; }));
        var traces = ports.map(function (p) {
          var by = {}; w.forEach(function (r) { if (r.portfolio === p) by[r.market] = r.avg_weight; });
          return { type: "bar", name: p, x: MARKETS, y: MARKETS.map(function (m) { return by[m] == null ? null : by[m] * 100; }),
            marker: { color: PORT[p] || "#555" }, hovertemplate: "%{x}<br>" + p + "<br>Average weight: %{y:.1f}%<extra></extra>" };
        });
        draw(node, traces, baseLayout({
          barmode: "group", yaxis: { title: { text: "Average country weight (%)" }, automargin: true, gridcolor: "#eef2f7" },
          annotations: [{ x: 0, y: 1.02, xref: "paper", yref: "paper", yanchor: "bottom", xanchor: "left", showarrow: false, font: { size: 11, color: "#5b6b82" },
            text: "Equal-country by construction" }]
        }));
      }
    }
    return render;
  };

  // 12. robustness explorer -------------------------------------------------
  CHARTS.robustness = function (node) {
    var controls = node.querySelector(".chart-controls");
    var rows = DATA.robustness || [];
    var fam = uniq(rows.map(function (r) { return r.family; }));
    var state = { family: fam[0], factor: "All", metric: "All", status: "All" };
    var facSel, metSel, staSel;
    makeSelect(controls, "Family", [{ value: "All", label: "All families" }].concat(fam.map(function (f) { return { value: f, label: f }; })), state.family, function (v) { state.family = v; sync(); });
    facSel = makeSelect(controls, "Factor", [{ value: "All", label: "All" }].concat(uniq(rows.map(function (r) { return r.factor; })).map(function (f) { return { value: f, label: f }; })), state.factor, function (v) { state.factor = v; onChange(); });
    metSel = makeSelect(controls, "Metric", [{ value: "All", label: "All" }].concat(uniq(rows.map(function (r) { return r.metric; })).map(function (m) { return { value: m, label: m }; })), state.metric, function (v) { state.metric = v; onChange(); });
    staSel = makeSelect(controls, "Status", [{ value: "All", label: "All" }, { value: "ok", label: "ok" }, { value: "na", label: "na" }], state.status, function (v) { state.status = v; onChange(); });
    function sync() { onChange(); }
    function onChange() { node.dataset.rendered = "1"; render(); }
    function render() {
      var f = rows.filter(function (r) {
        return (state.family === "All" || r.family === state.family) &&
          (state.factor === "All" || r.factor === state.factor) &&
          (state.metric === "All" || r.metric === state.metric) &&
          (state.status === "All" || r.status === state.status);
      });
      var cols = ["family", "variation", "factor", "group", "metric", "value", "status", "note"];
      var headers = ["Family", "Variation", "Factor", "Group", "Metric", "Value", "Status", "Note"];
      var values = cols.map(function (c) {
        return f.map(function (r) { return r[c] == null ? "" : String(r[c]); });
      });
      var height = Math.min(560, 90 + f.length * 22);
      draw(node, [{
        type: "table", header: { values: headers, fill: { color: "#eef2f7" }, align: "left", font: { size: 11 } },
        cells: { values: values, align: "left", height: 22, font: { size: 11 }, fill: { color: [f.length % 2 === 0 ? "#ffffff" : "#f6f8fb"] } }
      }], baseLayout({ margin: { l: 10, r: 10, t: 34, b: 10 }, height: height,
        annotations: [{ x: 0, y: 1.02, xref: "paper", yref: "paper", yanchor: "bottom", xanchor: "left", showarrow: false, font: { size: 11, color: "#5b6b82" },
          text: f.length + " of " + rows.length + " rows \u00b7 'na' = non-result" }] }));
    }
    return render;
  };

  // 13. annual heatmap ------------------------------------------------------
  CHARTS.annual = function (node) {
    var controls = node.querySelector(".chart-controls");
    controls.appendChild(Object.assign(document.createElement("p"), { className: "method-note", textContent: "2026* = 9-month partial year." }));
    function render() {
      var a = DATA.annual || {};
      var ports = PORT_ORDER.filter(function (p) { return a.net && a.net[p]; });
      var years = a.years.map(function (y) { return y === a.partial_year ? y + "*" : String(y); });
      // Plotly heatmap: x=ports, y=years -> z must be years (rows) x ports (cols).
      var z = a.years.map(function (y, i) {
        return ports.map(function (p) { var v = a.net[p][i]; return v == null ? null : v * 100; });
      });
      var text = z.map(function (row) { return row.map(function (v) { return v == null ? "" : v.toFixed(0); }); });
      draw(node, [{
        type: "heatmap", x: ports, y: years, z: z, text: text, texttemplate: "%{text}",
        textfont: { size: 10 },
        colorscale: [[0, "#b2182b"], [0.5, "#f7f7f7"], [1, "#2166ac"]], zmid: 0,
        colorbar: { title: { text: "Net return (%)", side: "right" }, thickness: 12 },
        hovertemplate: "%{y} \u00b7 %{x}<br>Net annual return: %{z:.1f}%<extra></extra>"
      }], baseLayout({ margin: { l: 60, r: 20, t: 34, b: 40 },
        xaxis: { type: "category", automargin: true, tickangle: -25 }, yaxis: { type: "category", automargin: true },
        annotations: [{ x: 0, y: 1.02, xref: "paper", yref: "paper", yanchor: "bottom", xanchor: "left", showarrow: false, font: { size: 11, color: "#5b6b82" },
          text: "Net of 15 bps + taxes; 2026* partial" }] }));
    }
    return render;
  };

  // 14. rolling 12m ---------------------------------------------------------
  CHARTS.rolling = function (node) {
    var controls = node.querySelector(".chart-controls");
    var includeBench = "Yes";
    makeSelect(controls, "Benchmark", [{ value: "Yes", label: "Include" }, { value: "No", label: "Hide" }], includeBench, function (v) { includeBench = v; onChange(); });
    function onChange() { node.dataset.rendered = "1"; render(); }
    function render() {
      var o = DATA.oos, traces = [];
      STRAT_ORDER.forEach(function (p) {
        traces.push({ type: "scatter", mode: "lines", name: p, x: o.months, y: o.rolling12[p],
          line: { color: PORT[p], width: 1.6 },
          hovertemplate: "%{x}<br>" + p + "<br>Trailing 12m net: %{y:.1%}<extra></extra>" });
      });
      if (includeBench === "Yes") {
        traces.push({ type: "scatter", mode: "lines", name: "Benchmark (uncharged)", x: o.months, y: o.rolling12_benchmark,
          line: { color: PORT["Benchmark"], width: 1.4, dash: "dot" },
          hovertemplate: "%{x}<br>Benchmark<br>Trailing 12m: %{y:.1%}<extra></extra>" });
      }
      draw(node, traces, baseLayout({
        yaxis: { title: { text: "Trailing 12-month net return" }, tickformat: ".0%", automargin: true, gridcolor: "#eef2f7" },
        annotations: [{ x: 0, y: 1.02, xref: "paper", yref: "paper", yanchor: "bottom", xanchor: "left", showarrow: false, font: { size: 11, color: "#5b6b82" },
          text: "Rolling 36m Sharpe omitted" }]
      }));
    }
    return render;
  };

  // 15. gross vs net annual comparison (recorded) ---------------------------
  CHARTS.grossnet = function (node) {
    var controls = node.querySelector(".chart-controls");
    var pf = "Momentum";
    makeSelect(controls, "Portfolio", STRAT_ORDER.map(function (p) { return { value: p, label: p }; }), pf, function (v) { pf = v; onChange(); });
    function onChange() { node.dataset.rendered = "1"; render(); }
    function render() {
      var a = DATA.annual || {};
      var years = a.years.map(function (y) { return y === a.partial_year ? y + "*" : String(y); });
      draw(node, [
        { type: "bar", name: "Gross (pre-cost)", x: years, y: a.gross[pf].map(function (v) { return v == null ? null : v * 100; }),
          marker: { color: "#8a94a6" }, hovertemplate: "%{x}<br>Gross: %{y:.1f}%<extra></extra>" },
        { type: "bar", name: "Net (15 bps + taxes)", x: years, y: a.net[pf].map(function (v) { return v == null ? null : v * 100; }),
          marker: { color: PORT[pf] }, hovertemplate: "%{x}<br>Net: %{y:.1f}%<extra></extra>" }
      ], baseLayout({
        barmode: "group", yaxis: { title: { text: "Annual return (%)" }, automargin: true, gridcolor: "#eef2f7" },
        annotations: [{ x: 0, y: 1.02, xref: "paper", yref: "paper", yanchor: "bottom", xanchor: "left", showarrow: false, font: { size: 11, color: "#5b6b82" },
          text: pf + " \u00b7 2026* partial" }]
      }));
    }
    return render;
  };

  // ---------------------------------------------------------------- pipeline
  function setupPipeline() {
    var tabs = Array.prototype.slice.call(document.querySelectorAll(".stage-tab"));
    if (!tabs.length) return;
    function select(i, focus) {
      tabs.forEach(function (t, j) {
        var on = i === j;
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.tabIndex = on ? 0 : -1;
        var panel = document.getElementById(t.getAttribute("aria-controls"));
        if (panel) panel.hidden = !on;
      });
      if (focus) tabs[i].focus();
    }
    tabs.forEach(function (t, i) {
      t.addEventListener("click", function () { select(i, false); });
      t.addEventListener("keydown", function (e) {
        if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); select((i + 1) % tabs.length, true); }
        else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); select((i - 1 + tabs.length) % tabs.length, true); }
      });
    });
    select(0, false);
  }

  // ---------------------------------------------------------------- literature
  function setupLiterature() {
    var root = document.getElementById("literature-table");
    if (!root || !DATA.literature) return;
    var lit = DATA.literature;
    var signals = lit.signals || [], sections = lit.sections || [];

    var controls = document.createElement("div"); controls.className = "lit-controls";
    var content = document.createElement("div");
    var opts = [{ value: "All", label: "All sections" }].concat(sections.map(function (s) { return { value: s.title, label: s.title }; }));
    makeSelect(controls, "Section", opts, "All", function (v) { renderSections(v); });
    root.appendChild(document.createElement("h3")).textContent = "Signal \u2192 method \u2192 literature";
    var tbl = document.createElement("div"); tbl.className = "table-scroll";
    tbl.tabIndex = 0; tbl.setAttribute("role", "region");
    tbl.setAttribute("aria-label", "Signal to method to literature mapping table, scroll horizontally for all columns");
    var table = document.createElement("table"); table.className = "data-table";
    var thead = document.createElement("thead");
    var hr = document.createElement("tr");
    ["Signal", "Implementation", "Literature anchor"].forEach(function (h) { var th = document.createElement("th"); th.scope = "col"; th.textContent = h; hr.appendChild(th); });
    thead.appendChild(hr); table.appendChild(thead);
    var tb = document.createElement("tbody");
    signals.forEach(function (s) {
      var tr = document.createElement("tr");
      [s.signal, s.implementation, s.anchor].forEach(function (val, idx) {
        var td = document.createElement(idx === 0 ? "th" : "td");
        if (idx === 0) td.scope = "row";
        td.textContent = val;
        tr.appendChild(td);
      });
      tb.appendChild(tr);
    });
    table.appendChild(tb); tbl.appendChild(table);
    var cue = document.createElement("p"); cue.className = "table-scroll-cue"; cue.setAttribute("aria-hidden", "true");
    cue.textContent = "Swipe table \u2192";
    root.appendChild(cue); root.appendChild(tbl);
    root.appendChild(document.createElement("h3")).textContent = "Method notes from the mapping";
    root.appendChild(controls);
    root.appendChild(content);

    function renderSections(which) {
      content.textContent = "";
      sections.filter(function (s) { return which === "All" || s.title === which; }).forEach(function (s) {
        var h = document.createElement("p"); h.className = "lit-section-title"; h.textContent = s.title;
        content.appendChild(h);
        var ul = document.createElement("ul"); ul.className = "lit-list";
        s.items.forEach(function (item) { var li = document.createElement("li"); li.textContent = item; ul.appendChild(li); });
        content.appendChild(ul);
      });
    }
    renderSections("All");

    var refs = document.getElementById("reference-list");
    if (refs) {
      (lit.references || []).forEach(function (r) {
        var li = document.createElement("li");
        var a = document.createElement("a");
        a.href = r.url; a.rel = "noopener"; a.textContent = r.cite;
        li.appendChild(a);
        refs.appendChild(li);
      });
    }
  }

  // ---------------------------------------------------------------- boot
  function boot() {
    setupPipeline();
    setupLiterature();
    var registry = new Map();
    var nodes = Array.prototype.slice.call(document.querySelectorAll("[data-chart]"));
    nodes.forEach(function (node) {
      var key = node.dataset.chart;
      var setup = CHARTS[key];
      if (!setup) return;
      var render = setup(node);
      registry.set(node, render);
    });
    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting && !e.target.dataset.rendered) {
            var r = registry.get(e.target);
            if (r) { e.target.dataset.rendered = "1"; r(); }
          }
        });
      }, { rootMargin: "200px 0px" });
      registry.forEach(function (_r, node) { io.observe(node); });
    } else {
      registry.forEach(function (r, node) { node.dataset.rendered = "1"; r(); });
    }
    window.__siteCharts = registry;
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
