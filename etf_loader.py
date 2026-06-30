"""
ETF 成分股載入與快照模組
- 解析發行商持股 CSV（容錯欄名與編碼：utf-8 / big5 / cp950）
- 帶日期快照存取：tw_quant_data/etf_holdings/{etf}/{YYYY-MM-DD}.json
- 與持股/追蹤清單重疊比對

說明：台灣 ETF 全成分股無乾淨的免費 API（FinMind 無、TWSE openapi 僅受益人數排行、
yfinance 收錄不全），故 v1 以使用者匯入發行商持股檔為主。快照帶日期，作為日後
「成分股變化（新增/剔除/權重）」diff 的基礎。
"""

import io
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from utils import read_json, write_json

ETF_HOLDINGS_DIR = Path("tw_quant_data") / "etf_holdings"

# 欄名候選（正規化後比對）
_TICKER_KEYS = ["股票代號", "證券代號", "商品代號", "成分股代號", "標的代號", "代號",
                "ticker", "code", "stockcode", "symbol"]
_NAME_KEYS = ["股票名稱", "商品名稱", "成分股名稱", "證券名稱", "標的名稱", "名稱",
              "name", "stockname"]
_WEIGHT_KEYS = ["權重", "權重(%)", "比例", "投資比例", "比重", "比重(%)", "持股權重",
                "佔淨值比例", "weight", "weighting", "percent", "percentage"]

# 非個股列關鍵字（過濾現金/合計/期貨等）
_SKIP_KEYS = ["現金", "合計", "總計", "小計", "期貨", "保證金", "其他", "存款",
              "cash", "total", "future", "nav", "margin"]


def _norm(s) -> str:
    return str(s).strip().lower().replace(" ", "").replace("　", "")


def _read_csv_any(file_or_bytes) -> Optional[pd.DataFrame]:
    """容錯讀 CSV：streamlit UploadedFile / bytes / str 皆可；嘗試多種編碼。"""
    if hasattr(file_or_bytes, "read"):
        data = file_or_bytes.read()
    else:
        data = file_or_bytes
    if isinstance(data, str):
        data = data.encode("utf-8")
    if not data:
        return None
    for enc in ("utf-8-sig", "big5", "cp950", "utf-8"):
        try:
            df = pd.read_csv(io.BytesIO(data), encoding=enc, dtype=str)
            if df is not None and len(df.columns) >= 1:
                return df
        except Exception:
            continue
    return None


def parse_holdings_csv(file_or_bytes) -> List[Dict]:
    """
    解析發行商持股 CSV → 正規化 [{ticker, name, weight}]，依權重由大到小排序。
    無法辨識代號/名稱欄時回傳空 list（呼叫端顯示提示，不捏造）。
    """
    df = _read_csv_any(file_or_bytes)
    if df is None or df.empty:
        return []

    cols = {_norm(c): c for c in df.columns}

    def _find(keys):
        for k in keys:                       # 精確比對
            if _norm(k) in cols:
                return cols[_norm(k)]
        for nk, orig in cols.items():        # 模糊包含
            if any(_norm(k) in nk for k in keys):
                return orig
        return None

    tcol, ncol, wcol = _find(_TICKER_KEYS), _find(_NAME_KEYS), _find(_WEIGHT_KEYS)
    if tcol is None and ncol is None:
        return []

    skip = [_norm(x) for x in _SKIP_KEYS]
    out: List[Dict] = []
    for _, row in df.iterrows():
        ticker = str(row.get(tcol, "")).strip() if tcol else ""
        name = str(row.get(ncol, "")).strip() if ncol else ""
        ticker = ticker.split(".")[0].strip()  # 去掉 .TW / .TWO 後綴
        if _norm(ticker) in ("", "nan") and _norm(name) in ("", "nan"):
            continue
        if any(sk in _norm(name) or sk in _norm(ticker) for sk in skip):
            continue
        weight = None
        if wcol is not None:
            wraw = str(row.get(wcol, "")).replace("%", "").replace(",", "").strip()
            try:
                weight = round(float(wraw), 4)
            except Exception:
                weight = None
        out.append({"ticker": ticker, "name": name, "weight": weight})

    out.sort(key=lambda r: (r["weight"] is None, -(r["weight"] or 0)))
    return out


# ── 快照存取 ──────────────────────────────────────────────────────────

def _etf_dir(etf: str) -> Path:
    return ETF_HOLDINGS_DIR / str(etf).strip()


def save_snapshot(etf: str, holdings: List[Dict], snap_date: Optional[str] = None) -> str:
    """存一份帶日期快照，回傳日期字串。"""
    d = snap_date or date.today().isoformat()
    write_json(_etf_dir(etf) / f"{d}.json",
               {"date": d, "etf": str(etf), "holdings": holdings})
    return d


def list_snapshots(etf: str) -> List[str]:
    """回傳該 ETF 已存在的快照日期（由舊到新）。"""
    p = _etf_dir(etf)
    if not p.exists():
        return []
    return sorted(f.stem for f in p.glob("*.json"))


def load_snapshot(etf: str, snap_date: str) -> Optional[Dict]:
    data = read_json(_etf_dir(etf) / f"{snap_date}.json", None)
    return data or None


def load_latest(etf: str) -> Optional[Dict]:
    snaps = list_snapshots(etf)
    return load_snapshot(etf, snaps[-1]) if snaps else None


def overlap_with(holdings: List[Dict], tickers) -> set:
    """回傳成分股代號與使用者 tickers 的交集。"""
    ts = {str(t).strip() for t in (tickers or [])}
    return {h.get("ticker") for h in holdings if h.get("ticker") in ts}


def fetch_issuer_holdings(etf: str) -> Optional[List[Dict]]:
    """
    （v2 預留）best-effort 自動抓發行商 PCF。各家格式不一且需逐家驗證，
    v1 不實作，一律回 None，呼叫端回退為 CSV 匯入。
    """
    return None
