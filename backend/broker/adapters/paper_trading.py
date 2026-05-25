"""
Paper Trading Adapter
======================
Simulated broker — fills orders instantly at current market price.
Useful for backtesting the UI flow before connecting a real broker.
"""

import asyncio
import time
import uuid
from typing import AsyncIterator, Dict, List

from ..base import (
    AccountBalance, BrokerAdapter, FilledOrder, Order, OrderSide,
    OrderStatus, OrderType, Position, Tick,
)


class PaperTradingAdapter(BrokerAdapter):
    broker_name            = "paper"
    supports_realtime      = True
    supports_paper_trading = True

    def __init__(self, starting_balance: float = 100_000.0, currency: str = "USD"):
        self._balance    = starting_balance
        self._currency   = currency
        self._positions: Dict[str, Position] = {}
        self._orders:    List[FilledOrder]   = []
        self._connected  = False

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def place_order(self, order: Order) -> str:
        """Instant fill at `order.price` (or 0 if market order)."""
        fill_price = order.price or 0.0
        oid = str(uuid.uuid4())[:8]
        cost = fill_price * order.quantity

        if order.side == OrderSide.BUY:
            self._balance -= cost
            existing = self._positions.get(order.symbol)
            if existing:
                total_qty = existing.quantity + order.quantity
                avg = (existing.avg_entry * existing.quantity + fill_price * order.quantity) / total_qty
                self._positions[order.symbol] = Position(
                    symbol=order.symbol, quantity=total_qty,
                    avg_entry=avg, current_price=fill_price,
                    unrealized_pnl=0, realized_pnl=existing.realized_pnl,
                )
            else:
                self._positions[order.symbol] = Position(
                    symbol=order.symbol, quantity=order.quantity,
                    avg_entry=fill_price, current_price=fill_price,
                    unrealized_pnl=0, realized_pnl=0,
                )
        else:
            self._balance += cost
            if order.symbol in self._positions:
                pos = self._positions[order.symbol]
                realized = (fill_price - pos.avg_entry) * order.quantity
                remaining = pos.quantity - order.quantity
                if remaining <= 0:
                    del self._positions[order.symbol]
                else:
                    pos.quantity = remaining
                    pos.realized_pnl += realized

        filled = FilledOrder(
            order_id=oid, symbol=order.symbol, side=order.side,
            quantity=order.quantity, avg_price=fill_price,
            status=OrderStatus.FILLED, timestamp=int(time.time()),
        )
        self._orders.append(filled)
        return oid

    async def cancel_order(self, order_id: str) -> bool:
        return True  # paper orders fill instantly, nothing to cancel

    async def fetch_orders(self) -> List[FilledOrder]:
        return list(self._orders[-50:])

    async def fetch_positions(self) -> List[Position]:
        return list(self._positions.values())

    async def fetch_balance(self) -> AccountBalance:
        return AccountBalance(
            total_equity=self._balance,
            available_margin=self._balance,
            used_margin=0,
            currency=self._currency,
        )

    async def fetch_ticks(self, symbol: str) -> AsyncIterator[Tick]:
        """Simulate a static tick stream — replace with real feed in prod."""
        while True:
            yield Tick(
                symbol=symbol,
                timestamp=int(time.time()),
                price=0.0,   # caller should override with live price
                volume=0.0,
            )
            await asyncio.sleep(1)
