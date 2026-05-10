"""
Bhandari Trading Analysis Dashboard
Entry point — run with:  python -m streamlit run main.py
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path regardless of launch directory
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

# ── Page config (must be first Streamlit call) ──────────────────────────────
st.set_page_config(
    page_title="Bhandari Trading Analysis",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": "Bhandari Trading Analysis Dashboard v1.0",
    },
)

# ── Inject custom CSS ────────────────────────────────────────────────────────
def _load_css():
    css_path = Path(__file__).parent / "assets" / "style.css"
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

_load_css()

# ── App header ───────────────────────────────────────────────────────────────
st.markdown(
    """
    <div class="app-header">
        <div class="app-title">
            <span>Bhandari</span> Trading Analysis
        </div>
        <div class="app-sub">
            <span class="live-dot"></span>Professional Market Intelligence Dashboard
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Ticker bar (top of every page) ───────────────────────────────────────────
try:
    from components.ticker_bar import render_ticker_bar
    render_ticker_bar()
except Exception as _e:
    st.caption(f"Ticker unavailable: {_e}")

# ── Diplomatic / market news banner ─────────────────────────────────────────
try:
    from components.news_banner import render_news_banner
    render_news_banner()
except Exception as _e:
    pass

# ── Navigation ───────────────────────────────────────────────────────────────
if "page" not in st.session_state:
    st.session_state.page = "Home"

PAGES = {
    "Home": "🏠 Home",
    "Nifty100": "📊 Nifty 100",
    "Momentum": "🚀 Momentum Scanner",
}

nav_cols = st.columns(len(PAGES))
for col, (key, label) in zip(nav_cols, PAGES.items()):
    active = "active" if st.session_state.page == key else ""
    # Use regular button; CSS handles active styling via session state
    if col.button(label, key=f"nav_{key}", use_container_width=True):
        st.session_state.page = key
        st.rerun()

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

except Exception as _page_err:
    import traceback
    st.error(f"Page error: {_page_err}")
    st.code(traceback.format_exc())
