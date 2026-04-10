"""Bybit perpetual market data service — public endpoints, no auth required.

Fetches derivatives-specific data: funding rates, open interest, mark price,
long/short pressure — data that does NOT exist on spot exchanges.

Optimised: bulk ticker (1 call for ALL symbols) + parallel funding/OI fetches.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

_log = logging.getLogger(__name__)

_BASE = "https://api.bybit.com"
_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 300  # seconds (funding rates / OI change slowly)

# Single thread pool reused across calls (max 10 concurrent connections)
_POOL = ThreadPoolExecutor(max_workers=10)


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


# ---------------------------------------------------------------------------
# Perpetual klines (candlestick data)
# ---------------------------------------------------------------------------

def get_perp_klines(symbol: str, interval: str = "60", limit: int = 200) -> list[dict]:
    """Fetch OHLCV klines for a linear perpetual from Bybit public API.

    Args:
        symbol: e.g. "BTC" (without USDT suffix)
        interval: 1,3,5,15,30,60,120,240,360,720,D,W,M
        limit: max 200

    Returns list of dicts sorted oldest→newest:
        [{time, open, high, low, close, volume, turnover}, ...]
    """
    bybit_sym = f"{symbol}USDT"
    result = _get("/v5/market/kline", {
        "category": "linear", "symbol": bybit_sym, "interval": interval, "limit": limit,
    })
    if not result or not result.get("list"):
        return []
    out = []
    for row in result["list"]:
        try:
            out.append({
                "time": int(row[0]) // 1000,  # ms → unix seconds
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "turnover": float(row[6]),
            })
        except (ValueError, TypeError, IndexError):
            continue
    out.sort(key=lambda x: x["time"])
    return out


# ---------------------------------------------------------------------------
# Bulk ticker — ONE call returns all linear perpetual tickers
# ---------------------------------------------------------------------------
_BULK_TICKER_CACHE: tuple[float, dict[str, dict]] = (0.0, {})


def _fetch_all_linear_tickers() -> dict[str, dict]:
    """Fetch ALL linear perpetual tickers in a single API call.
    Returns {symbol_without_USDT: parsed_ticker_dict}."""
    global _BULK_TICKER_CACHE
    now = time.time()
    if now - _BULK_TICKER_CACHE[0] < _CACHE_TTL and _BULK_TICKER_CACHE[1]:
        return _BULK_TICKER_CACHE[1]

    try:
        resp = requests.get(f"{_BASE}/v5/market/tickers", params={"category": "linear"}, timeout=10)
        data = resp.json()
        if data.get("retCode") != 0:
            _log.warning("Bybit bulk tickers error: %s", data.get("retMsg"))
            return _BULK_TICKER_CACHE[1]  # return stale on error
        tickers_raw = data.get("result", {}).get("list", [])
    except Exception as exc:
        _log.warning("Bybit bulk tickers failed: %s", exc)
        return _BULK_TICKER_CACHE[1]

    result: dict[str, dict] = {}
    for t in tickers_raw:
        raw_symbol = t.get("symbol", "")
        if not raw_symbol.endswith("USDT"):
            continue
        sym = raw_symbol[: -4]  # strip USDT
        try:
            funding_rate = float(t.get("fundingRate", 0))
            next_funding_ms = int(t.get("nextFundingTime", 0))
            next_funding_h = max(0, (next_funding_ms / 1000 - now) / 3600) if next_funding_ms else 0
            result[sym] = {
                "symbol": sym,
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
        except (ValueError, TypeError):
            continue

    _BULK_TICKER_CACHE = (now, result)
    return result


def get_perp_ticker(symbol: str) -> dict | None:
    """Get linear perpetual ticker — served from bulk cache."""
    all_tickers = _fetch_all_linear_tickers()
    ticker = all_tickers.get(symbol)
    if ticker:
        return dict(ticker)  # return a copy so callers can mutate
    return None


def get_batch_perp_tickers(symbols: list[str]) -> dict[str, dict]:
    """Lightweight batch — bulk ticker only (1 API call), no per-symbol enrichment.

    Adds funding_signal and premium_pct from ticker data that's already in the
    bulk response. Use this for the dashboard where speed matters.
    For the leverage engine, use get_batch_perp_snapshots() instead.
    """
    all_tickers = _fetch_all_linear_tickers()
    result: dict[str, dict] = {}
    for sym in symbols:
        t = all_tickers.get(sym)
        if not t:
            continue
        ticker = dict(t)
        # Spread
        if ticker["bid1"] > 0 and ticker["ask1"] > 0:
            ticker["spread_pct"] = round((ticker["ask1"] - ticker["bid1"]) / ticker["ask1"] * 100, 4)
        # Premium
        if ticker["index_price"] > 0:
            ticker["premium_pct"] = round(
                (ticker["mark_price"] - ticker["index_price"]) / ticker["index_price"] * 100, 3
            )
        else:
            ticker["premium_pct"] = 0
        # Funding signal (from ticker data, no extra API call)
        fr = ticker["funding_rate"]
        if fr > 0.0003:
            ticker["funding_signal"] = "HIGH_LONG_COST"
        elif fr > 0.0001:
            ticker["funding_signal"] = "NORMAL_LONG_COST"
        elif fr < -0.0003:
            ticker["funding_signal"] = "HIGH_SHORT_COST"
        elif fr < -0.0001:
            ticker["funding_signal"] = "NORMAL_SHORT_COST"
        else:
            ticker["funding_signal"] = "NEUTRAL"
        # OI trend from bulk data: unavailable without history call, mark as UNKNOWN
        ticker["oi_change_pct"] = 0
        ticker["oi_trend"] = "UNKNOWN"
        ticker["funding_history"] = []
        result[sym] = ticker
    return result


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


def _enrich_snapshot(symbol: str, ticker: dict) -> dict:
    """Add spread, premium, funding signal, OI trend, funding history to a ticker."""
    # Spread calculation
    if ticker["bid1"] > 0 and ticker["ask1"] > 0:
        ticker["spread_pct"] = round((ticker["ask1"] - ticker["bid1"]) / ticker["ask1"] * 100, 4)

    # Mark-index premium
    if ticker["index_price"] > 0:
        ticker["premium_pct"] = round(
            (ticker["mark_price"] - ticker["index_price"]) / ticker["index_price"] * 100, 3
        )
    else:
        ticker["premium_pct"] = 0

    # Funding direction signal
    fr = ticker["funding_rate"]
    if fr > 0.0003:
        ticker["funding_signal"] = "HIGH_LONG_COST"
    elif fr > 0.0001:
        ticker["funding_signal"] = "NORMAL_LONG_COST"
    elif fr < -0.0003:
        ticker["funding_signal"] = "HIGH_SHORT_COST"
    elif fr < -0.0001:
        ticker["funding_signal"] = "NORMAL_SHORT_COST"
    else:
        ticker["funding_signal"] = "NEUTRAL"

    # OI trend
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

    # Funding history
    ticker["funding_history"] = get_funding_history(symbol, 5)

    return ticker


def get_perp_snapshot(symbol: str) -> dict | None:
    """Full perpetual snapshot for a single symbol."""
    ticker = get_perp_ticker(symbol)
    if not ticker:
        return None
    return _enrich_snapshot(symbol, ticker)


def get_batch_perp_snapshots(symbols: list[str]) -> dict[str, dict]:
    """Get perpetual data for multiple symbols — optimised.

    1. Bulk ticker: 1 API call for ALL linear perps (cached 300s).
    2. Parallel enrichment: funding history + OI fetched concurrently.
    """
    all_tickers = _fetch_all_linear_tickers()

    # Filter to requested symbols that exist on Bybit
    to_enrich = {}
    for sym in symbols:
        t = all_tickers.get(sym)
        if t:
            to_enrich[sym] = dict(t)  # copy

    if not to_enrich:
        return {}

    # Parallel enrichment (funding history + OI history per symbol)
    result: dict[str, dict] = {}
    futures = {
        _POOL.submit(_enrich_snapshot, sym, ticker): sym
        for sym, ticker in to_enrich.items()
    }
    for future in as_completed(futures, timeout=15):
        sym = futures[future]
        try:
            result[sym] = future.result()
        except Exception as exc:
            _log.warning("Bybit enrich error for %s: %s", sym, exc)

    return result
