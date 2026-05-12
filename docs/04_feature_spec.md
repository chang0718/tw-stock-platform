# 04 — 功能規格

## UI 頁面

| 頁面 | 說明 |
|------|------|
| 🏠 首頁 Dashboard | 市場概況、近期加入的自選股、量化 TOP5 快速瀏覽 |
| 🌐 載入全市場 | 呼叫 TWSE / TPEx API，顯示全市場行情表格 |
| 📊 量化候選清單 | 六因子評分表，可篩選產業、市場、分數門檻 |
| ⭐ 自選股 | 追蹤清單，顯示即時行情與模型分數 |
| 💼 持倉管理 | 成本、市值、損益計算，持倉比例圖 |
| 🔍 個股分析 | 輸入代號，顯示基本面、技術指標、籌碼、模型分析 |
| ⚙️ 設定 | 因子權重調整、FinMind token 輸入 |

## API 端點（config.py）

```python
API_ENDPOINTS = {
    "twse_company": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    "twse_daily":   "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
    "tpex_company": "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis",
    "tpex_daily":   "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
}
```

## 量化候選清單篩選條件（CANDIDATE_CRITERIA）

```python
CANDIDATE_CRITERIA = {
    "min_composite_score": 60,   # 綜合分數門檻
    "min_close":           10,   # 最低股價（元）
    "max_close":        10000,   # 最高股價（元）
    "exclude_groups":  ["ETF"],  # 排除 ETF
}
```

## 每日 Email 報告（GitHub Actions）

- **觸發時間**：週一至週五 UTC 06:30（台灣 14:30）
- **流程**：
  1. `run_model.py` → 載入市場 → 執行量化模型 → 存 `snapshots.json`
  2. `daily_report.py` → 讀 snapshots → 選 TOP5 → SMTP 寄信
- **Secrets**：`GMAIL_USER`、`GMAIL_APP_PASSWORD`、`FINMIND_TOKEN`（選用）

## 股票代碼驗證規則（validate_ticker）

- 長度：4-6 個字元
- 第一個字元必須是數字
- 例：`2330`（有效）、`00878`（有效，5 位）、`ABCD`（無效）、`1234567`（無效，7 位）
