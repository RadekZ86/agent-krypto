from __future__ import annotations

import numpy as np
import pandas as pd

from app.config import settings


def build_indicator_frame(rows: list[object]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(
        {
            "timestamp": [row.timestamp for row in rows],
            "open": [row.open for row in rows],
            "high": [row.high for row in rows],
            "low": [row.low for row in rows],
            "close": [row.close for row in rows],
            "volume": [row.volume for row in rows],
            "source": [row.source for row in rows],
        }
    ).sort_values("timestamp", ascending=True, kind="stable")

    df["ema12"] = df["close"].ewm(span=12, adjust=False).mean()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema26"] = df["close"].ewm(span=26, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["macd"] = df["ema12"] - df["ema26"]
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = (100 - (100 / (1 + rs))).fillna(50.0)
    df["volume_change"] = df["volume"].pct_change().replace([np.inf, -np.inf], 0.0).fillna(0.0)
    # Smoothed volume change (3-bar EMA) — less noisy for probability engine
    df["vol_change_smooth"] = df["volume_change"].ewm(span=3, adjust=False).mean().fillna(0.0)

    one_day_bars = max(1, settings.bars_per_day)
    seven_day_bars = max(1, min(len(df) - 1, 7 * settings.bars_per_day)) if len(df) > 1 else 1
    thirty_day_bars = max(1, min(len(df) - 1, 30 * settings.bars_per_day)) if len(df) > 1 else 1
    volatility_window = max(10, min(len(df), 14 * settings.bars_per_day))

    df["change_24h"] = (df["close"].pct_change(one_day_bars).replace([np.inf, -np.inf], 0.0).fillna(0.0) * 100)
    df["change_7d"] = (df["close"].pct_change(seven_day_bars).replace([np.inf, -np.inf], 0.0).fillna(0.0) * 100)
    df["change_30d"] = (df["close"].pct_change(thirty_day_bars).replace([np.inf, -np.inf], 0.0).fillna(0.0) * 100)
    df["volatility_14d"] = (
        df["close"].pct_change().rolling(volatility_window, min_periods=max(5, volatility_window // 4)).std(ddof=0).fillna(0.0)
        * 100
    )
    df["ema_gap_pct"] = (((df["ema20"] - df["ema50"]) / df["ema50"].replace(0, np.nan)).fillna(0.0) * 100)
    # Trend classification with hysteresis to prevent thrashing:
    # Enter UP: gap > +0.15%  |  Exit UP (to SIDEWAYS): gap < +0.05%
    # Enter DOWN: gap < -0.15%  |  Exit DOWN (to SIDEWAYS): gap > -0.05%
    _trend_vals = ["SIDEWAYS"] * len(df)
    _prev_trend = "SIDEWAYS"
    for _ti in range(len(df)):
        _gap = df["ema_gap_pct"].iat[_ti]
        if _prev_trend == "UP":
            if _gap < -0.15:
                _prev_trend = "DOWN"
            elif _gap < 0.05:
                _prev_trend = "SIDEWAYS"
        elif _prev_trend == "DOWN":
            if _gap > 0.15:
                _prev_trend = "UP"
            elif _gap > -0.05:
                _prev_trend = "SIDEWAYS"
        else:  # SIDEWAYS
            if _gap > 0.15:
                _prev_trend = "UP"
            elif _gap < -0.15:
                _prev_trend = "DOWN"
        _trend_vals[_ti] = _prev_trend
    df["trend"] = _trend_vals

    # ── Bollinger Bands (20-period SMA ± 2 std dev) ──
    df["sma20"] = df["close"].rolling(window=20, min_periods=10).mean()
    rolling_std = df["close"].rolling(window=20, min_periods=10).std(ddof=0)
    df["bb_upper"] = df["sma20"] + 2 * rolling_std
    df["bb_lower"] = df["sma20"] - 2 * rolling_std

    # ── VWAP (cumulative TypicalPrice*Volume / cumulative Volume) ──
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cum_tp_vol = (typical_price * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum().replace(0, np.nan)
    df["vwap"] = (cum_tp_vol / cum_vol).fillna(df["close"])

    # ── Whale / anomaly indicators ──
    from app.services.whale_detector import compute_whale_indicators
    df = compute_whale_indicators(df)

    return df.reset_index(drop=True)