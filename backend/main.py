"""
Real-Time Trading Terminal — FastAPI Backend
=============================================
Serves WebSocket feeds for live candle + indicator streaming.
Run: uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
"""

import asyncio
import json
import logging
import sys
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Ensure project root is on path so data.smc_analysis is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.smc_analysis import (
    detect_order_blocks,
    detect_fvg,
    detect_market_structure,
    institutional_analysis,
)

from .event_bus import EventBus
from .websocket_manager import WebSocketManager
from .data_engine.candle_store import CandleStore
from .data_engine.hyperliquid_ws import HyperliquidWSClient
from .data_engine.yfinance_engine import YFinanceEngine
from .indicator_engine.incremental import IncrementalIndicatorEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

YFINANCE_CACHE_DIR = Path(__file__).resolve().parents[1] / "logs" / "yfinance_cache"
YFINANCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
if hasattr(yf, "set_tz_cache_location"):
    yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))

# ── Shared singletons ────────────────────────────────────────────────────────

event_bus      = EventBus()
ws_manager     = WebSocketManager()
candle_store   = CandleStore()
indicator_eng  = IncrementalIndicatorEngine(candle_store)

# ── Startup / shutdown ───────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting data engines …")

    hl_client = HyperliquidWSClient(
        symbols=["BTC", "ETH"],
        candle_store=candle_store,
        event_bus=event_bus,
    )
    yf_engine = YFinanceEngine(
        symbols=["^NSEI", "^NSEBANK", "GC=F", "SI=F", "BTC-USD", "ETH-USD"],
        candle_store=candle_store,
        event_bus=event_bus,
        indicator_engine=indicator_eng,
    )

    tasks = [
        asyncio.create_task(hl_client.run(),  name="hyperliquid-ws"),
        asyncio.create_task(yf_engine.run(),  name="yfinance-engine"),
        asyncio.create_task(_broadcast_loop(), name="broadcast-loop"),
    ]

    try:
        yield
    finally:
        logger.info("Shutting down data engines …")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await hl_client.close()


# ── Broadcast loop ───────────────────────────────────────────────────────────

async def _broadcast_loop():
    """Consume candle_update events → update indicators → push to WS clients."""
    async for event in event_bus.subscribe("candle_update"):
        symbol    = event["symbol"]
        timeframe = event["timeframe"]
        candle    = event["candle"]
        topic     = f"{symbol}:{timeframe}"

        if ws_manager.subscriber_count(topic) == 0:
            continue  # nobody watching, skip indicator work

        indicators = await indicator_eng.update(symbol, timeframe, candle)

        message = json.dumps({
            "type":      "candle_update",
            "symbol":    symbol,
            "timeframe": timeframe,
            "candle":    candle,
            "indicators": indicators,
        }, allow_nan=False)

        await ws_manager.broadcast_to_topic(topic, message)


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Trading Terminal API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws/{symbol}/{timeframe}")
async def ws_endpoint(websocket: WebSocket, symbol: str, timeframe: str):
    """
    Client connects here to receive live candle + indicator stream.
    On connect: full historical init payload.
    On tick:   incremental candle_update message.
    """
    topic = f"{symbol}:{timeframe}"
    await ws_manager.connect(websocket, topic)

    try:
        # Send historical snapshot immediately
        candles    = candle_store.get_candles(symbol, timeframe, limit=600)
        indicators = indicator_eng.get_full_series(symbol, timeframe)

        await websocket.send_json({
            "type":       "init",
            "symbol":     symbol,
            "timeframe":  timeframe,
            "candles":    candles,
            "indicators": indicators,
        })

        # Handle client → server messages (timeframe switch, indicator toggle)
        while True:
            raw = await websocket.receive_text()
            await _handle_client_msg(websocket, symbol, timeframe, json.loads(raw))

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, topic)
    except Exception as exc:
        logger.error("WS error  topic=%s  err=%s", topic, exc)
        ws_manager.disconnect(websocket, topic)


async def _handle_client_msg(
    ws: WebSocket, symbol: str, current_tf: str, msg: dict
):
    """Handle client-initiated actions: timeframe switch, ping, etc."""
    action = msg.get("action")

    if action == "switch_timeframe":
        new_tf  = msg.get("timeframe", current_tf)
        new_topic = f"{symbol}:{new_tf}"
        old_topic = f"{symbol}:{current_tf}"
        ws_manager.disconnect(ws, old_topic)
        ws_manager._topics[new_topic].add(ws)

        candles    = candle_store.get_candles(symbol, new_tf, limit=600)
        indicators = indicator_eng.get_full_series(symbol, new_tf)
        await ws.send_json({
            "type":       "init",
            "symbol":     symbol,
            "timeframe":  new_tf,
            "candles":    candles,
            "indicators": indicators,
        })

    elif action == "ping":
        await ws.send_json({"type": "pong"})


# ── REST endpoints ────────────────────────────────────────────────────────────

@app.get("/api/candles/{symbol}/{timeframe}")
async def get_candles(symbol: str, timeframe: str, limit: int = Query(500, le=2000)):
    candles = candle_store.get_candles(symbol, timeframe, limit)
    return {"symbol": symbol, "timeframe": timeframe, "candles": candles, "count": len(candles)}


@app.get("/api/indicators/{symbol}/{timeframe}")
async def get_indicators(symbol: str, timeframe: str):
    series = indicator_eng.get_full_series(symbol, timeframe)
    return {"symbol": symbol, "timeframe": timeframe, "series": series}


@app.get("/api/watchlist/prices")
async def get_watchlist_prices(symbols: str = Query(..., description="Comma-separated list of symbols")):
    """Return current price + change data for a comma-separated list of symbols."""
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()][:50]
    result: dict = {}

    async def _fetch_one(sym: str) -> None:
        try:
            info = await asyncio.to_thread(lambda: yf.Ticker(sym).fast_info)
            price = getattr(info, "last_price", None)
            prev  = getattr(info, "previous_close", None)
            if price is None:
                price = getattr(info, "regularMarketPrice", None)
            change     = (price - prev)          if price is not None and prev else None
            change_pct = (change / prev * 100)   if change is not None and prev else None
            result[sym] = {
                "symbol":     sym,
                "price":      price,
                "change":     round(change, 4)     if change     is not None else None,
                "change_pct": round(change_pct, 4) if change_pct is not None else None,
                "prev_close": prev,
            }
        except Exception as exc:
            logger.warning("watchlist price fetch failed  sym=%s  err=%s", sym, exc)
            result[sym] = {"symbol": sym, "price": None, "change": None, "change_pct": None, "prev_close": None}

    await asyncio.gather(*[_fetch_one(s) for s in symbol_list])
    return result


@app.get("/api/status")
async def get_status():
    return {
        "status":      "ok",
        "topics":      ws_manager.all_topics(),
        "symbols":     candle_store.available_symbols(),
    }


# ── SMC Analysis endpoint ─────────────────────────────────────────────────────

@app.get("/api/smc")
async def get_smc_analysis(
    symbol:   str = Query(..., description="yfinance symbol, e.g. RELIANCE.NS"),
    period:   str = Query("3mo"),
    interval: str = Query("1d"),
):
    """Download OHLCV via yfinance and return full SMC analysis."""
    try:
        df = await asyncio.to_thread(
            lambda: yf.download(symbol, period=period, interval=interval,
                                progress=False, auto_adjust=True)
        )
        if df is None or df.empty:
            return {"error": "no_data", "symbol": symbol}

        # Flatten MultiIndex columns produced by yf.download
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]

        ob   = detect_order_blocks(df)
        fvg  = detect_fvg(df)
        ms   = detect_market_structure(df)
        inst = institutional_analysis(df)

        cur = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2]) if len(df) > 1 else cur
        chg_pct = round((cur - prev) / (prev + 1e-9) * 100, 2)

        return {
            "symbol":           symbol,
            "current_price":    cur,
            "change_pct":       chg_pct,
            "order_blocks":     ob,
            "fvg":              fvg,
            "market_structure": ms,
            "institutional":    inst,
        }
    except Exception as exc:
        logger.warning("SMC analysis failed  sym=%s  err=%s", symbol, exc)
        return {"error": str(exc), "symbol": symbol}


# ── CFD / Global asset prices ─────────────────────────────────────────────────

CFD_SYMBOLS = {
    "GC=F":     {"name": "Gold",      "icon": "Au",  "category": "COMMODITY", "unit": "USD/oz"},
    "SI=F":     {"name": "Silver",    "icon": "Ag",  "category": "COMMODITY", "unit": "USD/oz"},
    "BTC-USD":  {"name": "Bitcoin",   "icon": "BTC", "category": "CRYPTO",    "unit": "USD"},
    "ETH-USD":  {"name": "Ethereum",  "icon": "ETH", "category": "CRYPTO",    "unit": "USD"},
    "^NSEI":    {"name": "Nifty 50",  "icon": "NI",  "category": "INDEX",     "unit": "INR pts"},
    "^NSEBANK": {"name": "BankNifty", "icon": "BNK", "category": "INDEX",     "unit": "INR pts"},
    "NQ=F":     {"name": "Nasdaq",    "icon": "NQ",  "category": "INDEX",     "unit": "USD pts"},
    "CL=F":     {"name": "Crude Oil", "icon": "OIL", "category": "COMMODITY", "unit": "USD/bbl"},
    "EURUSD=X": {"name": "EUR/USD",   "icon": "EUR", "category": "FOREX",     "unit": "Rate"},
    "GBPUSD=X": {"name": "GBP/USD",   "icon": "GBP", "category": "FOREX",     "unit": "Rate"},
}


@app.get("/api/cfd/prices")
async def get_cfd_prices():
    """Return latest prices + metadata for the 10 core CFD assets."""
    sym_list = list(CFD_SYMBOLS.keys())
    result: dict = {}

    async def _fetch(sym: str) -> None:
        meta = CFD_SYMBOLS[sym]
        try:
            info  = await asyncio.to_thread(lambda: yf.Ticker(sym).fast_info)
            price = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
            prev  = getattr(info, "previous_close", None)
            change     = (price - prev)         if price and prev else None
            change_pct = (change / prev * 100)  if change and prev else None
            result[sym] = {
                **meta,
                "symbol":     sym,
                "price":      price,
                "change":     round(change,     4) if change     is not None else None,
                "change_pct": round(change_pct, 4) if change_pct is not None else None,
            }
        except Exception as exc:
            logger.warning("CFD price fetch failed  sym=%s  err=%s", sym, exc)
            result[sym] = {**meta, "symbol": sym, "price": None, "change": None, "change_pct": None}

    await asyncio.gather(*[_fetch(s) for s in sym_list])
    # Return in defined order
    return [result[s] for s in sym_list if s in result]
