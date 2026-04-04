from __future__ import annotations

import math
from typing import Any

import pandas as pd


class ProbabilityEngine:
    def estimate(self, latest: pd.Series, previous: pd.Series | None = None) -> dict[str, Any]:
        rsi = float(latest["rsi"])
        close = float(latest["close"])
        ema20 = float(latest["ema20"])
        ema50 = float(latest["ema50"])
        macd = float(latest["macd"])
        macd_signal = float(latest["macd_signal"])
        macd_hist = float(latest.get("macd_hist", macd - macd_signal))
        previous_hist = float(previous.get("macd_hist", previous["macd"] - previous["macd_signal"])) if previous is not None else macd_hist
        hist_slope = macd_hist - previous_hist
        volume_change = float(latest.get("volume_change", 0.0))
        change_24h = float(latest.get("change_24h", 0.0))
        change_7d = float(latest.get("change_7d", 0.0))
        trend = str(latest.get("trend", "SIDEWAYS"))

        price_vs_ema20 = (close - ema20) / ema20 if ema20 else 0.0
        price_vs_ema50 = (close - ema50) / ema50 if ema50 else 0.0
        macd_strength = self._clip(((macd - macd_signal) / close) * 250 if close else 0.0, -2.5, 2.5)
        hist_strength = self._clip((hist_slope / close) * 800 if close else 0.0, -2.5, 2.5)
        trend_bias = 1.0 if trend == "UP" else -1.0 if trend == "DOWN" else 0.0
        volume_bias = self._clip(volume_change * 3, -1.5, 1.5)
        short_momentum = self._clip(change_24h / 4, -1.5, 1.5)
        weekly_momentum = self._clip(change_7d / 10, -1.5, 1.5)

        up_score = (
            trend_bias * 0.95
            + macd_strength * 0.85
            + hist_strength * 0.65
            + volume_bias * 0.35
            + short_momentum * 0.35
            + weekly_momentum * 0.30
            - self._clip((rsi - 70) / 18, 0.0, 1.5) * 0.45
            + self._clip((35 - rsi) / 18, 0.0, 1.5) * 0.25
        )
        bottom_score = (
            self._clip((32 - rsi) / 10, -1.5, 2.4) * 1.15
            + self._clip(-price_vs_ema20 * 14, -1.5, 1.8) * 0.6
            + hist_strength * 0.95
            + volume_bias * 0.35
            - trend_bias * 0.20
        )
        top_score = (
            self._clip((rsi - 68) / 10, -1.5, 2.4) * 1.15
            + self._clip(price_vs_ema20 * 14, -1.5, 1.8) * 0.6
            - hist_strength * 0.95
            + self._clip(-volume_change * 3, -1.0, 1.2) * 0.2
            + trend_bias * 0.20
        )

        up_probability = round(self._sigmoid(up_score) * 100, 1)
        bottom_probability = round(self._sigmoid(bottom_score) * 100, 1)
        top_probability = round(self._sigmoid(top_score) * 100, 1)
        down_probability = round(100 - up_probability, 1)
        reversal_signal = "NEUTRAL"
        if bottom_probability >= 65 and up_probability >= 50:
            reversal_signal = "BOTTOM_WATCH"
        elif top_probability >= 65 and up_probability <= 50:
            reversal_signal = "TOP_WATCH"
        elif up_probability >= 60:
            reversal_signal = "UP_BIAS"
        elif up_probability <= 40:
            reversal_signal = "DOWN_BIAS"

        explanation: list[str] = []
        if bottom_probability >= 60:
            explanation.append("Rynek jest mocno wyprzedany i pojawia sie szansa lokalnego dolka.")
        if top_probability >= 60:
            explanation.append("Rynek jest wykupiony i mozliwy jest lokalny szczyt albo schlodzenie.")
        if trend == "UP":
            explanation.append("Trend srednioterminowy pozostaje wzrostowy.")
        elif trend == "DOWN":
            explanation.append("Trend srednioterminowy pozostaje spadkowy.")
        if macd_strength > 0.25:
            explanation.append("Momentum MACD wspiera ruch w gore.")
        elif macd_strength < -0.25:
            explanation.append("Momentum MACD wspiera presje spadkowa.")
        if not explanation:
            explanation.append("Sygnaly sa mieszane i nie ma wyraznej przewagi jednej strony rynku.")

        return {
            "up_probability": up_probability,
            "down_probability": down_probability,
            "bottom_probability": bottom_probability,
            "top_probability": top_probability,
            "reversal_signal": reversal_signal,
            "price_vs_ema20_pct": round(price_vs_ema20 * 100, 2),
            "price_vs_ema50_pct": round(price_vs_ema50 * 100, 2),
            "explanation": explanation,
        }

    def _sigmoid(self, value: float) -> float:
        return 1 / (1 + math.exp(-value))

    def _clip(self, value: float, lower: float, upper: float) -> float:
        return max(lower, min(value, upper))