"""
美股市場資料 + 台股供應鏈映射 + 產業上中下游鏈
資料來源: yfinance（免費，15分鐘延遲）
pip install yfinance
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

_CACHE_FILE = Path("tw_quant_data/us_market_cache.json")
_TTL = 3600  # 1小時

try:
    import yfinance as yf
    _HAS_YF = True
except ImportError:
    _HAS_YF = False

# ── 美股指數 ──────────────────────────────────────────────────────

US_INDICES = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ",
    "^SOX":  "費城半導體",
    "^DJI":  "道瓊",
    "^VIX":  "VIX 恐慌指數",
}

# ── 關鍵美股 ──────────────────────────────────────────────────────

US_KEY_STOCKS = {
    "NVDA": "NVIDIA（AI GPU）",
    "AMD":  "AMD（CPU/GPU）",
    "INTC": "Intel（CPU/晶圓廠）",
    "MU":   "美光（DRAM/HBM）",
    "AMAT": "應材（半導體設備）",
    "ASML": "ASML（EUV設備）",
    "QCOM": "高通（手機SoC）",
    "AVGO": "博通（網通/AI ASIC）",
    "AAPL": "蘋果（消費電子）",
    "MSFT": "微軟（Azure/AI）",
    "GOOG": "Google（GCP/TPU）",
    "AMZN": "亞馬遜（AWS）",
    "META": "Meta（AI基礎建設）",
    "TSLA": "特斯拉（電動車）",
    "TSM":  "台積電 ADR",
}

# ── 美股 → 台股供應鏈映射 ─────────────────────────────────────────
# role 說明供應鏈位置；同一 us_ticker 可對應多家台股

US_TW_SUPPLY_CHAIN: Dict[str, Dict] = {
    "NVDA": {
        "name": "NVIDIA", "theme": "AI GPU / HPC 伺服器",
        "tw_stocks": [
            {"ticker": "6669", "name": "緯穎",   "role": "AI伺服器純ODM"},
            {"ticker": "2382", "name": "廣達",   "role": "AI伺服器ODM"},
            {"ticker": "2356", "name": "英業達", "role": "AI伺服器ODM"},
            {"ticker": "3231", "name": "緯創",   "role": "AI伺服器ODM"},
            {"ticker": "3017", "name": "奇鋐",   "role": "散熱模組"},
            {"ticker": "3324", "name": "雙鴻",   "role": "散熱模組"},
            {"ticker": "2421", "name": "建準",   "role": "風扇/散熱"},
            {"ticker": "2308", "name": "台達電", "role": "電源/散熱解決方案"},
            {"ticker": "2301", "name": "光寶科", "role": "電源供應器"},
            {"ticker": "3533", "name": "嘉澤",   "role": "高速連接器"},
            {"ticker": "6093", "name": "正淩",   "role": "高速背板連接器"},
            {"ticker": "6515", "name": "穎崴",   "role": "連接器"},
        ],
    },
    "AMD": {
        "name": "AMD", "theme": "CPU/GPU / AI 加速器",
        "tw_stocks": [
            {"ticker": "2330", "name": "台積電", "role": "代工（EPYC/Instinct）"},
            {"ticker": "6669", "name": "緯穎",   "role": "AI伺服器ODM"},
            {"ticker": "2382", "name": "廣達",   "role": "伺服器ODM"},
            {"ticker": "3017", "name": "奇鋐",   "role": "散熱"},
            {"ticker": "3711", "name": "日月光",  "role": "先進封裝"},
        ],
    },
    "MU": {
        "name": "美光", "theme": "DRAM / NAND / HBM",
        "tw_stocks": [
            {"ticker": "2408", "name": "南亞科", "role": "DRAM設計製造"},
            {"ticker": "4958", "name": "華邦電", "role": "DRAM / NOR Flash"},
            {"ticker": "2337", "name": "旺宏",   "role": "NOR Flash"},
            {"ticker": "3483", "name": "力旺",   "role": "eNVM IP授權"},
        ],
    },
    "AMAT": {
        "name": "應用材料", "theme": "半導體設備（沉積/蝕刻）",
        "tw_stocks": [
            {"ticker": "3131", "name": "弘塑",   "role": "清洗設備"},
            {"ticker": "3583", "name": "辛耘",   "role": "濕製程設備"},
            {"ticker": "6196", "name": "帆宣",   "role": "設備系統整合"},
            {"ticker": "5347", "name": "世界先進", "role": "晶圓廠設備耗材"},
        ],
    },
    "ASML": {
        "name": "ASML", "theme": "EUV / DUV 微影設備",
        "tw_stocks": [
            {"ticker": "2330", "name": "台積電", "role": "EUV最大客戶"},
            {"ticker": "2303", "name": "聯電",   "role": "DUV客戶"},
            {"ticker": "6488", "name": "環球晶", "role": "矽晶圓供應"},
        ],
    },
    "AAPL": {
        "name": "蘋果", "theme": "iPhone / Mac 供應鏈",
        "tw_stocks": [
            {"ticker": "2317", "name": "鴻海",   "role": "iPhone最大代工"},
            {"ticker": "2474", "name": "可成",   "role": "金屬機殼"},
            {"ticker": "3008", "name": "大立光", "role": "鏡頭模組"},
            {"ticker": "3406", "name": "玉晶光", "role": "玻璃鏡片"},
            {"ticker": "6269", "name": "台郡",   "role": "FPC軟板"},
            {"ticker": "3533", "name": "嘉澤",   "role": "連接器"},
            {"ticker": "2354", "name": "鴻準",   "role": "機殼/散熱"},
            {"ticker": "2330", "name": "台積電", "role": "A系列晶片代工"},
        ],
    },
    "MSFT": {
        "name": "微軟", "theme": "Azure 雲端 / AI Copilot",
        "tw_stocks": [
            {"ticker": "6669", "name": "緯穎",   "role": "Azure伺服器ODM"},
            {"ticker": "2382", "name": "廣達",   "role": "雲端伺服器"},
            {"ticker": "2308", "name": "台達電", "role": "UPS/電源"},
            {"ticker": "2412", "name": "中華電", "role": "Azure台灣合作夥伴"},
        ],
    },
    "GOOG": {
        "name": "Google", "theme": "GCP 雲端 / TPU / AI",
        "tw_stocks": [
            {"ticker": "2356", "name": "英業達", "role": "Google伺服器ODM"},
            {"ticker": "2382", "name": "廣達",   "role": "雲端伺服器"},
            {"ticker": "2330", "name": "台積電", "role": "TPU晶片代工"},
            {"ticker": "3081", "name": "聯亞",   "role": "光收發模組（網路骨幹）"},
        ],
    },
    "AMZN": {
        "name": "亞馬遜", "theme": "AWS 雲端 / Trainium",
        "tw_stocks": [
            {"ticker": "2356", "name": "英業達", "role": "AWS伺服器"},
            {"ticker": "3231", "name": "緯創",   "role": "AWS伺服器"},
            {"ticker": "4979", "name": "華星光", "role": "光收發模組"},
        ],
    },
    "META": {
        "name": "Meta", "theme": "AI 基礎建設 / 資料中心",
        "tw_stocks": [
            {"ticker": "6669", "name": "緯穎",   "role": "Meta AI伺服器"},
            {"ticker": "3017", "name": "奇鋐",   "role": "散熱"},
            {"ticker": "3081", "name": "聯亞",   "role": "光收發（資料中心互聯）"},
        ],
    },
    "QCOM": {
        "name": "高通", "theme": "手機 SoC / IoT / 車用",
        "tw_stocks": [
            {"ticker": "2330", "name": "台積電", "role": "Snapdragon代工"},
            {"ticker": "2454", "name": "聯發科", "role": "競爭對手（市場同向）"},
            {"ticker": "3034", "name": "聯詠",   "role": "顯示驅動IC（手機生態）"},
        ],
    },
    "AVGO": {
        "name": "博通", "theme": "網通晶片 / AI ASIC / 光纖",
        "tw_stocks": [
            {"ticker": "2345", "name": "智邦",   "role": "網通交換器"},
            {"ticker": "3081", "name": "聯亞",   "role": "光收發模組"},
            {"ticker": "4979", "name": "華星光", "role": "光收發模組"},
            {"ticker": "5388", "name": "中磊",   "role": "CPE/路由器"},
        ],
    },
    "TSLA": {
        "name": "特斯拉", "theme": "電動車 / 儲能",
        "tw_stocks": [
            {"ticker": "2308", "name": "台達電", "role": "充電模組/車用電源"},
            {"ticker": "6282", "name": "康舒",   "role": "車用電源"},
            {"ticker": "1536", "name": "和大",   "role": "電動車傳動零件"},
            {"ticker": "2355", "name": "敬鵬",   "role": "車用高頻PCB"},
            {"ticker": "1533", "name": "車王電", "role": "車用電子"},
        ],
    },
    "INTC": {
        "name": "Intel", "theme": "CPU / 晶圓代工（IFS）",
        "tw_stocks": [
            {"ticker": "2303", "name": "聯電",   "role": "成熟製程競爭/合作"},
            {"ticker": "3711", "name": "日月光",  "role": "封裝"},
            {"ticker": "6488", "name": "環球晶", "role": "矽晶圓供應"},
        ],
    },
    "TSM": {
        "name": "台積電 ADR", "theme": "晶圓代工",
        "tw_stocks": [
            {"ticker": "2330", "name": "台積電", "role": "本體"},
            {"ticker": "3711", "name": "日月光",  "role": "封測"},
            {"ticker": "2449", "name": "京元電", "role": "晶圓測試"},
            {"ticker": "6488", "name": "環球晶", "role": "矽晶圓"},
        ],
    },
}

# ── 台灣產業完整上中下游鏈 ────────────────────────────────────────

TW_INDUSTRY_CHAIN: Dict[str, Dict] = {
    "半導體": {
        "上游_材料與設備": [
            {"ticker": "6488", "name": "環球晶",  "desc": "矽晶圓（全球第3大）"},
            {"ticker": "4543", "name": "萬潤",   "desc": "半導體測試耗材"},
            {"ticker": "3131", "name": "弘塑",   "desc": "清洗/去光阻設備"},
            {"ticker": "3583", "name": "辛耘",   "desc": "濕製程設備"},
            {"ticker": "6196", "name": "帆宣",   "desc": "廠務設備系統整合"},
        ],
        "中游_晶圓代工": [
            {"ticker": "2330", "name": "台積電",  "desc": "晶圓代工全球龍頭（N2/N3）"},
            {"ticker": "2303", "name": "聯電",   "desc": "成熟製程代工"},
            {"ticker": "5347", "name": "世界先進", "desc": "功率/模擬IC代工"},
        ],
        "中游_記憶體": [
            {"ticker": "2408", "name": "南亞科",  "desc": "DRAM設計製造"},
            {"ticker": "4958", "name": "華邦電",  "desc": "DRAM / NOR Flash"},
            {"ticker": "2337", "name": "旺宏",   "desc": "NOR Flash"},
        ],
        "IC設計": [
            {"ticker": "2454", "name": "聯發科",  "desc": "手機/AIoT SoC（天璣）"},
            {"ticker": "3034", "name": "聯詠",   "desc": "顯示驅動IC"},
            {"ticker": "2379", "name": "瑞昱",   "desc": "網通IC"},
            {"ticker": "5269", "name": "祥碩",   "desc": "USB4/PCIe控制器"},
            {"ticker": "3661", "name": "世芯-KY", "desc": "ASIC客製設計"},
            {"ticker": "3414", "name": "奇景光電", "desc": "顯示驅動IC / TDDI"},
            {"ticker": "3483", "name": "力旺",   "desc": "eNVM IP授權"},
        ],
        "下游_封測": [
            {"ticker": "3711", "name": "日月光投控", "desc": "封裝測試全球龍頭"},
            {"ticker": "6257", "name": "矽格",   "desc": "IC封裝"},
            {"ticker": "2449", "name": "京元電子", "desc": "晶圓級測試"},
        ],
    },
    "AI伺服器散熱": {
        "整機ODM": [
            {"ticker": "6669", "name": "緯穎",   "desc": "AI伺服器純ODM（NVDA DGX供應商）"},
            {"ticker": "2382", "name": "廣達",   "desc": "伺服器/筆電ODM"},
            {"ticker": "2356", "name": "英業達",  "desc": "伺服器ODM"},
            {"ticker": "3231", "name": "緯創",   "desc": "伺服器/NB ODM"},
        ],
        "散熱": [
            {"ticker": "3017", "name": "奇鋐",   "desc": "散熱模組（AI伺服器龍頭）"},
            {"ticker": "3324", "name": "雙鴻",   "desc": "散熱模組"},
            {"ticker": "2421", "name": "建準",   "desc": "風扇/散熱系統"},
            {"ticker": "2354", "name": "鴻準",   "desc": "機殼/散熱"},
            {"ticker": "8299", "name": "群電",   "desc": "電源+散熱整合"},
        ],
        "電源供應": [
            {"ticker": "2308", "name": "台達電",  "desc": "UPS/電源/散熱解決方案"},
            {"ticker": "2301", "name": "光寶科",  "desc": "電源供應器ODM"},
            {"ticker": "6282", "name": "康舒",   "desc": "電源供應器"},
        ],
        "高速連接": [
            {"ticker": "3533", "name": "嘉澤",   "desc": "高速連接器（AI伺服器）"},
            {"ticker": "6093", "name": "正淩",   "desc": "高速背板連接器"},
            {"ticker": "6515", "name": "穎崴",   "desc": "連接器"},
            {"ticker": "3665", "name": "貿聯-KY", "desc": "線束/電源線"},
        ],
    },
    "光通訊網通": {
        "光收發模組": [
            {"ticker": "3081", "name": "聯亞",   "desc": "高速光收發（400G/800G）"},
            {"ticker": "4979", "name": "華星光",  "desc": "光收發模組"},
            {"ticker": "3491", "name": "昇達科",  "desc": "光纖被動元件"},
        ],
        "網通設備": [
            {"ticker": "2345", "name": "智邦",   "desc": "雲端網路白牌交換器"},
            {"ticker": "3704", "name": "合勤控",  "desc": "中小企業網通設備"},
            {"ticker": "5388", "name": "中磊",   "desc": "路由器/CPE/Cable Modem"},
            {"ticker": "2485", "name": "兆赫",   "desc": "有線電視/機上盒"},
        ],
        "IaaS/電信": [
            {"ticker": "2412", "name": "中華電",  "desc": "台灣電信龍頭/雲端"},
            {"ticker": "3045", "name": "台灣大",  "desc": "電信/5G"},
            {"ticker": "4904", "name": "遠傳",   "desc": "電信/5G"},
        ],
    },
    "iPhone蘋果供應鏈": {
        "組裝代工": [
            {"ticker": "2317", "name": "鴻海",   "desc": "iPhone最大代工廠"},
            {"ticker": "2354", "name": "鴻準",   "desc": "金屬機殼/散熱"},
            {"ticker": "2474", "name": "可成",   "desc": "鋁合金機殼"},
        ],
        "光學鏡頭": [
            {"ticker": "3008", "name": "大立光",  "desc": "iPhone鏡頭塑膠鏡片龍頭"},
            {"ticker": "3406", "name": "玉晶光",  "desc": "玻璃鏡片"},
            {"ticker": "5348", "name": "厚生",   "desc": "光學薄膜"},
        ],
        "PCB軟板": [
            {"ticker": "6269", "name": "台郡",   "desc": "FPC軟板（蘋果大客戶）"},
            {"ticker": "8150", "name": "南茂",   "desc": "晶片封裝（觸控IC）"},
        ],
        "連接與其他": [
            {"ticker": "3533", "name": "嘉澤",   "desc": "連接器"},
            {"ticker": "2330", "name": "台積電",  "desc": "A系列/M系列晶片代工"},
        ],
    },
    "電動車": {
        "電源充電": [
            {"ticker": "2308", "name": "台達電",  "desc": "車用充電模組/DC-DC"},
            {"ticker": "6282", "name": "康舒",   "desc": "車用電源供應"},
            {"ticker": "3665", "name": "貿聯-KY", "desc": "充電槍/線束"},
        ],
        "PCB電子": [
            {"ticker": "2355", "name": "敬鵬",   "desc": "車用高頻PCB"},
            {"ticker": "3037", "name": "欣興",   "desc": "ABF載板/車用PCB"},
        ],
        "機構零件": [
            {"ticker": "1536", "name": "和大",   "desc": "電動車傳動/差速器"},
            {"ticker": "1533", "name": "車王電",  "desc": "車用電子/馬達控制"},
            {"ticker": "2612", "name": "中航",   "desc": "碳纖維複合材料"},
        ],
    },
    "金融": {
        "銀行": [
            {"ticker": "2882", "name": "國泰金",  "desc": "壽險/銀行"},
            {"ticker": "2881", "name": "富邦金",  "desc": "壽險/銀行/證券"},
            {"ticker": "2886", "name": "兆豐金",  "desc": "銀行/外匯"},
            {"ticker": "2891", "name": "中信金",  "desc": "銀行/消費金融"},
        ],
        "證券保險": [
            {"ticker": "2883", "name": "開發金",  "desc": "創投/銀行"},
            {"ticker": "2884", "name": "玉山金",  "desc": "銀行/數位金融"},
        ],
    },
    "航運": {
        "貨櫃": [
            {"ticker": "2603", "name": "長榮",   "desc": "全球前五大貨櫃航運"},
            {"ticker": "2609", "name": "陽明",   "desc": "貨櫃航運"},
            {"ticker": "2615", "name": "萬海",   "desc": "亞洲內航線/貨櫃"},
        ],
        "散裝港口": [
            {"ticker": "2376", "name": "技嘉",   "desc": ""},  # not shipping
            {"ticker": "5607", "name": "遠雄港",  "desc": "港口物流"},
            {"ticker": "2605", "name": "新興",   "desc": "散裝航運"},
        ],
    },
}


# ── 載入器 ────────────────────────────────────────────────────────

class USMarketLoader:

    def __init__(self):
        self._cache = self._load()

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

    # ── 取得美股資料 ──────────────────────────────────────────────

    def get_market_data(self) -> Dict:
        """取得所有指數 + 關鍵股前一交易日資料（1小時快取）"""
        key = "us_market"
        cached = self._hit(key)
        if cached is not None:
            return cached

        if not _HAS_YF:
            return {"error": "需安裝 yfinance：pip install yfinance", "indices": {}, "stocks": {}}

        all_tickers = list(US_INDICES.keys()) + list(US_KEY_STOCKS.keys())

        try:
            raw = yf.download(
                all_tickers, period="5d", interval="1d",
                progress=False, auto_adjust=True, group_by="ticker",
            )
        except Exception as e:
            return {"error": str(e), "indices": {}, "stocks": {}}

        def _extract(ticker):
            try:
                if len(all_tickers) == 1:
                    df = raw
                else:
                    df = raw[ticker]
                df = df.dropna(subset=["Close"])
                if len(df) < 2:
                    return None
                prev  = float(df["Close"].iloc[-2])
                last  = float(df["Close"].iloc[-1])
                chg   = round((last - prev) / prev * 100, 2) if prev else 0
                date_ = str(df.index[-1].date())
                return {"price": round(last, 2), "change_pct": chg, "date": date_}
            except Exception:
                return None

        indices = {}
        for t, name in US_INDICES.items():
            d = _extract(t)
            if d:
                indices[t] = {**d, "name": name}

        stocks = {}
        for t, name in US_KEY_STOCKS.items():
            d = _extract(t)
            if d:
                stocks[t] = {**d, "name": name}

        result = {
            "indices": indices,
            "stocks":  stocks,
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        self._put(key, result)
        return result

    # ── 影響分析 ─────────────────────────────────────────────────

    def analyze_impact(self, market_data: Dict) -> List[Dict]:
        """
        定性分析：美股昨夜表現 → 台股今日預期方向
        只輸出有顯著移動（≥1%）的美股觸媒
        """
        if "error" in market_data:
            return []

        stocks  = market_data.get("stocks",  {})
        indices = market_data.get("indices", {})

        # 大盤整體氛圍
        sox_chg  = indices.get("^SOX",  {}).get("change_pct", 0)
        ndx_chg  = indices.get("^IXIC", {}).get("change_pct", 0)
        vix_val  = indices.get("^VIX",  {}).get("price", 20)
        sp5_chg  = indices.get("^GSPC", {}).get("change_pct", 0)

        if vix_val >= 30:
            macro_note = f"⚠️ VIX={vix_val:.0f}（恐慌區），市場避險情緒高，台股整體承壓"
        elif vix_val >= 20:
            macro_note = f"🟡 VIX={vix_val:.0f}（謹慎區），波動偏大，注意下行風險"
        else:
            macro_note = f"🟢 VIX={vix_val:.0f}（平靜區），市場情緒穩定"

        impacts = [{"type": "macro", "text": macro_note, "change_pct": 0}]

        # 逐一美股觸媒
        for us_ticker, chain in US_TW_SUPPLY_CHAIN.items():
            s = stocks.get(us_ticker)
            if not s:
                continue
            chg = s["change_pct"]
            if abs(chg) < 1.0:
                continue

            direction = "利多" if chg > 0 else "利空"
            if abs(chg) >= 5:
                mag = "大幅"
            elif abs(chg) >= 2:
                mag = "明顯"
            else:
                mag = "小幅"

            # 台股預期描述（美股收盤影響的是台股「下一個交易日」，非當日；並標註報價日期避免誤導）
            _qd = s.get("date", "")
            _qd_label = f"（{_qd[5:].replace('-', '/')} 美股收盤）" if _qd else ""
            if chg > 0:
                tw_expect = f"台灣 {chain['theme']} 族群下一個交易日易偏多，留意開盤量能是否跟進"
            else:
                tw_expect = f"台灣 {chain['theme']} 族群下一個交易日易承壓，觀察是否跌深反彈"

            impacts.append({
                "type":       "stock",
                "us_ticker":  us_ticker,
                "us_name":    chain["name"],
                "theme":      chain["theme"],
                "change_pct": chg,
                "direction":  direction,
                "magnitude":  mag,
                "as_of":      _qd,
                "tw_stocks":  chain["tw_stocks"],
                "text":       f"**{chain['name']}** {chg:+.1f}%{_qd_label} → {mag}{direction}，{tw_expect}",
            })

        # 費半指數整體提示
        if abs(sox_chg) >= 1.5:
            d = "偏多" if sox_chg > 0 else "偏空"
            impacts.append({
                "type": "index",
                "text": f"費城半導體指數 {sox_chg:+.1f}%，台灣半導體族群（台積電/日月光/聯發科）整體{d}",
                "change_pct": sox_chg,
            })

        return sorted(impacts, key=lambda x: abs(x["change_pct"]), reverse=True)

    def get_tw_industry_chain_for_us(self, us_ticker: str) -> Optional[Dict]:
        """取得特定美股對應的供應鏈資訊"""
        return US_TW_SUPPLY_CHAIN.get(us_ticker)
