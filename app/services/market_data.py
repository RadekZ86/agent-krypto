from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import requests
from dateutil import parser
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import MarketData


SOURCE_PRIORITY = {
    "demo": 0,
    "coingecko": 1,
    "coinbase": 2,
    "binance": 3,
}


def normalize_market_timestamp(timestamp: datetime) -> datetime:
    interval = _market_interval_delta()
    seconds = max(1, int(interval.total_seconds()))
    epoch = datetime(1970, 1, 1)
    bucket = int((timestamp - epoch).total_seconds() // seconds) * seconds
    return epoch + timedelta(seconds=bucket)


def _market_interval_delta() -> timedelta:
    mapping = {
        "15m": timedelta(minutes=15),
        "30m": timedelta(minutes=30),
        "1h": timedelta(hours=1),
        "2h": timedelta(hours=2),
        "4h": timedelta(hours=4),
        "6h": timedelta(hours=6),
        "8h": timedelta(hours=8),
        "12h": timedelta(hours=12),
        "1d": timedelta(days=1),
    }
    return mapping.get(settings.market_interval, timedelta(hours=1))


def _market_row_preference_key(row: MarketData) -> tuple[int, datetime, int]:
    return (
        SOURCE_PRIORITY.get(row.source, 0),
        row.timestamp,
        int(getattr(row, "id", 0) or 0),
    )


def _preferred_rows_by_bucket(rows: list[MarketData]) -> list[MarketData]:
    preferred_by_bucket: dict[datetime, MarketData] = {}
    for row in rows:
        bucket = normalize_market_timestamp(row.timestamp)
        existing = preferred_by_bucket.get(bucket)
        if existing is None or _market_row_preference_key(row) >= _market_row_preference_key(existing):
            preferred_by_bucket[bucket] = row
    return [row for _, row in sorted(preferred_by_bucket.items(), key=lambda item: item[0])]


def load_symbol_market_rows(session: Session, symbol: str, limit: int | None = None) -> list[MarketData]:
    if limit is None:
        rows = session.execute(
            select(MarketData)
            .where(MarketData.symbol == symbol)
            .order_by(MarketData.timestamp.asc(), MarketData.id.asc())
        ).scalars().all()

        return _preferred_rows_by_bucket(rows)

    batch_size = max(limit * max(len(SOURCE_PRIORITY), 2), 200)
    offset = 0
    preferred_by_bucket: dict[datetime, MarketData] = {}

    while len(preferred_by_bucket) < limit:
        batch = session.execute(
            select(MarketData)
            .where(MarketData.symbol == symbol)
            .order_by(MarketData.timestamp.desc(), MarketData.id.desc())
            .offset(offset)
            .limit(batch_size)
        ).scalars().all()
        if not batch:
            break

        for row in batch:
            bucket = normalize_market_timestamp(row.timestamp)
            existing = preferred_by_bucket.get(bucket)
            if existing is None or _market_row_preference_key(row) >= _market_row_preference_key(existing):
                preferred_by_bucket[bucket] = row

        offset += batch_size

    normalized = [row for _, row in sorted(preferred_by_bucket.items(), key=lambda item: item[0])]
    return normalized[-limit:]


def load_latest_market_row(session: Session, symbol: str) -> MarketData | None:
    """Return the single most recent preferred MarketData row for *symbol*."""
    row = session.execute(
        select(MarketData)
        .where(MarketData.symbol == symbol)
        .order_by(MarketData.timestamp.desc(), MarketData.id.desc())
        .limit(1)
    ).scalars().first()
    return row


class MarketDataService:
    def __init__(self) -> None:
        self.coingecko_base_url = "https://api.coingecko.com/api/v3"
        self.binance_base_url = "https://api.binance.com/api/v3"
        self.coinbase_base_url = "https://api.exchange.coinbase.com"

    def update_symbol(self, session: Session, symbol: str) -> dict[str, float | str | datetime]:
        try:
            records = self._fetch_live_series(symbol)
        except (requests.RequestException, ValueError):
            records = self._generate_demo_series(session, symbol)

        self._persist_records(session, symbol, records)
        latest = records[-1]
        return {
            "symbol": symbol,
            "timestamp": latest["timestamp"],
            "close": latest["close"],
            "volume": latest["volume"],
            "source": latest["source"],
        }

    def _fetch_live_series(self, symbol: str) -> list[dict[str, float | datetime | str]]:
        fetchers = [
            self._fetch_binance_series,
            self._fetch_coinbase_series,
            self._fetch_coingecko_series,
        ]
        last_error: Exception | None = None
        for fetcher in fetchers:
            try:
                records = fetcher(symbol)
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                continue
            if records:
                return records
        raise ValueError(f"Brak live danych dla {symbol}: {last_error}")

    def _fetch_binance_series(self, symbol: str) -> list[dict[str, float | datetime | str]]:
        pair = settings.binance_symbols.get(symbol, f"{symbol}{settings.exchange_quote_currency}")
        rows: list[list[object]] = []
        remaining = max(1, settings.history_bars)
        end_time: int | None = None
        interval_ms = max(60_000, int(self._interval_delta().total_seconds() * 1000))

        while remaining > 0:
            limit = min(remaining, 1000)
            params = {"symbol": pair, "interval": settings.market_interval, "limit": limit}
            if end_time is not None:
                params["endTime"] = end_time

            response = requests.get(
                f"{self.binance_base_url}/klines",
                params=params,
                timeout=20,
            )
            response.raise_for_status()
            batch = response.json()
            if not batch:
                break

            rows = batch + rows
            remaining -= len(batch)
            first_open_time = int(batch[0][0])
            if len(batch) < limit:
                break
            end_time = first_open_time - interval_ms

        if not rows:
            raise ValueError(f"Brak danych Binance dla {symbol}")

        if len(rows) > settings.history_bars:
            rows = rows[-settings.history_bars :]

        records: list[dict[str, float | datetime | str]] = []
        for row in rows:
            timestamp = datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC).replace(tzinfo=None)
            records.append(
                {
                    "timestamp": timestamp,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[7]) if float(row[7]) > 0 else float(row[5]),
                    "source": "binance",
                }
            )
        return records

    def _fetch_coinbase_series(self, symbol: str) -> list[dict[str, float | datetime | str]]:
        product = settings.coinbase_products.get(symbol)
        if product is None:
            raise ValueError(f"Brak produktu Coinbase dla {symbol}")

        granularity = self._coinbase_granularity()
        end_time = datetime.now(tz=UTC)
        start_time = end_time - timedelta(seconds=granularity * settings.history_bars)
        response = requests.get(
            f"{self.coinbase_base_url}/products/{product}/candles",
            params={
                "granularity": granularity,
                "start": start_time.isoformat().replace("+00:00", "Z"),
                "end": end_time.isoformat().replace("+00:00", "Z"),
            },
            headers={"Accept": "application/json"},
            timeout=20,
        )
        response.raise_for_status()
        rows = response.json()
        if not rows:
            raise ValueError(f"Brak danych Coinbase dla {symbol}")

        records: list[dict[str, float | datetime | str]] = []
        for row in sorted(rows, key=lambda item: item[0]):
            timestamp = datetime.fromtimestamp(int(row[0]), tz=UTC).replace(tzinfo=None)
            records.append(
                {
                    "timestamp": timestamp,
                    "open": float(row[3]),
                    "high": float(row[2]),
                    "low": float(row[1]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "source": "coinbase",
                }
            )
        return records

    def _fetch_coingecko_series(self, symbol: str) -> list[dict[str, float | datetime | str]]:
        coin_id = settings.coingecko_ids[symbol]
        days = max(2, min(settings.history_days, max(2, settings.history_bars // max(1, settings.bars_per_day) + 2)))
        response = requests.get(
            f"{self.coingecko_base_url}/coins/{coin_id}/market_chart",
            params={"vs_currency": settings.quote_currency.lower(), "days": days},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        price_rows = payload.get("prices", [])[-settings.history_bars :]
        volume_rows = payload.get("total_volumes", [])[-settings.history_bars :]
        if not price_rows:
            raise ValueError(f"Brak danych CoinGecko dla {symbol}")

        volume_by_timestamp = {
            datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC).replace(minute=0, second=0, microsecond=0).replace(tzinfo=None): float(row[1])
            for row in volume_rows
        }

        records: list[dict[str, float | datetime | str]] = []
        previous_close: float | None = None
        for row in price_rows:
            timestamp = datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC).replace(minute=0, second=0, microsecond=0).replace(tzinfo=None)
            close_price = float(row[1])
            open_price = previous_close if previous_close is not None else close_price
            records.append(
                {
                    "timestamp": timestamp,
                    "open": float(open_price),
                    "high": float(max(open_price, close_price)),
                    "low": float(min(open_price, close_price)),
                    "close": close_price,
                    "volume": float(volume_by_timestamp.get(timestamp, 0.0)),
                    "source": "coingecko",
                }
            )
            previous_close = close_price

        return records

    def _generate_demo_series(self, session: Session, symbol: str) -> list[dict[str, float | datetime | str]]:
        seed = sum(ord(char) for char in symbol)
        generator = np.random.default_rng(seed)
        # Realistic fallback prices (USD) for all tracked coins.
        # Used ONLY when no real market data exists yet for a symbol.
        base_prices = {
            "BTC": 84000.0, "ETH": 1900.0, "BNB": 590.0, "SOL": 165.0,
            "XRP": 0.60, "ADA": 0.35, "DOGE": 0.17, "TRX": 0.24,
            "AVAX": 22.0, "DOT": 4.3, "LINK": 14.0, "TON": 3.5,
            "SUI": 2.2, "LTC": 84.0, "BCH": 340.0, "ATOM": 4.8,
            "UNI": 6.0, "NEAR": 2.6, "APT": 5.3, "ETC": 16.0,
            "XLM": 0.27, "HBAR": 0.17, "FIL": 2.8, "ARB": 0.35,
            "AAVE": 180.0, "OP": 0.70, "INJ": 9.0, "ICP": 7.5,
            "VET": 0.025, "ALGO": 0.20, "SHIB": 0.000012, "PEPE": 0.0000070,
            "SEI": 0.20, "FET": 0.55, "RENDER": 4.2, "WLD": 0.85,
            "KAS": 0.035, "MNT": 0.72, "PYTH": 0.15, "RUNE": 1.3,
        }
        base_price = base_prices.get(symbol, 1.0)

        # If we already have real (non-demo) market data for this symbol,
        # use its last close price as the base to avoid wild price jumps.
        last_real = session.execute(
            select(MarketData.close)
            .where(MarketData.symbol == symbol, MarketData.source != "demo")
            .order_by(MarketData.timestamp.desc())
            .limit(1)
        ).scalar()
        if last_real is not None and last_real > 0:
            base_price = float(last_real)
        step = self._interval_delta()
        timestamp = datetime.utcnow() - step * settings.history_bars
        records: list[dict[str, float | datetime | str]] = []
        current_close = base_price

        for index in range(settings.history_bars):
            drift = 1 + (np.sin(index / 11) * 0.009) + generator.normal(0, 0.006)
            current_open = current_close
            current_close = max(0.01, current_close * drift)
            day_high = max(current_open, current_close) * (1 + abs(generator.normal(0.006, 0.004)))
            day_low = min(current_open, current_close) * (1 - abs(generator.normal(0.006, 0.004)))
            volume = abs(base_price * 2500 * (1 + generator.normal(0, 0.18)))
            records.append(
                {
                    "timestamp": (timestamp + step * index).replace(second=0, microsecond=0),
                    "open": float(current_open),
                    "high": float(day_high),
                    "low": float(day_low),
                    "close": float(current_close),
                    "volume": float(volume),
                    "source": "demo",
                }
            )

        return records

    def _persist_records(self, session: Session, symbol: str, records: list[dict[str, float | datetime | str]]) -> None:
        unique_records_by_key: dict[tuple[datetime, str], dict[str, float | datetime | str]] = {}
        for record in records:
            normalized_timestamp = normalize_market_timestamp(record["timestamp"])
            normalized_record = {
                **record,
                "timestamp": normalized_timestamp,
            }
            key = (normalized_timestamp, str(record["source"]))
            unique_records_by_key[key] = normalized_record

        normalized_records = sorted(unique_records_by_key.values(), key=lambda item: (item["timestamp"], str(item["source"])))
        timestamps = list({record["timestamp"] for record in normalized_records})
        existing_rows = session.execute(
            select(MarketData).where(MarketData.symbol == symbol, MarketData.timestamp.in_(timestamps))
        ).scalars().all()
        existing_by_key = {(row.timestamp, row.source): row for row in existing_rows}

        for record in normalized_records:
            key = (record["timestamp"], str(record["source"]))
            existing = existing_by_key.get(key)
            if existing is not None:
                existing.open = record["open"]
                existing.high = record["high"]
                existing.low = record["low"]
                existing.close = record["close"]
                existing.volume = record["volume"]
                continue
            session.add(
                MarketData(
                    symbol=symbol,
                    timestamp=record["timestamp"],
                    open=record["open"],
                    high=record["high"],
                    low=record["low"],
                    close=record["close"],
                    volume=record["volume"],
                    source=record["source"],
                )
            )

    def _coinbase_granularity(self) -> int:
        mapping = {
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "6h": 21600,
            "1d": 86400,
        }
        return mapping.get(settings.market_interval, 3600)

    def _interval_delta(self) -> timedelta:
        return _market_interval_delta()


class LiveQuoteService:
    def __init__(self) -> None:
        self.binance_base_url = "https://api.binance.com/api/v3"
        self._cache: tuple[datetime, dict[str, dict[str, float | str]]] | None = None
        self._fresh_ttl = timedelta(seconds=max(2, settings.live_quote_cache_seconds))
        self._stale_ttl = timedelta(minutes=15)
        self._timeout_seconds = 4

    def get_quote(self, symbol: str) -> dict[str, float | str] | None:
        quotes = self._get_binance_quotes()
        return quotes.get(symbol)

    def _get_binance_quotes(self) -> dict[str, dict[str, float | str]]:
        if self._cache is not None and (datetime.utcnow() - self._cache[0]) < self._fresh_ttl:
            return self._cache[1]

        try:
            response = requests.get(
                f"{self.binance_base_url}/ticker/price",
                timeout=self._timeout_seconds,
                headers={"Accept": "application/json", "User-Agent": "Agent-Krypto/1.0"},
            )
            response.raise_for_status()
            rows = response.json()
            by_pair = {str(row["symbol"]): float(row["price"]) for row in rows if "symbol" in row and "price" in row}
            timestamp = datetime.utcnow().isoformat()
            quotes = {
                symbol: {
                    "price": by_pair[pair],
                    "source": "binance-spot",
                    "timestamp": timestamp,
                }
                for symbol, pair in settings.binance_symbols.items()
                if pair in by_pair
            }
            self._cache = (datetime.utcnow(), quotes)
            return quotes
        except requests.RequestException:
            if self._cache is None:
                return {}
            age = datetime.utcnow() - self._cache[0]
            if age > self._stale_ttl:
                return {}
            return {
                symbol: {
                    **quote,
                    "source": f"{quote['source']}-stale",
                }
                for symbol, quote in self._cache[1].items()
            }