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
                "dividend_yield":       _f(dy * 100) if dy and 0 < dy < 0.30 else None,
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
            (datetime.now() - timedelta(days=760)).strftime("%Y-%m-%d"),  # 25個月確保有去年同月
        )
        if not rows or len(rows) < 2:
            return None
        df = pd.DataFrame(rows).sort_values("date")
        df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
        df = df.dropna(subset=["revenue"])
        if df.empty:
            return None
        df["ym"] = df["date"].astype(str).str[:7]
        ym_rev = df.drop_duplicates("ym", keep="last").set_index("ym")["revenue"]

        latest_ym = ym_rev.index[-1]
        latest_rev = float(ym_rev.iloc[-1])
        result = {"latest_revenue_month": latest_ym}

        # MoM：比前一個月
        if len(ym_rev) >= 2 and ym_rev.iloc[-2] != 0:
            result["revenue_mom"] = round(
                (latest_rev - float(ym_rev.iloc[-2])) / abs(float(ym_rev.iloc[-2])) * 100, 2
            )

        # YoY：依日期找去年同月，避免缺月造成位移誤差
        yr, mo = int(latest_ym[:4]), int(latest_ym[5:7])
        prev_ym = f"{yr - 1:04d}-{mo:02d}"
        if prev_ym in ym_rev.index and ym_rev[prev_ym] != 0:
            prev_rev = float(ym_rev[prev_ym])
            result["revenue_yoy"] = round(
                (latest_rev - prev_rev) / abs(prev_rev) * 100, 2
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
            (datetime.now() - timedelta(days=760)).strftime("%Y-%m-%d"),  # 25個月
        )
        if rows and len(rows) >= 2:
            df = pd.DataFrame(rows).sort_values("date")
            df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
            df = df.dropna(subset=["revenue"])
            if not df.empty:
                df["ym"] = df["date"].astype(str).str[:7]
                ym_rev = df.drop_duplicates("ym", keep="last").set_index("ym")["revenue"]
                latest_ym = ym_rev.index[-1]
                latest_rev = float(ym_rev.iloc[-1])
                out["latest_revenue_month"] = latest_ym
                if len(ym_rev) >= 2 and ym_rev.iloc[-2] != 0:
                    out["revenue_mom"] = round(
                        (latest_rev - float(ym_rev.iloc[-2])) / abs(float(ym_rev.iloc[-2])) * 100, 2
                    )
                yr, mo = int(latest_ym[:4]), int(latest_ym[5:7])
                prev_ym = f"{yr - 1:04d}-{mo:02d}"
                if prev_ym in ym_rev.index and ym_rev[prev_ym] != 0:
                    prev_rev = float(ym_rev[prev_ym])
                    out["revenue_yoy"] = round(
                        (latest_rev - prev_rev) / abs(prev_rev) * 100, 2
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
                    # EPS：改用近四季合計（TTM），而非最新單季
                    if "EPS" in pv.columns:
                        eps_series = pv["EPS"].dropna()
                        if len(eps_series) >= 4:
                            out["eps"] = round(float(eps_series.iloc[-4:].sum()), 2)  # TTM
                        elif len(eps_series) > 0:
                            out["eps"] = _f(eps_series.iloc[-1])
                    # 毛利率 / 淨利率：取最新一季
                    gp = _f(last.get("GrossProfit"))
                    rv = _f(last.get("Revenue"))
                    if gp is not None and rv:
                        out["gross_margin"] = round(gp / rv * 100, 2)
                    ni = _f(last.get("NetIncome"))
                    if ni is not None and rv:
                        out["net_margin"] = round(ni / rv * 100, 2)
                    # EPS YoY：近四季 TTM vs 前四季 TTM（日期比對，不用位置索引）
                    if "EPS" in pv.columns:
                        eps_s = pv["EPS"].dropna()
                        if len(eps_s) >= 8:
                            ttm_now  = float(eps_s.iloc[-4:].sum())
                            ttm_prev = float(eps_s.iloc[-8:-4].sum())
                            if ttm_prev and ttm_prev != 0:
                                out["eps_growth_yoy"] = round(
                                    (ttm_now - ttm_prev) / abs(ttm_prev) * 100, 2
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
            # 補充 eps_growth_yoy（yfinance 不提供，用 FinMind 季報計算 TTM YoY）
            if out.get("eps_growth_yoy") is None:
                fin = self.get_financial_trend(ticker, quarters=8)
                eps_valid = [r["eps"] for r in fin if r.get("eps") is not None]
                if len(eps_valid) >= 8:
                    ttm_now  = sum(eps_valid[-4:])
                    ttm_prev = sum(eps_valid[-8:-4])
                    if ttm_prev and ttm_prev != 0:
                        out["eps_growth_yoy"] = round(
                            (ttm_now - ttm_prev) / abs(ttm_prev) * 100, 2
                        )
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

        # 拉 25 個月確保有去年同月數據
        start = (datetime.now() - timedelta(days=760)).strftime("%Y-%m-%d")
        rows  = self._api("TaiwanStockMonthRevenue", ticker, start)
        if not rows:
            return []

        df = pd.DataFrame(rows).sort_values("date")
        df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
        df = df.dropna(subset=["revenue"])
        df["ym"] = df["date"].astype(str).str[:7]
        df = df.drop_duplicates("ym", keep="last").reset_index(drop=True)

        # 建立 ym → revenue 查詢表，供日期比對 YoY
        ym_rev = df.set_index("ym")["revenue"].to_dict()

        result = []
        for _, r in df.iterrows():
            curr_ym = r["ym"]
            curr_rev = float(r["revenue"])
            mom = yoy = None

            # MoM：找上個月
            yr, mo = int(curr_ym[:4]), int(curr_ym[5:7])
            mo -= 1
            if mo == 0:
                mo, yr = 12, yr - 1
            prev_ym = f"{yr:04d}-{mo:02d}"
            if prev_ym in ym_rev and ym_rev[prev_ym]:
                mom = round((curr_rev - ym_rev[prev_ym]) / abs(ym_rev[prev_ym]) * 100, 2)

            # YoY：找去年同月（日期比對，不用位置索引）
            yr2, mo2 = int(curr_ym[:4]), int(curr_ym[5:7])
            prev_yr_ym = f"{yr2 - 1:04d}-{mo2:02d}"
            if prev_yr_ym in ym_rev and ym_rev[prev_yr_ym]:
                yoy = round((curr_rev - ym_rev[prev_yr_ym]) / abs(ym_rev[prev_yr_ym]) * 100, 2)

            # YTD YoY：今年 Jan–目前月累計 vs 去年同期累計
            yr2, mo2 = int(curr_ym[:4]), int(curr_ym[5:7])
            ytd_curr = sum(ym_rev.get(f"{yr2:04d}-{m:02d}", 0) for m in range(1, mo2 + 1))
            ytd_prev_val = sum(ym_rev.get(f"{yr2-1:04d}-{m:02d}", 0) for m in range(1, mo2 + 1))
            prev_months_cnt = sum(1 for m in range(1, mo2 + 1) if f"{yr2-1:04d}-{m:02d}" in ym_rev)
            ytd_yoy = None
            if ytd_prev_val > 0 and prev_months_cnt == mo2:
                ytd_yoy = round((ytd_curr - ytd_prev_val) / ytd_prev_val * 100, 2)

            result.append({
                "month":       curr_ym,
                "revenue":     int(curr_rev),
                "yoy_pct":     yoy,
                "mom_pct":     mom,
                "ytd_yoy_pct": ytd_yoy,
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
                    "eps_qoq":      None,
                    "gm_qoq":       None,
                    "eps_yoy":      None,  # 去年同季比較
                })
            # QoQ（季環比）：與前一季比較
            for i in range(1, len(result)):
                cur = result[i]; prv = result[i - 1]
                if cur["eps"] is not None and prv["eps"] is not None and prv["eps"] != 0:
                    cur["eps_qoq"] = round((cur["eps"] - prv["eps"]) / abs(prv["eps"]) * 100, 2)
                if cur["gross_margin"] is not None and prv["gross_margin"] is not None:
                    cur["gm_qoq"] = round(cur["gross_margin"] - prv["gross_margin"], 2)
            # YoY（同季年比）：日期比對，找去年同季
            q_eps_map = {r["quarter"]: r["eps"] for r in result if r["eps"] is not None}
            for r in result:
                if r["eps"] is None:
                    continue
                ym = r["quarter"]  # e.g. "2026-03"
                yr2, mo2 = int(ym[:4]), int(ym[5:7])
                prev_ym2 = f"{yr2 - 1:04d}-{mo2:02d}"
                prev_eps2 = q_eps_map.get(prev_ym2)
                if prev_eps2 is not None and abs(prev_eps2) > 0.001:
                    r["eps_yoy"] = round((r["eps"] - prev_eps2) / abs(prev_eps2) * 100, 2)
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

    def get_eps_fair_value(self, ticker: str) -> Dict:
        """
        用歷史中位數 PE × 近四季 EPS，估算基本面公平價區間。
        回傳：{
            fair_low:  float|None,   # 25th percentile PE × EPS
            fair_mid:  float|None,   # median PE × EPS
            fair_high: float|None,   # 75th percentile PE × EPS
            pe_25:  float|None,
            pe_50:  float|None,
            pe_75:  float|None,
            eps:    float|None,
            has_data: bool,
        }
        完全基於 get_per_trend() + get_fundamental()，無需額外 API。
        """
        trend = self.get_per_trend(ticker, months=36)
        fund  = self.get_fundamental(ticker)
        eps   = fund.get("eps")

        empty = {
            "fair_low": None, "fair_mid": None, "fair_high": None,
            "fair_growth": None,
            "pe_25": None, "pe_50": None, "pe_75": None,
            "eps": eps, "has_data": False,
            "eps_growth_rate": None, "gm_trend": None, "pe_growth_adj": None,
        }

        if not trend or eps is None or eps <= 0:
            return empty

        pe_hist = sorted([r["pe"] for r in trend if r["pe"] is not None and r["pe"] > 0])
        if len(pe_hist) < 6:
            return empty

        n = len(pe_hist)
        pe_25 = pe_hist[int(n * 0.25)]
        pe_50 = pe_hist[int(n * 0.50)]
        pe_75 = pe_hist[int(n * 0.75)]

        result = {
            "fair_low":  round(pe_25 * eps, 2),
            "fair_mid":  round(pe_50 * eps, 2),
            "fair_high": round(pe_75 * eps, 2),
            "fair_growth": None,
            "pe_25":     round(pe_25, 1),
            "pe_50":     round(pe_50, 1),
            "pe_75":     round(pe_75, 1),
            "eps":       eps,
            "has_data":  True,
            "eps_growth_rate": None, "gm_trend": None, "pe_growth_adj": None,
        }

        # PEG 成長調整目標價：近四季 EPS 成長率 × 毛利率趨勢溢價
        fin_trend = self.get_financial_trend(ticker, quarters=10)
        valid_q = [(r["eps"], r["gross_margin"]) for r in fin_trend
                   if r.get("eps") is not None]
        if len(valid_q) >= 8:
            recent_eps = [e for e, _ in valid_q[-4:]]
            prior_eps  = [e for e, _ in valid_q[-8:-4]]
            recent_gm  = [g for _, g in valid_q[-4:] if g is not None]
            prior_gm   = [g for _, g in valid_q[-8:-4] if g is not None]
            recent_sum = sum(recent_eps); prior_sum = sum(prior_eps)
            eps_gr = None
            if prior_sum and prior_sum != 0:
                eps_gr = (recent_sum - prior_sum) / abs(prior_sum)
            gm_tr = None
            if recent_gm and prior_gm:
                gm_tr = round(sum(recent_gm)/len(recent_gm) - sum(prior_gm)/len(prior_gm), 2)
            if eps_gr is not None:
                growth_adj = max(-0.30, min(0.50, eps_gr))
                gm_adj = 1 + max(-0.10, min(0.20, (gm_tr or 0) / 100))
                pe_growth_adj = round(pe_50 * (1 + growth_adj), 1)
                result.update({
                    "fair_growth":    round(pe_growth_adj * eps * gm_adj, 2),
                    "eps_growth_rate": round(eps_gr * 100, 1),
                    "gm_trend":       gm_tr,
                    "pe_growth_adj":  pe_growth_adj,
                })
        return result

    def get_eps_breakout(self, ticker: str) -> Dict:
        """
        今年 YTD 累計 EPS 是否已接近/超越去年全年 EPS（爆發訊號）。
        回傳: {prev_full_year_eps, ytd_eps, quarters_counted, pace_ratio,
               annual_pace, on_track_to_exceed, already_exceeded, prev_year, curr_year}
        """
        fin_trend = self.get_financial_trend(ticker, quarters=12)
        if len(fin_trend) < 5:
            return {}

        from collections import defaultdict
        year_eps: dict = defaultdict(list)
        for q in fin_trend:
            qdate = q.get("quarter", "")
            eps = q.get("eps")
            if len(qdate) >= 4 and eps is not None:
                year_eps[int(qdate[:4])].append(eps)

        if not year_eps:
            return {}
        curr_year = max(year_eps.keys())
        prev_year = curr_year - 1
        if prev_year not in year_eps or len(year_eps[prev_year]) < 4:
            return {}

        curr_quarters = year_eps[curr_year]
        prev_quarters = year_eps[prev_year]
        if not curr_quarters:
            return {}

        prev_full = sum(prev_quarters)
        ytd_eps   = sum(curr_quarters)
        q_cnt     = len(curr_quarters)
        if prev_full == 0:
            return {}

        annual_pace = ytd_eps * (4 / q_cnt)
        return {
            "prev_full_year_eps": round(prev_full, 2),
            "ytd_eps":            round(ytd_eps, 2),
            "quarters_counted":   q_cnt,
            "pace_ratio":         round(ytd_eps / prev_full, 3),
            "annual_pace":        round(annual_pace, 2),
            "on_track_to_exceed": annual_pace >= prev_full,
            "already_exceeded":   ytd_eps >= prev_full,
            "prev_year":          prev_year,
            "curr_year":          curr_year,
        }

    def get_institutional_trend(self, ticker: str, days: int = 20) -> List[Dict]:
        """
        個股近 N 交易日三大法人每日買賣超（FinMind TaiwanStockInstitutionalInvestorsBuySell）。
        回傳: [{date, foreign_net, trust_net, dealer_net}]，按日期升序排列。
        快取 1 天。需要 FinMind token。
        """
        key = f"inst_trend:{ticker}:{days}"
        e = self._cache.get(key)
        if e and (time.time() - e.get("ts", 0)) < 86400:
            return e["data"]

        start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
        rows = self._api("TaiwanStockInstitutionalInvestorsBuySell", ticker, start)
        if not rows:
            return []

        try:
            df = pd.DataFrame(rows)
            if df.empty or "name" not in df.columns:
                return []

            # 只取三大法人欄位，pivot by date + name
            # 欄位：date, stock_id, name, buy, sell, diff (= buy-sell 差)
            df["date"] = df["date"].astype(str).str[:10]
            df["diff"] = pd.to_numeric(df.get("diff", pd.Series([0]*len(df))), errors="coerce").fillna(0)

            name_map = {
                "外資":   "foreign_net",
                "外陸資": "foreign_net",
                "外資及陸資(不含外資自營商)": "foreign_net",
                "投信":   "trust_net",
                "自營商": "dealer_net",
                "自營商(自行買賣)": "dealer_net",
            }

            date_data: dict = {}
            for _, r in df.iterrows():
                d = r["date"]
                nm = str(r.get("name", ""))
                col = name_map.get(nm)
                if col is None:
                    continue
                if d not in date_data:
                    date_data[d] = {"date": d, "foreign_net": 0, "trust_net": 0, "dealer_net": 0}
                # 若同 name 多列，累加
                date_data[d][col] += int(r["diff"])

            result = sorted(date_data.values(), key=lambda x: x["date"])
            # 只取最近 days 筆交易日
            result = result[-days:]

            self._cache[key] = {"ts": time.time(), "data": result}
            self._flush()
            return result
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

    def get_etf_performance(self, ticker: str) -> dict:
        """
        計算 ETF 月/季/年報酬率（從 get_price_history 取首末收盤計算）
        回傳 {"month": float|None, "quarter": float|None, "year": float|None}
        """
        def _period_return(days: int) -> Optional[float]:
            df = self.get_price_history(ticker, days=days + 5)
            if df is None or len(df) < 2:
                return None
            first = df["close"].iloc[0]
            last  = df["close"].iloc[-1]
            if first and first > 0:
                return round((last / first - 1) * 100, 2)
            return None

        return {
            "month":   _period_return(20),
            "quarter": _period_return(60),
            "year":    _period_return(252),
        }
