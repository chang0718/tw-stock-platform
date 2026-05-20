"""
SEC 13F 大型機構持股追蹤
使用 edgartools（pip install edgartools，免費，無需 API key）
注意：13F 每季更新一次，有最長 45 天申報延遲
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

_CACHE_FILE = Path("tw_quant_data/institutional_13f_cache.json")
_TTL = 7 * 24 * 3600  # 7天（13F 季報不常更新）

# 追蹤的基金（CIK 號碼）
TRACKED_FUNDS = {
    "Bridgewater Associates": "1061005",
    "Berkshire Hathaway":     "0001067983",
    "Renaissance Technologies": "0001037389",
    "Two Sigma":              "0001496585",
    "Citadel Advisors":       "0001423298",
}

# 台股相關的美國掛牌標的（ADR 或供應鏈）
TW_RELATED_TICKERS = {
    "TSM":   "台積電 ADR",
    "ASX":   "聯電 ADR",
    "ASML":  "ASML（台積電主要設備供應商）",
    "AMAT":  "Applied Materials（半導體設備）",
    "KLAC":  "KLA Corp（半導體設備）",
    "LRCX":  "Lam Research（半導體設備）",
    "MU":    "Micron（記憶體，台系封測客戶）",
    "NVDA":  "NVIDIA（AI晶片，台積電主力客戶）",
    "AMD":   "AMD（IC設計，台積電客戶）",
    "INTC":  "Intel（晶圓代工競爭對手）",
    "QCOM":  "Qualcomm（IC設計，聯發科競對）",
    "HON":   "Honeywell（工業自動化）",
    "PANW":  "Palo Alto（網路安全，相關台廠：智邦）",
}

try:
    import edgar
    _HAS_EDGAR = True
except ImportError:
    try:
        from edgar import Company, set_identity
        _HAS_EDGAR = True
    except ImportError:
        _HAS_EDGAR = False


class InstitutionalTracker:

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

    # ── 主要方法 ───────────────────────────────────────────────────

    def get_holdings(self, fund_name: str, top_n: int = 20) -> List[Dict]:
        """
        取得指定基金最新 13F 持倉前 N 名
        回傳：[{ticker, company, value_usd, shares, pct_portfolio, tw_related}]
        """
        cik = TRACKED_FUNDS.get(fund_name)
        if not cik:
            return []

        key = f"holdings:{cik}:{top_n}"
        cached = self._hit(key)
        if cached is not None:
            return cached

        if not _HAS_EDGAR:
            self._put(key, [])
            return []

        try:
            from edgar import Company, set_identity
            set_identity("tw-stock-platform research@example.com")
            company = Company(cik)
            filings = company.get_filings(form="13F-HR")
            if not filings:
                self._put(key, [])
                return []

            # 取最新一份
            latest = filings[0]
            doc = latest.obj()
            if doc is None:
                self._put(key, [])
                return []

            holdings_raw = doc.holdings if hasattr(doc, "holdings") else []
            if not holdings_raw:
                self._put(key, [])
                return []

            results = []
            total_value = sum(getattr(h, "value", 0) or 0 for h in holdings_raw)
            for h in sorted(holdings_raw, key=lambda x: getattr(x, "value", 0) or 0, reverse=True)[:top_n]:
                ticker = getattr(h, "cusip", "") or ""
                name   = getattr(h, "name",  "") or getattr(h, "issuer_name", "")
                value  = getattr(h, "value", 0) or 0
                shares = getattr(h, "shares", 0) or 0
                pct    = round(value / total_value * 100, 2) if total_value > 0 else None
                # 嘗試從 name 反查 tw_related
                tw_note = ""
                for sym, note in TW_RELATED_TICKERS.items():
                    if sym.upper() in (name or "").upper() or sym.upper() in ticker.upper():
                        tw_note = note
                        break
                results.append({
                    "ticker":        ticker,
                    "company":       name,
                    "value_usd":     value,
                    "shares":        shares,
                    "pct_portfolio": pct,
                    "tw_related":    tw_note,
                })

            self._put(key, results)
            return results

        except Exception:
            self._put(key, [])
            return []

    def get_tw_related_holdings(self) -> List[Dict]:
        """
        跨所有追蹤基金，篩出與台股相關的持股
        回傳：[{fund, ticker, company, value_usd, pct_portfolio, tw_related}]
        """
        key = "tw_related_all"
        cached = self._hit(key)
        if cached is not None:
            return cached

        results = []
        for fund_name in TRACKED_FUNDS:
            holdings = self.get_holdings(fund_name, top_n=50)
            for h in holdings:
                if h.get("tw_related"):
                    results.append({"fund": fund_name, **h})

        self._put(key, results)
        return results

    def get_filing_date(self, fund_name: str) -> Optional[str]:
        """取得最新 13F 的申報日期"""
        cik = TRACKED_FUNDS.get(fund_name)
        if not cik or not _HAS_EDGAR:
            return None
        try:
            from edgar import Company, set_identity
            set_identity("tw-stock-platform research@example.com")
            company = Company(cik)
            filings = company.get_filings(form="13F-HR")
            if filings:
                return str(getattr(filings[0], "filing_date", ""))[:10]
        except Exception:
            pass
        return None

    @property
    def has_edgar(self) -> bool:
        return _HAS_EDGAR

    @staticmethod
    def install_hint() -> str:
        return "pip install edgartools"
