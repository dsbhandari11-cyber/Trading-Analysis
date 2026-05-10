"""
Nifty 100 Screener page.
Fetches technical data for all Nifty 100 stocks and allows filtering/sorting.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
import streamlit as st
import pandas as pd
import numpy as np
from data.fetcher import batch_download, get_pe_ratio
from data.technical import calculate_rsi, calculate_volume_ratio, price_change_pct, momentum_score
from data.stocks_list import NIFTY100_SYMBOLS, get_display_name
from config import REFRESH_INTERVAL, COLORS, PE_MAX_VALUE, RSI_BULLISH, VOLUME_SPIKE_MULTIPLIER
from utils.helpers import fmt_price, ist_now, color_for_change
from utils.logger import get_logger

log = get_logger(__name__)

_BATCH_PROCESS_DELAY = 0.05


def render_nifty100():
    st.markdown(
        f'<meta http-equiv="refresh" content="{REFRESH_INTERVAL}">',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="section-header"><span class="section-title">Nifty 100 Screener</span>'
        '<span class="section-badge">LIVE</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="refresh-info"><span class="live-dot"></span> Updated {ist_now()} · '
        f'Auto-refreshes every {REFRESH_INTERVAL}s</div>',
        unsafe_allow_html=True,
    )

    filters = _render_filters()
    _render_table(filters)


def _render_filters() -> dict:
    st.markdown('<div class="filter-bar">', unsafe_allow_html=True)
    c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 1])

    with c1:
        search = st.text_input("🔍 Search stock", placeholder="e.g. RELIANCE, TCS...", label_visibility="collapsed")
    with c2:
        pe_filter = st.checkbox(f"P/E < {PE_MAX_VALUE}", value=False, key="n100_pe")
    with c3:
        rsi_filter = st.checkbox(f"RSI > {RSI_BULLISH}", value=False, key="n100_rsi")
    with c4:
        vol_filter = st.checkbox(f"Vol Spike >{VOLUME_SPIKE_MULTIPLIER:.0f}x", value=False, key="n100_vol")
    with c5:
        sort_by = st.selectbox(
            "Sort by",
            ["Momentum Score", "RSI", "Volume Ratio", "Change %", "Price"],
            index=0,
            label_visibility="collapsed",
        )
    st.markdown("</div>", unsafe_allow_html=True)

    return {
        "search": search.strip().upper(),
        "pe_filter": pe_filter,
        "rsi_filter": rsi_filter,
        "vol_filter": vol_filter,
        "sort_by": sort_by,
    }


@st.cache_data(ttl=120, show_spinner=False)
def _load_screener_data() -> pd.DataFrame:
    symbols = NIFTY100_SYMBOLS
    rows = []

    hist_data = batch_download(symbols, period="3mo")

    for sym in symbols:
        try:
            df = hist_data.get(sym)
            if df is None or df.empty or "Close" not in df.columns:
                continue

            rsi_series = calculate_rsi(df)
            rsi = float(rsi_series.iloc[-1]) if len(rsi_series) > 0 and not pd.isna(rsi_series.iloc[-1]) else None

            vol_ratio_s = calculate_volume_ratio(df)
            vol_ratio = float(vol_ratio_s.iloc[-1]) if len(vol_ratio_s) > 0 and not pd.isna(vol_ratio_s.iloc[-1]) else None

            price_chg_1d = price_change_pct(df, days=1)
            price_chg_5d = price_change_pct(df, days=5)
            current_price = float(df["Close"].iloc[-1]) if len(df) > 0 else None

            score = momentum_score(
                rsi if rsi is not None else 50.0,
                vol_ratio if vol_ratio is not None else 1.0,
                price_chg_5d,
            )

            rows.append({
                "symbol": sym,
                "name": get_display_name(sym),
                "price": current_price,
                "rsi": rsi,
                "vol_ratio": vol_ratio,
                "price_chg_1d": price_chg_1d,
                "price_chg_5d": price_chg_5d,
                "momentum_score": score,
                "pe": None,
            })
        except Exception as e:
            log.warning("Screener error for %s: %s", sym, e)
        time.sleep(_BATCH_PROCESS_DELAY)

    return pd.DataFrame(rows)


def _render_table(filters: dict):
    with st.spinner("Loading Nifty 100 data… This may take 30–60 seconds on first load."):
        df = _load_screener_data()

    if df.empty:
        st.error("No data loaded. Check your internet connection and try again.")
        return

    if filters["search"]:
        mask = (
            df["symbol"].str.contains(filters["search"], case=False, na=False)
            | df["name"].str.contains(filters["search"], case=False, na=False)
        )
        df = df[mask]

    if filters["pe_filter"]:
        df = df[df["pe"].isna() | (df["pe"] < PE_MAX_VALUE)]

    if filters["rsi_filter"]:
        df = df[df["rsi"].notna() & (df["rsi"] >= RSI_BULLISH)]

    if filters["vol_filter"]:
        df = df[df["vol_ratio"].notna() & (df["vol_ratio"] >= VOLUME_SPIKE_MULTIPLIER)]

    sort_map = {
        "Momentum Score": "momentum_score",
        "RSI": "rsi",
        "Volume Ratio": "vol_ratio",
        "Change %": "price_chg_1d",
        "Price": "price",
    }
    sort_col = sort_map.get(filters["sort_by"], "momentum_score")
    df = df.sort_values(sort_col, ascending=False, na_position="last")

    st.markdown(
        f'<div style="color:{COLORS["text_muted"]};font-size:0.8rem;margin-bottom:6px;">'
        f'Showing {len(df)} of {len(NIFTY100_SYMBOLS)} stocks</div>',
        unsafe_allow_html=True,
    )

    display_df = _build_display_df(df)
    styled = _style_df(display_df, df)
    st.dataframe(styled, width="stretch", hide_index=True, height=520)


def _build_display_df(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in df.iterrows():
        rsi = row["rsi"]
        vol = row["vol_ratio"]
        chg1 = row["price_chg_1d"]
        chg5 = row["price_chg_5d"]
        score = row["momentum_score"]
        price = row["price"]

        rsi_str = f"{rsi:.1f}" if rsi is not None and rsi == rsi else "N/A"
        vol_str = f"{vol:.2f}x" if vol is not None and vol == vol else "N/A"
        chg1_str = f"{'+' if chg1 >= 0 else ''}{chg1:.2f}%" if chg1 is not None else "N/A"
        chg5_str = f"{'+' if chg5 >= 0 else ''}{chg5:.2f}%" if chg5 is not None else "N/A"
        score_str = f"{score:.1f}" if score is not None else "N/A"
        price_str = f"₹{price:,.2f}" if price is not None else "N/A"
        pe_str = f"{row['pe']:.1f}" if row["pe"] is not None and row["pe"] == row["pe"] else "—"

        rows.append({
            "Ticker": row["symbol"].replace(".NS", ""),
            "Company": row["name"][:24],
            "Price": price_str,
            "1D %": chg1_str,
            "5D %": chg5_str,
            "RSI": rsi_str,
            "Vol Ratio": vol_str,
            "P/E": pe_str,
            "Score": score_str,
        })
    return pd.DataFrame(rows)


def _style_df(display_df: pd.DataFrame, source_df: pd.DataFrame):
    def color_change(val):
        if val == "N/A" or val == "—":
            return f"color: {COLORS['neutral']}"
        try:
            v = float(val.replace("%", "").replace("+", ""))
            return f"color: {COLORS['positive']}" if v >= 0 else f"color: {COLORS['negative']}"
        except Exception:
            return ""

    def color_rsi(val):
        if val == "N/A":
            return f"color: {COLORS['neutral']}"
        try:
            v = float(val)
            if v >= 70:
                return f"color: {COLORS['negative']}"
            if v <= 30:
                return f"color: {COLORS['warning']}"
            if v >= 50:
                return f"color: {COLORS['positive']}"
        except Exception:
            pass
        return f"color: {COLORS['neutral']}"

    def color_score(val):
        if val == "N/A":
            return f"color: {COLORS['neutral']}"
        try:
            v = float(val)
            if v >= 60:
                return f"color: {COLORS['positive']};font-weight:700"
            if v >= 30:
                return f"color: {COLORS['warning']}"
            return f"color: {COLORS['negative']}"
        except Exception:
            return ""

    return (
        display_df.style
        .map(color_change, subset=["1D %", "5D %"])
        .map(color_rsi, subset=["RSI"])
        .map(color_score, subset=["Score"])
        .set_properties(**{"font-size": "0.83rem"})
    )
