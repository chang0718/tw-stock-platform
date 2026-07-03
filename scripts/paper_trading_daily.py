# -*- coding: utf-8 -*-
"""
GitHub Actions 用：每日盤後執行紙上交易一日，並把帳本寫入 data/paper_trading/ledger.json
（由 workflow 後續步驟 commit 回存 repo，長期累積以評估模型選股能力）。

用法: python scripts/paper_trading_daily.py

設計重點：
- 與 App 共用 QuantModel.compute_final_composite 計分，確保排名一致
- 基準採 0050（yfinance），用以計算 Alpha
- 不使用未來資料：僅以當日盤後分數決策，下一交易日才結算
- 任一外部資料失敗皆 best-effort 降級，不中斷每日記帳
"""
import sys
import types
from datetime import datetime
from pathlib import Path

# ── 在 import 任何專案模組前，注入 fake streamlit（CI 無 streamlit）──────────
def _safe_log(*a, **k):
    try:
        print("[ST]", *a)
    except Exception:
        pass  # 避免 Windows cp950 主控台無法輸出 emoji 時中斷


_st = types.ModuleType("streamlit")
for _fn in ("info", "success", "warning", "error", "spinner", "write", "cache_data"):
    setattr(_st, _fn, _safe_log)
_st.cache_data = lambda *a, **k: (lambda f: f)
sys.modules["streamlit"] = _st
# ────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DEFAULT_WEIGHTS                 # noqa: E402
from data_loader import MarketDataLoader           # noqa: E402
from quant_model import QuantModel                 # noqa: E402
from paper_trading import PaperTradingEngine, LEDGER_FILE  # noqa: E402


def fetch_benchmark_close(symbols=("0050.TW", "^TWII")):
    """抓基準最新收盤（0050 優先，退回大盤 ^TWII）；全失敗回 None（Alpha 當日略過）。"""
    try:
        import yfinance as yf
    except Exception as e:
        print(f"[WARN] yfinance 不可用：{e}")
        return None
    for sym in symbols:
        try:
            hist = yf.Ticker(sym).history(period="5d")
            if hist is not None and not hist.empty:
                px = hist["Close"].dropna()
                if not px.empty:
                    print(f"[INFO] 基準採用 {sym}")
                    return float(px.iloc[-1])
        except Exception as e:
            print(f"[WARN] 基準 {sym} 抓取失敗：{e}")
    return None


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"[INFO] 紙上交易每日執行 {today}")

    print("[INFO] 載入市場資料...")
    loader = MarketDataLoader()
    df, _ = loader.load_all_market_data()
    if df is None or df.empty:
        print("[ERR] 市場資料載入失敗，跳過")
        sys.exit(1)

    print(f"[INFO] 載入 {len(df)} 檔，計算量化模型...")
    model = QuantModel(weights=DEFAULT_WEIGHTS)
    model_df = model.enrich_dataframe(df, preferred_groups=[])
    if model_df is None or model_df.empty:
        print("[ERR] 模型結果為空")
        sys.exit(1)

    # 與 App 共用計分（headless 無逐檔基本面/新聞 → 用模型核心分；overlay 為 v2）
    model_df["final_composite"] = QuantModel.compute_final_composite(
        model_df, preferred_groups=[], sentiment_data={}, fundamental_data={}
    )

    benchmark = fetch_benchmark_close()
    print(f"[INFO] 基準 0050 收盤：{benchmark}")

    engine = PaperTradingEngine.load(LEDGER_FILE)
    rec = engine.run_day(model_df, date=today, benchmark_close=benchmark)
    engine.save(LEDGER_FILE)

    metrics = engine.equity_metrics()
    print(f"[OK] NAV={rec['nav']:.0f}  持倉={rec['n_pos']}  "
          f"累積={rec['cum_return_pct']}%  基準={rec.get('bench_return_pct')}%")
    print(f"[OK] 指標：Sharpe={metrics['sharpe']} MDD={metrics['max_drawdown_pct']}% "
          f"勝率={metrics['win_rate_pct']}% IC={metrics['ic']} (已平倉 {metrics['n_closed']})")
    today_trades = [t for t in engine.ledger["trades"] if t.get("date") == today]
    for t in today_trades:
        print(f"   {t['action']} {t['ticker']} {t['name']} x{t['shares']} @ {t['price']}  {t['reason']}")
    print(f"[OK] 帳本已寫入 {LEDGER_FILE}")


if __name__ == "__main__":
    main()
