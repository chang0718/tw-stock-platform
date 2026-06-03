"""
台股盤後量化分析平台 - 主程式
v3.0 真實數據版

功能:
- 上市 + 上櫃市場
- 六因子量化模型（真實 API 數據）
- 三大法人 / 融資融券（TWSE 全市場一次載入）
- 基本面（FinMind，追蹤清單自動載入）
- 新聞情緒（RSS 關鍵字，個股頁面）
- 追蹤清單（自動載入基本面 + 新聞）
- 期望報酬率系統
- 歷史回測
"""

import hashlib
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import (
    CONCEPT_STOCKS,
    SUPPLY_CHAIN_GROUPS,
    SUPPLY_CHAIN_TREE,
    DEFAULT_WEIGHTS,
    DISPLAY_COLUMNS,
    NOTES_FILE,
    SNAPSHOT_FILE,
    WATCHLIST_FILE,
    WEIGHT_LABELS,
    WEIGHTS_FILE,
)
from utils import format_percentage, read_json, write_json
from data_loader import MarketDataLoader
from quant_model import QuantModel
from finmind_loader import FinMindLoader
from twse_institutional import TWSeInstitutionalLoader
from news_analyzer import NewsAnalyzer
from tech_analyzer import analyze as tech_analyze, INDICATOR_EXPLANATIONS
from us_market import USMarketLoader, US_TW_SUPPLY_CHAIN, TW_INDUSTRY_CHAIN, US_INDICES, US_KEY_STOCKS
from macro_loader import MacroLoader
from institutional_tracker import InstitutionalTracker, TRACKED_FUNDS
from signal_engine import SignalEngine
from portfolio import Portfolio

# ============================================================
# 頁面配置
# ============================================================

st.set_page_config(
    page_title="台股盤後量化分析平台｜v3.0",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"About": "個人自用台股分析工具 v3.0"},
)

# ============================================================
# 密碼保護
# ============================================================

def _check_password() -> bool:
    try:
        correct = st.secrets["auth"]["password"]
    except Exception:
        return True  # 本機沒設 secrets 時跳過驗證

    if st.session_state.get("_authenticated"):
        return True

    with st.container():
        st.title("台股分析平台")
        pwd = st.text_input("請輸入密碼", type="password", key="_pwd_input")
        if st.button("登入"):
            if pwd == correct:
                st.session_state["_authenticated"] = True
                st.rerun()
            else:
                st.error("密碼錯誤")
    return False

if not _check_password():
    st.stop()

# ============================================================
# Session State 初始化
# ============================================================

def initialize_session_state():
    defaults = {
        "universe_df":       pd.DataFrame(),
        "weights":           read_json(WEIGHTS_FILE, DEFAULT_WEIGHTS),
        "notes":             read_json(NOTES_FILE, {}),
        "last_update":       None,
        "data_date":         "",
        # 追蹤清單：{ticker: {name, added_date}}
        "watchlist":         read_json(WATCHLIST_FILE, {}),
        "watchlist_data":    {},   # {ticker: {fundamental, news, name}}
        # 法人 / 融資券（市場載入時抓）
        "institutional_data": {"inst": {}, "margin": {}},
        # 個別股票已載入的基本面
        "stock_fundamentals": {},
        # 模型輸出快取
        "model_df_cached":   pd.DataFrame(),
        "model_cache_key":   "",
        # FinMind token
        "finmind_token":     "",
        # 技術分析快取 {ticker: analysis_dict}
        "tech_data":         {},
        # 美股市場快取
        "us_market_data":    {},
        "us_market_ts":      0,
        # 持倉管理
        "portfolio":         Portfolio(),
        # 每日快照（回測/調優用）
        "snapshots":         read_json(SNAPSHOT_FILE, []),
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # 若 secrets.toml 已填入真實 FinMind token，自動載入（避免每次重啟都要手動輸入）
    if not st.session_state.get("finmind_token"):
        try:
            secret_token = st.secrets.get("finmind", {}).get("token", "")
            if secret_token and secret_token != "your_finmind_token_here":
                st.session_state.finmind_token = secret_token
        except Exception:
            pass


# ============================================================
# 資料載入
# ============================================================

def _update_price_history(df: pd.DataFrame):
    """將今日收盤價累積到本機 price_history.json（動能/波動率基礎）"""
    from config import HISTORY_FILE
    from utils import read_json, write_json
    today = date.today().isoformat()
    history = read_json(HISTORY_FILE, {})
    updated = 0
    for _, row in df.iterrows():
        t     = row.get("ticker")
        daily = row.get("daily") if isinstance(row.get("daily"), dict) else {}
        close = daily.get("close")
        if t and close is not None:
            records = history.get(t, [])
            if not records or records[-1].get("date") != today:
                records.append({"date": today, "close": float(close)})
                records = records[-300:]   # 保留最近 300 個交易日
                history[t] = records
                updated += 1
    if updated:
        write_json(HISTORY_FILE, history)
    return updated


def load_market_data_action(include_tpex: bool = True):
    with st.spinner("📥 載入市場行情資料..."):
        loader = MarketDataLoader()
        df, data_date = loader.load_all_market_data(include_tpex=include_tpex)
        if df.empty:
            st.error("❌ 市場資料與備用資料都無法取得，請確認網路連線後重試")
            return
        st.session_state.universe_df = df
        st.session_state.last_update = datetime.now()
        st.session_state.data_date   = data_date
        st.session_state.model_cache_key = ""   # 強制重算

    # 累積今日價格到本機歷史（讓動能/波動率分數逐日建立）
    n_updated = _update_price_history(df)
    valid_prices = df["daily"].apply(lambda d: d.get("close") if isinstance(d, dict) else None).notna().sum()
    st.success(f"✅ 載入 {len(df)} 檔，有效收盤價 {valid_prices} 檔，累積歷史 {n_updated} 筆")
    if data_date:
        today_str = date.today().isoformat()
        if data_date == today_str:
            st.info(f"📅 行情資料日期：{data_date}（今日收盤）")
        else:
            st.warning(f"⚠️ 行情資料日期：{data_date}（前一交易日）｜TWSE 盤後資料通常於 17:00 後更新")

    with st.spinner("📊 載入三大法人 / 融資融券（最多 25 秒）..."):
        import concurrent.futures as _cf
        inst_loader = TWSeInstitutionalLoader()
        token = st.session_state.get("finmind_token", "")

        def _load_inst():
            return inst_loader.get_institutional_all(finmind_token=token)

        def _load_margin():
            return inst_loader.get_margin_all()

        inst = margin = {}
        try:
            with _cf.ThreadPoolExecutor(max_workers=2) as _ex:
                _fi = _ex.submit(_load_inst)
                _fm = _ex.submit(_load_margin)
                # 各給 12 秒，總計不超過 25 秒
                inst   = _fi.result(timeout=12) or {}
                margin = _fm.result(timeout=12) or {}
        except _cf.TimeoutError:
            st.warning("⚠️ 三大法人 API 回應逾時（TWSE 伺服器繁忙），使用昨日快取或空值繼續")
        except Exception as _e:
            st.warning(f"⚠️ 三大法人載入失敗：{_e}")

        st.session_state.institutional_data = {
            "inst":   inst,
            "margin": margin,
        }

    n_inst = len(st.session_state.institutional_data["inst"])
    if n_inst:
        st.success(f"✅ 三大法人已載入（{n_inst} 檔）")
    else:
        st.warning("⚠️ 三大法人暫時無法取得（非交易日、API 逾時或無資料）")


def load_csv_action(uploaded_file):
    loader = MarketDataLoader()
    df = loader.load_from_csv(uploaded_file)
    if df is not None:
        st.session_state.universe_df = df
        st.session_state.last_update = datetime.now()
        st.session_state.model_cache_key = ""


def load_watchlist_data():
    """追蹤清單個股自動載入基本面 + 新聞（有 7天/1小時快取）"""
    if not st.session_state.watchlist or st.session_state.universe_df.empty:
        return

    missing = [
        t for t in st.session_state.watchlist
        if t not in st.session_state.watchlist_data
    ]
    if not missing:
        return

    fm = FinMindLoader(token=st.session_state.get("finmind_token", ""))
    na = NewsAnalyzer()

    with st.spinner(f"🔍 自動載入 {len(missing)} 檔追蹤個股基本面..."):
        for ticker in missing:
            name = st.session_state.watchlist[ticker].get("name", ticker)
            fundamental = fm.get_fundamental(ticker)
            news_data   = na.get_stock_news_sentiment(ticker, name)
            st.session_state.watchlist_data[ticker] = {
                "fundamental": fundamental,
                "news":        news_data,
                "name":        name,
            }
            # 同步至 stock_fundamentals，讓模型用真實基本面評分
            st.session_state.stock_fundamentals[ticker] = fundamental

    # 有新資料：強制模型重算
    if missing:
        st.session_state.model_cache_key = ""


# ============================================================
# 篩選
# ============================================================

def apply_filters(df: pd.DataFrame, filters: Dict) -> pd.DataFrame:
    result = df.copy()

    # 供應鏈過濾（新）：優先於產業別，真正限縮股票池
    selected_scs = filters.get("supply_chains", [])
    if selected_scs:
        allowed: set = set()
        for sc in selected_scs:
            allowed |= set(SUPPLY_CHAIN_GROUPS.get(sc, []))
        result = result[result["ticker"].isin(allowed)]

    if filters["industry"] != "全部":
        result = result[result["group"] == filters["industry"]]
    if filters["market"] != "全部":
        result = result[result["market"] == filters["market"]]
    if filters["query"].strip():
        q = filters["query"].strip().lower()
        mask = (
            result["ticker"].astype(str).str.contains(q, case=False, na=False)
            | result["name"].astype(str).str.contains(q, case=False, na=False)
            | result["industry"].astype(str).str.contains(q, case=False, na=False)
            | result["group"].astype(str).str.contains(q, case=False, na=False)
        )
        result = result[mask]
    if filters["candidate_level"] != "全部":
        result = result[result["candidate_level"] == filters["candidate_level"]]
    if filters["only_complete"]:
        result = result[result["complete_score"] == True]
    if not filters["include_uncategorized"]:
        result = result[result["group"] != "未分類"]
    if not result.empty:
        result = result.sort_values(
            filters["sort_by"],
            ascending=filters["sort_ascending"],
            key=lambda x: pd.to_numeric(x, errors="coerce"),
        )
        result = result.head(filters["display_count"])
    return result


# ============================================================
# 側邊欄
# ============================================================

def render_sidebar(universe_df: pd.DataFrame) -> Dict:
    st.sidebar.title("📊 篩選條件")

    if not universe_df.empty and "group" in universe_df.columns:
        all_g = universe_df["group"].tolist()
        available_groups = sorted({
            str(g) for g in all_g
            if g is not None and str(g) not in ["nan", "None", "", "NaN"] and not pd.isna(g)
        })
    else:
        available_groups = []

    if not universe_df.empty and "market" in universe_df.columns:
        all_m = universe_df["market"].tolist()
        available_markets = sorted({
            str(m) for m in all_m
            if m is not None and str(m) not in ["nan", "None", "", "NaN"] and not pd.isna(m)
        })
    else:
        available_markets = []

    if not available_groups:
        available_groups = ["半導體", "光通訊/網通", "AI伺服器/電子", "金融", "航運", "未分類"]
    if not available_markets:
        available_markets = ["上市", "上櫃"]

    filters: Dict = {}

    # ── 供應鏈篩選已移至 Tab 7 產業瀏覽器 ────────────────────────
    filters["supply_chains"] = []  # Tab 7 pills 選擇，此處不再篩選

    # ── 快速搜尋（移至最頂）─────────────────────────────────────
    st.sidebar.markdown("### 🔍 快速搜尋")
    filters["query"] = st.sidebar.text_input(
        "", placeholder="代號、名稱、產業，如 2330", key="search_query",
        label_visibility="collapsed",
    )

    st.sidebar.markdown("### 🎯 篩選條件")
    filters["market"]   = st.sidebar.selectbox("市場",   ["全部"] + available_markets, key="market_filter")
    filters["candidate_level"] = st.sidebar.selectbox(
        "候選等級",
        ["全部", "核心候選", "觀察候選", "高風險觀察", "保守觀望"],
        key="candidate_filter",
    )
    filters["industry"] = st.sidebar.selectbox("產業別", ["全部"] + available_groups, key="industry_filter")

    st.sidebar.markdown("### 📈 排序與顯示")
    sort_options = {
        "綜合評分":    "final_composite",
        "20日上漲機率": "prob20",
        "5日上漲機率":  "prob5",
        "60日上漲機率": "prob60",
        "期望報酬率":   "expected_return_20d",
        "模型信心度":   "confidence",
        "風險分數":    "risk_score",
        "成交量":      "volume",
    }
    sort_label = st.sidebar.selectbox("排序欄位", list(sort_options.keys()), key="sort_field")
    filters["sort_by"]        = sort_options[sort_label]
    filters["sort_ascending"] = sort_label == "風險分數"

    filters["only_complete"] = st.sidebar.checkbox("✅ 只顯示完整評分（真實數據）", value=False, key="complete_filter")
    filters["include_uncategorized"] = st.sidebar.checkbox("📦 包含未分類產業", value=True, key="uncat_filter")
    filters["display_count"] = st.sidebar.slider("顯示筆數", 10, 500, 50, 10, key="display_count")

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📥 資料操作")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("🔄 載入上市", use_container_width=True):
            load_market_data_action(include_tpex=False)
            st.rerun()
    with col2:
        if st.button("🌐 載入全市場", use_container_width=True):
            load_market_data_action(include_tpex=True)
            st.rerun()

    uploaded = st.sidebar.file_uploader("📂 匯入CSV", type=["csv"], help="需包含欄位: ticker, name, industry, close")
    if uploaded is not None:
        load_csv_action(uploaded)
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚖️ 因子權重")
    st.sidebar.caption(f"權重總和: {sum(st.session_state.weights.values())} (自動標準化)")
    for key, label in WEIGHT_LABELS.items():
        st.session_state.weights[key] = st.sidebar.slider(
            label, 0, 60,
            int(st.session_state.weights.get(key, DEFAULT_WEIGHTS[key])),
            1, key=f"weight_{key}",
        )
    write_json(WEIGHTS_FILE, st.session_state.weights)

    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⭐ 特別關注產業")
    st.sidebar.caption("僅做排序加權，不無條件看多")
    preferred_default = [g for g in ["半導體", "光通訊/網通", "AI伺服器/電子"] if g in available_groups]
    filters["preferred_groups"] = st.sidebar.multiselect(
        "有興趣項目", available_groups, default=preferred_default, key="preferred_groups"
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("### ℹ️ 關於")
    if st.session_state.last_update:
        st.sidebar.caption(f"最後更新: {st.session_state.last_update.strftime('%Y-%m-%d %H:%M')}")
    if st.session_state.get("data_date"):
        st.sidebar.caption(f"行情資料日：{st.session_state.data_date}")
    inst_count = len(st.session_state.institutional_data.get("inst", {}))
    wl_count   = len(st.session_state.watchlist)
    st.sidebar.caption(
        f"股票池: {len(universe_df)} 檔\n\n"
        f"法人資料: {inst_count} 檔\n\n"
        f"追蹤清單: {wl_count} 檔\n\n"
        f"資料更新: {st.session_state.get('data_date', '--')}"
    )

    if st.sidebar.checkbox("🔧 顯示除錯資訊", value=False):
        with st.sidebar.expander("除錯資訊"):
            st.write(f"股票數: {len(universe_df)}")
            if not universe_df.empty:
                st.write(f"欄位: {list(universe_df.columns)}")
                if "group" in universe_df.columns:
                    uq = universe_df["group"].unique()
                    st.write(f"產業數: {len(uq)}")
                    st.write(f"產業（前5）: {list(uq[:5])}...")

    st.sidebar.markdown("---")
    st.sidebar.caption("💡 按 `[` 鍵可收合側邊欄，獲得更大瀏覽區域。\n\n供應鏈/概念股篩選已移至「📊 產業瀏覽器」Tab。")

    return filters


# ============================================================
# 快照
# ============================================================



# ============================================================
# UI 輔助：基本面顯示區塊
# ============================================================

def render_fundamental_block(fund: Dict):
    """通用基本面顯示（含數據來源標籤 + 白話解讀）"""
    if not fund or fund.get("data_type") == "NO_DATA":
        src = fund.get("fund_data_source") or fund.get("data_source", "")
        st.warning(
            f"⚠️ 暫無基本面數據（{src}）\n\n"
            "建議：① 在 **⚙️ 模型設定** 填入 FinMind 免費 token，或 ② 加入追蹤清單，"
            "系統會自動嘗試從 yfinance 取得 PE/EPS 等基本指標。"
        )
        return

    src_label = fund.get("data_source", "✅ FinMind")

    c1, c2, c3, c4 = st.columns(4)
    def _m(col, label, val, fmt, help_txt=""):
        with col:
            if val is not None:
                col.metric(label, fmt(val), help=help_txt)
            else:
                col.metric(label, "N/A", help=help_txt)

    _m(c1, "營收年增率",  fund.get("revenue_yoy"),
       lambda v: f"{v:+.1f}%", "比去年同期多賣多少。正數=成長，負數=衰退")
    _m(c2, "每股獲利 EPS", fund.get("eps"),
       lambda v: f"${v:.2f}", "每一股票一年賺多少元。越高越好，負數代表虧損")
    _m(c3, "本益比 PE",    fund.get("pe"),
       lambda v: f"{v:.1f}倍", "股價是每年獲利的幾倍。<15倍偏便宜；>30倍偏貴")
    _m(c4, "毛利率",       fund.get("gross_margin"),
       lambda v: f"{v:.1f}%", "扣掉直接成本後還剩多少比例。>30%不錯；>50%護城河強")

    c5, c6, c7, c8 = st.columns(4)
    _m(c5, "EPS年增率",   fund.get("eps_growth_yoy"),
       lambda v: f"{v:+.1f}%", "獲利比去年成長多少。持續為正代表公司持續賺更多")
    _m(c6, "淨利率",      fund.get("net_margin"),
       lambda v: f"{v:.1f}%",  "最終賺到的比例（扣掉所有費用後）。>10%算不錯")
    _m(c7, "股價淨值比",  fund.get("pb"),
       lambda v: f"{v:.2f}倍", "股價是帳面價值的幾倍。<1倍可能被低估；>3倍偏貴")
    _m(c8, "現金殖利率",  fund.get("dividend_yield"),
       lambda v: f"{v:.2f}%",  "每年配股息的比例。>5%適合存股；<2%配息少")

    if fund.get("latest_revenue_month"):
        st.caption(f"最新營收月份: {fund['latest_revenue_month']} ｜ 資料來源: {src_label}")

    # ── 白話解讀 ──────────────────────────────────────────────────
    pe  = fund.get("pe")
    gm  = fund.get("gross_margin")
    nm  = fund.get("net_margin")
    ry  = fund.get("revenue_yoy")
    eps = fund.get("eps")
    dy  = fund.get("dividend_yield")
    eg  = fund.get("eps_growth_yoy")

    interps = []
    if pe is not None:
        if pe < 10:
            interps.append(f"🏷️ **本益比 {pe:.1f}倍**：相當便宜，但要確認獲利是否穩定（本益比過低有時是因為公司有問題）")
        elif pe < 18:
            interps.append(f"✅ **本益比 {pe:.1f}倍**：估值合理，不算貴")
        elif pe < 30:
            interps.append(f"🟡 **本益比 {pe:.1f}倍**：偏高，需確認成長能支撐這個價格")
        else:
            interps.append(f"⚠️ **本益比 {pe:.1f}倍**：偏貴，追高風險高，除非成長非常強勁")
    if gm is not None:
        if gm >= 50:
            interps.append(f"💎 **毛利率 {gm:.1f}%**：護城河強，公司有很強的定價能力")
        elif gm >= 30:
            interps.append(f"✅ **毛利率 {gm:.1f}%**：獲利能力不錯")
        else:
            interps.append(f"🟡 **毛利率 {gm:.1f}%**：偏低，屬低毛利行業，需靠量取勝")
    if ry is not None:
        if ry >= 20:
            interps.append(f"🚀 **營收年增 {ry:+.1f}%**：成長強勁，業績明顯擴張")
        elif ry >= 5:
            interps.append(f"✅ **營收年增 {ry:+.1f}%**：穩健成長")
        elif ry >= -5:
            interps.append(f"➡️ **營收年增 {ry:+.1f}%**：持平，需觀察後續是否好轉")
        else:
            interps.append(f"⚠️ **營收年增 {ry:+.1f}%**：衰退中，需留意是否為結構性問題")
    if nm is not None:
        if nm < 0:
            interps.append(f"🔴 **淨利率 {nm:.1f}%**：目前虧損，費用大於收入")
        elif nm < 5:
            interps.append(f"🟡 **淨利率 {nm:.1f}%**：獲利薄，稍有風吹草動就可能虧損")
        elif nm >= 20:
            interps.append(f"💰 **淨利率 {nm:.1f}%**：賺錢效率極高")
    if dy is not None and dy > 0:
        if dy >= 5:
            interps.append(f"💵 **殖利率 {dy:.2f}%**：配息豐厚，適合存股族")
        elif dy >= 2:
            interps.append(f"✅ **殖利率 {dy:.2f}%**：有穩定配息")

    if interps:
        st.markdown("##### 📝 白話解讀")
        for t in interps:
            st.markdown(f"- {t}")
        st.caption("⚠️ 以上為財務數字的初步解讀，不構成買賣建議。請搭配產業趨勢與整體市場環境判斷。")


def render_news_block(news_data: Dict):
    """新聞情緒區塊（直接列新聞，不顯示無意義情緒分數）"""
    if not news_data:
        return

    s         = news_data.get("sentiment", {})
    news_list = news_data.get("news", [])

    # 整體情緒（只在有足夠新聞時才顯示，且移除沒意義的純數字分數）
    if news_list:
        label       = s.get("label", "中性")
        label_color = s.get("label_color", "🟡")
        pos_kw = s.get("pos_keywords", [])
        neg_kw = s.get("neg_keywords", [])

        sent_col, kw_col = st.columns([1, 3])
        with sent_col:
            st.metric("整體情緒傾向", f"{label_color} {label}",
                      help="根據新聞標題關鍵字判斷，正面/負面/中性。\n新聞數量少時準確度有限，僅供參考。")
        with kw_col:
            if pos_kw:
                st.caption(f"正面關鍵字：{', '.join(pos_kw)}")
            if neg_kw:
                st.caption(f"負面關鍵字：{', '.join(neg_kw)}")
            st.caption(f"資料來源：{s.get('data_source', '關鍵字分析')}　共 {len(news_list)} 則新聞")

        st.markdown("---")

    # 新聞列表（直接展示，不折疊）
    if news_list:
        st.markdown(f"**📰 近期相關新聞（{len(news_list)} 則）**")
        for n in news_list:
            src_icon = "📡" if n.get("source") == "yfinance" else "📰"
            st.markdown(f"{src_icon} **[{n['title']}]({n['link']})** — `{n['published'][:10]}`")
            if n.get("summary"):
                st.caption(n["summary"])
        st.caption("⚠️ 新聞來源：yfinance / Google RSS。點擊標題可前往原文閱讀。")
    else:
        st.info("⚠️ 目前沒有抓到新聞。可能原因：① 股票代號較冷門 ② 網路連線問題 ③ 需安裝 feedparser（`pip install feedparser`）")


def render_flow_block(stock: dict, show_reload: bool = False):
    """籌碼資料區塊"""
    src = stock.get("flow_data_source", "⚠️ 暫無數據")
    has_data = stock.get("foreign_net") is not None or stock.get("margin_balance") is not None
    if not has_data:
        inst_loaded = bool(st.session_state.get("institutional_data", {}).get("inst"))
        if inst_loaded:
            st.info("ℹ️ 本股今日無三大法人買賣記錄（TWSE T86 API 只回傳當日有交易的標的）")
        else:
            st.warning("⚠️ 籌碼數據未載入。請點擊側邊欄「🔄 載入上市」或「🌐 載入全市場」以取得三大法人資料。")
        if show_reload:
            if st.button("🔄 重新載入三大法人資料", key="reload_inst"):
                with st.spinner("載入中..."):
                    il = TWSeInstitutionalLoader()
                    st.session_state.institutional_data = {
                        "inst":   il.get_institutional_all(
                            finmind_token=st.session_state.get("finmind_token", "")
                        ) or {},
                        "margin": il.get_margin_all() or {},
                    }
                    st.session_state.model_cache_key = ""
                st.rerun()
        return
    st.caption(f"資料來源: {src}")
    c1, c2, c3 = st.columns(3)
    def _flow(col, label, val):
        with col:
            if val is not None:
                col.metric(label, f"{val:+,} 千股")
            else:
                col.metric(label, "N/A")
    _flow(c1, "外資買賣超", stock.get("foreign_net"))
    _flow(c2, "投信買賣超", stock.get("trust_net"))
    _flow(c3, "自營商買賣超", stock.get("dealer_net"))

    c4, c5 = st.columns(2)
    with c4:
        mb = stock.get("margin_balance")
        mc = stock.get("margin_change")
        if mb is not None:
            c4.metric("融資餘額", f"{mb:,}", delta=f"{mc:+,}" if mc else None)
        else:
            c4.metric("融資餘額", "N/A")
    with c5:
        sb = stock.get("short_balance")
        sc = stock.get("short_change")
        if sb is not None:
            c5.metric("融券餘額", f"{sb:,}", delta=f"{sc:+,}" if sc else None)
        else:
            c5.metric("融券餘額", "N/A")


def render_tech_block(ta: Dict, stock: Dict = None):
    """技術分析圖表（subplot 版）+ 文字摘要 + 購買信心指數"""
    if "error" in ta:
        st.warning(ta["error"])
        return

    from plotly.subplots import make_subplots

    ind   = ta["indicators"]
    ana   = ta["analysis"]
    dates = ind["dates"]

    # ── 四合一 Subplot ──
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        row_heights=[0.50, 0.16, 0.17, 0.17],
        vertical_spacing=0.03,
        subplot_titles=("K線 + MA + 布林通道", "成交量", "RSI (14)", "MACD (12,26,9)"),
    )

    # Row 1: K線
    fig.add_trace(go.Candlestick(
        x=dates, open=ind["open"], high=ind["high"],
        low=ind["low"], close=ind["close"],
        name="K線", increasing_line_color="#ef5350",
        decreasing_line_color="#26a69a",
    ), row=1, col=1)
    for ma_key, color, lbl, width in [
        ("ma5","#FFA726","MA5",1.2),("ma20","royalblue","MA20",1.4),
        ("ma60","#AB47BC","MA60",1.4),("ma120","#FF7043","MA120",1.2),("ma240","#26C6DA","MA240（年線）",1.2),
    ]:
        if ma_key not in ind:
            continue
        vals = ind[ma_key]
        if any(v == v and v is not None for v in vals):
            fig.add_trace(go.Scatter(x=dates, y=vals, name=lbl,
                                     line=dict(color=color, width=width), opacity=0.85), row=1, col=1)
    fig.add_trace(go.Scatter(x=dates, y=ind["bb_upper"], name="布林上",
                              line=dict(color="gray", dash="dot", width=1), opacity=0.5,
                              showlegend=True), row=1, col=1)
    fig.add_trace(go.Scatter(x=dates, y=ind["bb_lower"], name="布林下",
                              line=dict(color="gray", dash="dot", width=1), opacity=0.5,
                              fill="tonexty", fillcolor="rgba(180,180,180,0.08)"), row=1, col=1)

    # Row 2: 成交量
    vol_colors = ["#ef5350" if c >= o else "#26a69a"
                  for c, o in zip(ind["close"], ind["open"])]
    fig.add_trace(go.Bar(x=dates, y=ind["volume"], name="成交量",
                          marker_color=vol_colors, opacity=0.8), row=2, col=1)
    fig.add_trace(go.Scatter(x=dates, y=ind["vol_ma20"], name="量MA20",
                              line=dict(color="orange", width=1.3)), row=2, col=1)

    # Row 3: RSI
    fig.add_trace(go.Scatter(x=dates, y=ind["rsi"], name="RSI",
                              line=dict(color="rgb(99,110,250)", width=1.5)), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red",   opacity=0.6,
                  annotation_text="超買70", annotation_position="top right", row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", opacity=0.6,
                  annotation_text="超賣30", annotation_position="bottom right", row=3, col=1)

    # Row 4: MACD
    hist_colors = ["#ef5350" if v >= 0 else "#26a69a" for v in ind["macd_hist"]]
    fig.add_trace(go.Bar(x=dates, y=ind["macd_hist"], name="MACD柱",
                          marker_color=hist_colors, opacity=0.7), row=4, col=1)
    fig.add_trace(go.Scatter(x=dates, y=ind["macd"],        name="MACD",
                              line=dict(color="royalblue", width=1.5)), row=4, col=1)
    fig.add_trace(go.Scatter(x=dates, y=ind["macd_signal"], name="Signal",
                              line=dict(color="orange",    width=1.5)), row=4, col=1)

    fig.update_layout(
        height=800,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.01, x=0),
        margin=dict(t=60, b=20),
    )
    fig.update_yaxes(row=3, col=1, range=[0, 100])
    fig.update_xaxes(row=4, col=1, showticklabels=True)
    st.plotly_chart(fig, use_container_width=True)

    # ── 購買信心指數 ──
    tech_score_norm = min(100, max(0, 50 + ana["score"] * 8))
    prob20      = (stock.get("prob20", 50)       if stock else 50)
    comp_score  = (stock.get("composite_score", 50) if stock else 50)
    flow_score  = (stock.get("flow_score", 50)   if stock else 50)
    quality     = (stock.get("quality_score", 50) if stock else 50)

    buy_confidence = round(
        tech_score_norm * 0.30
        + prob20        * 0.30
        + comp_score    * 0.15
        + flow_score    * 0.15
        + quality       * 0.10,
        1,
    )

    if buy_confidence >= 70:
        conf_label = "🟢 建議買進"
        conf_color = "success"
    elif buy_confidence >= 55:
        conf_label = "🟡 可分批佈局"
        conf_color = "info"
    elif buy_confidence >= 40:
        conf_label = "🟡 觀望"
        conf_color = "warning"
    else:
        conf_label = "🔴 建議迴避 / 考慮賣出"
        conf_color = "error"

    st.markdown("---")
    st.markdown("#### 🎯 購買信心指數")
    ci1, ci2, ci3, ci4, ci5, ci6 = st.columns(6)
    ci1.metric("**信心指數**", f"{buy_confidence:.0f} / 100")
    ci2.metric("建議", conf_label)
    ci3.metric("技術評分", f"{tech_score_norm:.0f}")
    ci4.metric("20日機率", f"{prob20:.1f}%")
    ci5.metric("籌碼分", f"{flow_score:.0f}")
    ci6.metric("品質分", f"{quality:.0f}")
    st.caption("門檻：≥70 建議買進 ｜ 55-70 分批佈局 ｜ 40-55 觀望 ｜ <40 建議迴避")

    # ── 技術判斷摘要 ──
    st.markdown("---")
    st.markdown(f"### {ana['overall']}")
    cp = ana["current_price"]

    # 目標價
    t5l, t5h   = ana["target_5d"]
    t20l, t20h = ana["target_20d"]
    tc1, tc2, tc3, tc4 = st.columns(4)
    tc1.metric("現價",       f"${cp:.2f}")
    tc2.metric("5日目標",    f"${t5l:.2f}–${t5h:.2f}", f"{(t5h-cp)/cp*100:+.1f}%")
    tc3.metric("20日目標",   f"${t20l:.2f}–${t20h:.2f}", f"{(t20h-cp)/cp*100:+.1f}%")
    h52, l52 = ana.get("high_52w", cp), ana.get("low_52w", cp)
    pct_52 = (cp - l52) / (h52 - l52) * 100 if h52 != l52 else 50
    tc4.metric("52週位置", f"{pct_52:.0f}%", f"H:{h52:.0f} L:{l52:.0f}")

    # 訊號
    st.markdown("#### 📡 技術訊號")
    for sig in ana["signals"]:
        st.write(sig)

    # 支撐壓力 + 費波那契
    col_s, col_r, col_f = st.columns(3)
    with col_s:
        st.markdown("**短期支撐位**")
        for s in ana["supports"][:4]:
            dist = (s - cp) / cp * 100
            st.write(f"${s:.2f}  `{dist:+.1f}%`")
    with col_r:
        st.markdown("**短期壓力位**")
        for r in ana["resistances"][:4]:
            dist = (r - cp) / cp * 100
            st.write(f"${r:.2f}  `{dist:+.1f}%`")
    with col_f:
        st.markdown("**費波那契回撤（52週）**")
        fib = ana.get("fib_levels", {})
        for label, lvl in fib.items():
            dist = (lvl - cp) / cp * 100
            icon = "🔵" if lvl < cp else "🟠"
            st.write(f"{icon} {label}：${lvl:.2f}  `{dist:+.1f}%`")

    st.caption("⚠️ 以上為技術層面分析，請搭配基本面與籌碼綜合判斷。技術分析不保證準確。")

    # ── 指標教學說明 ──
    with st.expander("📖 各技術指標原理與判讀說明"):
        for key, exp in INDICATOR_EXPLANATIONS.items():
            st.markdown(f"**{exp['name']}**")
            st.caption(f"原理：{exp['principle']}")
            st.markdown(exp["how_to_read"])
            st.markdown("---")


# ============================================================
# 主函數
# ============================================================

def main():
    # 確保快取目錄存在（Streamlit Cloud 也需要）
    from pathlib import Path as _Path
    _Path("tw_quant_data").mkdir(exist_ok=True)

    initialize_session_state()

    st.markdown("""<style>
    .stTabs [data-baseweb="tab"] { font-size:13px; padding:8px 10px; }
    [data-testid="metric-container"] {
        background:#161b22; border:1px solid #30363d;
        border-radius:6px; padding:12px;
    }
    </style>""", unsafe_allow_html=True)

    st.title("📈 台股盤後量化分析平台")
    st.caption(
        "✨ **v3.0 真實數據版** | "
        "TWSE 三大法人 | FinMind 基本面 | RSS 新聞情緒 | 無模擬數據"
    )

    if st.session_state.universe_df.empty:
        st.info("👋 歡迎！請先從側邊欄載入市場資料")
        st.markdown("""
        ### 快速開始
        1. 點擊側邊欄 **🔄 載入上市** 或 **🌐 載入全市場**
        2. 調整 **⚖️ 因子權重** 和 **⭐ 特別關注產業**
        3. 在 **🔍 個股分析** 加入追蹤，自動載入基本面

        ### 資料來源（全部免費）
        - 股價: TWSE / TPEx OpenAPI
        - 三大法人 / 融資融券: TWSE 官方
        - 基本面: FinMind API（免費帳號）
        - 新聞情緒: RSS 關鍵字分析

        ⚠️ 本工具僅供個人研究，不構成投資建議
        """)
        if st.button("🚀 立即載入上市資料", type="primary"):
            load_market_data_action(include_tpex=False)
            st.rerun()
        return

    # 自動載入追蹤清單基本面
    load_watchlist_data()

    # ── 盤後自動更新提示（台灣時間 15:30 後）─────────────────────
    _now_tw = datetime.now(timezone(timedelta(hours=8)))
    _data_date = st.session_state.get("data_date", "")
    _today_str = _now_tw.strftime("%Y-%m-%d")
    if (
        _data_date
        and _data_date < _today_str
        and _now_tw.hour >= 15
        and _now_tw.minute >= 30
    ):
        _col_a, _col_b = st.columns([5, 1])
        _col_a.warning(
            f"⏰ 行情資料停留在 **{_data_date}**，今日盤後資料已可更新（台灣時間 {_now_tw.strftime('%H:%M')}）"
        )
        if _col_b.button("🔄 更新今日收盤", use_container_width=True, key="auto_refresh_btn"):
            load_market_data_action(include_tpex=True)
            st.rerun()

    # 渲染側邊欄
    filters = render_sidebar(st.session_state.universe_df)
    sc_category = "全部產業"  # 供應鏈篩選已移至 Tab 7，sidebar 不再設定

    # ── 模型計算（帶快取）─────────────────────────────────────────
    _w   = str(sorted(st.session_state.weights.items()))
    _p   = str(sorted(filters["preferred_groups"]))
    _sz  = str(len(st.session_state.universe_df))
    _fk  = str(sorted(st.session_state.stock_fundamentals.keys()))
    _ck  = hashlib.md5(f"{_w}{_p}{_sz}{_fk}".encode()).hexdigest()[:8]

    if st.session_state.model_cache_key != _ck or st.session_state.model_df_cached.empty:
        with st.spinner("🧮 計算量化指標中..."):
            fund_data = {**st.session_state.stock_fundamentals}
            fund_data.update({
                t: d["fundamental"]
                for t, d in st.session_state.watchlist_data.items()
                if "fundamental" in d
            })
            # 從追蹤清單取得新聞情緒 score（-1.0 ~ 1.0）
            sentiment_data = {
                t: d["news"]["sentiment"]["score"]
                for t, d in st.session_state.watchlist_data.items()
                if "news" in d and isinstance(d["news"].get("sentiment"), dict)
                   and d["news"]["sentiment"].get("score") is not None
            }
            inst = st.session_state.institutional_data
            model = QuantModel(st.session_state.weights)
            model_df = model.enrich_dataframe(
                st.session_state.universe_df,
                filters["preferred_groups"],
                inst_data        = inst.get("inst", {}),
                margin_data      = inst.get("margin", {}),
                fundamental_data = fund_data,
                sentiment_data   = sentiment_data,
            )

            # 重算 final_composite（籌碼+技術+基本面三面向加權）
            pg = filters["preferred_groups"]
            group_boost_series        = model_df["group"].apply(lambda g: 4.0 if g in pg else 0.0)
            completeness_bonus_series = model_df["complete_score"].apply(lambda c: 3.0 if c else 0.0)
            news_adj_series           = model_df["ticker"].apply(
                lambda t: float(max(-5.0, min(5.0, sentiment_data.get(t, 0) * 5)))
            )
            model_df["final_composite"] = (
                model_df["prob20"]        * 0.40
                + model_df["confidence"]  * 0.25
                + (100 - model_df["risk_score"]) * 0.20
                + model_df["composite_score"] * 0.15
                + group_boost_series
                + completeness_bonus_series
                + news_adj_series
            ).round(2)

            st.session_state.model_df_cached = model_df
            st.session_state.model_cache_key = _ck
    else:
        model_df = st.session_state.model_df_cached

    # ── 篩選 ──────────────────────────────────────────────────────
    filtered_df = apply_filters(model_df, filters)

    # ── 頂部指標卡 ────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("📋 符合筆數",   len(filtered_df))
    c2.metric("📊 平均20日訊號", format_percentage(filtered_df["prob20"].mean() if not filtered_df.empty else 0))
    c3.metric("⭐ 核心候選",   int((filtered_df["candidate_level"] == "核心候選").sum()) if not filtered_df.empty else 0)
    c4.metric("💪 平均信心度", format_percentage(filtered_df["confidence"].mean() if not filtered_df.empty else 0))
    real_fund_pct = (model_df["has_real_fund"].sum() / max(len(model_df), 1) * 100) if not model_df.empty else 0
    real_flow_pct = (model_df["has_real_flow"].sum() / max(len(model_df), 1) * 100) if not model_df.empty else 0
    c5.metric("✅ 真實數據率", f"{real_fund_pct:.0f}%/{real_flow_pct:.0f}%", help="基本面/籌碼真實數據比例")

    # ── 分頁 ──────────────────────────────────────────────────────
    tabs = st.tabs([
        "🏆 整體分析",
        "🌍 美股連動",
        "🔍 個股分析",
        "💼 持倉管理",
        "⭐ 追蹤清單",
        "🔥 熱度排行",
        "📊 產業瀏覽器",
        "⚙️ 模型設定",
        "🎯 潛力股",
        "📈 ETF 排行",
    ])

    # ========== Tab 0: 整體分析 ==========
    with tabs[0]:
        st.subheader("🏆 整體分析 - 多面向綜合推薦")
        if model_df.empty:
            st.warning("⚠️ 沒有資料，請先點擊左側「載入市場資料」")
        else:
            top10 = filtered_df.head(10).copy() if not filtered_df.empty else model_df.nlargest(10, "final_composite").copy()

            # ── 本週市場話題 → 受益族群 ───────────────────────────────
            with st.expander("📡 本週市場熱點話題（點選族群可在產業瀏覽器查看）", expanded=False):
                try:
                    _na = st.session_state.get("news_analyzer_obj")
                    if _na is None:
                        _na = NewsAnalyzer()
                        st.session_state["news_analyzer_obj"] = _na
                    _hot = _na.get_hot_topics()
                    if _hot:
                        for _ht in _hot[:6]:
                            _topic    = _ht["topic"]
                            _chains   = _ht["supply_chains"]
                            _headlines = _ht.get("headlines", [])
                            _ht_cols = st.columns([2] + [1] * min(len(_chains), 3))
                            _ht_cols[0].markdown(f"**{_topic}**")
                            for ci, sc in enumerate(_chains[:3], 1):
                                if _ht_cols[ci].button(sc, key=f"hot_{_topic}_{sc}",
                                                       use_container_width=True):
                                    st.session_state["sc_browser_type"] = "supply"
                                    st.session_state["sc_browser_key"]  = sc
                                    st.info(f"已選取「{sc}」，請切換到「📊 產業瀏覽器」Tab 查看")
                            if _headlines:
                                st.caption(f"↳ {_headlines[0][:60]}…" if len(_headlines[0]) > 60 else f"↳ {_headlines[0]}")
                    else:
                        st.caption("暫無近期產業新聞熱點（需要網路連線）")
                except Exception:
                    st.caption("新聞熱點載入失敗")

            # ── 近三日資金流向預測 ─────────────────────────────────────
            with st.expander("📊 近三日資金流向預測（新聞熱度 × 法人籌碼）", expanded=False):
                try:
                    _na2 = st.session_state.get("news_analyzer_obj") or NewsAnalyzer()
                    st.session_state["news_analyzer_obj"] = _na2
                    _inst_data = st.session_state.institutional_data.get("inst", {})
                    _flow_sigs = _na2.get_fund_flow_signals(days=3, institutional_data=_inst_data)
                    if _flow_sigs:
                        _theme_colors = {
                            "漲價受惠": "#ef5350", "缺貨缺料": "#ff9800",
                            "AI需求爆發": "#1f6feb", "車用電動車": "#26a69a", "地緣政治": "#9c27b0",
                        }
                        for _fs in _flow_sigs:
                            _fc1, _fc2, _fc3 = st.columns([2, 1, 2])
                            _color = _theme_colors.get(_fs["theme"], "#888")
                            _fc1.markdown(
                                f'<span style="background:{_color}22;color:{_color};padding:2px 8px;border-radius:4px;font-size:13px">'
                                f'{_fs["theme"]}</span>',
                                unsafe_allow_html=True,
                            )
                            _fc2.markdown(f'{_fs["direction"]}')
                            _flow_k = _fs.get("inst_flow_k", 0)
                            _fc3.caption(
                                f'新聞熱度 {_fs["heat_score"]}  |  '
                                f'法人 {_flow_k:+.0f}K張  |  '
                                + ("  ".join(_fs["tickers"][:3]) if _fs["tickers"] else "")
                            )
                    else:
                        st.caption("需要市場資料 + 新聞連線才能計算資金流向")
                except Exception:
                    st.caption("資金流向分析載入失敗")

            # ── 市場概況摘要 ──────────────────────────────────────────
            sc_label = f" ({sc_category})" if sc_category != "全部產業" else ""
            st.markdown(f"### 📊 市場概況摘要{sc_label}")
            tc1, tc2, tc3, tc4 = st.columns(4)
            _risers = (model_df["change_pct"] > 0).sum() if "change_pct" in model_df.columns else 0
            _fallers = (model_df["change_pct"] < 0).sum() if "change_pct" in model_df.columns else 0
            tc1.metric("今日上漲", f"{_risers} 支", help="收盤較前日上漲的股票數量")
            tc2.metric("今日下跌", f"{_fallers} 支", delta_color="inverse", help="收盤較前日下跌的股票數量")
            tc3.metric("核心候選", f"{(top10['candidate_level']=='核心候選').sum()}/10",
                       help="前10推薦中符合核心候選條件（基本面+技術+籌碼均偏多）的數量")
            _avg_rsk = top10["risk_score"].mean() if "risk_score" in top10.columns else 50
            tc4.metric("平均風險分", f"{_avg_rsk:.0f}/100",
                       delta_color="inverse",
                       help="0=極低風險，100=極高風險。<40偏穩健，>70需謹慎。")
            st.caption("⚠️ 以上指標為統計模型輸出，不構成投資建議。排序依籌碼+技術+基本面三面向綜合評估。")
            st.markdown("---")

            st.markdown("### 📋 推薦清單（依綜合評估排序）")
            for idx, (_, stock) in enumerate(top10.iterrows(), 1):
                emoji = {"核心候選": "⭐", "觀察候選": "👀", "高風險觀察": "⚠️"}.get(stock["candidate_level"], "🛡️")
                chg = stock.get("change_pct", 0) or 0
                chg_str = f"{'▲' if chg >= 0 else '▼'}{abs(chg):.2f}%"
                with st.expander(
                    f"**#{idx}** {emoji} **{stock['ticker']} {stock['name']}** | "
                    f"{chg_str} | {stock['group']} | {stock['market']}",
                    expanded=(idx <= 3),
                ):
                    # ── 行情摘要 ─────────────────────────────────────
                    pr1, pr2, pr3, pr4 = st.columns(4)
                    pr1.metric("收盤價", f"NT${stock['close']:.0f}" if pd.notna(stock.get("close")) else "--",
                               help="今日收盤價（元）")
                    pr2.metric("今日漲跌", chg_str, delta=f"{chg:+.2f}%",
                               help="今日漲跌幅。正值=上漲，負值=下跌。")
                    vol = stock.get("volume", 0) or 0
                    pr3.metric("成交量", f"{int(vol):,} 張" if vol > 0 else "--",
                               help="今日成交量（張=1000股）。成交量大代表市場關注度高。")
                    pr4.metric("風險等級", stock.get("candidate_level", "--"),
                               help="核心候選=多面向偏多；觀察候選=部分指標偏多；高風險=波動較大請謹慎。")

                    # ── 三面向信號 ───────────────────────────────────
                    s_inst, s_tech, s_fund = st.columns(3)

                    with s_inst:
                        st.markdown("**🏦 籌碼信號**")
                        _inst_d = st.session_state.institutional_data.get("inst", {}).get(stock["ticker"], {})
                        _fn = int(_inst_d.get("foreign_net", 0) or 0)
                        _tn = int(_inst_d.get("trust_net",   0) or 0)
                        _dn = int(_inst_d.get("dealer_net",  0) or 0)
                        if _fn > 0:   st.write(f"🟢 外資買超 {_fn:+,} 千股")
                        elif _fn < 0: st.write(f"🔴 外資賣超 {_fn:+,} 千股")
                        else:         st.write("⬜ 外資 持平/無資料")
                        if _tn > 0:   st.write(f"🟢 投信買超 {_tn:+,} 千股")
                        elif _tn < 0: st.write(f"🔴 投信賣超 {_tn:+,} 千股")
                        else:         st.write("⬜ 投信 持平/無資料")
                        ms = stock.get("flow_score", 50) or 50
                        st.caption(f"籌碼強度：{'強 🔥' if ms >= 70 else '弱 ❄️' if ms <= 30 else '中 ➡️'}")

                    with s_tech:
                        st.markdown("**📈 技術信號**")
                        _td = st.session_state.tech_data.get(stock["ticker"], {})
                        _ana = _td.get("analysis", {}) if _td else {}
                        _ind = _td.get("indicators", {}) if _td else {}
                        _rsi = _ana.get("rsi")
                        _macd_l = _ind.get("macd", [])
                        _macd_s = _ind.get("macd_signal", [])
                        if _rsi is not None:
                            rsi_lbl = "🔥 超買" if _rsi > 70 else "❄️ 超賣" if _rsi < 30 else "✅ 正常"
                            st.write(f"RSI {_rsi:.0f}：{rsi_lbl}")
                        if _macd_l and _macd_s:
                            cross = "⬆️ MACD 金叉" if _macd_l[-1] > _macd_s[-1] else "⬇️ MACD 死叉"
                            st.write(cross)
                        _bias20 = _ana.get("bias20")
                        if _bias20 is not None:
                            bias_lbl = "⚠️ 過熱" if _bias20 > 10 else "💡 超賣" if _bias20 < -10 else "✅ 正常"
                            st.write(f"MA20乖離 {_bias20:+.1f}%：{bias_lbl}")
                        ms2 = stock.get("momentum_score", 50) or 50
                        if not any([_rsi, _macd_l, _bias20]):
                            st.write(f"動能分：{'強 🔥' if ms2 >= 70 else '弱 ❄️' if ms2 <= 30 else '中 ➡️'} ({ms2:.0f}/100)")
                        st.caption("技術面以近期趨勢為主，不保證持續性。")

                    with s_fund:
                        st.markdown("**📊 基本面亮點**")
                        _fdata = st.session_state.stock_fundamentals.get(stock["ticker"]) or \
                                 st.session_state.watchlist_data.get(stock["ticker"], {}).get("fundamental") or {}
                        _pe  = _fdata.get("pe")
                        _gm  = _fdata.get("gross_margin")
                        _yoy = _fdata.get("revenue_yoy")
                        _dy  = _fdata.get("dividend_yield")
                        if _pe:
                            pe_lbl = "🏷️ 便宜" if _pe < 15 else "🟡 合理" if _pe < 25 else "🔴 偏貴"
                            st.write(f"本益比 {_pe:.1f}x：{pe_lbl}")
                        if _gm:
                            st.write(f"毛利率 {_gm:.1f}%：{'優秀 💎' if _gm > 40 else '正常 ✅' if _gm > 20 else '偏低 ⚠️'}")
                        if _yoy is not None:
                            st.write(f"營收年增 {_yoy:+.1f}%：{'成長 📈' if _yoy > 10 else '衰退 📉' if _yoy < -10 else '平穩 ➡️'}")
                        if _dy:
                            st.write(f"殖利率 {_dy:.1f}%：{'高息 💰' if _dy > 4 else '普通' if _dy > 2 else '低息'}")
                        if not any([_pe, _gm, _yoy]):
                            qs = stock.get("quality_score", 50) or 50
                            vs = stock.get("value_score", 50) or 50
                            st.write(f"品質分 {qs:.0f}/100　價值分 {vs:.0f}/100")
                            st.caption("尚無基本面資料（點選個股分析自動載入）")

                    # ── 新聞情緒 ──────────────────────────────────────
                    _ss = stock.get("sentiment_score")
                    if _ss is not None and pd.notna(_ss):
                        lbl = "🟢 正面" if _ss > 0.2 else "🔴 負面" if _ss < -0.2 else "🟡 中性"
                        st.caption(f"新聞情緒：{lbl}（分數 {_ss:+.2f}）| "
                                   + (" | ".join(
                                       [f"🟢{k}" for k in ["外資買超", "投信買超"]
                                        if (_fn > 0 and k == "外資買超") or (_tn > 0 and k == "投信買超")]
                                   ) or ""))

                    note = st.session_state.notes.get(stock["ticker"], "")
                    if note:
                        st.caption(f"📝 筆記：{note[:80]}{'...' if len(note) > 80 else ''}")
                    if stock.get("risk_score", 0) > 70:
                        st.warning("⚠️ 風險提醒：此股波動較大，請控制部位，勿重押。")

                    _btn_c1, _btn_c2 = st.columns(2)
                    with _btn_c1:
                        if st.button("🔍 個股分析", key=f"top10_goto_{stock['ticker']}",
                                     use_container_width=True):
                            st.session_state["goto_ticker"] = stock["ticker"]
                            st.rerun()
                    with _btn_c2:
                        _already_in = stock["ticker"] in st.session_state.watchlist
                        if not _already_in:
                            if st.button("⭐ 加入追蹤", key=f"top10_wl_{stock['ticker']}",
                                         use_container_width=True):
                                st.session_state.watchlist[stock["ticker"]] = {
                                    "name": stock["name"],
                                    "added_date": date.today().isoformat(),
                                }
                                write_json(WATCHLIST_FILE, st.session_state.watchlist)
                                st.session_state.model_cache_key = ""
                                st.rerun()
                        else:
                            st.caption("✅ 已追蹤")

            st.markdown("---")
            csv_cols = [c for c in ["ticker", "name", "market", "group", "close", "change_pct",
                                    "volume", "risk_score", "candidate_level"] if c in top10.columns]
            csv_data = top10[csv_cols].to_csv(index=False).encode("utf-8-sig")
            st.download_button("📥 下載推薦清單 CSV", csv_data,
                               file_name=f"top10_{date.today()}.csv", mime="text/csv")


        # ── 候選清單（整合至整體分析底部）──
        with st.expander("📋 完整候選清單（展開）", expanded=False):
            if not filtered_df.empty:
                _sc_note = f"（{sc_category}）" if sc_category != "全部產業" else ""
                st.caption(f"共 {len(filtered_df)} 筆{_sc_note}，依综合評估排序。")
                _bc = ["ticker","name","group","market","close","change_pct","volume","candidate_level"]
                _ac = [c for c in _bc if c in filtered_df.columns]
                _dd = filtered_df[_ac].copy().rename(columns={
                    "ticker":"代碼","name":"名稱","group":"產業","market":"市場",
                    "close":"收盤(元)","change_pct":"漲跌%","volume":"成交量(張)","candidate_level":"候選等級",
                })
                st.dataframe(_dd, use_container_width=True, height=400)
                _csv2 = filtered_df[_ac].to_csv(index=False).encode("utf-8-sig")
                st.download_button("📥 下載CSV", _csv2,
                                   file_name=f"candidates_{date.today()}.csv", mime="text/csv")
            else:
                st.info("⚠️ 請先載入市場資料")

    # ========== Tab 1: 美股連動 ==========
    with tabs[1]:
        st.subheader("🌍 美股連動分析")
        st.caption("資料來源：yfinance（免費，15分鐘延遲）｜每小時自動更新")

        # 載入美股資料
        us_loader = USMarketLoader()
        if st.button("🔄 更新美股資料", key="refresh_us"):
            st.session_state.us_market_data = {}
            st.session_state.us_market_ts   = 0

        us_data = st.session_state.get("us_market_data") or {}
        if not us_data or not us_data.get("indices"):
            with st.spinner("📡 載入美股資料..."):
                us_data = us_loader.get_market_data()
                st.session_state.us_market_data = us_data
                st.session_state.us_market_ts   = time.time()

        if "error" in us_data:
            st.error(f"⚠️ {us_data['error']}")
            st.info("請執行：`pip install yfinance`")
        else:
            sample_date = next(
                (v.get("date", "") for v in us_data.get("indices", {}).values() if v.get("date")),
                ""
            )
            date_label = f"資料日：{sample_date}（美東時間）" if sample_date else f"取得時間：{us_data.get('fetched_at', '')}"
            st.caption(f"資料來源：yfinance（15分鐘延遲）｜{date_label}｜每小時快取")

            # ── 大盤指數 ──
            st.markdown("### 📊 美股主要指數")
            idx_cols = st.columns(len(US_INDICES))
            for i, (ticker, name) in enumerate(US_INDICES.items()):
                d = us_data.get("indices", {}).get(ticker, {})
                if d:
                    chg = d["change_pct"]
                    color = "normal" if abs(chg) < 0.5 else ("inverse" if chg < 0 else "normal")
                    idx_cols[i].metric(
                        name,
                        f"{d['price']:,.2f}",
                        f"{chg:+.2f}%",
                        delta_color="normal" if chg >= 0 else "inverse",
                    )

            st.markdown("---")

            # ── 關鍵個股 ──
            st.markdown("### 💹 關鍵美股表現")
            us_rows = []
            for ticker, name in US_KEY_STOCKS.items():
                d = us_data.get("stocks", {}).get(ticker, {})
                if d:
                    chg = d["change_pct"]
                    us_rows.append({
                        "代碼": ticker, "公司": name,
                        "收盤價": d["price"],
                        "漲跌幅(%)": chg,
                        "方向": "▲" if chg > 0 else ("▼" if chg < 0 else "—"),
                    })
            if us_rows:
                us_df = pd.DataFrame(us_rows)
                st.dataframe(
                    us_df.style.map(
                        lambda v: "color: #ef5350" if isinstance(v, float) and v < 0
                        else ("color: #26a69a" if isinstance(v, float) and v > 0 else ""),
                        subset=["漲跌幅(%)"],
                    ),
                    use_container_width=True, hide_index=True,
                )

            st.markdown("---")

            # ── 影響分析 ──
            st.markdown("### 🔗 對台股產業鏈的影響預判")
            impacts = us_loader.analyze_impact(us_data)
            if impacts:
                for imp in impacts:
                    if imp["type"] == "macro":
                        st.info(imp["text"])
                    elif imp["type"] == "index":
                        chg = imp["change_pct"]
                        icon = "📈" if chg > 0 else "📉"
                        st.markdown(f"{icon} {imp['text']}")
                    else:  # stock
                        chg = imp["change_pct"]
                        color = "🟢" if chg > 0 else "🔴"
                        with st.expander(f"{color} {imp['text']}", expanded=abs(chg) >= 3):
                            tw_cols = st.columns(4)
                            for i, tw in enumerate(imp["tw_stocks"]):
                                tw_cols[i % 4].markdown(
                                    f"**{tw['ticker']} {tw['name']}**  \n`{tw['role']}`"
                                )

            st.markdown("---")

            # ── 宏觀環境儀表板 ──
            st.markdown("### 🌐 宏觀經濟儀表板")
            st.caption("資料來源：yfinance（WTI油價/美債/VIX/黃金/美元）｜1小時快取")
            with st.spinner("載入宏觀指標..."):
                macro_loader = MacroLoader()
                macro_snap   = macro_loader.get_snapshot()
                macro_impact = macro_loader.analyze_macro_impact(macro_snap)

            if macro_snap:
                mc_cols = st.columns(len(macro_snap))
                for i, (name, d) in enumerate(macro_snap.items()):
                    with mc_cols[i]:
                        chg = d.get("chg_pct")
                        chg_str = f"{chg:+.2f}%" if chg is not None else ""
                        label_txt = d.get("label", name)
                        unit_txt  = d.get("unit", "")
                        price_txt = f"{d['price']:.2f}{' ' + unit_txt if unit_txt else ''}"
                        st.metric(label_txt, price_txt, chg_str)

                st.markdown(f"**整體判斷：{macro_impact['overall']}**")
                for r in macro_impact.get("reasons", []):
                    st.markdown(f"- {r}")

                # 產業影響矩陣
                si = macro_impact.get("sector_impact", {})
                if si:
                    st.markdown("**台股各產業宏觀影響：**")
                    si_rows = [
                        {"產業": sec, "影響": v[0], "說明": v[1]}
                        for sec, v in si.items()
                    ]
                    st.dataframe(pd.DataFrame(si_rows), use_container_width=True, hide_index=True)
            else:
                st.info("⚠️ 無法取得宏觀指標（需安裝 yfinance）")

            st.markdown("---")

            # ── 大戶持股追蹤（SEC 13F）──
            with st.expander("🏦 大型機構持股追蹤（SEC 13F，僅供參考）", expanded=False):
                st.caption("13F 每季申報一次，有最長 45 天延遲。資料來源：SEC EDGAR（免費）。需安裝：`pip install edgartools`")
                tracker = InstitutionalTracker()
                if not tracker.has_edgar:
                    st.warning(f"⚠️ 未安裝 edgartools，請執行：`{tracker.install_hint()}`")
                else:
                    fund_choice = st.selectbox("選擇機構", list(TRACKED_FUNDS.keys()),
                                               key="fund_select_tab1")
                    with st.spinner(f"載入 {fund_choice} 13F 持倉..."):
                        holdings = tracker.get_holdings(fund_choice, top_n=20)
                        filing_dt = tracker.get_filing_date(fund_choice)

                    if holdings:
                        if filing_dt:
                            st.caption(f"最新申報日：{filing_dt}（截至當日持倉快照）")
                        h_rows = []
                        for h in holdings:
                            val_b = h["value_usd"] / 1e6 if h["value_usd"] else None
                            h_rows.append({
                                "股票":   h["company"],
                                "市值(百萬USD)": f"{val_b:.0f}" if val_b else "--",
                                "持倉%":  f"{h['pct_portfolio']:.2f}%" if h["pct_portfolio"] else "--",
                                "台股關聯": h["tw_related"] or "—",
                            })
                        h_df = pd.DataFrame(h_rows)
                        st.dataframe(h_df, use_container_width=True, hide_index=True)

                        # 台股相關持股特別標示
                        tw_related = [h for h in holdings if h.get("tw_related")]
                        if tw_related:
                            st.markdown("**與台股相關持股：**")
                            for h in tw_related:
                                st.markdown(f"- **{h['company']}**：{h['tw_related']}")
                    else:
                        st.info("⚠️ 暫無 13F 資料（可能網路問題或 Edgar API 限速）")

                    # 跨基金台股相關彙整
                    st.markdown("**所有追蹤基金 × 台股相關持股彙整：**")
                    with st.spinner("彙整所有基金台股相關持股..."):
                        all_tw = tracker.get_tw_related_holdings()
                    if all_tw:
                        tw_df = pd.DataFrame([{
                            "基金":  r["fund"],
                            "股票":  r["company"],
                            "台股關聯": r["tw_related"],
                            "持倉%": f"{r['pct_portfolio']:.2f}%" if r["pct_portfolio"] else "--",
                        } for r in all_tw])
                        st.dataframe(tw_df, use_container_width=True, hide_index=True)
                    else:
                        st.info("暫無台股相關持股資料")

            st.markdown("---")

            # ── 供應鏈映射完整表 ──
            st.markdown("### 📋 美股 → 台股供應鏈完整對照表")
            for us_ticker, chain in US_TW_SUPPLY_CHAIN.items():
                us_d = us_data.get("stocks", {}).get(us_ticker, {})
                chg_str = f"{us_d['change_pct']:+.2f}%" if us_d else "N/A"
                color_tag = "🟢" if us_d and us_d["change_pct"] > 0 else ("🔴" if us_d and us_d["change_pct"] < 0 else "⚪")
                with st.expander(f"{color_tag} {us_ticker} {chain['name']} ({chg_str}) — {chain['theme']}"):
                    tw_df = pd.DataFrame(chain["tw_stocks"])
                    st.dataframe(tw_df, use_container_width=True, hide_index=True)

            st.markdown("---")

            # ── 台灣產業上中下游鏈 ──
            st.markdown("### 🏭 台灣產業完整上中下游鏈（含潛力股）")
            for industry, chain in TW_INDUSTRY_CHAIN.items():
                with st.expander(f"🔷 {industry} 完整產業鏈"):
                    for stage, stocks_list in chain.items():
                        st.markdown(f"**{stage.replace('_', ' ')}**")
                        stage_rows = []
                        for s in stocks_list:
                            row_m = model_df[model_df["ticker"] == s["ticker"]] if not model_df.empty else pd.DataFrame()
                            prob20 = f"{row_m.iloc[0]['prob20']:.1f}%" if not row_m.empty else "—"
                            cand   = row_m.iloc[0]["candidate_level"]  if not row_m.empty else "—"
                            stage_rows.append({
                                "代碼": s["ticker"], "名稱": s["name"],
                                "說明": s["desc"], "20日機率": prob20, "候選等級": cand,
                            })
                        st.dataframe(pd.DataFrame(stage_rows), use_container_width=True, hide_index=True)

            st.markdown("---")

            # ── 總體事件 ──
            st.markdown("### 📰 近期總體經濟 / 地緣政治事件")
            st.caption("⚠️ 僅顯示新聞標題，影響判斷請自行閱讀原文")
            na = NewsAnalyzer()
            macro_news = na.fetch_macro_events()
            if not macro_news:
                st.info("⚠️ 無法取得 RSS 新聞（需安裝 feedparser 或網路問題）")
            else:
                by_cat = defaultdict(list)
                for n in macro_news:
                    by_cat[n["category"]].append(n)
                for cat, items in by_cat.items():
                    st.markdown(f"**{cat}**")
                    for item in items[:4]:
                        st.markdown(f"- [{item['title']}]({item['link']}) `{item['published'][:10]}`")

    # ========== Tab 2: 候選清單 ==========

    # ========== Tab 3: 個股分析 ==========
    with tabs[2]:
        st.subheader("個股分析")
        # 處理熱度排行/產業總覽的「完整分析」跳轉
        _goto = st.session_state.pop("goto_ticker", None)

        if filtered_df.empty and model_df.empty:
            st.warning("⚠️ 目前篩選條件下沒有資料")
        else:
            # 若 goto_ticker 不在目前過濾清單，暫時用 model_df 全清單
            _ticker_pool = (
                model_df["ticker"].tolist() if not model_df.empty
                else filtered_df["ticker"].tolist()
            )
            _filtered_pool = filtered_df["ticker"].tolist() if not filtered_df.empty else _ticker_pool

            if _goto and _goto in _ticker_pool:
                _default_pool = _ticker_pool if _goto not in _filtered_pool else _filtered_pool
                _default_idx  = _default_pool.index(_goto)
            else:
                _default_pool = _filtered_pool
                _default_idx  = 0

            selected_ticker = st.selectbox(
                "選擇個股",
                _default_pool,
                index=_default_idx,
                format_func=lambda t: (
                    f"{t} {model_df.loc[model_df['ticker']==t, 'name'].iloc[0]}"
                    if not model_df[model_df["ticker"] == t].empty else t
                ),
                key="stock_selector",
            )
            if model_df[model_df["ticker"] == selected_ticker].empty:
                st.warning(f"⚠️ 找不到 {selected_ticker} 的資料，請重新選擇")
                st.stop()
            stock = model_df[model_df["ticker"] == selected_ticker].iloc[0]

            # ── 標題與基本指標 ──
            sc1, sc2 = st.columns([3, 1])
            with sc1:
                st.markdown(f"### {stock['ticker']} {stock['name']}")
                st.caption(f"{stock['group']} | {stock['market']} | {stock['candidate_level']}")
            with sc2:
                in_wl = selected_ticker in st.session_state.watchlist
                if in_wl:
                    if st.button("❌ 移除追蹤", use_container_width=True):
                        del st.session_state.watchlist[selected_ticker]
                        st.session_state.watchlist_data.pop(selected_ticker, None)
                        st.session_state.stock_fundamentals.pop(selected_ticker, None)
                        write_json(WATCHLIST_FILE, st.session_state.watchlist)
                        st.session_state.model_cache_key = ""
                        st.rerun()
                else:
                    if st.button("⭐ 加入追蹤", use_container_width=True):
                        st.session_state.watchlist[selected_ticker] = {
                            "name": stock["name"],
                            "added_date": date.today().isoformat(),
                        }
                        write_json(WATCHLIST_FILE, st.session_state.watchlist)
                        st.success("✅ 已加入追蹤，下次啟動自動載入基本面")
                        st.rerun()

            # ── 行情摘要橫幅（取代6個分數 metric）──
            chg3 = stock.get("change_pct", 0) or 0
            close3 = stock.get("close") or 0
            vol3   = stock.get("volume", 0) or 0
            h52 = stock.get("high_52w") or st.session_state.stock_fundamentals.get(selected_ticker, {}).get("high_52w")
            l52 = stock.get("low_52w")  or st.session_state.stock_fundamentals.get(selected_ticker, {}).get("low_52w")
            bm1, bm2, bm3, bm4, bm5 = st.columns(5)
            bm1.metric("收盤價", f"NT${close3:,.0f}" if close3 else "--",
                       delta=f"{chg3:+.2f}%", help="今日收盤價（元）")
            bm2.metric("今日漲跌", f"{chg3:+.2f}%",
                       help="今日漲跌幅。正值=上漲，負值=下跌。台股漲跌幅限制±10%。")
            bm3.metric("成交量", f"{int(vol3):,} 張" if vol3 else "--",
                       help="今日成交量（張=1,000股）。量大代表市場活躍；縮量下跌或放量上漲需關注。")
            bm4.metric("52週高點", f"NT${h52:,.0f}" if h52 else "--",
                       help="過去一年最高收盤價。若目前股價接近52週高點，代表強勢；遠低於高點需了解原因。")
            bm5.metric("52週低點", f"NT${l52:,.0f}" if l52 else "--",
                       help="過去一年最低收盤價。若股價接近52週低點，需確認是否有基本面問題。")

            # ── 整體信號判斷橫幅 ──────────────────────────────────
            _sig_count_pos = _sig_count_neg = 0
            _inst3 = st.session_state.institutional_data.get("inst", {}).get(selected_ticker, {})
            if (_inst3.get("foreign_net") or 0) > 0: _sig_count_pos += 1
            else: _sig_count_neg += 1
            if (_inst3.get("trust_net") or 0) > 0: _sig_count_pos += 1
            else: _sig_count_neg += 1
            _td3 = st.session_state.tech_data.get(selected_ticker, {})
            _ana3 = _td3.get("analysis", {}) if _td3 else {}
            _rsi3 = _ana3.get("rsi")
            _ml3  = _td3.get("indicators", {}).get("macd", []) if _td3 else []
            _ms3  = _td3.get("indicators", {}).get("macd_signal", []) if _td3 else []
            if _rsi3 and 30 < _rsi3 < 70: _sig_count_pos += 1
            elif _rsi3: _sig_count_neg += 1
            if _ml3 and _ms3:
                if _ml3[-1] > _ms3[-1]: _sig_count_pos += 1
                else: _sig_count_neg += 1
            _ss3 = stock.get("sentiment_score")
            if _ss3 is not None and pd.notna(_ss3):
                if _ss3 > 0.1: _sig_count_pos += 1
                elif _ss3 < -0.1: _sig_count_neg += 1

            _total3 = _sig_count_pos + _sig_count_neg
            if _total3 > 0:
                if _sig_count_pos >= _total3 * 0.7:
                    st.success(f"🟢 **多方傾向**（{_sig_count_pos}/{_total3} 項指標偏多）— 謹慎樂觀，注意進出場時機")
                elif _sig_count_neg >= _total3 * 0.7:
                    st.error(f"🔴 **空方傾向**（{_sig_count_neg}/{_total3} 項指標偏空）— 保守觀望，留意下行風險")
                else:
                    st.info(f"🟡 **多空分歧**（{_sig_count_pos} 多 / {_sig_count_neg} 空）— 方向不明，等待更清晰信號")
            st.caption("⚠️ 信號判斷為統計模型評估，不構成投資建議。操作前請自行評估風險與部位。")

            # ── 數據載入狀態（精簡版）──────────────────────────────
            has_fund = stock.get("has_real_fund", False)
            has_flow = stock.get("has_real_flow", False)
            _status_tags = []
            if has_fund: _status_tags.append("✅ 基本面")
            else:        _status_tags.append("⚠️ 基本面(估算)")
            if has_flow: _status_tags.append("✅ 法人籌碼")
            else:        _status_tags.append("⚠️ 籌碼(估算)")
            st.caption("資料狀態：" + " | ".join(_status_tags))

            # ── 子分頁（基本面 / 技術面 / 籌碼 / 新聞操作）──
            epsfv   = {}
            val_pct = {}
            _stabs = st.tabs(["📊 基本面", "📈 技術面", "🏦 籌碼", "💬 新聞/操作"])

            with _stabs[0]:  # ── 基本面（fund + 月季趨勢 + YTP + EPS 公平價）
                # ── 基本面 ──
                st.markdown("---")
                st.markdown("#### 📊 基本面（Yahoo Finance 主力 / FinMind 補月營收）")

                fund_key = selected_ticker
                if fund_key in st.session_state.stock_fundamentals:
                    render_fundamental_block(st.session_state.stock_fundamentals[fund_key])
                elif selected_ticker in st.session_state.watchlist_data and \
                        st.session_state.watchlist_data[selected_ticker].get("fundamental"):
                    render_fundamental_block(
                        st.session_state.watchlist_data[selected_ticker].get("fundamental", {})
                    )
                else:
                    with st.spinner("📊 自動載入基本面（Yahoo Finance）..."):
                        fm = FinMindLoader(token=st.session_state.get("finmind_token", ""))
                        fdata = fm.get_fundamental(selected_ticker)
                        st.session_state.stock_fundamentals[selected_ticker] = fdata
                        st.session_state.model_cache_key = ""
                    render_fundamental_block(fdata)

                # ── 月/季趨勢 ──
                if selected_ticker in st.session_state.stock_fundamentals:
                    st.markdown("---")
                    st.markdown("#### 📈 月營收 + 季報趨勢（FinMind）")
                    fm_trend = FinMindLoader(token=st.session_state.get("finmind_token", ""))
                    rev_trend = fm_trend.get_revenue_trend(selected_ticker)
                    fin_trend = fm_trend.get_financial_trend(selected_ticker)

                    tc1, tc2 = st.columns(2)
                    with tc1:
                        if rev_trend:
                            rev_df = pd.DataFrame(rev_trend)
                            fig_rev = go.Figure()
                            fig_rev.add_bar(x=rev_df["month"], y=rev_df["revenue"],
                                            name="月營收", marker_color="royalblue", opacity=0.7)
                            if rev_df["yoy_pct"].notna().any():
                                fig_rev.add_scatter(x=rev_df["month"], y=rev_df["yoy_pct"],
                                                    name="YoY%", yaxis="y2",
                                                    line=dict(color="orange", width=2))
                            fig_rev.update_layout(
                                title="月營收趨勢（柱=金額，線=YoY%）",
                                yaxis2=dict(overlaying="y", side="right", showgrid=False),
                                height=300, margin=dict(t=40, b=20),
                            )
                            st.plotly_chart(fig_rev, use_container_width=True)
                            # 月營收數字表
                            tbl_rev = rev_df[["month", "revenue", "yoy_pct", "mom_pct"]].copy()
                            tbl_rev.columns = ["月份", "月營收(千元)", "年增%", "月增%"]
                            tbl_rev["月營收(千元)"] = tbl_rev["月營收(千元)"].apply(
                                lambda x: f"{int(x):,}" if pd.notna(x) else "--"
                            )
                            for col in ["年增%", "月增%"]:
                                tbl_rev[col] = tbl_rev[col].apply(
                                    lambda x: f"{x:+.1f}%" if pd.notna(x) else "--"
                                )
                            st.dataframe(
                                tbl_rev.sort_values("月份", ascending=False).reset_index(drop=True),
                                use_container_width=True, hide_index=True, height=220,
                            )
                        else:
                            st.info("⚠️ 無月營收資料（需 FinMind token 且已加入追蹤）")

                    with tc2:
                        if fin_trend:
                            fin_df = pd.DataFrame(fin_trend)
                            fig_fin = go.Figure()
                            if fin_df["eps"].notna().any():
                                fig_fin.add_bar(x=fin_df["quarter"], y=fin_df["eps"],
                                                name="EPS", marker_color="#26a69a", opacity=0.8)
                            if fin_df["gross_margin"].notna().any():
                                fig_fin.add_scatter(x=fin_df["quarter"], y=fin_df["gross_margin"],
                                                    name="毛利率%", yaxis="y2",
                                                    line=dict(color="purple", width=2))
                            fig_fin.update_layout(
                                title="季報 EPS（柱）+ 毛利率（線）",
                                yaxis2=dict(overlaying="y", side="right", showgrid=False),
                                height=300, margin=dict(t=40, b=20),
                            )
                            st.plotly_chart(fig_fin, use_container_width=True)
                            # 季報數字表
                            tbl_fin = fin_df[["quarter", "eps", "gross_margin", "net_margin"]].copy()
                            tbl_fin.columns = ["季度", "EPS(元)", "毛利率%", "淨利率%"]
                            for col in ["EPS(元)", "毛利率%", "淨利率%"]:
                                tbl_fin[col] = tbl_fin[col].apply(
                                    lambda x: f"{x:.2f}" if pd.notna(x) else "--"
                                )
                            st.dataframe(
                                tbl_fin.sort_values("季度", ascending=False).reset_index(drop=True),
                                use_container_width=True, hide_index=True, height=220,
                            )
                        else:
                            st.info("⚠️ 無季報資料")

                    # ── 基本面摘要 ──
                    summary_parts = []
                    if rev_trend:
                        last_rev = rev_trend[-1]
                        yoy = last_rev.get("yoy_pct")
                        mom = last_rev.get("mom_pct")
                        yoy_txt = f"年增 **{yoy:+.1f}%**" if yoy is not None else "年增資料不足"
                        mom_txt = f"，月增 {mom:+.1f}%" if mom is not None else ""
                        summary_parts.append(
                            f"- 月營收（{last_rev.get('month','--')}）：{yoy_txt}{mom_txt}"
                        )
                    if fin_trend:
                        eps_vals = [q["eps"] for q in fin_trend if q.get("eps") is not None]
                        gm_vals  = [q["gross_margin"] for q in fin_trend if q.get("gross_margin") is not None]
                        if eps_vals:
                            eps_dir = ("↑ 成長" if eps_vals[-1] > eps_vals[0] else "↓ 下滑") if len(eps_vals) >= 2 else ""
                            summary_parts.append(f"- 最近季 EPS：**{eps_vals[-1]:.2f} 元** {eps_dir}".strip())
                        if gm_vals:
                            gm_dir = ("擴張" if gm_vals[-1] > gm_vals[0] else "收縮") if len(gm_vals) >= 2 else ""
                            summary_parts.append(f"- 毛利率：**{gm_vals[-1]:.1f}%**（近期{gm_dir}）" if gm_dir else f"- 毛利率：**{gm_vals[-1]:.1f}%**")
                    if summary_parts:
                        st.markdown("**📋 基本面摘要**")
                        st.markdown("\n".join(summary_parts))
                        st.caption("⚠️ 以上為歷史財務數據，僅供研究參考，不構成投資建議。")

                    # ── YTP 三率趨勢 + 歷史分位數 ──
                    st.markdown("---")
                    st.markdown("#### 📊 PE／PB／殖利率歷史分位數（估值高低估判斷）")
                    with st.spinner("載入 YTP 三率趨勢..."):
                        fm_val = FinMindLoader(token=st.session_state.get("finmind_token", ""))
                        per_trend = fm_val.get_per_trend(selected_ticker, months=36)
                        val_pct   = fm_val.get_valuation_percentile(selected_ticker)

                    if per_trend:
                        per_df = pd.DataFrame(per_trend)
                        fig_per = go.Figure()
                        if per_df["pe"].notna().any():
                            fig_per.add_scatter(x=per_df["date"], y=per_df["pe"],
                                                name="本益比(PE)", line=dict(color="royalblue", width=2))
                        if per_df["pb"].notna().any():
                            fig_per.add_scatter(x=per_df["date"], y=per_df["pb"],
                                                name="本淨比(PB)", yaxis="y2",
                                                line=dict(color="orange", width=2, dash="dot"))
                        if per_df["dy"].notna().any():
                            fig_per.add_scatter(x=per_df["date"], y=per_df["dy"],
                                                name="殖利率%", yaxis="y3",
                                                line=dict(color="green", width=2, dash="dash"))
                        fig_per.update_layout(
                            title="PE / PB / 殖利率 近36個月趨勢",
                            height=320, margin=dict(t=40, b=20),
                            yaxis=dict(title="PE", side="left"),
                            yaxis2=dict(title="PB", overlaying="y", side="right", showgrid=False),
                            yaxis3=dict(title="殖利率%", overlaying="y", side="right",
                                        anchor="free", position=1.0, showgrid=False),
                            legend=dict(orientation="h", y=-0.2),
                        )
                        st.plotly_chart(fig_per, use_container_width=True)
                    else:
                        st.info("⚠️ 無 PE/PB/殖利率歷史資料（需 FinMind 有效 token）")

                    # 分位數橫條
                    st.markdown(f"**估值判斷：{val_pct.get('status', '--')}**")
                    st.caption(val_pct.get("suggestion", ""))
                    pct_cols = st.columns(3)
                    for col, (label, key, curr_key, low_good) in zip(pct_cols, [
                        ("本益比 PE",  "pe_pct",  "pe_curr",  True),
                        ("本淨比 PB",  "pb_pct",  "pb_curr",  True),
                        ("殖利率 DY",  "dy_pct",  "dy_curr",  False),
                    ]):
                        with col:
                            pct  = val_pct.get(key)
                            curr = val_pct.get(curr_key)
                            curr_str = f"{curr:.1f}" if curr is not None else "--"
                            if pct is not None:
                                bar_color = (
                                    "🟢" if (low_good and pct < 30) or (not low_good and pct < 30)
                                    else "🔴" if (low_good and pct > 70) or (not low_good and pct > 70)
                                    else "🟡"
                                )
                                st.metric(label, curr_str, f"歷史 {pct:.0f}% 分位")
                                st.progress(int(pct) / 100, text=f"{bar_color} {'低估' if pct < 30 else '高估' if pct > 70 else '合理'}")
                            else:
                                st.metric(label, curr_str, "分位資料不足")

                    # ── EPS 公平價估算 ──────────────────────────────────
                    st.markdown("---")
                    st.markdown("#### 💡 EPS 公平價估算（歷史 PE 分位 × 近四季 EPS）")
                    fm_epsfv = FinMindLoader(token=st.session_state.get("finmind_token", ""))
                    epsfv = fm_epsfv.get_eps_fair_value(selected_ticker)
                    if epsfv.get("has_data"):
                        curr_price = stock.get("close")
                        ev1, ev2, ev3 = st.columns(3)
                        ev1.metric("保守價（PE 25th）", f"{epsfv['fair_low']:.1f}",
                                   help=f"PE {epsfv['pe_25']}x × EPS {epsfv['eps']:.2f}元")
                        ev2.metric("合理價（PE 中位）", f"{epsfv['fair_mid']:.1f}",
                                   help=f"PE {epsfv['pe_50']}x × EPS {epsfv['eps']:.2f}元",
                                   delta=f"目前 {((curr_price / epsfv['fair_mid'] - 1) * 100):+.1f}%" if curr_price and epsfv['fair_mid'] else None)
                        ev3.metric("樂觀價（PE 75th）", f"{epsfv['fair_high']:.1f}",
                                   help=f"PE {epsfv['pe_75']}x × EPS {epsfv['eps']:.2f}元")

                        if curr_price:
                            if curr_price < epsfv["fair_low"]:
                                st.success(f"✅ 目前股價 {curr_price:.1f} 元低於保守估值，具備安全邊際")
                            elif curr_price < epsfv["fair_mid"]:
                                st.info(f"🟡 目前股價 {curr_price:.1f} 元介於保守與合理估值之間，偏合理")
                            elif curr_price < epsfv["fair_high"]:
                                st.warning(f"🟡 目前股價 {curr_price:.1f} 元高於合理中位（{epsfv['fair_mid']:.1f}），需留意估值風險")
                            else:
                                st.error(f"🔴 目前股價 {curr_price:.1f} 元超過樂觀估值（{epsfv['fair_high']:.1f}），追高風險高")
                        st.caption("⚠️ 公平價係根據過去3年PE中位數×近四季EPS估算，僅供研究，不構成投資建議。")
                    else:
                        st.caption("⚠️ EPS 公平價估算需要 FinMind 財報資料（token + 加入追蹤後自動更新）")


            with _stabs[1]:  # ── 技術面（K線 + 操作區間 + 訊號）
                # ── 技術分析 ──
                st.markdown("---")
                st.markdown("#### 📈 技術分析（FinMind 歷史數據）")
                _ta_result = None
                if selected_ticker in st.session_state.tech_data:
                    _ta_result = st.session_state.tech_data[selected_ticker]
                    render_tech_block(_ta_result, stock.to_dict())
                    if st.button("🔄 重新載入技術分析", key=f"reload_tech_{selected_ticker}"):
                        st.session_state.tech_data.pop(selected_ticker, None)
                        st.rerun()
                else:
                    with st.spinner("📈 自動載入技術分析（120日K線）..."):
                        fm = FinMindLoader(token=st.session_state.get("finmind_token", ""))
                        price_df = fm.get_price_history(selected_ticker, days=120)
                        ta = tech_analyze(price_df, selected_ticker, stock["name"])
                        st.session_state.tech_data[selected_ticker] = ta
                        _ta_result = ta
                    if ta:
                        render_tech_block(ta, stock.to_dict())
                    else:
                        st.warning("⚠️ 無法取得歷史 K 線資料（可能為上櫃新股或 API 暫無數據）")

                # ── 綜合操作區間 ──
                if _ta_result and _ta_result.get("analysis"):
                    _analysis = _ta_result["analysis"]
                    _curr     = _analysis.get("current_price") or stock.get("close")
                    _supports = _analysis.get("supports", [])
                    _resists  = _analysis.get("resistances", [])
                    _rsi      = _analysis.get("rsi")
                    _bias20   = _analysis.get("bias20")
                    _kd_cross = _analysis.get("kd_cross", False)

                    # 取 EPS fair value（若基本面區塊已填充，否則為空 dict）
                    _epsfv = epsfv
                    _vp    = val_pct

                    st.markdown("---")
                    st.markdown("#### 📍 操作價格區間參考")
                    st.caption("⚠️ 以下價格區間整合技術面支撐壓力 + 基本面估值，僅供研究，不構成投資建議。")

                    with st.expander("展開操作區間分析", expanded=True):
                        # 計算四個區間
                        _buy_low  = _supports[-1] if _supports else (_curr * 0.90 if _curr else None)
                        _buy_high = _supports[0]  if len(_supports) >= 1 else (_curr * 0.95 if _curr else None)
                        _exit_low = _resists[0]   if _resists else (_curr * 1.08 if _curr else None)
                        _exit_high = _resists[1]  if len(_resists) >= 2 else (_exit_low * 1.03 if _exit_low else None)
                        _stop     = _supports[-1] if len(_supports) >= 2 else (_curr * 0.92 if _curr else None)

                        # 若有基本面估值，用 fair_mid 修正觀望/出清邊界
                        _fair_mid  = _epsfv.get("fair_mid")  if _epsfv.get("has_data") else None
                        _fair_high = _epsfv.get("fair_high") if _epsfv.get("has_data") else None
                        _pe_pct    = _vp.get("pe_pct")

                        def _pstr(v):
                            return f"{v:.1f}" if v is not None else "--"

                        # ─ 買進區 ─
                        _buy_reasons = []
                        if _supports:
                            _buy_reasons.append(f"接近支撐位（{_pstr(_buy_high)} 元附近）")
                        if _pe_pct is not None and _pe_pct < 35:
                            _buy_reasons.append(f"PE 在歷史 {_pe_pct:.0f}% 分位（偏低估）")
                        if _analysis.get("bias20") is not None and _analysis["bias20"] < -8:
                            _buy_reasons.append(f"MA20 乖離率 {_analysis['bias20']:.1f}%（超賣區）")
                        if _kd_cross:
                            _buy_reasons.append("KD 黃金交叉")

                        # ─ 出清區 ─
                        _exit_reasons = []
                        if _resists:
                            _exit_reasons.append(f"接近壓力位（{_pstr(_exit_low)} 元附近）")
                        if _fair_high is not None:
                            _exit_reasons.append(f"超過樂觀估值（{_pstr(_fair_high)} 元）")
                        if _pe_pct is not None and _pe_pct > 70:
                            _exit_reasons.append(f"PE 在歷史 {_pe_pct:.0f}% 分位（偏高估）")
                        if _rsi is not None and _rsi > 70:
                            _exit_reasons.append(f"RSI {_rsi:.1f}（超買）")
                        if _bias20 is not None and _bias20 > 12:
                            _exit_reasons.append(f"MA20 乖離率 +{_bias20:.1f}%（過熱）")

                        # 顯示四格卡片
                        z1, z2, z3, z4 = st.columns(4)
                        with z1:
                            st.markdown("🟢 **積極買進區**")
                            st.markdown(f"**{_pstr(_buy_low)} — {_pstr(_buy_high)} 元**")
                            for r in (_buy_reasons or ["技術支撐附近"]):
                                st.caption(f"• {r}")
                        with z2:
                            _hold_lo = _buy_high or _curr
                            _hold_hi = _fair_mid or (_curr * 1.03 if _curr else None)
                            st.markdown("🟡 **分批介入 / 持有**")
                            st.markdown(f"**{_pstr(_hold_lo)} — {_pstr(_hold_hi)} 元**")
                            st.caption(f"• PE 合理區")
                            if _fair_mid:
                                st.caption(f"• 合理估值中位 {_pstr(_fair_mid)} 元附近")
                        with z3:
                            _watch_lo = _hold_hi or _curr
                            _watch_hi = _exit_low
                            st.markdown("⚪ **觀望 / 持股待漲**")
                            st.markdown(f"**{_pstr(_watch_lo)} — {_pstr(_watch_hi)} 元**")
                            st.caption("• 技術面仍偏多，但估值趨中性")
                            st.caption("• 宜縮小新增部位")
                        with z4:
                            st.markdown("🔴 **逢高分批出清**")
                            st.markdown(f"**{_pstr(_exit_low)} 元以上**")
                            for r in (_exit_reasons or ["接近技術壓力區"]):
                                st.caption(f"• {r}")

                        st.markdown("---")
                        _stop_reason = f"支撐失守（{_pstr(_stop)} 元）" if _stop else "技術破位"
                        st.error(f"🔴 **止損參考**：{_pstr(_stop)} 元  ｜  理由：{_stop_reason}")

            # ── 蒙地卡羅 GBM 20 日股價模擬 ─────────────────────────────
            if _ta_result and _ta_result.get("analysis"):
                _ana_mc   = _ta_result["analysis"]
                _atr_mc   = _ana_mc.get("atr")
                _close_mc = _ana_mc.get("current_price") or stock.get("close")
                if _close_mc and _close_mc > 0 and _atr_mc and _atr_mc > 0:
                    _sigma_mc = (_atr_mc / _close_mc) * (252 ** 0.5)  # 年化波動率
                    _mo_score = stock.get("momentum_score", 50) or 50
                    _mu_mc    = (_mo_score - 50) / 50 * 0.3             # 動能轉年化漂移
                    _mc_res   = QuantModel.monte_carlo_price(
                        _close_mc, _sigma_mc, mu=_mu_mc, days=20, n_sim=800
                    )
                    if _mc_res:
                        st.markdown("---")
                        st.markdown("#### 🎲 蒙地卡羅模擬（20日）")
                        st.caption(
                            f"GBM 模型 800 路徑，年化波動率 {_mc_res['sigma_used']:.1f}%。"
                            "歷史模擬，不代表未來報酬，不構成投資建議。"
                        )
                        _mc_c1, _mc_c2, _mc_c3, _mc_c4 = st.columns(4)
                        _mc_c1.metric("上漲機率", f"{_mc_res['prob_up']:.1f}%")
                        _mc_c2.metric("P10（悲觀）", f"{_mc_res['p10']:.1f}")
                        _mc_c3.metric("P50（中位）", f"{_mc_res['p50']:.1f}",
                                      delta=f"{_mc_res['expected_return']:+.1f}%")
                        _mc_c4.metric("P90（樂觀）", f"{_mc_res['p90']:.1f}")

                        # 簡單區間長條圖
                        _mc_fig = go.Figure()
                        _mc_fig.add_bar(
                            x=["P10", "P25", "P50", "P75", "P90"],
                            y=[_mc_res["p10"], _mc_res["p25"], _mc_res["p50"],
                               _mc_res["p75"], _mc_res["p90"]],
                            marker_color=["#ef5350", "#ff9800", "#1f6feb", "#4caf50", "#26a69a"],
                        )
                        _mc_fig.add_hline(y=_close_mc, line_dash="dash", line_color="gray",
                                          annotation_text=f"現價 {_close_mc:.1f}")
                        _mc_fig.update_layout(
                            title="20日後股價分位數分布",
                            height=250, margin=dict(t=40, b=20),
                            showlegend=False,
                        )
                        st.plotly_chart(_mc_fig, use_container_width=True)

                # ── 買入/賣出訊號 ──
                st.markdown("---")
                st.markdown("#### 🎯 買入/賣出訊號")
                _engine = SignalEngine()
                _tech_for_signal = st.session_state.tech_data.get(selected_ticker)
                _sig = _engine.get_signal(stock.to_dict(), _tech_for_signal)
                sig_c1, sig_c2, sig_c3 = st.columns(3)
                sig_c1.metric("訊號", _sig["label"])
                sig_c2.metric("信心度", f"{_sig['confidence']:.0f}%")
                sig_c3.metric("評分路徑", _sig["scoring_path"])
                st.markdown("**買進理由：**")
                for r in _sig["reasons"]:
                    st.write(r)
                if _sig["caution"]:
                    st.markdown("**注意事項：**")
                    for c in _sig["caution"]:
                        st.warning(c)


            with _stabs[2]:  # ── 籌碼（三大法人 + 融資融券）
                # ── 籌碼 ──
                st.markdown("---")
                st.markdown("#### 💰 籌碼（TWSE 三大法人 + 融資融券）")
                render_flow_block(stock.to_dict(), show_reload=True)


            with _stabs[3]:  # ── 新聞/筆記/信號彙整
                # ── 新聞情緒 ──
                st.markdown("---")
                st.markdown("#### 📰 新聞情緒（RSS，近 7 天）")
                news_key = selected_ticker
                if news_key in st.session_state.watchlist_data and \
                        st.session_state.watchlist_data[news_key].get("news"):
                    render_news_block(st.session_state.watchlist_data[news_key].get("news", {}))
                else:
                    with st.spinner("📰 自動載入新聞情緒（RSS）..."):
                        na = NewsAnalyzer()
                        nd = na.get_stock_news_sentiment(selected_ticker, stock["name"])
                        if selected_ticker not in st.session_state.watchlist_data:
                            st.session_state.watchlist_data[selected_ticker] = {}
                        st.session_state.watchlist_data[selected_ticker]["news"] = nd
                    render_news_block(nd)

                # ── 個人筆記 ──
                st.markdown("---")
                st.subheader("📝 個人研究筆記")
                current_note = st.session_state.notes.get(selected_ticker, "")
                new_note = st.text_area("筆記內容", current_note, height=150,
                                        placeholder="研究想法、觀察重點、進出場理由...",
                                        key=f"note_{selected_ticker}")
                if st.button("💾 保存筆記"):
                    st.session_state.notes[selected_ticker] = new_note
                    write_json(NOTES_FILE, st.session_state.notes)
                    st.success("✅ 筆記已保存")

                # ── 即時信號彙整 ──
                st.markdown("---")
                with st.expander("📡 即時信號彙整（籌碼 / 融資券 / 新聞媒體）", expanded=False):
                    _inst_row = st.session_state.institutional_data.get("inst", {}).get(selected_ticker, {})
                    _marg_row = st.session_state.institutional_data.get("margin", {}).get(selected_ticker, {})
                    _news_d   = st.session_state.watchlist_data.get(selected_ticker, {}).get("news", {})

                    # 籌碼動向
                    st.markdown("**三大法人今日淨買賣（千股）**")
                    st.caption("正值=買超、負值=賣超。外資長線影響最大；投信買超通常帶動短中期動能；自營商多為短線避險。")
                    ci1, ci2, ci3 = st.columns(3)
                    fn_v = int(_inst_row.get("foreign_net", 0) or 0)
                    tn_v = int(_inst_row.get("trust_net",   0) or 0)
                    dn_v = int(_inst_row.get("dealer_net",  0) or 0)
                    ci1.metric("外資", f"{fn_v:+,}", help="外資今日淨買超（正=買超/負=賣超），單位千股。外資連續買超通常是多頭訊號。")
                    ci2.metric("投信", f"{tn_v:+,}", help="投信（國內基金）今日淨買超，持續買超常帶動短中期行情。")
                    ci3.metric("自營商", f"{dn_v:+,}", help="自營商今日淨買超，多為短線避險操作，參考性較低。")

                    # 融資融券
                    if _marg_row:
                        st.markdown("**融資融券（張）**")
                        st.caption("融資增加=散戶用槓桿買進（過熱警訊）；融券增加=放空張數增加（可能有軋空行情）。")
                        mr1, mr2, mr3, mr4 = st.columns(4)
                        mr1.metric("融資餘額", f"{int(_marg_row.get('margin_balance', 0) or 0):,}",
                                   help="目前融資未還清張數。餘額過高代表市場過熱，下跌時容易引發斷頭賣壓。")
                        mr2.metric("融資變化", f"{int(_marg_row.get('margin_change',  0) or 0):+,}",
                                   help="今日融資增減張數。連續增加需注意籌碼過熱風險。")
                        mr3.metric("融券餘額", f"{int(_marg_row.get('short_balance',  0) or 0):,}",
                                   help="目前空單未回補張數。融券大增代表空方看壞；若空頭回補則可能軋空上漲。")
                        mr4.metric("融券變化", f"{int(_marg_row.get('short_change',   0) or 0):+,}",
                                   help="今日融券增減張數。大量回補（負值）可能帶動股價上漲。")

                    # 技術信號
                    _td = st.session_state.tech_data.get(selected_ticker, {})
                    if _td and isinstance(_td, dict):
                        st.markdown("**技術信號**")
                        _analysis = _td.get("analysis", {})
                        _indicators = _td.get("indicators", {})
                        rsi_v = _analysis.get("rsi")
                        macd_list = _indicators.get("macd", [])
                        macd_sig_list = _indicators.get("macd_signal", [])
                        macd_v = macd_list[-1] if macd_list else None
                        macd_sig = macd_sig_list[-1] if macd_sig_list else None
                        if rsi_v is not None:
                            rsi_lbl = "🔥 超買(>70)" if rsi_v > 70 else ("❄️ 超賣(<30)" if rsi_v < 30 else "正常區間")
                            st.write(f"RSI(14)：**{rsi_v:.1f}** — {rsi_lbl}（RSI 衡量近期漲跌強度，>70 過熱，<30 過冷）")
                        if macd_v is not None and macd_sig is not None:
                            cross = "⬆️ 金叉（多頭）" if macd_v > macd_sig else "⬇️ 死叉（空頭）"
                            st.write(f"MACD：{cross}（MACD 金叉代表短均線上穿長均線，為買入信號；死叉相反）")
                        # 其他技術信號列表
                        tech_signals = _analysis.get("signals", [])
                        if tech_signals:
                            st.caption("其他信號：" + " | ".join(tech_signals[:4]))

                    # 最新媒體報導
                    news_list = _news_d.get("news", []) if isinstance(_news_d, dict) else []
                    if news_list:
                        st.markdown("**最新媒體報導（前5則）**")
                        for n in news_list[:5]:
                            src_icon = {"yfinance": "📰", "google_news": "🗞️", "ptt_stock": "💬",
                                        "moneydj": "💹"}.get(n.get("source", ""), "📄")
                            src_name = n.get("source", "").replace("youtube_", "📺 ")
                            if "youtube_" in n.get("source", ""):
                                src_icon = "📺"
                            st.markdown(
                                f"{src_icon} [{n['title']}]({n.get('link','#')}) "
                                f"<small style='color:gray'>({n.get('published','')[:10]} · {src_name})</small>",
                                unsafe_allow_html=True,
                            )
                    elif selected_ticker not in st.session_state.watchlist:
                        st.info("將此股票加入追蹤清單後，系統會自動抓取新聞與情緒資料。")


    # ========== Tab 4: 持倉管理 ==========
    with tabs[3]:
        st.subheader("💼 我的持倉管理")
        port: Portfolio = st.session_state.portfolio

        # ── 新增持倉 ──
        with st.expander("➕ 新增 / 更新持倉", expanded=not port.get_holdings()):
            pa, pb_col, pc, pd_col, pe_col = st.columns(5)
            with pa:
                p_ticker = st.text_input("股票代號", placeholder="例: 2330", key="port_ticker").strip().upper()
            with pb_col:
                p_name = st.text_input("公司名稱", placeholder="例: 台積電", key="port_name").strip()
            with pc:
                p_shares = st.number_input("持有股數", min_value=1, value=1000, step=100, key="port_shares")
            with pd_col:
                p_buy_price = st.number_input("買入均價", min_value=0.01, value=100.0, step=0.5, key="port_buy_price")
            with pe_col:
                p_buy_date = st.date_input("買入日期", value=date.today(), key="port_buy_date")

            if st.button("💾 加入持倉", use_container_width=True, key="add_holding_btn"):
                if p_ticker:
                    # auto-fill name from model_df if available
                    if not p_name and not model_df.empty:
                        match = model_df[model_df["ticker"] == p_ticker]
                        if not match.empty:
                            p_name = match.iloc[0]["name"]
                    port.add_holding(p_ticker, p_name or p_ticker, p_shares, p_buy_price, p_buy_date.isoformat())
                    st.success(f"✅ 已加入 {p_ticker} {p_name}")
                    st.rerun()
                else:
                    st.warning("請輸入股票代號")

        holdings = port.get_holdings()

        if not holdings:
            st.info("目前沒有持倉。點擊上方「➕ 新增 / 更新持倉」加入第一筆。")
        else:
            # Build current prices dict from model_df
            prices = {}
            if not model_df.empty:
                for _, r in model_df.iterrows():
                    if r.get("close") is not None:
                        try:
                            prices[r["ticker"]] = float(r["close"])
                        except (TypeError, ValueError):
                            pass

            pnl_list = port.calculate_pnl(prices)

            # ── 總覽 ──
            summary = port.total_pnl_summary(pnl_list)
            s1, s2, s3, s4, s5 = st.columns(5)
            s1.metric("持倉檔數", summary["holding_count"])
            s2.metric("總成本", f"${summary['total_cost']:,.0f}")
            s3.metric("現值", f"${summary['total_value']:,.0f}" if summary["total_value"] else "N/A")
            pnl_delta = f"{summary['total_pnl_pct']:+.2f}%" if summary["total_pnl_abs"] is not None else None
            s4.metric("總損益", f"${summary['total_pnl_abs']:+,.0f}" if summary["total_pnl_abs"] is not None else "N/A", pnl_delta)
            s5.metric("獲利/虧損", f"{summary['winner_count']}勝/{summary['loser_count']}負")

            st.markdown("---")

            # ── 各股明細 ──
            for entry in sorted(pnl_list, key=lambda x: x.get("pnl_pct") or 0, reverse=True):
                ticker = entry["ticker"]
                pnl_pct = entry.get("pnl_pct")
                pnl_abs = entry.get("pnl_abs")
                cp      = entry.get("current_price")

                pnl_color = "🟢" if pnl_pct and pnl_pct > 0 else ("🔴" if pnl_pct and pnl_pct < 0 else "⚪")
                pnl_str   = f"{pnl_pct:+.2f}%" if pnl_pct is not None else "N/A"

                stock_row = model_df[model_df["ticker"] == ticker] if not model_df.empty else pd.DataFrame()
                stock_data = stock_row.iloc[0].to_dict() if not stock_row.empty else {}

                with st.expander(
                    f"{pnl_color} **{ticker} {entry['name']}** — 損益 {pnl_str} | 持有 {entry.get('hold_days', 0)} 天",
                    expanded=False,
                ):
                    c1, c2, c3, c4, c5 = st.columns(5)
                    c1.metric("買入均價",  f"${entry['buy_price']:.2f}",
                              help="你當初買進這檔股票的平均價格")
                    c2.metric("目前股價", f"${cp:.2f}" if cp else "N/A",
                              help="今日收盤價（從市場資料取得）")
                    c3.metric("獲利/虧損%", pnl_str,
                              delta_color="normal" if (pnl_pct or 0) >= 0 else "inverse",
                              help="相對買入價格的漲跌幅。正數=賺錢，負數=虧損")
                    c4.metric("獲利/虧損金額", f"${pnl_abs:+,.0f}" if pnl_abs is not None else "N/A",
                              help="實際賺或虧的金額（元）")
                    c5.metric("投入成本", f"${entry['cost']:,.0f}",
                              help="你買這檔股票花了多少錢（買入均價 × 股數）")

                    st.markdown("---")

                    # ── 策略建議（白話）──
                    st.markdown("#### 💡 目前建議怎麼做？")
                    suggestion = port.get_strategy_suggestion(entry, stock_data)
                    st.info(suggestion)

                    # ── 這檔股票現況分析（白話）──
                    if stock_data:
                        st.markdown("#### 📊 這檔股票目前狀況")
                        p1, p2, p3, p4 = st.columns(4)
                        prob20 = stock_data.get("prob20", 50)
                        prob60 = stock_data.get("prob60", 50)
                        conf   = stock_data.get("confidence", 50)
                        risk   = stock_data.get("risk_score", 50)
                        risk_label = "低（穩定）" if risk < 40 else ("中等" if risk < 65 else "高（容易大漲大跌）")

                        p1.metric("未來1個月漲機率", f"{prob20:.0f}%",
                                  help="模型預測未來1個月股價上漲的可能性\n>60% 看多　50% 中性　<40% 看空")
                        p2.metric("未來3個月趨勢", f"{prob60:.0f}%",
                                  help="模型預測未來3個月的趨勢方向\n長線投資人的參考指標")
                        p3.metric("預測可靠性", f"{conf:.0f}%",
                                  help=">70% 訊號較可靠\n<50% 不確定性高，建議觀望")
                        p4.metric("波動風險", risk_label,
                                  help="這檔股票容不容易突然大漲或大跌\n低 = 穩定；高 = 容易劇烈波動，需控制部位")

                        # ── 財務體質（有基本面時才顯示）──
                        has_fund = stock_data.get("has_real_fund", False)
                        if has_fund:
                            st.markdown("#### 📋 公司財務體質")
                            f1, f2, f3, f4 = st.columns(4)
                            pe = stock_data.get("pe")
                            eps = stock_data.get("eps")
                            gm  = stock_data.get("gross_margin")
                            ry  = stock_data.get("revenue_yoy")
                            f1.metric("本益比（PE）",
                                      f"{pe:.1f}倍" if pe else "N/A",
                                      help="股價是每年獲利的幾倍\n<15倍偏便宜　15-25倍合理　>30倍偏貴")
                            f2.metric("每股獲利（EPS）",
                                      f"${eps:.2f}" if eps else "N/A",
                                      help="每一股每年賺多少元\n越高越好，負數代表虧損")
                            f3.metric("毛利率",
                                      f"{gm:.1f}%" if gm else "N/A",
                                      help="賣出產品扣掉直接成本後還剩多少比例\n>30% 不錯　>50% 護城河很強")
                            f4.metric("營收年增率",
                                      f"{ry:+.1f}%" if ry else "N/A",
                                      help="比去年同期營收多或少多少\n正數成長中　負數衰退中")
                        else:
                            st.caption("⚠️ 尚無財務數據。前往「🔍 個股分析」加入追蹤，系統會自動載入財務資料。")

                        # ── 模型建議訊號 ──
                        st.markdown("#### 🎯 模型買賣建議")
                        engine = SignalEngine()
                        sig = engine.get_signal(stock_data)
                        sig_col1, sig_col2 = st.columns([1, 2])
                        with sig_col1:
                            st.metric("建議動作", sig["label"])
                            st.metric("建議可靠度", f"{sig['confidence']:.0f}%",
                                      help=">70% 訊號明確　50-70% 普通　<50% 不確定")
                        with sig_col2:
                            st.markdown("**理由：**")
                            for r in sig["reasons"][:4]:
                                st.write(r)
                            if sig.get("caution"):
                                st.markdown("**注意：**")
                                for c in sig["caution"][:2]:
                                    st.warning(c)

                    st.markdown("---")
                    # 刪除按鈕
                    if st.button(f"🗑️ 移除持倉 {ticker} {entry['name']}", key=f"rm_{ticker}"):
                        port.remove_holding(ticker)
                        st.rerun()

    # ========== Tab 5: 追蹤清單 ==========
    with tabs[4]:
        st.subheader("⭐ 追蹤清單")

        if not st.session_state.watchlist:
            st.info("目前沒有追蹤個股。\n\n前往「🔍 個股分析」點擊 **⭐ 加入追蹤** 按鈕。")
        else:
            wl_tickers = list(st.session_state.watchlist.keys())
            # 顯示追蹤清單概覽
            wl_rows = []
            for t in wl_tickers:
                row_in_model = model_df[model_df["ticker"] == t]
                added = st.session_state.watchlist[t].get("added_date", "")
                has_fund = t in st.session_state.watchlist_data
                if not row_in_model.empty:
                    r = row_in_model.iloc[0]
                    wl_rows.append({
                        "代碼": t,
                        "名稱": r["name"],
                        "加入日期": added,
                        "20日機率(%)": r["prob20"],
                        "期望報酬(%)": r.get("expected_return_20d"),
                        "信心度(%)": r["confidence"],
                        "風險": r["risk_score"],
                        "候選等級": r["candidate_level"],
                        "基本面": "✅" if has_fund else "⚠️",
                    })
                else:
                    wl_rows.append({
                        "代碼": t, "名稱": st.session_state.watchlist[t].get("name", t),
                        "加入日期": added, "20日機率(%)": None, "期望報酬(%)": None,
                        "信心度(%)": None, "風險": None, "候選等級": "待計算", "基本面": "⚠️",
                    })

            wl_df = pd.DataFrame(wl_rows)
            st.dataframe(wl_df, use_container_width=True)

            # 重新載入基本面按鈕
            if st.button("🔄 重新載入所有追蹤個股基本面"):
                st.session_state.watchlist_data = {}
                st.session_state.model_cache_key = ""
                st.rerun()

            st.markdown("---")
            st.markdown("### 🔍 追蹤個股詳細分析")

            selected_wl = st.selectbox(
                "選擇追蹤個股",
                wl_tickers,
                format_func=lambda t: f"{t} {st.session_state.watchlist[t].get('name', '')}",
                key="wl_selector",
            )

            row_in_model = model_df[model_df["ticker"] == selected_wl]
            if row_in_model.empty:
                st.warning("此股票不在目前市場資料中，請重新載入市場資料")
            else:
                wl_stock = row_in_model.iloc[0]
                st.markdown(f"#### {wl_stock['ticker']} {wl_stock['name']}")
                st.caption(f"{wl_stock['group']} | {wl_stock['market']} | {wl_stock['candidate_level']}")

                wc1, wc2, wc3, wc4, wc5 = st.columns(5)
                wc1.metric("20日機率", f"{wl_stock['prob20']:.1f}%")
                wc2.metric("期望報酬", f"{wl_stock['expected_return_20d']:+.1f}%" if pd.notna(wl_stock.get("expected_return_20d")) else "N/A")
                wc3.metric("信心度",   f"{wl_stock['confidence']:.1f}%")
                wc4.metric("風險",     f"{wl_stock['risk_score']:.0f}")
                wc5.metric("收盤價",   f"${wl_stock['close']:.2f}" if wl_stock.get('close') is not None else "--")

                # 基本面
                st.markdown("##### 📊 基本面")
                if selected_wl in st.session_state.watchlist_data:
                    render_fundamental_block(
                        st.session_state.watchlist_data[selected_wl].get("fundamental", {})
                    )
                else:
                    st.info("⚠️ 載入中...")

                # 籌碼
                st.markdown("##### 💰 籌碼")
                render_flow_block(wl_stock.to_dict())

                # 新聞
                st.markdown("##### 📰 新聞情緒")
                if selected_wl in st.session_state.watchlist_data:
                    render_news_block(
                        st.session_state.watchlist_data[selected_wl].get("news", {})
                    )
                else:
                    st.info("⚠️ 載入中...")

                # ── 財報更新 → 續抱評估 ─────────────────────────────────────
                _wl_meta = st.session_state.watchlist.get(selected_wl, {})
                _prev_eps = _wl_meta.get("last_seen_eps")
                _prev_q   = _wl_meta.get("last_seen_quarter", "")
                _fund_wl  = (st.session_state.watchlist_data.get(selected_wl, {}).get("fundamental")
                             or st.session_state.stock_fundamentals.get(selected_wl) or {})
                _curr_eps = _fund_wl.get("eps")
                _curr_pe  = _fund_wl.get("pe")
                _curr_gm  = _fund_wl.get("gross_margin")
                _curr_yoy = _fund_wl.get("revenue_yoy")

                if _curr_eps is not None:
                    _eps_updated = (_prev_eps is not None and abs(_curr_eps - _prev_eps) > 0.01)
                    if _eps_updated:
                        st.warning(f"🆕 **財報更新偵測**：EPS 從 {_prev_eps:.2f} → {_curr_eps:.2f} 元（{_prev_q} 以來）")

                    with st.expander("📋 續抱評估（點擊展開）", expanded=_eps_updated):
                        if _prev_eps is not None and abs(_prev_eps) > 0.01:
                            _eps_chg = (_curr_eps - _prev_eps) / abs(_prev_eps) * 100
                        else:
                            _eps_chg = None

                        st.markdown(f"**目前 EPS：{_curr_eps:.2f} 元**")
                        if _eps_chg is not None:
                            st.metric("EPS 變化（vs 上次記錄）", f"{_curr_eps:.2f}",
                                      delta=f"{_eps_chg:+.1f}%",
                                      delta_color="normal" if _eps_chg > 0 else "inverse")

                        if _curr_pe is not None:
                            pe_lbl = "🏷️ 偏低" if _curr_pe < 15 else "🟡 合理" if _curr_pe < 25 else "🔴 偏高"
                            st.write(f"PE：{_curr_pe:.1f}x — {pe_lbl}")
                        if _curr_gm is not None:
                            st.write(f"毛利率：{_curr_gm:.1f}%")
                        if _curr_yoy is not None:
                            st.write(f"月營收 YoY：{_curr_yoy:+.1f}%")

                        # 簡單決策樹
                        if _eps_chg is not None:
                            if _eps_chg > 20 and (_curr_pe or 99) < 20:
                                verdict = "🟢 建議：可續抱或考慮加碼，EPS 強勁成長且 PE 合理"
                            elif _eps_chg > 5:
                                verdict = "🟡 建議：可續抱，EPS 成長中，注意 PE 是否偏高"
                            elif _eps_chg < -15 and (_curr_pe or 0) > 25:
                                verdict = "🔴 建議：考慮減倉，EPS 衰退且估值偏高"
                            elif _eps_chg < 0:
                                verdict = "🟡 建議：觀察，EPS 小幅下降，追蹤下季確認趨勢"
                            else:
                                verdict = "⚪ 建議：持平觀望，EPS 變化不大"
                        elif _curr_pe is not None:
                            if _curr_pe < 12:
                                verdict = "🟢 估值偏低，有安全邊際"
                            elif _curr_pe > 30:
                                verdict = "🟡 估值偏高，控制部位"
                            else:
                                verdict = "⚪ 估值合理，持續追蹤"
                        else:
                            verdict = "⚪ 資料不足，請載入基本面後評估"

                        st.info(verdict)

                        if st.button("✅ 更新基準（記錄目前 EPS）", key=f"update_eps_{selected_wl}"):
                            st.session_state.watchlist[selected_wl]["last_seen_eps"] = _curr_eps
                            st.session_state.watchlist[selected_wl]["last_seen_quarter"] = date.today().strftime("%Y-Q?")
                            st.session_state.watchlist[selected_wl]["last_eval_date"] = date.today().isoformat()
                            write_json(WATCHLIST_FILE, st.session_state.watchlist)
                            st.success(f"✅ 已記錄 {selected_wl} EPS 基準：{_curr_eps:.2f}")
                            st.rerun()

                # 移除追蹤
                if st.button(f"❌ 移除 {selected_wl} 的追蹤", key=f"rm_wl_{selected_wl}"):
                    del st.session_state.watchlist[selected_wl]
                    st.session_state.watchlist_data.pop(selected_wl, None)
                    st.session_state.stock_fundamentals.pop(selected_wl, None)
                    write_json(WATCHLIST_FILE, st.session_state.watchlist)
                    st.session_state.model_cache_key = ""
                    st.rerun()


        # ── 基本面彙整（自選股跨公司比較）──
        with st.expander("📊 基本面彙整 — 自選股跨公司比較（展開）", expanded=False):
            st.subheader("📊 基本面彙整 — 自選股跨公司比較")
            st.caption("⚠️ 財務數據來自 FinMind / Yahoo Finance，僅供研究參考，不構成投資建議。")

            wl = st.session_state.get("watchlist", {})
            if not wl:
                st.info("⭐ 請先在「追蹤清單」Tab 加入自選股，再回此頁查看跨公司比較。")
            else:
                fm_fund = FinMindLoader(token=st.session_state.get("finmind_token", ""))
                tickers = list(wl.keys())

                # ── 批次載入（帶 session 快取）──
                if "fundsummary_cache" not in st.session_state:
                    st.session_state["fundsummary_cache"] = {}

                missing_rev = [t for t in tickers if f"rev_{t}" not in st.session_state["fundsummary_cache"]]
                missing_fin = [t for t in tickers if f"fin_{t}" not in st.session_state["fundsummary_cache"]]

                if missing_rev or missing_fin:
                    with st.spinner(f"載入 {len(tickers)} 檔自選股基本面（首次需時較長，後續快取）..."):
                        for t in tickers:
                            if f"rev_{t}" not in st.session_state["fundsummary_cache"]:
                                st.session_state["fundsummary_cache"][f"rev_{t}"] = fm_fund.get_revenue_trend(t, months=13)
                            if f"fin_{t}" not in st.session_state["fundsummary_cache"]:
                                st.session_state["fundsummary_cache"][f"fin_{t}"] = fm_fund.get_financial_trend(t, quarters=8)

                # 整理名稱對照
                name_map = {t: wl[t].get("name", t) for t in tickers}

                st.markdown("---")

                # ── 區塊 1：月營收 YoY% 矩陣 ──
                st.markdown("#### 📅 月營收年增率（YoY%）比較")
                rev_rows = {}
                all_months = set()
                for t in tickers:
                    trend = st.session_state["fundsummary_cache"].get(f"rev_{t}", [])
                    if trend:
                        rev_rows[t] = {r["month"]: r.get("yoy_pct") for r in trend}
                        all_months.update(rev_rows[t].keys())

                if rev_rows:
                    sorted_months = sorted(all_months, reverse=True)[:13]
                    rev_matrix = {}
                    for t in tickers:
                        if t not in rev_rows:
                            continue
                        label = f"{t} {name_map[t]}"
                        row = {}
                        for m in sorted_months:
                            val = rev_rows[t].get(m)
                            row[m] = f"{val:+.1f}%" if val is not None else "--"
                        rev_matrix[label] = row
                    if rev_matrix:
                        rev_mat_df = pd.DataFrame(rev_matrix).T
                        rev_mat_df = rev_mat_df[sorted_months]
                        # 標色：正增長綠、負增長紅
                        def _color_yoy(val):
                            if val == "--" or not isinstance(val, str):
                                return ""
                            try:
                                num = float(val.replace("%", "").replace("+", ""))
                                if num > 10:
                                    return "background-color:#d4edda; color:#155724"
                                if num > 0:
                                    return "background-color:#e8f5e9; color:#1b5e20"
                                if num < -10:
                                    return "background-color:#f8d7da; color:#721c24"
                                if num < 0:
                                    return "background-color:#fff3cd; color:#856404"
                            except Exception:
                                pass
                            return ""
                        st.dataframe(
                            rev_mat_df.style.map(_color_yoy),
                            use_container_width=True,
                            height=min(60 + len(rev_matrix) * 35, 400),
                        )
                        st.caption("綠：正成長 ｜ 紅：負成長 ｜ 深色：>±10%")
                    else:
                        st.info("⚠️ 無月營收資料（需 FinMind token 或資料尚未更新）")
                else:
                    st.info("⚠️ 無月營收資料（需 FinMind token 或資料尚未更新）")

                st.markdown("---")

                # ── 區塊 2：季 EPS 比較表 ──
                st.markdown("#### 📈 近 8 季 EPS（元）比較")
                fin_rows = {}
                all_quarters = set()
                for t in tickers:
                    trend = st.session_state["fundsummary_cache"].get(f"fin_{t}", [])
                    if trend:
                        fin_rows[t] = {r["quarter"]: r.get("eps") for r in trend}
                        all_quarters.update(fin_rows[t].keys())

                if fin_rows:
                    sorted_quarters = sorted(all_quarters, reverse=True)[:8]
                    eps_matrix = {}
                    for t in tickers:
                        if t not in fin_rows:
                            continue
                        label = f"{t} {name_map[t]}"
                        row = {}
                        for q in sorted_quarters:
                            val = fin_rows[t].get(q)
                            row[q] = f"{val:.2f}" if val is not None else "--"
                        eps_matrix[label] = row
                    if eps_matrix:
                        eps_mat_df = pd.DataFrame(eps_matrix).T
                        eps_mat_df = eps_mat_df[sorted_quarters]
                        st.dataframe(eps_mat_df, use_container_width=True,
                                     height=min(60 + len(eps_matrix) * 35, 400))
                    else:
                        st.info("⚠️ 無季報 EPS 資料")
                else:
                    st.info("⚠️ 無季報 EPS 資料")

                st.markdown("---")

                # ── 區塊 3：最新基本面快照 ──
                st.markdown("#### 🔢 最新基本面快照")
                snap_rows = []
                for t in tickers:
                    fd = st.session_state.get("watchlist_data", {}).get(t, {}).get("fundamental")
                    if fd is None:
                        fd = fm_fund.get_fundamental(t)
                    rev_t = st.session_state["fundsummary_cache"].get(f"rev_{t}", [])
                    latest_yoy = rev_t[-1].get("yoy_pct") if rev_t else None
                    latest_month = rev_t[-1].get("month", "--") if rev_t else "--"
                    snap_rows.append({
                        "代號": t,
                        "名稱": name_map[t],
                        f"最新月YoY%\n({latest_month})": f"{latest_yoy:+.1f}%" if latest_yoy is not None else "--",
                        "EPS(元)": f"{fd.get('eps'):.2f}" if fd.get("eps") is not None else "--",
                        "PE": f"{fd.get('pe'):.1f}" if fd.get("pe") is not None else "--",
                        "PB": f"{fd.get('pb'):.2f}" if fd.get("pb") is not None else "--",
                        "殖利率%": f"{fd.get('dividend_yield'):.2f}%" if fd.get("dividend_yield") is not None else "--",
                        "毛利率%": f"{fd.get('gross_margin'):.1f}%" if fd.get("gross_margin") is not None else "--",
                        "淨利率%": f"{fd.get('net_margin'):.1f}%" if fd.get("net_margin") is not None else "--",
                        "ROE%": f"{fd.get('roe'):.1f}%" if fd.get("roe") is not None else "--",
                        "資料來源": fd.get("data_source", "--"),
                    })
                if snap_rows:
                    st.dataframe(pd.DataFrame(snap_rows), use_container_width=True, hide_index=True)
                st.caption("⚠️ 所有財務數據均為歷史資料，不構成個人化投資建議。")

                # ── 重新整理按鈕 ──
                if st.button("🔄 重新載入自選股基本面", key="fundsummary_refresh"):
                    st.session_state.pop("fundsummary_cache", None)
                    st.rerun()



    # ========== Tab 6: 熱度排行 ==========
    with tabs[5]:
        st.subheader("🔥 產業熱度排行")
        if model_df.empty:
            st.warning("⚠️ 請先載入市場資料")
        else:
            heat_df = QuantModel(st.session_state.weights).calculate_industry_heat(model_df, SUPPLY_CHAIN_GROUPS)
            if heat_df.empty:
                st.info("載入全市場資料後，熱度指數將自動計算。")
            else:
                # ── 排行榜 Bar Chart ──────────────────────────────────
                st.markdown("#### 📊 產業熱度排行榜（籌碼 35% + 技術 35% + 新聞 20% + 漲跌 10%）")
                top_n = min(len(heat_df), 20)
                heat_top = heat_df.head(top_n).iloc[::-1]  # 反轉讓最熱的在頂部
                bar_colors = [
                    f"rgba({int(255*(1-h/100))},{int(80+h*0.5)},{int(80*(1-h/100))},0.85)"
                    for h in heat_top["heat_index"]
                ]
                fig_heat = go.Figure(go.Bar(
                    x=heat_top["heat_index"],
                    y=heat_top["group"],
                    orientation="h",
                    marker_color=bar_colors,
                    text=heat_top["heat_index"].apply(lambda v: f"{v:.0f}"),
                    textposition="outside",
                    hovertemplate=(
                        "<b>%{y}</b><br>"
                        "熱度: %{x:.1f}<br>"
                        "<extra></extra>"
                    ),
                ))
                fig_heat.update_layout(
                    height=max(300, top_n * 28),
                    margin=dict(l=10, r=60, t=10, b=10),
                    xaxis=dict(range=[0, 105], title="熱度指數"),
                    yaxis=dict(tickfont=dict(size=11)),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_heat, use_container_width=True)
                st.caption("熱度指數越高代表市場資金與注意力越集中於該產業。分數僅反映當日籌碼與技術狀態，不代表未來走勢，請勿作為單一買賣依據。")

                # ── 熱度分解表 ───────────────────────────────────────
                st.markdown("#### 📋 熱度分解明細")
                st.caption(
                    "🔥熱度 = 籌碼35% + 技術35% + 新聞20% + 漲跌10%，均為0–100分。"
                    "籌碼：外資+投信×2+自營加總；技術：動能分；新聞：情緒分；漲跌：近日漲跌幅換算。"
                )
                heat_display = heat_df.rename(columns={
                    "group": "產業/概念",
                    "heat_index": "🔥熱度(0-100)",
                    "inst_score": "籌碼分",
                    "tech_score": "技術分",
                    "news_score": "新聞分",
                    "price_score": "漲跌分",
                    "stock_count": "成分股數",
                    "avg_change": "均漲跌%",
                    "top_gainers": "漲幅前3股",
                })
                st.dataframe(heat_display, use_container_width=True, height=400)

                # ── 供應鏈個股儀表板 ─────────────────────────────────
                st.markdown("---")
                st.markdown("#### 🔍 供應鏈個股儀表板")
                sel_group = st.selectbox(
                    "選擇產業/概念",
                    heat_df["group"].tolist(),
                    key="heat_sel_group",
                )
                if sel_group:
                    grp_tickers = SUPPLY_CHAIN_GROUPS.get(sel_group, [])
                    grp_df = model_df[model_df["ticker"].isin(grp_tickers)].copy()
                    if grp_df.empty:
                        st.info("目前載入的市場資料中未包含此供應鏈的股票，請先載入全市場。")
                    else:
                        # 顯示欄位
                        list_cols = ["ticker", "name", "close", "change_pct", "volume",
                                     "foreign_net", "trust_net", "prob20", "momentum_score"]
                        avail_cols = [c for c in list_cols if c in grp_df.columns]
                        disp = grp_df[avail_cols].rename(columns={
                            "ticker": "代號", "name": "名稱",
                            "close": "收盤", "change_pct": "漲跌%",
                            "volume": "成交量(張)", "foreign_net": "外資淨(千股)",
                            "trust_net": "投信淨(千股)", "prob20": "20日機率%",
                            "momentum_score": "動能分",
                        })
                        # 信號欄
                        def _heat_signal(row):
                            chips = []
                            fn = row.get("外資淨(千股)", 0) or 0
                            if fn > 0:  chips.append("🟢外資↑")
                            elif fn < 0: chips.append("🔴外資↓")
                            sc = row.get("動能分", 50) or 50
                            if sc >= 70:   chips.append("⚡動能強")
                            elif sc <= 30: chips.append("📉動能弱")
                            return " ".join(chips) if chips else "—"
                        disp["信號"] = disp.apply(_heat_signal, axis=1)
                        st.dataframe(
                            disp.sort_values("漲跌%", ascending=False, key=lambda x: pd.to_numeric(x, errors="coerce")),
                            use_container_width=True,
                            height=350,
                        )

                        # 個股快速展開
                        st.markdown("**點選個股查看信號摘要**")
                        sel_ticker_heat = st.selectbox(
                            "個股",
                            grp_df["ticker"].tolist(),
                            format_func=lambda t: f"{t} {grp_df.loc[grp_df['ticker']==t,'name'].values[0] if not grp_df.loc[grp_df['ticker']==t,'name'].empty else ''}",
                            key="heat_sel_ticker",
                        )
                        if sel_ticker_heat:
                            srow = grp_df[grp_df["ticker"] == sel_ticker_heat].iloc[0]
                            with st.expander(f"📡 {sel_ticker_heat} 信號摘要", expanded=True):
                                m1, m2, m3, m4 = st.columns(4)
                                m1.metric("收盤", f"{srow.get('close', '-')}",
                                          help="今日收盤價（元）")
                                chg = srow.get("change_pct", 0) or 0
                                m2.metric("漲跌%", f"{chg:+.2f}%", delta=f"{chg:+.2f}%",
                                          help="今日漲跌幅（%）。正值=上漲，負值=下跌。")
                                m3.metric("外資淨(千股)", f"{int(srow.get('foreign_net', 0) or 0):+,}",
                                          help="外資今日淨買超（正=買超/負=賣超），單位千股。")
                                m4.metric("20日機率", f"{srow.get('prob20', '-')}%",
                                          help="模型預測未來20個交易日上漲機率，50%以上偏多，60%以上為強多訊號。")

                                c_inst, c_tech, c_news = st.columns(3)
                                with c_inst:
                                    st.markdown("**籌碼信號**")
                                    fn  = int(srow.get("foreign_net", 0) or 0)
                                    tn  = int(srow.get("trust_net", 0) or 0)
                                    dn  = int(srow.get("dealer_net", 0) or 0)
                                    st.write(f"外資：{'🟢 買超' if fn > 0 else '🔴 賣超' if fn < 0 else '⬜ 持平'} {fn:+,} 千股")
                                    st.write(f"投信：{'🟢 買超' if tn > 0 else '🔴 賣超' if tn < 0 else '⬜ 持平'} {tn:+,} 千股")
                                    st.write(f"自營：{'🟢 買超' if dn > 0 else '🔴 賣超' if dn < 0 else '⬜ 持平'} {dn:+,} 千股")

                                with c_tech:
                                    st.markdown("**技術信號**")
                                    ms = srow.get("momentum_score", 50) or 50
                                    lv = srow.get("low_vol_score", 50) or 50
                                    st.write(f"動能分：{ms:.0f} {'🔥 強勢' if ms >= 70 else '❄️ 弱勢' if ms <= 30 else '➡️ 中性'}")
                                    st.write(f"低波動分：{lv:.0f}（越高代表波動越低，適合穩健型持有）")
                                    td = st.session_state.get("tech_data", {}).get(sel_ticker_heat, {})
                                    rsi = td.get("analysis", {}).get("rsi") if td else None
                                    if rsi:
                                        st.write(f"RSI(14)：{rsi:.1f} {'🔥超買' if rsi > 70 else '❄️超賣' if rsi < 30 else '正常'}")

                                with c_news:
                                    st.markdown("**新聞情緒**")
                                    ss = srow.get("sentiment_score")
                                    if ss is not None:
                                        lbl = "🟢 正面" if ss > 0.2 else "🔴 負面" if ss < -0.2 else "🟡 中性"
                                        st.write(f"情緒：{lbl} ({ss:+.2f})")
                                    else:
                                        st.write("情緒：暫無資料")

                                if st.button("🔍 完整分析", key=f"heat_goto_{sel_ticker_heat}"):
                                    st.session_state["goto_ticker"] = sel_ticker_heat
                                    st.rerun()

    # ========== Tab 7: 產業瀏覽器（供應鏈二欄式儀表板）==========
    with tabs[6]:
        st.subheader("📊 產業 / 概念股瀏覽器")
        if model_df.empty:
            st.warning("⚠️ 請先載入市場資料")
        else:
            # ── 三竹風格：頂部 pills 導覽（全寬）──────────────────────────
            # 第一列：模式切換（概念股 / 供應鏈）
            mode_sel = st.radio(
                "瀏覽模式",
                ["💡 概念股", "🏭 供應鏈"],
                horizontal=True,
                key="tab7_mode",
                label_visibility="collapsed",
            )

            if mode_sel == "💡 概念股":
                # 第二列：概念股 pills
                concept_keys = list(CONCEPT_STOCKS.keys())
                _init_concept = st.session_state.get("sc_browser_key") \
                    if st.session_state.get("sc_browser_type") == "concept" else None
                _init_concept = _init_concept if _init_concept in concept_keys else concept_keys[0]
                sel_concept = st.pills(
                    "概念股分類",
                    concept_keys,
                    default=_init_concept,
                    selection_mode="single",
                    key="tab7_concept_pill",
                    label_visibility="collapsed",
                )
                sc_key  = sel_concept or concept_keys[0]
                sc_type = "concept"
                st.session_state["sc_browser_type"] = "concept"
                st.session_state["sc_browser_key"]  = sc_key
            else:
                # 第二列：供應鏈大類 pills
                major_keys = list(SUPPLY_CHAIN_TREE.keys())
                _init_major = major_keys[0]
                sel_major = st.pills(
                    "供應鏈大類",
                    major_keys,
                    default=_init_major,
                    selection_mode="single",
                    key="tab7_major_pill",
                    label_visibility="collapsed",
                )
                major_key = sel_major or major_keys[0]
                # 第三列：子類 pills（key 含大類名稱，避免切換大類時殘留舊選擇）
                sub_keys = SUPPLY_CHAIN_TREE.get(major_key, [])
                _major_slug = major_key.split()[0]
                sel_sub = st.pills(
                    "子供應鏈",
                    sub_keys,
                    default=sub_keys[0] if sub_keys else None,
                    selection_mode="single",
                    key=f"tab7_sub_{_major_slug}",
                    label_visibility="collapsed",
                )
                sc_key  = sel_sub or (sub_keys[0] if sub_keys else "")
                sc_type = "supply"
                st.session_state["sc_browser_type"] = "supply"
                st.session_state["sc_browser_key"]  = sc_key

            # ── 右側內容區（全寬）────────────────────────────────────────
            if True:  # 原先的 with right_col，現在改為全寬

                if sc_type == "supply":
                    tickers_in = SUPPLY_CHAIN_GROUPS.get(sc_key, [])
                    label_prefix = "🏭"
                else:
                    tickers_in = CONCEPT_STOCKS.get(sc_key, [])
                    label_prefix = "💡"

                if not sc_key:
                    st.info("請在左側選擇供應鏈或概念股分類")
                else:
                    sub_df = model_df[model_df["ticker"].isin(tickers_in)].sort_values(
                        "final_composite", ascending=False
                    )
                    missing_tickers = [t for t in tickers_in if t not in model_df["ticker"].values]

                    st.markdown(f"### {label_prefix} {sc_key}（{len(sub_df)} / {len(tickers_in)} 支）")

                    # 摘要指標列
                    if not sub_df.empty:
                        fn_col = pd.to_numeric(sub_df.get("foreign_net", pd.Series(dtype=float)), errors="coerce")
                        avg_chg = sub_df["change_pct"].mean()
                        total_fn = fn_col.sum()
                        avg_risk = sub_df["risk_score"].mean()
                        avg_pe   = pd.to_numeric(sub_df.get("pe", pd.Series(dtype=float)), errors="coerce").mean()

                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("平均漲跌", f"{avg_chg:+.2f}%" if pd.notna(avg_chg) else "--")
                        m2.metric("外資合計", f"{int(total_fn):+,}張" if pd.notna(total_fn) else "--")
                        m3.metric("平均風險分", f"{avg_risk:.0f}" if pd.notna(avg_risk) else "--")
                        m4.metric("平均PE", f"{avg_pe:.1f}x" if pd.notna(avg_pe) and avg_pe > 0 else "--")

                    st.markdown("---")

                    if sub_df.empty:
                        st.info("此分類目前無市場資料，載入後自動更新")
                    else:
                        # ── 三竹風格：HTML 卡片行清單 ─────────────────────────
                        if "tab7_css" not in st.session_state:
                            st.markdown("""
<style>
.sc-row{display:flex;align-items:center;padding:8px 14px;border:1px solid #30363d;
  border-radius:6px;margin-bottom:5px;background:#161b22;font-size:14px;gap:0;}
.sc-row:hover{border-color:#1f6feb;background:#1c2128;}
.sc-tid{font-weight:700;width:56px;color:#e6edf3;flex-shrink:0;}
.sc-nm{flex:1;color:#8b949e;font-size:13px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;padding-right:8px;}
.sc-px{width:68px;text-align:right;font-weight:600;flex-shrink:0;}
.sc-chg{width:80px;text-align:right;font-weight:600;flex-shrink:0;}
.sc-vol{width:72px;text-align:right;color:#8b949e;font-size:12px;flex-shrink:0;}
.sc-sig{width:60px;text-align:center;font-size:13px;flex-shrink:0;}
.sc-lv{width:52px;text-align:center;font-size:11px;flex-shrink:0;}
.up{color:#ef5350;}.down{color:#26a69a;}
.badge-c{background:#1f6feb22;color:#388bfd;border:1px solid #1f6feb;border-radius:3px;padding:1px 4px;}
.badge-w{background:#d2992222;color:#d29922;border:1px solid #d29922;border-radius:3px;padding:1px 4px;}
</style>""", unsafe_allow_html=True)
                            st.session_state["tab7_css"] = True

                        cards = []
                        # 欄標題行
                        cards.append(
                            '<div class="sc-row" style="border-color:#1f6feb22;background:#0d1117;'
                            'font-size:11px;color:#8b949e;padding:4px 14px;">'
                            '<span class="sc-tid">代號</span>'
                            '<span class="sc-nm">名稱</span>'
                            '<span class="sc-px">收盤</span>'
                            '<span class="sc-chg">漲跌%</span>'
                            '<span class="sc-vol">成交量</span>'
                            '<span class="sc-sig">籌碼</span>'
                            '<span class="sc-lv">等級</span>'
                            '</div>'
                        )
                        for _, r in sub_df.iterrows():
                            close = r.get("close")
                            chg   = r.get("change_pct")
                            fn    = pd.to_numeric(r.get("foreign_net"), errors="coerce")
                            vol   = r.get("volume")
                            level = str(r.get("candidate_level", ""))
                            px_s  = f"{close:.1f}" if pd.notna(close) and close else "--"
                            chg_c = "up" if (chg and chg > 0) else ("down" if chg and chg < 0 else "")
                            chg_s = (f"▲{chg:.2f}%" if chg and chg > 0
                                     else f"▼{abs(chg):.2f}%" if chg and chg < 0 else "--")
                            vol_s = f"{int(vol/10000)}萬" if pd.notna(vol) and vol else "--"
                            sig   = ("🟢" if (pd.notna(fn) and fn > 0)
                                     else ("🔴" if (pd.notna(fn) and fn < 0) else "🟡"))
                            nm    = str(r.get("name", ""))[:8].replace("<", "&lt;").replace(">", "&gt;")
                            lv_html = ""
                            if level == "核心候選":
                                lv_html = '<span class="badge-c">核心</span>'
                            elif level == "觀察候選":
                                lv_html = '<span class="badge-w">觀察</span>'
                            cards.append(
                                f'<div class="sc-row">'
                                f'<span class="sc-tid">{r["ticker"]}</span>'
                                f'<span class="sc-nm">{nm}</span>'
                                f'<span class="sc-px">{px_s}</span>'
                                f'<span class="sc-chg {chg_c}">{chg_s}</span>'
                                f'<span class="sc-vol">{vol_s}</span>'
                                f'<span class="sc-sig">{sig}</span>'
                                f'<span class="sc-lv">{lv_html}</span>'
                                f'</div>'
                            )
                        st.markdown("".join(cards), unsafe_allow_html=True)

                        if missing_tickers:
                            st.caption(f"⚠️ 以下代碼未在市場資料中：{', '.join(missing_tickers)}")

                        # 點選個股跳轉
                        sel_t = st.selectbox(
                            "選股快速跳轉到個股分析",
                            ["（請選擇）"] + sub_df["ticker"].tolist(),
                            format_func=lambda t: t if t == "（請選擇）" else
                                f"{t}　{sub_df.loc[sub_df['ticker']==t, 'name'].iloc[0] if not sub_df.loc[sub_df['ticker']==t].empty else ''}",
                            key="sc_browser_goto",
                        )
                        if sel_t != "（請選擇）":
                            if st.button(f"🔍 前往 {sel_t} 個股分析", key="sc_browser_goto_btn"):
                                st.session_state["goto_ticker"] = sel_t
                                st.info(f"請切換到「🔍 個股分析」Tab，已預選 {sel_t}")

                    # 相關產業新聞（收合式 expander）
                    with st.expander("📰 相關產業新聞（點擊展開）", expanded=False):
                        with st.spinner("載入產業新聞..."):
                            try:
                                news_analyzer = st.session_state.get("news_analyzer_obj")
                                if news_analyzer is None:
                                    news_analyzer = NewsAnalyzer()
                                    st.session_state["news_analyzer_obj"] = news_analyzer
                                events = news_analyzer.fetch_industry_events(supply_chain=sc_key)
                                if events:
                                    for ev in events[:6]:
                                        pub = ev.get("published", "")[:10]
                                        cat = ev.get("category", "")
                                        title = ev.get("title", "")
                                        link  = ev.get("link", "")
                                        if link:
                                            st.markdown(f"- [{title}]({link}) `{cat}` {pub}")
                                        else:
                                            st.markdown(f"- {title} `{cat}` {pub}")
                                else:
                                    st.caption("暫無相關產業新聞（需要網路連線）")
                            except Exception:
                                st.caption("產業新聞載入失敗")

                    # ── 各領域基本面前三名 ────────────────────────────────────
                    if not model_df.empty:
                        st.markdown("---")
                        st.markdown("##### ⭐ 本族群基本面前三名")
                        _top3_cols = [c for c in ["gross_margin", "eps", "revenue_yoy"]
                                      if c in model_df.columns]
                        if _top3_cols and not sub_df.empty:
                            _model_sub = model_df[model_df["ticker"].isin(sub_df["ticker"].tolist())]
                            _top3_metric = _top3_cols[0]
                            _top3 = QuantModel.top_by_group(
                                _model_sub, group_col="group",
                                metric=_top3_metric, top_n=3
                            )
                            if not _top3.empty:
                                _t3c = st.columns(min(3, len(_top3)))
                                for _ci, (_, _tr) in enumerate(list(_top3.iterrows())[:3]):
                                    _t3_ticker = _tr.get("ticker", "")
                                    _t3_name   = _tr.get("name", "")
                                    _t3_val    = _tr.get(_top3_metric)
                                    _label_map = {
                                        "gross_margin": "毛利率%",
                                        "eps": "EPS(元)",
                                        "revenue_yoy": "營收YoY%",
                                    }
                                    with _t3c[_ci]:
                                        st.markdown(f"**#{_ci+1} {_t3_ticker}**")
                                        st.caption(_t3_name[:8])
                                        st.metric(_label_map.get(_top3_metric, _top3_metric),
                                                  f"{_t3_val:.1f}" if _t3_val else "--")
                                        if _t3_ticker not in st.session_state.watchlist:
                                            if st.button("⭐ 追蹤", key=f"t3_wl_{_t3_ticker}",
                                                         use_container_width=True):
                                                st.session_state.watchlist[_t3_ticker] = {
                                                    "name": _t3_name,
                                                    "added_date": date.today().isoformat(),
                                                }
                                                write_json(WATCHLIST_FILE, st.session_state.watchlist)
                                                st.rerun()
                                        else:
                                            st.caption("✅ 已追蹤")

    # ========== Tab 8: 模型設定 ==========
    with tabs[7]:
        st.subheader("模型設定與權重")

        # ── FinMind Token 設定 ──
        st.markdown("#### 🔑 FinMind Token 設定")
        st.caption("免費帳號申請：[finmindtrade.com](https://finmindtrade.com)　→　登入後「個人資訊」複製 token")
        token_input = st.text_input(
            "FinMind API Token",
            value=st.session_state.finmind_token,
            type="password",
            placeholder="貼上 token 後按 Enter 儲存",
            key="finmind_token_input",
        )
        if token_input != st.session_state.finmind_token:
            st.session_state.finmind_token = token_input
            st.session_state.watchlist_data = {}       # 清快取，下次重抓
            st.session_state.model_cache_key = ""
            st.success("✅ Token 已更新，重新載入基本面時生效")

        st.markdown("---")
        sc1, sc2 = st.columns(2)
        with sc1:
            st.markdown("#### 📊 目前權重分布")
            wdf = pd.DataFrame([{"因子": WEIGHT_LABELS[k], "權重": v}
                                 for k, v in st.session_state.weights.items()])
            fig = px.pie(wdf, values="權重", names="因子", title="因子權重",
                         color_discrete_sequence=px.colors.qualitative.Set3)
            st.plotly_chart(fig, use_container_width=True)
            norm = QuantModel(st.session_state.weights).weights
            st.dataframe(
                pd.DataFrame([{"因子": WEIGHT_LABELS[k], "標準化權重": f"{v*100:.1f}%"}
                               for k, v in norm.items()]),
                use_container_width=True, hide_index=True,
            )
        with sc2:
            st.markdown("#### 📖 模型說明")
            st.markdown("""
            **六大因子（無模擬數據版）:**
            - **動能**: MA20/MA60乖離率（本機快照計算）
            - **成長**: 營收YoY + EPS成長（FinMind 真實數據）
            - **品質**: 毛利率 + EPS（FinMind 真實數據）
            - **價值**: 本益比（FinMind 真實數據）
            - **籌碼**: 三大法人買賣超（TWSE 真實數據）
            - **低波動**: 20日波動率（本機快照計算）

            **數據標籤:**
            - ✅ 真實 API 數據
            - ⚠️ 暫無數據（因子使用中性值 50）

            **期望報酬率公式:**
            `E[R] = P(上漲) × 預期漲幅 + P(下跌) × 預期跌幅`
            預期漲跌幅以 20日波動率估算

            ⚠️ 本工具僅供個人研究，不構成任何投資建議
            """)

            # 數據品質報告
            st.markdown("#### 📋 數據品質報告")
            if not model_df.empty:
                total = len(model_df)
                st.write(f"- 總計 **{total}** 檔股票")
                st.write(f"- 真實基本面: **{int(model_df['has_real_fund'].sum())}** 檔（{model_df['has_real_fund'].mean()*100:.0f}%）")
                st.write(f"- 真實籌碼: **{int(model_df['has_real_flow'].sum())}** 檔（{model_df['has_real_flow'].mean()*100:.0f}%）")
                real_tech = (model_df.get("m20", pd.Series([None]*total)).notna().sum())
                st.write(f"- 真實技術指標: **{real_tech}** 檔（需累積快照）")
                complete = int(model_df["complete_score"].sum())
                st.write(f"- 完整真實評分: **{complete}** 檔（{complete/total*100:.0f}%）")

        st.markdown("---")
        st.markdown("#### 🤖 自動參數調優")
        sc = len(st.session_state.snapshots)
        if sc < 10:
            st.info(f"⚠️ 快照數不足（{sc}/10），請每日盤後保存快照，累積 10 天後可執行調優")
        else:
            st.caption(f"已累積 {sc} 個快照，可執行自動調優")
            opt_col1, opt_col2 = st.columns(2)
            with opt_col1:
                if st.button("🔍 分析命中率 & 機率偏差", use_container_width=True):
                    with st.spinner("分析中..."):
                        backtest = BacktestEngine(st.session_state.snapshots)
                        sample_tickers = model_df["ticker"].head(100).tolist()
                        result = backtest.optimize_weights(sample_tickers, 20, 3)
                    if "error" in result:
                        st.error(result["error"])
                    else:
                        st.success(f"✅ 基準命中率 {result['baseline_hit_rate']}% → 最佳 {result['optimized_hit_rate']}%（+{result['improvement']}%）")
                        st.write(f"- 有效樣本：{result['valid_stocks']} 檔 × {result['total_samples']} 筆")
                        st.write(f"- 高機率預測（≥60%）命中率：**{result['high_prob_hit_rate']}%**")
                        st.write(f"- 低機率預測（<50%）命中率：**{result['low_prob_hit_rate']}%**")
                        if result["suggestions"]:
                            st.markdown("**建議調整：**")
                            for s in result["suggestions"]:
                                st.write(f"  • {s}")
                        else:
                            st.write("模型參數表現良好，無明顯調整建議")

                        # Apply 按鈕
                        bias = result.get("prob_bias", 0)
                        if abs(bias) > 2:
                            delta = int(round(abs(bias)))
                            if st.button(
                                f"✅ 套用建議：{'提高' if bias > 0 else '降低'}動能/成長權重 +{delta}",
                                key="apply_opt"
                            ):
                                w = st.session_state.weights.copy()
                                if bias > 0:
                                    w["momentum"] = min(60, w.get("momentum", 25) + delta)
                                    w["growth"]   = min(60, w.get("growth",   20) + delta // 2)
                                else:
                                    w["momentum"] = max(0, w.get("momentum", 25) - delta)
                                    w["low_vol"]  = min(60, w.get("low_vol",  10) + delta)
                                st.session_state.weights = w
                                write_json(WEIGHTS_FILE, w)
                                st.session_state.model_cache_key = ""
                                st.success("✅ 權重已更新，模型將重新計算")
                                st.rerun()
            with opt_col2:
                if st.button("📊 機率校準分析", use_container_width=True):
                    with st.spinner("校準中..."):
                        backtest = BacktestEngine(st.session_state.snapshots)
                        sample_tickers = model_df["ticker"].head(100).tolist()
                        cal = backtest.calibrate_probabilities(sample_tickers, 20, 3)
                    if "error" in cal:
                        st.error(cal["error"])
                    else:
                        st.write(f"**{cal['note']}**（整體偏差 {cal['avg_bias']:+.1f}%）")
                        cal_df = pd.DataFrame(cal["calibration_table"])
                        st.dataframe(cal_df, use_container_width=True, hide_index=True)
                        if abs(cal["avg_bias"]) > 3:
                            st.warning(
                                f"建議在側邊欄調整權重：{'提高動能/成長' if cal['avg_bias'] > 0 else '降低動能或提高低波動'}因子權重"
                            )

            st.markdown("---")
            st.markdown("### 💾 資料備份與還原")
            st.caption("Streamlit Cloud 重新部署後本機資料會清空，請定期備份。")

            import json as _json

            # ── 備份 ──
            backup_data = {
                "portfolio":  st.session_state.portfolio._holdings,
                "watchlist":  st.session_state.watchlist,
                "notes":      st.session_state.notes,
                "snapshots":  st.session_state.snapshots,
            }
            st.download_button(
                "📥 下載備份（JSON）",
                data=_json.dumps(backup_data, ensure_ascii=False, indent=2, default=str),
                file_name=f"tw_quant_backup_{date.today()}.json",
                mime="application/json",
                use_container_width=True,
            )

            # ── 還原 ──
            uploaded_backup = st.file_uploader("📤 上傳備份檔還原", type=["json"], key="restore_upload")
            if uploaded_backup is not None:
                try:
                    restored = _json.load(uploaded_backup)
                    if st.button("✅ 確認還原", use_container_width=True, key="confirm_restore"):
                        if "portfolio" in restored:
                            st.session_state.portfolio._holdings = restored["portfolio"]
                            st.session_state.portfolio.save()
                        if "watchlist" in restored:
                            st.session_state.watchlist = restored["watchlist"]
                            write_json(WATCHLIST_FILE, restored["watchlist"])
                        if "notes" in restored:
                            st.session_state.notes = restored["notes"]
                            write_json(NOTES_FILE, restored["notes"])
                        if "snapshots" in restored:
                            st.session_state.snapshots = restored["snapshots"]
                            write_json(SNAPSHOT_FILE, restored["snapshots"])
                        st.success("✅ 資料還原完成！")
                        st.rerun()
                except Exception as e:
                    st.error(f"❌ 備份檔格式錯誤：{e}")


    # ========== Tab 9: 潛力股 ==========
    with tabs[8]:
        st.subheader("🎯 每日潛力補漲候選")
        st.caption("⚠️ 以下為模型信號，不構成投資建議。請結合基本面自行判斷。")

        if model_df.empty:
            st.warning("⚠️ 請先載入市場資料")
        else:
            # 條件說明
            c1, c2, c3, c4 = st.columns(4)
            c1.info("📉 落後同族群")
            c2.info("🏦 外資淨買超")
            c3.info("📈 技術金叉中")
            c4.info("📊 基本面及格")

            st.markdown("---")

            with st.spinner("分析中..."):
                catchup_df = model.find_catchup_candidates(model_df, top_n=10)

            if catchup_df.empty:
                st.info("目前條件下無符合候選（需要籌碼數據與技術面資料，請先載入市場資料）")
            else:
                st.markdown(f"**找到 {len(catchup_df)} 支補漲候選**")
                for rank, (_, row) in enumerate(catchup_df.iterrows(), 1):
                    ticker  = row.get("ticker", "")
                    name    = row.get("name", "")
                    group   = row.get("group", "")
                    close   = row.get("close")
                    chg     = row.get("change_pct")
                    fn      = row.get("foreign_net")
                    flow    = row.get("flow_score", 50)
                    quality = row.get("quality_score", 50)
                    growth  = row.get("growth_score", 50)
                    peer_lag = row.get("peer_lag_score", 50)
                    inst_e  = row.get("inst_entry", 0)
                    kd_x    = row.get("kd_cross", False)
                    macd_p  = row.get("macd_pre_cross", False)
                    pe      = row.get("pe")
                    gm      = row.get("gross_margin")
                    rev_yoy = row.get("revenue_yoy")

                    chg_str  = f"▲{chg:+.2f}%" if chg and chg > 0 else (f"▼{chg:.2f}%" if chg else "--")
                    close_str = f"{close:.1f}" if close else "--"
                    fn_str   = f"+{int(fn):,}張" if fn and fn > 0 else ("--" if not fn else f"{int(fn):,}張")

                    # 訊號燈
                    lag_icon  = "🟢" if peer_lag > 55 else "🟡"
                    inst_icon = "🟢" if inst_e else "🟡"
                    tech_icon = "🟢" if (kd_x or macd_p) else "🟡"
                    fund_icon = "🟢" if (quality > 50 and growth > 50) else "🟡"

                    with st.expander(
                        f"#{rank}  {ticker} {name}  {group}  {chg_str}  "
                        f"{lag_icon}{inst_icon}{tech_icon}{fund_icon}",
                        expanded=(rank <= 3),
                    ):
                        r1c1, r1c2, r1c3 = st.columns(3)
                        r1c1.metric("收盤", close_str, delta=f"{chg:+.2f}%" if chg else None)
                        r1c2.metric("外資", fn_str)
                        r1c3.metric("族群落後分位", f"{peer_lag:.0f}" if peer_lag else "--")

                        r2c1, r2c2, r2c3, r2c4 = st.columns(4)
                        r2c1.markdown(f"**籌碼**  {inst_icon} 外資{'入場' if inst_e else '觀望'}")
                        r2c2.markdown(f"**技術**  {'🟢 KD金叉' if kd_x else ('🟡 MACD收斂' if macd_p else '🟡 待觀察')}")
                        r2c3.markdown(f"**PE**  {f'{pe:.1f}x' if pe else '--'}")
                        r2c4.markdown(f"**毛利率**  {f'{gm:.1f}%' if gm else '--'}")

                        if rev_yoy is not None:
                            st.markdown(f"**營收YoY**：{rev_yoy:+.1f}%  ｜  **品質分**：{quality:.0f}  ｜  **成長分**：{growth:.0f}")

                        # PE 歷史分位（快速估值判斷）
                        _ckey = f"catchup_val_{ticker}"
                        if _ckey not in st.session_state:
                            st.session_state[_ckey] = None
                        if st.session_state[_ckey] is None and rank <= 5:
                            try:
                                _fm_c = FinMindLoader(token=st.session_state.get("finmind_token", ""))
                                st.session_state[_ckey] = _fm_c.get_valuation_percentile(ticker)
                            except Exception:
                                st.session_state[_ckey] = {}
                        _cvp = st.session_state.get(_ckey) or {}
                        if _cvp.get("pe_pct") is not None:
                            _pe_pct_c = _cvp["pe_pct"]
                            _pe_icon  = "🟢" if _pe_pct_c < 35 else ("🔴" if _pe_pct_c > 70 else "🟡")
                            st.markdown(f"**估值分位** {_pe_icon} PE 在歷史 {_pe_pct_c:.0f}% 分位 — {_cvp.get('status','')}")

                        if st.button("🔍 完整個股分析", key=f"catchup_goto_{ticker}_{rank}"):
                            st.session_state["goto_ticker"] = ticker
                            st.info(f"請切換到「🔍 個股分析」Tab，已預選 {ticker}")

        # ── 跨年 EPS 超越排行前十名 ──────────────────────────────────────
        st.markdown("---")
        st.markdown("#### 📈 今年 EPS 進度超越去年全年 — 前十名")
        st.caption("找出今年已公布季度的 EPS 累計，年化後超越去年全年 EPS 的股票（獲利爆發訊號）。")
        with st.expander("展開 EPS 超越排行", expanded=True):
            if model_df.empty:
                st.info("請先載入市場資料")
            else:
                _fm_eps = FinMindLoader(token=st.session_state.get("finmind_token", ""))
                _breakout_rows = []
                _pool = model_df["ticker"].tolist()[:80]  # 限制 80 檔避免過慢
                with st.spinner(f"分析 {len(_pool)} 檔 EPS 進度..."):
                    for _t in _pool:
                        _r = _fm_eps.get_eps_breakout(_t)
                        if _r and _r.get("on_track_to_exceed"):
                            _row = model_df[model_df["ticker"] == _t]
                            _name = _row.iloc[0]["name"] if not _row.empty else ""
                            _breakout_rows.append({
                                "代號": _t,
                                "名稱": _name,
                                "去年全年EPS": _r["prev_full_year_eps"],
                                "今年累計EPS": _r["ytd_eps"],
                                f"已公布季數": _r["quarters_counted"],
                                "年化進度%": round(_r["pace_ratio"] * 100, 1),
                                "年化預估EPS": _r["annual_pace"],
                                "狀態": "✅ 已超越" if _r["already_exceeded"] else "🔥 進度中",
                            })

                if _breakout_rows:
                    _bdf = (pd.DataFrame(_breakout_rows)
                            .sort_values("年化進度%", ascending=False)
                            .head(10)
                            .reset_index(drop=True))
                    st.dataframe(_bdf, use_container_width=True, hide_index=True)
                    st.caption(f"⚠️ 分析前 {len(_pool)} 檔股票，找到 {len(_breakout_rows)} 檔符合條件，顯示前 10 名。")
                else:
                    st.info("目前追蹤清單股票中，尚無今年 EPS 進度明顯超越去年的標的（可能資料不足）。")

    # ========== Tab 10: ETF 排行 ==========
    with tabs[9]:
        st.subheader("📈 ETF 績效排行")
        st.caption("⚠️ 報酬率為統計性指標，不構成投資建議。ETF 成分股資料來自 yfinance，台灣 ETF 可能資料不足。")

        if model_df.empty:
            st.warning("⚠️ 請先載入市場資料")
        else:
            # 篩出 ETF
            etf_mask = (
                model_df["ticker"].str.startswith("00")
                | model_df["group"].str.contains("ETF", na=False)
                | model_df["industry"].str.contains("ETF|指數股票型|槓桿", na=False)
            )
            etf_df = model_df[etf_mask].copy()

            if etf_df.empty:
                st.info("目前市場資料中無 ETF（代碼以 00 開頭的 ETF 需透過 TWSE API 或 TPEx API 載入）")
            else:
                sort_opt = st.radio(
                    "排序依據",
                    ["今日漲跌", "月報酬", "季報酬", "年報酬"],
                    horizontal=True,
                    key="etf_sort",
                )

                fm_inst = st.session_state.get("fm_loader")
                if fm_inst is None:
                    fm_inst = FinMindLoader(st.session_state.get("finmind_token", ""))

                # 計算報酬率（使用快取，批次一次性）
                if "etf_perf_cache" not in st.session_state:
                    st.session_state["etf_perf_cache"] = {}

                with st.spinner("計算 ETF 報酬率（首次需時較長）..."):
                    for t in etf_df["ticker"].tolist():
                        if t not in st.session_state["etf_perf_cache"]:
                            st.session_state["etf_perf_cache"][t] = fm_inst.get_etf_performance(t)

                etf_df["月報酬%"]  = etf_df["ticker"].apply(
                    lambda t: st.session_state["etf_perf_cache"].get(t, {}).get("month")
                )
                etf_df["季報酬%"]  = etf_df["ticker"].apply(
                    lambda t: st.session_state["etf_perf_cache"].get(t, {}).get("quarter")
                )
                etf_df["年報酬%"]  = etf_df["ticker"].apply(
                    lambda t: st.session_state["etf_perf_cache"].get(t, {}).get("year")
                )

                sort_col_map = {
                    "今日漲跌": "change_pct",
                    "月報酬":   "月報酬%",
                    "季報酬":   "季報酬%",
                    "年報酬":   "年報酬%",
                }
                sort_col = sort_col_map[sort_opt]
                etf_sorted = etf_df.dropna(subset=[sort_col]).sort_values(sort_col, ascending=False).head(10)

                if etf_sorted.empty:
                    st.info("目前無足夠 ETF 績效資料（需要歷史 OHLCV，請確認 FinMind Token 或等資料累積）")
                else:
                    # 顯示排行表
                    disp_etf = etf_sorted[["ticker", "name"]].copy()
                    disp_etf["收盤"]   = etf_sorted["close"].apply(lambda x: f"{x:.2f}" if pd.notna(x) and x else "--")
                    disp_etf["今日%"]  = etf_sorted["change_pct"].apply(
                        lambda x: f"{x:+.2f}%" if pd.notna(x) and x is not None else "--"
                    )
                    disp_etf["月報酬"] = etf_sorted["月報酬%"].apply(
                        lambda x: f"{x:+.2f}%" if pd.notna(x) else "--"
                    )
                    disp_etf["季報酬"] = etf_sorted["季報酬%"].apply(
                        lambda x: f"{x:+.2f}%" if pd.notna(x) else "--"
                    )
                    disp_etf["年報酬"] = etf_sorted["年報酬%"].apply(
                        lambda x: f"{x:+.2f}%" if pd.notna(x) else "--"
                    )
                    disp_etf["成交量(萬)"] = etf_sorted["volume"].apply(
                        lambda x: f"{int(x/10000)}" if pd.notna(x) and x else "--"
                    )
                    disp_etf = disp_etf.rename(columns={"ticker": "代號", "name": "名稱"})
                    disp_etf.insert(0, "排名", range(1, len(disp_etf) + 1))

                    st.dataframe(disp_etf.reset_index(drop=True), use_container_width=True, hide_index=True)

                    st.markdown("---")
                    st.markdown("#### 展開 ETF 詳情")
                    sel_etf = st.selectbox(
                        "選擇 ETF",
                        ["（請選擇）"] + etf_sorted["ticker"].tolist(),
                        format_func=lambda t: t if t == "（請選擇）" else
                            f"{t}　{etf_sorted.loc[etf_sorted['ticker']==t, 'name'].iloc[0] if not etf_sorted.loc[etf_sorted['ticker']==t].empty else ''}",
                        key="etf_detail_select",
                    )
                    if sel_etf != "（請選擇）":
                        sel_row = etf_sorted[etf_sorted["ticker"] == sel_etf].iloc[0]
                        with st.expander(f"📊 {sel_etf} {sel_row.get('name','')} 詳情", expanded=True):
                            d1, d2, d3, d4 = st.columns(4)
                            d1.metric("月報酬", f"{sel_row['月報酬%']:+.2f}%" if pd.notna(sel_row['月報酬%']) else "--")
                            d2.metric("季報酬", f"{sel_row['季報酬%']:+.2f}%" if pd.notna(sel_row['季報酬%']) else "--")
                            d3.metric("年報酬", f"{sel_row['年報酬%']:+.2f}%" if pd.notna(sel_row['年報酬%']) else "--")
                            d4.metric("今日", f"{sel_row['change_pct']:+.2f}%" if pd.notna(sel_row.get('change_pct')) else "--")

                            # 前十大成分股（yfinance）
                            st.markdown("**前十大成分股**")
                            try:
                                import yfinance as yf
                                etf_yf = yf.Ticker(f"{sel_etf}.TW")
                                holdings = None
                                try:
                                    fd = etf_yf.funds_data
                                    holdings = fd.top_holdings if fd else None
                                except Exception:
                                    pass
                                if holdings is not None and not holdings.empty:
                                    st.dataframe(holdings, use_container_width=True, height=240)
                                else:
                                    st.caption("⚠️ 台灣 ETF 成分股資料不足（yfinance 未收錄此 ETF 的持股明細）")
                            except Exception:
                                st.caption("⚠️ 成分股資料載入失敗")


# ============================================================
# 進入點
# ============================================================

if __name__ == "__main__":
    main()
