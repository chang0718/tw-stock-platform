# 台股分析平台 — 對話交接文件

> 最後更新：2026-05-26（Phase A-G 全面優化完成）
> 建立時間：2026-05-12  
> 用途：新對話繼續開發時的完整上下文

---

## 一、專案基本資訊

| 項目 | 內容 |
|------|------|
| 專案路徑 | `C:\投資\tw-stock-platform_20260511` |
| GitHub | https://github.com/chang0718/tw-stock-platform |
| Streamlit Cloud | https://tw-stock-platform-9zxud2zaqzb758nbcinhea.streamlit.app/ |
| 登入密碼 | scps6667 |
| Gmail | scps960810@gmail.com |
| 每日報告 | 週一至週五 14:30 自動寄信到 Gmail |
| 本機啟動 | 終端執行 `.\run.ps1`，或先 `.\.venv\Scripts\Activate.ps1` 再 `streamlit run app.py` |
| 本機網址 | http://localhost:8501 |
| 手機（同WiFi）| http://172.20.10.9:8501 |

---

## 零、本輪（2026-05-26）最新完成功能（尚未 git commit）

### 新增 Tab

| Tab | 功能 | 核心邏輯 |
|-----|------|---------|
| tabs[9] 🎯 潛力股 | 落後補漲候選排行 | `quant_model.find_catchup_candidates()` — peer_lag_score × 0.35 + flow_score × 0.30 + KD/MACD × 0.20 + inst_entry × 0.15 |
| tabs[10] 📈 ETF 排行 | ETF 月/季/年報酬率排行 | `finmind_loader.get_etf_performance()` |
| tabs[7] 📊 產業瀏覽器 | 重構為左右兩欄 | 左=供應鏈樹+概念股按鈕，右=儀表板+股票表+產業新聞 |

### Tab 0 — 新增「📡 本週市場熱點話題」expander

- `config.NEWS_TO_SUPPLY_CHAIN`（12 個話題→供應鏈族群映射）
- `news_analyzer.get_hot_topics()`（快取 2 小時）自動識別熱點話題並顯示受益族群

### Tab 3 — 個股分析強化

- **估值區間卡片**：`finmind_loader.get_eps_fair_value()` 顯示保守/合理/樂觀目標價（歷史 PE 25/50/75 分位 × trailing EPS）
- **操作四區間說明**：整合技術面 S/R + PE 分位 + EPS 公平價，顯示積極買進/分批介入/觀望持有/逢高出清四區間附中文理由

### 新增技術指標

- `tech_analyzer.calc_kd()` — KD 指標（FastRSV→K→D）
- `analyze()` 輸出新增 `kd_cross`、`k_val`、`d_val`

### 新增評分維度（`quant_model.enrich_dataframe()`）

- `peer_lag_score` — 族群平均動能 vs 個股動能差（越大越落後，補漲潛力越高）
- `inst_entry` — 外資淨買入但 flow_score < 60（籌碼面剛開始建倉）
- `macd_pre_cross` — MACD 柱狀圖負值收斂（黃金交叉前兆）

### ⚠️ 重要開發規則（本輪兩次 bug 的教訓）

**禁止在函式內部寫 `from X import Y`（尤其是 `main()` 內的 try 塊）**

原因：Python 函式作用域規則讓整個 `main()` 把該名稱視為局部變數，早於 import 的呼叫會觸發 `UnboundLocalError`。

驗證三步驟（每次修改後必跑）：
```powershell
python -m py_compile app.py && echo "語法 OK"
python -m pytest tests/ -q              # 應為 57 passed
grep -n "^from\|^import" app.py | head  # 確認無函式內 import
```

---

## 二、已完成事項

### 環境建置（SETUP_SOP.md 步驟 1-12）
- [x] Python 3.14.5 安裝並加入 PATH
- [x] Git 2.54.0 安裝
- [x] VS Code 1.119.0 + Python/Pylance 擴充套件
- [x] Node.js 24.15.0 + Claude Code CLI 2.1.138
- [x] Python 虛擬環境 `.venv` + 所有套件（streamlit 1.57.0、pandas 3.0.2 等）
- [x] 資料目錄確認（portfolio.json、watchlist.json、weights.json）
- [x] `.streamlit/secrets.toml` 建立（密碼、FinMind token 欄位）

### 雲端部署
- [x] GitHub 倉庫建立：chang0718/tw-stock-platform（Public）
- [x] Streamlit Cloud 部署完成，有密碼保護
- [x] Streamlit Cloud Secrets 設定（auth.password = scps6667）
- [x] GitHub Actions：每日 14:30 自動寄 Email 報告（Gmail App Password 已設定為 GitHub Secret）

### 程式碼修正
- [x] `app.py`：加入密碼保護登入頁（`_check_password()`）
- [x] `app.py`：`applymap` → `map`（pandas 3.x 相容）
- [x] `app.py`：移除 headless 限制，瀏覽器自動開啟
- [x] `app.py`：載入市場後自動累積每日收盤價到 `price_history.json`
- [x] `app.py`：None 收盤價顯示 `--`，不顯示假資料
- [x] `app.py`：持倉頁面 None close 不崩潰
- [x] `data_loader.py`：移除假資料預設值（`close=100, change_pct=0, volume=1000` → `None`）
- [x] `quant_model.py`：`enrich_company` 正確處理 None close
- [x] `quant_model.py`：技術指標計算加 None 防護
- [x] `scripts/daily_report.py`：改用 Gmail SMTP 寄信（原為 LINE Notify）
- [x] `.github/workflows/daily_report.yml`：觸發時間改為 14:30 台灣時間
- [x] `.streamlit/config.toml`：修正 CORS/XSRF 警告
- [x] `run.ps1`：新增終端快速啟動腳本
- [x] `USER_SOP.md`：使用說明與換機還原 SOP

---

## 三、待辦事項（新對話繼續）

### ✅ 已完成（2026-05-12）

- [x] **廢棄檔清理**：刪除未使用的 `financials.py`、`news.py`，更新 `pack.ps1`
- [x] **冷啟動腳本**：新增 `scripts/init_price_history.py`
- [x] **雙擊啟動**：新增 `start.bat`
- [x] **TOP5 每日報告**：新增 `scripts/run_model.py`，更新 `daily_report.yml`
- [x] **SSL 修正**：`utils.py` → `session.verify = False`（台灣政府 API 憑證缺少 Subject Key Identifier）
- [x] **行情 / 公司清單分離**：即使 TWSE 盤後 API 空白也能載入公司名稱
- [x] **`_probit` 修正**：移除不存在的 `math.erfinv`，改用 Acklam rational approximation
- [x] **pytest 測試**：`tests/test_quant_model.py` + `tests/test_data_loader.py`（52 tests 全過）
- [x] **docs/ 文件**：7 份系統文件（`docs/00` 到 `docs/06`）

### 🔴 高優先（影響使用體驗）

1. **git commit 尚未提交的 6 個檔案**：`app.py`, `config.py`, `finmind_loader.py`, `news_analyzer.py`, `quant_model.py`, `tech_analyzer.py`（共 +812/-324 行）

2. **收盤價仍可能為 N/A**
   - TWSE API 偶爾在非交易日或剛開盤時回傳空行情
   - **待辦**：平日盤後（14:30-15:30）載入全市場，確認收盤價正確顯示

### 🟡 中優先（功能改善）

3. **FinMind Token 設定**
   - `secrets.toml` 裡 `token = "your_finmind_token_here"` 尚未填入真實 token
   - 影響：台股基本面（月營收、季報、本益比）以 yfinance 備援，部分資料可能缺失
   - **待辦**：到 finmindtrade.com 免費註冊取得 token，填入 `.streamlit/secrets.toml` 和 Streamlit Cloud Secrets（Secret 名稱：`FINMIND_TOKEN`）

4. **GitHub Actions 需新增 FINMIND_TOKEN Secret（選用）**
   - `daily_report.yml` 已加入 `FINMIND_TOKEN` 環境變數
   - 若不設定則 Actions 改用 yfinance 備援，功能仍可運作

5. **資料準確度確認**
   - **待辦**：平日盤後實際測試，確認模型 TOP5、收盤價、基本面數字是否合理

### 🟢 低優先（長期改善）

6. **模型水泥股問題**：TOP5 仍可能被無基本面小股票佔據，需調整評分權重

7. **KD 批次計算限制**：`enrich_dataframe()` 中 `kd_cross` 預設 False，因為 `price_history` 只有 close（無 OHLCV）。真實 KD 只在 Tab 3 個股分析時計算。

8. **Tab 3 估值卡片**：目前用 trailing EPS，未來可加入分析師 forward EPS 估算

9. **Streamlit Cloud 資料持久化**：自選股、持倉在雲端重啟後消失，需外部儲存（Google Sheets、Supabase 等）

   **自選股儲存說明**：
   - **本機執行**：`tw_quant_data/watchlist.json` 持久存在磁碟，關閉平台後資料仍在
   - **Streamlit Cloud**：檔案系統為 ephemeral，每次重啟（約每 7 天或閒置後）`watchlist.json` 消失
   - `tw_quant_data/` 在 `.gitignore` 裡，不會上傳 GitHub，也不會從雲端同步回來
   - **解法**（未來）：改用 Google Sheets API 或 Supabase 儲存自選股清單

8. **美股資料錯誤**：yfinance 延遲 15 分鐘，部分美股指數資料有問題，需排查

---

## 四、關鍵檔案說明

| 檔案 | 說明 |
|------|------|
| `app.py` | 主程式（~2900 行），11-Tab UI 邏輯 |
| `quant_model.py` | 六因子量化模型（跨截面 Z-score） |
| `data_loader.py` | TWSE / TPEx 市場資料載入 |
| `finmind_loader.py` | FinMind API + yfinance 基本面（含 7 天快取） |
| `twse_institutional.py` | 三大法人、融資融券 |
| `signal_engine.py` | 買賣訊號生成 |
| `portfolio.py` | 持倉管理 |
| `tech_analyzer.py` | 技術指標（MA/RSI/MACD/KD/Bollinger/ATR/Fibonacci）|
| `news_analyzer.py` | 新聞爬取、情緒分析、熱點話題 |
| `config.py` | 供應鏈樹、概念股、ETF 清單、NEWS_TO_SUPPLY_CHAIN 映射 |
| `tw_quant_data/` | 個人資料（持倉、自選股、快照、歷史價格） |
| `.streamlit/secrets.toml` | 本機敏感設定（密碼、token）— 不上傳 GitHub |
| `run.ps1` | PowerShell 啟動腳本 |
| `start.bat` | 雙擊啟動腳本（不需開 PowerShell）|
| `scripts/init_price_history.py` | 冷啟動：批次下載前100大台股60天歷史 |
| `scripts/run_model.py` | GitHub Actions 用：執行模型生成快照 |
| `scripts/daily_report.py` | 每日報告寄信 |
| `SETUP_SOP.md` | 環境建置 SOP |
| `USER_SOP.md` | 使用說明與換機 SOP |

---

## 五、整合測試步驟

### 步驟 1 — 合併三個 PR（GitHub 上操作）
依序合併以下 PR（在 GitHub 上 Merge Pull Request）：
1. `feat/init-price-history` → 建立 PR: https://github.com/chang0718/tw-stock-platform/pull/new/feat/init-price-history
2. `feat/start-bat` → 建立 PR: https://github.com/chang0718/tw-stock-platform/pull/new/feat/start-bat
3. `feat/fix-daily-report-top5` → 建立 PR: https://github.com/chang0718/tw-stock-platform/pull/new/feat/fix-daily-report-top5

合併後執行 `git pull origin main` 拉到本機。

### 步驟 2 — 冷啟動歷史資料（本機執行一次）
```powershell
# 在專案目錄執行（約 3~5 分鐘）
.\run.ps1  # 先確認能正常啟動，再關閉
python scripts/init_price_history.py
```
完成後確認 `tw_quant_data/price_history.json` 存在且有資料。

### 步驟 3 — 確認模型分數差異
1. 執行 `.\run.ps1` 或雙擊 `start.bat` 啟動平台
2. 點「🌐 載入全市場」
3. 查看「量化候選清單」頁面 — 各股分數應有明顯差異（不再全是 50）

### 步驟 4 — 測試 start.bat
在 Windows 檔案總管中雙擊 `start.bat`，確認平台能自動啟動。

### 步驟 5 — 測試 Actions 自動報告（手動觸發）
1. 前往 GitHub → Actions → 「每日盤後分析報告」
2. 點「Run workflow」手動觸發
3. 觀察 logs：應能看到「Run quantitative model」步驟成功
4. 確認 Gmail 收到報告且 TOP5 有實際股票名稱（不再顯示「無快照資料」）

---

## 六、給新對話 Claude 的指令範本

```
請閱讀 HANDOFF.md 了解專案現況。
目前最需要解決的問題是：[描述問題]
```

---

## 七、GitHub Secrets（Actions 用）

| Secret 名稱 | 用途 |
|-------------|------|
| `GMAIL_USER` | scps960810@gmail.com |
| `GMAIL_APP_PASSWORD` | Gmail App 密碼（已設定，勿外洩）|
| `FINMIND_TOKEN` | FinMind API token（選用，未設定則用 yfinance 備援）|

## 八、虛擬環境說明

**為什麼一定要在虛擬環境（.venv）裡執行？**

Python 套件安裝在「全域」或「虛擬環境」是兩件事：

| | 全域 Python | 虛擬環境 .venv |
|--|--|--|
| 套件安裝位置 | 整台電腦共用 | 只在這個專案 |
| 版本衝突風險 | 高（A 專案要 pandas 2.0，B 專案要 pandas 1.5 → 衝突）| 無（各自隔離）|
| 刪除影響 | 影響所有專案 | 只影響此專案 |

本專案的 `streamlit`、`pandas 3.x`、`yfinance` 等套件都裝在 `.venv` 裡，
全域 Python 裡沒有，所以直接執行 `python` 或 `streamlit` 會找不到套件。

**解法（三擇一）：**
1. 雙擊 `start.bat`（最簡單，自動 activate）
2. 執行 `.\run.ps1`（PowerShell 版）
3. 手動啟動：`.\.venv\Scripts\Activate.ps1` 再 `streamlit run app.py`

## 九、注意事項

- `secrets.toml` 已在 `.gitignore`，不會上傳 GitHub
- 每次修改 code 後需 `git add . && git commit && git push`，Streamlit Cloud 才會自動更新
- `tw_quant_data/` 也在 `.gitignore`，price_history.json 只存在本機，需用 `init_price_history.py` 重建
