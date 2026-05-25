"""
Professional trading chart component.
Uses TradingView Lightweight Charts v4 (free/CDN).

Multi-pane alignment strategy
──────────────────────────────
The root cause of RSI/MACD misalignment in separate-chart setups is that
each chart auto-sizes its right price scale independently (e.g. "3,500.50"
is ~68 px wide; "70.00" is ~40 px wide).  Setting the same
  rightPriceScale: { minimumWidth: PRICE_SCALE_W }
on ALL chart instances forces the price-scale column to the same fixed
width, so every chart's canvas area has identical pixel width → bars sit
at exactly the same x-pixel.  PRICE_SCALE_W = 72 is wide enough for
Indian large-cap prices up to "9,999.99".

Crosshair sync
──────────────
`isSyncing` flag breaks the feedback loop that would otherwise cause
subscribeVisibleLogicalRangeChange to ping-pong between charts.
`setCrosshairPosition(NaN, time, firstSeries)` syncs the vertical
crosshair bar across every sub-pane without affecting price lines.

Inline labels
─────────────
All overlay series have lastValueVisible: false and title: '' so no
floating "EMA(14)" / "SMA(20)" labels appear beside the lines.
Active indicators are shown only in the topbar chip row.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st


# Fixed price-scale width applied to every chart instance (main + all sub-panes).
# Must be ≥ widest price label that will appear on the main chart.
# 72 px comfortably fits "9,999.99" in the Inter / Segoe font at 11 px.
_PRICE_SCALE_W = 72


# ── OHLCV conversion ──────────────────────────────────────────────────────────

def _df_to_ohlcv(df: pd.DataFrame) -> tuple[list, list]:
    candles, volumes = [], []
    prev_close = None
    for idx, row in df.iterrows():
        try:
            ts  = int(pd.Timestamp(idx).timestamp())
            o   = float(row.get("Open",   0))
            h   = float(row.get("High",   0))
            l   = float(row.get("Low",    0))
            c   = float(row.get("Close",  0))
            vol = float(row.get("Volume", 0))
            if not (o and h and l and c):
                continue
            candles.append({"time": ts, "open": o, "high": h, "low": l, "close": c})
            up = prev_close is None or c >= prev_close
            volumes.append({"time": ts, "value": vol,
                            "color": "#00d4aa22" if up else "#f43f5e22"})
            prev_close = c
        except Exception:
            continue
    return candles, volumes


# ── Public render function ────────────────────────────────────────────────────

def render_chart(
    df:          pd.DataFrame,
    symbol:      str,
    overlays:    Optional[List[Dict]] = None,
    panes:       Optional[List[Dict]] = None,
    height:      int  = 560,
    show_volume: bool = True,
    timeframe:   str  = "1D",
    zones:       Optional[List[Dict]] = None,
) -> None:
    overlays = overlays or []
    panes    = panes    or []
    zones    = zones    or []

    candles, volumes = _df_to_ohlcv(df)
    if not candles:
        st.warning("No chart data available.")
        return

    pane_groups: Dict[str, List[Dict]] = {}
    for s in panes:
        key = s.get("pane", "indicator")
        pane_groups.setdefault(key, []).append(s)

    html = _build_chart_html(
        candles, volumes, symbol, overlays, pane_groups,
        height, show_volume, timeframe, zones,
    )
    st.components.v1.html(html, height=height + 6, scrolling=False)


# ── HTML builder ──────────────────────────────────────────────────────────────

def _build_chart_html(
    candles:     list,
    volumes:     list,
    symbol:      str,
    overlays:    List[Dict],
    pane_groups: Dict[str, List[Dict]],
    height:      int,
    show_volume: bool,
    timeframe:   str,
    zones:       Optional[List[Dict]] = None,
) -> str:

    num_panes   = len(pane_groups)
    vol_height  = 68 if show_volume else 0
    pane_height = 125 if num_panes else 0
    main_height = max(height - vol_height - pane_height * num_panes, 200)

    candles_json  = json.dumps(candles)
    volumes_json  = json.dumps(volumes)
    overlays_json = json.dumps(overlays)
    zones_json    = json.dumps(zones or [])

    ls_key = (
        f"chart_range_{symbol}_{timeframe}"
        .replace(".", "_").replace("^", "_").replace(" ", "_")
    )

    # ── Volume pane HTML + JS ─────────────────────────────────────────────────
    vol_html_block = (
        f'<div class="vol-sep"></div>'
        f'<div id="vol-pane" style="height:{vol_height}px;"></div>'
        if show_volume else ""
    )
    vol_js_block = (
        f"""
var volChart = LightweightCharts.createChart(
  document.getElementById("vol-pane"), subChartOpts({vol_height})
);
var volSeries = volChart.addHistogramSeries({{
  priceFormat:  {{ type: "volume" }},
  priceScaleId: "vol",
}});
volChart.priceScale("vol").applyOptions({{
  scaleMargins: {{ top: 0.08, bottom: 0 }},
}});
volSeries.setData(VOLUMES);
subCharts.push(volChart);
subChartFirstSeries.push(volSeries);
""" if show_volume else ""
    )

    # ── Indicator pane HTML + JS ──────────────────────────────────────────────
    pane_containers_html = ""
    pane_init_js         = ""

    for i, (pane_key, series_list) in enumerate(pane_groups.items()):
        pane_id    = f"pane_{pane_key}_{i}"
        label      = _pane_label(pane_key)
        series_js  = json.dumps(series_list)

        pane_containers_html += (
            f'<div class="sub-pane-label">{label}</div>'
            f'<div id="{pane_id}" style="height:{pane_height}px;"></div>'
        )

        pane_init_js += f"""
(function() {{
  var pEl = document.getElementById("{pane_id}");
  var pC  = LightweightCharts.createChart(pEl, subChartOpts({pane_height}));
  var seriesList = {series_js};
  var firstSeries = null;
  seriesList.forEach(function(s) {{
    var opts = {{
      color:            s.color,
      lineWidth:        s.linewidth || 1,
      lastValueVisible: true,
      priceLineVisible: false,
    }};
    var cs;
    if (s.series_type === "histogram") {{
      cs = pC.addHistogramSeries({{
        color:            s.color,
        priceLineVisible: false,
        lastValueVisible: false,
      }});
    }} else {{
      cs = pC.addLineSeries(opts);
    }}
    if (s.data && s.data.length) cs.setData(s.data);
    if (!firstSeries) firstSeries = cs;
  }});
  /* Reference lines */
  if ("{pane_key}" === "rsi") {{
    var times = seriesList[0] && seriesList[0].data
      ? seriesList[0].data.map(function(d) {{ return d.time; }}) : [];
    var ob = pC.addLineSeries({{ color:"#f43f5e55", lineWidth:1, lastValueVisible:false, priceLineVisible:false }});
    var os = pC.addLineSeries({{ color:"#00d4aa55", lineWidth:1, lastValueVisible:false, priceLineVisible:false }});
    ob.setData(times.map(function(t) {{ return {{ time:t, value:70 }}; }}));
    os.setData(times.map(function(t) {{ return {{ time:t, value:30 }}; }}));
    if (!firstSeries) firstSeries = ob;
  }}
  if ("{pane_key}" === "macd") {{
    var times2 = seriesList[0] && seriesList[0].data
      ? seriesList[0].data.map(function(d) {{ return d.time; }}) : [];
    var mid = pC.addLineSeries({{ color:"#64748b55", lineWidth:1, lastValueVisible:false, priceLineVisible:false }});
    mid.setData(times2.map(function(t) {{ return {{ time:t, value:0 }}; }}));
  }}
  subCharts.push(pC);
  subChartFirstSeries.push(firstSeries);
}})();"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{
  background: #080d17; overflow: hidden; width: 100%;
  font-family: 'Inter','Segoe UI',sans-serif;
}}

.chart-wrapper {{
  display: flex; flex-direction: column;
  background: #080d17;
  border: 1px solid #1e2d45;
  border-radius: 8px; overflow: hidden;
  animation: fadein 0.18s ease;
}}
@keyframes fadein {{ from {{ opacity:0; }} to {{ opacity:1; }} }}

.chart-topbar {{
  display: flex; align-items: center; gap: 10px;
  padding: 7px 13px;
  background: #0a0f1a; border-bottom: 1px solid #1e2d45;
}}

.chart-symbol {{
  color: #e2e8f0; font-size: 0.9rem; font-weight: 700;
  letter-spacing: 0.03em;
}}
.chart-tf-badge {{
  background: #1e2d45; color: #64748b;
  font-size: 0.68rem; padding: 2px 7px;
  border-radius: 4px; font-weight: 600;
}}

.topbar-chips {{ display: flex; gap: 5px; flex-wrap: wrap; flex: 1; }}
.topbar-chip {{
  display: inline-flex; align-items: center; gap: 3px;
  font-size: 0.65rem; font-weight: 600; padding: 2px 8px;
  border-radius: 10px; white-space: nowrap;
  background: #00d4aa12; color: #00d4aa; border: 1px solid #00d4aa2a;
}}

.price-display {{
  margin-left: auto; color: #e2e8f0;
  font-size: 0.82rem; font-family: 'Courier New', monospace;
  min-width: 180px; text-align: right; flex-shrink: 0;
}}

#main-chart {{ flex-shrink: 0; }}

.vol-sep  {{ height: 1px; background: #1e2d45; }}
#vol-pane {{ flex-shrink: 0; }}

.sub-pane-label {{
  padding: 2px 10px;
  background: #0a0f1a;
  color: #64748b; font-size: 0.67rem; font-weight: 700;
  letter-spacing: 0.06em; text-transform: uppercase;
  border-top: 1px solid #1e2d45;
}}
</style>
</head>
<body>
<div class="chart-wrapper">
  <div class="chart-topbar">
    <span class="chart-symbol">{symbol}</span>
    <span class="chart-tf-badge">{timeframe}</span>
    <div class="topbar-chips" id="topbar-chips"></div>
    <span class="price-display" id="price-display">—</span>
  </div>
  <div id="main-chart" style="height:{main_height}px;"></div>
  {vol_html_block}
  {pane_containers_html}
</div>

<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<script>
'use strict';

var CANDLES    = {candles_json};
var VOLUMES    = {volumes_json};
var OVERLAYS   = {overlays_json};
var SMC_ZONES  = {zones_json};
var LS_KEY     = '{ls_key}';

/* Shared state for all chart instances */
var subCharts           = [];   /* every non-main chart (vol + indicator panes) */
var subChartFirstSeries = [];   /* parallel array — first series of each sub-chart */
var isSyncing           = false; /* prevents range-sync feedback loop */
var isCrosshairSyncing  = false;

/* ── Chart option factories ────────────────────────────────────────── */
/*
 * ALIGNMENT KEY: every chart (main + sub) gets the same minimumWidth on
 * its right price scale.  This forces the price-scale column to be at
 * least {_PRICE_SCALE_W} px wide on every chart, so the canvas (bar) area
 * is the same width on all panes → bars line up pixel-perfectly.
 */
var PRICE_SCALE_OPTS = {{
  borderColor:  "#1e2d45",
  textColor:    "#64748b",
  minimumWidth: {_PRICE_SCALE_W},
}};

function baseOpts(h) {{
  return {{
    width:  document.body.clientWidth,
    height: h,
    layout: {{
      background: {{ type: "solid", color: "#080d17" }},
      textColor:  "#64748b",
      fontSize:   11,
      fontFamily: "Inter,'Segoe UI',sans-serif",
    }},
    grid: {{
      vertLines: {{ color: "#1e2d4533", style: 1 }},
      horzLines: {{ color: "#1e2d4533", style: 1 }},
    }},
    crosshair: {{
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine: {{ color: "#00d4aa44", width: 1, labelBackgroundColor: "#00d4aa" }},
      horzLine: {{ color: "#00d4aa44", width: 1, labelBackgroundColor: "#00d4aa" }},
    }},
    rightPriceScale: PRICE_SCALE_OPTS,
    timeScale: {{
      borderColor:    "#1e2d45",
      textColor:      "#64748b",
      timeVisible:    true,
      secondsVisible: false,
      rightOffset:    8,
    }},
    handleScroll: {{ mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true }},
    handleScale:  {{ axisPressedMouseMove: true, mouseWheel: true, pinch: true }},
  }};
}}

function subChartOpts(h) {{
  var o = baseOpts(h);
  o.timeScale.visible = false;
  o.crosshair.vertLine.labelVisible = false;
  return o;
}}

/* ── Main chart ─────────────────────────────────────────────────────── */
var mainChart = LightweightCharts.createChart(
  document.getElementById("main-chart"), baseOpts({main_height})
);

var candleSeries = mainChart.addCandlestickSeries({{
  upColor:       "#00d4aa",
  downColor:     "#f43f5e",
  borderVisible: false,
  wickUpColor:   "#00d4aa",
  wickDownColor: "#f43f5e",
}});
candleSeries.setData(CANDLES);

/* ── Overlay series ─────────────────────────────────────────────────── */
/*
 * lastValueVisible: false  — removes the floating "EMA(14)" label beside the line
 * title: ''                — removes any legend text rendered on the chart
 * Active indicator names appear only in the topbar chip row below.
 */
var overlaySeriesMap = {{}};
OVERLAYS.forEach(function(ov) {{
  var s = mainChart.addLineSeries({{
    color:            ov.color || "#00d4aa",
    lineWidth:        ov.linewidth || 2,
    priceLineVisible: false,
    lastValueVisible: false,
    title:            "",
  }});
  if (ov.data && ov.data.length) s.setData(ov.data);
  if (ov.id) overlaySeriesMap[ov.id] = s;
}});

/* ── Volume pane ────────────────────────────────────────────────────── */
{vol_js_block}

/* ── Indicator panes ────────────────────────────────────────────────── */
{pane_init_js}

/* ── Range synchronisation (with isSyncing guard) ──────────────────── */
/*
 * Without the guard, setting the range on sub-charts fires their own
 * subscribeVisibleLogicalRangeChange, which sets mainChart's range, which
 * fires again — an infinite feedback loop.  isSyncing breaks the cycle.
 */
function syncRangeFrom(sourceChart) {{
  if (isSyncing) return;
  isSyncing = true;
  var range = sourceChart.timeScale().getVisibleLogicalRange();
  if (range) {{
    var allCharts = [mainChart].concat(subCharts);
    allCharts.forEach(function(c) {{
      if (c !== sourceChart) {{
        c.timeScale().setVisibleLogicalRange(range);
      }}
    }});
  }}
  isSyncing = false;
}}

mainChart.timeScale().subscribeVisibleLogicalRangeChange(function() {{
  syncRangeFrom(mainChart);
}});
subCharts.forEach(function(sc) {{
  sc.timeScale().subscribeVisibleLogicalRangeChange(function() {{
    syncRangeFrom(sc);
  }});
}});

/* ── Crosshair synchronisation ──────────────────────────────────────── */
/*
 * When the crosshair moves on the main chart, mirror the vertical bar on
 * every sub-pane at the same timestamp.  We pass NaN as the price so the
 * horizontal crosshair line is NOT drawn (each pane has its own scale),
 * but the vertical timeline bar stays in sync.
 */
mainChart.subscribeCrosshairMove(function(param) {{
  /* Update OHLC topbar display */
  var el = document.getElementById("price-display");
  if (el) {{
    if (!param.time || !param.seriesData) {{
      el.innerHTML = "—";
    }} else {{
      var bar = param.seriesData.get(candleSeries);
      if (bar) {{
        var chg  = bar.close - bar.open;
        var pct  = ((chg / bar.open) * 100).toFixed(2);
        var clr  = chg >= 0 ? "#00d4aa" : "#f43f5e";
        var sign = chg >= 0 ? "+" : "";
        el.innerHTML =
          "<span style='color:#94a3b8;font-size:0.67rem'>O</span>"
          + "<span style='color:#e2e8f0'>" + bar.open.toFixed(2)  + "</span> "
          + "<span style='color:#94a3b8;font-size:0.67rem'>H</span>"
          + "<span style='color:#e2e8f0'>" + bar.high.toFixed(2)  + "</span> "
          + "<span style='color:#94a3b8;font-size:0.67rem'>L</span>"
          + "<span style='color:#e2e8f0'>" + bar.low.toFixed(2)   + "</span> "
          + "<span style='color:#94a3b8;font-size:0.67rem'>C</span>"
          + "<span style='color:#e2e8f0;font-weight:700'>" + bar.close.toFixed(2) + "</span> "
          + "<span style='color:" + clr + ";font-size:0.72rem'>"
          + sign + chg.toFixed(2) + " (" + sign + pct + "%)</span>";
      }}
    }}
  }}

  /* Mirror crosshair on sub-charts */
  if (isCrosshairSyncing) return;
  isCrosshairSyncing = true;
  subCharts.forEach(function(sc, idx) {{
    if (!param.time) {{
      try {{ sc.clearCrosshairPosition(); }} catch(e) {{}}
    }} else if (subChartFirstSeries[idx]) {{
      try {{
        sc.setCrosshairPosition(NaN, param.time, subChartFirstSeries[idx]);
      }} catch(e) {{}}
    }}
  }});
  isCrosshairSyncing = false;
}});

/* ── localStorage: persist & restore visible range ─────────────────── */
function saveRange() {{
  try {{
    var r = mainChart.timeScale().getVisibleLogicalRange();
    if (r) localStorage.setItem(LS_KEY, JSON.stringify(r));
  }} catch(e) {{}}
}}
function restoreRange() {{
  try {{
    var raw = localStorage.getItem(LS_KEY);
    if (!raw) {{ mainChart.timeScale().fitContent(); return; }}
    var r = JSON.parse(raw);
    mainChart.timeScale().setVisibleLogicalRange(r);
    syncRangeFrom(mainChart);
  }} catch(e) {{
    mainChart.timeScale().fitContent();
  }}
}}
mainChart.timeScale().subscribeVisibleLogicalRangeChange(saveRange);
setTimeout(restoreRange, 80);

/* ── postMessage bridge (CHART_BRIDGE) ──────────────────────────────── */
window.addEventListener("message", function(ev) {{
  if (!ev.data || ev.data.type !== "CHART_BRIDGE") return;
  var msg = ev.data;
  if (msg.action === "add_overlay" && msg.payload) {{
    var ov = msg.payload;
    if (overlaySeriesMap[ov.id]) {{
      overlaySeriesMap[ov.id].setData(ov.data || []);
    }} else {{
      var s = mainChart.addLineSeries({{
        color: ov.color || "#00d4aa", lineWidth: ov.linewidth || 2,
        priceLineVisible: false, lastValueVisible: false, title: "",
      }});
      if (ov.data && ov.data.length) s.setData(ov.data);
      if (ov.id) overlaySeriesMap[ov.id] = s;
    }}
  }}
  if (msg.action === "remove_overlay" && msg.id && overlaySeriesMap[msg.id]) {{
    try {{ mainChart.removeSeries(overlaySeriesMap[msg.id]); }} catch(e) {{}}
    delete overlaySeriesMap[msg.id];
  }}
  if (msg.action === "fit")        {{ mainChart.timeScale().fitContent(); }}
  if (msg.action === "save_range") {{ saveRange(); }}
}});

/* ── Cross-iframe overlay bridge (localStorage storage events) ───────── */
window.addEventListener("storage", function(ev) {{
  if (ev.key !== "pine_chart_actions") return;
  try {{
    var actions = JSON.parse(ev.newValue || "[]");
    actions.forEach(function(a) {{
      if (a.type === "remove" && a.id && overlaySeriesMap[a.id]) {{
        try {{ mainChart.removeSeries(overlaySeriesMap[a.id]); }} catch(e) {{}}
        delete overlaySeriesMap[a.id];
      }}
    }});
    localStorage.setItem("pine_chart_actions", "[]");
  }} catch(e) {{}}
}});
(function() {{
  try {{
    var pending = JSON.parse(localStorage.getItem("pine_chart_actions") || "[]");
    if (pending.length) {{
      pending.forEach(function(a) {{
        if (a.type === "remove" && a.id && overlaySeriesMap[a.id]) {{
          try {{ mainChart.removeSeries(overlaySeriesMap[a.id]); }} catch(e) {{}}
          delete overlaySeriesMap[a.id];
        }}
      }});
      localStorage.setItem("pine_chart_actions", "[]");
    }}
  }} catch(e) {{}}
}})();

/* ── Topbar indicator chips ─────────────────────────────────────────── */
(function() {{
  var chipsEl = document.getElementById("topbar-chips");
  if (!chipsEl) return;
  OVERLAYS.forEach(function(ov) {{
    if (!ov.label) return;
    var chip       = document.createElement("span");
    chip.className = "topbar-chip";
    chip.style.background  = (ov.color || "#00d4aa") + "12";
    chip.style.color        = ov.color || "#00d4aa";
    chip.style.borderColor  = (ov.color || "#00d4aa") + "2a";
    chip.textContent        = ov.label;
    chipsEl.appendChild(chip);
  }});
}})();

/* ── SMC Zone SVG overlay ───────────────────────────────────────────── */
(function() {{
  if (!SMC_ZONES || !SMC_ZONES.length) return;

  var mainEl = document.getElementById("main-chart");
  if (!mainEl) return;
  mainEl.style.position = "relative";

  var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.id = "smc-zone-svg";
  svg.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:10;overflow:visible;";
  mainEl.appendChild(svg);

  function drawZones() {{
    svg.innerHTML = "";
    var w = mainEl.clientWidth;
    var h = mainEl.clientHeight;
    var now = Math.floor(Date.now() / 1000) + 86400 * 60;

    SMC_ZONES.forEach(function(zone) {{
      try {{
        var y1 = candleSeries.priceToCoordinate(zone.high);
        var y2 = candleSeries.priceToCoordinate(zone.low);
        if (y1 === null || y2 === null) return;

        var x1 = mainChart.timeScale().timeToCoordinate(zone.time_start);
        var x2 = zone.time_end
          ? mainChart.timeScale().timeToCoordinate(zone.time_end)
          : w;
        if (x1 === null) return;
        if (x2 === null) x2 = w;

        var top  = Math.min(y1, y2);
        var zh   = Math.max(Math.abs(y2 - y1), 2);
        var left = Math.min(x1, x2);
        var zw   = Math.max(Math.abs(x2 - x1), 8);

        if (top + zh < 0 || top > h || left + zw < 0 || left > w) return;

        var rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        rect.setAttribute("x",            left.toFixed(1));
        rect.setAttribute("y",            top.toFixed(1));
        rect.setAttribute("width",        zw.toFixed(1));
        rect.setAttribute("height",       zh.toFixed(1));
        rect.setAttribute("fill",         zone.fill_color  || "#00d4aa18");
        rect.setAttribute("stroke",       zone.border_color || "#00d4aa80");
        rect.setAttribute("stroke-width", "1");
        rect.setAttribute("rx",           "1");
        svg.appendChild(rect);

        if (zone.label && zh >= 8) {{
          var txt = document.createElementNS("http://www.w3.org/2000/svg", "text");
          txt.setAttribute("x",           (left + 3).toFixed(1));
          txt.setAttribute("y",           (top + Math.min(10, zh - 2)).toFixed(1));
          txt.setAttribute("fill",        zone.label_color || zone.border_color || "#00d4aa");
          txt.setAttribute("font-size",   "8.5");
          txt.setAttribute("font-weight", "700");
          txt.setAttribute("font-family", "Inter,'Segoe UI',sans-serif");
          txt.textContent = zone.label;
          svg.appendChild(txt);
        }}
      }} catch(e) {{}}
    }});
  }}

  mainChart.timeScale().subscribeVisibleLogicalRangeChange(function() {{
    requestAnimationFrame(drawZones);
  }});
  mainChart.subscribeCrosshairMove(function() {{
    requestAnimationFrame(drawZones);
  }});
  setTimeout(drawZones, 350);
}})();

/* ── Responsive resize ──────────────────────────────────────────────── */
window.addEventListener("resize", function() {{
  var w = document.body.clientWidth;
  mainChart.applyOptions({{ width: w }});
  subCharts.forEach(function(sc) {{ sc.applyOptions({{ width: w }}); }});
  var zsvg = document.getElementById("smc-zone-svg");
  if (zsvg) {{ requestAnimationFrame(function() {{
    var mainEl2 = document.getElementById("main-chart");
    if (mainEl2 && window._drawZones) window._drawZones();
  }}); }}
}});
</script>
</body>
</html>"""


def _pane_label(pane_key: str) -> str:
    return {
        "rsi":       "RSI",
        "macd":      "MACD",
        "atr":       "ATR",
        "adx":       "ADX / DMI",
        "stoch":     "Stochastic",
        "cci":       "CCI",
        "indicator": "Indicator",
        "volume":    "Volume",
    }.get(pane_key, pane_key.upper())
