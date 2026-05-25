"""
yfinance Smart Polling Engine
==============================
• Adaptive poll interval via session_clock (fast during market hours, slow otherwise)
• Startup: full historical load for all symbols × timeframes (run_in_executor → non-blocking)
• Runtime: incremental tail fetch — only last N bars, upsert into CandleStore
• Staggered polling to avoid hammering yfinance simultaneously
• Warms up IncrementalIndicatorEngine after bulk load
"""

import asyncio
import logging
import time
from typing import List, Optional, TYPE_CHECKING

import pandas as pd

from .candle_store import Candle, CandleStore
from .session_clock import get_poll_interval
from ..event_bus import EventBus

if TYPE_CHECKING:
    from ..indicator_engine.incremental import IncrementalIndicatorEngine

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
    _HAS_YF = True
except ImportError:
    _HAS_YF = False
    logger.warning("yfinance not installed — market data engine disabled")

# Timeframe → (historical period, yfinance interval)
_TF_CONFIG = {
    "1m":  ("7d",   "1m"),
    "5m":  ("60d",  "5m"),
    "15m": ("60d",  "15m"),
    "1H":  ("730d", "60m"),
    "4H":  ("730d", "1h"),
    "1D":  ("5y",   "1d"),
}

# Timeframes polled during active market (1m resolution needed)
_ACTIVE_TFS  = ["1m", "5m"]
# Timeframes polled during closed market
_IDLE_TFS    = ["5m", "15m", "1H"]


class YFinanceEngine:
    def __init__(
        self,
        symbols: List[str],
        candle_store: CandleStore,
        event_bus: EventBus,
        indicator_engine: Optional["IncrementalIndicatorEngine"] = None,
    ):
        self.symbols          = symbols
        self.candle_store     = candle_store
        self.event_bus        = event_bus
        self.indicator_engine = indicator_engine
        self._running         = False

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        if not _HAS_YF:
            return

        self._running = True
        await self._initial_load()

        while self._running:
            await self._poll_cycle()

    async def stop(self) -> None:
        self._running = False

    # ── Historical bulk load ──────────────────────────────────────────────────

    async def _initial_load(self) -> None:
        logger.info("yfinance: loading historical data for %d symbols …", len(self.symbols))
        loop = asyncio.get_event_loop()

        # Load 1D and 1H first (most important for indicators to warm up)
        priority_order = ["1D", "1H", "4H", "15m", "5m", "1m"]

        for tf in priority_order:
            for symbol in self.symbols:
                try:
                    candles = await loop.run_in_executor(
                        None, self._fetch_history, symbol, tf
                    )
                    if candles:
                        self.candle_store.bulk_insert(symbol, tf, candles)
                        logger.info("  %s/%s: %d candles", symbol, tf, len(candles))

                        # Warm up indicator engine immediately
                        if self.indicator_engine:
                            self.indicator_engine.initialize_from_history(symbol, tf)
                except Exception as exc:
                    logger.warning("  Failed %s/%s: %s", symbol, tf, exc)

                # Small sleep to avoid yfinance rate-limit
                await asyncio.sleep(0.3)

        logger.info("yfinance: historical load complete")

    # ── Incremental polling ───────────────────────────────────────────────────

    async def _poll_cycle(self) -> None:
        """Fetch tail of each active symbol/timeframe and push updates."""
        loop = asyncio.get_event_loop()

        # Determine which timeframes to poll based on active markets
        active_tfs = _ACTIVE_TFS  # always poll 1m+5m; session_clock controls interval

        for i, symbol in enumerate(self.symbols):
            for tf in active_tfs:
                if not self._running:
                    return
                try:
                    candles = await loop.run_in_executor(
                        None, self._fetch_tail, symbol, tf
                    )
                    for candle in candles:
                        is_new = self.candle_store.upsert_candle(symbol, tf, candle)
                        self.event_bus.publish("candle_update", {
                            "symbol":     symbol,
                            "timeframe":  tf,
                            "candle":     candle.to_dict(),
                            "is_new_bar": is_new,
                        })
                except Exception as exc:
                    logger.debug("Poll error %s/%s: %s", symbol, tf, exc)

                # Stagger requests: don't hammer yfinance all at once
                await asyncio.sleep(0.2)

        # Wait adaptive interval before next cycle
        interval = min(get_poll_interval(s) for s in self.symbols)
        await asyncio.sleep(max(interval, 1.0))

    # ── yfinance fetchers (run in executor — blocking) ────────────────────────

    def _fetch_history(self, symbol: str, timeframe: str) -> List[Candle]:
        period, interval = _TF_CONFIG[timeframe]
        try:
            df = yf.download(
                symbol, period=period, interval=interval,
                progress=False, auto_adjust=True, threads=False,
            )
            return self._df_to_candles(df)
        except Exception as exc:
            logger.debug("yf history error %s/%s: %s", symbol, timeframe, exc)
            return []

    def _fetch_tail(self, symbol: str, timeframe: str) -> List[Candle]:
        """Only fetch the last day or two — much faster than full history."""
        tail_period = "2d" if timeframe in ("1m", "5m") else "5d"
        _, interval = _TF_CONFIG[timeframe]
        try:
            df = yf.download(
                symbol, period=tail_period, interval=interval,
                progress=False, auto_adjust=True, threads=False,
            )
            return self._df_to_candles(df)
        except Exception as exc:
            logger.debug("yf tail error %s/%s: %s", symbol, timeframe, exc)
            return []

    @staticmethod
    def _df_to_candles(df: "pd.DataFrame") -> List[Candle]:
        if df is None or df.empty:
            return []
        candles = []
        for idx, row in df.iterrows():
            try:
                ts = int(idx.timestamp())
            except (AttributeError, TypeError):
                ts = int(time.time())

            # Handle both flat and multi-level column DataFrames
            def _get(col: str) -> float:
                for key in (col, col.lower(), col.capitalize()):
                    if key in row.index:
                        v = row[key]
                        if hasattr(v, '__len__'):
                            v = float(v.iloc[0]) if len(v) > 0 else 0.0
                        return float(v) if v is not None and v == v else 0.0
                return 0.0

            candles.append(Candle(
                time=ts,
                open=_get("Open"),
                high=_get("High"),
                low=_get("Low"),
                close=_get("Close"),
                volume=_get("Volume"),
            ))
        return candles
