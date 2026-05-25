"""
Background data manager for non-blocking market data access.

Architecture:
  ┌─ Render thread (Streamlit) ─────────────────────────────────────────────┐
  │  dm.get_df(symbol, period, interval)  → returns cached df immediately   │
  │  if stale → triggers background fetch; stale data served until fresh    │
  └─────────────────────────────────────────────────────────────────────────┘
  ┌─ Worker thread (daemon) ────────────────────────────────────────────────┐
  │  drains _queue → calls yfinance → writes to _store (thread-safe)        │
  └─────────────────────────────────────────────────────────────────────────┘

Usage:
    from core.data_manager import get_data_manager
    dm = get_data_manager()
    df = dm.get_df("GC=F", "30d", "60m", ttl=60)   # never blocks
    h  = dm.get_hash("GC=F", "30d", "60m")          # for indicator gating
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

# Max candle-store entries — covers all CFD assets × all timeframes with headroom
_MAX_ENTRIES = 96
# Pre-refresh at 70 % of TTL so data is ready before the render-thread asks
_PREFETCH_RATIO = 0.70


@st.cache_resource(show_spinner=False)
def get_data_manager() -> "DataManager":
    """Singleton — survives across Streamlit reruns (cache_resource semantics)."""
    return DataManager()


class DataManager:
    """
    Thread-safe in-memory candle store.
    The background worker keeps data fresh; the render thread never waits.
    """

    def __init__(self) -> None:
        self._lock   = threading.RLock()
        self._store: OrderedDict[str, Dict]  = OrderedDict()   # key → entry
        self._inflight: set = set()                            # keys being fetched
        self._queue:  List[Tuple[int, float, str, str, str, Optional[str]]] = []
        self._event  = threading.Event()
        self._stop   = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="DMWorker"
        )
        self._thread.start()

    # ── Public read API (render thread) ────────────────────────────────────────

    def get_df(
        self,
        symbol:   str,
        period:   str,
        interval: str,
        resample: Optional[str] = None,
        ttl:      float = 60.0,
        priority: int   = 0,
    ) -> Optional[pd.DataFrame]:
        """
        Return cached DataFrame immediately — never blocks.
        • Fresh entry  → return df as-is.
        • Stale entry  → enqueue background refresh, return stale df.
        • Missing      → enqueue fetch, return None (caller renders placeholder).
        """
        key = _key(symbol, period, interval, resample)
        with self._lock:
            entry = self._store.get(key)

        age = time.time() - entry["ts"] if entry else float("inf")

        if age >= ttl * _PREFETCH_RATIO:
            # Stale or missing — kick off background refresh
            self._enqueue(symbol, period, interval, resample, priority)

        return entry["df"] if entry else None

    def get_hash(
        self,
        symbol:   str,
        period:   str,
        interval: str,
        resample: Optional[str] = None,
    ) -> Optional[str]:
        """
        12-char hex hash of (last_timestamp, last_close).
        Returns None when data not yet available.
        """
        key = _key(symbol, period, interval, resample)
        with self._lock:
            entry = self._store.get(key)
        return entry["hash"] if entry else None

    def prefetch(
        self,
        symbol:   str,
        period:   str,
        interval: str,
        resample: Optional[str] = None,
        priority: int = 5,
    ) -> None:
        """Pre-warm the cache — call on page load before any render."""
        key = _key(symbol, period, interval, resample)
        with self._lock:
            if key not in self._store:
                self._enqueue(symbol, period, interval, resample, priority)

    def force_refresh(
        self,
        symbol:   str,
        period:   str,
        interval: str,
        resample: Optional[str] = None,
    ) -> None:
        """Evict a cache entry and immediately enqueue a high-priority fetch."""
        key = _key(symbol, period, interval, resample)
        with self._lock:
            self._store.pop(key, None)
        self._enqueue(symbol, period, interval, resample, priority=10)

    # ── Queue management ────────────────────────────────────────────────────────

    def _enqueue(
        self,
        symbol:   str,
        period:   str,
        interval: str,
        resample: Optional[str],
        priority: int,
    ) -> None:
        key = _key(symbol, period, interval, resample)
        with self._lock:
            if key in self._inflight:
                return
            # De-duplicate: remove existing entry for same key
            self._queue = [q for q in self._queue if q[2] != symbol
                           or q[3] != period or q[4] != interval or q[5] != resample]
            self._queue.append((priority, time.time(), symbol, period, interval, resample))
            # Sort descending by priority so highest-priority pops first
            self._queue.sort(key=lambda x: x[0], reverse=True)
        self._event.set()

    # ── Worker thread ───────────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop.is_set():
            self._event.wait(timeout=2.0)
            self._event.clear()
            # Drain all pending fetches
            while True:
                with self._lock:
                    if not self._queue:
                        break
                    item = self._queue.pop(0)
                    _, _, symbol, period, interval, resample = item
                    k = _key(symbol, period, interval, resample)
                    self._inflight.add(k)
                self._fetch(symbol, period, interval, resample)
                with self._lock:
                    self._inflight.discard(k)

    def _fetch(
        self,
        symbol:   str,
        period:   str,
        interval: str,
        resample: Optional[str],
    ) -> None:
        key = _key(symbol, period, interval, resample)
        try:
            import yfinance as yf
            df = yf.Ticker(symbol).history(
                period=period, interval=interval, auto_adjust=True
            )
            if df is None or df.empty:
                return
            df.index = pd.to_datetime(df.index)
            if resample:
                df = df.resample(resample).agg({
                    "Open": "first", "High": "max",
                    "Low": "min",  "Close": "last", "Volume": "sum",
                }).dropna(how="any")
            last_ts = str(df.index[-1])
            last_cl = str(round(float(df["Close"].iloc[-1]), 4))
            h = hashlib.md5(f"{last_ts}|{last_cl}".encode()).hexdigest()[:12]
            with self._lock:
                self._store[key] = {"df": df, "hash": h, "ts": time.time()}
                # LRU eviction — drop oldest entries when over limit
                while len(self._store) > _MAX_ENTRIES:
                    self._store.popitem(last=False)
        except Exception:
            pass


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _key(symbol: str, period: str, interval: str, resample: Optional[str]) -> str:
    return f"{symbol}|{period}|{interval}|{resample or ''}"
