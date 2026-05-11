# financials.py
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import List, Optional
import numpy as np
import pandas as pd
import requests


REQUEST_TIMEOUT = 20

# TWSE OpenAPI：上市公司綜合損益表 / 資產負債表
# suffix 說明：
# basi 一般業、bd 銀行業、fh 金控業、ins 保險業、mim 異業、ci 證券期貨業
TWSE_INCOME_ENDPOINTS = [
    "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_basi",
    "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_bd",
    "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_fh",
    "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ins",
    "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_mim",
    "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci",
]

TWSE_BALANCE_ENDPOINTS = [
    "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_basi",
    "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_bd",
    "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_fh",
    "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ins",
    "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_mim",
    "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci",
]

# TPEx endpoint 名稱可能隨官方調整，程式採候選清單，抓不到就回傳空表，不補假資料。
TPEX_INCOME_ENDPOINTS = [
    "https://www.tpex.org.tw/openapi/v1/t187ap06_O_basi",
    "https://www.tpex.org.tw/openapi/v1/t187ap06_O_bd",
    "https://www.tpex.org.tw/openapi/v1/t187ap06_O_fh",
    "https://www.tpex.org.tw/openapi/v1/t187ap06_O_ins",
    "https://www.tpex.org.tw/openapi/v1/t187ap06_O_mim",
    "https://www.tpex.org.tw/openapi/v1/t187ap06_O_ci",
]

TPEX_BALANCE_ENDPOINTS = [
    "https://www.tpex.org.tw/openapi/v1/t187ap07_O_basi",
    "https://www.tpex.org.tw/openapi/v1/t187ap07_O_bd",
    "https://www.tpex.org.tw/openapi/v1/t187ap07_O_fh",
    "https://www.tpex.org.tw/openapi/v1/t187ap07_O_ins",
    "https://www.tpex.org.tw/openapi/v1/t187ap07_O_mim",
    "https://www.tpex.org.tw/openapi/v1/t187ap07_O_ci",
]


def to_float(value) -> float:
    if value is None:
        return np.nan

    text = str(value).strip()
    if text in {"", "-", "--", "X", "nan", "None", "不適用"}:
        return np.nan

    text = (
        text.replace(",", "")
        .replace("+", "")
        .replace("%", "")
        .replace(" ", "")
    )

    # 會計資料有時用括號表示負數
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]

    try:
        return float(text)
    except Exception:
        return np.nan


def first_existing(row: pd.Series, candidates: List[str]):
    for col in candidates:
        if col in row.index:
            return row[col]
    return None


def safe_get_json(url: str) -> Optional[pd.DataFrame]:
    try:
        res = requests.get(url, timeout=REQUEST_TIMEOUT)
        res.raise_for_status()
        data = res.json()
        df = pd.DataFrame(data)
        return df if not df.empty else None
    except Exception:
        return None


def fetch_many_json(endpoints: List[str]) -> pd.DataFrame:
    frames = []

    for url in endpoints:
        df = safe_get_json(url)
        if df is not None and not df.empty:
            df["_source_url"] = url
            frames.append(df)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def normalize_income(raw: pd.DataFrame, market: str) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()

    records = []

    for _, row in raw.iterrows():
        ticker = str(first_existing(row, ["公司代號", "Code", "CompanyCode", "股票代號"]) or "").strip()
        if not ticker:
            continue

        name = first_existing(row, ["公司名稱", "Name", "CompanyName"])
        year = first_existing(row, ["年度", "Year"])
        quarter = first_existing(row, ["季別", "Season", "季度"])
        report_date = first_existing(row, ["出表日期", "公告日期", "PublishDate"])

        revenue = to_float(first_existing(row, [
            "營業收入",
            "收益",
            "淨收益",
            "收入",
            "營業收益",
        ]))

        operating_cost = to_float(first_existing(row, [
            "營業成本",
            "營業費用及損失",
        ]))

        gross_profit = to_float(first_existing(row, [
            "營業毛利（毛損）",
            "營業毛利",
            "營業毛利毛損",
        ]))

        operating_income = to_float(first_existing(row, [
            "營業利益（損失）",
            "營業利益",
            "營業淨利",
            "繼續營業單位稅前純益（純損）",
        ]))

        net_income = to_float(first_existing(row, [
            "本期淨利（淨損）",
            "本期淨利",
            "本期稅後淨利（淨損）",
            "繼續營業單位本期純益（純損）",
            "淨利（淨損）歸屬於母公司業主",
        ]))

        eps = to_float(first_existing(row, [
            "基本每股盈餘（元）",
            "基本每股盈餘",
            "每股盈餘",
            "EPS",
        ]))

        if pd.isna(gross_profit) and not pd.isna(revenue) and not pd.isna(operating_cost):
            gross_profit = revenue - operating_cost

        gross_margin = np.nan
        operating_margin = np.nan
        net_margin = np.nan

        if not pd.isna(revenue) and revenue != 0:
            if not pd.isna(gross_profit):
                gross_margin = round(gross_profit / revenue * 100, 2)
            if not pd.isna(operating_income):
                operating_margin = round(operating_income / revenue * 100, 2)
            if not pd.isna(net_income):
                net_margin = round(net_income / revenue * 100, 2)

        records.append({
            "股票代號": ticker,
            "公司名稱_財報": name,
            "市場_財報": market,
            "年度": year,
            "季別": quarter,
            "財報出表日期": report_date,
            "營業收入_財報": revenue,
            "營業成本": operating_cost,
            "營業毛利": gross_profit,
            "營業利益": operating_income,
            "本期淨利": net_income,
            "EPS": eps,
            "毛利率%": gross_margin,
            "營益率%": operating_margin,
            "淨利率%": net_margin,
            "損益表來源": first_existing(row, ["_source_url"]) or "",
        })

    return pd.DataFrame(records)


def normalize_balance(raw: pd.DataFrame, market: str) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()

    records = []

    for _, row in raw.iterrows():
        ticker = str(first_existing(row, ["公司代號", "Code", "CompanyCode", "股票代號"]) or "").strip()
        if not ticker:
            continue

        name = first_existing(row, ["公司名稱", "Name", "CompanyName"])
        year = first_existing(row, ["年度", "Year"])
        quarter = first_existing(row, ["季別", "Season", "季度"])
        report_date = first_existing(row, ["出表日期", "公告日期", "PublishDate"])

        total_assets = to_float(first_existing(row, [
            "資產總額",
            "資產總計",
            "資產合計",
        ]))

        total_liabilities = to_float(first_existing(row, [
            "負債總額",
            "負債總計",
            "負債合計",
        ]))

        total_equity = to_float(first_existing(row, [
            "權益總額",
            "權益總計",
            "權益合計",
            "歸屬於母公司業主之權益合計",
        ]))

        current_assets = to_float(first_existing(row, ["流動資產"]))
        current_liabilities = to_float(first_existing(row, ["流動負債"]))

        debt_ratio = np.nan
        if not pd.isna(total_assets) and total_assets != 0 and not pd.isna(total_liabilities):
            debt_ratio = round(total_liabilities / total_assets * 100, 2)

        equity_ratio = np.nan
        if not pd.isna(total_assets) and total_assets != 0 and not pd.isna(total_equity):
            equity_ratio = round(total_equity / total_assets * 100, 2)

        current_ratio = np.nan
        if not pd.isna(current_liabilities) and current_liabilities != 0 and not pd.isna(current_assets):
            current_ratio = round(current_assets / current_liabilities * 100, 2)

        records.append({
            "股票代號": ticker,
            "公司名稱_資產負債": name,
            "市場_資產負債": market,
            "年度_資產負債": year,
            "季別_資產負債": quarter,
            "資產負債表出表日期": report_date,
            "資產總額": total_assets,
            "負債總額": total_liabilities,
            "權益總額": total_equity,
            "流動資產": current_assets,
            "流動負債": current_liabilities,
            "負債比%": debt_ratio,
            "權益比%": equity_ratio,
            "流動比率%": current_ratio,
            "資產負債表來源": first_existing(row, ["_source_url"]) or "",
        })

    return pd.DataFrame(records)


def score_from_range(value: float, low: float, high: float, reverse: bool = False) -> float:
    if pd.isna(value):
        return np.nan
    value = max(low, min(high, value))
    score = (value - low) / (high - low) * 100
    return round(100 - score if reverse else score, 1)


def fetch_financials() -> pd.DataFrame:
    """
    回傳全市場可取得之財報摘要。
    抓不到資料就回傳空表，不補假資料。
    """
    twse_income_raw = fetch_many_json(TWSE_INCOME_ENDPOINTS)
    tpex_income_raw = fetch_many_json(TPEX_INCOME_ENDPOINTS)
    twse_balance_raw = fetch_many_json(TWSE_BALANCE_ENDPOINTS)
    tpex_balance_raw = fetch_many_json(TPEX_BALANCE_ENDPOINTS)

    income_frames = []
    balance_frames = []

    if not twse_income_raw.empty:
        income_frames.append(normalize_income(twse_income_raw, "上市"))
    if not tpex_income_raw.empty:
        income_frames.append(normalize_income(tpex_income_raw, "上櫃"))

    if not twse_balance_raw.empty:
        balance_frames.append(normalize_balance(twse_balance_raw, "上市"))
    if not tpex_balance_raw.empty:
        balance_frames.append(normalize_balance(tpex_balance_raw, "上櫃"))

    income = pd.concat(income_frames, ignore_index=True) if income_frames else pd.DataFrame()
    balance = pd.concat(balance_frames, ignore_index=True) if balance_frames else pd.DataFrame()

    if income.empty and balance.empty:
        return pd.DataFrame()

    if income.empty:
        out = balance.copy()
    elif balance.empty:
        out = income.copy()
    else:
        out = income.merge(balance, on="股票代號", how="outer")

    out["公司名稱_財報整合"] = out.get("公司名稱_財報", pd.Series(dtype=object)).combine_first(
        out.get("公司名稱_資產負債", pd.Series(dtype=object))
    )

    out["市場_財報整合"] = out.get("市場_財報", pd.Series(dtype=object)).combine_first(
        out.get("市場_資產負債", pd.Series(dtype=object))
    )

    # 財報品質分數：只用真實財報欄位
    out["毛利率分數"] = out["毛利率%"].apply(lambda x: score_from_range(x, 0, 60))
    out["營益率分數"] = out["營益率%"].apply(lambda x: score_from_range(x, -10, 40))
    out["淨利率分數"] = out["淨利率%"].apply(lambda x: score_from_range(x, -10, 35))
    out["負債比分數"] = out["負債比%"].apply(lambda x: score_from_range(x, 20, 90, reverse=True))

    out["品質分數"] = out.apply(
        lambda r: np.nan
        if any(pd.isna(r.get(c, np.nan)) for c in ["毛利率分數", "營益率分數", "淨利率分數", "負債比分數"])
        else round(
            r["毛利率分數"] * 0.30
            + r["營益率分數"] * 0.30
            + r["淨利率分數"] * 0.20
            + r["負債比分數"] * 0.20,
            1,
        ),
        axis=1,
    )

    return out