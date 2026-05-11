# -*- coding: utf-8 -*-
"""
每日盤後分析報告 - Gmail 寄送
由 GitHub Actions 自動執行（台灣時間 14:30 盤後）
"""

import os
import sys
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date, datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))


def send_email(gmail_user: str, app_password: str, to_addr: str, subject: str, body: str) -> bool:
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = gmail_user
        msg["To"] = to_addr
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, app_password)
            server.sendmail(gmail_user, to_addr, msg.as_string())
        return True
    except Exception as e:
        print(f"Email 寄送失敗: {e}")
        return False


def load_model_snapshot() -> list:
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
    pf_file = Path("tw_quant_data/portfolio.json")
    if not pf_file.exists():
        return {}
    try:
        return json.loads(pf_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def fetch_us_summary() -> str:
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
        f"台股盤後分析報告",
        f"日期：{today}  時間：{now}",
        "=" * 30,
    ]

    lines.append("\n【美股昨收概況】")
    lines.append(fetch_us_summary())

    if rows:
        sorted_rows = sorted(rows, key=lambda r: r.get("prob20", 0), reverse=True)[:5]
        lines.append("\n【模型 TOP5（1月漲機率）】")
        for i, r in enumerate(sorted_rows, 1):
            prob = r.get("prob20", 0)
            name = r.get("name", r.get("ticker", ""))
            ticker = r.get("ticker", "")
            lines.append(f"  {i}. {ticker} {name}: {prob:.0f}%")
    else:
        lines.append("\n【TOP5】：無快照資料（請在平台保存快照）")

    if portfolio:
        lines.append(f"\n【持倉 {len(portfolio)} 檔】")
        for ticker, h in list(portfolio.items())[:5]:
            lines.append(f"  • {ticker} {h.get('name', '')} — 買入 ${h.get('buy_price', 0):.1f}")

    lines.append("\n" + "=" * 30)
    lines.append("詳細分析請開啟平台")
    lines.append("本報告僅供參考，非投資建議")

    return "\n".join(lines)


def main():
    gmail_user   = os.environ.get("GMAIL_USER", "")
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    to_addr      = os.environ.get("REPORT_TO", gmail_user)

    report  = build_report()
    subject = f"台股盤後報告 {date.today().strftime('%Y/%m/%d')}"

    print(report)

    if not gmail_user or not app_password:
        print("\n⚠️ 未設定 GMAIL_USER / GMAIL_APP_PASSWORD，僅輸出報告，不寄送")
        return

    ok = send_email(gmail_user, app_password, to_addr, subject, report)
    print("✅ 報告已寄出" if ok else "❌ 寄送失敗")


if __name__ == "__main__":
    main()
