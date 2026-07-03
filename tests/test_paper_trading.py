# -*- coding: utf-8 -*-
"""紙上交易引擎單元測試：維持 N 檔、輪動換股、扣成本、NAV/指標計算。"""
import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from paper_trading import PaperTradingEngine  # noqa: E402


def _mk_df(scores: dict, price=100.0, risk=30.0, senti=None):
    """scores: {ticker: final_composite}；其餘欄位用合理預設。"""
    rows = []
    for t, fc in scores.items():
        rows.append({
            "ticker": t, "name": f"股{t}", "close": price,
            "final_composite": fc, "risk_score": risk,
            "sentiment_score": (senti or {}).get(t),
            "volume": 5000,
        })
    return pd.DataFrame(rows)


def test_maintains_n_positions_and_costs():
    eng = PaperTradingEngine(config={"initial_budget": 1_000_000, "max_positions": 5})
    df = _mk_df({"A": 90, "B": 85, "C": 80, "D": 75, "E": 70, "F": 65}, price=100.0)
    rec = eng.run_day(df, date="2026-01-01", benchmark_close=50.0)
    # 應持有前 5 名 A~E，F 落榜
    assert set(eng.ledger["positions"].keys()) == {"A", "B", "C", "D", "E"}
    assert rec["n_pos"] == 5
    # 買進有扣成本 → 現金 + 部位市值 應略低於初始（成本損耗）
    assert rec["nav"] < 1_000_000
    assert rec["nav"] > 990_000  # 但損耗很小（手續費+滑價約 0.24%）


def test_rotation_sells_dropouts():
    eng = PaperTradingEngine(config={"max_positions": 3})
    d1 = _mk_df({"A": 90, "B": 80, "C": 70, "D": 60}, price=100.0)
    eng.run_day(d1, date="2026-01-01", benchmark_close=50.0)
    assert set(eng.ledger["positions"]) == {"A", "B", "C"}
    # 次日 C 掉出、D 升上 → 應賣 C 買 D
    d2 = _mk_df({"A": 90, "B": 80, "D": 75, "C": 50}, price=100.0)
    eng.run_day(d2, date="2026-01-02", benchmark_close=51.0)
    assert set(eng.ledger["positions"]) == {"A", "B", "D"}
    sells = [t for t in eng.ledger["trades"] if t["action"] == "SELL"]
    assert any(s["ticker"] == "C" for s in sells)


def test_risk_guard_sells():
    eng = PaperTradingEngine(config={"max_positions": 2, "risk_guard": 80})
    d1 = _mk_df({"A": 90, "B": 80}, price=100.0, risk=30.0)
    eng.run_day(d1, date="2026-01-01", benchmark_close=50.0)
    assert set(eng.ledger["positions"]) == {"A", "B"}
    # A 風險飆高（利空）→ 即使仍在榜上也賣出
    d2 = pd.DataFrame([
        {"ticker": "A", "name": "股A", "close": 100, "final_composite": 90, "risk_score": 95, "sentiment_score": None, "volume": 5000},
        {"ticker": "B", "name": "股B", "close": 100, "final_composite": 80, "risk_score": 30, "sentiment_score": None, "volume": 5000},
    ])
    eng.run_day(d2, date="2026-01-02", benchmark_close=50.0)
    assert "A" not in eng.ledger["positions"]


def test_nav_tracks_price_gain():
    eng = PaperTradingEngine(config={"max_positions": 1, "initial_budget": 1_000_000})
    d1 = _mk_df({"A": 90}, price=100.0)
    eng.run_day(d1, date="2026-01-01", benchmark_close=50.0)
    nav1 = eng.ledger["daily_nav"][-1]["nav"]
    # 次日 A 漲 10% → NAV 應上升
    d2 = _mk_df({"A": 90}, price=110.0)
    rec2 = eng.run_day(d2, date="2026-01-02", benchmark_close=50.0)
    assert rec2["nav"] > nav1


def test_same_day_idempotent():
    eng = PaperTradingEngine(config={"max_positions": 2})
    df = _mk_df({"A": 90, "B": 80}, price=100.0)
    eng.run_day(df, date="2026-01-01", benchmark_close=50.0)
    n_trades = len(eng.ledger["trades"])
    eng.run_day(df, date="2026-01-01", benchmark_close=50.0)  # 同日重跑
    assert len(eng.ledger["trades"]) == n_trades  # 不重複下單


def test_metrics_and_alpha():
    eng = PaperTradingEngine(config={"max_positions": 1, "initial_budget": 1_000_000})
    # 三日：策略漲、基準也漲，計算 alpha/sharpe/mdd
    eng.run_day(_mk_df({"A": 90}, price=100.0), date="2026-01-01", benchmark_close=100.0)
    eng.run_day(_mk_df({"A": 90}, price=110.0), date="2026-01-02", benchmark_close=103.0)
    eng.run_day(_mk_df({"A": 90}, price=121.0), date="2026-01-03", benchmark_close=106.0)
    m = eng.equity_metrics()
    assert m["days"] == 3
    assert m["cum_return_pct"] is not None and m["cum_return_pct"] > 0
    assert m["max_drawdown_pct"] is not None
    assert m["alpha_pct"] is not None  # 策略約 +21% vs 基準 +6% → 正 alpha
    assert m["alpha_pct"] > 0


def test_roundtrip_serialization():
    eng = PaperTradingEngine(config={"max_positions": 2})
    eng.run_day(_mk_df({"A": 90, "B": 80}, price=100.0), date="2026-01-01", benchmark_close=50.0)
    import json
    s = json.dumps(eng.ledger, ensure_ascii=False, default=str)
    eng2 = PaperTradingEngine(ledger=json.loads(s))
    assert eng2.ledger["positions"].keys() == eng.ledger["positions"].keys()


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
            passed += 1
        except Exception:
            print(f"[FAIL] {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
