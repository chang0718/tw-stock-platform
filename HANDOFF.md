# 台股分析平台 — 對話交接文件

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

### 🔴 高優先（影響使用體驗）

1. **分數差異問題（核心問題）**
   - 現狀：新安裝沒有 price_history.json → 動能/波動率因子全部 = 50（中性）→ 大多數股票分數雷同
   - 已修正：每次「載入市場」後自動累積今日收盤價，20 天後動能分數開始拉開差距
   - 追蹤清單的股票已可用 yfinance 基本面（PE、毛利率）做差異評分
   - **待辦**：開機後載入市場，確認分數是否有差異；若仍雷同，考慮從 yfinance 批次拉前 60 天歷史給前 100 大股票

2. **收盤價仍可能為 N/A**
   - 現狀：TWSE API 偶爾會回傳空行情（非交易日、剛開盤時）
   - **待辦**：測試在交易時間載入，確認收盤價是否正確顯示

3. **終端啟動體驗**
   - 現狀：需要先 activate venv 才能直接用 `streamlit run app.py`
   - **待辦**：考慮建立 `start.bat` 批次檔，讓使用者雙點擊就能啟動（不用開 PowerShell）

### 🟡 中優先（功能改善）

4. **FinMind Token 設定**
   - 現狀：secrets.toml 裡 `token = "your_finmind_token_here"` 尚未填入真實 token
   - 影響：台股基本面（月營收、季報、本益比）以 yfinance 備援，部分資料可能缺失
   - **待辦**：到 finmindtrade.com 免費註冊取得 token，填入 `.streamlit/secrets.toml` 和 Streamlit Cloud Secrets

5. **資料錯誤診斷**
   - 使用者反映「進去都是錯誤的數字跟資訊」
   - 已修正假資料問題，但需要在交易時間實際測試確認
   - **待辦**：平日盤後（14:30-15:30）載入全市場，截圖確認數字是否合理

6. **price_history.json 冷啟動問題（已確認要做）**
   - 現狀：第一次使用時無歷史資料，技術分數全為 50，分數幾乎無差異
   - **待辦**：新增 `scripts/init_price_history.py`，一次性從 yfinance 批次下載前 100 大台股的 60 天歷史收盤價，寫入 `tw_quant_data/price_history.json`
   - 執行後動能 / 波動率因子立即有真實資料，分數差距可明顯拉開
   - 腳本加間隔（每筆 0.5 秒）避免 yfinance rate limit

7. **TOP5 在每日報告中無資料**
   - 現狀：daily_report.py 讀取 `tw_quant_data/snapshots.json`，但 Streamlit Cloud 的儲存在重啟後消失
   - **待辦**：在平台點「保存快照」後，GitHub Actions 才能抓到 TOP5；或改為讓 Actions 自己跑模型（需要更多依賴）

### 🟢 低優先（長期改善）

8. **模型水泥股問題**：TOP5 仍可能被無基本面的小股票佔據，需進一步調整評分權重

9. **Streamlit Cloud 資料持久化**：自選股、持倉、快照在雲端重啟後消失，需要外部儲存（Google Sheets、Supabase 等）

10. **美股資料錯誤**：yfinance 延遲 15 分鐘，部分美股指數資料顯示有問題，需排查

---

## 四、關鍵檔案說明

| 檔案 | 說明 |
|------|------|
| `app.py` | 主程式（1900+ 行），所有 UI 邏輯 |
| `quant_model.py` | 六因子量化模型（跨截面 Z-score） |
| `data_loader.py` | TWSE / TPEx 市場資料載入 |
| `finmind_loader.py` | FinMind API + yfinance 基本面（含 7 天快取） |
| `twse_institutional.py` | 三大法人、融資融券 |
| `signal_engine.py` | 買賣訊號生成 |
| `portfolio.py` | 持倉管理 |
| `config.py` | 全域設定（因子權重、顯示欄位） |
| `tw_quant_data/` | 個人資料（持倉、自選股、快照、歷史價格） |
| `.streamlit/secrets.toml` | 本機敏感設定（密碼、token）— 不上傳 GitHub |
| `run.ps1` | 終端啟動腳本 |
| `SETUP_SOP.md` | 環境建置 SOP |
| `USER_SOP.md` | 使用說明與換機 SOP |

---

## 五、給新對話 Claude 的指令範本

```
請閱讀 HANDOFF.md 了解專案現況。
目前最需要解決的問題是：[描述問題]
```

---

## 六、GitHub Secrets（Actions 寄信用）

| Secret 名稱 | 用途 |
|-------------|------|
| `GMAIL_USER` | scps960810@gmail.com |
| `GMAIL_APP_PASSWORD` | Gmail App 密碼（已設定，勿外洩） |

## 七、注意事項

- `secrets.toml` 已在 `.gitignore`，不會上傳 GitHub
- 每次修改 code 後需 `git add . && git commit && git push`，Streamlit Cloud 才會自動更新
- 虛擬環境在 `.venv/`，每次開新 PowerShell 需先執行 `.\.venv\Scripts\Activate.ps1`
- `run.ps1` 會自動 activate 虛擬環境再啟動
