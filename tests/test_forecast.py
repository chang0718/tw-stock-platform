# -*- coding: utf-8 -*-
"""
forecast.py 前瞻推估引擎測試（合成資料，不連網）

覆蓋：
- 年度營收估（進度追蹤法 / 年化）
- 年度 EPS 估（seasonal 投影）
- FY+1 成長率 clamp 邊界
- Forward P/E 計算
- 高估旗標（overvalued_warning）
- 資料不足回 has_data False
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from forecast import (
    build_forward_estimates,
    GROWTH_CLAMP_LOW,
    GROWTH_CLAMP_HIGH,
)


# ── 合成資料工具 ────────────────────────────────────────────────────

def _rev_trend_two_years(curr_year=2026, months_reported=6,
                         prev_monthly=100, yoy_pct=10.0):
    """去年 12 個月 + 今年已報 months_reported 個月。revenue 單位任意。"""
    out = []
    # 去年完整 12 月
    for m in range(1, 13):
        out.append({
            "month": f"{curr_year-1:04d}-{m:02d}",
            "revenue": prev_monthly,
            "yoy_pct": None,
            "mom_pct": None,
            "ytd_yoy_pct": None,
        })
    # 今年已報月份（YoY = yoy_pct）
    curr_monthly = round(prev_monthly * (1 + yoy_pct / 100.0))
    for m in range(1, months_reported + 1):
        out.append({
            "month": f"{curr_year:04d}-{m:02d}",
            "revenue": curr_monthly,
            "yoy_pct": yoy_pct,
            "mom_pct": 0.0,
            "ytd_yoy_pct": yoy_pct,
        })
    return out


def _fin_trend_two_years(curr_year=2026, quarters_reported=2,
                         prev_q_eps=1.0, eps_yoy=20.0):
    """去年 4 季 + 今年已報 quarters_reported 季。台股季別月份 03/06/09/12。"""
    q_months = ["03", "06", "09", "12"]
    out = []
    for mm in q_months:
        out.append({
            "quarter": f"{curr_year-1:04d}-{mm}",
            "eps": prev_q_eps,
            "gross_margin": 40.0,
            "operating_margin": 20.0,
            "net_margin": 15.0,
            "eps_qoq": None,
            "gm_qoq": None,
            "eps_yoy": None,
        })
    curr_q_eps = round(prev_q_eps * (1 + eps_yoy / 100.0), 4)
    for i in range(quarters_reported):
        out.append({
            "quarter": f"{curr_year:04d}-{q_months[i]}",
            "eps": curr_q_eps,
            "gross_margin": 42.0,
            "operating_margin": 22.0,
            "net_margin": 16.0,
            "eps_qoq": None,
            "gm_qoq": None,
            "eps_yoy": eps_yoy,
        })
    return out


def _per_trend(pe=15.0, n=300):
    return [{"date": f"2026-01-{(i % 28)+1:02d}", "pe": pe, "pb": 2.0, "dy": 3.0}
            for i in range(n)]


# ============================================================
# 1. 年度營收估（進度追蹤法）
# ============================================================

class TestAnnualRevenue:
    def test_annualizes_full_year(self):
        """6 月已報 + 6 月推估 → 全年估 ≈ YTD/6 × 全年（YoY 10%）"""
        rev = _rev_trend_two_years(months_reported=6, prev_monthly=100, yoy_pct=10.0)
        est = build_forward_estimates(rev_trend=rev, fin_trend=[])
        assert est["has_data"] is True
        r = est["revenue"]
        # 今年月營收 = 110；YTD(6月) = 660
        assert r["ytd_actual"] == 660
        # 剩餘 6 月 = 去年同月(100)×(1+0.10) = 110 ×6 = 660 → 全年 1320
        assert r["fy_revenue_est"] == pytest.approx(1320, abs=1)
        assert r["is_estimate"] is True

    def test_prior_year_actuals_present(self):
        """回傳前一年度實際年營收（供長條圖）"""
        rev = _rev_trend_two_years(curr_year=2026, months_reported=6)
        est = build_forward_estimates(rev_trend=rev, fin_trend=[])
        actuals = est["revenue"]["annual_actuals"]
        assert 2025 in actuals
        assert actuals[2025] == pytest.approx(1200, abs=1)  # 100×12

    def test_assumptions_yoy_clamped(self):
        """近3月平均 YoY 被 clamp 到上限（避免異常放大）"""
        rev = _rev_trend_two_years(months_reported=3, prev_monthly=100, yoy_pct=200.0)
        est = build_forward_estimates(rev_trend=rev, fin_trend=[])
        avg = est["revenue"]["assumptions"]["avg_yoy_used"] / 100.0
        assert avg <= GROWTH_CLAMP_HIGH + 1e-9


# ============================================================
# 2. 年度 EPS 估（seasonal）
# ============================================================

class TestAnnualEPS:
    def test_seasonal_projection(self):
        """2 季已報 + 2 季用去年同季×(1+YoY) 投影"""
        fin = _fin_trend_two_years(quarters_reported=2, prev_q_eps=1.0, eps_yoy=20.0)
        est = build_forward_estimates(rev_trend=[], fin_trend=fin)
        e = est["eps"]
        # 已報 2 季 EPS = 1.2×2 = 2.4
        assert e["reported_eps_ytd"] == pytest.approx(2.4, abs=0.01)
        # 未報 Q3+Q4 = 去年(1.0)×(1+0.20)×2 = 2.4 → 全年 4.8
        assert e["fy_eps_est"] == pytest.approx(4.8, abs=0.02)
        assert e["quarters_reported"] == 2

    def test_annual_pace_crosscheck_passed_through(self):
        """breakout.annual_pace 作為交叉驗證欄位傳出"""
        fin = _fin_trend_two_years(quarters_reported=2)
        breakout = {"annual_pace": 5.0, "prev_full_year_eps": 4.0}
        est = build_forward_estimates(rev_trend=[], fin_trend=fin, breakout=breakout)
        assert est["eps"]["annual_pace_crosscheck"] == 5.0


# ============================================================
# 3. FY+1 成長率 clamp
# ============================================================

class TestFY1Growth:
    def test_growth_clamped_high(self):
        """極高營收動能 + EPS CAGR → forward_growth clamp 到 +50%"""
        # 營收 YoY 100%，且年度 EPS 從 4→8（CAGR 100%）
        rev = _rev_trend_two_years(months_reported=3, yoy_pct=100.0)
        fin = _fin_trend_two_years(quarters_reported=4, prev_q_eps=1.0, eps_yoy=100.0)
        est = build_forward_estimates(rev_trend=rev, fin_trend=fin)
        fg = est["eps_fy1"]["forward_growth"] / 100.0
        assert fg <= GROWTH_CLAMP_HIGH + 1e-9

    def test_growth_clamped_low(self):
        """極差動能 → forward_growth clamp 到 -30%"""
        rev = _rev_trend_two_years(months_reported=3, yoy_pct=-80.0)
        fin = _fin_trend_two_years(quarters_reported=4, prev_q_eps=2.0, eps_yoy=-80.0)
        est = build_forward_estimates(rev_trend=rev, fin_trend=fin)
        fg = est["eps_fy1"]["forward_growth"] / 100.0
        assert fg >= GROWTH_CLAMP_LOW - 1e-9

    def test_band_ordering(self):
        """保守 ≤ 基準 ≤ 樂觀"""
        rev = _rev_trend_two_years(months_reported=3, yoy_pct=10.0)
        fin = _fin_trend_two_years(quarters_reported=2, prev_q_eps=1.0, eps_yoy=10.0)
        est = build_forward_estimates(rev_trend=rev, fin_trend=fin)
        fy1 = est["eps_fy1"]
        assert fy1["fy1_eps_conservative"] <= fy1["fy1_eps_est"] <= fy1["fy1_eps_optimistic"]


# ============================================================
# 4. Forward P/E + 高估旗標
# ============================================================

class TestForwardPE:
    def test_forward_pe_computation(self):
        """fwd_pe_cur = close / FY_EPS_est"""
        fin = _fin_trend_two_years(quarters_reported=2, prev_q_eps=1.0, eps_yoy=20.0)
        # FY EPS 估 ≈ 4.8；close=48 → fwd_pe ≈ 10
        est = build_forward_estimates(rev_trend=[], fin_trend=fin,
                                      close=48.0, per_trend=_per_trend(pe=12.0))
        fp = est["forward_pe"]
        assert fp["fwd_pe_cur"] == pytest.approx(10.0, abs=0.1)
        assert fp["hist_median_pe"] == pytest.approx(12.0, abs=0.01)

    def test_overvalued_flag_true(self):
        """前瞻 PE 明顯高於歷史中位 → overvalued_warning True"""
        fin = _fin_trend_two_years(quarters_reported=2, prev_q_eps=1.0, eps_yoy=20.0)
        # FY EPS ≈ 4.8；close=100 → fwd_pe ≈ 20.8；歷史中位 10 → ratio ≈ 2.08 > 1.2
        est = build_forward_estimates(rev_trend=[], fin_trend=fin,
                                      close=100.0, per_trend=_per_trend(pe=10.0))
        fp = est["forward_pe"]
        assert fp["overvalued_warning"] is True
        assert fp["warning_msg"] is not None
        assert "追高" in fp["warning_msg"]

    def test_overvalued_flag_false_when_cheap(self):
        """前瞻 PE 低於歷史中位 → 不觸發旗標"""
        fin = _fin_trend_two_years(quarters_reported=2, prev_q_eps=1.0, eps_yoy=20.0)
        # FY EPS ≈ 4.8；close=48 → fwd_pe ≈ 10；歷史中位 25 → 不高估
        est = build_forward_estimates(rev_trend=[], fin_trend=fin,
                                      close=48.0, per_trend=_per_trend(pe=25.0))
        assert est["forward_pe"]["overvalued_warning"] is False


# ============================================================
# 5. 資料不足
# ============================================================

class TestInsufficientData:
    def test_empty_inputs_returns_has_data_false(self):
        est = build_forward_estimates()
        assert est == {"has_data": False}

    def test_no_revenue_no_eps_returns_false(self):
        est = build_forward_estimates(rev_trend=[], fin_trend=[], close=100.0)
        assert est["has_data"] is False

    def test_only_revenue_still_has_data(self):
        """只有營收也算有資料（EPS 部分為 None）"""
        rev = _rev_trend_two_years(months_reported=6)
        est = build_forward_estimates(rev_trend=rev, fin_trend=[])
        assert est["has_data"] is True
        assert est["revenue"] is not None
        assert est["eps"] is None
