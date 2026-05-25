"""
Hyperliquid Broker Adapter — STUB
===================================
Connects the Hyperliquid DEX for live crypto trading.
Wire up with the hyperliquid-python-sdk: pip install hyperliquid-python-sdk

See: https://github.com/hyperliquid-dex/hyperliquid-python-sdk
"""

import asyncio
import time
from typing import AsyncIterator, List

from ..base import (
    AccountBalance, BrokerAdapter, FilledOrder, Order,
    OrderSide, OrderStatus, Position, Tick,
)


class HyperliquidBrokerAdapter(BrokerAdapter):
    broker_name            = "hyperliquid"
    supports_realtime      = True
    supports_paper_trading = True
    supports_orderbook     = True

    def __init__(self, wallet_address: str, private_key: str, testnet: bool = True):
        self._address     = wallet_address
        self._private_key = private_key
        self._testnet     = testnet
        self._exchange    = None
        self._info        = None

    async def connect(self) -> bool:
        # from hyperliquid.exchange import Exchange
        # from hyperliquid.info import Info
        # self._exchange = Exchange(wallet_address=self._address, private_key=self._private_key, testnet=self._testnet)
        # self._info = Info(testnet=self._testnet)
        raise NotImplementedError("pip install hyperliquid-python-sdk then uncomment")

    async def disconnect(self) -> None:
        self._exchange = None

    async def place_order(self, order: Order) -> str:
        # result = self._exchange.market_open(
        #     coin=order.symbol.replace("USD", ""),
        #     is_buy=(order.side == OrderSide.BUY),
        #     sz=order.quantity,
        #     px=order.price,
        # )
        # return str(result.get("response", {}).get("data", {}).get("statuses", [{}])[0].get("resting", {}).get("oid", ""))
        raise NotImplementedError

    async def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError

    async def fetch_orders(self) -> List[FilledOrder]:
        raise NotImplementedError

    async def fetch_positions(self) -> List[Position]:
        raise NotImplementedError

    async def fetch_balance(self) -> AccountBalance:
        raise NotImplementedError

    async def fetch_ticks(self, symbol: str) -> AsyncIterator[Tick]:
        raise NotImplementedError
