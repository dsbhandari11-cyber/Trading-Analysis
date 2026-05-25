"""
Persistent Pine Script storage — SQLite metadata + local .pine files.
Survives Streamlit refresh, app restart, and system reboot.
"""

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PINE_DIR = Path(__file__).resolve().parent.parent / "pine_scripts"
DB_PATH  = PINE_DIR / "pine_scripts.db"

FOLDERS: Dict[str, Path] = {
    "overlay":  PINE_DIR / "overlays",
    "pane":     PINE_DIR / "panes",
    "strategy": PINE_DIR / "strategies",
    "favorites": PINE_DIR / "favorites",
    "templates": PINE_DIR / "templates",
}

# ── Built-in indicator Pine Script v5 seeds ──────────────────────────────────
_BUILTIN_SEEDS = [
    {
        "name": "EMA",
        "category": "overlay",
        "script_type": "indicator",
        "overlay": True,
        "code": """//@version=5
indicator("EMA", overlay=true)
length = input.int(14, title="Length", minval=1)
src    = input.source(close, title="Source")
plot(ta.ema(src, length), color=color.new(color.aqua, 0), linewidth=2, title="EMA")
""",
    },
    {
        "name": "SMA",
        "category": "overlay",
        "script_type": "indicator",
        "overlay": True,
        "code": """//@version=5
indicator("SMA", overlay=true)
length = input.int(20, title="Length", minval=1)
src    = input.source(close, title="Source")
plot(ta.sma(src, length), color=color.new(color.blue, 0), linewidth=2, title="SMA")
""",
    },
    {
        "name": "RSI",
        "category": "pane",
        "script_type": "indicator",
        "overlay": False,
        "code": """//@version=5
indicator("RSI", overlay=false)
length = input.int(14, title="Length", minval=1)
rsi    = ta.rsi(close, length)
plot(rsi, color=color.new(color.orange, 0), linewidth=2, title="RSI")
hline(70, "Overbought", color=color.red,   linestyle=hline.style_dashed)
hline(30, "Oversold",   color=color.green, linestyle=hline.style_dashed)
""",
    },
    {
        "name": "MACD",
        "category": "pane",
        "script_type": "indicator",
        "overlay": False,
        "code": """//@version=5
indicator("MACD", overlay=false)
fastPeriod   = input.int(12, title="Fast Period")
slowPeriod   = input.int(26, title="Slow Period")
signalPeriod = input.int(9,  title="Signal Period")
[macdLine, signalLine, histLine] = ta.macd(close, fastPeriod, slowPeriod, signalPeriod)
plot(macdLine,   color=color.aqua,   linewidth=2, title="MACD")
plot(signalLine, color=color.red,    linewidth=1, title="Signal")
plot(histLine,   color=color.blue,   style=plot.style_histogram, title="Histogram")
""",
    },
    {
        "name": "Bollinger Bands",
        "category": "overlay",
        "script_type": "indicator",
        "overlay": True,
        "code": """//@version=5
indicator("Bollinger Bands", overlay=true)
length = input.int(20,  title="Length", minval=1)
mult   = input.float(2.0, title="Std Dev Mult")
basis  = ta.sma(close, length)
dev    = mult * ta.stdev(close, length)
upper  = basis + dev
lower  = basis - dev
plot(upper,  color=color.blue, linewidth=1, title="BB Upper")
plot(basis,  color=color.gray, linewidth=1, title="BB Middle")
plot(lower,  color=color.blue, linewidth=1, title="BB Lower")
fill(plot(upper), plot(lower), color=color.new(color.blue, 90))
""",
    },
    {
        "name": "VWAP",
        "category": "overlay",
        "script_type": "indicator",
        "overlay": True,
        "code": """//@version=5
indicator("VWAP", overlay=true)
vwap_val = ta.vwap(hlc3)
plot(vwap_val, color=color.new(color.orange, 0), linewidth=2, title="VWAP")
""",
    },
    {
        "name": "ATR",
        "category": "pane",
        "script_type": "indicator",
        "overlay": False,
        "code": """//@version=5
indicator("ATR", overlay=false)
period = input.int(14, title="Period", minval=1)
plot(ta.atr(period), color=color.purple, linewidth=2, title="ATR")
""",
    },
    {
        "name": "ADX / DMI",
        "category": "pane",
        "script_type": "indicator",
        "overlay": False,
        "code": """//@version=5
indicator("ADX / DMI", overlay=false)
period = input.int(14, title="Period", minval=1)
[diPlus, diMinus, adx] = ta.dmi(period, period)
plot(adx,     color=color.orange, linewidth=2, title="ADX")
plot(diPlus,  color=color.green,  linewidth=1, title="+DI")
plot(diMinus, color=color.red,    linewidth=1, title="-DI")
""",
    },
    {
        "name": "Supertrend",
        "category": "overlay",
        "script_type": "indicator",
        "overlay": True,
        "code": """//@version=5
indicator("Supertrend", overlay=true)
atrPeriod = input.int(10,  title="ATR Period")
factor    = input.float(3.0, title="Factor")
[supertrend, direction] = ta.supertrend(factor, atrPeriod)
plot(direction < 0 ? supertrend : na, color=color.green, linewidth=2, title="Up Trend")
plot(direction > 0 ? supertrend : na, color=color.red,   linewidth=2, title="Down Trend")
""",
    },
]


# ── Dataclass ────────────────────────────────────────────────────────────────

@dataclass
class PineScript:
    name:        str
    code:        str
    category:    str          # overlay | pane | strategy
    script_type: str          # indicator | strategy
    overlay:     bool
    id:          str   = field(default_factory=lambda: str(uuid.uuid4())[:8])
    upload_date: str   = field(default_factory=lambda: datetime.now().isoformat())
    enabled:     bool  = False
    favorite:    bool  = False
    filename:    str   = ""
    metadata:    Dict  = field(default_factory=dict)
    parameters:  Dict  = field(default_factory=dict)
    builtin:     bool  = False


# ── Database ─────────────────────────────────────────────────────────────────

class PineScriptDB:
    """Thread-safe SQLite-backed Pine Script registry."""

    def __init__(self):
        self._ensure_dirs()
        self._init_db()
        self._seed_builtins()

    # ── Init helpers ──────────────────────────────────────────────────────────

    def _ensure_dirs(self):
        PINE_DIR.mkdir(parents=True, exist_ok=True)
        for folder in FOLDERS.values():
            folder.mkdir(parents=True, exist_ok=True)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS scripts (
                    id          TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    filename    TEXT NOT NULL DEFAULT '',
                    category    TEXT NOT NULL,
                    script_type TEXT NOT NULL,
                    overlay     INTEGER NOT NULL DEFAULT 0,
                    enabled     INTEGER NOT NULL DEFAULT 0,
                    favorite    INTEGER NOT NULL DEFAULT 0,
                    builtin     INTEGER NOT NULL DEFAULT 0,
                    upload_date TEXT NOT NULL,
                    code        TEXT NOT NULL,
                    metadata    TEXT NOT NULL DEFAULT '{}',
                    parameters  TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS chart_layouts (
                    id          TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    symbol      TEXT NOT NULL,
                    timeframe   TEXT NOT NULL,
                    indicators  TEXT NOT NULL DEFAULT '[]',
                    drawings    TEXT NOT NULL DEFAULT '[]',
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_preferences (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)

    def _seed_builtins(self):
        """Insert built-in indicators once — skip if already present."""
        with self._conn() as conn:
            existing = {
                row[0]
                for row in conn.execute("SELECT name FROM scripts WHERE builtin = 1")
            }
        for seed in _BUILTIN_SEEDS:
            if seed["name"] not in existing:
                from data.pine_parser import parse_pine_script
                parsed = parse_pine_script(seed["code"])
                script = PineScript(
                    name=seed["name"],
                    code=seed["code"],
                    category=seed["category"],
                    script_type=seed["script_type"],
                    overlay=seed["overlay"],
                    metadata=parsed.metadata,
                    parameters=parsed.parameters,
                    builtin=True,
                )
                self.save_script(script)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def save_script(self, script: PineScript) -> str:
        """Persist script to disk (.pine file) and DB. Returns script.id."""
        folder = FOLDERS.get(script.category, FOLDERS["pane"])
        safe   = "".join(c if c.isalnum() or c in "_-" else "_" for c in script.name)
        if not script.filename:
            script.filename = f"{safe}_{script.id}.pine"
        file_path = folder / script.filename
        file_path.write_text(script.code, encoding="utf-8")

        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO scripts
                (id, name, filename, category, script_type, overlay,
                 enabled, favorite, builtin, upload_date, code, metadata, parameters)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                script.id, script.name, script.filename, script.category,
                script.script_type, int(script.overlay), int(script.enabled),
                int(script.favorite), int(script.builtin), script.upload_date,
                script.code, json.dumps(script.metadata), json.dumps(script.parameters),
            ))
        return script.id

    def get_all_scripts(self) -> List[PineScript]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM scripts ORDER BY builtin DESC, name ASC"
            ).fetchall()
        return [self._row_to_script(r) for r in rows]

    def get_script(self, script_id: str) -> Optional[PineScript]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM scripts WHERE id = ?", (script_id,)
            ).fetchone()
        return self._row_to_script(row) if row else None

    def get_enabled_scripts(self) -> List[PineScript]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM scripts WHERE enabled = 1 ORDER BY category, name"
            ).fetchall()
        return [self._row_to_script(r) for r in rows]

    def update_script(self, script_id: str, **kwargs):
        allowed = {"name", "enabled", "favorite", "category", "parameters", "code"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        # Serialize dict values
        serialized = {
            k: (json.dumps(v) if isinstance(v, (dict, list)) else int(v) if isinstance(v, bool) else v)
            for k, v in updates.items()
        }
        set_clause = ", ".join(f"{k} = ?" for k in serialized)
        values     = list(serialized.values()) + [script_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE scripts SET {set_clause} WHERE id = ?", values)

    def delete_script(self, script_id: str):
        script = self.get_script(script_id)
        if script and script.filename:
            for folder in FOLDERS.values():
                fp = folder / script.filename
                if fp.exists():
                    fp.unlink(missing_ok=True)
        with self._conn() as conn:
            conn.execute("DELETE FROM scripts WHERE id = ?", (script_id,))

    # ── Chart layouts ─────────────────────────────────────────────────────────

    def save_layout(
        self, name: str, symbol: str, timeframe: str,
        indicators: List[str], drawings: Optional[List] = None,
    ) -> str:
        layout_id = str(uuid.uuid4())[:8]
        now       = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO chart_layouts
                (id, name, symbol, timeframe, indicators, drawings, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                layout_id, name, symbol, timeframe,
                json.dumps(indicators), json.dumps(drawings or []),
                now, now,
            ))
        return layout_id

    def get_layouts(self) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM chart_layouts ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_layout(self, layout_id: str):
        with self._conn() as conn:
            conn.execute("DELETE FROM chart_layouts WHERE id = ?", (layout_id,))

    # ── User preferences ──────────────────────────────────────────────────────

    def get_preference(self, key: str, default: Any = None) -> Any:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM user_preferences WHERE key = ?", (key,)
            ).fetchone()
        return json.loads(row["value"]) if row else default

    def set_preference(self, key: str, value: Any):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_preferences (key, value) VALUES (?,?)",
                (key, json.dumps(value)),
            )

    # ── Category map ─────────────────────────────────────────────────────────

    # Valid non-favorites categories — used to prevent accidental self-reference
    _CAT_KEYS = frozenset({"overlay", "pane", "strategy", "template"})

    def get_category_map(self) -> Dict[str, List["PineScript"]]:
        """
        Return all scripts grouped into the canonical display sections.

        Keys (always present, may be empty list):
          "favorites"  — scripts with favorite=True, any category (duplicate refs OK)
          "overlay"    — overlay indicators
          "pane"       — pane indicators
          "strategy"   — strategy scripts
          "template"   — template scripts
        """
        all_scripts = self.get_all_scripts()
        result: Dict[str, List[PineScript]] = {
            "favorites": [],
            "overlay":   [],
            "pane":      [],
            "strategy":  [],
            "template":  [],
        }
        for s in all_scripts:
            # Normalize unknown/special categories to "pane"
            cat = s.category if s.category in self._CAT_KEYS else "pane"
            result[cat].append(s)
            # Favorites section: separate pass, never duplicates within favorites list
            if s.favorite:
                result["favorites"].append(s)
        return result

    def get_scripts_by_category(self, category: str) -> List["PineScript"]:
        """Return scripts filtered by exact category."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM scripts WHERE category = ? ORDER BY builtin DESC, name ASC",
                (category,),
            ).fetchall()
        return [self._row_to_script(r) for r in rows]

    def get_favorites(self) -> List["PineScript"]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM scripts WHERE favorite = 1 ORDER BY name ASC"
            ).fetchall()
        return [self._row_to_script(r) for r in rows]

    # ── Folder scanner ────────────────────────────────────────────────────────

    def scan_and_import(self):
        """
        Import any .pine / .txt files in all script folders not yet in DB.

        Dedup key: filename only — one DB record per unique filename regardless of
        which folder contains it (prevents double-importing the same file).

        Favorites pass: when a file in favorites/ is ALREADY in DB (same filename),
        its favorite flag is updated to 1 instead of creating a duplicate record.
        After all folder scans, sync_favorites_from_disk() does a final enforcement.
        """
        from data.pine_parser import parse_pine_script

        with self._conn() as conn:
            existing_filenames: set = {
                row[0]
                for row in conn.execute("SELECT filename FROM scripts")
            }

        scan_targets = [
            ("overlay",  FOLDERS["overlay"],   False, False),
            ("pane",     FOLDERS["pane"],       False, False),
            ("strategy", FOLDERS["strategy"],   False, False),
            ("",         FOLDERS["favorites"],  True,  False),
            ("template", FOLDERS["templates"],  False, True),
        ]

        for default_cat, folder, mark_favorite, force_template in scan_targets:
            for filepath in list(folder.glob("*.pine")) + list(folder.glob("*.txt")):
                if filepath.name in existing_filenames:
                    # File already in DB — if favorites folder, enforce the flag
                    if mark_favorite:
                        with self._conn() as conn:
                            conn.execute(
                                "UPDATE scripts SET favorite = 1 "
                                "WHERE filename = ? AND favorite = 0",
                                (filepath.name,),
                            )
                    continue

                try:
                    code   = filepath.read_text(encoding="utf-8", errors="replace")
                    parsed = parse_pine_script(code)

                    if force_template:
                        cat = "template"
                    elif default_cat:
                        cat = parsed.category or default_cat
                    else:
                        cat = parsed.category or "pane"

                    script = PineScript(
                        name        = filepath.stem,
                        code        = code,
                        category    = cat,
                        script_type = parsed.script_type,
                        overlay     = parsed.overlay,
                        metadata    = parsed.metadata,
                        parameters  = parsed.parameters,
                        filename    = filepath.name,
                        favorite    = mark_favorite,
                    )
                    self.save_script(script)
                    existing_filenames.add(filepath.name)
                except Exception:
                    pass

        self.sync_favorites_from_disk()

    def sync_favorites_from_disk(self):
        """Set favorite=1 for every DB script whose filename appears in favorites/ folder."""
        fav_folder = FOLDERS["favorites"]
        fav_names  = {
            f.name
            for f in list(fav_folder.glob("*.pine")) + list(fav_folder.glob("*.txt"))
        }
        if not fav_names:
            return
        with self._conn() as conn:
            for fname in fav_names:
                conn.execute(
                    "UPDATE scripts SET favorite = 1 WHERE filename = ?",
                    (fname,),
                )

    def deduplicate_scripts(self):
        """
        Remove duplicate DB rows that share (name, category).
        Keeps the row with the highest (enabled + favorite) score, then newest upload.
        """
        with self._conn() as conn:
            dupes = conn.execute("""
                SELECT name, category
                FROM scripts
                GROUP BY name, category
                HAVING COUNT(*) > 1
            """).fetchall()
            for name, category in dupes:
                rows = conn.execute(
                    """SELECT id, enabled, favorite, upload_date
                       FROM scripts WHERE name = ? AND category = ?
                       ORDER BY (enabled + favorite) DESC, upload_date DESC""",
                    (name, category),
                ).fetchall()
                keep_id = rows[0][0]
                for row in rows[1:]:
                    conn.execute("DELETE FROM scripts WHERE id = ?", (row[0],))

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _row_to_script(row) -> PineScript:
        d = dict(row)
        return PineScript(
            id          = d["id"],
            name        = d["name"],
            filename    = d.get("filename", ""),
            category    = d["category"],
            script_type = d["script_type"],
            overlay     = bool(d["overlay"]),
            enabled     = bool(d["enabled"]),
            favorite    = bool(d["favorite"]),
            builtin     = bool(d.get("builtin", 0)),
            upload_date = d["upload_date"],
            code        = d["code"],
            metadata    = json.loads(d.get("metadata", "{}")),
            parameters  = json.loads(d.get("parameters", "{}")),
        )
