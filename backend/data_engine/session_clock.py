"""
Market Session Clock
====================
Returns whether a given market is currently in its active trading session.
Used by yfinance engine to set adaptive poll intervals.
"""

from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional


class MarketSession(str, Enum):
    PRE_MARKET  = "pre_market"
    OPEN        = "open"
    POST_MARKET = "post_market"
    CLOSED      = "closed"


_IST  = timezone(timedelta(hours=5,  minutes=30))
_ET   = timezone(timedelta(hours=-5))          # EST (no DST adjustment for simplicity)
_UTC  = timezone.utc


def _now(tz: timezone) -> datetime:
    return datetime.now(tz)


def nse_session() -> MarketSession:
    """NSE/BSE: 09:15–15:30 IST, Mon–Fri."""
    now = _now(_IST)
    if now.weekday() >= 5:
        return MarketSession.CLOSED
    h, m = now.hour, now.minute
    total = h * 60 + m
    if 555 <= total < 915:          # 09:15 → pre-open ends 09:15
        return MarketSession.PRE_MARKET
    if 915 <= total <= 930:         # 09:15 → 09:30 pre-open call auction
        return MarketSession.PRE_MARKET
    if 930 <= total < 930 + 360:    # 09:30 → 15:30
        return MarketSession.OPEN
    return MarketSession.CLOSED


def nse_is_open() -> bool:
    return nse_session() == MarketSession.OPEN


def us_session() -> MarketSession:
    """NYSE/NASDAQ: 09:30–16:00 ET, Mon–Fri."""
    now = _now(_ET)
    if now.weekday() >= 5:
        return MarketSession.CLOSED
    h, m = now.hour, now.minute
    total = h * 60 + m
    if 240 <= total < 570:          # 04:00–09:30 pre-market
        return MarketSession.PRE_MARKET
    if 570 <= total < 960:          # 09:30–16:00
        return MarketSession.OPEN
    if 960 <= total < 1200:         # 16:00–20:00 after-hours
        return MarketSession.POST_MARKET
    return MarketSession.CLOSED


def us_is_open() -> bool:
    return us_session() == MarketSession.OPEN


def crypto_session() -> MarketSession:
    """Crypto trades 24/7."""
    return MarketSession.OPEN


def get_poll_interval(symbol: str) -> float:
    """Return recommended polling interval (seconds) for a given symbol."""
    sym = symbol.upper()

    # Crypto — always fast, but Hyperliquid WS handles it; yfinance fallback
    if any(x in sym for x in ["BTC", "ETH", "BNB", "SOL"]):
        return 5.0

    # Gold / Silver futures — US market hours
    if sym in ("GC=F", "SI=F", "CL=F", "NG=F"):
        return 3.0 if us_is_open() else 30.0

    # NSE / BSE
    if sym.startswith("^NSE") or sym.startswith("^BSE") or sym.endswith(".NS") or sym.endswith(".BO"):
        if nse_is_open():
            return 2.0
        return 60.0

    # US equities
    if us_is_open():
        return 3.0
    if us_session() in (MarketSession.PRE_MARKET, MarketSession.POST_MARKET):
        return 15.0
    return 60.0
