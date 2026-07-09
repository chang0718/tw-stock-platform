"""籌碼資料顯示元件"""

import streamlit as st
import plotly.graph_objects as go

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


def render_major_holder_block(foreign_trend: list, major: dict):
    """
    大戶 / 主力籌碼（免費資料源）：
      - 外資持股比例趨勢（FinMind，每日）：最大法人主力的「持股水位」
      - 集保大戶持股比例（TDCC，每週）：≥1000 張 / ≥400 張大戶占比

    ⚠️ 定位：持股「存量水位」，與 T86 每日「買賣超流量」互補。
       非券商分點「主力進出」（該資料需付費），此處為官方免費替代指標。
    """
    st.markdown("##### 🐳 大戶／外資籌碼水位（免費資料）")
    st.caption(
        "存量觀點：外資持股比例（每日）＋集保大戶持股比例（每週）。"
        "與上方 T86『當日買賣超』互補——一個看水位、一個看流速。"
    )

    # ── 外資持股比例趨勢（每日）───────────────────────────────────
    ft = [p for p in (foreign_trend or []) if p.get("foreign_ratio") is not None]
    if ft:
        latest = ft[-1]
        ref = ft[-21] if len(ft) >= 21 else ft[0]  # 約 20 交易日前
        delta = round(latest["foreign_ratio"] - ref["foreign_ratio"], 2)
        cA, cB = st.columns([1, 2])
        with cA:
            st.metric(
                "外資持股比例",
                f"{latest['foreign_ratio']:.2f}%",
                delta=f"{delta:+.2f}pp（近月）",
                help="外資持有占已發行股數比例。上升=外資增持、下降=減持。資料：FinMind（每日）。",
            )
            st.caption(f"資料日：{latest.get('date','')}")
        with cB:
            fig = go.Figure()
            fig.add_scatter(
                x=[p["date"] for p in ft],
                y=[p["foreign_ratio"] for p in ft],
                mode="lines", line=dict(color="#26a69a", width=2),
                name="外資持股%",
            )
            fig.update_layout(
                title="外資持股比例趨勢（%）",
                height=220, margin=dict(t=34, b=16, l=8, r=8),
                paper_bgcolor="#0d1117", plot_bgcolor="#161b22",
                font=dict(color="#8b949e"), showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("（外資持股比例：暫無資料，需 FinMind 可用）")

    # ── 集保大戶持股比例（每週）──────────────────────────────────
    if major and major.get("has_data"):
        def _wow(v):
            return f"{v:+.2f}pp（週）" if v is not None else None
        d1, d2 = st.columns(2)
        d1.metric(
            "大戶持股 ≥1000 張",
            f"{major.get('ge1000_ratio', 0):.2f}%",
            delta=_wow(major.get("wow_ge1000")),
            help="持有 1,000 張以上大戶，占集保庫存比例。資料：集保 TDCC（每週）。",
        )
        d2.metric(
            "大戶持股 ≥400 張",
            f"{major.get('ge400_ratio', 0):.2f}%",
            delta=_wow(major.get("wow_ge400")),
            help="持有 400 張以上大戶占比。",
        )
        _tw = len(major.get("trend", []))
        _wk_hint = "（首次載入僅一週，之後每週累積可見增減）" if _tw < 2 else ""
        st.caption(
            f"集保股權分散資料日：{major.get('date','')}（每週更新）{_wk_hint}"
        )
    else:
        st.caption("（集保大戶持股：暫無資料）")

    st.caption(
        "ℹ️ 大戶持股上升不必然=看多，需搭配基本面與估值判讀；"
        "本區為研究參考，不構成投資建議。真正的『券商分點主力進出』需付費資料，本平台不採用。"
    )
