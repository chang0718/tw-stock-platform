"""
merge_tabs.py: 安全版
- 移除 Tab 2（候選清單） → 已移到 Tab 0 expander（在 refactor_tab3.py 之前手動加入）
- 移除 Tab 11（基本面彙整） → 加到 Tab 5（追蹤清單）expander
- 用單一 regex pass 正確重命名索引（避免連鎖替換問題）
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app.py"
src = APP.read_text(encoding="utf-8")

# ── 先加入候選清單到 Tab 0 末尾（expander）─────────────────────────
# 找 Tab 0 最後的 download_button 行
tab0_end_marker = '            st.download_button("📥 下載推薦清單 CSV", csv_data,\n'
tab0_anchor = (
    '                               file_name=f"top10_{date.today()}.csv", mime="text/csv")\n'
    '\n'
    '    # ========== Tab 1: 美股連動 =========='
)
assert tab0_anchor in src, "找不到 Tab 0 / Tab 1 邊界"

candidate_expander = '''
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

    # ========== Tab 1: 美股連動 =========='''

src = src.replace(
    '    # ========== Tab 1: 美股連動 ==========',
    candidate_expander,
    1
)
print("[OK] 候選清單 expander 加入 Tab 0")

# ── 提取 Tab 11 的 body（不含 with tabs[11]: 行）──────────────────
tab11_with = '    with tabs[11]:\n'
tab11_pos = src.find(tab11_with)
assert tab11_pos > 0, "找不到 with tabs[11]:"

entry_marker = '\n# ============================================================\n# 進入點'
entry_pos = src.find(entry_marker, tab11_pos)
assert entry_pos > 0

# 取 Tab 11 的 body（去掉第一行 with tabs[11]:）
tab11_body_raw = src[tab11_pos + len(tab11_with):entry_pos]

# 把 8sp 縮排加 4sp → 12sp
def add_indent(text, spaces=4):
    lines = text.split("\n")
    out = []
    for l in lines:
        if l.strip():
            out.append(" " * spaces + l)
        else:
            out.append(l)
    return "\n".join(out)

tab11_body_indented = add_indent(tab11_body_raw, 4)

# ── 加入 Tab 5（追蹤清單）末尾 ────────────────────────────────────
tab6_marker = '    # ========== Tab 6: 熱度排行 =========='
tab6_pos = src.find(tab6_marker)
assert tab6_pos > 0, "找不到 Tab 6 標記"

fund_summary_block = f'''
        # ── 基本面彙整（自選股跨公司比較）──
        with st.expander("📊 基本面彙整 — 自選股跨公司比較（展開）", expanded=False):
{tab11_body_indented}

    {tab6_marker.strip()}'''

src = src[:tab6_pos] + fund_summary_block + src[tab6_pos + len(tab6_marker):]
print("[OK] 基本面彙整 expander 加入 Tab 5")

# ── 移除 with tabs[2]: 候選清單區塊 ─────────────────────────────────
tab2_with = '    with tabs[2]:\n        st.subheader("📋 候選清單")'
tab2_pos = src.find(tab2_with)
assert tab2_pos > 0, "找不到 Tab 2 (候選清單)"
tab3_marker = '\n    # ========== Tab 3: 個股分析'
tab3_pos = src.find(tab3_marker, tab2_pos)
assert tab3_pos > 0
src = src[:tab2_pos] + src[tab3_pos:]
print("[OK] 已移除 Tab 2 區塊")

# ── 移除 with tabs[11]: 基本面彙整區塊 ───────────────────────────────
tab11_with2 = '\n    # ========== Tab 11: 基本面彙整'
tab11_pos2 = src.find(tab11_with2)
assert tab11_pos2 > 0
entry_pos2 = src.find(entry_marker, tab11_pos2)
assert entry_pos2 > 0
src = src[:tab11_pos2] + src[entry_pos2:]
print("[OK] 已移除 Tab 11 原始區塊")

# ── 更新 tabs = st.tabs([...]) 宣告 ─────────────────────────────────
old_tabs = ('    tabs = st.tabs([\n'
            '        "🏆 整體分析",\n'
            '        "🌍 美股連動",\n'
            '        "📋 候選清單",\n'
            '        "🔍 個股分析",\n'
            '        "💼 持倉管理",\n'
            '        "⭐ 追蹤清單",\n'
            '        "🔥 熱度排行",\n'
            '        "📊 產業瀏覽器",\n'
            '        "⚙️ 模型設定",\n'
            '        "🎯 潛力股",\n'
            '        "📈 ETF 排行",\n'
            '        "📊 基本面彙整",\n'
            '    ])')
new_tabs = ('    tabs = st.tabs([\n'
            '        "🏆 整體分析",\n'
            '        "🌍 美股連動",\n'
            '        "🔍 個股分析",\n'
            '        "💼 持倉管理",\n'
            '        "⭐ 追蹤清單",\n'
            '        "🔥 熱度排行",\n'
            '        "📊 產業瀏覽器",\n'
            '        "⚙️ 模型設定",\n'
            '        "🎯 潛力股",\n'
            '        "📈 ETF 排行",\n'
            '    ])')
assert old_tabs in src, "找不到 tabs 宣告"
src = src.replace(old_tabs, new_tabs, 1)
print("[OK] tabs 宣告已更新")

# ── 用單一 regex pass 重命名 tabs[N] 索引（N=3..10 → N-1=2..9）───────
# 只替換 `    with tabs[N]:` 格式（4 spaces + with tabs[N]:），且 N 在 3~10
def renumber_tabs(text):
    def repl(m):
        n = int(m.group(1))
        if 3 <= n <= 10:
            return f'    with tabs[{n - 1}]:'
        return m.group(0)
    # 只匹配行首4個空格 + "with tabs[N]:" 的精確格式
    return re.sub(r'^    with tabs\[(\d+)\]:', repl, text, flags=re.MULTILINE)

src = renumber_tabs(src)
print("[OK] tabs 索引已重命名（單一 pass）")

APP.write_text(src, encoding="utf-8")
print(f"[OK] 完成，Tab 數量 12 → 10")
