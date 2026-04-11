"""Whale & anomaly detection service.

Detects large-volume events, price spikes, and unusual market activity
from candle data and Binance aggregate trades.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Thresholds ──
VOLUME_ZSCORE_THRESHOLD = 2.5       # Std deviations above mean volume
VOLUME_SPIKE_MULTIPLIER = 3.0       # Volume > 3x rolling average
PRICE_SPIKE_PCT = 3.0               # Sudden price move > 3%
LARGE_TRADE_PCT_OF_AVG_VOL = 5.0    # Single trade > 5% of avg bar volume
OBV_DIVERGENCE_BARS = 5             # Bars to check for OBV divergence


def compute_whale_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add whale/anomaly columns to the indicator DataFrame.
    Must be called after build_indicator_frame() so OHLCV + EMA columns exist."""
    if df.empty or len(df) < 20:
        return df

    vol = df["volume"]

    # ── On-Balance Volume (OBV) ──
    obv_direction = np.where(df["close"] > df["close"].shift(1), 1,
                    np.where(df["close"] < df["close"].shift(1), -1, 0))
    df["obv"] = (vol * obv_direction).cumsum()

    # ── Volume rolling stats ──
    vol_window = min(20, len(df) - 1)
    df["vol_sma20"] = vol.rolling(window=vol_window, min_periods=5).mean()
    df["vol_std20"] = vol.rolling(window=vol_window, min_periods=5).std(ddof=0)
    df["vol_zscore"] = ((vol - df["vol_sma20"]) / df["vol_std20"].replace(0, np.nan)).fillna(0)
    df["vol_ratio"] = (vol / df["vol_sma20"].replace(0, np.nan)).fillna(1)

    # ── Price spike detection (bar-over-bar) ──
    df["price_change_pct"] = (df["close"].pct_change() * 100).fillna(0)
    df["bar_range_pct"] = (((df["high"] - df["low"]) / df["low"].replace(0, np.nan)) * 100).fillna(0)
    avg_range = df["bar_range_pct"].rolling(window=vol_window, min_periods=5).mean()
    df["range_ratio"] = (df["bar_range_pct"] / avg_range.replace(0, np.nan)).fillna(1)

    # ── Composite whale score (0-10) ──
    df["whale_score"] = _compute_whale_score(df)

    # ── Whale signal classification ──
    df["whale_signal"] = df.apply(_classify_whale_signal, axis=1)

    return df


def _compute_whale_score(df: pd.DataFrame) -> pd.Series:
    """Compute a 0-10 whale activity score per bar."""
    score = pd.Series(0.0, index=df.index)

    # Volume Z-score contribution (0-3)
    score += np.clip(df["vol_zscore"] / VOLUME_ZSCORE_THRESHOLD * 2, 0, 3)

    # Volume ratio contribution (0-3)
    score += np.clip((df["vol_ratio"] - 1) / (VOLUME_SPIKE_MULTIPLIER - 1) * 2, 0, 3)

    # Price spike contribution (0-2)
    score += np.clip(df["price_change_pct"].abs() / PRICE_SPIKE_PCT * 1.5, 0, 2)

    # Bar range anomaly (0-2)
    score += np.clip((df["range_ratio"] - 1) / 2, 0, 2)

    return score.clip(0, 10).round(2)


def _classify_whale_signal(row) -> str:
    """Classify the whale signal for a single bar."""
    ws = row["whale_score"]
    vol_z = row["vol_zscore"]
    price_chg = row["price_change_pct"]
    vol_ratio = row["vol_ratio"]

    if ws < 2.0:
        return "NONE"

    # Strong whale activity
    if ws >= 6.0:
        if price_chg > 0:
            return "WHALE_BUY"
        elif price_chg < 0:
            return "WHALE_SELL"
        else:
            return "WHALE_ACCUMULATE"

    # Moderate anomaly
    if vol_z >= VOLUME_ZSCORE_THRESHOLD:
        if price_chg > PRICE_SPIKE_PCT * 0.5:
            return "SPIKE_UP"
        elif price_chg < -PRICE_SPIKE_PCT * 0.5:
            return "SPIKE_DOWN"
        return "VOL_ANOMALY"

    if vol_ratio >= VOLUME_SPIKE_MULTIPLIER * 0.7:
        return "HIGH_VOLUME"

    if abs(price_chg) >= PRICE_SPIKE_PCT * 0.7:
        return "PRICE_ANOMALY"

    return "MILD_ANOMALY"


def detect_obv_divergence(df: pd.DataFrame) -> str:
    """Check for OBV divergence (smart money vs price).

    Uses linear regression slope over recent bars for more robust detection.
    Requires minimum magnitude threshold to avoid noise.
    Returns: 'BULLISH_DIV', 'BEARISH_DIV', or 'NONE'."""
    if len(df) < OBV_DIVERGENCE_BARS + 2 or "obv" not in df.columns:
        return "NONE"

    recent = df.tail(OBV_DIVERGENCE_BARS)
    prices = recent["close"].values
    obvs = recent["obv"].values

    if len(prices) < 3:
        return "NONE"

    # Linear regression slopes (more robust than start-end comparison)
    x = np.arange(len(prices), dtype=float)
    x_mean = x.mean()
    price_slope = np.sum((x - x_mean) * (prices - prices.mean())) / max(np.sum((x - x_mean) ** 2), 1e-10)
    obv_slope = np.sum((x - x_mean) * (obvs - obvs.mean())) / max(np.sum((x - x_mean) ** 2), 1e-10)

    # Normalize slopes for magnitude comparison
    avg_price = np.mean(np.abs(prices)) if np.any(prices != 0) else 1.0
    avg_obv = np.mean(np.abs(obvs)) if np.any(obvs != 0) else 1.0
    price_slope_norm = price_slope / avg_price if avg_price > 0 else 0
    obv_slope_norm = obv_slope / avg_obv if avg_obv > 0 else 0

    # Require minimum divergence magnitude (avoid noise)
    MIN_SLOPE_MAGNITUDE = 0.002  # 0.2% per bar minimum

    if abs(price_slope_norm) < MIN_SLOPE_MAGNITUDE and abs(obv_slope_norm) < MIN_SLOPE_MAGNITUDE:
        return "NONE"

    # Price down but OBV up → smart money accumulating (bullish)
    if price_slope_norm < -MIN_SLOPE_MAGNITUDE and obv_slope_norm > MIN_SLOPE_MAGNITUDE:
        return "BULLISH_DIV"
    # Price up but OBV down → smart money distributing (bearish)
    if price_slope_norm > MIN_SLOPE_MAGNITUDE and obv_slope_norm < -MIN_SLOPE_MAGNITUDE:
        return "BEARISH_DIV"

    return "NONE"


def analyze_large_trades(trades: list[dict], avg_bar_volume: float) -> list[dict]:
    """Analyze aggregate trades from Binance for whale activity.
    trades: list from Binance /api/v3/aggTrades
    Returns list of detected whale trades."""
    if not trades or avg_bar_volume <= 0:
        return []

    threshold = avg_bar_volume * (LARGE_TRADE_PCT_OF_AVG_VOL / 100)
    whale_trades = []

    for t in trades:
        qty = float(t.get("q", 0))
        price = float(t.get("p", 0))
        value = qty * price
        if qty >= threshold or value >= threshold:
            whale_trades.append({
                "trade_id": t.get("a"),
                "price": price,
                "quantity": qty,
                "value": round(value, 2),
                "is_buyer": not t.get("m", True),  # m=True means maker was seller → taker was buyer
                "timestamp": t.get("T"),
                "pct_of_avg_vol": round(qty / avg_bar_volume * 100, 2) if avg_bar_volume > 0 else 0,
            })

    return whale_trades


def build_whale_summary(df: pd.DataFrame, whale_trades: list[dict] | None = None) -> dict[str, Any]:
    """Build a summary of whale/anomaly signals for the latest bar."""
    if df.empty or "whale_score" not in df.columns:
        return _empty_summary()

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    obv_div = detect_obv_divergence(df)

    # Count recent anomaly bars (last 10)
    recent = df.tail(10)
    anomaly_count = int((recent["whale_score"] >= 2.0).sum())

    alerts: list[str] = []
    signal = str(latest["whale_signal"])
    ws = float(latest["whale_score"])

    if signal.startswith("WHALE_"):
        alerts.append(f"Wykryto aktywnosc wieloryba: {signal} (score {ws:.1f})")
    if signal in ("SPIKE_UP", "SPIKE_DOWN"):
        alerts.append(f"Nagly ruch cenowy: {latest['price_change_pct']:.1f}% przy wolumenie {latest['vol_ratio']:.1f}x sredniej")
    if signal == "VOL_ANOMALY":
        alerts.append(f"Anomalia wolumenu: {latest['vol_zscore']:.1f} sigma ponad srednia")
    if obv_div == "BULLISH_DIV":
        alerts.append("OBV dywergencja bycza: smart money akumuluje mimo spadku ceny")
    elif obv_div == "BEARISH_DIV":
        alerts.append("OBV dywergencja niedzwiedzia: smart money dystrybuuje mimo wzrostu ceny")

    if whale_trades:
        buy_trades = [t for t in whale_trades if t["is_buyer"]]
        sell_trades = [t for t in whale_trades if not t["is_buyer"]]
        if buy_trades:
            alerts.append(f"Duze zakupy: {len(buy_trades)} transakcji wielorybow (kupno)")
        if sell_trades:
            alerts.append(f"Duza sprzedaz: {len(sell_trades)} transakcji wielorybow (sprzedaz)")

    return {
        "whale_score": round(ws, 2),
        "whale_signal": signal,
        "obv_divergence": obv_div,
        "vol_zscore": round(float(latest["vol_zscore"]), 2),
        "vol_ratio": round(float(latest["vol_ratio"]), 2),
        "price_change_pct": round(float(latest["price_change_pct"]), 2),
        "range_ratio": round(float(latest["range_ratio"]), 2),
        "obv": round(float(latest["obv"]), 2),
        "anomaly_bars_10": anomaly_count,
        "whale_trades_count": len(whale_trades) if whale_trades else 0,
        "alerts": alerts,
    }


def _empty_summary() -> dict[str, Any]:
    return {
        "whale_score": 0, "whale_signal": "NONE", "obv_divergence": "NONE",
        "vol_zscore": 0, "vol_ratio": 1, "price_change_pct": 0,
        "range_ratio": 1, "obv": 0, "anomaly_bars_10": 0,
        "whale_trades_count": 0, "alerts": [],
    }
