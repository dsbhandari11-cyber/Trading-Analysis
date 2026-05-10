"""
Drill-down stock analysis page.
Renders when the user selects a stock from the watchlist or search.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Optional, List, Dict
import yfinance as yf

from data.fetcher import get_history, get_stock_info
from data.news import fetch_stock_related_news, fetch_all_headlines
from utils.helpers import (
    fmt_price, fmt_change, fmt_large,
    color_for_change, rsi_color, clean_symbol, ist_now,
)
from config import COLORS
from data.stocks_list import get_display_name, SYMBOL_NAMES


# ─── Sector peer map ─────────────────────────────────────────────────────────

SECTOR_PEERS: Dict[str, List[str]] = {
    "Technology": ["TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS", "LTIM.NS", "PERSISTENT.NS"],
    "Financial Services": ["HDFCBANK.NS", "ICICIBANK.NS", "AXISBANK.NS", "KOTAKBANK.NS", "SBIN.NS", "BAJFINANCE.NS", "INDUSINDBK.NS"],
    "Energy": ["RELIANCE.NS", "ONGC.NS", "BPCL.NS", "IOC.NS", "COALINDIA.NS", "NTPC.NS", "POWERGRID.NS"],
    "Consumer Defensive": ["HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS", "MARICO.NS", "COLPAL.NS", "TATACONSUM.NS"],
    "Basic Materials": ["TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS", "VEDL.NS", "GRASIM.NS", "AMBUJACEM.NS", "SHREECEM.NS"],
    "Industrials": ["LT.NS", "SIEMENS.NS", "ABB.NS", "HAL.NS", "BEL.NS", "BHEL.NS", "POLYCAB.NS"],
    "Healthcare": ["SUNPHARMA.NS", "CIPLA.NS", "DRREDDY.NS", "DIVISLAB.NS", "LUPIN.NS", "APOLLOHOSP.NS", "MAXHEALTH.NS"],
    "Consumer Cyclical": ["MARUTI.NS", "TATAMOTORS.NS", "BAJAJ-AUTO.NS", "HEROMOTOCO.NS", "EICHERMOT.NS", "TVSMOTOR.NS", "M&M.NS"],
    "Communication Services": ["BHARTIARTL.NS", "INDUSTOWER.NS", "NAUKRI.NS"],
    "Utilities": ["NTPC.NS", "POWERGRID.NS"],
    "Real Estate": ["GODREJPROP.NS", "DLF.NS"],
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _safe_float(val, default: float = 0.0) -> float:
    try:
        f = float(val)
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def _fmt_ratio(val, decimals: int = 2, suffix: str = "", prefix: str = "") -> str:
    if val is None:
        return "N/A"
    try:
        f = float(val)
        if f != f:
            return "N/A"
        return f"{prefix}{f:.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return "N/A"


def _to_crore(val) -> Optional[float]:
    try:
        f = float(val)
        return None if f != f else f / 1e7
    except (TypeError, ValueError):
        return None


def _fmt_crore(val) -> str:
    cr = _to_crore(val)
    if cr is None:
        return "N/A"
    if abs(cr) >= 1_00_000:
        return f"₹{cr/1_00_000:.2f}L Cr"
    if abs(cr) >= 1_000:
        return f"₹{cr/1_000:.2f}K Cr"
    return f"₹{cr:.2f} Cr"


def _get_row(df: pd.DataFrame, *keys) -> Optional[pd.Series]:
    """Get the first matching row from a DataFrame by trying multiple key names."""
    for key in keys:
        if key in df.index:
            return df.loc[key]
    return None


def _calc_rsi(df: pd.DataFrame, period: int = 14) -> Optional[pd.Series]:
    if df is None or df.empty or "Close" not in df.columns:
        return None
    try:
        import ta
        return ta.momentum.RSIIndicator(close=df["Close"], window=period).rsi()
    except Exception:
        pass
    try:
        delta = df["Close"].diff()
        gain = delta.clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
        loss = (-delta.clip(upper=0)).ewm(com=period - 1, min_periods=period).mean()
        rs = gain / loss.replace(0, float("nan"))
        return 100 - (100 / (1 + rs))
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def _get_quarterly_data(symbol: str) -> Dict:
    """Fetch quarterly financials — cached for 1 hour."""
    t = yf.Ticker(symbol)
    result: Dict = {}
    try:
        result["income"] = t.quarterly_income_stmt
    except Exception:
        result["income"] = None
    try:
        result["balance"] = t.quarterly_balance_sheet
    except Exception:
        result["balance"] = None
    try:
        result["cashflow"] = t.quarterly_cashflow
    except Exception:
        result["cashflow"] = None
    return result


def _watchlist_contains(symbol: str) -> bool:
    return symbol in st.session_state.get("watchlist", [])


def _toggle_watchlist(symbol: str) -> None:
    watchlist = st.session_state.setdefault("watchlist", [])
    if symbol in watchlist:
        st.session_state.watchlist = [item for item in watchlist if item != symbol]
    else:
        watchlist.append(symbol)


def _stock_snapshot_csv(symbol: str, info: dict) -> bytes:
    rows = [
        ("Symbol", clean_symbol(symbol)),
        ("Company", info.get("longName") or info.get("shortName") or get_display_name(symbol)),
        ("Exchange", "NSE" if symbol.endswith(".NS") else info.get("exchange", "US")),
        ("Sector", info.get("sector", "")),
        ("Industry", info.get("industry", "")),
        ("Current Price", info.get("currentPrice") or info.get("regularMarketPrice")),
        ("Previous Close", info.get("previousClose") or info.get("regularMarketPreviousClose")),
        ("Market Cap", info.get("marketCap")),
        ("Volume", info.get("volume") or info.get("regularMarketVolume")),
        ("52 Week High", info.get("fiftyTwoWeekHigh")),
        ("52 Week Low", info.get("fiftyTwoWeekLow")),
        ("Trailing P/E", info.get("trailingPE")),
        ("EPS", info.get("trailingEps")),
    ]
    return pd.DataFrame(rows, columns=["Metric", "Value"]).to_csv(index=False).encode("utf-8")


def _format_currency_for_symbol(symbol: str, value: float) -> str:
    if value is None or value != value:
        return "N/A"
    prefix = "Rs. " if symbol.endswith((".NS", ".BO")) else "$"
    return f"{prefix}{value:,.2f}"


# ─── Main entry point ────────────────────────────────────────────────────────

def render_stock_detail(symbol: str):
    """Full drill-down analysis page for a single stock."""
    with st.spinner(f"Loading data for {clean_symbol(symbol)}…"):
        info = get_stock_info(symbol)

    if not info:
        st.warning(f"Could not load data for {symbol}. Check the symbol or try again.")
        if st.button("← Back to Dashboard", key="detail_back_empty"):
            st.session_state.page = "Home"
            st.rerun()
        return

    name = (
        info.get("longName")
        or info.get("shortName")
        or get_display_name(symbol)
    )
    exchange = (
        "NSE" if symbol.endswith(".NS")
        else "BSE" if symbol.endswith(".BO")
        else info.get("exchange", "")
    )
    symbol_clean = clean_symbol(symbol)
    sector       = info.get("sector", "")
    industry     = info.get("industry", "")

    current    = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
    prev_close = _safe_float(info.get("previousClose") or info.get("regularMarketPreviousClose"))
    change     = current - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0.0
    clr        = color_for_change(change_pct)
    arrow      = "▲" if change >= 0 else "▼"

    day_high   = _safe_float(info.get("dayHigh") or info.get("regularMarketDayHigh"))
    day_low    = _safe_float(info.get("dayLow") or info.get("regularMarketDayLow"))
    wk52_high  = _safe_float(info.get("fiftyTwoWeekHigh"))
    wk52_low   = _safe_float(info.get("fiftyTwoWeekLow"))
    volume     = info.get("volume") or info.get("regularMarketVolume") or 0
    market_cap = info.get("marketCap")

    sub_parts = [exchange]
    if sector:
        sub_parts.append(sector)
    if industry:
        sub_parts.append(industry)
    sub = " · ".join(sub_parts)

    # ── Back button ──────────────────────────────────────────────────────────
    bcol, _, wcol, ecol = st.columns([1.1, 4.8, 1.4, 1.4])
    with bcol:
        if st.button("Back", key="detail_back_btn", use_container_width=True):
            st.session_state.page = "Home"
            st.rerun()
    with wcol:
        watch_label = "Remove" if _watchlist_contains(symbol) else "Watch"
        if st.button(watch_label, key=f"detail_watch_{symbol}", use_container_width=True):
            _toggle_watchlist(symbol)
            st.rerun()
    with ecol:
        st.download_button(
            "Export",
            data=_stock_snapshot_csv(symbol, info),
            file_name=f"{clean_symbol(symbol)}_snapshot.csv",
            mime="text/csv",
            key=f"detail_export_{symbol}",
            use_container_width=True,
        )

    # ── Stock header card ────────────────────────────────────────────────────
    pe_ttm = _safe_float(info.get("trailingPE"))
    eps    = _safe_float(info.get("trailingEps"))
    mc_str = _fmt_crore(market_cap) if market_cap else "N/A"

    st.markdown(f"""
    <div class="stock-header-card">
      <div class="stock-header-inner">
        <div style="flex:1;">
          <span class="stock-symbol-badge">{symbol_clean}</span>
          <div class="stock-full-name">{name}</div>
          <div style="color:{COLORS['text_muted']};font-size:0.77rem;margin-top:4px;">{sub}</div>
        </div>
        <div class="stock-price-block">
          <div class="stock-price-large">{fmt_price(current)}</div>
          <div style="font-size:1.05rem;font-weight:600;color:{clr};margin-top:2px;">
            {arrow} {fmt_price(abs(change))} &nbsp;({fmt_change(change_pct)})
          </div>
          <div style="color:{COLORS['text_muted']};font-size:0.74rem;margin-top:4px;">
            Prev Close: {fmt_price(prev_close)} &nbsp;·&nbsp; {ist_now()}
          </div>
        </div>
      </div>
      <div class="stock-header-chips">
        <span class="sh-chip">H: {fmt_price(day_high)}</span>
        <span class="sh-chip">L: {fmt_price(day_low)}</span>
        <span class="sh-chip">52W H: {fmt_price(wk52_high)}</span>
        <span class="sh-chip">52W L: {fmt_price(wk52_low)}</span>
        <span class="sh-chip">Vol: {fmt_large(volume)}</span>
        <span class="sh-chip">Mkt Cap: {mc_str}</span>
        {f'<span class="sh-chip">P/E: {pe_ttm:.1f}</span>' if pe_ttm else ''}
        {f'<span class="sh-chip">EPS: ₹{eps:.2f}</span>' if eps else ''}
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Tabs ─────────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "Chart",
        "Performance",
        "Fundamentals",
        "Financials",
        "Peers",
        "News",
        "Notes",
    ])

    with tab1:
        _render_chart_tab(symbol, info)

    with tab2:
        _render_performance_tab(symbol, info, current)

    with tab3:
        _render_fundamentals_tab(info)

    with tab4:
        _render_financials_tab(symbol, info)

    with tab5:
        _render_peers_tab(symbol, info)

    with tab6:
        _render_news_tab(symbol, name)

    with tab7:
        _render_notes_tab(symbol, name)


# ─── Tab 1: Chart & Technicals ───────────────────────────────────────────────

def _render_chart_tab(symbol: str, info: dict):
    PERIOD_MAP = {
        "1D": ("1d", "5m"),
        "5D": ("5d", "15m"),
        "1M": ("1mo", "1d"),
        "3M": ("3mo", "1d"),
        "6M": ("6mo", "1d"),
        "1Y": ("1y", "1d"),
        "5Y": ("5y", "1wk"),
    }

    ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([1.2, 1.4, 2.3, 1.1])
    with ctrl1:
        period_label = st.selectbox(
            "Timeframe", list(PERIOD_MAP.keys()), index=3,
            key="detail_period", label_visibility="collapsed",
        )
    with ctrl2:
        chart_type = st.selectbox(
            "Chart", ["Candlestick", "Line"],
            key="detail_chart_type", label_visibility="collapsed",
        )
    with ctrl3:
        overlays = st.multiselect(
            "Overlays",
            ["SMA", "EMA", "VWAP", "Bollinger Bands"],
            default=["SMA", "EMA"],
            key="detail_overlays",
            label_visibility="collapsed",
        )
    with ctrl4:
        live_refresh = st.checkbox("Live", key="detail_live_refresh", value=False)
        if live_refresh:
            st.markdown('<meta http-equiv="refresh" content="60">', unsafe_allow_html=True)

    period, interval = PERIOD_MAP[period_label]
    hist = get_history(symbol, period=period, interval=interval)

    if hist is None or hist.empty:
        st.warning("No chart data available for the selected period.")
        return

    sma20 = hist["Close"].rolling(20, min_periods=1).mean()
    sma50 = hist["Close"].rolling(50, min_periods=1).mean()
    ema20 = hist["Close"].ewm(span=20, adjust=False).mean()
    ema50 = hist["Close"].ewm(span=50, adjust=False).mean()
    rsi_s = _calc_rsi(hist)
    typical_price = (hist["High"] + hist["Low"] + hist["Close"]) / 3
    vwap = (typical_price * hist["Volume"]).cumsum() / hist["Volume"].replace(0, np.nan).cumsum()

    bb_mid = hist["Close"].rolling(20).mean()
    bb_std = hist["Close"].rolling(20).std()
    bb_up  = bb_mid + 2 * bb_std
    bb_low = bb_mid - 2 * bb_std

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.60, 0.20, 0.20],
        vertical_spacing=0.04,
    )

    if chart_type == "Candlestick":
        fig.add_trace(go.Candlestick(
            x=hist.index,
            open=hist["Open"], high=hist["High"],
            low=hist["Low"],   close=hist["Close"],
            increasing_line_color=COLORS["positive"],
            decreasing_line_color=COLORS["negative"],
            name="OHLC", showlegend=False,
        ), row=1, col=1)
    else:
        pos = hist["Close"].iloc[-1] >= hist["Close"].iloc[0]
        fig.add_trace(go.Scatter(
            x=hist.index, y=hist["Close"],
            mode="lines",
            line=dict(color=COLORS["positive"] if pos else COLORS["negative"], width=2),
            fill="tozeroy",
            fillcolor="rgba(0,212,170,0.06)" if pos else "rgba(255,68,68,0.06)",
            name="Price", showlegend=False,
        ), row=1, col=1)

    if "SMA" in overlays:
        fig.add_trace(go.Scatter(
            x=hist.index, y=sma20,
            mode="lines", line=dict(color="#4ea1ff", width=1.2),
            name="SMA 20",
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=hist.index, y=sma50,
            mode="lines", line=dict(color="#6c7a89", width=1.1),
            name="SMA 50",
        ), row=1, col=1)

    if "EMA" in overlays:
        fig.add_trace(go.Scatter(
            x=hist.index, y=ema20,
            mode="lines", line=dict(color="#f0ad4e", width=1.2, dash="dot"),
            name="EMA 20",
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=hist.index, y=ema50,
            mode="lines", line=dict(color="#7c57ff", width=1.2, dash="dot"),
            name="EMA 50",
        ), row=1, col=1)

    if "VWAP" in overlays and vwap.notna().any():
        fig.add_trace(go.Scatter(
            x=hist.index, y=vwap,
            mode="lines", line=dict(color="#ff7f50", width=1.4),
            name="VWAP",
        ), row=1, col=1)

    if "Bollinger Bands" in overlays:
        fig.add_trace(go.Scatter(
            x=list(hist.index) + list(hist.index[::-1]),
            y=list(bb_up) + list(bb_low[::-1]),
            fill="toself",
            fillcolor="rgba(0,212,170,0.05)",
            line=dict(color="rgba(0,0,0,0)"),
            name="BB Band", showlegend=True,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=hist.index, y=bb_up,
            mode="lines", line=dict(color="rgba(0,212,170,0.27)", width=1),
            name="BB Upper", showlegend=False,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=hist.index, y=bb_low,
            mode="lines", line=dict(color="rgba(0,212,170,0.27)", width=1),
            name="BB Lower", showlegend=False,
        ), row=1, col=1)

    vol_colors = [
        COLORS["positive"] if c >= o else COLORS["negative"]
        for c, o in zip(hist["Close"], hist["Open"])
    ]
    fig.add_trace(go.Bar(
        x=hist.index, y=hist["Volume"],
        marker_color=vol_colors, opacity=0.65,
        name="Volume", showlegend=False,
    ), row=2, col=1)

    if rsi_s is not None and len(rsi_s) > 0:
        fig.add_trace(go.Scatter(
            x=hist.index, y=rsi_s,
            mode="lines", line=dict(color="#00d4aa", width=1.5),
            name="RSI(14)", showlegend=False,
        ), row=3, col=1)
        for level, color in [(70, "rgba(255,68,68,0.47)"), (50, "rgba(139,148,158,0.33)"), (30, "rgba(0,212,170,0.47)")]:
            fig.add_shape(
                type="line", x0=hist.index[0], x1=hist.index[-1],
                y0=level, y1=level,
                line=dict(color=color, width=1, dash="dash"),
                row=3, col=1,
            )

    _GRID  = dict(gridcolor="#21262d", zerolinecolor="#30363d")
    _XAXIS = dict(showgrid=False, color="#8b949e", linecolor="#30363d")

    fig.update_layout(
        paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
        font=dict(color="#8b949e", size=11),
        height=580,
        margin=dict(l=8, r=8, t=16, b=8),
        showlegend=True,
        legend=dict(
            bgcolor="#1c2333", bordercolor="#30363d", borderwidth=1,
            font=dict(color="#8b949e", size=10),
            orientation="h", x=0, y=1.04,
        ),
        dragmode="pan",
        modebar=dict(bgcolor="#161b22", color="#8b949e", activecolor="#00d4aa"),
        xaxis=dict(**_XAXIS, rangeslider=dict(visible=True, thickness=0.05)),
        yaxis=dict(**_GRID, color="#8b949e", linecolor="#30363d", title="Price (₹)"),
        xaxis2=dict(**_XAXIS),
        yaxis2=dict(**_GRID, color="#8b949e", linecolor="#30363d", title="Vol"),
        xaxis3=dict(**_XAXIS),
        yaxis3=dict(**_GRID, color="#8b949e", linecolor="#30363d",
                    range=[0, 100], title="RSI"),
    )
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "scrollZoom": True,
            "displaylogo": False,
            "modeBarButtonsToAdd": [
                "drawline",
                "drawopenpath",
                "drawrect",
                "eraseshape",
            ],
        },
    )

    # ── Technicals summary chips ─────────────────────────────────────────────
    if rsi_s is not None and len(rsi_s) > 0:
        rsi_now   = _safe_float(rsi_s.iloc[-1])
        ema20_now = _safe_float(ema20.iloc[-1])
        ema50_now = _safe_float(ema50.iloc[-1])
        c_price   = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        vol_ratio = 0.0
        if "Volume" in hist.columns and len(hist) >= 20:
            avg_vol = hist["Volume"].iloc[-20:].mean()
            if avg_vol:
                vol_ratio = hist["Volume"].iloc[-1] / avg_vol

        rsi_clr   = rsi_color(rsi_now)
        rsi_lbl   = "Overbought" if rsi_now >= 70 else ("Oversold" if rsi_now <= 30 else "Neutral")
        ema_lbl   = "Above EMA20 ▲" if c_price > ema20_now else "Below EMA20 ▼"
        ema_clr   = COLORS["positive"] if c_price > ema20_now else COLORS["negative"]
        ema50_lbl = "Above EMA50 ▲" if c_price > ema50_now else "Below EMA50 ▼"
        ema50_clr = COLORS["positive"] if c_price > ema50_now else COLORS["negative"]
        vol_lbl   = f"{vol_ratio:.1f}x avg vol" if vol_ratio else "N/A"
        vol_clr   = COLORS["positive"] if vol_ratio >= 1.5 else COLORS["text_muted"]

        # Trend signal
        bullish_signals = sum([
            c_price > ema20_now,
            c_price > ema50_now,
            rsi_now < 70 and rsi_now > 40,
            vol_ratio >= 1.0,
        ])
        trend_lbl = "Bullish" if bullish_signals >= 3 else ("Bearish" if bullish_signals <= 1 else "Neutral")
        trend_clr = COLORS["positive"] if trend_lbl == "Bullish" else (
            COLORS["negative"] if trend_lbl == "Bearish" else COLORS["warning"]
        )

        st.markdown(f"""
        <div class="tech-summary-row">
          <div class="tech-chip">
            <span class="tech-chip-label">Trend Signal</span>
            <span class="tech-chip-val" style="color:{trend_clr};font-size:0.9rem;font-weight:700;">
              ● {trend_lbl}
            </span>
          </div>
          <div class="tech-chip">
            <span class="tech-chip-label">RSI(14)</span>
            <span class="tech-chip-val" style="color:{rsi_clr};">{rsi_now:.1f} — {rsi_lbl}</span>
          </div>
          <div class="tech-chip">
            <span class="tech-chip-label">EMA 20</span>
            <span class="tech-chip-val" style="color:{ema_clr};">{ema_lbl}</span>
          </div>
          <div class="tech-chip">
            <span class="tech-chip-label">EMA 50</span>
            <span class="tech-chip-val" style="color:{ema50_clr};">{ema50_lbl}</span>
          </div>
          <div class="tech-chip">
            <span class="tech-chip-label">Volume</span>
            <span class="tech-chip-val" style="color:{vol_clr};">{vol_lbl}</span>
          </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Buy/Sell Pressure ─────────────────────────────────────────────────
        st.markdown("---")
        _render_market_sentiment(info, hist)


def _render_market_sentiment(info: dict, hist: pd.DataFrame):
    """Buy/sell pressure and momentum indicators."""
    st.markdown(
        '<div class="section-header"><span class="section-title">Market Sentiment</span></div>',
        unsafe_allow_html=True,
    )

    # Derive pressure from recent price movement
    if hist is not None and not hist.empty and len(hist) >= 5:
        recent = hist.tail(5)
        up_days = (recent["Close"] > recent["Open"]).sum()
        dn_days = 5 - up_days
        buy_pct  = int(up_days / 5 * 100)
        sell_pct = 100 - buy_pct
        last_price = _safe_float(hist["Close"].iloc[-1])
        avg_vol = hist["Volume"].tail(20).mean() if "Volume" in hist.columns else 0
        vol_ratio = (hist["Volume"].iloc[-1] / avg_vol) if avg_vol else 0
        trend_dir = "Uptrend" if hist["Close"].iloc[-1] >= hist["Close"].tail(min(len(hist), 20)).mean() else "Downtrend"
        momentum_score = max(0, min(100, int(buy_pct * 0.45 + max(-10, min(20, recent["Close"].pct_change().sum() * 100)) * 2 + min(30, vol_ratio * 12))))

        bids = []
        asks = []
        base_qty = int(max(100, (hist["Volume"].tail(10).mean() if "Volume" in hist.columns else 1000) / 1000))
        step = max(last_price * 0.001, 0.05)
        for level in range(5):
            bids.append((last_price - step * (level + 1), base_qty * (5 - level) * max(1, buy_pct // 20)))
            asks.append((last_price + step * (level + 1), base_qty * (5 - level) * max(1, sell_pct // 20)))

        ob_col, pressure_col = st.columns([1.3, 1])
        with ob_col:
            bid_rows = "".join(
                f"<div class='order-row'><span>{price:.2f}</span><span class='order-buy'>{qty:,}</span></div>"
                for price, qty in bids
            )
            ask_rows = "".join(
                f"<div class='order-row'><span>{price:.2f}</span><span class='order-sell'>{qty:,}</span></div>"
                for price, qty in asks
            )
            st.markdown(
                f"""
                <div class="orderbook-card">
                    <div class="orderbook-title">Bid / Ask Order Sentiment</div>
                    <div class="orderbook-grid">
                        <div>
                            <div class="orderbook-label">Bid (Buy Orders)</div>
                            {bid_rows}
                        </div>
                        <div>
                            <div class="orderbook-label">Ask (Sell Orders)</div>
                            {ask_rows}
                        </div>
                    </div>
                    <div class="pressure-track">
                        <div class="pressure-buy" style="width:{buy_pct}%"></div>
                        <div class="pressure-sell" style="width:{sell_pct}%"></div>
                    </div>
                    <div class="pressure-caption">
                        <span>Bid total {sum(q for _, q in bids):,}</span>
                        <span>Ask total {sum(q for _, q in asks):,}</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with pressure_col:
            st.markdown('<div class="sentiment-panel-title">Activity Gauges</div>', unsafe_allow_html=True)
            st.caption("Buy vs sell pressure")
            st.progress(buy_pct / 100)
            st.caption("Volume activity")
            st.progress(min(vol_ratio / 3, 1.0))
            st.caption("Momentum score")
            st.progress(momentum_score / 100)
            st.markdown(
                f"""
                <div class="trend-pill {'trend-up' if trend_dir == 'Uptrend' else 'trend-down'}">
                    {trend_dir}
                </div>
                """,
                unsafe_allow_html=True,
            )

        c1, c2, c3, c4 = st.columns(4)

        # Buy pressure
        with c1:
            st.markdown(f"""
            <div class="sentiment-card sentiment-bull">
              <div class="sent-label">Buy Pressure</div>
              <div class="sent-val" style="color:{COLORS['positive']};">{buy_pct}%</div>
              <div class="sent-sub">{up_days}/5 days bullish</div>
            </div>""", unsafe_allow_html=True)

        # Sell pressure
        with c2:
            st.markdown(f"""
            <div class="sentiment-card sentiment-bear">
              <div class="sent-label">Sell Pressure</div>
              <div class="sent-val" style="color:{COLORS['negative']};">{sell_pct}%</div>
              <div class="sent-sub">{dn_days}/5 days bearish</div>
            </div>""", unsafe_allow_html=True)

        # Momentum
        mom_pct = ((hist["Close"].iloc[-1] - hist["Close"].iloc[-10]) / hist["Close"].iloc[-10] * 100
                   ) if len(hist) >= 10 else 0.0
        mom_clr = COLORS["positive"] if mom_pct >= 0 else COLORS["negative"]
        with c3:
            st.markdown(f"""
            <div class="sentiment-card">
              <div class="sent-label">10-Day Momentum</div>
              <div class="sent-val" style="color:{mom_clr};">
                {"▲" if mom_pct >= 0 else "▼"} {abs(mom_pct):.2f}%
              </div>
              <div class="sent-sub">Price momentum</div>
            </div>""", unsafe_allow_html=True)

        # Volatility
        if len(hist) >= 20:
            returns = hist["Close"].pct_change().dropna()
            vol_ann = returns.std() * (252 ** 0.5) * 100
            vol_lbl = "High" if vol_ann > 40 else ("Medium" if vol_ann > 20 else "Low")
            vol_clr = COLORS["negative"] if vol_ann > 40 else (
                COLORS["warning"] if vol_ann > 20 else COLORS["positive"]
            )
        else:
            vol_ann, vol_lbl, vol_clr = 0.0, "N/A", COLORS["text_muted"]

        with c4:
            st.markdown(f"""
            <div class="sentiment-card">
              <div class="sent-label">Annualised Volatility</div>
              <div class="sent-val" style="color:{vol_clr};">{vol_ann:.1f}%</div>
              <div class="sent-sub">{vol_lbl} volatility</div>
            </div>""", unsafe_allow_html=True)

        # Buy/Sell progress bar
        st.markdown(f"""
        <div style="margin:12px 0 4px 0;">
          <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
            <span style="color:{COLORS['positive']};font-size:0.78rem;font-weight:600;">
              BUY {buy_pct}%
            </span>
            <span style="color:{COLORS['negative']};font-size:0.78rem;font-weight:600;">
              SELL {sell_pct}%
            </span>
          </div>
          <div style="height:8px;background:#30363d;border-radius:4px;overflow:hidden;">
            <div style="height:100%;width:{buy_pct}%;
                        background:linear-gradient(90deg,{COLORS['positive']},{COLORS['positive']}99);
                        border-radius:4px;"></div>
          </div>
        </div>
        """, unsafe_allow_html=True)


# ─── Tab 2: Performance ───────────────────────────────────────────────────────

def _render_performance_tab(symbol: str, info: dict, current: float):
    open_price = _safe_float(info.get("open") or info.get("regularMarketOpen"))
    prev_close = _safe_float(info.get("previousClose") or info.get("regularMarketPreviousClose"))
    day_high   = _safe_float(info.get("dayHigh") or info.get("regularMarketDayHigh"))
    day_low    = _safe_float(info.get("dayLow") or info.get("regularMarketDayLow"))
    wk52_high  = _safe_float(info.get("fiftyTwoWeekHigh"))
    wk52_low   = _safe_float(info.get("fiftyTwoWeekLow"))
    volume     = info.get("volume") or info.get("regularMarketVolume") or 0
    avg_vol    = info.get("averageVolume") or info.get("averageDailyVolume10Day") or 0
    ma50       = _safe_float(info.get("fiftyDayAverage"))
    ma200      = _safe_float(info.get("twoHundredDayAverage"))
    beta       = info.get("beta")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(
            '<div class="section-header"><span class="section-title">Market Data</span></div>',
            unsafe_allow_html=True,
        )
        rows = [
            ("Open",         fmt_price(open_price)),
            ("Prev. Close",  fmt_price(prev_close)),
            ("Today's High", fmt_price(day_high)),
            ("Today's Low",  fmt_price(day_low)),
            ("Volume",       fmt_large(volume)),
            ("Avg. Volume",  fmt_large(avg_vol)),
            ("50-Day MA",    fmt_price(ma50)),
            ("200-Day MA",   fmt_price(ma200)),
        ]
        if beta is not None:
            rows.append(("Beta", _fmt_ratio(beta)))
        _render_perf_table(rows)

    with col2:
        st.markdown(
            '<div class="section-header"><span class="section-title">52-Week Performance</span></div>',
            unsafe_allow_html=True,
        )

        if wk52_low and wk52_high and wk52_high > wk52_low and current:
            pos = max(0.0, min(100.0,
                (current - wk52_low) / (wk52_high - wk52_low) * 100))
            nc  = COLORS["negative"]
            pc  = COLORS["positive"]
            tm  = COLORS["text_muted"]
            tx  = COLORS["text"]
            st.markdown(f"""
            <div style="padding:8px 0 16px 0;">
              <div style="display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:10px;">
                <div>
                  <div style="color:{nc};font-weight:700;font-size:0.95rem;">{fmt_price(wk52_low)}</div>
                  <div style="color:{tm};font-size:0.7rem;">52W Low</div>
                </div>
                <div style="text-align:center;">
                  <div style="color:{tx};font-weight:800;font-size:1.25rem;font-family:monospace;">{fmt_price(current)}</div>
                  <div style="color:{tm};font-size:0.7rem;">Current</div>
                </div>
                <div style="text-align:right;">
                  <div style="color:{pc};font-weight:700;font-size:0.95rem;">{fmt_price(wk52_high)}</div>
                  <div style="color:{tm};font-size:0.7rem;">52W High</div>
                </div>
              </div>
              <div style="position:relative;height:10px;background:#30363d;border-radius:5px;margin:4px 0 20px 0;">
                <div style="position:absolute;left:0;top:0;height:100%;width:{pos:.1f}%;
                            background:linear-gradient(90deg,#ff4444,#f0ad4e 50%,#00d4aa);
                            border-radius:5px;"></div>
                <div style="position:absolute;left:{pos:.1f}%;top:50%;
                            transform:translate(-50%,-50%);
                            width:16px;height:16px;background:#e6edf3;
                            border-radius:50%;border:2px solid #00d4aa;
                            box-shadow:0 0 6px rgba(0,212,170,0.6);"></div>
              </div>
              <div style="color:{tm};font-size:0.75rem;text-align:center;margin-top:4px;">
                {pos:.1f}% above 52-week low
              </div>
            </div>
            """, unsafe_allow_html=True)

    # ── 1-week & 4-week performance ──────────────────────────────────────────
    hist_1m = get_history(symbol, period="1mo", interval="1d")
    if hist_1m is not None and not hist_1m.empty and len(hist_1m) >= 2:
        close    = hist_1m["Close"]
        wk1_chg  = ((close.iloc[-1] - close.iloc[max(-6, -len(close))]) /
                    close.iloc[max(-6, -len(close))] * 100) if len(close) >= 5 else 0.0
        wk4_chg  = ((close.iloc[-1] - close.iloc[0]) / close.iloc[0] * 100) if len(close) >= 2 else 0.0
        wk1_hi   = close.iloc[-6:].max() if len(close) >= 6 else close.max()
        wk1_lo   = close.iloc[-6:].min() if len(close) >= 6 else close.min()
        wk4_hi   = close.max()
        wk4_lo   = close.min()

        wk1_clr = color_for_change(wk1_chg)
        wk4_clr = color_for_change(wk4_chg)
        tm = COLORS["text_muted"]
        tx = COLORS["text"]

        st.markdown(f"""
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:16px;">
          <div class="perf-mini-card">
            <div class="perf-mini-title">1-Week Performance</div>
            <div style="font-size:1.1rem;font-weight:700;color:{wk1_clr};margin:4px 0;">
              {"▲" if wk1_chg >= 0 else "▼"} {abs(wk1_chg):.2f}%
            </div>
            <div style="color:{tm};font-size:0.72rem;">
              High: <span style="color:{tx};font-family:monospace;">{fmt_price(wk1_hi)}</span>
              &nbsp; Low: <span style="color:{tx};font-family:monospace;">{fmt_price(wk1_lo)}</span>
            </div>
          </div>
          <div class="perf-mini-card">
            <div class="perf-mini-title">4-Week Performance</div>
            <div style="font-size:1.1rem;font-weight:700;color:{wk4_clr};margin:4px 0;">
              {"▲" if wk4_chg >= 0 else "▼"} {abs(wk4_chg):.2f}%
            </div>
            <div style="color:{tm};font-size:0.72rem;">
              High: <span style="color:{tx};font-family:monospace;">{fmt_price(wk4_hi)}</span>
              &nbsp; Low: <span style="color:{tx};font-family:monospace;">{fmt_price(wk4_lo)}</span>
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    # ── 3-month & 6-month performance ────────────────────────────────────────
    hist_6m = get_history(symbol, period="6mo", interval="1d")
    if hist_6m is not None and not hist_6m.empty and len(hist_6m) >= 2:
        close6    = hist_6m["Close"]
        mid_idx   = max(0, len(close6) // 2)
        mo3_chg   = ((close6.iloc[-1] - close6.iloc[mid_idx]) / close6.iloc[mid_idx] * 100)
        mo6_chg   = ((close6.iloc[-1] - close6.iloc[0]) / close6.iloc[0] * 100)
        mo3_clr   = color_for_change(mo3_chg)
        mo6_clr   = color_for_change(mo6_chg)
        tm = COLORS["text_muted"]

        st.markdown(f"""
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px;">
          <div class="perf-mini-card">
            <div class="perf-mini-title">3-Month Performance</div>
            <div style="font-size:1.1rem;font-weight:700;color:{mo3_clr};margin:4px 0;">
              {"▲" if mo3_chg >= 0 else "▼"} {abs(mo3_chg):.2f}%
            </div>
            <div style="color:{tm};font-size:0.72rem;">vs mid-period price</div>
          </div>
          <div class="perf-mini-card">
            <div class="perf-mini-title">6-Month Performance</div>
            <div style="font-size:1.1rem;font-weight:700;color:{mo6_clr};margin:4px 0;">
              {"▲" if mo6_chg >= 0 else "▼"} {abs(mo6_chg):.2f}%
            </div>
            <div style="color:{tm};font-size:0.72rem;">vs 6 months ago</div>
          </div>
        </div>
        """, unsafe_allow_html=True)


# ─── Tab 3: Fundamentals ─────────────────────────────────────────────────────

def _render_fundamentals_tab(info: dict):
    market_cap    = info.get("marketCap")
    pe_ttm        = info.get("trailingPE")
    pe_fwd        = info.get("forwardPE")
    eps           = info.get("trailingEps")
    div_yield     = info.get("dividendYield")
    div_rate      = info.get("dividendRate")
    pb            = info.get("priceToBook")
    de            = info.get("debtToEquity")
    roe           = info.get("returnOnEquity")
    roa           = info.get("returnOnAssets")
    ps            = info.get("priceToSalesTrailing12Months")
    cr            = info.get("currentRatio")
    beta          = info.get("beta")
    profit_margin = info.get("profitMargins")
    gross_margin  = info.get("grossMargins")
    op_margin     = info.get("operatingMargins")
    revenue       = info.get("totalRevenue")
    ebitda        = info.get("ebitda")
    fcf           = info.get("freeCashflow")
    target_mean   = info.get("targetMeanPrice")
    target_median = info.get("targetMedianPrice")
    recommend     = info.get("recommendationKey", "")
    peg           = info.get("pegRatio")
    book_val      = info.get("bookValue")

    pct = lambda v: _fmt_ratio((v * 100) if v else None, 2, suffix="%") if v else "N/A"
    dy_str  = pct(div_yield)
    roe_str = pct(roe)
    roa_str = pct(roa)
    pm_str  = pct(profit_margin)
    gm_str  = pct(gross_margin)
    om_str  = pct(op_margin)

    st.markdown(
        '<div class="section-header"><span class="section-title">Fundamental KPI Cards</span></div>',
        unsafe_allow_html=True,
    )
    kpis = [
        ("P/E Ratio", _fmt_ratio(pe_ttm)),
        ("EPS", _fmt_ratio(eps, prefix="Rs. ")),
        ("ROE", roe_str),
        ("ROA", roa_str),
        ("Debt/Equity", _fmt_ratio(de)),
        ("Dividend Yield", dy_str),
        ("Book Value", _fmt_ratio(book_val, prefix="Rs. ")),
        ("Profit Margin", pm_str),
        ("Revenue Growth", pct(info.get("revenueGrowth"))),
        ("Current Ratio", _fmt_ratio(cr)),
        ("PEG Ratio", _fmt_ratio(peg)),
        ("Market Cap", _fmt_crore(market_cap) if market_cap else "N/A"),
    ]
    for row_start in range(0, len(kpis), 4):
        cols = st.columns(4)
        for col, (label, value) in zip(cols, kpis[row_start: row_start + 4]):
            with col:
                st.markdown(
                    f"""
                    <div class="kpi-card">
                        <div class="kpi-label">{label}</div>
                        <div class="kpi-value">{value}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(
            '<div class="section-header"><span class="section-title">Valuation Metrics</span></div>',
            unsafe_allow_html=True,
        )
        _render_perf_table([
            ("Market Cap",       _fmt_crore(market_cap) if market_cap else "N/A"),
            ("P/E Ratio (TTM)",  _fmt_ratio(pe_ttm)),
            ("P/E Ratio (Fwd)",  _fmt_ratio(pe_fwd)),
            ("PEG Ratio",        _fmt_ratio(peg)),
            ("EPS (TTM)",        _fmt_ratio(eps, prefix="₹")),
            ("Price to Book",    _fmt_ratio(pb, suffix="x")),
            ("Price to Sales",   _fmt_ratio(ps, suffix="x")),
            ("Book Value/Share", _fmt_ratio(book_val, prefix="₹")),
            ("Dividend Yield",   dy_str),
            ("Dividend Rate",    _fmt_ratio(div_rate, prefix="₹") if div_rate else "N/A"),
            ("Beta",             _fmt_ratio(beta)),
        ])

    with col2:
        st.markdown(
            '<div class="section-header"><span class="section-title">Financial Health</span></div>',
            unsafe_allow_html=True,
        )
        _render_perf_table([
            ("Debt to Equity",   _fmt_ratio(de)),
            ("Current Ratio",    _fmt_ratio(cr)),
            ("Return on Equity", roe_str),
            ("Return on Assets", roa_str),
            ("Profit Margin",    pm_str),
            ("Gross Margin",     gm_str),
            ("Operating Margin", om_str),
            ("Total Revenue",    fmt_large(revenue) if revenue else "N/A"),
            ("EBITDA",           fmt_large(ebitda) if ebitda else "N/A"),
            ("Free Cash Flow",   fmt_large(fcf) if fcf else "N/A"),
        ])

    # ── Analyst Estimates ────────────────────────────────────────────────────
    if target_mean or target_median or recommend:
        st.markdown(
            '<div class="section-header" style="margin-top:16px;">'
            '<span class="section-title">Analyst Estimates</span>'
            '</div>',
            unsafe_allow_html=True,
        )
        rec_map = {
            "strong_buy": ("STRONG BUY", COLORS["positive"]),
            "buy":        ("BUY",        COLORS["positive"]),
            "hold":       ("HOLD",       COLORS["warning"]),
            "sell":       ("SELL",       COLORS["negative"]),
            "strong_sell":("STRONG SELL",COLORS["negative"]),
        }
        rec_label, rec_clr = rec_map.get(
            recommend.lower() if recommend else "",
            (recommend.upper().replace("-", " ") if recommend else "N/A", COLORS["text_muted"]),
        )

        ac1, ac2, ac3 = st.columns(3)
        with ac1:
            st.markdown(f"""
            <div class="metric-card" style="text-align:center;">
              <div class="metric-label">Consensus Rating</div>
              <div class="metric-value" style="font-size:1.1rem;color:{rec_clr};">{rec_label}</div>
            </div>""", unsafe_allow_html=True)
        with ac2:
            st.markdown(f"""
            <div class="metric-card" style="text-align:center;">
              <div class="metric-label">Target Price (Mean)</div>
              <div class="metric-value" style="font-size:1.1rem;">{fmt_price(_safe_float(target_mean)) if target_mean else "N/A"}</div>
            </div>""", unsafe_allow_html=True)
        with ac3:
            st.markdown(f"""
            <div class="metric-card" style="text-align:center;">
              <div class="metric-label">Target Price (Median)</div>
              <div class="metric-value" style="font-size:1.1rem;">{fmt_price(_safe_float(target_median)) if target_median else "N/A"}</div>
            </div>""", unsafe_allow_html=True)


# ─── Tab 4: Financials (Quarterly) ───────────────────────────────────────────

def _render_financials_tab(symbol: str, info: dict):
    with st.spinner("Loading quarterly financials…"):
        qdata = _get_quarterly_data(symbol)

    income = qdata.get("income")
    balance = qdata.get("balance")
    cashflow = qdata.get("cashflow")

    if income is None or income.empty:
        st.info("Quarterly financial data not available for this stock.")
        return

    # ── Revenue & Net Income trend chart ────────────────────────────────────
    rev_row   = _get_row(income, "Total Revenue", "Operating Revenue")
    ni_row    = _get_row(income, "Net Income", "Net Income Common Stockholders",
                         "Net Income From Continuing Operation Net Minority Interest")
    eps_row   = _get_row(income, "Diluted EPS", "Basic EPS")
    op_inc    = _get_row(income, "Operating Income", "EBIT")
    ebitda_r  = _get_row(income, "EBITDA", "Normalized EBITDA")

    if rev_row is not None:
        # Use last 8 quarters, newest first → reverse for chart
        qtrs = income.columns[:8][::-1]
        qtrs_labels = [q.strftime("%b '%y") for q in qtrs]

        rev_vals  = [_to_crore(rev_row.get(q)) for q in qtrs]
        ni_vals   = [_to_crore(ni_row.get(q)) if ni_row is not None else None for q in qtrs]
        eps_vals  = [_safe_float(eps_row.get(q), 0) if eps_row is not None else 0 for q in qtrs]
        opm_vals  = []
        for q in qtrs:
            r = _to_crore(rev_row.get(q)) if rev_row is not None else None
            o = _to_crore(op_inc.get(q)) if op_inc is not None else None
            if r and o and r != 0:
                opm_vals.append(round(o / r * 100, 2))
            else:
                opm_vals.append(None)

        # ── Chart 1: Revenue + Net Income ─────────────────────────────────
        fig_rev = make_subplots(specs=[[{"secondary_y": True}]])
        fig_rev.add_trace(go.Bar(
            x=qtrs_labels, y=rev_vals,
            name="Revenue (Cr)", marker_color="#3d7ebf",
            text=[f"₹{v:.0f}Cr" if v else "" for v in rev_vals],
            textposition="outside", textfont=dict(size=9, color="#8b949e"),
        ), secondary_y=False)
        if any(v is not None for v in ni_vals):
            ni_colors = [COLORS["positive"] if (v or 0) >= 0 else COLORS["negative"]
                         for v in ni_vals]
            fig_rev.add_trace(go.Bar(
                x=qtrs_labels, y=ni_vals,
                name="Net Profit (Cr)", marker_color=ni_colors, opacity=0.8,
            ), secondary_y=False)
        if any(v for v in opm_vals):
            fig_rev.add_trace(go.Scatter(
                x=qtrs_labels, y=opm_vals,
                name="OPM %", mode="lines+markers",
                line=dict(color="#f0ad4e", width=2),
                marker=dict(size=6),
            ), secondary_y=True)

        fig_rev.update_layout(
            paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
            font=dict(color="#8b949e", size=10),
            height=300, barmode="group",
            margin=dict(l=8, r=8, t=36, b=8),
            title=dict(text="Quarterly Revenue & Net Profit", font=dict(size=12, color="#e6edf3"), x=0),
            legend=dict(bgcolor="#1c2333", bordercolor="#30363d", font=dict(size=9), x=0, y=1.14, orientation="h"),
            xaxis=dict(showgrid=False, color="#8b949e", linecolor="#30363d"),
            yaxis=dict(gridcolor="#21262d", color="#8b949e", title="₹ Crores"),
            yaxis2=dict(gridcolor="#21262d", color="#f0ad4e", title="OPM %", showgrid=False),
        )
        st.plotly_chart(fig_rev, use_container_width=True)

        # ── Chart 2: EPS trend ────────────────────────────────────────────
        if eps_row is not None and any(eps_vals):
            eps_clrs = [COLORS["positive"] if v >= 0 else COLORS["negative"] for v in eps_vals]
            fig_eps = go.Figure(go.Bar(
                x=qtrs_labels, y=eps_vals,
                name="EPS (₹)", marker_color=eps_clrs,
                text=[f"₹{v:.2f}" for v in eps_vals],
                textposition="outside", textfont=dict(size=9, color="#8b949e"),
            ))
            fig_eps.update_layout(
                paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
                font=dict(color="#8b949e", size=10),
                height=220, margin=dict(l=8, r=8, t=36, b=8),
                title=dict(text="Earnings Per Share (EPS) — Quarterly", font=dict(size=12, color="#e6edf3"), x=0),
                xaxis=dict(showgrid=False, color="#8b949e"),
                yaxis=dict(gridcolor="#21262d", color="#8b949e", title="₹ EPS"),
            )
            st.plotly_chart(fig_eps, use_container_width=True)

    # ── Sub-tabs: Income, Balance Sheet, Cash Flow ───────────────────────────
    ftab1, ftab2, ftab3, ftab4, ftab5 = st.tabs([
        "Quarterly Results",
        "Profit & Loss",
        "Balance Sheet",
        "Cash Flow",
        "Shareholding Pattern",
    ])

    with ftab1:
        _render_income_table(income)

    with ftab2:
        _render_income_table(income)

    with ftab3:
        if balance is not None and not balance.empty:
            _render_balance_table(balance)
        else:
            st.info("Balance sheet data unavailable.")

    with ftab4:
        if cashflow is not None and not cashflow.empty:
            _render_cashflow_table(cashflow)
        else:
            st.info("Cash flow data unavailable.")

    with ftab5:
        _render_shareholding_tab(info)


def _render_shareholding_tab(info: dict):
    insiders = info.get("heldPercentInsiders") or 0
    institutions = info.get("heldPercentInstitutions") or 0
    insiders_pct = max(0.0, min(100.0, insiders * 100))
    institutions_pct = max(0.0, min(100.0, institutions * 100))
    public_pct = max(0.0, 100.0 - insiders_pct - institutions_pct)

    pie_df = pd.DataFrame({
        "Holder": ["Promoters / Insiders", "Institutions", "Public / Others"],
        "Percent": [insiders_pct, institutions_pct, public_pct],
    })
    fig = go.Figure(go.Pie(
        labels=pie_df["Holder"],
        values=pie_df["Percent"],
        hole=0.55,
        marker=dict(colors=["#00d4aa", "#3d7ebf", "#f0ad4e"]),
        textinfo="label+percent",
    ))
    fig.update_layout(
        paper_bgcolor="#0d1117",
        plot_bgcolor="#0d1117",
        font=dict(color="#8b949e", size=11),
        height=330,
        margin=dict(l=8, r=8, t=28, b=8),
        title=dict(text="Shareholding Pattern", font=dict(size=13, color="#e6edf3"), x=0),
        legend=dict(orientation="h", y=-0.05),
    )

    c1, c2 = st.columns([1.1, 1])
    with c1:
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.markdown(
            '<div class="section-header"><span class="section-title">Top Holder Snapshot</span></div>',
            unsafe_allow_html=True,
        )
        _render_perf_table([
            ("Promoters / Insiders", f"{insiders_pct:.2f}%"),
            ("Institutions", f"{institutions_pct:.2f}%"),
            ("Public / Others", f"{public_pct:.2f}%"),
            ("Float Shares", fmt_large(info.get("floatShares")) if info.get("floatShares") else "N/A"),
            ("Shares Outstanding", fmt_large(info.get("sharesOutstanding")) if info.get("sharesOutstanding") else "N/A"),
        ])


def _fmt_qtr_val(val, is_inr: bool = True) -> str:
    """Format a quarterly financial value into Crores string."""
    cr = _to_crore(val)
    if cr is None:
        return "—"
    sign = "+" if cr > 0 else ""
    if abs(cr) >= 1_00_000:
        return f"{sign}₹{cr/1_00_000:.2f}L Cr"
    if abs(cr) >= 1_000:
        return f"{sign}₹{cr/1_000:.2f}K Cr"
    return f"{sign}₹{cr:.0f} Cr"


def _income_rows_display():
    return [
        ("Total Revenue",      "Total Revenue", "Operating Revenue"),
        ("Gross Profit",       "Gross Profit",),
        ("Operating Income",   "Operating Income", "EBIT"),
        ("EBITDA",             "EBITDA", "Normalized EBITDA"),
        ("Net Income",         "Net Income", "Net Income Common Stockholders"),
        ("EPS (Diluted, ₹)",   "Diluted EPS"),
        ("EPS (Basic, ₹)",     "Basic EPS"),
        ("Tax Provision",      "Tax Provision"),
    ]


def _render_income_table(income: pd.DataFrame):
    qtrs = income.columns[:8]
    qtr_labels = [q.strftime("%b '%y") for q in qtrs]

    st.markdown(
        '<div class="section-header"><span class="section-title">Quarterly Income Statement</span>'
        '<span class="section-badge" style="font-size:0.72rem;color:#8b949e;">Figures in ₹ Crores</span></div>',
        unsafe_allow_html=True,
    )

    display_rows = _income_rows_display()
    table_data = []

    for entry in display_rows:
        label = entry[0]
        keys  = entry[1:]
        row   = _get_row(income, *keys)
        if row is None:
            continue
        is_eps = "EPS" in label
        vals = []
        for q in qtrs:
            raw = row.get(q)
            if is_eps:
                vals.append(_fmt_ratio(raw, 2, prefix="₹"))
            else:
                vals.append(_fmt_qtr_val(raw))
        table_data.append([label] + vals)

    if table_data:
        df_disp = pd.DataFrame(table_data, columns=["Metric"] + qtr_labels)
        st.dataframe(
            df_disp.set_index("Metric"),
            use_container_width=True,
        )


def _render_balance_table(balance: pd.DataFrame):
    qtrs = balance.columns[:4]
    qtr_labels = [q.strftime("%b '%y") for q in qtrs]

    st.markdown(
        '<div class="section-header"><span class="section-title">Balance Sheet</span>'
        '<span class="section-badge" style="font-size:0.72rem;color:#8b949e;">Figures in ₹ Crores</span></div>',
        unsafe_allow_html=True,
    )

    display_rows = [
        ("Total Assets",            "Total Assets"),
        ("Total Liabilities",       "Total Liabilities Net Minority Interest"),
        ("Stockholders' Equity",    "Stockholders Equity", "Common Stock Equity",
         "Total Equity Gross Minority Interest"),
        ("Total Debt",              "Total Debt"),
        ("Net Debt",                "Net Debt"),
        ("Working Capital",         "Working Capital"),
        ("Cash & Equivalents",      "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"),
    ]

    table_data = []
    for entry in display_rows:
        label = entry[0]
        keys  = entry[1:]
        row   = _get_row(balance, *keys)
        if row is None:
            continue
        vals = [_fmt_qtr_val(row.get(q)) for q in qtrs]
        table_data.append([label] + vals)

    if table_data:
        df_disp = pd.DataFrame(table_data, columns=["Metric"] + qtr_labels)
        st.dataframe(df_disp.set_index("Metric"), use_container_width=True)


def _render_cashflow_table(cashflow: pd.DataFrame):
    qtrs = cashflow.columns[:4]
    qtr_labels = [q.strftime("%b '%y") for q in qtrs]

    st.markdown(
        '<div class="section-header"><span class="section-title">Cash Flow Statement</span>'
        '<span class="section-badge" style="font-size:0.72rem;color:#8b949e;">Figures in ₹ Crores</span></div>',
        unsafe_allow_html=True,
    )

    display_rows = [
        ("Operating Cash Flow",     "Operating Cash Flow", "Cash Flow From Continuing Operating Activities"),
        ("Investing Cash Flow",     "Investing Cash Flow", "Cash Flow From Continuing Investing Activities"),
        ("Financing Cash Flow",     "Financing Cash Flow", "Cash Flow From Continuing Financing Activities"),
        ("Free Cash Flow",          "Free Cash Flow"),
        ("Capital Expenditure",     "Capital Expenditure"),
    ]

    table_data = []
    for entry in display_rows:
        label = entry[0]
        keys  = entry[1:]
        row   = _get_row(cashflow, *keys)
        if row is None:
            continue
        vals = [_fmt_qtr_val(row.get(q)) for q in qtrs]
        table_data.append([label] + vals)

    if table_data:
        df_disp = pd.DataFrame(table_data, columns=["Metric"] + qtr_labels)
        st.dataframe(df_disp.set_index("Metric"), use_container_width=True)


# ─── Tab 5: Peers ────────────────────────────────────────────────────────────

def _render_peers_tab(symbol: str, info: dict):
    sector = info.get("sector", "")
    peers_all = SECTOR_PEERS.get(sector, [])
    if symbol == "PCJEWELLER.NS":
        peers_all = ["TITAN.NS", "KALYANKJIL.NS", "THANGAMAYL.NS", "PCJEWELLER.NS"]
    # Exclude current stock
    peers = [p for p in peers_all if p != symbol][:6]

    if not peers:
        # Try to find by name match
        sym_clean = clean_symbol(symbol)
        for sec, syms in SECTOR_PEERS.items():
            if any(s.startswith(sym_clean) for s in syms):
                peers = [p for p in syms if p != symbol][:6]
                break

    if not peers:
        st.info(f"Sector peer data not available for sector: '{sector or 'Unknown'}'.\n\n"
                f"Try searching for related stocks in the sidebar.")
        return

    st.markdown(
        '<div class="section-header">'
        f'<span class="section-title">Peer Comparison — {sector}</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    # Fetch data for current stock + peers
    all_syms = [symbol] + peers
    with st.spinner("Loading peer data…"):
        peer_data = []
        for sym in all_syms:
            try:
                pinfo = get_stock_info(sym)
                if not pinfo:
                    continue
                price   = _safe_float(pinfo.get("currentPrice") or pinfo.get("regularMarketPrice"))
                pc      = _safe_float(pinfo.get("previousClose") or pinfo.get("regularMarketPreviousClose"))
                chg_pct = ((price - pc) / pc * 100) if pc else 0.0
                mcap    = pinfo.get("marketCap")
                pe      = _safe_float(pinfo.get("trailingPE"))
                pb      = _safe_float(pinfo.get("priceToBook"))
                roe     = pinfo.get("returnOnEquity")
                roe_pct = round(roe * 100, 2) if roe else None
                roce    = pinfo.get("returnOnCapitalEmployed") or pinfo.get("returnOnAssets")
                roce_pct = round(roce * 100, 2) if roce else None
                d_e     = _safe_float(pinfo.get("debtToEquity"))
                div_y   = pinfo.get("dividendYield")
                div_pct = round(div_y * 100, 2) if div_y else 0.0
                sales_growth = pinfo.get("revenueGrowth")
                profit_growth = pinfo.get("earningsGrowth")
                op_margin = pinfo.get("operatingMargins")
                wk52h   = _safe_float(pinfo.get("fiftyTwoWeekHigh"))
                wk52l   = _safe_float(pinfo.get("fiftyTwoWeekLow"))
                wk52chg = ((price - wk52l) / wk52l * 100) if wk52l else 0.0
                pname   = pinfo.get("shortName") or pinfo.get("longName") or clean_symbol(sym)

                peer_data.append({
                    "Symbol": clean_symbol(sym),
                    "Company": pname[:22],
                    "CMP (₹)": round(price, 2),
                    "Day %": round(chg_pct, 2),
                    "Mkt Cap (Cr)": round(_to_crore(mcap), 0) if mcap and _to_crore(mcap) else 0,
                    "P/E": round(pe, 1) if pe else None,
                    "P/B": round(pb, 2) if pb else None,
                    "Sales Growth %": round(sales_growth * 100, 2) if sales_growth else None,
                    "Profit Growth %": round(profit_growth * 100, 2) if profit_growth else None,
                    "ROCE %": roce_pct,
                    "Margins %": round(op_margin * 100, 2) if op_margin else None,
                    "ROE %": roe_pct,
                    "D/E": round(d_e, 2) if d_e else None,
                    "Div Yield %": div_pct,
                    "52W Gain %": round(wk52chg, 2),
                    "is_current": sym == symbol,
                })
            except Exception:
                continue

    if not peer_data:
        st.warning("Could not load peer data.")
        return

    df_peers = pd.DataFrame(peer_data)
    is_current = df_peers.pop("is_current")

    tcol, scol, ecol = st.columns([2.5, 1.6, 1.2])
    with tcol:
        peer_filter = st.text_input(
            "Filter peers",
            placeholder="Company or symbol",
            key=f"peer_filter_{symbol}",
            label_visibility="collapsed",
        )
    with scol:
        sort_col = st.selectbox(
            "Sort by",
            [col for col in df_peers.columns if col not in ("Company",)],
            index=0,
            key=f"peer_sort_{symbol}",
            label_visibility="collapsed",
        )
    with ecol:
        st.download_button(
            "CSV",
            df_peers.to_csv(index=False).encode("utf-8"),
            file_name=f"{clean_symbol(symbol)}_peers.csv",
            mime="text/csv",
            use_container_width=True,
            key=f"peer_export_{symbol}",
        )

    if peer_filter:
        needle = peer_filter.lower()
        df_peers = df_peers[
            df_peers["Symbol"].str.lower().str.contains(needle)
            | df_peers["Company"].str.lower().str.contains(needle)
        ]
    if sort_col in df_peers.columns:
        df_peers = df_peers.sort_values(sort_col, ascending=False, na_position="last")

    # ── Styled peer table ────────────────────────────────────────────────────
    def _color_day(val):
        try:
            v = float(val)
            c = "#00d4aa" if v >= 0 else "#ff4444"
            return f"color: {c}; font-weight: 600;"
        except Exception:
            return ""

    def _highlight_current(row):
        if row.get("Symbol") == clean_symbol(symbol):
            return ["background-color: #1c2d3a; font-weight: 700;"] * len(row)
        return [""] * len(row)

    styled = (
        df_peers.style
        .apply(_highlight_current, axis=1)
        .map(_color_day, subset=["Day %", "52W Gain %"])
        .format({
            "CMP (₹)":     "{:,.2f}",
            "Day %":       "{:+.2f}%",
            "Mkt Cap (Cr)": "{:,.0f}",
            "P/E":         lambda x: f"{x:.1f}" if x else "N/A",
            "P/B":         lambda x: f"{x:.2f}" if x else "N/A",
            "Sales Growth %": lambda x: f"{x:.1f}%" if x else "N/A",
            "Profit Growth %": lambda x: f"{x:.1f}%" if x else "N/A",
            "ROCE %":      lambda x: f"{x:.1f}%" if x else "N/A",
            "Margins %":   lambda x: f"{x:.1f}%" if x else "N/A",
            "ROE %":       lambda x: f"{x:.1f}%" if x else "N/A",
            "D/E":         lambda x: f"{x:.2f}" if x else "N/A",
            "Div Yield %": "{:.2f}%",
            "52W Gain %":  "{:+.1f}%",
        }, na_rep="N/A")
        .set_properties(**{
            "background-color": "#0d1117",
            "color": "#e6edf3",
            "border": "1px solid #21262d",
            "font-size": "0.82rem",
        })
    )
    st.dataframe(styled, use_container_width=True, height=280)

    # ── P/E Comparison chart ─────────────────────────────────────────────────
    df_chart = df_peers[df_peers["P/E"].notna()].copy()
    if not df_chart.empty:
        bar_colors = [
            "#00d4aa" if df_chart.iloc[i]["Symbol"] == clean_symbol(symbol) else "#3d7ebf"
            for i in range(len(df_chart))
        ]
        fig_pe = go.Figure(go.Bar(
            x=df_chart["Symbol"],
            y=df_chart["P/E"],
            marker_color=bar_colors,
            text=[f"{v:.1f}" for v in df_chart["P/E"]],
            textposition="outside",
            textfont=dict(size=10, color="#8b949e"),
        ))
        fig_pe.update_layout(
            paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
            font=dict(color="#8b949e", size=10),
            height=220, margin=dict(l=8, r=8, t=36, b=8),
            title=dict(text="P/E Ratio Comparison", font=dict(size=12, color="#e6edf3"), x=0),
            xaxis=dict(showgrid=False, color="#8b949e"),
            yaxis=dict(gridcolor="#21262d", color="#8b949e", title="P/E Ratio"),
        )
        st.plotly_chart(fig_pe, use_container_width=True)

    # ── Market Cap comparison ────────────────────────────────────────────────
    df_mc = df_peers[df_peers["Mkt Cap (Cr)"] > 0].copy()
    if not df_mc.empty:
        mc_colors = [
            "#00d4aa" if df_mc.iloc[i]["Symbol"] == clean_symbol(symbol) else "#7c57ff"
            for i in range(len(df_mc))
        ]
        fig_mc = go.Figure(go.Bar(
            x=df_mc["Symbol"],
            y=df_mc["Mkt Cap (Cr)"],
            marker_color=mc_colors,
            text=[f"₹{v/1000:.1f}K Cr" if v >= 1000 else f"₹{v:.0f} Cr"
                  for v in df_mc["Mkt Cap (Cr)"]],
            textposition="outside",
            textfont=dict(size=9, color="#8b949e"),
        ))
        fig_mc.update_layout(
            paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
            font=dict(color="#8b949e", size=10),
            height=220, margin=dict(l=8, r=8, t=36, b=8),
            title=dict(text="Market Capitalisation (₹ Crores)", font=dict(size=12, color="#e6edf3"), x=0),
            xaxis=dict(showgrid=False, color="#8b949e"),
            yaxis=dict(gridcolor="#21262d", color="#8b949e", title="₹ Crores"),
        )
        st.plotly_chart(fig_mc, use_container_width=True)


# ─── Tab 6: Related News ─────────────────────────────────────────────────────

def _render_news_tab(symbol: str, company_name: str):
    sym_clean = clean_symbol(symbol)
    articles = fetch_stock_related_news(symbol, max_items=10)

    if len(articles) < 3:
        company_kw = company_name.split()[0].lower() if company_name else sym_clean.lower()
        all_news = fetch_all_headlines(30)
        for item in all_news:
            text = (item["title"] + " " + item.get("summary", "")).lower()
            if company_kw in text and item not in articles:
                articles.append(item)
            if len(articles) >= 10:
                break

    if not articles:
        st.info(f"No recent news found for {sym_clean}.")
        return

    st.markdown(
        f'<div class="section-header">'
        f'<span class="section-title">Recent News</span>'
        f'<span class="section-badge">{len(articles)} articles</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    for item in articles:
        title   = item.get("title", "").strip()
        source  = item.get("source", "")
        pub     = item.get("published", "")
        link    = item.get("link", "#")
        summary = item.get("summary", "").strip()
        if len(summary) > 200:
            summary = summary[:200] + "…"

        st.markdown(f"""
        <div class="news-item-card">
          <div class="news-item-meta">{source}{' · ' + pub[:16] if pub else ''}</div>
          <a href="{link}" target="_blank" class="news-item-title">{title}</a>
          {f'<div class="news-item-summary">{summary}</div>' if summary else ''}
        </div>
        """, unsafe_allow_html=True)


# ─── Shared rendering helpers ─────────────────────────────────────────────────

def _render_notes_tab(symbol: str, company_name: str):
    notes_store = st.session_state.setdefault("stock_notes", {})
    current = notes_store.setdefault(symbol, {
        "notes": "",
        "tags": "",
        "trade_idea": "",
        "bookmarked": False,
    })

    st.markdown(
        f'<div class="section-header"><span class="section-title">Notebook - {company_name}</span></div>',
        unsafe_allow_html=True,
    )
    bookmarked = st.checkbox(
        "Bookmark stock",
        value=bool(current.get("bookmarked")),
        key=f"note_bookmark_{symbol}",
    )
    tags = st.text_input(
        "Tags",
        value=current.get("tags", ""),
        placeholder="breakout, long-term, watch earnings",
        key=f"note_tags_{symbol}",
    )
    trade_idea = st.text_area(
        "Trade idea",
        value=current.get("trade_idea", ""),
        placeholder="Entry, invalidation, target, catalyst",
        key=f"note_trade_{symbol}",
        height=120,
    )
    notes = st.text_area(
        "Observations",
        value=current.get("notes", ""),
        placeholder="Write observations from chart, peers, fundamentals, or news.",
        key=f"note_body_{symbol}",
        height=180,
    )
    if st.button("Save notes", key=f"note_save_{symbol}", use_container_width=True):
        notes_store[symbol] = {
            "notes": notes,
            "tags": tags,
            "trade_idea": trade_idea,
            "bookmarked": bookmarked,
        }
        st.success("Notes saved for this session.")


def _render_perf_table(rows):
    html = '<div class="perf-table">' + "".join(
        f'<div class="perf-row">'
        f'<span class="perf-label">{lbl}</span>'
        f'<span class="perf-value">{val}</span>'
        f'</div>'
        for lbl, val in rows
    ) + '</div>'
    st.markdown(html, unsafe_allow_html=True)
