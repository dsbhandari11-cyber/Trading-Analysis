import os
from dotenv import load_dotenv

load_dotenv()

APP_NAME = "Bhandari Trading Analysis"
APP_TAGLINE = "Professional Market Intelligence Dashboard"
APP_VERSION = "1.0.0"

REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL", 60))
CACHE_TTL = 60
HIST_PERIOD = "3mo"
HIST_PERIOD_SHORT = "1mo"
INTRADAY_INTERVAL = "1d"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = "trading_dashboard.log"

MAJOR_INDICES = {
    "NIFTY 50": "^NSEI",
    "BANK NIFTY": "^NSEBANK",
    "SENSEX": "^BSESN",
    "NIFTY IT": "^CNXIT",
    "NIFTY PHARMA": "^CNXPHARMA",
}

TICKER_SYMBOLS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "KOTAKBANK.NS", "AXISBANK.NS", "BHARTIARTL.NS", "ITC.NS",
    "SBIN.NS", "LT.NS", "BAJFINANCE.NS", "WIPRO.NS", "HCLTECH.NS",
    "MARUTI.NS", "TITAN.NS", "ADANIENT.NS", "NTPC.NS", "POWERGRID.NS",
    "SUNPHARMA.NS", "TATAMOTORS.NS", "JSWSTEEL.NS", "M&M.NS", "ASIANPAINT.NS",
]

NEWS_FEEDS = {
    "Economic Times Markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Moneycontrol": "https://www.moneycontrol.com/rss/marketsindia.xml",
    "NDTV Profit": "https://feeds.feedburner.com/ndtvprofit-latest",
    "Business Standard": "https://www.business-standard.com/rss/markets-106.rss",
    "Livemint Markets": "https://www.livemint.com/rss/markets",
}

DIPLOMATIC_KEYWORDS = [
    "Trump", "Modi", "India-US", "trade deal", "tariff", "bilateral",
    "diplomatic", "agreement", "sanction", "G20", "BRICS", "FTA",
    "export", "import", "India China", "India Pakistan", "geopolitical",
    "trade war", "US-India", "foreign policy",
]

RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
RSI_BULLISH = 50
VOLUME_SPIKE_MULTIPLIER = 2.0
VOLUME_MOMENTUM_MULTIPLIER = 1.5
PE_MAX_VALUE = 20
MOMENTUM_LOOKBACK = 10
NEWS_FETCH_TIMEOUT = 10
MAX_NEWS_ITEMS = 30
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

COLORS = {
    "positive": "#00d4aa",
    "negative": "#ff4444",
    "neutral": "#8b949e",
    "warning": "#f0ad4e",
    "accent": "#00d4aa",
    "bg_card": "#1c2333",
    "bg_secondary": "#161b22",
    "bg_primary": "#0d1117",
    "border": "#30363d",
    "text": "#e6edf3",
    "text_muted": "#8b949e",
}
