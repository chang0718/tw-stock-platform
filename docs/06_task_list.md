# 06 — 任務清單

## 已完成

### 環境與基礎架構
- [x] Python 3.14.5 + venv + 所有套件
- [x] Streamlit Cloud 部署（含密碼保護）
- [x] GitHub Actions 每日報告（Gmail SMTP）
- [x] `start.bat` 雙擊啟動

### 資料載入修正
- [x] SSL 修正：`utils.py` → `verify=False`（台灣政府 API 憑證問題）
- [x] 分離公司清單與盤後行情：即使行情 API 空白也能載入公司名稱
- [x] 收盤價缺失時顯示 `--`，不顯示假值

### 量化模型
- [x] 六因子跨截面 Z-score 評分
- [x] `_probit` 改用 Acklam rational approximation（移除不存在的 `math.erfinv`）
- [x] `calculate_expected_return` 對數常態報酬公式

### 腳本
- [x] `scripts/init_price_history.py`：冷啟動批次下載 60 天歷史
- [x] `scripts/run_model.py`：GitHub Actions 用，mock streamlit 後執行模型
- [x] `scripts/daily_report.py`：Gmail 寄信

### 測試
- [x] `tests/test_quant_model.py`：52 tests，涵蓋所有關鍵公式
- [x] `tests/test_data_loader.py`：涵蓋 `parse_twse_daily` 與 `build_company_list`

### 文件
- [x] `docs/00_project_goal.md`
- [x] `docs/01_data_sources.md`
- [x] `docs/02_investment_policy.md`
- [x] `docs/03_system_architecture.md`
- [x] `docs/04_feature_spec.md`
- [x] `docs/05_risk_and_compliance.md`
- [x] `docs/06_task_list.md`（本文件）
- [x] `HANDOFF.md`：更新自選股儲存說明

---

## 待辦（優先順序）

### 🔴 高優先

1. **FinMind Token 填入**
   - 到 finmindtrade.com 註冊取得 token
   - 填入 `.streamlit/secrets.toml` 和 Streamlit Cloud Secrets
   - 影響：基本面數據品質（PE、EPS、月營收）

2. **平日盤後實測**
   - 確認收盤價正確載入（1000+ 筆）
   - 確認量化候選清單分數有差異（非全部 50）
   - 確認 TOP5 名單合理

### 🟡 中優先

3. **美股資料排查**
   - yfinance 美股指數資料部分有問題
   - 確認 `.TW` / `.TWO` 後綴正確性

4. **模型水泥股問題**
   - TOP5 偶被無基本面小股票佔據
   - 考慮加入最低流動性門檻篩選

### 🟢 低優先

5. **自選股雲端持久化**
   - 現況：本機 JSON 持久，Streamlit Cloud 重啟後消失
   - 選項：Google Sheets API、Supabase PostgreSQL
   - 成本：Google Sheets 免費；Supabase 免費 tier 500MB

6. **美股頁面**
   - yfinance S&P 500 成分股篩選
   - 同樣六因子評分架構

7. **回測功能**
   - 需歷史財報資料（FinMind 付費）
   - 注意 survivorship bias、交易成本
