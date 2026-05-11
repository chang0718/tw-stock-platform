# 新電腦還原 SOP — 台股分析平台

> **給 Agent 的指令**：請依序執行本文件每個步驟，每步驟完成後輸出 `[DONE] 步驟X`，若失敗立即停止並回報錯誤。
> **預計總時間**：15–25 分鐘（視網速）

---

## 前置假設

- 作業系統：Windows 10 / 11
- 已將 ZIP 解壓到 `C:\投資\`（或自訂路徑，以下以 `PROJECT_DIR` 代稱）
- 有網路連線
- 有管理員權限（安裝軟體需要）

---

## 步驟 1：安裝 Python 3.11

```powershell
# 檢查是否已安裝
python --version
```

**若輸出 `Python 3.11.x` → 跳到步驟 2**

若未安裝，下載安裝：
```powershell
# 用 winget 安裝（Windows 10/11 內建）
winget install Python.Python.3.11 --silent

# 安裝完成後確認
python --version   # 應顯示 3.11.x
pip --version
```

> ⚠️ 若 winget 不可用：手動前往 https://www.python.org/downloads/ 下載 3.11.x
> 安裝時務必勾選 **"Add Python to PATH"**

---

## 步驟 2：安裝 Git

```powershell
git --version
```

**若有輸出 → 跳到步驟 3**

```powershell
winget install Git.Git --silent
# 重開 PowerShell 後確認
git --version
```

---

## 步驟 3：安裝 VS Code（可選，有 IDE 才需要）

```powershell
winget install Microsoft.VisualStudioCode --silent
```

### VS Code 擴充套件（安裝後在 VS Code 內執行，或用 CLI）：

```powershell
# Python 支援（必裝）
code --install-extension ms-python.python
code --install-extension ms-python.pylance

# 選裝：Git 視覺化、格式化
code --install-extension eamodio.gitlens
code --install-extension ms-python.black-formatter
```

---

## 步驟 4：安裝 Claude Code CLI（必裝，用於 AI 輔助開發）

```powershell
# 需先安裝 Node.js（Claude Code 的執行環境）
winget install OpenJS.NodeJS.LTS --silent

# 重開 PowerShell 後安裝 Claude Code
npm install -g @anthropic-ai/claude-code

# 確認
claude --version
```

---

## 步驟 5：進入專案目錄，安裝 Python 套件

```powershell
cd "C:\投資"   # 或你的實際解壓路徑

# 建立虛擬環境（建議，避免污染全域）
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 若 PowerShell 回報「執行原則限制」，先執行：
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# 安裝所有依賴
pip install -r requirements.txt

# 確認關鍵套件
python -c "import streamlit, pandas, numpy, plotly, requests, yfinance; print('ALL OK')"
```

---

## 步驟 6：還原資料目錄

```powershell
# 確認個人資料檔存在
Test-Path "tw_quant_data\portfolio.json"   # 應為 True（持倉）
Test-Path "tw_quant_data\watchlist.json"   # 應為 True（自選股）
Test-Path "tw_quant_data\weights.json"     # 應為 True（評分權重）
```

若上方有 False，從 ZIP 裡手動複製對應檔案到 `tw_quant_data\`。

---

## 步驟 7：設定 API Secrets（本機）

```powershell
# 複製範本
Copy-Item ".streamlit\secrets.toml.example" ".streamlit\secrets.toml"
```

用文字編輯器開啟 `.streamlit\secrets.toml`，填入：
```toml
[finmind]
token = "你的FinMind Token"   # 在 finmindtrade.com 登入後取得

[line]
notify_token = "你的LINE Token"   # 在 notify-bot.line.me/my/ 取得
```

> ⚠️ `secrets.toml` 已在 `.gitignore` 中，不會被 git 追蹤，**請勿上傳到 GitHub**

---

## 步驟 8：語法檢查（整合測試）

```powershell
$env:PYTHONIOENCODING = "utf-8"

$files = @("app.py","quant_model.py","finmind_loader.py","signal_engine.py",
           "portfolio.py","twse_institutional.py","news_analyzer.py",
           "scripts\daily_report.py")

$allOk = $true
foreach ($f in $files) {
    $result = python -c "import ast; ast.parse(open('$f', encoding='utf-8').read()); print('OK: $f')" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: $f — $result" -ForegroundColor Red
        $allOk = $false
    } else {
        Write-Host $result -ForegroundColor Green
    }
}
if ($allOk) { Write-Host "`n[PASS] 所有語法檢查通過" -ForegroundColor Cyan }
```

---

## 步驟 9：啟動平台（本機測試）

```powershell
cd "C:\投資"
.\.venv\Scripts\Activate.ps1   # 若使用虛擬環境
streamlit run app.py
```

瀏覽器自動開啟 `http://localhost:8501`

**驗收清單：**
- [ ] 首頁載入無錯誤
- [ ] 可輸入股票代號並載入資料
- [ ] 持倉管理頁看到 3017 奇鋐科技
- [ ] 自選股頁看到追蹤清單

---

## 步驟 10：設定 Git 並推送到 GitHub（部署用）

```powershell
cd "C:\投資"
git config --global user.email "scps960810@gmail.com"
git config --global user.name "你的名字"

git init
git add .
git commit -m "init: 台股分析平台還原"
git branch -M main

# 換成你的 GitHub 倉庫網址
git remote add origin https://github.com/你的帳號/tw-stock-platform.git
git push -u origin main
```

---

## 步驟 11：Streamlit Cloud 部署（手機用 PWA）

1. 前往 https://share.streamlit.io，用 GitHub 帳號登入
2. New app → 選倉庫 `tw-stock-platform` → Main file: `app.py` → Deploy
3. 部署完成後，在 App Settings → Secrets 貼入：
   ```toml
   [finmind]
   token = "你的FinMind Token"

   [line]
   notify_token = "你的LINE Token"
   ```
4. iPhone Safari 開啟網址 → 分享 → 加入主畫面

---

## 步驟 12：LINE Notify 自動推播設定

1. GitHub 倉庫 → Settings → Secrets and variables → Actions
2. New repository secret：`LINE_NOTIFY_TOKEN` = 你的 LINE Token
3. Actions 分頁確認 workflow 已啟用
4. 手動測試：Actions → 每日盤後分析報告 → Run workflow

---

## 環境版本對照表

| 軟體 | 需求版本 | 確認指令 |
|------|---------|---------|
| Python | 3.11.x | `python --version` |
| pip | 23.x+ | `pip --version` |
| Git | 2.x+ | `git --version` |
| Node.js | 18 LTS+ | `node --version` |
| Claude Code | 最新 | `claude --version` |
| streamlit | ≥1.32.0 | `pip show streamlit` |
| pandas | ≥2.0.0 | `pip show pandas` |
| yfinance | ≥0.2.40 | `pip show yfinance` |

---

## 尚未完成的待辦事項

> 以下項目需要手動操作（涉及帳號/Token/外部服務），無法由 Agent 自動完成：

| # | 項目 | 說明 | 優先度 |
|---|------|------|--------|
| 1 | **建立 GitHub 倉庫** | 在 github.com 新增 `tw-stock-platform` 私人倉庫 | 🔴 必要（部署前提） |
| 2 | **Streamlit Community Cloud 部署** | share.streamlit.io 連接 GitHub 倉庫並 Deploy | 🔴 必要（iPhone PWA 前提） |
| 3 | **FinMind Token 填入** | 在 secrets.toml 或 Streamlit Cloud Secrets 填入 Token | 🟡 基本面資料需要 |
| 4 | **LINE Notify Token 取得並設定** | notify-bot.line.me/my/ 取得後加入 GitHub Secrets | 🟡 每日推播需要 |
| 5 | **iPhone 加入主畫面** | Safari 開啟 Streamlit 網址 → 分享 → 加入主畫面 | 🟢 Streamlit 部署後操作 |
| 6 | **模型分數優化（水泥股問題）** | TOP5 仍被無基本面股票佔據；需進一步調整評分邏輯 | 🟡 功能改進（非阻塞） |

---

## 快速故障排除

| 問題 | 解法 |
|------|------|
| `streamlit: command not found` | 確認虛擬環境已啟動：`.\.venv\Scripts\Activate.ps1` |
| `ModuleNotFoundError: feedparser` | `pip install feedparser` |
| `UnicodeDecodeError` | 在 PowerShell 加 `$env:PYTHONIOENCODING="utf-8"` |
| FinMind 資料載入失敗 | 免費帳號有每日限額，等隔天或升級方案 |
| 三大法人資料顯示 N/A | TWSE API 假日不回傳，平日才有資料 |
| Streamlit Cloud 重啟資料消失 | 在設定頁匯出 JSON 備份，新機器還原時匯入 |
