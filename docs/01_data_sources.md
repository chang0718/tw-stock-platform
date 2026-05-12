# 01 — 資料來源說明

## 台股市場資料（免費，每日更新）

### TWSE 上市公司清單
- **端點**：`https://openapi.twse.com.tw/v1/opendata/t187ap03_L`
- **欄位**：公司代號、公司名稱、產業別
- **更新**：收盤後約 15:30

### TWSE 盤後行情（STOCK_DAY_ALL）
- **端點**：`https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL`
- **欄位**：Code、ClosingPrice、Change、TradeVolume
- **更新**：交易日收盤後約 15:30
- **注意**：非交易日 / 盤中查詢時回傳空陣列，屬正常現象

### TPEx 上櫃公司清單
- **端點**：`https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis`
- **欄位**：SecuritiesCompanyCode、CompanyName、IndustryCategory

### TPEx 盤後行情
- **端點**：`https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes`
- **格式**：JSON `data` 陣列，第 0 欄代號、第 2 欄收盤價

### SSL 憑證注意事項
台灣政府 API 憑證缺少 Subject Key Identifier 擴充，Python 3.12+ 拒絕連線。
已在 `utils.get_retry_session()` 設定 `verify=False` 並抑制警告。

---

## 基本面資料

### FinMind API（主要）
- **類型**：付費 / 免費限流
- **使用**：月營收、季報 EPS、本益比、股利
- **設定**：`.streamlit/secrets.toml` → `[finmind] token`
- **備援**：token 缺失或 API 超流量時改用 yfinance

### yfinance（備援）
- **類型**：免費（雅虎財經，延遲資料）
- **使用**：PE、EPS、股利殖利率
- **限制**：台股代號需加 `.TW` / `.TWO` 後綴

---

## 歷史價格

### 本機 price_history.json
- **路徑**：`tw_quant_data/price_history.json`
- **結構**：`{"2330": [{"date": "2026-05-01", "close": 1050.0}, ...]}`
- **來源**：每次「載入全市場」後自動累積最新收盤價
- **初始化**：`python scripts/init_price_history.py`（使用 yfinance 下載 60 天）

---

## 費用比較

| 來源 | 費用 | 延遲 | 資料完整性 |
|------|------|------|----------|
| TWSE / TPEx openapi | 免費 | 盤後 | 行情完整，無財報 |
| FinMind 免費版 | 免費（限流） | 當日 | 月營收、季報 |
| FinMind 付費版 | 月費 | 當日 | 完整財報、法人 |
| yfinance | 免費 | 15 分鐘延遲 | 部分基本面 |
