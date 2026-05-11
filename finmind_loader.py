"""
FinMind 資料載入器 - 免費台股基本面數據
月營收 / 季報 / 本益比，7 天本機快取
無需付費，免費帳號取得 token 後額度更高
"""

import json
import math
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

try:
    import yfinance as yf
    _HAS_YFINANCE = True
except ImportError:
    _HAS_YFINANCE = False

_CACHE_FILE = Path("tw_quant_data/finmind_cache.json")
_TTL = 7 * 24 * 3600  # 7天


def _f(val) -> Optional[float]:
    """安全轉 float，NaN/None 回傳 None"""
    try:
        v = float(val)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 4)
    except (TypeError, ValueError):
        return None


class FinMindLoader:
    BASE_URL = "https://api.finmindtrade.com/api/v4/data"

    def __init__(self, token: str = ""):
        self.token = token
        self.session = requests.Session()
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

    def _hit(self, key: str) -> Optional[dict]:
        e = self._cache.get(key)
        if e and (time.time() - e.get("ts", 0)) < _TTL:
            return e["data"]
        return None

    def _put(self, key: str, data: dict):
        self._cache[key] = {"ts": time.time(), "data": data}
        self._flush()

    # ── API ────────────────────────────────────────────────────────

    def _api(self, dataset: str, data_id: str, start: str) -> Optional[list]:
        params = {"dataset": dataset, "data_id": data_id, "start_date": start}
        if self.token:
            params["token"] = self.token
        try:
            r = self.session.get(self.BASE_URL, params=params, timeout=15)
            r.raise_for_status()
            body = r.json()
            if body.get("status") != 200:
                return None
            return body.get("data") or []
        except Exception:
            return None

    # ── 主要方法 ───────────────────────────────────────────────────

    def get_fundamental(self, ticker: str) -> Dict:
        """
        取得個股完整基本面（月營收 + 季報 + 本益比）
        7 天快取，同一檔重複查詢瞬間回傳
        """
        key = f"fm:{ticker}"
        cached = self._hit(key)
        if cached is not None:
            return cached

        out = {
            "revenue_yoy": None,
            "revenue_mom": None,
            "latest_revenue_month": None,
            "eps": None,
            "eps_growth_yoy": None,
            "gross_margin": None,
            "net_margin": None,
            "pe": None,
            "pb": None,
            "dividend_yield": None,
            "data_source": "⚠️ 暫無數據",
            "data_type": "NO_DATA",
        }
        has = False

        # ── 月營收 ──
        rows = self._api(
            "TaiwanStockMonthRevenue",
            ticker,
            (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d"),
        )
        if rows and len(rows) >= 2:
            df = pd.DataFrame(rows).sort_values("date")
            rev = df["revenue"].astype(float)
            out["latest_revenue_month"] = df.iloc[-1]["date"]
            if rev.iloc[-2] != 0:
                out["revenue_mom"] = round(
                    (rev.iloc[-1] - rev.iloc[-2]) / abs(rev.iloc[-2]) * 100, 2
                )
            if len(df) >= 13 and rev.iloc[-13] != 0:
                out["revenue_yoy"] = round(
                    (rev.iloc[-1] - rev.iloc[-13]) / abs(rev.iloc[-13]) * 100, 2
                )
            has = True

        # ── 財務報表（季報）──
        rows = self._api(
            "TaiwanStockFinancialStatements",
            ticker,
            (datetime.now() - timedelta(days=365 * 3)).strftime("%Y-%m-%d"),
        )
        if rows:
            try:
                df = pd.DataFrame(rows).sort_values("date")
                pv = df.pivot_table(
                    index="date", columns="type", values="value", aggfunc="last"
                )
                if not pv.empty:
                    last = pv.iloc[-1]
                    out["eps"] = _f(last.get("EPS"))
                    gp = _f(last.get("GrossProfit"))
                    rv = _f(last.get("Revenue"))
                    if gp is not None and rv:
                        out["gross_margin"] = round(gp / rv * 100, 2)
                    ni = _f(last.get("NetIncome"))
                    if ni is not None and rv:
                        out["net_margin"] = round(ni / rv * 100, 2)
                    if len(pv) >= 5 and out["eps"] is not None:
                        y = _f(pv.iloc[-5].get("EPS"))
                        if y and y != 0:
                            out["eps_growth_yoy"] = round(
                                (out["eps"] - y) / abs(y) * 100, 2
                            )
                    has = True
            except Exception:
                pass

        # ── 本益比 / 股價淨值比 ──
        rows = self._api(
            "TaiwanStockPER",
            ticker,
            (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"),
        )
        if rows:
            df = pd.DataFrame(rows).sort_values("date")
            last = df.iloc[-1]
            out["pe"] = _f(last.get("PER"))
            out["pb"] = _f(last.get("PBR"))
            out["dividend_yield"] = _f(last.get("dividend_yield"))
            has = True

        if has:
            out["data_source"] = "✅ FinMind API"
            out["data_type"] = "REAL"

        # yfinance 備援：FinMind 無數據時嘗試取得基本指標
        if not has and _HAS_YFINANCE:
            try:
                info = yf.Ticker(f"{ticker}.TW").info
                pe  = info.get("trailingPE") or info.get("forwardPE")
                pb  = info.get("priceToBook")
                dy  = info.get("dividendYield")
                eps = info.get("trailingEps")
                ry  = info.get("revenueGrowth")
                gm  = info.get("grossMargins")
                nm  = info.get("profitMargins")
                if any(v is not None for v in [pe, pb, dy, eps]):
                    out["pe"]             = _f(pe)
                    out["pb"]             = _f(pb)
                    out["dividend_yield"] = _f(dy * 100) if dy else None
                    out["eps"]            = _f(eps)
                    out["revenue_yoy"]    = _f(ry * 100) if ry else None
                    out["gross_margin"]   = _f(gm * 100) if gm else None
                    out["net_margin"]     = _f(nm * 100) if nm else None
                    out["data_source"]    = "✅ yfinance (備援)"
                    out["data_type"]      = "REAL"
                    has = True
            except Exception:
                pass

        self._put(key, out)
        return out

    def get_revenue_trend(self, ticker: str, months: int = 13) -> List[Dict]:
        """
        月營收趨勢（YoY / MoM），用於個股基本面趨勢圖
        回傳: [{month, revenue, yoy_pct, mom_pct}]，按月份排序
        """
        key = f"rev_trend:{ticker}"
        cached = self._hit(key)
        if cached is not None:
            return cached

        start = (datetime.now() - timedelta(days=30 * (months + 14))).strftime("%Y-%m-%d")
        rows  = self._api("TaiwanStockMonthRevenue", ticker, start)
        if not rows:
            return []

        df = pd.DataFrame(rows).sort_values("date")
        df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
        df = df.dropna(subset=["revenue"]).tail(months + 13)

        result = []
        for i, (_, r) in enumerate(df.iterrows()):
            mom = yoy = None
            if i > 0:
                prev_rev = df.iloc[i - 1]["revenue"]
                if prev_rev:
                    mom = round((r["revenue"] - prev_rev) / abs(prev_rev) * 100, 2)
            if i >= 12:
                yoy_rev = df.iloc[i - 12]["revenue"]
                if yoy_rev:
                    yoy = round((r["revenue"] - yoy_rev) / abs(yoy_rev) * 100, 2)
            result.append({
                "month":   str(r["date"])[:7],
                "revenue": int(r["revenue"]),
                "yoy_pct": yoy,
                "mom_pct": mom,
            })

        out = result[-months:]
        self._put(key, out)
        return out

    def get_financial_trend(self, ticker: str, quarters: int = 8) -> List[Dict]:
        """
        季報趨勢（EPS / 毛利率 / 淨利率），用於個股基本面趨勢圖
        回傳: [{quarter, eps, gross_margin, net_margin}]
        """
        key = f"fin_trend:{ticker}"
        cached = self._hit(key)
        if cached is not None:
            return cached

        start = (datetime.now() - timedelta(days=365 * 3)).strftime("%Y-%m-%d")
        rows  = self._api("TaiwanStockFinancialStatements", ticker, start)
        if not rows:
            return []

        try:
            df = pd.DataFrame(rows)
            pv = df.pivot_table(
                index="date", columns="type", values="value", aggfunc="last"
            )
            result = []
            for date_idx, row in pv.iterrows():
                eps = _f(row.get("EPS"))
                gp  = _f(row.get("GrossProfit"))
                ni  = _f(row.get("NetIncome"))
                rv  = _f(row.get("Revenue"))
                gm  = round(gp / rv * 100, 2) if gp is not None and rv else None
                nm  = round(ni / rv * 100, 2) if ni is not None and rv else None
                result.append({
                    "quarter":      str(date_idx)[:7],
                    "eps":          eps,
                    "gross_margin": gm,
                    "net_margin":   nm,
                })
            out = result[-quarters:]
            self._put(key, out)
            return out
        except Exception:
            return []

    def get_price_history(self, ticker: str, days: int = 120) -> Optional[pd.DataFrame]:
        """
        取得個股歷史 OHLCV（用於技術分析）
        快取 1 天（盤後更新一次即可）
        """
        key = f"ohlcv:{ticker}:{days}"
        # 價格歷史用較短 TTL（1天）
        e = self._cache.get(key)
        if e and (time.time() - e.get("ts", 0)) < 86400:
            data = e["data"]
            if data:
                return pd.DataFrame(data)
            return None

        start = (datetime.now() - timedelta(days=days + 10)).strftime("%Y-%m-%d")
        rows = self._api("TaiwanStockPrice", ticker, start)
        if not rows:
            if not _HAS_YFINANCE:
                return None
            try:
                import datetime as _dt
                yf_df = yf.download(
                    f"{ticker}.TW",
                    start=(_dt.datetime.now() - _dt.timedelta(days=days + 10)).strftime("%Y-%m-%d"),
                    progress=False,
                    auto_adjust=True,
                )
                if yf_df is None or yf_df.empty:
                    return None
                yf_df = yf_df.reset_index()
                # Handle multi-level columns from yfinance
                if isinstance(yf_df.columns, pd.MultiIndex):
                    yf_df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in yf_df.columns]
                else:
                    yf_df.columns = [c.lower() for c in yf_df.columns]
                yf_df = yf_df.rename(columns={"date": "date", "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"})
                need = {"date", "open", "high", "low", "close", "volume"}
                if not need.issubset(yf_df.columns):
                    return None
                yf_df["date"] = yf_df["date"].astype(str).str[:10]
                for c in ["open", "high", "low", "close", "volume"]:
                    yf_df[c] = pd.to_numeric(yf_df[c], errors="coerce")
                yf_df = yf_df[list(need)].dropna().sort_values("date").tail(days).reset_index(drop=True)
                self._cache[key] = {"ts": time.time(), "data": yf_df.to_dict("records")}
                self._flush()
                return yf_df
            except Exception:
                return None

        df = pd.DataFrame(rows)
        need = {"date", "open", "max", "min", "close", "Trading_Volume"}
        if not need.issubset(df.columns):
            return None

        df = df[["date", "open", "max", "min", "close", "Trading_Volume"]].copy()
        df.columns = ["date", "open", "high", "low", "close", "volume"]
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna().sort_values("date").tail(days).reset_index(drop=True)

        self._cache[key] = {"ts": time.time(), "data": df.to_dict("records")}
        self._flush()
        return df
