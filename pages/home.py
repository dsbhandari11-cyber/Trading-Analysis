"""
Home page: 3-column layout — watchlist | index chart | strategy scanner.
Below: Today's Movers → Momentum Scanner → Recent News.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
from plotly.subplots import make_subplots
import plotly.graph_objects as go

from data.fetcher import (
    get_index_data, get_gainers_losers, get_ticker_prices,
    get_history, batch_download,
)
from data.news import fetch_all_headlines
from data.stocks_list import get_display_name
from data.technical import (
    calculate_rsi, calculate_volume_ratio, price_change_pct,
    is_price_breakout, is_volume_spike, momentum_score,
)
from components.watchlist_sidebar import ensure_watchlist_state, all_stock_options, normalize_symbol
from config import TICKER_SYMBOLS, COLORS, VOLUME_MOMENTUM_MULTIPLIER, RSI_OVERBOUGHT, RSI_OVERSOLD
from utils.helpers import ist_now, color_for_change, clean_symbol

_INDEX_OPTIONS = {
    "NIFTY 100":     "^CNX100",
    "NIFTY 50":      "^NSEI",
    "BANK NIFTY":    "^NSEBANK",
    "NIFTY FINANCE": "^CNXFIN",
}


def _go_to_stock(symbol: str):
    st.session_state.selected_stock = symbol
    st.session_state.page = "StockDetail"
    st.rerun()


def _add_stock(symbol: str):
    wl = st.session_state.setdefault("watchlist", [])
    if symbol and symbol not in wl:
        wl.append(symbol)


def _remove_stock(symbol: str):
    st.session_state.watchlist = [s for s in st.session_state.watchlist if s != symbol]
    if st.session_state.get("selected_stock") == symbol:
        st.session_state.selected_stock = None
        st.session_state.page = "Home"


@st.cache_data(ttl=120, show_spinner=False)
def _quick_scan() -> list:
    """Lightweight scan of TICKER_SYMBOLS (25 stocks) for the strategy panel."""
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
                "symbol": sym,
                "price": price,
                "rsi": rsi,
                "vol_ratio": vol_ratio,
                "chg1d": chg1d,
                "signal": sig,
                "momentum_score": score,
            })
        except Exception:
            pass
    signals.sort(key=lambda x: x["momentum_score"], reverse=True)
    return signals


def _build_index_chart(hist: pd.DataFrame) -> go.Figure:
    ema20 = hist["Close"].ewm(span=20, adjust=False).mean()
    ema50 = hist["Close"].ewm(span=50, adjust=False).mean()

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.78, 0.22],
        vertical_spacing=0.03,
    )

    fig.add_trace(go.Candlestick(
        x=hist.index,
        open=hist["Open"], high=hist["High"],
        low=hist["Low"], close=hist["Close"],
        increasing_line_color="#00d4aa",
        decreasing_line_color="#ff4444",
        name="Price",
        showlegend=False,
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=hist.index, y=ema20,
        mode="lines", line=dict(color="#4d9de0", width=1.4),
        name="EMA 20",
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=hist.index, y=ema50,
        mode="lines", line=dict(color="#f0ad4e", width=1.4, dash="dot"),
        name="EMA 50",
    ), row=1, col=1)

    vol_colors = [
        "#00d4aa" if c >= o else "#ff4444"
        for c, o in zip(hist["Close"], hist["Open"])
    ]
    fig.add_trace(go.Bar(
        x=hist.index, y=hist["Volume"],
        marker_color=vol_colors, opacity=0.5,
        name="Volume", showlegend=False,
    ), row=2, col=1)

    ax = dict(gridcolor="#21262d", color="#8b949e", linecolor="#30363d")
    fig.update_layout(
        paper_bgcolor="#0d1117",
        plot_bgcolor="#0d1117",
        font=dict(color="#8b949e", size=11),
        margin=dict(l=8, r=8, t=16, b=8),
        height=370,
        showlegend=True,
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color="#8b949e", size=10),
            orientation="h", x=0, y=1.04,
        ),
        xaxis=dict(**ax, showgrid=False, rangeslider=dict(visible=False)),
        yaxis=dict(**ax, showgrid=True),
        xaxis2=dict(**ax, showgrid=False),
        yaxis2=dict(**ax, showgrid=False),
    )
    return fig


# ── Page entry point ─────────────────────────────────────────────────────────

def render_home():
    col_watch, col_chart, col_strat = st.columns([1.1, 2.25, 1.5], gap="medium")

    with col_watch:
        _render_watchlist_panel()

    with col_chart:
        _render_index_chart()

    with col_strat:
        _render_strategy_panel()

    st.markdown("---")
    _render_gainers_losers()
    st.markdown("---")
    _render_compact_scanner()
    st.markdown("---")
    _render_news_feed()


# ── Column renders ────────────────────────────────────────────────────────────

def _render_watchlist_panel():
    ensure_watchlist_state()
    catalog = all_stock_options()

    st.markdown('<div class="wl-panel-title">Watchlist</div>', unsafe_allow_html=True)
    st.caption("NSE and US equities")

    query = st.text_input(
        "Search",
        placeholder="Search ticker or company",
        key="home_wl_search",
        label_visibility="collapsed",
    ).strip().lower()

    matches = [
        (sym, name)
        for sym, name in catalog.items()
        if not query
        or query in sym.lower()
        or query in name.lower()
        or query in clean_symbol(sym).lower()
    ][:20]

    if matches:
        labels = [f"{clean_symbol(sym)} - {name}" for sym, name in matches]
        sel_label = st.selectbox(
            "Results",
            labels,
            key="home_wl_search_result",
            label_visibility="collapsed",
        )
        sel_sym = matches[labels.index(sel_label)][0]
        oc1, oc2 = st.columns(2)
        if oc1.button("Open", key="home_wl_open", use_container_width=True):
            _add_stock(sel_sym)
            _go_to_stock(sel_sym)
        if oc2.button("Add", key="home_wl_add", use_container_width=True):
            _add_stock(sel_sym)
            st.toast(f"Added {clean_symbol(sel_sym)}")

    with st.expander("▸ Add ticker manually", expanded=False):
        exchange = st.radio("Exchange", ["NSE", "US"], horizontal=True, key="home_wl_exchange")
        manual = st.text_input("Ticker", placeholder="RELIANCE or AAPL", key="home_wl_manual")
        manual_sym = normalize_symbol(manual, exchange)
        if st.button("Add ticker", key="home_wl_manual_add", use_container_width=True):
            if manual_sym:
                _add_stock(manual_sym)
                st.toast(f"Added {clean_symbol(manual_sym)}")

    st.markdown('<div class="wl-section-label">WATCHLIST STOCKS</div>', unsafe_allow_html=True)

    watchlist = st.session_state.get("watchlist", [])
    if not watchlist:
        st.caption("No stocks added yet. Search above to add.")
        return

    price_data = get_ticker_prices(watchlist)
    price_map = {p["symbol"]: p for p in price_data}

    for sym in watchlist:
        name = catalog.get(sym) or get_display_name(sym)
        ticker = clean_symbol(sym)
        pdata = price_map.get(sym, {})
        price = pdata.get("price")
        pct = pdata.get("pct_change", 0.0)

        price_str = f"₹{price:,.2f}" if price else "—"
        pct_color = COLORS["positive"] if pct >= 0 else COLORS["negative"]
        pct_str = f"{pct:+.2f}%" if price else ""
        arrow = "▲" if pct >= 0 else "▼"
        card_cls = "wl-stock-card-active" if sym == st.session_state.get("selected_stock") else "wl-stock-card"

        st.markdown(
            f"""<div class="{card_cls}">
                <div class="wl-stock-top">
                    <span class="wl-stock-sym">{ticker}</span>
                    <span class="wl-stock-price">{price_str}</span>
                </div>
                <div class="wl-stock-bot">
                    <span class="wl-stock-name">{name[:22]}</span>
                    <span style="color:{pct_color};font-size:0.75rem;font-weight:700;">{arrow} {pct_str}</span>
                </div>
            </div>""",
            unsafe_allow_html=True,
        )
        bc1, bc2 = st.columns([5, 1])
        if bc1.button("↗ Analyse", key=f"home_wl_sel_{sym}", use_container_width=True):
            _go_to_stock(sym)
        if bc2.button("✕", key=f"home_wl_rm_{sym}", use_container_width=True):
            _remove_stock(sym)
            st.rerun()


def _render_index_chart():
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
        f"""<div class="idx-header">
            <span class="idx-name">{sel_name}</span>
            <span class="idx-price">{current:,.2f}</span>
            <span style="color:{clr};font-size:0.88rem;font-weight:700;">
                &nbsp;{arrow} {abs(change):,.2f} ({abs(pct):.2f}%)
            </span>
        </div>""",
        unsafe_allow_html=True,
    )

    hist = get_history(symbol, period="3mo")
    if hist is not None and not hist.empty:
        fig = _build_index_chart(hist)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    else:
        st.info("Chart data unavailable for this index.")


def _render_strategy_panel():
    st.markdown('<div class="strat-title">Strategy</div>', unsafe_allow_html=True)

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
                rsi_str = f"{s['rsi']:.0f}" if s.get("rsi") is not None else "N/A"
                vol_str = f"{s['vol_ratio']:.1f}x" if s.get("vol_ratio") is not None else "N/A"
                rows.append({
                    "Stock": s["symbol"].replace(".NS", ""),
                    "Price": f"₹{s['price']:,.0f}",
                    "Chg%": f"{s['chg1d']:+.1f}%" if s.get("chg1d") is not None else "N/A",
                    "Volume": vol_str,
                    "RSI": rsi_str,
                })
            st.dataframe(
                pd.DataFrame(rows),
                hide_index=True,
                use_container_width=True,
                height=220,
            )
        else:
            st.info("No signals in current scan.")

    except Exception as scan_err:
        st.warning(f"Scanner unavailable: {scan_err}")

    st.markdown("---")
    st.markdown('<div class="strat-section-lbl">Filters</div>', unsafe_allow_html=True)

    st.selectbox(
        "RSI crossovers",
        ["RSI crossovers", "Overbought >70", "Oversold <30", "Bull cross 50"],
        key="home_rsi_cross",
        label_visibility="collapsed",
    )
    st.selectbox(
        "Breakout volume",
        ["All", "> 1.5x avg", "> 2x avg", "> 3x avg"],
        key="home_vol_bk",
        label_visibility="collapsed",
    )
    st.selectbox(
        "RS",
        ["All", "RS > 1.0", "RS > 1.5"],
        key="home_rs",
        label_visibility="collapsed",
    )

    if st.button("🚀 Run Scanner", key="home_run_scan", use_container_width=True):
        st.session_state.page = "Momentum"
        st.rerun()


# ── Below-the-fold sections ───────────────────────────────────────────────────

def _render_gainers_losers():
    st.markdown(
        '<div class="section-header"><span class="section-title">Today\'s Movers</span></div>',
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
        sym = item["symbol"]
        name = get_display_name(sym)
        price = item["price"]
        pct = item["pct_change"]
        ticker = clean_symbol(sym)
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
        if c5.button("↗", key=f"home_mv_{sym}", help=f"Analyse {name}", use_container_width=True):
            _go_to_stock(sym)


def _render_compact_scanner():
    st.markdown(
        '<div class="section-header"><span class="section-title">Momentum Scanner</span>'
        '<span class="section-badge">TOP SIGNALS</span></div>',
        unsafe_allow_html=True,
    )
    try:
        signals = _quick_scan()
        top = [s for s in signals if s["signal"]][:6]

        if not top:
            st.info("No active signals in current scan. Markets may be consolidating.")
            if st.button("Open Full Scanner →", key="home_open_scanner"):
                st.session_state.page = "Momentum"
                st.rerun()
            return

        cols = st.columns(3)
        for i, sig in enumerate(top):
            clr = COLORS["positive"] if sig["signal"] in ("BREAKOUT", "MOMENTUM") else COLORS["warning"]
            chg = sig.get("chg1d") or 0.0
            chg_clr = COLORS["positive"] if chg >= 0 else COLORS["negative"]
            rsi_str = f"{sig['rsi']:.0f}" if sig.get("rsi") is not None else "—"
            with cols[i % 3]:
                st.markdown(
                    f"""<div class="compact-signal-card" style="border-left-color:{clr};">
                        <div class="csc-top">
                            <span class="csc-sym">{sig['symbol'].replace('.NS','')}</span>
                            <span class="csc-badge" style="color:{clr};">{sig['signal']}</span>
                        </div>
                        <div class="csc-price">₹{sig['price']:,.1f} · RSI {rsi_str}</div>
                        <div style="color:{chg_clr};font-size:0.8rem;font-weight:700;">{chg:+.2f}%</div>
                    </div>""",
                    unsafe_allow_html=True,
                )

        if st.button("View Full Scanner →", key="home_full_scan"):
            st.session_state.page = "Momentum"
            st.rerun()

    except Exception as e:
        st.warning(f"Scanner data unavailable: {e}")
        if st.button("Open Full Scanner", key="home_open_scanner_err"):
            st.session_state.page = "Momentum"
            st.rerun()


def _render_news_feed():
    st.markdown(
        '<div class="section-header"><span class="section-title">Recent News</span>'
        '<span class="section-badge">RSS</span></div>',
        unsafe_allow_html=True,
    )
    with st.spinner("Loading headlines…"):
        headlines = fetch_all_headlines(12)

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
            f'{source} · {published[:16] if published else ""}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
