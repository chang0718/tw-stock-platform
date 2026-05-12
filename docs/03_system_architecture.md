# 03 — 系統架構

## 模組結構

```
tw-stock-platform/
├── app.py                  主程式（Streamlit UI，~1900 行）
├── quant_model.py          六因子量化模型
├── data_loader.py          TWSE / TPEx 市場資料載入
├── finmind_loader.py       FinMind + yfinance 基本面
├── twse_institutional.py   三大法人、融資融券
├── signal_engine.py        買賣訊號生成
├── portfolio.py            持倉管理
├── config.py               全域設定（權重、API 端點）
├── utils.py                HTTP / JSON / 驗證工具函數
├── scripts/
│   ├── init_price_history.py   冷啟動歷史資料
│   ├── run_model.py            GitHub Actions 量化快照
│   └── daily_report.py         每日 Email 報告
├── tests/
│   ├── test_quant_model.py     量化公式測試（52 tests）
│   └── test_data_loader.py     資料載入測試
├── tw_quant_data/          個人資料（.gitignore）
│   ├── portfolio.json      持倉
│   ├── watchlist.json      自選股
│   ├── weights.json        因子權重設定
│   ├── price_history.json  歷史收盤價快照
│   └── snapshots.json      量化模型快照
└── .github/workflows/
    └── daily_report.yml    GitHub Actions 排程
```

## 資料流

```
TWSE openapi ──┐
TPEx openapi ──┤→ data_loader.py → MarketDataLoader
               │
FinMind API ───┤→ finmind_loader.py → FinMindLoader
yfinance ──────┘

MarketDataLoader + FinMindLoader
    ↓
quant_model.py → QuantModel.enrich_dataframe()
    ↓
app.py → Streamlit UI（表格、圖表、篩選）
    ↓
tw_quant_data/*.json（本機持久化）
```

## 量化模型架構

### 六因子
| 因子 | 衡量指標 | 學術依據 |
|------|---------|--------|
| 價值 (value) | E/P（本益比倒數） | Fama & French (1992) |
| 品質 (quality) | 毛利率、淨利率、EPS | Novy-Marx (2013) |
| 成長 (growth) | 月營收 YoY、EPS 成長 | Earnings momentum |
| 動能 (momentum) | MA20 / MA60 乖離率 | Jegadeesh & Titman (1993) |
| 籌碼 (flow) | 法人淨買、融資變化 | Gompers & Metrick (2001) |
| 低波動 (low_vol) | 20 日波動率（反向） | Frazzini & Pedersen (2014) |

### 跨截面標準化
每個因子分數以同期全市場股票分布為基準：
`Z = (x - μ) / σ` → `score = Φ(Z) × 100`

樣本 < 5 支或 σ ≈ 0 時，回傳中性值 50。

### 期望報酬公式
`E[R] = σ_stock × Φ⁻¹(p20)` （對數常態假設）

其中 `p20` 為 20 日上漲機率，`σ_stock` 為歷史波動率。

## 資料庫現況

目前使用 JSON 檔案作為本機儲存，無獨立 DB。
Streamlit Cloud 部署時資料為 ephemeral（重啟即消失），
需 Google Sheets / Supabase 整合才能做雲端持久化。

## 關鍵設定檔

- `config.py`：API 端點、因子權重、產業映射
- `.streamlit/secrets.toml`：密碼、FinMind token（本機，不上傳）
- `.github/workflows/daily_report.yml`：Actions 排程與 Secrets 引用
