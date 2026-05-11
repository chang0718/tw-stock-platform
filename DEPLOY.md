# 台股分析平台 — 部署指南

> 完成後可在 iPhone / Android 以「加入主畫面」方式使用，效果如 App

---

## 步驟一：建立 GitHub 倉庫

1. 開啟 https://github.com/new
2. Repository name: `tw-stock-platform`（或自訂）
3. 設定為 **Private**（保護你的設定）
4. 不要勾選任何初始化選項 → 按 **Create repository**

### 在本機初始化並推送：
```bash
cd d:\投資
git init
git add .
git commit -m "init: 台股分析平台"
git branch -M main
git remote add origin https://github.com/你的帳號/tw-stock-platform.git
git push -u origin main
```

> ⚠️ `tw_quant_data/` 已在 .gitignore 中排除（快取與個人持倉不會上傳）

---

## 步驟二：部署到 Streamlit Community Cloud（免費）

1. 開啟 https://share.streamlit.io
2. 用 GitHub 帳號登入
3. 按 **New app**
4. 選擇你的倉庫 `tw-stock-platform`，Branch: `main`，Main file: `app.py`
5. 按 **Deploy** → 等待 2-3 分鐘

### 設定 Secrets（API Key）：
部署完成後，進入 **App settings → Secrets**，貼上：
```toml
FINMIND_TOKEN = "你的FinMind Token"
LINE_NOTIFY_TOKEN = "你的LINE Notify Token"
```

---

## 步驟三：在 iPhone 加入主畫面（PWA）

1. 用 **Safari** 開啟你的 Streamlit 網址（格式：`https://xxx.streamlit.app`）
2. 點下方 **分享按鈕**（方形+箭頭圖示）
3. 選 **「加入主畫面」**
4. 命名為「台股分析」→ 按 **新增**
5. 從主畫面開啟 → 全螢幕顯示，如同 App

---

## 步驟四：設定 LINE Notify 每日推播

### 取得 LINE Notify Token：
1. 開啟 https://notify-bot.line.me/my/
2. 登入 LINE 帳號
3. 按 **「發行權杖」**
4. 選擇要推播的聊天室（或「1對1」）
5. 複製 Token

### 在 GitHub 設定 Secret：
1. 進入你的 GitHub 倉庫 → **Settings → Secrets and variables → Actions**
2. 按 **New repository secret**
3. Name: `LINE_NOTIFY_TOKEN`，Value: 貼上你的 Token
4. 按 **Add secret**

### 確認 GitHub Actions 已啟用：
- 進入倉庫 → **Actions** 分頁
- 若看到「Workflows aren't being run on this fork」提示，按 **Enable**
- 每個台灣時間下午 4:30（盤後），系統自動推播當日報告

### 手動測試推播：
進入 Actions → **「每日盤後分析推播」** → **Run workflow** → 確認 LINE 收到訊息

---

## 本機執行（開發測試）

```bash
cd d:\投資
pip install -r requirements.txt
streamlit run app.py
```

瀏覽器開啟 http://localhost:8501

---

## 費用說明

| 項目 | 費用 |
|------|------|
| Streamlit Community Cloud | **免費**（1個 public/private app） |
| GitHub | **免費**（私人倉庫） |
| GitHub Actions | **免費**（每月 2,000 分鐘） |
| LINE Notify | **免費** |
| TWSE 資料 API | **免費** |
| FinMind 基本方案 | **免費**（有限額） |
| yfinance | **免費** |

---

## 常見問題

**Q: Streamlit Cloud 部署後資料消失？**
A: `tw_quant_data/` 在 .gitignore 中，每次重啟會清空。建議在設定頁使用「備份/還原」功能。

**Q: FinMind 資料顯示失敗？**
A: 免費帳號有每日限額。在模型設定頁貼上 Token 後重新載入。

**Q: LINE 推播沒收到？**
A: 確認 Token 已加入 GitHub Secrets，且 Actions 已啟用。可手動觸發測試。

**Q: iPhone 版沒有全螢幕？**
A: 必須用 Safari 的「加入主畫面」功能，用其他瀏覽器無法全螢幕。
