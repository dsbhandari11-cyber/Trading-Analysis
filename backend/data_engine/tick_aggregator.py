"""
Tick Aggregator
===============
Converts raw trade ticks into OHLCV candles for any timeframe.
One instance per (symbol, timeframe). Thread-safe via GIL on simple attrs.
"""

from typing import Optional
from .candle_store import Candle, CandleStore, TIMEFRAME_SECONDS
from ..event_bus import EventBus


class TickAggregator:
    __slots__ = (
        "symbol", "timeframe", "_period",
        "candle_store", "event_bus", "_current",
    )

    def __init__(
        self,
        symbol: str,
        timeframe: str,
        candle_store: CandleStore,
        event_bus: EventBus,
    ):
        self.symbol      = symbol
        self.timeframe   = timeframe
        self._period     = TIMEFRAME_SECONDS[timeframe]
        self.candle_store = candle_store
        self.event_bus   = event_bus
        self._current: Optional[Candle] = None

    def on_tick(self, timestamp: int, price: float, volume: float) -> None:
        """Process a single raw trade tick."""
        bar_start = (timestamp // self._period) * self._period

        if self._current is None or self._current.time != bar_start:
            self._current = Candle(
                time=bar_start, open=price, high=price,
                low=price, close=price, volume=volume,
            )
        else:
            c = self._current
            self._current = Candle(
                time=c.time,
                open=c.open,
                high=max(c.high, price),
                low=min(c.low, price),
                close=price,
                volume=c.volume + volume,
            )

        is_new = self.candle_store.upsert_candle(
            self.symbol, self.timeframe, self._current
        )
        self.event_bus.publish("candle_update", {
            "symbol":     self.symbol,
            "timeframe":  self.timeframe,
            "candle":     self._current.to_dict(),
            "is_new_bar": is_new,
        })
