# -*- coding: utf-8 -*-
"""
quant_model.py 關鍵公式驗證測試

覆蓋：
- _norm：權重正規化
- _norm_cdf / _probit：正態函數數學性質
- calculate_composite_score：加權和邊界
- calculate_probability：機率與信心度範圍
- calculate_risk_score：風險分數範圍
- calculate_expected_return：對數常態報酬公式
- _cross_sectional_score：Z-score → CDF 轉換
"""

import sys
import math
from pathlib import Path

import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DEFAULT_WEIGHTS
from quant_model import QuantModel

# ── 固定測試用模型（使用預設權重）─────────────────────────────────────
@pytest.fixture(scope="module")
def model():
    return QuantModel(weights=DEFAULT_WEIGHTS)


# ── 測試工具分數（每個因子皆為 50，即中性）─────────────────────────────
NEUTRAL_SCORES = {
    "value_score":    50.0,
    "quality_score":  50.0,
    "growth_score":   50.0,
    "momentum_score": 50.0,
    "flow_score":     50.0,
    "low_vol_score":  50.0,
}


# ============================================================
# 1. _norm：權重正規化
# ============================================================

class TestNorm:
    def test_sum_equals_one(self, model):
        """正規化後加總必須 = 1.0"""
        total = sum(model.weights.values())
        assert abs(total - 1.0) < 1e-9

    def test_uniform_weights(self):
        """相等輸入 → 每個比例相等"""
        w = {"a": 10, "b": 10, "c": 10}
        result = QuantModel._norm(w)
        for v in result.values():
            assert abs(v - 1/3) < 1e-9

    def test_zero_total_no_crash(self):
        """全零輸入不崩潰（分母改 1）"""
        w = {"a": 0, "b": 0}
        result = QuantModel._norm(w)
        assert sum(result.values()) == 0.0

    def test_single_key(self):
        """單一權重正規化後 = 1.0"""
        result = QuantModel._norm({"x": 42})
        assert abs(result["x"] - 1.0) < 1e-9


# ============================================================
# 2. _norm_cdf / _probit：正態函數數學性質
# ============================================================

class TestNormalFunctions:
    def test_cdf_at_zero(self, model):
        """Φ(0) = 0.5"""
        assert abs(model._norm_cdf(0.0) - 0.5) < 1e-9

    def test_cdf_positive_z(self, model):
        """z > 0 → CDF > 0.5"""
        assert model._norm_cdf(1.0) > 0.5

    def test_cdf_negative_z(self, model):
        """z < 0 → CDF < 0.5"""
        assert model._norm_cdf(-1.0) < 0.5

    def test_cdf_bounds(self, model):
        """CDF 輸出在 [0, 1]"""
        for z in [-10, -3, -1, 0, 1, 3, 10]:
            v = model._norm_cdf(float(z))
            assert 0.0 <= v <= 1.0

    def test_cdf_symmetry(self, model):
        """Φ(z) + Φ(-z) = 1"""
        for z in [0.5, 1.0, 2.0]:
            assert abs(model._norm_cdf(z) + model._norm_cdf(-z) - 1.0) < 1e-9

    def test_probit_inverse_of_cdf(self, model):
        """probit(Φ(z)) ≈ z（反函數驗證）"""
        for z in [-2.0, -1.0, 0.0, 1.0, 2.0]:
            p = model._norm_cdf(z)
            assert abs(model._probit(p) - z) < 1e-6

    def test_probit_clamps_extreme(self, model):
        """probit 對極端值不崩潰"""
        model._probit(0.0)   # → 使用 1e-6
        model._probit(1.0)   # → 使用 1-1e-6


# ============================================================
# 3. calculate_composite_score：加權和邊界
# ============================================================

class TestCompositeScore:
    def test_neutral_scores_gives_50(self, model):
        """所有因子 50 → composite ≈ 50"""
        score = model.calculate_composite_score(NEUTRAL_SCORES)
        assert abs(score - 50.0) < 0.01

    def test_all_zero_gives_zero(self, model):
        """所有因子 0 → composite = 0"""
        scores = {k: 0.0 for k in NEUTRAL_SCORES}
        assert model.calculate_composite_score(scores) == 0.0

    def test_all_hundred_gives_hundred(self, model):
        """所有因子 100 → composite = 100"""
        scores = {k: 100.0 for k in NEUTRAL_SCORES}
        assert model.calculate_composite_score(scores) == 100.0

    def test_output_in_range(self, model):
        """任意合法輸入 composite 在 [0, 100]"""
        import random
        random.seed(42)
        for _ in range(50):
            scores = {k: random.uniform(0, 100) for k in NEUTRAL_SCORES}
            c = model.calculate_composite_score(scores)
            assert 0.0 <= c <= 100.0


# ============================================================
# 4. calculate_probability：機率與信心度範圍
# ============================================================

class TestProbability:
    @pytest.mark.parametrize("composite,horizon,risk,vol", [
        (50, 5,  30, 20),
        (70, 20, 50, 30),
        (30, 60, 80, 40),
        (90, 20, 10, 15),
        (10, 20, 90, 50),
    ])
    def test_probability_range(self, model, composite, horizon, risk, vol):
        """機率在 [10, 90]"""
        result = model.calculate_probability(composite, horizon, risk, vol)
        p = result["probability"]
        assert 10.0 <= p <= 90.0, f"probability={p} out of [10,90]"

    @pytest.mark.parametrize("composite,horizon,risk,vol", [
        (50, 5,  30, 20),
        (70, 20, 50, 30),
        (30, 60, 80, 40),
    ])
    def test_confidence_range(self, model, composite, horizon, risk, vol):
        """信心度在 [35, 88]"""
        result = model.calculate_probability(composite, horizon, risk, vol)
        c = result["confidence"]
        assert 35.0 <= c <= 88.0, f"confidence={c} out of [35,88]"

    def test_higher_composite_higher_prob(self, model):
        """較高 composite → 較高機率（同 horizon / risk / vol）"""
        p_low  = model.calculate_probability(30, 20, 50, 25)["probability"]
        p_high = model.calculate_probability(70, 20, 50, 25)["probability"]
        assert p_high > p_low

    def test_higher_risk_lower_prob(self, model):
        """較高風險分數 → 較低機率（邊界：risk >70）"""
        p_low_risk  = model.calculate_probability(55, 20, 30, 25)["probability"]
        p_high_risk = model.calculate_probability(55, 20, 80, 25)["probability"]
        assert p_high_risk <= p_low_risk

    def test_horizon_60_higher_than_5(self, model):
        """60 日機率 > 5 日機率（中性 composite）"""
        p5  = model.calculate_probability(55, 5,  40, 25)["probability"]
        p60 = model.calculate_probability(55, 60, 40, 25)["probability"]
        assert p60 > p5


# ============================================================
# 5. calculate_risk_score：風險分數範圍
# ============================================================

class TestRiskScore:
    def test_output_in_clamp_range(self, model):
        """風險分數在 [1, 99]"""
        for pe, vol in [(5, 10), (15, 25), (50, 60), (100, 80)]:
            metrics = {"pe": pe, "volatility": vol}
            risk = model.calculate_risk_score(metrics, NEUTRAL_SCORES)
            assert 1 <= risk <= 99, f"risk={risk} for pe={pe}, vol={vol}"

    def test_none_metrics_no_crash(self, model):
        """None 值不崩潰，使用預設值"""
        risk = model.calculate_risk_score({"pe": None, "volatility": None}, NEUTRAL_SCORES)
        assert 1 <= risk <= 99

    def test_high_pe_high_risk(self, model):
        """高 PE → 風險分數較高"""
        r_low  = model.calculate_risk_score({"pe": 10, "volatility": 20}, NEUTRAL_SCORES)
        r_high = model.calculate_risk_score({"pe": 80, "volatility": 20}, NEUTRAL_SCORES)
        assert r_high >= r_low


# ============================================================
# 6. calculate_expected_return：對數常態報酬
# ============================================================

class TestExpectedReturn:
    def test_returns_none_for_zero_vol(self, model):
        """波動率 = 0 → 回傳 None"""
        assert model.calculate_expected_return(60, 0) is None

    def test_returns_none_for_none_vol(self, model):
        """波動率 = None → 回傳 None"""
        assert model.calculate_expected_return(60, None) is None

    def test_positive_prob_positive_return(self, model):
        """prob20 > 50 → 期望報酬為正"""
        r = model.calculate_expected_return(70, 25)
        assert r is not None and r > 0

    def test_prob_50_near_zero_return(self, model):
        """prob20 = 50（Φ⁻¹(0.5)=0）→ 期望報酬 ≈ 0"""
        r = model.calculate_expected_return(50, 25)
        assert r is not None and abs(r) < 0.01


# ============================================================
# 7. _cross_sectional_score：Z-score → CDF 轉換
# ============================================================

class TestCrossSectionalScore:
    def test_output_in_0_100(self, model):
        """輸出值在 [0, 100]"""
        s = pd.Series([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], dtype=float)
        result = model._cross_sectional_score(s)
        assert (result >= 0).all() and (result <= 100).all()

    def test_higher_value_higher_score(self, model):
        """higher_is_better=True → 較大值得到較高分"""
        s = pd.Series([10.0, 25.0, 50.0, 75.0, 90.0])
        result = model._cross_sectional_score(s, higher_is_better=True)
        assert result.iloc[0] < result.iloc[2] < result.iloc[4]

    def test_lower_is_better_inverted(self, model):
        """higher_is_better=False → 較小值得到較高分"""
        s = pd.Series([10.0, 25.0, 50.0, 75.0, 90.0])
        result = model._cross_sectional_score(s, higher_is_better=False)
        assert result.iloc[0] > result.iloc[2] > result.iloc[4]

    def test_nan_becomes_50(self, model):
        """NaN 映射為中性值 50"""
        s = pd.Series([10.0, float("nan"), 90.0])
        result = model._cross_sectional_score(s)
        assert result.iloc[1] == 50.0

    def test_constant_series_returns_50(self, model):
        """所有值相同（σ=0） → 全部回傳 50"""
        s = pd.Series([42.0] * 10)
        result = model._cross_sectional_score(s)
        assert (result == 50.0).all()

    def test_small_series_returns_50(self, model):
        """樣本數 < 5 → 全部回傳 50"""
        s = pd.Series([1.0, 2.0, 3.0])
        result = model._cross_sectional_score(s)
        assert (result == 50.0).all()

    def test_median_near_50(self, model):
        """對稱分佈的中位數附近分數應接近 50"""
        np.random.seed(42)
        s = pd.Series(np.random.normal(0, 1, 200))
        result = model._cross_sectional_score(s)
        median_score = float(result.median())
        assert 40.0 < median_score < 60.0


# ============================================================
# 8. calculate_probability：score_std 資料驅動除數
# ============================================================

class TestProbabilityStd:
    def test_default_std_unchanged(self, model):
        """預設 score_std=15 → 與舊行為一致（回歸保護）"""
        r_def = model.calculate_probability(65, 20, 40, 25)
        r_15  = model.calculate_probability(65, 20, 40, 25, score_std=15.0)
        assert r_def["probability"] == r_15["probability"]

    def test_smaller_std_sharper(self, model):
        """較小 std → z 較大 → 高分股機率更高（刻度更陡）"""
        p_wide = model.calculate_probability(70, 20, 40, 25, score_std=25.0)["probability"]
        p_narrow = model.calculate_probability(70, 20, 40, 25, score_std=8.0)["probability"]
        assert p_narrow > p_wide

    def test_zero_std_falls_back(self, model):
        """score_std<=0 → 退回 15，不崩潰"""
        r0 = model.calculate_probability(60, 20, 40, 25, score_std=0.0)
        r15 = model.calculate_probability(60, 20, 40, 25, score_std=15.0)
        assert r0["probability"] == r15["probability"]


# ============================================================
# 9. _apply_cross_sectional_scores：因子構建（F3/F5）
# ============================================================

class TestCrossSectionalFactors:
    @staticmethod
    def _sample_df():
        n = 8
        return pd.DataFrame({
            "ticker":       [f"T{i}" for i in range(n)],
            "group":        ["G"] * n,
            "has_real_fund": [True] * n,
            "pe":           [10, 12, 15, 20, 8, 25, 30, 18],
            "pb":           [1.0, 1.5, 2.0, 3.0, 0.8, 4.0, 5.0, 2.5],
            "gross_margin": [40, 30, 50, 20, 45, 15, 35, 25],
            "net_margin":   [15, 10, 20, 5, 18, 3, 12, 8],
            "eps_growth":   [50, 5, -10, 30, 20, 0, 40, 15],
            "revenue_yoy":  [20, 5, -5, 15, 25, 0, 10, 8],
            "foreign_net":  [1000, -500, 200, 0, 800, -300, 100, 50],
            "volume":       [5000, 3000, 8000, 1000, 6000, 500, 4000, 2000],
            "volatility":   [20, 25, 15, 40, 18, 50, 22, 30],
            "m20":          [5, -3, 8, -10, 6, -15, 2, 0],
            "m60":          [10, -5, 12, -20, 8, -25, 3, 1],
            "change_pct":   [1, -1, 2, -3, 1.5, -4, 0.5, 0],
        })

    def test_value_uses_ep_and_bp(self, model):
        """value 為 E/P + B/P 合成：低 PE 且低 PB 的股票分數最高"""
        df = self._sample_df()
        r = model._apply_cross_sectional_scores(df)
        # index 4：PE=8、PB=0.8（最便宜）應得高於 index 6：PE=30、PB=5
        assert r["value_score"].iloc[4] > r["value_score"].iloc[6]

    def test_quality_excludes_eps_growth(self, model):
        """quality 只用毛利/淨利（+ROE），eps_growth 大幅變動不應改變 quality"""
        df = self._sample_df()
        r1 = model._apply_cross_sectional_scores(df)
        df2 = df.copy()
        df2["eps_growth"] = df2["eps_growth"] * -1  # 反轉 eps_growth
        r2 = model._apply_cross_sectional_scores(df2)
        # quality 不含 eps_growth → 兩者相同
        pd.testing.assert_series_equal(
            r1["quality_score"], r2["quality_score"], check_names=False
        )

    def test_quality_includes_roe_when_present(self, model):
        """有 roe 欄且有資料時，roe 影響 quality"""
        df = self._sample_df()
        base = model._apply_cross_sectional_scores(df)["quality_score"]
        df_roe = df.copy()
        df_roe["roe"] = [25, 5, 30, 2, 22, 1, 15, 8]
        with_roe = model._apply_cross_sectional_scores(df_roe)["quality_score"]
        assert not base.equals(with_roe)
