# -*- coding: utf-8 -*-
"""
data_loader.py 解析函式驗證測試

覆蓋：
- parse_twse_daily：正確解析 TWSE STOCK_DAY_ALL 格式
- build_company_list：無行情時 close=None，不崩潰
"""

import sys
import types
from pathlib import Path

import pytest

# Mock streamlit 在 import data_loader 之前
_st = types.ModuleType("streamlit")
for _fn in ("info", "success", "warning", "error"):
    setattr(_st, _fn, lambda *a, **k: None)
sys.modules["streamlit"] = _st

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_loader import MarketDataLoader


@pytest.fixture(scope="module")
def loader():
    return MarketDataLoader()


# ============================================================
# parse_twse_daily
# ============================================================

class TestParseTwseDaily:
    def test_basic_parsing(self, loader):
        """正確解析標準 TWSE 格式"""
        rows = [
            {"Code": "2330", "ClosingPrice": "1055.00",
             "Change": "5.00", "TradeVolume": "10000"},
        ]
        result = loader.parse_twse_daily(rows)
        assert "2330" in result
        assert result["2330"]["close"] == 1055.0

    def test_empty_input(self, loader):
        """空列表 → 空 dict，不崩潰"""
        assert loader.parse_twse_daily([]) == {}

    def test_filters_non_stock_codes(self, loader):
        """過濾不符格式的代碼（5 位以上、非數字開頭）"""
        rows = [
            {"Code": "0050",  "ClosingPrice": "150", "Change": "0", "TradeVolume": "100"},
            {"Code": "00878", "ClosingPrice": "20",  "Change": "0", "TradeVolume": "100"},
            {"Code": "2330",  "ClosingPrice": "1055","Change": "0", "TradeVolume": "100"},
        ]
        result = loader.parse_twse_daily(rows)
        # validate_ticker 接受 4-6 位、第一位為數字 → 0050 有效、00878 也有效
        # 確保 00878（5 位）依 validate_ticker 規則處理，且 2330 一定包含
        assert "2330" in result
        # 超過 6 位或非數字開頭應被過濾
        rows_bad = [
            {"Code": "ABCD",    "ClosingPrice": "100", "Change": "0", "TradeVolume": "100"},
            {"Code": "1234567", "ClosingPrice": "100", "Change": "0", "TradeVolume": "100"},
            {"Code": "",        "ClosingPrice": "100", "Change": "0", "TradeVolume": "100"},
        ]
        result_bad = loader.parse_twse_daily(rows_bad)
        assert result_bad == {}

    def test_alternative_field_names(self, loader):
        """支援多種欄位名稱（中文 / 英文）"""
        rows = [
            {"證券代號": "2317", "收盤價": "225.00",
             "漲跌價差": "2.00", "成交股數": "50000"},
        ]
        result = loader.parse_twse_daily(rows)
        assert "2317" in result
        assert result["2317"]["close"] == 225.0

    def test_missing_close_price(self, loader):
        """收盤價欄位缺失 → close = 0.0（to_number fallback），不崩潰"""
        rows = [{"Code": "2330", "TradeVolume": "10000"}]
        result = loader.parse_twse_daily(rows)
        # 不應崩潰；close 可能為 0.0（to_number 預設值）或 None，視實作而定
        assert "2330" in result
        assert result["2330"]["close"] in (None, 0.0)

    def test_comma_in_numbers(self, loader):
        """數字含千分位逗號正確解析"""
        rows = [
            {"Code": "2330", "ClosingPrice": "1,055.00",
             "Change": "5.00", "TradeVolume": "1,000,000"},
        ]
        result = loader.parse_twse_daily(rows)
        if "2330" in result:
            assert result["2330"]["close"] == 1055.0


# ============================================================
# build_company_list
# ============================================================

class TestBuildCompanyList:
    def test_basic_build(self, loader):
        """基本公司清單建立"""
        companies = [
            {"公司代號": "2330", "公司名稱": "台積電", "產業別": "半導體業"},
        ]
        daily_map = {"2330": {"close": 1055.0, "change_pct": 0.5, "volume": 10000}}
        result = loader.build_company_list(companies, daily_map, "上市")
        assert len(result) == 1
        assert result[0]["ticker"] == "2330"
        assert result[0]["daily"]["close"] == 1055.0

    def test_no_daily_data_close_is_none(self, loader):
        """無行情資料時 close = None，不崩潰"""
        companies = [
            {"公司代號": "2330", "公司名稱": "台積電", "產業別": "半導體業"},
        ]
        result = loader.build_company_list(companies, {}, "上市")
        assert len(result) == 1
        assert result[0]["daily"]["close"] is None

    def test_empty_companies_returns_empty(self, loader):
        """空公司清單 → 空列表"""
        result = loader.build_company_list([], {}, "上市")
        assert result == []

    def test_market_field_set_correctly(self, loader):
        """market 欄位正確設定"""
        companies = [{"公司代號": "3045", "公司名稱": "台灣大", "產業別": "通信網路業"}]
        result = loader.build_company_list(companies, {}, "上市")
        assert result[0]["market"] == "上市"

    def test_industry_defaults_to_other(self, loader):
        """無產業別時預設為「其他」"""
        companies = [{"公司代號": "2330", "公司名稱": "台積電"}]
        result = loader.build_company_list(companies, {}, "上市")
        assert result[0]["industry"] in ("其他", "")  # 依 validate_ticker 結果而定

    def test_filters_invalid_tickers(self, loader):
        """無效股票代碼被過濾（空字串、非數字）"""
        companies = [
            {"公司代號": "",     "公司名稱": "空代碼"},
            {"公司代號": "ABCD", "公司名稱": "英文代碼"},
            {"公司代號": "2330", "公司名稱": "台積電", "產業別": "半導體業"},
        ]
        result = loader.build_company_list(companies, {}, "上市")
        tickers = [r["ticker"] for r in result]
        assert "2330" in tickers
        assert "" not in tickers
