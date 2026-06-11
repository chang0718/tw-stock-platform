"""技術分析圖表元件"""

from typing import Dict, Optional

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from tech_analyzer import INDICATOR_EXPLANATIONS


def render_tech_block(ta: Dict, stock: Optional[Dict] = None):
    """技術分析圖表（subplot 版）+ 文字摘要 + 購買信心指數"""
    if "error" in ta:
        st.warning(ta["error"])
        return

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
    prob20     = (stock.get("prob20", 50)          if stock else 50)
    comp_score = (stock.get("composite_score", 50) if stock else 50)
    flow_score = (stock.get("flow_score", 50)      if stock else 50)
    quality    = (stock.get("quality_score", 50)   if stock else 50)

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
    elif buy_confidence >= 55:
        conf_label = "🟡 可分批佈局"
    elif buy_confidence >= 40:
        conf_label = "🟡 觀望"
    else:
        conf_label = "🔴 建議迴避 / 考慮賣出"

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

    t5l, t5h   = ana["target_5d"]
    t20l, t20h = ana["target_20d"]
    tc1, tc2, tc3, tc4 = st.columns(4)
    tc1.metric("現價",       f"${cp:.2f}")
    tc2.metric("5日目標",    f"${t5l:.2f}–${t5h:.2f}", f"{(t5h-cp)/cp*100:+.1f}%")
    tc3.metric("20日目標",   f"${t20l:.2f}–${t20h:.2f}", f"{(t20h-cp)/cp*100:+.1f}%")
    h52, l52 = ana.get("high_52w", cp), ana.get("low_52w", cp)
    pct_52 = (cp - l52) / (h52 - l52) * 100 if h52 != l52 else 50
    tc4.metric("52週位置", f"{pct_52:.0f}%", f"H:{h52:.0f} L:{l52:.0f}")

    st.markdown("#### 📡 技術訊號")
    for sig in ana["signals"]:
        st.write(sig)

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

    with st.expander("📖 各技術指標原理與判讀說明"):
        for key, exp in INDICATOR_EXPLANATIONS.items():
            st.markdown(f"**{exp['name']}**")
            st.caption(f"原理：{exp['principle']}")
            st.markdown(exp["how_to_read"])
            st.markdown("---")
