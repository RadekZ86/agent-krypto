"""Bybit perpetual market data service — public endpoints, no auth required.

Fetches derivatives-specific data: funding rates, open interest, mark price,
long/short pressure — data that does NOT exist on spot exchanges.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

_log = logging.getLogger(__name__)

_BASE = "https://api.bybit.com"
_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 120  # seconds


def _get(path: str, params: dict) -> dict | None:
    """Simple GET with caching and error handling."""
    cache_key = f"{path}:{sorted(params.items())}"
    now = time.time()
    cached = _CACHE.get(cache_key)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]
    try:
        resp = requests.get(f"{_BASE}{path}", params=params, timeout=8)
        data = resp.json()
        if data.get("retCode") != 0:
            _log.warning("Bybit public API %s error: %s", path, data.get("retMsg"))
            return None
        result = data.get("result")
        _CACHE[cache_key] = (now, result)
        return result
    except Exception as exc:
        _log.warning("Bybit public API %s failed: %s", path, exc)
        return None


def get_perp_ticker(symbol: str) -> dict | None:
    """Get linear perpetual ticker with funding rate, open interest, mark price."""
    bybit_sym = f"{symbol}USDT"
    result = _get("/v5/market/tickers", {"category": "linear", "symbol": bybit_sym})
    if not result or not result.get("list"):
        return None
    t = result["list"][0]
    try:
        funding_rate = float(t.get("fundingRate", 0))
        next_funding_ms = int(t.get("nextFundingTime", 0))
        next_funding_h = max(0, (next_funding_ms / 1000 - time.time()) / 3600) if next_funding_ms else 0

        return {
            "symbol": symbol,
            "last_price": float(t.get("lastPrice", 0)),
            "mark_price": float(t.get("markPrice", 0)),
            "index_price": float(t.get("indexPrice", 0)),
            "price_24h_pct": float(t.get("price24hPcnt", 0)) * 100,
            "high_24h": float(t.get("highPrice24h", 0)),
            "low_24h": float(t.get("lowPrice24h", 0)),
            "volume_24h": float(t.get("volume24h", 0)),
            "turnover_24h": float(t.get("turnover24h", 0)),
            "open_interest": float(t.get("openInterest", 0)),
            "open_interest_value": float(t.get("openInterestValue", 0)),
            "funding_rate": funding_rate,
            "funding_rate_pct": round(funding_rate * 100, 4),
            "next_funding_hours": round(next_funding_h, 1),
            "bid1": float(t.get("bid1Price", 0)),
            "ask1": float(t.get("ask1Price", 0)),
            "spread_pct": 0,
        }
    except (ValueError, TypeError) as exc:
        _log.warning("Bybit ticker parse error for %s: %s", symbol, exc)
        return None


def get_funding_history(symbol: str, limit: int = 10) -> list[dict]:
    """Get recent funding rate history."""
    bybit_sym = f"{symbol}USDT"
    result = _get("/v5/market/funding/history", {
        "category": "linear", "symbol": bybit_sym, "limit": limit,
    })
    if not result or not result.get("list"):
        return []
    out = []
    for r in result["list"]:
        try:
            out.append({
                "rate": float(r.get("fundingRate", 0)),
                "rate_pct": round(float(r.get("fundingRate", 0)) * 100, 4),
                "timestamp": int(r.get("fundingRateTimestamp", 0)),
            })
        except (ValueError, TypeError):
            pass
    return out


def get_open_interest_history(symbol: str, interval: str = "1h", limit: int = 10) -> list[dict]:
    """Get open interest history."""
    bybit_sym = f"{symbol}USDT"
    result = _get("/v5/market/open-interest", {
        "category": "linear", "symbol": bybit_sym, "intervalTime": interval, "limit": limit,
    })
    if not result or not result.get("list"):
        return []
    out = []
    for r in result["list"]:
        try:
            out.append({
                "open_interest": float(r.get("openInterest", 0)),
                "timestamp": int(r.get("timestamp", 0)),
            })
        except (ValueError, TypeError):
            pass
    return out


def get_perp_snapshot(symbol: str) -> dict | None:
    """Full perpetual snapshot for a symbol — combines ticker + funding + OI trends.

    Returns extra signals for the leverage engine:
    - funding_rate & direction (positive = longs pay shorts)
    - open_interest change trend (rising/falling)
    - mark vs index price premium/discount
    - bid-ask spread
    """
    ticker = get_perp_ticker(symbol)
    if not ticker:
        return None

    # Spread calculation
    if ticker["bid1"] > 0 and ticker["ask1"] > 0:
        ticker["spread_pct"] = round((ticker["ask1"] - ticker["bid1"]) / ticker["ask1"] * 100, 4)

    # Mark-index premium — when mark > index = longs dominant, shorts pay less
    if ticker["index_price"] > 0:
        ticker["premium_pct"] = round(
            (ticker["mark_price"] - ticker["index_price"]) / ticker["index_price"] * 100, 3
        )
    else:
        ticker["premium_pct"] = 0

    # Funding direction signal
    fr = ticker["funding_rate"]
    if fr > 0.0003:
        ticker["funding_signal"] = "HIGH_LONG_COST"  # longs pay a lot — crowded long
    elif fr > 0.0001:
        ticker["funding_signal"] = "NORMAL_LONG_COST"
    elif fr < -0.0003:
        ticker["funding_signal"] = "HIGH_SHORT_COST"  # shorts pay — crowded short
    elif fr < -0.0001:
        ticker["funding_signal"] = "NORMAL_SHORT_COST"
    else:
        ticker["funding_signal"] = "NEUTRAL"

    # OI trend (compare latest 2 values)
    oi_history = get_open_interest_history(symbol, "1h", 3)
    if len(oi_history) >= 2:
        oi_now = oi_history[0]["open_interest"]
        oi_prev = oi_history[1]["open_interest"]
        if oi_prev > 0:
            oi_change_pct = (oi_now - oi_prev) / oi_prev * 100
            ticker["oi_change_pct"] = round(oi_change_pct, 2)
            ticker["oi_trend"] = "RISING" if oi_change_pct > 1 else ("FALLING" if oi_change_pct < -1 else "STABLE")
        else:
            ticker["oi_change_pct"] = 0
            ticker["oi_trend"] = "STABLE"
    else:
        ticker["oi_change_pct"] = 0
        ticker["oi_trend"] = "UNKNOWN"

    # Funding history (last few)
    ticker["funding_history"] = get_funding_history(symbol, 5)

    return ticker


def get_batch_perp_snapshots(symbols: list[str]) -> dict[str, dict]:
    """Get perpetual data for multiple symbols. Returns {symbol: snapshot}."""
    result = {}
    for sym in symbols:
        snap = get_perp_snapshot(sym)
        if snap:
            result[sym] = snap
    return result
