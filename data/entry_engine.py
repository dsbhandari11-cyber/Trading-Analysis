"""
Institutional Entry Engine — React to Liquidity Behavior

Detects institutional footprints and generates SMC-based entry setups.
Principle: react to confirmed liquidity behaviour, never predict tops/bottoms.

Components:
  - EMA trend alignment (EMA200 on HTF)
  - Liquidity sweep detection (sell-side / buy-side)
  - Stop-hunt detection (wick-based)
  - Volume profile: HVN / LVN / POC
  - Rejection candle pattern engine
  - Confluence-weighted confidence scoring
  - ATR-based entry / stop / take-profit logic
  - Multi-timeframe bias alignment
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Technical primitives
# ─────────────────────────────────────────────────────────────────────────────

def _ema_array(closes: np.ndarray, period: int) -> np.ndarray:
    """Full EMA array; returns NaN until the seed bar."""
    out  = np.full(len(closes), np.nan)
    seed = int(min(period, len(closes)))
    if seed < 1:
        return out
    out[seed - 1] = float(np.mean(closes[:seed]))
    mult = 2.0 / (period + 1)
    for i in range(seed, len(closes)):
        out[i] = closes[i] * mult + out[i - 1] * (1 - mult)
    return out


def ema_latest(closes: np.ndarray, period: int) -> float:
    arr   = _ema_array(closes, period)
    valid = arr[~np.isnan(arr)]
    return float(valid[-1]) if len(valid) else float(closes[-1])


def calc_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
             period: int = 14) -> float:
    if len(highs) < 2:
        return float(highs[-1] - lows[-1])
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - closes[:-1]),
                   np.abs(lows[1:]  - closes[:-1])),
    )
    return float(np.mean(tr[-period:]))


def calc_rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    d = np.diff(closes.astype(float))
    g = np.where(d > 0, d, 0.0)
    l = np.where(d < 0, -d, 0.0)
    return round(100 - 100 / (1 + float(np.mean(g[-period:])) /
                               (float(np.mean(l[-period:])) + 1e-9)), 1)


# ─────────────────────────────────────────────────────────────────────────────
# Volume Profile
# ─────────────────────────────────────────────────────────────────────────────

def build_volume_profile(df: pd.DataFrame, bins: int = 60) -> Optional[Dict]:
    """
    Distribute candle volume proportionally across the price range of each bar.
    Returns {prices, volumes, poc} or None when no volume data is available.
    """
    if "Volume" not in df.columns:
        return None
    total_vol = float(df["Volume"].sum())
    if total_vol < 1:
        return None

    p_min = float(df["Low"].min())
    p_max = float(df["High"].max())
    if p_max <= p_min:
        return None

    edges   = np.linspace(p_min, p_max, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    vols    = np.zeros(bins, dtype=float)

    H = df["High"].values.astype(float)
    L = df["Low"].values.astype(float)
    V = df["Volume"].values.astype(float)

    for i in range(len(df)):
        if V[i] <= 0 or H[i] == L[i]:
            continue
        mask = (centers >= L[i]) & (centers <= H[i])
        cnt  = int(mask.sum())
        if cnt:
            vols[mask] += V[i] / cnt

    poc_idx = int(np.argmax(vols))
    return {
        "prices":  centers,
        "volumes": vols,
        "poc":     float(centers[poc_idx]),
    }


def find_hvn_lvn(vp: Optional[Dict], cur: float, n: int = 4) -> Dict:
    """High Volume Nodes (HVN) and Low Volume Nodes (LVN) near current price."""
    empty = {"hvn": [], "lvn": [], "poc": None}
    if vp is None:
        return empty

    prices = vp["prices"]
    vols   = vp["volumes"]
    if vols.max() == 0:
        return empty

    avg = float(np.mean(vols))
    hvn = [float(p) for p, v in zip(prices, vols) if v > avg * 1.4]
    lvn = [float(p) for p, v in zip(prices, vols) if v < avg * 0.45]

    hvn_near = sorted(hvn, key=lambda p: abs(p - cur))[:n]
    lvn_near = sorted(lvn, key=lambda p: abs(p - cur))[:n]

    return {"hvn": hvn_near, "lvn": lvn_near, "poc": vp.get("poc")}


# ─────────────────────────────────────────────────────────────────────────────
# Liquidity Sweep Detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_liquidity_sweeps(df: pd.DataFrame, lookback: int = 120,
                             tol: float = 0.0035) -> Dict:
    """
    Sell-side sweep : equal lows pierced from below, price recovers above level.
    Buy-side  sweep : equal highs pierced from above, price drops below level.

    Returns the most-recent sweeps sorted by recency (bars ago).
    """
    recent = df.iloc[-lookback:].copy() if len(df) > lookback else df.copy()
    H  = recent["High"].values.astype(float)
    L  = recent["Low"].values.astype(float)
    C  = recent["Close"].values.astype(float)
    ts = list(recent.index)
    n  = len(recent)

    sell_sweeps: List[Dict] = []
    buy_sweeps:  List[Dict] = []
    seen_sell: set = set()
    seen_buy:  set = set()

    for i in range(3, n - 5):
        for j in range(i + 2, min(i + 30, n - 2)):
            # ── Equal lows (sell-side pool) ───────────────────────────────
            if abs(L[i] - L[j]) / (L[i] + 1e-9) < tol:
                level = (L[i] + L[j]) / 2
                lvl_key = round(level, 4)
                if lvl_key not in seen_sell:
                    for k in range(j + 1, min(j + 10, n)):
                        if L[k] < level * (1 - tol * 0.4) and C[k] > level:
                            seen_sell.add(lvl_key)
                            sell_sweeps.append({
                                "level":    round(float(level), 6),
                                "sweep_low":round(float(L[k]),  6),
                                "recovery": round(float(C[k]),  6),
                                "time":     ts[k],
                                "bars_ago": n - k,
                            })
                            break
                break  # one pair per i

            # ── Equal highs (buy-side pool) ───────────────────────────────
            if abs(H[i] - H[j]) / (H[i] + 1e-9) < tol:
                level = (H[i] + H[j]) / 2
                lvl_key = round(level, 4)
                if lvl_key not in seen_buy:
                    for k in range(j + 1, min(j + 10, n)):
                        if H[k] > level * (1 + tol * 0.4) and C[k] < level:
                            seen_buy.add(lvl_key)
                            buy_sweeps.append({
                                "level":     round(float(level),  6),
                                "sweep_high":round(float(H[k]),   6),
                                "recovery":  round(float(C[k]),   6),
                                "time":      ts[k],
                                "bars_ago":  n - k,
                            })
                            break
                break

    sell_sweeps.sort(key=lambda x: x["bars_ago"])
    buy_sweeps.sort(key=lambda x: x["bars_ago"])

    return {
        "sell_side":      sell_sweeps[:6],
        "buy_side":       buy_sweeps[:6],
        "has_sell_sweep": len(sell_sweeps) > 0,
        "has_buy_sweep":  len(buy_sweeps)  > 0,
        "recent_sell":    sell_sweeps[0] if sell_sweeps else None,
        "recent_buy":     buy_sweeps[0]  if buy_sweeps  else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Stop-Hunt Detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_stop_hunt(df: pd.DataFrame, lookback: int = 40) -> Dict:
    """
    Bullish stop-hunt : long lower wick (>2.5× body), candle closes bullish.
    Bearish stop-hunt : long upper wick (>2.5× body), candle closes bearish.
    """
    recent = df.iloc[-lookback:].copy() if len(df) > lookback else df.copy()
    O = recent["Open"].values.astype(float)
    H = recent["High"].values.astype(float)
    L = recent["Low"].values.astype(float)
    C = recent["Close"].values.astype(float)

    bull_hunts: List[Dict] = []
    bear_hunts: List[Dict] = []
    n = len(recent)

    for i in range(1, n):
        body = abs(C[i] - O[i])
        rng  = H[i] - L[i]
        if rng < 1e-9 or body < 1e-9:
            continue
        lw = min(O[i], C[i]) - L[i]
        uw = H[i] - max(O[i], C[i])

        if lw > body * 2.5 and lw > rng * 0.45 and C[i] > O[i]:
            bull_hunts.append({
                "low":        float(L[i]),
                "close":      float(C[i]),
                "wick_ratio": round(lw / body, 1),
                "bars_ago":   n - i,
            })
        if uw > body * 2.5 and uw > rng * 0.45 and C[i] < O[i]:
            bear_hunts.append({
                "high":       float(H[i]),
                "close":      float(C[i]),
                "wick_ratio": round(uw / body, 1),
                "bars_ago":   n - i,
            })

    bull_hunts.sort(key=lambda x: x["bars_ago"])
    bear_hunts.sort(key=lambda x: x["bars_ago"])

    return {
        "bull":     bull_hunts[:3],
        "bear":     bear_hunts[:3],
        "has_bull": len(bull_hunts) > 0,
        "has_bear": len(bear_hunts) > 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Rejection Candle
# ─────────────────────────────────────────────────────────────────────────────

def detect_rejection(df: pd.DataFrame, lookback: int = 5) -> Dict:
    """Detect hammer / shooting star / engulfing in the last N candles."""
    recent = df.iloc[-lookback:].copy() if len(df) > lookback else df.copy()
    O = recent["Open"].values.astype(float)
    H = recent["High"].values.astype(float)
    L = recent["Low"].values.astype(float)
    C = recent["Close"].values.astype(float)

    bull = False; bull_type = None
    bear = False; bear_type = None

    for i in range(len(recent)):
        body = abs(C[i] - O[i])
        rng  = H[i] - L[i]
        if rng < 1e-9:
            continue
        lw = min(O[i], C[i]) - L[i]
        uw = H[i] - max(O[i], C[i])

        if lw > body * 2 and lw > rng * 0.45 and not bull:
            bull = True; bull_type = "Hammer"
        if uw > body * 2 and uw > rng * 0.45 and not bear:
            bear = True; bear_type = "Shooting Star"

        if i > 0:
            if C[i] > O[i] and C[i-1] < O[i-1]:
                if C[i] > O[i-1] and O[i] < C[i-1]:
                    bull = True; bull_type = "Engulfing"
            if C[i] < O[i] and C[i-1] > O[i-1]:
                if C[i] < O[i-1] and O[i] > C[i-1]:
                    bear = True; bear_type = "Engulfing"

    return {"bullish": bull, "bearish": bear,
            "bull_type": bull_type, "bear_type": bear_type}


# ─────────────────────────────────────────────────────────────────────────────
# Confidence Scoring Engine
# ─────────────────────────────────────────────────────────────────────────────

_WEIGHTS: Dict[str, int] = {
    "bos_aligned":     2,
    "ema_aligned":     1,
    "order_block":     2,
    "fvg_present":     1,
    "liq_sweep":       3,
    "stop_hunt":       1,
    "volume_confirm":  2,
    "rsi_aligned":     1,
    "hvn_lvn":         1,
    "rejection":       1,
}
_MAX_SCORE = sum(_WEIGHTS.values())   # 15

_SIGNAL_LABELS: Dict[str, Tuple[str, str]] = {
    "bos_aligned":    ("BOS Aligned",       "+2"),
    "ema_aligned":    ("EMA200 Aligned",     "+1"),
    "order_block":    ("Order Block",        "+2"),
    "fvg_present":    ("FVG Present",        "+1"),
    "liq_sweep":      ("Liquidity Sweep",    "+3"),
    "stop_hunt":      ("Stop Hunt",          "+1"),
    "volume_confirm": ("Volume Expansion",   "+2"),
    "rsi_aligned":    ("RSI Aligned",        "+1"),
    "hvn_lvn":        ("HVN / LVN Node",     "+1"),
    "rejection":      ("Rejection Candle",   "+1"),
}


def score_signals(signals: Dict[str, bool]) -> Dict:
    score = sum(_WEIGHTS[k] for k, v in signals.items() if v and k in _WEIGHTS)
    pct   = round(score / _MAX_SCORE * 100)

    if   score >= 10: quality = "Strong"
    elif score >= 7:  quality = "Moderate"
    elif score >= 4:  quality = "Weak"
    else:             quality = "Avoid"

    if   score >= 10: inst_bias = "Institutional"
    elif score >= 7:  inst_bias = "Developing"
    elif score >= 4:  inst_bias = "Retail"
    else:             inst_bias = "No Signal"

    return {
        "score":      score,
        "max_score":  _MAX_SCORE,
        "confidence": pct,
        "quality":    quality,
        "inst_bias":  inst_bias,
        "signals":    signals,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Liquidity narrative builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_narrative(direction: str, sweeps: Dict, sh: Dict,
                     ob: bool, fvg: bool, bos: bool, zone: str) -> List[str]:
    lines: List[str] = []
    if direction == "long":
        rs = sweeps.get("recent_sell")
        if rs:
            lines.append(
                f"Sell-side liquidity swept at {rs['level']:,.4f} — "
                f"equal-low stops triggered, smart money absorbed supply."
            )
        if sh.get("has_bull"):
            h = sh["bull"][0]
            lines.append(
                f"Stop-hunt wick detected ({h['wick_ratio']:.1f}× body) — "
                "retail stops flushed below key level, bullish recovery confirms."
            )
        if ob:
            lines.append(
                "Price reacting within a Bullish Order Block — "
                "institutional demand zone is active."
            )
        if fvg:
            lines.append(
                "Bullish Fair Value Gap present — "
                "price may seek upside imbalance fill as institutions defend the gap."
            )
        if bos:
            lines.append(
                "Bullish Break of Structure confirmed — "
                "higher high established, buy-side momentum building."
            )
        if zone == "Discount":
            lines.append(
                "Price is trading in the Discount zone (below equilibrium) — "
                "optimal range for institutional LONG accumulation."
            )
        if not lines:
            lines.append(
                "No confirmed sell-side sweep yet. "
                "Monitor equal lows for a potential liquidity grab before entering."
            )
    else:
        rb = sweeps.get("recent_buy")
        if rb:
            lines.append(
                f"Buy-side liquidity swept at {rb['level']:,.4f} — "
                f"equal-high stops triggered, smart money distributed supply."
            )
        if sh.get("has_bear"):
            h = sh["bear"][0]
            lines.append(
                f"Stop-hunt wick detected ({h['wick_ratio']:.1f}× body) — "
                "retail longs flushed above key level, bearish rejection confirms."
            )
        if ob:
            lines.append(
                "Price reacting within a Bearish Order Block — "
                "institutional supply zone is active."
            )
        if fvg:
            lines.append(
                "Bearish Fair Value Gap present — "
                "price seeking downside imbalance fill."
            )
        if bos:
            lines.append(
                "Bearish Break of Structure confirmed — "
                "lower low established, sell-side momentum building."
            )
        if zone == "Premium":
            lines.append(
                "Price is trading in the Premium zone (above equilibrium) — "
                "optimal range for institutional SHORT distribution."
            )
        if not lines:
            lines.append(
                "No confirmed buy-side sweep yet. "
                "Monitor equal highs for a potential liquidity grab before entering."
            )
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Multi-timeframe bias
# ─────────────────────────────────────────────────────────────────────────────

def calc_mtf_bias(df_htf: Optional[pd.DataFrame],
                  df_main: pd.DataFrame) -> Dict:
    def _bias(df: Optional[pd.DataFrame], label: str) -> Dict:
        if df is None or len(df) < 20:
            return {"label": label, "bias": "neutral", "ema200": None}
        c   = df["Close"].values.astype(float)
        e   = ema_latest(c, min(200, len(c) - 1))
        mid = max(len(c) // 5, 5)
        sl  = c[-1] - c[-mid]
        if c[-1] > e and sl > 0:   b = "bullish"
        elif c[-1] < e and sl < 0: b = "bearish"
        else:                      b = "neutral"
        return {"label": label, "bias": b, "ema200": round(e, 6)}

    htf_d  = _bias(df_htf,  "1H")
    main_d = _bias(df_main, "Main")
    aligned = htf_d["bias"] == main_d["bias"] and htf_d["bias"] != "neutral"

    return {
        "htf":      htf_d,
        "main":     main_d,
        "aligned":  aligned,
        "combined": htf_d["bias"] if aligned else "neutral",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main entry-signal generator
# ─────────────────────────────────────────────────────────────────────────────

def generate_entry_signal(
    df_htf:   Optional[pd.DataFrame],
    df_main:  pd.DataFrame,
    ob_data:  Dict,
    fvg_data: Dict,
    ms_data:  Dict,
) -> Dict:
    """
    Generate a full institutional entry analysis.

    df_htf  : 1H data for EMA200 bias (may be None)
    df_main : Current-TF chart data
    ob_data : output of detect_order_blocks()
    fvg_data: output of detect_fvg()
    ms_data : output of detect_market_structure()
    """
    if df_main is None or len(df_main) < 20:
        return {}

    C  = df_main["Close"].values.astype(float)
    H  = df_main["High"].values.astype(float)
    L  = df_main["Low"].values.astype(float)
    V  = (df_main["Volume"].values.astype(float)
          if "Volume" in df_main.columns else np.ones(len(df_main)))

    cur     = float(C[-1])
    atr_v   = calc_atr(H, L, C, 14)
    rsi_v   = calc_rsi(C, 14)

    # Volume expansion check
    avg_vol   = float(np.mean(V[-20:])) if len(V) >= 20 else float(np.mean(V))
    vol_spike = float(V[-1]) > avg_vol * 1.20

    # EMA200 on HTF
    htf_c    = (df_htf["Close"].values.astype(float)
                if df_htf is not None and len(df_htf) >= 20 else C)
    ema200   = ema_latest(htf_c, min(200, len(htf_c) - 1))
    ema_bull = float(htf_c[-1]) > ema200
    ema_bear = float(htf_c[-1]) < ema200

    # MTF bias
    bias = calc_mtf_bias(df_htf, df_main)

    # Structure signals
    bos_list = ms_data.get("bos", [])
    bull_bos = any(b["direction"] == "bullish" for b in bos_list)
    bear_bos = any(b["direction"] == "bearish" for b in bos_list)
    zone     = ms_data.get("zone", "Neutral")
    eq       = float(ms_data.get("equilibrium", cur))
    rh       = float(ms_data.get("recent_high",  cur * 1.02))
    rl       = float(ms_data.get("recent_low",   cur * 0.98))
    liq_pool = ms_data.get("liquidity", [])

    # OBs / FVGs
    a_bull_ob  = bool(ob_data.get("active_bullish"))
    a_bear_ob  = bool(ob_data.get("active_bearish"))
    a_bull_fvg = bool(fvg_data.get("bullish"))
    a_bear_fvg = bool(fvg_data.get("bearish"))

    # Sweeps, stop hunts, rejections
    sweeps    = detect_liquidity_sweeps(df_main)
    stop_hunt = detect_stop_hunt(df_main)
    rejection = detect_rejection(df_main)

    # Volume profile
    vp         = build_volume_profile(df_main)
    hvn_lvn_d  = find_hvn_lvn(vp, cur)
    hvn_signal = bool(hvn_lvn_d["hvn"] or hvn_lvn_d["lvn"])

    # ── Long signals ──────────────────────────────────────────────────────────
    long_sigs: Dict[str, bool] = {
        "bos_aligned":    bull_bos,
        "ema_aligned":    ema_bull,
        "order_block":    a_bull_ob,
        "fvg_present":    a_bull_fvg,
        "liq_sweep":      sweeps["has_sell_sweep"],
        "stop_hunt":      stop_hunt["has_bull"],
        "volume_confirm": vol_spike,
        "rsi_aligned":    25 < rsi_v < 62,
        "hvn_lvn":        hvn_signal,
        "rejection":      rejection["bullish"],
    }

    # ── Short signals ─────────────────────────────────────────────────────────
    short_sigs: Dict[str, bool] = {
        "bos_aligned":    bear_bos,
        "ema_aligned":    ema_bear,
        "order_block":    a_bear_ob,
        "fvg_present":    a_bear_fvg,
        "liq_sweep":      sweeps["has_buy_sweep"],
        "stop_hunt":      stop_hunt["has_bear"],
        "volume_confirm": vol_spike,
        "rsi_aligned":    38 < rsi_v < 75,
        "hvn_lvn":        hvn_signal,
        "rejection":      rejection["bearish"],
    }

    long_score  = score_signals(long_sigs)
    short_score = score_signals(short_sigs)

    # ── Entry / SL / TP (long) ────────────────────────────────────────────────
    sl_mult = 1.5
    long_entry = cur

    if sweeps["sell_side"]:
        sl_ref_long = min(s["sweep_low"] for s in sweeps["sell_side"][:2])
        long_sl     = min(float(sl_ref_long) * 0.997, cur - atr_v * sl_mult)
    elif ob_data.get("active_bullish"):
        long_sl = float(ob_data["active_bullish"][-1]["low"]) * 0.998
    else:
        long_sl = cur - atr_v * sl_mult

    hvn_above  = sorted([h for h in hvn_lvn_d["hvn"] if h > cur])
    liq_above  = sorted([l["price"] for l in liq_pool if l["price"] > cur])
    long_tp1   = min(
        hvn_above[0] if hvn_above else cur + atr_v * 2,
        liq_above[0] if liq_above else cur + atr_v * 2,
        rh,
    )
    long_tp2   = rh
    long_risk  = max(cur - long_sl, 1e-9)
    long_rr1   = round((long_tp1 - cur) / long_risk, 2)
    long_rr2   = round((long_tp2 - cur) / long_risk, 2)

    # ── Entry / SL / TP (short) ───────────────────────────────────────────────
    short_entry = cur

    if sweeps["buy_side"]:
        sl_ref_short = max(s["sweep_high"] for s in sweeps["buy_side"][:2])
        short_sl     = max(float(sl_ref_short) * 1.003, cur + atr_v * sl_mult)
    elif ob_data.get("active_bearish"):
        short_sl = float(ob_data["active_bearish"][-1]["high"]) * 1.002
    else:
        short_sl = cur + atr_v * sl_mult

    hvn_below   = sorted([h for h in hvn_lvn_d["hvn"] if h < cur], reverse=True)
    liq_below   = sorted([l["price"] for l in liq_pool if l["price"] < cur], reverse=True)
    short_tp1   = max(
        hvn_below[0] if hvn_below else cur - atr_v * 2,
        liq_below[0] if liq_below else cur - atr_v * 2,
        rl,
    )
    short_tp2   = rl
    short_risk  = max(short_sl - cur, 1e-9)
    short_rr1   = round((cur - short_tp1) / short_risk, 2)
    short_rr2   = round((cur - short_tp2) / short_risk, 2)

    # ── Narratives ────────────────────────────────────────────────────────────
    long_narrative  = _build_narrative("long",  sweeps, stop_hunt,
                                       a_bull_ob, a_bull_fvg, bull_bos, zone)
    short_narrative = _build_narrative("short", sweeps, stop_hunt,
                                       a_bear_ob, a_bear_fvg, bear_bos, zone)

    # ── Signal table rows (for display) ──────────────────────────────────────
    signal_rows = [
        {
            "signal": label,
            "weight": weight,
            "long":   long_sigs.get(key, False),
            "short":  short_sigs.get(key, False),
        }
        for key, (label, weight) in _SIGNAL_LABELS.items()
    ]

    return {
        "long": {
            **long_score,
            "entry":     round(long_entry,  6),
            "sl":        round(long_sl,     6),
            "tp1":       round(long_tp1,    6),
            "tp2":       round(long_tp2,    6),
            "rr1":       long_rr1,
            "rr2":       long_rr2,
            "narrative": long_narrative,
            "rejection": rejection.get("bull_type"),
        },
        "short": {
            **short_score,
            "entry":     round(short_entry, 6),
            "sl":        round(short_sl,    6),
            "tp1":       round(short_tp1,   6),
            "tp2":       round(short_tp2,   6),
            "rr1":       short_rr1,
            "rr2":       short_rr2,
            "narrative": short_narrative,
            "rejection": rejection.get("bear_type"),
        },
        "signal_rows":  signal_rows,
        "sweeps":       sweeps,
        "stop_hunt":    stop_hunt,
        "vp":           vp,
        "hvn_lvn":      hvn_lvn_d,
        "atr":          round(atr_v, 6),
        "rsi":          rsi_v,
        "ema200":       round(ema200, 6),
        "ema_bias":     "bullish" if ema_bull else "bearish",
        "bias":         bias,
        "zone":         zone,
        "trend":        ms_data.get("trend", "neutral"),
    }
