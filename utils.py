"""
台股盤後量化分析平台 - 工具函數
包含通用的輔助函數
"""

import json
import math
import os
from pathlib import Path
from functools import lru_cache
from typing import Any, Dict

import urllib3
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from config import HTTP_CONFIG, INDUSTRY_MAPPING, TWSE_INDUSTRY_CODES

# 台灣政府 API（TWSE/TPEx）SSL 憑證缺少 Subject Key Identifier，
# Python 3.12+ 拒絕連線；使用 verify=False 並抑制警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ============================================================
# HTTP 工具
# ============================================================

def get_retry_session(
    retries: int = HTTP_CONFIG["retries"],
    backoff_factor: float = HTTP_CONFIG["backoff_factor"],
    status_forcelist: tuple = HTTP_CONFIG["status_forcelist"],
) -> requests.Session:
    """建立具有重試機制的 HTTP session（停用 SSL 驗證以相容台灣政府 API）"""
    session = requests.Session()
    session.verify = False  # TWSE/TPEx 憑證缺少 Subject Key Identifier
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


# ============================================================
# JSON 檔案操作
# ============================================================

def read_json(path: Path, default: Any = None) -> Any:
    """
    安全讀取JSON檔案
    
    Args:
        path: 檔案路徑
        default: 讀取失敗時的預設值
    
    Returns:
        JSON內容或預設值
    """
    try:
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"⚠️ 讀取 {path.name} 失敗: {e}")
    return default if default is not None else {}


def write_json(path: Path, data: Any) -> bool:
    """
    Atomic JSON 寫入：先寫 .tmp 再 os.replace()，避免寫到一半時平台重載造成資料損壞。
    tmp 檔與目標在同目錄，確保 os.replace() 是同磁碟 rename（原子操作）。
    """
    path = Path(path)
    tmp = path.parent / (path.stem + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"❌ 寫入 {path.name} 失敗: {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


# ============================================================
# 資料轉換
# ============================================================

def to_number(value: Any, fallback: float = 0.0) -> float:
    """
    安全轉換為數字
    
    Args:
        value: 要轉換的值
        fallback: 轉換失敗時的預設值
    
    Returns:
        轉換後的數字
    """
    try:
        if value is None or pd.isna(value):
            return fallback
        # 移除千分位逗號
        return float(str(value).replace(",", ""))
    except Exception:
        return fallback


def clamp(value: float, low: float = 1, high: float = 99) -> int:
    """
    限制數值範圍並取整
    
    Args:
        value: 輸入值
        low: 下限
        high: 上限
    
    Returns:
        限制後的整數值
    """
    try:
        value = int(round(value))
    except Exception:
        value = int(low)
    return max(low, min(high, value))


# ============================================================
# 數學函數
# ============================================================

def sigmoid(x: float) -> float:
    """
    Sigmoid函數 (用於機率轉換)
    
    Args:
        x: 輸入值
    
    Returns:
        0-1之間的數值
    """
    # 限制範圍避免溢位
    x = max(-100, min(100, x))
    return 1 / (1 + math.exp(-x))


@lru_cache(maxsize=1000)
def stable_seed(*parts) -> int:
    """
    產生穩定的種子值(用於一致性的模擬數據)
    使用LRU快取避免重複計算
    
    Args:
        *parts: 任意數量的參數
    
    Returns:
        種子值
    """
    text = "-".join(map(str, parts))
    return sum(ord(ch) for ch in text)


# ============================================================
# 產業分類
# ============================================================

def industry_group(industry: str, ticker: str = "", name: str = "") -> str:
    """
    將產業名稱映射到標準分類

    Args:
        industry: 原始產業名稱
        ticker:   股票代號（選填，用於 ETF 判斷）
        name:     股票名稱（選填，用於 ETF 判斷）

    Returns:
        標準產業分類
    """
    industry = str(industry or "").strip()
    ticker   = str(ticker or "").strip()
    name     = str(name or "").strip()

    # ETF 判斷（代號以 00 開頭，或名稱/產業包含 ETF）
    if (
        ticker.startswith("00")
        or "ETF" in name.upper()
        or "ETF" in industry.upper()
    ):
        return "ETF"

    # 數字代碼直接轉換
    code = industry.zfill(2)
    if code in TWSE_INDUSTRY_CODES:
        industry = TWSE_INDUSTRY_CODES[code]

    # 遍歷映射表
    for group, keywords in INDUSTRY_MAPPING.items():
        if any(kw in industry for kw in keywords):
            return group

    # 未分類
    if not industry or industry in ["nan", "None", ""]:
        return "未分類"

    # 保持原產業名稱
    return industry


# ============================================================
# 資料驗證
# ============================================================

def validate_ticker(ticker: str) -> bool:
    """
    驗證股票代碼格式
    
    Args:
        ticker: 股票代碼
    
    Returns:
        是否有效
    """
    if not ticker:
        return False
    
    ticker = str(ticker).strip()
    
    # 基本格式檢查: 4-6位數字或數字+字母
    if len(ticker) < 4 or len(ticker) > 6:
        return False
    
    # 第一個字元必須是數字
    if not ticker[0].isdigit():
        return False
    
    return True


def validate_dataframe(df: pd.DataFrame, required_columns: list) -> bool:
    """
    驗證DataFrame是否包含必要欄位
    
    Args:
        df: DataFrame
        required_columns: 必要欄位列表
    
    Returns:
        是否通過驗證
    """
    if df is None or df.empty:
        return False
    
    missing = set(required_columns) - set(df.columns)
    
    if missing:
        print(f"❌ 缺少欄位: {missing}")
        return False
    
    return True


# ============================================================
# 格式化輸出
# ============================================================

def format_percentage(value: float, decimals: int = 1) -> str:
    """
    格式化百分比
    
    Args:
        value: 數值
        decimals: 小數位數
    
    Returns:
        格式化字串
    """
    return f"{value:.{decimals}f}%"


def format_number(value: float, decimals: int = 2) -> str:
    """
    格式化數字(加千分位)
    
    Args:
        value: 數值
        decimals: 小數位數
    
    Returns:
        格式化字串
    """
    return f"{value:,.{decimals}f}"


def format_change(value: float) -> str:
    """
    格式化漲跌幅(帶正負號和顏色)
    
    Args:
        value: 漲跌幅
    
    Returns:
        格式化字串
    """
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


# ============================================================
# 日期處理
# ============================================================

def get_trading_days_ago(days: int) -> str:
    """
    獲取N個交易日前的日期(簡化版,實際應考慮假日)
    
    Args:
        days: 交易日數
    
    Returns:
        日期字串 (YYYY-MM-DD)
    """
    from datetime import datetime, timedelta
    
    # 簡化: 假設每週5個交易日
    calendar_days = int(days * 1.4)  # 考慮週末
    target_date = datetime.now() - timedelta(days=calendar_days)
    
    return target_date.strftime("%Y-%m-%d")


# ============================================================
# 統計函數
# ============================================================

def calculate_percentile(values: list, percentile: float) -> float:
    """
    計算百分位數
    
    Args:
        values: 數值列表
        percentile: 百分位 (0-100)
    
    Returns:
        百分位數值
    """
    if not values:
        return 0.0
    
    import numpy as np
    return np.percentile(values, percentile)


def calculate_zscore(value: float, mean: float, std: float) -> float:
    """
    計算Z-score
    
    Args:
        value: 觀測值
        mean: 平均值
        std: 標準差
    
    Returns:
        Z-score
    """
    if std == 0:
        return 0.0
    
    return (value - mean) / std


# ============================================================
# 字典操作
# ============================================================

def merge_dicts(*dicts: Dict) -> Dict:
    """
    合併多個字典
    
    Args:
        *dicts: 要合併的字典
    
    Returns:
        合併後的字典
    """
    result = {}
    for d in dicts:
        if d:
            result.update(d)
    return result


def safe_get(data: Dict, key: str, default: Any = None) -> Any:
    """
    安全取得字典值
    
    Args:
        data: 字典
        key: 鍵
        default: 預設值
    
    Returns:
        值或預設值
    """
    try:
        return data.get(key, default)
    except Exception:
        return default
