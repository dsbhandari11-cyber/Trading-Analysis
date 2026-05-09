"""
News fetcher using RSS feeds.
No paid API required. All feeds are public.
"""

import time
import requests
import streamlit as st
import feedparser
from typing import List, Dict
from datetime import datetime
from config import NEWS_FEEDS, DIPLOMATIC_KEYWORDS, NEWS_FETCH_TIMEOUT, MAX_NEWS_ITEMS, CACHE_TTL
from utils.logger import get_logger

log = get_logger(__name__)

_FEED_CACHE: Dict[str, dict] = {}
_CACHE_EXPIRY: Dict[str, float] = {}
_CACHE_DURATION = 120.0  # seconds


def _fetch_feed(url: str) -> List[Dict]:
    now = time.time()
    if url in _FEED_CACHE and now < _CACHE_EXPIRY.get(url, 0):
        return _FEED_CACHE[url]

    items = []
    try:
        headers = {"User-Agent": "BhandariTradingDashboard/1.0 (+trading-dashboard)"}
        resp = requests.get(url, timeout=NEWS_FETCH_TIMEOUT, headers=headers)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        for entry in feed.entries[:20]:
            title = getattr(entry, "title", "") or ""
            summary = getattr(entry, "summary", "") or ""
            link = getattr(entry, "link", "#") or "#"
            pub = getattr(entry, "published", "") or getattr(entry, "updated", "") or ""
            items.append({"title": title.strip(), "summary": summary.strip(), "link": link, "published": pub})
    except Exception as e:
        log.warning("Feed fetch failed (%s): %s", url, e)

    _FEED_CACHE[url] = items
    _CACHE_EXPIRY[url] = now + _CACHE_DURATION
    return items


@st.cache_data(ttl=CACHE_TTL * 2, show_spinner=False)
def fetch_all_headlines(max_items: int = MAX_NEWS_ITEMS) -> List[Dict]:
    all_items: List[Dict] = []
    for source, url in NEWS_FEEDS.items():
        try:
            items = _fetch_feed(url)
            for item in items:
                item["source"] = source
                all_items.append(item)
        except Exception as e:
            log.warning("Failed to fetch %s: %s", source, e)

    seen = set()
    unique = []
    for item in all_items:
        key = item["title"][:60]
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique[:max_items]


@st.cache_data(ttl=CACHE_TTL * 2, show_spinner=False)
def fetch_diplomatic_news(max_items: int = 5) -> List[Dict]:
    all_headlines = fetch_all_headlines(MAX_NEWS_ITEMS)
    diplomatic = []
    for item in all_headlines:
        text = (item["title"] + " " + item["summary"]).lower()
        if any(kw.lower() in text for kw in DIPLOMATIC_KEYWORDS):
            diplomatic.append(item)
        if len(diplomatic) >= max_items:
            break
    return diplomatic


@st.cache_data(ttl=CACHE_TTL * 2, show_spinner=False)
def fetch_stock_related_news(symbol: str, max_items: int = 5) -> List[Dict]:
    clean_sym = symbol.replace(".NS", "").replace(".BO", "").lower()
    all_headlines = fetch_all_headlines(MAX_NEWS_ITEMS)
    related = []
    for item in all_headlines:
        text = (item["title"] + " " + item["summary"]).lower()
        if clean_sym in text:
            related.append(item)
        if len(related) >= max_items:
            break
    return related


def ticker_headline_text(max_items: int = 10) -> str:
    """Returns a single string for use in the news ticker."""
    headlines = fetch_all_headlines(max_items)
    if not headlines:
        return "Market news loading... | "
    parts = []
    for item in headlines[:max_items]:
        title = item["title"]
        source = item.get("source", "")
        parts.append(f"📰 {title}  [{source}]")
    return "     •     ".join(parts)


def diplomatic_ticker_text() -> str:
    """Diplomatic news for the banner."""
    items = fetch_diplomatic_news(5)
    if not items:
        return "No diplomatic news available at this time."
    return "  |  ".join(f"🌐 {item['title']}" for item in items)
