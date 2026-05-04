from __future__ import annotations

import math

from app.models import FeatureSnapshot
from app.services.analysis_frame import build_indicator_frame
from app.services.market_data import load_symbol_market_rows
from app.services.probability_engine import ProbabilityEngine


def _isnan(v) -> bool:
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return True


class IndicatorService:
    def __init__(self) -> None:
        self.probability_engine = ProbabilityEngine()

    def compute_for_symbol(self, symbol: str) -> dict[str, float | str] | None:
        rows = load_symbol_market_rows(symbol)
        if len(rows) < 35:
            return None

        df = build_indicator_frame(rows)
        latest = df.iloc[-1]
        previous = df.iloc[-2] if len(df) > 1 else latest
        prev2 = df.iloc[-3] if len(df) > 2 else previous

        # Reject if critical indicators are NaN (means not enough data for meaningful analysis)
        _critical = ["rsi", "macd", "macd_signal", "ema20", "ema50"]
        _nan_count = sum(1 for c in _critical if _isnan(latest.get(c, float("nan"))))
        if _nan_count >= 3:
            return None

        trend = str(latest["trend"])
        probabilities = self.probability_engine.estimate(latest, previous)

        feature = FeatureSnapshot.objects.filter(
            symbol=symbol,
            timestamp=latest["timestamp"],
        ).first()
        if feature is None:
            feature = FeatureSnapshot(symbol=symbol, timestamp=latest["timestamp"])

        feature.rsi = float(latest["rsi"])
        feature.macd = float(latest["macd"])
        feature.macd_signal = float(latest["macd_signal"])
        feature.ema20 = float(latest["ema20"])
        feature.ema50 = float(latest["ema50"])
        feature.trend = trend
        feature.volume_change = float(latest["volume_change"])
        feature.save()

        return {
            "symbol": symbol,
            "timestamp": latest["timestamp"],
            "close": float(latest["close"]),
            "rsi": float(latest["rsi"]),
            "macd": float(latest["macd"]),
            "macd_signal": float(latest["macd_signal"]),
            "ema20": float(latest["ema20"]),
            "ema50": float(latest["ema50"]),
            "trend": trend,
            "volume_change": float(latest["volume_change"]),
            "macd_hist": float(latest["macd_hist"]),
            "change_24h": float(latest["change_24h"]),
            "change_7d": float(latest["change_7d"]),
            "change_30d": float(latest["change_30d"]),
            "volatility_14d": float(latest["volatility_14d"]),
            "up_probability": probabilities["up_probability"],
            "down_probability": probabilities["down_probability"],
            "bottom_probability": probabilities["bottom_probability"],
            "top_probability": probabilities["top_probability"],
            "reversal_signal": probabilities["reversal_signal"],
            # Bollinger Bands
            "bb_upper": float(latest["bb_upper"]) if not _isnan(latest["bb_upper"]) else float(latest["close"]),
            "bb_lower": float(latest["bb_lower"]) if not _isnan(latest["bb_lower"]) else float(latest["close"]),
            "sma20": float(latest["sma20"]) if not _isnan(latest["sma20"]) else float(latest["close"]),
            "vwap": float(latest["vwap"]) if not _isnan(latest["vwap"]) else float(latest["close"]),
            # Previous bar data for divergence detection
            "prev_close": float(previous["close"]),
            "prev_rsi": float(previous["rsi"]),
            "prev_macd_hist": float(previous["macd_hist"]),
            "prev2_close": float(prev2["close"]),
            "prev2_rsi": float(prev2["rsi"]),
            "prev2_macd_hist": float(prev2["macd_hist"]),
            "prev_macd": float(previous["macd"]),
            "prev_macd_signal": float(previous["macd_signal"]),
            # Bollinger Band width (volatility squeeze indicator)
            "bb_width": float((latest["bb_upper"] - latest["bb_lower"]) / latest["sma20"] * 100) if not _isnan(latest["sma20"]) and latest["sma20"] != 0 else 0.0,
            "open": float(latest["open"]),
            "high": float(latest["high"]),
            "low": float(latest["low"]),
            "volume": float(latest["volume"]),
            # Whale / anomaly indicators
            "whale_score": float(latest.get("whale_score", 0)) if not _isnan(latest.get("whale_score", 0)) else 0.0,
            "whale_signal": str(latest.get("whale_signal", "NONE")),
            "vol_zscore": float(latest.get("vol_zscore", 0)) if not _isnan(latest.get("vol_zscore", 0)) else 0.0,
            "vol_ratio": float(latest.get("vol_ratio", 1)) if not _isnan(latest.get("vol_ratio", 1)) else 1.0,
            "obv": float(latest.get("obv", 0)) if not _isnan(latest.get("obv", 0)) else 0.0,
            "price_change_pct": float(latest.get("price_change_pct", 0)) if not _isnan(latest.get("price_change_pct", 0)) else 0.0,
            "range_ratio": float(latest.get("range_ratio", 1)) if not _isnan(latest.get("range_ratio", 1)) else 1.0,
            "obv_divergence": _detect_obv_div(df),
            # Higher Timeframe (4h) confluence
            "htf_trend": str(latest.get("htf_trend", "SIDEWAYS")),
            "htf_rsi": float(latest.get("htf_rsi", 50.0)) if not _isnan(latest.get("htf_rsi", 50.0)) else 50.0,
            "htf_macd_hist": float(latest.get("htf_macd_hist", 0.0)) if not _isnan(latest.get("htf_macd_hist", 0.0)) else 0.0,
        }


def _detect_obv_div(df) -> str:
    """Wrapper for OBV divergence detection."""
    try:
        from app.services.whale_detector import detect_obv_divergence
        return detect_obv_divergence(df)
    except Exception:
        return "NONE"