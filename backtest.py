"""
台股盤後量化分析平台 - 回測引擎模組
負責歷史驗證和績效分析
"""

from typing import Dict, List, Tuple, Optional
import numpy as np
import pandas as pd

from utils import to_number


class BacktestEngine:
    """
    回測引擎
    計算歷史命中率、Brier Score等指標
    """
    
    def __init__(self, snapshots: List[Dict]):
        """
        初始化回測引擎
        
        Args:
            snapshots: 歷史快照列表
        """
        self.snapshots = sorted(snapshots, key=lambda x: x.get("date", ""))
    
    def calculate_hit_rate(
        self,
        ticker: str,
        horizon: int = 20,
        min_samples: int = 5
    ) -> Tuple[float, int, str]:
        """
        計算歷史命中率
        
        Args:
            ticker: 股票代碼
            horizon: 時間週期(天)
            min_samples: 最小樣本數
        
        Returns:
            (命中率, 樣本數, 資料來源)
        """
        wins = 0
        total = 0
        
        # 遍歷所有可用的窗口
        for i in range(len(self.snapshots) - horizon):
            current_snap = self.snapshots[i]
            
            # 找horizon天後的快照
            if i + horizon < len(self.snapshots):
                future_snap = self.snapshots[i + horizon]
            else:
                continue
            
            current_rows = current_snap.get("rows", [])
            future_rows = future_snap.get("rows", [])
            
            # 找到對應股票
            current_item = next(
                (r for r in current_rows if r.get("ticker") == ticker),
                None
            )
            future_item = next(
                (r for r in future_rows if r.get("ticker") == ticker),
                None
            )
            
            if not current_item or not future_item:
                continue
            
            current_close = to_number(current_item.get("close"))
            future_close = to_number(future_item.get("close"))
            
            if current_close == 0 or future_close == 0:
                continue
            
            total += 1
            
            # 判定是否上漲
            if future_close > current_close:
                wins += 1
        
        # 檢查樣本數
        if total >= min_samples:
            hit_rate = round(wins / total * 100, 1)
            return hit_rate, total, "本機快照"
        else:
            return 0, total, "樣本不足"
    
    def calculate_brier_score(
        self,
        ticker: str,
        horizon: int = 20,
        min_samples: int = 5
    ) -> Optional[float]:
        """
        計算Brier Score (機率預測準確度)
        Brier Score = 平均((預測機率 - 實際結果)^2)
        越小越好,完美預測為0
        
        Args:
            ticker: 股票代碼
            horizon: 時間週期
            min_samples: 最小樣本數
        
        Returns:
            Brier Score或None
        """
        predictions = []
        outcomes = []
        
        for i in range(len(self.snapshots) - horizon):
            current_snap = self.snapshots[i]
            
            if i + horizon < len(self.snapshots):
                future_snap = self.snapshots[i + horizon]
            else:
                continue
            
            current_rows = current_snap.get("rows", [])
            future_rows = future_snap.get("rows", [])
            
            current_item = next(
                (r for r in current_rows if r.get("ticker") == ticker),
                None
            )
            future_item = next(
                (r for r in future_rows if r.get("ticker") == ticker),
                None
            )
            
            if not current_item or not future_item:
                continue
            
            # 取得預測機率
            prob_key = f"prob{horizon}"
            probability = current_item.get(prob_key, 50) / 100  # 轉為0-1
            
            # 取得實際結果
            current_close = to_number(current_item.get("close"))
            future_close = to_number(future_item.get("close"))
            
            if current_close == 0 or future_close == 0:
                continue
            
            outcome = 1 if future_close > current_close else 0
            
            predictions.append(probability)
            outcomes.append(outcome)
        
        # 檢查樣本數
        if len(predictions) >= min_samples:
            brier = np.mean([(p - o) ** 2 for p, o in zip(predictions, outcomes)])
            return round(brier, 4)
        else:
            return None
    
    def calculate_calibration(
        self,
        ticker: str,
        horizon: int = 20,
        bins: int = 10
    ) -> Optional[pd.DataFrame]:
        """
        計算機率校準度
        (將預測機率分組,檢查實際命中率是否接近預測)
        
        Args:
            ticker: 股票代碼
            horizon: 時間週期
            bins: 分組數
        
        Returns:
            校準度DataFrame或None
        """
        predictions = []
        outcomes = []
        
        for i in range(len(self.snapshots) - horizon):
            current_snap = self.snapshots[i]
            
            if i + horizon < len(self.snapshots):
                future_snap = self.snapshots[i + horizon]
            else:
                continue
            
            current_rows = current_snap.get("rows", [])
            future_rows = future_snap.get("rows", [])
            
            current_item = next(
                (r for r in current_rows if r.get("ticker") == ticker),
                None
            )
            future_item = next(
                (r for r in future_rows if r.get("ticker") == ticker),
                None
            )
            
            if not current_item or not future_item:
                continue
            
            prob_key = f"prob{horizon}"
            probability = current_item.get(prob_key, 50)
            
            current_close = to_number(current_item.get("close"))
            future_close = to_number(future_item.get("close"))
            
            if current_close == 0 or future_close == 0:
                continue
            
            outcome = 1 if future_close > current_close else 0
            
            predictions.append(probability)
            outcomes.append(outcome)
        
        if len(predictions) < 10:
            return None
        
        # 分組
        df = pd.DataFrame({
            "prediction": predictions,
            "outcome": outcomes
        })
        
        df["bin"] = pd.cut(df["prediction"], bins=bins, labels=False)
        
        calibration = df.groupby("bin").agg({
            "prediction": "mean",
            "outcome": "mean",
            "outcome": "count"
        }).reset_index()
        
        calibration.columns = ["bin", "predicted", "actual", "count"]
        
        return calibration
    
    def calculate_aggregate_stats(
        self,
        tickers: List[str],
        horizon: int = 20,
        min_samples: int = 3
    ) -> Dict:
        """
        計算多檔股票的聚合統計
        
        Args:
            tickers: 股票代碼列表
            horizon: 時間週期
            min_samples: 最小樣本數
        
        Returns:
            聚合統計字典
        """
        hit_rates = []
        brier_scores = []
        sample_sizes = []
        
        for ticker in tickers:
            # 命中率
            hit_rate, samples, source = self.calculate_hit_rate(
                ticker, horizon, min_samples
            )
            
            if source == "本機快照":
                hit_rates.append(hit_rate)
                sample_sizes.append(samples)
                
                # Brier Score
                brier = self.calculate_brier_score(ticker, horizon, min_samples)
                if brier is not None:
                    brier_scores.append(brier)
        
        if not hit_rates:
            return {
                "avg_hit_rate": 0,
                "median_hit_rate": 0,
                "avg_brier_score": 0,
                "total_samples": 0,
                "valid_stocks": 0,
            }
        
        return {
            "avg_hit_rate": round(np.mean(hit_rates), 1),
            "median_hit_rate": round(np.median(hit_rates), 1),
            "std_hit_rate": round(np.std(hit_rates), 1),
            "avg_brier_score": round(np.mean(brier_scores), 4) if brier_scores else 0,
            "total_samples": sum(sample_sizes),
            "valid_stocks": len(hit_rates),
        }
    
    def get_performance_over_time(
        self,
        ticker: str,
        horizon: int = 20
    ) -> pd.DataFrame:
        """
        取得隨時間變化的績效
        
        Args:
            ticker: 股票代碼
            horizon: 時間週期
        
        Returns:
            績效時間序列DataFrame
        """
        results = []
        
        for i in range(len(self.snapshots) - horizon):
            current_snap = self.snapshots[i]
            
            if i + horizon < len(self.snapshots):
                future_snap = self.snapshots[i + horizon]
            else:
                continue
            
            current_rows = current_snap.get("rows", [])
            future_rows = future_snap.get("rows", [])
            
            current_item = next(
                (r for r in current_rows if r.get("ticker") == ticker),
                None
            )
            future_item = next(
                (r for r in future_rows if r.get("ticker") == ticker),
                None
            )
            
            if not current_item or not future_item:
                continue
            
            current_close = to_number(current_item.get("close"))
            future_close = to_number(future_item.get("close"))
            
            if current_close == 0 or future_close == 0:
                continue
            
            prob_key = f"prob{horizon}"
            predicted_prob = current_item.get(prob_key, 50)
            
            actual_return = ((future_close - current_close) / current_close) * 100
            is_up = future_close > current_close
            
            results.append({
                "date": current_snap.get("date"),
                "predicted_prob": predicted_prob,
                "actual_return": actual_return,
                "is_up": is_up,
                "close": current_close,
            })
        
        if not results:
            return pd.DataFrame()
        
        df = pd.DataFrame(results)
        
        # 計算累積命中率
        df["cumulative_hit_rate"] = df["is_up"].expanding().mean() * 100
        
        return df
    
    def get_snapshot_count(self) -> int:
        """
        取得快照數量
        
        Returns:
            快照數
        """
        return len(self.snapshots)
    
    def get_date_range(self) -> Tuple[str, str]:
        if not self.snapshots:
            return ("", "")
        return (
            self.snapshots[0].get("date", ""),
            self.snapshots[-1].get("date", "")
        )

    # ── 自動參數調優 ────────────────────────────────────────────────

    def optimize_weights(
        self,
        tickers: List[str],
        horizon: int = 20,
        min_samples: int = 3,
    ) -> Dict:
        """
        Grid search 找最佳因子權重組合（最大化整體命中率）
        需至少 10 個快照才有意義
        回傳 best_weights, best_hit_rate, improvement
        """
        if len(self.snapshots) < 10:
            return {"error": "快照不足 10 天，無法優化"}

        # 收集各股票的 (預測機率序列, 實際漲跌序列)
        stock_data: Dict[str, List[Tuple[float, int]]] = {}
        for ticker in tickers:
            pairs = []
            for i in range(len(self.snapshots) - horizon):
                cur  = self.snapshots[i]
                fut  = self.snapshots[i + horizon]
                cr   = next((r for r in cur.get("rows", []) if r.get("ticker") == ticker), None)
                fr   = next((r for r in fut.get("rows", []) if r.get("ticker") == ticker), None)
                if not cr or not fr:
                    continue
                cc = to_number(cr.get("close", 0))
                fc = to_number(fr.get("close", 0))
                if cc <= 0 or fc <= 0:
                    continue
                prob = cr.get(f"prob{horizon}", 50)
                pairs.append((prob, int(fc > cc)))
            if len(pairs) >= min_samples:
                stock_data[ticker] = pairs

        if not stock_data:
            return {"error": "有效樣本不足"}

        # 計算目前基準命中率
        def overall_hit(weight_bias: float) -> float:
            """weight_bias: 0=不調整，>0 推高機率，<0 壓低機率"""
            hits = total = 0
            for pairs in stock_data.values():
                for prob, actual in pairs:
                    adj = min(95, max(5, prob + weight_bias))
                    predicted_up = adj >= 50
                    if predicted_up == bool(actual):
                        hits += 1
                    total += 1
            return hits / total * 100 if total else 0

        # 搜尋最佳 probability bias（-10 ~ +10）
        best_bias = 0.0
        best_hit  = overall_hit(0.0)
        for bias in np.arange(-10, 11, 0.5):
            h = overall_hit(bias)
            if h > best_hit:
                best_hit  = h
                best_bias = bias

        baseline = overall_hit(0.0)

        # 找對各因子應提高/降低的建議
        # 透過分析高機率預測（>60%）vs 低機率預測的命中率差異
        high_prob_hits = sum(
            int(bool(actual)) for pairs in stock_data.values()
            for prob, actual in pairs if prob >= 60
        )
        high_prob_total = sum(
            1 for pairs in stock_data.values()
            for prob, actual in pairs if prob >= 60
        )
        low_prob_hits = sum(
            int(bool(actual)) for pairs in stock_data.values()
            for prob, actual in pairs if prob < 50
        )
        low_prob_total = sum(
            1 for pairs in stock_data.values()
            for prob, actual in pairs if prob < 50
        )

        high_hr = high_prob_hits / high_prob_total * 100 if high_prob_total else 0
        low_hr  = low_prob_hits  / low_prob_total  * 100 if low_prob_total  else 0

        suggestions = []
        if high_hr < 55:
            suggestions.append("高機率預測命中率偏低（<55%），建議提高信心門檻或降低動能權重")
        if low_hr > 45:
            suggestions.append("低機率預測命中率偏高（>45%），模型可能整體偏空，建議校正機率偏移")
        if best_bias > 2:
            suggestions.append(f"機率整體偏低 {best_bias:+.1f}%，建議在模型設定提高動能/成長權重")
        elif best_bias < -2:
            suggestions.append(f"機率整體偏高 {best_bias:+.1f}%，建議降低動能權重或提高風險門檻")

        return {
            "baseline_hit_rate":  round(baseline, 1),
            "optimized_hit_rate": round(best_hit, 1),
            "improvement":        round(best_hit - baseline, 1),
            "prob_bias":          round(best_bias, 1),
            "high_prob_hit_rate": round(high_hr, 1),
            "low_prob_hit_rate":  round(low_hr, 1),
            "valid_stocks":       len(stock_data),
            "total_samples":      sum(len(p) for p in stock_data.values()),
            "suggestions":        suggestions,
        }

    def calibrate_probabilities(
        self,
        tickers: List[str],
        horizon: int = 20,
        min_samples: int = 3,
    ) -> Dict:
        """
        機率校準：統計模型預測 vs 實際命中率，產生校準曲線
        回傳各區間的預測偏差，以及整體偏移量
        """
        if len(self.snapshots) < 10:
            return {"error": "快照不足 10 天"}

        bins = {
            "30-40": {"pred": [], "actual": []},
            "40-50": {"pred": [], "actual": []},
            "50-60": {"pred": [], "actual": []},
            "60-70": {"pred": [], "actual": []},
            "70-80": {"pred": [], "actual": []},
        }

        for ticker in tickers:
            for i in range(len(self.snapshots) - horizon):
                cur = self.snapshots[i]
                fut = self.snapshots[i + horizon]
                cr  = next((r for r in cur.get("rows", []) if r.get("ticker") == ticker), None)
                fr  = next((r for r in fut.get("rows", []) if r.get("ticker") == ticker), None)
                if not cr or not fr:
                    continue
                cc = to_number(cr.get("close", 0))
                fc = to_number(fr.get("close", 0))
                if cc <= 0 or fc <= 0:
                    continue
                prob   = cr.get(f"prob{horizon}", 50)
                actual = int(fc > cc)
                for label, lo, hi in [
                    ("30-40", 30, 40), ("40-50", 40, 50),
                    ("50-60", 50, 60), ("60-70", 60, 70), ("70-80", 70, 80),
                ]:
                    if lo <= prob < hi:
                        bins[label]["pred"].append(prob)
                        bins[label]["actual"].append(actual)

        rows = []
        for label, data in bins.items():
            if len(data["actual"]) < min_samples:
                continue
            avg_pred   = np.mean(data["pred"])
            actual_hr  = np.mean(data["actual"]) * 100
            rows.append({
                "區間":    label + "%",
                "預測均值": round(avg_pred, 1),
                "實際命中": round(actual_hr, 1),
                "偏差":    round(actual_hr - avg_pred, 1),
                "樣本數":  len(data["actual"]),
            })

        if not rows:
            return {"error": "樣本不足以校準"}

        df = pd.DataFrame(rows)
        avg_bias = round(df["偏差"].mean(), 1)
        note = (
            f"模型整體{'低估' if avg_bias > 0 else '高估'}上漲機率 {abs(avg_bias):.1f}%"
            if abs(avg_bias) > 2 else "模型機率校準良好"
        )

        return {
            "calibration_table": df.to_dict("records"),
            "avg_bias": avg_bias,
            "note": note,
        }

    def bootstrap_model_confidence(
        self, ticker: str = None, horizon: int = 20, n_boot: int = 500
    ) -> Dict:
        """
        以 Bootstrap 有放回抽樣估算命中率的 95% 信賴區間。
        學術依據：Efron & Tibshirani (1993) bootstrap resampling。

        Args:
            ticker:   指定股票代號（None = 全市場）
            horizon:  預測天數（5/20/60）
            n_boot:   抽樣次數

        Returns: {hit_rate, ci_low, ci_high, n_samples, note}
        """
        if len(self.snapshots) < 5:
            return {"error": "快照數不足（需 ≥ 5）"}

        # 蒐集所有 (predicted_prob, actual_up) 樣本
        samples = []
        for i in range(len(self.snapshots) - 1):
            cur = self.snapshots[i]
            fut = self.snapshots[i + 1] if i + 1 < len(self.snapshots) else None
            if fut is None:
                continue
            cur_stocks  = {s["ticker"]: s for s in cur.get("stocks", []) if "ticker" in s}
            fut_stocks  = {s["ticker"]: s for s in fut.get("stocks", []) if "ticker" in s}
            tickers = [ticker] if ticker else list(cur_stocks.keys())
            for t in tickers:
                cs = cur_stocks.get(t)
                fs = fut_stocks.get(t)
                if cs and fs:
                    prob = to_number(cs.get("prob_up_20d", cs.get("prob_up")))
                    cp = to_number(cs.get("close"))
                    fp = to_number(fs.get("close"))
                    if prob is not None and cp and fp:
                        samples.append((prob / 100, int(fp > cp)))

        if len(samples) < 10:
            return {"error": f"有效樣本不足（{len(samples)} 筆，需 ≥ 10）"}

        probs = np.array([s[0] for s in samples])
        actuals = np.array([s[1] for s in samples])
        overall_hit = float(actuals.mean() * 100)

        rng = np.random.default_rng(42)
        boot_hits = []
        n = len(samples)
        for _ in range(n_boot):
            idx = rng.integers(0, n, size=n)
            boot_hits.append(actuals[idx].mean() * 100)
        boot_hits = np.array(boot_hits)
        ci_low  = float(np.percentile(boot_hits, 2.5))
        ci_high = float(np.percentile(boot_hits, 97.5))

        return {
            "hit_rate":  round(overall_hit, 1),
            "ci_low":    round(ci_low, 1),
            "ci_high":   round(ci_high, 1),
            "n_samples": n,
            "note": f"命中率 {overall_hit:.1f}%（95% CI: {ci_low:.1f}%–{ci_high:.1f}%），樣本數 {n}",
        }
