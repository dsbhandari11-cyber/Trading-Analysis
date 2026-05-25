"""
Thread-Safe Centralized OHLC Candle Store
==========================================
• Keyed by (symbol, timeframe)
• Append-only writes; last candle is updated in-place for live ticks
• bulk_insert() for historical load (yfinance startup)
• Readers get Python dicts — safe to serialize to JSON directly
"""

import threading
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Set, Tuple

MAX_CANDLES = 2000  # per (symbol, timeframe)

TIMEFRAME_SECONDS: Dict[str, int] = {
    "1m":  60,
    "5m":  300,
    "15m": 900,
    "30m": 1800,
    "1H":  3600,
    "4H":  14400,
    "1D":  86400,
}


@dataclass(slots=True)
class Candle:
    time:   int    # Unix epoch, seconds, bar-open time
    open:   float
    high:   float
    low:    float
    close:  float
    volume: float

    def to_dict(self) -> dict:
        return {
            "time":   self.time,
            "open":   self.open,
            "high":   self.high,
            "low":    self.low,
            "close":  self.close,
            "volume": self.volume,
        }


class CandleStore:
    def __init__(self):
        self._store: Dict[Tuple[str, str], deque] = defaultdict(
            lambda: deque(maxlen=MAX_CANDLES)
        )
        self._lock = threading.RLock()

    # ── Writers ──────────────────────────────────────────────────────────────

    def upsert_candle(self, symbol: str, timeframe: str, candle: Candle) -> bool:
        """
        Insert or update.
        Returns True  → new bar opened (consumers may recalc structure signals)
        Returns False → live tick on current bar
        """
        key = (symbol, timeframe)
        with self._lock:
            store = self._store[key]
            if store and store[-1].time == candle.time:
                store[-1] = candle          # update current bar in-place
                return False
            store.append(candle)            # new bar
            return True

    def bulk_insert(self, symbol: str, timeframe: str, candles: List[Candle]):
        """Replace full history (called once on startup from yfinance/historical)."""
        key = (symbol, timeframe)
        with self._lock:
            self._store[key] = deque(candles, maxlen=MAX_CANDLES)

    # ── Readers ──────────────────────────────────────────────────────────────

    def get_candles(
        self, symbol: str, timeframe: str, limit: int = 500
    ) -> List[dict]:
        key = (symbol, timeframe)
        with self._lock:
            store = self._store[key]
            sliced = list(store)[-limit:] if len(store) > limit else list(store)
            return [c.to_dict() for c in sliced]

    def get_latest(self, symbol: str, timeframe: str) -> Optional[Candle]:
        key = (symbol, timeframe)
        with self._lock:
            store = self._store[key]
            return store[-1] if store else None

    def get_close_series(self, symbol: str, timeframe: str) -> List[float]:
        key = (symbol, timeframe)
        with self._lock:
            return [c.close for c in self._store[key]]

    def get_ohlcv_arrays(
        self, symbol: str, timeframe: str, limit: int = 500
    ) -> dict:
        """Return numpy-friendly dict of arrays — used by indicator engine."""
        key = (symbol, timeframe)
        with self._lock:
            store = self._store[key]
            sliced = list(store)[-limit:] if len(store) > limit else list(store)

        return {
            "time":   [c.time   for c in sliced],
            "open":   [c.open   for c in sliced],
            "high":   [c.high   for c in sliced],
            "low":    [c.low    for c in sliced],
            "close":  [c.close  for c in sliced],
            "volume": [c.volume for c in sliced],
        }

    def available_symbols(self) -> List[str]:
        with self._lock:
            seen: Set[str] = set()
            result = []
            for sym, tf in self._store:
                if sym not in seen:
                    seen.add(sym)
                    result.append(sym)
            return result

    def has_data(self, symbol: str, timeframe: str) -> bool:
        key = (symbol, timeframe)
        with self._lock:
            return bool(self._store[key])
