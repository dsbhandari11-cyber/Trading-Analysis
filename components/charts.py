"""
Plotly chart components with a light fintech trading terminal theme.
"""

import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from typing import Optional, List, Dict
from config import COLORS


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


_LAYOUT_BASE = dict(
    paper_bgcolor="#ffffff",
    plot_bgcolor="#ffffff",
    font=dict(color="#667085", size=11),
    margin=dict(l=8, r=8, t=28, b=8),
    showlegend=False,
)

_GRID = dict(gridcolor="#eef2f6", zerolinecolor="#dce3ee")
_XAXIS = dict(showgrid=False, color="#667085", linecolor="#dce3ee")
_YAXIS = dict(**_GRID, color="#667085", linecolor="#dce3ee")


def mini_sparkline(history: pd.DataFrame, positive: bool = True) -> go.Figure:
    """Tiny sparkline chart for index cards."""
    color = COLORS["positive"] if positive else COLORS["negative"]
    fig = go.Figure()
    if history is not None and not history.empty and "Close" in history.columns:
        y = history["Close"].values
        fig.add_trace(go.Scatter(
            y=y,
            mode="lines",
            line=dict(color=color, width=2),
            fill="tozeroy",
            fillcolor=_hex_to_rgba(color, 0.07),
        ))
    fig.update_layout(
        **{**_LAYOUT_BASE, "margin": dict(l=0, r=0, t=0, b=0)},
        height=60,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    return fig


def index_line_chart(history: pd.DataFrame, title: str, positive: bool = True) -> go.Figure:
    color = COLORS["positive"] if positive else COLORS["negative"]
    fig = go.Figure()
    if history is not None and not history.empty and "Close" in history.columns:
        fig.add_trace(go.Scatter(
            x=history.index,
            y=history["Close"],
            mode="lines",
            line=dict(color=color, width=2),
            fill="tozeroy",
            fillcolor=_hex_to_rgba(color, 0.08),
            name=title,
            hovertemplate="<b>%{x|%d %b}</b><br>₹%{y:,.2f}<extra></extra>",
        ))
    fig.update_layout(
        **_LAYOUT_BASE,
        title=dict(text=title, font=dict(size=12, color="#182230"), x=0),
        height=180,
        xaxis=dict(**_XAXIS, tickformat="%d %b"),
        yaxis=dict(**_YAXIS),
    )
    return fig


def candlestick_chart(df: pd.DataFrame, title: str = "") -> go.Figure:
    fig = go.Figure()
    if df is None or df.empty:
        return fig

    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"],
        increasing_line_color=COLORS["positive"],
        decreasing_line_color=COLORS["negative"],
        name="OHLC",
    ))
    fig.add_trace(go.Bar(
        x=df.index,
        y=df["Volume"],
        marker_color=[COLORS["positive"] if c >= o else COLORS["negative"]
                      for c, o in zip(df["Close"], df["Open"])],
        opacity=0.4,
        yaxis="y2",
        name="Volume",
    ))
    fig.update_layout(
        **_LAYOUT_BASE,
        title=dict(text=title, font=dict(size=13, color="#182230"), x=0),
        height=350,
        xaxis=dict(**_XAXIS, rangeslider=dict(visible=False)),
        yaxis=dict(**_YAXIS, title="Price (₹)"),
        yaxis2=dict(overlaying="y", side="right", showgrid=False, visible=False),
    )
    return fig


def heatmap_chart(data: List[Dict], value_col: str = "pct_change", label_col: str = "symbol") -> go.Figure:
    """Sector / stock heatmap coloured by % change."""
    if not data:
        fig = go.Figure()
        fig.update_layout(**_LAYOUT_BASE, height=200)
        return fig

    df = pd.DataFrame(data)
    df[label_col] = df[label_col].str.replace(".NS", "", regex=False)
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce").fillna(0)

    n = len(df)
    cols = min(8, n)
    rows = (n + cols - 1) // cols

    fig = go.Figure(go.Treemap(
        labels=df[label_col].tolist(),
        values=[abs(v) + 0.1 for v in df[value_col].tolist()],
        parents=[""] * n,
        text=[f"{v:+.2f}%" for v in df[value_col].tolist()],
        textposition="middle center",
        marker=dict(
            colors=df[value_col].tolist(),
            colorscale=[
                [0.0, "#b42318"],
                [0.25, "#f04438"],
                [0.45, "#f2f4f7"],
                [0.55, "#f2f4f7"],
                [0.75, "#12b76a"],
                [1.0, "#067647"],
            ],
            cmid=0,
            showscale=False,
        ),
        customdata=df[[value_col]].values,
        hovertemplate="<b>%{label}</b><br>Change: %{text}<extra></extra>",
    ))
    fig.update_layout(**{**_LAYOUT_BASE, "margin": dict(l=4, r=4, t=4, b=4)}, height=280)
    return fig


def rsi_gauge(rsi: float) -> go.Figure:
    """Small gauge chart for RSI."""
    color = COLORS["negative"] if rsi >= 70 else (COLORS["warning"] if rsi <= 30 else COLORS["positive"])
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=rsi,
        number=dict(font=dict(color=color, size=20)),
        gauge=dict(
            axis=dict(range=[0, 100], tickcolor="#dce3ee", tickfont=dict(color="#667085", size=9)),
            bar=dict(color=color, thickness=0.3),
            bgcolor="#f8fafc",
            bordercolor="#dce3ee",
            steps=[
                dict(range=[0, 30], color="rgba(217,45,32,0.10)"),
                dict(range=[30, 70], color="#f2f4f7"),
                dict(range=[70, 100], color="rgba(15,159,110,0.10)"),
            ],
            threshold=dict(line=dict(color=color, width=2), thickness=0.75, value=rsi),
        ),
    ))
    fig.update_layout(**{**_LAYOUT_BASE, "margin": dict(l=8, r=8, t=16, b=8)}, height=120)
    return fig


def momentum_bar_chart(data: List[Dict]) -> go.Figure:
    """Horizontal bar chart ranked by momentum score."""
    if not data:
        fig = go.Figure()
        fig.update_layout(**_LAYOUT_BASE, height=200)
        return fig
    df = pd.DataFrame(data).sort_values("momentum_score", ascending=True).tail(15)
    df["symbol_clean"] = df["symbol"].str.replace(".NS", "", regex=False)
    colors_list = [COLORS["positive"] if s >= 50 else COLORS["negative"] for s in df["momentum_score"]]

    fig = go.Figure(go.Bar(
        x=df["momentum_score"],
        y=df["symbol_clean"],
        orientation="h",
        marker_color=colors_list,
        text=[f"{s:.1f}" for s in df["momentum_score"]],
        textposition="auto",
        hovertemplate="<b>%{y}</b><br>Score: %{x:.1f}<extra></extra>",
    ))
    fig.update_layout(
        **_LAYOUT_BASE,
        height=max(250, len(df) * 22),
        xaxis=dict(**_XAXIS, range=[0, 100], title="Momentum Score"),
        yaxis=dict(**_YAXIS),
        title=dict(text="Momentum Rankings", font=dict(size=12, color="#182230"), x=0),
    )
    return fig
