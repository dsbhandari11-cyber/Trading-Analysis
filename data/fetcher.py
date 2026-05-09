"""
yfinance data fetcher with Streamlit caching and rate-limit protection.
All cache TTLs default to config.CACHE_TTL (60 seconds).
"""

import time
import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from typing import Optional, List, Dict
from utils.logger import get_logger
from config import CACHE_TTL, HIST_PERIOD, HIST_PERIOD_SHORT, INTRADAY_INTERVAL

log = get_logger(__name__)

_BATCH_DELAY = 0.3  # seconds between batch downloads to avoid rate limits


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_history(symbol: str, period: str = HIST_PERIOD, interval: str = INTRADAY_INTERVAL) -> Optional[pd.DataFrame]:
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            log.warning("No history data for %s", symbol)
            return None
        df.index = pd.to_datetime(df.index)
        return df
    except Exception as e:
        log.error("get_history(%s): %s", symbol, e)
        return None


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_stock_info(symbol: str) -> Dict:
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        return info
    except Exception as e:
        log.error("get_stock_info(%s): %s", symbol, e)
        return {}


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_current_price(symbol: str) -> Optional[float]:
    try:
        info = get_stock_info(symbol)
        price = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
        )
        return float(price) if price else None
    except Exception:
        return None


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_price_change(symbol: str) -> Dict:
    try:
        info = get_stock_info(symbol)
        current = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
        prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose") or 0.0
        change = current - prev_close
        pct_change = (change / prev_close * 100) if prev_close else 0.0
        return {
            "current": float(current),
            "prev_close": float(prev_close),
            "change": float(change),
            "pct_change": float(pct_change),
        }
    except Exception as e:
        log.error("get_price_change(%s): %s", symbol, e)
        return {"current": 0.0, "prev_close": 0.0, "change": 0.0, "pct_change": 0.0}


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_index_data(symbol: str) -> Dict:
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        hist = ticker.history(period="5d", interval="1d", auto_adjust=True)

        current = info.get("regularMarketPrice") or info.get("previousClose") or 0.0
        prev = info.get("previousClose") or info.get("regularMarketPreviousClose") or 0.0

        if hist is not None and len(hist) >= 2:
            current = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2])

        change = current - prev
        pct_change = (change / prev * 100) if prev else 0.0

        hist_1m = None
        if hist is not None and not hist.empty:
            hist_1m = hist

        return {
            "current": round(float(current), 2),
            "prev_close": round(float(prev), 2),
            "change": round(float(change), 2),
            "pct_change": round(float(pct_change), 2),
            "history": hist_1m,
        }
    except Exception as e:
        log.error("get_index_data(%s): %s", symbol, e)
        return {"current": 0.0, "prev_close": 0.0, "change": 0.0, "pct_change": 0.0, "history": None}


@st.cache_data(ttl=CACHE_TTL * 3, show_spinner=False)
def batch_download(symbols: List[str], period: str = HIST_PERIOD) -> Dict[str, pd.DataFrame]:
    """Download OHLCV history for multiple symbols in one yfinance call."""
    results: Dict[str, pd.DataFrame] = {}
    chunk_size = 20
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i: i + chunk_size]
        try:
            raw = yf.download(
                chunk,
                period=period,
                interval="1d",
                auto_adjust=True,
                group_by="ticker",
                threads=True,
                progress=False,
            )
            if raw.empty:
                continue
            for sym in chunk:
                try:
                    if len(chunk) == 1:
                        df = raw.copy()
                    else:
                        df = raw[sym].dropna(how="all")
                    if df is not None and not df.empty:
                        results[sym] = df
                except Exception:
                    pass
        except Exception as e:
            log.error("batch_download chunk %s: %s", chunk, e)
        if i + chunk_size < len(symbols):
            time.sleep(_BATCH_DELAY)
    return results


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_ticker_prices(symbols: List[str]) -> List[Dict]:
    """Fast price fetch for ticker bar using batch download."""
    results = []
    try:
        sym_str = " ".join(symbols)
        raw = yf.download(
            sym_str,
            period="2d",
            interval="1d",
            auto_adjust=True,
            group_by="ticker",
            threads=True,
            progress=False,
        )
        for sym in symbols:
            try:
                if len(symbols) == 1:
                    closes = raw["Close"]
                else:
                    closes = raw[sym]["Close"]
                closes = closes.dropna()
                if len(closes) >= 2:
                    cur = float(closes.iloc[-1])
                    prev = float(closes.iloc[-2])
                    pct = (cur - prev) / prev * 100
                    results.append({"symbol": sym, "price": cur, "pct_change": pct})
                elif len(closes) == 1:
                    results.append({"symbol": sym, "price": float(closes.iloc[-1]), "pct_change": 0.0})
            except Exception:
                pass
    except Exception as e:
        log.error("get_ticker_prices: %s", e)
    return results


@st.cache_data(ttl=CACHE_TTL * 5, show_spinner=False)
def get_pe_ratio(symbol: str) -> Optional[float]:
    try:
        info = get_stock_info(symbol)
        pe = info.get("trailingPE") or info.get("forwardPE")
        return float(pe) if pe and pe == pe else None
    except Exception:
        return None


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_gainers_losers(symbols: List[str], top_n: int = 10) -> Dict:
    """Return top N gainers and losers from a list of symbols."""
    price_data = get_ticker_prices(symbols)
    sorted_by_change = sorted(price_data, key=lambda x: x.get("pct_change", 0), reverse=True)
    return {
        "gainers": sorted_by_change[:top_n],
        "losers": sorted_by_change[-top_n:][::-1],
    }
