"""
update_architecture.py
自動更新 architecture.html 中的動態區段。

執行方式：
    python scripts/update_architecture.py          # 正常更新
    python scripts/update_architecture.py --init   # 強制重建（若佔位符被意外刪除）

整合：
    - pack.ps1：打包前自動執行
    - .git/hooks/pre-commit：git commit 前自動執行並 git add architecture.html
"""

import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HTML_FILE = ROOT / "architecture.html"
APP_FILE  = ROOT / "app.py"

# ── 從 config.py 匯入分類資料 ────────────────────────────────────────────


def _load_config():
    try:
        from config import SUPPLY_CHAIN_TREE, CONCEPT_STOCKS
        return SUPPLY_CHAIN_TREE, CONCEPT_STOCKS
    except ImportError as e:
        print(f"⚠️  無法匯入 config.py：{e}")
        return {}, {}


# ── 解析 app.py 取得 Tab 名稱 ────────────────────────────────────────────


def _parse_tabs(app_text: str) -> list:
    m = re.search(r'tabs\s*=\s*st\.tabs\(\s*\[(.*?)\]\s*\)', app_text, re.DOTALL)
    if not m:
        return []
    raw = m.group(1)
    # 提取雙引號或單引號字串
    return re.findall(r'["\']([^"\']+)["\']', raw)


# ── 各區段 HTML 生成器 ────────────────────────────────────────────────────

_TAB_DESC = {
    "🏆 整體分析":   "六因子量化 Top 10 推薦；市場概況（漲跌家數）；本週熱點話題；快速加入追蹤",
    "🌍 美股連動":   "美股大盤指數（S&P500/Nasdaq/Dow）；台積電ADR；科技股與供應鏈連動分析",
    "📋 候選清單":   "完整量化候選清單；多欄籌碼/技術/基本面信號；CSV 下載",
    "🔍 個股分析":   "個股完整分析：行情/估值/技術圖/月營收趨勢/季報EPS表/PE歷史分位數/新聞情緒",
    "💼 持倉管理":   "持倉新增/刪除；總損益統計；各股損益率、持有天數、策略建議",
    "⭐ 追蹤清單":   "自選股追蹤；基本面+新聞自動載入；20日機率/期望報酬/信心度指標",
    "🔥 熱度排行":   "產業熱度 Top 20 橫條圖；熱度分解（籌碼/技術/新聞/漲跌分）；成分股儀表板",
    "📊 產業瀏覽器": "概念股/供應鏈 pills 切換導覽；卡片行股票清單（漲紅跌綠）；摘要指標；產業新聞",
    "⚙️ 模型設定":   "六因子權重調整（動能/成長/品質/價值/籌碼/低波動）；分數預覽；存檔",
    "🎯 潛力股":     "落後補漲候選排行；peer_lag_score × 族群平均動能差；外資剛建倉訊號",
    "📈 ETF 排行":   "台灣 ETF 月/季/年報酬率排行；ETF 詳情（前十大成分股）",
    "📊 基本面彙整": "自選股跨公司比較：月營收 YoY% 矩陣（正綠負紅）、近8季 EPS 矩陣、最新指標快照",
}


def build_tabs_html(tab_names: list) -> str:
    parts = ['<div class="tab-grid">']
    for i, name in enumerate(tab_names):
        desc = _TAB_DESC.get(name, f"功能詳見 app.py with tabs[{i}]")
        parts.append(
            f'    <div class="tab-card">'
            f'<div class="tc-num">Tab {i}</div>'
            f'<div class="tc-name">{name}</div>'
            f'<div class="tc-desc">{desc}</div>'
            f'</div>'
        )
    parts.append('</div>')
    return "\n".join(parts)


def build_supply_chain_html(tree: dict) -> str:
    parts = []
    for major, subs in tree.items():
        li_items = "".join(f"<li>{s}</li>" for s in subs)
        parts.append(
            f'<details>\n'
            f'  <summary>{major}</summary>\n'
            f'  <ul class="sub-list">{li_items}</ul>\n'
            f'</details>'
        )
    return "\n".join(parts)


def build_concept_html(concepts: dict) -> str:
    parts = []
    for name, tickers in concepts.items():
        count = len(tickers)
        parts.append(
            f'<div class="concept-item">'
            f'<span>{name}</span>'
            f'<span class="concept-count">{count} 檔</span>'
            f'</div>'
        )
    return "\n".join(parts)


def build_generated_at_html() -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f'最後更新：{now}'


# ── HTML 佔位符替換 ───────────────────────────────────────────────────────


def replace_placeholder(html: str, key: str, new_content: str) -> str:
    pattern = rf'<!-- AUTO:{key} -->.*?<!-- /AUTO:{key} -->'
    replacement = f'<!-- AUTO:{key} -->\n{new_content}\n<!-- /AUTO:{key} -->'
    result, n = re.subn(pattern, replacement, html, flags=re.DOTALL)
    if n == 0:
        print(f"  [WARN] placeholder AUTO:{key} not found, skipped")
    return result


# ── 主流程 ────────────────────────────────────────────────────────────────


def main():
    print("[update_architecture] start...")

    if not HTML_FILE.exists():
        print(f"  [ERROR] not found: {HTML_FILE}")
        sys.exit(1)

    html = HTML_FILE.read_text(encoding="utf-8")

    if not APP_FILE.exists():
        print(f"  [ERROR] not found: {APP_FILE}")
        sys.exit(1)
    app_text = APP_FILE.read_text(encoding="utf-8")

    tree, concepts = _load_config()
    tab_names = _parse_tabs(app_text)

    print(f"  tabs detected: {len(tab_names)}")
    print(f"  supply chain major: {len(tree)}")
    print(f"  concept themes: {len(concepts)}")

    if tab_names:
        html = replace_placeholder(html, "TABS", build_tabs_html(tab_names))
    if tree:
        html = replace_placeholder(html, "SUPPLY_CHAIN", build_supply_chain_html(tree))
    if concepts:
        html = replace_placeholder(html, "CONCEPTS", build_concept_html(concepts))
    html = replace_placeholder(html, "GENERATED_AT", build_generated_at_html())

    HTML_FILE.write_text(html, encoding="utf-8")
    print(f"  [OK] updated {HTML_FILE.name}")
    print(f"       tabs={len(tab_names)}, major={len(tree)}, sub={sum(len(v) for v in tree.values())}, concepts={len(concepts)}")


if __name__ == "__main__":
    main()
