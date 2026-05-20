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
    from scipy import stats as _sp_stats
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False

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

    def _yfinance_fundamental(self, ticker: str) -> Optional[Dict]:
        """yfinance 主力基本面（PE/EPS/毛利率/ROE 等）"""
        if not _HAS_YFINANCE:
            return None
        try:
            info = yf.Ticker(f"{ticker}.TW").info
            if not info:
                return None
            pe  = info.get("trailingPE") or info.get("forwardPE")
            pb  = info.get("priceToBook")
            dy  = info.get("dividendYield")
            eps = info.get("trailingEps")
            ry  = info.get("revenueGrowth")
            gm  = info.get("grossMargins")
            nm  = info.get("profitMargins")
            roe = info.get("returnOnEquity")
            de  = info.get("debtToEquity")
            mc  = info.get("marketCap")
            h52 = info.get("fiftyTwoWeekHigh")
            l52 = info.get("fiftyTwoWeekLow")
            if not any(v is not None for v in [pe, pb, dy, eps, gm]):
                return None
            return {
                "pe":                   _f(pe),
                "pb":                   _f(pb),
                "eps":                  _f(eps),
                "dividend_yield":       _f(dy * 100) if dy else None,
                "gross_margin":         _f(gm * 100) if gm else None,
                "net_margin":           _f(nm * 100) if nm else None,
                "revenue_yoy":          _f(ry * 100) if ry else None,
                "roe":                  _f(roe * 100) if roe else None,
                "debt_equity":          _f(de),
                "market_cap":           mc,
                "high_52w":             _f(h52),
                "low_52w":              _f(l52),
                # fields not available from yfinance – will be filled by FinMind
                "revenue_mom":          None,
                "latest_revenue_month": None,
                "eps_growth_yoy":       None,
                "data_source":          "✅ Yahoo Finance",
                "data_type":            "REAL",
            }
        except Exception:
            return None

    def _finmind_revenue_only(self, ticker: str) -> Optional[Dict]:
        """只抓 FinMind 月營收（補 yfinance 缺少的 MoM/YoY），節省 API 配額"""
        rows = self._api(
            "TaiwanStockMonthRevenue",
            ticker,
            (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d"),
        )
        if not rows or len(rows) < 2:
            return None
        df = pd.DataFrame(rows).sort_values("date")
        rev = df["revenue"].astype(float)
        result = {"latest_revenue_month": df.iloc[-1]["date"]}
        if rev.iloc[-2] != 0:
            result["revenue_mom"] = round(
                (rev.iloc[-1] - rev.iloc[-2]) / abs(rev.iloc[-2]) * 100, 2
            )
        if len(df) >= 13 and rev.iloc[-13] != 0:
            result["revenue_yoy"] = round(
                (rev.iloc[-1] - rev.iloc[-13]) / abs(rev.iloc[-13]) * 100, 2
            )
        return result

    def _finmind_fundamental(self, ticker: str) -> Dict:
        """完整 FinMind 基本面（月營收 + 季報 + 本益比）"""
        out = {
            "revenue_yoy": None, "revenue_mom": None,
            "latest_revenue_month": None, "eps": None,
            "eps_growth_yoy": None, "gross_margin": None,
            "net_margin": None, "pe": None, "pb": None,
            "dividend_yield": None,
            "data_source": "⚠️ 暫無數據", "data_type": "NO_DATA",
        }
        has = False

        rows = self._api(
            "TaiwanStockMonthRevenue", ticker,
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

        rows = self._api(
            "TaiwanStockFinancialStatements", ticker,
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

        rows = self._api(
            "TaiwanStockPER", ticker,
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
        return out

    def get_fundamental(self, ticker: str) -> Dict:
        """
        取得個股完整基本面。優先 Yahoo Finance（無限制），
        補充 FinMind 月營收（Yahoo 無此欄位）；Yahoo 無資料時 fallback 到 FinMind。
        7 天快取。
        """
        key = f"fm:{ticker}"
        cached = self._hit(key)
        if cached is not None:
            return cached

        # 1. yfinance 主力
        out = self._yfinance_fundamental(ticker)
        if out:
            # 補 FinMind 月營收（YoY/MoM）
            rev = self._finmind_revenue_only(ticker)
            if rev:
                out.update(rev)
                out["data_source"] = "✅ Yahoo Finance + FinMind月營收"
            self._put(key, out)
            return out

        # 2. FinMind 完整備援
        out = self._finmind_fundamental(ticker)
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

    def get_per_trend(self, ticker: str, months: int = 36) -> List[Dict]:
        """
        取得個股 PE/PB/DY 歷史趨勢（FinMind TaiwanStockPER）
        回傳：[{date, pe, pb, dy}]，按日期排序，用於歷史分位數與趨勢圖
        """
        key = f"per_trend:{ticker}"
        cached = self._hit(key)
        if cached is not None:
            return cached

        start = (datetime.now() - timedelta(days=30 * months + 30)).strftime("%Y-%m-%d")
        rows = self._api("TaiwanStockPER", ticker, start)
        if not rows:
            self._put(key, [])
            return []

        df = pd.DataFrame(rows).sort_values("date")
        result = [
            {
                "date": str(r["date"])[:10],
                "pe":   _f(r.get("PER")),
                "pb":   _f(r.get("PBR")),
                "dy":   _f(r.get("dividend_yield")),
            }
            for _, r in df.iterrows()
        ]
        out = result[-months * 22:]  # 每月約22交易日
        self._put(key, out)
        return out

    def get_valuation_percentile(self, ticker: str) -> Dict:
        """
        計算目前 PE/PB/DY 在歷史（3年）中的分位數
        回傳：{pe_pct, pb_pct, dy_pct, pe_curr, pb_curr, dy_curr, status, suggestion}
        分位數低 = 便宜（PE低/PB低/DY高）
        """
        trend = self.get_per_trend(ticker, months=36)
        fund  = self.get_fundamental(ticker)

        result: Dict = {
            "pe_curr": fund.get("pe"),
            "pb_curr": fund.get("pb"),
            "dy_curr": fund.get("dividend_yield"),
            "pe_pct":  None, "pb_pct": None, "dy_pct": None,
            "status":  "⚪ 資料不足",
            "suggestion": "歷史估值資料不足，無法判斷高低估",
        }

        if not trend:
            return result

        pe_hist = [r["pe"] for r in trend if r["pe"] is not None]
        pb_hist = [r["pb"] for r in trend if r["pb"] is not None]
        dy_hist = [r["dy"] for r in trend if r["dy"] is not None]

        def _pct(val, hist):
            if val is None or not hist:
                return None
            if _HAS_SCIPY:
                return round(_sp_stats.percentileofscore(hist, val, kind="rank"), 1)
            # 不依賴 scipy：手算
            below = sum(1 for h in hist if h <= val)
            return round(below / len(hist) * 100, 1)

        pe_pct = _pct(result["pe_curr"], pe_hist)
        pb_pct = _pct(result["pb_curr"], pb_hist)
        # DY 分位數反轉：DY 越高越便宜，所以用 100 - pct
        dy_pct_raw = _pct(result["dy_curr"], dy_hist)
        dy_pct = round(100 - dy_pct_raw, 1) if dy_pct_raw is not None else None

        result.update({"pe_pct": pe_pct, "pb_pct": pb_pct, "dy_pct": dy_pct})

        # 綜合判斷（取有效分位數的平均）
        valid_pcts = [p for p in [pe_pct, pb_pct, dy_pct] if p is not None]
        if valid_pcts:
            avg = sum(valid_pcts) / len(valid_pcts)
            if avg < 25:
                result["status"]     = "🟢 歷史低估區"
                result["suggestion"] = f"PE/PB/DY 綜合分位數 {avg:.0f}%，目前估值偏低，具備安全邊際"
            elif avg < 50:
                result["status"]     = "🟡 合理偏低"
                result["suggestion"] = f"PE/PB/DY 綜合分位數 {avg:.0f}%，估值合理偏低，可逐步觀察"
            elif avg < 75:
                result["status"]     = "🟡 合理偏高"
                result["suggestion"] = f"PE/PB/DY 綜合分位數 {avg:.0f}%，估值偏高，建議等待更好買點"
            else:
                result["status"]     = "🔴 歷史高估區"
                result["suggestion"] = f"PE/PB/DY 綜合分位數 {avg:.0f}%，估值偏高，追高風險大"

        return result

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
