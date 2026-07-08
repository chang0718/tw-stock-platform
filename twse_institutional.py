"""
TWSE 三大法人 + 融資融券資料載入器
全市場一次 API 呼叫，1 天本機快取
資料來源: TWSE 官方開放資料（完全免費）
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from utils import get_retry_session

_CACHE_FILE = Path("tw_quant_data/institutional_cache.json")
_TTL = 24 * 3600  # 1天


class TWSeInstitutionalLoader:

    def __init__(self):
        self.session = get_retry_session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
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
                json.dumps(self._cache, ensure_ascii=False),
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

    # ── 工具 ──────────────────────────────────────────────────────

    @staticmethod
    def _roc(dt: datetime) -> str:
        """轉民國年格式 YYYMMDD"""
        return f"{dt.year - 1911}{dt.strftime('%m%d')}"

    @staticmethod
    def _num(s) -> int:
        try:
            return int(str(s).replace(",", "").replace("+", "").strip())
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _records_date(data: dict) -> Optional[str]:
        """從已建立的結果字典取出資料日期（ISO YYYY-MM-DD），供日期對齊判斷。"""
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, dict) and v.get("date"):
                    return v["date"]
        return None

    def _stale_for(self, data: dict, prefer_date: Optional[str]) -> bool:
        """指定對齊日期時，若快取資料日期不符即視為過時（需重抓對齊）。"""
        if not prefer_date:
            return False
        return self._records_date(data) != prefer_date

    @staticmethod
    def _date_candidates(prefer_date: Optional[str]):
        """產生嘗試日期清單：優先對齊 prefer_date（行情日期），再退回最近 3 個交易日。"""
        cands = []
        if prefer_date:
            try:
                cands.append(datetime.strptime(prefer_date, "%Y-%m-%d"))
            except (ValueError, TypeError):
                pass
        for delta in range(3):
            cands.append(datetime.now() - timedelta(days=delta))
        # 去重（保序）+ 濾掉週末
        seen, out = set(), []
        for dt in cands:
            ymd = dt.strftime("%Y%m%d")
            if ymd in seen or dt.weekday() >= 5:
                continue
            seen.add(ymd)
            out.append(dt)
        return out

    # ── FinMind 備援（單股，已有 FinMind token 才有效）──────────────

    def _finmind_inst_fallback(self, token: str = "") -> Dict[str, Dict]:
        """FinMind TaiwanStockInstitutionalInvestorsBuySell 全市場備援"""
        try:
            from datetime import date
            import requests as _req
            today = date.today().strftime("%Y-%m-%d")
            params = {
                "dataset":    "TaiwanStockInstitutionalInvestorsBuySell",
                "start_date": today,
            }
            if token:
                params["token"] = token
            resp = _req.get(
                "https://api.finmindtrade.com/api/v4/data",
                params=params, timeout=(5, 10),
            )
            body = resp.json()
            if body.get("status") != 200:
                return {}
            rows = body.get("data") or []
            result: Dict[str, Dict] = {}
            for row in rows:
                t = str(row.get("stock_id", "")).strip()
                if not t:
                    continue
                name = row.get("name", "")
                if name in ("外陸資買賣超股數(千股)", "自營商買賣超股數(千股)", "投信買賣超股數(千股)", "三大法人買賣超股數"):
                    continue
                # FinMind 同樣以「股」為單位，÷1000 換算為「張」與 TWSE 路徑一致
                fn = round(int(row.get("Foreign_Investor_diff", 0) or 0) / 1000)
                tn = round(int(row.get("Investment_Trust_diff",  0) or 0) / 1000)
                dn = round(int(row.get("Dealer_diff",             0) or 0) / 1000)
                if t not in result:
                    result[t] = {
                        "foreign_net": fn, "trust_net": tn, "dealer_net": dn,
                        "total_net":   fn + tn + dn,
                        "date":        today,
                        "data_source": "✅ FinMind (備援)",
                    }
            return result
        except Exception:
            return {}

    # ── 三大法人 ──────────────────────────────────────────────────

    def get_institutional_all(
        self, finmind_token: str = "", prefer_date: Optional[str] = None
    ) -> Dict[str, Dict]:
        """
        取得全市場三大法人買賣超（1 天快取）

        prefer_date（ISO YYYY-MM-DD）：優先抓「與行情同一交易日」的法人資料，避免卡面
        價格與法人分屬不同日期造成誤解（例：價格 07-02、法人 07-03）。該日 T86 尚未
        發布才退回最近一筆；每筆結果均含實際 `date` 欄供 UI 標注。
        單次 API 呼叫取得所有股票。API 原始單位為「股」，
        本方法已換算為「張」（= 1,000 股 = 千股）後回傳，與全平台顯示一致。
        """
        key = "inst"
        cached = self._hit(key)
        if cached is not None and not self._stale_for(cached, prefer_date):
            return cached

        # 優先對齊行情日期，再退回最近 3 個交易日（法人資料最多延遲 1 天）
        for dt in self._date_candidates(prefer_date):
            try:
                r = self.session.get(
                    "https://www.twse.com.tw/fund/T86",
                    params={
                        "response": "json",
                        "date": dt.strftime("%Y%m%d"),  # T86 需西元 YYYYMMDD（非民國）
                        "selectType": "ALL",
                    },
                    timeout=(5, 8),  # (connect_timeout, read_timeout)
                )
                r.raise_for_status()
                body = r.json()
                if body.get("stat") != "OK":
                    continue

                # 用欄位名稱決定索引，提高穩定性
                fields = body.get("fields", [])
                fi = {f: i for i, f in enumerate(fields)}

                def idx(candidates, default):
                    for c in candidates:
                        if c in fi:
                            return fi[c]
                    return default

                # TWSE T86 實際欄位名（單位為「股」），保留舊名作為相容備援
                f_idx = idx(["外陸資買賣超股數(不含外資自營商)", "外陸資買賣超股數(千股)", "外資買賣超股數(千股)"], 4)
                t_idx = idx(["投信買賣超股數", "投信買賣超股數(千股)"], 10)
                d_idx = idx(["自營商買賣超股數", "自營商買賣超股數(千股)"], 11)
                # 三大法人合計（通常是最後一欄）
                total_keys = [k for k in fi if "三大法人" in k]
                tot_idx = fi[total_keys[0]] if total_keys else (len(fields) - 1)

                result = {}
                date_label = dt.strftime("%Y-%m-%d")
                for row in body.get("data", []):
                    if len(row) <= max(f_idx, t_idx, d_idx):
                        continue
                    ticker = str(row[0]).strip()
                    if not ticker or not ticker[0].isdigit():
                        continue
                    # T86 回傳單位為「股」，平台統一以「張」（= 1,000 股）顯示，故 ÷1000
                    fn = round(self._num(row[f_idx]) / 1000)
                    tn = round(self._num(row[t_idx]) / 1000)
                    dn = round(self._num(row[d_idx]) / 1000)
                    tot = (
                        round(self._num(row[tot_idx]) / 1000)
                        if len(row) > tot_idx else fn + tn + dn
                    )
                    result[ticker] = {
                        "foreign_net": fn,
                        "trust_net": tn,
                        "dealer_net": dn,
                        "total_net": tot,
                        "date": date_label,
                        "data_source": "✅ TWSE API",
                    }

                if result:
                    self._put(key, result)
                    return result

            except Exception:
                continue

        # TWSE 全部失敗 → 嘗試 FinMind 備援
        fallback = self._finmind_inst_fallback(finmind_token)
        if fallback:
            self._put(key, fallback)
            return fallback

        return {}

    # ── 融資融券 ──────────────────────────────────────────────────

    def get_margin_all(self, prefer_date: Optional[str] = None) -> Dict[str, Dict]:
        """
        取得全市場融資融券餘額（1 天快取）
        單次 API 呼叫取得所有股票；prefer_date 優先對齊行情日期（同 get_institutional_all）。
        """
        key = "margin"
        cached = self._hit(key)
        if cached is not None and not self._stale_for(cached, prefer_date):
            return cached

        for dt in self._date_candidates(prefer_date):
            try:
                r = self.session.get(
                    "https://www.twse.com.tw/exchangeReport/MI_MARGN",
                    params={
                        "response": "json",
                        "date": dt.strftime("%Y%m%d"),  # MI_MARGN 需西元 YYYYMMDD（非民國）
                        "selectType": "ALL",
                    },
                    timeout=(5, 8),  # (connect_timeout, read_timeout)
                )
                r.raise_for_status()
                body = r.json()
                if body.get("stat") != "OK":
                    continue

                fields = body.get("fields", [])
                fi = {f: i for i, f in enumerate(fields)}

                def idx(candidates, default):
                    for c in candidates:
                        if c in fi:
                            return fi[c]
                    return default

                mb_idx = idx(["融資餘額"], 5)
                sb_idx = idx(["融券餘額"], 10)
                buy_idx = idx(["融資買進"], 2)
                sell_idx = idx(["融資賣出"], 3)
                repay_idx = idx(["融資現金償還"], 4)
                ss_idx = idx(["融券賣出"], 7)
                sc_idx = idx(["融券買進"], 8)

                result = {}
                date_label = dt.strftime("%Y-%m-%d")
                for row in body.get("data", []):
                    if len(row) <= max(mb_idx, sb_idx):
                        continue
                    ticker = str(row[0]).strip()
                    if not ticker or not ticker[0].isdigit():
                        continue
                    margin_chg = (
                        self._num(row[buy_idx])
                        - self._num(row[sell_idx])
                        - self._num(row[repay_idx])
                    )
                    short_chg = self._num(row[ss_idx]) - self._num(row[sc_idx])
                    result[ticker] = {
                        "margin_balance": self._num(row[mb_idx]),
                        "margin_change": margin_chg,
                        "short_balance": self._num(row[sb_idx]),
                        "short_change": short_chg,
                        "date": date_label,
                        "data_source": "✅ TWSE API",
                    }

                if result:
                    self._put(key, result)
                    return result

            except Exception:
                continue

        return {}
