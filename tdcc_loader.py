"""
tdcc_loader.py — 集保結算所（TDCC）股權分散表：大戶持股比例（免費、每週）

資料源：TDCC OpenData 股權分散表（全市場最新一週快照，免費、免 token）
    https://opendata.tdcc.com.tw/getOD.ashx?id=1-5
欄位：資料日期, 證券代號, 持股分級, 人數, 股數, 占集保庫存數比例%

持股分級（張＝1,000 股）：
    級距 1~15 為股數級距，16=差異數調整，17=合計。
    級距 15 = 1,000,001 股以上 → **≥1,000 張大戶**
    級距 12~15 = 400,001 股以上 → **≥400 張大戶**
    級距 1    = 1~999 股         → 零股/最小散戶

用途定位：反映「大戶持股水位」的週變化（增持/減持），屬官方合法資料。
⚠️ 限制：
    1. TDCC OpenData 只提供「最新一週」快照 → 週增減需逐週累積本機快照（首次僅一週）。
    2. 每週更新（非每日、非即時），與 T86 每日買賣超為不同時間尺度。
    3. 這不是「券商分點主力進出」（那需付費資料），是合法免費的大戶持股替代指標。
"""

from __future__ import annotations

import csv
import io
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests
import urllib3

from utils import read_json, write_json

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_TDCC_URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
_RAW_CACHE_FILE = Path("tw_quant_data/tdcc_cache.json")   # 全市場解析後快取（1 天，ephemeral 可）
# 逐週累積快照 → 放 tracked 路徑，供 GitHub Actions commit-back 長期保存
# （tw_quant_data/ 為 gitignore 且雲端 ephemeral，重啟即失，故改此處）
_HISTORY_FILE = Path("data/major_holders/history.json")
_RAW_TTL = 24 * 3600          # 全市場 CSV 1 天內不重抓（週更新，抓一次夠）
_MAX_WEEKS = 20               # 每檔最多保留 20 週歷史

# 大戶級距定義（≥400 張 / ≥1000 張）
_GE400_LEVELS = {"12", "13", "14", "15"}
_GE1000_LEVELS = {"15"}


class TDCCLoader:
    """集保股權分散大戶持股載入器（免費、每週）。"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

    # ── 全市場 CSV（1 天快取，避免重複下載 ~2MB）────────────────────

    def _fetch_all(self) -> Dict[str, Dict]:
        """
        下載並解析 TDCC 全市場股權分散，回傳
        {ticker: {"date": YYYY-MM-DD, "levels": {級距: 占比%}}}。
        1 天內用本機快取。
        """
        cache = read_json(_RAW_CACHE_FILE, {})
        if cache and (time.time() - cache.get("ts", 0)) < _RAW_TTL:
            return cache.get("data", {})

        try:
            r = self.session.get(_TDCC_URL, timeout=60, verify=False)
            r.raise_for_status()
            text = r.text
        except Exception:
            # 下載失敗 → 退回舊快取（若有），否則空
            return cache.get("data", {}) if cache else {}

        parsed: Dict[str, Dict] = {}
        reader = csv.reader(io.StringIO(text))
        header = next(reader, None)  # 跳過表頭
        for row in reader:
            if len(row) < 6:
                continue
            date_raw, ticker, level, holders, shares, ratio = row[:6]
            ticker = ticker.strip()
            level = level.strip()
            if not ticker or not level:
                continue
            d = date_raw.strip()
            iso = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 and d.isdigit() else d
            try:
                ratio_f = float(ratio)
            except (ValueError, TypeError):
                ratio_f = 0.0
            entry = parsed.setdefault(ticker, {"date": iso, "levels": {}})
            entry["levels"][level] = ratio_f

        if parsed:
            write_json(_RAW_CACHE_FILE, {"ts": time.time(), "data": parsed})
        return parsed

    @staticmethod
    def _ratios(levels: Dict[str, float]) -> tuple:
        """由持股分級占比算 (ge400_ratio, ge1000_ratio)。"""
        ge1000 = round(sum(levels.get(l, 0.0) for l in _GE1000_LEVELS), 2)
        ge400 = round(sum(levels.get(l, 0.0) for l in _GE400_LEVELS), 2)
        return ge400, ge1000

    # ── 批次週快照（供 GitHub Actions 每週回存 tracked 歷史）────────

    def bulk_snapshot(self, tickers) -> int:
        """
        對 tickers 抓當週大戶比例，累積進 tracked 歷史檔（依日期去重、保留最近 N 週）。
        一次讀寫歷史檔（非逐檔），回傳本次新增的檔數。供排程呼叫。
        """
        alldata = self._fetch_all()
        if not alldata:
            return 0
        hist = read_json(_HISTORY_FILE, {})
        added = 0
        for t in {str(x) for x in tickers}:
            rec = alldata.get(t)
            if not rec:
                continue
            ge400, ge1000 = self._ratios(rec.get("levels", {}))
            date = rec.get("date", "")
            series = hist.get(t, [])
            if not any(s.get("date") == date for s in series):
                series.append({"date": date, "ge400": ge400, "ge1000": ge1000})
                hist[t] = sorted(series, key=lambda s: s.get("date", ""))[-_MAX_WEEKS:]
                added += 1
        if added:
            write_json(_HISTORY_FILE, hist)
        return added

    # ── 單檔大戶持股（含逐週累積趨勢）──────────────────────────────

    def get_major_holders(self, ticker: str) -> Dict:
        """
        回傳單檔大戶持股比例與（本機累積的）週趨勢：
        {
          has_data, date,
          ge1000_ratio,          # ≥1000 張大戶占集保庫存比例%
          ge400_ratio,           # ≥400 張大戶占比%
          wow_ge1000, wow_ge400, # 對上一筆快照的週增減（pp）；無前週則 None
          trend: [{date, ge400, ge1000}, ...]  # 排程累積的歷史 + 本週（唯讀，不寫檔）
        }

        ⚠️ 唯讀：歷史累積由 scripts/tdcc_snapshot.py（排程）寫入 tracked 檔並 commit-back。
        本方法僅讀取歷史 + 併入本週值供顯示，不寫檔（避免 UI 污染 tracked 工作樹）。
        """
        alldata = self._fetch_all()
        rec = alldata.get(str(ticker))
        if not rec:
            return {"has_data": False}

        ge400, ge1000 = self._ratios(rec.get("levels", {}))
        date = rec.get("date", "")

        # 讀已累積歷史，在記憶體併入本週（去重），不寫檔
        hist = read_json(_HISTORY_FILE, {})
        series = list(hist.get(str(ticker), []))
        if not any(s.get("date") == date for s in series):
            series.append({"date": date, "ge400": ge400, "ge1000": ge1000})
        trend = sorted(series, key=lambda s: s.get("date", ""))[-_MAX_WEEKS:]

        wow_ge1000 = wow_ge400 = None
        if len(trend) >= 2:
            prev = trend[-2]
            wow_ge1000 = round(ge1000 - prev["ge1000"], 2)
            wow_ge400 = round(ge400 - prev["ge400"], 2)

        return {
            "has_data": True,
            "date": date,
            "ge1000_ratio": ge1000,
            "ge400_ratio": ge400,
            "wow_ge1000": wow_ge1000,
            "wow_ge400": wow_ge400,
            "trend": trend,
        }
