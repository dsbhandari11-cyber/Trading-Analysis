"""
Zerodha Kite Connect Adapter — STUB
=====================================
Wire up with kiteconnect library: pip install kiteconnect

Replace every `raise NotImplementedError` with real Kite API calls.
See: https://kite.trade/docs/connect/v3/
"""

import asyncio
from typing import AsyncIterator, List

from ..base import (
    AccountBalance, BrokerAdapter, FilledOrder, Order,
    OrderSide, OrderStatus, OrderType, Position, Tick,
)


class ZerodhaAdapter(BrokerAdapter):
    broker_name       = "zerodha"
    supports_realtime = True

    def __init__(self, api_key: str, access_token: str):
        self._api_key      = api_key
        self._access_token = access_token
        self._kite         = None   # KiteConnect instance

    async def connect(self) -> bool:
        # from kiteconnect import KiteConnect
        # self._kite = KiteConnect(api_key=self._api_key)
        # self._kite.set_access_token(self._access_token)
        raise NotImplementedError("Install kiteconnect and uncomment above")

    async def disconnect(self) -> None:
        self._kite = None

    async def place_order(self, order: Order) -> str:
        # return self._kite.place_order(
        #     variety=self._kite.VARIETY_REGULAR,
        #     exchange=self._kite.EXCHANGE_NSE,
        #     tradingsymbol=order.symbol,
        #     transaction_type=self._kite.TRANSACTION_TYPE_BUY if order.side == OrderSide.BUY else self._kite.TRANSACTION_TYPE_SELL,
        #     quantity=int(order.quantity),
        #     product=self._kite.PRODUCT_MIS,
        #     order_type=self._kite.ORDER_TYPE_MARKET,
        # )
        raise NotImplementedError

    async def cancel_order(self, order_id: str) -> bool:
        # self._kite.cancel_order(variety=self._kite.VARIETY_REGULAR, order_id=order_id)
        raise NotImplementedError

    async def fetch_orders(self) -> List[FilledOrder]:
        raise NotImplementedError

    async def fetch_positions(self) -> List[Position]:
        raise NotImplementedError

    async def fetch_balance(self) -> AccountBalance:
        raise NotImplementedError

    async def fetch_ticks(self, symbol: str) -> AsyncIterator[Tick]:
        # Use KiteTicker for live ticks
        raise NotImplementedError
