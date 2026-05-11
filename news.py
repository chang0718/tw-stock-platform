# news.py
# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime
from typing import List
import re
import xml.etree.ElementTree as ET

import pandas as pd
import requests


REQUEST_TIMEOUT = 12

DEFAULT_RSS_FEEDS = [
    # 建議放官方 RSS、公司公告 RSS、你確認可使用的新聞 RSS。
    # 不建議抓新聞全文。
    # 可自行新增：
    # "https://news.google.com/rss/search?q=台積電+台股&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
]


POSITIVE_KEYWORDS = [
    "成長", "創高", "大增", "轉盈", "獲利", "擴產", "接單", "調升", "升級",
    "新高", "強勁", "旺季", "利多", "上修", "突破", "合作", "量產",
]

NEGATIVE_KEYWORDS = [
    "下滑", "衰退", "虧損", "減產", "砍單", "下修", "利空", "裁員", "罰款",
    "調降", "延後", "庫存", "疲弱", "警示", "違約", "停工", "訴訟",
]

EVENT_KEYWORDS = {
    "財報": ["財報", "EPS", "獲利", "營收", "毛利率", "法說"],
    "訂單": ["接單", "訂單", "出貨", "客戶", "供應鏈"],
    "產能": ["擴產", "量產", "產能", "新廠", "良率"],
    "併購合作": ["併購", "投資", "合作", "策略聯盟", "入股"],
    "法規風險": ["裁罰", "訴訟", "調查", "違規", "制裁"],
    "股利": ["股利", "配息", "除息", "現金股利"],
    "技術產品": ["AI", "CPO", "矽光子", "CoWoS", "HBM", "800G", "1.6T"],
}


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", str(text))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def classify_sentiment(title: str) -> str:
    title = clean_text(title)

    pos = sum(1 for kw in POSITIVE_KEYWORDS if kw in title)
    neg = sum(1 for kw in NEGATIVE_KEYWORDS if kw in title)

    if pos > neg:
        return "正向"
    if neg > pos:
        return "負向"
    return "中性"


def classify_events(title: str) -> str:
    title = clean_text(title)
    matched = []

    for event, keywords in EVENT_KEYWORDS.items():
        if any(kw in title for kw in keywords):
            matched.append(event)

    return "、".join(matched) if matched else "一般新聞"


def title_based_summary(title: str, company_name: str = "") -> str:
    """
    安全摘要：
    不抓新聞全文，不複製媒體摘要。
    只根據標題生成事件描述。
    """
    sentiment = classify_sentiment(title)
    events = classify_events(title)
    prefix = f"{company_name}相關消息" if company_name else "相關消息"
    return f"{prefix}，事件類型：{events}，標題情緒：{sentiment}。"


def parse_rss_feed(url: str, keyword: str = "") -> pd.DataFrame:
    try:
        res = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        res.raise_for_status()
        root = ET.fromstring(res.content)
    except Exception:
        return pd.DataFrame()

    rows = []

    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title"))
        link = clean_text(item.findtext("link"))
        pub_date = clean_text(item.findtext("pubDate"))

        source = ""
        source_node = item.find("{http://www.google.com/schemas/sitemap-news/0.9}publication")
        if source_node is not None:
            source = clean_text(source_node.findtext("{http://www.google.com/schemas/sitemap-news/0.9}name"))

        if not source:
            source = clean_text(item.findtext("source"))

        if keyword and keyword not in title:
            # 保守過濾，只保留標題含關鍵字的項目
            continue

        rows.append({
            "新聞日期": pub_date,
            "新聞來源": source or "RSS",
            "新聞標題": title,
            "新聞連結": link,
            "事件分類": classify_events(title),
            "新聞情緒": classify_sentiment(title),
            "安全摘要": title_based_summary(title, keyword),
        })

    return pd.DataFrame(rows)


def build_google_news_rss_url(keyword: str) -> str:
    """
    Google News RSS 不抓全文，只讀 RSS item 的 title/source/link/date。
    若你擔心 Google News 條款，可不用此函式，改用你有授權的 RSS。
    """
    from urllib.parse import quote_plus
    q = quote_plus(keyword)
    return f"https://news.google.com/rss/search?q={q}+台股&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"


def fetch_news_for_company(
    ticker: str,
    company_name: str,
    use_google_news: bool = False,
    custom_rss_feeds: List[str] | None = None,
) -> pd.DataFrame:
    feeds = list(custom_rss_feeds or DEFAULT_RSS_FEEDS)

    if use_google_news:
        feeds.append(build_google_news_rss_url(company_name))

    frames = []
    for feed in feeds:
        df = parse_rss_feed(feed, keyword=company_name)
        if not df.empty:
            df["股票代號"] = ticker
            df["公司名稱"] = company_name
            df["RSS來源"] = feed
            frames.append(df)

    if not frames:
        return pd.DataFrame(columns=[
            "股票代號", "公司名稱", "新聞日期", "新聞來源", "新聞標題",
            "新聞連結", "事件分類", "新聞情緒", "安全摘要", "RSS來源"
        ])

    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset=["新聞標題", "新聞連結"])
    return out.head(20)


def news_score(news_df: pd.DataFrame) -> float:
    if news_df.empty:
        return float("nan")

    score_map = {"正向": 1, "中性": 0, "負向": -1}
    raw = news_df["新聞情緒"].map(score_map).fillna(0).sum()

    # 映射到 0~100
    # 正負新聞過多都限制在合理區間
    raw = max(-5, min(5, raw))
    return round((raw + 5) / 10 * 100, 1)