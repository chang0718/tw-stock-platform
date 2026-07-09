# 台股分析平台 — 對話交接文件

> 最後更新：2026-07-09（大戶／外資籌碼水位免費資料 + 法人快取防呆；前一輪：模型 F1~F6 + 紙上交易選股池 + 前瞻推估）
> 用途：新對話繼續開發時的完整上下文

---

## 一、專案基本資訊

| 項目 | 內容 |
|------|------|
| 專案路徑 | `C:\投資\tw-stock-platform_20260511` |
| GitHub | https://github.com/chang0718/tw-stock-platform |
| Streamlit Cloud | https://tw-stock-platform-9zxud2zaqzb758nbcinhea.streamlit.app/ |
| 登入密碼 | 見 `.streamlit/secrets.toml` 的 `[auth] password`（請勿寫入文件）|
| 本機開發繞過登入 | 設定環境變數 `LOCAL_DEV=1` |
| 本機啟動 | 終端執行 `.\run.ps1` 或 `streamlit run app.py` |
| 本機網址 | http://localhost:8501 |

---

## 二、目前平台架構（5 個 Tab，Phase 2 完成後）

`st.tabs` 定義於 app.py 第 3361 行，各 Tab 內容以閉包函式實作（`def _render_tab_XXX():` 位於 main() 內部）：

```
tabs[0] 🎯 候選篩選      — 子 Tab：🏆 綜合推薦 + 🎯 潛力股
tabs[1] 🌍 情勢雷達      — 美股連動 + 宏觀指標 + 13F
tabs[2] 🔍 個股研究      — 子 Tab：📊基本面 + 📈技術面 + 🏦籌碼 + 💬新聞/操作
tabs[3] 🔥 主題供應鏈    — 子 Tab：🔥 熱度排行 + 📊 產業瀏覽器
tabs[4] ⭐ 追蹤與組合    — 子 Tab：⭐追蹤清單 + 💼持倉管理 + 📈ETF排行 + 📊紙上交易 + ⚙️模型設定
```

### 閉包函式對應表（全部在 main() 內定義，起始約行）

| 閉包函式 | 舊 Tab | 內容摘要 |
|---------|--------|---------|
| `_render_tab_overall()` | 舊 tabs[0] | Top 10 推薦 + 熱點話題 + 資金流向 + 候選清單 |
| `_render_tab_us_market()` | 舊 tabs[1] | 美股指數 + ADR + 宏觀 + 13F |
| `_render_tab_stock_analysis()` | 舊 tabs[2] | 個股研究 4 子 Tab（基本面/技術/籌碼/新聞）|
| `_render_tab_portfolio()` | 舊 tabs[3] | 持倉管理 |
| `_render_tab_watchlist()` | 舊 tabs[4] | 追蹤清單 4 子 Tab（基本面籌碼/技術/估值/筆記）|
| `_render_tab_heat()` | 舊 tabs[5] | 產業熱度排行 |
| `_render_tab_industry()` | 舊 tabs[6] | 產業/概念股瀏覽器 |
| `_render_tab_settings()` | 舊 tabs[7] | 模型設定 + 備份還原 |
| `_render_tab_potential()` | 舊 tabs[8] | 潛力補漲候選 + EPS 超越排行 |
| `_render_tab_etf()` | 舊 tabs[9] | ETF 績效排行 |

### tabs[2]「個股研究」的子 Tab（`_stabs`）
| 子 Tab | 內容 |
|--------|------|
| 📊 基本面 | 🏥健檢雷達圖（四維 0-100）+ 8指標 + 白話解讀 + 月營收/季EPS + PE/PB歷史分位 + EPS公平價 |
| 📈 技術面 | K線圖（MA+布林）+ RSI/MACD + 購買信心指數 + 蒙地卡羅GBM + 支撐壓力 + 費波那契 |
| 🏦 籌碼 | 今日三大法人 + 融資融券 + 20日歷史趨勢（需FinMind Token）|
| 💬 新聞/操作 | 新聞情緒 + 個人筆記 + 即時信號彙整 |

### tabs[4]「追蹤與組合」→ ⭐追蹤清單 子 Tab（`_wl_stabs`）
| 子 Tab | 內容 |
|--------|------|
| 📊 基本面/籌碼 | 健檢雷達圖 + 基本面 + 籌碼 + 續抱評估 |
| 📈 技術面 | K線 + 操作區間 + 蒙地卡羅 + 購買信心指數 |
| ⚖️ 估值/操作 | PE/PB/殖利率歷史分位 + EPS公平價 |
| 💬 新聞/筆記 | 新聞情緒 + 個人研究筆記 |

---

## 三、核心 Python 模組（共 21 個）

### 主程式與架構層

| 模組 | 行數 | 功能 |
|------|------|------|
| `app.py` | 3,600+ | Streamlit 主程式（5 個 Tab，閉包方案）— render 函式已移至 components/ |
| `state.py` | ~55 | 全域 session_state 初始化（從 app.py 抽離）|
| `radar_loader.py` | ~220 | RadarLoader：整合事件日程 + 主題熱度 + 宏觀快照 |
| `paper_trading.py` | ~260 | PaperTradingEngine：每日虛擬買賣（5 檔輪動）+ 學術級指標（Sharpe/MDD/Alpha/IC）|
| `etf_loader.py` | ~150 | ETF 持股 CSV 解析 + 日期快照 + 持股重疊比對（v1）|
| `forecast.py` | ~380 | 前瞻推估引擎（純函式、不連網）：`build_forward_estimates()` 本年/次年營收EPS估 + Forward P/E（模型 run-rate 外推，非分析師共識）|
| `tdcc_loader.py` | ~150 | 集保 TDCC 股權分散：`get_major_holders()` 大戶(≥400/≥1000張)持股比例（免費、每週、逐週累積快照）|

### 元件層（components/）— 2026-06-08 新建

| 模組 | 功能 |
|------|------|
| `components/fundamental_blocks.py` | `render_fundamental_block()` + `render_health_check_block()` |
| `components/technical_blocks.py` | `render_tech_block()` |
| `components/flow_blocks.py` | `render_flow_block()` |
| `components/news_blocks.py` | `render_news_block()` |
| `components/radar_blocks.py` | `render_theme_cards()` + `render_event_calendar()` + `render_macro_bar()` |

### 服務層（services/）— 2026-06-08 新建

| 模組 | 功能 |
|------|------|
| `services/persistence_service.py` | `validate_backup()` + `preview_backup()` + `restore_backup()`（schema 驗證 + atomic 寫入）|

### 資料與分析模組（維持不動）

| 模組 | 行數 | 功能 |
|------|------|------|
| `quant_model.py` | 788 | 六因子跨截面 Z-score 量化評分 + `health_check_score()` + `monte_carlo_price()` + `find_catchup_candidates()` + `top_by_group()` |
| `finmind_loader.py` | 690 | yfinance 主力 + FinMind 補月營收 + `get_financial_trend()` + `get_revenue_trend()` + `get_per_trend()` + `get_valuation_percentile()` + `get_eps_fair_value()` + `get_eps_breakout()` |
| `tech_analyzer.py` | 397 | 技術分析（ATR/布林/支撐壓力/費波那契/KD/MACD/RSI）|
| `news_analyzer.py` | 566 | RSS 新聞 + `get_hot_topics()` + `get_theme_heat()` + `get_fund_flow_signals()` |
| `signal_engine.py` | 171 | 買賣訊號（支援 `fund_data=` 參數覆蓋快照）|
| `twse_institutional.py` | 235 | TWSE 三大法人（並行載入，硬性 12 秒超時保護）|
| `backtest.py` | 571 | 回測 + `bootstrap_model_confidence()` |
| `config.py` | 372 | 常數：SUPPLY_CHAIN_TREE / SUPPLY_CHAIN_GROUPS / CONCEPT_STOCKS / PRICE_THEMES / NEWS_TO_SUPPLY_CHAIN |
| `portfolio.py` | 132 | 持倉管理（add/remove/calculate_pnl）|
| `us_market.py` | 471 | 美股資料 + US_TW_SUPPLY_CHAIN + TW_INDUSTRY_CHAIN + US_INDICES + US_KEY_STOCKS |
| `utils.py` | ~330 | 共用工具（format_percentage / read_json / write_json[atomic] / clamp / sigmoid / to_number）|
| `data_loader.py` | 421 | MarketDataLoader — TWSE/TPEx OpenAPI 統一載入介面 |
| `macro_loader.py` | 232 | MacroLoader — 宏觀指標（FED、美債、DXY 等）|
| `institutional_tracker.py` | 165 | InstitutionalTracker + TRACKED_FUNDS（13F 機構持倉追蹤）|

---

## 四、關鍵 render 函式（已移至 components/）

⚠️ 這些函式已從 app.py 抽離至 components/，app.py 頂部以 import 引用：

| 函式 | 位置 | 功能 |
|------|------|------|
| `render_health_check_block(fund, fin_trend, val_pct, epsfv, compact=False)` | `components/fundamental_blocks.py` | 四維健檢（總評橫幅 + 進度條 + 雷達圖 + 明細術語解說）|
| `render_fundamental_block(fund)` | `components/fundamental_blocks.py` | 8指標 metric + 白話解讀 |
| `render_flow_block(stock, show_reload=False)` | `components/flow_blocks.py` | 三大法人今日 + 融資券（單位：張）|
| `render_tech_block(ta, stock)` | `components/technical_blocks.py` | K線四合一 subplot + 購買信心指數 + 支撐壓力 + 費波那契 |
| `render_news_block(news_dict)` | `components/news_blocks.py` | 新聞情緒 + 新聞列表 |
| `render_sidebar(universe_df)` | `app.py`（保留）| 側邊欄篩選條件（依賴 load_market_data_action，暫不抽離）|

---

## 五、模型計算核心邏輯（app.py 第 1025~1101 行）

```python
model_df["final_composite"] = (
    model_df["prob20"]           * 0.40   # 20日上漲機率
    + model_df["confidence"]     * 0.25   # 模型信心度
    + (100 - model_df["risk_score"]) * 0.20  # 風險反轉
    + model_df["composite_score"] * 0.15   # 六因子加權分
    + group_boost_series                   # 偏好產業 +4 分
    + completeness_bonus_series            # 真實數據 +3 分
    + news_adj_series                      # 新聞情緒 ±5 分
    + fund_quality_series                  # 基本面品質 +0~+12 分
)
```

**基本面品質加成規則（最高 +12）：**
- EPS YoY > 30%：+4；> 15%：+2.5；> 0%：+1
- 營收 YoY > 20%：+3；> 5%：+1.5
- 毛利率 > 40%：+2.5；> 25%：+1
- 淨利率 > 10%：+2.5

---

## 六、FinMindLoader 關鍵實作細節

- **EPS**：近四季合計（TTM），非最新單季
- **EPS YoY**：TTM now vs TTM prev（日期比對，非位置索引）
- **月營收 YoY/MoM**：日期比對（避免缺月誤差）
- **yfinance 優先**：主力基本面用 Yahoo Finance，補 FinMind 月營收（YoY/MoM）
- **快取 TTL**：7 天（finmind_cache.json）

---

## 六-B、data/ 目錄（Phase 3 新增）

JSON 配置來源：`C:\TaiwanTechNewsMonitor\config\`（人工同步，不自動更新）

| 檔案 | 內容 | 主要用途 |
|------|------|---------|
| `supply_chains.json` | 9 條供應鏈，含上/中/下游節點 + 台股 ticker | THEME_GRAPH drill-down |
| `events.json` | 11 類全球事件 + 傳導方向 | 事件日程分類 |
| `event_to_supply_chain_rules.json` | 10 條傳導規則 | 事件→受影響供應鏈 |
| `future_events.json` | 22 個種子事件 + 5 個時間窗口 | 未來事件日程 |
| `future_event_sources.json` | 28 個官方來源（Fed/BLS/Apple/TSMC 等）| 事件來源追蹤 |
| `concepts.json` | AI伺服器、先進封裝等垂直分類 + 子產業 + 台股 | 概念股詳細展開 |

---

## 七、資料快取機制

| 快取 | 位置 | TTL |
|------|------|-----|
| FinMind 基本面/月營收/季報 | `tw_quant_data/finmind_cache.json` | 7 天 |
| 新聞情緒 | `tw_quant_data/news_cache.json` | 1 小時 |
| 三大法人/融資券 | `tw_quant_data/institutional_cache.json` | 1 天 |
| 技術分析 OHLCV | `tw_quant_data/finmind_cache.json` 內 | 1 天 |
| 本機價格歷史 | `tw_quant_data/price_history.json` | 每日累積（保留 300 天）|
| 市場行情 | `tw_quant_data/market_cache.json` | 當日 |
| Streamlit session | `st.session_state` | 重啟清除 |

---

## 八、Git 狀態（截至 2026-06-08）

- **目前分支**：main
- **領先 origin/main**：15 個 commit（尚未 push 至 GitHub）
- **Modified（未暫存）**：app.py, utils.py, HANDOFF.md
- **Untracked（新增，待 commit）**：state.py, components/, services/
- **Untracked（不應 commit）**：`.claude/settings.json`

最近 commit：
1. `4e0211c` feat: Tab 5 追蹤清單加入四子 Tab（技術面/估值/新聞筆記）
2. `ecd3cd9` fix: 三項 UI/邏輯問題修正
3. `3209772` feat: 個股健檢儀表板 + Top 10 基本面品質加成

### 本次對話（2026-06-08）未提交變更摘要

| 類型 | 檔案 | 說明 |
|------|------|------|
| 修改 | `app.py` | 登入繞過修復 + 5個 render 函式移除 + import 新增 + 備份還原升級 |
| 修改 | `utils.py` | `write_json` 改為 atomic 寫入（.tmp + os.replace）|
| 修改 | `HANDOFF.md` | 移除密碼/Gmail + 更新架構 |
| 新建 | `state.py` | 全域 session_state 初始化 |
| 新建 | `components/__init__.py` | package 入口 |
| 新建 | `components/fundamental_blocks.py` | 基本面 + 健檢 render |
| 新建 | `components/technical_blocks.py` | 技術分析 render |
| 新建 | `components/flow_blocks.py` | 籌碼 render |
| 新建 | `components/news_blocks.py` | 新聞情緒 render |
| 新建 | `services/__init__.py` | package 入口 |
| 新建 | `services/persistence_service.py` | 備份還原 schema 驗證 + atomic 寫入 |
| 移動 | `scripts/archive/merge_tabs.py` | 危險腳本封存 |
| 移動 | `scripts/archive/refactor_tab3.py` | 危險腳本封存 |

### 本次對話（2026-06-11）資料準確性修正

**A. 三大法人/成交量數字錯誤（3 個 bug，已驗證修復）**

| # | 檔案 | 問題 | 修正 |
|---|------|------|------|
| 1 | `twse_institutional.py` | T86/MI_MARGN 的 date 參數送「民國 7 碼」(`_roc`)，API 實際要「西元 8 碼」→ 法人資料整條 TWSE 路徑長期失敗，只能靠需 token 的 FinMind 備援 | date 改 `dt.strftime("%Y%m%d")` |
| 2 | `twse_institutional.py` | T86 回傳單位為「股」，但全平台顯示/門檻皆以「張(千股)」為準 → 買賣超數字放大 1000 倍 | loader 源頭 `round(值/1000)`（TWSE + FinMind 兩路徑）|
| 3 | `data_loader.py` | 成交量同為「股」卻標示「張」→ 放大 1000 倍 | `parse_twse_daily` / `fetch_tpex_daily` 改 `int(volume // 1000)` |

- 欄位比對：T86 實際欄位名為「外陸資買賣超股數(不含外資自營商)」等，舊程式找「(千股)」找不到、靠 hard-code index 僥倖正確；已把真實欄位名加入 `idx()` 候選清單。
- 驗證：2330（2026-06-10）外資 -15,543 張、投信 -4、自營 -731、合計 -16,278 張，= 原始 API 股數 ÷1000，正確。
- 影響範圍：`flow_blocks`(張)、`app.py`(千股)、`signal_engine`(門檻 500/200 千股)、`news_analyzer`(inst_flow_k 千張) 全部一次校正；因 quant_model 只用跨截面排名，評分結果不變。
- ⚠️ 待查：`MI_MARGN` 融資融券為巢狀結構（頂層 `fields=None`），單位（張）未變動，但解析穩定性需另行驗證。

**B. 供應鏈/概念股分類校正（`config.py`）**

- 移除全部 `待確認` 代號；錯置者歸位：8213 志超→PCB、6269 台郡→PCB、3406 玉晶光→光學鏡頭、3533 嘉澤/3665 貿聯→連接器、3532 台勝科→半導體材料、1533 車王電→電動車。
- 重建純淨的「半導體材料/光學鏡頭/醫療器材/儲能太陽能」群組（移除 6285 啟碁、6244 茂迪、4174 浩鼎等錯置）。
- 原則：只保留高把握代號，寧缺勿錯（符合 CLAUDE.md 反捏造規範）。

**C. 族群清單顯示個股法人張數 + 擴充偏少群組（app.py + config.py）**

- **起因**：使用者用 Yahoo 對照「被動元件」族群覺得對不上。實測官方 T86（6/10）證實**平台數字正確**（國巨 -6,206 張 = Yahoo），問題在呈現。
- **app.py（產業瀏覽器族群清單）**：
  - 「籌碼」欄從只有燈號 → 改「燈號 + 帶色外資張數」（如 `🔴 -6,206`），可直接與 Yahoo/玩股網核對。`.sc-sig` 欄寬 60→108px。
  - 「外資合計」改名「外資合計(全族群)」+ 加 help/caption 標明是**全族群加總、非單一個股**（避免再被誤讀）。
  - 成交量 `int(vol/10000)萬` → `f"{vol/10000:.1f}萬"`，修正小量股顯示「0萬」。
- **config.py 群組擴充（新增代號全經官方 STOCK_DAY_ALL 清單逐一覆核名稱）**：
  - 修兩個既有錯誤：**8249** 官方為「菱光」非雲豹能源（移除）；**6770** 為「力積電(晶圓代工)」非立積——立積實為 **4968**（已歸位）。
  - 移除下市 **2456 奇力新**（併入國巨）。
  - 擴充：被動元件(2→6)、晶圓代工(+6770)、IC設計(+4968/5269)、電源管理(+8081/3588)、電動車(+1536/1521/6605)、儲能太陽能(+6443)、散裝航運(+2637)、醫療器材(+1786)、機器人(+4540/1597)。
  - 排除查證為下市/上櫃無法當場驗證者：3514昱晶(下市)、6244茂迪/4735豪展/6138茂達(上櫃未驗)。

**D. 上櫃（TPEx）資料來源修復（data_loader.py + config.py）**

- **問題**：櫃買中心網站改版後，舊端點 `tpex_mainboard_companies`（公司清單）與 `mops_api_qry`（tpex_daily）皆回傳 HTML → **上櫃股票長期完全載入失敗**（許多上櫃股顯示「未在市場資料中」）。
- **修復**：改用單一穩定端點 `tpex_mainboard_daily_close_quotes`（JSON，含代號＋名稱＋收盤＋成交股數，免 token、無日期參數）。`data_loader.py` 新增 `_fetch_tpex_raw()` 共用快取，`fetch_tpex_companies` / `fetch_tpex_daily` 由其派生。成交股數同樣 ÷1000 轉「張」。
- **驗證**：成功載入 886 檔上櫃公司＋行情；世界先進(5347)/茂達(6138)/精華(1565)/中美晶(5483)/環球晶(6488)/家登(3680) 均正常。
- 注意：daily_close_quotes 無產業別欄位，上櫃股產業別暫帶「其他」（供應鏈分組由 config 代號清單決定，不受影響）。

**E. 個股追蹤/分析強化：完整三率＋財報摘要＋同業比較（合規長期版）**

- **finmind_loader.py**：新增**營業利益率**（`OperatingIncome/Revenue`）；並修正既有 bug——淨利率原用 `NetIncome` 鍵（FinMind 無此鍵、恆為 None），改為 `IncomeAfterTaxes`（稅後淨利）。`_finmind_fundamental` 與 `get_financial_trend` 皆已補。以光寶科 2301 驗證：毛利 21.66/營益 9.44/淨利 8.7%、EPS(TTM) 6.8，與法說會數據相符。
- **components/fundamental_blocks.py**：新增三個可重用 render——
  - `render_earnings_summary(fund, val_pct)`：財報重點摘要（三率＋EPS TTM/YoY＋月營收動能＋估值分位）。
  - `render_three_rates(fin_trend)`：三率近 8 季趨勢圖。
  - `render_peer_comparison(target, model_df, key_prefix)`：同業比較表，radio 可切換**供應鏈群組／產業別**，target 個股底色標示，僅用 model_df 既有欄位（無額外 API）。
  - `render_fundamental_block` 指標區重組為三率並列＋補營益率與白話解讀。
- **app.py**：追蹤頁與個股分析頁基本面子頁皆接入上述三區塊；個股分析季報圖/表補營益率與淨利率。
- **tech_analyzer.py**：analysis dict 新增 `vol_ratio`（量/20日均量）；兩頁「操作價格區間」底部加**量能狀態**說明（定位為布局時機脈絡，非追價訊號）。
- **合規**：刻意不實作「今天/明後天該不該進、抄底點、追進勝率」等短線擇時；支撐壓力/量能一律以「分批布局＋止損＋再檢查」框架呈現（符合 CLAUDE.md）。

**F. 上線後回報問題修正（5 項）**

1. **個股分析頁崩潰**（`ValueError: Unknown format code 'f' for object of type 'str'`，app.py:1372）：季報表第二個格式化迴圈以「含 %」篩欄位，未排除新加的「營益率%」→ 已被第一迴圈轉成字串又被 `:+.1f` 套用而崩潰。修正：排除清單補上「營益率%」。
2. **美光大漲卻顯示利空**（us_market.py）：方向判斷正確，但 yfinance 免費日K結算時點導致抓到前一交易日（-1.4% vs 實際 +10.84%）。修正：影響文字標註美股收盤日期、「今日」改「下一個交易日」（台股實際隔日反應），使時點透明、避免誤導。yfinance 即時值無法在本機環境重現（沙箱抓 MU 失敗）。
3. **edgartools 提示**（app.py:1024）：非 bug，為 SEC 13F 選用功能。warning 改為 info 並標明「選用功能、不影響其他功能」。
4. **供應鏈缺群組**（config.py）：新增 **ABF載板**(3037/8046/3189)、**PCB材料 CCL/銅箔/鑽針**(2383台光電/6213聯茂/8021尖點)、**測試介面 探針卡**(6515穎崴/2449京元)，並掛入 SUPPLY_CHAIN_TREE。新增代號均經官方上市清單覆核；台燿6274/金居8358/精測6510/旺矽6223/雍智5251（多上櫃）因 TPEx SSL 暫無法驗，先不加。

**G. 主流 ETF 成分股顯示（v1，2026-06-16）**

- **背景**：台灣 ETF 全成分股無免費 API（FinMind 無、TWSE openapi 僅受益人數排行 `/ETFReport/ETFRank`、yfinance 收錄不全）。v1 採**匯入發行商持股 CSV**為主，最可靠零捏造。
- **新檔 `etf_loader.py`**：`parse_holdings_csv`（容錯欄名＋編碼 utf-8/big5/cp950，過濾現金/合計，依權重排序）、帶日期快照存取（`tw_quant_data/etf_holdings/{etf}/{date}.json`，重用 utils atomic write）、`overlap_with`（與持股/追蹤重疊）、`fetch_issuer_holdings`（v2 預留）。
- **config.py**：`MAINSTREAM_ETFS`（市值核心/高股息/主題科技/槓桿主動四類，名稱以匯入資料為準不硬編）。
- **app.py**：ETF 分頁拆「🏆 績效排行 / 📋 成分股」兩子頁（原 `_render_tab_etf` body 改名 `_render_etf_performance` 零重縮排）。成分股子頁：選 ETF → 匯入 CSV → 顯示成分＋權重（重疊者標 ⭐）→ 重疊檔數/占權重提示（集中度風險）→ 沿用 `goto_ticker` 跳轉個股分析。
- **v2 待做**：快照已帶日期，diff 兩份即得新增/剔除/權重變化（純 UI＋diff）。
- 驗證：Big5 CSV 解析、過濾、排序、快照、重疊比對皆通過；啟動測試通過。

**H. 每日虛擬買賣 / 紙上交易（v1，2026-07-03）**

- **目標**：每交易日盤後自動用模型挑股虛擬買賣，長期累積權益曲線與學術級指標，檢驗
  模型「到底有沒有選股能力」，作為迭代依據。使用者決策：固定 5 檔輪動、資金上限
  NT$1,000,000（先驗證精準度，日後放寬）。
- **抽出共用計分（review #1，前置）**：帶加成的 `final_composite` 原本**只在 app.py**
  計算、`run_model.py`／`enrich_dataframe` 用基礎分 → 排名不一致。已抽成
  `QuantModel.compute_final_composite(model_df, preferred_groups, sentiment_data,
  fundamental_data)`（`quant_model.py`），App 與每日腳本共用；回歸測試前後數值 0 差異。
  ⚠️ 注意：這與 `enrich_dataframe` 內的 base `final_composite`（權重不同、無基本面品質
  加成）是兩式，**以 compute_final_composite 為準**。
- **新檔 `paper_trading.py`**：`PaperTradingEngine`（load/save、`run_day`、
  `equity_metrics`）。策略＝取合格前 5 名；掉出榜外或觸發 **風險/利空 guard**
  （`risk_score`>80 或新聞情緒<-0.5）賣出，等權補滿 5 檔。計入手續費 0.1425%＋賣出
  證交稅 0.3%＋滑價 0.1%。指標：累積/年化、Sharpe、最大回撤、Alpha(vs 0050)、勝率、
  **IC 資訊係數**（進場分數 vs 實現報酬 Spearman，Grinold-Kahn）。
- **帳本持久化**：`data/paper_trading/ledger.json`（**tracked 路徑**，非 `tw_quant_data/`；
  後者 gitignore 且雲端 ephemeral）。由 GitHub Actions 每日 commit 回存 repo 長期累積。
- **新檔 `scripts/paper_trading_daily.py`**：仿 `run_model.py`（注入 fake streamlit），
  載入行情 → `compute_final_composite` → 引擎決策/記帳 → 抓 0050(退回 ^TWII) 基準 →
  atomic 寫 ledger。已本機跑通（1977 檔，NAV 產出正常）。
- **CI（`.github/workflows/daily_report.yml`）**：新增 paper trading step ＋ commit-back
  step（`permissions: contents: write`，commit 訊息帶 `[skip ci]` 避免迴圈）。
- **App**：Tab 4 新增「📊 紙上交易」子頁（`_render_paper_trading`）：graphviz 運作邏輯圖
  ＋計分公式＋指標定義、權益曲線 vs 0050、8 張指標卡、持倉表、近期交易紀錄、免責。
- **測試**：`tests/test_paper_trading.py` 7/7 通過（維持 N 檔、輪動、guard、NAV、
  Alpha、同日冪等、序列化）。
- **v1 已知限制**：headless 每日 job 無逐檔基本面/新聞 → 用「模型核心分」（無基本面
  品質/新聞 overlay）；TOP5 易被無基本面小型股佔據（＝既有 P1「流動性門檻」問題）。
  可調 `config.min_volume_lots` 緩解，或 v2 接入逐檔基本面/新聞情緒與國際情勢疊加。
  → **已於 I 節解決（四層選股池）**。

---

## 八-B、本輪（2026-07-08）— 模型嚴謹度 + 紙上交易選股池 + 前瞻推估

分三個子 agent 並行實作（檔案所有權互斥）。全套測試 90 passed，py_compile 全乾淨。

**I. 量化模型嚴謹度 F1~F6（對齊業界分析模型，`quant_model.py` / `finmind_loader.py`）**

| 代號 | 問題 | 修正 |
|------|------|------|
| F1 | 毛利/營益/淨利率取**最新單季**，與 EPS(TTM) 口徑不一致 | `_finmind_fundamental` 三率改**近四季 TTM**（`sum(近四季分子)/sum(近四季Revenue)`），<4 季退回單季。`get_financial_trend` 維持單季（趨勢圖用）|
| F2 | `prob=Φ((composite−50)/15)` 的 15 為魔數、未校準 | `calculate_probability` 新增 `score_std` 參數；`enrich_dataframe` 用當日 composite 實際跨截面 std（clamp [8,25]）驅動。文件標「統計刻度·非回測校準」|
| F3 | Value 因子只用 E/P | 改 **E/P + B/P 合成**（各自跨截面後平均）|
| F4 | Momentum 用 MA20/60 乖離卻標 Jegadeesh-Titman | 有歷史時改 **60 日累積報酬（跳最近 5 日）**優先；乖離正名「趨勢乖離」；change_pct 退路標「短期代理」|
| F5 | Quality 含 `eps_growth`，與 Growth 因子**雙重計數** | Quality 只留 gross/net margin（有 ROE 則加），移除 eps_growth |
| — | 測試 | `test_quant_model.py` 既有 44 綠 + 新增 7（F2/F3/F5 鎖定）|

> ⚠️ **F2~F5 會改變排名**（value 加 B/P、quality 去 eps_growth、momentum 改 60 日報酬、機率重新縮放）。上線後應人工檢視真實 TOP20 差異。預設 `score_std=15` 保留舊行為 → 單股頁與既有測試不回歸。

**J. 紙上交易四層選股池（解決「抓到中小股」，`paper_trading.py` / `scripts/paper_trading_daily.py`）**

- **`DEFAULT_CONFIG`（在 `paper_trading.py`，非 config.py）**：`min_volume_lots` 0→**500**；新增 `min_market_cap`=1e10（100 億）、`require_real_fund`=True、`candidate_levels`=["核心候選","觀察候選"]。
- **`run_day` 四層合格池**（欄位守衛，缺欄自動略過該層）：`close>0` → 成交量 → 市值 → 有真實基本面 → 候選等級 → 再 `sort_values("final_composite")` 取前 N。**不足 N 檔時逆序放寬**（等級→基本面→市值→量），放寬原因寫入當日 `rec["relaxed"]` + log。
- **每日 job**：先用量能預篩 top 200 liquid universe（控 API 量）→ 對子集載 FinMind 基本面（best-effort，wrap）→ 附 `market_cap`/`has_real_fund` → 交 `compute_final_composite`。無 token 則優雅降級（require_real_fund 自動放寬並記錄）。
- **驗證**：本機實跑 `scripts/paper_trading_daily.py`（1978→預篩 200→200/200 有基本面）選出美時1795/新纖1409/環泥1104/儒鴻1476/亞德客1590（皆流動中大型股，無放寬）。小型股 bug 解決。
- **測試**：`test_paper_trading.py` 7 舊 + 6 新（低量/無基本面/等級/市值過濾、放寬機制）= 13 綠。

**K. 個股前瞻營收/EPS + Forward P/E（新 `forecast.py` + `components/fundamental_blocks.py`）**

- ⚠️ **合規**：免費源無分析師共識/財測 → 全為**模型 run-rate 歷史外推**，UI 明確標「非分析師共識/財測」+ 列假設 + 免責（守 CLAUDE.md 反造假）。
- **新檔 `forecast.py`**（純函式、不連網、可單元測試）`build_forward_estimates(rev_trend, fin_trend, breakout, per_trend, close, fund)`：
  - 本年營收估＝**進度追蹤法**（YTD 實際 + 剩餘月份 = 去年同月×(1+近3月平均YoY)），附前 2~3 年年度實際。
  - 本年 EPS 估＝**季度 seasonal 法**（已報季 + 未報季 = 去年同季×(1+近期EPS YoY)）＋ `annual_pace` 交叉驗證＋歷史年 EPS 實際（供柱圖）。
  - FY+1 EPS 估＝本年估×(1+前瞻成長率)，成長率=營收動能與 EPS CAGR 混合，clamp [-30%,+50%]，附保守/基準/樂觀（±10pp）帶。
  - **Forward P/E**＝現價/前瞻EPS；對照歷史 PE 中位，>1.2× 觸發「已反映樂觀預期·不宜追高」旗標。
  - 資料不足回 `{"has_data": False}`。測試 `tests/test_forecast.py` 15 綠。
- **`render_forecast_block(estimates)`**（`components/fundamental_blocks.py`）：EPS 柱（實心歷史+斜線推估）、營收柱（億元）、Forward P/E metric + 高估 warning、FY+1 情境三卡、假設 expander、免責。深色 plotly 沿用專案慣例。
- **接線**：`app.py` 個股研究「📊 基本面」子頁月營收/季EPS 圖之後（僅多一支 `get_eps_breakout` API，其餘重用 in-scope 資料）。追蹤頁估值子頁**刻意略過**（避免額外 2+ 次 FinMind 呼叫）。紙上交易分頁加四層過濾說明 caption。

**L. 大戶／外資籌碼水位（免費資料，2026-07-09）**

- **背景**：使用者問「大戶買賣張數 / 主力進出」。查證結論：真正的**券商分點主力進出**免費源不可靠、商用皆付費 → 不採用（守不造假/揭露成本）。改以兩個**官方免費**替代：
- **外資持股比例趨勢**（`finmind_loader.get_foreign_holding_trend`，FinMind `TaiwanStockShareholding`，**免費、每日、有歷史**）：外資＝最大法人主力的「持股水位」，與 T86 每日買賣超「流量」互補。
- **集保大戶持股**（新 `tdcc_loader.py`，TDCC OpenData id=1-5，**免費、每週**）：級距 15=≥1000張、12~15=≥400張大戶占比；TDCC 只給最新一週 → **逐週累積本機快照**（`tw_quant_data/major_holder_history.json`）才有週增減；全市場 CSV(~2MB) 快取 1 天。
- **UI**：`components/flow_blocks.render_major_holder_block`（外資持股折線 + 大戶 metric + 週增減）；接個股研究「🏦 籌碼」子頁，**lazy 按鈕載入**避免每次抓 2MB。
- **驗證案例**：6531 外資持股 4/27 32.7% → 7/8 28.61%（近月減持），即使 7/8 單日買超 +193 張 → 佐證「水位 vs 流量」互補。大戶(≥1000張) 52.97%。
- **快取防呆**：`twse_institutional` 加 `_MAX_ROWS=4000`，法人/融資券快取筆數異常膨脹（舊版殘留，如曾出現 13,564 筆）即視為失效重抓，修正「投信 −4／合計錯誤」類舊快取誤導。
- **測試**：`tests/test_tdcc.py` 3 綠（級距聚合、週增減、缺股）。全套 **93 passed**。
- ⚠️ 限制：TDCC 週更新、本機快照首次僅一週；雲端 `tw_quant_data/` ephemeral，長期週趨勢累積需比照紙上交易 commit-back（暫未做）。

---

## 九、待優化方向

### Phase 1 已完成（2026-06-08）

- [x] P0 安全修復：登入繞過、write_json atomic、HANDOFF 敏感資料清除
- [x] P1 架構分解：state.py、components/、services/persistence_service.py
- [x] 危險腳本封存至 scripts/archive/

### Phase 2 已完成（2026-06-08）

- [x] 10 個 Tab → 5 個主 Tab（closure 方案）
- [x] 合併 熱度排行 + 產業瀏覽器 → 🔥 主題供應鏈
- [x] 合併 整體分析 + 潛力股 → 🎯 候選篩選
- [x] 合併 持倉管理 + 追蹤清單 + ETF排行 + 模型設定 → ⭐ 追蹤與組合

### Phase 3 已完成（2026-06-08）

- [x] **THEME_GRAPH**：`config.py` 新增 7 個主題（AI基礎建設/先進封裝/光通訊/低軌衛星/地緣政治/電動車機器人/漲價受惠），橋接 PRICE_THEMES + SUPPLY_CHAIN_GROUPS + data/ JSON
- [x] **data/ 目錄**：從 TaiwanTechNewsMonitor/config/ 複製 6 個 JSON（supply_chains/events/rules/future_events/sources/concepts）
- [x] **radar_loader.py**：RadarLoader 整合事件日程 + 主題熱度 + 傳導規則，11 個未來事件、7 個主題可載入
- [x] **components/radar_blocks.py**：主題卡片 + 事件日程 + 宏觀指標 render 元件
- [x] **情勢雷達強化**：Tab 1（`_render_tab_radar`）新增主題訊號 + 未來 60 天事件日程 + 宏觀快照，原美股連動保留在底部

### Phase 3 待執行（資料模型）

- [ ] 建立 `THEME_GRAPH`（整合 NEWS_TO_SUPPLY_CHAIN + PRICE_THEMES + SUPPLY_CHAIN_GROUPS）

### 其他已知待優化

1. **UI 整體 RWD**：目前無 mobile 支援，寬度固定
2. **Tab 4 追蹤清單技術面**：首次需手動點載入按鈕，可考慮自動預載
3. **毛利率/淨利率**：仍取最新單季（非 TTM 平均），可進一步優化
4. **Bootstrap CI**：`backtest.py` 已實作 `bootstrap_model_confidence()`，但 Tab 7 模型設定尚未整合顯示
5. **app.py 舊 comment**：Tab 2 候選清單 / Tab 3 個股分析 的 comment 為過時遺留（可清理）

---

## 十、開發規範提醒

1. **絕對禁止在函式內部 `from x import y`** — 已發生三次，每次在 `main()` 造成 UnboundLocalError
2. **修改大型函式前先 Read 上下文**（app.py 超過 3,500 行）
3. **每次修改後驗證**：`.\.venv\Scripts\python.exe -m py_compile app.py`
4. **`git add` 時不要 commit `.claude/settings.json`**（個人設定不入庫）

---

## 十一、啟動測試指令

```powershell
cd "C:\投資\tw-stock-platform_20260511"
.\.venv\Scripts\python.exe -m py_compile app.py  # 語法檢查
.\run.ps1                                         # 啟動平台
```
