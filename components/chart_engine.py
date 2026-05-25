"""
Chart Engine adapter — multi-provider chart rendering with persistence.

Engines
-------
  Lightweight   Institutional chart (Lightweight Charts v4, built-in MA/RSI/MACD/
                ATR/ADX toolbar, SMC zones, Pine overlays, localStorage workspace).
  TradingView   TradingView Advanced Chart Widget (free iframe embed — full TV
                indicator library, drawing tools, TradingView workspace cloud save).
  IQ Chart      Aligned multi-pane chart (Lightweight Charts v4 with fixed
                price-scale widths for pixel-perfect pane sync; renders SMC zones
                and Pine-computed overlays from the sidebar without an internal
                indicator bar, keeping the canvas clean for custom Pine scripts).

Architecture
------------
  render_chart(engine, symbol, df, timeframe, ...) dispatches to the right adapter.
  render_engine_selector(prefix, db) renders the selectbox and persists the choice.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


# ── Engine registry ────────────────────────────────────────────────────────────

ENGINES: List[str] = ["Lightweight", "TradingView", "IQ Chart"]

# ── Adaptive engine routing ────────────────────────────────────────────────────

_INDIAN_SUFFIXES = (".NS", ".BO")
_INDIAN_INDICES  = {"^NSEI", "^NSEBANK", "^BSESN"}


def is_indian_symbol(symbol: str) -> bool:
    """Return True for NSE/BSE stocks and Indian indices."""
    return (
        any(symbol.endswith(s) for s in _INDIAN_SUFFIXES)
        or symbol in _INDIAN_INDICES
    )


def resolve_engine(engine: str, symbol: str) -> str:
    """
    Return the effective engine for the given symbol.
    TradingView is blocked for Indian equities (NSE/BSE licensing restrictions).
    Automatically falls back to Lightweight for Indian stocks/indices.
    """
    if engine == "TradingView" and is_indian_symbol(symbol):
        return "Lightweight"
    return engine

_ICONS: Dict[str, str] = {
    "Lightweight": "⚡",
    "TradingView": "📊",
    "IQ Chart":    "🔬",
}

_DESCRIPTIONS: Dict[str, str] = {
    "Lightweight": "Built-in MA/RSI/MACD · SMC zones · localStorage restore",
    "TradingView": "Full TV indicator library · drawing tools · cloud workspace",
    "IQ Chart":    "Aligned panes · Pine overlays · clean canvas",
}


# ── Symbol / interval converters ───────────────────────────────────────────────

_TV_SYMBOL_MAP: Dict[str, str] = {
    "GC=F":     "TVC:GOLD",
    "SI=F":     "TVC:SILVER",
    "CL=F":     "TVC:USOIL",
    "NG=F":     "TVC:NATURALGAS",
    "BTC-USD":  "BITSTAMP:BTCUSD",
    "ETH-USD":  "BITSTAMP:ETHUSD",
    "BNB-USD":  "BINANCE:BNBUSDT",
    "^NSEI":    "NSE:NIFTY50",
    "^NSEBANK": "NSE:BANKNIFTY",
    "^BSESN":   "BSE:SENSEX",
    "^DJI":     "DJ:DJI",
    "^GSPC":    "SP:SPX",
    "^IXIC":    "NASDAQ:NDX",
}

_TV_INTERVAL_MAP: Dict[str, str] = {
    "1m":  "1",
    "5m":  "5",
    "15m": "15",
    "30m": "30",
    "1H":  "60",
    "4H":  "240",
    "1D":  "D",
    "1W":  "W",
}


def _to_tv_symbol(yf_symbol: str) -> str:
    if yf_symbol in _TV_SYMBOL_MAP:
        return _TV_SYMBOL_MAP[yf_symbol]
    if yf_symbol.endswith(".NS"):
        return "NSE:" + yf_symbol[:-3]
    if yf_symbol.endswith(".BO"):
        return "BSE:" + yf_symbol[:-3]
    return yf_symbol


def _to_tv_interval(tf_key: str) -> str:
    return _TV_INTERVAL_MAP.get(tf_key, "D")


# ── Engine selector widget ─────────────────────────────────────────────────────

def get_engine(prefix: str) -> str:
    """Return the currently selected engine for the given page prefix."""
    return st.session_state.get(f"{prefix}_chart_engine", "Lightweight")


def render_engine_selector(prefix: str, db=None) -> str:
    """
    Render the chart-engine selectbox and persist the choice.

    Args:
        prefix: page namespace — "cs" for Chart Studio, "cfd" for CFD Market.
        db:     PineScriptDB instance for cross-session persistence (optional).

    Returns:
        Selected engine name ("Lightweight" | "TradingView" | "IQ Chart").
    """
    ss_key     = f"{prefix}_chart_engine"
    widget_key = f"{prefix}_engine_selectbox"
    current    = st.session_state.get(ss_key, "Lightweight")

    chosen = st.selectbox(
        "Engine",
        ENGINES,
        index=ENGINES.index(current) if current in ENGINES else 0,
        key=widget_key,
        label_visibility="collapsed",
        format_func=lambda e: f"{_ICONS[e]} {e}",
        help="\n".join(f"{_ICONS[e]} {e}: {_DESCRIPTIONS[e]}" for e in ENGINES),
    )

    if chosen != current:
        st.session_state[ss_key] = chosen
        if db is not None:
            try:
                db.set_preference(f"{prefix}_chart_engine", chosen)
            except Exception:
                pass
        st.rerun()

    return chosen


# ── TradingView renderer ───────────────────────────────────────────────────────

def _build_tv_html(tv_symbol: str, interval: str, height: int) -> str:
    uid       = abs(hash(f"{tv_symbol}:{interval}")) % 10 ** 9
    widget_id = f"tvw_{uid}"
    tv_link   = f"https://www.tradingview.com/chart/?symbol={tv_symbol}"

    cfg = json.dumps(
        {
            "autosize":            True,
            "symbol":              tv_symbol,
            "interval":            interval,
            "timezone":            "Asia/Kolkata",
            "theme":               "dark",
            "style":               "1",
            "locale":              "en",
            "backgroundColor":     "#080d17",
            "gridColor":           "rgba(30,45,69,0.5)",
            "withdateranges":      True,
            "allow_symbol_change": True,
            "save_image":          True,
            "calendar":            False,
            "hide_legend":         False,
            "support_host":        "https://www.tradingview.com",
        },
        indent=2,
    )
    # NOTE: script tag must NOT use async — TradingView's embed script reads its
    # config via document.currentScript.textContent, which is null under async.
    return f"""<!DOCTYPE html>
<!-- {tv_symbol}:{interval}:{uid} -->
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
html,body{{background:#080d17;height:{height}px;overflow:hidden;position:relative;}}
.tw{{width:100%;height:{height}px;}}
.tradingview-widget-copyright{{display:none!important;}}
#tvfb{{
  display:none;position:absolute;inset:0;z-index:999;
  background:rgba(8,13,23,0.97);
  flex-direction:column;align-items:center;justify-content:center;gap:12px;
  font-family:system-ui,sans-serif;text-align:center;padding:24px;
}}
#tvfb.show{{display:flex;}}
.tvfb-icon{{font-size:2.4rem;}}
.tvfb-title{{color:#e2e8f0;font-size:1.05rem;font-weight:700;}}
.tvfb-sub{{color:#94a3b8;font-size:0.82rem;max-width:340px;line-height:1.5;}}
.tvfb-btn{{
  margin-top:6px;padding:8px 20px;border-radius:6px;
  background:#2563eb;color:#fff;text-decoration:none;
  font-size:0.84rem;font-weight:600;
  border:1px solid #3b82f6;
}}
.tvfb-btn:hover{{background:#1d4ed8;}}
.tvfb-note{{color:#64748b;font-size:0.74rem;margin-top:2px;}}
</style>
</head>
<body>
<!-- fallback overlay: shown by JS when TV emits an error for this symbol -->
<div id="tvfb">
  <div class="tvfb-icon">⚠</div>
  <div class="tvfb-title">TradingView Login Required</div>
  <div class="tvfb-sub">Indian stocks (NSE / BSE) require a free TradingView account due to exchange data licensing. Sign in on TradingView to unlock this symbol.</div>
  <a class="tvfb-btn" href="{tv_link}" target="_blank">Open {tv_symbol} on TradingView ↗</a>
  <div class="tvfb-note">Or switch to the Lightweight engine (no login needed).</div>
</div>
<div class="tw" id="{widget_id}">
  <div class="tradingview-widget-container" style="width:100%;height:100%;">
    <div id="{widget_id}_w" class="tradingview-widget-container__widget" style="width:100%;height:100%;"></div>
    <script type="text/javascript"
      src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js">
{cfg}
    </script>
  </div>
</div>
<script>
(function(){{
  var fb = document.getElementById('tvfb');
  var ERRORS = ['only available on TradingView','Symbol not found','cannot be displayed'];
  function _hasErr(){{
    var t = document.body ? (document.body.innerText || '') : '';
    for(var i=0;i<ERRORS.length;i++){{ if(t.indexOf(ERRORS[i])!==-1) return true; }}
    return false;
  }}
  function _show(){{ if(fb) fb.classList.add('show'); }}
  try{{
    var obs = new MutationObserver(function(){{ if(_hasErr()){{ _show(); obs.disconnect(); }} }});
    obs.observe(document.body,{{subtree:true,childList:true,characterData:true}});
    setTimeout(function(){{obs.disconnect();}},20000);
  }}catch(e){{}}
  setTimeout(function(){{ if(_hasErr()) _show(); }},3500);
  setTimeout(function(){{ if(_hasErr()) _show(); }},8000);
}})();
</script>
</body>
</html>"""


def render_tradingview_chart(
    symbol:    str,
    timeframe: str = "1D",
    height:    int = 580,
) -> None:
    tv_sym    = _to_tv_symbol(symbol)
    interval  = _to_tv_interval(timeframe)
    is_india  = tv_sym.startswith(("NSE:", "BSE:"))

    st.markdown(
        f'<div class="ce-engine-badge" data-engine="tv">'
        f'<span class="ce-engine-icon">📊</span>'
        f'<span class="ce-engine-name">TradingView</span>'
        f'<span class="ce-engine-sep">·</span>'
        f'<span class="ce-engine-sym">{tv_sym}</span>'
        f'<span class="ce-engine-sep">·</span>'
        f'<span class="ce-engine-tf">{interval}</span>'
        f'<span class="ce-engine-note">Workspace saved by TradingView</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if is_india:
        tv_login = "https://www.tradingview.com"
        st.markdown(
            f'<div class="tv-india-note">'
            f'<span class="tv-india-icon">ℹ</span>'
            f'Indian stocks (NSE / BSE) require a free '
            f'<a href="{tv_login}" target="_blank">TradingView account ↗</a> '
            f'due to exchange licensing. If the chart shows an error, '
            f'log in on TradingView or switch to the <strong>Lightweight</strong> engine.'
            f'</div>',
            unsafe_allow_html=True,
        )

    # components.html() sets srcdoc — React diffs the content so the iframe
    # fully reloads whenever the HTML changes (symbol or interval changed).
    components.html(
        _build_tv_html(tv_sym, interval, height),
        height=height + 8,
        scrolling=False,
    )


# ── IQ Chart renderer ──────────────────────────────────────────────────────────

def render_iq_chart(
    df:             pd.DataFrame,
    symbol:         str,
    timeframe:      str             = "1D",
    height:         int             = 580,
    show_volume:    bool            = True,
    zones:          Optional[List[Dict]] = None,
    extra_overlays: Optional[List[Dict]] = None,
) -> None:
    """Render the aligned multi-pane chart via chartiq_chart.render_chart()."""
    from components.chartiq_chart import render_chart as _ciq_render

    # Convert Pine-computed overlays to chartiq_chart's overlay format
    overlays: List[Dict] = []
    if extra_overlays:
        for ov in extra_overlays:
            if ov.get("data"):
                overlays.append(
                    {
                        "data":      ov["data"],
                        "color":     ov.get("color",     "#00d4aa"),
                        "linewidth": ov.get("linewidth", 1),
                        "label":     ov.get("label",     ""),
                    }
                )

    clean_sym = symbol.replace(".NS", "").replace(".BO", "")
    st.markdown(
        f'<div class="ce-engine-badge" data-engine="iq">'
        f'<span class="ce-engine-icon">🔬</span>'
        f'<span class="ce-engine-name">IQ Chart</span>'
        f'<span class="ce-engine-sep">·</span>'
        f'<span class="ce-engine-sym">{clean_sym}</span>'
        f'<span class="ce-engine-note">Aligned panes · Pine overlays via sidebar</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    _ciq_render(
        df          = df,
        symbol      = symbol,
        overlays    = overlays,
        panes       = [],          # user adds pane indicators via Pine Manager
        height      = height,
        show_volume = show_volume,
        timeframe   = timeframe,
        zones       = zones or [],
    )


# ── Main dispatch ──────────────────────────────────────────────────────────────

def render_chart(
    engine:         str,
    symbol:         str,
    df:             pd.DataFrame,
    timeframe:      str             = "1D",
    height:         int             = 580,
    display_name:   str             = "",
    show_volume:    bool            = True,
    zones:          Optional[List[Dict]] = None,
    extra_overlays: Optional[List[Dict]] = None,
) -> None:
    """
    Dispatch chart rendering to the correct engine adapter.

    All three engines receive the same arguments; each adapter uses only
    what it needs and ignores the rest so the calling page stays unchanged.
    """
    # Auto-route: Indian equities must not use TradingView (NSE/BSE licensing).
    effective = resolve_engine(engine, symbol)

    if effective == "TradingView":
        render_tradingview_chart(symbol, timeframe, height)

    elif effective == "IQ Chart":
        render_iq_chart(
            df             = df,
            symbol         = display_name or symbol,
            timeframe      = timeframe,
            height         = height,
            show_volume    = show_volume,
            zones          = zones,
            extra_overlays = extra_overlays,
        )

    else:
        from components.institutional_chart import render_institutional_chart
        render_institutional_chart(
            symbol         = symbol,
            timeframe      = timeframe,
            height         = height,
            display_name   = display_name,
            show_volume    = show_volume,
            zones          = zones,
            extra_overlays = extra_overlays,
        )
