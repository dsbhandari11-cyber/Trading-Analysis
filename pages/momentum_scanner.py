"""
Momentum Scanner page.
Scans NSE stocks for breakouts, reversals, and momentum signals.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
import streamlit as st
import pandas as pd
from data.fetcher import batch_download
from data.technical import (
    calculate_rsi, calculate_volume_ratio, price_change_pct,
    is_price_breakout, is_volume_spike, momentum_score
)
from data.stocks_list import NIFTY100_SYMBOLS, get_display_name
from data.news import fetch_stock_related_news
from components.charts import momentum_bar_chart
from config import (
    REFRESH_INTERVAL, COLORS, RSI_OVERBOUGHT, RSI_OVERSOLD,
    VOLUME_MOMENTUM_MULTIPLIER
)
from utils.helpers import ist_now
from utils.logger import get_logger

log = get_logger(__name__)


def render_momentum_scanner():
    st.markdown(
        f'<meta http-equiv="refresh" content="{REFRESH_INTERVAL}">',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="section-header"><span class="section-title">Momentum Scanner</span>'
        '<span class="section-badge">SCANNING</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="refresh-info"><span class="live-dot"></span> Scanned at {ist_now()} · '
        f'Refreshes every {REFRESH_INTERVAL}s</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;
                    padding:10px 16px;margin-bottom:12px;font-size:0.82rem;color:#8b949e;">
            <b style="color:#e6edf3;">Signal Criteria:</b>
            &nbsp; 🟢 Breakout: Vol &gt; {VOLUME_MOMENTUM_MULTIPLIER}x avg + RSI &gt; {RSI_OVERBOUGHT} + price breakout
            &nbsp;|&nbsp; 🔴 Reversal: RSI &lt; {RSI_OVERSOLD}
            &nbsp;|&nbsp; ⚡ Momentum: Vol spike + positive price trend
        </div>
        """,
        unsafe_allow_html=True,
    )

    results = _run_scan()

    if not results["breakouts"] and not results["reversals"] and not results["momentum"]:
        st.warning("No signals found in current scan. Market may be consolidating. Try again after market hours warm up.")
        return

    tab1, tab2, tab3, tab4 = st.tabs([
        f"🟢 Breakouts ({len(results['breakouts'])})",
        f"🔴 Reversals ({len(results['reversals'])})",
        f"⚡ Momentum ({len(results['momentum'])})",
        "📊 Rankings",
    ])

    with tab1:
        _render_signal_cards(results["breakouts"], "breakout")

    with tab2:
        _render_signal_cards(results["reversals"], "reversal")

    with tab3:
        _render_signal_cards(results["momentum"], "momentum")

    with tab4:
        _render_rankings(results)


@st.cache_data(ttl=90, show_spinner=False)
def _run_scan() -> dict:
    symbols = NIFTY100_SYMBOLS
    breakouts = []
    reversals = []
    momentum_signals = []

    with st.spinner("Scanning Nifty 100 for momentum signals…"):
        hist_data = batch_download(symbols, period="2mo")

    total = len(symbols)
    prog = st.progress(0, text="Analysing signals…")

    for idx, sym in enumerate(symbols):
        try:
            df = hist_data.get(sym)
            if df is None or df.empty or len(df) < 20:
                continue
            if "Close" not in df.columns or "Volume" not in df.columns:
                continue

            rsi_s = calculate_rsi(df)
            rsi = float(rsi_s.iloc[-1]) if len(rsi_s) > 0 and not pd.isna(rsi_s.iloc[-1]) else None

            vol_s = calculate_volume_ratio(df, period=10)
            vol_ratio = float(vol_s.iloc[-1]) if len(vol_s) > 0 and not pd.isna(vol_s.iloc[-1]) else None

            chg1d = price_change_pct(df, days=1)
            chg5d = price_change_pct(df, days=5)
            price = float(df["Close"].iloc[-1])
            score = momentum_score(rsi or 50.0, vol_ratio or 1.0, chg5d)

            breakout = is_price_breakout(df) and is_volume_spike(df, VOLUME_MOMENTUM_MULTIPLIER, 10)
            volume_spike = (vol_ratio is not None and vol_ratio >= VOLUME_MOMENTUM_MULTIPLIER)
            reversal_cond = (rsi is not None and rsi < RSI_OVERSOLD)
            overbought = (rsi is not None and rsi > RSI_OVERBOUGHT)

            base = {
                "symbol": sym,
                "name": get_display_name(sym),
                "price": price,
                "rsi": rsi,
                "vol_ratio": vol_ratio,
                "chg1d": chg1d,
                "chg5d": chg5d,
                "momentum_score": score,
            }

            if breakout or (volume_spike and overbought):
                breakouts.append({**base, "signal": "BREAKOUT"})

            if reversal_cond:
                reversals.append({**base, "signal": "REVERSAL WATCH"})

            if volume_spike and chg1d > 0 and not overbought and not reversal_cond:
                momentum_signals.append({**base, "signal": "MOMENTUM"})

        except Exception as e:
            log.debug("Scan error %s: %s", sym, e)
        finally:
            prog.progress(int(100 * (idx + 1) / total), text=f"Scanning {sym}…")
        time.sleep(0.02)

    prog.empty()

    breakouts.sort(key=lambda x: x["momentum_score"], reverse=True)
    reversals.sort(key=lambda x: x.get("rsi", 100))
    momentum_signals.sort(key=lambda x: x.get("vol_ratio", 0), reverse=True)

    return {"breakouts": breakouts, "reversals": reversals, "momentum": momentum_signals}


def _render_signal_cards(signals: list, signal_type: str):
    if not signals:
        st.info(f"No {signal_type} signals detected in current scan.")
        return

    type_class = {
        "breakout": ("signal-bull", "badge-breakout", "🟢 BREAKOUT"),
        "reversal": ("signal-bear", "badge-reversal", "🔴 REVERSAL WATCH"),
        "momentum": ("signal-bull", "badge-breakout", "⚡ MOMENTUM"),
    }.get(signal_type, ("signal-neutral", "", "SIGNAL"))

    card_class, badge_class, badge_text = type_class

    cols = st.columns(2)
    for i, sig in enumerate(signals[:20]):
        rsi_str = f"{sig['rsi']:.1f}" if sig.get("rsi") else "N/A"
        vol_str = f"{sig['vol_ratio']:.2f}x" if sig.get("vol_ratio") else "N/A"
        chg1d = sig.get("chg1d", 0)
        chg_color = COLORS["positive"] if chg1d >= 0 else COLORS["negative"]
        chg_sign = "+" if chg1d >= 0 else ""

        card_html = f"""
        <div class="signal-card {card_class}">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                <span class="signal-ticker">{sig['symbol'].replace('.NS','')}</span>
                <span class="signal-badge {badge_class}">{badge_text}</span>
            </div>
            <div class="signal-price">{sig['name'][:28]}</div>
            <div style="display:flex;gap:16px;margin-top:8px;font-size:0.8rem;">
                <div><span style="color:#8b949e;">Price </span>
                     <span style="color:#e6edf3;font-family:monospace;">₹{sig['price']:,.2f}</span></div>
                <div><span style="color:#8b949e;">RSI </span>
                     <span style="color:#e6edf3;">{rsi_str}</span></div>
                <div><span style="color:#8b949e;">Vol </span>
                     <span style="color:#e6edf3;">{vol_str}</span></div>
                <div><span style="color:#8b949e;">1D </span>
                     <span style="color:{chg_color};">{chg_sign}{chg1d:.2f}%</span></div>
            </div>
            <div style="margin-top:6px;">
                <span style="color:#8b949e;font-size:0.76rem;">Momentum Score: </span>
                <span style="color:#00d4aa;font-weight:700;font-size:0.85rem;">{sig['momentum_score']:.1f}</span>
            </div>
        </div>
        """
        with cols[i % 2]:
            st.markdown(card_html, unsafe_allow_html=True)

    if len(signals) > 20:
        st.caption(f"Showing top 20 of {len(signals)} signals.")


def _render_rankings(results: dict):
    all_signals = (
        results["breakouts"] + results["reversals"] + results["momentum"]
    )
    if not all_signals:
        st.info("No ranked data available.")
        return

    seen = set()
    unique = []
    for s in all_signals:
        if s["symbol"] not in seen:
            seen.add(s["symbol"])
            unique.append(s)

    fig = momentum_bar_chart(unique)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    st.markdown("---")
    st.markdown(
        '<div class="section-header"><span class="section-title">All Signals Table</span></div>',
        unsafe_allow_html=True,
    )

    rows = []
    for s in unique[:50]:
        rows.append({
            "Ticker": s["symbol"].replace(".NS", ""),
            "Company": s["name"][:22],
            "Signal": s.get("signal", ""),
            "Price": f"₹{s['price']:,.2f}",
            "RSI": f"{s['rsi']:.1f}" if s.get("rsi") else "N/A",
            "Vol Ratio": f"{s['vol_ratio']:.2f}x" if s.get("vol_ratio") else "N/A",
            "1D %": f"{'+' if s['chg1d'] >= 0 else ''}{s['chg1d']:.2f}%",
            "Score": f"{s['momentum_score']:.1f}",
        })

    if rows:
        df = pd.DataFrame(rows)

        def color_signal(val):
            if "BREAKOUT" in val or "MOMENTUM" in val:
                return f"color: {COLORS['positive']};font-weight:700"
            if "REVERSAL" in val:
                return f"color: {COLORS['warning']};font-weight:700"
            return ""

        def color_pct(val):
            try:
                v = float(val.replace("%", "").replace("+", ""))
                return f"color: {COLORS['positive']}" if v >= 0 else f"color: {COLORS['negative']}"
            except Exception:
                return ""

        styled = (
            df.style
            .map(color_signal, subset=["Signal"])
            .map(color_pct, subset=["1D %"])
            .set_properties(**{"font-size": "0.82rem"})
        )
        st.dataframe(styled, width="stretch", hide_index=True, height=400)

    st.markdown("---")
    st.markdown(
        '<div class="section-header"><span class="section-title">Related News</span></div>',
        unsafe_allow_html=True,
    )
    top_signals = unique[:5]
    for sig in top_signals:
        sym_clean = sig["symbol"].replace(".NS", "")
        news = fetch_stock_related_news(sym_clean, max_items=2)
        if news:
            st.markdown(
                f'<div style="color:{COLORS["text_muted"]};font-size:0.78rem;'
                f'margin:8px 0 3px 0;">{sym_clean} — Related Headlines</div>',
                unsafe_allow_html=True,
            )
            for item in news:
                st.markdown(
                    f'<div style="background:#161b22;border:1px solid #30363d;border-radius:6px;'
                    f'padding:8px 12px;margin:3px 0;font-size:0.82rem;">'
                    f'<a href="{item["link"]}" target="_blank" style="color:#e6edf3;'
                    f'text-decoration:none;">{item["title"]}</a></div>',
                    unsafe_allow_html=True,
                )
