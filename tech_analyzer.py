"""
技術面分析模組
輸入：OHLCV DataFrame（來自 FinMind）
輸出：指標數據 + 訊號判斷 + 文字摘要 + 目標價區間
"""

from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

# ── 指標說明（UI 教學用）────────────────────────────────────────

INDICATOR_EXPLANATIONS = {
    "MA": {
        "name": "移動平均線 MA",
        "principle": "以過去 N 日收盤價平均，平滑雜訊，反映趨勢方向。",
        "how_to_read": (
            "• MA5 > MA20 > MA60：多頭排列，趨勢健康\n"
            "• 股價跌破 MA20：短線轉弱；跌破 MA60：中期趨勢反轉\n"
            "• MA5 上穿 MA20：黃金交叉（買訊）；下穿：死亡交叉（賣訊）\n"
            "• MA 斜率向上且股價站上 MA：多頭格局可持股"
        ),
    },
    "RSI": {
        "name": "相對強弱指標 RSI(14)",
        "principle": "衡量過去 14 日漲跌比值，範圍 0-100。RSI = 100 - 100/(1+平均漲幅/平均跌幅)。",
        "how_to_read": (
            "• RSI < 30：超賣，反彈機率高（強跌趨勢中可能繼續破底）\n"
            "• RSI > 70：超買，注意回調（強勢股可持續高 RSI）\n"
            "• RSI 50 為多空分界；站上 50 偏多，跌破偏空\n"
            "• 頂背離：股價新高但 RSI 未新高（賣訊）；底背離：股價新低但 RSI 未新低（買訊）"
        ),
    },
    "MACD": {
        "name": "MACD(12,26,9)",
        "principle": "MACD = EMA12 - EMA26；訊號線 = MACD 的 EMA9；柱狀圖 = MACD - 訊號線。",
        "how_to_read": (
            "• 柱狀圖由負翻正：動能轉多（買訊）；由正翻負：賣訊\n"
            "• MACD 線上穿訊號線：黃金交叉，趨勢轉強\n"
            "• 零軸上方偏多；零軸下方偏空\n"
            "• 背離：股價新高但 MACD 峰值降低，上漲動能衰退"
        ),
    },
    "BOLL": {
        "name": "布林通道 Bollinger Bands(20, 2σ)",
        "principle": "中軌 = MA20；上軌 = MA20+2σ；下軌 = MA20-2σ。通道寬度反映波動。",
        "how_to_read": (
            "• 觸及上軌：短線過熱，注意壓回\n"
            "• 跌破下軌：超賣，反彈機率高\n"
            "• 布林收縮後常出現方向性突破\n"
            "• %B = (價格-下軌)/(上軌-下軌)，>1 超買，<0 超賣"
        ),
    },
    "VOL": {
        "name": "成交量",
        "principle": "量是價的先行指標，反映市場參與程度。",
        "how_to_read": (
            "• 放量上漲（量 > 均量 1.5x）：強勢確認，資金流入\n"
            "• 縮量上漲：動能不足，突破可信度低\n"
            "• 放量下跌：賣壓沉重\n"
            "• 縮量整理後放量突破：趨勢啟動訊號"
        ),
    },
    "FIBO": {
        "name": "費波那契回撤 Fibonacci",
        "principle": "以行情高低點標出 23.6%、38.2%、50%、61.8%（黃金比例）、78.6% 回撤位。",
        "how_to_read": (
            "• 上漲後回撤，61.8% 是最常見支撐（黃金分割）\n"
            "• 38.2% 淺回撤（趨勢強）；50% 中等；61.8% 深回撤\n"
            "• 跌破 61.8% 趨勢可能反轉，78.6% 是最後防線\n"
            "• 費波那契搭配成交量和 MA 使用，訊號更可靠"
        ),
    },
}


# ── 指標計算 ────────────────────────────────────────────────────

def calc_ma(close: pd.Series, n: int) -> pd.Series:
    return close.rolling(n).mean()


def calc_rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(n).mean()
    loss  = (-delta.clip(upper=0)).rolling(n).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def calc_macd(close: pd.Series, fast=12, slow=26, signal=9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    ema_f  = close.ewm(span=fast,   adjust=False).mean()
    ema_s  = close.ewm(span=slow,   adjust=False).mean()
    macd   = ema_f - ema_s
    sig    = macd.ewm(span=signal,  adjust=False).mean()
    hist   = macd - sig
    return macd, sig, hist


def calc_bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    ma  = close.rolling(n).mean()
    std = close.rolling(n).std()
    return ma + k * std, ma, ma - k * std


def calc_atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    hl  = df["high"] - df["low"]
    hc  = (df["high"] - df["close"].shift()).abs()
    lc  = (df["low"]  - df["close"].shift()).abs()
    tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(n).mean()


# ── 主要分析函數 ─────────────────────────────────────────────────

def analyze(df: pd.DataFrame, ticker: str = "", name: str = "") -> Dict:
    """
    完整技術分析
    回傳 dict，包含 indicators（用於畫圖）與 analysis（文字摘要 + 目標價）
    """
    if df is None or len(df) < 20:
        return {"error": "歷史資料不足（需至少 20 天）"}

    df = df.copy().reset_index(drop=True)
    close  = df["close"]
    volume = df["volume"]

    # ── 計算指標 ──
    ma5   = calc_ma(close, 5)
    ma20  = calc_ma(close, 20)
    ma60  = calc_ma(close, 60)  if len(df) >= 60  else pd.Series([np.nan] * len(df))
    ma120 = calc_ma(close, 120) if len(df) >= 120 else pd.Series([np.nan] * len(df))
    ma240 = calc_ma(close, 240) if len(df) >= 240 else pd.Series([np.nan] * len(df))
    rsi   = calc_rsi(close)
    macd_line, macd_sig, macd_hist = calc_macd(close)
    bb_up, bb_mid, bb_dn = calc_bollinger(close)
    atr   = calc_atr(df)
    vol_ma20 = volume.rolling(20).mean()

    # 乖離率 (BIAS) = (收盤 - 均線) / 均線 × 100
    bias20 = ((close - ma20) / ma20 * 100).round(2)
    bias60 = ((close - ma60) / ma60 * 100).round(2)

    last    = close.iloc[-1]
    last_rsi       = rsi.iloc[-1]
    last_macd      = macd_line.iloc[-1]
    last_macd_sig  = macd_sig.iloc[-1]
    last_macd_hist = macd_hist.iloc[-1]
    last_bb_up     = bb_up.iloc[-1]
    last_bb_dn     = bb_dn.iloc[-1]
    last_bb_mid    = bb_mid.iloc[-1]
    last_ma5       = ma5.iloc[-1]
    last_ma20      = ma20.iloc[-1]
    last_ma60      = ma60.iloc[-1] if not np.isnan(ma60.iloc[-1]) else None
    last_atr       = atr.iloc[-1]
    last_vol       = volume.iloc[-1]
    last_vol_ma    = vol_ma20.iloc[-1]
    last_bias20    = bias20.iloc[-1] if not np.isnan(bias20.iloc[-1]) else None
    last_bias60    = bias60.iloc[-1] if not np.isnan(bias60.iloc[-1]) else None

    # ── 訊號判斷 ──
    signals: List[str] = []
    score = 0  # 正=偏多，負=偏空

    # MA 交叉
    if len(df) >= 3:
        if ma5.iloc[-2] < ma20.iloc[-2] and last_ma5 > last_ma20:
            signals.append("🟢 MA5/MA20 黃金交叉（短線偏多）")
            score += 2
        elif ma5.iloc[-2] > ma20.iloc[-2] and last_ma5 < last_ma20:
            signals.append("🔴 MA5/MA20 死亡交叉（短線偏空）")
            score -= 2

    # 價格與均線位置
    if not np.isnan(last_ma20):
        if last > last_ma20 * 1.05:
            signals.append(f"🟡 股價高於 MA20 {((last/last_ma20-1)*100):.1f}%（留意過熱）")
            score += 1
        elif last > last_ma20:
            signals.append(f"🟢 股價站上 MA20（+{((last/last_ma20-1)*100):.1f}%）")
            score += 1
        else:
            signals.append(f"🔴 股價跌破 MA20（{((last/last_ma20-1)*100):.1f}%）")
            score -= 1

    if last_ma60 is not None and not np.isnan(last_ma60):
        if last > last_ma60:
            signals.append(f"🟢 股價站上 MA60（+{((last/last_ma60-1)*100):.1f}%）")
            score += 1
        else:
            signals.append(f"🔴 股價跌破 MA60（{((last/last_ma60-1)*100):.1f}%）")
            score -= 1

    # RSI
    if not np.isnan(last_rsi):
        if last_rsi < 30:
            signals.append(f"🟢 RSI {last_rsi:.1f} — 超賣區，反彈機率高")
            score += 2
        elif last_rsi < 40:
            signals.append(f"🟢 RSI {last_rsi:.1f} — 偏弱但接近支撐")
            score += 1
        elif last_rsi > 70:
            signals.append(f"🔴 RSI {last_rsi:.1f} — 超買區，注意回調")
            score -= 2
        elif last_rsi > 60:
            signals.append(f"🟡 RSI {last_rsi:.1f} — 偏強，續漲留意量能")
            score -= 1
        else:
            signals.append(f"🟡 RSI {last_rsi:.1f} — 中性區")

    # MACD
    if not np.isnan(last_macd) and not np.isnan(last_macd_sig):
        if len(df) >= 3:
            prev_hist = macd_hist.iloc[-2]
            if prev_hist < 0 and last_macd_hist > 0:
                signals.append("🟢 MACD 柱狀翻正（動能轉多）")
                score += 2
            elif prev_hist > 0 and last_macd_hist < 0:
                signals.append("🔴 MACD 柱狀翻負（動能轉空）")
                score -= 2
            elif last_macd > last_macd_sig:
                signals.append("🟢 MACD 在訊號線上方")
                score += 1
            else:
                signals.append("🔴 MACD 在訊號線下方")
                score -= 1

    # 布林通道
    if not np.isnan(last_bb_up) and not np.isnan(last_bb_dn):
        bb_pct = (last - last_bb_dn) / (last_bb_up - last_bb_dn + 1e-9)
        if last > last_bb_up:
            signals.append(f"🔴 突破布林上軌（{last:.2f} > {last_bb_up:.2f}），短線過熱")
            score -= 1
        elif last < last_bb_dn:
            signals.append(f"🟢 跌破布林下軌（{last:.2f} < {last_bb_dn:.2f}），超賣反彈機率高")
            score += 2
        else:
            signals.append(f"🟡 布林位置 {bb_pct*100:.0f}%（0%=下軌 / 100%=上軌）")

    # 成交量
    if not np.isnan(last_vol_ma) and last_vol_ma > 0:
        vol_ratio = last_vol / last_vol_ma
        if vol_ratio > 1.5:
            day_chg = (last - close.iloc[-2]) / close.iloc[-2] * 100
            tag = "放量上漲" if day_chg > 0 else "放量下跌"
            color = "🟢" if day_chg > 0 else "🔴"
            signals.append(f"{color} 成交量 {vol_ratio:.1f}x 均量（{tag}）")
            score += 1 if day_chg > 0 else -1
        elif vol_ratio < 0.5:
            signals.append("🟡 縮量（觀望氣氛濃）")

    # 乖離率 (BIAS)
    if last_bias20 is not None:
        if last_bias20 > 15:
            signals.append(f"🔴 MA20乖離率 +{last_bias20:.1f}%，短線過熱，留意回檔風險")
            score -= 1
        elif last_bias20 > 8:
            signals.append(f"🟡 MA20乖離率 +{last_bias20:.1f}%，偏高，短線宜謹慎追高")
        elif last_bias20 < -15:
            signals.append(f"🟢 MA20乖離率 {last_bias20:.1f}%，深度超賣，技術反彈機率高")
            score += 2
        elif last_bias20 < -8:
            signals.append(f"🟢 MA20乖離率 {last_bias20:.1f}%，短線超賣，可逢低分批觀察")
            score += 1
        else:
            signals.append(f"🟡 MA20乖離率 {last_bias20:.1f}%（合理區間）")

    # ── 長期均線訊號 ──
    last_ma120 = ma120.iloc[-1] if not np.isnan(ma120.iloc[-1]) else None
    last_ma240 = ma240.iloc[-1] if not np.isnan(ma240.iloc[-1]) else None
    if last_ma120 is not None:
        if last > last_ma120:
            signals.append(f"🟢 股價站上 MA120（+{((last/last_ma120-1)*100):.1f}%）｜中長期趨勢偏多")
            score += 1
        else:
            signals.append(f"🔴 股價跌破 MA120（{((last/last_ma120-1)*100):.1f}%）｜中長期趨勢轉弱")
            score -= 1
    if last_ma240 is not None:
        if last > last_ma240:
            signals.append(f"🟢 股價站上 MA240（年線）（+{((last/last_ma240-1)*100):.1f}%）｜長期趨勢健康")
        else:
            signals.append(f"🔴 股價跌破 MA240（年線）（{((last/last_ma240-1)*100):.1f}%）｜長期轉空，謹慎")
            score -= 1

    # ── 支撐 / 壓力 ──
    window = min(120, len(df))
    recent_high = close.iloc[-window:].max()
    recent_low  = close.iloc[-window:].min()
    # 52週高低
    w52 = min(252, len(df))
    high_52w = close.iloc[-w52:].max()
    low_52w  = close.iloc[-w52:].min()
    atr_val = last_atr if not np.isnan(last_atr) else last * 0.02

    raw_supports    = {round(last_bb_dn, 2), round(last_ma20, 2), round(recent_low, 2), round(low_52w, 2)}
    raw_resistances = {round(last_bb_up, 2), round(last_ma20 * 1.05, 2), round(recent_high, 2), round(high_52w, 2)}
    if last_ma60 is not None and not np.isnan(last_ma60):
        raw_supports.add(round(last_ma60, 2))
        raw_resistances.add(round(last_ma60 * 1.03, 2))
    if last_ma120 is not None:
        raw_supports.add(round(last_ma120, 2))
        raw_resistances.add(round(last_ma120 * 1.02, 2))

    # ── 費波那契回撤位 ──
    fib_high = high_52w
    fib_low  = low_52w
    fib_range = fib_high - fib_low
    fib_levels = {}
    if fib_range > 0:
        for ratio, label in [(0.236, "23.6%"), (0.382, "38.2%"), (0.500, "50.0%"),
                              (0.618, "61.8%"), (0.786, "78.6%")]:
            lvl = round(fib_high - fib_range * ratio, 2)
            fib_levels[label] = lvl
            if lvl < last:
                raw_supports.add(lvl)
            else:
                raw_resistances.add(lvl)

    supports    = sorted([s for s in raw_supports    if s < last])
    resistances = sorted([r for r in raw_resistances if r > last])

    # 確保壓力位永遠有值（用 ATR 補）
    if not resistances:
        resistances = [round(last + atr_val, 2), round(last + atr_val * 2, 2)]
    # 確保支撐位永遠有值
    if not supports:
        supports = [round(last - atr_val * 2, 2), round(last - atr_val, 2)]

    # ── 目標價估算（使用 S/R 位置，非 ATR 任意倍數）──
    #
    # 學術依據：
    # - 5日目標：使用最近壓力位（阻力）或支撐位（空頭），
    #   反映短期價格磁吸效應（support/resistance as price targets）
    # - 20日目標：使用次近壓力/支撐，或布林通道量測移動（measured move）
    # - 若無 S/R，以 ATR×√(T/1) 計算統計置信區間（random walk base case）
    #   ATR×√5 ≈ 5日±1σ，ATR×√20 ≈ 20日±1σ（基於 IID 日報酬假設）

    atr_5d  = round(atr_val * np.sqrt(5),  2)
    atr_20d = round(atr_val * np.sqrt(20), 2)

    if score >= 0:  # 偏多：目標在壓力位
        trend_label = "偏多" if score >= 2 else "震盪偏多"
        if resistances:
            t5_high  = resistances[0]
            t20_high = resistances[1] if len(resistances) >= 2 else round(resistances[0] * 1.02, 2)
        else:
            t5_high  = round(last + atr_5d,  2)
            t20_high = round(last + atr_20d, 2)
        t5_low  = round(max(last - atr_5d,  supports[-1] if supports else last * 0.97), 2)
        t20_low = round(max(last - atr_20d, supports[0]  if supports else last * 0.94), 2)
    else:           # 偏空：目標在支撐位
        trend_label = "偏空" if score <= -2 else "震盪偏空"
        if supports:
            t5_low  = supports[-1]
            t20_low = supports[0] if len(supports) >= 2 else round(supports[-1] * 0.98, 2)
        else:
            t5_low  = round(last - atr_5d,  2)
            t20_low = round(last - atr_20d, 2)
        t5_high  = round(min(last + atr_5d,  resistances[0] if resistances else last * 1.03), 2)
        t20_high = round(min(last + atr_20d, resistances[0] if resistances else last * 1.06), 2)

    target_5d  = (t5_low,  t5_high)
    target_20d = (t20_low, t20_high)

    # ── 文字摘要 ──
    overall = (
        "📈 短線偏多，建議觀察量能確認" if score >= 3 else
        "🟢 多方訊號略多，可考慮分批佈局" if score >= 1 else
        "🟡 多空訊號混雜，建議觀望" if score == 0 else
        "🔴 空方訊號偏多，注意風險控管" if score >= -2 else
        "📉 短線偏空，建議等待低點訊號"
    )

    return {
        "indicators": {
            "dates":       df["date"].tolist(),
            "open":        df["open"].tolist(),
            "high":        df["high"].tolist(),
            "low":         df["low"].tolist(),
            "close":       close.tolist(),
            "volume":      volume.tolist(),
            "ma5":         ma5.tolist(),
            "ma20":        ma20.tolist(),
            "ma60":        ma60.tolist(),
            "ma120":       ma120.tolist(),
            "ma240":       ma240.tolist(),
            "rsi":         rsi.tolist(),
            "macd":        macd_line.tolist(),
            "macd_signal": macd_sig.tolist(),
            "macd_hist":   macd_hist.tolist(),
            "bb_upper":    bb_up.tolist(),
            "bb_lower":    bb_dn.tolist(),
            "vol_ma20":    vol_ma20.tolist(),
            "bias20":      bias20.tolist(),
            "bias60":      bias60.tolist(),
        },
        "analysis": {
            "score":         score,
            "trend":         trend_label,
            "overall":       overall,
            "signals":       signals,
            "supports":      sorted([s for s in supports    if s < last], reverse=True),
            "resistances":   sorted([r for r in resistances if r > last]),
            "fib_levels":    fib_levels,
            "high_52w":      round(high_52w, 2),
            "low_52w":       round(low_52w, 2),
            "target_range":  target_20d,
            "target_5d":     target_5d,
            "target_20d":    target_20d,
            "current_price": last,
            "rsi":           round(last_rsi, 1) if not np.isnan(last_rsi) else None,
            "atr":           round(atr_val, 2),
            "ma120":         round(last_ma120, 2) if last_ma120 is not None else None,
            "ma240":         round(last_ma240, 2) if last_ma240 is not None else None,
            "bias20":        round(last_bias20, 2) if last_bias20 is not None else None,
            "bias60":        round(last_bias60, 2) if last_bias60 is not None else None,
        },
    }
