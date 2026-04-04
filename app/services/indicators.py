from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FeatureSnapshot
from app.services.analysis_frame import build_indicator_frame
from app.services.market_data import load_symbol_market_rows
from app.services.probability_engine import ProbabilityEngine


class IndicatorService:
    def __init__(self) -> None:
        self.probability_engine = ProbabilityEngine()

    def compute_for_symbol(self, session: Session, symbol: str) -> dict[str, float | str] | None:
        rows = load_symbol_market_rows(session, symbol)
        if len(rows) < 35:
            return None

        df = build_indicator_frame(rows)
        latest = df.iloc[-1]
        previous = df.iloc[-2] if len(df) > 1 else latest
        trend = str(latest["trend"])
        probabilities = self.probability_engine.estimate(latest, previous)

        feature = session.execute(
            select(FeatureSnapshot).where(
                FeatureSnapshot.symbol == symbol,
                FeatureSnapshot.timestamp == latest["timestamp"],
            )
        ).scalar_one_or_none()
        if feature is None:
            feature = FeatureSnapshot(symbol=symbol, timestamp=latest["timestamp"])
            session.add(feature)

        feature.rsi = float(latest["rsi"])
        feature.macd = float(latest["macd"])
        feature.macd_signal = float(latest["macd_signal"])
        feature.ema20 = float(latest["ema20"])
        feature.ema50 = float(latest["ema50"])
        feature.trend = trend
        feature.volume_change = float(latest["volume_change"])

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
        }