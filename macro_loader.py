"""
宏觀經濟指標載入器（yfinance 代理）
無需 API key，1小時本機快取
指標：WTI油價 / 美10Y / 美2Y / VIX / 黃金 / 美元指數
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

try:
    import yfinance as yf
    _HAS_YFINANCE = True
except ImportError:
    _HAS_YFINANCE = False

_CACHE_FILE = Path("tw_quant_data/macro_cache.json")
_TTL = 3600  # 1小時

# yfinance 代理符號
_MACRO_SYMBOLS = {
    "oil":    ("CL=F",      "WTI 原油",    "美元/桶"),
    "us10y":  ("^TNX",      "美10年期公債", "%"),
    "us2y":   ("^IRX",      "美2年期公債",  "%"),
    "vix":    ("^VIX",      "VIX 恐慌指數", ""),
    "gold":   ("GC=F",      "黃金",         "美元/盎司"),
    "dxy":    ("DX-Y.NYB",  "美元指數",     ""),
}

# 對台股各產業的宏觀影響分析規則
_SECTOR_IMPACT_RULES = {
    "半導體": {
        "high_vix":  ("🔴 偏空", "市場恐慌高，法人可能減碼高本益比科技股"),
        "low_vix":   ("🟢 偏多", "市場穩定，AI/半導體需求資金流入"),
        "high_us10y":("🟡 中性", "高利率壓縮成長股本益比，但AI需求面仍強"),
        "high_oil":  ("🟡 中性", "油價影響製造成本，但半導體以能源密集為主"),
        "high_dxy":  ("🟡 中性", "強美元使台積電ADR吸引力下降，但台幣報價有利"),
    },
    "金融": {
        "high_us10y":("🟢 偏多", "高利率擴大銀行利差收入，金控受益"),
        "low_us10y": ("🔴 偏空", "低利率壓縮利差，影響銀行獲利能力"),
        "high_vix":  ("🔴 偏空", "市場動盪，金融股通常先跌"),
        "low_vix":   ("🟢 偏多", "市場穩定，金融股估值回升"),
    },
    "航運": {
        "high_oil":  ("🔴 偏空", "油價上升直接增加燃油成本，壓縮航運利潤"),
        "low_oil":   ("🟢 偏多", "低油價降低燃料成本，改善航運毛利"),
        "high_dxy":  ("🟡 中性", "強美元使美元計價運費收入對台灣航商較有利"),
    },
    "生技醫療": {
        "high_us10y":("🔴 偏空", "高折現率壓縮生技股（多數無盈利）估值"),
        "low_us10y": ("🟢 偏多", "低利率讓長期現金流的生技股估值擴張"),
        "high_vix":  ("🟡 中性", "防禦性較強，但資金仍會避風險"),
    },
    "電動車/綠能": {
        "high_oil":  ("🟢 偏多", "油價高刺激電動車需求，帶動供應鏈"),
        "low_oil":   ("🔴 偏空", "低油價降低電動車相對優勢"),
        "high_us10y":("🔴 偏空", "高利率增加電動車車貸成本，壓制需求"),
    },
}


class MacroLoader:

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

    # ── 資料抓取 ─────────────────────────────────────────────────

    def _fetch_symbol(self, symbol: str) -> Optional[Dict]:
        """抓單一 yfinance 符號的最新價格與前一日漲跌"""
        if not _HAS_YFINANCE:
            return None
        try:
            tk = yf.Ticker(symbol)
            hist = tk.fast_info
            price = getattr(hist, "last_price", None) or getattr(hist, "regularMarketPrice", None)
            prev  = getattr(hist, "previous_close", None)
            if price is None:
                # 備援：下載近2日 OHLCV
                df = tk.history(period="2d", auto_adjust=True)
                if df is not None and not df.empty:
                    price = float(df["Close"].iloc[-1])
                    prev  = float(df["Close"].iloc[-2]) if len(df) >= 2 else price
            if price is None:
                return None
            chg_pct = round((price - prev) / prev * 100, 2) if prev else None
            return {"price": round(float(price), 4), "chg_pct": chg_pct}
        except Exception:
            return None

    def get_snapshot(self) -> Dict:
        """
        取得最新宏觀指標快照（1小時快取）
        回傳：{oil, us10y, us2y, vix, gold, dxy}
        每個值：{price, chg_pct, label, unit, symbol}
        """
        key = "macro_snapshot"
        cached = self._hit(key)
        if cached is not None:
            return cached

        result = {}
        for name, (symbol, label, unit) in _MACRO_SYMBOLS.items():
            data = self._fetch_symbol(symbol)
            if data:
                result[name] = {**data, "label": label, "unit": unit, "symbol": symbol}

        self._put(key, result)
        return result

    def get_trend(self, name: str, days: int = 90) -> List[Dict]:
        """
        取得單一指標的歷史趨勢（用於圖表）
        name: oil / us10y / us2y / vix / gold / dxy
        """
        if name not in _MACRO_SYMBOLS:
            return []
        key = f"macro_trend:{name}:{days}"
        cached = self._hit(key)
        if cached is not None:
            return cached

        symbol = _MACRO_SYMBOLS[name][0]
        if not _HAS_YFINANCE:
            return []
        try:
            tk = yf.Ticker(symbol)
            start = (datetime.now() - timedelta(days=days + 5)).strftime("%Y-%m-%d")
            df = tk.history(start=start, auto_adjust=True)
            if df is None or df.empty:
                return []
            df = df.reset_index()
            df["Date"] = df["Date"].astype(str).str[:10]
            result = [
                {"date": row["Date"], "price": round(float(row["Close"]), 4)}
                for _, row in df.iterrows()
            ]
            self._put(key, result[-days:])
            return result[-days:]
        except Exception:
            return []

    def analyze_macro_impact(self, snapshot: Dict) -> Dict:
        """
        依據當前宏觀環境，輸出：
        - overall: 整體判斷（樂觀/中性/謹慎）
        - reasons: 關鍵原因列表
        - sector_impact: {產業名稱: (icon, 說明)}
        """
        if not snapshot:
            return {"overall": "⚪ 資料不足", "reasons": [], "sector_impact": {}}

        vix   = snapshot.get("vix",   {}).get("price")
        us10y = snapshot.get("us10y", {}).get("price")
        us2y  = snapshot.get("us2y",  {}).get("price")
        oil   = snapshot.get("oil",   {}).get("price")
        dxy   = snapshot.get("dxy",   {}).get("price")

        reasons = []
        pos_cnt = neg_cnt = 0

        # VIX 判斷
        if vix is not None:
            if vix > 25:
                reasons.append(f"⚠️ VIX {vix:.1f} — 恐慌偏高，市場波動大，建議謹慎")
                neg_cnt += 1
            elif vix > 20:
                reasons.append(f"🟡 VIX {vix:.1f} — 市場略有不安，需留意下行風險")
            else:
                reasons.append(f"✅ VIX {vix:.1f} — 市場相對平穩，有利風險性資產")
                pos_cnt += 1

        # 利差判斷（10Y - 2Y）
        if us10y is not None and us2y is not None:
            spread = us10y - us2y
            if spread < 0:
                reasons.append(f"⚠️ 美債利差 {spread:.2f}% — 殖利率曲線倒掛，衰退警示訊號")
                neg_cnt += 1
            elif spread < 0.3:
                reasons.append(f"🟡 美債利差 {spread:.2f}% — 曲線趨平，景氣動能放緩")
            else:
                reasons.append(f"✅ 美債利差 {spread:.2f}% — 殖利率曲線正常，景氣仍有支撐")
                pos_cnt += 1

        # 美10Y 對估值影響
        if us10y is not None:
            if us10y > 4.5:
                reasons.append(f"⚠️ 美10年期殖利率 {us10y:.2f}% — 高利率壓縮成長股估值空間")
                neg_cnt += 1
            elif us10y < 3.5:
                reasons.append(f"✅ 美10年期殖利率 {us10y:.2f}% — 低利率有利成長股與科技股")
                pos_cnt += 1
            else:
                reasons.append(f"🟡 美10年期殖利率 {us10y:.2f}% — 中性水準，對市場影響有限")

        # 油價
        if oil is not None:
            if oil > 90:
                reasons.append(f"⚠️ WTI 油價 ${oil:.1f} — 高油價推升通膨壓力，不利航運/消費")
                neg_cnt += 1
            elif oil < 65:
                reasons.append(f"✅ WTI 油價 ${oil:.1f} — 低油價有利降低生產成本")
                pos_cnt += 1
            else:
                reasons.append(f"🟡 WTI 油價 ${oil:.1f} — 油價平穩，整體中性")

        # 整體判斷
        if pos_cnt >= 2 and neg_cnt == 0:
            overall = "🟢 整體偏樂觀"
        elif neg_cnt >= 2:
            overall = "🔴 謹慎觀望"
        else:
            overall = "🟡 中性偏謹慎"

        # 產業影響分析
        sector_impact = {}
        state_flags = {
            "high_vix":   vix   is not None and vix   > 25,
            "low_vix":    vix   is not None and vix   < 18,
            "high_us10y": us10y is not None and us10y > 4.5,
            "low_us10y":  us10y is not None and us10y < 3.5,
            "high_oil":   oil   is not None and oil   > 90,
            "low_oil":    oil   is not None and oil   < 65,
            "high_dxy":   dxy   is not None and dxy   > 103,
        }

        for sector, rules in _SECTOR_IMPACT_RULES.items():
            matched = None
            for flag, (impact_label, impact_desc) in rules.items():
                if state_flags.get(flag, False):
                    matched = (impact_label, impact_desc)
                    break
            if matched is None:
                matched = ("🟡 中性", "目前宏觀環境對該產業影響有限")
            sector_impact[sector] = matched

        return {"overall": overall, "reasons": reasons, "sector_impact": sector_impact}
