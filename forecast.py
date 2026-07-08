# -*- coding: utf-8 -*-
"""
forecast.py — 個股前瞻營收 / EPS / Forward P/E 推估引擎（純函式、不連網）

⚠️ 合規重點（守 CLAUDE.md 反造假）：
    免費資料源（FinMind / yfinance）**無分析師共識/財測**。
    本模組所有前瞻數字皆為「歷史 run-rate 模型外推」，**非分析師預估**。
    每項估計皆附 `assumptions`（YoY 視窗、clamp、資料季數）與 `is_estimate=True`，
    UI 必須明確標示「模型推估·非分析師共識/財測」並列出假設。

輸入皆為 finmind_loader 既有函式的回傳形狀：
    rev_trend : get_revenue_trend()  → [{month, revenue, yoy_pct, mom_pct, ytd_yoy_pct}]
    fin_trend : get_financial_trend() → [{quarter, eps, gross_margin, ..., eps_yoy}]
    breakout  : get_eps_breakout()    → {annual_pace, ytd_eps, quarters_counted,
                                          prev_full_year_eps, curr_year, prev_year, ...}
    per_trend : get_per_trend()       → [{date, pe, pb, dy}]
    close     : float 現價
    fund      : get_fundamental()     → {eps(TTM), pe, pb, ...}

所有函式為純函式（無 I/O、無隨機），可單元測試。
"""

from statistics import median
from typing import Dict, List, Optional

# 成長率 clamp 邊界（比照 finmind_loader.get_eps_fair_value 的 fair_growth）
GROWTH_CLAMP_LOW = -0.30
GROWTH_CLAMP_HIGH = 0.50
# 前瞻 PE 相對歷史中位的高估門檻
OVERVALUED_PE_RATIO = 1.2


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _safe_year(ym: str) -> Optional[int]:
    """從 'YYYY-MM' 取年份"""
    if isinstance(ym, str) and len(ym) >= 4 and ym[:4].isdigit():
        return int(ym[:4])
    return None


def _safe_month(ym: str) -> Optional[int]:
    if isinstance(ym, str) and len(ym) >= 7 and ym[5:7].isdigit():
        return int(ym[5:7])
    return None


# ── 1. 年度營收估（進度追蹤法）────────────────────────────────────────

def _estimate_annual_revenue(rev_trend: List[Dict]) -> Optional[Dict]:
    """
    本年度全年營收估（進度追蹤法）：
        今年已公布月營收（實際） + 剩餘月份用「去年同月 ×(1 + 近3月平均 YoY)」推估。
    另回傳前 2~3 年的年度實際營收（by year 合計），供長條圖。
    """
    if not rev_trend:
        return None

    # 建立 ym → revenue 查表 與 年度合計
    ym_rev: Dict[str, float] = {}
    year_sum: Dict[int, float] = {}
    year_months: Dict[int, int] = {}
    for r in rev_trend:
        ym = r.get("month")
        rev = r.get("revenue")
        y = _safe_year(ym or "")
        if ym is None or rev is None or y is None:
            continue
        ym_rev[ym] = float(rev)
        year_sum[y] = year_sum.get(y, 0.0) + float(rev)
        year_months[y] = year_months.get(y, 0) + 1

    if not ym_rev:
        return None

    latest_ym = max(ym_rev.keys())
    curr_year = _safe_year(latest_ym)
    latest_month = _safe_month(latest_ym)
    if curr_year is None or latest_month is None:
        return None

    # 近 3 個月平均 YoY（過濾 None）
    recent_yoy = [r.get("yoy_pct") for r in rev_trend if r.get("yoy_pct") is not None]
    recent_yoy = recent_yoy[-3:]
    avg_yoy = (sum(recent_yoy) / len(recent_yoy) / 100.0) if recent_yoy else 0.0
    # YoY 也 clamp 避免單月異常放大全年估
    avg_yoy = _clamp(avg_yoy, GROWTH_CLAMP_LOW, GROWTH_CLAMP_HIGH)

    # 今年 YTD 實際（1..latest_month）
    ytd_actual = sum(
        ym_rev.get(f"{curr_year:04d}-{m:02d}", 0.0) for m in range(1, latest_month + 1)
    )

    # 剩餘月份推估：去年同月 ×(1+avg_yoy)
    est_remaining = 0.0
    remaining_estimable = 0
    for m in range(latest_month + 1, 13):
        prev_key = f"{curr_year - 1:04d}-{m:02d}"
        if prev_key in ym_rev:
            est_remaining += ym_rev[prev_key] * (1 + avg_yoy)
            remaining_estimable += 1

    fy_rev_est = ytd_actual + est_remaining

    # 前 2~3 年完整年度實際（只取有 >=12 個月 或 最完整的歷史年）
    annual_actuals: Dict[int, float] = {}
    for y, total in year_sum.items():
        if y == curr_year:
            continue
        annual_actuals[y] = round(total, 0)
    # 只保留最近 3 個歷史年
    hist_years = sorted(annual_actuals.keys())[-3:]
    annual_actuals = {y: annual_actuals[y] for y in hist_years}

    return {
        "curr_year": curr_year,
        "fy_revenue_est": round(fy_rev_est, 0),
        "ytd_actual": round(ytd_actual, 0),
        "months_reported": latest_month,
        "annual_actuals": annual_actuals,   # {year: revenue}
        "assumptions": {
            "method": "進度追蹤法（YTD 實際 + 剩餘月份 = 去年同月×(1+近3月平均YoY)）",
            "avg_yoy_used": round(avg_yoy * 100, 2),
            "yoy_window": len(recent_yoy),
            "remaining_months_estimated": 12 - latest_month,
            "remaining_months_have_prior": remaining_estimable,
            "clamp": [GROWTH_CLAMP_LOW, GROWTH_CLAMP_HIGH],
        },
        "is_estimate": True,
    }


# ── 2. 年度 EPS 估（seasonal 法）─────────────────────────────────────

def _estimate_annual_eps(fin_trend: List[Dict], breakout: Dict) -> Optional[Dict]:
    """
    本年度全年 EPS 估（seasonal 法）：
        已公布季（實際） + 未公布季 = 去年同季 ×(1 + 近期 EPS YoY)。
    另附 breakout.annual_pace（YTD×4/季數）作交叉驗證。
    """
    if not fin_trend:
        return None

    # 建立 quarter(YYYY-MM) → eps，並按年分組
    q_eps: Dict[str, float] = {}
    year_q: Dict[int, List[str]] = {}
    for q in fin_trend:
        qm = q.get("quarter")
        eps = q.get("eps")
        y = _safe_year(qm or "")
        if qm is None or eps is None or y is None:
            continue
        q_eps[qm] = float(eps)
        year_q.setdefault(y, []).append(qm)

    if not q_eps:
        return None

    latest_q = max(q_eps.keys())
    curr_year = _safe_year(latest_q)
    if curr_year is None:
        return None

    # 近期 EPS YoY（近 4 季有值者平均）
    recent_eyoy = [q.get("eps_yoy") for q in fin_trend if q.get("eps_yoy") is not None]
    recent_eyoy = recent_eyoy[-4:]
    avg_eyoy = (sum(recent_eyoy) / len(recent_eyoy) / 100.0) if recent_eyoy else 0.0
    avg_eyoy = _clamp(avg_eyoy, GROWTH_CLAMP_LOW, GROWTH_CLAMP_HIGH)

    # 台股季別以月份 03/06/09/12 為 Q1..Q4
    quarter_months = ["03", "06", "09", "12"]
    reported_this_year = sorted(year_q.get(curr_year, []))
    reported_eps_sum = sum(q_eps[qm] for qm in reported_this_year)
    reported_months = {qm[5:7] for qm in reported_this_year}

    # 未公布季用去年同季 ×(1+avg_eyoy)
    est_unreported = 0.0
    unreported_cnt = 0
    for mm in quarter_months:
        if mm in reported_months:
            continue
        prev_key = f"{curr_year - 1:04d}-{mm}"
        if prev_key in q_eps:
            est_unreported += q_eps[prev_key] * (1 + avg_eyoy)
            unreported_cnt += 1

    fy_eps_est = reported_eps_sum + est_unreported

    annual_pace = breakout.get("annual_pace") if breakout else None

    # 前 2~3 年完整年度實際 EPS（>=4 季者，供長條圖歷史柱）
    annual_actuals: Dict[int, float] = {}
    for y in sorted(year_q.keys()):
        if y == curr_year:
            continue
        qs = [qm for qm in year_q[y] if qm in q_eps]
        if len(qs) >= 4:
            annual_actuals[y] = round(sum(q_eps[qm] for qm in qs), 2)
    # 退回：breakout 的去年全年 EPS（季報不足 4 季但有官方全年數時）
    if breakout:
        pfy = breakout.get("prev_full_year_eps")
        pyr = breakout.get("prev_year")
        if pfy is not None and pyr is not None and pyr not in annual_actuals:
            annual_actuals[int(pyr)] = round(float(pfy), 2)
    annual_actuals = {y: annual_actuals[y] for y in sorted(annual_actuals.keys())[-3:]}

    return {
        "curr_year": curr_year,
        "fy_eps_est": round(fy_eps_est, 2),
        "reported_eps_ytd": round(reported_eps_sum, 2),
        "quarters_reported": len(reported_this_year),
        "annual_pace_crosscheck": annual_pace,
        "annual_actuals": annual_actuals,   # {year: eps}
        "assumptions": {
            "method": "季度 seasonal 法（已報季實際 + 未報季 = 去年同季×(1+近期EPS YoY)）",
            "avg_eps_yoy_used": round(avg_eyoy * 100, 2),
            "eps_yoy_window": len(recent_eyoy),
            "quarters_estimated": unreported_cnt,
            "clamp": [GROWTH_CLAMP_LOW, GROWTH_CLAMP_HIGH],
        },
        "is_estimate": True,
    }


# ── 3. FY+1 EPS 估（前瞻成長率）──────────────────────────────────────

def _eps_cagr(fin_trend: List[Dict]) -> Optional[float]:
    """由季報 EPS 估算年度 EPS 的歷史 CAGR（以年度合計計）。回小數（如 0.15）。"""
    year_eps: Dict[int, float] = {}
    for q in fin_trend or []:
        y = _safe_year(q.get("quarter") or "")
        eps = q.get("eps")
        if y is not None and eps is not None:
            year_eps[y] = year_eps.get(y, 0.0) + float(eps)
    # 只取「完整」年（>=4 季）避免當年不完整拖低
    full_years = {y: v for y, v in year_eps.items()
                  if sum(1 for q in fin_trend if _safe_year(q.get("quarter") or "") == y
                         and q.get("eps") is not None) >= 4}
    ys = sorted(full_years.keys())
    if len(ys) < 2:
        return None
    first, last = full_years[ys[0]], full_years[ys[-1]]
    n = ys[-1] - ys[0]
    if first <= 0 or last <= 0 or n <= 0:
        return None
    return (last / first) ** (1.0 / n) - 1.0


def _estimate_fy1_eps(fy_eps_est: Optional[float],
                      rev_trend: List[Dict],
                      fin_trend: List[Dict]) -> Optional[Dict]:
    """
    FY+1 EPS 估 = 本年 EPS 估 ×(1 + forward_growth)。
    forward_growth = 營收動能與歷史 EPS CAGR 混合，clamp [-30%, +50%]。
    附保守/基準/樂觀帶（±10pp）。
    """
    if fy_eps_est is None:
        return None

    # 營收動能：近 3 月平均 YoY
    recent_yoy = [r.get("yoy_pct") for r in (rev_trend or []) if r.get("yoy_pct") is not None]
    rev_mom = (sum(recent_yoy[-3:]) / len(recent_yoy[-3:]) / 100.0) if recent_yoy else None

    eps_cagr = _eps_cagr(fin_trend)

    # 混合：兩者皆有取平均；僅一者用該值；皆無用 0
    parts = [x for x in (rev_mom, eps_cagr) if x is not None]
    forward_growth = (sum(parts) / len(parts)) if parts else 0.0
    forward_growth = _clamp(forward_growth, GROWTH_CLAMP_LOW, GROWTH_CLAMP_HIGH)

    def _eps_at(g: float) -> float:
        return round(fy_eps_est * (1 + g), 2)

    base = _eps_at(forward_growth)
    conservative = _eps_at(_clamp(forward_growth - 0.10, GROWTH_CLAMP_LOW, GROWTH_CLAMP_HIGH))
    optimistic = _eps_at(_clamp(forward_growth + 0.10, GROWTH_CLAMP_LOW, GROWTH_CLAMP_HIGH))

    return {
        "fy1_eps_est": base,
        "fy1_eps_conservative": conservative,
        "fy1_eps_optimistic": optimistic,
        "forward_growth": round(forward_growth * 100, 2),
        "assumptions": {
            "method": "FY 本年估 ×(1+前瞻成長率)；成長率=營收動能與EPS CAGR混合",
            "revenue_momentum_yoy": round(rev_mom * 100, 2) if rev_mom is not None else None,
            "eps_cagr": round(eps_cagr * 100, 2) if eps_cagr is not None else None,
            "band": "基準 ±10pp（保守/樂觀）",
            "clamp": [GROWTH_CLAMP_LOW, GROWTH_CLAMP_HIGH],
        },
        "is_estimate": True,
    }


# ── 4. Forward P/E ─────────────────────────────────────────────────

def _historical_median_pe(per_trend: List[Dict], fund: Dict) -> Optional[float]:
    pes = [p.get("pe") for p in (per_trend or [])
           if p.get("pe") is not None and p.get("pe") > 0]
    if pes:
        return round(float(median(pes)), 2)
    # 退回：用現行 PE 當唯一參考（無歷史時無法談分位，回 None 較誠實）
    cur = (fund or {}).get("pe")
    if cur is not None and cur > 0:
        return round(float(cur), 2)
    return None


def _forward_pe(close: Optional[float],
                fy_eps_est: Optional[float],
                fy1_eps_est: Optional[float],
                per_trend: List[Dict],
                fund: Dict) -> Optional[Dict]:
    if close is None or close <= 0:
        return None

    def _pe(eps: Optional[float]) -> Optional[float]:
        if eps is None or eps <= 0:
            return None
        return round(close / eps, 2)

    fwd_pe_cur = _pe(fy_eps_est)
    fwd_pe_next = _pe(fy1_eps_est)
    hist_median = _historical_median_pe(per_trend, fund)

    overvalued = False
    warning = None
    ratio = None
    # 以「本年前瞻 PE」對照歷史中位判斷是否已反映樂觀預期
    ref_pe = fwd_pe_cur if fwd_pe_cur is not None else fwd_pe_next
    if ref_pe is not None and hist_median is not None and hist_median > 0:
        ratio = round(ref_pe / hist_median, 2)
        if ratio >= OVERVALUED_PE_RATIO:
            overvalued = True
            warning = (
                f"前瞻本益比（{ref_pe}）已明顯高於歷史中位（{hist_median}），"
                f"約 {ratio}×，可能已反映樂觀預期·不宜追高。"
            )

    return {
        "fwd_pe_cur": fwd_pe_cur,
        "fwd_pe_next": fwd_pe_next,
        "hist_median_pe": hist_median,
        "fwd_vs_hist_ratio": ratio,
        "overvalued_warning": overvalued,
        "warning_msg": warning,
        "assumptions": {
            "method": "Forward P/E = 現價 / 前瞻 EPS 估；對照歷史 PE 中位",
            "overvalued_ratio_threshold": OVERVALUED_PE_RATIO,
        },
        "is_estimate": True,
    }


# ── 對外主函式 ──────────────────────────────────────────────────────

def build_forward_estimates(
    rev_trend: Optional[List[Dict]] = None,
    fin_trend: Optional[List[Dict]] = None,
    breakout: Optional[Dict] = None,
    per_trend: Optional[List[Dict]] = None,
    close: Optional[float] = None,
    fund: Optional[Dict] = None,
) -> Dict:
    """
    整合前瞻推估：回傳本年營收/EPS 估、FY+1 EPS 估、Forward P/E 與高估旗標。

    資料不足時回 {"has_data": False}（優雅退場，UI 不顯示前瞻區塊）。
    所有估計皆為模型 run-rate 外推，非分析師共識/財測（is_estimate=True）。
    """
    rev_trend = rev_trend or []
    fin_trend = fin_trend or []
    breakout = breakout or {}
    per_trend = per_trend or []
    fund = fund or {}

    revenue_est = _estimate_annual_revenue(rev_trend)
    eps_est = _estimate_annual_eps(fin_trend, breakout)

    # 兩大估計皆缺 → 無足夠資料
    if revenue_est is None and eps_est is None:
        return {"has_data": False}

    fy_eps_val = eps_est.get("fy_eps_est") if eps_est else None
    fy1_est = _estimate_fy1_eps(fy_eps_val, rev_trend, fin_trend)

    fy1_eps_val = fy1_est.get("fy1_eps_est") if fy1_est else None
    fwd_pe = _forward_pe(close, fy_eps_val, fy1_eps_val, per_trend, fund)

    return {
        "has_data": True,
        "is_estimate": True,
        "disclaimer": "營收/EPS 為模型 run-rate 外推，非分析師共識/財測；僅供研究參考，不構成投資建議。",
        "revenue": revenue_est,
        "eps": eps_est,
        "eps_fy1": fy1_est,
        "forward_pe": fwd_pe,
    }
