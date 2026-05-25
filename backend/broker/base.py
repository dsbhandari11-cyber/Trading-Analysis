"""
Abstract Broker Adapter
========================
Implement this interface to integrate any broker in one file.

Pattern:
  class MyBrokerAdapter(BrokerAdapter):
      broker_name = "mybroker"
      ...implement abstract methods...

Register in backend/broker/registry.py and the order panel picks it up.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Dict, List, Optional


# ── Value objects ─────────────────────────────────────────────────────────────

class OrderSide(str, Enum):
    BUY  = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET     = "market"
    LIMIT      = "limit"
    STOP       = "stop"
    STOP_LIMIT = "stop_limit"
    TRAILING   = "trailing_stop"


class OrderStatus(str, Enum):
    PENDING   = "pending"
    OPEN      = "open"
    FILLED    = "filled"
    PARTIAL   = "partial"
    CANCELLED = "cancelled"
    REJECTED  = "rejected"


@dataclass
class Order:
    symbol:      str
    side:        OrderSide
    order_type:  OrderType
    quantity:    float
    price:       Optional[float] = None
    stop_price:  Optional[float] = None
    tag:         Optional[str]   = None   # internal label / strategy id
    client_id:   Optional[str]   = None


@dataclass
class FilledOrder:
    order_id:    str
    symbol:      str
    side:        OrderSide
    quantity:    float
    avg_price:   float
    status:      OrderStatus
    timestamp:   int


@dataclass
class Position:
    symbol:         str
    quantity:       float
    avg_entry:      float
    current_price:  float
    unrealized_pnl: float
    realized_pnl:   float
    side:           OrderSide = OrderSide.BUY


@dataclass
class AccountBalance:
    total_equity:    float
    available_margin: float
    used_margin:     float
    currency:        str = "INR"


@dataclass
class Tick:
    symbol:    str
    timestamp: int
    price:     float
    volume:    float
    bid:       Optional[float] = None
    ask:       Optional[float] = None


@dataclass
class OrderBook:
    symbol: str
    bids:   List[List[float]] = field(default_factory=list)  # [[price, qty], …]
    asks:   List[List[float]] = field(default_factory=list)


# ── Abstract adapter ──────────────────────────────────────────────────────────

class BrokerAdapter(ABC):
    """
    Base class for all broker integrations.

    To add a new broker:
      1. Create backend/broker/adapters/<name>.py
      2. Subclass BrokerAdapter
      3. Set `broker_name`, `supports_realtime`, `supports_paper_trading`
      4. Implement all @abstractmethods
      5. Register in backend/broker/registry.py

    Only `place_order`, `cancel_order`, `fetch_positions`, `fetch_balance`,
    and `fetch_ticks` are mandatory. The rest have stub defaults.
    """

    broker_name:            str  = "base"
    supports_realtime:      bool = False
    supports_paper_trading: bool = False
    supports_orderbook:     bool = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @abstractmethod
    async def connect(self) -> bool:
        """Authenticate. Returns True on success."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Clean shutdown."""
        ...

    # ── Orders ────────────────────────────────────────────────────────────────

    @abstractmethod
    async def place_order(self, order: Order) -> str:
        """Submit order. Returns broker order_id."""
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel open order. Returns True on success."""
        ...

    @abstractmethod
    async def fetch_orders(self) -> List[FilledOrder]:
        """Return all open + recent orders."""
        ...

    # ── Portfolio ─────────────────────────────────────────────────────────────

    @abstractmethod
    async def fetch_positions(self) -> List[Position]:
        """Return all open positions."""
        ...

    @abstractmethod
    async def fetch_balance(self) -> AccountBalance:
        """Return account equity and margin."""
        ...

    # ── Market data ───────────────────────────────────────────────────────────

    @abstractmethod
    async def fetch_ticks(self, symbol: str) -> AsyncIterator[Tick]:
        """Async generator — yields live ticks for symbol."""
        ...

    # ── Optional (override for brokers that support it) ───────────────────────

    async def fetch_orderbook(self, symbol: str, depth: int = 10) -> OrderBook:
        raise NotImplementedError(f"{self.broker_name}: orderbook not supported")

    async def fetch_historical(
        self, symbol: str, timeframe: str, limit: int = 500
    ) -> List[dict]:
        raise NotImplementedError(f"{self.broker_name}: historical not supported")

    async def modify_order(
        self, order_id: str, new_price: Optional[float] = None,
        new_qty: Optional[float] = None
    ) -> bool:
        raise NotImplementedError(f"{self.broker_name}: modify_order not supported")
