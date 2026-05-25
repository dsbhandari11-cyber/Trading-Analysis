"""
Bhandari Trading Analysis Dashboard
Entry point — run with:  python -m streamlit run main.py
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── SSL patch — handles corporate proxies / Windows cert-store mismatches ────
import ssl
import os
import urllib3

try:
    # Use Windows cert store if python-certifi-win32 is installed
    import certifi_win32  # noqa: F401
except ImportError:
    # Fallback: disable SSL verification for local dev.
    # Safe for a local trading dashboard that only calls trusted public APIs.
    ssl._create_default_https_context = ssl._create_unverified_context  # type: ignore[attr-defined]
    os.environ.setdefault("PYTHONHTTPSVERIFY", "0")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
# Inject a minimal no-flicker override FIRST (before the full stylesheet loads)
# so there is zero chance of the dim overlay appearing even on first paint.
st.markdown("""<style>
.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"],.main,.main .block-container
{opacity:1!important;transition:none!important;}
[data-testid="stStatusWidget"]{display:none!important;}
.stSkeleton,[data-testid="stSkeleton"]{display:none!important;}
.element-container,.stMarkdown,.stColumns,.stHorizontalBlock
{transition:none!important;animation-duration:0s!important;}
[data-stale="true"],[data-stale="false"]{opacity:1!important;transition:none!important;}
</style>""", unsafe_allow_html=True)

def _load_css():
    css_path = Path(__file__).parent / "assets" / "style.css"
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

_load_css()

# ── Auto-refresh ──────────────────────────────────────────────────────────────
# The first call uses the user-configured interval.  After _get_market_status()
# runs (below), we write an adaptive interval back to session state so the
# *next* rerun automatically slows down when all markets are closed.
try:
    from streamlit_autorefresh import st_autorefresh as _st_autorefresh
    _refresh_ms = max(30, st.session_state.get("refresh_interval", 60)) * 1000
    _st_autorefresh(interval=_refresh_ms, limit=None, key="dashboard_autorefresh")
except ImportError:
    pass  # Graceful fallback if package not yet installed

# ── Pine Script DB — initialise once at startup (auto-loads saved scripts) ───
try:
    from components.pine_manager import get_pine_db as _init_pine_db
    _init_pine_db()          # seeds built-ins, scans disk, survives reboots
except Exception:
    pass

# ── Session state defaults ───────────────────────────────────────────────────
if "page" not in st.session_state:
    st.session_state.page = "Nifty100"
if "selected_stock" not in st.session_state:
    st.session_state.selected_stock = None
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

# Adaptive refresh — clamp to 30 s during live sessions, 120 s off-hours.
# Written to session state so the *next* autorefresh tick uses the right rate.
_any_market_open = any(m["open"] for m in markets.values())
_base_s = st.session_state.get("refresh_interval", 60)
st.session_state["_eff_refresh_s"] = max(30, _base_s) if _any_market_open else max(120, _base_s)

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
<div class="paytm-top-shell">
    <div class="paytm-brand">
        <div class="app-title-v2">
            <span class="brand-accent">Bhandari</span> Trading Analysis
        </div>
        <div class="app-sub-v2">
            <span class="live-dot-v2" style="background:{dot_color};box-shadow:{dot_shadow};"></span>
            <span style="color:{dot_color};font-weight:800;font-size:0.72rem;letter-spacing:0.06em;">{status_txt}</span>
            <span class="header-separator">|</span>
            Professional Market Intelligence Dashboard
        </div>
    </div>
    <div class="market-hours-row">{chips_html}</div>
</div>
""", unsafe_allow_html=True)

# ── Ticker bar — independent fragment: refreshes without a full page rerun ───
@st.fragment(run_every=30)
def _ticker_fragment():
    try:
        from components.ticker_bar import render_ticker_bar
        render_ticker_bar()
    except Exception as _e:
        st.caption(f"Ticker unavailable: {_e}")

_ticker_fragment()

# ── News banner — independent fragment ───────────────────────────────────────
@st.fragment(run_every=120)
def _news_fragment():
    try:
        from components.news_banner import render_news_banner
        render_news_banner()
    except Exception:
        pass

_news_fragment()

# ── Navigation ───────────────────────────────────────────────────────────────

NAV_ITEMS = [
    ("Market",    "Market",       "Nifty100"),
    ("Chart",     "Chart Studio", "ChartStudio"),
    ("Portfolio", "Portfolio",    None),
    ("Orders",    "Orders",       None),
    ("Funds",     "Funds",        None),
    ("Call Us",   "Call Us",      None),
    ("ID",        "ID",           None),
    ("More",      "More",         None),
]

st.markdown('<div class="top-nav-band">', unsafe_allow_html=True)
nav_cols = st.columns([1.05, 1.15, 1.15, 0.95, 0.85, 1.05, 0.6, 0.75])
current_page = st.session_state.get("page", "Nifty100")
for col, (key, label, target) in zip(nav_cols, NAV_ITEMS):
    active = (target == current_page
              or (key == "Chart" and current_page == "ChartStudio"))
    nav_label = f"{'▸ ' if active else ''}{label}"
    if col.button(nav_label, key=f"nav_{key}", use_container_width=True):
        if target and target != current_page:
            st.session_state.page = target
            st.session_state.selected_stock = None
            st.rerun()
        elif not target:
            st.toast(f"{label} — coming soon.")
st.markdown('</div>', unsafe_allow_html=True)

# ── Page routing ─────────────────────────────────────────────────────────────
page = st.session_state.page

try:
    if page == "Home":
        from pages.home import render_home
        render_home()

    elif page == "Nifty100":
        from pages.nifty100 import render_nifty100
        render_nifty100()

    elif page == "ChartStudio":
        from pages.chart_studio import render_chart_studio
        render_chart_studio()

    elif page == "StockDetail":
        from pages.stock_detail import render_stock_detail
        symbol = st.session_state.get("selected_stock")
        if symbol:
            render_stock_detail(symbol)
        else:
            st.session_state.page = "Nifty100"
            st.rerun()

except Exception as _page_err:
    import traceback
    st.error(f"Page error: {_page_err}")
    st.code(traceback.format_exc())
