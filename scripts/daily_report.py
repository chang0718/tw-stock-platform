# -*- coding: utf-8 -*-
"""
每日盤後分析報告 - LINE Notify 推送
由 GitHub Actions 自動執行（台灣時間 16:30 盤後）
"""

import os
import sys
import json
import requests
from datetime import date, datetime

# Windows console UTF-8 fix
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path

# 確保可以 import 上層模組
sys.path.insert(0, str(Path(__file__).parent.parent))


def send_line_notify(token: str, message: str) -> bool:
    try:
        resp = requests.post(
            "https://notify-api.line.me/api/notify",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": message},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"LINE Notify 失敗: {e}")
        return False


def load_model_snapshot() -> list:
    """讀取最新快照（若有）"""
    snapshot_file = Path("tw_quant_data/snapshots.json")
    if not snapshot_file.exists():
        return []
    try:
        data = json.loads(snapshot_file.read_text(encoding="utf-8"))
        if data:
            return data[-1].get("rows", [])
    except Exception:
        pass
    return []


def load_portfolio() -> dict:
    """讀取持倉"""
    pf_file = Path("tw_quant_data/portfolio.json")
    if not pf_file.exists():
        return {}
    try:
        return json.loads(pf_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def fetch_us_summary() -> str:
    """抓取美股重要指數簡報"""
    try:
        import yfinance as yf
        indices = {"^GSPC": "S&P500", "^IXIC": "那斯達克", "^SOX": "費城半導體", "^VIX": "VIX恐慌"}
        lines = []
        for sym, name in indices.items():
            t = yf.Ticker(sym)
            hist = t.history(period="2d")
            if len(hist) >= 2:
                prev, last = hist["Close"].iloc[-2], hist["Close"].iloc[-1]
                chg = (last - prev) / prev * 100
                arrow = "▲" if chg > 0 else "▼"
                lines.append(f"  {arrow} {name}: {last:,.1f} ({chg:+.2f}%)")
        return "\n".join(lines) if lines else "  無法取得"
    except Exception:
        return "  需安裝 yfinance"


def build_report() -> str:
    today = date.today().strftime("%Y/%m/%d")
    now   = datetime.now().strftime("%H:%M")
    rows  = load_model_snapshot()
    portfolio = load_portfolio()

    lines = [
        f"\n📈 台股盤後分析報告",
        f"📅 {today}  ⏰ {now}",
        "━━━━━━━━━━━━━━━━━━",
    ]

    # 美股概況
    lines.append("\n🌍 美股昨收概況")
    lines.append(fetch_us_summary())

    # TOP 5 推薦（從快照取）
    if rows:
        sorted_rows = sorted(rows, key=lambda r: r.get("prob20", 0), reverse=True)[:5]
        lines.append("\n⭐ 模型TOP5（1月漲機率）")
        for i, r in enumerate(sorted_rows, 1):
            prob = r.get("prob20", 0)
            name = r.get("name", r.get("ticker", ""))
            ticker = r.get("ticker", "")
            lines.append(f"  {i}. {ticker} {name}: {prob:.0f}%")
    else:
        lines.append("\n⭐ TOP5：無快照資料（請在平台保存快照）")

    # 持倉概況
    if portfolio:
        lines.append(f"\n💼 持倉 {len(portfolio)} 檔")
        for ticker, h in list(portfolio.items())[:5]:
            lines.append(f"  • {ticker} {h.get('name', '')} — 買入 ${h.get('buy_price', 0):.1f}")

    lines.append("\n━━━━━━━━━━━━━━━━━━")
    lines.append("🔍 詳細分析請開啟平台")
    lines.append("⚠️ 本報告僅供參考，非投資建議")

    return "\n".join(lines)


def main():
    token = os.environ.get("LINE_NOTIFY_TOKEN", "")
    if not token:
        print("⚠️ 未設定 LINE_NOTIFY_TOKEN，僅輸出報告內容")
        print(build_report())
        return

    report = build_report()
    print(report)
    ok = send_line_notify(token, report)
    print("✅ 已推送到 LINE" if ok else "❌ 推送失敗")


if __name__ == "__main__":
    main()
