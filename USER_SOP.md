# 台股分析平台 — 使用 & 換機還原 SOP

> 本文件記錄平台所有關鍵資訊，換裝置或長時間未用時照此操作即可還原。

---

## 一、重要資訊速查

| 項目 | 內容 |
|------|------|
| 平台網址 | https://tw-stock-platform-9zxud2zaqzb758nbcinhea.streamlit.app/ |
| 登入密碼 | scps6667 |
| GitHub 倉庫 | https://github.com/chang0718/tw-stock-platform |
| GitHub 帳號 | chang0718 |
| Gmail | scps960810@gmail.com |
| 每日報告時間 | 台灣時間 週一至週五 14:30（自動寄到 Gmail） |

---

## 二、手機安裝（一次設定，永久使用）

### iPhone（Safari）
1. 用 **Safari**（不能用 Chrome）開啟平台網址
2. 輸入密碼登入，確認頁面正常
3. 點下方工具列中間的 **分享按鈕**（方框加向上箭頭）
4. 往下滑找到 **「加入主畫面」**
5. 名稱輸入「台股分析」→ 點右上角**新增**
6. 桌面出現圖示即完成，之後直接點圖示開啟

### Android（Chrome）
1. 用 **Chrome** 開啟平台網址並登入
2. 右上角三個點 → **「新增至主畫面」**
3. 點**新增**完成

> 安裝後像 App 一樣全螢幕開啟，不會顯示瀏覽器網址列。

---

## 三、平台功能說明

### 側邊欄功能
- **市場總覽**：載入全市場股票並跑量化評分模型
- **個股分析**：輸入股票代號查看基本面、技術面、新聞
- **追蹤清單**：自選股管理，可新增/刪除追蹤標的
- **持倉管理**：記錄買入價格與部位
- **美股概況**：S&P500、那斯達克、費城半導體、VIX 概覽
- **歷史回測**：測試策略歷史表現

### 重要操作
- **保存快照**：在市場總覽跑完模型後點「保存快照」，每日報告才有 TOP5 資料
- **匯出資料**：持倉與自選股可在設定頁匯出 JSON，換機時用來還原

---

## 四、每日自動報告

- **觸發時間**：週一至週五 台灣時間 14:30（收盤後）
- **寄件來源**：scps960810@gmail.com（自己寄給自己）
- **內容**：美股昨收概況、模型 TOP5、持倉摘要
- **手動觸發測試**：
  1. 開啟 https://github.com/chang0718/tw-stock-platform/actions
  2. 點「每日盤後分析報告」→ 右側 **Run workflow**

---

## 五、換新裝置還原 SOP

> 換電腦或重灌系統後，照以下步驟還原完整開發環境。

### 必要帳號（先確認能登入）
- [ ] GitHub：github.com，帳號 chang0718
- [ ] Gmail：scps960810@gmail.com
- [ ] Streamlit Cloud：share.streamlit.io（用 GitHub 登入）

### 步驟 1：安裝基本環境

```powershell
# 安裝 Python 3.11+
winget install Python.Python.3.11 --silent

# 安裝 Git
winget install Git.Git --silent

# 安裝 Node.js（Claude Code 需要）
winget install OpenJS.NodeJS.LTS --silent
```

### 步驟 2：下載專案

```powershell
cd C:\投資
git clone https://github.com/chang0718/tw-stock-platform.git tw-stock-platform_YYYYMMDD
cd tw-stock-platform_YYYYMMDD
```

### 步驟 3：安裝套件

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 驗證
python -c "import streamlit, pandas, numpy, plotly, requests, yfinance; print('ALL OK')"
```

### 步驟 4：還原個人資料

若有舊機器，先從舊機器匯出：
- `tw_quant_data\portfolio.json`（持倉）
- `tw_quant_data\watchlist.json`（自選股）
- `tw_quant_data\weights.json`（評分權重）

複製到新機器的 `tw_quant_data\` 資料夾。

### 步驟 5：設定 Secrets

```powershell
Copy-Item ".streamlit\secrets.toml.example" ".streamlit\secrets.toml"
```

用文字編輯器開啟 `.streamlit\secrets.toml`，填入：

```toml
[auth]
password = "scps6667"

[finmind]
token = "your_finmind_token_here"
```

### 步驟 6：本機測試

```powershell
cd C:\投資\tw-stock-platform_YYYYMMDD
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

瀏覽器開啟 http://localhost:8501，輸入密碼確認正常。

### 步驟 7：確認 Streamlit Cloud 與 GitHub Actions 仍正常

- 平台網址仍可正常開啟：https://tw-stock-platform-9zxud2zaqzb758nbcinhea.streamlit.app/
- GitHub Actions 每日報告仍在運作（查看 Actions 分頁）

> Streamlit Cloud 與 GitHub Actions 在雲端自動運作，換電腦不影響。

---

## 六、GitHub Secrets 備份（Actions 寄信用）

若 GitHub Secrets 遺失（如刪除倉庫重建），需重新設定：

1. 開啟 https://github.com/chang0718/tw-stock-platform/settings/secrets/actions
2. 新增以下兩筆：

| Secret 名稱 | 值 |
|-------------|-----|
| `GMAIL_USER` | scps960810@gmail.com |
| `GMAIL_APP_PASSWORD` | （Gmail App 密碼，需重新產生） |

> Gmail App 密碼產生位置：myaccount.google.com/apppasswords

---

## 七、Streamlit Cloud Secrets 備份

若 Streamlit Cloud 需要重新部署：

1. 開啟 share.streamlit.io → 選 app → Manage app → Settings → Secrets
2. 貼入：

```toml
[auth]
password = "scps6667"

[finmind]
token = "your_finmind_token_here"
```

---

## 八、常見問題

| 問題 | 解法 |
|------|------|
| 平台打不開 | 確認網址正確；Streamlit Cloud 免費版閒置會休眠，開啟後等 30 秒自動喚醒 |
| 密碼忘了 | 看本文件第一節或 `.streamlit/secrets.toml` |
| 每日報告沒收到 | 確認當天是週一至週五；到 GitHub Actions 手動觸發測試 |
| 資料顯示錯誤 | 多數為 API 限額或假日無資料，隔天再試 |
| 換電腦後自選股消失 | 從舊機器備份 `tw_quant_data\watchlist.json` 複製過來 |
