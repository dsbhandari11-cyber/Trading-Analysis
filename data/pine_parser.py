"""
Pine Script v5 parser.
Detects: indicator/strategy type, overlay flag, inputs, plots, alertconditions,
used technical functions, and auto-generates parameter defaults.
Pure Python — no external dependencies.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Sub-models ────────────────────────────────────────────────────────────────

@dataclass
class PineInput:
    name:       str
    input_type: str       # int | float | bool | string | color | source | timeframe
    default:    Any
    title:      str  = ""
    min_val:    Optional[float] = None
    max_val:    Optional[float] = None


@dataclass
class PinePlot:
    series:    str
    color:     str = ""
    linewidth: int = 1
    style:     str = "line"
    title:     str = ""


@dataclass
class ParsedPine:
    script_type:      str  = "indicator"   # indicator | strategy
    overlay:          bool = False
    category:         str  = "pane"        # overlay | pane | strategy
    title:            str  = ""
    inputs:           List[PineInput] = field(default_factory=list)
    plots:            List[PinePlot]  = field(default_factory=list)
    has_fill:         bool = False
    has_alertcondition: bool = False
    has_plotshape:    bool = False
    uses_indicators:  List[str] = field(default_factory=list)
    metadata:         Dict = field(default_factory=dict)
    parameters:       Dict = field(default_factory=dict)


# ── Known technical indicators (Pine + common shorthand) ─────────────────────

_INDICATOR_MAP = {
    "ta.ema":        "EMA",
    "ta.sma":        "SMA",
    "ta.rsi":        "RSI",
    "ta.macd":       "MACD",
    "ta.bbands":     "BOLLINGER_BANDS",
    "BollingerBands":"BOLLINGER_BANDS",
    "ta.atr":        "ATR",
    "ta.adx":        "ADX",
    "ta.dmi":        "DMI",
    "ta.vwap":       "VWAP",
    "ta.stoch":      "STOCHASTIC",
    "ta.cci":        "CCI",
    "ta.williams":   "WILLIAMS",
    "ta.supertrend": "SUPERTREND",
    "ta.highest":    "HIGHEST",
    "ta.lowest":     "LOWEST",
    "ta.pivothigh":  "PIVOT",
    "ta.pivotlow":   "PIVOT",
    "supertrend":    "SUPERTREND",
    "vwap":          "VWAP",
}

# ── Regex patterns ────────────────────────────────────────────────────────────

_INPUT_RE = re.compile(
    r"""(\w+)\s*=\s*input\.(int|float|bool|string|color|source|timeframe)\s*\(
        \s*([^,)\n]+?)                          # default value
        (?:\s*,\s*title\s*=\s*["']([^"']+)["'])?  # optional title
        (?:\s*,\s*minval\s*=\s*([0-9.+-]+))?       # optional minval
        (?:\s*,\s*maxval\s*=\s*([0-9.+-]+))?       # optional maxval
        [^)]*\)""",
    re.VERBOSE | re.MULTILINE,
)

_PLOT_RE = re.compile(
    r"""plot\s*\(\s*([^,)\n]+?)
        (?:\s*,\s*(?:color\s*=\s*([^,)\n]+?)))?
        (?:\s*,\s*title\s*=\s*["']([^"']+)["'])?
        [^)]*\)""",
    re.VERBOSE | re.MULTILINE,
)

_STRATEGY_RE  = re.compile(r"^\s*strategy\s*\(", re.MULTILINE)
_INDICATOR_RE = re.compile(r"^\s*indicator\s*\(", re.MULTILINE)
_TITLE_RE     = re.compile(r"""title\s*=\s*["']([^"']+)["']""")
_OVERLAY_RE   = re.compile(r"overlay\s*=\s*(true|false)", re.IGNORECASE)


# ── Public API ────────────────────────────────────────────────────────────────

def parse_pine_script(code: str) -> ParsedPine:
    """Parse a Pine Script v5 string and return a ParsedPine dataclass."""
    result = ParsedPine()
    clean  = _strip_comments(code)

    # ── Detect strategy vs indicator ──────────────────────────────────────────
    if _STRATEGY_RE.search(clean):
        result.script_type = "strategy"
        result.category    = "strategy"
        m = _TITLE_RE.search(_get_first_call(clean, "strategy"))
        if m:
            result.title = m.group(1)
    elif _INDICATOR_RE.search(clean):
        result.script_type = "indicator"
        m_call = _get_first_call(clean, "indicator")
        m = _TITLE_RE.search(m_call)
        if m:
            result.title = m.group(1)
        m_ov = _OVERLAY_RE.search(m_call)
        if m_ov:
            result.overlay  = m_ov.group(1).lower() == "true"
            result.category = "overlay" if result.overlay else "pane"

    # Fallback overlay detection anywhere in script
    if result.script_type != "strategy":
        m_ov = _OVERLAY_RE.search(clean)
        if m_ov and m_ov.group(1).lower() == "true":
            result.overlay  = True
            result.category = "overlay"

    # ── Parse inputs ──────────────────────────────────────────────────────────
    for m in _INPUT_RE.finditer(clean):
        var_name   = m.group(1)
        inp_type   = m.group(2)
        default_s  = m.group(3).strip()
        title      = m.group(4) or var_name.replace("_", " ").title()
        min_v      = _try_float(m.group(5))
        max_v      = _try_float(m.group(6))

        default = _coerce_default(default_s, inp_type)
        inp = PineInput(
            name=var_name, input_type=inp_type, default=default,
            title=title, min_val=min_v, max_val=max_v,
        )
        result.inputs.append(inp)
        result.parameters[var_name] = default

    # ── Parse plots ───────────────────────────────────────────────────────────
    for m in _PLOT_RE.finditer(clean):
        series = m.group(1).strip()
        color  = (m.group(2) or "").strip()
        title  = m.group(3) or series
        result.plots.append(PinePlot(series=series, color=color, title=title))

    # ── Detect features ───────────────────────────────────────────────────────
    result.has_fill            = bool(re.search(r'\bfill\s*\(', clean))
    result.has_alertcondition  = bool(re.search(r'\balertcondition\s*\(', clean))
    result.has_plotshape       = bool(re.search(r'\bplotshape\s*\(', clean))

    # ── Detect used indicators ────────────────────────────────────────────────
    seen: set = set()
    for pattern, canonical in _INDICATOR_MAP.items():
        if re.search(re.escape(pattern) + r'\s*\(', clean, re.IGNORECASE):
            if canonical not in seen:
                result.uses_indicators.append(canonical)
                seen.add(canonical)

    # ── Build metadata ────────────────────────────────────────────────────────
    result.metadata = {
        "title":              result.title or result.script_type.title(),
        "uses_indicators":    result.uses_indicators,
        "has_fill":           result.has_fill,
        "has_alertcondition": result.has_alertcondition,
        "has_plotshape":      result.has_plotshape,
        "plot_count":         len(result.plots),
        "input_count":        len(result.inputs),
    }

    return result


def detect_indicator_type(code: str) -> str:
    """Quick helper: returns 'overlay', 'pane', or 'strategy'."""
    return parse_pine_script(code).category


# ── Private helpers ───────────────────────────────────────────────────────────

def _strip_comments(code: str) -> str:
    """Remove Pine Script // line comments."""
    lines = []
    for line in code.splitlines():
        idx = line.find("//")
        lines.append(line[:idx] if idx >= 0 else line)
    return "\n".join(lines)


def _get_first_call(code: str, func: str) -> str:
    """Return the content of the first func(...) call (up to 512 chars)."""
    m = re.search(re.escape(func) + r'\s*\(([^)]{0,512})\)', code, re.DOTALL)
    return m.group(0) if m else ""


def _try_float(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return float(s.strip())
    except ValueError:
        return None


def _coerce_default(raw: str, inp_type: str) -> Any:
    raw = raw.strip().strip("'\"")
    if inp_type in ("int", "float"):
        try:
            return float(raw)
        except ValueError:
            return 0.0
    if inp_type == "bool":
        return raw.lower() == "true"
    return raw
