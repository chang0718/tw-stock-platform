# 紙上交易帳本（Paper Trading Ledger）

本目錄存放每日虛擬買賣的帳本 `ledger.json`，由 GitHub Actions
（`.github/workflows/daily_report.yml` → `scripts/paper_trading_daily.py`）每個交易日
盤後自動產生並 **commit 回存 repo**，以長期累積、評估量化模型的選股能力。

> 本目錄刻意放在 `data/`（已入庫）而非 `tw_quant_data/`（被 .gitignore 且雲端 ephemeral），
> 才能跨日持久化。

## ledger.json 結構

```json
{
  "config": {
    "initial_budget": 1000000, "max_positions": 5,
    "fee_bps": 14.25, "tax_bps": 30.0, "slippage_bps": 10.0,
    "risk_guard": 80.0, "news_guard": -0.5, "min_volume_lots": 0
  },
  "cash": 0,
  "benchmark_base": 0,
  "positions": {
    "2330": {"name": "...", "shares": 0, "cost_basis": 0, "buy_date": "YYYY-MM-DD",
             "entry_score": 0, "last_price": 0}
  },
  "trades": [
    {"date": "YYYY-MM-DD", "ticker": "..", "name": "..", "action": "BUY|SELL",
     "price": 0, "shares": 0, "amount": 0, "reason": "..",
     "entry_score": 0, "ret_pct": null}
  ],
  "daily_nav": [
    {"date": "YYYY-MM-DD", "nav": 0, "cash": 0, "pos_value": 0, "n_pos": 5,
     "benchmark_close": 0, "cum_return_pct": 0, "bench_return_pct": 0}
  ]
}
```

## 策略（v1）

- 維持固定 5 檔持倉、每日輪動：用 `QuantModel.compute_final_composite`（與 App 同一套
  計分）取合格前 5 名；掉出榜外或觸發 **風險/利空 guard**（`risk_score` 過高、新聞情緒
  過負）即賣出，補進新上榜者。
- 計入手續費 0.1425% + 賣出證交稅 0.3% + 滑價 0.1%，避免高估績效。
- 評估指標：累積/年化報酬、Sharpe、最大回撤、Alpha(vs 0050)、勝率、IC。

## 已知限制（v1 → v2）

- headless 每日job 無逐檔基本面/新聞 → 用「模型核心分」（無基本面品質/新聞 overlay）；
  TOP5 易被無基本面小型股佔據。可調 `config.min_volume_lots`（流動性門檻，單位：張）
  緩解，或 v2 接入逐檔基本面/新聞情緒。
- 歷史回測不代表未來報酬，僅供策略穩定性與風險特徵參考；非投資建議。
</content>
