"""
TradingView-style Pine Script indicator management panel.

Uses a bidirectional Streamlit custom component (pine_manager_frontend/index.html)
so toggles, favorites and parameter edits update instantly in JS while Python
syncs the DB in the background — no full-page-rerun flash on every click.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import streamlit as st
import streamlit.components.v1 as _stc

from data.pine_db import PineScript, PineScriptDB


# ── Component declaration ─────────────────────────────────────────────────────

_FRONTEND_DIR  = Path(__file__).parent / "pine_manager_frontend"
_indicator_panel = _stc.declare_component(
    "indicator_panel",
    path=str(_FRONTEND_DIR),
)


# ── Singleton DB ──────────────────────────────────────────────────────────────

@st.cache_resource
def get_pine_db() -> PineScriptDB:
    db = PineScriptDB()
    db.deduplicate_scripts()
    db.scan_and_import()          # also calls sync_favorites_from_disk internally
    return db


# ── Section definitions ───────────────────────────────────────────────────────

_SECTIONS: List[Tuple[str, str, str]] = [
    # (key,        label,        accent_color)
    ("favorites",  "Favorites",  "#f0ad4e"),
    ("overlay",    "Overlays",   "#00d4aa"),
    ("pane",       "Panes",      "#4d9de0"),
    ("strategy",   "Strategies", "#f0ad4e"),
    ("template",   "Templates",  "#7c3aed"),
]

_CAT_ICON: Dict[str, str] = {
    "overlay":  "◈",
    "pane":     "◇",
    "strategy": "⚡",
    "template": "◻",
}


# ── Public API ────────────────────────────────────────────────────────────────

def render_pine_manager(db: Optional[PineScriptDB] = None) -> Tuple[List[str], List[str]]:
    """
    Render the indicator panel and return (overlay_ids, pane_ids) of enabled scripts.

    The custom JS component handles all toggle/favorite/edit interactions.
    State changes are sent back as a component return value.

    Rerun policy:
    - Only rerun when the set of ENABLED scripts changes (chart data changes).
    - Favorite/param-only changes also rerun so the chip row updates.
    - Rescan / upload always reruns.
    - The timestamp guard prevents double-processing on repeated reruns.
    """
    if db is None:
        db = get_pine_db()

    sections_data = _build_sections_data(db)

    result = _indicator_panel(
        sections=sections_data,
        key="pine_panel",
        default=None,
        height=600,
    )

    if result:
        changed = _handle_result(db, result)
        if changed:
            st.rerun()

    enabled = db.get_enabled_scripts()
    overlay_ids = [s.id for s in enabled if s.category == "overlay"]
    pane_ids    = [s.id for s in enabled if s.category in ("pane", "strategy")]
    return overlay_ids, pane_ids


def render_enabled_badge_row(db: Optional[PineScriptDB] = None) -> None:
    """Chip row of active indicators shown above the chart."""
    if db is None:
        db = get_pine_db()
    enabled = db.get_enabled_scripts()
    if not enabled:
        return
    chips = "".join(
        f'<span class="ind-chip ind-chip-{s.category}">'
        f'{_CAT_ICON.get(s.category,"○")} {s.name}'
        f'</span>'
        for s in enabled
    )
    st.markdown(f'<div class="ind-chip-row">{chips}</div>', unsafe_allow_html=True)


# ── Data serialisation ────────────────────────────────────────────────────────

def _build_sections_data(db: PineScriptDB) -> list:
    cat_map = db.get_category_map()
    out = []
    for key, label, color in _SECTIONS:
        scripts = cat_map.get(key, [])
        out.append({
            "key":     key,
            "label":   label,
            "color":   color,
            "scripts": [_s2d(s) for s in scripts],
        })
    return out


def _s2d(s: PineScript) -> dict:
    return {
        "id":          s.id,
        "name":        s.name,
        "category":    s.category,
        "script_type": s.script_type,
        "overlay":     s.overlay,
        "enabled":     s.enabled,
        "favorite":    s.favorite,
        "builtin":     s.builtin,
        "parameters":  s.parameters,
    }


# ── Result processing ─────────────────────────────────────────────────────────

def _handle_result(db: PineScriptDB, result: dict) -> bool:
    """
    Process a value sent by the JS component.
    Returns True if a rerun is warranted.
    Uses a timestamp guard to avoid double-processing on repeated reruns.

    Only triggers a rerun when:
    - The enabled set changes (chart must be rebuilt)
    - Params change (chart must be rebuilt)
    - Upload / rescan / delete occurs
    Favorite-only changes also rerun to refresh the chip row.
    """
    ts      = result.get("timestamp", 0)
    last_ts = st.session_state.get("_pine_last_ts", 0)
    if ts <= last_ts:
        return False
    st.session_state["_pine_last_ts"] = ts

    action = result.get("action", "")

    if action == "update":
        return _apply_update(db, result)

    if action == "delete":
        delete_id = result.get("delete_id", "")
        if delete_id:
            db.delete_script(delete_id)
            return True

    if action == "upload":
        return _apply_upload(db, result)

    if action == "rescan":
        db.scan_and_import()
        return True

    return False


def _apply_update(db: PineScriptDB, result: dict) -> bool:
    new_enabled   = set(result.get("enabled",   []))
    new_favorites = set(result.get("favorites", []))
    param_updates = result.get("param_updates", {})
    # JS sends all known script IDs — only touch scripts the panel reported on
    known_ids     = set(result.get("known_ids", []))
    changed       = False

    for script in db.get_all_scripts():
        updates: dict = {}
        # Only reconcile enabled/favorite for IDs the JS explicitly reported.
        # If known_ids is empty (old frontend), fall back to full reconcile.
        in_scope = (not known_ids) or (script.id in known_ids)

        if in_scope:
            want_on  = script.id in new_enabled
            want_fav = script.id in new_favorites
            if script.enabled  != want_on:  updates["enabled"]  = want_on
            if script.favorite != want_fav: updates["favorite"] = want_fav

        if script.id in param_updates:
            updates["parameters"] = param_updates[script.id]

        if updates:
            db.update_script(script.id, **updates)
            changed = True

    return changed


def _apply_upload(db: PineScriptDB, result: dict) -> bool:
    name = (result.get("name") or "").strip()
    code = (result.get("code") or "").strip()
    if not name or not code:
        return False
    try:
        from data.pine_parser import parse_pine_script
        parsed = parse_pine_script(code)
        db.save_script(PineScript(
            name        = name,
            code        = code,
            category    = parsed.category,
            script_type = parsed.script_type,
            overlay     = parsed.overlay,
            metadata    = parsed.metadata,
            parameters  = parsed.parameters,
        ))
        return True
    except Exception:
        return False
