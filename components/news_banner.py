"""
Diplomatic / geopolitical news scrolling banner.
Filters RSS headlines for political / trade keywords.
"""

import streamlit as st
from data.news import diplomatic_ticker_text, ticker_headline_text


def render_news_banner():
    text = diplomatic_ticker_text()
    if not text:
        text = ticker_headline_text(8)

    doubled = text + "  •  " + text

    html = f"""
    <div class="news-banner-outer">
        <span class="news-banner-label">LIVE NEWS</span>
        <span style="display:inline-block;overflow:hidden;vertical-align:middle;max-width:calc(100% - 90px);">
            <span class="news-banner-track">
                <span class="news-banner-text">{doubled}</span>
            </span>
        </span>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)
