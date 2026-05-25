"""
Home page: two-column layout — persistent watchlist (left) | analysis panel (right).
The right panel shows the FULL existing render_stock_detail engine when a stock is selected,
or the default index-chart + strategy view when nothing is selected.
Below the fold: Today's Movers → Momentum Scanner → Recent News.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd

from data.fetcher import (
    get_index_data, get_gainers_losers, get_ticker_prices,
    batch_download,
)
from data.news import fetch_all_headlines
from data.stocks_list import get_display_name
from data.technical import (
    calculate_rsi, calculate_volume_ratio, price_change_pct,
    is_price_breakout, is_volume_spike, momentum_score,
)
from components.watchlist_sidebar import ensure_watchlist_state, all_stock_options, normalize_symbol
from config import TICKER_SYMBOLS, COLORS, VOLUME_MOMENTUM_MULTIPLIER, RSI_OVERBOUGHT, RSI_OVERSOLD
from utils.helpers import color_for_change, clean_symbol

_INDEX_OPTIONS = {
    "NIFTY 100":     "^CNX100",
    "NIFTY 50":      "^NSEI",
    "BANK NIFTY":    "^NSEBANK",
    "NIFTY FINANCE": "^CNXFIN",
}


# ── State helpers ─────────────────────────────────────────────────────────────

def _select_inline(symbol: str):
    """Select a stock for inline right-panel display, staying on the Home page."""
    st.session_state.selected_stock = symbol
    st.rerun()


def _add_stock(symbol: str):
    wl = st.session_state.setdefault("watchlist", [])
    if symbol and symbol not in wl:
        wl.append(symbol)


def _remove_stock(symbol: str):
    st.session_state.watchlist = [s for s in st.session_state.watchlist if s != symbol]
    if st.session_state.get("selected_stock") == symbol:
        st.session_state.selected_stock = None


# ── Cached scanner ────────────────────────────────────────────────────────────

@st.cache_data(ttl=120, show_spinner=False)
def _quick_scan() -> list:
    hist_data = batch_download(TICKER_SYMBOLS, period="2mo")
    signals = []
    for sym in TICKER_SYMBOLS:
        try:
            df = hist_data.get(sym)
            if df is None or df.empty or len(df) < 20:
                continue
            rsi_s = calculate_rsi(df)
            rsi = float(rsi_s.iloc[-1]) if len(rsi_s) and not pd.isna(rsi_s.iloc[-1]) else None
            vol_s = calculate_volume_ratio(df, period=10)
            vol_ratio = float(vol_s.iloc[-1]) if len(vol_s) and not pd.isna(vol_s.iloc[-1]) else None
            chg1d = price_change_pct(df, days=1)
            price = float(df["Close"].iloc[-1])
            score = momentum_score(rsi or 50.0, vol_ratio or 1.0, chg1d)
            if is_price_breakout(df) and is_volume_spike(df, VOLUME_MOMENTUM_MULTIPLIER, 10):
                sig = "BREAKOUT"
            elif rsi is not None and rsi < RSI_OVERSOLD:
                sig = "REVERSAL"
            elif vol_ratio is not None and vol_ratio >= VOLUME_MOMENTUM_MULTIPLIER and chg1d > 0:
                sig = "MOMENTUM"
            else:
                sig = ""
            signals.append({
                "symbol": sym, "price": price, "rsi": rsi,
                "vol_ratio": vol_ratio, "chg1d": chg1d,
                "signal": sig, "momentum_score": score,
            })
        except Exception:
            pass
    signals.sort(key=lambda x: x["momentum_score"], reverse=True)
    return signals


# ── Page entry point ──────────────────────────────────────────────────────────

def render_home():
    left_col, right_col = st.columns([1.1, 2.5], gap="medium")

    with left_col:
        _render_watchlist_panel()

    with right_col:
        sel = st.session_state.get("selected_stock")
        if sel:
            _render_stock_analysis_panel(sel)
        else:
            _render_default_right_panel()

    st.markdown("---")
    _render_gainers_losers()
    st.markdown("---")
    _render_compact_scanner()
    st.markdown("---")
    _render_news_feed()


# ── Left panel: watchlist ─────────────────────────────────────────────────────

def _render_watchlist_panel():
    ensure_watchlist_state()
    catalog = all_stock_options()

    if "wl_edit_mode" not in st.session_state:
        st.session_state.wl_edit_mode = False

    # Title row + Edit / Done toggle
    title_col, edit_col = st.columns([3, 1])
    with title_col:
        st.markdown('<div class="wl-panel-title">My Watchlist</div>', unsafe_allow_html=True)
    with edit_col:
        btn_label = "✓ Done" if st.session_state.wl_edit_mode else "✎ Edit"
        if st.button(btn_label, key="wl_edit_toggle", use_container_width=True):
            st.session_state.wl_edit_mode = not st.session_state.wl_edit_mode
            st.rerun()

    # Search
    query = st.text_input(
        "Search",
        placeholder="Search ticker or company…",
        key="home_wl_search",
        label_visibility="collapsed",
    ).strip().lower()

    if query:
        matches = [
            (sym, name)
            for sym, name in catalog.items()
            if query in sym.lower() or query in name.lower() or query in clean_symbol(sym).lower()
        ][:6]
        if matches:
            st.markdown('<div class="wl-section-label">SEARCH RESULTS</div>', unsafe_allow_html=True)
            for sel_sym, sel_name in matches:
                if st.button(
                    f"{clean_symbol(sel_sym)} — {sel_name[:28]}",
                    key=f"home_wl_pick_{sel_sym}",
                    use_container_width=True,
                ):
                    _add_stock(sel_sym)
                    _select_inline(sel_sym)
        else:
            st.caption("No matches. Add manually below.")

    # Add ticker manually
    with st.expander("▸ Add ticker manually", expanded=False):
        exchange = st.radio("Exchange", ["NSE", "US"], horizontal=True, key="home_wl_exchange")
        manual = st.text_input("Ticker", placeholder="RELIANCE or AAPL", key="home_wl_manual")
        manual_sym = normalize_symbol(manual, exchange)
        if st.button("Add", key="home_wl_manual_add", use_container_width=True):
            if manual_sym:
                _add_stock(manual_sym)
                st.toast(f"Added {clean_symbol(manual_sym)}")
                st.rerun()

    st.markdown('<div class="wl-section-label">STOCKS</div>', unsafe_allow_html=True)

    watchlist = st.session_state.get("watchlist", [])
    if not watchlist:
        st.caption("No stocks yet. Search above to add.")
        return

    price_data = get_ticker_prices(watchlist)
    price_map = {p["symbol"]: p for p in price_data}
    edit_mode = st.session_state.wl_edit_mode

    for sym in watchlist:
        name = catalog.get(sym) or get_display_name(sym)
        ticker = clean_symbol(sym)
        pdata = price_map.get(sym, {})
        price = pdata.get("price")
        pct = pdata.get("pct_change", 0.0)

        price_str = f"₹{price:,.2f}" if price else "—"
        pct_color = COLORS["positive"] if pct >= 0 else COLORS["negative"]
        pct_str = f"{pct:+.2f}%" if price else "—"
        arrow = "▲" if pct >= 0 else "▼"
        is_active = sym == st.session_state.get("selected_stock")

        # Identical structure in both modes: HTML card (c1) + action button (c2).
        # Only the action button icon differs — ›  in normal mode, 🗑 in edit mode.
        card_cls = "wl-card-active" if is_active else "wl-card"
        c1, c2 = st.columns([5, 1])

        with c1:
            st.markdown(
                f'<div class="{card_cls}">'
                f'  <div class="wl-card-top">'
                f'    <span class="wl-card-ticker">{ticker}</span>'
                f'    <span class="wl-card-price">{price_str}</span>'
                f'  </div>'
                f'  <div class="wl-card-bot">'
                f'    <span class="wl-card-name">{name[:24]}</span>'
                f'    <span class="wl-card-pct" style="color:{pct_color};">{arrow} {pct_str}</span>'
                f'  </div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with c2:
            if edit_mode:
                # Marker div lets CSS :has() scope styles to only this button
                st.markdown('<div class="wl-del-marker"></div>', unsafe_allow_html=True)
                if st.button("🗑", key=f"wl_del_{sym}", use_container_width=True):
                    _remove_stock(sym)
                    st.rerun()
            else:
                st.markdown('<div class="wl-sel-marker"></div>', unsafe_allow_html=True)
                if st.button("›", key=f"wl_sel_{sym}", use_container_width=True):
                    _select_inline(sym)


# ── Right panel: stock analysis (full existing engine) ────────────────────────

def _render_stock_analysis_panel(symbol: str):
    """
    Renders the FULL existing render_stock_detail analysis inside the right column.
    No analysis logic lives here — we delegate entirely to the existing engine.
    """
    from pages.stock_detail import render_stock_detail
    render_stock_detail(symbol)


# ── Right panel: default view (no stock selected) ─────────────────────────────

def _render_default_right_panel():
    idx_col, strat_col = st.columns([2.0, 1.2], gap="medium")
    with idx_col:
        _render_index_chart()
    with strat_col:
        _render_strategy_panel()


# ── Index chart ───────────────────────────────────────────────────────────────

def _render_index_chart():
    from components.advanced_chart import render_chart_controls, render_advanced_chart

    sel_name = st.selectbox(
        "Index",
        list(_INDEX_OPTIONS.keys()),
        key="home_index_sel",
        label_visibility="collapsed",
    )
    symbol = _INDEX_OPTIONS[sel_name]

    data = get_index_data(symbol)
    current = data["current"]
    pct = data["pct_change"]
    change = data["change"]
    clr = color_for_change(pct)
    arrow = "▲" if pct >= 0 else "▼"

    st.markdown(
        f'<div class="idx-header">'
        f'  <span class="idx-name">{sel_name}</span>'
        f'  <span class="idx-price">{current:,.2f}</span>'
        f'  <span style="color:{clr};font-size:0.88rem;font-weight:700;">'
        f'    &nbsp;{arrow} {abs(change):,.2f} ({abs(pct):.2f}%)'
        f'  </span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    interval = render_chart_controls(f"index_{symbol}")
    render_advanced_chart(symbol, interval=interval, height=420)


# ── Strategy panel ────────────────────────────────────────────────────────────

def _render_strategy_panel():
    st.markdown('<div class="strat-title">Strategy Scanner</div>', unsafe_allow_html=True)

    scan_type = st.selectbox(
        "Signal filter",
        ["All Signals", "Breakouts", "Momentum", "Reversals"],
        key="home_strat_type",
        label_visibility="collapsed",
    )
    st.markdown('<div class="strat-section-lbl">Scanner Results</div>', unsafe_allow_html=True)

    try:
        with st.spinner("Scanning…"):
            signals = _quick_scan()

        if scan_type == "Breakouts":
            filtered = [s for s in signals if s["signal"] == "BREAKOUT"]
        elif scan_type == "Momentum":
            filtered = [s for s in signals if s["signal"] == "MOMENTUM"]
        elif scan_type == "Reversals":
            filtered = [s for s in signals if s["signal"] == "REVERSAL"]
        else:
            filtered = signals

        if filtered:
            rows = []
            for s in filtered[:8]:
                rows.append({
                    "Stock": s["symbol"].replace(".NS", ""),
                    "Price": f"₹{s['price']:,.0f}",
                    "Chg%":  f"{s['chg1d']:+.1f}%" if s.get("chg1d") is not None else "N/A",
                    "Vol":   f"{s['vol_ratio']:.1f}x" if s.get("vol_ratio") is not None else "N/A",
                    "RSI":   f"{s['rsi']:.0f}" if s.get("rsi") is not None else "N/A",
                })
            st.dataframe(
                pd.DataFrame(rows),
                hide_index=True,
                use_container_width=True,
                height=210,
            )
        else:
            st.info("No signals in current scan.")

    except Exception as scan_err:
        st.warning(f"Scanner unavailable: {scan_err}")

    st.markdown("---")
    st.markdown('<div class="strat-section-lbl">Filters</div>', unsafe_allow_html=True)
    st.selectbox(
        "RSI filter",
        ["RSI crossovers", "Overbought >70", "Oversold <30", "Bull cross 50"],
        key="home_rsi_cross",
        label_visibility="collapsed",
    )
    st.selectbox(
        "Volume filter",
        ["All", "> 1.5x avg", "> 2x avg", "> 3x avg"],
        key="home_vol_bk",
        label_visibility="collapsed",
    )
    if st.button("🚀 Run Full Scanner", key="home_run_scan", use_container_width=True):
        st.session_state.page = "Momentum"
        st.rerun()


# ── Below-fold: Movers ────────────────────────────────────────────────────────

def _render_gainers_losers():
    st.markdown(
        '<div class="section-header">'
        '<span class="section-title">Today\'s Movers</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    with st.spinner("Fetching movers…"):
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


def _render_mover_list(items: list, pct_color: str):
    if not items:
        st.info("No data.")
        return
    for item in items:
        sym    = item["symbol"]
        name   = get_display_name(sym)
        price  = item["price"]
        pct    = item["pct_change"]
        ticker = clean_symbol(sym)
        c1, c2, c3, c4 = st.columns([1.4, 2.2, 1.5, 1.1])
        if c1.button(ticker, key=f"home_mv_{sym}", help=name, use_container_width=True):
            _select_inline(sym)
        c2.markdown(
            f'<span style="color:#667085;font-size:0.78rem;">{name[:20]}</span>',
            unsafe_allow_html=True,
        )
        c3.markdown(
            f'<span style="font-family:monospace;color:#182230;font-size:0.85rem;">₹{price:,.2f}</span>',
            unsafe_allow_html=True,
        )
        c4.markdown(
            f'<span style="color:{pct_color};font-weight:700;font-size:0.85rem;">{pct:+.2f}%</span>',
            unsafe_allow_html=True,
        )


# ── Below-fold: Scanner ───────────────────────────────────────────────────────

def _render_compact_scanner():
    st.markdown(
        '<div class="section-header">'
        '<span class="section-title">Momentum Scanner</span>'
        '<span class="section-badge">TOP SIGNALS</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    try:
        signals = _quick_scan()
        top = [s for s in signals if s["signal"]][:6]

        if not top:
            st.info("No active signals. Markets may be consolidating.")
            if st.button("Open Full Scanner →", key="home_open_scanner"):
                st.session_state.page = "Momentum"
                st.rerun()
            return

        cols = st.columns(3)
        for i, sig in enumerate(top):
            clr     = COLORS["positive"] if sig["signal"] in ("BREAKOUT", "MOMENTUM") else COLORS["warning"]
            chg     = sig.get("chg1d") or 0.0
            chg_clr = COLORS["positive"] if chg >= 0 else COLORS["negative"]
            rsi_str = f"{sig['rsi']:.0f}" if sig.get("rsi") is not None else "—"
            sym_clean = sig["symbol"].replace(".NS", "")
            with cols[i % 3]:
                st.markdown(
                    f'<div class="compact-signal-card" style="border-left-color:{clr};">'
                    f'  <div class="csc-top">'
                    f'    <span class="csc-sym">{sym_clean}</span>'
                    f'    <span class="csc-badge" style="color:{clr};">{sig["signal"]}</span>'
                    f'  </div>'
                    f'  <div class="csc-price">₹{sig["price"]:,.1f} · RSI {rsi_str}</div>'
                    f'  <div style="color:{chg_clr};font-size:0.8rem;font-weight:700;">{chg:+.2f}%</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if st.button(
                    f"{sym_clean} →",
                    key=f"home_signal_pick_{sig['symbol']}_{i}",
                    use_container_width=True,
                ):
                    _select_inline(sig["symbol"])

        if st.button("View Full Scanner →", key="home_full_scan"):
            st.session_state.page = "Momentum"
            st.rerun()

    except Exception as e:
        st.warning(f"Scanner data unavailable: {e}")


# ── Below-fold: News ──────────────────────────────────────────────────────────

def _render_news_feed():
    st.markdown(
        '<div class="section-header">'
        '<span class="section-title">Recent News</span>'
        '<span class="section-badge">RSS</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    with st.spinner("Loading headlines…"):
        headlines = fetch_all_headlines(12)

    if not headlines:
        st.info("News unavailable.")
        return

    for item in headlines:
        title     = item.get("title", "")
        source    = item.get("source", "")
        link      = item.get("link", "#")
        published = str(item.get("published", ""))
        st.markdown(
            f'<div style="background:#ffffff;border:1px solid #dce3ee;border-radius:7px;'
            f'padding:10px 14px;margin:5px 0;">'
            f'<a href="{link}" target="_blank" style="color:#182230;text-decoration:none;'
            f'font-size:0.88rem;font-weight:600;">{title}</a>'
            f'<div style="color:#667085;font-size:0.74rem;margin-top:4px;">'
            f'{source} · {published[:16] if published else ""}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
