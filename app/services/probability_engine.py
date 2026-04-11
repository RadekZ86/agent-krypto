from __future__ import annotations

import math
from typing import Any

import pandas as pd


class ProbabilityEngine:
    """Multi-factor probability estimator with normalized inputs.

    Architecture:
    - 4 independent signal tiers (trend, momentum, mean-reversion, volume)
    - Each tier produces a normalized [-1, +1] sub-score
    - Tiers combined with configurable weights → sigmoid → probability
    - Avoids double-counting by keeping tiers orthogonal
    """

    # ── Tier weights (sum ≈ 1 for interpretability) ──
    W_TREND = 0.30       # EMA alignment + direction
    W_MOMENTUM = 0.30    # MACD crossover + histogram acceleration
    W_REVERSION = 0.25   # RSI extremes + Bollinger position
    W_VOLUME = 0.15      # Volume confirmation + momentum change

    # ── Calibration offset: shift sigmoid center so 50% = truly neutral ──
    # Positive bias → more conservative BUY, negative → more aggressive
    CALIBRATION_OFFSET = -0.05

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
        vol_smooth = float(latest.get("vol_change_smooth", volume_change))
        change_24h = float(latest.get("change_24h", 0.0))
        change_7d = float(latest.get("change_7d", 0.0))
        trend = str(latest.get("trend", "SIDEWAYS"))
        bb_upper = float(latest.get("bb_upper", close))
        bb_lower = float(latest.get("bb_lower", close))

        # ── Tier 1: TREND (EMA alignment + price position) ──
        price_vs_ema20 = (close - ema20) / ema20 if ema20 else 0.0
        price_vs_ema50 = (close - ema50) / ema50 if ema50 else 0.0
        ema_alignment = (ema20 - ema50) / ema50 if ema50 else 0.0
        trend_score = self._clip(
            ema_alignment * 40              # EMA gap normalized: 2.5% gap → +1.0
            + price_vs_ema20 * 15           # How far above/below EMA20
            + price_vs_ema50 * 8,           # Broader trend context
            -2.0, 2.0
        )

        # ── Tier 2: MOMENTUM (MACD + histogram acceleration) ──
        # Normalize MACD by price to make it comparable across assets
        macd_norm = ((macd - macd_signal) / close * 100) if close else 0.0
        hist_accel = (hist_slope / close * 100) if close else 0.0
        momentum_score = self._clip(
            macd_norm * 12                  # MACD diff normalized: 0.08% → +1.0
            + hist_accel * 20               # Histogram acceleration
            + self._clip(change_24h / 5, -1.0, 1.0) * 0.5   # Short-term momentum
            + self._clip(change_7d / 12, -0.8, 0.8) * 0.3,   # Weekly context
            -2.0, 2.0
        )

        # ── Tier 3: MEAN-REVERSION (RSI + Bollinger position) ──
        # RSI: normalize to [-1, +1] centered on 50
        rsi_norm = (rsi - 50) / 25  # RSI 25 → -1.0, RSI 75 → +1.0
        # Bollinger position: 0 = lower band, 1 = upper band
        bb_range = bb_upper - bb_lower if bb_upper != bb_lower else 1.0
        bb_pos = (close - bb_lower) / bb_range if bb_range > 0 else 0.5
        bb_norm = (bb_pos - 0.5) * 2  # [-1, +1]

        # For UP probability: oversold (low RSI) is bullish (inverted)
        reversion_up = self._clip(
            -rsi_norm * 1.2                 # Low RSI = high up probability
            - bb_norm * 0.6,                # Near lower band = up potential
            -2.0, 2.0
        )
        # For bottom/top detection: use raw extremes
        bottom_score_raw = self._clip(
            -rsi_norm * 1.5                 # Very low RSI → strong bottom signal
            - bb_norm * 0.8                 # Near/below lower BB
            + hist_accel * 15,              # Histogram turning up from negative
            -2.0, 2.5
        )
        top_score_raw = self._clip(
            rsi_norm * 1.5                  # Very high RSI → strong top signal
            + bb_norm * 0.8                 # Near upper BB
            - hist_accel * 15,              # Histogram turning down from positive
            -2.0, 2.5
        )

        # ── Tier 4: VOLUME CONFIRMATION ──
        # Use smoothed volume change when available (less noisy)
        vol_factor = self._clip(vol_smooth * 2.5, -1.5, 1.5)
        # Volume confirms the dominant direction
        volume_score = vol_factor * (1.0 if trend_score > 0 else -0.5 if trend_score < 0 else 0.3)

        # ── Combine tiers for UP probability ──
        up_raw = (
            trend_score * self.W_TREND
            + momentum_score * self.W_MOMENTUM
            + reversion_up * self.W_REVERSION
            + volume_score * self.W_VOLUME
            + self.CALIBRATION_OFFSET
        )

        # ── Apply sigmoid with steepness control ──
        up_probability = round(self._sigmoid(up_raw * 2.5) * 100, 1)
        bottom_probability = round(self._sigmoid(bottom_score_raw * 1.8) * 100, 1)
        top_probability = round(self._sigmoid(top_score_raw * 1.8) * 100, 1)
        down_probability = round(100 - up_probability, 1)

        # ── Clamp to realistic range [15%, 85%] — no model should claim 95% certainty ──
        up_probability = max(15.0, min(85.0, up_probability))
        down_probability = max(15.0, min(85.0, down_probability))
        bottom_probability = max(10.0, min(88.0, bottom_probability))
        top_probability = max(10.0, min(88.0, top_probability))

        reversal_signal = "NEUTRAL"
        if bottom_probability >= 62 and up_probability >= 48:
            reversal_signal = "BOTTOM_WATCH"
        elif top_probability >= 62 and up_probability <= 52:
            reversal_signal = "TOP_WATCH"
        elif up_probability >= 58:
            reversal_signal = "UP_BIAS"
        elif up_probability <= 42:
            reversal_signal = "DOWN_BIAS"

        # ── Tier breakdown for explainability ──
        explanation: list[str] = []
        dominant_tier = max(
            [("trend", abs(trend_score)), ("momentum", abs(momentum_score)),
             ("reversion", abs(reversion_up)), ("volume", abs(volume_score))],
            key=lambda x: x[1]
        )[0]

        if bottom_probability >= 58:
            explanation.append("Rynek jest mocno wyprzedany i pojawia sie szansa lokalnego dolka.")
        if top_probability >= 58:
            explanation.append("Rynek jest wykupiony i mozliwy jest lokalny szczyt albo schlodzenie.")
        if trend_score > 0.5:
            explanation.append("Trend srednioterminowy pozostaje wzrostowy.")
        elif trend_score < -0.5:
            explanation.append("Trend srednioterminowy pozostaje spadkowy.")
        if momentum_score > 0.5:
            explanation.append("Momentum MACD wspiera ruch w gore.")
        elif momentum_score < -0.5:
            explanation.append("Momentum MACD wspiera presje spadkowa.")
        if abs(vol_smooth) > 0.15:
            dir_label = "rosnacy" if vol_smooth > 0 else "malejacy"
            explanation.append(f"Wolumen {dir_label} potwierdza kierunek ruchu.")
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
            "dominant_factor": dominant_tier,
            "tier_scores": {
                "trend": round(trend_score, 3),
                "momentum": round(momentum_score, 3),
                "reversion": round(reversion_up, 3),
                "volume": round(volume_score, 3),
            },
            "explanation": explanation,
        }

    def _sigmoid(self, value: float) -> float:
        clamped = max(-10, min(10, value))
        return 1 / (1 + math.exp(-clamped))

    def _clip(self, value: float, lower: float, upper: float) -> float:
        return max(lower, min(value, upper))