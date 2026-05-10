"""
Bhandari Trading Analysis Dashboard
Entry point — run with:  python -m streamlit run main.py
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

# ── Page config (must be first Streamlit call) ───────────────────────────────
st.set_page_config(
    page_title="Bhandari Trading Analysis",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": "Bhandari Trading Analysis Dashboard v2.0",
    },
)

# ── CSS ──────────────────────────────────────────────────────────────────────
def _load_css():
    css_path = Path(__file__).parent / "assets" / "style.css"
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

_load_css()

# ── Auto-refresh: reruns without resetting session_state ─────────────────────
try:
    from streamlit_autorefresh import st_autorefresh
    _refresh_ms = st.session_state.get("refresh_interval", 60) * 1000
    st_autorefresh(interval=_refresh_ms, limit=None, key="dashboard_autorefresh")
except ImportError:
    pass  # Graceful fallback if package not yet installed

# ── Session state defaults ───────────────────────────────────────────────────
if "page" not in st.session_state:
    st.session_state.page = "Home"
if "selected_stock" not in st.session_state:
    st.session_state.selected_stock = None
if "search_counter" not in st.session_state:
    st.session_state.search_counter = 0
if "refresh_interval" not in st.session_state:
    st.session_state.refresh_interval = 60

# ── Market status ────────────────────────────────────────────────────────────
def _get_market_status() -> dict:
    import pytz
    from datetime import datetime

    now_utc = datetime.now(pytz.utc)

    def _is_open(tz_name: str, open_h: int, open_m: int, close_h: int, close_m: int) -> bool:
        tz = pytz.timezone(tz_name)
        local = now_utc.astimezone(tz)
        if local.weekday() >= 5:
            return False
        t = local.hour * 60 + local.minute
        return (open_h * 60 + open_m) <= t < (close_h * 60 + close_m)

    def _local_time(tz_name: str) -> str:
        tz = pytz.timezone(tz_name)
        return now_utc.astimezone(tz).strftime("%H:%M")

    return {
        "India": {
            "label": "🇮🇳 NSE/BSE",
            "open": _is_open("Asia/Kolkata", 9, 15, 15, 30),
            "hours": "09:15–15:30",
            "tz": "IST",
            "time": _local_time("Asia/Kolkata"),
        },
        "UK": {
            "label": "🇬🇧 LSE",
            "open": _is_open("Europe/London", 8, 0, 16, 30),
            "hours": "08:00–16:30",
            "tz": "GMT/BST",
            "time": _local_time("Europe/London"),
        },
        "USA": {
            "label": "🇺🇸 NYSE",
            "open": _is_open("America/New_York", 9, 30, 16, 0),
            "hours": "09:30–16:00",
            "tz": "ET",
            "time": _local_time("America/New_York"),
        },
        "Germany": {
            "label": "🇩🇪 Xetra",
            "open": _is_open("Europe/Berlin", 9, 0, 17, 30),
            "hours": "09:00–17:30",
            "tz": "CET/CEST",
            "time": _local_time("Europe/Berlin"),
        },
    }

markets = _get_market_status()
india_open = markets["India"]["open"]

# ── Watchlist sidebar ────────────────────────────────────────────────────────
try:
    from components.watchlist_sidebar import render_watchlist_sidebar
    render_watchlist_sidebar()
except Exception as _e:
    st.sidebar.warning(f"Watchlist unavailable: {_e}")

# ── Header ───────────────────────────────────────────────────────────────────
dot_color  = "#00d4aa" if india_open else "#4d9de0"
dot_shadow = f"0 0 8px {dot_color}"
status_txt = "LIVE" if india_open else "OFFLINE"

chips_html = ""
for mdata in markets.values():
    clr    = "#00d4aa" if mdata["open"] else "#8b949e"
    status = "OPEN" if mdata["open"] else "CLOSED"
    chips_html += f"""
    <div class="market-chip">
        <span class="market-chip-dot" style="background:{clr};box-shadow:0 0 5px {clr if mdata['open'] else 'transparent'};"></span>
        <div class="market-chip-body">
            <span class="market-chip-label">{mdata['label']}</span>
            <span class="market-chip-time">{mdata['time']} <span class="market-chip-tz">{mdata['tz']}</span></span>
            <span class="market-chip-status" style="color:{clr};">{status}</span>
        </div>
    </div>"""

st.markdown(f"""
<div class="app-header-v2">
    <div class="app-header-left">
        <div class="app-title-v2">
            <span class="brand-accent">Bhandari</span> Trading Analysis
        </div>
        <div class="app-sub-v2">
            <span class="live-dot-v2" style="background:{dot_color};box-shadow:{dot_shadow};"></span>
            <span style="color:{dot_color};font-weight:700;font-size:0.72rem;letter-spacing:0.06em;">{status_txt}</span>
            <span style="color:#30363d;">|</span>
            Professional Market Intelligence Dashboard
        </div>
    </div>
    <div class="market-hours-row">{chips_html}</div>
</div>
""", unsafe_allow_html=True)

# ── Ticker bar ───────────────────────────────────────────────────────────────
try:
    from components.ticker_bar import render_ticker_bar
    render_ticker_bar()
except Exception as _e:
    st.caption(f"Ticker unavailable: {_e}")

# ── News banner ──────────────────────────────────────────────────────────────
try:
    from components.news_banner import render_news_banner
    render_news_banner()
except Exception:
    pass

# ── Global search + navigation row ──────────────────────────────────────────
from data.stocks_list import SYMBOL_NAMES

_all_search_opts = {
    f"{sym.replace('.NS','').replace('.BO','')} — {name}": sym
    for sym, name in sorted(SYMBOL_NAMES.items(), key=lambda x: x[0])
}

_REFRESH_OPTIONS = {"10 sec": 10, "30 sec": 30, "1 min": 60, "5 min": 300, "10 min": 600}

search_col, nav_col, refresh_col = st.columns([1.6, 2.0, 0.65])

with search_col:
    chosen = st.selectbox(
        "search",
        [""] + list(_all_search_opts.keys()),
        index=0,
        key=f"global_search_{st.session_state.search_counter}",
        label_visibility="collapsed",
        placeholder="🔍  Search stock name or symbol…",
    )
    if chosen:
        st.session_state.selected_stock = _all_search_opts[chosen]
        st.session_state.page = "StockDetail"
        st.session_state.search_counter += 1
        st.rerun()

PAGES = {"Home": "🏠 Home", "Nifty100": "📊 Nifty 100", "Momentum": "🚀 Momentum Scanner"}
with nav_col:
    nav_cols = st.columns(len(PAGES))
    for col, (key, label) in zip(nav_cols, PAGES.items()):
        if col.button(label, key=f"nav_{key}", use_container_width=True):
            st.session_state.page = key
            st.rerun()

with refresh_col:
    _current_label = next(
        (k for k, v in _REFRESH_OPTIONS.items() if v == st.session_state.refresh_interval),
        "1 min",
    )
    _sel = st.selectbox(
        "⟳ Refresh",
        list(_REFRESH_OPTIONS.keys()),
        index=list(_REFRESH_OPTIONS.keys()).index(_current_label),
        key="refresh_selector",
    )
    st.session_state.refresh_interval = _REFRESH_OPTIONS[_sel]

st.markdown("---")

# ── Page routing ─────────────────────────────────────────────────────────────
page = st.session_state.page

try:
    if page == "Home":
        from pages.home import render_home
        render_home()

    elif page == "Nifty100":
        from pages.nifty100 import render_nifty100
        render_nifty100()

    elif page == "Momentum":
        from pages.momentum_scanner import render_momentum_scanner
        render_momentum_scanner()

    elif page == "StockDetail":
        from pages.stock_detail import render_stock_detail
        symbol = st.session_state.get("selected_stock")
        if symbol:
            render_stock_detail(symbol)
        else:
            st.session_state.page = "Home"
            st.rerun()

except Exception as _page_err:
    import traceback
    st.error(f"Page error: {_page_err}")
    st.code(traceback.format_exc())
