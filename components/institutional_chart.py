"""
Institutional Chart — Full Indicator Suite
==========================================
TradingView Lightweight Charts v4.1.3 with:

  Overlays (toggle bar):
    EMA 9/21/50/200 · SMA 50/200 · Bollinger Bands(20,2)
    VWAP · Supertrend(10,3)

  Pane indicators (toggle bar):
    Volume · RSI(14) · MACD(12,26,9) · ATR(14) · ADX/DMI(14)

  SMC zone SVG overlay:
    Order Blocks · FVG · IFVG · any rect zone from caller

  Extra line series:
    Pine-computed overlays passed as extra_overlays list

  Range buttons: 1D · 5D · 1M · 3M · 6M · 1Y · 5Y · MAX

Public API:
  render_institutional_chart(symbol, timeframe, height, display_name,
                             show_volume, zones, extra_overlays)
  clear_chart_cache()
"""

from __future__ import annotations

import json
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from data.fetcher import get_history


# ── Config ────────────────────────────────────────────────────────────────────

_TF_CONFIG: dict[str, dict] = {
    "1m":  {"yf_interval": "1m",  "period": "7d",   "resample": None},
    "5m":  {"yf_interval": "5m",  "period": "60d",  "resample": None},
    "15m": {"yf_interval": "15m", "period": "60d",  "resample": None},
    "30m": {"yf_interval": "30m", "period": "60d",  "resample": None},
    "1H":  {"yf_interval": "60m", "period": "730d", "resample": None},
    "4H":  {"yf_interval": "60m", "period": "730d", "resample": "4h"},
    "1D":  {"yf_interval": "1d",  "period": "5y",   "resample": None},
    "1W":  {"yf_interval": "1wk", "period": "10y",  "resample": None},
}

_DEFAULT_RANGE: dict[str, str] = {
    "1m": "1D", "5m": "5D", "15m": "1M", "30m": "1M",
    "1H": "3M", "4H": "6M", "1D":  "1Y", "1W":  "5Y",
}

_INTRADAY_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"}

MAX_BARS = 2000


# ── Indicator computations ────────────────────────────────────────────────────

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()

def _bb(s: pd.Series, n: int = 20, mult: float = 2.0):
    mid = s.rolling(n).mean()
    sd  = s.rolling(n).std(ddof=0)
    return mid + mult * sd, mid, mid - mult * sd

def _rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d    = s.diff()
    gain = d.clip(lower=0).ewm(com=n - 1, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(com=n - 1, adjust=False).mean()
    rs   = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)

def _macd(s: pd.Series):
    fast   = s.ewm(span=12, adjust=False).mean()
    slow   = s.ewm(span=26, adjust=False).mean()
    line   = fast - slow
    signal = line.ewm(span=9, adjust=False).mean()
    return line, signal, line - signal

def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, pc = df["High"], df["Low"], df["Close"].shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(com=n - 1, adjust=False).mean()

def _adx(df: pd.DataFrame, n: int = 14):
    h, l, c = df["High"].astype(float), df["Low"].astype(float), df["Close"].astype(float)
    prev_h = h.shift(1); prev_l = l.shift(1); prev_c = c.shift(1)
    tr   = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    up   = h - prev_h
    down = prev_l - l
    pdm  = up.where((up > down) & (up > 0), 0.0)
    ndm  = down.where((down > up) & (down > 0), 0.0)
    atr  = tr.ewm(com=n - 1, adjust=False).mean().replace(0, np.nan)
    pdi  = (100 * pdm.ewm(com=n - 1, adjust=False).mean() / atr).fillna(0)
    ndi  = (100 * ndm.ewm(com=n - 1, adjust=False).mean() / atr).fillna(0)
    dx   = (100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)).fillna(0)
    adx  = dx.ewm(com=n - 1, adjust=False).mean()
    return pdi, ndi, adx

def _vwap(df: pd.DataFrame) -> pd.Series:
    if "Volume" not in df.columns:
        return pd.Series(np.nan, index=df.index)
    vol    = df["Volume"].astype(float).replace(0, np.nan)
    tp     = (df["High"] + df["Low"] + df["Close"]) / 3.0
    dates  = df.index.normalize()
    cum_pv = (tp * vol).groupby(dates).cumsum()
    cum_v  = vol.groupby(dates).cumsum()
    return (cum_pv / cum_v).ffill()

def _supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0):
    h = df["High"].values.astype(float)
    l = df["Low"].values.astype(float)
    c = df["Close"].values.astype(float)
    nb = len(c)

    prev_c = np.empty(nb); prev_c[0] = c[0]; prev_c[1:] = c[:-1]
    tr  = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr = np.zeros(nb)
    if nb >= n:
        atr[n - 1] = tr[:n].mean()
        for i in range(n, nb):
            atr[i] = (atr[i - 1] * (n - 1) + tr[i]) / n

    hl2  = (h + l) / 2.0
    up_r = hl2 + mult * atr
    dn_r = hl2 - mult * atr
    up   = up_r.copy(); dn = dn_r.copy()
    dir_ = np.ones(nb, dtype=np.int8)

    for i in range(1, nb):
        up[i] = min(up_r[i], up[i - 1]) if c[i - 1] > up[i - 1] else up_r[i]
        dn[i] = max(dn_r[i], dn[i - 1]) if c[i - 1] < dn[i - 1] else dn_r[i]
        if   dir_[i - 1] ==  1 and c[i] < dn[i]: dir_[i] = -1
        elif dir_[i - 1] == -1 and c[i] > up[i]: dir_[i] =  1
        else:                                      dir_[i] = dir_[i - 1]

    st = np.where(dir_ == 1, dn, up).astype(float)
    st[:n] = np.nan
    bull = pd.Series(np.where(dir_ == 1,  st, np.nan), index=df.index)
    bear = pd.Series(np.where(dir_ == -1, st, np.nan), index=df.index)
    return bull, bear


# ── Serialisers ───────────────────────────────────────────────────────────────

def _ts(idx) -> int:
    try:    return int(pd.Timestamp(idx).timestamp())
    except: return 0

def _ser(series: pd.Series, index) -> list[dict]:
    out = []
    for ts, v in zip(index, series):
        if pd.isna(v): continue
        out.append({"time": _ts(ts), "value": round(float(v), 6)})
    return out

def _candles(df: pd.DataFrame) -> list[dict]:
    out = []
    for ts, row in df.iterrows():
        try:
            o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
            if not all([o, h, l, c]): continue
            out.append({"time": _ts(ts), "open": round(o,6), "high": round(h,6),
                        "low": round(l,6), "close": round(c,6)})
        except: pass
    return out

def _volume(df: pd.DataFrame) -> list[dict]:
    out = []
    for ts, row in df.iterrows():
        try:
            up  = float(row["Close"]) >= float(row["Open"])
            vol = int(float(row.get("Volume") or 0))
            out.append({"time": _ts(ts), "value": vol,
                        "color": "rgba(0,212,170,.40)" if up else "rgba(244,63,94,.40)"})
        except: pass
    return out

def _hist_ser(hist: pd.Series, index) -> list[dict]:
    out = []
    for ts, v in zip(index, hist):
        if pd.isna(v): continue
        out.append({"time": _ts(ts), "value": round(float(v), 6),
                    "color": "#00d4aa55" if v >= 0 else "#f43f5e55"})
    return out


# ── Data fetch + full indicator compute (cached) ──────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def _fetch_chart_data(symbol: str, timeframe: str) -> dict | None:
    cfg = _TF_CONFIG.get(timeframe, _TF_CONFIG["1D"])
    df  = get_history(symbol, period=cfg["period"], interval=cfg["yf_interval"])
    if df is None or df.empty:
        return None

    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if cfg["resample"]:
        df = df.resample(cfg["resample"]).agg({
            "Open": "first", "High": "max", "Low": "min",
            "Close": "last", "Volume": "sum",
        }).dropna(how="any")

    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    if len(df) > MAX_BARS:
        df = df.iloc[-MAX_BARS:]

    close = df["Close"].astype(float)
    is_intraday = cfg["yf_interval"] in _INTRADAY_INTERVALS

    # Moving averages
    ema9   = _ema(close, 9)
    ema21  = _ema(close, 21)
    ema50  = _ema(close, 50)
    ema200 = _ema(close, 200)
    sma50  = _sma(close, 50)
    sma200 = _sma(close, 200)

    # Bollinger
    bb_up, bb_mid, bb_dn = _bb(close)

    # VWAP (meaningful only for intraday)
    vwap = _vwap(df) if is_intraday else pd.Series(np.nan, index=df.index)

    # Supertrend
    st_bull, st_bear = _supertrend(df)

    # Oscillators
    rsi_s             = _rsi(close)
    macd_l, macd_s, macd_h = _macd(close)

    # ATR
    atr_s = _atr(df)

    # ADX / DMI
    pdi_s, ndi_s, adx_s = _adx(df)

    last  = float(close.iloc[-1])
    prev  = float(close.iloc[-2]) if len(close) >= 2 else last
    chg   = round((last - prev) / prev * 100, 2) if prev else 0.0

    return {
        "symbol":     symbol,
        "timeframe":  timeframe,
        "lastPrice":  round(last, 6),
        "changePct":  chg,
        "isIntraday": is_intraday,
        # Price data
        "candles":    _candles(df),
        "volume":     _volume(df),
        # MA overlays
        "ema9":       _ser(ema9,   df.index),
        "ema21":      _ser(ema21,  df.index),
        "ema50":      _ser(ema50,  df.index),
        "ema200":     _ser(ema200, df.index),
        "sma50":      _ser(sma50,  df.index),
        "sma200":     _ser(sma200, df.index),
        # Bollinger
        "bbUpper":    _ser(bb_up,  df.index),
        "bbMid":      _ser(bb_mid, df.index),
        "bbLower":    _ser(bb_dn,  df.index),
        # VWAP
        "vwap":       _ser(vwap, df.index),
        # Supertrend
        "stBull":     _ser(st_bull, df.index),
        "stBear":     _ser(st_bear, df.index),
        # Pane: RSI
        "rsi":        _ser(rsi_s, df.index),
        # Pane: MACD
        "macd":       _ser(macd_l, df.index),
        "signal":     _ser(macd_s, df.index),
        "macdHist":   _hist_ser(macd_h, df.index),
        # Pane: ATR
        "atr":        _ser(atr_s, df.index),
        # Pane: ADX
        "pdi":        _ser(pdi_s, df.index),
        "ndi":        _ser(ndi_s, df.index),
        "adx":        _ser(adx_s, df.index),
    }


# ── HTML builder ──────────────────────────────────────────────────────────────

def _build_html(
    payload:        dict,
    height:         int,
    display_name:   str,
    show_volume:    bool,
    zones:          list,
    extra_overlays: list,
) -> str:
    TOP    = 42
    IND    = 32
    TF_BAR = 34
    avail  = height - TOP - IND - TF_BAR

    h_vol  = max(int(avail * 0.12), 50) if show_volume else 0
    h_rsi  = max(int(avail * 0.14), 60)
    h_macd = max(int(avail * 0.14), 60)
    h_atr  = max(int(avail * 0.10), 44)
    h_adx  = max(int(avail * 0.10), 44)
    # Main starts with vol+rsi visible; JS recalculates dynamically
    h_main = avail - h_vol - h_rsi

    is_intraday   = payload.get("isIntraday", False)
    sym_label     = display_name or payload["symbol"].replace(".NS","").replace(".BO","")
    tf_label      = payload["timeframe"]
    default_range = _DEFAULT_RANGE.get(tf_label, "3M")

    data_json     = json.dumps(payload,           ensure_ascii=False, separators=(",",":"))
    zones_json    = json.dumps(zones or [],       ensure_ascii=False, separators=(",",":"))
    overlays_json = json.dumps(extra_overlays or [], ensure_ascii=False, separators=(",",":"))

    vol_pane_html = (
        '<div class="pane" id="pane-vol">'
        '<span class="plbl">VOL</span><div id="cv"></div></div>'
    ) if show_volume else ""

    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
:root{
  --bg:#080d17;--bg2:#0a0f1a;--bg3:#0d1520;
  --border:#1e2d45;--text:#e2e8f0;--muted:#64748b;
  --up:#00d4aa;--dn:#f43f5e;
  --macd-l:#38bdf8;--macd-s:#fb923c;--rsi:#a78bfa;
  --adx:#f59e0b;--atr:#94a3b8;
}
html,body{background:var(--bg);color:var(--text);
  font-family:'Inter','Segoe UI',monospace,sans-serif;height:100vh;overflow:hidden;}
#top-bar{
  display:flex;align-items:center;gap:10px;
  padding:0 12px;height:42px;
  background:var(--bg2);border-bottom:1px solid var(--border);flex-shrink:0;
}
#sym{font-weight:800;font-size:.9rem;color:var(--up);font-family:monospace;white-space:nowrap;}
#tf-badge{background:var(--border);color:var(--muted);font-size:.68rem;
  padding:2px 7px;border-radius:4px;font-weight:700;white-space:nowrap;}
#ohlc{font-size:.68rem;color:var(--muted);font-family:monospace;
  flex:1;white-space:nowrap;overflow:hidden;}
#ind-vals{font-size:.62rem;color:var(--muted);font-family:monospace;
  white-space:nowrap;overflow:hidden;max-width:340px;flex-shrink:0;}
#chg-badge{font-size:.75rem;font-weight:700;padding:2px 7px;border-radius:4px;
  white-space:nowrap;flex-shrink:0;}
#price-live{font-size:.95rem;font-weight:700;font-family:monospace;
  color:var(--text);white-space:nowrap;flex-shrink:0;}
/* Indicator bar */
#ind-bar{
  display:flex;align-items:center;gap:3px;
  padding:3px 10px;height:32px;
  background:var(--bg2);border-bottom:1px solid var(--border);
  flex-shrink:0;overflow-x:auto;
}
#ind-bar::-webkit-scrollbar{height:3px;}
#ind-bar::-webkit-scrollbar-thumb{background:var(--border);}
.ibtn{
  padding:1px 6px;border-radius:3px;cursor:pointer;
  font-size:.63rem;font-weight:700;letter-spacing:.03em;
  border:1px solid transparent;background:transparent;
  color:var(--muted);transition:all .1s;font-family:monospace;white-space:nowrap;
  flex-shrink:0;
}
.ibtn:hover{color:var(--text);border-color:var(--border);}
.ibtn.on{color:var(--up);border-color:var(--up);background:rgba(0,212,170,.08);}
.ibtn.on.sky{color:var(--macd-l);border-color:var(--macd-l);background:rgba(56,189,248,.08);}
.ibtn.on.org{color:var(--macd-s);border-color:var(--macd-s);background:rgba(251,146,60,.08);}
.ibtn.on.red{color:var(--dn);border-color:var(--dn);background:rgba(244,63,94,.08);}
.ibtn.on.yel{color:var(--adx);border-color:var(--adx);background:rgba(245,158,11,.08);}
.ibtn.on.vio{color:var(--rsi);border-color:var(--rsi);background:rgba(167,139,250,.08);}
.isep{width:1px;height:16px;background:var(--border);margin:0 4px;flex-shrink:0;}
/* Chart panes */
#wrap{display:flex;flex-direction:column;overflow:hidden;flex:1;}
.pane{position:relative;width:100%;flex-shrink:0;}
.pane+.pane{border-top:1px solid var(--border);}
.plbl{position:absolute;top:4px;left:8px;font-size:.57rem;color:var(--muted);
  font-weight:700;text-transform:uppercase;letter-spacing:.06em;z-index:9;pointer-events:none;}
.pind-vals{position:absolute;top:4px;left:48px;font-size:.57rem;font-family:monospace;
  z-index:9;pointer-events:none;display:flex;gap:8px;}
/* TF bar */
#tf-bar{
  display:flex;align-items:center;gap:2px;
  padding:3px 10px;height:34px;
  background:var(--bg2);border-top:1px solid var(--border);flex-shrink:0;
}
.tfbtn{
  padding:2px 8px;border-radius:4px;cursor:pointer;font-size:.7rem;
  font-weight:700;letter-spacing:.03em;border:1px solid transparent;
  background:transparent;color:var(--muted);transition:all .12s;font-family:monospace;
}
.tfbtn:hover{color:var(--text);border-color:var(--border);}
.tfbtn.on{color:var(--up);border-color:var(--up);
  background:rgba(0,212,170,.08);box-shadow:0 0 0 2px rgba(0,212,170,.1);}
</style>
</head>
<body>
<div id="top-bar">
  <span id="sym">__SYM__</span>
  <span id="tf-badge">__TF__</span>
  <span id="ohlc">O:&mdash; H:&mdash; L:&mdash; C:&mdash;</span>
  <span id="ind-vals"></span>
  <span id="chg-badge"></span>
  <span id="price-live"></span>
</div>
<div id="ind-bar">
  <button class="ibtn on"  id="btn-ema9"   onclick="toggleOv('ema9')">E9</button>
  <button class="ibtn on"  id="btn-ema21"  onclick="toggleOv('ema21')">E21</button>
  <button class="ibtn on"  id="btn-ema50"  onclick="toggleOv('ema50')">E50</button>
  <button class="ibtn on"  id="btn-ema200" onclick="toggleOv('ema200')">E200</button>
  <button class="ibtn"     id="btn-sma50"  onclick="toggleOv('sma50')">S50</button>
  <button class="ibtn"     id="btn-sma200" onclick="toggleOv('sma200')">S200</button>
  <button class="ibtn"     id="btn-bb"     onclick="toggleOv('bb')">BB</button>
  <button class="ibtn"     id="btn-vwap"   onclick="toggleOv('vwap')">VWAP</button>
  <button class="ibtn"     id="btn-st"     onclick="toggleOv('st')">ST</button>
  <div class="isep"></div>
  <button class="ibtn on vio" id="btn-rsi"  onclick="togglePane('rsi')">RSI</button>
  <button class="ibtn sky"    id="btn-macd" onclick="togglePane('macd')">MACD</button>
  <button class="ibtn yel"    id="btn-atr"  onclick="togglePane('atr')">ATR</button>
  <button class="ibtn org"    id="btn-adx"  onclick="togglePane('adx')">ADX</button>
</div>
<div id="wrap">
  <div class="pane" id="pane-main">
    <span class="plbl">PRICE</span>
    <div class="pind-vals" id="ma-vals"></div>
    <div id="cm"></div>
  </div>
  __VOL_PANE__
  <div class="pane" id="pane-rsi">
    <span class="plbl">RSI(14)</span>
    <div class="pind-vals" id="rsi-val"></div>
    <div id="cr"></div>
  </div>
  <div class="pane" id="pane-macd" style="display:none;">
    <span class="plbl">MACD(12,26,9)</span>
    <div class="pind-vals" id="macd-val"></div>
    <div id="cma"></div>
  </div>
  <div class="pane" id="pane-atr" style="display:none;">
    <span class="plbl">ATR(14)</span>
    <div class="pind-vals" id="atr-val"></div>
    <div id="ca"></div>
  </div>
  <div class="pane" id="pane-adx" style="display:none;">
    <span class="plbl">ADX/DMI(14)</span>
    <div class="pind-vals" id="adx-val"></div>
    <div id="cadx"></div>
  </div>
</div>
<div id="tf-bar">
  <button class="tfbtn" id="tf-1D"  onclick="setRange('1D')">1D</button>
  <button class="tfbtn" id="tf-5D"  onclick="setRange('5D')">5D</button>
  <button class="tfbtn" id="tf-1M"  onclick="setRange('1M')">1M</button>
  <button class="tfbtn" id="tf-3M"  onclick="setRange('3M')">3M</button>
  <button class="tfbtn" id="tf-6M"  onclick="setRange('6M')">6M</button>
  <button class="tfbtn" id="tf-1Y"  onclick="setRange('1Y')">1Y</button>
  <button class="tfbtn" id="tf-5Y"  onclick="setRange('5Y')">5Y</button>
  <button class="tfbtn" id="tf-MAX" onclick="setRange('MAX')">MAX</button>
</div>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<script>
'use strict';
var D         = __DATA__;
var SMC_ZONES = __ZONES__;
var EXTRA_OVS = __OVERLAYS__;
var H_MAIN=__HMAIN__, H_VOL=__HVOL__, H_RSI=__HRSI__;
var H_MACD=__HMACD__, H_ATR=__HATR__, H_ADX=__HADX__;
var AVAIL=__AVAIL__;
var SHOW_VOL=__SHOW_VOL__;
var IS_INTRADAY=__INTRADAY__;
var DEFAULT_RANGE='__DEFAULT_RANGE__';

// ── Element heights ──────────────────────────────────────────────────────────
document.getElementById('cm').style.height = H_MAIN + 'px';
if (SHOW_VOL && document.getElementById('cv'))
  document.getElementById('cv').style.height = H_VOL + 'px';
document.getElementById('cr').style.height  = H_RSI  + 'px';
document.getElementById('cma').style.height = H_MACD + 'px';
document.getElementById('ca').style.height  = H_ATR  + 'px';
document.getElementById('cadx').style.height = H_ADX + 'px';

// ── Chart factory ────────────────────────────────────────────────────────────
var BASE_CFG = {
  layout:    { background:{ type:'solid', color:'#080d17' }, textColor:'#64748b' },
  grid:      { vertLines:{ color:'#1e2d4528', style:1 }, horzLines:{ color:'#1e2d4528', style:1 } },
  crosshair: {
    mode:     LightweightCharts.CrosshairMode.Normal,
    vertLine: { color:'#00d4aa44', width:1, labelBackgroundColor:'#0a0f1a' },
    horzLine: { color:'#00d4aa44', width:1, labelBackgroundColor:'#0a0f1a' },
  },
  handleScale:  { axisPressedMouseMove:{ time:true, price:true }, mouseWheel:true, pinch:true },
  handleScroll: { mouseWheel:true, pressedMouseMove:true, horzTouchDrag:true },
};
var PS_CFG = { borderColor:'#1e2d45', textColor:'#64748b' };
var TS_VIS = { borderColor:'#1e2d45', textColor:'#64748b', timeVisible:true, secondsVisible:false, barSpacing:6, minBarSpacing:.5 };
var TS_HID = { borderColor:'#1e2d45', visible:false };

function mkChart(elId, h, showTS) {
  return LightweightCharts.createChart(document.getElementById(elId),
    Object.assign({}, BASE_CFG, { rightPriceScale:PS_CFG, timeScale: showTS ? TS_VIS : TS_HID, width:0, height:h }));
}

var cMain = mkChart('cm',   H_MAIN, true);
var cVol  = SHOW_VOL ? mkChart('cv',  H_VOL,  false) : null;
var cRsi  = mkChart('cr',   H_RSI,  false);
var cMacd = mkChart('cma',  H_MACD, false);
var cAtr  = mkChart('ca',   H_ATR,  false);
var cAdx  = mkChart('cadx', H_ADX,  false);

// ── Candle series ────────────────────────────────────────────────────────────
var sSeries = cMain.addCandlestickSeries({
  upColor:'#00d4aa', downColor:'#f43f5e',
  borderUpColor:'#00d4aa', borderDownColor:'#f43f5e',
  wickUpColor:'#00d4aa',   wickDownColor:'#f43f5e',
  priceLineColor:'#00d4aa88', lastValueVisible:true,
});
sSeries.setData(D.candles);

// ── MA overlay series ────────────────────────────────────────────────────────
function mkLine(chart, color, width, style, title) {
  return chart.addLineSeries({
    color:color, lineWidth:width || 1,
    lineStyle: style || 0,
    priceLineVisible:false, lastValueVisible:false,
    title: title || '',
    crosshairMarkerVisible: false,
  });
}

var sEma9   = mkLine(cMain, '#00d4aa',  1,   0, 'E9');
var sEma21  = mkLine(cMain, '#38bdf8',  1,   0, 'E21');
var sEma50  = mkLine(cMain, '#fb923c',  1.5, 0, 'E50');
var sEma200 = mkLine(cMain, '#f43f5e',  1.5, 0, 'E200');
var sSma50  = mkLine(cMain, '#94a3b8',  1,   2, 'S50');
var sSma200 = mkLine(cMain, '#64748b',  1.5, 2, 'S200');

sEma9.setData(D.ema9);
sEma21.setData(D.ema21);
sEma50.setData(D.ema50);
sEma200.setData(D.ema200);
sSma50.setData(D.sma50);
sSma200.setData(D.sma200);

// ── Bollinger Bands ──────────────────────────────────────────────────────────
var sBbUp  = mkLine(cMain, '#4d9de066', 1, 2);
var sBbMid = mkLine(cMain, '#4d9de0',   1, 0, 'BB(20)');
var sBbDn  = mkLine(cMain, '#4d9de066', 1, 2);
sBbUp.setData(D.bbUpper); sBbMid.setData(D.bbMid); sBbDn.setData(D.bbLower);

// ── VWAP ─────────────────────────────────────────────────────────────────────
var sVwap = mkLine(cMain, '#f59e0b', 1.5, 1, 'VWAP');
sVwap.setData(D.vwap);

// ── Supertrend ────────────────────────────────────────────────────────────────
var sStBull = mkLine(cMain, '#00d4aa', 2, 0);
var sStBear = mkLine(cMain, '#f43f5e', 2, 0);
sStBull.setData(D.stBull);
sStBear.setData(D.stBear);

// ── Extra Pine overlays ───────────────────────────────────────────────────────
EXTRA_OVS.forEach(function(ov) {
  if (!ov.data || !ov.data.length) return;
  var s = cMain.addLineSeries({
    color: ov.color || '#00d4aa', lineWidth: ov.linewidth || 1,
    priceLineVisible:false, lastValueVisible:false, title:'',
  });
  s.setData(ov.data);
});

// ── Volume ────────────────────────────────────────────────────────────────────
var sVol = null;
if (SHOW_VOL && cVol) {
  sVol = cVol.addHistogramSeries({ priceFormat:{type:'volume'}, priceScaleId:'vol', lastValueVisible:false });
  cVol.priceScale('vol').applyOptions({ scaleMargins:{top:.1, bottom:0} });
  sVol.setData(D.volume);
}

// ── RSI ───────────────────────────────────────────────────────────────────────
var sRsi = cRsi.addLineSeries({ color:'#a78bfa', lineWidth:1.5, priceLineVisible:false, lastValueVisible:true });
sRsi.setData(D.rsi);
if (D.rsi.length >= 2) {
  var t0 = D.rsi[0].time, t1 = D.rsi[D.rsi.length-1].time;
  [[70,'rgba(244,63,94,.25)'],[50,'rgba(100,116,139,.2)'],[30,'rgba(0,212,170,.25)']].forEach(function(p) {
    var ls = cRsi.addLineSeries({ color:p[1], lineWidth:1, lineStyle:2, priceLineVisible:false, lastValueVisible:false, crosshairMarkerVisible:false });
    ls.setData([{time:t0,value:p[0]},{time:t1,value:p[0]}]);
  });
  cRsi.applyOptions({ rightPriceScale:{ scaleMargins:{top:.1,bottom:.1} } });
}

// ── MACD ──────────────────────────────────────────────────────────────────────
var sMacdLine = cMacd.addLineSeries({ color:'#38bdf8', lineWidth:1.5, priceLineVisible:false, lastValueVisible:false });
var sMacdSig  = cMacd.addLineSeries({ color:'#fb923c', lineWidth:1.2, priceLineVisible:false, lastValueVisible:false });
var sMacdHist = cMacd.addHistogramSeries({ priceScaleId:'macd', lastValueVisible:false });
sMacdLine.setData(D.macd); sMacdSig.setData(D.signal); sMacdHist.setData(D.macdHist);

// ── ATR ───────────────────────────────────────────────────────────────────────
var sAtr = cAtr.addLineSeries({ color:'#94a3b8', lineWidth:1.5, priceLineVisible:false, lastValueVisible:true });
sAtr.setData(D.atr);

// ── ADX / DMI ─────────────────────────────────────────────────────────────────
var sPdi = cAdx.addLineSeries({ color:'#00d4aa', lineWidth:1.5, priceLineVisible:false, lastValueVisible:false, title:'+DI' });
var sNdi = cAdx.addLineSeries({ color:'#f43f5e', lineWidth:1.5, priceLineVisible:false, lastValueVisible:false, title:'-DI' });
var sAdx = cAdx.addLineSeries({ color:'#f59e0b', lineWidth:2,   priceLineVisible:false, lastValueVisible:false, title:'ADX' });
sPdi.setData(D.pdi); sNdi.setData(D.ndi); sAdx.setData(D.adx);
if (D.adx.length >= 2) {
  var at0 = D.adx[0].time, at1 = D.adx[D.adx.length-1].time;
  var adxLvl = cAdx.addLineSeries({ color:'rgba(245,158,11,.3)', lineWidth:1, lineStyle:2, priceLineVisible:false, lastValueVisible:false, crosshairMarkerVisible:false });
  adxLvl.setData([{time:at0,value:25},{time:at1,value:25}]);
}

// ── Header update ─────────────────────────────────────────────────────────────
document.getElementById('sym').textContent = D.symbol.replace('.NS','').replace('.BO','');
document.getElementById('tf-badge').textContent = D.timeframe;
var fmt4 = function(n) { return parseFloat(n).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:4}); };
document.getElementById('price-live').textContent = fmt4(D.lastPrice);
var chgBadge = document.getElementById('chg-badge');
var chgPct   = D.changePct || 0;
chgBadge.textContent = (chgPct>=0?'▲ ':'▼ ') + Math.abs(chgPct).toFixed(2) + '%';
chgBadge.style.color      = chgPct>=0 ? '#00d4aa' : '#f43f5e';
chgBadge.style.background = chgPct>=0 ? 'rgba(0,212,170,.1)' : 'rgba(244,63,94,.1)';
chgBadge.style.border     = '1px solid '+(chgPct>=0?'rgba(0,212,170,.3)':'rgba(244,63,94,.3)');

// ── Overlay visibility state ──────────────────────────────────────────────────
var OV = {
  ema9:true, ema21:true, ema50:true, ema200:true,
  sma50:false, sma200:false,
  bb:false, vwap:IS_INTRADAY, st:false,
};
var OV_SERIES = {
  ema9:  [sEma9],
  ema21: [sEma21],
  ema50: [sEma50],
  ema200:[sEma200],
  sma50: [sSma50],
  sma200:[sSma200],
  bb:    [sBbUp, sBbMid, sBbDn],
  vwap:  [sVwap],
  st:    [sStBull, sStBear],
};

function applyOvVis() {
  Object.keys(OV_SERIES).forEach(function(k) {
    var vis = OV[k];
    OV_SERIES[k].forEach(function(s) { try{s.applyOptions({visible:vis});}catch(e){} });
  });
}
// Init VWAP button state
if (IS_INTRADAY) document.getElementById('btn-vwap').classList.add('on');
applyOvVis();

function toggleOv(key) {
  OV[key] = !OV[key];
  document.getElementById('btn-'+key).classList.toggle('on', OV[key]);
  applyOvVis();
  setTimeout(_forceRedraw, 30);
  _saveState();
}

// ── Pane visibility + resize ──────────────────────────────────────────────────
var PANES = [
  {name:'rsi',  chart:cRsi,  h:H_RSI,  vis:true},
  {name:'macd', chart:cMacd, h:H_MACD, vis:false},
  {name:'atr',  chart:cAtr,  h:H_ATR,  vis:false},
  {name:'adx',  chart:cAdx,  h:H_ADX,  vis:false},
];

function resize() {
  var W = document.body.clientWidth;
  var used = SHOW_VOL ? H_VOL : 0;
  PANES.forEach(function(p) { if (p.vis) used += p.h; });
  var mainH = Math.max(AVAIL - used, 100);
  document.getElementById('cm').style.height = mainH + 'px';
  cMain.applyOptions({width:W, height:mainH});
  if (cVol) cVol.applyOptions({width:W, height:H_VOL});
  PANES.forEach(function(p) { p.chart.applyOptions({width:W, height:p.h}); });
}

function togglePane(name) {
  var p = PANES.filter(function(x){return x.name===name;})[0];
  if (!p) return;
  p.vis = !p.vis;
  document.getElementById('pane-'+name).style.display = p.vis ? 'block' : 'none';
  document.getElementById('btn-'+name).classList.toggle('on', p.vis);
  resize();
  setTimeout(_forceRedraw, 50);
  _saveState();
}
window.addEventListener('resize', resize);

// ── OHLC crosshair ────────────────────────────────────────────────────────────
cMain.subscribeCrosshairMove(function(param) {
  var bar = param.seriesData && param.seriesData.get(sSeries);
  if (!bar) {
    document.getElementById('ohlc').innerHTML = 'O:&mdash; H:&mdash; L:&mdash; C:&mdash;';
    document.getElementById('ma-vals').innerHTML = '';
    return;
  }
  var up = bar.close >= bar.open, c = up ? '#00d4aa' : '#f43f5e';
  var f = fmt4;
  document.getElementById('ohlc').innerHTML =
    '<span style="color:#64748b">O:</span><span style="color:'+c+'"> '+f(bar.open)+' </span>'+
    '<span style="color:#64748b">H:</span><span style="color:#00d4aa"> '+f(bar.high)+' </span>'+
    '<span style="color:#64748b">L:</span><span style="color:#f43f5e"> '+f(bar.low)+' </span>'+
    '<span style="color:#64748b">C:</span><span style="color:'+c+';font-weight:700"> '+f(bar.close)+'</span>';
  // MA values display
  var t = param.time;
  var maHtml = '';
  var maEntries = [
    {key:'ema9', lbl:'E9', clr:'#00d4aa', map:ema9Map},
    {key:'ema21',lbl:'E21',clr:'#38bdf8', map:ema21Map},
    {key:'ema50',lbl:'E50',clr:'#fb923c', map:ema50Map},
    {key:'ema200',lbl:'E200',clr:'#f43f5e',map:ema200Map},
    {key:'vwap', lbl:'VWAP',clr:'#f59e0b',map:vwapMap},
  ];
  maEntries.forEach(function(e) {
    if (!OV[e.key]) return;
    var v = e.map.get(t);
    if (v!==undefined) maHtml += '<span style="color:'+e.clr+'">'+e.lbl+':'+f(v)+' </span>';
  });
  document.getElementById('ma-vals').innerHTML = maHtml;
});

// Pre-build lookup maps for crosshair tooltip
var ema9Map   = new Map(D.ema9.map(function(d){return[d.time,d.value];}));
var ema21Map  = new Map(D.ema21.map(function(d){return[d.time,d.value];}));
var ema50Map  = new Map(D.ema50.map(function(d){return[d.time,d.value];}));
var ema200Map = new Map(D.ema200.map(function(d){return[d.time,d.value];}));
var vwapMap   = new Map(D.vwap.map(function(d){return[d.time,d.value];}));
var volMap    = new Map(D.volume.map(function(d){return[d.time,d.value];}));
var rsiMap    = new Map(D.rsi.map(function(d){return[d.time,d.value];}));
var macdMap   = new Map(D.macd.map(function(d){return[d.time,d.value];}));
var sigMap    = new Map(D.signal.map(function(d){return[d.time,d.value];}));
var atrMap    = new Map(D.atr.map(function(d){return[d.time,d.value];}));
var adxMap    = new Map(D.adx.map(function(d){return[d.time,d.value];}));
var pdiMap    = new Map(D.pdi.map(function(d){return[d.time,d.value];}));
var ndiMap    = new Map(D.ndi.map(function(d){return[d.time,d.value];}));

// ── Pane crosshair sync ───────────────────────────────────────────────────────
cMain.subscribeCrosshairMove(function(param) {
  if (!param.time) {
    [cVol,cRsi,cMacd,cAtr,cAdx].forEach(function(c){if(c)try{c.clearCrosshairPosition();}catch(e){}});
    ['rsi-val','macd-val','atr-val','adx-val'].forEach(function(id){document.getElementById(id).innerHTML='';});
    return;
  }
  var t = param.time;
  var f2 = function(n){return parseFloat(n).toFixed(2);};
  var f4 = function(n){return parseFloat(n).toFixed(4);};

  if (cVol && sVol) { var v=volMap.get(t); if(v!==undefined)try{cVol.setCrosshairPosition(v,t,sVol);}catch(e){} }

  var r=rsiMap.get(t);
  if(r!==undefined){
    try{cRsi.setCrosshairPosition(r,t,sRsi);}catch(e){}
    var rclr = r>70?'#f43f5e':(r<30?'#00d4aa':'#a78bfa');
    document.getElementById('rsi-val').innerHTML='<span style="color:'+rclr+'">'+f2(r)+'</span>';
  }

  var ml=macdMap.get(t), ms=sigMap.get(t);
  if(ml!==undefined){
    try{cMacd.setCrosshairPosition(ml,t,sMacdLine);}catch(e){}
    document.getElementById('macd-val').innerHTML=
      '<span style="color:#38bdf8">'+f4(ml)+'</span>'+
      (ms!==undefined?'<span style="color:#fb923c"> '+f4(ms)+'</span>':'');
  }

  var at=atrMap.get(t);
  if(at!==undefined){
    try{cAtr.setCrosshairPosition(at,t,sAtr);}catch(e){}
    document.getElementById('atr-val').innerHTML='<span style="color:#94a3b8">'+f4(at)+'</span>';
  }

  var ax=adxMap.get(t), pd=pdiMap.get(t), nd=ndiMap.get(t);
  if(ax!==undefined){
    try{cAdx.setCrosshairPosition(ax,t,sAdx);}catch(e){}
    document.getElementById('adx-val').innerHTML=
      (pd!==undefined?'<span style="color:#00d4aa">+DI:'+f2(pd)+'</span>':'')+
      (nd!==undefined?'<span style="color:#f43f5e"> -DI:'+f2(nd)+'</span>':'')+
      '<span style="color:#f59e0b"> ADX:'+f2(ax)+'</span>';
  }
});

// ── Time-scale sync (all charts follow cMain) ─────────────────────────────────
var allCharts = [cMain, cRsi, cMacd, cAtr, cAdx];
if (cVol) allCharts.push(cVol);
var syncing = false;
allCharts.forEach(function(chart) {
  chart.timeScale().subscribeVisibleLogicalRangeChange(function(range) {
    if (syncing || !range) return;
    syncing = true;
    allCharts.forEach(function(c) { if (c !== chart) try{c.timeScale().setVisibleLogicalRange(range);}catch(e){} });
    syncing = false;
  });
});

// ── TF range buttons ──────────────────────────────────────────────────────────
var TF_SEC = {
  '1D':86400,'5D':86400*5,'1M':86400*30,'3M':86400*91,
  '6M':86400*183,'1Y':86400*365,'5Y':86400*365*5,'MAX':null,
};
var activeRange = '';

// ── Workspace persistence (debounced, per-symbol key) ────────────────────────
var _LS_KEY = 'ic_' + (D.symbol || 'chart');
var _saveTimer = null;
function _saveState() {
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(function() {
    try {
      var ps = {}; PANES.forEach(function(p) { ps[p.name] = p.vis; });
      localStorage.setItem(_LS_KEY, JSON.stringify({ ov: OV, panes: ps, range: activeRange }));
    } catch(e) {}
  }, 350);
}

function setRange(tf) {
  if (activeRange) { var pb=document.getElementById('tf-'+activeRange); if(pb)pb.classList.remove('on'); }
  var btn=document.getElementById('tf-'+tf); if(btn)btn.classList.add('on');
  activeRange = tf;
  var last = D.candles.length ? D.candles[D.candles.length-1] : null;
  if (!last) return;
  if (TF_SEC[tf]===null) { cMain.timeScale().fitContent(); _saveState(); return; }
  var to=last.time+3600, from=to-TF_SEC[tf];
  try { cMain.timeScale().setVisibleRange({from:from,to:to}); }
  catch(e) { cMain.timeScale().fitContent(); }
  _saveState();
}

// ── SMC zone SVG overlay ──────────────────────────────────────────────────────
(function() {
  if (!SMC_ZONES || !SMC_ZONES.length) return;
  var mainEl = document.getElementById('pane-main');
  mainEl.style.position = 'relative';
  var svg = document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:10;overflow:visible;';
  mainEl.appendChild(svg);

  function drawZones() {
    svg.innerHTML = '';
    var w = mainEl.clientWidth;
    SMC_ZONES.forEach(function(zone) {
      try {
        var y1=sSeries.priceToCoordinate(zone.high), y2=sSeries.priceToCoordinate(zone.low);
        if (y1===null||y2===null) return;
        var x1=cMain.timeScale().timeToCoordinate(zone.time_start);
        var x2=zone.time_end ? cMain.timeScale().timeToCoordinate(zone.time_end) : w;
        if (x1===null) return; if (x2===null) x2=w;
        var top=Math.min(y1,y2), zh=Math.max(Math.abs(y2-y1),2);
        var left=Math.min(x1,x2), zw=Math.max(Math.abs(x2-x1),8);
        if (top+zh<0||top>mainEl.clientHeight||left+zw<0||left>w) return;
        var rect=document.createElementNS('http://www.w3.org/2000/svg','rect');
        rect.setAttribute('x',left.toFixed(1)); rect.setAttribute('y',top.toFixed(1));
        rect.setAttribute('width',zw.toFixed(1)); rect.setAttribute('height',zh.toFixed(1));
        rect.setAttribute('fill',zone.fill_color||'#00d4aa18');
        rect.setAttribute('stroke',zone.border_color||'#00d4aa80');
        rect.setAttribute('stroke-width','1'); rect.setAttribute('rx','1');
        svg.appendChild(rect);
        if (zone.label && zh>=8) {
          var txt=document.createElementNS('http://www.w3.org/2000/svg','text');
          txt.setAttribute('x',(left+3).toFixed(1));
          txt.setAttribute('y',(top+Math.min(10,zh-2)).toFixed(1));
          txt.setAttribute('fill',zone.label_color||zone.border_color||'#00d4aa');
          txt.setAttribute('font-size','8.5'); txt.setAttribute('font-weight','700');
          txt.setAttribute('font-family',"Inter,'Segoe UI',sans-serif");
          txt.textContent = zone.label; svg.appendChild(txt);
        }
      } catch(e) {}
    });
  }
  cMain.timeScale().subscribeVisibleLogicalRangeChange(function(){requestAnimationFrame(drawZones);});
  cMain.subscribeCrosshairMove(function(){requestAnimationFrame(drawZones);});
  setTimeout(drawZones, 400);
})();

// ── Force repaint: re-apply visibility + nudge time scale ────────────────────
function _forceRedraw() {
  try {
    // Re-apply all overlay visibility so Lightweight Charts repaints
    Object.keys(OV_SERIES).forEach(function(k) {
      var vis = OV[k];
      OV_SERIES[k].forEach(function(sr) { try { sr.applyOptions({ visible: vis }); } catch(e) {} });
    });
    // Nudge the visible range to trigger an internal layout pass
    var ts = cMain.timeScale();
    var r = ts.getVisibleLogicalRange();
    if (r) { ts.setVisibleLogicalRange(r); } else { ts.fitContent(); }
  } catch(e) {}
}

// ── Full workspace restore (called after first chart paint) ───────────────────
function _restoreState() {
  try {
    var raw = localStorage.getItem(_LS_KEY);
    if (!raw) { setRange(DEFAULT_RANGE); return; }   // fresh start
    var s = JSON.parse(raw);

    // 1. Restore overlay toggles into OV map
    if (s.ov) {
      Object.keys(s.ov).forEach(function(k) { if (k in OV) OV[k] = s.ov[k]; });
    }

    // 2. Apply visibility to every overlay series
    applyOvVis();

    // 3. Sync indicator-bar button classes to match restored OV
    Object.keys(OV).forEach(function(k) {
      var btn = document.getElementById('btn-' + k);
      if (btn) btn.classList.toggle('on', OV[k]);
    });

    // 4. Restore pane visibility + sync pane buttons
    if (s.panes) {
      PANES.forEach(function(p) {
        if (p.name in s.panes) {
          p.vis = s.panes[p.name];
          var el  = document.getElementById('pane-' + p.name);
          var btn = document.getElementById('btn-'  + p.name);
          if (el)  el.style.display = p.vis ? 'block' : 'none';
          if (btn) btn.classList.toggle('on', p.vis);
        }
      });
    }

    // 5. Recalculate chart heights with restored pane layout
    resize();

    // 6. Restore visible range button
    if (s.range) activeRange = s.range;
    setRange(activeRange || DEFAULT_RANGE);

    // 7. Force two-stage repaint: immediate + after 80 ms (covers async chart settle)
    _forceRedraw();
    setTimeout(_forceRedraw, 80);

  } catch(e) {
    // Fallback: safe defaults
    try { setRange(DEFAULT_RANGE); } catch(e2) {}
  }
}

// ── Init: size charts, then restore workspace after first paint ───────────────
resize();
requestAnimationFrame(_restoreState);
</script>
</body>
</html>"""

    return (html
        .replace("__SYM__",            sym_label)
        .replace("__TF__",             tf_label)
        .replace("__VOL_PANE__",       vol_pane_html)
        .replace("__DATA__",           data_json)
        .replace("__ZONES__",          zones_json)
        .replace("__OVERLAYS__",       overlays_json)
        .replace("__HMAIN__",          str(h_main))
        .replace("__HVOL__",           str(h_vol))
        .replace("__HRSI__",           str(h_rsi))
        .replace("__HMACD__",          str(h_macd))
        .replace("__HATR__",           str(h_atr))
        .replace("__HADX__",           str(h_adx))
        .replace("__AVAIL__",          str(avail))
        .replace("__SHOW_VOL__",       "true" if show_volume else "false")
        .replace("__INTRADAY__",       "true" if is_intraday else "false")
        .replace("__DEFAULT_RANGE__",  default_range)
    )


# ── Public API ────────────────────────────────────────────────────────────────

def render_institutional_chart(
    symbol:         str,
    timeframe:      str  = "1D",
    height:         int  = 580,
    display_name:   str  = "",
    show_volume:    bool = True,
    zones:          list = None,
    extra_overlays: list = None,
) -> None:
    """
    Render a full-indicator institutional dark chart.

    Args:
        symbol:         yfinance ticker (e.g. "GC=F", "^NSEI", "RELIANCE.NS")
        timeframe:      "1m" | "5m" | "15m" | "30m" | "1H" | "4H" | "1D" | "1W"
        height:         total component height in pixels
        display_name:   label shown in chart header (defaults to cleaned symbol)
        show_volume:    whether to show the volume pane (default ON)
        zones:          SMC zone dicts [{time_start,time_end,high,low,fill_color,...}]
        extra_overlays: pre-computed line series [{color,linewidth,data:[{time,value}]}]
    """
    with st.spinner(f"Loading {display_name or symbol} {timeframe}…"):
        payload = _fetch_chart_data(symbol, timeframe)

    if payload is None:
        st.warning(
            f"No chart data for **{symbol}** ({timeframe}). "
            "Check your connection or try a different timeframe."
        )
        return

    if display_name:
        payload = dict(payload, symbol=display_name)

    html = _build_html(payload, height, display_name, show_volume, zones, extra_overlays)
    components.html(html, height=height + 6, scrolling=False)


def clear_chart_cache() -> None:
    """Bust cached chart data (call after manual refresh)."""
    _fetch_chart_data.clear()
