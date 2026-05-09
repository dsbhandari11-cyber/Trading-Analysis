# Bhandari Trading Analysis Dashboard — Claude Context

## Project Overview

Single-file Streamlit app (`main.py`) with modular page routing via `st.session_state.page`.
No FastAPI backend. No database. All data fetched live via yfinance and RSS.

## Architecture

```
main.py  →  pages/{home,nifty100,momentum_scanner}.py
         →  components/{ticker_bar,news_banner,charts}.py
         →  data/{fetcher,technical,news,stocks_list}.py
         →  utils/{logger,helpers}.py
         →  config.py
```

## Key Design Decisions

- **No TA-Lib**: using `ta` package (pip-installable, no C compiler needed on Windows)
- **No paid APIs**: yfinance (free, 15-min delayed) + RSS feeds
- **Caching**: `@st.cache_data(ttl=60)` on all expensive fetches
- **Rate limiting**: `batch_download()` in `data/fetcher.py` sleeps 0.3s between chunks of 20
- **Auto-refresh**: `streamlit_autorefresh` (not `st.fragment`) for broader Streamlit version support
- **Navigation**: session state buttons (not Streamlit multipage) so ticker/banner persist across pages

## Common Tasks

### Add a new stock to the ticker
Edit `config.py` → `TICKER_SYMBOLS` list.

### Add a new RSS feed
Edit `config.py` → `NEWS_FEEDS` dict.

### Change refresh interval
Edit `config.py` → `REFRESH_INTERVAL` (seconds).

### Add a new page
1. Create `pages/new_page.py` with `def render_new_page(): ...`
2. Add to `PAGES` dict in `main.py`
3. Add routing case in `main.py`

### Change theme colors
Edit `config.py` → `COLORS` dict and `assets/style.css`.

## NSE Symbol Format

yfinance requires `.NS` suffix for NSE stocks: `RELIANCE.NS`, `TCS.NS`, etc.
BSE stocks use `.BO` suffix. Indices: `^NSEI` (Nifty 50), `^NSEBANK`, `^BSESN` (Sensex).

## Run Locally

```powershell
python -m streamlit run main.py
```

## Deploy

Push to GitHub → Streamlit Cloud → select `main.py` → deploy.
Public URL: `https://yourapp.streamlit.app`
