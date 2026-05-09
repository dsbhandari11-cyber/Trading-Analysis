from datetime import datetime
import pytz
from config import COLORS


IST = pytz.timezone("Asia/Kolkata")


def fmt_price(value: float) -> str:
    if value is None or value != value:
        return "N/A"
    return f"₹{value:,.2f}"


def fmt_change(value: float) -> str:
    if value is None or value != value:
        return "N/A"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def fmt_large(value: float) -> str:
    if value is None or value != value:
        return "N/A"
    if abs(value) >= 1e7:
        return f"{value/1e7:.2f}Cr"
    if abs(value) >= 1e5:
        return f"{value/1e5:.2f}L"
    return f"{value:,.0f}"


def color_for_change(value: float) -> str:
    if value is None or value != value:
        return COLORS["neutral"]
    return COLORS["positive"] if value >= 0 else COLORS["negative"]


def rsi_color(rsi: float) -> str:
    if rsi is None or rsi != rsi:
        return COLORS["neutral"]
    if rsi >= 70:
        return COLORS["negative"]
    if rsi <= 30:
        return COLORS["warning"]
    if rsi >= 50:
        return COLORS["positive"]
    return COLORS["neutral"]


def signal_emoji(value: float, bullish_threshold: float, bearish_threshold: float) -> str:
    if value >= bullish_threshold:
        return "🟢"
    if value <= bearish_threshold:
        return "🔴"
    return "🟡"


def ist_now() -> str:
    return datetime.now(IST).strftime("%d %b %Y %H:%M:%S IST")


def momentum_score_color(score: float) -> str:
    if score >= 70:
        return COLORS["positive"]
    if score >= 40:
        return COLORS["warning"]
    return COLORS["negative"]


def clean_symbol(symbol: str) -> str:
    return symbol.replace(".NS", "").replace(".BO", "")


def styled_metric(label: str, value: str, delta: float = None) -> str:
    delta_html = ""
    if delta is not None:
        clr = color_for_change(delta)
        sign = "▲" if delta >= 0 else "▼"
        delta_html = f'<span style="color:{clr};font-size:0.85rem;">{sign} {abs(delta):.2f}%</span>'

    return f"""
    <div style="background:{COLORS['bg_card']};border:1px solid {COLORS['border']};
                border-radius:8px;padding:12px 16px;margin:4px 0;">
        <div style="color:{COLORS['text_muted']};font-size:0.78rem;margin-bottom:4px;">{label}</div>
        <div style="color:{COLORS['text']};font-size:1.3rem;font-weight:700;">{value}</div>
        {delta_html}
    </div>
    """
