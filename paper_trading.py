# -*- coding: utf-8 -*-
"""
紙上交易引擎（Paper Trading）

核心思考邏輯：
每日盤後用「與 App 完全相同」的綜合分數（QuantModel.compute_final_composite）挑出最佳
N 檔；維持固定 N 檔持倉、每日輪動 —— 掉出榜外或踩到利空/風險 guard 才換股。每日記錄
投資組合淨值（NAV）並與大盤基準（0050）比較，長期累積出一條可驗證的權益曲線與學術級
評估指標（累積/年化報酬、Sharpe、最大回撤、勝率、Alpha、Information Coefficient），
用以檢驗模型「到底有沒有選股能力」，作為後續模型迭代的依據。

合規（依 CLAUDE.md 回測規範）：
- 計入交易成本（手續費）、稅費（證交稅）、滑價，避免高估績效
- 不使用未來資料（每日僅用當日盤後分數決策，下一交易日才結算）
- 績效一律附「歷史回測不代表未來報酬」免責
- 本模組為研究/風險評估用途，不構成個人化投資建議
"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from utils import read_json, write_json

# 帳本存於「tracked」路徑（data/ 已入庫），才能由 GitHub Actions 每日回存 repo、長期累積。
# 不可放 tw_quant_data/（被 .gitignore，且雲端 ephemeral）。
LEDGER_DIR = Path(__file__).parent / "data" / "paper_trading"
LEDGER_FILE = LEDGER_DIR / "ledger.json"

DEFAULT_CONFIG = {
    "initial_budget": 1_000_000,  # 總資金上限（NT$）；先驗證精準度，日後再放寬
    "max_positions": 5,           # 固定持倉檔數（不論換股，維持 N 檔）
    "fee_bps": 14.25,             # 手續費 0.1425%（買賣皆收）
    "tax_bps": 30.0,              # 證交稅 0.3%（僅賣出）
    "slippage_bps": 10.0,         # 滑價假設 0.1%（買賣皆計）
    "risk_guard": 80.0,           # risk_score 超過即視為利空 → 賣出
    "news_guard": -0.5,           # 新聞情緒分數（-1~1）低於即視為利空 → 賣出
    # ── 選股池合格門檻（四層過濾，避免抓到零量微型股）──────────────────
    # 各層皆「有欄位才套用」；設 0 / False / [] 即關閉該層過濾。
    "min_volume_lots": 500,       # 流動性門檻（張/日）；0 = 不過濾（資料無量時不誤殺）
    "min_market_cap": 1e10,       # 市值門檻（NT$，1e10 = 100 億）；0 = 不過濾（無 market_cap 欄時自動略過）
    "require_real_fund": True,    # 是否要求有真實基本面（has_real_fund==True）；False = 允許純技術面股票
    "candidate_levels": ["核心候選", "觀察候選"],  # 只買這些候選等級；空 [] = 不依候選等級過濾
}


class PaperTradingEngine:
    """維持固定 N 檔、每日輪動的紙上交易引擎。狀態以單一 ledger dict 表示，可序列化。"""

    def __init__(self, ledger: Optional[Dict] = None, config: Optional[Dict] = None):
        self.ledger = ledger or self._empty_ledger(config)
        # 確保 config 欄位齊全（向後相容舊帳本）
        cfg = dict(DEFAULT_CONFIG)
        cfg.update(self.ledger.get("config") or {})
        if config:
            cfg.update(config)
        self.ledger["config"] = cfg
        self.ledger.setdefault("cash", cfg["initial_budget"])
        self.ledger.setdefault("positions", {})
        self.ledger.setdefault("trades", [])
        self.ledger.setdefault("daily_nav", [])
        self.ledger.setdefault("benchmark_base", None)

    # ── 持久化 ────────────────────────────────────────────────────────────
    @staticmethod
    def _empty_ledger(config: Optional[Dict] = None) -> Dict:
        cfg = dict(DEFAULT_CONFIG)
        if config:
            cfg.update(config)
        return {
            "config": cfg,
            "cash": cfg["initial_budget"],
            "positions": {},
            "trades": [],
            "daily_nav": [],
            "benchmark_base": None,
        }

    @classmethod
    def load(cls, path: Path = LEDGER_FILE) -> "PaperTradingEngine":
        data = read_json(Path(path), None)
        return cls(ledger=data) if isinstance(data, dict) else cls()

    def save(self, path: Path = LEDGER_FILE) -> bool:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return write_json(Path(path), self.ledger)

    # ── 成本 ──────────────────────────────────────────────────────────────
    @property
    def cfg(self) -> Dict:
        return self.ledger["config"]

    def _buy_rate(self) -> float:
        return (self.cfg["fee_bps"] + self.cfg["slippage_bps"]) / 10000.0

    def _sell_rate(self) -> float:
        return (self.cfg["fee_bps"] + self.cfg["tax_bps"] + self.cfg["slippage_bps"]) / 10000.0

    # ── 估值 ──────────────────────────────────────────────────────────────
    def positions_value(self, prices: Dict[str, float]) -> float:
        total = 0.0
        for t, pos in self.ledger["positions"].items():
            px = prices.get(t)
            if px is None:
                px = pos.get("last_price", pos.get("cost_basis", 0.0))
            total += pos["shares"] * px
        return total

    # ── 每日主流程 ─────────────────────────────────────────────────────────
    def run_day(
        self,
        model_df: pd.DataFrame,
        date: Optional[str] = None,
        benchmark_close: Optional[float] = None,
        force: bool = False,
    ) -> Dict:
        """
        以當日盤後 model_df（須含 final_composite/close/risk_score/sentiment_score）執行一日。
        回傳當日 daily_nav 記錄。同日重複執行預設為 no-op（避免重複下單），force=True 可覆寫。
        """
        date = date or datetime.now().strftime("%Y-%m-%d")
        navs = self.ledger["daily_nav"]
        if navs and navs[-1].get("date") == date and not force:
            return navs[-1]

        cfg = self.cfg
        n = int(cfg["max_positions"])

        # 價格與屬性查表
        df = model_df.copy()
        if "final_composite" not in df.columns:
            raise ValueError("model_df 缺少 final_composite 欄位；請先呼叫 compute_final_composite")
        prices, risk, senti, names = {}, {}, {}, {}
        for _, r in df.iterrows():
            t = str(r["ticker"])
            prices[t] = float(r.get("close") or 0.0)
            risk[t] = float(r.get("risk_score") or 0.0)
            sv = r.get("sentiment_score")
            senti[t] = None if sv is None or (isinstance(sv, float) and math.isnan(sv)) else float(sv)
            names[t] = str(r.get("name") or t)

        # ── 合格池：分層過濾（liquidity → 市值 → 真實基本面 → 候選等級）──────
        # 每層皆「有欄位才套用」，minimal dataframe 不會 crash。
        # 過濾後若不足 N 檔 → 逆序逐層放寬（先放候選等級，再基本面、市值、量能），
        # 直到湊滿 N 檔或所有層皆放寬，避免「無合格標的」；並記錄放寬原因。
        base = df[df["close"].astype(float) > 0].copy()

        def _apply_layers(active: set) -> pd.DataFrame:
            """依 active 集合套用各過濾層，回傳過濾後的合格池。"""
            e = base
            if "volume" in active and cfg.get("min_volume_lots", 0) and "volume" in e.columns:
                e = e[pd.to_numeric(e["volume"], errors="coerce").fillna(0) >= cfg["min_volume_lots"]]
            if "market_cap" in active and cfg.get("min_market_cap", 0) and "market_cap" in e.columns:
                e = e[pd.to_numeric(e["market_cap"], errors="coerce").fillna(0) >= cfg["min_market_cap"]]
            if "has_real_fund" in active and cfg.get("require_real_fund") and "has_real_fund" in e.columns:
                e = e[e["has_real_fund"] == True]  # noqa: E712（保留欄位語意，允許 NaN 被濾除）
            if "candidate_level" in active and cfg.get("candidate_levels") and "candidate_level" in e.columns:
                e = e[e["candidate_level"].isin(cfg["candidate_levels"])]
            return e

        # 放寬順序（逆序：最後套用的最先被放寬）
        relax_order = ["candidate_level", "has_real_fund", "market_cap", "volume"]
        active_layers = set(relax_order)
        relaxed: List[str] = []  # 記錄本日實際放寬的層（供稽核/log）

        elig = _apply_layers(active_layers)
        while len(elig) < n and relax_order:
            dropped = relax_order.pop(0)
            active_layers.discard(dropped)
            relaxed.append(dropped)
            elig = _apply_layers(active_layers)

        elig = elig.copy().sort_values("final_composite", ascending=False)
        target = [str(t) for t in elig["ticker"].head(n).tolist()]
        target_set = set(target)

        if relaxed:
            print(f"[PAPER] {date} 合格池不足 {n} 檔，放寬過濾層：{relaxed}（剩 {len(elig)} 檔候選）")

        trades: List[Dict] = []

        # ── 1) 賣出：掉出榜外，或觸發利空/風險 guard ──────────────────────────
        for t in list(self.ledger["positions"].keys()):
            pos = self.ledger["positions"][t]
            px = prices.get(t, pos.get("last_price", pos.get("cost_basis", 0.0)))
            reason = None
            if risk.get(t, 0.0) > cfg["risk_guard"]:
                reason = f"風險過高(利空) risk={risk.get(t):.0f}"
            elif senti.get(t) is not None and senti[t] < cfg["news_guard"]:
                reason = f"負面新聞(利空) senti={senti[t]:.2f}"
            elif t not in target_set:
                reason = "掉出前 N 名"
            if reason and px > 0:
                exec_px = px * (1 - self._sell_rate())
                proceeds = pos["shares"] * exec_px
                self.ledger["cash"] += proceeds
                ret_pct = (exec_px / pos["cost_basis"] - 1) * 100 if pos.get("cost_basis") else 0.0
                trades.append({
                    "date": date, "ticker": t, "name": pos.get("name", names.get(t, t)),
                    "action": "SELL", "price": round(px, 2), "shares": pos["shares"],
                    "amount": round(proceeds, 0), "reason": reason,
                    "entry_score": pos.get("entry_score"), "ret_pct": round(ret_pct, 2),
                })
                del self.ledger["positions"][t]

        # ── 2) 買進：補滿至 N 檔（等權分配可用現金）──────────────────────────
        held = set(self.ledger["positions"].keys())
        # 候選 = 目標池中尚未持有、且未觸發 guard 者
        buy_candidates = [
            t for t in target
            if t not in held
            and risk.get(t, 0.0) <= cfg["risk_guard"]
            and not (senti.get(t) is not None and senti[t] < cfg["news_guard"])
            and prices.get(t, 0.0) > 0
        ]
        slots = max(0, n - len(held))
        buy_candidates = buy_candidates[:slots]
        if buy_candidates:
            alloc = self.ledger["cash"] / len(buy_candidates)
            for t in buy_candidates:
                px = prices[t]
                exec_px = px * (1 + self._buy_rate())
                shares = int(alloc // exec_px)  # 允許零股（台股盤後零股可成交）
                if shares <= 0:
                    continue
                cost = shares * exec_px
                self.ledger["cash"] -= cost
                score_row = elig[elig["ticker"].astype(str) == t]
                entry_score = float(score_row["final_composite"].iloc[0]) if not score_row.empty else None
                self.ledger["positions"][t] = {
                    "name": names.get(t, t), "shares": shares,
                    "cost_basis": round(exec_px, 4), "buy_date": date,
                    "entry_score": entry_score, "last_price": px,
                }
                trades.append({
                    "date": date, "ticker": t, "name": names.get(t, t),
                    "action": "BUY", "price": round(px, 2), "shares": shares,
                    "amount": round(cost, 0), "reason": f"進入前 {n} 名 score={entry_score:.1f}" if entry_score else "進入前 N 名",
                    "entry_score": entry_score, "ret_pct": None,
                })

        # ── 3) 結算當日 NAV（以收盤價 mark-to-market）────────────────────────
        for t, pos in self.ledger["positions"].items():
            if prices.get(t):
                pos["last_price"] = prices[t]
        pos_value = self.positions_value(prices)
        nav = self.ledger["cash"] + pos_value
        init = cfg["initial_budget"]
        cum_return_pct = (nav / init - 1) * 100 if init else 0.0

        # 基準（0050）累積報酬
        bench_return_pct = None
        if benchmark_close is not None and benchmark_close > 0:
            if not self.ledger.get("benchmark_base"):
                self.ledger["benchmark_base"] = benchmark_close
            base = self.ledger["benchmark_base"]
            bench_return_pct = (benchmark_close / base - 1) * 100 if base else 0.0

        rec = {
            "date": date, "nav": round(nav, 0), "cash": round(self.ledger["cash"], 0),
            "pos_value": round(pos_value, 0), "n_pos": len(self.ledger["positions"]),
            "benchmark_close": benchmark_close,
            "cum_return_pct": round(cum_return_pct, 2),
            "bench_return_pct": round(bench_return_pct, 2) if bench_return_pct is not None else None,
            "relaxed": relaxed,  # 本日被放寬的過濾層（空 = 四層皆滿足；供稽核選股池品質）
        }
        # 同日覆寫（force 情境）
        self.ledger["daily_nav"] = [d for d in navs if d.get("date") != date] + [rec]
        self.ledger["daily_nav"].sort(key=lambda d: d["date"])
        self.ledger["trades"].extend(trades)
        return rec

    # ── 評估指標（學術級）──────────────────────────────────────────────────
    def equity_metrics(self, risk_free_annual: float = 0.015, trading_days: int = 252) -> Dict:
        """
        產出權益曲線指標：累積/年化報酬、Sharpe、最大回撤、Alpha(vs 0050)、勝率、IC。
        IC = entry final_composite 與「實現報酬」之 Spearman 等級相關（Grinold & Kahn 選股技術指標）。
        """
        navs = self.ledger["daily_nav"]
        out = {
            "days": len(navs), "cum_return_pct": None, "annual_return_pct": None,
            "sharpe": None, "max_drawdown_pct": None, "alpha_pct": None,
            "win_rate_pct": None, "n_closed": 0, "ic": None,
            "disclaimer": "歷史回測不代表未來報酬，僅供策略穩定性與風險特徵參考。",
        }
        if len(navs) >= 2:
            series = pd.Series([r["nav"] for r in navs], dtype=float)
            rets = series.pct_change().dropna()
            out["cum_return_pct"] = round((series.iloc[-1] / series.iloc[0] - 1) * 100, 2)
            # 年化（以實際天數外推）
            yrs = max(len(navs) / trading_days, 1e-9)
            out["annual_return_pct"] = round(((series.iloc[-1] / series.iloc[0]) ** (1 / yrs) - 1) * 100, 2)
            if rets.std(ddof=1) > 0:
                rf_daily = risk_free_annual / trading_days
                out["sharpe"] = round((rets.mean() - rf_daily) / rets.std(ddof=1) * math.sqrt(trading_days), 2)
            # 最大回撤
            peak = series.cummax()
            dd = (series / peak - 1) * 100
            out["max_drawdown_pct"] = round(dd.min(), 2)
            # Alpha vs 基準
            last = navs[-1]
            if last.get("bench_return_pct") is not None and last.get("cum_return_pct") is not None:
                out["alpha_pct"] = round(last["cum_return_pct"] - last["bench_return_pct"], 2)

        # 勝率 + IC（用已平倉 SELL 交易）
        closed = [t for t in self.ledger["trades"] if t.get("action") == "SELL" and t.get("ret_pct") is not None]
        out["n_closed"] = len(closed)
        if closed:
            wins = sum(1 for t in closed if t["ret_pct"] > 0)
            out["win_rate_pct"] = round(wins / len(closed) * 100, 1)
            pairs = [(t["entry_score"], t["ret_pct"]) for t in closed if t.get("entry_score") is not None]
            if len(pairs) >= 5:
                a = pd.Series([p[0] for p in pairs])
                b = pd.Series([p[1] for p in pairs])
                ic = a.corr(b, method="spearman")
                out["ic"] = round(float(ic), 3) if ic == ic else None  # NaN guard
        return out
