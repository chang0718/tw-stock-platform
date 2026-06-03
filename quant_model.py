"""
台股盤後量化分析平台 - 量化模型模組
v4.0 嚴謹版：因子分數改跨截面 Z-score 標準化

學術依據：
- 價值因子 (E/P)：Fama & French (1992)
- 品質因子 (毛利率/淨利率/EPS)：Novy-Marx (2013)
- 成長因子 (營收/EPS動能)：earnings momentum literature
- 動能因子 (MA乖離)：Jegadeesh & Titman (1993)
- 籌碼因子 (法人淨買)：Gompers & Metrick (2001)
- 低波動因子：Frazzini & Pedersen (2014)
- 期望報酬率：對數常態報酬 E[R]=σ×Φ⁻¹(p)
- 短期反轉/中期動能 horizon 調整：Jegadeesh (1990)
"""

import math
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from config import HISTORY_FILE, CANDIDATE_CRITERIA
from utils import read_json, clamp, sigmoid, to_number


class QuantModel:

    def __init__(self, weights: Dict[str, float]):
        self.weights = self._norm(weights)
        self.price_history = read_json(HISTORY_FILE, {})

    # ── 靜態工具 ──────────────────────────────────────────────────

    @staticmethod
    def _norm(weights: Dict) -> Dict:
        total = sum(weights.values()) or 1
        return {k: v / total for k, v in weights.items()}

    @staticmethod
    def normalize_weights(weights: Dict) -> Dict:
        return QuantModel._norm(weights)

    @staticmethod
    def _norm_cdf(z: float) -> float:
        """正態分佈 CDF，使用 math.erf（stdlib，無需 scipy）"""
        return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

    @staticmethod
    def _probit(p: float) -> float:
        """正態分佈反函數 Φ⁻¹(p)，Acklam rational approximation（無需 scipy）"""
        p = max(1e-6, min(1 - 1e-6, p))
        # Rational approximation — Acklam (2002)
        a = [-3.969683028665376e+01,  2.209460984245205e+02,
             -2.759285104469687e+02,  1.383577518672690e+02,
             -3.066479806614716e+01,  2.506628277459239e+00]
        b = [-5.447609879822406e+01,  1.615858368580409e+02,
             -1.556989798598866e+02,  6.680131188771972e+01,
             -1.328068155288572e+01]
        c = [-7.784894002430293e-03, -3.223964580411365e-01,
             -2.400758277161838e+00, -2.549732539343734e+00,
              4.374664141464968e+00,  2.938163982698783e+00]
        d = [ 7.784695709041462e-03,  3.224671290700398e-01,
              2.445134137142996e+00,  3.754408661907416e+00]
        plo, phi = 0.02425, 1 - 0.02425
        if p < plo:
            q = math.sqrt(-2 * math.log(p))
            x = (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        elif p <= phi:
            q = p - 0.5
            r = q * q
            x = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
                (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
        else:
            q = math.sqrt(-2 * math.log(1 - p))
            x = -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                 ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        return x

    def _cross_sectional_score(
        self, series: pd.Series, higher_is_better: bool = True
    ) -> pd.Series:
        """
        跨截面 Z-score 標準化 → 正態 CDF → 0-100 分
        - 以同期所有股票的分布為基準（非絕對門檻）
        - NaN（無數據）映射為中性值 50
        - 依據：Fama-French (1992) 跨截面因子排序方法
        """
        series = pd.to_numeric(series, errors="coerce")
        s = series if higher_is_better else -series
        valid = s.dropna()
        if len(valid) < 5:
            return pd.Series(50.0, index=series.index)
        mu    = valid.mean()
        sigma = valid.std(ddof=1)
        if sigma < 1e-9:
            return pd.Series(50.0, index=series.index)
        z = (s - mu) / sigma
        return z.apply(
            lambda v: round(self._norm_cdf(float(v)) * 100, 2) if pd.notna(v) else 50.0
        )

    def _col_cs(self, df: pd.DataFrame, col: str, up: bool = True) -> pd.Series:
        """取 DataFrame 欄位做跨截面評分，欄不存在時回中性 50"""
        if col not in df.columns:
            return pd.Series(50.0, index=df.index)
        return self._cross_sectional_score(df[col], up)

    # ── 技術指標（本機快照）────────────────────────────────────────

    def calculate_technical_metrics(
        self, ticker: str, close: Optional[float], change_pct: float = 0
    ) -> Dict:
        if (
            close is not None
            and ticker in self.price_history
            and len(self.price_history[ticker]) >= 20
        ):
            history = self.price_history[ticker][-60:]
            prices  = [p["close"] for p in history if p.get("close") is not None]
            if len(prices) >= 20 and np.mean(prices[-20:]) > 0:
                ma20 = np.mean(prices[-20:])
                m20  = ((close - ma20) / ma20) * 100
                m60  = (
                    ((close - np.mean(prices[-60:])) / np.mean(prices[-60:])) * 100
                    if len(prices) >= 60 else m20
                )
                vol = (np.std(prices[-20:]) / ma20) * 100
                return {
                    "m20": round(m20, 2), "m60": round(m60, 2),
                    "volatility": round(vol, 2), "change_pct": change_pct,
                    "tech_data_source": "✅ 本機快照",
                }
        return {
            "m20": None, "m60": None, "volatility": None,
            "change_pct": change_pct,
            "tech_data_source": "⚠️ 歷史資料不足（每日載入後逐步累積）",
        }

    # ── 基本面（接收預載數據）──────────────────────────────────────

    def calculate_fundamental_metrics(self, fundamental: Optional[Dict] = None) -> Dict:
        if fundamental and fundamental.get("data_type") == "REAL":
            return {
                "revenue_yoy":          fundamental.get("revenue_yoy"),
                "revenue_mom":          fundamental.get("revenue_mom"),
                "eps_growth":           fundamental.get("eps_growth_yoy"),
                "gross_margin":         fundamental.get("gross_margin"),
                "net_margin":           fundamental.get("net_margin"),
                "pe":                   fundamental.get("pe"),
                "pb":                   fundamental.get("pb"),
                "eps":                  fundamental.get("eps"),
                "dividend_yield":       fundamental.get("dividend_yield"),
                "latest_revenue_month": fundamental.get("latest_revenue_month"),
                "fund_data_source":     fundamental.get("data_source", "✅ FinMind API"),
            }
        return {
            "revenue_yoy": None, "revenue_mom": None, "eps_growth": None,
            "gross_margin": None, "net_margin": None, "pe": None,
            "pb": None, "eps": None, "dividend_yield": None,
            "latest_revenue_month": None,
            "fund_data_source": "⚠️ 暫無數據（加入追蹤可自動載入）",
        }

    # ── 籌碼（接收預載數據）────────────────────────────────────────

    def calculate_flow_metrics(
        self, volume: int,
        stock_inst: Optional[Dict] = None,
        stock_margin: Optional[Dict] = None,
    ) -> Dict:
        result: Dict = {"volume": volume}
        if stock_inst:
            result.update({
                "foreign_net":    stock_inst.get("foreign_net"),
                "trust_net":      stock_inst.get("trust_net"),
                "dealer_net":     stock_inst.get("dealer_net"),
                "total_inst_net": stock_inst.get("total_net"),
                "inst_date":      stock_inst.get("date"),
            })
        else:
            result.update({"foreign_net": None, "trust_net": None,
                            "dealer_net": None, "total_inst_net": None})
        if stock_margin:
            result.update({
                "margin_balance": stock_margin.get("margin_balance"),
                "margin_change":  stock_margin.get("margin_change"),
                "short_balance":  stock_margin.get("short_balance"),
                "short_change":   stock_margin.get("short_change"),
            })
        else:
            result.update({"margin_balance": None, "margin_change": None,
                            "short_balance": None, "short_change": None})
        has = result.get("foreign_net") is not None or result.get("margin_balance") is not None
        result["flow_data_source"] = "✅ TWSE API" if has else "⚠️ 暫無數據"
        return result

    # ── 單股因子分數（僅供個股頁面顯示；全量計算使用跨截面版）──────

    def calculate_factor_scores(self, metrics: Dict) -> Dict:
        """
        ⚠️  此方法為單股近似版（絕對公式），僅用於個股頁面即時顯示。
        全量 enrich_dataframe 使用跨截面 Z-score，結果更嚴謹。
        """
        pe  = metrics.get("pe")
        gm  = metrics.get("gross_margin")
        eg  = metrics.get("eps_growth") or 0
        ry  = metrics.get("revenue_yoy") or 0
        m20 = metrics.get("m20") or 0
        m60 = metrics.get("m60") or 0
        cp  = metrics.get("change_pct") or 0
        vol = metrics.get("volatility") or 25
        fn  = metrics.get("foreign_net")

        value_score    = clamp(92 - pe * 1.35)        if pe is not None else 50
        quality_score  = clamp(38 + gm * 0.8 + eg * 0.18) if gm is not None else 50
        growth_score   = clamp(48 + ry * 0.7          + eg * 0.25)
        momentum_score = clamp(50 + m20 * 0.65        + m60 * 0.35 + cp * 3)
        flow_score     = clamp(50 + fn / 120)          if fn is not None else 50
        low_vol_score  = clamp(100 - vol)

        return {
            "value_score": value_score, "quality_score": quality_score,
            "growth_score": growth_score, "momentum_score": momentum_score,
            "flow_score": flow_score, "low_vol_score": low_vol_score,
        }

    # ── 跨截面因子分數（全量計算用）──────────────────────────────────

    def _apply_cross_sectional_scores(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        以同期全市場股票為基準，對每個因子做跨截面 Z-score 標準化。

        因子構建依據：
        value      : E/P = 1/PE，越高越便宜（Fama-French 1992）
        quality    : 毛利率、淨利率、EPS 成長的平均跨截面評分（Novy-Marx 2013）
        growth     : 營收 YoY、EPS 成長的平均跨截面評分（盈餘動能文獻）
        momentum   : MA20 + MA60 乖離率（Jegadeesh-Titman 1993，20日=中期動能）
        flow       : 外資淨買（法人效應，Gompers-Metrick 2001）
        low_vol    : 負波動率（低波動異象，Frazzini-Pedersen 2014）

        注意：沒有真實基本面數據的股票，value/quality/growth 固定 50（中性），
        防止 E/P 或品質因子對無數據股票產生假訊號（garbage in, garbage out）。
        """
        r = df.copy()
        has_fund = df.get("has_real_fund", pd.Series(False, index=df.index)).fillna(False)

        # ── Value: E/P ratio（越高越便宜）──
        pe_num = pd.to_numeric(df["pe"], errors="coerce")
        ep = pe_num.apply(lambda x: 1.0 / x if pd.notna(x) and x > 0 else np.nan)
        value_cs = self._cross_sectional_score(ep, higher_is_better=True)
        r["value_score"] = value_cs.where(has_fund, 50.0)

        # ── Quality: 三指標平均（已各自跨截面標準化，直接平均即可；
        #    不再對平均值二次 Z-score，避免壓縮有效數據與無數據股票的差距）──
        q_components = [self._col_cs(df, col, up=True)
                        for col in ["gross_margin", "net_margin", "eps_growth"]]
        quality_raw = pd.concat(q_components, axis=1).mean(axis=1)
        r["quality_score"] = quality_raw.where(has_fund, 50.0)

        # ── Growth: 同上，直接平均不再二次 Z-score ──
        g_components = [self._col_cs(df, "revenue_yoy", True),
                        self._col_cs(df, "eps_growth",  True)]
        growth_raw = pd.concat(g_components, axis=1).mean(axis=1)
        r["growth_score"] = growth_raw.where(has_fund, 50.0)

        # ── Momentum: MA20(60%) + MA60(40%)，無歷史時以今日漲跌%代理 ──
        # change_pct 全市場皆有，無快照時用它做跨截面排名，避免全部 50
        m20_s = self._col_cs(df, "m20", True)
        m60_s = self._col_cs(df, "m60", True)
        cp_s  = self._col_cs(df, "change_pct", True)
        has_m20 = pd.to_numeric(df.get("m20", pd.Series(dtype=float)), errors="coerce").notna()
        momentum_raw = (
            m20_s.where(has_m20, cp_s) * 0.6 +
            m60_s.where(has_m20, cp_s) * 0.4
        )
        r["momentum_score"] = self._cross_sectional_score(momentum_raw, higher_is_better=True)

        # ── Flow: 外資淨買（千股）；無外資資料時以成交量跨截面排名代理 ──
        # volume 反映市場關注度，無法人資料時給 25-75 範圍（不給滿分 50 避免與有資料混淆）
        has_fn = pd.to_numeric(df.get("foreign_net", pd.Series(dtype=float)), errors="coerce").notna()
        flow_cs  = self._col_cs(df, "foreign_net", up=True)
        vol_cs   = self._col_cs(df, "volume", up=True)
        vol_proxy = (vol_cs * 0.5 + 25).clip(25, 75)  # 壓縮到 25-75，保留外資評分的空間
        r["flow_score"] = flow_cs.where(has_fn, vol_proxy)

        # ── Low Vol: 波動率越低越好（低波動異象）──
        r["low_vol_score"] = self._col_cs(df, "volatility", up=False)

        return r

    def calculate_composite_score(self, scores: Dict) -> float:
        return round(
            self.weights["value"]    * scores["value_score"]    +
            self.weights["quality"]  * scores["quality_score"]  +
            self.weights["growth"]   * scores["growth_score"]   +
            self.weights["momentum"] * scores["momentum_score"] +
            self.weights["flow"]     * scores["flow_score"]     +
            self.weights["low_vol"]  * scores["low_vol_score"],
            2,
        )

    def calculate_risk_score(self, metrics: Dict, scores: Dict) -> float:
        pe  = metrics.get("pe") or 15
        vol = metrics.get("volatility") or 25
        valuation_risk = clamp(pe * 1.7 + vol * 0.45)
        return clamp(
            valuation_risk * 0.45
            + vol          * 0.75
            + max(0, pe - 25) * 0.9
            - scores["low_vol_score"] * 0.12
        )

    def calculate_probability(
        self,
        composite_score: float,
        horizon: int,
        risk_score: float,
        volatility: float,
    ) -> Dict:
        """
        機率計算依據：
        - z = (composite_score - 50) / 15
          composite_score 為跨截面標準化後的加權分數，std ≈ 15
        - horizon 調整：
            5日：短期反轉傾向 (Jegadeesh 1990)，輕微負調整
            60日：中期動能持續 (Jegadeesh-Titman 1993)，輕微正調整
        - 風險懲罰：高風險股預測方向不確定性更高
        - 移除任意縮放係數（原 *0.72）及主觀 industry_boost
        """
        horizon_adj  = {5: -0.08, 20: 0.0, 60: 0.10}.get(horizon, 0.0)
        risk_penalty = 0.15 if risk_score > 70 else (0.10 if risk_score > 55 else 0.0)

        z           = (composite_score - 50) / 15 + horizon_adj - risk_penalty
        probability = clamp(self._norm_cdf(z) * 100, 10, 90)

        confidence  = clamp(
            42
            + abs(probability - 50) * 0.9
            + (8 if composite_score > 60 else 0)
            + (8 if (volatility or 25) < 20 else 0)
            - (8 if risk_score > 75 else 0),
            35, 88,
        )
        return {
            "probability": round(probability, 1),
            "confidence":  round(confidence, 1),
        }

    def calculate_expected_return(
        self, prob20: float, volatility: Optional[float]
    ) -> Optional[float]:
        """
        20 日期望報酬率（%）

        學術依據：對數常態報酬假設
        若 R ~ N(μ, σ²)，則 P(R > 0) = Φ(μ/σ)
        因此 μ = σ × Φ⁻¹(P(R > 0))

        其中 σ 為 20 日波動率（以 20 日價格 std/mean*100 近似）
        Φ⁻¹ = probit 函數（正態分佈反函數）
        """
        if volatility is None or volatility <= 0:
            return None
        p        = max(0.05, min(0.95, prob20 / 100))
        sigma_20 = volatility / 100          # 轉為小數
        mu       = sigma_20 * self._probit(p)
        return round(mu * 100, 2)            # 轉回百分比

    def determine_candidate_level(
        self, prob20: float, confidence: float, risk_score: float
    ) -> str:
        c = CANDIDATE_CRITERIA["核心候選"]
        if prob20 >= c["prob20_min"] and confidence >= c["confidence_min"] and risk_score <= c["risk_max"]:
            return "核心候選"
        c = CANDIDATE_CRITERIA["觀察候選"]
        if prob20 >= c["prob20_min"] and confidence >= c["confidence_min"] and risk_score <= c["risk_max"]:
            return "觀察候選"
        c = CANDIDATE_CRITERIA["高風險觀察"]
        if prob20 >= c["prob20_min"] and risk_score >= c["risk_min"]:
            return "高風險觀察"
        return "保守觀望"

    # ── 個股完整計算（單股頁面用，因子分數為近似版）────────────────

    def enrich_company(
        self, row: Dict, preferred_groups: List[str],
        stock_inst: Optional[Dict] = None,
        stock_margin: Optional[Dict] = None,
        fundamental: Optional[Dict] = None,
    ) -> Dict:
        ticker     = row["ticker"]
        daily      = row.get("daily", {})
        close      = daily.get("close")      # None = 無資料，不填假值
        change_pct = daily.get("change_pct") or 0.0
        volume     = daily.get("volume")     or 0

        tech  = self.calculate_technical_metrics(ticker, close, change_pct)
        fund  = self.calculate_fundamental_metrics(fundamental)
        flow  = self.calculate_flow_metrics(volume, stock_inst, stock_margin)
        all_m = {**tech, **fund, **flow, "close": close}

        scores    = self.calculate_factor_scores(all_m)     # 近似版
        composite = self.calculate_composite_score(scores)
        risk      = self.calculate_risk_score(all_m, scores)

        probs: Dict = {}
        for h in [5, 20, 60]:
            r = self.calculate_probability(
                composite, h, risk, all_m.get("volatility") or 25
            )
            probs[f"prob{h}"] = r["probability"]
            if h == 20:
                probs["confidence"] = r["confidence"]

        candidate_level = self.determine_candidate_level(
            probs["prob20"], probs["confidence"], risk
        )
        expected_return = self.calculate_expected_return(
            probs["prob20"], all_m.get("volatility")
        )

        has_real_fund = all_m.get("pe") is not None or all_m.get("gross_margin") is not None
        has_real_flow = all_m.get("foreign_net") is not None
        scoring_path  = "完整" if has_real_fund else "技術動能"

        return {
            "ticker": ticker, "name": row["name"],
            "industry": row["industry"], "group": row["group"], "market": row["market"],
            **all_m, **scores, **probs,
            "composite_score": composite, "risk_score": risk,
            "candidate_level": candidate_level,
            "expected_return_20d": expected_return,
            "complete_score": has_real_fund and has_real_flow and all_m.get("m20") is not None,
            "has_real_fund": has_real_fund,
            "has_real_flow": has_real_flow,
            "scoring_path": scoring_path,
        }

    # ── 全量計算（跨截面標準化版）────────────────────────────────────

    def enrich_dataframe(
        self, df: pd.DataFrame, preferred_groups: List[str],
        inst_data: Dict = None, margin_data: Dict = None,
        fundamental_data: Dict = None,
        sentiment_data: Dict = None,
    ) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame()

        inst_data        = inst_data        or {}
        margin_data      = margin_data      or {}
        fundamental_data = fundamental_data or {}
        sentiment_data   = sentiment_data   or {}

        # Pass 1：收集各股原始指標
        rows = []
        for _, row in df.iterrows():
            t = row["ticker"]
            rows.append(self.enrich_company(
                row.to_dict(), preferred_groups,
                stock_inst   = inst_data.get(t),
                stock_margin = margin_data.get(t),
                fundamental  = fundamental_data.get(t),
            ))
        result = pd.DataFrame(rows)

        # Pass 2：跨截面 Z-score 替換因子分數
        result = self._apply_cross_sectional_scores(result)

        # 族群落後分：同 group 均值 - 個股 momentum_score → 越大代表落後越多（補漲空間）
        grp_avg_mom = result.groupby("group")["momentum_score"].transform("mean")
        peer_lag_raw = grp_avg_mom - result["momentum_score"]
        result["peer_lag_score"] = self._cross_sectional_score(peer_lag_raw)

        # 外資入場訊號：今日淨買超 且 籌碼分不過熱（剛開始買）
        fn_series = pd.to_numeric(result["foreign_net"], errors="coerce")
        result["inst_entry"] = ((fn_series > 0) & (result["flow_score"] < 60)).astype(int)

        # MACD 即將金叉：從 price_history 計算（close-only MACD，histogram 前負今收斂）
        def _macd_pre_cross(ticker: str) -> bool:
            hist = self.price_history.get(ticker, [])
            closes = [p["close"] for p in hist if p.get("close") is not None]
            if len(closes) < 35:
                return False
            s = pd.Series(closes, dtype=float)
            ema12 = s.ewm(span=12, adjust=False).mean()
            ema26 = s.ewm(span=26, adjust=False).mean()
            macd  = ema12 - ema26
            sig   = macd.ewm(span=9, adjust=False).mean()
            hist_s = macd - sig
            if len(hist_s) < 3:
                return False
            prev_h = hist_s.iloc[-2]
            curr_h = hist_s.iloc[-1]
            # 前一根柱狀為負且本根絕對值縮小（收斂中）
            return bool(prev_h < 0 and abs(curr_h) < abs(prev_h))

        result["macd_pre_cross"] = result["ticker"].apply(_macd_pre_cross)

        # Pass 3：用跨截面因子分數重算 composite / risk / probability
        for idx, row in result.iterrows():
            scores = {
                "value_score":    row["value_score"],
                "quality_score":  row["quality_score"],
                "growth_score":   row["growth_score"],
                "momentum_score": row["momentum_score"],
                "flow_score":     row["flow_score"],
                "low_vol_score":  row["low_vol_score"],
            }
            metrics = {
                "pe":         row.get("pe"),
                "volatility": row.get("volatility"),
            }
            composite = self.calculate_composite_score(scores)

            # 混合評分路徑：無基本面股票改用技術/動能/籌碼加權
            if not row.get("has_real_fund", False):
                tech_composite = (
                    scores["momentum_score"] * 0.45
                    + scores["flow_score"]   * 0.30
                    + scores["low_vol_score"] * 0.25
                )
                # 混合：技術路徑 60%，原始路徑 40%（避免完全忽略任何因子）
                composite = round(tech_composite * 0.6 + composite * 0.4, 2)

            result.at[idx, "scoring_path"] = "完整" if row.get("has_real_fund", False) else "技術動能"

            risk      = self.calculate_risk_score(metrics, scores)
            vol       = row.get("volatility") or 25

            for h in [5, 20, 60]:
                r = self.calculate_probability(composite, h, risk, vol)
                result.at[idx, f"prob{h}"] = r["probability"]
                if h == 20:
                    result.at[idx, "confidence"] = r["confidence"]

            result.at[idx, "composite_score"]    = composite
            result.at[idx, "risk_score"]         = risk
            result.at[idx, "candidate_level"]    = self.determine_candidate_level(
                result.at[idx, "prob20"], result.at[idx, "confidence"], risk
            )
            result.at[idx, "expected_return_20d"] = self.calculate_expected_return(
                result.at[idx, "prob20"], row.get("volatility")
            )

        base_fc = (
            result["prob20"]      * 0.35
            + result["confidence"] * 0.20
            + (result["prob20"] * 0.85) * 0.20   # hit_rate 佔位
            + (100 - result["risk_score"]) * 0.15
            + result["composite_score"]   * 0.10
        )
        # 板塊偏好加成（主動管理選股邏輯，使用者明確的投資主題偏好）
        # +4 分 ≈ 典型分數區間 65-75 的 5-6%，有意義但不主導排名
        group_boost = result["group"].apply(
            lambda g: 4.0 if g in preferred_groups else 0.0
        )
        # 數據完整度加成：有真實基本面+籌碼+技術的股票，預測品質更高
        completeness_bonus = result["complete_score"].apply(
            lambda c: 3.0 if c else 0.0
        )
        # 新聞情緒調整（−5 到 +5 分）：僅對有情緒數據的股票生效
        # sentiment_score: -1.0~1.0（正面新聞佔比），無資料給 0（不影響排名）
        def _news_adj(ticker):
            s = sentiment_data.get(ticker)
            if s is None:
                return 0.0
            return float(max(-5.0, min(5.0, s * 5)))

        news_adj = result["ticker"].apply(_news_adj)
        result["sentiment_score"] = result["ticker"].apply(
            lambda t: sentiment_data.get(t)
        )
        result["final_composite"] = (base_fc + group_boost + completeness_bonus + news_adj).round(2)
        return result

    def find_catchup_candidates(
        self, df: pd.DataFrame, top_n: int = 10
    ) -> pd.DataFrame:
        """
        每日落後補漲候選：族群落後 + 外資入場 + 技術金叉 + 基本面及格
        df 必須已經過 enrich_dataframe()（含 peer_lag_score / inst_entry / kd_cross）
        """
        if df.empty:
            return pd.DataFrame()

        needed = {"peer_lag_score", "inst_entry", "quality_score", "growth_score"}
        missing = needed - set(df.columns)
        if missing:
            return pd.DataFrame()

        sub = df.copy()

        # 基本條件：基本面及格
        sub = sub[
            (sub["quality_score"] > 45) &
            (sub["growth_score"]  > 45)
        ]
        if sub.empty:
            return sub

        # 計算技術金叉分（KD金叉 或 MACD柱翻正）
        def _tech_cross_score(row):
            score = 0
            if row.get("kd_cross", False):
                score += 2
            if row.get("macd_pre_cross", False):
                score += 1
            return score

        if "kd_cross" not in sub.columns:
            sub["kd_cross"] = False
        if "macd_pre_cross" not in sub.columns:
            sub["macd_pre_cross"] = False

        sub["_tech_cross"] = sub.apply(_tech_cross_score, axis=1)

        # 四維度加權排序（不硬性 AND 以避免無候選）
        sub["_catchup_score"] = (
            sub["peer_lag_score"] * 0.35
            + sub["flow_score"]   * 0.30
            + sub["_tech_cross"]  * 10 * 0.20   # 0~3 → 縮放至百分制
            + sub["inst_entry"]   * 100 * 0.15
        )

        # 偏好落後族群 + 外資入場的股票排序，但條件不全的仍可出現
        result = sub.sort_values("_catchup_score", ascending=False).head(top_n)
        return result.drop(columns=["_catchup_score", "_tech_cross"], errors="ignore")

    def calculate_industry_heat(
        self,
        model_df: pd.DataFrame,
        supply_chains: dict,
    ) -> pd.DataFrame:
        """
        計算各產業/供應鏈熱度指數（0–100）。
        組成：籌碼 35% + 技術動能 35% + 新聞情緒 20% + 價格動能 10%
        """
        rows = []
        for group_name, tickers in supply_chains.items():
            sub = model_df[model_df["ticker"].isin(tickers)]
            if sub.empty:
                continue

            # 籌碼分：外資+投信×2+自營，正數表示買超
            fn = pd.to_numeric(sub.get("foreign_net", pd.Series(dtype=float)), errors="coerce")
            tn = pd.to_numeric(sub.get("trust_net",   pd.Series(dtype=float)), errors="coerce")
            dn = pd.to_numeric(sub.get("dealer_net",  pd.Series(dtype=float)), errors="coerce")
            if fn.notna().any():
                total_inst = fn.fillna(0) + tn.fillna(0) * 2 + dn.fillna(0)
                # 每千股 500 為 ±50 分基準，clip 到 10–90
                inst_score = float(np.clip(50 + total_inst.mean() / 500, 10, 90))
            else:
                inst_score = 50.0

            # 技術分：momentum_score 跨截面已 0-100 標準化
            ms = pd.to_numeric(sub.get("momentum_score", pd.Series(dtype=float)), errors="coerce")
            tech_score = float(ms.mean()) if ms.notna().any() else 50.0

            # 新聞情緒分：sentiment_score -1~1 轉 0-100
            ss = pd.to_numeric(sub.get("sentiment_score", pd.Series(dtype=float)), errors="coerce")
            news_score = float(np.clip(50 + ss.mean() * 50, 10, 90)) if ss.notna().any() else 50.0

            # 價格動能分：今日漲跌幅，±10% 對應 0-100
            cp = pd.to_numeric(sub.get("change_pct", pd.Series(dtype=float)), errors="coerce")
            price_score = float(np.clip(50 + cp.mean() * 5, 10, 90)) if cp.notna().any() else 50.0

            heat_index = round(
                inst_score * 0.35 + tech_score * 0.35 + news_score * 0.20 + price_score * 0.10,
                1,
            )

            # 代表股：漲幅前3
            top_gainers: List[str] = []
            if "change_pct" in sub.columns and cp.notna().any():
                top_gainers = sub.nlargest(3, "change_pct")["ticker"].tolist()

            rows.append({
                "group":       group_name,
                "heat_index":  heat_index,
                "inst_score":  round(inst_score, 1),
                "tech_score":  round(tech_score, 1),
                "news_score":  round(news_score, 1),
                "price_score": round(price_score, 1),
                "stock_count": len(sub),
                "avg_change":  round(float(cp.mean()), 2) if cp.notna().any() else 0.0,
                "top_gainers": ", ".join(top_gainers),
            })

        if not rows:
            return pd.DataFrame()
        return (
            pd.DataFrame(rows)
            .sort_values("heat_index", ascending=False)
            .reset_index(drop=True)
        )

    # ── 各族群基本面前 N 名 ────────────────────────────────────────────

    @staticmethod
    def top_by_group(
        df: pd.DataFrame,
        group_col: str = "group",
        metric: str = "gross_margin",
        top_n: int = 3,
    ) -> pd.DataFrame:
        """
        各族群依 metric 取前 top_n 名，回傳含 group/rank/ticker/name/metric 欄位。
        metric 為 None 或 NaN 的列自動排至末尾。
        """
        if df.empty or metric not in df.columns or group_col not in df.columns:
            return pd.DataFrame()
        rows = []
        for grp, sub in df.groupby(group_col, sort=False):
            valid = sub[pd.to_numeric(sub[metric], errors="coerce").notna()].copy()
            valid["_m"] = pd.to_numeric(valid[metric], errors="coerce")
            top = valid.nlargest(top_n, "_m")
            for rank, (_, r) in enumerate(top.iterrows(), 1):
                rows.append({
                    "group":  grp,
                    "rank":   rank,
                    "ticker": r.get("ticker", ""),
                    "name":   r.get("name", ""),
                    metric:   r["_m"],
                })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).reset_index(drop=True)

    # ── 蒙地卡羅 GBM 股價路徑模擬 ────────────────────────────────────

    @staticmethod
    def monte_carlo_price(
        close: float,
        sigma: float,
        mu: float = 0.0,
        days: int = 20,
        n_sim: int = 1000,
    ) -> Dict:
        """
        Geometric Brownian Motion 股價路徑模擬（Geometric Brownian Motion）。
        學術依據：Black-Scholes (1973) GBM 股價過程假設。

        Args:
            close:  現價
            sigma:  年化波動率（小數，如 0.35 = 35%）
            mu:     年化期望報酬（小數，預設 0）
            days:   模擬天數
            n_sim:  模擬路徑數

        Returns: {p10, p25, p50, p75, p90, prob_up, expected_return,
                  range_label, sigma_used}
        """
        if close <= 0 or sigma <= 0:
            return {}
        dt = 1 / 252
        rng = np.random.default_rng()
        Z = rng.standard_normal((n_sim, days))
        log_returns = (mu - 0.5 * sigma ** 2) * dt + sigma * np.sqrt(dt) * Z
        paths = close * np.exp(np.cumsum(log_returns, axis=1))
        final = paths[:, -1]
        p10, p25, p50, p75, p90 = np.percentile(final, [10, 25, 50, 75, 90])
        prob_up = float((final > close).mean() * 100)
        exp_ret = float((p50 - close) / close * 100)
        return {
            "p10":             round(float(p10), 2),
            "p25":             round(float(p25), 2),
            "p50":             round(float(p50), 2),
            "p75":             round(float(p75), 2),
            "p90":             round(float(p90), 2),
            "prob_up":         round(prob_up, 1),
            "expected_return": round(exp_ret, 2),
            "sigma_used":      round(sigma * 100, 1),
            "days":            days,
            "n_sim":           n_sim,
        }
