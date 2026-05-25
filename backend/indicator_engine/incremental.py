"""
Incremental Indicator Engine
=============================
All indicators update in O(1) per tick — no full-series recomputation.

Supported:
  EMA  (9, 21, 50, 200) — exponential moving average
  RSI  (14)             — Wilder smoothing RSI
  ATR  (14)             — Wilder smoothing ATR
  VWAP                  — session-reset VWAP (resets each UTC day)
  MACD (12,26,9)        — difference of two EMAs + signal EMA

State is initialized by replaying the historical candles (initialize_from_history).
After that, each live tick costs O(1) arithmetic — no pandas, no reallocs.

Thread safety: RLock per engine instance, OK for multiple asyncio coroutines
calling from a single event loop thread.
"""

import math
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..data_engine.candle_store import CandleStore

# ── Per-indicator state dataclasses ──────────────────────────────────────────

@dataclass
class _EMAState:
    period: int
    value:  Optional[float] = None

    def __post_init__(self):
        self._k = 2.0 / (self.period + 1)

    def update(self, price: float) -> float:
        if self.value is None:
            self.value = price
        else:
            self.value = price * self._k + self.value * (1 - self._k)
        return self.value

    def warm(self, prices: List[float]) -> None:
        for p in prices:
            self.update(p)


@dataclass
class _RSIState:
    period:    int   = 14
    avg_gain:  float = 0.0
    avg_loss:  float = 0.0
    last:      Optional[float] = None
    ready:     bool  = False
    _buf_g:    list  = field(default_factory=list)
    _buf_l:    list  = field(default_factory=list)

    def update(self, price: float) -> Optional[float]:
        if self.last is None:
            self.last = price
            return None
        delta = price - self.last
        self.last = price
        g = max(delta, 0.0)
        l = max(-delta, 0.0)

        if not self.ready:
            self._buf_g.append(g)
            self._buf_l.append(l)
            if len(self._buf_g) >= self.period:
                self.avg_gain = sum(self._buf_g) / self.period
                self.avg_loss = sum(self._buf_l) / self.period
                self.ready = True
        else:
            self.avg_gain = (self.avg_gain * (self.period - 1) + g) / self.period
            self.avg_loss = (self.avg_loss * (self.period - 1) + l) / self.period

        if not self.ready:
            return None
        if self.avg_loss == 0:
            return 100.0
        rs = self.avg_gain / self.avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def warm(self, prices: List[float]) -> None:
        for p in prices:
            self.update(p)


@dataclass
class _ATRState:
    period:     int   = 14
    atr:        Optional[float] = None
    last_close: Optional[float] = None
    _buf:       list  = field(default_factory=list)

    def update(self, high: float, low: float, close: float) -> Optional[float]:
        if self.last_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - self.last_close), abs(low - self.last_close))
        self.last_close = close

        if self.atr is None:
            self._buf.append(tr)
            if len(self._buf) >= self.period:
                self.atr = sum(self._buf) / self.period
        else:
            self.atr = (self.atr * (self.period - 1) + tr) / self.period
        return self.atr

    def warm(self, highs, lows, closes) -> None:
        for h, l, c in zip(highs, lows, closes):
            self.update(h, l, c)


@dataclass
class _VWAPState:
    cum_pv:   float = 0.0
    cum_vol:  float = 0.0
    day:      int   = -1   # Unix day bucket

    def update(self, high: float, low: float, close: float, volume: float, ts: int) -> float:
        day = ts // 86400
        if day != self.day:             # new session → reset
            self.cum_pv  = 0.0
            self.cum_vol = 0.0
            self.day     = day
        tp = (high + low + close) / 3.0
        self.cum_pv  += tp * volume
        self.cum_vol += volume
        return self.cum_pv / self.cum_vol if self.cum_vol else close

    def warm(self, highs, lows, closes, vols, times) -> None:
        for h, l, c, v, t in zip(highs, lows, closes, vols, times):
            self.update(h, l, c, v, t)


@dataclass
class _MACDState:
    fast:   _EMAState = field(default_factory=lambda: _EMAState(12))
    slow:   _EMAState = field(default_factory=lambda: _EMAState(26))
    signal: _EMAState = field(default_factory=lambda: _EMAState(9))

    def update(self, price: float) -> Tuple[float, float, float]:
        f = self.fast.update(price)
        s = self.slow.update(price)
        macd_line = f - s
        sig       = self.signal.update(macd_line)
        hist      = macd_line - sig
        return macd_line, sig, hist

    def warm(self, prices: List[float]) -> None:
        for p in prices:
            self.update(p)


# ── Engine ────────────────────────────────────────────────────────────────────

_EMA_PERIODS = (9, 21, 50, 200)


class IncrementalIndicatorEngine:
    def __init__(self, candle_store: CandleStore):
        self._store  = candle_store
        self._lock   = threading.RLock()

        self._emas:  Dict[Tuple, Dict[int, _EMAState]]  = {}
        self._rsis:  Dict[Tuple, _RSIState]  = {}
        self._atrs:  Dict[Tuple, _ATRState]  = {}
        self._vwaps: Dict[Tuple, _VWAPState] = {}
        self._macds: Dict[Tuple, _MACDState] = {}

    def _key(self, symbol: str, tf: str) -> tuple:
        return (symbol, tf)

    def _ensure(self, key: tuple) -> None:
        if key not in self._emas:
            self._emas[key]  = {p: _EMAState(p) for p in _EMA_PERIODS}
            self._rsis[key]  = _RSIState()
            self._atrs[key]  = _ATRState()
            self._vwaps[key] = _VWAPState()
            self._macds[key] = _MACDState()

    # ── Warm-up (call after bulk_insert) ─────────────────────────────────────

    def initialize_from_history(self, symbol: str, tf: str) -> None:
        """Replay all stored candles to warm up indicator states."""
        data = self._store.get_ohlcv_arrays(symbol, tf, limit=600)
        if not data["close"]:
            return
        key = self._key(symbol, tf)
        with self._lock:
            self._ensure(key)
            closes = data["close"]
            highs  = data["high"]
            lows   = data["low"]
            vols   = data["volume"]
            times  = data["time"]

            for p, state in self._emas[key].items():
                state.warm(closes)
            self._rsis[key].warm(closes)
            self._atrs[key].warm(highs, lows, closes)
            self._vwaps[key].warm(highs, lows, closes, vols, times)
            self._macds[key].warm(closes)

    # ── Per-tick update (O(1)) ────────────────────────────────────────────────

    async def update(self, symbol: str, tf: str, candle: dict) -> dict:
        """Update all indicators for the latest candle. Returns latest values."""
        key = self._key(symbol, tf)
        ts  = candle["time"]
        c   = candle["close"]
        h   = candle["high"]
        l   = candle["low"]
        v   = candle["volume"]

        with self._lock:
            self._ensure(key)

            ema_vals = {
                f"ema_{p}": _nan_safe(s.update(c))
                for p, s in self._emas[key].items()
            }
            rsi       = _nan_safe(self._rsis[key].update(c))
            atr       = _nan_safe(self._atrs[key].update(h, l, c))
            vwap      = _nan_safe(self._vwaps[key].update(h, l, c, v, ts))
            ml, ms, mh = self._macds[key].update(c)

        return {
            "timestamp":    ts,
            **ema_vals,
            "rsi":          rsi,
            "atr":          atr,
            "vwap":         vwap,
            "macd":         _nan_safe(ml),
            "macd_signal":  _nan_safe(ms),
            "macd_hist":    _nan_safe(mh),
        }

    # ── Full series (O(n), called once on WS connect) ─────────────────────────

    def get_full_series(self, symbol: str, tf: str) -> dict:
        """
        Compute full indicator arrays from stored candle history.
        Uses temporary state objects — doesn't touch the live states.
        """
        data = self._store.get_ohlcv_arrays(symbol, tf, limit=600)
        if not data["close"]:
            return {}

        closes = data["close"]
        highs  = data["high"]
        lows   = data["low"]
        vols   = data["volume"]
        times  = data["time"]
        n      = len(closes)

        # Temporary states for batch computation (don't disturb live states)
        ema_states  = {p: _EMAState(p) for p in _EMA_PERIODS}
        rsi_state   = _RSIState()
        atr_state   = _ATRState()
        vwap_state  = _VWAPState()
        macd_state  = _MACDState()

        out: dict = {
            "timestamps":  times,
            **{f"ema_{p}": [] for p in _EMA_PERIODS},
            "rsi":         [],
            "atr":         [],
            "vwap":        [],
            "macd":        [],
            "macd_signal": [],
            "macd_hist":   [],
        }

        for i in range(n):
            c = closes[i]; h = highs[i]; l = lows[i]
            v = vols[i];   t = times[i]

            for p, s in ema_states.items():
                out[f"ema_{p}"].append(_nan_safe(s.update(c)))

            out["rsi"].append(_nan_safe(rsi_state.update(c)))
            out["atr"].append(_nan_safe(atr_state.update(h, l, c)))
            out["vwap"].append(_nan_safe(vwap_state.update(h, l, c, v, t)))

            ml, ms, mh = macd_state.update(c)
            out["macd"].append(_nan_safe(ml))
            out["macd_signal"].append(_nan_safe(ms))
            out["macd_hist"].append(_nan_safe(mh))

        return out


def _nan_safe(v) -> Optional[float]:
    """Replace NaN/Inf with None so JSON serialisation doesn't crash."""
    if v is None:
        return None
    try:
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 6)
    except (TypeError, ValueError):
        return None
