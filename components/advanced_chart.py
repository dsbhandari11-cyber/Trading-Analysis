"""
Advanced trading chart component using TradingView Lightweight Charts (free, Apache-2.0).
Renders a professional multi-pane chart with EMA/SMA/BB/VWAP/RSI/MACD/Volume.
"""

from __future__ import annotations

import json
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np

from data.fetcher import get_history

# Interval → (yfinance interval, fetch period)
_INTERVAL_MAP: dict[str, tuple[str, str]] = {
    "1m":  ("1m",  "5d"),
    "5m":  ("5m",  "60d"),
    "15m": ("15m", "60d"),
    "30m": ("30m", "60d"),
    "1h":  ("1h",  "2y"),
    "1d":  ("1d",  "5y"),
}


# ── Indicator computation ────────────────────────────────────────────────────

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()

def _rsi(s: pd.Series, n: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0).ewm(com=n - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=n - 1, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)

def _macd(s: pd.Series):
    fast = s.ewm(span=12, adjust=False).mean()
    slow = s.ewm(span=26, adjust=False).mean()
    line = fast - slow
    signal = line.ewm(span=9, adjust=False).mean()
    return line, signal, line - signal

def _bollinger(s: pd.Series, n: int = 20, k: float = 2.0):
    mid = _sma(s, n)
    std = s.rolling(n).std()
    return mid + k * std, mid, mid - k * std

def _vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    return (tp * df["Volume"]).cumsum() / df["Volume"].replace(0, np.nan).cumsum()


# ── Data serialisation ───────────────────────────────────────────────────────

def _line(series: pd.Series, index) -> list[dict]:
    out = []
    for ts, v in zip(index, series):
        if pd.isna(v):
            continue
        try:
            out.append({"time": int(ts.timestamp()), "value": round(float(v), 4)})
        except Exception:
            pass
    return out

def _candles(df: pd.DataFrame) -> list[dict]:
    out = []
    for ts, row in df.iterrows():
        try:
            out.append({
                "time":   int(ts.timestamp()),
                "open":   round(float(row["Open"]),   2),
                "high":   round(float(row["High"]),   2),
                "low":    round(float(row["Low"]),    2),
                "close":  round(float(row["Close"]),  2),
                "volume": int(float(row.get("Volume") or 0)),
            })
        except Exception:
            pass
    return out

def _volume(df: pd.DataFrame) -> list[dict]:
    out = []
    for ts, row in df.iterrows():
        try:
            up = float(row["Close"]) >= float(row["Open"])
            out.append({
                "time":  int(ts.timestamp()),
                "value": int(float(row.get("Volume") or 0)),
                "color": "rgba(0,212,170,0.5)" if up else "rgba(255,68,68,0.5)",
            })
        except Exception:
            pass
    return out

def _macd_hist(hist_series: pd.Series, index) -> list[dict]:
    out = []
    for ts, v in zip(index, hist_series):
        if pd.isna(v):
            continue
        try:
            out.append({
                "time":  int(ts.timestamp()),
                "value": round(float(v), 6),
                "color": "#00d4aa" if v >= 0 else "#ff4444",
            })
        except Exception:
            pass
    return out


# ── HTML generator ───────────────────────────────────────────────────────────

def _build_html(payload: dict, height: int) -> str:
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    # Heights for each pane
    top_bars  = 44 + 36      # top-bar + indicator-bar
    tf_bar    = 36
    avail     = height - top_bars - tf_bar
    h_main    = int(avail * 0.62)
    h_vol     = int(avail * 0.14)
    h_rsi     = int(avail * 0.12)
    h_macd    = int(avail * 0.12)

    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box;}
:root{
  --bg:#0d1117;--bg2:#161b22;--bg3:#1c2333;
  --border:#30363d;--text:#e6edf3;--muted:#8b949e;
  --teal:#00d4aa;--red:#ff4444;--gold:#f0ad4e;
  --blue:#4d9de0;--purple:#7c57ff;--orange:#ff7f50;
}
html,body{background:var(--bg);color:var(--text);
  font-family:'Inter','Segoe UI',monospace,sans-serif;
  height:100vh;overflow:hidden;}
#top-bar{
  display:flex;align-items:center;gap:12px;
  padding:0 12px;height:44px;
  background:var(--bg2);border-bottom:1px solid var(--border);
  flex-shrink:0;
}
#sym{font-weight:800;font-size:.9rem;color:var(--teal);font-family:monospace;}
#price{font-size:1rem;font-weight:700;font-family:monospace;}
#ohlc{font-size:.72rem;color:var(--muted);font-family:monospace;flex:1;white-space:nowrap;}
#chg-badge{
  font-size:.78rem;font-weight:700;font-family:monospace;
  padding:2px 8px;border-radius:4px;
}
#fs-btn{
  background:none;border:1px solid var(--border);color:var(--muted);
  border-radius:5px;padding:3px 10px;cursor:pointer;font-size:.72rem;
  transition:all .2s;white-space:nowrap;
}
#fs-btn:hover{border-color:var(--teal);color:var(--teal);box-shadow:0 0 6px rgba(0,212,170,.2);}
#ind-bar{
  display:flex;align-items:center;gap:5px;flex-wrap:wrap;
  padding:4px 12px;height:36px;min-height:36px;
  background:var(--bg2);border-bottom:1px solid var(--border);flex-shrink:0;
}
.sep{color:var(--border);margin:0 2px;}
.lbl{color:var(--muted);font-size:.68rem;white-space:nowrap;}
.ibtn{
  padding:2px 9px;border-radius:4px;cursor:pointer;
  font-size:.7rem;font-weight:600;letter-spacing:.02em;
  border:1px solid var(--border);background:transparent;
  color:var(--muted);transition:all .15s;white-space:nowrap;
}
.ibtn:hover:not(.on){border-color:var(--muted);color:var(--text);}
.ibtn.on{background:rgba(0,212,170,.1);border-color:var(--teal);
  color:var(--teal);box-shadow:0 0 8px rgba(0,212,170,.2);}
.ibtn.e20{color:var(--blue)!important;}
.ibtn.e20.on{border-color:var(--blue)!important;
  background:rgba(77,157,224,.1)!important;box-shadow:0 0 8px rgba(77,157,224,.2)!important;}
.ibtn.e50{color:var(--gold)!important;}
.ibtn.e50.on{border-color:var(--gold)!important;
  background:rgba(240,173,78,.1)!important;box-shadow:0 0 8px rgba(240,173,78,.2)!important;}
.ibtn.e200{color:#a78bfa!important;}
.ibtn.e200.on{border-color:#a78bfa!important;background:rgba(167,139,250,.1)!important;}
.ibtn.s20{color:var(--purple)!important;}
.ibtn.s20.on{border-color:var(--purple)!important;background:rgba(124,87,255,.1)!important;}
.ibtn.bb{color:rgba(0,212,170,.8)!important;}
.ibtn.bb.on{border-color:var(--teal)!important;background:rgba(0,212,170,.08)!important;}
.ibtn.vw{color:var(--orange)!important;}
.ibtn.vw.on{border-color:var(--orange)!important;background:rgba(255,127,80,.1)!important;}
#wrap{display:flex;flex-direction:column;overflow:hidden;}
.pane{position:relative;width:100%;flex-shrink:0;}
.pane+.pane{border-top:1px solid var(--border);}
.plbl{
  position:absolute;top:4px;left:8px;
  font-size:.6rem;color:var(--muted);font-weight:700;
  text-transform:uppercase;letter-spacing:.06em;z-index:9;pointer-events:none;
  background:rgba(13,17,23,.7);padding:1px 4px;border-radius:3px;
}
#tf-bar{
  display:flex;align-items:center;gap:3px;
  padding:4px 12px;height:36px;flex-shrink:0;
  background:var(--bg2);border-top:1px solid var(--border);
}
.tfbtn{
  padding:3px 9px;border-radius:4px;cursor:pointer;
  font-size:.73rem;font-weight:700;letter-spacing:.03em;
  border:1px solid transparent;background:transparent;
  color:var(--muted);transition:all .15s;font-family:monospace;
}
.tfbtn:hover{color:var(--text);border-color:var(--border);}
.tfbtn.on{
  color:var(--teal);border-color:var(--teal);
  background:rgba(0,212,170,.1);
  box-shadow:0 0 10px rgba(0,212,170,.25);
}
#interval-pill{
  margin-left:auto;font-size:.7rem;color:var(--muted);
  font-family:monospace;background:var(--bg3);
  border:1px solid var(--border);border-radius:4px;padding:2px 8px;
}
</style>
</head>
<body>
<div id="top-bar">
  <span id="sym"></span>
  <span id="price"></span>
  <span id="chg-badge"></span>
  <span id="ohlc">O:&mdash; H:&mdash; L:&mdash; C:&mdash;</span>
  <button id="fs-btn" onclick="toggleFS()">&#x26F6; Full</button>
</div>
<div id="ind-bar">
  <span class="lbl">Overlays:</span>
  <button class="ibtn e20 on" id="b-e20" onclick="tog('e20')">EMA 20</button>
  <button class="ibtn e50 on" id="b-e50" onclick="tog('e50')">EMA 50</button>
  <button class="ibtn e200"   id="b-e200" onclick="tog('e200')">EMA 200</button>
  <button class="ibtn s20"    id="b-s20"  onclick="tog('s20')">SMA 20</button>
  <button class="ibtn bb"     id="b-bb"   onclick="tog('bb')">Bollinger</button>
  <button class="ibtn vw"     id="b-vw"   onclick="tog('vw')">VWAP</button>
  <span class="sep">|</span>
  <span class="lbl">Panes:</span>
  <button class="ibtn on" id="b-vol"  onclick="togPane('vol')">Volume</button>
  <button class="ibtn on" id="b-rsi"  onclick="togPane('rsi')">RSI</button>
  <button class="ibtn"    id="b-macd" onclick="togPane('macd')">MACD</button>
</div>
<div id="wrap">
  <div class="pane" id="pane-main"><span class="plbl">PRICE</span><div id="cm"></div></div>
  <div class="pane" id="pane-vol" ><span class="plbl">VOLUME</span><div id="cv"></div></div>
  <div class="pane" id="pane-rsi" ><span class="plbl">RSI(14)</span><div id="cr"></div></div>
  <div class="pane" id="pane-macd"><span class="plbl">MACD(12,26,9)</span><div id="cma"></div></div>
</div>
<div id="tf-bar">
  <button class="tfbtn" id="tf-1D"  onclick="setTF('1D')">1D</button>
  <button class="tfbtn" id="tf-5D"  onclick="setTF('5D')">5D</button>
  <button class="tfbtn" id="tf-1M"  onclick="setTF('1M')">1M</button>
  <button class="tfbtn" id="tf-3M"  onclick="setTF('3M')">3M</button>
  <button class="tfbtn" id="tf-6M"  onclick="setTF('6M')">6M</button>
  <button class="tfbtn" id="tf-1Y"  onclick="setTF('1Y')">1Y</button>
  <button class="tfbtn" id="tf-5Y"  onclick="setTF('5Y')">5Y</button>
  <button class="tfbtn" id="tf-MAX" onclick="setTF('MAX')">MAX</button>
  <span id="interval-pill"></span>
</div>
<script>
const D = __DATA__;
const H_MAIN=__HMAIN__,H_VOL=__HVOL__,H_RSI=__HRSI__,H_MACD=__HMACD__;

// ── Set up pane heights ───────────────────────────────────────────────────
document.getElementById('cm').style.height=H_MAIN+'px';
document.getElementById('cv').style.height=H_VOL+'px';
document.getElementById('cr').style.height=H_RSI+'px';
document.getElementById('cma').style.height=H_MACD+'px';

// ── Chart factory ──────────────────────────────────────────────────────────
const BASE={
  layout:{background:{type:'solid',color:'#0d1117'},textColor:'#8b949e'},
  grid:{vertLines:{color:'#21262d'},horzLines:{color:'#21262d'}},
  crosshair:{
    mode:LightweightCharts.CrosshairMode.Normal,
    vertLine:{color:'#00d4aa55',width:1,style:3,labelBackgroundColor:'#161b22'},
    horzLine:{color:'#00d4aa55',width:1,style:3,labelBackgroundColor:'#161b22'},
  },
  handleScale:{axisPressedMouseMove:{time:true,price:true}},
  handleScroll:{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true},
};
const BORDER={borderColor:'#30363d'};
const TS_COMMON={...BORDER,timeVisible:true,secondsVisible:false,barSpacing:6,minBarSpacing:0.5};

function mkChart(el,h,showTS){
  return LightweightCharts.createChart(el,{
    ...BASE,
    rightPriceScale:BORDER,
    timeScale:showTS?TS_COMMON:{...TS_COMMON,visible:false},
    width:0,height:h,
  });
}
const cMain=mkChart(document.getElementById('cm'),  H_MAIN, true);
const cVol =mkChart(document.getElementById('cv'),  H_VOL,  false);
const cRsi =mkChart(document.getElementById('cr'),  H_RSI,  false);
const cMacd=mkChart(document.getElementById('cma'), H_MACD, false);

// ── Series — main chart ────────────────────────────────────────────────────
const sSeries=cMain.addCandlestickSeries({
  upColor:'#00d4aa',downColor:'#ff4444',
  borderUpColor:'#00d4aa',borderDownColor:'#ff4444',
  wickUpColor:'#00d4aa',wickDownColor:'#ff4444',
  priceLineColor:'#00d4aa88',lastValueVisible:true,
});
sSeries.setData(D.candles);

const sE20 =cMain.addLineSeries({color:'#4d9de0',lineWidth:1.5,priceLineVisible:false,lastValueVisible:false});
const sE50 =cMain.addLineSeries({color:'#f0ad4e',lineWidth:1.5,lineStyle:2,priceLineVisible:false,lastValueVisible:false});
const sE200=cMain.addLineSeries({color:'#a78bfa',lineWidth:1.2,lineStyle:3,priceLineVisible:false,lastValueVisible:false});
const sS20 =cMain.addLineSeries({color:'#7c57ff',lineWidth:1.2,priceLineVisible:false,lastValueVisible:false});
const sBBU =cMain.addLineSeries({color:'rgba(0,212,170,.4)',lineWidth:1,priceLineVisible:false,lastValueVisible:false});
const sBBM =cMain.addLineSeries({color:'rgba(0,212,170,.2)',lineWidth:1,lineStyle:2,priceLineVisible:false,lastValueVisible:false});
const sBBL =cMain.addLineSeries({color:'rgba(0,212,170,.4)',lineWidth:1,priceLineVisible:false,lastValueVisible:false});
const sVWAP=cMain.addLineSeries({color:'#ff7f50',lineWidth:1.5,priceLineVisible:false,lastValueVisible:false});

sE20.setData(D.ema20); sE50.setData(D.ema50); sE200.setData(D.ema200); sS20.setData(D.sma20);
sBBU.setData(D.bbU);   sBBM.setData(D.bbM);   sBBL.setData(D.bbL);
if(D.vwap.length) sVWAP.setData(D.vwap);

// Default visibility
[sE200,sS20,sBBU,sBBM,sBBL,sVWAP].forEach(s=>s.applyOptions({visible:false}));
if(!D.vwap.length) sVWAP.applyOptions({visible:false});

// ── Series — volume ────────────────────────────────────────────────────────
const sVol=cVol.addHistogramSeries({priceFormat:{type:'volume'},priceScaleId:'vol',lastValueVisible:false});
sVol.setData(D.volume);

// ── Series — RSI ───────────────────────────────────────────────────────────
const sRsi=cRsi.addLineSeries({color:'#00d4aa',lineWidth:1.5,priceLineVisible:false,lastValueVisible:true});
sRsi.setData(D.rsi);
// RSI bands
if(D.rsi.length>=2){
  const t0=D.rsi[0].time, t1=D.rsi[D.rsi.length-1].time;
  [[70,'rgba(255,68,68,.35)'],[50,'rgba(139,148,158,.25)'],[30,'rgba(0,212,170,.35)']].forEach(([lvl,clr])=>{
    const ls=cRsi.addLineSeries({color:clr,lineWidth:1,lineStyle:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
    ls.setData([{time:t0,value:lvl},{time:t1,value:lvl}]);
  });
  cRsi.applyOptions({rightPriceScale:{scaleMargins:{top:.1,bottom:.1}}});
}

// ── Series — MACD ──────────────────────────────────────────────────────────
const sMacdLine  =cMacd.addLineSeries({color:'#4d9de0',lineWidth:1.5,priceLineVisible:false,lastValueVisible:false});
const sMacdSig   =cMacd.addLineSeries({color:'#ff7f50',lineWidth:1.2,priceLineVisible:false,lastValueVisible:false});
const sMacdHist  =cMacd.addHistogramSeries({priceScaleId:'macd',lastValueVisible:false});
sMacdLine.setData(D.macd); sMacdSig.setData(D.signal); sMacdHist.setData(D.macdHist);
document.getElementById('pane-macd').style.display='none'; // hidden by default

// ── Header ─────────────────────────────────────────────────────────────────
document.getElementById('sym').textContent=D.symbol;
document.getElementById('price').textContent='₹'+D.lastPrice.toFixed(2);
document.getElementById('interval-pill').textContent='⏱ '+D.interval;

const chgBadge=document.getElementById('chg-badge');
const chgPct=D.changePct||0;
chgBadge.textContent=(chgPct>=0?'▲':'▼')+' '+Math.abs(chgPct).toFixed(2)+'%';
chgBadge.style.color=chgPct>=0?'#00d4aa':'#ff4444';
chgBadge.style.background=chgPct>=0?'rgba(0,212,170,.1)':'rgba(255,68,68,.1)';
chgBadge.style.border='1px solid '+(chgPct>=0?'rgba(0,212,170,.3)':'rgba(255,68,68,.3)');

// ── Crosshair OHLC tooltip ─────────────────────────────────────────────────
cMain.subscribeCrosshairMove(param=>{
  const bar=param.seriesData&&param.seriesData.get(sSeries);
  if(!bar){document.getElementById('ohlc').innerHTML='O:&mdash; H:&mdash; L:&mdash; C:&mdash;';return;}
  const up=bar.close>=bar.open;
  const c=up?'#00d4aa':'#ff4444';
  document.getElementById('ohlc').innerHTML=
    `<span style="color:#8b949e">O:</span><span style="color:${c}"> ${bar.open.toFixed(2)} </span>`+
    `<span style="color:#8b949e">H:</span><span style="color:#00d4aa"> ${bar.high.toFixed(2)} </span>`+
    `<span style="color:#8b949e">L:</span><span style="color:#ff4444"> ${bar.low.toFixed(2)} </span>`+
    `<span style="color:#8b949e">C:</span><span style="color:${c};font-weight:700"> ${bar.close.toFixed(2)}</span>`;
});

// ── Lookup maps for crosshair sync ─────────────────────────────────────────
const volMap =new Map(D.volume.map(d=>[d.time,d.value]));
const rsiMap =new Map(D.rsi.map(d=>[d.time,d.value]));
const macdMap=new Map(D.macd.map(d=>[d.time,d.value]));

cMain.subscribeCrosshairMove(param=>{
  if(!param.time){
    try{cVol.clearCrosshairPosition();}catch(e){}
    try{cRsi.clearCrosshairPosition();}catch(e){}
    try{cMacd.clearCrosshairPosition();}catch(e){}
    return;
  }
  const t=param.time;
  const v=volMap.get(t); if(v!==undefined) try{cVol.setCrosshairPosition(v,t,sVol);}catch(e){}
  const r=rsiMap.get(t); if(r!==undefined) try{cRsi.setCrosshairPosition(r,t,sRsi);}catch(e){}
  const m=macdMap.get(t);if(m!==undefined) try{cMacd.setCrosshairPosition(m,t,sMacdLine);}catch(e){}
});

// ── Time-scale sync ────────────────────────────────────────────────────────
const allCharts=[cMain,cVol,cRsi,cMacd];
let syncing=false;
allCharts.forEach(chart=>{
  chart.timeScale().subscribeVisibleLogicalRangeChange(range=>{
    if(syncing||!range)return;
    syncing=true;
    allCharts.forEach(c=>{if(c!==chart)c.timeScale().setVisibleLogicalRange(range);});
    syncing=false;
  });
});

// ── Indicator toggles ──────────────────────────────────────────────────────
const serMap={
  e20:[sE20], e50:[sE50], e200:[sE200], s20:[sS20],
  bb:[sBBU,sBBM,sBBL], vw:[sVWAP],
};
const vis={e20:true,e50:true,e200:false,s20:false,bb:false,vw:D.vwap.length>0};

function tog(k){
  vis[k]=!vis[k];
  serMap[k].forEach(s=>s.applyOptions({visible:vis[k]}));
  document.getElementById('b-'+k).classList.toggle('on',vis[k]);
}

// ── Pane toggle ────────────────────────────────────────────────────────────
const paneVis={vol:true,rsi:true,macd:false};

function togPane(k){
  paneVis[k]=!paneVis[k];
  document.getElementById('pane-'+k).style.display=paneVis[k]?'block':'none';
  document.getElementById('b-'+k).classList.toggle('on',paneVis[k]);
  resize();
}

// ── Timeframe buttons ──────────────────────────────────────────────────────
const TF_SEC={
  '1D':86400,'5D':86400*5,'1M':86400*30,'3M':86400*91,
  '6M':86400*183,'1Y':86400*365,'5Y':86400*365*5,'MAX':null,
};
let activeTF='1D';

function setTF(tf){
  if(activeTF)document.getElementById('tf-'+activeTF).classList.remove('on');
  document.getElementById('tf-'+tf).classList.add('on');
  activeTF=tf;
  const last=D.candles.length?D.candles[D.candles.length-1]:null;
  if(!last)return;
  if(TF_SEC[tf]===null){cMain.timeScale().fitContent();return;}
  const to=last.time+3600;
  const from=to-TF_SEC[tf];
  try{cMain.timeScale().setVisibleRange({from,to});}catch(e){cMain.timeScale().fitContent();}
}

// ── Responsive resize ──────────────────────────────────────────────────────
function resize(){
  const W=document.body.clientWidth;
  let used=0;
  const pH={vol:H_VOL,rsi:H_RSI,macd:H_MACD};
  Object.entries(paneVis).forEach(([k,v])=>{if(v)used+=pH[k];});
  const hm=__AVAIL__-used;
  document.getElementById('cm').style.height=hm+'px';
  cMain.applyOptions({width:W,height:hm});
  cVol.applyOptions({width:W,height:H_VOL});
  cRsi.applyOptions({width:W,height:H_RSI});
  cMacd.applyOptions({width:W,height:H_MACD});
}
window.addEventListener('resize',resize);
resize();

// ── Fullscreen ─────────────────────────────────────────────────────────────
function toggleFS(){
  if(!document.fullscreenElement){
    document.documentElement.requestFullscreen().catch(()=>{});
    document.getElementById('fs-btn').textContent='✕ Exit';
  } else {
    document.exitFullscreen();
    document.getElementById('fs-btn').textContent='⛶ Full';
  }
}
document.addEventListener('fullscreenchange',()=>{
  if(!document.fullscreenElement)document.getElementById('fs-btn').textContent='⛶ Full';
  setTimeout(resize,120);
});

// ── Initial range ──────────────────────────────────────────────────────────
setTF('1D');
</script>
</body>
</html>"""

    html = (html
        .replace("__DATA__",   data_json)
        .replace("__HMAIN__",  str(h_main))
        .replace("__HVOL__",   str(h_vol))
        .replace("__HRSI__",   str(h_rsi))
        .replace("__HMACD__",  str(h_macd))
        .replace("__AVAIL__",  str(avail))
    )
    return html


# ── Public API ───────────────────────────────────────────────────────────────

def render_chart_controls(symbol: str = "") -> str:
    """Interval selector rendered above the chart. Returns selected yfinance interval string."""
    options = ["1m", "5m", "15m", "30m", "1h", "1d"]
    labels  = ["1 min", "5 min", "15 min", "30 min", "1 hour", "Daily"]
    label_map = dict(zip(labels, options))

    c1, c2 = st.columns([2.2, 5])
    with c1:
        sel_label = st.select_slider(
            "Candle interval",
            options=labels,
            value="5 min",
            key=f"adv_interval_{symbol}",
            label_visibility="collapsed",
        )
    with c2:
        interval = label_map[sel_label]
        yf_iv, period = _INTERVAL_MAP[interval]
        data_avail = {
            "1m": "up to 5 days",
            "5m": "up to 60 days",
            "15m": "up to 60 days",
            "30m": "up to 60 days",
            "1h": "up to 2 years",
            "1d": "up to 5 years",
        }
        st.markdown(
            f'<div style="padding:6px 0;color:#8b949e;font-size:0.78rem;">'
            f'Candle: <b style="color:#00d4aa">{sel_label}</b>'
            f'&nbsp;·&nbsp; Data: <b style="color:#e6edf3">{data_avail[interval]}</b>'
            f'&nbsp;·&nbsp; Use timeframe buttons <b style="color:#e6edf3">below</b> the chart to pan history'
            f'</div>',
            unsafe_allow_html=True,
        )
    return interval


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_and_compute(symbol: str, interval: str) -> dict | None:
    yf_iv, period = _INTERVAL_MAP.get(interval, ("5m", "60d"))
    df = get_history(symbol, period=period, interval=yf_iv)
    if df is None or df.empty:
        return None

    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    close = df["Close"]

    bb_u, bb_m, bb_l = _bollinger(close)
    macd_l, macd_s, macd_h = _macd(close)
    is_intraday = interval in ("1m", "5m", "15m", "30m", "1h")
    vwap_data = _line(_vwap(df), df.index) if is_intraday else []

    last_price = float(close.iloc[-1])
    prev_price = float(close.iloc[-2]) if len(close) >= 2 else last_price
    change_pct = round((last_price - prev_price) / prev_price * 100, 2) if prev_price else 0.0

    return {
        "symbol":    symbol.replace(".NS", "").replace(".BO", ""),
        "interval":  interval,
        "lastPrice": round(last_price, 2),
        "changePct": change_pct,
        "candles":   _candles(df),
        "volume":    _volume(df),
        "ema20":     _line(_ema(close, 20),  df.index),
        "ema50":     _line(_ema(close, 50),  df.index),
        "ema200":    _line(_ema(close, 200), df.index),
        "sma20":     _line(_sma(close, 20),  df.index),
        "bbU":       _line(bb_u, df.index),
        "bbM":       _line(bb_m, df.index),
        "bbL":       _line(bb_l, df.index),
        "vwap":      vwap_data,
        "rsi":       _line(_rsi(close), df.index),
        "macd":      _line(macd_l, df.index),
        "signal":    _line(macd_s, df.index),
        "macdHist":  _macd_hist(macd_h, df.index),
    }


def render_advanced_chart(symbol: str, interval: str = "5m", height: int = 620):
    """
    Render a professional TradingView Lightweight Charts component.
    Height is the inner chart height in pixels (the Streamlit component will
    be slightly taller to account for controls).
    """
    with st.spinner(f"Loading {interval} chart for {symbol.replace('.NS','')}…"):
        payload = _fetch_and_compute(symbol, interval)

    if payload is None:
        st.warning(
            f"No chart data for **{symbol}** at **{interval}** interval. "
            "yfinance may not have intraday data for this symbol or the market is closed."
        )
        return

    html = _build_html(payload, height)
    components.html(html, height=height + 10, scrolling=False)
