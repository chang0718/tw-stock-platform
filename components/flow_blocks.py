"""籌碼資料顯示元件"""

import streamlit as st

from twse_institutional import TWSeInstitutionalLoader


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
                    _pd = st.session_state.get("data_date", "")
                    st.session_state.institutional_data = {
                        "inst":   il.get_institutional_all(
                            finmind_token=st.session_state.get("finmind_token", ""),
                            prefer_date=_pd,
                        ) or {},
                        "margin": il.get_margin_all(prefer_date=_pd) or {},
                    }
                    st.session_state.model_cache_key = ""
                st.rerun()
        return

    _inst_date = stock.get("inst_date") or stock.get("date", "")
    _date_hint = f"　日期：{_inst_date}" if _inst_date else ""
    st.caption(f"資料來源：{src}{_date_hint}　｜　單位：張（= 千股 = 1,000 股）")

    c1, c2, c3 = st.columns(3)
    def _flow(col, label, val):
        with col:
            if val is not None:
                col.metric(label, f"{val:+,} 張",
                           help="正值=買超（法人在買進），負值=賣超（法人在賣出）。單位：張（1張=1,000股）。")
            else:
                col.metric(label, "N/A")
    _flow(c1, "外資今日買賣超", stock.get("foreign_net"))
    _flow(c2, "投信今日買賣超", stock.get("trust_net"))
    _flow(c3, "自營今日買賣超", stock.get("dealer_net"))

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
        sc_val = stock.get("short_change")
        if sb is not None:
            c5.metric("融券餘額", f"{sb:,}", delta=f"{sc_val:+,}" if sc_val else None)
        else:
            c5.metric("融券餘額", "N/A")
