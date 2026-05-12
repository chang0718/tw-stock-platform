"""
台股盤後量化分析平台 - 資料載入模組
負責從各種來源載入市場資料
"""

import time
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

from config import API_ENDPOINTS, CACHE_FILE, FALLBACK_DATA, HTTP_CONFIG
from utils import (
    get_retry_session,
    read_json,
    write_json,
    to_number,
    validate_ticker,
    industry_group,
)


class MarketDataLoader:
    """
    市場資料載入器
    整合TWSE、TPEx等多個資料來源
    """
    
    def __init__(self):
        """初始化載入器"""
        self.session = get_retry_session()
        self.cache = read_json(CACHE_FILE, {})
        self.cache_expiry = 3600  # 快取1小時
    
    def is_cache_valid(self, key: str) -> bool:
        """
        檢查快取是否有效
        
        Args:
            key: 快取鍵
        
        Returns:
            是否有效
        """
        if key not in self.cache:
            return False
        
        cache_time = self.cache[key].get("timestamp", 0)
        return (time.time() - cache_time) < self.cache_expiry
    
    def save_cache(self, key: str, data: any):
        """
        保存快取
        
        Args:
            key: 快取鍵
            data: 資料
        """
        self.cache[key] = {
            "timestamp": time.time(),
            "data": data,
        }
        write_json(CACHE_FILE, self.cache)
    
    def fetch_twse_companies(self) -> List[Dict]:
        """
        載入上市公司清單
        
        Returns:
            公司列表
        """
        try:
            response = self.session.get(
                API_ENDPOINTS["twse_company"],
                timeout=HTTP_CONFIG["timeout"]
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            st.warning(f"⚠️ 無法載入上市公司清單: {e}")
            return []
    
    def fetch_twse_daily(self) -> List[Dict]:
        """
        載入上市盤後行情
        
        Returns:
            行情列表
        """
        try:
            response = self.session.get(
                API_ENDPOINTS["twse_daily"],
                timeout=HTTP_CONFIG["timeout"]
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            st.warning(f"⚠️ 無法載入上市盤後行情: {e}")
            return []
    
    def fetch_tpex_companies(self) -> List[Dict]:
        """
        載入上櫃公司清單
        
        Returns:
            公司列表
        """
        try:
            response = self.session.get(
                API_ENDPOINTS["tpex_company"],
                timeout=HTTP_CONFIG["timeout"]
            )
            response.raise_for_status()
            data = response.json()
            
            # TPEx API 格式轉換為標準格式
            companies = []
            for item in data:
                companies.append({
                    "公司代號": item.get("SecuritiesCompanyCode", ""),
                    "公司名稱": item.get("CompanyName", ""),
                    "產業別": item.get("IndustryCategory", ""),
                })
            
            return companies
        except Exception as e:
            st.warning(f"⚠️ 無法載入上櫃公司清單: {e}")
            return []
    
    def fetch_tpex_daily(self) -> Dict:
        """
        載入上櫃盤後行情
        
        Returns:
            股票代碼到行情的對照表
        """
        try:
            from datetime import datetime
            
            # TPEx的API需要日期參數
            today = datetime.now().strftime("%Y%m%d")
            params = {
                "response": "json",
                "date": today,
            }
            
            response = self.session.get(
                API_ENDPOINTS["tpex_daily"],
                params=params,
                timeout=HTTP_CONFIG["timeout"]
            )
            response.raise_for_status()
            
            data = response.json()
            daily_map = {}
            
            # 解析TPEx格式
            if "data" in data:
                for row in data["data"]:
                    if len(row) >= 3:
                        ticker = str(row[0]).strip()
                        close = to_number(row[2])
                        change = to_number(row[3]) if len(row) > 3 else 0
                        volume = to_number(row[7]) if len(row) > 7 else 0
                        
                        daily_map[ticker] = {
                            "close": close,
                            "change": change,
                            "volume": volume,
                        }
            
            return daily_map
        except Exception as e:
            st.warning(f"⚠️ 無法載入上櫃盤後行情: {e}")
            return {}
    
    def parse_twse_daily(self, daily_rows: List[Dict]) -> Dict:
        """
        解析上市行情資料
        
        Args:
            daily_rows: 原始行情資料
        
        Returns:
            股票代碼到行情的對照表
        """
        daily_map = {}
        
        for row in daily_rows:
            # 支援多種欄位名稱
            ticker = str(
                row.get("Code") or
                row.get("證券代號") or
                row.get("股票代號") or
                row.get("有價證券代號") or
                ""
            ).strip()
            
            if not ticker or not validate_ticker(ticker):
                continue
            
            close = to_number(
                row.get("ClosingPrice") or
                row.get("收盤價") or
                row.get("Close") or
                row.get("收盤價(元)")
            )
            
            change = to_number(
                row.get("Change") or
                row.get("漲跌價差") or
                row.get("漲跌")
            )
            
            volume = to_number(
                row.get("TradeVolume") or
                row.get("成交股數") or
                row.get("Volume") or
                row.get("成交量")
            )
            
            # 計算漲跌幅
            prev_close = max(1, close - change)
            change_pct = round(change / prev_close * 100, 2) if close else 0
            
            daily_map[ticker] = {
                "close": close,
                "change_pct": change_pct,
                "volume": int(volume),
            }
        
        return daily_map
    
    def build_company_list(
        self,
        companies: List[Dict],
        daily_map: Dict,
        market: str
    ) -> List[Dict]:
        """
        建立公司列表
        
        Args:
            companies: 公司基本資料
            daily_map: 行情資料對照表
            market: 市場類別 (上市/上櫃)
        
        Returns:
            標準化的公司列表
        """
        result = []
        
        for row in companies:
            ticker = str(
                row.get("公司代號") or
                row.get("Code") or
                row.get("ticker") or
                ""
            ).strip()
            
            if not ticker or not validate_ticker(ticker):
                continue
            
            name = str(
                row.get("公司名稱") or
                row.get("Name") or
                row.get("name") or
                ""
            ).strip()
            
            industry = str(
                row.get("產業別") or
                row.get("Industry") or
                row.get("industry") or
                "其他"
            ).strip()
            
            # 取得行情資料，無資料時保留 None，不填假值
            daily = daily_map.get(ticker, {
                "close": None,
                "change_pct": None,
                "volume": None,
            })
            
            result.append({
                "ticker": ticker,
                "name": name,
                "industry": industry,
                "group": industry_group(industry),
                "market": market,
                "daily": daily,
            })
        
        return result
    
    def load_fallback_data(self) -> pd.DataFrame:
        """
        載入備用資料(當所有API都失敗時)
        
        Returns:
            備用資料DataFrame
        """
        companies = []
        
        for ticker, name, industry, market, close in FALLBACK_DATA:
            companies.append({
                "ticker": ticker,
                "name": name,
                "industry": industry,
                "group": industry_group(industry),
                "market": market,
                "daily": {
                    "close": close,
                    "change_pct": None,
                    "volume": None,
                },
            })
        
        return pd.DataFrame(companies)
    
    def load_all_market_data(self, include_tpex: bool = True) -> pd.DataFrame:
        """
        載入完整市場資料
        
        Args:
            include_tpex: 是否包含上櫃
        
        Returns:
            市場資料DataFrame
        """
        companies = []
        
        # === 載入上市資料 ===
        st.info("📥 載入上市公司資料...")
        twse_companies = self.fetch_twse_companies()
        twse_daily = self.fetch_twse_daily()
        
        if twse_companies and twse_daily:
            daily_map = self.parse_twse_daily(twse_daily)
            twse_list = self.build_company_list(
                twse_companies,
                daily_map,
                "上市"
            )
            companies.extend(twse_list)
            st.success(f"✅ 已載入 {len(twse_list)} 檔上市股票")
        else:
            st.warning("⚠️ 上市資料載入失敗")
        
        # === 載入上櫃資料 ===
        if include_tpex:
            st.info("📥 載入上櫃公司資料...")
            tpex_companies = self.fetch_tpex_companies()
            tpex_daily = self.fetch_tpex_daily()
            
            if tpex_companies:
                tpex_list = self.build_company_list(
                    tpex_companies,
                    tpex_daily,
                    "上櫃"
                )
                companies.extend(tpex_list)
                st.success(f"✅ 已載入 {len(tpex_list)} 檔上櫃股票")
            else:
                st.warning("⚠️ 上櫃資料載入失敗")
        
        # === 檢查結果 ===
        if not companies:
            st.error("❌ 所有資料來源都失敗,使用備用資料")
            return self.load_fallback_data()
        
        df = pd.DataFrame(companies)
        
        # 移除重複
        df = df.drop_duplicates(subset=['ticker'], keep='first')
        
        st.success(f"🎉 總共載入 {len(df)} 檔股票")
        
        return df
    
    def load_from_csv(self, uploaded_file) -> Optional[pd.DataFrame]:
        """
        從CSV檔案載入資料
        
        Args:
            uploaded_file: Streamlit上傳的檔案物件
        
        Returns:
            DataFrame或None
        """
        try:
            csv_df = pd.read_csv(uploaded_file)
            required = {"ticker", "name", "industry", "close"}
            
            if not required.issubset(csv_df.columns):
                st.error("❌ CSV需包含欄位: ticker, name, industry, close")
                return None
            
            companies = []
            
            for _, row in csv_df.iterrows():
                ticker = str(row["ticker"]).strip()
                
                if not validate_ticker(ticker):
                    continue
                
                companies.append({
                    "ticker": ticker,
                    "name": str(row["name"]),
                    "industry": str(row["industry"]),
                    "group": industry_group(str(row["industry"])),
                    "market": row.get("market", "自訂"),
                    "daily": {
                        "close": to_number(row["close"]),
                        "change_pct": to_number(row.get("change_pct", 0)),
                        "volume": int(to_number(row.get("volume", 1000))),
                    },
                })
            
            if not companies:
                st.error("❌ CSV沒有有效資料")
                return None
            
            df = pd.DataFrame(companies)
            st.success(f"✅ 已從CSV匯入 {len(df)} 檔股票")
            
            return df
            
        except Exception as e:
            st.error(f"❌ CSV載入失敗: {e}")
            return None
