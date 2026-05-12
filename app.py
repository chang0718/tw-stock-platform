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
from datetime import date, datetime
from typing import Dict, List

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import (
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
from backtest import BacktestEngine
from finmind_loader import FinMindLoader
from twse_institutional import TWSeInstitutionalLoader
from news_analyzer import NewsAnalyzer
from tech_analyzer import analyze as tech_analyze, INDICATOR_EXPLANATIONS
from us_market import USMarketLoader, US_TW_SUPPLY_CHAIN, TW_INDUSTRY_CHAIN, US_INDICES, US_KEY_STOCKS
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
        "snapshots":         read_json(SNAPSHOT_FILE, []),
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
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


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
        df = loader.load_all_market_data(include_tpex=include_tpex)
        if df.empty:
            st.warning("⚠️ 無法取得市場行情，請確認網路連線後重試")
            return
        st.session_state.universe_df = df
        st.session_state.last_update = datetime.now()
        st.session_state.model_cache_key = ""   # 強制重算

    # 累積今日價格到本機歷史（讓動能/波動率分數逐日建立）
    n_updated = _update_price_history(df)
    valid_prices = df["daily"].apply(lambda d: d.get("close") if isinstance(d, dict) else None).notna().sum()
    st.success(f"✅ 載入 {len(df)} 檔，有效收盤價 {valid_prices} 檔，累積歷史 {n_updated} 筆")

    with st.spinner("📊 載入三大法人 / 融資融券..."):
        inst_loader = TWSeInstitutionalLoader()
        inst   = inst_loader.get_institutional_all(
            finmind_token=st.session_state.get("finmind_token", "")
        )
        margin = inst_loader.get_margin_all()
        st.session_state.institutional_data = {
            "inst":   inst   or {},
            "margin": margin or {},
        }

    n_inst = len(st.session_state.institutional_data["inst"])
    if n_inst:
        st.success(f"✅ 三大法人已載入（{n_inst} 檔）")
    else:
        st.warning("⚠️ 三大法人暫時無法取得（非交易日或 API 異常）")


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
        result = result.sort_values(filters["sort_by"], ascending=filters["sort_ascending"])
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

    st.sidebar.markdown("### 🔍 基本篩選")
    filters["industry"] = st.sidebar.selectbox("產業別", ["全部"] + available_groups, key="industry_filter")
    filters["market"]   = st.sidebar.selectbox("市場",   ["全部"] + available_markets, key="market_filter")
    filters["query"]    = st.sidebar.text_input("自由搜尋", placeholder="代號、名稱、產業...", key="search_query")

    st.sidebar.markdown("### 🎯 進階篩選")
    filters["candidate_level"] = st.sidebar.selectbox(
        "研究候選等級",
        ["全部", "核心候選", "觀察候選", "高風險觀察", "保守觀望"],
        key="candidate_filter",
    )

    st.sidebar.markdown("### 📈 排序與顯示")
    sort_options = {
        "綜合評分":    "final_composite",
        "20日上漲機率": "prob20",
        "5日上漲機率":  "prob5",
        "60日上漲機率": "prob60",
        "期望報酬率":   "expected_return_20d",
        "模型信心度":   "confidence",
        "歷史命中率":   "hit_rate",
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
    inst_count = len(st.session_state.institutional_data.get("inst", {}))
    wl_count   = len(st.session_state.watchlist)
    st.sidebar.caption(
        f"股票池: {len(universe_df)} 檔\n\n"
        f"法人資料: {inst_count} 檔\n\n"
        f"追蹤清單: {wl_count} 檔\n\n"
        f"快照數: {len(st.session_state.snapshots)} 天"
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

    return filters


# ============================================================
# 快照
# ============================================================

def save_snapshot_action(model_df: pd.DataFrame):
    if model_df.empty:
        st.warning("⚠️ 沒有資料可保存")
        return
    today    = date.today().isoformat()
    snap_rows = model_df[["ticker", "name", "close", "prob5", "prob20", "prob60", "confidence", "risk_score"]].to_dict("records")
    snapshots = [s for s in st.session_state.snapshots if s.get("date") != today]
    snapshots.append({"date": today, "rows": snap_rows})
    snapshots = snapshots[-120:]
    write_json(SNAPSHOT_FILE, snapshots)
    st.session_state.snapshots = snapshots
    st.success(f"✅ 已保存 {today} 快照（累積 {len(snapshots)} 天）")


def clear_snapshots_action():
    write_json(SNAPSHOT_FILE, [])
    st.session_state.snapshots = []
    st.warning("🗑️ 已清除所有快照")


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
        4. 點擊 **💾 保存今日快照** 累積歷史資料

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

    # 渲染側邊欄
    filters = render_sidebar(st.session_state.universe_df)

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
            inst = st.session_state.institutional_data
            model = QuantModel(st.session_state.weights)
            model_df = model.enrich_dataframe(
                st.session_state.universe_df,
                filters["preferred_groups"],
                inst_data        = inst.get("inst", {}),
                margin_data      = inst.get("margin", {}),
                fundamental_data = fund_data,
            )

            # 加入回測命中率
            if st.session_state.snapshots:
                backtest = BacktestEngine(st.session_state.snapshots)
                for idx, row in model_df.iterrows():
                    hr, samples, source = backtest.calculate_hit_rate(row["ticker"], 20, 5)
                    model_df.at[idx, "hit_rate"]         = hr if source == "本機快照" else round((row["prob5"] + row["prob20"] + row["prob60"]) / 3 * 0.85)
                    model_df.at[idx, "hit_rate_source"]  = source if source == "本機快照" else "示範估算"
                    model_df.at[idx, "local_sample_size"] = samples
            else:
                model_df["hit_rate"]          = (model_df["prob5"] + model_df["prob20"] + model_df["prob60"]) / 3 * 0.85
                model_df["hit_rate_source"]   = "示範估算"
                model_df["local_sample_size"] = 0

            # 重算 final_composite（含真實 hit_rate + 板塊偏好 + 數據完整度）
            pg = filters["preferred_groups"]
            group_boost_series       = model_df["group"].apply(lambda g: 4.0 if g in pg else 0.0)
            completeness_bonus_series = model_df["complete_score"].apply(lambda c: 3.0 if c else 0.0)
            model_df["final_composite"] = (
                model_df["prob20"]        * 0.35
                + model_df["confidence"]  * 0.2
                + model_df["hit_rate"]    * 0.2
                + (100 - model_df["risk_score"]) * 0.15
                + model_df["composite_score"] * 0.1
                + group_boost_series
                + completeness_bonus_series
            ).round(2)

            st.session_state.model_df_cached = model_df
            st.session_state.model_cache_key = _ck
    else:
        model_df = st.session_state.model_df_cached

    # ── 篩選 ──────────────────────────────────────────────────────
    filtered_df = apply_filters(model_df, filters)

    # ── 頂部指標卡 ────────────────────────────────────────────────
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("📋 符合筆數",   len(filtered_df))
    c2.metric("📊 平均20日機率", format_percentage(filtered_df["prob20"].mean() if not filtered_df.empty else 0))
    c3.metric("⭐ 核心候選",   int((filtered_df["candidate_level"] == "核心候選").sum()) if not filtered_df.empty else 0)
    c4.metric("💪 平均信心度", format_percentage(filtered_df["confidence"].mean() if not filtered_df.empty else 0))
    c5.metric("🎯 平均命中率", format_percentage(filtered_df["hit_rate"].mean() if not filtered_df.empty else 0))

    real_fund_pct = (model_df["has_real_fund"].sum() / max(len(model_df), 1) * 100) if not model_df.empty else 0
    real_flow_pct = (model_df["has_real_flow"].sum() / max(len(model_df), 1) * 100) if not model_df.empty else 0
    c6.metric("✅ 真實數據率", f"{real_fund_pct:.0f}%/{real_flow_pct:.0f}%", help="基本面/籌碼真實數據比例")

    # ── 快照操作 ──────────────────────────────────────────────────
    st.markdown("---")
    bc1, bc2, bc3 = st.columns([2, 2, 4])
    with bc1:
        if st.button("💾 保存今日快照", use_container_width=True, type="primary"):
            save_snapshot_action(model_df)
    with bc2:
        if st.button("🗑️ 清除快照", use_container_width=True):
            clear_snapshots_action()
    with bc3:
        sc = len(st.session_state.snapshots)
        if sc >= 5:
            st.success(f"✅ 本機快照: {sc} 個交易日（已可回測）")
        else:
            st.info(f"📊 本機快照: {sc} 個交易日（建議至少 5 天）")

    # ── 分頁 ──────────────────────────────────────────────────────
    tabs = st.tabs([
        "🏆 整體分析",
        "🌍 美股連動",
        "📋 候選清單",
        "🔍 個股分析",
        "💼 持倉管理",
        "⭐ 追蹤清單",
        "📊 產業總覽",
        "⚙️ 模型設定",
        "📈 回測報告",
    ])

    # ========== Tab 0: 整體分析 ==========
    with tabs[0]:
        st.subheader("🏆 整體分析 - TOP 10 最值得投資標的")
        if model_df.empty:
            st.warning("⚠️ 沒有資料")
        else:
            top10 = model_df.nlargest(10, "final_composite").copy()

            st.markdown("### 📊 核心推薦指標")
            tc1, tc2, tc3, tc4 = st.columns(4)
            tc1.metric("平均20日機率", f"{top10['prob20'].mean():.1f}%", delta=f"{top10['prob20'].mean()-50:.1f}%" if top10['prob20'].mean() > 50 else None)
            tc2.metric("平均信心度",   f"{top10['confidence'].mean():.1f}%")
            tc3.metric("核心候選數",   f"{(top10['candidate_level']=='核心候選').sum()}/10")
            tc4.metric("平均風險",     f"{top10['risk_score'].mean():.1f}", delta_color="inverse")
            st.markdown("---")

            st.markdown("### 📋 TOP 10 詳細清單")
            for idx, (_, stock) in enumerate(top10.iterrows(), 1):
                emoji = {"核心候選": "⭐", "觀察候選": "👀", "高風險觀察": "⚠️"}.get(stock["candidate_level"], "🛡️")
                with st.expander(
                    f"**#{idx}** {emoji} **{stock['ticker']} {stock['name']}** — "
                    f"{stock['group']} | {stock['market']} | {stock['candidate_level']}",
                    expanded=(idx <= 3),
                ):
                    sc1, sc2, sc3, sc4, sc5, sc6 = st.columns(6)
                    sc1.metric("收盤價",  f"${stock['close']:.2f}" if stock.get('close') is not None else "--")
                    sc2.metric("📅 1週漲機率",  f"{stock['prob5']:.1f}%",
                               help="未來5個交易日股價上漲的可能性，>60% 看多")
                    sc3.metric("📅 1月漲機率", f"{stock['prob20']:.1f}%",
                               help="未來1個月股價上漲的可能性，最重要的參考指標")
                    sc4.metric("📅 3月漲機率", f"{stock['prob60']:.1f}%",
                               help="未來3個月的趨勢方向，長線投資人參考")
                    sc5.metric("🎯 預測可靠性",   f"{stock['confidence']:.1f}%",
                               help=">70% 訊號較可靠；<50% 不確定性高")
                    sc6.metric("💰 預估1月報酬", f"{stock['expected_return_20d']:+.1f}%" if pd.notna(stock.get("expected_return_20d")) else "N/A",
                               help="統計估算的預期報酬，非保證獲利")

                    st.markdown("##### 六大評分（100分滿分，>60分代表正面信號）")
                    fc1, fc2, fc3 = st.columns(3)
                    with fc1:
                        st.write(f"📈 近期漲勢（動能）: **{stock['momentum_score']:.0f}**/100")
                        st.write(f"🚀 成長速度（營收/獲利）: **{stock['growth_score']:.0f}**/100")
                    with fc2:
                        st.write(f"💎 獲利品質（毛利/淨利）: **{stock['quality_score']:.0f}**/100")
                        st.write(f"🏷️ 股價便宜程度（價值）: **{stock['value_score']:.0f}**/100")
                    with fc3:
                        st.write(f"🏦 大戶買賣方向（籌碼）: **{stock['flow_score']:.0f}**/100")
                        st.write(f"🪨 股價穩定程度（低波動）: **{stock['low_vol_score']:.0f}**/100")

                    # 數據來源標籤
                    tags = []
                    if stock.get("has_real_fund"):
                        tags.append("✅ 真實基本面")
                    else:
                        tags.append("⚠️ 基本面待載入")
                    if stock.get("has_real_flow"):
                        tags.append("✅ 真實籌碼")
                    else:
                        tags.append("⚠️ 籌碼待載入")
                    path = stock.get("scoring_path", "技術動能")
                    tags.append(f"{'📊' if path == '完整' else '📈'} 評分路徑: {path}")
                    st.caption(" | ".join(tags))

                    note = st.session_state.notes.get(stock["ticker"], "")
                    if note:
                        st.markdown("##### 📝 個人筆記")
                        st.info(note[:100] + "..." if len(note) > 100 else note)

                    if stock["risk_score"] > 70:
                        st.warning("⚠️ 風險提醒: 風險分數偏高，請注意波動")

            st.markdown("---")
            csv_data = top10[["ticker", "name", "market", "group", "close",
                               "prob5", "prob20", "prob60", "confidence",
                               "expected_return_20d", "hit_rate", "risk_score",
                               "candidate_level", "final_composite"]].to_csv(index=False).encode("utf-8-sig")
            st.download_button("📥 下載 TOP 10 CSV", csv_data,
                               file_name=f"top10_{date.today()}.csv", mime="text/csv")

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
            fetched = us_data.get("fetched_at", "")
            st.caption(f"資料時間：{fetched}（前一交易日收盤）")

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
    with tabs[2]:
        st.subheader("候選清單")
        if filtered_df.empty:
            st.warning("⚠️ 目前篩選條件下沒有資料")
        else:
            column_mapping = {
                "ticker": "代碼", "name": "名稱", "market": "市場",
                "group": "產業分類", "industry": "細分產業",
                "close": "收盤價", "change_pct": "漲跌幅(%)",
                "prob5": "5日機率(%)", "prob20": "20日機率(%)", "prob60": "60日機率(%)",
                "expected_return_20d": "期望報酬(%)", "confidence": "信心度(%)",
                "hit_rate": "命中率(%)", "hit_rate_source": "資料來源",
                "risk_score": "風險分數", "candidate_level": "候選等級",
                "composite_score": "綜合評分",
            }
            cols = [c for c in DISPLAY_COLUMNS["候選清單"] if c in filtered_df.columns]
            if "expected_return_20d" not in cols:
                cols.insert(cols.index("confidence") if "confidence" in cols else -1, "expected_return_20d")
            display_df = filtered_df[cols].rename(columns=column_mapping)
            st.dataframe(display_df, use_container_width=True, height=500)
            csv_data = filtered_df[cols].to_csv(index=False).encode("utf-8-sig")
            st.download_button("📥 下載CSV", csv_data,
                               file_name=f"candidates_{date.today()}.csv", mime="text/csv")

    # ========== Tab 3: 個股分析 ==========
    with tabs[3]:
        st.subheader("個股分析")
        if filtered_df.empty:
            st.warning("⚠️ 目前篩選條件下沒有資料")
        else:
            selected_ticker = st.selectbox(
                "選擇個股",
                filtered_df["ticker"].tolist(),
                format_func=lambda t: (
                    f"{t} {model_df.loc[model_df['ticker']==t, 'name'].iloc[0]}"
                    if not model_df[model_df["ticker"] == t].empty else t
                ),
                key="stock_selector",
            )
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

            mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
            mc1.metric("📅 1週漲機率",  format_percentage(stock["prob5"]),
                       help="未來5個交易日（約1週）股價上漲的可能性\n✅ >60% 模型看多　⚠️ <40% 模型看空")
            mc2.metric("📅 1月漲機率", format_percentage(stock["prob20"]),
                       help="未來20個交易日（約1個月）股價上漲的可能性\n✅ >60% 看多　➡️ 50% 中性　⚠️ <40% 看空\n（最重要的參考指標）")
            mc3.metric("📅 3月漲機率", format_percentage(stock["prob60"]),
                       help="未來60個交易日（約3個月）股價上漲的可能性\n適合長期投資人參考趨勢方向")
            mc4.metric("🎯 預測可靠性", format_percentage(stock["confidence"]),
                       help="模型對這次預測有多確定\n✅ >70% 較可靠　➡️ 50-70% 普通　⚠️ <50% 不確定，勿輕易跟進")
            mc5.metric("📊 歷史準確率", format_percentage(stock["hit_rate"]), stock["hit_rate_source"],
                       help="過去模型看多時，股票實際上漲的比例\n本機快照累積越多天，這個數字越準確")
            mc6.metric("💰 預估1月報酬", f"{stock['expected_return_20d']:+.1f}%" if pd.notna(stock.get("expected_return_20d")) else "N/A",
                       help="根據模型機率和股票波動率估算的預期報酬\n僅供參考，不保證實際獲利")

            # ── 指標白話速查 ──
            with st.expander("📖 看不懂這些數字？點這裡看白話說明"):
                st.markdown("""
| 指標 | 意思 | 怎麼看 |
|------|------|--------|
| **1週/1月/3月漲機率** | 模型預測未來這段時間股價上漲的可能性 | >60% 偏多、50% 中性、<40% 偏空 |
| **預測可靠性** | 模型對這次預測有多確定 | >70% 較可信、<50% 參考就好 |
| **歷史準確率** | 過去模型看多時實際上漲的比例 | 快照越多天越準確，初期為估算值 |
| **預估1月報酬** | 根據波動率算出的預期獲利 | 僅為統計估算，不保證 |
| **近期漲勢（動能）** | 股價最近是否有往上走的慣性 | 分數越高代表近期走勢越強 |
| **成長速度** | 公司營收和獲利是否持續增加 | 有真實財報才準確，否則為估算 |
| **獲利品質** | 毛利率、淨利率高不高 | 越高代表公司賺錢能力越強 |
| **股價便宜程度（價值）** | 目前股價相對獲利是貴還是便宜 | 分數越高代表相對便宜 |
| **大戶動向（籌碼）** | 外資、投信等大型機構在買還是在賣 | 分數越高代表大戶在買 |
| **股價穩定度** | 這檔股票容不容易大幅波動 | 分數越高代表越穩定 |
                """)
                st.caption("⚠️ 以上指標均為統計模型輸出，不構成投資建議。實際操作前請自行評估風險。")

            # ── 圖表區 ──
            ch1, ch2 = st.columns(2)
            with ch1:
                fig = go.Figure()
                fig.add_trace(go.Scatterpolar(
                    r=[stock[f] for f in ["momentum_score", "growth_score", "quality_score",
                                          "value_score", "flow_score", "low_vol_score"]],
                    theta=list(WEIGHT_LABELS.values()),
                    fill="toself", name="因子分數", line_color="rgb(99,110,250)",
                ))
                fig.update_layout(
                    title="六因子雷達圖",
                    polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                    showlegend=False, height=350,
                )
                st.plotly_chart(fig, use_container_width=True)

            with ch2:
                st.markdown("**📋 數據載入狀態**")
                has_fund = stock.get("has_real_fund", False)
                has_flow = stock.get("has_real_flow", False)
                has_snap = stock.get("m20") is not None
                path     = stock.get("scoring_path", "技術動能")

                st.write("✅ 基本面已載入" if has_fund else "⚠️ 基本面：未載入（點下方按鈕）")
                st.write("✅ 法人/籌碼已載入" if has_flow else "⚠️ 法人資料：未載入（側邊欄載入市場）")
                st.write("✅ 技術快照充足" if has_snap else "⚠️ 技術快照不足（累積快照後更準）")
                st.write(f"📈 評分模式：{'完整六因子' if path == '完整' else '技術動能路徑'}")

                st.markdown("---")
                if not has_fund and not has_flow:
                    st.warning("⚠️ **數據不足**：目前機率與評分為估算值，分數僅供參考。\n\n載入基本面資料後準確度會大幅提升。")
                elif not has_fund:
                    st.info("💡 載入基本面後，估值與獲利品質評分會更準確。")
                elif not has_flow:
                    st.info("💡 載入三大法人資料後，籌碼評分會更準確。")
                else:
                    st.success("✅ 數據完整，評分具有參考價值。")

            # ── 基本面 ──
            st.markdown("---")
            st.markdown("#### 📊 基本面（FinMind API）")

            fund_key = selected_ticker
            if fund_key in st.session_state.stock_fundamentals:
                render_fundamental_block(st.session_state.stock_fundamentals[fund_key])
            elif selected_ticker in st.session_state.watchlist_data:
                render_fundamental_block(
                    st.session_state.watchlist_data[selected_ticker].get("fundamental", {})
                )
            else:
                col_btn, _ = st.columns([2, 3])
                with col_btn:
                    if st.button("📊 載入基本面資料", use_container_width=True,
                                 key=f"load_fm_{selected_ticker}"):
                        with st.spinner("向 FinMind 請求資料..."):
                            fm = FinMindLoader(token=st.session_state.get("finmind_token", ""))
                            fdata = fm.get_fundamental(selected_ticker)
                            st.session_state.stock_fundamentals[selected_ticker] = fdata
                            st.session_state.model_cache_key = ""  # 觸發重算
                        st.rerun()
                st.info("⚠️ 尚未載入基本面（或加入追蹤，下次啟動自動載入）")

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
                    else:
                        st.info("⚠️ 無季報資料")

            # ── 籌碼 ──
            st.markdown("---")
            st.markdown("#### 💰 籌碼（TWSE 三大法人 + 融資融券）")
            render_flow_block(stock.to_dict(), show_reload=True)

            # ── 技術分析 ──
            st.markdown("---")
            st.markdown("#### 📈 技術分析（FinMind 歷史數據）")
            if selected_ticker in st.session_state.tech_data:
                render_tech_block(st.session_state.tech_data[selected_ticker], stock.to_dict())
                if st.button("🔄 重新載入技術分析", key=f"reload_tech_{selected_ticker}"):
                    st.session_state.tech_data.pop(selected_ticker, None)
                    st.rerun()
            else:
                col_tb, _ = st.columns([2, 3])
                with col_tb:
                    if st.button("📈 載入技術分析", use_container_width=True,
                                 key=f"load_tech_{selected_ticker}"):
                        with st.spinner("載入歷史 K 線資料..."):
                            fm = FinMindLoader(token=st.session_state.get("finmind_token", ""))
                            price_df = fm.get_price_history(selected_ticker, days=120)
                            ta = tech_analyze(price_df, selected_ticker, stock["name"])
                            st.session_state.tech_data[selected_ticker] = ta
                        st.rerun()
                st.info("⚠️ 點擊上方按鈕載入 120 日歷史 K 線與技術指標（需 FinMind token）")

            # ── 新聞情緒 ──
            st.markdown("---")
            st.markdown("#### 📰 新聞情緒（RSS，近 7 天）")
            news_key = selected_ticker
            if news_key in st.session_state.watchlist_data:
                render_news_block(st.session_state.watchlist_data[news_key].get("news", {}))
            else:
                col_btn2, _ = st.columns([2, 3])
                with col_btn2:
                    if st.button("📰 載入新聞分析", use_container_width=True,
                                 key=f"load_news_{selected_ticker}"):
                        with st.spinner("爬取 RSS 新聞..."):
                            na = NewsAnalyzer()
                            nd = na.get_stock_news_sentiment(selected_ticker, stock["name"])
                            if selected_ticker not in st.session_state.watchlist_data:
                                st.session_state.watchlist_data[selected_ticker] = {}
                            st.session_state.watchlist_data[selected_ticker]["news"] = nd
                        st.rerun()
                st.info("⚠️ 尚未載入新聞（或加入追蹤，下次啟動自動載入）")

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

    # ========== Tab 4: 持倉管理 ==========
    with tabs[4]:
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
    with tabs[5]:
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

                # 移除追蹤
                if st.button(f"❌ 移除 {selected_wl} 的追蹤", key=f"rm_wl_{selected_wl}"):
                    del st.session_state.watchlist[selected_wl]
                    st.session_state.watchlist_data.pop(selected_wl, None)
                    st.session_state.stock_fundamentals.pop(selected_wl, None)
                    write_json(WATCHLIST_FILE, st.session_state.watchlist)
                    st.session_state.model_cache_key = ""
                    st.rerun()

    # ========== Tab 6: 產業總覽 ==========
    with tabs[6]:
        st.subheader("產業總覽")
        if model_df.empty:
            st.warning("⚠️ 沒有資料")
        else:
            ind_sum = model_df.groupby("group", dropna=False).agg(
                股票數=("ticker", "count"),
                平均20日機率=("prob20", "mean"),
                平均期望報酬=("expected_return_20d", "mean"),
                平均信心度=("confidence", "mean"),
                平均命中率=("hit_rate", "mean"),
                平均風險=("risk_score", "mean"),
                核心候選=("candidate_level", lambda x: (x == "核心候選").sum()),
            ).reset_index().round({
                "平均20日機率": 1, "平均期望報酬": 2, "平均信心度": 1,
                "平均命中率": 1, "平均風險": 1,
            }).rename(columns={"group": "產業"}).sort_values("平均20日機率", ascending=False)

            st.dataframe(ind_sum, use_container_width=True, height=400)

            st.markdown("### 產業期望報酬 vs 風險")
            fig = px.scatter(
                ind_sum, x="平均期望報酬", y="平均風險",
                size="股票數", color="核心候選",
                hover_data=["產業", "平均信心度", "平均命中率"],
                text="產業", title="產業期望報酬風險分析",
                labels={"平均期望報酬": "20日期望報酬(%)", "平均風險": "風險分數"},
                color_continuous_scale="Viridis",
            )
            fig.update_traces(textposition="top center")
            fig.add_hline(y=50, line_dash="dash", line_color="gray", opacity=0.5)
            fig.add_vline(x=0, line_dash="dash", line_color="green", opacity=0.5)
            st.plotly_chart(fig, use_container_width=True)

    # ========== Tab 7: 模型設定 ==========
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

    # ========== Tab 8: 回測報告 ==========
    with tabs[8]:
        st.subheader("回測報告")
        sc = len(st.session_state.snapshots)
        if sc < 5:
            st.warning(f"⚠️ 快照不足（目前 {sc} 筆，建議至少 10 筆）\n\n請每日盤後點擊「💾 保存今日快照」")
        else:
            backtest = BacktestEngine(st.session_state.snapshots)
            start_d, end_d = backtest.get_date_range()
            st.success(f"✅ 已累積 {sc} 個交易日快照")
            st.caption(f"📅 {start_d} ~ {end_d}")

            st.markdown("### 📊 整體回測統計")
            sample_tickers = model_df["ticker"].head(50).tolist()
            with st.spinner("計算中..."):
                stats = backtest.calculate_aggregate_stats(sample_tickers, 20, 3)
            bc1, bc2, bc3, bc4 = st.columns(4)
            bc1.metric("平均命中率", format_percentage(stats["avg_hit_rate"]))
            bc2.metric("中位命中率", format_percentage(stats["median_hit_rate"]))
            bc3.metric("有效樣本數", stats["valid_stocks"])
            bc4.metric("總觀測數",   stats["total_samples"])

            if stats["valid_stocks"] > 0:
                hit_rates = []
                for t in sample_tickers:
                    hr, _, src = backtest.calculate_hit_rate(t, 20, 3)
                    if src == "本機快照":
                        hit_rates.append(hr)
                if hit_rates:
                    fig = px.histogram(x=hit_rates, nbins=20, title="20日命中率分布",
                                       labels={"x": "命中率(%)", "y": "股票數"},
                                       color_discrete_sequence=["rgb(99,110,250)"])
                    fig.add_vline(x=np.mean(hit_rates), line_dash="dash", line_color="red",
                                  annotation_text=f"平均: {np.mean(hit_rates):.1f}%")
                    st.plotly_chart(fig, use_container_width=True)


# ============================================================
# 進入點
# ============================================================

if __name__ == "__main__":
    main()
