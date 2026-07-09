"""
scripts/tdcc_snapshot.py — 每週集保大戶持股快照（GitHub Actions 回存 repo）

TDCC OpenData 僅提供「最新一週」快照 → 週增減需逐週累積。本腳本由排程每日執行
（TDCC 週更新，靠日期去重，重跑冪等），把「關注股票池」的當週大戶比例累積進
tracked 歷史檔 data/major_holders/history.json，由 workflow commit 回存長期保留。

股票池 = config 供應鏈/概念股清單 ∪ 紙上交易持倉 ∪ 現有歷史檔已收錄者。
（雲端讀不到使用者本機 watchlist，故以平台聚焦的投資標的為主。）

無 token、免付費；純官方免費資料。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from tdcc_loader import TDCCLoader
from utils import read_json

_LEDGER = Path("data/paper_trading/ledger.json")
_HISTORY = Path("data/major_holders/history.json")


def _build_universe() -> set:
    tickers: set = set()

    # 1) config 供應鏈 + 概念股（平台聚焦的投資標的）
    for src in (getattr(config, "SUPPLY_CHAIN_GROUPS", {}),
                getattr(config, "CONCEPT_STOCKS", {})):
        if isinstance(src, dict):
            for lst in src.values():
                if isinstance(lst, (list, tuple)):
                    tickers.update(str(t) for t in lst)

    # 2) 紙上交易目前持倉
    ledger = read_json(_LEDGER, {})
    positions = ledger.get("positions", {}) if isinstance(ledger, dict) else {}
    tickers.update(str(t) for t in positions.keys())

    # 3) 現有歷史檔已收錄者（維持其連續累積）
    hist = read_json(_HISTORY, {})
    if isinstance(hist, dict):
        tickers.update(str(t) for t in hist.keys())

    # 過濾非數字代號
    return {t for t in tickers if t and t[0].isdigit()}


def main() -> int:
    universe = _build_universe()
    print(f"[tdcc_snapshot] 股票池 {len(universe)} 檔")
    if not universe:
        print("[tdcc_snapshot] 股票池為空，跳過")
        return 0

    loader = TDCCLoader()
    added = loader.bulk_snapshot(universe)
    print(f"[tdcc_snapshot] 本次新增/更新 {added} 檔當週快照 -> {_HISTORY}")
    return added


if __name__ == "__main__":
    main()
