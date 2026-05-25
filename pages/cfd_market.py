"""
CFD Market — institutional-grade multi-asset trading terminal.
Assets: Gold (XAUUSD), Silver (XAGUSD), Bitcoin (BTCUSD), Ethereum (ETHUSD)

Layout:
  ┌─ Asset header cards (live price + Δ) ───────────────────────────────────┐
  │  Timeframe strip                                                          │
  ├─ Chart (3.2) ─────────────────────┬─ Pine Manager (0.9) ─────────────────┤
  │  SMC zone overlays                │  Indicator drawer                     │
  │  OHLCV strip                      │  Saved layouts                        │
  ├─ Order Block panel ───────────────┴─ FVG / IFVG panel ─────────────────  │
  ├─ Market Structure panel ──────────────────────────────────────────────── │
  └─ Institutional AI Analysis panel ─────────────────────────────────────── │
"""
from __future__ import annotations

import time as _time_mod
import json

import pandas as pd
import numpy as np
import streamlit as st
from typing import Dict, List, Optional

from data.fetcher import get_history
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


# ── Asset registry ─────────────────────────────────────────────────────────────

CFD_ASSETS: Dict[str, Dict] = {
    "XAUUSD":    {"symbol": "GC=F",      "name": "Gold",       "icon": "Au",  "cat": "Metals", "unit": "USD/oz"},
    "XAGUSD":    {"symbol": "SI=F",      "name": "Silver",     "icon": "Ag",  "cat": "Metals", "unit": "USD/oz"},
    "BTCUSD":    {"symbol": "BTC-USD",   "name": "Bitcoin",    "icon": "BTC", "cat": "Crypto", "unit": "USD"},
    "ETHUSD":    {"symbol": "ETH-USD",   "name": "Ethereum",   "icon": "ETH", "cat": "Crypto", "unit": "USD"},
    "NIFTY50":   {"symbol": "^NSEI",     "name": "Nifty 50",   "icon": "N50", "cat": "Index",  "unit": "INR"},
    "BANKNIFTY": {"symbol": "^NSEBANK",  "name": "Bank Nifty", "icon": "BNK", "cat": "Index",  "unit": "INR"},
}

_CFD_TF: Dict[str, Dict] = {
    "1m":  {"period": "7d",   "interval": "1m",  "label": "1m",  "resample": None},
    "5m":  {"period": "60d",  "interval": "5m",  "label": "5m",  "resample": None},
    "15m": {"period": "60d",  "interval": "15m", "label": "15m", "resample": None},
    "1H":  {"period": "730d", "interval": "60m", "label": "1H",  "resample": None},
    "4H":  {"period": "730d", "interval": "60m", "label": "4H",  "resample": "4h"},
    "1D":  {"period": "5y",   "interval": "1d",  "label": "1D",  "resample": None},
}
_TF_KEYS = list(_CFD_TF.keys())

_CHART_HEIGHTS = {"Compact": 460, "Standard": 580, "Expanded": 700, "Full": 840}

# ── Session state ──────────────────────────────────────────────────────────────

def _init_state() -> None:
    defaults = {
        "cfd_asset":        "XAUUSD",
        "cfd_tf":           "1H",
        "cfd_height_lbl":   "Standard",
        "cfd_show_vol":     True,
        "cfd_chart_engine": "Lightweight",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── Data fetcher ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def _load_data(symbol: str, period: str, interval: str, resample: Optional[str]) -> Optional[pd.DataFrame]:
    try:
        df = get_history(symbol, period=period, interval=interval)
        if df is None or df.empty:
            return None
        if resample:
            df = df.resample(resample).agg({
                "Open": "first", "High": "max", "Low": "min",
                "Close": "last", "Volume": "sum",
            }).dropna(how="any")
        df.index = pd.to_datetime(df.index)
        return df
    except Exception:
        return None


# ── Zone builder ───────────────────────────────────────────────────────────────

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

    for f in fvg.get("bullish", []):
        zones.append({
            "time_start":   f["time_start"],
            "time_end":     far_future,
            "high":         f["high"],
            "low":          f["low"],
            "fill_color":   "#4d9de014",
            "border_color": "#4d9de060",
            "label":        "FVG+",
            "label_color":  "#4d9de0cc",
        })

    for f in fvg.get("bearish", []):
        zones.append({
            "time_start":   f["time_start"],
            "time_end":     far_future,
            "high":         f["high"],
            "low":          f["low"],
            "fill_color":   "#f59e0b10",
            "border_color": "#f59e0b55",
            "label":        "FVG-",
            "label_color":  "#f59e0bcc",
        })

    for f in fvg.get("bull_ifvg", [])[-2:]:
        zones.append({
            "time_start":   f["time_start"],
            "time_end":     far_future,
            "high":         f["high"],
            "low":          f["low"],
            "fill_color":   "#a855f710",
            "border_color": "#a855f755",
            "label":        "IFVG",
            "label_color":  "#a855f7cc",
        })

    for f in fvg.get("bear_ifvg", [])[-2:]:
        zones.append({
            "time_start":   f["time_start"],
            "time_end":     far_future,
            "high":         f["high"],
            "low":          f["low"],
            "fill_color":   "#ec489914",
            "border_color": "#ec489960",
            "label":        "IFVG",
            "label_color":  "#ec4899cc",
        })

    return zones


# ── Price helpers ──────────────────────────────────────────────────────────────

def _fmt_price(p: float, asset_key: str) -> str:
    if asset_key in ("BTCUSD", "ETHUSD"):
        return f"{p:,.2f}"
    return f"{p:,.4f}" if p < 100 else f"{p:,.2f}"


def _fmt_vol(v: float) -> str:
    if v >= 1e9: return f"{v/1e9:.2f}B"
    if v >= 1e6: return f"{v/1e6:.1f}M"
    if v >= 1e3: return f"{v/1e3:.0f}K"
    return str(int(v))


# ── Page entry point ───────────────────────────────────────────────────────────

def render_cfd_market() -> None:
    _init_state()
    db = get_pine_db()

    # ── Page header ──────────────────────────────────────────────────────────
    st.markdown("""
<div class="cfd-page-header">
  <div class="cfd-page-title">
    <span class="cfd-title-diamond">◈</span>
    CFD <span class="cfd-title-accent">Market</span>
  </div>
  <div class="cfd-page-subtitle">Institutional Multi-Asset · Smart Money Concepts · Real-Time Analysis</div>
</div>""", unsafe_allow_html=True)

    # ── Asset selector ───────────────────────────────────────────────────────
    _render_asset_cards()

    # ── Timeframe strip ──────────────────────────────────────────────────────
    _render_tf_strip()

    st.markdown('<div class="cs-divider"></div>', unsafe_allow_html=True)

    # ── Load data — try background store first, fall back to direct fetch ────
    asset_key = st.session_state.cfd_asset
    asset     = CFD_ASSETS[asset_key]
    tf_key    = st.session_state.cfd_tf
    tf        = _CFD_TF[tf_key]

    dm = get_data_manager()
    ic = get_indicator_cache()

    # Non-blocking read from background store (returns stale if refreshing)
    df = dm.get_df(
        asset["symbol"], tf["period"], tf["interval"],
        resample=tf.get("resample"), ttl=60, priority=10,
    )
    if df is None:
        # First visit or cold start — fall back to direct blocking fetch once,
        # then the background store takes over on subsequent reruns.
        df = _load_data(asset["symbol"], tf["period"], tf["interval"], tf.get("resample"))

    if df is None or df.empty:
        st.warning(f"No market data for **{asset['name']}**. Try a different timeframe or check your connection.")
        return

    # ── SMC computations — hash-gated: skip if candle data unchanged ─────────
    # candle_hash is None only when background store hasn't fetched yet;
    # in that case the indicator cache always computes fresh.
    _ckey = f"{asset_key}_{tf_key}"
    _h    = dm.get_hash(asset["symbol"], tf["period"], tf["interval"], tf.get("resample"))

    ob_data  = ic.compute(f"ob_{_ckey}",  _h, detect_order_blocks,    df)
    fvg_data = ic.compute(f"fvg_{_ckey}", _h, detect_fvg,             df)
    ms_data  = ic.compute(f"ms_{_ckey}",  _h, detect_market_structure, df)
    ai_data  = ic.compute(f"ai_{_ckey}",  _h, institutional_analysis,  df)
    zones    = _build_zones(ob_data, fvg_data, int(_time_mod.time()))

    # ── Inline SMC strip (above chart) ────────────────────────────────────────
    smc_config   = _render_inline_smc_strip("cfd")
    visible_zones = filter_zones_by_smc(zones, smc_config)

    # ── Two-column layout: chart (3.0) + sentiment panel (1.1) ───────────────
    chart_col, panel_col = st.columns([3.0, 1.1], gap="small")

    with chart_col:
        # ── Chart controls ────────────────────────────────────────────────
        h_col, vol_col, eng_col, _spacer, ref_col = st.columns([1.2, 0.8, 1.4, 2.1, 0.4])
        with h_col:
            lbl = st.selectbox(
                "Height", list(_CHART_HEIGHTS.keys()),
                index=list(_CHART_HEIGHTS.keys()).index(
                    st.session_state.get("cfd_height_lbl", "Standard")
                ),
                key="cfd_height_sel", label_visibility="collapsed",
            )
            st.session_state.cfd_height_lbl = lbl
        with vol_col:
            st.session_state.cfd_show_vol = st.checkbox(
                "Volume", value=st.session_state.cfd_show_vol, key="cfd_vol_cb"
            )
        with eng_col:
            from components.chart_engine import render_engine_selector
            render_engine_selector("cfd")
        with ref_col:
            if st.button("⟳", key="cfd_refresh", help="Force-refresh data & indicators"):
                dm.force_refresh(
                    asset["symbol"], tf["period"],
                    tf["interval"], tf.get("resample"),
                )
                ic.invalidate(_ckey)
                _load_data.clear()
                st.rerun()

        height = _CHART_HEIGHTS.get(st.session_state.get("cfd_height_lbl", "Standard"), 580)
        engine = st.session_state.get("cfd_chart_engine", "Lightweight")

        # ── Chart (engine-dispatched) ──────────────────────────────────────
        from components.chart_engine import render_chart as _render_chart
        _render_chart(
            engine         = engine,
            symbol         = asset["symbol"],
            df             = df,
            timeframe      = tf_key,
            height         = height,
            display_name   = asset_key,
            show_volume    = st.session_state.cfd_show_vol,
            zones          = visible_zones,
            extra_overlays = None,
        )

        _render_price_strip(asset_key, asset, df)

    with panel_col:
        _render_cfd_sentiment_panel(df, ai_data)

    # ── Analysis panels ───────────────────────────────────────────────────────
    st.markdown('<div class="cfd-panels-divider"></div>', unsafe_allow_html=True)
    _render_order_block_panel(ob_data)
    st.markdown('<div class="cfd-panels-divider"></div>', unsafe_allow_html=True)
    _render_fvg_panel(fvg_data)
    st.markdown('<div class="cfd-panels-divider"></div>', unsafe_allow_html=True)
    _render_market_structure_panel(ms_data, df)
    st.markdown('<div class="cfd-panels-divider"></div>', unsafe_allow_html=True)
    _render_institutional_panel(ai_data, df)
    st.markdown('<div class="cfd-panels-divider"></div>', unsafe_allow_html=True)
    _render_ideal_entry_section(asset_key, asset, df, ob_data, fvg_data, ms_data)


# ── Inline SMC strip ──────────────────────────────────────────────────────────

def _render_inline_smc_strip(prefix: str) -> Dict:
    """Horizontal SMC visibility strip rendered above the chart. Returns smc_config."""
    sk_ob   = f"{prefix}_smc_show_ob"
    sk_fvg  = f"{prefix}_smc_show_fvg"
    sk_ifvg = f"{prefix}_smc_show_ifvg"
    for sk in (sk_ob, sk_fvg, sk_ifvg):
        if sk not in st.session_state:
            st.session_state[sk] = True

    st.markdown('<div class="cfd-smc-strip">', unsafe_allow_html=True)
    label_col, ob_col, fvg_col, ifvg_col, _pad = st.columns([0.6, 1.0, 1.0, 1.1, 3.0])
    with label_col:
        st.markdown('<div class="cfd-smc-strip-label">◈ SMC</div>', unsafe_allow_html=True)
    with ob_col:
        st.session_state[sk_ob] = st.checkbox(
            "Bull & Bear OB", value=st.session_state[sk_ob], key=f"{prefix}_smc_ob_cb"
        )
    with fvg_col:
        st.session_state[sk_fvg] = st.checkbox(
            "FVG (Bull/Bear)", value=st.session_state[sk_fvg], key=f"{prefix}_smc_fvg_cb"
        )
    with ifvg_col:
        st.session_state[sk_ifvg] = st.checkbox(
            "Inverse FVG", value=st.session_state[sk_ifvg], key=f"{prefix}_smc_ifvg_cb"
        )
    st.markdown('</div>', unsafe_allow_html=True)

    return {
        "show_ob":   st.session_state[sk_ob],
        "show_fvg":  st.session_state[sk_fvg],
        "show_ifvg": st.session_state[sk_ifvg],
    }


# ── Market Sentiment panel ─────────────────────────────────────────────────────

def _render_cfd_sentiment_panel(df: pd.DataFrame, ai: Dict) -> None:
    """Compact vertical Market Sentiment panel replacing the indicator sidebar."""
    if not ai:
        st.markdown('<div class="cfd-sent-empty">No analysis data</div>', unsafe_allow_html=True)
        return

    bias      = ai.get("bias", "Neutral")
    bull_prob = ai.get("bull_prob", 50)
    bear_prob = ai.get("bear_prob", 50)
    rsi_val   = ai.get("rsi", 50)
    mom_lbl   = ai.get("momentum_lbl", "Flat")
    mom       = ai.get("momentum", 0)
    vol_pct   = ai.get("volatility", 0)
    ts        = ai.get("trend_str", 25)
    rvol      = ai.get("rvol", 1.0)

    # ── A. Bid/Ask Order Sentiment ────────────────────────────────────────────
    bias_clr = "#00d4aa" if "Bull" in bias else ("#f43f5e" if "Bear" in bias else "#f59e0b")
    buy_pct  = bull_prob
    sell_pct = bear_prob
    st.markdown(f"""
<div class="ms-bidask-card">
  <div class="ms-bidask-title">◈ ORDER SENTIMENT</div>
  <div class="ms-bidask-row">
    <span class="ms-bidask-label" style="color:#00d4aa;">BUY</span>
    <div class="ms-bidask-bar-wrap">
      <div class="ms-bidask-bar" style="width:{buy_pct}%;background:#00d4aa;"></div>
    </div>
    <span class="ms-bidask-val" style="color:#00d4aa;">{buy_pct}%</span>
  </div>
  <div class="ms-bidask-row">
    <span class="ms-bidask-label" style="color:#f43f5e;">SELL</span>
    <div class="ms-bidask-bar-wrap">
      <div class="ms-bidask-bar" style="width:{sell_pct}%;background:#f43f5e;"></div>
    </div>
    <span class="ms-bidask-val" style="color:#f43f5e;">{sell_pct}%</span>
  </div>
  <div class="ms-bidask-meta">
    <div class="ms-bidask-meta-row">
      <span style="color:#64748b;font-size:0.68rem;">BIAS</span>
      <span style="color:{bias_clr};font-size:0.72rem;font-weight:700;">{bias}</span>
    </div>
  </div>
</div>""", unsafe_allow_html=True)

    # ── B. Activity Gauges ────────────────────────────────────────────────────
    vol_bar  = min(100, int(vol_pct * 25))
    mom_bar  = min(100, abs(int(mom * 500)))
    ts_bar   = min(100, int(ts))
    mom_clr  = "#00d4aa" if mom > 0 else ("#f43f5e" if mom < 0 else "#64748b")
    vol_clr  = "#f59e0b" if vol_pct > 2 else "#4d9de0"
    ts_clr   = "#00d4aa" if ts > 30 else "#64748b"

    st.markdown(f"""
<div class="ms-pressure-wrap">
  <div class="ms-pressure-title">◈ ACTIVITY GAUGES</div>
  <div style="margin-bottom:8px;">
    <div style="display:flex;justify-content:space-between;font-size:0.68rem;margin-bottom:3px;">
      <span style="color:#94a3b8;">Volume Activity</span>
      <span style="color:{vol_clr};font-weight:700;">{vol_pct:.2f}%</span>
    </div>
    <div class="ms-pressure-track">
      <div style="height:100%;width:{vol_bar}%;background:{vol_clr};border-radius:3px;transition:width 0.4s;"></div>
    </div>
  </div>
  <div style="margin-bottom:8px;">
    <div style="display:flex;justify-content:space-between;font-size:0.68rem;margin-bottom:3px;">
      <span style="color:#94a3b8;">Momentum</span>
      <span style="color:{mom_clr};font-weight:700;">{mom_lbl}</span>
    </div>
    <div class="ms-pressure-track">
      <div style="height:100%;width:{mom_bar}%;background:{mom_clr};border-radius:3px;transition:width 0.4s;"></div>
    </div>
  </div>
  <div>
    <div style="display:flex;justify-content:space-between;font-size:0.68rem;margin-bottom:3px;">
      <span style="color:#94a3b8;">Trend Strength</span>
      <span style="color:{ts_clr};font-weight:700;">{ts:.0f}</span>
    </div>
    <div class="ms-pressure-track">
      <div style="height:100%;width:{ts_bar}%;background:{ts_clr};border-radius:3px;transition:width 0.4s;"></div>
    </div>
  </div>
</div>""", unsafe_allow_html=True)

    # ── C. Signal Strength Cards ──────────────────────────────────────────────
    rsi_clr  = "#f43f5e" if rsi_val > 70 else ("#00d4aa" if rsi_val < 30 else "#e2e8f0")
    rsi_lbl  = "Overbought" if rsi_val > 70 else ("Oversold" if rsi_val < 30 else "Neutral")
    rvol_clr = "#f59e0b" if rvol > 1.5 else "#64748b"
    rvol_lbl = "High" if rvol > 1.5 else "Normal"

    st.markdown(f"""
<div class="ms-sig-grid" style="grid-template-columns:1fr 1fr;">
  <div class="ms-sig-card">
    <div class="ms-sig-icon" style="color:{rsi_clr};">◎</div>
    <div class="ms-sig-label">RSI</div>
    <div class="ms-sig-sub">{rsi_val:.0f}</div>
    <div style="font-size:0.62rem;color:{rsi_clr};margin-top:2px;">{rsi_lbl}</div>
  </div>
  <div class="ms-sig-card">
    <div class="ms-sig-icon" style="color:{mom_clr};">{'▲' if mom > 0 else ('▼' if mom < 0 else '◆')}</div>
    <div class="ms-sig-label">MOM</div>
    <div class="ms-sig-sub">{mom_lbl}</div>
    <div style="font-size:0.62rem;color:{mom_clr};margin-top:2px;">{mom:+.4f}</div>
  </div>
  <div class="ms-sig-card">
    <div class="ms-sig-icon" style="color:{ts_clr};">⚡</div>
    <div class="ms-sig-label">TS</div>
    <div class="ms-sig-sub">{ts:.0f}</div>
    <div style="font-size:0.62rem;color:{ts_clr};margin-top:2px;">{'Strong' if ts > 30 else 'Weak'}</div>
  </div>
  <div class="ms-sig-card">
    <div class="ms-sig-icon" style="color:{rvol_clr};">📊</div>
    <div class="ms-sig-label">RVOL</div>
    <div class="ms-sig-sub">{rvol:.2f}x</div>
    <div style="font-size:0.62rem;color:{rvol_clr};margin-top:2px;">{rvol_lbl}</div>
  </div>
</div>""", unsafe_allow_html=True)


# ── Asset selector cards ───────────────────────────────────────────────────────

def _render_asset_cards() -> None:
    cols = st.columns(len(CFD_ASSETS), gap="small")
    for col, (key, asset) in zip(cols, CFD_ASSETS.items()):
        active = (st.session_state.cfd_asset == key)
        with col:
            # Fetch quick price
            df_quick = _load_data(asset["symbol"], "2d", "1d", None)
            if df_quick is not None and len(df_quick) >= 2:
                price = float(df_quick["Close"].iloc[-1])
                prev  = float(df_quick["Close"].iloc[-2])
                chg   = price - prev
                pct   = chg / prev * 100 if prev else 0.0
            else:
                price, chg, pct = 0.0, 0.0, 0.0

            color  = "#00d4aa" if chg >= 0 else "#f43f5e"
            arrow  = "▲" if chg >= 0 else "▼"
            border = "#00d4aa" if active else "#1e2d45"
            bg     = "rgba(0,212,170,0.07)" if active else "#0d1321"
            badge_bg = "#00d4aa" if active else "#1e2d45"
            badge_cl = "#080d17" if active else "#64748b"
            cat_color = "#4d9de0" if asset["cat"] == "Crypto" else "#f59e0b"

            st.markdown(f"""
<div class="cfd-asset-card" style="border-color:{border};background:{bg};">
  <div class="cfd-asset-card-top">
    <span class="cfd-asset-icon" style="background:{badge_bg};color:{badge_cl};">{asset['icon']}</span>
    <span class="cfd-asset-cat" style="color:{cat_color};">{asset['cat']}</span>
  </div>
  <div class="cfd-asset-name">{asset['name']}</div>
  <div class="cfd-asset-ticker">{key}</div>
  <div class="cfd-asset-price">
    {_fmt_price(price, key) if price else '—'}
  </div>
  <div class="cfd-asset-chg" style="color:{color};">
    {arrow} {abs(pct):.2f}%
  </div>
  <div class="cfd-asset-unit">{asset['unit']}</div>
</div>""", unsafe_allow_html=True)

            if st.button(
                "Select" if not active else "Active",
                key=f"cfd_select_{key}",
                use_container_width=True,
                disabled=active,
            ):
                st.session_state.cfd_asset = key
                _load_data.clear()
                st.rerun()


# ── Timeframe strip ────────────────────────────────────────────────────────────

def _render_tf_strip() -> None:
    cur = st.session_state.cfd_tf
    st.markdown('<div class="cfd-tf-strip">', unsafe_allow_html=True)
    cols = st.columns(len(_TF_KEYS), gap="small")
    for col, tf in zip(cols, _TF_KEYS):
        active = (tf == cur)
        with col:
            if st.button(
                tf,
                key=f"cfd_tf_{tf}",
                use_container_width=True,
                type="primary" if active else "secondary",
            ):
                if tf != cur:
                    st.session_state.cfd_tf = tf
                    _load_data.clear()
                    st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)


# ── Price strip ────────────────────────────────────────────────────────────────

def _render_price_strip(key: str, asset: Dict, df: pd.DataFrame) -> None:
    if df is None or df.empty:
        return
    last  = float(df["Close"].iloc[-1])
    prev  = float(df["Close"].iloc[-2]) if len(df) > 1 else last
    chg   = last - prev
    pct   = (chg / prev * 100) if prev else 0.0
    clr   = "#00d4aa" if chg >= 0 else "#f43f5e"
    arrow = "▲" if chg >= 0 else "▼"
    high  = float(df["High"].max())
    low   = float(df["Low"].min())
    vol   = float(df["Volume"].iloc[-1]) if "Volume" in df.columns else 0

    st.markdown(f"""
<div class="cs-stock-strip">
  <div class="cs-strip-name">{key}<span class="cs-strip-full"> · {asset['name']}</span></div>
  <div class="cs-strip-price">{_fmt_price(last, key)}</div>
  <div class="cs-strip-chg" style="color:{clr}">{arrow} {abs(chg):,.4f} ({abs(pct):.2f}%)</div>
  <div class="cs-strip-stat"><span>H</span>{_fmt_price(high, key)}</div>
  <div class="cs-strip-stat"><span>L</span>{_fmt_price(low, key)}</div>
  <div class="cs-strip-stat"><span>Vol</span>{_fmt_vol(vol)}</div>
  <div class="cs-strip-stat"><span>Bars</span>{len(df)}</div>
</div>""", unsafe_allow_html=True)


# ── Order Block panel ──────────────────────────────────────────────────────────

def _render_order_block_panel(ob: Dict) -> None:
    bull_obs = ob.get("active_bullish", [])
    bear_obs = ob.get("active_bearish", [])

    st.markdown("""
<div class="cfd-panel-header">
  <span class="cfd-panel-icon" style="background:#00d4aa22;color:#00d4aa;">OB</span>
  <span class="cfd-panel-title">Order Blocks</span>
  <span class="cfd-panel-desc">Institutional demand/supply zones — unmitigated candles before impulse moves</span>
</div>""", unsafe_allow_html=True)

    col_bull, col_bear = st.columns(2, gap="small")

    with col_bull:
        st.markdown('<div class="cfd-ob-section cfd-ob-bull">', unsafe_allow_html=True)
        st.markdown("""
<div class="cfd-ob-section-head">
  <span class="cfd-ob-dot" style="background:#00d4aa;"></span>
  Bullish Order Blocks
</div>""", unsafe_allow_html=True)

        if not bull_obs:
            st.markdown('<div class="cfd-empty-state">No active bullish OBs detected</div>', unsafe_allow_html=True)
        else:
            rows_html = ""
            for i, o in enumerate(reversed(bull_obs[-5:]), 1):
                strength_bar = int(o.get("strength", 50))
                rows_html += f"""
<div class="cfd-ob-row">
  <div class="cfd-ob-row-num">{i}</div>
  <div class="cfd-ob-row-body">
    <div class="cfd-ob-levels">
      <span class="cfd-ob-high" style="color:#00d4aa;">{o['high']:,.4f}</span>
      <span class="cfd-ob-sep">—</span>
      <span class="cfd-ob-low">{o['low']:,.4f}</span>
    </div>
    <div class="cfd-ob-meta">
      <span class="cfd-ob-status cfd-ob-active">ACTIVE</span>
      <span class="cfd-ob-str">Body {strength_bar}%</span>
    </div>
    <div class="cfd-ob-strength-bar">
      <div class="cfd-ob-strength-fill" style="width:{strength_bar}%;background:#00d4aa;"></div>
    </div>
  </div>
</div>"""
            st.markdown(rows_html, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with col_bear:
        st.markdown('<div class="cfd-ob-section cfd-ob-bear">', unsafe_allow_html=True)
        st.markdown("""
<div class="cfd-ob-section-head">
  <span class="cfd-ob-dot" style="background:#f43f5e;"></span>
  Bearish Order Blocks
</div>""", unsafe_allow_html=True)

        if not bear_obs:
            st.markdown('<div class="cfd-empty-state">No active bearish OBs detected</div>', unsafe_allow_html=True)
        else:
            rows_html = ""
            for i, o in enumerate(reversed(bear_obs[-5:]), 1):
                strength_bar = int(o.get("strength", 50))
                rows_html += f"""
<div class="cfd-ob-row">
  <div class="cfd-ob-row-num">{i}</div>
  <div class="cfd-ob-row-body">
    <div class="cfd-ob-levels">
      <span class="cfd-ob-high" style="color:#f43f5e;">{o['high']:,.4f}</span>
      <span class="cfd-ob-sep">—</span>
      <span class="cfd-ob-low">{o['low']:,.4f}</span>
    </div>
    <div class="cfd-ob-meta">
      <span class="cfd-ob-status cfd-ob-active" style="background:#f43f5e22;color:#f43f5e;border-color:#f43f5e44;">ACTIVE</span>
      <span class="cfd-ob-str">Body {strength_bar}%</span>
    </div>
    <div class="cfd-ob-strength-bar">
      <div class="cfd-ob-strength-fill" style="width:{strength_bar}%;background:#f43f5e;"></div>
    </div>
  </div>
</div>"""
            st.markdown(rows_html, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)


# ── FVG / IFVG panel ───────────────────────────────────────────────────────────

def _render_fvg_panel(fvg: Dict) -> None:
    bull_fvg  = fvg.get("bullish", [])
    bear_fvg  = fvg.get("bearish", [])
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
  <div class="cfd-fvg-card-head" style="color:{color};">{label}</div>""", unsafe_allow_html=True)
            if not items:
                st.markdown(f'<div class="cfd-fvg-empty">No {tag} detected</div>', unsafe_allow_html=True)
            else:
                for f in reversed(items[-3:]):
                    gap_pct = f.get("gap_pct", 0)
                    st.markdown(f"""
<div class="cfd-fvg-row">
  <div class="cfd-fvg-levels">
    <span style="color:{color};">{f['high']:,.4f}</span>
    <span class="cfd-fvg-arrow">↓</span>
    <span>{f['low']:,.4f}</span>
  </div>
  <div class="cfd-fvg-gap">{gap_pct:.3f}% gap</div>
</div>""", unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

    _fvg_card(c1, bull_fvg,  "Bullish FVG",  "#4d9de0", "bullish FVGs")
    _fvg_card(c2, bear_fvg,  "Bearish FVG",  "#f59e0b", "bearish FVGs")
    _fvg_card(c3, bull_ifvg, "Bullish IFVG", "#a855f7", "bullish IFVGs")
    _fvg_card(c4, bear_ifvg, "Bearish IFVG", "#ec4899", "bearish IFVGs")


# ── Market Structure panel ─────────────────────────────────────────────────────

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

    # Summary metrics row
    st.markdown(f"""
<div class="cfd-ms-metrics">
  <div class="cfd-ms-metric">
    <div class="cfd-ms-metric-label">HTF TREND</div>
    <div class="cfd-ms-metric-val" style="color:{trend_color};">{trend_icon} {trend.upper()}</div>
  </div>
  <div class="cfd-ms-metric">
    <div class="cfd-ms-metric-label">PRICE ZONE</div>
    <div class="cfd-ms-metric-val" style="color:{zone_color};">{zone}</div>
  </div>
  <div class="cfd-ms-metric">
    <div class="cfd-ms-metric-label">EQ OFFSET</div>
    <div class="cfd-ms-metric-val" style="color:{zone_color};">{eq_pct:+.1f}%</div>
  </div>
  <div class="cfd-ms-metric">
    <div class="cfd-ms-metric-label">RANGE HIGH</div>
    <div class="cfd-ms-metric-val">{rh:,.4f}</div>
  </div>
  <div class="cfd-ms-metric">
    <div class="cfd-ms-metric-label">EQUILIBRIUM</div>
    <div class="cfd-ms-metric-val" style="color:#f59e0b;">{eq:,.4f}</div>
  </div>
  <div class="cfd-ms-metric">
    <div class="cfd-ms-metric-label">RANGE LOW</div>
    <div class="cfd-ms-metric-val">{rl:,.4f}</div>
  </div>
</div>""", unsafe_allow_html=True)

    bos_col, choch_col, liq_col = st.columns([1, 1, 1], gap="small")

    with bos_col:
        st.markdown('<div class="cfd-ms-section">', unsafe_allow_html=True)
        st.markdown('<div class="cfd-ms-section-title">Break of Structure (BOS)</div>', unsafe_allow_html=True)
        if not bos_list:
            st.markdown('<div class="cfd-empty-state">No recent BOS events</div>', unsafe_allow_html=True)
        else:
            for b in reversed(bos_list[-4:]):
                clr = "#00d4aa" if b["direction"] == "bullish" else "#f43f5e"
                st.markdown(f"""
<div class="cfd-ms-event">
  <span class="cfd-ms-event-badge" style="background:{clr}22;color:{clr};border-color:{clr}44;">BOS</span>
  <span class="cfd-ms-event-dir" style="color:{clr};">{b['direction'].upper()}</span>
  <span class="cfd-ms-event-level">{b['level']:,.4f}</span>
</div>""", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with choch_col:
        st.markdown('<div class="cfd-ms-section">', unsafe_allow_html=True)
        st.markdown('<div class="cfd-ms-section-title">Change of Character (CHoCH)</div>', unsafe_allow_html=True)
        if not choch:
            st.markdown('<div class="cfd-empty-state">No CHoCH detected</div>', unsafe_allow_html=True)
        else:
            for c in reversed(choch[-3:]):
                clr = "#00d4aa" if c["direction"] == "bullish" else "#f43f5e"
                st.markdown(f"""
<div class="cfd-ms-event">
  <span class="cfd-ms-event-badge" style="background:{clr}22;color:{clr};border-color:{clr}44;font-size:0.6rem;">CHoCH</span>
  <span class="cfd-ms-event-dir" style="color:{clr};">{c['direction'].upper()}</span>
  <span class="cfd-ms-event-level">{c['level']:,.4f}</span>
</div>""", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with liq_col:
        st.markdown('<div class="cfd-ms-section">', unsafe_allow_html=True)
        st.markdown('<div class="cfd-ms-section-title">Liquidity Pools</div>', unsafe_allow_html=True)
        if not liq:
            st.markdown('<div class="cfd-empty-state">No equal highs/lows found</div>', unsafe_allow_html=True)
        else:
            for lv in liq[-4:]:
                clr  = "#f43f5e" if lv["type"] == "EQH" else "#00d4aa"
                lbl  = "Equal Highs" if lv["type"] == "EQH" else "Equal Lows"
                st.markdown(f"""
<div class="cfd-ms-event">
  <span class="cfd-ms-event-badge" style="background:{clr}22;color:{clr};border-color:{clr}44;">{lv['type']}</span>
  <span class="cfd-ms-event-dir" style="color:{clr};">{lbl}</span>
  <span class="cfd-ms-event-level">{lv['price']:,.4f}</span>
</div>""", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)


# ── Institutional Analysis panel ────────────────────────────────────────────────

def _render_institutional_panel(ai: Dict, df: pd.DataFrame) -> None:
    if not ai:
        st.info("Insufficient data for institutional analysis.")
        return

    bias      = ai.get("bias", "Neutral")
    bull_prob = ai.get("bull_prob", 50)
    bear_prob = ai.get("bear_prob", 50)
    rsi_val   = ai.get("rsi", 50)
    mom       = ai.get("momentum", 0)
    mom_lbl   = ai.get("momentum_lbl", "Flat")
    vol_pct   = ai.get("volatility", 0)
    ts        = ai.get("trend_str", 25)
    rvol      = ai.get("rvol", 1)
    session   = ai.get("session", "—")
    liq_dir   = ai.get("liq_dir", "—")
    position  = ai.get("position", "Neutral")
    eq        = ai.get("equilibrium", 0)

    # Bias color
    if "Strong Bull" in bias:  bias_clr = "#00d4aa"; bias_icon = "▲▲"
    elif "Bullish" in bias:    bias_clr = "#00d4aa"; bias_icon = "▲"
    elif "Strong Bear" in bias:bias_clr = "#f43f5e"; bias_icon = "▼▼"
    elif "Bearish" in bias:    bias_clr = "#f43f5e"; bias_icon = "▼"
    else:                      bias_clr = "#f59e0b"; bias_icon = "◆"

    bull_bar = bull_prob
    bear_bar = bear_prob

    st.markdown(f"""
<div class="cfd-panel-header">
  <span class="cfd-panel-icon" style="background:#ec489922;color:#ec4899;">AI</span>
  <span class="cfd-panel-title">Institutional Analysis</span>
  <span class="cfd-panel-desc">Rule-based smart money bias · Entry/SL/TP zones · Session context</span>
</div>""", unsafe_allow_html=True)

    # Bias header + probability bar
    st.markdown(f"""
<div class="cfd-ai-bias-block">
  <div class="cfd-ai-bias-main">
    <span class="cfd-ai-bias-icon" style="color:{bias_clr};">{bias_icon}</span>
    <span class="cfd-ai-bias-label" style="color:{bias_clr};">{bias}</span>
  </div>
  <div class="cfd-ai-prob-row">
    <span class="cfd-ai-prob-bull">{bull_prob}% Bull</span>
    <div class="cfd-ai-prob-bar">
      <div class="cfd-ai-prob-fill-bull" style="width:{bull_bar}%;"></div>
      <div class="cfd-ai-prob-fill-bear" style="width:{bear_bar}%;"></div>
    </div>
    <span class="cfd-ai-prob-bear">{bear_prob}% Bear</span>
  </div>
</div>""", unsafe_allow_html=True)

    # Metrics grid
    rsi_clr  = "#f43f5e" if rsi_val > 70 else ("#00d4aa" if rsi_val < 30 else "#e2e8f0")
    mom_clr  = "#00d4aa" if mom > 0 else ("#f43f5e" if mom < 0 else "#64748b")
    vol_clr  = "#f59e0b" if vol_pct > 2 else "#64748b"
    ts_clr   = "#00d4aa" if ts > 30 else "#64748b"
    pos_clr  = "#f43f5e" if position == "Premium" else "#00d4aa"
    rvol_clr = "#f59e0b" if rvol > 1.5 else "#64748b"

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

    # Entry / SL / TP zones
    c_bull, c_bear = st.columns(2, gap="small")

    def _fmt(v):
        return f"{v:,.4f}" if v < 10000 else f"{v:,.2f}"

    with c_bull:
        rr   = ai.get("rr_bull", 0)
        eb   = ai.get("entry_bull", 0)
        slb  = ai.get("sl_bull", 0)
        tp1b = ai.get("tp1_bull", 0)
        tp2b = ai.get("tp2_bull", 0)
        st.markdown(f"""
<div class="cfd-trade-zone cfd-trade-bull">
  <div class="cfd-trade-header">
    <span class="cfd-trade-dir-badge cfd-trade-dir-bull">LONG</span>
    <span class="cfd-trade-rr">R:R {rr:.1f}</span>
  </div>
  <div class="cfd-trade-rows">
    <div class="cfd-trade-row">
      <span class="cfd-trade-lbl">Entry Zone</span>
      <span class="cfd-trade-val" style="color:#e2e8f0;">{_fmt(eb)}</span>
    </div>
    <div class="cfd-trade-row">
      <span class="cfd-trade-lbl">Stop Loss</span>
      <span class="cfd-trade-val" style="color:#f43f5e;">{_fmt(slb)}</span>
    </div>
    <div class="cfd-trade-row">
      <span class="cfd-trade-lbl">TP 1</span>
      <span class="cfd-trade-val" style="color:#00d4aa;">{_fmt(tp1b)}</span>
    </div>
    <div class="cfd-trade-row">
      <span class="cfd-trade-lbl">TP 2</span>
      <span class="cfd-trade-val" style="color:#00d4aa;">{_fmt(tp2b)}</span>
    </div>
  </div>
</div>""", unsafe_allow_html=True)

    with c_bear:
        rr   = ai.get("rr_bear", 0)
        ebe  = ai.get("entry_bear", 0)
        sle  = ai.get("sl_bear", 0)
        tp1e = ai.get("tp1_bear", 0)
        tp2e = ai.get("tp2_bear", 0)
        st.markdown(f"""
<div class="cfd-trade-zone cfd-trade-bear">
  <div class="cfd-trade-header">
    <span class="cfd-trade-dir-badge cfd-trade-dir-bear">SHORT</span>
    <span class="cfd-trade-rr">R:R {rr:.1f}</span>
  </div>
  <div class="cfd-trade-rows">
    <div class="cfd-trade-row">
      <span class="cfd-trade-lbl">Entry Zone</span>
      <span class="cfd-trade-val" style="color:#e2e8f0;">{_fmt(ebe)}</span>
    </div>
    <div class="cfd-trade-row">
      <span class="cfd-trade-lbl">Stop Loss</span>
      <span class="cfd-trade-val" style="color:#f43f5e;">{_fmt(sle)}</span>
    </div>
    <div class="cfd-trade-row">
      <span class="cfd-trade-lbl">TP 1</span>
      <span class="cfd-trade-val" style="color:#00d4aa;">{_fmt(tp1e)}</span>
    </div>
    <div class="cfd-trade-row">
      <span class="cfd-trade-lbl">TP 2</span>
      <span class="cfd-trade-val" style="color:#00d4aa;">{_fmt(tp2e)}</span>
    </div>
  </div>
</div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# IDEAL ENTRY — React to Liquidity Behavior
# ════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=120, show_spinner=False)
def _load_htf_data(symbol: str) -> Optional[pd.DataFrame]:
    """1H data for EMA200 HTF bias (180 days = 1 000+ bars for most assets)."""
    try:
        df = get_history(symbol, period="180d", interval="60m")
        if df is not None and not df.empty:
            df.index = pd.to_datetime(df.index)
        return df
    except Exception:
        return None


def _render_ideal_entry_section(
    asset_key: str,
    asset:     Dict,
    df:        pd.DataFrame,
    ob_data:   Dict,
    fvg_data:  Dict,
    ms_data:   Dict,
) -> None:
    """Full 'Ideal Entry — React to Liquidity Behavior' section."""

    # Section header
    st.markdown("""
<div class="ie-header">
  <div class="ie-header-left">
    <span class="ie-header-icon">⚡</span>
    <div>
      <div class="ie-header-title">Ideal Entry <span class="ie-header-accent">— React to Liquidity Behavior</span></div>
      <div class="ie-header-sub">Institutional SMC detection · Multi-timeframe confluence · No market prediction</div>
    </div>
  </div>
</div>""", unsafe_allow_html=True)

    # Fetch HTF data
    df_htf = _load_htf_data(asset["symbol"])

    # Run engine
    sig = generate_entry_signal(df_htf, df, ob_data, fvg_data, ms_data)
    if not sig:
        st.info("Insufficient bars for entry analysis. Try a higher timeframe.")
        return

    # MTF alignment strip
    _render_mtf_strip(sig)

    st.markdown('<div class="ie-spacer"></div>', unsafe_allow_html=True)

    # Long / Short cards
    c_long, c_short = st.columns(2, gap="small")
    with c_long:
        _render_entry_card("long",  sig["long"],  asset_key, sig)
    with c_short:
        _render_entry_card("short", sig["short"], asset_key, sig)

    st.markdown('<div class="ie-spacer"></div>', unsafe_allow_html=True)

    # Signal breakdown + liquidity side by side
    c_tbl, c_liq = st.columns([1.1, 0.9], gap="small")
    with c_tbl:
        _render_signal_table(sig["signal_rows"])
    with c_liq:
        _render_liquidity_panel(sig)

    st.markdown('<div class="ie-spacer"></div>', unsafe_allow_html=True)

    # Volume profile summary
    _render_vp_summary(sig["hvn_lvn"], sig.get("vp"), sig["atr"], asset_key, df)


# ── MTF alignment strip ──────────────────────────────────────────────────────

def _render_mtf_strip(sig: Dict) -> None:
    bias     = sig.get("bias", {})
    htf      = bias.get("htf",  {})
    main     = bias.get("main", {})
    aligned  = bias.get("aligned", False)
    ema200   = sig.get("ema200", 0)
    atr_v    = sig.get("atr", 0)
    rsi_v    = sig.get("rsi", 50)
    zone     = sig.get("zone", "—")
    sweeps   = sig.get("sweeps", {})

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
    <span class="ie-mtf-val">{_fmt_price_raw(ema200)}</span>
  </div>
  <div class="ie-mtf-chip">
    <span class="ie-mtf-label">ATR</span>
    <span class="ie-mtf-val">{_fmt_price_raw(atr_v)}</span>
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

def _render_entry_card(direction: str, data: Dict, asset_key: str, sig: Dict) -> None:
    is_long   = direction == "long"
    dir_color = "#00d4aa" if is_long else "#f43f5e"
    dir_label = "LONG" if is_long else "SHORT"
    dir_arrow = "▲" if is_long else "▼"

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

    sl_pct    = round((entry_p - sl_p)  / (entry_p + 1e-9) * 100, 2) if is_long  else \
                round((sl_p  - entry_p) / (entry_p + 1e-9) * 100, 2)
    tp1_pct   = round((tp1_p - entry_p) / (entry_p + 1e-9) * 100, 2) if is_long  else \
                round((entry_p - tp1_p) / (entry_p + 1e-9) * 100, 2)
    tp2_pct   = round((tp2_p - entry_p) / (entry_p + 1e-9) * 100, 2) if is_long  else \
                round((entry_p - tp2_p) / (entry_p + 1e-9) * 100, 2)

    def _fp(v): return _fmt_price(v, asset_key)

    rej_badge = (f'<span class="ie-rej-badge" style="border-color:{dir_color}44;color:{dir_color};">'
                 f'{rej}</span>') if rej else ""

    # Signal mini-chips (top 5 active)
    sigs = data.get("signals", {})
    from data.entry_engine import _SIGNAL_LABELS  # noqa
    chips_html = ""
    for k, (label, _) in list(_SIGNAL_LABELS.items())[:6]:
        if sigs.get(k):
            chips_html += f'<span class="ie-sig-chip" style="background:{dir_color}14;color:{dir_color};border-color:{dir_color}33;">{label}</span>'

    st.markdown(f"""
<div class="ie-entry-card" style="border-top:2.5px solid {dir_color};">
  <!-- Header row -->
  <div class="ie-card-header">
    <span class="ie-dir-badge" style="background:{dir_color}22;color:{dir_color};border-color:{dir_color}44;">
      {dir_arrow} {dir_label}
    </span>
    <span class="ie-qual-badge" style="background:{qual_bg};color:{qual_cl};">{quality}</span>
    <span class="ie-inst-badge">{inst_bias}</span>
    {rej_badge}
  </div>

  <!-- Confidence meter -->
  <div class="ie-conf-label">
    <span style="color:{dir_color};font-weight:800;font-size:1.1rem;">{conf}%</span>
    <span class="ie-conf-sublabel"> confidence · {score}/{max_sc} pts</span>
  </div>
  <div class="ie-conf-bar-wrap">
    <div class="ie-conf-bar-fill" style="width:{bar_fill}%;background:{bar_color};"></div>
  </div>

  <!-- Trade levels -->
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

  <!-- Active signal chips -->
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
    sh         = sig.get("stop_hunt", {})

    sell_sweeps = sweeps.get("sell_side", [])
    buy_sweeps  = sweeps.get("buy_side",  [])

    st.markdown('<div class="ie-liq-wrap">', unsafe_allow_html=True)
    st.markdown('<div class="ie-table-header">Liquidity Behavior</div>', unsafe_allow_html=True)

    # Long narrative
    st.markdown('<div class="ie-liq-dir-label" style="color:#00d4aa;">LONG — Sell-Side Sweep Analysis</div>',
                unsafe_allow_html=True)
    for line in long_narr:
        st.markdown(f'<div class="ie-liq-line">• {line}</div>', unsafe_allow_html=True)

    if sell_sweeps:
        st.markdown('<div class="ie-liq-events-head">Recent sell-side sweeps</div>', unsafe_allow_html=True)
        for s in sell_sweeps[:3]:
            ba  = s.get("bars_ago", 0)
            rec = f'{ba} bars ago'
            st.markdown(f"""
<div class="ie-liq-event ie-liq-bull">
  <span class="ie-liq-event-level">{s['level']:,.4f}</span>
  <span class="ie-liq-arrow">→</span>
  <span class="ie-liq-event-sweep" style="color:#f43f5e;">swept {s['sweep_low']:,.4f}</span>
  <span class="ie-liq-event-rec" style="color:#00d4aa;">recovered {s['recovery']:,.4f}</span>
  <span class="ie-liq-event-ago">{rec}</span>
</div>""", unsafe_allow_html=True)

    st.markdown('<div class="ie-liq-sep"></div>', unsafe_allow_html=True)

    # Short narrative
    st.markdown('<div class="ie-liq-dir-label" style="color:#f43f5e;">SHORT — Buy-Side Sweep Analysis</div>',
                unsafe_allow_html=True)
    for line in short_narr:
        st.markdown(f'<div class="ie-liq-line">• {line}</div>', unsafe_allow_html=True)

    if buy_sweeps:
        st.markdown('<div class="ie-liq-events-head">Recent buy-side sweeps</div>', unsafe_allow_html=True)
        for s in buy_sweeps[:3]:
            ba  = s.get("bars_ago", 0)
            rec = f'{ba} bars ago'
            st.markdown(f"""
<div class="ie-liq-event ie-liq-bear">
  <span class="ie-liq-event-level">{s['level']:,.4f}</span>
  <span class="ie-liq-arrow">→</span>
  <span class="ie-liq-event-sweep" style="color:#00d4aa;">swept {s['sweep_high']:,.4f}</span>
  <span class="ie-liq-event-rec" style="color:#f43f5e;">recovered {s['recovery']:,.4f}</span>
  <span class="ie-liq-event-ago">{rec}</span>
</div>""", unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ── Volume profile summary ────────────────────────────────────────────────────

def _render_vp_summary(hvn_lvn_d: Dict, vp: Optional[Dict],
                       atr_v: float, asset_key: str,
                       df: pd.DataFrame) -> None:
    poc     = hvn_lvn_d.get("poc")
    hvn     = hvn_lvn_d.get("hvn", [])
    lvn     = hvn_lvn_d.get("lvn", [])
    cur     = float(df["Close"].iloc[-1]) if df is not None and not df.empty else 0

    st.markdown("""
<div class="ie-vp-section">
  <div class="ie-table-header">Volume Profile · HVN / LVN Analysis</div>""",
                unsafe_allow_html=True)

    if vp is None:
        st.markdown(
            '<div class="ie-vp-no-vol">Volume data unavailable for this asset '
            '(indices / some futures). ATR-based zones used instead.</div>',
            unsafe_allow_html=True,
        )
        # ATR bands as fallback
        levels = [
            ("ATR +1.5",  cur + atr_v * 1.5, "resistance"),
            ("ATR +1.0",  cur + atr_v * 1.0, "resistance"),
            ("Current",   cur,                "current"),
            ("ATR -1.0",  cur - atr_v * 1.0, "support"),
            ("ATR -1.5",  cur - atr_v * 1.5, "support"),
        ]
        for lbl, price, role in levels:
            clr = "#f43f5e" if role == "resistance" else ("#00d4aa" if role == "support" else "#f59e0b")
            st.markdown(f"""
<div class="ie-vp-row-simple">
  <span class="ie-vp-lbl" style="color:{clr};">{lbl}</span>
  <span class="ie-vp-price">{_fmt_price(price, asset_key)}</span>
  <span class="ie-vp-role" style="color:{clr};">{role}</span>
</div>""", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        return

    # Full VP summary
    c_poc, c_hvn, c_lvn = st.columns(3, gap="small")

    with c_poc:
        st.markdown(f"""
<div class="ie-vp-card">
  <div class="ie-vp-card-title" style="color:#f59e0b;">POC</div>
  <div class="ie-vp-card-val">{_fmt_price(poc, asset_key) if poc else '—'}</div>
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
  <span style="color:{clr};">{_fmt_price(h, asset_key)}</span>
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
                clr  = "#a855f7"
                st.markdown(f"""
<div class="ie-vp-node-row">
  <span style="color:{clr};">{_fmt_price(lv, asset_key)}</span>
  <span class="ie-vp-node-role" style="color:{clr};">{role}</span>
</div>""", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # Mini VP bar chart (HTML)
    _render_vp_bars(vp, cur, hvn, lvn, asset_key)

    st.markdown('</div>', unsafe_allow_html=True)


def _render_vp_bars(vp: Dict, cur: float, hvn: List, lvn: List,
                    asset_key: str) -> None:
    """Render a 25-level horizontal volume bar chart near current price."""
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
        p   = float(prices[i])
        v   = float(vols[i])
        pct = round(v / max_v * 100, 1)
        is_cur = abs(p - cur) / (cur + 1e-9) < 0.008
        is_hvn = any(abs(p - h) / (h + 1e-9) < 0.012 for h in hvn)
        is_lvn = any(abs(p - lv) / (lv + 1e-9) < 0.012 for lv in lvn)
        bar_c  = "#00d4aa" if is_hvn else ("#a855f7" if is_lvn else ("#f59e0b" if is_cur else "#1e2d45"))
        lbl_c  = bar_c if (is_hvn or is_lvn or is_cur) else "#64748b"
        tag    = " HVN" if is_hvn else (" LVN" if is_lvn else (" ←" if is_cur else ""))
        bars  += f"""
<div class="ie-vp-bar-row">
  <div class="ie-vp-bar-price" style="color:{lbl_c};">{_fmt_price(p, asset_key)}</div>
  <div class="ie-vp-bar-track">
    <div class="ie-vp-bar-fill" style="width:{pct}%;background:{bar_c};"></div>
  </div>
  <div class="ie-vp-bar-tag" style="color:{lbl_c};">{tag}</div>
</div>"""
    bars += '</div>'
    st.markdown(bars, unsafe_allow_html=True)


# ── Price format helper (no asset suffix needed) ──────────────────────────────

def _fmt_price_raw(v: float) -> str:
    if v == 0:
        return "—"
    if v >= 10000:
        return f"{v:,.2f}"
    if v >= 100:
        return f"{v:,.2f}"
    return f"{v:,.4f}"
