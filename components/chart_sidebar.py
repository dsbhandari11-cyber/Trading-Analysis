"""
Unified Chart Sidebar
=====================
Reusable RHS indicator panel for CFD Market, Chart Studio, and future pages.

Layout (top → bottom):
  ① Pine Script indicator panel — Favorites / Overlays / Panes / Strategies
  ② Smart Money Concepts         — zone-type visibility toggles (optional)
  ③ Saved layouts manager

Public API
----------
  render_chart_sidebar(db, page_prefix, current_symbol, current_timeframe, show_smc)
    → (overlay_ids, pane_ids, smc_config)

  build_pine_extra_overlays(db, df)
    → list[{color, linewidth, data}] — ready for institutional_chart extra_overlays

  filter_zones_by_smc(zones, smc_config)
    → filtered zone list based on SMC visibility config
"""

from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from data.pine_db import PineScriptDB
from components.pine_manager import get_pine_db, render_pine_manager, render_enabled_badge_row


# ── SMC zone label groups ─────────────────────────────────────────────────────

_SMC_OB_LABELS   = {"Bull OB", "Bear OB"}
_SMC_FVG_LABELS  = {"FVG+", "FVG-"}
_SMC_IFVG_LABELS = {"IFVG"}


# ── Public API ────────────────────────────────────────────────────────────────

def render_chart_sidebar(
    db:                Optional[PineScriptDB] = None,
    page_prefix:       str = "cs",
    current_symbol:    str = "",
    current_timeframe: str = "1D",
    show_smc:          bool = False,
) -> Tuple[List[str], List[str], Dict]:
    """
    Render the unified RHS indicator sidebar.

    Args:
        db:                PineScriptDB instance (uses singleton if None)
        page_prefix:       session-state key namespace ("cs", "cfd", …)
        current_symbol:    current asset symbol — used when saving layouts
        current_timeframe: current timeframe    — used when saving layouts
        show_smc:          whether to render the Smart Money Concepts section

    Returns:
        overlay_ids:  list of enabled Pine overlay script IDs
        pane_ids:     list of enabled Pine pane/strategy script IDs
        smc_config:   {show_ob, show_fvg, show_ifvg} visibility flags
    """
    if db is None:
        db = get_pine_db()

    # ── ① Pine Script indicator panel ────────────────────────────────────────
    st.markdown('<div class="cs-panel">', unsafe_allow_html=True)
    overlay_ids, pane_ids = render_pine_manager(db)
    st.markdown('</div>', unsafe_allow_html=True)

    # ── ② Smart Money Concepts section ───────────────────────────────────────
    smc_config: Dict = {"show_ob": True, "show_fvg": True, "show_ifvg": True}
    if show_smc:
        st.markdown("---")
        smc_config = _render_smc_section(page_prefix)

    # ── ③ Saved layouts ───────────────────────────────────────────────────────
    st.markdown("---")
    _render_layout_manager(db, page_prefix, current_symbol, current_timeframe)

    return overlay_ids, pane_ids, smc_config


def build_pine_extra_overlays(
    db: Optional[PineScriptDB],
    df: Optional[pd.DataFrame],
) -> List[Dict]:
    """
    Compute Pine-script overlays against `df` and convert to the format
    expected by `render_institutional_chart(extra_overlays=...)`.

    Returns a list of:  {color: str, linewidth: int, data: [{time, value}]}
    """
    if db is None or df is None or df.empty:
        return []

    result: List[Dict] = []
    for script in db.get_enabled_scripts():
        if script.category not in ("overlay", "pane"):
            continue
        try:
            from data.pine_parser import parse_pine_script
            from data.pine_calculator import calculate_indicators
            parsed = parse_pine_script(script.code)
            ovs, _pns = calculate_indicators(df, parsed, script.parameters)
            for ov in ovs:
                if not ov.get("data"):
                    continue
                result.append({
                    "color":     ov.get("color",     "#00d4aa"),
                    "linewidth": ov.get("linewidth",  1),
                    "data":      ov["data"],
                })
        except Exception:
            pass

    return result


def filter_zones_by_smc(zones: List[Dict], smc_config: Dict) -> List[Dict]:
    """
    Filter the SMC zones list based on the sidebar's visibility toggles.

    Zones whose label belongs to a disabled group are removed.
    Zones with unrecognised labels (custom callers) are always kept.
    """
    if not zones:
        return []

    show_ob   = smc_config.get("show_ob",   True)
    show_fvg  = smc_config.get("show_fvg",  True)
    show_ifvg = smc_config.get("show_ifvg", True)

    out = []
    for z in zones:
        label = z.get("label", "")
        if label in _SMC_OB_LABELS   and not show_ob:   continue
        if label in _SMC_FVG_LABELS  and not show_fvg:  continue
        if label in _SMC_IFVG_LABELS and not show_ifvg: continue
        out.append(z)
    return out


# ── SMC section ───────────────────────────────────────────────────────────────

def _smc_key(page_prefix: str, name: str) -> str:
    return f"{page_prefix}_smc_{name}"


def _render_smc_section(page_prefix: str) -> Dict:
    """Render SMC zone visibility checkboxes and return config dict."""

    # Initialise defaults
    defaults = {"show_ob": True, "show_fvg": True, "show_ifvg": True}
    for k, v in defaults.items():
        sk = _smc_key(page_prefix, k)
        if sk not in st.session_state:
            st.session_state[sk] = v

    st.markdown("""
<div style="display:flex;align-items:center;gap:6px;padding:4px 2px 6px;">
  <span style="color:#ec4899;font-size:.78rem;font-weight:800;">◈</span>
  <span style="color:#e2e8f0;font-size:.72rem;font-weight:700;
    letter-spacing:.07em;text-transform:uppercase;">Smart Money</span>
</div>""", unsafe_allow_html=True)

    # Order Blocks
    st.markdown(
        '<div style="color:#00d4aa;font-size:.63rem;font-weight:700;'
        'letter-spacing:.05em;text-transform:uppercase;'
        'padding:2px 0 2px 2px;border-left:2px solid #00d4aa44;margin-left:2px;">'
        'Order Blocks</div>',
        unsafe_allow_html=True,
    )
    ob_key = _smc_key(page_prefix, "show_ob")
    show_ob = st.checkbox(
        "Bull & Bear OB",
        value=st.session_state[ob_key],
        key=f"{page_prefix}_cb_ob",
    )
    st.session_state[ob_key] = show_ob

    # Fair Value Gaps
    st.markdown(
        '<div style="color:#4d9de0;font-size:.63rem;font-weight:700;'
        'letter-spacing:.05em;text-transform:uppercase;'
        'padding:5px 0 2px 2px;border-left:2px solid #4d9de044;margin-left:2px;">'
        'Fair Value Gaps</div>',
        unsafe_allow_html=True,
    )
    fvg_key  = _smc_key(page_prefix, "show_fvg")
    ifvg_key = _smc_key(page_prefix, "show_ifvg")
    show_fvg = st.checkbox(
        "FVG (Bull / Bear)",
        value=st.session_state[fvg_key],
        key=f"{page_prefix}_cb_fvg",
    )
    st.session_state[fvg_key] = show_fvg

    show_ifvg = st.checkbox(
        "Inverse FVG",
        value=st.session_state[ifvg_key],
        key=f"{page_prefix}_cb_ifvg",
    )
    st.session_state[ifvg_key] = show_ifvg

    return {"show_ob": show_ob, "show_fvg": show_fvg, "show_ifvg": show_ifvg}


# ── Layout manager ────────────────────────────────────────────────────────────

def _render_layout_manager(
    db:           PineScriptDB,
    page_prefix:  str,
    symbol:       str,
    timeframe:    str,
) -> None:
    """Saved-layout expander — save and restore indicator+symbol setups."""
    with st.expander("💾 Saved Layouts", expanded=False):
        layouts = db.get_layouts()
        if not layouts:
            st.caption("No saved layouts yet.")
        else:
            for layout in layouts[:8]:
                lc1, lc2 = st.columns([3, 1])
                with lc1:
                    st.markdown(
                        f'<div class="cs-layout-item"><b>{layout["name"]}</b><br>'
                        f'<span style="color:#64748b;font-size:.72rem;">'
                        f'{layout["symbol"]} · {layout["timeframe"]}</span></div>',
                        unsafe_allow_html=True,
                    )
                with lc2:
                    if st.button(
                        "Load",
                        key=f"{page_prefix}_load_layout_{layout['id']}",
                        use_container_width=True,
                    ):
                        enabled_ids = json.loads(layout.get("indicators", "[]"))
                        for s in db.get_all_scripts():
                            db.update_script(s.id, enabled=(s.id in enabled_ids))
                        st.rerun()

        st.markdown("---")
        save_name = st.text_input(
            "Layout name",
            placeholder="My Layout",
            key=f"{page_prefix}_layout_name",
            label_visibility="collapsed",
        )
        if st.button(
            "💾 Save Layout",
            key=f"{page_prefix}_save_layout",
            use_container_width=True,
        ):
            if save_name:
                enabled = [s.id for s in db.get_enabled_scripts()]
                db.save_layout(
                    name      = save_name,
                    symbol    = symbol,
                    timeframe = timeframe,
                    indicators= enabled,
                )
                st.success("Saved.")
                st.rerun()
            else:
                st.warning("Enter a name.")
