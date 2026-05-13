# -*- coding: utf-8 -*-
"""
冷啟動腳本：從 yfinance 批次下載前 N 大台股 60 天歷史收盤價
執行後 price_history.json 立即有真實資料，模型動能/波動率分數差異立刻拉開

用法（在虛擬環境中執行）:
    python scripts/init_price_history.py
或只下載前 50 大:
    python scripts/init_price_history.py --top 50
"""

import argparse
import json
import sys
import time
from pathlib import Path

import urllib3
import requests
import yfinance as yf

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DATA_DIR

HISTORY_FILE = DATA_DIR / "price_history.json"
DEFAULT_TOP = 100
DEFAULT_DAYS = 60
DELAY = 0.5  # 每筆間隔秒數，避免 yfinance rate limit

# 備用清單（TWSE API 失敗時使用）：台股前 100 大成交量標的
FALLBACK_TICKERS = [
    "2330", "2317", "2454", "2412", "2308", "2303", "1301", "1303", "2882", "2881",
    "2002", "3711", "2886", "5871", "2884", "2891", "2892", "2885", "2880", "2883",
    "2345", "3045", "4904", "2382", "2395", "2379", "3008", "2357", "2327", "2337",
    "1402", "2609", "2615", "2603", "2610", "2301", "3034", "6505", "1326", "1216",
    "2207", "1101", "1102", "2105", "2103", "2408", "3481", "2376", "2356", "2353",
    "2324", "2371", "3706", "5880", "6669", "3533", "2352", "2344", "2323", "3231",
    "2377", "3017", "2368", "2347", "2361", "6415", "2385", "2360", "2498", "3037",
    "2404", "2401", "3673", "2349", "6770", "2388", "2393", "5483", "3443", "4938",
    "2449", "2459", "6285", "3529", "2492", "5274", "6230", "3042", "3714", "4915",
    "6462", "8046", "2409", "2460", "3552", "5347", "2425", "6531", "3665", "6230",
]


def fetch_twse_top_n(n: int) -> list:
    """從 TWSE 盤後行情 API 取前 N 大成交量股票代碼"""
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        r = requests.get(url, timeout=20, verify=False)
        r.raise_for_status()
        data = r.json()
        candidates = []
        for item in data:
            code = item.get("Code", "")
            vol_str = item.get("TradeVolume", "0").replace(",", "")
            # 只取 4 位數字的股票代碼（排除 ETF 與特殊商品）
            if code and code.isdigit() and len(code) == 4:
                try:
                    candidates.append((code, int(vol_str)))
                except ValueError:
                    pass
        candidates.sort(key=lambda x: x[1], reverse=True)
        result = [c[0] for c in candidates[:n]]
        print(f"[OK] TWSE API 取得 {len(result)} 個代碼（依成交量排序）")
        return result
    except Exception as e:
        print(f"[WARN] TWSE API 失敗: {e}，改用備用清單")
        return FALLBACK_TICKERS[:n]


def download_history(ticker: str, days: int) -> list:
    """用 yfinance 下載單檔台股歷史收盤價"""
    symbol = f"{ticker}.TW"
    try:
        df = yf.download(symbol, period=f"{days}d", auto_adjust=True, progress=False)
        if df.empty:
            return []
        records = []
        for idx, row in df.iterrows():
            close = row["Close"]
            # 處理 pandas Series（多層 column）或 scalar
            if hasattr(close, "item"):
                close = close.item()
            elif hasattr(close, "iloc"):
                close = float(close.iloc[0])
            records.append({
                "date": idx.strftime("%Y-%m-%d"),
                "close": round(float(close), 2),
            })
        return records
    except Exception as e:
        print(f"    WARN: {e}")
        return []


def main():
    parser = argparse.ArgumentParser(description="台股歷史收盤價冷啟動腳本")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP, help=f"下載前 N 大台股（預設 {DEFAULT_TOP}）")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"歷史天數（預設 {DEFAULT_DAYS}）")
    parser.add_argument("--delay", type=float, default=DELAY, help=f"每筆請求間隔秒（預設 {DELAY}）")
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)

    # 讀取現有資料（增量更新，不覆蓋已有的歷史）
    existing: dict = {}
    if HISTORY_FILE.exists():
        try:
            existing = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            print(f"[INFO] 已有 {len(existing)} 檔歷史資料，將增量更新")
        except Exception:
            existing = {}

    print(f"[INFO] 取得前 {args.top} 大台股代碼...")
    tickers = fetch_twse_top_n(args.top)
    print(f"[INFO] 開始下載 {args.days} 天歷史（間隔 {args.delay}s）...\n")

    updated = 0
    skipped = 0
    for i, ticker in enumerate(tickers, 1):
        print(f"  [{i:3d}/{len(tickers)}] {ticker}.TW", end=" ... ", flush=True)
        records = download_history(ticker, args.days)
        if records:
            existing[ticker] = records
            updated += 1
            print(f"OK  ({len(records)} 筆)")
        else:
            skipped += 1
            print("SKIP（無資料）")
        time.sleep(args.delay)

    HISTORY_FILE.write_text(
        json.dumps(existing, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"\n[DONE] 更新 {updated} 檔 / 跳過 {skipped} 檔")
    print(f"       儲存到 {HISTORY_FILE}")
    print(f"       現在重新開啟平台並「載入市場」，模型分數差異應明顯拉開")


if __name__ == "__main__":
    main()
