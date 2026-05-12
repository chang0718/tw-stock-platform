# -*- coding: utf-8 -*-
"""
GitHub Actions 用：在每日報告寄送前執行量化模型，生成 snapshots.json
讓 daily_report.py 的 TOP5 有真實資料，不再顯示「無快照資料」

用法: python scripts/run_model.py
"""

import json
import sys
import types
from datetime import datetime
from pathlib import Path

# ── 在 import 任何專案模組前，先注入 fake streamlit ──────────────────────
# data_loader.py 在載入時呼叫 st.info/warning/success，GitHub Actions 沒有 streamlit
_st = types.ModuleType("streamlit")
for _fn in ("info", "success", "warning", "error", "spinner", "write", "cache_data"):
    setattr(_st, _fn, lambda *a, **k: print("[ST]", *a))
_st.cache_data = lambda *a, **k: (lambda f: f)  # 讓 @st.cache_data 不崩潰
sys.modules["streamlit"] = _st
# ────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DATA_DIR, DEFAULT_WEIGHTS, SNAPSHOT_FILE  # noqa: E402
from data_loader import MarketDataLoader                      # noqa: E402
from quant_model import QuantModel                           # noqa: E402


def save_snapshot(rows: list) -> None:
    snapshot_file = DATA_DIR / SNAPSHOT_FILE
    today = datetime.now().strftime("%Y-%m-%d")

    existing: list = []
    if snapshot_file.exists():
        try:
            existing = json.loads(snapshot_file.read_text(encoding="utf-8"))
        except Exception:
            existing = []

    # 同一天只保留最新一筆
    existing = [s for s in existing if s.get("date") != today]
    existing.append({"date": today, "rows": rows})
    existing = existing[-120:]  # 最多保留 120 天

    snapshot_file.write_text(
        json.dumps(existing, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"[OK] 快照已儲存：{len(rows)} 檔，路徑 {snapshot_file}")


def to_python(val):
    """將 numpy scalar 轉為 Python 原生型別，確保 JSON 可序列化"""
    if hasattr(val, "item"):
        return val.item()
    return val


def main():
    DATA_DIR.mkdir(exist_ok=True)

    print("[INFO] 載入市場資料...")
    loader = MarketDataLoader()
    df = loader.load_all_market_data()

    if df is None or df.empty:
        print("[ERR] 市場資料載入失敗，跳過模型計算")
        sys.exit(1)

    print(f"[INFO] 載入 {len(df)} 檔，執行量化模型...")
    model = QuantModel(weights=DEFAULT_WEIGHTS)
    result_df = model.enrich_dataframe(df, preferred_groups=[])

    if result_df is None or result_df.empty:
        print("[ERR] 模型計算結果為空")
        sys.exit(1)

    # 轉為純 Python dict（排除 numpy scalar）
    rows = [
        {k: to_python(v) for k, v in record.items()}
        for record in result_df.to_dict("records")
    ]

    save_snapshot(rows)

    top5 = sorted(rows, key=lambda r: r.get("prob20", 0), reverse=True)[:5]
    print("[DONE] TOP5（1月漲機率）:")
    for i, r in enumerate(top5, 1):
        print(f"  {i}. {r.get('ticker')} {r.get('name', '')}  prob20={r.get('prob20', 0):.0f}%")


if __name__ == "__main__":
    main()
