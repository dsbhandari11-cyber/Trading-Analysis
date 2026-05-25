"""
Hash-gated indicator computation cache.

Prevents re-running expensive SMC analysis (Order Blocks, FVGs, Market
Structure, Entry Engine) on every Streamlit rerun when the underlying
candle data hasn't changed.

How it works:
  1. The DataManager computes a 12-char hash from (last_timestamp, last_close).
  2. Before computing an indicator, check if hash for that (key, hash) is cached.
  3. If the hash matches → return cached result instantly (μs latency).
  4. If the hash changed → recompute and store.

Usage:
    from core.indicator_cache import get_indicator_cache
    ic = get_indicator_cache()

    ob_data = ic.compute(
        key="ob_XAUUSD_1H",
        candle_hash=dm.get_hash(symbol, period, interval),
        fn=detect_order_blocks,
        df,                         # positional args to fn
    )
"""

from __future__ import annotations

from typing import Any, Callable, Optional
import streamlit as st

_MAX_ENTRIES = 512   # covers all assets × all TFs × all indicator types


@st.cache_resource(show_spinner=False)
def get_indicator_cache() -> "IndicatorCache":
    """Singleton — persists across Streamlit reruns."""
    return IndicatorCache()


class IndicatorCache:
    """
    Key-value store bound to candle hashes.

    Cache key  = f"{indicator_key}@{candle_hash}"
    On hash change the old entry for that indicator_key is evicted
    and the new result is stored.
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self._hits   = 0
        self._misses = 0

    # ── Public API ──────────────────────────────────────────────────────────────

    def compute(
        self,
        key:         str,
        candle_hash: Optional[str],
        fn:          Callable,
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Return cached result if candle_hash unchanged; otherwise recompute.
        If candle_hash is None (data not yet loaded) → always compute fresh.
        """
        if candle_hash is None:
            self._misses += 1
            return fn(*args, **kwargs)

        cache_key = f"{key}@{candle_hash}"

        if cache_key in self._store:
            self._hits += 1
            return self._store[cache_key]

        self._misses += 1
        result = fn(*args, **kwargs)

        # Evict stale entries for this key (different hash)
        stale = [k for k in self._store if _base_key(k) == key and k != cache_key]
        for s in stale:
            del self._store[s]

        # Bounded eviction — drop oldest by insertion order
        if len(self._store) >= _MAX_ENTRIES:
            self._store.pop(next(iter(self._store)))

        self._store[cache_key] = result
        return result

    def invalidate(self, key_prefix: str) -> None:
        """Remove all cached entries whose indicator key starts with key_prefix."""
        drop = [k for k in self._store if _base_key(k).startswith(key_prefix)]
        for d in drop:
            del self._store[d]

    def stats(self) -> dict:
        total = self._hits + self._misses
        hit_rate = round(self._hits / total * 100, 1) if total else 0.0
        return {
            "entries":  len(self._store),
            "hits":     self._hits,
            "misses":   self._misses,
            "hit_rate": f"{hit_rate}%",
        }


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _base_key(cache_key: str) -> str:
    """Extract indicator_key from 'indicator_key@hash'."""
    return cache_key.rsplit("@", 1)[0]
