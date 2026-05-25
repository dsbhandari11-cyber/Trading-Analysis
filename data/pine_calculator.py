"""
Server-side Pine Script indicator calculator.
Uses the `ta` library (no C compiler required) to compute indicator values
from a yfinance OHLCV DataFrame and return chart-ready JSON series.
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

import pandas as pd

from data.pine_parser import ParsedPine


# ── Public API ────────────────────────────────────────────────────────────────

def calculate_indicators(
    df: pd.DataFrame,
    parsed: ParsedPine,
    params: Dict | None = None,
) -> Tuple[List[Dict], List[Dict]]:
    """
    Calculate indicators for a parsed Pine Script.

    Returns
    -------
    overlays : list of {label, data, color, linewidth}  — rendered on main pane
    panes    : list of {label, data, color, type, pane} — rendered in sub-panes
    """
    if df is None or df.empty or "Close" not in df.columns:
        return [], []

    params = params or {}
    overlays: List[Dict] = []
    panes:    List[Dict] = []

    try:
        import ta  # noqa: F401
    except ImportError:
        return _fallback_indicators(df, parsed, params)

    inds = set(parsed.uses_indicators)

    # ── EMA ───────────────────────────────────────────────────────────────────
    if "EMA" in inds:
        period = _ip(params, ["length", "period"], 14)
        try:
            import ta.trend as tt
            s = tt.ema_indicator(df["Close"], window=period)
            overlays.append(_build(df, s, f"EMA({period})", "#00d4aa", 2))
        except Exception:
            pass

    # ── SMA ───────────────────────────────────────────────────────────────────
    if "SMA" in inds:
        period = _ip(params, ["length", "period"], 20)
        try:
            import ta.trend as tt
            s = tt.sma_indicator(df["Close"], window=period)
            overlays.append(_build(df, s, f"SMA({period})", "#4d9de0", 2))
        except Exception:
            pass

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    if "BOLLINGER_BANDS" in inds:
        period = _ip(params, ["length", "period"], 20)
        mult   = float(params.get("mult", params.get("stdDev", 2.0)))
        try:
            import ta.volatility as tv
            bb = tv.BollingerBands(df["Close"], window=period, window_dev=mult)
            overlays.append(_build(df, bb.bollinger_hband(),  "BB Upper",  "#4d9de0", 1))
            overlays.append(_build(df, bb.bollinger_mavg(),   "BB Middle", "#8b949e", 1))
            overlays.append(_build(df, bb.bollinger_lband(),  "BB Lower",  "#4d9de0", 1))
        except Exception:
            pass

    # ── VWAP ─────────────────────────────────────────────────────────────────
    if "VWAP" in inds and "Volume" in df.columns:
        try:
            import ta.volume as tvol
            vwap = tvol.VolumeWeightedAveragePrice(
                df["High"], df["Low"], df["Close"], df["Volume"]
            ).volume_weighted_average_price()
            overlays.append(_build(df, vwap, "VWAP", "#ff8c00", 2))
        except Exception:
            pass

    # ── Supertrend (manual calculation, ta lib doesn't expose it directly) ───
    if "SUPERTREND" in inds:
        atr_p  = _ip(params, ["atrPeriod", "period"], 10)
        factor = float(params.get("factor", 3.0))
        try:
            st_up, st_dn = _calc_supertrend(df, atr_p, factor)
            if st_up is not None:
                overlays.append(_build_raw(df, st_up,  "ST Up",   "#00d4aa", 2))
                overlays.append(_build_raw(df, st_dn,  "ST Down", "#ff4444", 2))
        except Exception:
            pass

    # ── RSI ───────────────────────────────────────────────────────────────────
    if "RSI" in inds:
        period = _ip(params, ["length", "period"], 14)
        try:
            import ta.momentum as tm
            s = tm.rsi(df["Close"], window=period)
            panes.append(_build(df, s, f"RSI({period})", "#f0ad4e", 1, pane="rsi"))
        except Exception:
            pass

    # ── MACD ─────────────────────────────────────────────────────────────────
    if "MACD" in inds:
        fast   = _ip(params, ["fastPeriod", "fast"],   12)
        slow   = _ip(params, ["slowPeriod", "slow"],   26)
        signal = _ip(params, ["signalPeriod", "signal"], 9)
        try:
            import ta.trend as tt
            obj = tt.MACD(df["Close"], window_fast=fast, window_slow=slow, window_sign=signal)
            panes.append(_build(df, obj.macd(),        "MACD",      "#00d4aa", 2, pane="macd"))
            panes.append(_build(df, obj.macd_signal(), "Signal",    "#ff6b6b", 1, pane="macd"))
            panes.append(_build(df, obj.macd_diff(),   "Histogram", "#4d9de0", 1, pane="macd",
                                series_type="histogram"))
        except Exception:
            pass

    # ── ATR ───────────────────────────────────────────────────────────────────
    if "ATR" in inds:
        period = _ip(params, ["period"], 14)
        try:
            import ta.volatility as tv
            s = tv.AverageTrueRange(df["High"], df["Low"], df["Close"], window=period).average_true_range()
            panes.append(_build(df, s, f"ATR({period})", "#7c3aed", 2, pane="atr"))
        except Exception:
            pass

    # ── ADX / DMI ─────────────────────────────────────────────────────────────
    if "ADX" in inds or "DMI" in inds:
        period = _ip(params, ["period"], 14)
        try:
            import ta.trend as tt
            obj = tt.ADXIndicator(df["High"], df["Low"], df["Close"], window=period)
            panes.append(_build(df, obj.adx(),     f"ADX({period})", "#f0ad4e", 2, pane="adx"))
            panes.append(_build(df, obj.adx_pos(), "+DI",            "#00d4aa", 1, pane="adx"))
            panes.append(_build(df, obj.adx_neg(), "-DI",            "#ff4444", 1, pane="adx"))
        except Exception:
            pass

    # ── Stochastic ────────────────────────────────────────────────────────────
    if "STOCHASTIC" in inds:
        k = _ip(params, ["kPeriod", "k"], 14)
        d = _ip(params, ["dPeriod", "d"], 3)
        try:
            import ta.momentum as tm
            obj = tm.StochasticOscillator(df["High"], df["Low"], df["Close"], window=k, smooth_window=d)
            panes.append(_build(df, obj.stoch(),        f"Stoch %K", "#00d4aa", 1, pane="stoch"))
            panes.append(_build(df, obj.stoch_signal(), f"Stoch %D", "#f0ad4e", 1, pane="stoch"))
        except Exception:
            pass

    # ── CCI ───────────────────────────────────────────────────────────────────
    if "CCI" in inds:
        period = _ip(params, ["period"], 20)
        try:
            import ta.trend as tt
            s = tt.cci(df["High"], df["Low"], df["Close"], window=period)
            panes.append(_build(df, s, f"CCI({period})", "#4d9de0", 1, pane="cci"))
        except Exception:
            pass

    return overlays, panes


# ── Fallback (no ta library) ─────────────────────────────────────────────────

def _fallback_indicators(
    df: pd.DataFrame, parsed: ParsedPine, params: Dict,
) -> Tuple[List[Dict], List[Dict]]:
    """Minimal pure-pandas fallback when `ta` is not installed."""
    overlays, panes = [], []
    inds = set(parsed.uses_indicators)
    if "EMA" in inds:
        p = _ip(params, ["length", "period"], 14)
        s = df["Close"].ewm(span=p, adjust=False).mean()
        overlays.append(_build(df, s, f"EMA({p})", "#00d4aa"))
    if "SMA" in inds:
        p = _ip(params, ["length", "period"], 20)
        s = df["Close"].rolling(p).mean()
        overlays.append(_build(df, s, f"SMA({p})", "#4d9de0"))
    if "RSI" in inds:
        p   = _ip(params, ["length", "period"], 14)
        d   = df["Close"].diff()
        g   = d.clip(lower=0).ewm(com=p - 1, min_periods=p).mean()
        l   = (-d.clip(upper=0)).ewm(com=p - 1, min_periods=p).mean()
        rs  = g / l.replace(0, float("nan"))
        s   = 100 - (100 / (1 + rs))
        panes.append(_build(df, s, f"RSI({p})", "#f0ad4e", pane="rsi"))
    return overlays, panes


# ── Supertrend manual calculation ─────────────────────────────────────────────

def _calc_supertrend(
    df: pd.DataFrame, period: int, factor: float
) -> Tuple[pd.Series | None, pd.Series | None]:
    try:
        import ta.volatility as tv
        hl2  = (df["High"] + df["Low"]) / 2
        atr  = tv.AverageTrueRange(df["High"], df["Low"], df["Close"], window=period).average_true_range()
        upper_band = hl2 + factor * atr
        lower_band = hl2 - factor * atr

        supertrend = pd.Series(index=df.index, dtype=float)
        direction  = pd.Series(index=df.index, dtype=int)

        for i in range(1, len(df)):
            if df["Close"].iloc[i] > upper_band.iloc[i - 1]:
                direction.iloc[i] = 1
            elif df["Close"].iloc[i] < lower_band.iloc[i - 1]:
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = direction.iloc[i - 1]

            if direction.iloc[i] == 1:
                supertrend.iloc[i] = lower_band.iloc[i]
            else:
                supertrend.iloc[i] = upper_band.iloc[i]

        st_up  = supertrend.where(direction == 1)
        st_dn  = supertrend.where(direction == -1)
        return st_up, st_dn
    except Exception:
        return None, None


# ── Series → dict conversion ──────────────────────────────────────────────────

def _build(
    df: pd.DataFrame,
    series: pd.Series,
    label: str,
    color: str,
    linewidth: int = 1,
    pane: str = "overlay",
    series_type: str = "line",
) -> Dict:
    data = []
    for idx, val in series.items():
        if val is None or (isinstance(val, float) and math.isnan(val)):
            continue
        try:
            ts = int(pd.Timestamp(idx).timestamp())
            data.append({"time": ts, "value": round(float(val), 6)})
        except Exception:
            continue
    return {
        "label":       label,
        "data":        data,
        "color":       color,
        "linewidth":   linewidth,
        "pane":        pane,
        "series_type": series_type,
    }


def _build_raw(
    df: pd.DataFrame,
    series: pd.Series,
    label: str,
    color: str,
    linewidth: int = 1,
) -> Dict:
    return _build(df, series, label, color, linewidth, pane="overlay")


# ── Parameter helper ──────────────────────────────────────────────────────────

def _ip(params: Dict, keys: List[str], default: int) -> int:
    """Look up the first matching key in params; return int default if missing."""
    for k in keys:
        if k in params:
            try:
                return max(1, int(float(params[k])))
            except (ValueError, TypeError):
                pass
    return default
