"""
備份還原服務：atomic 寫入 + schema 驗證。
負責集中管理 JSON 讀寫、備份/還原的驗證邏輯。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils import write_json


# ── Schema 定義 ─────────────────────────────────────────────────────────────

# 合法的台股/美股 ticker 格式
_TW_TICKER_RE = re.compile(r"^\d{4,6}[A-Z]?$")
_US_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")

_BACKUP_KEYS = ("portfolio", "watchlist", "notes", "snapshots")


def _is_valid_ticker(t: str) -> bool:
    return bool(_TW_TICKER_RE.match(str(t)) or _US_TICKER_RE.match(str(t)))


def _validate_watchlist(data: Any) -> Tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "watchlist 必須是 dict"
    invalid = [k for k in data if not _is_valid_ticker(k)]
    if invalid:
        return False, f"watchlist 包含不合法 ticker：{invalid[:5]}"
    return True, ""


def _validate_notes(data: Any) -> Tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "notes 必須是 dict"
    return True, ""


def _validate_portfolio(data: Any) -> Tuple[bool, str]:
    if not isinstance(data, (dict, list)):
        return False, "portfolio 必須是 dict 或 list"
    if isinstance(data, dict):
        invalid = [k for k in data if not _is_valid_ticker(k)]
        if invalid:
            return False, f"portfolio 包含不合法 ticker：{invalid[:5]}"
    return True, ""


def _validate_snapshots(data: Any) -> Tuple[bool, str]:
    if not isinstance(data, list):
        return False, "snapshots 必須是 list"
    if len(data) > 500:
        return False, f"snapshots 筆數過多（{len(data)}），可能是損壞資料"
    return True, ""


_VALIDATORS = {
    "watchlist": _validate_watchlist,
    "notes":     _validate_notes,
    "portfolio": _validate_portfolio,
    "snapshots": _validate_snapshots,
}


# ── 公開 API ────────────────────────────────────────────────────────────────

def validate_backup(data: Dict) -> Tuple[bool, List[str]]:
    """
    驗證備份 dict 的 schema。
    回傳 (is_valid, errors)。
    errors 為空 list 代表通過。
    """
    if not isinstance(data, dict):
        return False, ["備份檔頂層必須是 JSON object"]

    unknown = [k for k in data if k not in _BACKUP_KEYS]
    errors = []
    if unknown:
        errors.append(f"包含未知 key：{unknown}")

    for key, validator in _VALIDATORS.items():
        if key in data:
            ok, msg = validator(data[key])
            if not ok:
                errors.append(msg)

    return (len(errors) == 0), errors


def preview_backup(data: Dict) -> Dict[str, Any]:
    """
    產生備份內容的摘要預覽，供 UI 在還原前呈現給使用者確認。
    """
    preview: Dict[str, Any] = {}
    if "watchlist" in data:
        preview["追蹤清單"] = f"{len(data['watchlist'])} 檔"
    if "portfolio" in data:
        holdings = data["portfolio"]
        count = len(holdings) if isinstance(holdings, dict) else len(holdings)
        preview["持倉"] = f"{count} 筆"
    if "notes" in data:
        preview["筆記"] = f"{len(data['notes'])} 筆"
    if "snapshots" in data:
        preview["快照"] = f"{len(data['snapshots'])} 筆"
    return preview


def restore_backup(
    data: Dict,
    watchlist_file: Path,
    notes_file: Path,
    snapshot_file: Path,
) -> Tuple[bool, str]:
    """
    驗證通過後執行還原，atomic 寫入各 JSON 檔。
    回傳 (success, message)。
    不寫 portfolio（呼叫者需自行透過 Portfolio.save()）。
    """
    ok, errors = validate_backup(data)
    if not ok:
        return False, "驗證失敗：" + "；".join(errors)

    try:
        if "watchlist" in data:
            write_json(watchlist_file, data["watchlist"])
        if "notes" in data:
            write_json(notes_file, data["notes"])
        if "snapshots" in data:
            write_json(snapshot_file, data["snapshots"])
    except Exception as e:
        return False, f"寫入檔案失敗：{e}"

    return True, "還原成功"
