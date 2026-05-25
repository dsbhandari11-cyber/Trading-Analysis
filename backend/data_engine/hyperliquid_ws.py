"""
Hyperliquid WebSocket Client
=============================
• Streams live candles + trades for BTC, ETH (and any other HL-listed coin)
• Full reconnect with exponential back-off (cap 60 s)
• Heartbeat ping every 30 s to detect silent drops
• Candle feed from HL's 'candle' channel (direct OHLCV)
• Trade feed feeds TickAggregators for sub-1m synthetic bars

Hyperliquid WS docs: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket
"""

import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Tuple

try:
    import websockets
    from websockets.exceptions import ConnectionClosed, WebSocketException
    _HAS_WEBSOCKETS = True
except ImportError:
    _HAS_WEBSOCKETS = False

from .candle_store import Candle, CandleStore, TIMEFRAME_SECONDS
from .tick_aggregator import TickAggregator
from ..event_bus import EventBus

logger = logging.getLogger(__name__)

HL_WS_URL = "wss://api.hyperliquid.xyz/ws"

# HL interval string → internal timeframe key
_HL_TO_TF: Dict[str, str] = {
    "1m": "1m", "5m": "5m", "15m": "15m",
    "1h": "1H", "4h": "4H",  "1d": "1D",
}
_TF_TO_HL: Dict[str, str] = {v: k for k, v in _HL_TO_TF.items()}

# Display symbol (e.g. "BTCUSD") used as the store/event key
_COIN_TO_SYMBOL: Dict[str, str] = {}  # built dynamically


def _coin_display(coin: str) -> str:
    return _COIN_TO_SYMBOL.get(coin, coin + "USD")


SUPPORTED_TIMEFRAMES = ["1m", "5m", "15m", "1H", "4H", "1D"]


class HyperliquidWSClient:
    def __init__(
        self,
        symbols: List[str],
        candle_store: CandleStore,
        event_bus: EventBus,
    ):
        """
        symbols: Hyperliquid coin names e.g. ["BTC", "ETH"]
        """
        self.symbols     = symbols
        self.candle_store = candle_store
        self.event_bus   = event_bus

        self._ws         = None
        self._running    = False
        self._reconnect  = 3.0
        self._max_reconnect = 60.0

        # Build display name map
        for coin in symbols:
            _COIN_TO_SYMBOL[coin] = coin + "USD"

        # One TickAggregator per (coin, timeframe) for trade-level aggregation
        self._aggregators: Dict[Tuple[str, str], TickAggregator] = {
            (coin, tf): TickAggregator(
                symbol=_coin_display(coin),
                timeframe=tf,
                candle_store=candle_store,
                event_bus=event_bus,
            )
            for coin in symbols
            for tf in SUPPORTED_TIMEFRAMES
        }

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        if not _HAS_WEBSOCKETS:
            logger.warning("websockets package not installed — Hyperliquid disabled. pip install websockets")
            return

        self._running = True
        while self._running:
            try:
                await self._connect_and_stream()
                self._reconnect = 3.0          # reset on clean exit
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("HL WS error: %s — reconnecting in %.0fs", exc, self._reconnect)
                await asyncio.sleep(self._reconnect)
                self._reconnect = min(self._reconnect * 2, self._max_reconnect)

    async def close(self) -> None:
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

    # ── Connection ────────────────────────────────────────────────────────────

    async def _connect_and_stream(self) -> None:
        logger.info("Connecting to Hyperliquid WS …")
        async with websockets.connect(
            HL_WS_URL,
            ping_interval=30,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            self._ws = ws
            self._reconnect = 3.0
            logger.info("Hyperliquid WS connected — subscribing …")

            await self._subscribe(ws)

            async for raw in ws:
                msg = json.loads(raw)
                await self._dispatch(msg)

    async def _subscribe(self, ws) -> None:
        for coin in self.symbols:
            # Candle subscriptions for all timeframes
            for tf in SUPPORTED_TIMEFRAMES:
                hl_iv = _TF_TO_HL.get(tf, "1m")
                sub = {
                    "method": "subscribe",
                    "subscription": {
                        "type":     "candle",
                        "coin":     coin,
                        "interval": hl_iv,
                    },
                }
                await ws.send(json.dumps(sub))

            # Live trades for tick-level aggregation
            await ws.send(json.dumps({
                "method": "subscribe",
                "subscription": {"type": "trades", "coin": coin},
            }))

        logger.info("Hyperliquid: subscribed to %d symbols × %d timeframes",
                    len(self.symbols), len(SUPPORTED_TIMEFRAMES))

    # ── Message dispatch ──────────────────────────────────────────────────────

    async def _dispatch(self, msg: dict) -> None:
        channel = msg.get("channel", "")
        data    = msg.get("data")
        if not data:
            return

        if channel == "candle":
            self._handle_candle(data)
        elif channel == "trades":
            self._handle_trades(data)

    def _handle_candle(self, data: dict) -> None:
        """Direct OHLCV bar from HL candle channel."""
        try:
            coin   = data.get("s", "")          # e.g. "BTC"
            hl_iv  = data.get("i", "1m")
            tf     = _HL_TO_TF.get(hl_iv, "1m")
            symbol = _coin_display(coin)

            candle = Candle(
                time=int(data["t"]) // 1000,    # ms → seconds
                open=float(data["o"]),
                high=float(data["h"]),
                low=float(data["l"]),
                close=float(data["c"]),
                volume=float(data["v"]),
            )
            is_new = self.candle_store.upsert_candle(symbol, tf, candle)
            self.event_bus.publish("candle_update", {
                "symbol":     symbol,
                "timeframe":  tf,
                "candle":     candle.to_dict(),
                "is_new_bar": is_new,
            })
        except (KeyError, ValueError, TypeError) as exc:
            logger.debug("HL candle parse error: %s  data=%s", exc, data)

    def _handle_trades(self, trades: list) -> None:
        """Aggregate raw trades into synthetic candles for all timeframes."""
        if not isinstance(trades, list):
            return
        for trade in trades:
            try:
                coin   = trade.get("coin", "")
                price  = float(trade.get("px", 0))
                size   = float(trade.get("sz", 0))
                ts     = int(trade.get("time", time.time() * 1000)) // 1000

                for tf in SUPPORTED_TIMEFRAMES:
                    agg = self._aggregators.get((coin, tf))
                    if agg:
                        agg.on_tick(ts, price, size)
            except (KeyError, ValueError, TypeError) as exc:
                logger.debug("HL trade parse error: %s", exc)
