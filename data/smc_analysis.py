"""
Smart Money Concepts (SMC) analysis engine.
Detects institutional order flow: order blocks, FVGs, IFVGs, BOS/CHoCH,
premium/discount zones, liquidity levels, and market bias.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, List, Optional


# ── Swing point detection ──────────────────────────────────────────────────────

def _swing_points(highs: np.ndarray, lows: np.ndarray, left: int = 3, right: int = 3):
    """Local pivot highs and lows (index lists)."""
    sh, sl = [], []
    n = len(highs)
    for i in range(left, n - right):
        if all(highs[i] >= highs[i - j] for j in range(1, left + 1)) and \
           all(highs[i] >= highs[i + j] for j in range(1, right + 1)):
            sh.append(i)
        if all(lows[i] <= lows[i - j] for j in range(1, left + 1)) and \
           all(lows[i] <= lows[i + j] for j in range(1, right + 1)):
            sl.append(i)
    return sh, sl


# ── Order Blocks ───────────────────────────────────────────────────────────────

def detect_order_blocks(df: pd.DataFrame, lookback: int = 120) -> Dict:
    """
    Bullish OB : last bearish candle before an impulsive bullish leg that breaks structure.
    Bearish OB : last bullish candle before an impulsive bearish leg that breaks structure.
    """
    recent = df.iloc[-lookback:].copy() if len(df) > lookback else df.copy()
    opens  = recent["Open"].values.astype(float)
    highs  = recent["High"].values.astype(float)
    lows   = recent["Low"].values.astype(float)
    closes = recent["Close"].values.astype(float)
    times  = [int(pd.Timestamp(t).timestamp()) for t in recent.index]

    cur    = closes[-1]
    n      = len(recent)
    bull_obs, bear_obs = [], []

    for i in range(2, n - 3):
        rng = highs[i] - lows[i]
        if rng == 0:
            continue
        body = abs(closes[i] - opens[i])

        # Impulse confirmation: 3-bar window after the candidate
        lk  = min(i + 4, n)
        imp_up = float(np.max(closes[i + 1:lk])) > highs[i] * 1.002
        imp_dn = float(np.min(closes[i + 1:lk])) < lows[i]  * 0.998

        if closes[i] < opens[i] and imp_up:        # bearish candle → bullish OB
            mitigated = cur < closes[i]
            bull_obs.append({
                "time_start": times[i],
                "time_end":   None,
                "high":       float(opens[i]),
                "low":        float(closes[i]),
                "mitigated":  mitigated,
                "strength":   round(body / rng * 100, 1),
                "idx":        i,
            })

        if closes[i] > opens[i] and imp_dn:        # bullish candle → bearish OB
            mitigated = cur > closes[i]
            bear_obs.append({
                "time_start": times[i],
                "time_end":   None,
                "high":       float(closes[i]),
                "low":        float(opens[i]),
                "mitigated":  mitigated,
                "strength":   round(body / rng * 100, 1),
                "idx":        i,
            })

    active_bull = [ob for ob in bull_obs if not ob["mitigated"]][-5:]
    active_bear = [ob for ob in bear_obs if not ob["mitigated"]][-5:]

    return {
        "bullish":        bull_obs[-8:],
        "bearish":        bear_obs[-8:],
        "active_bullish": active_bull,
        "active_bearish": active_bear,
    }


# ── Fair Value Gaps ────────────────────────────────────────────────────────────

def detect_fvg(df: pd.DataFrame, lookback: int = 150) -> Dict:
    """
    Bullish FVG : candle[i-1].high < candle[i+1].low   (gap above middle candle)
    Bearish FVG : candle[i-1].low  > candle[i+1].high  (gap below middle candle)
    Filled FVGs that price re-entered are promoted to IFVGs (flipped imbalance).
    """
    recent = df.iloc[-lookback:].copy() if len(df) > lookback else df.copy()
    highs  = recent["High"].values.astype(float)
    lows   = recent["Low"].values.astype(float)
    closes = recent["Close"].values.astype(float)
    times  = [int(pd.Timestamp(t).timestamp()) for t in recent.index]

    cur = closes[-1]
    bull_fvg, bear_fvg = [], []

    for i in range(1, len(recent) - 1):
        # Bullish FVG
        if highs[i - 1] < lows[i + 1]:
            top    = float(lows[i + 1])
            bottom = float(highs[i - 1])
            gap    = top - bottom
            if gap > 0:
                filled = (bottom <= cur <= top)
                bull_fvg.append({
                    "time_start": times[i],
                    "high":       top,
                    "low":        bottom,
                    "gap_pct":    round(gap / (bottom + 1e-9) * 100, 3),
                    "filled":     filled,
                    "active":     cur > bottom,
                })

        # Bearish FVG
        if lows[i - 1] > highs[i + 1]:
            top    = float(lows[i - 1])
            bottom = float(highs[i + 1])
            gap    = top - bottom
            if gap > 0:
                filled = (bottom <= cur <= top)
                bear_fvg.append({
                    "time_start": times[i],
                    "high":       top,
                    "low":        bottom,
                    "gap_pct":    round(gap / (bottom + 1e-9) * 100, 3),
                    "filled":     filled,
                    "active":     cur < top,
                })

    # IFVGs: filled FVGs that have been mitigated (role-flip)
    bull_ifvg = [f for f in bull_fvg if f["filled"]][-4:]
    bear_ifvg = [f for f in bear_fvg if f["filled"]][-4:]

    active_bull = [f for f in bull_fvg if not f["filled"] and f["active"]][-5:]
    active_bear = [f for f in bear_fvg if not f["filled"] and f["active"]][-5:]

    return {
        "bullish":   active_bull,
        "bearish":   active_bear,
        "bull_ifvg": bull_ifvg,
        "bear_ifvg": bear_ifvg,
        "all_bull":  bull_fvg[-8:],
        "all_bear":  bear_fvg[-8:],
    }


# ── Market Structure ───────────────────────────────────────────────────────────

def detect_market_structure(df: pd.DataFrame, lookback: int = 200) -> Dict:
    """
    Identifies swing H/L, BOS, CHoCH, trend bias, premium/discount, liquidity pools.
    """
    recent = df.iloc[-lookback:].copy() if len(df) > lookback else df.copy()
    highs  = recent["High"].values.astype(float)
    lows   = recent["Low"].values.astype(float)
    closes = recent["Close"].values.astype(float)
    times  = [int(pd.Timestamp(t).timestamp()) for t in recent.index]

    sh_idxs, sl_idxs = _swing_points(highs, lows)
    swing_highs = [{"price": float(highs[i]), "time": times[i], "idx": i} for i in sh_idxs]
    swing_lows  = [{"price": float(lows[i]),  "time": times[i], "idx": i} for i in sl_idxs]

    cur = closes[-1]

    # Trend: compare recent half vs first half
    mid   = max(len(closes) // 4, 5)
    trend = "bullish" if closes[-1] > closes[-mid] else "bearish"

    # BOS events
    bos, choch = [], []
    for sh in swing_highs[-5:]:
        if cur > sh["price"] * 1.001:
            bos.append({"direction": "bullish", "level": sh["price"], "time": sh["time"]})
    for sl in swing_lows[-5:]:
        if cur < sl["price"] * 0.999:
            bos.append({"direction": "bearish", "level": sl["price"], "time": sl["time"]})

    # CHoCH: break opposite to current trend
    if trend == "bullish" and swing_lows:
        last_sl = swing_lows[-1]
        if cur < last_sl["price"] * 0.999:
            choch.append({"direction": "bearish", "level": last_sl["price"], "time": last_sl["time"]})
    if trend == "bearish" and swing_highs:
        last_sh = swing_highs[-1]
        if cur > last_sh["price"] * 1.001:
            choch.append({"direction": "bullish", "level": last_sh["price"], "time": last_sh["time"]})

    # Premium / Discount
    rh = max((sh["price"] for sh in swing_highs), default=float(np.max(highs)))
    rl = min((sl["price"] for sl in swing_lows),  default=float(np.min(lows)))
    eq = (rh + rl) / 2
    zone_label = "Premium" if cur > eq else "Discount"
    eq_pct = round((cur - eq) / (rh - rl + 1e-9) * 100, 1)

    # Equal highs / lows (liquidity pools)
    liq = []
    tol = 0.003
    for i in range(len(swing_highs)):
        for j in range(i + 1, len(swing_highs)):
            a, b = swing_highs[i]["price"], swing_highs[j]["price"]
            if abs(a - b) / (a + 1e-9) < tol:
                liq.append({"type": "EQH", "price": (a + b) / 2, "time": swing_highs[j]["time"]})
                break
    for i in range(len(swing_lows)):
        for j in range(i + 1, len(swing_lows)):
            a, b = swing_lows[i]["price"], swing_lows[j]["price"]
            if abs(a - b) / (a + 1e-9) < tol:
                liq.append({"type": "EQL", "price": (a + b) / 2, "time": swing_lows[j]["time"]})
                break

    return {
        "trend":         trend,
        "swing_highs":   swing_highs[-6:],
        "swing_lows":    swing_lows[-6:],
        "bos":           bos[-4:],
        "choch":         choch[-3:],
        "zone":          zone_label,
        "eq_pct":        eq_pct,
        "equilibrium":   float(eq),
        "recent_high":   float(rh),
        "recent_low":    float(rl),
        "liquidity":     liq[-6:],
    }


# ── Technical helpers ──────────────────────────────────────────────────────────

def _rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    d      = np.diff(closes.astype(float))
    gains  = np.where(d > 0, d, 0.0)
    losses = np.where(d < 0, -d, 0.0)
    ag     = float(np.mean(gains[-period:]))
    al     = float(np.mean(losses[-period:]))
    return round(100 - 100 / (1 + ag / (al + 1e-9)), 1)


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    if len(highs) < 2:
        return float(highs[-1] - lows[-1])
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])),
    )
    return float(np.mean(tr[-period:]))


# ── Institutional analysis ─────────────────────────────────────────────────────

def institutional_analysis(df: pd.DataFrame) -> Dict:
    """
    Rule-based institutional analysis: bias, probabilities, entry/SL/TP zones,
    session context, volatility, momentum, trend strength.
    """
    if df is None or len(df) < 20:
        return {}

    closes  = df["Close"].values.astype(float)
    highs   = df["High"].values.astype(float)
    lows    = df["Low"].values.astype(float)
    vols    = df["Volume"].values.astype(float) if "Volume" in df.columns else np.ones(len(df))

    cur = closes[-1]

    rsi_val  = _rsi(closes)
    atr_val  = _atr(highs, lows, closes)
    vol_pct  = round(atr_val / (cur + 1e-9) * 100, 2)
    mom_10   = round((closes[-1] - closes[-10]) / (closes[-10] + 1e-9) * 100, 2) if len(closes) > 10 else 0.0

    # ADX proxy
    if len(closes) > 20:
        dm_up   = np.maximum(np.diff(highs[-21:]), 0)
        dm_dn   = np.maximum(-np.diff(lows[-21:]), 0)
        dx      = np.abs(dm_up - dm_dn) / (dm_up + dm_dn + 1e-9)
        adx_val = round(float(np.mean(dx) * 100), 1)
    else:
        adx_val = 25.0

    # Relative volume
    avg_vol = float(np.mean(vols[-20:])) if len(vols) >= 20 else float(np.mean(vols))
    rvol    = round(vols[-1] / (avg_vol + 1e-9), 2) if avg_vol else 1.0

    # Price position in 50-bar range
    h50 = float(np.max(highs[-50:])) if len(highs) >= 50 else float(np.max(highs))
    l50 = float(np.min(lows[-50:]))  if len(lows)  >= 50 else float(np.min(lows))
    eq  = (h50 + l50) / 2.0

    # Bias scoring (0-100, >50 = bullish)
    score = 50
    score += (rsi_val - 50) * 0.4
    score += min(max(mom_10 * 3, -15), 15)
    score += 5 if rvol > 1.3 else (-3 if rvol < 0.7 else 0)
    score += 5 if cur > eq else -5
    score += min(max((adx_val - 25) * 0.3, -8), 8)
    bull_prob = int(min(max(round(score), 5), 95))
    bear_prob = 100 - bull_prob

    if   bull_prob >= 68: bias = "Strong Bullish"
    elif bull_prob >= 55: bias = "Bullish"
    elif bull_prob >= 45: bias = "Neutral"
    elif bull_prob >= 32: bias = "Bearish"
    else:                 bias = "Strong Bearish"

    # Session
    try:
        import pytz
        from datetime import datetime
        ny_hour = datetime.now(pytz.timezone("America/New_York")).hour
        if   9  <= ny_hour < 16: session, liq_dir = "New York",  "USD momentum"
        elif 3  <= ny_hour < 11: session, liq_dir = "London",    "EUR/GBP liquidity"
        elif 20 <= ny_hour or ny_hour < 4: session, liq_dir = "Asian",  "Range consolidation"
        else:                    session, liq_dir = "Overlap",   "High volatility"
    except Exception:
        session, liq_dir = "—", "—"

    # Momentum label
    if   mom_10 >  3: mom_label = "Strong ↑"
    elif mom_10 >  1: mom_label = "Mild ↑"
    elif mom_10 < -3: mom_label = "Strong ↓"
    elif mom_10 < -1: mom_label = "Mild ↓"
    else:             mom_label = "Flat"

    # Entry / SL / TP (Fibonacci-based on 50-bar range)
    rng  = h50 - l50
    entry_bull = round(l50 + rng * 0.382, 6)
    entry_bear = round(h50 - rng * 0.382, 6)
    sl_bull    = round(l50 - atr_val * 0.5, 6)
    sl_bear    = round(h50 + atr_val * 0.5, 6)
    tp1_bull   = round(eq,  6)
    tp2_bull   = round(h50, 6)
    tp1_bear   = round(eq,  6)
    tp2_bear   = round(l50, 6)

    # RR
    rr_bull = round((tp1_bull - entry_bull) / (entry_bull - sl_bull + 1e-9), 1)
    rr_bear = round((entry_bear - tp1_bear) / (sl_bear - entry_bear + 1e-9), 1)

    return {
        "bias":         bias,
        "bull_prob":    bull_prob,
        "bear_prob":    bear_prob,
        "rsi":          rsi_val,
        "momentum":     mom_10,
        "momentum_lbl": mom_label,
        "volatility":   vol_pct,
        "trend_str":    adx_val,
        "rvol":         rvol,
        "session":      session,
        "liq_dir":      liq_dir,
        "position":     "Premium" if cur > eq else "Discount",
        "equilibrium":  round(eq, 6),
        "range_high":   round(h50, 6),
        "range_low":    round(l50, 6),
        "entry_bull":   entry_bull,
        "entry_bear":   entry_bear,
        "sl_bull":      sl_bull,
        "sl_bear":      sl_bear,
        "tp1_bull":     tp1_bull,
        "tp2_bull":     tp2_bull,
        "tp1_bear":     tp1_bear,
        "tp2_bear":     tp2_bear,
        "rr_bull":      rr_bull,
        "rr_bear":      rr_bear,
    }
