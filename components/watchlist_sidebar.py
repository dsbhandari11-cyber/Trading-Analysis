"""
Interactive watchlist/search sidebar for the drill-down stock workflow.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import streamlit as st

from data.stocks_list import SYMBOL_NAMES, get_display_name
from utils.helpers import clean_symbol


DEFAULT_WATCHLIST = ["PCJEWELLER.NS", "ADANIENT.NS", "RELIANCE.NS", "TCS.NS"]

US_SYMBOL_NAMES: Dict[str, str] = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "NVIDIA",
    "GOOGL": "Alphabet",
    "AMZN": "Amazon",
    "META": "Meta Platforms",
    "TSLA": "Tesla",
    "AMD": "Advanced Micro Devices",
    "NFLX": "Netflix",
    "JPM": "JPMorgan Chase",
}


def ensure_watchlist_state() -> None:
    if "watchlist" not in st.session_state:
        st.session_state.watchlist = DEFAULT_WATCHLIST.copy()
    if "selected_stock" not in st.session_state:
        st.session_state.selected_stock = None
    if "stock_notes" not in st.session_state:
        st.session_state.stock_notes = {}


def all_stock_options() -> Dict[str, str]:
    options = dict(SYMBOL_NAMES)
    options.update(US_SYMBOL_NAMES)
    return dict(sorted(options.items(), key=lambda item: item[1].lower()))


def normalize_symbol(raw_symbol: str, exchange: str = "NSE") -> str:
    symbol = (raw_symbol or "").strip().upper().replace(" ", "")
    if not symbol:
        return ""
    if symbol.endswith((".NS", ".BO")):
        return symbol
    if exchange == "NSE":
        return f"{symbol}.NS"
    return symbol


def _option_label(symbol: str, name: str) -> str:
    return f"{clean_symbol(symbol)} - {name}"


def _select_stock(symbol: str) -> None:
    st.session_state.selected_stock = symbol
    st.session_state.page = "StockDetail"
    st.rerun()


def _add_stock(symbol: str) -> None:
    if symbol and symbol not in st.session_state.watchlist:
        st.session_state.watchlist.append(symbol)


def _remove_stock(symbol: str) -> None:
    st.session_state.watchlist = [
        item for item in st.session_state.watchlist if item != symbol
    ]
    if st.session_state.get("selected_stock") == symbol:
        st.session_state.selected_stock = None
        st.session_state.page = "Home"


def render_watchlist_sidebar() -> None:
    """Render a persistent left watchlist, search, and add-stock workflow."""
    ensure_watchlist_state()
    catalog = all_stock_options()

    with st.sidebar:
        st.markdown(
            '<div class="side-nav-title">Trading</div>'
            '<div class="side-nav-item active">⌂ Home</div>'
            '<div class="side-nav-item">▥ Charting</div>'
            '<div class="side-nav-item">▨ Trading</div>'
            '<div class="side-nav-item">◫ Portfolio</div>'
            '<div class="side-nav-item">◎ Profile</div>'
            '<div class="side-nav-item">▣ Analysis</div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div class="watchlist-title">Stocks</div>', unsafe_allow_html=True)
        st.caption("Tap any stock name to analyze")

        query = st.text_input(
            "Search stocks",
            placeholder="Search ticker or company",
            key="watchlist_search_query",
        ).strip().lower()

        matches: List[Tuple[str, str]] = [
            (symbol, name)
            for symbol, name in catalog.items()
            if not query
            or query in symbol.lower()
            or query in name.lower()
            or query in clean_symbol(symbol).lower()
        ][:25]

        if matches and query:
            st.markdown('<div class="watchlist-subtitle">Search Results</div>', unsafe_allow_html=True)
            for selected_symbol, selected_name in matches[:8]:
                if st.button(
                    _option_label(selected_symbol, selected_name),
                    key=f"watchlist_search_pick_{selected_symbol}",
                    use_container_width=True,
                ):
                    _add_stock(selected_symbol)
                    _select_stock(selected_symbol)
        elif query:
            st.caption("No catalog match. Add manually below.")

        with st.expander("Add ticker manually", expanded=False):
            exchange = st.radio(
                "Exchange",
                ["NSE", "US"],
                horizontal=True,
                key="watchlist_manual_exchange",
            )
            manual = st.text_input(
                "Ticker",
                placeholder="PCJEWELLER or AAPL",
                key="watchlist_manual_symbol",
            )
            manual_symbol = normalize_symbol(manual, exchange)
            if st.button("Add ticker", key="watchlist_manual_add", use_container_width=True):
                if manual_symbol:
                    _add_stock(manual_symbol)
                    st.toast(f"Added {clean_symbol(manual_symbol)}")

        st.markdown("---")
        st.markdown('<div class="watchlist-subtitle">Saved Stocks</div>', unsafe_allow_html=True)

        st.markdown('<div class="watchlist-scroll">', unsafe_allow_html=True)
        for symbol in list(st.session_state.watchlist):
            active = symbol == st.session_state.get("selected_stock")
            name = catalog.get(symbol) or get_display_name(symbol)
            css_class = "watchlist-row-active" if active else "watchlist-row"
            st.markdown(
                f"""
                <div class="{css_class}">
                    <div>
                        <div class="watchlist-symbol">{clean_symbol(symbol)}</div>
                        <div class="watchlist-name">{name}</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            c1, c2 = st.columns([5, 1])
            if c1.button(
                f"{clean_symbol(symbol)} - {name}",
                key=f"watchlist_select_{symbol}",
                use_container_width=True,
            ):
                _select_stock(symbol)
            if c2.button("X", key=f"watchlist_remove_{symbol}", use_container_width=True):
                _remove_stock(symbol)
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
