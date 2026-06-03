"""
Tab 3 重構腳本：把單一巨大頁面拆成 4 個子 Tab。

執行：python scripts/refactor_tab3.py
"""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app.py"

src = APP.read_text(encoding="utf-8")
lines = src.splitlines(keepends=True)

# ── 找各區塊起始行（0-indexed）────────────────────────────────────
def find_line(keyword, after=0):
    for i, l in enumerate(lines):
        if i < after:
            continue
        if keyword in l:
            return i
    return -1

# 定位 Tab 3 內各區段（全部 12-space indent）
L_STATUS_END   = find_line('st.caption("資料狀態：')       # 1567 (0-idx)
L_FUND_START   = find_line('# ── 基本面 ──', L_STATUS_END) # 1568
L_FLOW_START   = find_line('# ── 籌碼 ──', L_FUND_START)   # 1776
L_TECH_START   = find_line('# ── 技術分析 ──', L_FLOW_START) # 1781
L_NEWS_START   = find_line('# ── 新聞情緒 ──', L_TECH_START) # 1893
L_NOTES_START  = find_line('# ── 個人筆記 ──', L_NEWS_START) # 1909
L_SIG_START    = find_line('# ── 買入/賣出訊號 ──', L_NOTES_START) # 1921
L_SUM_START    = find_line('# ── 即時信號彙整 ──', L_SIG_START)    # 1939
L_TAB4_START   = find_line('# ========== Tab 4:', L_SUM_START)     # 2011

print(f"L_STATUS_END={L_STATUS_END+1}, L_FUND_START={L_FUND_START+1}")
print(f"L_FLOW_START={L_FLOW_START+1}, L_TECH_START={L_TECH_START+1}")
print(f"L_NEWS_START={L_NEWS_START+1}, L_NOTES_START={L_NOTES_START+1}")
print(f"L_SIG_START={L_SIG_START+1}, L_SUM_START={L_SUM_START+1}")
print(f"L_TAB4_START={L_TAB4_START+1}")

assert all(x > 0 for x in [L_STATUS_END, L_FUND_START, L_FLOW_START,
                             L_TECH_START, L_NEWS_START, L_NOTES_START,
                             L_SIG_START, L_SUM_START, L_TAB4_START]), \
       "找不到某個關鍵行，請檢查 app.py"

# ── 提取各區塊文字 ─────────────────────────────────────────────────
def get_block(start, end):
    return "".join(lines[start:end])

# 原本 12 spaces indent，需加到 16 spaces（多4格）
def reindent(text, extra=4):
    result = []
    for l in text.splitlines(keepends=True):
        if l.strip() == "":        # 空行不加 indent
            result.append(l)
        else:
            result.append(" " * extra + l)
    return "".join(result)

# 各區塊（0-indexed slice）
blk_fund   = get_block(L_FUND_START,  L_FLOW_START)   # 基本面+月季趨勢+YTP+EPS
blk_flow   = get_block(L_FLOW_START,  L_TECH_START)   # 籌碼
blk_tech   = get_block(L_TECH_START,  L_NEWS_START)   # 技術面+操作區間
blk_news   = get_block(L_NEWS_START,  L_NOTES_START)  # 新聞
blk_notes  = get_block(L_NOTES_START, L_SIG_START)    # 筆記
blk_sig    = get_block(L_SIG_START,   L_SUM_START)    # 訊號
blk_sum    = get_block(L_SUM_START,   L_TAB4_START)   # 即時彙整

# ── 建立新的 Tab 3 內容 ───────────────────────────────────────────
INDENT = "            "  # 12 spaces（status_end 後的 indent）

new_tab3 = (
    f"{INDENT}# ── 子分頁（基本面 / 技術面 / 籌碼 / 新聞操作）──\n"
    f"{INDENT}epsfv   = {{}}\n"
    f"{INDENT}val_pct = {{}}\n"
    f"{INDENT}_stabs = st.tabs([\"📊 基本面\", \"📈 技術面\", \"🏦 籌碼\", \"💬 新聞/操作\"])\n"
    f"\n"
    f"{INDENT}with _stabs[0]:  # ── 基本面（fund + 月季趨勢 + YTP + EPS 公平價）\n"
    + reindent(blk_fund)
    + f"\n"
    f"{INDENT}with _stabs[1]:  # ── 技術面（K線 + 操作區間 + 訊號）\n"
    + reindent(blk_tech)
    + reindent(blk_sig)
    + f"\n"
    f"{INDENT}with _stabs[2]:  # ── 籌碼（三大法人 + 融資融券）\n"
    + reindent(blk_flow)
    + f"\n"
    f"{INDENT}with _stabs[3]:  # ── 新聞/筆記/信號彙整\n"
    + reindent(blk_news)
    + reindent(blk_notes)
    + reindent(blk_sum)
    + "\n"
)

# ── 找到 epsfv/val_pct 原始初始化（L1572），需移除重複 ──────────────
# 在 blk_fund 內有 "epsfv   = {}   # 初始化" 和 "val_pct = {}   # 同上"
# 移除它們（因為我們在 sub_tabs 外面已初始化）
new_tab3 = new_tab3.replace(
    "                epsfv   = {}   # 初始化，稍後在財報區塊內填充\n",
    ""
).replace(
    "                val_pct = {}   # 同上\n",
    ""
)

# ── 組合最終文字 ──────────────────────────────────────────────────
before = "".join(lines[:L_STATUS_END + 1]) + "\n"
after  = "".join(lines[L_TAB4_START:])

new_src = before + new_tab3 + after

APP.write_text(new_src, encoding="utf-8")
print("[OK] Tab 3 重構完成")
print(f"     原始行數: {len(lines)}，新行數: {len(new_src.splitlines())}")
