"""
Technical analysis calculations using the `ta` library.
All functions accept a pandas DataFrame with OHLCV columns.
"""

import numpy as np
import pandas as pd
import streamlit as st
from typing import Optional, Tuple
from config import CACHE_TTL, RSI_OVERBOUGHT, RSI_OVERSOLD, VOLUME_SPIKE_MULTIPLIER

try:
    import ta
    _TA_AVAILABLE = True
except ImportError:
    _TA_AVAILABLE = False


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if df is None or df.empty or "Close" not in df.columns:
        return pd.Series(dtype=float)
    if _TA_AVAILABLE:
        try:
            indicator = ta.momentum.RSIIndicator(close=df["Close"], window=period)
            return indicator.rsi()
        except Exception:
            pass
    # Fallback: manual RSI
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calculate_volume_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    if df is None or df.empty or "Volume" not in df.columns:
        return pd.Series(dtype=float)
    vol_ma = df["Volume"].rolling(window=period, min_periods=1).mean()
    return df["Volume"] / vol_ma.replace(0, np.nan)


def calculate_macd(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series, pd.Series]:
    if df is None or df.empty or "Close" not in df.columns:
        empty = pd.Series(dtype=float)
        return empty, empty, empty
    if _TA_AVAILABLE:
        try:
            macd_ind = ta.trend.MACD(close=df["Close"])
            return macd_ind.macd(), macd_ind.macd_signal(), macd_ind.macd_diff()
        except Exception:
            pass
    empty = pd.Series(dtype=float)
    return empty, empty, empty


def calculate_bollinger(df: pd.DataFrame, period: int = 20) -> Tuple[pd.Series, pd.Series, pd.Series]:
    if df is None or df.empty or "Close" not in df.columns:
        empty = pd.Series(dtype=float)
        return empty, empty, empty
    if _TA_AVAILABLE:
        try:
            bb = ta.volatility.BollingerBands(close=df["Close"], window=period)
            return bb.bollinger_hband(), bb.bollinger_mavg(), bb.bollinger_lband()
        except Exception:
            pass
    empty = pd.Series(dtype=float)
    return empty, empty, empty


def calculate_ema(df: pd.DataFrame, period: int = 20) -> pd.Series:
    if df is None or df.empty or "Close" not in df.columns:
        return pd.Series(dtype=float)
    return df["Close"].ewm(span=period, adjust=False).mean()


def price_change_pct(df: pd.DataFrame, days: int = 5) -> float:
    if df is None or len(df) < days + 1:
        return 0.0
    try:
        cur = float(df["Close"].iloc[-1])
        past = float(df["Close"].iloc[-(days + 1)])
        return (cur - past) / past * 100 if past else 0.0
    except Exception:
        return 0.0


def is_volume_spike(df: pd.DataFrame, multiplier: float = VOLUME_SPIKE_MULTIPLIER, period: int = 20) -> bool:
    if df is None or df.empty or "Volume" not in df.columns:
        return False
    try:
        vol_ratio = calculate_volume_ratio(df, period)
        return float(vol_ratio.iloc[-1]) >= multiplier
    except Exception:
        return False


def is_price_breakout(df: pd.DataFrame, period: int = 20) -> bool:
    """Price closes above the rolling high of last `period` bars."""
    if df is None or len(df) < period + 1:
        return False
    try:
        rolling_high = df["Close"].iloc[-(period + 1):-1].max()
        return float(df["Close"].iloc[-1]) > rolling_high
    except Exception:
        return False


def momentum_score(rsi: float, vol_ratio: float, price_chg_5d: float) -> float:
    """Composite momentum score 0–100."""
    rsi_contribution = max(0.0, min(50.0, (rsi - 50.0))) if rsi == rsi else 0.0
    vol_contribution = max(0.0, min(30.0, (vol_ratio - 1.0) * 20)) if vol_ratio == vol_ratio else 0.0
    price_contribution = max(0.0, min(20.0, price_chg_5d * 2)) if price_chg_5d == price_chg_5d else 0.0
    return round(rsi_contribution + vol_contribution + price_contribution, 1)


@st.cache_data(ttl=CACHE_TTL * 3, show_spinner=False)
def compute_technicals_for_symbol(symbol: str, df_json: str) -> dict:
    """
    Accepts history as JSON string (for caching compatibility).
    Returns dict with rsi, vol_ratio, price_chg_5d, momentum_score, breakout, reversal.
    """
    try:
        df = pd.read_json(df_json)
        if df.empty:
            return _empty_technicals()

        rsi_series = calculate_rsi(df)
        rsi = float(rsi_series.iloc[-1]) if len(rsi_series) > 0 else float("nan")

        vol_ratio_series = calculate_volume_ratio(df)
        vol_ratio = float(vol_ratio_series.iloc[-1]) if len(vol_ratio_series) > 0 else float("nan")

        price_chg_5d = price_change_pct(df, days=5)
        price_chg_1d = price_change_pct(df, days=1)
        current_price = float(df["Close"].iloc[-1]) if len(df) > 0 else float("nan")

        breakout = is_price_breakout(df) and is_volume_spike(df, 1.5)
        reversal = (rsi < RSI_OVERSOLD) if rsi == rsi else False

        score = momentum_score(rsi, vol_ratio, price_chg_5d)

        return {
            "rsi": round(rsi, 2) if rsi == rsi else None,
            "vol_ratio": round(vol_ratio, 2) if vol_ratio == vol_ratio else None,
            "price_chg_5d": round(price_chg_5d, 2),
            "price_chg_1d": round(price_chg_1d, 2),
            "current_price": round(current_price, 2) if current_price == current_price else None,
            "momentum_score": score,
            "breakout": breakout,
            "reversal": reversal,
        }
    except Exception:
        return _empty_technicals()


def _empty_technicals() -> dict:
    return {
        "rsi": None,
        "vol_ratio": None,
        "price_chg_5d": None,
        "price_chg_1d": None,
        "current_price": None,
        "momentum_score": 0.0,
        "breakout": False,
        "reversal": False,
    }
