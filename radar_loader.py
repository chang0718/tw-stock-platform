"""
情勢雷達資料載入器。

整合三個來源：
  1. data/future_events.json   — 種子事件日程（Fed/財報/論壇/發表會）
  2. data/event_to_supply_chain_rules.json — 事件→供應鏈傳導規則
  3. data/supply_chains.json   — 供應鏈節點詳情
  4. config.THEME_GRAPH        — 主題→關鍵字→供應鏈→個股橋接
  5. news_analyzer.NewsAnalyzer — 近 3 日新聞熱度
  6. macro_loader.MacroLoader   — 宏觀快照（油/美債/VIX/金/美元）
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

_DATA_DIR = Path(__file__).parent / "data"
_CACHE_TTL = 3600  # 1 小時


def _load_json(filename: str) -> Any:
    path = _DATA_DIR / filename
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def _days_until(d: Optional[date], today: date) -> int:
    if d is None:
        return 9999
    return (d - today).days


def _time_window(days: int, windows: List[Dict]) -> Dict:
    for w in sorted(windows, key=lambda x: x.get("min_days", 0)):
        if w.get("min_days", 0) <= days <= w.get("max_days", 9999):
            return w
    return {"id": "beyond", "name": "超過觀察區間", "priority": 0}


# ── 事件類型 icon 對照 ──────────────────────────────────────────────────────

_EVENT_ICONS: Dict[str, str] = {
    "macro_inflation":       "📊",
    "central_bank":          "🏦",
    "taiwan_macro_industry": "🇹🇼",
    "ai_datacenter":         "🤖",
    "semiconductor":         "🔬",
    "advanced_packaging":    "💎",
    "leo_satellite":         "🛰️",
    "robotics":              "🦾",
    "geopolitical_risk":     "🌐",
    "energy_commodities":    "⚡",
    "ipo_capital_market":    "📈",
}

_DIRECTION_LABEL: Dict[str, str] = {
    "positive_watch": "🟢 正面觀察",
    "negative_watch": "🔴 風險注意",
    "mixed":          "🟡 混合影響",
    "watch_only":     "⚪ 觀察",
}


class RadarLoader:
    """情勢雷達資料載入器（可在 Streamlit session 內重用）"""

    def __init__(self):
        self._cache: Dict[str, Any] = {}
        # 延遲初始化重量級模組（避免循環 import）
        self._macro: Optional[Any] = None
        self._news: Optional[Any] = None

    # ── 快取輔助 ───────────────────────────────────────────────────────────

    def _hit(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry and (time.time() - entry["ts"]) < _CACHE_TTL:
            return entry["data"]
        return None

    def _put(self, key: str, data: Any) -> None:
        self._cache[key] = {"ts": time.time(), "data": data}

    # ── 模組延遲載入 ────────────────────────────────────────────────────────

    def _get_macro(self):
        if self._macro is None:
            from macro_loader import MacroLoader
            self._macro = MacroLoader()
        return self._macro

    def _get_news(self):
        if self._news is None:
            from news_analyzer import NewsAnalyzer
            self._news = NewsAnalyzer()
        return self._news

    # ── 公開 API ────────────────────────────────────────────────────────────

    def get_radar_snapshot(self) -> Dict[str, Any]:
        """
        一次性取得全部雷達資訊。
        回傳 {active_themes, upcoming_events, macro}。
        """
        key = "radar_snapshot"
        cached = self._hit(key)
        if cached is not None:
            return cached

        result = {
            "active_themes":    self.get_active_themes(),
            "upcoming_events":  self.get_upcoming_events(days=60),
            "macro":            self._get_macro_safe(),
        }
        self._put(key, result)
        return result

    def _get_macro_safe(self) -> Dict:
        try:
            return self._get_macro().get_snapshot()
        except Exception:
            return {}

    def get_upcoming_events(self, days: int = 60) -> List[Dict]:
        """
        從 data/future_events.json 讀取種子事件，
        計算距今天數，展開 event_type → 傳導規則 → 受影響供應鏈。
        只回傳 days 天內且 days_until >= 0 的事件，依 priority_score 排序。
        """
        key = f"upcoming_events:{days}"
        cached = self._hit(key)
        if cached is not None:
            return cached

        raw          = _load_json("future_events.json")
        rules_raw    = _load_json("event_to_supply_chain_rules.json")
        chains_raw   = _load_json("supply_chains.json")

        windows      = raw.get("time_windows", [])
        event_types  = {et["id"]: et for et in raw.get("event_types", [])}
        rules        = {r["id"]: r for r in rules_raw.get("rules", [])}
        chains       = {c["id"]: c for c in chains_raw.get("supply_chains", [])}
        today        = date.today()

        # 種子事件 + 週期性引擎自動生成的事件（後者避免種子過期造成事件雷達枯竭）
        all_events = list(raw.get("seed_events", [])) + self._generate_recurring_events(today, days)

        results: List[Dict] = []
        _seen = set()
        for ev in all_events:
            start = _parse_date(ev.get("start_date"))
            if start is None:
                continue
            d_until = _days_until(start, today)
            if d_until < 0 or d_until > days:
                continue
            # 去重（種子與週期生成可能重疊）：以 (標題, 日期) 為鍵
            _dk = (str(ev.get("title", "")), str(start))
            if _dk in _seen:
                continue
            _seen.add(_dk)

            et_id   = str(ev.get("event_type", ""))
            et_def  = event_types.get(et_id, {})
            icon    = _EVENT_ICONS.get(et_id, "📌")
            window  = _time_window(d_until, windows)
            status  = str(ev.get("status", "watch"))

            # 傳導規則展開
            affected_chains: List[Dict] = []
            directions: List[str] = []
            mechanisms: List[str] = []
            for rule_id in et_def.get("supply_chain_rule_ids", []):
                rule = rules.get(rule_id, {})
                if not rule:
                    continue
                directions.append(rule.get("direction", ""))
                mechanisms.append(rule.get("mechanism", ""))
                for chain_id in rule.get("chain_ids", []):
                    chain = chains.get(chain_id, {})
                    if chain and chain not in affected_chains:
                        affected_chains.append({
                            "id":   chain_id,
                            "name": chain.get("name", chain_id),
                        })

            # 優先度計分
            priority = window.get("priority", 0)
            if status == "official":
                priority += 2
            elif status == "scheduled":
                priority += 1

            # 主要影響方向（取第一個非空）
            primary_dir = next((d for d in directions if d), "watch_only")

            results.append({
                "id":              ev.get("id", ""),
                "title":           ev.get("title", ""),
                "event_type":      et_id,
                "event_type_name": et_def.get("name", et_id),
                "icon":            icon,
                "start_date":      str(start),
                "end_date":        str(_parse_date(ev.get("end_date")) or start),
                "days_until":      d_until,
                "time_window":     window,
                "status":          status,
                "source_name":     ev.get("source_name", ""),
                "source_url":      ev.get("source_url", ""),
                "watch_points":    ev.get("watch_points", []),
                "affected_chains": affected_chains,
                "direction":       primary_dir,
                "direction_label": _DIRECTION_LABEL.get(primary_dir, "⚪ 觀察"),
                "mechanism":       mechanisms[0] if mechanisms else "",
                "priority_score":  priority,
            })

        results.sort(key=lambda x: (-x["priority_score"], x["days_until"]))
        self._put(key, results)
        return results

    def _generate_recurring_events(self, today: date, days: int) -> List[Dict]:
        """
        依 data/recurring_event_templates.json 於執行時動態生成未來 `days` 天內的
        週期性事件（月營收公布、CPI、FOMC、台積電法說、SEMICON 等），避免種子過期。
        日期不確定者範本已標「推定」status，忠實傳遞、不假裝官方確認。
        """
        tpl = _load_json("recurring_event_templates.json")
        if not isinstance(tpl, dict):
            return []
        horizon = today + timedelta(days=days)
        out: List[Dict] = []

        # 每月固定日事件（如月營收次月 10 日、CPI 約當月中）
        for r in tpl.get("monthly", []):
            day = int(r.get("day", 10))
            y, m = today.year, today.month
            for _ in range((days // 28) + 2):
                try:
                    d = date(y, m, day)
                except ValueError:
                    d = None
                if d is not None and today <= d <= horizon:
                    out.append({
                        "id":          f"{r.get('id','recurring')}-{d.strftime('%Y%m')}",
                        "title":       r.get("title", ""),
                        "event_type":  r.get("event_type", ""),
                        "start_date":  str(d),
                        "status":      r.get("status", "推定"),
                        "source_name": r.get("source_name", ""),
                        "source_url":  r.get("source_url", ""),
                        "watch_points": r.get("watch_points", []),
                    })
                m += 1
                if m > 12:
                    m, y = 1, y + 1

        # 固定日期事件（FOMC / 法說 / 展會等，範本已標推定）
        for r in tpl.get("scheduled", []):
            d = _parse_date(r.get("date"))
            if d is not None and today <= d <= horizon:
                out.append({
                    "id":          r.get("id", "scheduled"),
                    "title":       r.get("title", ""),
                    "event_type":  r.get("event_type", ""),
                    "start_date":  str(d),
                    "status":      r.get("status", "推定"),
                    "source_name": r.get("source_name", ""),
                    "source_url":  r.get("source_url", ""),
                    "watch_points": r.get("watch_points", []),
                })
        return out

    def get_active_themes(self) -> List[Dict]:
        """
        結合 config.THEME_GRAPH 與近 3 日新聞熱度，
        回傳有佐證的主題卡片列表。
        """
        key = "active_themes"
        cached = self._hit(key)
        if cached is not None:
            return cached

        try:
            from config import THEME_GRAPH
        except ImportError:
            return []

        # 取近 3 日新聞主題熱度（key = theme 名稱, value = heat dict）
        news_heat: Dict[str, Dict] = {}
        try:
            heat_list = self._get_news().get_theme_heat(days=3)
            for h in heat_list:
                news_heat[h.get("theme", "")] = h
        except Exception:
            pass

        results: List[Dict] = []
        for theme_name, meta in THEME_GRAPH.items():
            # 從 price_theme key 找新聞熱度
            price_theme_key = meta.get("price_theme")
            heat_data       = news_heat.get(price_theme_key or "", {})
            heat_score      = heat_data.get("heat_score", 0)
            headlines       = heat_data.get("headlines", [])

            # 若無新聞熱度，嘗試關鍵字直接比對
            if heat_score == 0 and meta.get("keywords"):
                try:
                    all_heat = self._get_news().get_theme_heat(days=7)
                    for h in all_heat:
                        matched = any(
                            kw in " ".join(h.get("headlines", []))
                            for kw in meta["keywords"]
                        )
                        if matched and h.get("heat_score", 0) > heat_score:
                            heat_score = h["heat_score"]
                            headlines  = h.get("headlines", [])
                except Exception:
                    pass

            # 展開受益供應鏈群組
            beneficiary = meta.get("beneficiary_groups", [])

            results.append({
                "theme":       theme_name,
                "icon":        meta.get("icon", "📌"),
                "category":    meta.get("category", ""),
                "heat_score":  heat_score,
                "headlines":   headlines[:2],
                "keywords":    meta.get("keywords", [])[:5],
                "beneficiary": beneficiary[:4],
                "tickers":     meta.get("tickers", [])[:5],
                "supply_chain_ids": meta.get("supply_chain_ids", []),
            })

        # 依熱度排序，熱度 0 的放最後
        results.sort(key=lambda x: -x["heat_score"])
        self._put(key, results)
        return results

    def get_supply_chain_detail(self, chain_id: str) -> Dict:
        """從 data/supply_chains.json 讀取詳細供應鏈節點，供 drill-down 使用。"""
        raw    = _load_json("supply_chains.json")
        chains = {c["id"]: c for c in raw.get("supply_chains", [])}
        return chains.get(chain_id, {})

    def get_event_transmission(self, event_type_id: str) -> List[Dict]:
        """
        查詢特定事件類型對哪些供應鏈有影響（正/負/混合）。
        """
        raw    = _load_json("future_events.json")
        rules_raw = _load_json("event_to_supply_chain_rules.json")
        chains_raw = _load_json("supply_chains.json")

        et_map   = {et["id"]: et for et in raw.get("event_types", [])}
        rules    = {r["id"]: r for r in rules_raw.get("rules", [])}
        chains   = {c["id"]: c for c in chains_raw.get("supply_chains", [])}

        et_def   = et_map.get(event_type_id, {})
        results: List[Dict] = []
        for rule_id in et_def.get("supply_chain_rule_ids", []):
            rule = rules.get(rule_id, {})
            if not rule:
                continue
            affected = [
                {"id": cid, "name": chains.get(cid, {}).get("name", cid)}
                for cid in rule.get("chain_ids", [])
            ]
            results.append({
                "rule_id":   rule_id,
                "direction": rule.get("direction", ""),
                "mechanism": rule.get("mechanism", ""),
                "chains":    affected,
            })
        return results
