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
import os
import sys
import types
from datetime import datetime
from pathlib import Path

import pandas as pd

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
from paper_trading import PaperTradingEngine, LEDGER_FILE, DEFAULT_CONFIG  # noqa: E402
from finmind_loader import FinMindLoader           # noqa: E402

# 精簡 liquid universe 上限（僅對此子集抓基本面，控管 FinMind API 呼叫量／逾時風險）
LIQUID_UNIVERSE_SIZE = 200


def load_fundamentals_for_universe(df):
    """
    對「已預篩的精簡 liquid universe」逐檔載入 FinMind/Yahoo 基本面。

    回傳 (fundamental_data, market_cap_map, n_real)：
      - fundamental_data：{ticker: fundamental dict}，供 compute_final_composite 的品質加成
      - market_cap_map  ：{ticker: market_cap}，附回 model_df 供 B2 市值層過濾
      - n_real          ：實際取得真實基本面的檔數（供 log）

    無 token 時 FinMind 額度受限、多數會降級為 NO_DATA，屬預期行為（B2 的
    require_real_fund 層會自動放寬並記錄），本函式仍完成、不中斷每日記帳。
    """
    token = os.environ.get("FINMIND_TOKEN", "")
    fm = FinMindLoader(token=token)
    fundamental_data = {}
    market_cap_map = {}
    n_real = 0
    for t in df["ticker"].astype(str).tolist():
        try:
            fd = fm.get_fundamental(t)  # 沿用 App 相同介面（yfinance 主力 + FinMind 月營收）
        except Exception as e:
            print(f"[WARN] {t} 基本面載入失敗：{e}")
            continue
        if not fd:
            continue
        fundamental_data[t] = fd
        mc = fd.get("market_cap")
        if mc is not None:
            market_cap_map[t] = mc
        if fd.get("data_type") == "REAL":
            n_real += 1
    return fundamental_data, market_cap_map, n_real


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

    # ── 預篩 liquid universe：先用成交量（張）挑出最有量的前 N 檔，只對此子集抓基本面 ──
    # 目的：把 FinMind/Yahoo API 呼叫量壓在 ~200 檔內，避免全市場逐檔（成本/逾時），
    # 同時確保紙上交易選股池的基本面資料來自有流動性的標的。
    min_lots = DEFAULT_CONFIG.get("min_volume_lots", 0)
    liquid = df.copy()
    if "volume" in liquid.columns:
        liquid["_vol_num"] = pd.to_numeric(liquid["volume"], errors="coerce").fillna(0)
        if min_lots:
            liquid = liquid[liquid["_vol_num"] >= min_lots]
        liquid = liquid.sort_values("_vol_num", ascending=False).head(LIQUID_UNIVERSE_SIZE)
        liquid = liquid.drop(columns=["_vol_num"])
    else:
        liquid = liquid.head(LIQUID_UNIVERSE_SIZE)
    print(f"[INFO] 預篩 liquid universe：{len(liquid)} 檔（volume>={min_lots}張，上限 {LIQUID_UNIVERSE_SIZE}）")

    # ── 對精簡池載入基本面（best-effort；無 token 時多數降級，B2 會自動放寬）──
    print("[INFO] 載入精簡池基本面（FinMind/Yahoo）...")
    try:
        fundamental_data, market_cap_map, n_real = load_fundamentals_for_universe(liquid)
    except Exception as e:
        print(f"[WARN] 基本面批次載入異常，改用純技術面：{e}")
        fundamental_data, market_cap_map, n_real = {}, {}, 0
    print(f"[INFO] 取得真實基本面 {n_real}/{len(liquid)} 檔（market_cap {len(market_cap_map)} 檔）")

    print(f"[INFO] 對 {len(liquid)} 檔計算量化模型...")
    model = QuantModel(weights=DEFAULT_WEIGHTS)
    model_df = model.enrich_dataframe(
        liquid, preferred_groups=[], fundamental_data=fundamental_data
    )
    if model_df is None or model_df.empty:
        print("[ERR] 模型結果為空")
        sys.exit(1)

    # 附回 market_cap 欄位，供 paper_trading 的市值過濾層使用（無資料者為 NaN，自動被濾/放寬）
    model_df["market_cap"] = model_df["ticker"].astype(str).map(market_cap_map)

    # 與 App 共用計分（帶基本面品質加成，排名與 App 一致）
    model_df["final_composite"] = QuantModel.compute_final_composite(
        model_df, preferred_groups=[], sentiment_data={}, fundamental_data=fundamental_data
    )

    benchmark = fetch_benchmark_close()
    print(f"[INFO] 基準 0050 收盤：{benchmark}")

    engine = PaperTradingEngine.load(LEDGER_FILE)
    rec = engine.run_day(model_df, date=today, benchmark_close=benchmark)
    engine.save(LEDGER_FILE)

    metrics = engine.equity_metrics()
    if rec.get("relaxed"):
        print(f"[INFO] 選股池放寬過濾層：{rec['relaxed']}（合格池不足時逐層放寬）")
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
