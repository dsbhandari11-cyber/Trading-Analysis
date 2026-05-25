"""
Chart Studio — Indian Stocks professional trading terminal.

Layout:
  ┌─ Page header ──────────────────────────────────────────────────────────────┐
  ├─ Toolbar: symbol | height | vol | log | refresh ───────────────────────────┤
  ├─ TF strip: 1m | 5m | 15m | 30m | 1H | 4H | 1D | 1W ──────────────────────┤
  ├─ divider ──────────────────────────────────────────────────────────────────┤
  ├─ Chart (3.2) ──────────────────────────────────────────┬─ Panel (0.9) ────┤
  │  indicator chips · chart · stock strip                 │ Pine Manager     │
  │                                                        │ SMC toggles      │
  │                                                        │ Saved layouts    │
  ├─ Order Blocks panel ───────────────────────────────────────────────────────┤
  ├─ Fair Value Gaps panel ────────────────────────────────────────────────────┤
  ├─ Market Structure panel ───────────────────────────────────────────────────┤
  ├─ Institutional Analysis panel ─────────────────────────────────────────────┤
  └─ Ideal Entry — React to Liquidity Behavior ────────────────────────────────┘
"""

from __future__ import annotations

import time as _time_mod
import datetime as _dt

import numpy as np
import pandas as pd
import streamlit as st
from typing import Dict, List, Optional

from data.fetcher import get_history, get_ticker_prices
from data.news import fetch_all_headlines
from data.stocks_list import SYMBOL_NAMES, get_display_name
from data.pine_db import PineScriptDB
from data.smc_analysis import (
    detect_order_blocks,
    detect_fvg,
    detect_market_structure,
    institutional_analysis,
)
from data.entry_engine import generate_entry_signal
from core.data_manager import get_data_manager
from core.indicator_cache import get_indicator_cache
from components.institutional_chart import render_institutional_chart
from components.chart_sidebar import filter_zones_by_smc
from components.pine_manager import get_pine_db
from utils.helpers import clean_symbol


# ── CFD / Global asset registry (merged from CFD Market page) ─────────────────

_CS_CFD_ASSETS: dict = {
    "XAUUSD":    {"symbol": "GC=F",     "name": "Gold",       "icon": "Au",  "cat": "Metals", "unit": "USD/oz"},
    "XAGUSD":    {"symbol": "SI=F",     "name": "Silver",     "icon": "Ag",  "cat": "Metals", "unit": "USD/oz"},
    "BTCUSD":    {"symbol": "BTC-USD",  "name": "Bitcoin",    "icon": "BTC", "cat": "Crypto", "unit": "USD"},
    "ETHUSD":    {"symbol": "ETH-USD",  "name": "Ethereum",   "icon": "ETH", "cat": "Crypto", "unit": "USD"},
    "NIFTY50":   {"symbol": "^NSEI",    "name": "Nifty 50",   "icon": "N50", "cat": "Index",  "unit": "INR"},
    "BANKNIFTY": {"symbol": "^NSEBANK", "name": "Bank Nifty", "icon": "BNK", "cat": "Index",  "unit": "INR"},
}

_CFD_ASSET_SYMBOLS = {v["symbol"] for v in _CS_CFD_ASSETS.values()}


@st.cache_data(ttl=60, show_spinner=False)
def _cfd_quick_price(symbol: str) -> tuple:
    """Fetch latest close and 1-day % change for a CFD asset card."""
    try:
        df = get_history(symbol, period="2d", interval="1d")
        if df is not None and len(df) >= 2:
            price = float(df["Close"].iloc[-1])
            prev  = float(df["Close"].iloc[-2])
            pct   = (price - prev) / prev * 100 if prev else 0.0
            return price, pct
    except Exception:
        pass
    return 0.0, 0.0


def _fmt_cfd_price(price: float, symbol: str) -> str:
    if symbol in ("BTC-USD", "ETH-USD"):
        return f"{price:,.2f}"
    return f"{price:,.4f}" if price < 100 else f"{price:,.2f}"


# ── Timeframe map ─────────────────────────────────────────────────────────────

_TF_MAP: Dict[str, dict] = {
    "1m":  {"period": "7d",   "interval": "1m",  "label": "1 Min  · 7d",   "resample": None},
    "5m":  {"period": "60d",  "interval": "5m",  "label": "5 Min  · 60d",  "resample": None},
    "15m": {"period": "60d",  "interval": "15m", "label": "15 Min · 60d",  "resample": None},
    "30m": {"period": "60d",  "interval": "30m", "label": "30 Min · 60d",  "resample": None},
    "1H":  {"period": "730d", "interval": "60m", "label": "1 Hour · 2y",   "resample": None},
    "4H":  {"period": "730d", "interval": "60m", "label": "4 Hour · 2y",   "resample": "4h"},
    "1D":  {"period": "5y",   "interval": "1d",  "label": "Daily  · 5y",   "resample": None},
    "1W":  {"period": "10y",  "interval": "1wk", "label": "Weekly · 10y",  "resample": None},
}

_TF_KEYS = list(_TF_MAP.keys())

_CHART_HEIGHTS: Dict[str, int] = {
    "Compact":  460,
    "Standard": 580,
    "Expanded": 700,
    "Full":     840,
}


# ── Page entry point ──────────────────────────────────────────────────────────

def render_chart_studio() -> None:
    db = get_pine_db()
    _init_state(db)
    _sync_workspace_to_url()   # persist to URL params every render (survives page reload)

    st.markdown("""
<div class="cfd-page-header">
  <div class="cfd-page-title">
    <span class="cfd-title-diamond">◈</span>
    Chart <span class="cfd-title-accent">Studio</span>
  </div>
  <div class="cfd-page-subtitle">NSE · BSE · Global Assets · Smart Money Concepts · Institutional Analysis</div>
</div>""", unsafe_allow_html=True)

    # ── CFD / Global asset cards row ──────────────────────────────────────────
    _render_cfd_asset_strip()

    _render_toolbar(db)
    # TF strip now also returns SMC config (checkboxes are inline)
    smc_config = _render_tf_strip(db)

    st.markdown('<div class="cs-divider"></div>', unsafe_allow_html=True)

    symbol = st.session_state.get("cs_symbol", "RELIANCE.NS")
    tf_key = st.session_state.get("cs_timeframe", "1D")
    tf     = _TF_MAP.get(tf_key, _TF_MAP["1D"])

    dm = get_data_manager()
    ic = get_indicator_cache()

    # Non-blocking read from background store; fall back to direct fetch on cold start
    df = dm.get_df(
        symbol, tf["period"], tf["interval"],
        resample=tf.get("resample"), ttl=60, priority=10,
    )
    if df is None:
        with st.spinner(f"Loading {clean_symbol(symbol)} {tf['label']}…"):
            df = _get_chart_data(symbol, tf["period"], tf["interval"], tf.get("resample"))

    if df is None or df.empty:
        st.warning(
            f"No data for **{clean_symbol(symbol)}** ({tf['label']}). "
            "Try a different symbol or timeframe."
        )
        return

    sym_display = clean_symbol(symbol)
    _ckey = f"cs_{symbol}_{tf_key}"
    _h    = dm.get_hash(symbol, tf["period"], tf["interval"], tf.get("resample"))

    # SMC computations — hash-gated, skipped when candle data is unchanged
    ob_data  = ic.compute(f"ob_{_ckey}",  _h, detect_order_blocks,    df)
    fvg_data = ic.compute(f"fvg_{_ckey}", _h, detect_fvg,             df)
    ms_data  = ic.compute(f"ms_{_ckey}",  _h, detect_market_structure, df)
    ai_data  = ic.compute(f"ai_{_ckey}",  _h, institutional_analysis,  df)
    zones    = _build_zones(ob_data, fvg_data, int(_time_mod.time()))

    # ── Tab navigation ────────────────────────────────────────────────────────
    tab_chart, tab_perf, tab_fund, tab_fin, tab_peers, tab_news, tab_notes = st.tabs([
        "Chart", "Performance", "Fundamentals",
        "Financials", "Peers", "News", "Notes",
    ])

    with tab_chart:
        # smc_config already computed in _render_tf_strip() above the tabs
        visible_zones = filter_zones_by_smc(zones, smc_config)

        chart_col, panel_col = st.columns([3.0, 1.1], gap="small")

        with chart_col:
            height = _CHART_HEIGHTS.get(st.session_state.get("cs_chart_height_label", "Standard"), 580)
            engine = st.session_state.get("cs_chart_engine", "Lightweight")

            from components.chart_engine import render_chart as _render_chart
            _render_chart(
                engine         = engine,
                symbol         = symbol,
                df             = df,
                timeframe      = tf_key,
                height         = height,
                display_name   = sym_display,
                show_volume    = st.session_state.get("cs_show_volume", True),
                zones          = visible_zones,
                extra_overlays = None,
            )
            _render_stock_strip(symbol, df)

        with panel_col:
            _render_cs_sentiment_panel(df, ai_data)

        # ── SMC Analysis panels ───────────────────────────────────────────────
        st.markdown('<div class="cfd-panels-divider"></div>', unsafe_allow_html=True)
        _render_order_block_panel(ob_data)
        st.markdown('<div class="cfd-panels-divider"></div>', unsafe_allow_html=True)
        _render_market_structure_panel(ms_data, df)
        st.markdown('<div class="cfd-panels-divider"></div>', unsafe_allow_html=True)
        _render_institutional_panel(ai_data, df)
        st.markdown('<div class="cfd-panels-divider"></div>', unsafe_allow_html=True)
        _render_ideal_entry_section(sym_display, symbol, df, ob_data, fvg_data, ms_data)

    with tab_perf:
        _render_performance_tab(df, sym_display)

    with tab_fund:
        _render_fundamentals_tab(symbol, sym_display)

    with tab_fin:
        _render_financials_tab(symbol, sym_display)

    with tab_peers:
        _render_peers_tab(symbol, sym_display)

    with tab_news:
        _render_news_tab(symbol, sym_display)

    with tab_notes:
        _render_notes_tab(symbol, sym_display)


# ── CFD / Global asset card strip ────────────────────────────────────────────

def _render_cfd_asset_strip() -> None:
    """Row of CFD/global asset cards above the stock selector toolbar."""
    current_sym = st.session_state.get("cs_symbol", "RELIANCE.NS")

    cols = st.columns(len(_CS_CFD_ASSETS), gap="small")
    for col, (key, asset) in zip(cols, _CS_CFD_ASSETS.items()):
        active = (current_sym == asset["symbol"])
        price, pct = _cfd_quick_price(asset["symbol"])

        color    = "#00d4aa" if pct >= 0 else "#f43f5e"
        arrow    = "▲" if pct >= 0 else "▼"
        border   = "#00d4aa" if active else "#1e2d45"
        bg       = "rgba(0,212,170,0.07)" if active else "#0d1321"
        badge_bg = "#00d4aa" if active else "#1e2d45"
        badge_cl = "#080d17" if active else "#64748b"
        cat_color = (
            "#4d9de0" if asset["cat"] == "Crypto"
            else "#f59e0b" if asset["cat"] == "Metals"
            else "#a855f7"
        )
        price_str = _fmt_cfd_price(price, asset["symbol"]) if price else "—"

        with col:
            st.markdown(f"""
<div class="cfd-asset-card" style="border-color:{border};background:{bg};">
  <div class="cfd-asset-card-top">
    <span class="cfd-asset-icon" style="background:{badge_bg};color:{badge_cl};">{asset['icon']}</span>
    <span class="cfd-asset-cat" style="color:{cat_color};">{asset['cat']}</span>
  </div>
  <div class="cfd-asset-name">{asset['name']}</div>
  <div class="cfd-asset-ticker">{key}</div>
  <div class="cfd-asset-price">{price_str}</div>
  <div class="cfd-asset-chg" style="color:{color};">{arrow} {abs(pct):.2f}%</div>
  <div class="cfd-asset-unit">{asset['unit']}</div>
</div>""", unsafe_allow_html=True)

            if st.button(
                "Active" if active else "Select",
                key=f"cs_cfd_{key}",
                use_container_width=True,
                disabled=active,
            ):
                st.session_state.cs_symbol = asset["symbol"]
                try:
                    get_pine_db().set_preference("last_symbol", asset["symbol"])
                except Exception:
                    pass
                _cfd_quick_price.clear()
                _get_chart_data.clear()
                st.rerun()


# ── Toolbar ───────────────────────────────────────────────────────────────────

def _render_toolbar(db: PineScriptDB) -> None:
    st.markdown('<div class="cs-toolbar">', unsafe_allow_html=True)

    sym_col, h_col, vol_col, log_col, eng_col = st.columns([3.8, 1.1, 0.85, 0.6, 1.4])

    with sym_col:
        all_opts = {
            f"{sym.replace('.NS','').replace('.BO','')} — {name}": sym
            for sym, name in sorted(SYMBOL_NAMES.items(), key=lambda x: x[0])
        }
        current_sym = st.session_state.get("cs_symbol", "RELIANCE.NS")
        is_cfd      = current_sym in _CFD_ASSET_SYMBOLS
        opts_list   = [""] + list(all_opts.keys())

        if is_cfd:
            # ── CFD / Global asset is active ──────────────────────────────────
            # Use a SEPARATE widget key ("cs_symbol_search") so that
            # "cs_symbol_select" — which may hold a stale stock label in the
            # Streamlit frontend — is never rendered and is therefore
            # auto-removed from session state by Streamlit's widget cleanup.
            # This permanently breaks the stale-state feedback loop that was
            # overriding cs_symbol back to the stock on every auto-refresh.
            cfd_info = next((a for a in _CS_CFD_ASSETS.values() if a["symbol"] == current_sym), None)
            cfd_name = cfd_info["name"] if cfd_info else current_sym
            chosen = st.selectbox(
                "symbol", opts_list,
                index=0,                  # always show placeholder in CFD mode
                key="cs_symbol_search",   # DIFFERENT key from stock-mode widget
                label_visibility="collapsed",
                placeholder=f"◈ {cfd_name} active  ·  Search NSE/BSE stocks…",
            )
            if chosen:
                new_sym = all_opts.get(chosen)
                if new_sym and new_sym != current_sym:
                    st.session_state.cs_symbol = new_sym
                    db.set_preference("last_symbol", new_sym)
                    st.rerun()
        else:
            # ── Stock is active ───────────────────────────────────────────────
            # "cs_symbol_search" (CFD-mode key) is auto-removed by Streamlit
            # when switching back here, so the CFD→stock transition is also
            # stale-state-free.
            current_label = next((k for k, v in all_opts.items() if v == current_sym), "")
            chosen = st.selectbox(
                "symbol", opts_list,
                index=opts_list.index(current_label) if current_label in opts_list else 0,
                key="cs_symbol_select",
                label_visibility="collapsed",
                placeholder="🔍 Symbol…",
            )
            if chosen:
                new_sym = all_opts.get(chosen)
                if new_sym and new_sym != current_sym:
                    st.session_state.cs_symbol = new_sym
                    db.set_preference("last_symbol", new_sym)
                    st.rerun()

    with h_col:
        ch = st.selectbox(
            "Height", list(_CHART_HEIGHTS.keys()),
            index=list(_CHART_HEIGHTS.keys()).index(
                st.session_state.get("cs_chart_height_label", "Standard")
            ),
            key="cs_height_select",
            label_visibility="collapsed",
        )
        st.session_state.cs_chart_height_label = ch

    with vol_col:
        show_vol = st.checkbox(
            "Vol",
            value=st.session_state.get("cs_show_volume", True),
            key="cs_vol_toggle",
        )
        st.session_state.cs_show_volume = show_vol

    with log_col:
        st.checkbox(
            "Log",
            value=st.session_state.get("cs_log_scale", False),
            key="cs_log_toggle",
        )

    with eng_col:
        from components.chart_engine import render_engine_selector
        render_engine_selector("cs", db=db)

    st.markdown('</div>', unsafe_allow_html=True)


# ── TF slider + inline SMC controls ──────────────────────────────────────────

def _render_tf_strip(db: PineScriptDB) -> Dict:
    """Render timeframe slider with SMC OB toggle inline. Returns smc_config dict."""
    cur = st.session_state.get("cs_timeframe", "1D")
    safe_cur = cur if cur in _TF_KEYS else "1D"

    if "cs_smc_show_ob" not in st.session_state:
        st.session_state["cs_smc_show_ob"] = True

    # Layout: [TF slider] [◈SMC label] [OB toggle] [spacer+info]
    sl_col, smc_lbl, ob_col, info_col = st.columns(
        [2.2, 0.45, 1.05, 4.8], gap="small"
    )

    with sl_col:
        selected = st.select_slider(
            "Timeframe",
            options=_TF_KEYS,
            value=safe_cur,
            key="cs_tf_slider",
            label_visibility="collapsed",
        )

    with smc_lbl:
        st.markdown(
            '<div style="padding-top:9px;color:#4d9de0;font-size:0.7rem;'
            'font-weight:700;white-space:nowrap;">◈ SMC</div>',
            unsafe_allow_html=True,
        )

    with ob_col:
        st.session_state["cs_smc_show_ob"] = st.checkbox(
            "Bull & Bear OB",
            value=st.session_state["cs_smc_show_ob"],
            key="cs_smc_ob_cb",
        )

    with info_col:
        tf_info = _TF_MAP.get(selected, _TF_MAP["1D"])
        st.markdown(
            f'<div class="cs-tf-info">'
            f'Candle: <b style="color:#00d4aa;">{selected}</b>'
            f'&nbsp;·&nbsp;'
            f'Data: <b style="color:#4d9de0;">{tf_info["label"]}</b>'
            f'</div>',
            unsafe_allow_html=True,
        )

    if selected != cur:
        st.session_state.cs_timeframe = selected
        db.set_preference("last_timeframe", selected)
        _get_chart_data.clear()
        st.rerun()

    return {
        "show_ob":   st.session_state["cs_smc_show_ob"],
        "show_fvg":  False,
        "show_ifvg": False,
    }


# ── Stock strip ───────────────────────────────────────────────────────────────

def _render_stock_strip(symbol: str, df: pd.DataFrame) -> None:
    if df is None or df.empty:
        return
    last   = df["Close"].iloc[-1]
    prev   = df["Close"].iloc[-2] if len(df) > 1 else last
    chg    = last - prev
    pct    = (chg / prev * 100) if prev else 0.0
    clr    = "#00d4aa" if chg >= 0 else "#f43f5e"
    arrow  = "▲" if chg >= 0 else "▼"
    high52 = df["High"].max()
    low52  = df["Low"].min()
    vol    = df["Volume"].iloc[-1] if "Volume" in df.columns else 0
    # Use CFD asset name when applicable, fall back to stock name lookup
    cfd_info = next((a for a in _CS_CFD_ASSETS.values() if a["symbol"] == symbol), None)
    name = cfd_info["name"] if cfd_info else get_display_name(symbol)

    st.markdown(f"""
<div class="cs-stock-strip">
  <div class="cs-strip-name">{clean_symbol(symbol)}<span class="cs-strip-full"> · {name}</span></div>
  <div class="cs-strip-price">{last:,.2f}</div>
  <div class="cs-strip-chg" style="color:{clr}">{arrow} {abs(chg):,.2f} ({abs(pct):.2f}%)</div>
  <div class="cs-strip-stat"><span>H</span>{high52:,.2f}</div>
  <div class="cs-strip-stat"><span>L</span>{low52:,.2f}</div>
  <div class="cs-strip-stat"><span>Vol</span>{_fmt_vol(vol)}</div>
  <div class="cs-strip-stat"><span>Bars</span>{len(df)}</div>
</div>""", unsafe_allow_html=True)


# ── Zone builder ──────────────────────────────────────────────────────────────

def _build_zones(ob: Dict, fvg: Dict, ts_now: int) -> List[Dict]:
    far_future = ts_now + 86400 * 45
    zones: List[Dict] = []

    for o in ob.get("active_bullish", []):
        zones.append({
            "time_start":   o["time_start"],
            "time_end":     far_future,
            "high":         o["high"],
            "low":          o["low"],
            "fill_color":   "#00d4aa14",
            "border_color": "#00d4aa70",
            "label":        "Bull OB",
            "label_color":  "#00d4aacc",
        })

    for o in ob.get("active_bearish", []):
        zones.append({
            "time_start":   o["time_start"],
            "time_end":     far_future,
            "high":         o["high"],
            "low":          o["low"],
            "fill_color":   "#f43f5e14",
            "border_color": "#f43f5e70",
            "label":        "Bear OB",
            "label_color":  "#f43f5ecc",
        })

    # FVG / IFVG zones removed — section eliminated per design spec.
    # fvg parameter retained in signature for backward compatibility.
    _ = fvg

    return zones


# ── Order Block panel ─────────────────────────────────────────────────────────

def _render_order_block_panel(ob: Dict) -> None:
    bull_obs = ob.get("active_bullish", [])
    bear_obs = ob.get("active_bearish", [])

    st.markdown("""
<div class="cfd-panel-header">
  <span class="cfd-panel-icon" style="background:#00d4aa22;color:#00d4aa;">OB</span>
  <span class="cfd-panel-title">Order Blocks</span>
  <span class="cfd-panel-desc">Institutional demand/supply zones — unmitigated candles before impulse moves</span>
</div>""", unsafe_allow_html=True)

    if not bull_obs and not bear_obs:
        st.markdown('<div class="cfd-empty-state">No active order blocks detected</div>',
                    unsafe_allow_html=True)
        return

    cards_html = '<div class="ms-sig-grid" style="grid-template-columns:repeat(auto-fill,minmax(160px,1fr));">'

    for o in reversed(bull_obs[-5:]):
        sb  = int(o.get("strength", 50))
        clr = "#00d4aa"
        cards_html += f"""
<div class="ms-sig-card" style="border-top:2px solid {clr};box-shadow:0 2px 8px {clr}18;">
  <div class="ms-sig-icon" style="color:{clr};">▲ OB</div>
  <div class="ms-sig-label" style="color:{clr};">BULLISH</div>
  <div class="ms-sig-sub">{o['high']:,.2f} — {o['low']:,.2f}</div>
  <div class="cfd-ob-strength-bar" style="margin-top:6px;">
    <div class="cfd-ob-strength-fill" style="width:{sb}%;background:{clr};"></div>
  </div>
  <div class="ms-sig-sub" style="margin-top:3px;">Body {sb}%</div>
</div>"""

    for o in reversed(bear_obs[-5:]):
        sb  = int(o.get("strength", 50))
        clr = "#f43f5e"
        cards_html += f"""
<div class="ms-sig-card" style="border-top:2px solid {clr};box-shadow:0 2px 8px {clr}18;">
  <div class="ms-sig-icon" style="color:{clr};">▼ OB</div>
  <div class="ms-sig-label" style="color:{clr};">BEARISH</div>
  <div class="ms-sig-sub">{o['high']:,.2f} — {o['low']:,.2f}</div>
  <div class="cfd-ob-strength-bar" style="margin-top:6px;">
    <div class="cfd-ob-strength-fill" style="width:{sb}%;background:{clr};"></div>
  </div>
  <div class="ms-sig-sub" style="margin-top:3px;">Body {sb}%</div>
</div>"""

    cards_html += '</div>'
    st.markdown(cards_html, unsafe_allow_html=True)


# ── FVG / IFVG panel ──────────────────────────────────────────────────────────

def _render_fvg_panel(fvg: Dict) -> None:
    bull_fvg  = fvg.get("bullish",  [])
    bear_fvg  = fvg.get("bearish",  [])
    bull_ifvg = fvg.get("bull_ifvg", [])
    bear_ifvg = fvg.get("bear_ifvg", [])

    st.markdown("""
<div class="cfd-panel-header">
  <span class="cfd-panel-icon" style="background:#4d9de022;color:#4d9de0;">FVG</span>
  <span class="cfd-panel-title">Fair Value Gaps &amp; Inverse FVGs</span>
  <span class="cfd-panel-desc">Price inefficiencies and flipped imbalance zones</span>
</div>""", unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4, gap="small")

    def _fvg_card(col, items, label, color, tag):
        with col:
            st.markdown(f"""
<div class="cfd-fvg-card" style="border-color:{color}33;">
  <div class="cfd-fvg-card-head" style="color:{color};">{label}</div>""",
                        unsafe_allow_html=True)
            if not items:
                st.markdown(f'<div class="cfd-fvg-empty">No {tag} detected</div>',
                            unsafe_allow_html=True)
            else:
                for f in reversed(items[-3:]):
                    gap_pct = f.get("gap_pct", 0)
                    st.markdown(f"""
<div class="cfd-fvg-row">
  <div class="cfd-fvg-levels">
    <span style="color:{color};">{f['high']:,.2f}</span>
    <span class="cfd-fvg-arrow">↓</span>
    <span>{f['low']:,.2f}</span>
  </div>
  <div class="cfd-fvg-gap">{gap_pct:.3f}% gap</div>
</div>""", unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

    _fvg_card(c1, bull_fvg,  "Bullish FVG",  "#4d9de0", "bullish FVGs")
    _fvg_card(c2, bear_fvg,  "Bearish FVG",  "#f59e0b", "bearish FVGs")
    _fvg_card(c3, bull_ifvg, "Bullish IFVG", "#a855f7", "bullish IFVGs")
    _fvg_card(c4, bear_ifvg, "Bearish IFVG", "#ec4899", "bearish IFVGs")


# ── Market Structure panel ────────────────────────────────────────────────────

def _render_market_structure_panel(ms: Dict, df: pd.DataFrame) -> None:
    if not ms:
        return

    trend    = ms.get("trend", "neutral")
    zone     = ms.get("zone", "—")
    eq_pct   = ms.get("eq_pct", 0)
    bos_list = ms.get("bos", [])
    choch    = ms.get("choch", [])
    liq      = ms.get("liquidity", [])
    rh       = ms.get("recent_high", 0)
    rl       = ms.get("recent_low", 0)
    eq       = ms.get("equilibrium", 0)

    trend_color = "#00d4aa" if trend == "bullish" else "#f43f5e"
    zone_color  = "#f43f5e" if zone == "Premium" else "#00d4aa"
    trend_icon  = "▲" if trend == "bullish" else "▼"

    st.markdown("""
<div class="cfd-panel-header">
  <span class="cfd-panel-icon" style="background:#f59e0b22;color:#f59e0b;">MS</span>
  <span class="cfd-panel-title">Market Structure</span>
  <span class="cfd-panel-desc">BOS · CHoCH · Swing points · Premium/Discount · Liquidity pools</span>
</div>""", unsafe_allow_html=True)

    # Compact metric cards row
    st.markdown(f"""
<div class="ms-sig-grid" style="grid-template-columns:repeat(6,1fr);margin-bottom:10px;">
  <div class="ms-sig-card" style="border-top:2px solid {trend_color};box-shadow:0 2px 8px {trend_color}18;">
    <div class="ms-sig-icon" style="color:{trend_color};">{trend_icon}</div>
    <div class="ms-sig-label" style="color:{trend_color};">HTF TREND</div>
    <div class="ms-sig-sub">{trend.upper()}</div>
  </div>
  <div class="ms-sig-card" style="border-top:2px solid {zone_color};box-shadow:0 2px 8px {zone_color}18;">
    <div class="ms-sig-icon" style="color:{zone_color};">◈</div>
    <div class="ms-sig-label" style="color:{zone_color};">PRICE ZONE</div>
    <div class="ms-sig-sub">{zone}</div>
  </div>
  <div class="ms-sig-card" style="border-top:2px solid {zone_color};box-shadow:0 2px 8px {zone_color}18;">
    <div class="ms-sig-icon" style="color:{zone_color};">{eq_pct:+.1f}%</div>
    <div class="ms-sig-label" style="color:{zone_color};">EQ OFFSET</div>
    <div class="ms-sig-sub">vs equilibrium</div>
  </div>
  <div class="ms-sig-card" style="border-top:2px solid #f43f5e;box-shadow:0 2px 8px #f43f5e18;">
    <div class="ms-sig-icon" style="color:#f43f5e;">H</div>
    <div class="ms-sig-label" style="color:#64748b;">RANGE HIGH</div>
    <div class="ms-sig-sub">{rh:,.2f}</div>
  </div>
  <div class="ms-sig-card" style="border-top:2px solid #f59e0b;box-shadow:0 2px 8px #f59e0b18;">
    <div class="ms-sig-icon" style="color:#f59e0b;">EQ</div>
    <div class="ms-sig-label" style="color:#f59e0b;">EQUILIBRIUM</div>
    <div class="ms-sig-sub">{eq:,.2f}</div>
  </div>
  <div class="ms-sig-card" style="border-top:2px solid #00d4aa;box-shadow:0 2px 8px #00d4aa18;">
    <div class="ms-sig-icon" style="color:#00d4aa;">L</div>
    <div class="ms-sig-label" style="color:#64748b;">RANGE LOW</div>
    <div class="ms-sig-sub">{rl:,.2f}</div>
  </div>
</div>""", unsafe_allow_html=True)

    # BOS / CHoCH / Liquidity event cards
    events_html = '<div class="ms-sig-grid" style="grid-template-columns:repeat(auto-fill,minmax(150px,1fr));">'

    for b in reversed(bos_list[-4:]):
        clr = "#00d4aa" if b["direction"] == "bullish" else "#f43f5e"
        arrow = "▲" if b["direction"] == "bullish" else "▼"
        events_html += f"""
<div class="ms-sig-card" style="border-top:2px solid {clr};box-shadow:0 2px 8px {clr}18;">
  <div class="ms-sig-icon" style="color:{clr};">{arrow} BOS</div>
  <div class="ms-sig-label" style="color:{clr};">{b['direction'].upper()}</div>
  <div class="ms-sig-sub">{b['level']:,.2f}</div>
</div>"""

    for c in reversed(choch[-3:]):
        clr = "#00d4aa" if c["direction"] == "bullish" else "#f43f5e"
        arrow = "▲" if c["direction"] == "bullish" else "▼"
        events_html += f"""
<div class="ms-sig-card" style="border-top:2px solid {clr};box-shadow:0 2px 8px {clr}18;">
  <div class="ms-sig-icon" style="color:{clr};font-size:0.7rem;">{arrow} CHoCH</div>
  <div class="ms-sig-label" style="color:{clr};">{c['direction'].upper()}</div>
  <div class="ms-sig-sub">{c['level']:,.2f}</div>
</div>"""

    for lv in liq[-4:]:
        clr = "#f43f5e" if lv["type"] == "EQH" else "#00d4aa"
        lbl = "Eq. Highs" if lv["type"] == "EQH" else "Eq. Lows"
        events_html += f"""
<div class="ms-sig-card" style="border-top:2px solid {clr};box-shadow:0 2px 8px {clr}18;">
  <div class="ms-sig-icon" style="color:{clr};">{lv['type']}</div>
  <div class="ms-sig-label" style="color:{clr};">{lbl}</div>
  <div class="ms-sig-sub">{lv['price']:,.2f}</div>
</div>"""

    if not bos_list and not choch and not liq:
        events_html += '<div class="cfd-empty-state" style="grid-column:1/-1;">No MS events detected</div>'

    events_html += '</div>'
    st.markdown(events_html, unsafe_allow_html=True)


# ── Institutional Analysis panel ──────────────────────────────────────────────

def _render_institutional_panel(ai: Dict, df: pd.DataFrame) -> None:
    if not ai:
        st.info("Insufficient data for institutional analysis.")
        return

    bias      = ai.get("bias",         "Neutral")
    bull_prob = ai.get("bull_prob",    50)
    bear_prob = ai.get("bear_prob",    50)
    rsi_val   = ai.get("rsi",          50)
    mom       = ai.get("momentum",     0)
    mom_lbl   = ai.get("momentum_lbl", "Flat")
    vol_pct   = ai.get("volatility",   0)
    ts        = ai.get("trend_str",    25)
    rvol      = ai.get("rvol",         1)
    session   = ai.get("session",      "—")
    liq_dir   = ai.get("liq_dir",      "—")
    position  = ai.get("position",     "Neutral")

    if   "Strong Bull" in bias:  bias_clr = "#00d4aa"; bias_icon = "▲▲"
    elif "Bullish"     in bias:  bias_clr = "#00d4aa"; bias_icon = "▲"
    elif "Strong Bear" in bias:  bias_clr = "#f43f5e"; bias_icon = "▼▼"
    elif "Bearish"     in bias:  bias_clr = "#f43f5e"; bias_icon = "▼"
    else:                        bias_clr = "#f59e0b"; bias_icon = "◆"

    st.markdown(f"""
<div class="cfd-panel-header">
  <span class="cfd-panel-icon" style="background:#ec489922;color:#ec4899;">AI</span>
  <span class="cfd-panel-title">Institutional Analysis</span>
  <span class="cfd-panel-desc">Rule-based smart money bias · Entry/SL/TP zones · Session context</span>
</div>""", unsafe_allow_html=True)

    st.markdown(f"""
<div class="cfd-ai-bias-block">
  <div class="cfd-ai-bias-main">
    <span class="cfd-ai-bias-icon" style="color:{bias_clr};">{bias_icon}</span>
    <span class="cfd-ai-bias-label" style="color:{bias_clr};">{bias}</span>
  </div>
  <div class="cfd-ai-prob-row">
    <span class="cfd-ai-prob-bull">{bull_prob}% Bull</span>
    <div class="cfd-ai-prob-bar">
      <div class="cfd-ai-prob-fill-bull" style="width:{bull_prob}%;"></div>
      <div class="cfd-ai-prob-fill-bear" style="width:{bear_prob}%;"></div>
    </div>
    <span class="cfd-ai-prob-bear">{bear_prob}% Bear</span>
  </div>
</div>""", unsafe_allow_html=True)

    rsi_clr  = "#f43f5e" if rsi_val > 70 else ("#00d4aa" if rsi_val < 30 else "#e2e8f0")
    mom_clr  = "#00d4aa" if mom > 0     else ("#f43f5e" if mom < 0      else "#64748b")
    vol_clr  = "#f59e0b" if vol_pct > 2  else "#64748b"
    ts_clr   = "#00d4aa" if ts > 30      else "#64748b"
    pos_clr  = "#f43f5e" if position == "Premium" else "#00d4aa"
    rvol_clr = "#f59e0b" if rvol > 1.5  else "#64748b"

    st.markdown(f"""
<div class="cfd-ai-metrics-grid">
  <div class="cfd-ai-metric">
    <div class="cfd-ai-metric-label">RSI (14)</div>
    <div class="cfd-ai-metric-val" style="color:{rsi_clr};">{rsi_val}</div>
  </div>
  <div class="cfd-ai-metric">
    <div class="cfd-ai-metric-label">MOMENTUM</div>
    <div class="cfd-ai-metric-val" style="color:{mom_clr};">{mom_lbl}</div>
  </div>
  <div class="cfd-ai-metric">
    <div class="cfd-ai-metric-label">VOLATILITY</div>
    <div class="cfd-ai-metric-val" style="color:{vol_clr};">{vol_pct:.2f}%</div>
  </div>
  <div class="cfd-ai-metric">
    <div class="cfd-ai-metric-label">TREND STR.</div>
    <div class="cfd-ai-metric-val" style="color:{ts_clr};">{ts:.0f}</div>
  </div>
  <div class="cfd-ai-metric">
    <div class="cfd-ai-metric-label">REL. VOLUME</div>
    <div class="cfd-ai-metric-val" style="color:{rvol_clr};">{rvol:.2f}x</div>
  </div>
  <div class="cfd-ai-metric">
    <div class="cfd-ai-metric-label">PRICE ZONE</div>
    <div class="cfd-ai-metric-val" style="color:{pos_clr};">{position}</div>
  </div>
  <div class="cfd-ai-metric">
    <div class="cfd-ai-metric-label">SESSION</div>
    <div class="cfd-ai-metric-val">{session}</div>
  </div>
  <div class="cfd-ai-metric">
    <div class="cfd-ai-metric-label">LIQ. FLOW</div>
    <div class="cfd-ai-metric-val">{liq_dir}</div>
  </div>
</div>""", unsafe_allow_html=True)

    c_bull, c_bear = st.columns(2, gap="small")

    def _fp(v: float) -> str:
        return f"{v:,.2f}" if v else "—"

    with c_bull:
        rr   = ai.get("rr_bull",   0)
        eb   = ai.get("entry_bull", 0)
        slb  = ai.get("sl_bull",   0)
        tp1b = ai.get("tp1_bull",  0)
        tp2b = ai.get("tp2_bull",  0)
        st.markdown(f"""
<div class="cfd-trade-zone cfd-trade-bull">
  <div class="cfd-trade-header">
    <span class="cfd-trade-dir-badge cfd-trade-dir-bull">LONG</span>
    <span class="cfd-trade-rr">R:R {rr:.1f}</span>
  </div>
  <div class="cfd-trade-rows">
    <div class="cfd-trade-row">
      <span class="cfd-trade-lbl">Entry Zone</span>
      <span class="cfd-trade-val" style="color:#e2e8f0;">{_fp(eb)}</span>
    </div>
    <div class="cfd-trade-row">
      <span class="cfd-trade-lbl">Stop Loss</span>
      <span class="cfd-trade-val" style="color:#f43f5e;">{_fp(slb)}</span>
    </div>
    <div class="cfd-trade-row">
      <span class="cfd-trade-lbl">TP 1</span>
      <span class="cfd-trade-val" style="color:#00d4aa;">{_fp(tp1b)}</span>
    </div>
    <div class="cfd-trade-row">
      <span class="cfd-trade-lbl">TP 2</span>
      <span class="cfd-trade-val" style="color:#00d4aa;">{_fp(tp2b)}</span>
    </div>
  </div>
</div>""", unsafe_allow_html=True)

    with c_bear:
        rr   = ai.get("rr_bear",   0)
        ebe  = ai.get("entry_bear", 0)
        sle  = ai.get("sl_bear",   0)
        tp1e = ai.get("tp1_bear",  0)
        tp2e = ai.get("tp2_bear",  0)
        st.markdown(f"""
<div class="cfd-trade-zone cfd-trade-bear">
  <div class="cfd-trade-header">
    <span class="cfd-trade-dir-badge cfd-trade-dir-bear">SHORT</span>
    <span class="cfd-trade-rr">R:R {rr:.1f}</span>
  </div>
  <div class="cfd-trade-rows">
    <div class="cfd-trade-row">
      <span class="cfd-trade-lbl">Entry Zone</span>
      <span class="cfd-trade-val" style="color:#e2e8f0;">{_fp(ebe)}</span>
    </div>
    <div class="cfd-trade-row">
      <span class="cfd-trade-lbl">Stop Loss</span>
      <span class="cfd-trade-val" style="color:#f43f5e;">{_fp(sle)}</span>
    </div>
    <div class="cfd-trade-row">
      <span class="cfd-trade-lbl">TP 1</span>
      <span class="cfd-trade-val" style="color:#00d4aa;">{_fp(tp1e)}</span>
    </div>
    <div class="cfd-trade-row">
      <span class="cfd-trade-lbl">TP 2</span>
      <span class="cfd-trade-val" style="color:#00d4aa;">{_fp(tp2e)}</span>
    </div>
  </div>
</div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# IDEAL ENTRY — React to Liquidity Behavior
# ════════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=120, show_spinner=False)
def _load_htf_data(symbol: str) -> Optional[pd.DataFrame]:
    """1H data (180 d) for EMA-200 HTF bias."""
    try:
        df = get_history(symbol, period="180d", interval="60m")
        if df is not None and not df.empty:
            df.index = pd.to_datetime(df.index)
        return df
    except Exception:
        return None


def _render_ideal_entry_section(
    sym_display: str,
    symbol:      str,
    df:          pd.DataFrame,
    ob_data:     Dict,
    fvg_data:    Dict,
    ms_data:     Dict,
) -> None:
    st.markdown("""
<div class="ie-header">
  <div class="ie-header-left">
    <span class="ie-header-icon">⚡</span>
    <div>
      <div class="ie-header-title">
        Ideal Entry <span class="ie-header-accent">— React to Liquidity Behavior</span>
      </div>
      <div class="ie-header-sub">
        Institutional SMC detection · Multi-timeframe confluence · No market prediction
      </div>
    </div>
  </div>
</div>""", unsafe_allow_html=True)

    df_htf = _load_htf_data(symbol)
    sig    = generate_entry_signal(df_htf, df, ob_data, fvg_data, ms_data)
    if not sig:
        st.info("Insufficient bars for entry analysis. Try a higher timeframe.")
        return

    _render_mtf_strip(sig)
    st.markdown('<div class="ie-spacer"></div>', unsafe_allow_html=True)

    c_long, c_short = st.columns(2, gap="small")
    with c_long:
        _render_entry_card("long",  sig["long"],  sym_display, sig)
    with c_short:
        _render_entry_card("short", sig["short"], sym_display, sig)

    st.markdown('<div class="ie-spacer"></div>', unsafe_allow_html=True)

    c_tbl, c_liq = st.columns([1.1, 0.9], gap="small")
    with c_tbl:
        _render_signal_table(sig["signal_rows"])
    with c_liq:
        _render_liquidity_panel(sig)

    st.markdown('<div class="ie-spacer"></div>', unsafe_allow_html=True)
    _render_vp_summary(sig["hvn_lvn"], sig.get("vp"), sig["atr"], sym_display, df)


# ── MTF alignment strip ───────────────────────────────────────────────────────

def _render_mtf_strip(sig: Dict) -> None:
    bias    = sig.get("bias", {})
    htf     = bias.get("htf",  {})
    main    = bias.get("main", {})
    aligned = bias.get("aligned", False)
    ema200  = sig.get("ema200", 0)
    atr_v   = sig.get("atr",   0)
    rsi_v   = sig.get("rsi",   50)
    zone    = sig.get("zone",  "—")
    sweeps  = sig.get("sweeps", {})

    def _bias_color(b):
        return "#00d4aa" if b == "bullish" else ("#f43f5e" if b == "bearish" else "#f59e0b")

    def _bias_icon(b):
        return "▲" if b == "bullish" else ("▼" if b == "bearish" else "◆")

    htf_clr  = _bias_color(htf.get("bias",  "neutral"))
    main_clr = _bias_color(main.get("bias", "neutral"))
    al_clr   = "#00d4aa" if aligned else "#f59e0b"
    al_txt   = "ALIGNED" if aligned else "DIVERGENT"
    zone_clr = "#f43f5e" if zone == "Premium" else "#00d4aa"
    rsi_clr  = "#f43f5e" if rsi_v > 70 else ("#00d4aa" if rsi_v < 30 else "#e2e8f0")
    n_sell   = len(sweeps.get("sell_side", []))
    n_buy    = len(sweeps.get("buy_side",  []))

    ema_str = f"{ema200:,.2f}" if ema200 else "—"
    atr_str = f"{atr_v:,.2f}" if atr_v  else "—"

    st.markdown(f"""
<div class="ie-mtf-strip">
  <div class="ie-mtf-chip">
    <span class="ie-mtf-label">1H BIAS</span>
    <span class="ie-mtf-val" style="color:{htf_clr};">
      {_bias_icon(htf.get('bias','neutral'))} {htf.get('bias','—').upper()}
    </span>
  </div>
  <div class="ie-mtf-chip">
    <span class="ie-mtf-label">CURRENT TF</span>
    <span class="ie-mtf-val" style="color:{main_clr};">
      {_bias_icon(main.get('bias','neutral'))} {main.get('bias','—').upper()}
    </span>
  </div>
  <div class="ie-mtf-chip">
    <span class="ie-mtf-label">MTF ALIGN</span>
    <span class="ie-mtf-val" style="color:{al_clr};">{al_txt}</span>
  </div>
  <div class="ie-mtf-chip">
    <span class="ie-mtf-label">EMA 200</span>
    <span class="ie-mtf-val">{ema_str}</span>
  </div>
  <div class="ie-mtf-chip">
    <span class="ie-mtf-label">ATR</span>
    <span class="ie-mtf-val">{atr_str}</span>
  </div>
  <div class="ie-mtf-chip">
    <span class="ie-mtf-label">RSI 14</span>
    <span class="ie-mtf-val" style="color:{rsi_clr};">{rsi_v}</span>
  </div>
  <div class="ie-mtf-chip">
    <span class="ie-mtf-label">ZONE</span>
    <span class="ie-mtf-val" style="color:{zone_clr};">{zone}</span>
  </div>
  <div class="ie-mtf-chip">
    <span class="ie-mtf-label">SWEEPS</span>
    <span class="ie-mtf-val">
      <span style="color:#00d4aa;">{n_sell} SSL</span>
      <span style="color:#64748b;"> · </span>
      <span style="color:#f43f5e;">{n_buy} BSL</span>
    </span>
  </div>
</div>""", unsafe_allow_html=True)


# ── Entry card (Long / Short) ─────────────────────────────────────────────────

def _render_entry_card(direction: str, data: Dict, sym_display: str, sig: Dict) -> None:
    is_long   = direction == "long"
    dir_color = "#00d4aa" if is_long else "#f43f5e"
    dir_label = "LONG"    if is_long else "SHORT"
    dir_arrow = "▲"       if is_long else "▼"

    conf      = data.get("confidence",  0)
    quality   = data.get("quality",    "—")
    inst_bias = data.get("inst_bias",  "—")
    score     = data.get("score",       0)
    max_sc    = data.get("max_score",  15)
    entry_p   = data.get("entry",       0)
    sl_p      = data.get("sl",          0)
    tp1_p     = data.get("tp1",         0)
    tp2_p     = data.get("tp2",         0)
    rr1       = data.get("rr1",         0)
    rr2       = data.get("rr2",         0)
    rej       = data.get("rejection")

    if   quality == "Strong":   qual_bg = "#00d4aa22"; qual_cl = "#00d4aa"
    elif quality == "Moderate": qual_bg = "#f59e0b22"; qual_cl = "#f59e0b"
    elif quality == "Weak":     qual_bg = "#94a3b822"; qual_cl = "#94a3b8"
    else:                       qual_bg = "#f43f5e22"; qual_cl = "#f43f5e"

    bar_fill  = int(min(conf, 100))
    bar_color = dir_color if conf >= 60 else ("#f59e0b" if conf >= 40 else "#f43f5e")

    sl_pct  = round((entry_p - sl_p)  / (entry_p + 1e-9) * 100, 2) if is_long else \
              round((sl_p  - entry_p) / (entry_p + 1e-9) * 100, 2)
    tp1_pct = round((tp1_p - entry_p) / (entry_p + 1e-9) * 100, 2) if is_long else \
              round((entry_p - tp1_p) / (entry_p + 1e-9) * 100, 2)
    tp2_pct = round((tp2_p - entry_p) / (entry_p + 1e-9) * 100, 2) if is_long else \
              round((entry_p - tp2_p) / (entry_p + 1e-9) * 100, 2)

    def _fp(v: float) -> str:
        return f"{v:,.2f}" if v else "—"

    rej_badge = (
        f'<span class="ie-rej-badge" style="border-color:{dir_color}44;color:{dir_color};">'
        f'{rej}</span>'
    ) if rej else ""

    sigs = data.get("signals", {})
    from data.entry_engine import _SIGNAL_LABELS  # noqa: PLC0415
    chips_html = ""
    for k, (label, _) in list(_SIGNAL_LABELS.items())[:6]:
        if sigs.get(k):
            chips_html += (
                f'<span class="ie-sig-chip" style="background:{dir_color}14;'
                f'color:{dir_color};border-color:{dir_color}33;">{label}</span>'
            )

    st.markdown(f"""
<div class="ie-entry-card" style="border-top:2.5px solid {dir_color};">
  <div class="ie-card-header">
    <span class="ie-dir-badge" style="background:{dir_color}22;color:{dir_color};border-color:{dir_color}44;">
      {dir_arrow} {dir_label}
    </span>
    <span class="ie-qual-badge" style="background:{qual_bg};color:{qual_cl};">{quality}</span>
    <span class="ie-inst-badge">{inst_bias}</span>
    {rej_badge}
  </div>
  <div class="ie-conf-label">
    <span style="color:{dir_color};font-weight:800;font-size:1.1rem;">{conf}%</span>
    <span class="ie-conf-sublabel"> confidence · {score}/{max_sc} pts</span>
  </div>
  <div class="ie-conf-bar-wrap">
    <div class="ie-conf-bar-fill" style="width:{bar_fill}%;background:{bar_color};"></div>
  </div>
  <div class="ie-levels-grid">
    <div class="ie-level-row">
      <span class="ie-level-lbl">Entry</span>
      <span class="ie-level-val">{_fp(entry_p)}</span>
      <span class="ie-level-note" style="color:#64748b;">current</span>
    </div>
    <div class="ie-level-row">
      <span class="ie-level-lbl">Stop Loss</span>
      <span class="ie-level-val" style="color:#f43f5e;">{_fp(sl_p)}</span>
      <span class="ie-level-note" style="color:#f43f5e;">-{sl_pct:.2f}%</span>
    </div>
    <div class="ie-level-row">
      <span class="ie-level-lbl">TP 1</span>
      <span class="ie-level-val" style="color:#00d4aa;">{_fp(tp1_p)}</span>
      <span class="ie-level-note" style="color:#00d4aa;">+{tp1_pct:.2f}%</span>
    </div>
    <div class="ie-level-row">
      <span class="ie-level-lbl">TP 2</span>
      <span class="ie-level-val" style="color:#00d4aa;">{_fp(tp2_p)}</span>
      <span class="ie-level-note" style="color:#00d4aa;">+{tp2_pct:.2f}%</span>
    </div>
    <div class="ie-level-row ie-rr-row">
      <span class="ie-level-lbl">R:R (TP1)</span>
      <span class="ie-level-val" style="color:#f59e0b;">1 : {rr1}</span>
      <span class="ie-level-lbl" style="margin-left:10px;">R:R (TP2)</span>
      <span class="ie-level-val" style="color:#f59e0b;">1 : {rr2}</span>
    </div>
  </div>
  <div class="ie-sig-chips">{chips_html if chips_html else
      f'<span class="ie-no-sigs">No signals active</span>'}</div>
</div>""", unsafe_allow_html=True)


# ── Signal breakdown table ────────────────────────────────────────────────────

def _render_signal_table(rows: List[Dict]) -> None:
    st.markdown("""
<div class="ie-table-wrap">
  <div class="ie-table-header">Signal Breakdown</div>
  <table class="ie-signal-table">
    <thead>
      <tr>
        <th class="ie-th-signal">Signal</th>
        <th class="ie-th-dir">Long</th>
        <th class="ie-th-dir">Short</th>
        <th class="ie-th-w">Wt.</th>
      </tr>
    </thead>
    <tbody>""", unsafe_allow_html=True)

    rows_html = ""
    for r in rows:
        long_icon  = '<span class="ie-check-y">✓</span>' if r["long"]  else '<span class="ie-check-n">✗</span>'
        short_icon = '<span class="ie-check-y">✓</span>' if r["short"] else '<span class="ie-check-n">✗</span>'
        row_hi     = ' ie-row-highlight' if r["long"] or r["short"] else ''
        rows_html += f"""
      <tr class="ie-tr{row_hi}">
        <td class="ie-td-signal">{r['signal']}</td>
        <td class="ie-td-dir">{long_icon}</td>
        <td class="ie-td-dir">{short_icon}</td>
        <td class="ie-td-w">{r['weight']}</td>
      </tr>"""

    st.markdown(rows_html + """
    </tbody>
  </table>
</div>""", unsafe_allow_html=True)


# ── Liquidity behavior panel ──────────────────────────────────────────────────

def _render_liquidity_panel(sig: Dict) -> None:
    long_narr  = sig.get("long",  {}).get("narrative", [])
    short_narr = sig.get("short", {}).get("narrative", [])
    sweeps     = sig.get("sweeps", {})
    sell_sweeps = sweeps.get("sell_side", [])
    buy_sweeps  = sweeps.get("buy_side",  [])

    st.markdown('<div class="ie-liq-wrap">', unsafe_allow_html=True)
    st.markdown('<div class="ie-table-header">Liquidity Behavior</div>', unsafe_allow_html=True)

    st.markdown('<div class="ie-liq-dir-label" style="color:#00d4aa;">LONG — Sell-Side Sweep Analysis</div>',
                unsafe_allow_html=True)
    for line in long_narr:
        st.markdown(f'<div class="ie-liq-line">• {line}</div>', unsafe_allow_html=True)

    if sell_sweeps:
        st.markdown('<div class="ie-liq-events-head">Recent sell-side sweeps</div>',
                    unsafe_allow_html=True)
        for s in sell_sweeps[:3]:
            ba = s.get("bars_ago", 0)
            st.markdown(f"""
<div class="ie-liq-event ie-liq-bull">
  <span class="ie-liq-event-level">{s['level']:,.2f}</span>
  <span class="ie-liq-arrow">→</span>
  <span class="ie-liq-event-sweep" style="color:#f43f5e;">swept {s['sweep_low']:,.2f}</span>
  <span class="ie-liq-event-rec" style="color:#00d4aa;">recovered {s['recovery']:,.2f}</span>
  <span class="ie-liq-event-ago">{ba} bars ago</span>
</div>""", unsafe_allow_html=True)

    st.markdown('<div class="ie-liq-sep"></div>', unsafe_allow_html=True)

    st.markdown('<div class="ie-liq-dir-label" style="color:#f43f5e;">SHORT — Buy-Side Sweep Analysis</div>',
                unsafe_allow_html=True)
    for line in short_narr:
        st.markdown(f'<div class="ie-liq-line">• {line}</div>', unsafe_allow_html=True)

    if buy_sweeps:
        st.markdown('<div class="ie-liq-events-head">Recent buy-side sweeps</div>',
                    unsafe_allow_html=True)
        for s in buy_sweeps[:3]:
            ba = s.get("bars_ago", 0)
            st.markdown(f"""
<div class="ie-liq-event ie-liq-bear">
  <span class="ie-liq-event-level">{s['level']:,.2f}</span>
  <span class="ie-liq-arrow">→</span>
  <span class="ie-liq-event-sweep" style="color:#00d4aa;">swept {s['sweep_high']:,.2f}</span>
  <span class="ie-liq-event-rec" style="color:#f43f5e;">recovered {s['recovery']:,.2f}</span>
  <span class="ie-liq-event-ago">{ba} bars ago</span>
</div>""", unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ── Volume profile summary ────────────────────────────────────────────────────

def _render_vp_summary(
    hvn_lvn_d: Dict,
    vp:        Optional[Dict],
    atr_v:     float,
    sym_display: str,
    df:        pd.DataFrame,
) -> None:
    poc = hvn_lvn_d.get("poc")
    hvn = hvn_lvn_d.get("hvn", [])
    lvn = hvn_lvn_d.get("lvn", [])
    cur = float(df["Close"].iloc[-1]) if df is not None and not df.empty else 0

    st.markdown("""
<div class="ie-vp-section">
  <div class="ie-table-header">Volume Profile · HVN / LVN Analysis</div>""",
                unsafe_allow_html=True)

    if vp is None:
        st.markdown(
            '<div class="ie-vp-no-vol">Volume data unavailable for this timeframe. '
            'ATR-based zones used instead.</div>',
            unsafe_allow_html=True,
        )
        levels = [
            ("ATR +1.5", cur + atr_v * 1.5, "resistance"),
            ("ATR +1.0", cur + atr_v * 1.0, "resistance"),
            ("Current",  cur,                "current"),
            ("ATR -1.0", cur - atr_v * 1.0, "support"),
            ("ATR -1.5", cur - atr_v * 1.5, "support"),
        ]
        for lbl, price, role in levels:
            clr = "#f43f5e" if role == "resistance" else ("#00d4aa" if role == "support" else "#f59e0b")
            st.markdown(f"""
<div class="ie-vp-row-simple">
  <span class="ie-vp-lbl" style="color:{clr};">{lbl}</span>
  <span class="ie-vp-price">{price:,.2f}</span>
  <span class="ie-vp-role" style="color:{clr};">{role}</span>
</div>""", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        return

    c_poc, c_hvn, c_lvn = st.columns(3, gap="small")

    with c_poc:
        poc_str = f"{poc:,.2f}" if poc else "—"
        st.markdown(f"""
<div class="ie-vp-card">
  <div class="ie-vp-card-title" style="color:#f59e0b;">POC</div>
  <div class="ie-vp-card-val">{poc_str}</div>
  <div class="ie-vp-card-sub">Point of Control · Highest volume price</div>
</div>""", unsafe_allow_html=True)

    with c_hvn:
        st.markdown('<div class="ie-vp-card">', unsafe_allow_html=True)
        st.markdown('<div class="ie-vp-card-title" style="color:#00d4aa;">HVN — Support / Resistance</div>',
                    unsafe_allow_html=True)
        if not hvn:
            st.markdown('<div class="ie-vp-empty">No HVN near price</div>', unsafe_allow_html=True)
        else:
            for h in hvn[:4]:
                role = "above" if h > cur else "below"
                clr  = "#f43f5e" if h > cur else "#00d4aa"
                st.markdown(f"""
<div class="ie-vp-node-row">
  <span style="color:{clr};">{h:,.2f}</span>
  <span class="ie-vp-node-role" style="color:{clr};">{role}</span>
</div>""", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with c_lvn:
        st.markdown('<div class="ie-vp-card">', unsafe_allow_html=True)
        st.markdown('<div class="ie-vp-card-title" style="color:#a855f7;">LVN — Low-Resistance Paths</div>',
                    unsafe_allow_html=True)
        if not lvn:
            st.markdown('<div class="ie-vp-empty">No LVN near price</div>', unsafe_allow_html=True)
        else:
            for lv in lvn[:4]:
                role = "above (gap up)" if lv > cur else "below (gap dn)"
                st.markdown(f"""
<div class="ie-vp-node-row">
  <span style="color:#a855f7;">{lv:,.2f}</span>
  <span class="ie-vp-node-role" style="color:#a855f7;">{role}</span>
</div>""", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    _render_vp_bars(vp, cur, hvn, lvn)
    st.markdown('</div>', unsafe_allow_html=True)


def _render_vp_bars(vp: Dict, cur: float, hvn: List, lvn: List) -> None:
    import numpy as np
    prices = vp["prices"]
    vols   = vp["volumes"]
    max_v  = float(vols.max())
    if max_v == 0:
        return

    distances = np.abs(prices - cur)
    top_idx   = np.argsort(distances)[:28]
    top_idx   = np.sort(top_idx)

    bars = '<div class="ie-vp-chart">'
    for i in top_idx:
        p      = float(prices[i])
        v      = float(vols[i])
        pct    = round(v / max_v * 100, 1)
        is_cur = abs(p - cur) / (cur + 1e-9) < 0.008
        is_hvn = any(abs(p - h) / (h + 1e-9) < 0.012 for h in hvn)
        is_lvn = any(abs(p - lv) / (lv + 1e-9) < 0.012 for lv in lvn)
        bar_c  = "#00d4aa" if is_hvn else ("#a855f7" if is_lvn else ("#f59e0b" if is_cur else "#1e2d45"))
        lbl_c  = bar_c if (is_hvn or is_lvn or is_cur) else "#64748b"
        tag    = " HVN" if is_hvn else (" LVN" if is_lvn else (" ←" if is_cur else ""))
        bars  += f"""
<div class="ie-vp-bar-row">
  <div class="ie-vp-bar-price" style="color:{lbl_c};">{p:,.2f}</div>
  <div class="ie-vp-bar-track">
    <div class="ie-vp-bar-fill" style="width:{pct}%;background:{bar_c};"></div>
  </div>
  <div class="ie-vp-bar-tag" style="color:{lbl_c};">{tag}</div>
</div>"""
    bars += '</div>'
    st.markdown(bars, unsafe_allow_html=True)


# ── Data helpers ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def _get_chart_data(
    symbol:   str,
    period:   str,
    interval: str,
    resample: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    try:
        df = get_history(symbol, period=period, interval=interval)
        if df is None or df.empty:
            return None
        df.index = pd.to_datetime(df.index)
        if resample:
            df = df.resample(resample).agg({
                "Open": "first", "High": "max", "Low": "min",
                "Close": "last", "Volume": "sum",
            }).dropna(how="any")
        return df
    except Exception:
        return None


def _sync_workspace_to_url() -> None:
    """Write current workspace to URL query params (Streamlit 1.30+ non-reactive write).

    URL params survive hard page reloads — they're embedded in the browser URL
    and Streamlit reads them back in the next session.  This is the highest-
    priority persistence layer because it requires no external storage.
    """
    try:
        mapping = {
            "cs_sym": "cs_symbol",
            "cs_eng": "cs_chart_engine",
            "cs_tf":  "cs_timeframe",
        }
        for url_key, ss_key in mapping.items():
            val = st.session_state.get(ss_key)
            if val:
                st.query_params[url_key] = val
    except Exception:
        pass


def _init_state(db: PineScriptDB) -> None:
    """Restore workspace state for a fresh session.

    Priority:  URL query params  →  SQLite DB  →  hardcoded defaults.
    URL params survive hard page reloads (they're in the browser URL).
    DB covers new browser sessions or incognito mode.
    Session state is checked first so repeated reruns never overwrite
    state that is already live in the current session.
    """
    from components.chart_engine import ENGINES as _ENGINES  # avoid circular at module level
    params = st.query_params  # Streamlit 1.30+ read/write dict

    if "cs_symbol" not in st.session_state:
        url_sym = params.get("cs_sym", "")
        db_sym  = db.get_preference("last_symbol", "RELIANCE.NS")
        st.session_state.cs_symbol = url_sym or db_sym

    if "cs_timeframe" not in st.session_state:
        url_tf = params.get("cs_tf", "")
        db_tf  = db.get_preference("last_timeframe", "1D")
        tf     = url_tf if url_tf in _TF_KEYS else (db_tf if db_tf in _TF_KEYS else "1D")
        st.session_state.cs_timeframe = tf

    if "cs_chart_engine" not in st.session_state:
        url_eng = params.get("cs_eng", "")
        db_eng  = db.get_preference("cs_chart_engine", "Lightweight")
        eng     = url_eng if url_eng in _ENGINES else (db_eng if db_eng in _ENGINES else "Lightweight")
        st.session_state.cs_chart_engine = eng

    simple_defaults = {
        "cs_chart_height_label": "Standard",
        "cs_show_volume":        True,
        "cs_log_scale":          False,
        "cs_smc_show_ob":        True,
    }
    for k, v in simple_defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _fmt_vol(v: float) -> str:
    if v >= 1e7: return f"{v/1e7:.1f}Cr"
    if v >= 1e5: return f"{v/1e5:.1f}L"
    if v >= 1e3: return f"{v/1e3:.0f}K"
    return str(int(v))


# ── Compact sidebar sentiment panel ───────────────────────────────────────────

def _render_cs_sentiment_panel(df: pd.DataFrame, ai_data: Dict) -> None:
    """Compact vertical Market Sentiment panel in chart sidebar."""
    if df is None or df.empty or len(df) < 5:
        st.markdown('<div class="cfd-sent-empty">Insufficient data</div>', unsafe_allow_html=True)
        return

    m = _compute_sentiment(df, ai_data)

    # ── A. Bid/Ask Order Sentiment ────────────────────────────────────────────
    imb_side = "BUY" if m["buy_pct"] > m["sell_pct"] else "SELL"
    imb_clr  = "#00d4aa" if imb_side == "BUY" else "#f43f5e"
    imb_pct  = abs(m["buy_pct"] - m["sell_pct"])
    vr_clr   = "#00d4aa" if m["vol_ratio"] >= 1.5 else "#f59e0b" if m["vol_ratio"] >= 1.0 else "#64748b"

    st.markdown(f"""
<div class="ms-bidask-card">
  <div class="ms-bidask-title">◈ ORDER SENTIMENT</div>
  <div class="ms-bidask-row">
    <span class="ms-bidask-label" style="color:#00d4aa;">BUY</span>
    <div class="ms-bidask-bar-wrap">
      <div class="ms-bidask-bar" style="width:{m['buy_pct']}%;
           background:linear-gradient(90deg,#00d4aa44,#00d4aa);
           box-shadow:0 0 6px #00d4aa44;"></div>
    </div>
    <span class="ms-bidask-val" style="color:#00d4aa;">{m['buy_pct']}%</span>
  </div>
  <div class="ms-bidask-row">
    <span class="ms-bidask-label" style="color:#f43f5e;">SELL</span>
    <div class="ms-bidask-bar-wrap">
      <div class="ms-bidask-bar" style="width:{m['sell_pct']}%;
           background:linear-gradient(90deg,#f43f5e44,#f43f5e);
           box-shadow:0 0 6px #f43f5e44;"></div>
    </div>
    <span class="ms-bidask-val" style="color:#f43f5e;">{m['sell_pct']}%</span>
  </div>
  <div class="ms-bidask-meta">
    <div class="ms-bidask-meta-row">
      <span>Pressure</span>
      <span style="color:{imb_clr};font-weight:700;">{imb_side} +{imb_pct}%</span>
    </div>
    <div class="ms-bidask-meta-row">
      <span>Vol Ratio</span>
      <span style="color:{vr_clr};font-weight:700;">{m['vol_ratio']:.2f}x</span>
    </div>
  </div>
</div>""", unsafe_allow_html=True)

    # ── B. Activity Gauges (horizontal bars) ──────────────────────────────────
    vol_clr  = "#00d4aa" if m["vol_ratio"] >= 1.5 else "#f59e0b" if m["vol_ratio"] >= 1.0 else "#4d9de0"
    mom_clr  = "#00d4aa" if m["mom_1d"] > 0 else "#f43f5e"
    vola_clr = "#f59e0b" if m["rel_vol"] > 120 else "#64748b"

    st.markdown(f"""
<div class="ms-pressure-wrap">
  <div class="ms-pressure-title">◈ ACTIVITY GAUGES</div>
  <div style="margin-bottom:8px;">
    <div style="display:flex;justify-content:space-between;font-size:0.68rem;margin-bottom:3px;">
      <span style="color:#94a3b8;">Volume</span>
      <span style="color:{vol_clr};font-weight:700;">{m['vol_ratio']:.1f}x avg</span>
    </div>
    <div class="ms-pressure-track">
      <div style="height:100%;width:{m['g_vol']}%;background:{vol_clr};border-radius:3px;transition:width 0.4s;"></div>
    </div>
  </div>
  <div style="margin-bottom:8px;">
    <div style="display:flex;justify-content:space-between;font-size:0.68rem;margin-bottom:3px;">
      <span style="color:#94a3b8;">Momentum</span>
      <span style="color:{mom_clr};font-weight:700;">{m['mom_1d']:+.2f}%</span>
    </div>
    <div class="ms-pressure-track">
      <div style="height:100%;width:{m['g_mom']}%;background:{mom_clr};border-radius:3px;transition:width 0.4s;"></div>
    </div>
  </div>
  <div>
    <div style="display:flex;justify-content:space-between;font-size:0.68rem;margin-bottom:3px;">
      <span style="color:#94a3b8;">Volatility</span>
      <span style="color:{vola_clr};font-weight:700;">{'Elevated' if m['rel_vol'] > 120 else 'Normal'}</span>
    </div>
    <div class="ms-pressure-track">
      <div style="height:100%;width:{m['g_vola']}%;background:{vola_clr};border-radius:3px;transition:width 0.4s;"></div>
    </div>
  </div>
</div>""", unsafe_allow_html=True)

    # ── C. Signal Strength Cards ──────────────────────────────────────────────
    rsi = m["rsi_val"]
    ts  = m["trend_str"]
    bias = m["bias"]

    if   rsi >= 70: rsi_lbl, rsi_clr = "Overbought", "#f43f5e"
    elif rsi <= 30: rsi_lbl, rsi_clr = "Oversold",   "#f59e0b"
    else:           rsi_lbl, rsi_clr = "Neutral",    "#e2e8f0"

    if   "Strong Bull" in bias: b_clr, b_icon = "#00d4aa", "▲▲"
    elif "Bullish"     in bias: b_clr, b_icon = "#00d4aa", "▲"
    elif "Strong Bear" in bias: b_clr, b_icon = "#f43f5e", "▼▼"
    elif "Bearish"     in bias: b_clr, b_icon = "#f43f5e", "▼"
    else:                       b_clr, b_icon = "#f59e0b", "◆"

    e20_clr = "#00d4aa" if m["above_e20"] else "#f43f5e"
    e50_clr = "#00d4aa" if m["above_e50"] else "#f43f5e"
    rv_clr  = "#f59e0b" if m["rvol"] >= 1.5 else "#64748b"
    ts_clr  = "#00d4aa" if ts >= 30 else "#64748b"

    st.markdown(f"""
<div class="ms-sig-grid" style="grid-template-columns:1fr 1fr;">
  <div class="ms-sig-card" style="border-top:2px solid {rsi_clr};box-shadow:0 2px 8px {rsi_clr}18;">
    <div class="ms-sig-icon" style="color:{rsi_clr};">{rsi:.0f}</div>
    <div class="ms-sig-label" style="color:{rsi_clr};">RSI</div>
    <div class="ms-sig-sub">{rsi_lbl}</div>
  </div>
  <div class="ms-sig-card" style="border-top:2px solid {e20_clr};box-shadow:0 2px 8px {e20_clr}18;">
    <div class="ms-sig-icon" style="color:{e20_clr};">E20</div>
    <div class="ms-sig-label" style="color:{e20_clr};">EMA 20</div>
    <div class="ms-sig-sub">{'Above' if m['above_e20'] else 'Below'}</div>
  </div>
  <div class="ms-sig-card" style="border-top:2px solid {e50_clr};box-shadow:0 2px 8px {e50_clr}18;">
    <div class="ms-sig-icon" style="color:{e50_clr};">E50</div>
    <div class="ms-sig-label" style="color:{e50_clr};">EMA 50</div>
    <div class="ms-sig-sub">{'Above' if m['above_e50'] else 'Below'}</div>
  </div>
  <div class="ms-sig-card" style="border-top:2px solid {rv_clr};box-shadow:0 2px 8px {rv_clr}18;">
    <div class="ms-sig-icon" style="color:{rv_clr};">{m['rvol']:.1f}x</div>
    <div class="ms-sig-label" style="color:{rv_clr};">RelVol</div>
    <div class="ms-sig-sub">{'Spike' if m['rvol'] >= 1.5 else 'Normal'}</div>
  </div>
  <div class="ms-sig-card" style="border-top:2px solid {ts_clr};box-shadow:0 2px 8px {ts_clr}18;grid-column:span 2;">
    <div class="ms-sig-icon" style="color:{ts_clr};">TS {ts:.0f}</div>
    <div class="ms-sig-label" style="color:{ts_clr};">Trend Str.</div>
    <div class="ms-sig-sub">{'Strong trend' if ts >= 30 else 'Weak / no trend'}</div>
  </div>
</div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# MARKET SENTIMENT MODULE
# ════════════════════════════════════════════════════════════════════════════════

def _compute_sentiment(df: pd.DataFrame, ai_data: Dict) -> Dict:
    close  = df["Close"]
    open_  = df["Open"]
    volume = df["Volume"] if "Volume" in df.columns else pd.Series(np.ones(len(df)), index=df.index)

    is_bull  = close > open_
    buy_vol  = float(volume[is_bull].sum())
    sell_vol = float(volume[~is_bull].sum())
    total_v  = buy_vol + sell_vol or 1.0
    buy_pct  = round(buy_vol / total_v * 100)
    sell_pct = 100 - buy_pct

    n20      = min(20, len(df))
    avg_vol  = float(volume.mean()) or 1.0
    curr_vol = float(volume.iloc[-1])
    vol_ratio = round(curr_vol / avg_vol, 2)

    def _ret(n: int) -> float:
        idx = min(n, len(close) - 1)
        if idx == 0:
            return 0.0
        base = float(close.iloc[-idx - 1])
        return round((float(close.iloc[-1]) - base) / base * 100, 2) if base else 0.0

    mom_1d  = _ret(1)
    mom_5d  = _ret(5)
    mom_20d = _ret(20)
    intraday = round((float(close.iloc[-1]) - float(open_.iloc[-1])) / float(open_.iloc[-1]) * 100, 3) if len(open_) > 0 else 0.0

    pct_chg  = close.pct_change().dropna()
    vol_std  = float(pct_chg.std() * 100) if len(pct_chg) > 1 else 0.0
    hist_vol = float(pct_chg.rolling(60).std().iloc[-1] * 100) if len(pct_chg) >= 60 else vol_std
    rel_vol  = round(vol_std / hist_vol * 100) if hist_vol > 0 else 100

    curr     = float(close.iloc[-1])
    ema20_v  = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50_v  = float(close.ewm(span=50, adjust=False).mean().iloc[-1])

    rsi_val   = float(ai_data.get("rsi",       50)) if ai_data else 50.0
    trend_str = float(ai_data.get("trend_str", 25)) if ai_data else 25.0
    bias      = str(ai_data.get("bias", "Neutral")) if ai_data else "Neutral"
    rvol      = float(ai_data.get("rvol",       vol_ratio)) if ai_data else vol_ratio

    # Synthetic bid/ask order book levels (5 levels each side around current price)
    tick      = max(0.01, round(curr * 0.001, 4))   # 0.1% of price
    base_qty  = max(100, int(curr_vol / 15))
    bid_levels, ask_levels = [], []
    for i in range(1, 6):
        qty = round(max(100, int(base_qty / i)) / 100) * 100
        bid_levels.append({"price": round(curr - i * tick, 4), "qty": qty})
        ask_levels.append({"price": round(curr + i * tick, 4), "qty": qty})
    bid_total = sum(l["qty"] for l in bid_levels)
    ask_total = sum(l["qty"] for l in ask_levels)
    ba_total  = bid_total + ask_total or 1

    return {
        "buy_pct": buy_pct, "sell_pct": sell_pct,
        "buy_vol": buy_vol, "sell_vol": sell_vol,
        "vol_ratio": vol_ratio, "curr_vol": curr_vol,
        "mom_1d": mom_1d, "mom_5d": mom_5d, "mom_20d": mom_20d,
        "intraday": intraday,
        "rel_vol": rel_vol, "vol_std": vol_std,
        "rsi_val": rsi_val, "trend_str": trend_str, "bias": bias,
        "above_e20": curr > ema20_v, "above_e50": curr > ema50_v,
        "rvol": rvol, "n20": n20,
        "g_vol":  min(100, int(vol_ratio * 50)),
        "g_mom":  min(100, max(0, int(50 + mom_1d * 5))),
        "g_vola": min(100, max(0, rel_vol)),
        "g_buy":  buy_pct,
        "g_sell": sell_pct,
        "bid_levels": bid_levels,
        "ask_levels": ask_levels,
        "bid_total":  bid_total,
        "ask_total":  ask_total,
        "bid_bar_pct": round(bid_total / ba_total * 100),
    }


def _svg_gauge(title: str, pct: int, color: str, label: str) -> str:
    safe   = max(0, min(100, pct))
    circum = 201.06
    filled = safe / 100 * circum
    gap    = circum - filled
    return f"""
<div class="ms-gauge-card">
  <div class="ms-gauge-title">{title}</div>
  <svg viewBox="0 0 80 80" width="80" height="80" class="ms-gauge-svg">
    <circle cx="40" cy="40" r="32" fill="none" stroke="#1e2d45" stroke-width="8"/>
    <circle cx="40" cy="40" r="32" fill="none" stroke="{color}" stroke-width="8"
            stroke-dasharray="{filled:.1f} {gap:.1f}" stroke-dashoffset="50.3"
            stroke-linecap="round"
            style="filter:drop-shadow(0 0 5px {color}99);"/>
    <text x="40" y="45" text-anchor="middle"
          font-size="13" font-weight="800" fill="{color}"
          font-family="Courier New,monospace">{safe}</text>
  </svg>
  <div class="ms-gauge-label" style="color:{color};">{label}</div>
</div>"""


def _render_market_sentiment(df: pd.DataFrame, ai_data: Dict) -> None:
    if df is None or df.empty or len(df) < 5:
        st.info("Insufficient data for sentiment analysis.")
        return

    m = _compute_sentiment(df, ai_data)

    st.markdown("""
<div class="cfd-panel-header">
  <span class="cfd-panel-icon" style="background:#a855f722;color:#a855f7;">SN</span>
  <span class="cfd-panel-title">Market Sentiment</span>
  <span class="cfd-panel-desc">Bid/Ask pressure · Volume gauges · Signal cards · Momentum analytics</span>
</div>""", unsafe_allow_html=True)

    # ── Buy vs Sell Pressure Meter ────────────────────────────────────────────
    bias_glow = "#00d4aa" if m["buy_pct"] >= 50 else "#f43f5e"
    bias_lbl  = ("STRONG BUY" if m["buy_pct"] >= 65 else
                 "MILD BUY"   if m["buy_pct"] >= 55 else
                 "STRONG SELL" if m["sell_pct"] >= 65 else
                 "MILD SELL"  if m["sell_pct"] >= 55 else "BALANCED")
    st.markdown(f"""
<div class="ms-pressure-wrap">
  <div class="ms-pressure-header">
    <span style="color:#00d4aa;font-weight:800;font-size:0.85rem;">▲ BUY {m['buy_pct']}%</span>
    <span class="ms-pressure-title">Buy vs Sell Pressure</span>
    <span style="color:#f43f5e;font-weight:800;font-size:0.85rem;">▼ SELL {m['sell_pct']}%</span>
  </div>
  <div class="ms-pressure-track">
    <div class="ms-pressure-buy"  style="width:{m['buy_pct']}%;"></div>
    <div class="ms-pressure-sell" style="width:{m['sell_pct']}%;"></div>
  </div>
  <div class="ms-pressure-labels">
    <span style="color:#64748b;font-size:0.72rem;">Based on {m['n20']}-bar candle direction weighted by volume</span>
    <span style="color:{bias_glow};font-size:0.72rem;font-weight:700;">{bias_lbl}</span>
  </div>
</div>""", unsafe_allow_html=True)

    # ── Activity Gauges ───────────────────────────────────────────────────────
    gcols = st.columns(5, gap="small")
    vol_color  = "#00d4aa" if m["vol_ratio"] >= 1.5 else "#f59e0b" if m["vol_ratio"] >= 1.0 else "#64748b"
    mom_color  = "#00d4aa" if m["mom_1d"] > 0 else "#f43f5e"
    vola_color = "#f59e0b" if m["rel_vol"] > 120 else "#64748b"

    with gcols[0]:
        st.markdown(_svg_gauge("Volume Activity", m["g_vol"], vol_color,
                               f"{m['vol_ratio']:.1f}x avg"), unsafe_allow_html=True)
    with gcols[1]:
        st.markdown(_svg_gauge("Momentum", m["g_mom"], mom_color,
                               f"{m['mom_1d']:+.2f}% 1D"), unsafe_allow_html=True)
    with gcols[2]:
        st.markdown(_svg_gauge("Volatility", m["g_vola"], vola_color,
                               "Elevated" if m["rel_vol"] > 120 else "Normal"), unsafe_allow_html=True)
    with gcols[3]:
        st.markdown(_svg_gauge("Buying Pressure", m["g_buy"], "#00d4aa",
                               f"{m['buy_pct']}% bulls"), unsafe_allow_html=True)
    with gcols[4]:
        st.markdown(_svg_gauge("Selling Pressure", m["g_sell"], "#f43f5e",
                               f"{m['sell_pct']}% bears"), unsafe_allow_html=True)

    # ── Bid/Ask + Signal Cards ────────────────────────────────────────────────
    bid_col, sig_col = st.columns([1, 2], gap="small")
    with bid_col:
        _render_bid_ask_panel(m)
    with sig_col:
        _render_trend_signal_cards(m)

    # ── Momentum Analytics ────────────────────────────────────────────────────
    st.markdown('<div class="ms-divider"></div>', unsafe_allow_html=True)
    _render_momentum_analytics(m)


def _render_bid_ask_panel(m: Dict) -> None:
    def _fq(v: float) -> str:
        if v >= 1e7: return f"{v/1e7:.1f}Cr"
        if v >= 1e5: return f"{v/1e5:.1f}L"
        return f"{int(v):,}"

    def _fp(p: float) -> str:
        return f"{p:,.2f}" if p >= 1 else f"{p:.4f}"

    bid_levels = m.get("bid_levels", [])
    ask_levels = m.get("ask_levels", [])
    bid_total  = m.get("bid_total", 0)
    ask_total  = m.get("ask_total", 0)
    bid_pct    = m.get("bid_bar_pct", 50)
    ask_pct    = 100 - bid_pct

    # Build rows HTML
    bid_rows = ""
    for lv in bid_levels:
        bid_rows += f"""
  <div class="ba-row">
    <span class="ba-price">{_fp(lv['price'])}</span>
    <span class="ba-qty ba-bid-qty">{_fq(lv['qty'])}</span>
  </div>"""

    ask_rows = ""
    for lv in ask_levels:
        ask_rows += f"""
  <div class="ba-row">
    <span class="ba-price">{_fp(lv['price'])}</span>
    <span class="ba-qty ba-ask-qty">{_fq(lv['qty'])}</span>
  </div>"""

    st.markdown(f"""
<div class="ba-card">
  <div class="ba-header">Bid / Ask Order Sentiment</div>
  <div class="ba-columns">
    <div class="ba-col">
      <div class="ba-col-header">BID (BUY ORDERS)</div>
      {bid_rows}
    </div>
    <div class="ba-col ba-ask-col">
      <div class="ba-col-header">ASK (SELL ORDERS)</div>
      {ask_rows}
    </div>
  </div>
  <div class="ba-bar-wrap">
    <div class="ba-bar-bid" style="width:{bid_pct}%;"></div>
    <div class="ba-bar-ask" style="width:{ask_pct}%;"></div>
  </div>
  <div class="ba-totals">
    <span class="ba-bid-total">Bid total {_fq(bid_total)}</span>
    <span class="ba-ask-total">Ask total {_fq(ask_total)}</span>
  </div>
</div>""", unsafe_allow_html=True)


def _render_trend_signal_cards(m: Dict) -> None:
    rsi = m["rsi_val"]
    ts  = m["trend_str"]
    bias = m["bias"]

    if   rsi >= 70: rsi_lbl, rsi_clr = "RSI Overbought", "#f43f5e"
    elif rsi <= 30: rsi_lbl, rsi_clr = "RSI Oversold",   "#f59e0b"
    else:           rsi_lbl, rsi_clr = "RSI Neutral",    "#64748b"

    if   "Strong Bull" in bias: b_lbl, b_clr, b_icon = "Strong Bullish", "#00d4aa", "▲▲"
    elif "Bullish"     in bias: b_lbl, b_clr, b_icon = "Bullish",        "#00d4aa", "▲"
    elif "Strong Bear" in bias: b_lbl, b_clr, b_icon = "Strong Bearish", "#f43f5e", "▼▼"
    elif "Bearish"     in bias: b_lbl, b_clr, b_icon = "Bearish",        "#f43f5e", "▼"
    else:                       b_lbl, b_clr, b_icon = "Neutral",        "#f59e0b", "◆"

    signals = [
        (b_icon, b_lbl,                         b_clr,
         f"Institutional bias: {bias}"),
        (f"{rsi:.1f}", rsi_lbl,                 rsi_clr,
         "RSI(14) — momentum oscillator"),
        ("E20", f"{'Above' if m['above_e20'] else 'Below'} EMA20",
         "#00d4aa" if m["above_e20"] else "#f43f5e",
         "Price vs 20-period EMA"),
        ("E50", f"{'Above' if m['above_e50'] else 'Below'} EMA50",
         "#00d4aa" if m["above_e50"] else "#f43f5e",
         "Price vs 50-period EMA"),
        (f"{m['rvol']:.1f}x", "Relative Volume",
         "#f59e0b" if m["rvol"] >= 1.5 else "#64748b",
         "Vol spike" if m["rvol"] >= 1.5 else "Normal volume"),
        (f"TS {ts:.0f}", "Trend Strength",
         "#00d4aa" if ts >= 30 else "#64748b",
         "Strong trend" if ts >= 30 else "Weak / no trend"),
    ]

    cards_html = '<div class="ms-sig-grid">'
    for icon, label, color, sub in signals:
        cards_html += f"""
<div class="ms-sig-card" style="border-top:2px solid {color};box-shadow:0 2px 8px {color}18;">
  <div class="ms-sig-icon" style="color:{color};">{icon}</div>
  <div class="ms-sig-label" style="color:{color};">{label}</div>
  <div class="ms-sig-sub">{sub}</div>
</div>"""
    cards_html += '</div>'
    st.markdown(cards_html, unsafe_allow_html=True)


def _render_momentum_analytics(m: Dict) -> None:
    st.markdown("""
<div class="cfd-panel-header" style="margin-top:4px;">
  <span class="cfd-panel-icon" style="background:#4d9de022;color:#4d9de0;">MA</span>
  <span class="cfd-panel-title">Momentum Analytics</span>
  <span class="cfd-panel-desc">Intraday · 1D · 5D · 20D · Relative volatility · Trend strength</span>
</div>""", unsafe_allow_html=True)

    metrics = [
        ("Intraday",       m["intraday"],   "pct",   "Open → Current"),
        ("1D Change",      m["mom_1d"],     "pct",   "Yesterday → Today"),
        ("5D Change",      m["mom_5d"],     "pct",   "5-bar lookback"),
        ("20D Change",     m["mom_20d"],    "pct",   "20-bar lookback"),
        ("Rel. Volatility", m["rel_vol"],   "abs",   "vs 60-bar avg vol"),
        ("Trend Strength", m["trend_str"],  "abs",   "0–100 scale"),
    ]

    cols = st.columns(len(metrics), gap="small")
    for col, (name, val, kind, sub) in zip(cols, metrics):
        if kind == "pct":
            clr     = "#00d4aa" if val > 0 else "#f43f5e" if val < 0 else "#64748b"
            sign    = "+" if val > 0 else ""
            val_str = f"{sign}{val:.2f}%"
        else:
            clr     = "#00d4aa" if val >= 30 else "#f59e0b" if val >= 80 else "#64748b"
            val_str = f"{val:.0f}"

        col.markdown(f"""
<div class="ms-mom-card">
  <div class="ms-mom-label">{name}</div>
  <div class="ms-mom-val" style="color:{clr};">{val_str}</div>
  <div class="ms-mom-sub">{sub}</div>
</div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# ANALYSIS TABS
# ════════════════════════════════════════════════════════════════════════════════

# ── Performance Tab ───────────────────────────────────────────────────────────

def _render_performance_tab(df: pd.DataFrame, sym_display: str) -> None:
    if df is None or df.empty:
        st.info("No data for performance analysis.")
        return

    st.markdown("""
<div class="cfd-panel-header">
  <span class="cfd-panel-icon" style="background:#00d4aa22;color:#00d4aa;">PR</span>
  <span class="cfd-panel-title">Performance</span>
  <span class="cfd-panel-desc">Returns · Volatility · Drawdown · Daily return distribution</span>
</div>""", unsafe_allow_html=True)

    close = df["Close"]
    curr  = float(close.iloc[-1])

    def _ret(n: int) -> float:
        idx  = min(n, len(close) - 1)
        base = float(close.iloc[-idx - 1]) if idx > 0 else curr
        return round((curr - base) / base * 100, 2) if base else 0.0

    pct_chg = close.pct_change().dropna()
    ann_vol = round(float(pct_chg.std()) * (252 ** 0.5) * 100, 2) if len(pct_chg) > 1 else 0.0
    max_dd  = round(float(((close - close.cummax()) / close.cummax() * 100).min()), 2)
    sharpe  = round((_ret(252) / ann_vol) if ann_vol > 0 else 0.0, 2)

    periods = [("1D", _ret(1)), ("5D", _ret(5)), ("1M", _ret(22)),
               ("3M", _ret(66)), ("6M", _ret(132)), ("1Y", _ret(252))]

    chips_html = '<div class="perf-return-grid">'
    for label, r in periods:
        clr  = "#00d4aa" if r >= 0 else "#f43f5e"
        sign = "+" if r >= 0 else ""
        chips_html += f"""
<div class="perf-return-chip" style="border-color:{clr}44;">
  <div class="perf-chip-period">{label}</div>
  <div class="perf-chip-val" style="color:{clr};">{sign}{r:.2f}%</div>
</div>"""
    chips_html += '</div>'
    st.markdown(chips_html, unsafe_allow_html=True)

    mc1, mc2, mc3, mc4 = st.columns(4, gap="small")
    for col, (lbl, val, clr, sub) in zip(
        [mc1, mc2, mc3, mc4],
        [
            ("Ann. Volatility", f"{ann_vol:.2f}%", "#f59e0b",  "Annualised std dev"),
            ("Max Drawdown",    f"{max_dd:.2f}%",  "#f43f5e",  "Peak to trough"),
            ("Sharpe (1Y)",     f"{sharpe:.2f}",   "#4d9de0",  "Return / volatility"),
            ("Current",         f"₹{curr:,.2f}",   "#e2e8f0",  "Latest close price"),
        ],
    ):
        col.markdown(f"""
<div class="ms-mom-card">
  <div class="ms-mom-label">{lbl}</div>
  <div class="ms-mom-val" style="color:{clr};">{val}</div>
  <div class="ms-mom-sub">{sub}</div>
</div>""", unsafe_allow_html=True)

    # Daily returns bar chart (last 40 bars)
    daily = pct_chg.tail(40) * 100
    if not daily.empty:
        mx = max(abs(daily.max()), abs(daily.min()), 0.01)
        bars = '<div class="perf-hist-wrap"><div class="perf-hist-title">Last 40-Bar Daily Returns</div><div class="perf-hist-bars">'
        for r in daily:
            clr = "#00d4aa" if r >= 0 else "#f43f5e"
            h   = int(abs(r) / mx * 90)
            bars += f'<div class="perf-hist-bar" style="height:{max(2,h)}px;background:{clr};"></div>'
        bars += '</div></div>'
        st.markdown(bars, unsafe_allow_html=True)

    # Rolling volatility chart
    roll_vol = pct_chg.rolling(10).std().dropna() * 100
    if not roll_vol.empty:
        vdata = roll_vol.tail(60).tolist()
        mx    = max(vdata) or 1.0
        bars  = '<div class="perf-hist-wrap"><div class="perf-hist-title">Rolling 10-bar Volatility</div><div class="perf-hist-bars">'
        for v in vdata:
            h = int(v / mx * 90)
            bars += f'<div class="perf-hist-bar" style="height:{max(2,h)}px;background:#4d9de0;"></div>'
        bars += '</div></div>'
        st.markdown(bars, unsafe_allow_html=True)


# ── Fundamentals Tab ──────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_ticker_info(symbol: str) -> Dict:
    try:
        import yfinance as yf
        return yf.Ticker(symbol).info or {}
    except Exception:
        return {}


def _render_fundamentals_tab(symbol: str, sym_display: str) -> None:
    st.markdown("""
<div class="cfd-panel-header">
  <span class="cfd-panel-icon" style="background:#4d9de022;color:#4d9de0;">FU</span>
  <span class="cfd-panel-title">Fundamentals</span>
  <span class="cfd-panel-desc">Valuation · Profitability · Company profile</span>
</div>""", unsafe_allow_html=True)

    with st.spinner("Loading fundamentals…"):
        info = _fetch_ticker_info(symbol)

    if not info:
        st.info("Fundamental data unavailable for this symbol.")
        return

    def _fmtv(v, prefix="", pct=False, decimals=2):
        if v is None or (isinstance(v, float) and v != v):
            return "—"
        try:
            f = float(v)
            if pct:
                return f"{f * 100:.2f}%"
            if abs(f) >= 1e12: return f"{prefix}{f/1e12:.2f}T"
            if abs(f) >= 1e9:  return f"{prefix}{f/1e9:.2f}B"
            if abs(f) >= 1e7:  return f"{prefix}{f/1e7:.2f}Cr"
            if abs(f) >= 1e5:  return f"{prefix}{f/1e5:.2f}L"
            return f"{prefix}{f:.{decimals}f}"
        except Exception:
            return str(v)

    # Company overview card
    overview = {
        "Sector":    info.get("sector",   "—"),
        "Industry":  info.get("industry", "—"),
        "Country":   info.get("country",  "—"),
        "Employees": f"{info['fullTimeEmployees']:,}" if info.get("fullTimeEmployees") else "—",
        "Website":   info.get("website",  "—"),
    }
    ov_html = '<div class="fund-overview-card">'
    for k, v in overview.items():
        ov_html += f'<div class="fund-overview-row"><span class="fund-ov-label">{k}</span><span class="fund-ov-val">{v}</span></div>'
    ov_html += '</div>'
    st.markdown(ov_html, unsafe_allow_html=True)

    # Metrics grid
    metrics = [
        ("P/E Ratio",    _fmtv(info.get("trailingPE"))),
        ("Fwd P/E",      _fmtv(info.get("forwardPE"))),
        ("P/B Ratio",    _fmtv(info.get("priceToBook"))),
        ("P/S Ratio",    _fmtv(info.get("priceToSalesTrailing12Months"))),
        ("Market Cap",   _fmtv(info.get("marketCap"), prefix="₹")),
        ("EPS (TTM)",    _fmtv(info.get("trailingEps"), prefix="₹")),
        ("Div. Yield",   _fmtv(info.get("dividendYield"), pct=True)),
        ("Beta",         _fmtv(info.get("beta"))),
        ("ROE",          _fmtv(info.get("returnOnEquity"), pct=True)),
        ("ROA",          _fmtv(info.get("returnOnAssets"), pct=True)),
        ("Debt/Equity",  _fmtv(info.get("debtToEquity"))),
        ("52W High",     _fmtv(info.get("fiftyTwoWeekHigh"), prefix="₹")),
        ("52W Low",      _fmtv(info.get("fiftyTwoWeekLow"),  prefix="₹")),
        ("Avg Volume",   _fmtv(info.get("averageVolume"))),
        ("Float",        _fmtv(info.get("floatShares"))),
        ("Short Ratio",  _fmtv(info.get("shortRatio"))),
    ]
    grid = '<div class="fund-metrics-grid">'
    for name, val in metrics:
        clr = "#e2e8f0" if val != "—" else "#334155"
        grid += f'<div class="fund-metric-card"><div class="fund-metric-label">{name}</div><div class="fund-metric-val" style="color:{clr};">{val}</div></div>'
    grid += '</div>'
    st.markdown(grid, unsafe_allow_html=True)

    summary = info.get("longBusinessSummary", "")
    if summary:
        st.markdown(f"""
<div class="fund-summary">
  <div class="fund-summary-title">Business Overview</div>
  <div class="fund-summary-text">{summary[:700]}{'…' if len(summary) > 700 else ''}</div>
</div>""", unsafe_allow_html=True)


# ── Financials Tab ────────────────────────────────────────────────────────────

def _render_financials_tab(symbol: str, sym_display: str) -> None:
    st.markdown("""
<div class="cfd-panel-header">
  <span class="cfd-panel-icon" style="background:#f59e0b22;color:#f59e0b;">FN</span>
  <span class="cfd-panel-title">Financials</span>
  <span class="cfd-panel-desc">Revenue · Profit · Cash flow · Key financial ratios</span>
</div>""", unsafe_allow_html=True)

    with st.spinner("Loading financials…"):
        info = _fetch_ticker_info(symbol)

    if not info:
        st.info("Financial data unavailable for this symbol.")
        return

    def _cr(v):
        if v is None or (isinstance(v, float) and v != v):
            return "—"
        try:
            f = float(v)
            if abs(f) >= 1e12: return f"₹{f/1e12:.2f}T"
            if abs(f) >= 1e9:  return f"₹{f/1e9:.2f}B"
            if abs(f) >= 1e7:  return f"₹{f/1e7:.1f}Cr"
            if abs(f) >= 1e5:  return f"₹{f/1e5:.1f}L"
            return f"₹{f:,.0f}"
        except Exception:
            return "—"

    def _pct(v):
        if v is None or (isinstance(v, float) and v != v):
            return "—", "#64748b"
        try:
            p = float(v) * 100
            return f"{p:.2f}%", "#00d4aa" if p >= 0 else "#f43f5e"
        except Exception:
            return "—", "#64748b"

    fin_items = [
        ("Revenue (TTM)",   _cr(info.get("totalRevenue")),     "#e2e8f0"),
        ("Gross Profit",    _cr(info.get("grossProfits")),     "#e2e8f0"),
        ("EBITDA",          _cr(info.get("ebitda")),           "#e2e8f0"),
        ("Net Income",      _cr(info.get("netIncomeToCommon")),  "#e2e8f0"),
        ("Free Cash Flow",  _cr(info.get("freeCashflow")),     "#e2e8f0"),
        ("Operating Cash",  _cr(info.get("operatingCashflow")), "#e2e8f0"),
        ("Total Cash",      _cr(info.get("totalCash")),        "#e2e8f0"),
        ("Total Debt",      _cr(info.get("totalDebt")),        "#f43f5e" if info.get("totalDebt") else "#e2e8f0"),
        ("Profit Margin",   *_pct(info.get("profitMargins"))),
        ("Op. Margin",      *_pct(info.get("operatingMargins"))),
        ("ROE",             *_pct(info.get("returnOnEquity"))),
        ("ROA",             *_pct(info.get("returnOnAssets"))),
    ]

    grid = '<div class="fund-metrics-grid">'
    for row in fin_items:
        name, val, clr = row
        grid += f'<div class="fund-metric-card"><div class="fund-metric-label">{name}</div><div class="fund-metric-val" style="color:{clr};">{val}</div></div>'
    grid += '</div>'
    st.markdown(grid, unsafe_allow_html=True)


# ── Peers Tab ─────────────────────────────────────────────────────────────────

_SECTOR_PEERS: Dict[str, List[str]] = {
    "Technology":     ["TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS"],
    "Banking":        ["HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS"],
    "Financial":      ["BAJFINANCE.NS", "BAJAJFINSV.NS", "HDFCLIFE.NS", "SBILIFE.NS", "MUTHOOTFIN.NS"],
    "Consumer":       ["HINDUNILVR.NS", "NESTLEIND.NS", "BRITANNIA.NS", "DABUR.NS", "MARICO.NS"],
    "Pharma":         ["SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS", "APOLLOHOSP.NS"],
    "Auto":           ["MARUTI.NS", "TATAMOTORS.NS", "M&M.NS", "BAJAJ-AUTO.NS", "EICHERMOT.NS"],
    "Energy":         ["RELIANCE.NS", "ONGC.NS", "BPCL.NS", "IOC.NS", "GAIL.NS"],
    "Metals":         ["TATASTEEL.NS", "HINDALCO.NS", "JSWSTEEL.NS", "COALINDIA.NS", "VEDL.NS"],
    "Infrastructure": ["ADANIPORTS.NS", "ULTRACEMCO.NS", "GRASIM.NS", "NTPC.NS", "POWERGRID.NS"],
}


def _render_peers_tab(symbol: str, sym_display: str) -> None:
    st.markdown("""
<div class="cfd-panel-header">
  <span class="cfd-panel-icon" style="background:#ec489922;color:#ec4899;">PE</span>
  <span class="cfd-panel-title">Peers</span>
  <span class="cfd-panel-desc">Sector comparison · Relative performance · Today's change</span>
</div>""", unsafe_allow_html=True)

    info   = _fetch_ticker_info(symbol)
    sector = info.get("sector", "")

    peer_syms: List[str] = []
    for sec_key, peers in _SECTOR_PEERS.items():
        if symbol in peers or sec_key.lower() in sector.lower():
            peer_syms = [p for p in peers if p != symbol][:4]
            break
    if not peer_syms:
        peer_syms = [p for p in ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS"] if p != symbol][:4]

    all_syms = [symbol] + peer_syms
    with st.spinner("Loading peer data…"):
        price_data = get_ticker_prices(all_syms)
    price_map = {p["symbol"]: p for p in price_data}

    rows_html = ""
    for sym in all_syms:
        name  = get_display_name(sym)
        pdata = price_map.get(sym, {})
        price = pdata.get("price")
        pct   = pdata.get("pct_change", 0.0)
        is_me = sym == symbol
        clr   = "#00d4aa" if pct >= 0 else "#f43f5e"
        row_c = "peer-row-active" if is_me else "peer-row"
        sc    = sym.replace(".NS", "").replace(".BO", "")
        ps    = f"₹{price:,.2f}" if price else "—"
        me_tag = " ◀" if is_me else ""
        rows_html += f"""
<div class="{row_c}">
  <div class="peer-sym">{sc}{me_tag}</div>
  <div class="peer-name">{name[:30]}</div>
  <div class="peer-price">{ps}</div>
  <div class="peer-pct" style="color:{clr};">{pct:+.2f}%</div>
</div>"""

    st.markdown(f"""
<div class="peer-table-wrap">
  <div class="peer-table-head">
    <span>Symbol</span><span>Company</span><span>Price</span><span>1D %</span>
  </div>
  {rows_html}
</div>""", unsafe_allow_html=True)


# ── News Tab ──────────────────────────────────────────────────────────────────

def _render_news_tab(symbol: str, sym_display: str) -> None:
    st.markdown(f"""
<div class="cfd-panel-header">
  <span class="cfd-panel-icon" style="background:#f59e0b22;color:#f59e0b;">NW</span>
  <span class="cfd-panel-title">News — {sym_display}</span>
  <span class="cfd-panel-desc">Stock-specific updates · Market headlines</span>
</div>""", unsafe_allow_html=True)

    with st.spinner("Fetching news…"):
        try:
            import yfinance as yf
            yfnews = list(yf.Ticker(symbol).news or [])
        except Exception:
            yfnews = []
        headlines = fetch_all_headlines(8)

    if yfnews:
        st.markdown('<div class="ms-mom-label" style="margin:8px 0;">Stock-Specific News</div>',
                    unsafe_allow_html=True)
        for item in yfnews[:6]:
            title    = item.get("title", "")
            link     = item.get("link", "#")
            pub      = item.get("providerPublishTime", 0)
            provider = item.get("publisher", "")
            pub_str  = _dt.datetime.fromtimestamp(pub).strftime("%d %b %Y %H:%M") if pub else ""
            st.markdown(f"""
<div class="news-card-market">
  <a href="{link}" target="_blank" class="news-card-title">{title}</a>
  <div class="news-card-meta">{provider} · {pub_str}</div>
</div>""", unsafe_allow_html=True)

    if headlines:
        st.markdown('<div class="ms-divider"></div>', unsafe_allow_html=True)
        st.markdown('<div class="ms-mom-label" style="margin:8px 0;">Market Headlines</div>',
                    unsafe_allow_html=True)
        for item in headlines:
            title     = item.get("title", "")
            source    = item.get("source", "")
            link      = item.get("link", "#")
            published = str(item.get("published", ""))
            st.markdown(f"""
<div class="news-card-market">
  <a href="{link}" target="_blank" class="news-card-title">{title}</a>
  <div class="news-card-meta">{source} · {published[:16]}</div>
</div>""", unsafe_allow_html=True)

    if not yfnews and not headlines:
        st.info("No news available at this time.")


# ── Notes Tab ─────────────────────────────────────────────────────────────────

def _render_notes_tab(symbol: str, sym_display: str) -> None:
    st.markdown(f"""
<div class="cfd-panel-header">
  <span class="cfd-panel-icon" style="background:#64748b22;color:#94a3b8;">NT</span>
  <span class="cfd-panel-title">Notes — {sym_display}</span>
  <span class="cfd-panel-desc">Trade notes · Analysis observations · Session log</span>
</div>""", unsafe_allow_html=True)

    note_key = f"cs_notes_{symbol}"
    existing = st.session_state.get(note_key, "")

    note = st.text_area(
        "notes",
        value=existing,
        height=260,
        key=f"cs_notes_input_{symbol}",
        label_visibility="collapsed",
        placeholder=f"Trade notes for {sym_display}…\n\nEntry rationale · Key levels · Observations…",
    )

    c_save, c_clear, _ = st.columns([1, 1, 4])
    if c_save.button("Save Notes", key=f"cs_notes_save_{symbol}", use_container_width=True):
        st.session_state[note_key] = note
        st.toast(f"Notes saved for {sym_display}")
    if c_clear.button("Clear", key=f"cs_notes_clear_{symbol}", use_container_width=True):
        st.session_state[note_key] = ""
        st.rerun()

    if existing:
        st.markdown(f"""
<div class="fund-summary" style="margin-top:10px;">
  <div class="fund-summary-title">Saved Notes</div>
  <pre class="fund-summary-text" style="white-space:pre-wrap;font-family:inherit;">{existing}</pre>
</div>""", unsafe_allow_html=True)
