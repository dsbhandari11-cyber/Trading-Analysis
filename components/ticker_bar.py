"""
Real-time scrolling ticker bar rendered via HTML/CSS.
Fetches prices for a fixed list of NSE stocks.
"""

import streamlit as st
from data.fetcher import get_ticker_prices
from data.stocks_list import get_display_name
from config import TICKER_SYMBOLS
from utils.helpers import clean_symbol


def render_ticker_bar():
    # get_ticker_prices is @st.cache_data — returns instantly on cache hit.
    # No spinner: a cache miss resolves in the background via the data manager;
    # we show the placeholder row instead of blocking the render thread.
    prices = get_ticker_prices(TICKER_SYMBOLS)

    if not prices:
        st.markdown(
            '<div class="ticker-outer"><span style="color:#8b949e;padding:6px 16px;font-size:0.82rem;">Fetching market data...</span></div>',
            unsafe_allow_html=True,
        )
        return

    items_html = _build_items_html(prices)
    doubled = items_html + items_html  # duplicate for seamless loop

    html = f"""
    <div class="ticker-outer">
        <div class="ticker-track">
            {doubled}
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def _build_items_html(prices: list) -> str:
    parts = []
    for item in prices:
        sym = item["symbol"]
        name = clean_symbol(sym)
        price = item["price"]
        pct = item["pct_change"]
        direction = "ticker-up" if pct >= 0 else "ticker-down"
        arrow = "▲" if pct >= 0 else "▼"
        sign = "+" if pct >= 0 else ""

        parts.append(
            f'<span class="ticker-item">'
            f'<span class="ticker-name">{name}</span>'
            f'<span class="ticker-price">₹{price:,.2f}</span>'
            f'<span class="{direction}">{arrow} {sign}{pct:.2f}%</span>'
            f'</span>'
            f'<span style="color:#30363d;padding:0 4px;">|</span>'
        )
    return "".join(parts)
