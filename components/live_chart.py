"""
WebSocket-Powered Live Chart Component
========================================
Renders TradingView Lightweight Charts connected directly to the FastAPI
WebSocket backend.  No Streamlit reruns required for live price updates.

Architecture:
  Browser JS ←→ FastAPI WS (ws://localhost:8000/ws/{symbol}/{tf})
      ↓
  candleSeries.update()   ← incremental tick, no full redraw
  candleSeries.setData()  ← only on initial load / timeframe switch

Chart layout:
  ┌─────────────────────────────────────┐
  │  OHLC topbar + live price           │
  ├─────────────────────────────────────┤
  │  Main chart (candles + EMA + VWAP)  │  ~65% height
  ├─────────────────────────────────────┤
  │  Volume histogram                   │  ~12% height
  ├─────────────────────────────────────┤
  │  RSI (14) + 70/30 bands             │  ~12% height
  ├─────────────────────────────────────┤
  │  MACD (12,26,9)                     │  ~11% height
  └─────────────────────────────────────┘

Usage:
  from components.live_chart import render_live_chart
  render_live_chart(symbol="BTCUSD", timeframe="1m", height=720)
"""

import streamlit as st
import streamlit.components.v1 as components

BACKEND_WS_URL  = "ws://localhost:8000/ws"
BACKEND_REST_URL = "http://localhost:8000/api"

_LWCHARTS_CDN = "https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"

# Color palette — matches the dark terminal theme
_PALETTE = {
    "bg":          "#0a0e1a",
    "bg2":         "#0d1117",
    "panel":       "#111827",
    "border":      "#1e2d3d",
    "text":        "#e2e8f0",
    "muted":       "#64748b",
    "bullish":     "#00d4aa",
    "bearish":     "#f43f5e",
    "ema9":        "#00d4aa",
    "ema21":       "#f59e0b",
    "ema50":       "#818cf8",
    "ema200":      "#f87171",
    "vwap":        "#38bdf8",
    "rsi_line":    "#a78bfa",
    "macd_line":   "#38bdf8",
    "macd_sig":    "#fb923c",
    "macd_hist_u": "#00d4aa55",
    "macd_hist_d": "#f43f5e55",
    "crosshair":   "#334155",
    "grid":        "#0f1923",
    "scale_bg":    "#0a0e1a",
}


def _build_html(
    symbol: str,
    timeframe: str,
    height: int,
    show_volume: bool,
    show_rsi: bool,
    show_macd: bool,
    show_ema: bool,
    show_vwap: bool,
    backend_ws: str,
) -> str:
    p = _PALETTE

    # Sub-pane height allocation
    vol_px    = 70  if show_volume else 0
    rsi_px    = 90  if show_rsi    else 0
    macd_px   = 90  if show_macd   else 0
    topbar_px = 48
    sub_total = vol_px + rsi_px + macd_px
    main_px   = max(height - topbar_px - sub_total - 16, 200)

    show_vol_js  = str(show_volume).lower()
    show_rsi_js  = str(show_rsi).lower()
    show_macd_js = str(show_macd).lower()
    show_ema_js  = str(show_ema).lower()
    show_vwap_js = str(show_vwap).lower()

    # Pre-compute snippets that would require backslashes inside f-string exprs
    _tfs = ["1m", "5m", "15m", "1H", "4H", "1D"]
    tf_buttons = "".join(
        '<button class="tf-btn{active}" onclick="switchTF(\'{t}\')">{t}</button>'.format(
            active=' active' if timeframe == t else '',
            t=t,
        )
        for t in _tfs
    )

    _vol_html = (
        '<div class="divider"></div>'
        '<div class="chart-section" id="vol-wrap" style="height:{h}px;">'
        '<div class="pane-label">VOL</div>'
        '<div id="vol-chart" style="height:100%;width:100%;"></div></div>'
    ).format(h=vol_px) if show_volume else ""

    _rsi_html = (
        '<div class="divider"></div>'
        '<div class="chart-section" id="rsi-wrap" style="height:{h}px;">'
        '<div class="pane-label">RSI(14)</div>'
        '<div id="rsi-chart" style="height:100%;width:100%;"></div></div>'
    ).format(h=rsi_px) if show_rsi else ""

    _macd_html = (
        '<div class="divider"></div>'
        '<div class="chart-section" id="macd-wrap" style="height:{h}px;">'
        '<div class="pane-label">MACD(12,26,9)</div>'
        '<div id="macd-chart" style="height:100%;width:100%;"></div></div>'
    ).format(h=macd_px) if show_macd else ""

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: {p['bg']};
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    color: {p['text']};
    overflow: hidden;
    user-select: none;
  }}
  #root {{
    display: flex;
    flex-direction: column;
    height: {height}px;
    width: 100%;
  }}
  /* ── Topbar ── */
  #topbar {{
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 0 12px;
    height: {topbar_px}px;
    background: {p['panel']};
    border-bottom: 1px solid {p['border']};
    flex-shrink: 0;
  }}
  #symbol-label {{
    font-size: 14px;
    font-weight: 700;
    color: {p['text']};
    letter-spacing: 0.5px;
  }}
  .tf-btn {{
    font-size: 11px;
    padding: 3px 8px;
    border-radius: 4px;
    border: 1px solid {p['border']};
    background: transparent;
    color: {p['muted']};
    cursor: pointer;
    transition: all 0.15s ease;
  }}
  .tf-btn:hover, .tf-btn.active {{
    background: {p['bullish']}22;
    border-color: {p['bullish']};
    color: {p['bullish']};
  }}
  #price-display {{
    margin-left: auto;
    display: flex;
    align-items: baseline;
    gap: 10px;
  }}
  #live-price {{
    font-size: 18px;
    font-weight: 700;
    color: {p['bullish']};
    transition: color 0.3s ease;
  }}
  #live-price.down {{ color: {p['bearish']}; }}
  #price-change {{
    font-size: 12px;
    color: {p['muted']};
  }}
  #ohlc-strip {{
    font-size: 10px;
    color: {p['muted']};
    display: flex;
    gap: 8px;
    flex-wrap: nowrap;
  }}
  .ohlc-item span {{ color: {p['text']}; }}
  /* ── Status dot ── */
  #ws-dot {{
    width: 7px; height: 7px;
    border-radius: 50%;
    background: {p['muted']};
    flex-shrink: 0;
    transition: background 0.4s ease;
  }}
  #ws-dot.live {{ background: {p['bullish']}; box-shadow: 0 0 6px {p['bullish']}88; }}
  #ws-dot.error {{ background: {p['bearish']}; }}
  /* ── Chart sections ── */
  .chart-section {{
    width: 100%;
    flex-shrink: 0;
    position: relative;
  }}
  .pane-label {{
    position: absolute;
    top: 4px;
    left: 8px;
    font-size: 9px;
    color: {p['muted']};
    z-index: 5;
    pointer-events: none;
  }}
  .divider {{
    height: 1px;
    background: {p['border']};
    flex-shrink: 0;
  }}
  /* ── Indicator chips ── */
  #ind-chips {{
    display: flex;
    gap: 6px;
    margin-left: 12px;
  }}
  .chip {{
    font-size: 9px;
    padding: 1px 5px;
    border-radius: 3px;
    font-weight: 600;
  }}
</style>
</head>
<body>
<div id="root">

  <!-- Topbar -->
  <div id="topbar">
    <div id="ws-dot"></div>
    <div id="symbol-label">{symbol} · {timeframe}</div>
    <!-- Timeframe buttons -->
    <div style="display:flex;gap:4px;margin-left:4px;">
      {tf_buttons}
    </div>
    <!-- Indicator chips -->
    <div id="ind-chips"></div>
    <!-- OHLC + price -->
    <div id="price-display">
      <div id="ohlc-strip">
        <div class="ohlc-item">O <span id="o-val">—</span></div>
        <div class="ohlc-item">H <span id="h-val">—</span></div>
        <div class="ohlc-item">L <span id="l-val">—</span></div>
        <div class="ohlc-item">C <span id="c-val">—</span></div>
      </div>
      <div id="price-change">—</div>
      <div id="live-price">—</div>
    </div>
  </div>

  <!-- Main chart -->
  <div class="chart-section" id="main-wrap" style="height:{main_px}px;">
    <div class="pane-label">PRICE</div>
    <div id="main-chart" style="height:100%;width:100%;"></div>
  </div>

  <!-- Volume -->
  {_vol_html}

  <!-- RSI -->
  {_rsi_html}

  <!-- MACD -->
  {_macd_html}

</div>

<script src="{_LWCHARTS_CDN}"></script>
<script>
"use strict";

// ── Config ──────────────────────────────────────────────────────────────────
const SYMBOL    = "{symbol}";
const TIMEFRAME = "{timeframe}";
const WS_BASE   = "{backend_ws}";
const SHOW_VOL  = {show_vol_js};
const SHOW_RSI  = {show_rsi_js};
const SHOW_MACD = {show_macd_js};
const SHOW_EMA  = {show_ema_js};
const SHOW_VWAP = {show_vwap_js};

const P = {{
  bg:        "{p['bg']}",
  bg2:       "{p['bg2']}",
  panel:     "{p['panel']}",
  border:    "{p['border']}",
  text:      "{p['text']}",
  muted:     "{p['muted']}",
  bullish:   "{p['bullish']}",
  bearish:   "{p['bearish']}",
  ema9:      "{p['ema9']}",
  ema21:     "{p['ema21']}",
  ema50:     "{p['ema50']}",
  ema200:    "{p['ema200']}",
  vwap:      "{p['vwap']}",
  rsi_line:  "{p['rsi_line']}",
  macd_line: "{p['macd_line']}",
  macd_sig:  "{p['macd_sig']}",
  macd_u:    "{p['macd_hist_u']}",
  macd_d:    "{p['macd_hist_d']}",
  cross:     "{p['crosshair']}",
  grid:      "{p['grid']}",
}};

// ── Chart options ────────────────────────────────────────────────────────────
const BASE_OPTS = {{
  layout: {{
    background:  {{ type: "solid", color: P.bg }},
    textColor:   P.muted,
    fontSize:    10,
  }},
  grid: {{
    vertLines:  {{ color: P.grid, style: 1 }},
    horzLines:  {{ color: P.grid, style: 1 }},
  }},
  crosshair: {{
    vertLine: {{ color: P.cross, labelBackgroundColor: P.panel }},
    horzLine: {{ color: P.cross, labelBackgroundColor: P.panel }},
  }},
  rightPriceScale: {{
    borderColor: P.border,
    scaleMargins: {{ top: 0.08, bottom: 0.05 }},
  }},
  timeScale: {{
    borderColor:     P.border,
    timeVisible:     true,
    secondsVisible:  TIMEFRAME === "1m",
    fixRightEdge:    true,
    lockVisibleTimeRangeOnResize: true,
  }},
  handleScroll:   true,
  handleScale:    true,
}};

// ── Create charts ────────────────────────────────────────────────────────────
const mainEl = document.getElementById("main-chart");
const mainChart = LightweightCharts.createChart(mainEl, BASE_OPTS);

const candleSeries = mainChart.addCandlestickSeries({{
  upColor:        P.bullish,  downColor:      P.bearish,
  borderUpColor:  P.bullish,  borderDownColor: P.bearish,
  wickUpColor:    P.bullish,  wickDownColor:  P.bearish,
}});

// EMA series
let ema9s, ema21s, ema50s, ema200s, vwapS;
if (SHOW_EMA) {{
  ema9s   = mainChart.addLineSeries({{ color: P.ema9,   lineWidth: 1, priceLineVisible: false, lastValueVisible: false }});
  ema21s  = mainChart.addLineSeries({{ color: P.ema21,  lineWidth: 1, priceLineVisible: false, lastValueVisible: false }});
  ema50s  = mainChart.addLineSeries({{ color: P.ema50,  lineWidth: 1, priceLineVisible: false, lastValueVisible: false }});
  ema200s = mainChart.addLineSeries({{ color: P.ema200, lineWidth: 2, priceLineVisible: false, lastValueVisible: false }});
}}
if (SHOW_VWAP) {{
  vwapS = mainChart.addLineSeries({{ color: P.vwap, lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false }});
}}

// Volume
let volSeries;
if (SHOW_VOL) {{
  const volEl = document.getElementById("vol-chart");
  const volChart = LightweightCharts.createChart(volEl, {{
    ...BASE_OPTS,
    rightPriceScale: {{ borderColor: P.border, scaleMargins: {{ top: 0.1, bottom: 0 }}, minimumWidth: 60 }},
    timeScale: {{ ...BASE_OPTS.timeScale, visible: false }},
  }});
  volSeries = volChart.addHistogramSeries({{
    priceFormat: {{ type: "volume" }},
    priceScaleId: "right",
  }});
  syncTimeScale(mainChart, volChart);
}}

// RSI
let rsiSeries, rsiChart;
if (SHOW_RSI) {{
  const rsiEl = document.getElementById("rsi-chart");
  rsiChart = LightweightCharts.createChart(rsiEl, {{
    ...BASE_OPTS,
    rightPriceScale: {{ borderColor: P.border, scaleMargins: {{ top: 0.1, bottom: 0.1 }}, minimumWidth: 60 }},
    timeScale: {{ ...BASE_OPTS.timeScale, visible: false }},
  }});
  rsiSeries = rsiChart.addLineSeries({{
    color: P.rsi_line, lineWidth: 1,
    priceLineVisible: false, lastValueVisible: true,
    autoscaleInfoProvider: () => ({{ priceRange: {{ minValue: 0, maxValue: 100 }} }}),
  }});
  // RSI 70/30 bands
  rsiChart.addLineSeries({{ color: "#f43f5e44", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, autoscaleInfoProvider: () => ({{ priceRange: {{ minValue: 0, maxValue: 100 }} }}) }})
    .setData([]);  // filled dynamically
  syncTimeScale(mainChart, rsiChart);
}}

// MACD
let macdLineSeries, macdSignalSeries, macdHistSeries, macdChart;
if (SHOW_MACD) {{
  const macdEl = document.getElementById("macd-chart");
  macdChart = LightweightCharts.createChart(macdEl, {{
    ...BASE_OPTS,
    rightPriceScale: {{ borderColor: P.border, scaleMargins: {{ top: 0.2, bottom: 0.2 }}, minimumWidth: 60 }},
    timeScale: {{ ...BASE_OPTS.timeScale, visible: true }},
  }});
  macdLineSeries   = macdChart.addLineSeries({{ color: P.macd_line, lineWidth: 1, priceLineVisible: false, lastValueVisible: false }});
  macdSignalSeries = macdChart.addLineSeries({{ color: P.macd_sig,  lineWidth: 1, priceLineVisible: false, lastValueVisible: false }});
  macdHistSeries   = macdChart.addHistogramSeries({{ priceLineVisible: false, lastValueVisible: false }});
  syncTimeScale(mainChart, macdChart);
}}

// ── Time-scale synchronization ───────────────────────────────────────────────
function syncTimeScale(master, slave) {{
  master.timeScale().subscribeVisibleLogicalRangeChange(r => {{
    if (r) slave.timeScale().setVisibleLogicalRange(r);
  }});
  slave.timeScale().subscribeVisibleLogicalRangeChange(r => {{
    if (r) master.timeScale().setVisibleLogicalRange(r);
  }});
}}

// ── Crosshair sync ───────────────────────────────────────────────────────────
function syncCrosshair(source, targets) {{
  source.subscribeCrosshairMove(param => {{
    if (!param.point) {{ targets.forEach(t => t.clearCrosshairPosition()); return; }}
    targets.forEach(t => t.setCrosshairPosition(param.point.x, param.time, t.series?.[0] ?? null));
  }});
}}

// ── Topbar OHLC update ───────────────────────────────────────────────────────
let prevClose = null;
function updateTopbar(c) {{
  const fmt = v => v?.toLocaleString("en-IN", {{ maximumFractionDigits: 2 }}) ?? "—";
  document.getElementById("o-val").textContent = fmt(c.open);
  document.getElementById("h-val").textContent = fmt(c.high);
  document.getElementById("l-val").textContent = fmt(c.low);
  document.getElementById("c-val").textContent = fmt(c.close);

  const liveEl = document.getElementById("live-price");
  liveEl.textContent = fmt(c.close);
  liveEl.className = (prevClose !== null && c.close < prevClose) ? "down" : "";
  prevClose = c.close;
}}

function setOHLCFromCrosshair(param, series) {{
  const data = param.seriesData.get(series);
  if (data) updateTopbar(data);
}}

mainChart.subscribeCrosshairMove(param => {{
  if (param.seriesData && param.seriesData.has(candleSeries))
    setOHLCFromCrosshair(param, candleSeries);
}});

// ── Indicator chips ───────────────────────────────────────────────────────────
function buildChips() {{
  const chips = document.getElementById("ind-chips");
  const defs = [
    SHOW_EMA  && [["EMA9","ema9"],["EMA21","ema21"],["EMA50","ema50"],["EMA200","ema200"]],
    SHOW_VWAP && [["VWAP","vwap"]],
    SHOW_RSI  && [["RSI","rsi_line"]],
    SHOW_MACD && [["MACD","macd_line"]],
  ].filter(Boolean).flat();
  defs.forEach(([label, key]) => {{
    const c = document.createElement("div");
    c.className = "chip";
    c.textContent = label;
    c.style.background = P[key] + "22";
    c.style.color = P[key];
    c.style.border = `1px solid ${{P[key]}}44`;
    chips.appendChild(c);
  }});
}}
buildChips();

// ── localStorage range persistence ───────────────────────────────────────────
const LS_KEY = `lwc_range_${{SYMBOL}}_${{TIMEFRAME}}`;
function saveRange() {{
  const r = mainChart.timeScale().getVisibleLogicalRange();
  if (r) localStorage.setItem(LS_KEY, JSON.stringify(r));
}}
function restoreRange() {{
  const raw = localStorage.getItem(LS_KEY);
  if (raw) {{
    try {{
      const r = JSON.parse(raw);
      mainChart.timeScale().setVisibleLogicalRange(r);
    }} catch(e) {{}}
  }}
}}
mainChart.timeScale().subscribeVisibleLogicalRangeChange(saveRange);

// ── WebSocket ────────────────────────────────────────────────────────────────
let ws = null;
let currentTF = TIMEFRAME;
let reconnectTimer = null;
let reconnectDelay = 2000;

const dot = document.getElementById("ws-dot");

function setDot(state) {{
  dot.className = state === "live" ? "live" : state === "error" ? "error" : "";
}}

function connectWS(sym, tf) {{
  if (ws) {{ try {{ ws.close(); }} catch(e) {{}} }}
  const url = `${{WS_BASE}}/${{sym}}/${{tf}}`;
  ws = new WebSocket(url);

  ws.onopen = () => {{
    setDot("live");
    reconnectDelay = 2000;
    document.getElementById("symbol-label").textContent = `${{sym}} · ${{tf}}`;
    clearTimeout(reconnectTimer);
  }};

  ws.onmessage = (ev) => {{
    const msg = JSON.parse(ev.data);
    if (msg.type === "init") {{
      handleInit(msg);
    }} else if (msg.type === "candle_update") {{
      handleUpdate(msg);
    }}
  }};

  ws.onclose = () => {{
    setDot("error");
    reconnectTimer = setTimeout(() => connectWS(sym, tf), reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);
  }};

  ws.onerror = () => setDot("error");
}}

// ── Init: full history render ─────────────────────────────────────────────────
function handleInit(msg) {{
  const candles = msg.candles || [];
  if (!candles.length) return;

  candleSeries.setData(candles);

  if (SHOW_VOL && volSeries) {{
    volSeries.setData(candles.map(c => ({{
      time:  c.time,
      value: c.volume,
      color: c.close >= c.open ? P.bullish + "55" : P.bearish + "55",
    }})));
  }}

  const ind = msg.indicators || {{}};
  const times = ind.timestamps || candles.map(c => c.time);

  function toPoints(arr) {{
    return (arr || []).map((v, i) => v !== null ? {{ time: times[i], value: v }} : null).filter(Boolean);
  }}

  if (SHOW_EMA) {{
    ema9s?.setData(toPoints(ind.ema_9));
    ema21s?.setData(toPoints(ind.ema_21));
    ema50s?.setData(toPoints(ind.ema_50));
    ema200s?.setData(toPoints(ind.ema_200));
  }}
  if (SHOW_VWAP) {{
    vwapS?.setData(toPoints(ind.vwap));
  }}
  if (SHOW_RSI && rsiSeries) {{
    rsiSeries.setData(toPoints(ind.rsi));
    // Add static 70/30 reference lines
    if (times.length > 0) {{
      const first = times[0], last = times[times.length - 1];
      const ob70 = [{{ time: first, value: 70 }}, {{ time: last, value: 70 }}];
      const os30 = [{{ time: first, value: 30 }}, {{ time: last, value: 30 }}];
      // Would need separate line series — approximated via markup
    }}
  }}
  if (SHOW_MACD) {{
    macdLineSeries?.setData(toPoints(ind.macd));
    macdSignalSeries?.setData(toPoints(ind.macd_signal));
    macdHistSeries?.setData((ind.macd_hist || []).map((v, i) => v !== null ? {{
      time:  times[i],
      value: v,
      color: v >= 0 ? P.macd_u : P.macd_d,
    }} : null).filter(Boolean));
  }}

  // Update topbar with latest candle
  if (candles.length) updateTopbar(candles[candles.length - 1]);

  restoreRange();
  mainChart.timeScale().scrollToRealTime();
}}

// ── Update: single candle tick (incremental) ───────────────────────────────────
function handleUpdate(msg) {{
  const c   = msg.candle;
  const ind = msg.indicators || {{}};

  // O(1) update — no full redraw
  candleSeries.update(c);

  if (SHOW_VOL && volSeries) {{
    volSeries.update({{
      time:  c.time,
      value: c.volume,
      color: c.close >= c.open ? P.bullish + "55" : P.bearish + "55",
    }});
  }}

  const ts = ind.timestamp ?? c.time;

  if (SHOW_EMA) {{
    if (ind.ema_9   !== null && ind.ema_9   !== undefined) ema9s?.update({{ time: ts, value: ind.ema_9   }});
    if (ind.ema_21  !== null && ind.ema_21  !== undefined) ema21s?.update({{ time: ts, value: ind.ema_21  }});
    if (ind.ema_50  !== null && ind.ema_50  !== undefined) ema50s?.update({{ time: ts, value: ind.ema_50  }});
    if (ind.ema_200 !== null && ind.ema_200 !== undefined) ema200s?.update({{ time: ts, value: ind.ema_200 }});
  }}
  if (SHOW_VWAP && ind.vwap !== null && ind.vwap !== undefined) {{
    vwapS?.update({{ time: ts, value: ind.vwap }});
  }}
  if (SHOW_RSI && ind.rsi !== null && ind.rsi !== undefined) {{
    rsiSeries?.update({{ time: ts, value: ind.rsi }});
  }}
  if (SHOW_MACD) {{
    if (ind.macd       !== null && ind.macd       !== undefined) macdLineSeries?.update({{ time: ts, value: ind.macd }});
    if (ind.macd_signal !== null && ind.macd_signal !== undefined) macdSignalSeries?.update({{ time: ts, value: ind.macd_signal }});
    if (ind.macd_hist  !== null && ind.macd_hist  !== undefined) {{
      macdHistSeries?.update({{ time: ts, value: ind.macd_hist, color: ind.macd_hist >= 0 ? P.macd_u : P.macd_d }});
    }}
  }}

  updateTopbar(c);
  // Price change display
  const chg = ((c.close - c.open) / c.open * 100).toFixed(2);
  document.getElementById("price-change").textContent = (chg >= 0 ? "+" : "") + chg + "%";
  document.getElementById("price-change").style.color = chg >= 0 ? P.bullish : P.bearish;
}}

// ── Timeframe switch ──────────────────────────────────────────────────────────
function switchTF(tf) {{
  document.querySelectorAll(".tf-btn").forEach(b => {{
    b.classList.toggle("active", b.textContent === tf);
  }});
  currentTF = tf;
  // Send switch request to backend via WS
  if (ws && ws.readyState === WebSocket.OPEN) {{
    ws.send(JSON.stringify({{ action: "switch_timeframe", timeframe: tf }}));
  }} else {{
    connectWS(SYMBOL, tf);
  }}
}}

// ── Responsive resize ─────────────────────────────────────────────────────────
const ro = new ResizeObserver(() => {{
  mainChart.applyOptions({{ width: mainEl.offsetWidth }});
}});
ro.observe(mainEl);

// ── Connect ───────────────────────────────────────────────────────────────────
connectWS(SYMBOL, TIMEFRAME);
</script>
</body>
</html>
"""


def render_live_chart(
    symbol:       str   = "BTCUSD",
    timeframe:    str   = "1m",
    height:       int   = 720,
    show_volume:  bool  = True,
    show_rsi:     bool  = True,
    show_macd:    bool  = True,
    show_ema:     bool  = True,
    show_vwap:    bool  = True,
    backend_host: str   = "localhost",
    backend_port: int   = 8000,
) -> None:
    """
    Render the live WebSocket chart in Streamlit.

    The chart connects directly from the browser to FastAPI — no Streamlit
    reruns occur during live price updates.
    """
    ws_url = f"ws://{backend_host}:{backend_port}/ws"
    html = _build_html(
        symbol=symbol,
        timeframe=timeframe,
        height=height,
        show_volume=show_volume,
        show_rsi=show_rsi,
        show_macd=show_macd,
        show_ema=show_ema,
        show_vwap=show_vwap,
        backend_ws=ws_url,
    )
    components.html(html, height=height + 4, scrolling=False)
