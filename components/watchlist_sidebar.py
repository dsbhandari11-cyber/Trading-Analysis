"""
Watchlist sidebar - TradingView-style compact watchlist with settings panel.

Architecture:
  - CSS marker span -> sibling button styled via :has() selector
  - Dynamic CSS variables injected from session-state theme dict
  - Edit mode: columns [5,1] with card button + trash icon
  - Settings panel: expander with preset picker + fine-grain controls
"""

from __future__ import annotations

from typing import Dict

import streamlit as st

from data.stocks_list import SYMBOL_NAMES, get_display_name
from data.fetcher import get_price_change
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

# Each preset stores numeric values so sliders can read them back cleanly.
THEME_PRESETS: Dict[str, Dict] = {
    "Professional Black": {
        "card_bg": "#111111",
        "card_border": "#222222",
        "card_hover": "#1a1a1a",
        "card_active_bg": "#0d1f0d",
        "card_active_border": "#00d4aa",
        "accent": "#00d4aa",
        "bullish": "#00d4aa",
        "bearish": "#f43f5e",
        "text_primary": "#ffffff",
        "text_secondary": "#666666",
        "card_radius": "5px",
        "pad_v": 8,
        "pad_h": 11,
        "card_gap": 2,
        "glow": 0.10,
        "shadow": 0.20,
        "anim": 0.12,
    },
    "TradingView Dark": {
        "card_bg": "#1e222d",
        "card_border": "#2a2e39",
        "card_hover": "#2a2e39",
        "card_active_bg": "#132638",
        "card_active_border": "#2962ff",
        "accent": "#2962ff",
        "bullish": "#26a69a",
        "bearish": "#ef5350",
        "text_primary": "#d1d4dc",
        "text_secondary": "#787b86",
        "card_radius": "4px",
        "pad_v": 7,
        "pad_h": 10,
        "card_gap": 1,
        "glow": 0.0,
        "shadow": 0.0,
        "anim": 0.12,
    },
    "Bloomberg Terminal": {
        "card_bg": "#000000",
        "card_border": "#331100",
        "card_hover": "#111111",
        "card_active_bg": "#1a0a00",
        "card_active_border": "#ff6600",
        "accent": "#ff6600",
        "bullish": "#00cc44",
        "bearish": "#ff3333",
        "text_primary": "#ff6600",
        "text_secondary": "#884400",
        "card_radius": "0px",
        "pad_v": 7,
        "pad_h": 9,
        "card_gap": 1,
        "glow": 0.30,
        "shadow": 0.0,
        "anim": 0.05,
    },
    "Binance Dark": {
        "card_bg": "#1e2026",
        "card_border": "#2b2f36",
        "card_hover": "#2b2f36",
        "card_active_bg": "#1a1f2a",
        "card_active_border": "#f0b90b",
        "accent": "#f0b90b",
        "bullish": "#0ecb81",
        "bearish": "#f6465d",
        "text_primary": "#eaecef",
        "text_secondary": "#848e9c",
        "card_radius": "4px",
        "pad_v": 8,
        "pad_h": 10,
        "card_gap": 2,
        "glow": 0.0,
        "shadow": 0.10,
        "anim": 0.15,
    },
    "Institutional Blue": {
        "card_bg": "#0d1b2a",
        "card_border": "#1e3a5f",
        "card_hover": "#142339",
        "card_active_bg": "#0a2040",
        "card_active_border": "#4d9de0",
        "accent": "#4d9de0",
        "bullish": "#00d4aa",
        "bearish": "#f43f5e",
        "text_primary": "#e2e8f0",
        "text_secondary": "#64748b",
        "card_radius": "6px",
        "pad_v": 9,
        "pad_h": 11,
        "card_gap": 3,
        "glow": 0.15,
        "shadow": 0.10,
        "anim": 0.15,
    },
    "Cyberpunk Neon": {
        "card_bg": "#0d001a",
        "card_border": "#330066",
        "card_hover": "#15002b",
        "card_active_bg": "#1a0033",
        "card_active_border": "#00ffff",
        "accent": "#00ffff",
        "bullish": "#00ff9f",
        "bearish": "#ff2d55",
        "text_primary": "#e0e0ff",
        "text_secondary": "#7070aa",
        "card_radius": "4px",
        "pad_v": 8,
        "pad_h": 10,
        "card_gap": 2,
        "glow": 0.50,
        "shadow": 0.30,
        "anim": 0.10,
    },
    "Minimal Glass": {
        "card_bg": "rgba(255,255,255,0.03)",
        "card_border": "rgba(255,255,255,0.08)",
        "card_hover": "rgba(255,255,255,0.06)",
        "card_active_bg": "rgba(99,179,237,0.10)",
        "card_active_border": "#63b3ed",
        "accent": "#63b3ed",
        "bullish": "#48bb78",
        "bearish": "#fc8181",
        "text_primary": "#e2e8f0",
        "text_secondary": "#718096",
        "card_radius": "8px",
        "pad_v": 9,
        "pad_h": 12,
        "card_gap": 3,
        "glow": 0.20,
        "shadow": 0.15,
        "anim": 0.20,
    },
}

_DEFAULT_PRESET = "Professional Black"


def ensure_watchlist_state() -> None:
    defaults = {
        "watchlist": DEFAULT_WATCHLIST.copy(),
        "selected_stock": None,
        "stock_notes": {},
        "watchlist_edit_mode": False,
        "wl_theme": THEME_PRESETS[_DEFAULT_PRESET].copy(),
        "wl_preset_name": _DEFAULT_PRESET,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def all_stock_options() -> Dict[str, str]:
    options = dict(SYMBOL_NAMES)
    options.update(US_SYMBOL_NAMES)
    return dict(sorted(options.items(), key=lambda item: item[1].lower()))


def normalize_symbol(raw: str, exchange: str = "NSE") -> str:
    symbol = (raw or "").strip().upper().replace(" ", "")
    if not symbol:
        return ""
    if symbol.endswith((".NS", ".BO")):
        return symbol
    return f"{symbol}.NS" if exchange == "NSE" else symbol


def _select_stock(symbol: str) -> None:
    st.session_state.selected_stock = symbol
    st.session_state.page = "StockDetail"
    st.rerun()


def _add_stock(symbol: str) -> None:
    if symbol and symbol not in st.session_state.watchlist:
        st.session_state.watchlist.append(symbol)


def _remove_stock(symbol: str) -> None:
    st.session_state.watchlist = [s for s in st.session_state.watchlist if s != symbol]
    if st.session_state.get("selected_stock") == symbol:
        st.session_state.selected_stock = None
        st.session_state.page = "Home"


def _inject_wl_css() -> None:
    theme = st.session_state.wl_theme
    pad_v = int(theme.get("pad_v", 8))
    pad_h = int(theme.get("pad_h", 11))
    gap = int(theme.get("card_gap", 2))
    glow = float(theme.get("glow", 0.0))
    shadow = float(theme.get("shadow", 0.1))
    speed = float(theme.get("anim", 0.15))
    accent = theme["accent"]
    radius = theme.get("card_radius", "5px")

    try:
        raw = accent.lstrip("#")
        if len(raw) == 6:
            red, green, blue = int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
            glow_css = f"0 0 10px rgba({red},{green},{blue},{glow:.2f})" if glow > 0 else "none"
        else:
            glow_css = "none"
    except Exception:
        glow_css = "none"

    shadow_css = f"0 2px 6px rgba(0,0,0,{shadow:.2f})" if shadow > 0 else "none"
    active_ring = f"0 0 0 1.5px {accent}55"
    sidebar = "section[data-testid='stSidebar']"

    st.markdown(
        f"""<style>
{sidebar} {{
    --wl-bg:      {theme['card_bg']};
    --wl-bd:      {theme['card_border']};
    --wl-hov:     {theme['card_hover']};
    --wl-act-bg:  {theme['card_active_bg']};
    --wl-act-bd:  {theme['card_active_border']};
    --wl-acc:     {accent};
    --wl-bull:    {theme['bullish']};
    --wl-bear:    {theme['bearish']};
    --wl-txt:     {theme['text_primary']};
    --wl-mut:     {theme['text_secondary']};
    --wl-r:       {radius};
    --wl-pv:      {pad_v}px;
    --wl-ph:      {pad_h}px;
    --wl-gap:     {gap}px;
    --wl-spd:     {speed}s;
    --wl-glow:    {glow_css};
    --wl-shad:    {shadow_css};
    --wl-ring:    {active_ring};
}}

{sidebar} .wl2m {{
    display: block; height: 0; overflow: hidden;
    margin: 0; padding: 0; line-height: 0; font-size: 0;
}}
{sidebar} .element-container:has(.wl2m) {{
    margin-bottom: 0 !important;
    min-height: 0 !important;
}}

{sidebar} .element-container:has(.wl2-card) + .element-container .stButton > button {{
    background:    var(--wl-bg) !important;
    border:        1px solid var(--wl-bd) !important;
    border-left:   2.5px solid var(--wl-bd) !important;
    border-radius: var(--wl-r) !important;
    padding:       var(--wl-pv) var(--wl-ph) !important;
    min-height:    unset !important;
    height:        auto !important;
    width:         100% !important;
    text-align:    left !important;
    color:         var(--wl-txt) !important;
    font-size:     0.77rem !important;
    font-weight:   400 !important;
    letter-spacing:0.01em !important;
    white-space:   pre-wrap !important;
    line-height:   1.5 !important;
    transition:    background var(--wl-spd) ease,
                   border-color var(--wl-spd) ease,
                   box-shadow var(--wl-spd) ease !important;
    box-shadow:    var(--wl-shad) !important;
    margin-bottom: var(--wl-gap) !important;
}}

{sidebar} .element-container:has(.wl2-card) + .element-container .stButton > button:hover {{
    background:  var(--wl-hov) !important;
    border-color:var(--wl-acc) !important;
    border-left-color: var(--wl-acc) !important;
    box-shadow:  var(--wl-glow), var(--wl-shad) !important;
}}

{sidebar} .element-container:has(.wl2-bull) + .element-container .stButton > button {{
    border-left-color: var(--wl-bull) !important;
}}
{sidebar} .element-container:has(.wl2-bear) + .element-container .stButton > button {{
    border-left-color: var(--wl-bear) !important;
}}

{sidebar} .element-container:has(.wl2-active) + .element-container .stButton > button {{
    background:   var(--wl-act-bg) !important;
    border-color: var(--wl-act-bd) !important;
    border-left-color: var(--wl-act-bd) !important;
    box-shadow:   var(--wl-ring), var(--wl-shad) !important;
}}
{sidebar} .element-container:has(.wl2-active) + .element-container .stButton > button:hover {{
    box-shadow: var(--wl-ring), var(--wl-glow), var(--wl-shad) !important;
}}

{sidebar} .element-container:has(.wl2-del) + .element-container .stButton > button {{
    background:    rgba(244,63,94,0.08) !important;
    border:        1px solid rgba(244,63,94,0.20) !important;
    border-radius: var(--wl-r) !important;
    color:         #f43f5e !important;
    font-size:     0.85rem !important;
    min-height:    unset !important;
    height:        100% !important;
    padding:       3px 2px !important;
    margin:        0 0 var(--wl-gap) 0 !important;
    transition:    background var(--wl-spd) ease,
                   border-color var(--wl-spd) ease,
                   box-shadow var(--wl-spd) ease !important;
}}
{sidebar} .element-container:has(.wl2-del) + .element-container .stButton > button:hover {{
    background:  rgba(244,63,94,0.22) !important;
    border-color:#f43f5e !important;
    box-shadow:  0 0 8px rgba(244,63,94,0.22) !important;
}}

{sidebar} .element-container:has(.wl2-edit) + .element-container .stButton > button {{
    background:     transparent !important;
    border:         1px solid var(--wl-bd) !important;
    color:          var(--wl-mut) !important;
    font-size:      0.65rem !important;
    font-weight:    700 !important;
    min-height:     20px !important;
    padding:        1px 6px !important;
    border-radius:  3px !important;
    letter-spacing: 0.05em !important;
    text-transform: uppercase !important;
    margin:         0 !important;
    transition:     border-color var(--wl-spd), color var(--wl-spd) !important;
}}
{sidebar} .element-container:has(.wl2-edit) + .element-container .stButton > button:hover {{
    border-color: var(--wl-acc) !important;
    color:        var(--wl-acc) !important;
}}

/* ── Edit-mode: unified card row (card + delete as one box) ─── */
{sidebar} div[data-testid="stHorizontalBlock"]:has(.wl2-del) {{
    gap: 0 !important;
    background: var(--wl-bg) !important;
    border: 1px solid var(--wl-bd) !important;
    border-left: 2.5px solid var(--wl-bd) !important;
    border-radius: var(--wl-r) !important;
    margin-bottom: var(--wl-gap) !important;
    overflow: hidden !important;
    box-shadow: var(--wl-shad) !important;
    align-items: stretch !important;
    transition: background var(--wl-spd) ease,
                border-color var(--wl-spd) ease,
                box-shadow var(--wl-spd) ease !important;
}}
{sidebar} div[data-testid="stHorizontalBlock"]:has(.wl2-del):hover {{
    background: var(--wl-hov) !important;
    border-color: var(--wl-acc) !important;
    border-left-color: var(--wl-acc) !important;
    box-shadow: var(--wl-glow), var(--wl-shad) !important;
}}
{sidebar} div[data-testid="stHorizontalBlock"]:has(.wl2-del):has(.wl2-active) {{
    background: var(--wl-act-bg) !important;
    border-color: var(--wl-act-bd) !important;
    border-left-color: var(--wl-act-bd) !important;
    box-shadow: var(--wl-ring), var(--wl-shad) !important;
}}
{sidebar} div[data-testid="stHorizontalBlock"]:has(.wl2-del):has(.wl2-bull) {{
    border-left-color: var(--wl-bull) !important;
}}
{sidebar} div[data-testid="stHorizontalBlock"]:has(.wl2-del):has(.wl2-bear) {{
    border-left-color: var(--wl-bear) !important;
}}
{sidebar} div[data-testid="stHorizontalBlock"]:has(.wl2-del) > div[data-testid="column"] {{
    padding: 0 !important;
    min-height: unset !important;
}}
{sidebar} div[data-testid="stHorizontalBlock"]:has(.wl2-del) .element-container {{
    margin: 0 !important;
    padding: 0 !important;
    min-height: unset !important;
}}
/* Card button transparent inside unified block */
{sidebar} div[data-testid="stHorizontalBlock"]:has(.wl2-del) .element-container:has(.wl2-card) + .element-container .stButton > button {{
    background:    transparent !important;
    border:        none !important;
    border-radius: 0 !important;
    box-shadow:    none !important;
    margin:        0 !important;
    width:         100% !important;
    height:        100% !important;
}}
{sidebar} div[data-testid="stHorizontalBlock"]:has(.wl2-del) .element-container:has(.wl2-card) + .element-container .stButton > button:hover {{
    background: transparent !important;
    box-shadow: none !important;
}}
/* Delete button inside unified block */
{sidebar} div[data-testid="stHorizontalBlock"]:has(.wl2-del) .element-container:has(.wl2-del) + .element-container .stButton > button {{
    background:    transparent !important;
    border:        none !important;
    border-left:   1px solid var(--wl-bd) !important;
    border-radius: 0 !important;
    height:        100% !important;
    width:         100% !important;
    color:         #f43f5e !important;
    font-size:     1rem !important;
    margin:        0 !important;
    padding:       4px 6px !important;
    box-shadow:    none !important;
    transition:    background var(--wl-spd) ease,
                   border-color var(--wl-spd) ease !important;
}}
{sidebar} div[data-testid="stHorizontalBlock"]:has(.wl2-del) .element-container:has(.wl2-del) + .element-container .stButton > button:hover {{
    background:  rgba(244,63,94,0.18) !important;
    border-left-color: #f43f5e !important;
    box-shadow:  none !important;
}}
</style>""",
        unsafe_allow_html=True,
    )


_RADIUS_MAP = {"0": "0px", "2": "2px", "4": "4px", "5": "5px", "6": "6px", "8": "8px", "12": "12px"}
_ANIM_MAP = {"Instant": 0.05, "Fast": 0.12, "Normal": 0.18, "Smooth": 0.25, "Slow": 0.40}


def _render_settings_panel() -> None:
    with st.expander("UI Settings", expanded=False):
        theme = st.session_state.wl_theme

        preset_names = list(THEME_PRESETS.keys())
        current_index = (
            preset_names.index(st.session_state.wl_preset_name)
            if st.session_state.wl_preset_name in preset_names
            else 0
        )
        chosen = st.selectbox("Theme Preset", preset_names, index=current_index, key="wl_preset_sel")
        if st.button("Apply Preset", key="wl_apply_preset", use_container_width=True):
            st.session_state.wl_theme = THEME_PRESETS[chosen].copy()
            st.session_state.wl_preset_name = chosen
            st.rerun()

        st.markdown(
            '<p style="font-size:.62rem;color:#64748b;text-transform:uppercase;'
            'letter-spacing:.07em;font-weight:700;margin:10px 0 4px">COLORS</p>',
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns(2)
        with c1:
            theme["card_bg"] = st.color_picker("Card BG", theme["card_bg"], key="wl_cp_bg")
            theme["card_hover"] = st.color_picker("Hover BG", theme.get("card_hover", theme["card_bg"]), key="wl_cp_hov")
            theme["accent"] = st.color_picker("Accent", theme["accent"], key="wl_cp_acc")
            theme["bullish"] = st.color_picker("Bullish", theme["bullish"], key="wl_cp_bull")
        with c2:
            theme["card_border"] = st.color_picker("Border", theme["card_border"], key="wl_cp_brd")
            theme["card_active_bg"] = st.color_picker("Active BG", theme["card_active_bg"], key="wl_cp_abg")
            theme["card_active_border"] = st.color_picker("Active Border", theme["card_active_border"], key="wl_cp_abd")
            theme["bearish"] = st.color_picker("Bearish", theme["bearish"], key="wl_cp_bear")

        st.markdown(
            '<p style="font-size:.62rem;color:#64748b;text-transform:uppercase;'
            'letter-spacing:.07em;font-weight:700;margin:10px 0 4px">CARD STYLE</p>',
            unsafe_allow_html=True,
        )
        current_radius = next((key for key, value in _RADIUS_MAP.items() if value == theme.get("card_radius", "5px")), "5")
        radius_choice = st.select_slider("Corner Radius (px)", list(_RADIUS_MAP.keys()), value=current_radius, key="wl_sl_r")
        theme["card_radius"] = _RADIUS_MAP[radius_choice]

        theme["pad_v"] = st.slider("Padding V", 4, 16, int(theme.get("pad_v", 8)), 1, key="wl_sl_pv")
        theme["pad_h"] = st.slider("Padding H", 6, 20, int(theme.get("pad_h", 11)), 1, key="wl_sl_ph")
        theme["card_gap"] = st.slider("Gap between cards", 0, 8, int(theme.get("card_gap", 2)), 1, key="wl_sl_gap")
        theme["glow"] = st.slider("Glow intensity", 0.0, 1.0, float(theme.get("glow", 0.0)), 0.05, key="wl_sl_glow")
        theme["shadow"] = st.slider("Shadow intensity", 0.0, 0.5, float(theme.get("shadow", 0.1)), 0.05, key="wl_sl_shad")

        current_speed = float(theme.get("anim", 0.15))
        current_anim = min(_ANIM_MAP, key=lambda key: abs(_ANIM_MAP[key] - current_speed))
        anim_choice = st.select_slider("Animation speed", list(_ANIM_MAP.keys()), value=current_anim, key="wl_sl_anim")
        theme["anim"] = _ANIM_MAP[anim_choice]

        st.session_state.wl_theme = theme


def _card_label(ticker: str, name: str, price: float, pct: float) -> str:
    short_name = (name[:17] + "...") if len(name) > 17 else name
    arrow = "^" if pct >= 0 else "v"
    sign = "+" if pct >= 0 else ""
    price_text = f"Rs {price:,.1f}" if price and price > 0 else "--"
    return f"{ticker}  {price_text}\n{short_name}  {arrow} {sign}{pct:.2f}%"


def _marker_cls(active: bool, bull: bool) -> str:
    parts = ["wl2m", "wl2-card", "wl2-bull" if bull else "wl2-bear"]
    if active:
        parts.append("wl2-active")
    return " ".join(parts)


def render_watchlist_sidebar() -> None:
    """Render the persistent left watchlist sidebar."""
    ensure_watchlist_state()
    _inject_wl_css()
    catalog = all_stock_options()

    watchlist_symbols = st.session_state.watchlist
    price_changes = {symbol: get_price_change(symbol) for symbol in watchlist_symbols}

    with st.sidebar:
        st.markdown(
            '<div class="side-nav-title">Trading</div>'
            '<div class="side-nav-item active">Home</div>'
            '<div class="side-nav-item">Charting</div>'
            '<div class="side-nav-item">Trading</div>'
            '<div class="side-nav-item">Portfolio</div>'
            '<div class="side-nav-item">Profile</div>'
            '<div class="side-nav-item">Analysis</div>',
            unsafe_allow_html=True,
        )

        hcol, ecol = st.columns([5, 2])
        with hcol:
            st.markdown('<div class="watchlist-title">Stocks</div>', unsafe_allow_html=True)
        with ecol:
            edit_label = "Done" if st.session_state.watchlist_edit_mode else "Edit"
            st.markdown('<span class="wl2m wl2-edit"></span>', unsafe_allow_html=True)
            if st.button(edit_label, key="sb_wl_edit_toggle", use_container_width=True):
                st.session_state.watchlist_edit_mode = not st.session_state.watchlist_edit_mode
                st.rerun()

        query = st.text_input(
            "Search stocks",
            placeholder="Search ticker or company",
            key="watchlist_search_query",
        ).strip().lower()

        if query:
            matches = [
                (symbol, name)
                for symbol, name in catalog.items()
                if query in symbol.lower()
                or query in name.lower()
                or query in clean_symbol(symbol).lower()
            ][:8]
            if matches:
                st.markdown('<div class="watchlist-subtitle">Search Results</div>', unsafe_allow_html=True)
                for selected_symbol, selected_name in matches:
                    if st.button(
                        f"{clean_symbol(selected_symbol)} - {selected_name}",
                        key=f"wl_search_{selected_symbol}",
                        use_container_width=True,
                    ):
                        _add_stock(selected_symbol)
                        _select_stock(selected_symbol)
            else:
                st.caption("No match. Add manually below.")

        with st.expander("Add ticker manually", expanded=False):
            exchange = st.radio("Exchange", ["NSE", "US"], horizontal=True, key="wl_exchange")
            manual = st.text_input("Ticker", placeholder="RELIANCE or AAPL", key="wl_manual_sym")
            manual_symbol = normalize_symbol(manual, exchange)
            if st.button("Add ticker", key="wl_manual_add", use_container_width=True):
                if manual_symbol:
                    _add_stock(manual_symbol)
                    st.toast(f"Added {clean_symbol(manual_symbol)}")

        _render_settings_panel()

        st.markdown("---")

        count = len(st.session_state.watchlist)
        st.markdown(
            f'<div class="watchlist-subtitle">Saved Stocks '
            f'<span style="background:#1e2d45;color:#64748b;font-size:.62rem;'
            f'padding:1px 6px;border-radius:8px;font-weight:700;margin-left:4px">{count}</span></div>',
            unsafe_allow_html=True,
        )

        edit_mode = st.session_state.watchlist_edit_mode

        for symbol in list(st.session_state.watchlist):
            active = symbol == st.session_state.get("selected_stock")
            name = catalog.get(symbol) or get_display_name(symbol)
            ticker = clean_symbol(symbol)

            change_data = price_changes.get(symbol, {})
            pct = change_data.get("pct_change", 0.0)
            price = change_data.get("current", 0.0)

            label = _card_label(ticker, name, price, pct)
            marker_cls = _marker_cls(active, pct >= 0)

            if edit_mode:
                c_card, c_del = st.columns([5, 1])
                with c_card:
                    st.markdown(f'<span class="{marker_cls}"></span>', unsafe_allow_html=True)
                    if st.button(label, key=f"sb_wl_sel_{symbol}", use_container_width=True):
                        _select_stock(symbol)
                with c_del:
                    st.markdown('<span class="wl2m wl2-del"></span>', unsafe_allow_html=True)
                    if st.button("🗑", key=f"sb_wl_del_{symbol}", use_container_width=True):
                        _remove_stock(symbol)
                        st.rerun()
            else:
                st.markdown(f'<span class="{marker_cls}"></span>', unsafe_allow_html=True)
                if st.button(label, key=f"sb_wl_sel_{symbol}", use_container_width=True):
                    _select_stock(symbol)
