# -*- coding: utf-8 -*-
"""
Simulate Streamlit Cloud startup: no secrets, no network APIs.
Verifies the app won't crash at initialization.
"""
import sys
import types
import pandas as pd

# --- Mock streamlit ---
_st = types.ModuleType("streamlit")
for _fn in ("info", "success", "warning", "error", "spinner",
            "set_page_config", "title", "caption", "stop", "rerun",
            "markdown", "button", "text_input", "container", "write"):
    setattr(_st, _fn, lambda *a, **kw: None)

class SessionState(dict):
    def __getattr__(self, k):
        return self.get(k)
    def __setattr__(self, k, v):
        self[k] = v

_st.session_state = SessionState()

class FakeSecrets:
    def get(self, k, d=None):
        return d
    def __getitem__(self, k):
        raise KeyError(k)

_st.secrets = FakeSecrets()
_st.cache_data = lambda *a, **kw: (lambda f: f)
sys.modules["streamlit"] = _st
# ---------------------

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from config import DEFAULT_WEIGHTS, NOTES_FILE, SNAPSHOT_FILE, WATCHLIST_FILE, WEIGHTS_FILE
from utils import read_json
from portfolio import Portfolio
from data_loader import MarketDataLoader
from unittest.mock import patch

# 1. initialize_session_state
defaults = {
    "universe_df":        pd.DataFrame(),
    "weights":            read_json(WEIGHTS_FILE, DEFAULT_WEIGHTS),
    "notes":              read_json(NOTES_FILE, {}),
    "last_update":        None,
    "data_date":          "",
    "snapshots":          read_json(SNAPSHOT_FILE, []),
    "watchlist":          read_json(WATCHLIST_FILE, {}),
    "watchlist_data":     {},
    "institutional_data": {"inst": {}, "margin": {}},
    "stock_fundamentals": {},
    "model_df_cached":    pd.DataFrame(),
    "model_cache_key":    "",
    "finmind_token":      "",
    "tech_data":          {},
    "us_market_data":     {},
    "us_market_ts":       0,
    "portfolio":          Portfolio(),
}
for k, v in defaults.items():
    if k not in _st.session_state:
        _st.session_state[k] = v

# secrets auto-load (no secrets configured)
if not _st.session_state.get("finmind_token"):
    try:
        secret_token = _st.secrets.get("finmind", {}).get("token", "")
        if secret_token and secret_token != "your_finmind_token_here":
            _st.session_state.finmind_token = secret_token
    except Exception:
        pass

print("initialize_session_state: OK")

# 2. load_all_market_data - all APIs fail → fallback
loader = MarketDataLoader()
with patch.object(loader, "fetch_twse_companies", return_value=[]), \
     patch.object(loader, "fetch_twse_daily",     return_value=[]), \
     patch.object(loader, "fetch_tpex_companies", return_value=[]), \
     patch.object(loader, "fetch_tpex_daily",     return_value={}):

    df, data_date = loader.load_all_market_data()

assert isinstance(df, pd.DataFrame), "df must be DataFrame"
assert isinstance(data_date, str),   "data_date must be str"
assert not df.empty, "fallback df should not be empty"
print(f"load_all_market_data (all-fail): OK — {len(df)} rows, data_date={repr(data_date)}")

# 3. load_all_market_data - only TWSE succeeds
twse_companies = [
    {"公司代號": "2330", "公司名稱": "台積電", "產業別": "半導體業"},
    {"公司代號": "2317", "公司名稱": "鴻海",   "產業別": "其他電子業"},
]
with patch.object(loader, "fetch_twse_companies", return_value=twse_companies), \
     patch.object(loader, "fetch_twse_daily",     return_value=[]), \
     patch.object(loader, "fetch_tpex_companies", return_value=[]), \
     patch.object(loader, "fetch_tpex_daily",     return_value={}):

    df2, data_date2 = loader.load_all_market_data()

assert len(df2) == 2
assert data_date2 == ""
print(f"load_all_market_data (TWSE-only, no prices): OK — {len(df2)} rows")

print("\nALL STARTUP CHECKS PASSED")
