# 台股分析平台 — 對話交接文件

> 最後更新：2026-06-11（法人買賣超/成交量單位修正 + 供應鏈分類校正）
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
tabs[4] ⭐ 追蹤與組合    — 子 Tab：⭐追蹤清單 + 💼持倉管理 + 📈ETF排行 + ⚙️模型設定
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

## 三、核心 Python 模組（共 19 個）

### 主程式與架構層

| 模組 | 行數 | 功能 |
|------|------|------|
| `app.py` | 3,450+ | Streamlit 主程式（5 個 Tab，閉包方案）— render 函式已移至 components/ |
| `state.py` | ~55 | 全域 session_state 初始化（從 app.py 抽離）|
| `radar_loader.py` | ~220 | RadarLoader：整合事件日程 + 主題熱度 + 宏觀快照 |

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
