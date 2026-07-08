"""情勢雷達 UI 元件"""

from typing import Dict, List

import streamlit as st


# ── 顏色常數 ────────────────────────────────────────────────────────────────

_HEAT_COLOR = {
    "high":   "#ef5350",   # >= 60
    "mid":    "#ff9800",   # >= 30
    "low":    "#26a69a",   # < 30
}

_STATUS_BADGE = {
    "official":  ("✅ 官方確認", "#26a69a"),
    "scheduled": ("📅 制度排程", "#1f6feb"),
    "watch":     ("👁️ 觀察", "#8b949e"),
    "推定":       ("🔶 週期推定", "#d29922"),
}

_WINDOW_COLOR = {
    "near":      "#ef5350",
    "short_mid": "#ff9800",
    "mid":       "#1f6feb",
    "long":      "#8b949e",
    "watchlist": "#484f58",
}


def render_theme_cards(themes: List[Dict], max_cards: int = 6) -> None:
    """
    顯示主題卡片（每行 3 欄）。
    每張卡含：icon + 名稱、熱度進度條、最新 2 則新聞標題、受益供應鏈 tag。
    """
    if not themes:
        st.caption("⚠️ 目前無主題訊號（新聞資料可能尚未載入）")
        return

    top = [t for t in themes if t.get("heat_score", 0) > 0][:max_cards]
    cold = [t for t in themes if t.get("heat_score", 0) == 0][:max(0, max_cards - len(top))]
    display = top + cold

    cols = st.columns(3)
    for i, th in enumerate(display):
        col = cols[i % 3]
        heat = th.get("heat_score", 0)
        _bar_color = _HEAT_COLOR["high"] if heat >= 60 else (_HEAT_COLOR["mid"] if heat >= 30 else _HEAT_COLOR["low"])
        heat_label = "🔥🔥🔥" if heat >= 70 else ("🔥🔥" if heat >= 40 else ("🔥" if heat >= 15 else ""))

        with col:
            st.markdown(
                f'<div style="background:#161b22;border:1px solid #30363d;border-radius:8px;'
                f'padding:12px 14px;margin-bottom:8px;">'
                f'<div style="font-size:15px;font-weight:700;color:#e6edf3">'
                f'{th.get("icon","📌")} {th.get("theme","")}</div>'
                f'<div style="display:flex;align-items:center;gap:6px;margin:6px 0 2px">'
                f'<div style="flex:1;background:#30363d;border-radius:3px;height:6px">'
                f'<div style="background:{_bar_color};width:{min(heat,100)}%;height:6px;border-radius:3px"></div>'
                f'</div>'
                f'<span style="font-size:12px;color:{_bar_color};white-space:nowrap">'
                f'{heat} {heat_label}</span></div>',
                unsafe_allow_html=True,
            )
            headlines = th.get("headlines", [])
            if headlines:
                for hl in headlines[:2]:
                    st.markdown(
                        f'<div style="font-size:12px;color:#8b949e;margin:3px 0;'
                        f'overflow:hidden;white-space:nowrap;text-overflow:ellipsis">'
                        f'・{hl}</div>',
                        unsafe_allow_html=True,
                    )
            else:
                kws = th.get("keywords", [])
                if kws:
                    st.markdown(
                        f'<div style="font-size:12px;color:#484f58;margin:3px 0">'
                        f'關鍵字：{" / ".join(kws[:4])}</div>',
                        unsafe_allow_html=True,
                    )
            # 受益供應鏈 tags
            beneficiary = th.get("beneficiary", [])
            if beneficiary:
                tags_html = "".join(
                    f'<span style="background:#1f6feb22;color:#388bfd;border:1px solid #1f6feb44;'
                    f'border-radius:3px;padding:1px 5px;font-size:11px;margin:2px">{g}</span>'
                    for g in beneficiary[:3]
                )
                st.markdown(
                    f'<div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:2px">'
                    f'{tags_html}</div>',
                    unsafe_allow_html=True,
                )
            st.markdown("</div>", unsafe_allow_html=True)

    st.caption("⚠️ 熱度分數基於近 3-7 日新聞關鍵字匹配，不構成投資建議。實際供應鏈受益需參考公司財報與法說。")


def render_event_calendar(events: List[Dict], max_events: int = 12) -> None:
    """
    顯示未來事件清單。
    欄位：距今天數、日期、事件名稱、類型 icon、影響方向、受影響供應鏈、來源。
    """
    if not events:
        st.info("ℹ️ 未來 60 天內無已知重要事件（種子事件日曆可能需要更新）")
        return

    top_events = events[:max_events]

    st.markdown(f"**共 {len(events)} 個事件，顯示前 {len(top_events)} 個（依優先度排序）**")

    for ev in top_events:
        days_until = ev.get("days_until", 0)
        window_id  = ev.get("time_window", {}).get("id", "")
        badge_color = _WINDOW_COLOR.get(window_id, "#484f58")

        status = ev.get("status", "watch")
        status_icon, _sc = _STATUS_BADGE.get(status, ("📌", "#8b949e"))
        direction_label = ev.get("direction_label", "⚪ 觀察")

        # 受影響供應鏈名稱
        chains = ev.get("affected_chains", [])
        chains_str = " · ".join(c["name"] for c in chains[:3]) if chains else "—"

        source_url  = ev.get("source_url", "")
        source_name = ev.get("source_name", "")
        source_link = f"[{source_name}]({source_url})" if source_url else source_name

        with st.expander(
            f"{ev.get('icon','📌')} **{ev.get('title','')}**　"
            f"`{ev.get('start_date','')}` · {days_until} 天後　{direction_label}　{status_icon}",
            expanded=False,
        ):
            c1, c2, c3 = st.columns([2, 2, 3])
            c1.markdown(
                f'<span style="background:{badge_color}33;color:{badge_color};'
                f'border-radius:3px;padding:2px 6px;font-size:12px">'
                f'{ev.get("time_window",{}).get("name","")}</span>',
                unsafe_allow_html=True,
            )
            c2.markdown(f"類型：{ev.get('event_type_name','')}")
            c3.markdown(f"來源：{source_link}")

            if ev.get("mechanism"):
                st.caption(f"傳導機制：{ev['mechanism'][:200]}")

            if chains:
                st.markdown(f"**受影響供應鏈：** {chains_str}")

            watch_pts = ev.get("watch_points", [])
            if watch_pts:
                st.markdown("**觀察重點：**")
                for wp in watch_pts[:4]:
                    st.markdown(f"- {wp}")

    st.caption("⚠️ 事件日程來源：Federal Reserve、BLS、Apple Developer、台積電等官方網站。日期需以原始來源確認。")


def render_macro_bar(macro: Dict) -> None:
    """顯示 6 個宏觀指標橫向 metric 卡片"""
    if not macro:
        st.caption("ℹ️ 宏觀指標載入中…")
        return

    order = ["oil", "us10y", "us2y", "vix", "gold", "dxy"]
    cols  = st.columns(len(order))

    for col, key in zip(cols, order):
        item = macro.get(key, {})
        if not item:
            col.metric(key, "N/A")
            continue
        price    = item.get("price", 0)
        chg      = item.get("chg_pct", 0)
        label    = item.get("label", key)
        unit     = item.get("unit", "")
        sign     = "+" if chg and chg > 0 else ""
        delta    = f"{sign}{chg:.2f}%" if chg is not None else None
        val_str  = f"{price:.2f}" if price else "N/A"
        if unit:
            val_str = f"{val_str} {unit}"
        col.metric(label, val_str, delta=delta)
