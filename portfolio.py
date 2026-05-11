"""
持倉管理模組
儲存個人持股資訊，計算損益，提供策略建議
"""

import json
import time
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional


_PORTFOLIO_FILE = Path("tw_quant_data/portfolio.json")


class Portfolio:

    def __init__(self):
        self._holdings: Dict[str, Dict] = {}
        self.load()

    def load(self):
        try:
            if _PORTFOLIO_FILE.exists():
                data = json.loads(_PORTFOLIO_FILE.read_text(encoding="utf-8"))
                self._holdings = data if isinstance(data, dict) else {}
        except Exception:
            self._holdings = {}

    def save(self):
        try:
            _PORTFOLIO_FILE.parent.mkdir(parents=True, exist_ok=True)
            _PORTFOLIO_FILE.write_text(
                json.dumps(self._holdings, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:
            pass

    def add_holding(
        self,
        ticker: str,
        name: str,
        shares: float,
        buy_price: float,
        buy_date: str = None,
    ):
        """新增或更新持倉"""
        self._holdings[ticker] = {
            "ticker":    ticker,
            "name":      name,
            "shares":    float(shares),
            "buy_price": float(buy_price),
            "buy_date":  buy_date or date.today().isoformat(),
            "added_at":  datetime.now().isoformat(),
        }
        self.save()

    def remove_holding(self, ticker: str):
        self._holdings.pop(ticker, None)
        self.save()

    def get_holdings(self) -> List[Dict]:
        return list(self._holdings.values())

    def calculate_pnl(self, current_prices: Dict[str, float]) -> List[Dict]:
        """
        計算每筆持倉損益
        current_prices: {ticker: close_price}
        """
        result = []
        for ticker, h in self._holdings.items():
            cp = current_prices.get(ticker)
            bp = h["buy_price"]
            shares = h["shares"]
            cost = bp * shares
            if cp is not None and cp > 0:
                current_val = cp * shares
                pnl_abs = round(current_val - cost, 2)
                pnl_pct = round((cp - bp) / bp * 100, 2) if bp > 0 else 0
            else:
                current_val = None
                pnl_abs = None
                pnl_pct = None

            # 持有天數
            try:
                bd = datetime.strptime(h["buy_date"], "%Y-%m-%d").date()
                hold_days = (date.today() - bd).days
            except Exception:
                hold_days = 0

            result.append({
                **h,
                "current_price": cp,
                "current_value": current_val,
                "cost":          round(cost, 2),
                "pnl_abs":       pnl_abs,
                "pnl_pct":       pnl_pct,
                "hold_days":     hold_days,
            })
        return result

    def get_strategy_suggestion(self, pnl_entry: Dict, stock_data: Dict = None) -> str:
        """
        根據持倉狀況給出策略建議
        pnl_entry: 來自 calculate_pnl() 的單筆結果
        stock_data: 模型計算結果（可選）
        """
        pnl_pct   = pnl_entry.get("pnl_pct")
        hold_days = pnl_entry.get("hold_days", 0)
        prob20    = stock_data.get("prob20", 50) if stock_data else 50
        risk      = stock_data.get("risk_score", 50) if stock_data else 50

        if pnl_pct is None:
            return "⚠️ 無法取得現價，請更新報價"

        if pnl_pct >= 25 and hold_days >= 30:
            return "🟢 已達短期目標，考慮分批獲利了結（建議先賣 1/3）"
        elif pnl_pct >= 15:
            return "🟢 獲利良好，可設定移動止盈（現價下方 8%）"
        elif pnl_pct >= 5:
            if prob20 >= 60:
                return "🟡 小幅獲利，模型仍看多，可繼續持有"
            else:
                return "🟡 小幅獲利，模型訊號中性，觀察量能再定奪"
        elif pnl_pct >= -5:
            return "🟡 損益持平，繼續觀察，無需急於操作"
        elif pnl_pct >= -10:
            if risk > 70:
                return "🔴 高風險股虧損 -10%，建議設定停損（現成本下方 -5%）"
            else:
                return "🟡 小幅虧損，若基本面無惡化，可考慮加碼攤平"
        elif pnl_pct >= -20:
            return f"🔴 虧損 {pnl_pct:.1f}%，建議重新評估投資邏輯，考慮停損"
        else:
            return f"🔴 虧損超過 20%（{pnl_pct:.1f}%），強烈建議停損，保存資金"

    def total_pnl_summary(self, pnl_list: List[Dict]) -> Dict:
        """彙總損益統計"""
        total_cost    = sum(p["cost"] for p in pnl_list)
        total_val     = sum(p["current_value"] for p in pnl_list if p["current_value"] is not None)
        total_pnl_abs = sum(p["pnl_abs"] for p in pnl_list if p["pnl_abs"] is not None)
        winners  = [p for p in pnl_list if p.get("pnl_pct") is not None and p["pnl_pct"] > 0]
        losers   = [p for p in pnl_list if p.get("pnl_pct") is not None and p["pnl_pct"] < 0]
        return {
            "total_cost":     round(total_cost, 2),
            "total_value":    round(total_val, 2),
            "total_pnl_abs":  round(total_pnl_abs, 2),
            "total_pnl_pct":  round(total_pnl_abs / total_cost * 100, 2) if total_cost > 0 else 0,
            "winner_count":   len(winners),
            "loser_count":    len(losers),
            "holding_count":  len(pnl_list),
        }
