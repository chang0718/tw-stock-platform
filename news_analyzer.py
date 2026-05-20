"""
新聞 RSS 爬蟲 + 關鍵字情緒分析
來源: Yahoo 財經 / 鉅亨網 / MoneyDJ
零費用，1 小時本機快取
需安裝: pip install feedparser
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

try:
    import feedparser
    _HAS_FEEDPARSER = True
except ImportError:
    _HAS_FEEDPARSER = False

_CACHE_FILE = Path("tw_quant_data/news_cache.json")
_TTL = 3600  # 1小時

_POS_KW = [
    "創新高", "成長", "獲利", "上漲", "看好", "營收增加",
    "突破", "強勢", "推薦", "買進", "升級", "擴廠", "接單",
    "需求強", "表現亮眼", "超預期", "配息", "新高", "轉機",
    "毛利率提升", "法說會", "獲利成長",
]
_NEG_KW = [
    "下跌", "虧損", "衰退", "不利", "示警", "減少", "縮水",
    "下修", "賣出", "裁員", "下滑", "轉弱", "疲弱",
    "獲利下降", "不如預期", "警示", "停牌", "看淡",
    "毛利率下滑", "營收衰退", "展望保守",
]

_GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
_MONEYDJ_RSS     = "https://www.moneydj.com/RSS/SubClass_Article.aspx?svc=NW&subclass=MB01"
_YOUTUBE_RSS     = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"

# YouTube 財經頻道（免費公開 RSS，無需 API key）
_YOUTUBE_CHANNELS = {
    "股癌":     "UCe17MYfNYBTvqXV48oXA-0w",
    "CMoney":   "UCG_K9XwBOxkLBMU6VBpzUAA",
    "雪球股神": "UCiPiS4SFDJ4xVDQb15LRCBA",
    "財經M平方": "UC7ywxSuWlA5KqBFMhKGCNlQ",
}

# 總體經濟 / 地緣政治 / 財經媒體關鍵字
_MACRO_QUERIES = [
    ("川普 關稅 貿易",         "貿易/關稅"),
    ("聯準會 Fed 利率",        "Fed/利率"),
    ("中美 貿易戰",            "中美關係"),
    ("台海 地緣政治",          "地緣風險"),
    ("NVIDIA AMD 財報",        "半導體大廠"),
    ("AI 人工智慧 投資",       "AI趨勢"),
    ("通膨 CPI 景氣",          "總經指標"),
    ("台股 外資 投信 買超",    "三大法人動向"),
    ("台灣 法說會 財報",       "法說會"),
    ("股癌 Gooaye 台股",       "財經媒體-股癌"),
    ("CMoney 台股 本週",       "財經媒體-CMoney"),
    ("財經M平方 景氣 指標",    "財經媒體-M平方"),
    ("美股 道瓊 納指 本週",    "美股指數"),
]

# 產業題材特定關鍵字（建廠/報價/技術世代）
_INDUSTRY_QUERIES = [
    ("台積電 CoWoS 先進封裝 擴產",     "半導體封裝"),
    ("NAND DRAM 記憶體 報價",          "記憶體報價"),
    ("面板 報價 供需",                  "面板報價"),
    ("太陽能 儲能 補貼 政策",          "綠能政策"),
    ("電動車 台灣 供應商 訂單",        "電動車供應"),
    ("AI 伺服器 訂單 台廠",            "AI伺服器訂單"),
    ("CoWoS 液冷 散熱 建廠",          "產能建置"),
    ("光通訊 800G 1.6T 需求",         "光通訊世代"),
    ("晶圓代工 報價 漲價",             "晶圓報價"),
    ("PCB 銅箔基板 報價",              "PCB報價"),
    ("被動元件 MLCC 報價",             "被動元件報價"),
    ("台積電 美國 日本 建廠",          "台積電海外建廠"),
    ("機器人 自動化 AI 台廠",          "機器人自動化"),
]


class NewsAnalyzer:

    def __init__(self):
        self._cache = self._load()

    # ── 快取 ──────────────────────────────────────────────────────

    def _load(self) -> dict:
        try:
            if _CACHE_FILE.exists():
                return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _flush(self):
        try:
            _CACHE_FILE.write_text(
                json.dumps(self._cache, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _hit(self, key: str):
        e = self._cache.get(key)
        if e and (time.time() - e.get("ts", 0)) < _TTL:
            return e["data"]
        return None

    def _put(self, key: str, data):
        self._cache[key] = {"ts": time.time(), "data": data}
        self._flush()

    # ── 爬蟲 ──────────────────────────────────────────────────────

    def fetch_news(self, query: str, days: int = 7) -> List[Dict]:
        """
        爬取新聞，1 小時快取。
        來源優先順序：
        1. Google News RSS（繁中搜尋，最穩定）
        2. MoneyDJ RSS（台股財經，過濾 query 關鍵字）
        """
        if not _HAS_FEEDPARSER:
            return []

        key = f"news:{query}:{days}"
        cached = self._hit(key)
        if cached is not None:
            return cached

        import urllib.parse
        cutoff  = datetime.now() - timedelta(days=days)
        results = []

        def _parse_entry(entry, src):
            title   = entry.get("title", "")
            summary = entry.get("summary", "")
            try:
                pub = (
                    datetime(*entry.published_parsed[:6])
                    if hasattr(entry, "published_parsed") and entry.published_parsed
                    else datetime.now()
                )
            except Exception:
                pub = datetime.now()
            if pub < cutoff:
                return None
            return {
                "title":     title,
                "link":      entry.get("link", ""),
                "published": pub.strftime("%Y-%m-%d %H:%M"),
                "source":    src,
                "summary":   summary[:200],
            }

        # 1. Google News RSS（query 已內嵌於 URL，不需再過濾）
        try:
            gurl = _GOOGLE_NEWS_RSS.format(
                query=urllib.parse.quote(f"{query} 股票")
            )
            feed = feedparser.parse(gurl)
            for entry in feed.entries[:30]:
                item = _parse_entry(entry, "google_news")
                if item:
                    results.append(item)
        except Exception:
            pass

        # 2. MoneyDJ RSS（財經通用，關鍵字過濾）
        if len(results) < 5:
            try:
                feed = feedparser.parse(_MONEYDJ_RSS)
                for entry in feed.entries:
                    title   = entry.get("title", "")
                    summary = entry.get("summary", "")
                    if query and query not in title and query not in summary:
                        continue
                    item = _parse_entry(entry, "moneydj")
                    if item:
                        results.append(item)
            except Exception:
                pass

        results.sort(key=lambda x: x["published"], reverse=True)
        self._put(key, results[:20])
        return results[:20]

    # ── 情緒分析 ──────────────────────────────────────────────────

    def analyze_sentiment(self, news_list: List[Dict]) -> Dict:
        """關鍵字加權情緒分析"""
        pos = neg = neu = 0
        pk: List[str] = []
        nk: List[str] = []

        for item in news_list:
            text = item["title"] + " " + item.get("summary", "")
            p = sum(1 for w in _POS_KW if w in text)
            n = sum(1 for w in _NEG_KW if w in text)
            if p > n:
                pos += 1
                pk += [w for w in _POS_KW if w in text]
            elif n > p:
                neg += 1
                nk += [w for w in _NEG_KW if w in text]
            else:
                neu += 1

        total = max(len(news_list), 1)
        score = round((pos - neg) / total, 3)

        if score > 0.2:
            label = "正面"
            label_color = "🟢"
        elif score < -0.2:
            label = "負面"
            label_color = "🔴"
        else:
            label = "中性"
            label_color = "🟡"

        return {
            "label": label,
            "label_color": label_color,
            "score": score,
            "positive": pos,
            "negative": neg,
            "neutral": neu,
            "total": total,
            "pos_keywords": list(set(pk))[:5],
            "neg_keywords": list(set(nk))[:5],
            "data_source": "🔧 關鍵字分析（免費）",
        }

    def fetch_youtube_news(self) -> List[Dict]:
        """
        抓取 YouTube 財經頻道最新影片標題（公開 RSS，1hr 快取）。
        不需 API key，完全免費。
        """
        if not _HAS_FEEDPARSER:
            return []

        key = "youtube_finance"
        cached = self._hit(key)
        if cached is not None:
            return cached

        results = []
        for ch_name, cid in _YOUTUBE_CHANNELS.items():
            try:
                feed = feedparser.parse(_YOUTUBE_RSS.format(cid=cid))
                for entry in feed.entries[:5]:
                    title = entry.get("title", "")
                    if not title:
                        continue
                    try:
                        pub = (
                            datetime(*entry.published_parsed[:6])
                            if hasattr(entry, "published_parsed") and entry.published_parsed
                            else datetime.now()
                        )
                    except Exception:
                        pub = datetime.now()
                    results.append({
                        "title":     title,
                        "link":      entry.get("link", ""),
                        "published": pub.strftime("%Y-%m-%d %H:%M"),
                        "source":    f"youtube_{ch_name}",
                        "summary":   "",
                    })
            except Exception:
                continue

        self._put(key, results[:20])
        return results[:20]

    def fetch_ptt_stock(self, ticker: str, name: str) -> List[Dict]:
        """
        爬取 PTT Stock 版搜尋結果（不需登入），回傳文章標題清單。
        使用關鍵字情緒分析（與 analyze_sentiment 一致）。
        """
        import re
        try:
            import requests as _req
        except ImportError:
            return []

        key = f"ptt_{ticker}"
        cached = self._hit(key)
        if cached is not None:
            return cached

        results = []
        # PTT 搜尋：股票代號為主，公司名前兩字為輔
        short_name = re.sub(r"[\-＊*\s]", "", name)[:3]
        for query in [ticker, short_name]:
            try:
                url = f"https://www.ptt.cc/bbs/Stock/search?q={query}&page=1"
                r = _req.get(
                    url,
                    headers={
                        "Cookie": "over18=1",
                        "User-Agent": "Mozilla/5.0 (compatible; tw-stock-bot/1.0)",
                    },
                    timeout=8,
                    verify=False,
                )
                if r.status_code != 200:
                    continue
                # 從 HTML 中擷取文章標題（不用 BeautifulSoup 降低依賴）
                titles = re.findall(
                    r'class="title"[^>]*>\s*<a[^>]*>([^<]+)</a>', r.text
                )
                for t in titles[:15]:
                    t = t.strip()
                    if t and ticker in t or short_name in t or any(
                        kw in t for kw in [ticker, name[:2]]
                    ):
                        results.append({
                            "title":     t,
                            "link":      url,
                            "published": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "source":    "ptt_stock",
                            "summary":   "",
                        })
            except Exception:
                continue

        self._put(key, results[:10])
        return results[:10]

    def get_stock_news_sentiment(self, ticker: str, name: str) -> Dict:
        """個股新聞情緒（yfinance 優先 → RSS 備援 → PTT Stock 板）"""
        news = []

        # 1. 嘗試 yfinance 新聞
        try:
            import yfinance as yf
            yf_ticker = yf.Ticker(f"{ticker}.TW")
            yf_news = yf_ticker.news or []
            for item in yf_news[:15]:
                title   = item.get("title", "")
                link    = item.get("link", "") or item.get("url", "")
                pub_ts  = item.get("providerPublishTime", 0)
                pub_str = (
                    datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d %H:%M")
                    if pub_ts else datetime.now().strftime("%Y-%m-%d %H:%M")
                )
                if title:
                    news.append({
                        "title":     title,
                        "link":      link,
                        "published": pub_str,
                        "source":    "yfinance",
                        "summary":   item.get("summary", "")[:200],
                    })
        except Exception:
            pass

        # 2. RSS 備援（yfinance 沒有足夠新聞時）
        if len(news) < 3:
            rss_news = self.fetch_news(name) if name else []
            if not rss_news:
                rss_news = self.fetch_news(ticker)
            news.extend(rss_news)

        # 3. PTT Stock 板補充（情緒信號）
        try:
            ptt_news = self.fetch_ptt_stock(ticker, name)
            news.extend(ptt_news)
        except Exception:
            pass

        # 4. YouTube 財經頻道（過濾有提及個股的影片標題）
        try:
            yt_news = self.fetch_youtube_news()
            keywords = [ticker, name[:2] if name else ""]
            for item in yt_news:
                if any(kw and kw in item["title"] for kw in keywords):
                    news.append(item)
        except Exception:
            pass

        # 去重（依標題前30字元）
        seen = set()
        deduped = []
        for n in news:
            key = n["title"][:30]
            if key not in seen:
                seen.add(key)
                deduped.append(n)

        return {
            "sentiment":      self.analyze_sentiment(deduped[:20]),
            "news":           deduped[:15],
            "has_feedparser": _HAS_FEEDPARSER,
        }

    def fetch_macro_events(self) -> List[Dict]:
        """
        抓取總體經濟 / 地緣政治重大事件（RSS，1 小時快取）
        回傳: [{category, title, link, published, source}]
        """
        if not _HAS_FEEDPARSER:
            return []

        key = "macro_events"
        cached = self._hit(key)
        if cached is not None:
            return cached

        import urllib.parse
        cutoff  = datetime.now() - timedelta(days=14)
        results = []

        for query, category in _MACRO_QUERIES:
            try:
                gurl = _GOOGLE_NEWS_RSS.format(query=urllib.parse.quote(query))
                feed = feedparser.parse(gurl)
                for entry in feed.entries[:5]:
                    title = entry.get("title", "")
                    try:
                        pub = (
                            datetime(*entry.published_parsed[:6])
                            if hasattr(entry, "published_parsed") and entry.published_parsed
                            else datetime.now()
                        )
                    except Exception:
                        pub = datetime.now()
                    if pub < cutoff:
                        continue
                    results.append({
                        "category":  category,
                        "title":     title,
                        "link":      entry.get("link", ""),
                        "published": pub.strftime("%Y-%m-%d %H:%M"),
                        "source":    "google_news",
                    })
            except Exception:
                continue

        results.sort(key=lambda x: x["published"], reverse=True)
        out = results[:30]
        self._put(key, out)
        return out

    def fetch_industry_events(self, supply_chain: str = "") -> List[Dict]:
        """
        抓取產業題材新聞（建廠/報價/技術世代等）
        supply_chain: 可指定篩選特定供應鏈關鍵字，留空=全部
        回傳: [{category, title, link, published, source}]
        """
        if not _HAS_FEEDPARSER:
            return []

        key = f"industry_events:{supply_chain}"
        cached = self._hit(key)
        if cached is not None:
            return cached

        import urllib.parse
        cutoff  = datetime.now() - timedelta(days=14)
        results = []

        queries = _INDUSTRY_QUERIES
        if supply_chain:
            # 只抓與 supply_chain 關鍵字相關的
            queries = [(q, cat) for q, cat in _INDUSTRY_QUERIES
                       if any(kw in supply_chain for kw in q.split()[:3])
                       or any(kw in q for kw in supply_chain.split()[:2])]
            if not queries:
                queries = _INDUSTRY_QUERIES[:5]  # fallback to first 5

        for query, category in queries:
            try:
                gurl = _GOOGLE_NEWS_RSS.format(query=urllib.parse.quote(query))
                feed = feedparser.parse(gurl)
                for entry in feed.entries[:4]:
                    title = entry.get("title", "")
                    try:
                        pub = (
                            datetime(*entry.published_parsed[:6])
                            if hasattr(entry, "published_parsed") and entry.published_parsed
                            else datetime.now()
                        )
                    except Exception:
                        pub = datetime.now()
                    if pub < cutoff:
                        continue
                    results.append({
                        "category":  category,
                        "title":     title,
                        "link":      entry.get("link", ""),
                        "published": pub.strftime("%Y-%m-%d %H:%M"),
                        "source":    "google_news",
                    })
            except Exception:
                continue

        results.sort(key=lambda x: x["published"], reverse=True)
        out = results[:25]
        self._put(key, out)
        return out
