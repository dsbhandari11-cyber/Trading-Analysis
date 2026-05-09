# Bhandari Trading Analysis Dashboard

Professional dark-themed market intelligence dashboard built with Streamlit + Python.

## Features

- **Real-time scrolling ticker** — top NSE stocks, updates every 60 s
- **Diplomatic news banner** — Trump, Modi, India-US trade headlines
- **Home page** — Major indices (Nifty 50, Bank Nifty, Sensex), heatmap, top gainers/losers, news feed
- **Nifty 100 Screener** — RSI, Volume Ratio, P/E, Momentum Score, sortable/filterable
- **Momentum Scanner** — Breakout, Reversal, Momentum signals with ranked cards

---

## Quick Start (Windows 11)

### Prerequisites

- Python 3.11+ → https://www.python.org/downloads/
- pip (bundled with Python)

### 1. Clone / download project

```
cd d:\Claudes\Screener_1
```

### 2. Create virtual environment

```powershell
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install dependencies

```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure environment (optional)

```powershell
copy .env.example .env
# Edit .env if needed
```

### 5. Run the dashboard

```powershell
python -m streamlit run main.py
```

Browser opens automatically at **http://localhost:8501**

---

## Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m streamlit run main.py
```

---

## Deployment — Streamlit Cloud (Free Hosted URL)

1. Push this project to a GitHub repository.
2. Go to https://share.streamlit.io → **New app**
3. Select your repo, branch `main`, file `main.py`
4. Click **Deploy**
5. Your public URL: `https://your-app.streamlit.app`

> No Docker, no server config needed. Streamlit Cloud handles everything.

---

## Deployment — Render (Alternative)

1. Create account at https://render.com
2. New → **Web Service** → connect GitHub repo
3. Runtime: **Python 3**
4. Build command: `pip install -r requirements.txt`
5. Start command: `streamlit run main.py --server.port $PORT --server.headless true`
6. Click Deploy → get `https://yourapp.onrender.com`

---

## Desktop .exe (PyInstaller — Windows)

```powershell
pip install pyinstaller
pyinstaller --onefile --name "BhandariDashboard" launcher.py
```

Create `launcher.py`:

```python
import subprocess, sys, webbrowser, time

proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "main.py"])
time.sleep(4)
webbrowser.open("http://localhost:8501")
proc.wait()
```

Then run:
```powershell
dist\BhandariDashboard.exe
```

> Note: Include the full project folder alongside the .exe; PyInstaller bundles Python but not Streamlit's web assets.

---

## Data Sources

| Source | Type | Latency |
|--------|------|---------|
| yfinance / Yahoo Finance | OHLCV, P/E | ~15 min delay |
| Economic Times RSS | News | Real-time |
| Moneycontrol RSS | News | Real-time |
| NDTV Profit RSS | News | Real-time |
| Business Standard RSS | News | Real-time |

---

## Tech Stack

- **UI**: Streamlit 1.31+
- **Data**: yfinance, pandas, numpy
- **TA**: ta (RSI, MACD, Bollinger Bands)
- **Charts**: Plotly
- **News**: feedparser + RSS feeds
- **Caching**: Streamlit `@st.cache_data` (60 s TTL)

---

## Folder Structure

```
Screener_1/
├── main.py                  # Entry point
├── config.py                # All constants
├── requirements.txt
├── .env.example
├── .streamlit/
│   └── config.toml          # Dark theme
├── assets/
│   └── style.css            # Custom CSS
├── data/
│   ├── stocks_list.py       # Nifty 100 symbols
│   ├── fetcher.py           # yfinance wrapper
│   ├── technical.py         # RSI, volume, momentum
│   └── news.py              # RSS news fetcher
├── components/
│   ├── ticker_bar.py        # Scrolling ticker
│   ├── news_banner.py       # Diplomatic news banner
│   └── charts.py            # Plotly charts
├── pages/
│   ├── home.py              # Home dashboard
│   ├── nifty100.py          # Screener
│   └── momentum_scanner.py  # Scanner
└── utils/
    ├── logger.py
    └── helpers.py
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` in venv |
| Blank charts | yfinance rate-limited; wait 60 s and reload |
| Slow first load | Nifty 100 downloads 100 stocks; normal on first run (~30 s) |
| News not loading | Check internet; RSS feeds may be temporarily down |
| Port 8501 in use | `streamlit run main.py --server.port 8502` |
"# Trading-Analysis" 
