"""
Home page: live market overview, major indices, gainers/losers, heatmap.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
from data.fetcher import get_index_data, get_gainers_losers, get_ticker_prices
from data.news import fetch_all_headlines
from data.stocks_list import NIFTY50_SYMBOLS, get_display_name
from components.charts import index_line_chart, heatmap_chart, mini_sparkline
from config import MAJOR_INDICES, REFRESH_INTERVAL, TICKER_SYMBOLS, COLORS
from utils.helpers import fmt_price, fmt_change, ist_now, color_for_change


def _go_to_stock(symbol: str):
    st.session_state.selected_stock = symbol
    st.session_state.page = "StockDetail"
    st.rerun()


def render_home():
    st.markdown(
        f'<div class="refresh-info"><span class="live-dot"></span> Live · Updated {ist_now()}</div>',
        unsafe_allow_html=True,
    )

    _render_major_indices()
    _render_heatmap()
    _render_gainers_losers()
    _render_news_feed()


def _render_major_indices():
    st.markdown(
        '<div class="section-header"><span class="section-title">Major Indices</span>'
        '<span class="section-badge">LIVE</span></div>',
        unsafe_allow_html=True,
    )
    cols = st.columns(len(MAJOR_INDICES))
    for i, (name, symbol) in enumerate(MAJOR_INDICES.items()):
        data = get_index_data(symbol)
        current = data["current"]
        pct = data["pct_change"]
        change = data["change"]
        hist = data.get("history")
        clr = color_for_change(pct)
        arrow = "▲" if pct >= 0 else "▼"

        with cols[i]:
            card_html = f"""
            <div class="metric-card">
                <div class="metric-label">{name}</div>
                <div class="metric-value">{current:,.2f}</div>
                <div style="color:{clr};font-size:0.82rem;margin-top:3px;">
                    {arrow} {abs(change):,.2f} ({abs(pct):.2f}%)
                </div>
            </div>
            """
            st.markdown(card_html, unsafe_allow_html=True)
            if hist is not None and not hist.empty:
                fig = mini_sparkline(hist, positive=(pct >= 0))
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.markdown("---")


def _render_heatmap():
    st.markdown(
        '<div class="section-header"><span class="section-title">Nifty 50 Heatmap</span>'
        '<span style="color:#8b949e;font-size:0.78rem;margin-left:auto;">Click a stock below to analyze</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    with st.spinner("Loading heatmap..."):
        prices = get_ticker_prices(TICKER_SYMBOLS)

    if prices:
        heatmap_data = [
            {"symbol": p["symbol"], "pct_change": p["pct_change"]}
            for p in prices
        ]
        fig = heatmap_chart(heatmap_data)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        # Quick-select from heatmap stocks
        sym_map = {f"{p['symbol'].replace('.NS','')} ({p['pct_change']:+.2f}%)": p["symbol"] for p in prices}
        hm_pick = st.selectbox(
            "heatmap_pick",
            [""] + list(sym_map.keys()),
            index=0,
            key="heatmap_stock_pick",
            label_visibility="collapsed",
            placeholder="↗ Analyze a heatmap stock…",
        )
        if hm_pick:
            _go_to_stock(sym_map[hm_pick])
    else:
        st.info("Heatmap data unavailable. Retrying on next refresh.")

    st.markdown("---")


def _render_gainers_losers():
    st.markdown(
        '<div class="section-header"><span class="section-title">Today\'s Movers</span></div>',
        unsafe_allow_html=True,
    )
    with st.spinner("Fetching movers..."):
        movers = get_gainers_losers(TICKER_SYMBOLS, top_n=10)

    col_g, col_l = st.columns(2)

    with col_g:
        st.markdown(
            f'<div style="color:{COLORS["positive"]};font-weight:700;font-size:0.9rem;'
            f'margin-bottom:6px;">▲ Top Gainers</div>',
            unsafe_allow_html=True,
        )
        _render_mover_list(movers.get("gainers", []), COLORS["positive"])

    with col_l:
        st.markdown(
            f'<div style="color:{COLORS["negative"]};font-weight:700;font-size:0.9rem;'
            f'margin-bottom:6px;">▼ Top Losers</div>',
            unsafe_allow_html=True,
        )
        _render_mover_list(movers.get("losers", []), COLORS["negative"])

    st.markdown("---")


def _render_mover_list(items: list, pct_color: str):
    if not items:
        st.info("No data.")
        return

    for item in items:
        sym = item["symbol"]
        name = get_display_name(sym)
        price = item["price"]
        pct = item["pct_change"]
        ticker = sym.replace(".NS", "").replace(".BO", "")

        c1, c2, c3, c4, c5 = st.columns([1.2, 2.2, 1.5, 1.1, 0.7])
        c1.markdown(
            f'<span style="color:#e6edf3;font-weight:800;font-family:monospace;font-size:0.85rem;">{ticker}</span>',
            unsafe_allow_html=True,
        )
        c2.markdown(
            f'<span style="color:#8b949e;font-size:0.78rem;">{name[:20]}</span>',
            unsafe_allow_html=True,
        )
        c3.markdown(
            f'<span style="font-family:monospace;color:#e6edf3;font-size:0.85rem;">₹{price:,.2f}</span>',
            unsafe_allow_html=True,
        )
        c4.markdown(
            f'<span style="color:{pct_color};font-weight:700;font-size:0.85rem;">{pct:+.2f}%</span>',
            unsafe_allow_html=True,
        )
        if c5.button("↗", key=f"mover_{sym}", help=f"Analyze {name}", use_container_width=True):
            _go_to_stock(sym)


def _render_news_feed():
    st.markdown(
        '<div class="section-header"><span class="section-title">Market News</span>'
        '<span class="section-badge">RSS</span></div>',
        unsafe_allow_html=True,
    )
    with st.spinner("Loading headlines..."):
        headlines = fetch_all_headlines(15)

    if not headlines:
        st.info("News unavailable. Check your internet connection.")
        return

    for item in headlines:
        title = item.get("title", "")
        source = item.get("source", "")
        link = item.get("link", "#")
        published = item.get("published", "")

        st.markdown(
            f'<div style="background:#161b22;border:1px solid #30363d;border-radius:7px;'
            f'padding:10px 14px;margin:5px 0;">'
            f'<a href="{link}" target="_blank" style="color:#e6edf3;text-decoration:none;'
            f'font-size:0.88rem;font-weight:600;">{title}</a>'
            f'<div style="color:#8b949e;font-size:0.74rem;margin-top:4px;">'
            f'{source}  ·  {published[:16] if published else ""}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
