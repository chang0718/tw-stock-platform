"""
訊號引擎 - 個股買入/賣出/持有建議
基於技術面、籌碼面、基本面的綜合判斷
零假數據：每條理由必須基於真實可用的數據
"""

from typing import Dict, List, Optional


class SignalEngine:

    def get_signal(
        self,
        stock: Dict,        # from model_df row (prob20, momentum_score, flow_score, etc.)
        tech: Dict = None,  # from tech_analyze() result (analysis sub-dict)
    ) -> Dict:
        """
        回傳:
        {
            "signal":     "BUY" | "SELL" | "HOLD",
            "label":      "🟢 建議買進" | "🔴 建議賣出" | "🟡 持續觀察",
            "confidence": float,   # 0-100
            "reasons":    [str],   # 3-5 條具體理由（Traditional Chinese）
            "caution":    [str],   # 0-3 條風險提示
            "scoring_path": str,   # "完整" or "技術動能"
        }
        """
        reasons: List[str] = []
        cautions: List[str] = []
        bullish_score = 0
        bearish_score = 0

        prob20       = stock.get("prob20", 50)
        prob5        = stock.get("prob5", 50)
        prob60       = stock.get("prob60", 50)
        confidence   = stock.get("confidence", 50)
        risk_score   = stock.get("risk_score", 50)
        momentum     = stock.get("momentum_score", 50)
        flow         = stock.get("flow_score", 50)
        quality      = stock.get("quality_score", 50)
        composite    = stock.get("composite_score", 50)
        foreign_net  = stock.get("foreign_net")
        trust_net    = stock.get("trust_net")
        pe           = stock.get("pe")
        pb           = stock.get("pb")
        eps          = stock.get("eps")
        revenue_yoy  = stock.get("revenue_yoy")
        gross_margin = stock.get("gross_margin")
        scoring_path = stock.get("scoring_path", "技術動能")

        # ── 量化機率訊號 ──
        if prob20 >= 65:
            bullish_score += 2
            reasons.append(f"📊 模型20日上漲機率 {prob20:.1f}%，高於多數個股")
        elif prob20 <= 40:
            bearish_score += 2
            reasons.append(f"📊 模型20日上漲機率僅 {prob20:.1f}%，偏低")

        if confidence >= 70:
            bullish_score += 1
            reasons.append(f"🎯 模型信心度 {confidence:.0f}%，訊號較為明確")
        elif confidence <= 45:
            cautions.append(f"⚠️ 模型信心度 {confidence:.0f}%，訊號不確定性高")

        # ── 技術面訊號 ──
        if momentum >= 65:
            bullish_score += 2
            reasons.append(f"📈 動能分數 {momentum:.0f}/100，股價走勢強勢")
        elif momentum <= 40:
            bearish_score += 1
            reasons.append(f"📉 動能分數 {momentum:.0f}/100，近期走勢偏弱")

        if tech:
            ana = tech.get("analysis", {})
            signals = ana.get("signals", [])
            # Count bullish/bearish signals from tech analysis
            for sig in signals:
                if any(kw in sig for kw in ["黃金交叉", "突破", "多頭", "走強", "支撐"]):
                    bullish_score += 1
                    if len(reasons) < 5:
                        reasons.append(f"📡 {sig}")
                    break
            for sig in signals:
                if any(kw in sig for kw in ["死亡交叉", "跌破", "空頭", "走弱", "壓力"]):
                    bearish_score += 1
                    if len(cautions) < 3:
                        cautions.append(f"⚠️ {sig}")
                    break

            tech_score = ana.get("score", 0)
            if tech_score >= 4:
                bullish_score += 1
                if len(reasons) < 5:
                    reasons.append(f"📈 技術面整體偏多（技術分數 {tech_score}/10）")
            elif tech_score <= -3:
                bearish_score += 1
                if len(cautions) < 3:
                    cautions.append(f"⚠️ 技術面整體偏空（技術分數 {tech_score}/10）")

        # ── 籌碼訊號 ──
        if foreign_net is not None:
            if foreign_net > 500:
                bullish_score += 2
                reasons.append(f"💰 外資買超 {foreign_net:+,} 千股，籌碼積極流入")
            elif foreign_net < -500:
                bearish_score += 2
                reasons.append(f"💸 外資賣超 {abs(foreign_net):,} 千股，籌碼流出明顯")
            elif foreign_net > 0:
                bullish_score += 1
                reasons.append(f"💰 外資小幅買超 {foreign_net:+,} 千股")

        if trust_net is not None and abs(trust_net) > 200:
            if trust_net > 0:
                bullish_score += 1
                if len(reasons) < 5:
                    reasons.append(f"🏦 投信買超 {trust_net:+,} 千股，法人佈局")

        if flow >= 65:
            if len(reasons) < 5:
                reasons.append(f"💹 籌碼分數 {flow:.0f}/100，法人整體買超")
            bullish_score += 1

        # ── 基本面訊號（僅限有真實數據時）──
        if scoring_path == "完整":
            if revenue_yoy is not None:
                if revenue_yoy >= 20:
                    bullish_score += 2
                    if len(reasons) < 5:
                        reasons.append(f"📦 月營收 YoY {revenue_yoy:+.1f}%，成長強勁")
                elif revenue_yoy <= -15:
                    bearish_score += 1
                    cautions.append(f"⚠️ 月營收 YoY {revenue_yoy:+.1f}%，衰退需關注")

            if pe is not None:
                if pe < 12:
                    bullish_score += 1
                    if len(reasons) < 5:
                        reasons.append(f"💎 本益比 {pe:.1f}x，估值偏低")
                elif pe > 40:
                    cautions.append(f"⚠️ 本益比 {pe:.1f}x，估值偏高，需注意回調")

            if gross_margin is not None and gross_margin >= 40:
                bullish_score += 1
                if len(reasons) < 5:
                    reasons.append(f"✨ 毛利率 {gross_margin:.1f}%，護城河強")

        # ── 風險提示 ──
        if risk_score > 70:
            cautions.append(f"⚠️ 風險分數 {risk_score:.0f}，波動較大，建議控制部位")

        # ── 最終判斷 ──
        net = bullish_score - bearish_score

        if net >= 4:
            signal, label = "BUY", "🟢 建議買進"
        elif net >= 2:
            signal, label = "BUY", "🟢 可分批佈局"
        elif net <= -3:
            signal, label = "SELL", "🔴 建議減碼"
        elif net <= -1:
            signal, label = "SELL", "🔴 觀察賣出時機"
        else:
            signal, label = "HOLD", "🟡 持續觀察"

        # 計算信心指數
        sig_conf = round(
            min(90, 40 + abs(net) * 10 + (confidence - 50) * 0.3),
            1
        )

        # 若資料不足，降低信心
        if not reasons:
            reasons.append("⚠️ 數據不足，以下為初步判斷")
        if scoring_path == "技術動能":
            cautions.append("ℹ️ 尚無基本面數據，建議加入追蹤後載入 FinMind 基本面")

        return {
            "signal":       signal,
            "label":        label,
            "confidence":   sig_conf,
            "reasons":      reasons[:5],
            "caution":      cautions[:3],
            "bullish_pts":  bullish_score,
            "bearish_pts":  bearish_score,
            "scoring_path": scoring_path,
        }
