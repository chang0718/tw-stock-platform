"""
全域 session state 初始化與快取 key 管理。
所有 st.session_state 的初始 key 集中在此定義，避免散落在 app.py 各處。
"""

import pandas as pd
import streamlit as st

from config import DEFAULT_WEIGHTS, NOTES_FILE, SNAPSHOT_FILE, WATCHLIST_FILE, WEIGHTS_FILE
from portfolio import Portfolio
from utils import read_json


def initialize_session_state() -> None:
    defaults = {
        "universe_df":        pd.DataFrame(),
        "weights":            read_json(WEIGHTS_FILE, DEFAULT_WEIGHTS),
        "notes":              read_json(NOTES_FILE, {}),
        "last_update":        None,
        "data_date":          "",
        # 追蹤清單：{ticker: {name, added_date}}
        "watchlist":          read_json(WATCHLIST_FILE, {}),
        "watchlist_data":     {},   # {ticker: {fundamental, news, name}}
        # 法人 / 融資券（市場載入時抓）
        "institutional_data": {"inst": {}, "margin": {}},
        # 個別股票已載入的基本面
        "stock_fundamentals": {},
        # 模型輸出快取
        "model_df_cached":    pd.DataFrame(),
        "model_cache_key":    "",
        # FinMind token
        "finmind_token":      "",
        # 技術分析快取 {ticker: analysis_dict}
        "tech_data":          {},
        # 美股市場快取
        "us_market_data":     {},
        "us_market_ts":       0,
        # 持倉管理
        "portfolio":          Portfolio(),
        # 每日快照（回測/調優用）
        "snapshots":          read_json(SNAPSHOT_FILE, []),
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
