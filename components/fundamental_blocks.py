"""基本面顯示元件：render_fundamental_block + render_health_check_block"""

from typing import Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from quant_model import QuantModel


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

    _rev_month = fund.get("latest_revenue_month", "")
    _rev_label = f"營收年增率（{_rev_month}）" if _rev_month else "營收年增率"

    # ── 三率（毛利 / 營益 / 淨利）並列 ──────────────────────────────
    st.markdown("**📐 三率（最新一季）**")
    t1, t2, t3 = st.columns(3)
    _m(t1, "毛利率",       fund.get("gross_margin"),
       lambda v: f"{v:.1f}%", "扣掉直接成本後還剩多少比例。>30%不錯；>50%護城河強")
    _m(t2, "營業利益率",   fund.get("operating_margin"),
       lambda v: f"{v:.1f}%", "本業賺錢效率（毛利再扣管銷研發費用）。反映本業競爭力與費用控管，高值化轉型的關鍵指標。")
    _m(t3, "淨利率",       fund.get("net_margin"),
       lambda v: f"{v:.1f}%", "最終賺到的比例（扣掉所有費用與稅）。>10%算不錯")

    # ── 獲利 / 成長 / 估值 ─────────────────────────────────────────
    _m(c1, _rev_label, fund.get("revenue_yoy"),
       lambda v: f"{v:+.1f}%", f"最新月份（{_rev_month}）月營收 vs 去年同月比較。正數=成長，負數=衰退。")
    _m(c2, "EPS（近四季 TTM）", fund.get("eps"),
       lambda v: f"${v:.2f}", "近四季每股盈餘合計（TTM）。越高越好，負數代表虧損。用於計算 PE/公平價。")
    _m(c3, "EPS年增率（TTM YoY）", fund.get("eps_growth_yoy"),
       lambda v: f"{v:+.1f}%", "近四季合計 EPS vs 前四季合計 EPS 的增長率。正值=獲利成長，負值=衰退。")
    _m(c4, "本益比 PE",    fund.get("pe"),
       lambda v: f"{v:.1f}倍", "股價是每年獲利的幾倍。<15倍偏便宜；>30倍偏貴")

    c5, c6 = st.columns(2)
    _m(c5, "股價淨值比",  fund.get("pb"),
       lambda v: f"{v:.2f}倍", "股價是帳面價值的幾倍。<1倍可能被低估；>3倍偏貴")
    _m(c6, "現金殖利率",  fund.get("dividend_yield"),
       lambda v: f"{v:.2f}%",  "每年配股息的比例。>5%適合存股；<2%配息少")

    if fund.get("latest_revenue_month"):
        st.caption(f"最新營收月份: {fund['latest_revenue_month']} ｜ 資料來源: {src_label}")

    # ── 白話解讀 ──────────────────────────────────────────────────
    pe  = fund.get("pe")
    gm  = fund.get("gross_margin")
    om  = fund.get("operating_margin")
    nm  = fund.get("net_margin")
    ry  = fund.get("revenue_yoy")
    dy  = fund.get("dividend_yield")

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
    if om is not None and gm is not None:
        _gap = gm - om
        if om >= 15:
            interps.append(f"✅ **營益率 {om:.1f}%**：本業獲利能力強，費用控管良好")
        elif om >= 7:
            interps.append(f"➡️ **營益率 {om:.1f}%**：本業獲利穩健（毛利到營益流失約 {_gap:.1f} 個百分點為營業費用）")
        elif om > 0:
            interps.append(f"🟡 **營益率 {om:.1f}%**：本業獲利偏薄，營業費用占比較高，留意費用率變化")
        else:
            interps.append(f"🔴 **營益率 {om:.1f}%**：本業虧損，須確認是一次性因素或結構性問題")
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


def render_health_check_block(fund: dict, fin_trend: Optional[List] = None,
                               val_pct: Optional[dict] = None, epsfv: Optional[dict] = None,
                               compact: bool = False):
    """
    個股四維健檢儀表板（參考 winvest.tw 風格）。
    compact=True 時只顯示分數條，不顯示詳細說明。
    """
    scores = QuantModel.health_check_score(fund, fin_trend, val_pct, epsfv)
    if not fund or fund.get("data_type") == "NO_DATA":
        st.caption("⚠️ 健檢需要基本面資料（請載入個股或填入 FinMind token）")
        return

    total   = scores["total"]
    verdict = scores["verdict"]
    color   = scores["verdict_color"]

    # ── 總評橫幅 ──────────────────────────────────────────────────
    st.markdown(
        f'<div style="background:{color}22;border-left:4px solid {color};'
        f'padding:10px 16px;border-radius:6px;margin-bottom:12px;">'
        f'<span style="font-size:20px;font-weight:700;color:{color}">{total:.0f} 分</span>'
        f'&ensp;<span style="color:#e6edf3;font-size:15px">{verdict}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── 四維進度條 ────────────────────────────────────────────────
    dims = [
        ("💰 獲利力", scores["profitability"],
         "EPS / 毛利率 / 淨利率 / ROE 綜合評分"),
        ("📈 成長力", scores["growth"],
         "營收 YoY / EPS YoY / 最新季加速度"),
        ("🎁 股利力", scores["dividend"],
         "現金殖利率 / 配息可持續性"),
        ("⚖️ 估 值", scores["valuation"],
         "PE 歷史分位 / PB / 公平價估算"),
    ]
    _hc_cols = st.columns(4)
    for col, (label, sc, tip) in zip(_hc_cols, dims):
        with col:
            _bar_color = "#26a69a" if sc >= 70 else ("#ff9800" if sc >= 45 else "#ef5350")
            st.markdown(f"**{label}**")
            st.markdown(
                f'<div style="background:#30363d;border-radius:4px;height:8px;margin:4px 0 2px">'
                f'<div style="background:{_bar_color};width:{sc}%;height:8px;border-radius:4px"></div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.markdown(f'<span style="font-size:18px;font-weight:700;color:{_bar_color}">{sc:.0f}</span>'
                        f'<span style="font-size:12px;color:#8b949e"> / 100</span>',
                        unsafe_allow_html=True)
            if not compact:
                st.caption(tip)

    if compact:
        return

    # ── 估值資料缺失提示 ────────────────────────────────────────────
    if scores["valuation"] == 0 and not (val_pct or epsfv):
        st.info(
            "ℹ️ **估值分數 = 0**：尚無歷史 PE/PB 分位資料。"
            "請在 **⚙️ 模型設定** 填入 FinMind Token，並在本 Tab 向下捲動載入「PE/PB 歷史分位」後，"
            "估值分數將自動更新（快取在 session，重新選股即生效）。"
        )

    # ── 雷達圖 ────────────────────────────────────────────────────
    _categories = ["獲利力", "成長力", "股利力", "估值", "獲利力"]
    _values = [scores["profitability"], scores["growth"],
               scores["dividend"],      scores["valuation"],
               scores["profitability"]]
    _fig_radar = go.Figure(go.Scatterpolar(
        r=_values, theta=_categories, fill="toself",
        line_color="#1f6feb", fillcolor="rgba(31,111,235,0.25)",
        name="健檢分數",
    ))
    _fig_radar.add_trace(go.Scatterpolar(
        r=[70, 70, 70, 70, 70], theta=_categories,
        mode="lines", line=dict(color="#ff9800", dash="dot", width=1),
        name="良好基準線（70）",
    ))
    _fig_radar.update_layout(
        polar=dict(
            bgcolor="#161b22",
            radialaxis=dict(visible=True, range=[0, 100], tickfont=dict(color="#8b949e")),
            angularaxis=dict(tickfont=dict(color="#e6edf3")),
        ),
        paper_bgcolor="#0d1117",
        showlegend=True,
        height=320, margin=dict(t=20, b=20),
        legend=dict(font=dict(color="#8b949e"), bgcolor="#0d1117"),
    )
    st.plotly_chart(_fig_radar, use_container_width=True)

    # ── 加分明細（可展開）+ 白話術語解說 ───────────────────────────
    _TERM_EXPLAIN = {
        "EPS盈利":    "每股盈餘（EPS）：公司每1股在過去12個月賺了多少錢。正值=獲利，負值=虧損，是最基本的獲利能力指標。",
        "毛利率":     "毛利率：賣出商品扣除直接成本（原料、製造費）後剩的比例。越高代表定價能力越強。>30%算優秀，>50%代表強護城河。",
        "淨利率":     "淨利率：扣掉所有費用（管銷、研發、稅等）後，最終賺到的比例。>10%不錯，>15%卓越，<5%要留意費用控制。",
        "ROE":        "股東權益報酬率（ROE）：公司用股東投入的錢賺了多少，衡量管理效率。>15%代表高效，<8%代表資本運用偏差。",
        "營收YoY":   "月營收年增率：和去年同月相比，銷售額成長或衰退多少（%）。持續正成長是好訊號，衰退需確認是否為產業性還是公司特定問題。",
        "EPS YoY":   "EPS 年增率（TTM YoY）：近四季獲利合計 vs 前四季合計的成長率。>20%為加速成長，負值代表獲利在下滑。",
        "季度加速":   "最新一季和去年同季比較的 EPS 成長率。連續加速（每季比去年同期更好）代表獲利動能持續增強，是強勢的訊號。",
        "殖利率":     "現金殖利率：每年配發的股息 ÷ 目前股價。代表持股每年能領到多少利息比例。>4%算高息股，<2%以配息角度吸引力偏低。",
        "盈利能力":   "EPS 為正，代表公司目前有獲利，具備未來配發現金股利的能力基礎。",
        "估值加成":   "本益比偏低（PE < 20倍），代表以目前股價買到每單位獲利更便宜，也讓殖利率有較高空間。",
        "配息可持續": "以殖利率 × PE 估算的配息比率（payout ratio proxy）。若估算比率 < 100% 代表配息有可能可持續。",
        "PE分位":     "本益比歷史分位數：目前 PE 在過去3年中的位置。25%以下=歷史便宜區（低估），75%以上=歷史貴區（高估），50%=中性。",
        "PB":         "股價淨值比（PB）：股價是帳面資產的幾倍。<1.5倍通常算便宜，>3倍偏貴。金融業和資產重的公司更常用 PB 評估。",
        "公平價估值": "以歷史 PE 中位數×近四季 EPS 計算的合理價，和目前 PE 在歷史分位比較，判斷目前股價是偏高還是偏低。",
    }
    if scores.get("details"):
        with st.expander("📋 健檢評分明細（含術語解說）", expanded=False):
            _det = scores["details"]
            _d1, _d2 = st.columns(2)
            _profit_keys = [k for k in _det if k in ("EPS盈利", "毛利率", "淨利率", "ROE")]
            _growth_keys = [k for k in _det if k in ("營收YoY", "EPS YoY", "季度加速")]
            _div_keys    = [k for k in _det if k in ("殖利率", "盈利能力", "估值加成", "配息可持續")]
            _val_keys    = [k for k in _det if k in ("PE分位", "PB", "公平價估值")]

            def _show_items(keys):
                for k in keys:
                    st.markdown(f"**• {k}**：{_det[k]}")
                    if k in _TERM_EXPLAIN:
                        st.caption(f"  💬 {_TERM_EXPLAIN[k]}")

            with _d1:
                st.markdown("**💰 獲利力**")
                _show_items(_profit_keys)
                st.markdown("**📈 成長力**")
                _show_items(_growth_keys)
            with _d2:
                st.markdown("**🎁 股利力**")
                _show_items(_div_keys)
                st.markdown("**⚖️ 估值**")
                _show_items(_val_keys)
    st.caption("⚠️ 健檢評分為量化模型參考，不構成投資建議。請結合產業趨勢與個人風險承受度自行判斷。")


def render_earnings_summary(fund: Dict, val_pct: Optional[dict] = None):
    """
    財報重點摘要（結論摘要式條列）：三率 + EPS(TTM) + 營收動能 + 估值狀態。
    語氣合規（長期研究導向，不做短線擇時建議）。重用既有 fund 欄位。
    """
    if not fund or fund.get("data_type") == "NO_DATA":
        return

    parts: List[str] = []

    gm, om, nm = fund.get("gross_margin"), fund.get("operating_margin"), fund.get("net_margin")
    if any(v is not None for v in (gm, om, nm)):
        rates = []
        if gm is not None: rates.append(f"毛利 {gm:.1f}%")
        if om is not None: rates.append(f"營益 {om:.1f}%")
        if nm is not None: rates.append(f"淨利 {nm:.1f}%")
        parts.append("**三率（最新季）**：" + "／".join(rates))

    eps = fund.get("eps")
    egy = fund.get("eps_growth_yoy")
    if eps is not None:
        s = f"**EPS（近四季 TTM）**：{eps:.2f} 元"
        if egy is not None:
            s += f"（年增 {egy:+.1f}%）"
        parts.append(s)

    ry = fund.get("revenue_yoy")
    rmm = fund.get("revenue_mom")
    rmonth = fund.get("latest_revenue_month", "")
    if ry is not None:
        s = f"**月營收動能**：{rmonth + ' ' if rmonth else ''}年增 {ry:+.1f}%"
        if rmm is not None:
            s += f"、月增 {rmm:+.1f}%"
        parts.append(s)

    pe = fund.get("pe")
    pe_pct = val_pct.get("pe_pct") if val_pct else None
    if pe_pct is not None:
        tag = "歷史低估區" if pe_pct < 30 else "歷史偏高區" if pe_pct > 70 else "歷史中性區"
        head = f"PE {pe:.1f}倍，" if pe is not None else "PE "
        parts.append(f"**估值**：{head}位於近 3 年 {pe_pct:.0f}% 分位（{tag}）")
    elif pe is not None:
        parts.append(f"**估值**：PE {pe:.1f}倍")

    if not parts:
        return

    st.markdown("##### 🧾 財報重點摘要")
    for p in parts:
        st.markdown(f"- {p}")
    st.caption("⚠️ 以上為已公布財報數據整理，僅供長期研究參考，不構成買賣或擇時建議。")


def render_three_rates(fin_trend: Optional[List[Dict]]):
    """三率（毛利 / 營益 / 淨利）近 8 季趨勢圖。重用 FinMindLoader.get_financial_trend。"""
    if not fin_trend:
        st.caption("⚠️ 無季報三率資料（需 FinMind token）")
        return

    df = pd.DataFrame(fin_trend)
    st.markdown("##### 📈 三率趨勢（近 8 季）")
    fig = go.Figure()
    for col, name, color in [
        ("gross_margin",     "毛利率", "#1f6feb"),
        ("operating_margin", "營益率", "#26a69a"),
        ("net_margin",       "淨利率", "#ff9800"),
    ]:
        if col in df.columns and df[col].notna().any():
            fig.add_scatter(x=df["quarter"], y=df[col], name=name,
                            mode="lines+markers", line=dict(color=color, width=2))
    fig.update_layout(
        height=260, margin=dict(t=10, b=20),
        yaxis=dict(title="%"), legend=dict(orientation="h", y=-0.25),
        paper_bgcolor="#0d1117", plot_bgcolor="#161b22",
        font=dict(color="#8b949e"),
    )
    st.plotly_chart(fig, use_container_width=True)

    if len(df) >= 2:
        last, prev = df.iloc[-1], df.iloc[-2]
        notes = []
        for col, name in [("gross_margin", "毛利率"), ("operating_margin", "營益率"), ("net_margin", "淨利率")]:
            cur, pv = last.get(col), prev.get(col)
            if pd.notna(cur) and pd.notna(pv):
                diff = cur - pv
                arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "→")
                notes.append(f"{name} {cur:.1f}%（{arrow}{abs(diff):.1f}pt）")
        if notes:
            st.caption("最新季 vs 前季： " + " ｜ ".join(notes)
                       + "　—　三率同步走升代表本業獲利品質改善。")


def render_peer_comparison(target_ticker: str, model_df, key_prefix: str = ""):
    """
    同業比較表：可切換『供應鏈群組 / 產業別』。target 個股以底色標示。
    僅使用 model_df 既有欄位（不額外呼叫 API）。
    """
    if model_df is None or getattr(model_df, "empty", True):
        st.caption("⚠️ 無同業比較資料（市場資料未載入）")
        return
    if target_ticker not in model_df["ticker"].values:
        st.caption("⚠️ 此股不在目前市場資料中，無法比較同業")
        return

    trow = model_df[model_df["ticker"] == target_ticker].iloc[0]
    mode = st.radio(
        "同業範圍", ["供應鏈群組", "產業別"],
        horizontal=True, key=f"peer_mode_{key_prefix}{target_ticker}",
    )
    col = "group" if mode == "供應鏈群組" else "industry"
    val = trow.get(col)
    if col not in model_df.columns or val is None:
        st.info("目前資料缺少分類欄位，無法比較同業。")
        return
    peers = model_df[model_df[col] == val].copy()
    if len(peers) < 2:
        st.info(f"此{mode}（{val}）目前無足夠同業可比較。")
        return

    want = [
        ("ticker", "代號"), ("name", "名稱"), ("close", "收盤"),
        ("change_pct", "漲跌%"), ("pe", "PE"), ("gross_margin", "毛利率%"),
        ("revenue_yoy", "營收YoY%"), ("risk_score", "風險分"),
    ]
    use = [(c, l) for c, l in want if c in peers.columns]
    disp = peers[[c for c, _ in use]].copy()
    if "pe" in disp.columns:
        disp = disp.sort_values("pe", na_position="last")
    disp = disp.rename(columns=dict(use))

    fmt = {}
    for c, l in use:
        if c == "close":            fmt[l] = "{:.1f}"
        elif c == "change_pct":     fmt[l] = "{:+.2f}%"
        elif c == "pe":             fmt[l] = "{:.1f}"
        elif c == "gross_margin":   fmt[l] = "{:.1f}%"
        elif c == "revenue_yoy":    fmt[l] = "{:+.1f}%"
        elif c == "risk_score":     fmt[l] = "{:.0f}"

    def _hl(row):
        is_t = (row.get("代號") == target_ticker)
        return ['background-color:#1f6feb44;font-weight:700' if is_t else '' for _ in row]

    st.markdown(f"##### 🏭 同業比較（{mode}：{val}）")
    try:
        styler = disp.style.apply(_hl, axis=1).format(fmt, na_rep="--")
        st.dataframe(styler, use_container_width=True, hide_index=True)
    except Exception:
        st.dataframe(disp, use_container_width=True, hide_index=True)
    st.caption(
        f"共 {len(peers)} 檔同{mode}成員，PE 由低到高排序，藍底為目前個股。"
        "（營益率/淨利率屬個股深度欄位，批次比較以毛利率代表獲利力。）"
        "數據僅供研究，不構成投資建議。"
    )


def _fmt_assumptions(assumptions: Optional[Dict]) -> List[str]:
    """把 forecast.py 的 assumptions dict 攤平成可讀的條列字串。"""
    lines: List[str] = []
    if not assumptions:
        return lines
    for k, v in assumptions.items():
        if v is None:
            continue
        lines.append(f"{k}：{v}")
    return lines


def render_forecast_block(estimates: Dict):
    """
    前瞻推估區塊（營收 / EPS / Forward P/E）。

    ⚠️ 合規：`estimates` 來自 forecast.build_forward_estimates()，
    所有數字皆為「模型 run-rate 歷史外推」，非分析師共識/財測。
    本區塊必須明確標示此性質、列出假設，並附下行免責。
    """
    if not estimates or not estimates.get("has_data"):
        st.info(
            "ℹ️ 目前資料不足，無法進行前瞻推估。"
            "需要更完整的月營收與季報 EPS 歷史（請填入 FinMind token 並加入追蹤後自動更新）。"
        )
        return

    revenue = estimates.get("revenue") or {}
    eps = estimates.get("eps") or {}
    eps_fy1 = estimates.get("eps_fy1") or {}
    fwd_pe = estimates.get("forward_pe") or {}

    # ── 標題 + 性質標示 ────────────────────────────────────────────
    st.markdown("#### 🔮 前瞻推估（模型 run-rate 外推）")
    st.caption(
        "⚠️ 以下為**模型 run-rate 歷史外推推估，非分析師共識/財測**。"
        "免費資料源（FinMind/yfinance）無分析師預估，此處純以歷史營收/EPS 動能外推，"
        "僅供研究與風險評估參考，不構成投資建議。"
    )

    # ── EPS 長條圖（歷史實際 + 本年估 + FY+1 估）────────────────────
    curr_year = eps.get("curr_year") or revenue.get("curr_year")
    fy_eps_est = eps.get("fy_eps_est")
    fy1_eps_est = eps_fy1.get("fy1_eps_est")

    if fy_eps_est is not None or fy1_eps_est is not None:
        st.markdown("##### 📊 年度 EPS：歷史實際 vs 推估")
        eps_x, eps_y, eps_colors, eps_patterns = [], [], [], []
        # 歷史年度實際 EPS（實心柱）：來自 forecast.py eps.annual_actuals
        eps_actuals = eps.get("annual_actuals") or {}
        for y in sorted(eps_actuals.keys()):
            eps_x.append(str(y))
            eps_y.append(eps_actuals[y])
            eps_colors.append("#1f6feb")
            eps_patterns.append("")
        # 本年估 / FY+1 估（斜線推估柱）
        if fy_eps_est is not None and curr_year is not None:
            eps_x.append(f"{curr_year}(推估)")
            eps_y.append(fy_eps_est)
            eps_colors.append("#26a69a")
            eps_patterns.append("/")
        if fy1_eps_est is not None and curr_year is not None:
            eps_x.append(f"{curr_year + 1}(推估)")
            eps_y.append(fy1_eps_est)
            eps_colors.append("#7ee0d0")
            eps_patterns.append("/")

        if eps_x:
            fig_eps = go.Figure()
            fig_eps.add_bar(
                x=eps_x, y=eps_y,
                marker_color=eps_colors, opacity=0.85,
                marker_pattern=dict(shape=eps_patterns),
                text=[f"{v:.2f}" for v in eps_y], textposition="outside",
                name="EPS 估",
            )
            fig_eps.update_layout(
                title="年度 EPS（實心=歷史實際，斜線=模型推估）",
                height=300, margin=dict(t=40, b=20),
                yaxis=dict(title="EPS(元)"),
                paper_bgcolor="#0d1117", plot_bgcolor="#161b22",
                font=dict(color="#8b949e"), showlegend=False,
            )
            st.plotly_chart(fig_eps, use_container_width=True)

        # FY+1 保守/基準/樂觀帶
        cons = eps_fy1.get("fy1_eps_conservative")
        base = eps_fy1.get("fy1_eps_est")
        opti = eps_fy1.get("fy1_eps_optimistic")
        if any(v is not None for v in (cons, base, opti)) and curr_year is not None:
            st.markdown(f"**{curr_year + 1} 年 EPS 推估區間（±10pp 情境帶）**")
            bc1, bc2, bc3 = st.columns(3)
            bc1.metric("保守", f"{cons:.2f} 元" if cons is not None else "—")
            bc2.metric("基準", f"{base:.2f} 元" if base is not None else "—")
            bc3.metric("樂觀", f"{opti:.2f} 元" if opti is not None else "—")

    # ── 營收長條圖（歷史年度實際 + 本年估）─────────────────────────
    fy_rev_est = revenue.get("fy_revenue_est")
    annual_actuals = revenue.get("annual_actuals") or {}
    rev_curr_year = revenue.get("curr_year")
    if fy_rev_est is not None or annual_actuals:
        st.markdown("##### 📊 年度營收：歷史實際 vs 本年估")
        # 月營收（FinMind）單位為「千元」，換算為「億元」需 ÷ 1e5
        rev_x, rev_y, rev_colors, rev_patterns = [], [], [], []
        for y in sorted(annual_actuals.keys()):
            rev_x.append(str(y))
            rev_y.append(annual_actuals[y] / 1e5)  # 千元 → 億元
            rev_colors.append("royalblue")
            rev_patterns.append("")
        if fy_rev_est is not None and rev_curr_year is not None:
            rev_x.append(f"{rev_curr_year}(推估)")
            rev_y.append(fy_rev_est / 1e5)
            rev_colors.append("#8ab4f8")
            rev_patterns.append("/")

        if rev_x:
            fig_rev = go.Figure()
            fig_rev.add_bar(
                x=rev_x, y=rev_y,
                marker_color=rev_colors, opacity=0.8,
                marker_pattern=dict(shape=rev_patterns),
                text=[f"{v:,.0f}" for v in rev_y], textposition="outside",
                name="年度營收",
            )
            fig_rev.update_layout(
                title="年度營收（億元；斜線=本年進度追蹤推估）",
                height=300, margin=dict(t=40, b=20),
                yaxis=dict(title="營收(億元)"),
                paper_bgcolor="#0d1117", plot_bgcolor="#161b22",
                font=dict(color="#8b949e"), showlegend=False,
            )
            st.plotly_chart(fig_rev, use_container_width=True)
            if revenue.get("months_reported"):
                st.caption(
                    f"本年已公布 {revenue['months_reported']} 個月實際，"
                    f"剩餘月份以『去年同月 ×(1+近3月平均YoY)』推估。"
                )

    # ── Forward P/E ───────────────────────────────────────────────
    if fwd_pe:
        st.markdown("##### ⚖️ 前瞻本益比 Forward P/E")
        pe1, pe2, pe3 = st.columns(3)
        fwd_cur = fwd_pe.get("fwd_pe_cur")
        fwd_next = fwd_pe.get("fwd_pe_next")
        hist_med = fwd_pe.get("hist_median_pe")
        pe1.metric("本年前瞻 PE", f"{fwd_cur:.1f} 倍" if fwd_cur is not None else "—",
                   help="現價 ÷ 本年 EPS 估")
        pe2.metric("FY+1 前瞻 PE", f"{fwd_next:.1f} 倍" if fwd_next is not None else "—",
                   help="現價 ÷ 明年 EPS 估")
        pe3.metric("歷史 PE 中位", f"{hist_med:.1f} 倍" if hist_med is not None else "—",
                   help="近 3 年 PE 中位數，作為前瞻 PE 高低估的對照基準")

        if fwd_pe.get("overvalued_warning"):
            st.warning(
                "🔴 " + (fwd_pe.get("warning_msg")
                         or "前瞻本益比已明顯高於歷史中位，可能已反映樂觀預期·不宜追高。")
            )

    # ── 假設條列 ──────────────────────────────────────────────────
    assump_lines: List[str] = []
    for _label, _blk in [("營收估", revenue), ("EPS 估", eps),
                         ("FY+1 EPS 估", eps_fy1), ("Forward P/E", fwd_pe)]:
        _al = _fmt_assumptions(_blk.get("assumptions"))
        if _al:
            assump_lines.append(f"**{_label}**：" + "；".join(_al))
    if assump_lines:
        with st.expander("📋 推估假設與方法（模型參數）", expanded=False):
            for _ln in assump_lines:
                st.markdown(f"- {_ln}")

    # ── 下行免責 ──────────────────────────────────────────────────
    st.caption(
        estimates.get("disclaimer")
        or "歷史推估不代表未來，僅供研究與風險評估，不構成投資建議。"
    )
