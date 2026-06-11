"""新聞情緒顯示元件"""

from typing import Dict

import streamlit as st


def render_news_block(news_data: Dict):
    """新聞情緒區塊（直接列新聞，不顯示無意義情緒分數）"""
    if not news_data:
        return

    s         = news_data.get("sentiment", {})
    news_list = news_data.get("news", [])

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
