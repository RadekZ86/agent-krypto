from __future__ import annotations

from datetime import datetime, timedelta

import requests


class CurrencyService:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[datetime, float, str]] = {}
        self._fresh_ttl = timedelta(minutes=5)
        self._stale_ttl = timedelta(hours=12)
        self._live_timeout_seconds = 4
        self._fallback_timeout_seconds = 3

    def get_rate(self, base_currency: str, target_currency: str) -> tuple[float, str]:
        base = base_currency.upper()
        target = target_currency.upper()
        if base == target:
            return 1.0, "identity"

        cache_key = f"{base}_{target}"
        cached = self._cache.get(cache_key)
        if cached is not None and (datetime.utcnow() - cached[0]) < self._fresh_ttl:
            return cached[1], cached[2]

        normalized_base = "USD" if base == "USDT" else base
        if normalized_base == "USD" and target == "PLN":
            live_rate = self._fetch_live_usdt_pln_rate()
            if live_rate is not None:
                self._cache[cache_key] = (datetime.utcnow(), live_rate, "coingecko-usdt")
                return live_rate, "coingecko-usdt"
            try:
                response = requests.get(
                    "https://api.nbp.pl/api/exchangerates/rates/A/USD/?format=json",
                    timeout=self._fallback_timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
                rate = float(payload["rates"][0]["mid"])
                self._cache[cache_key] = (datetime.utcnow(), rate, "nbp")
                return rate, "nbp"
            except requests.RequestException:
                stale_cached = self._get_stale_cached_rate(cache_key)
                if stale_cached is not None:
                    return stale_cached
                fallback = 4.0
                self._cache[cache_key] = (datetime.utcnow(), fallback, "fallback")
                return fallback, "fallback"

        return 1.0, "identity"

    def _get_stale_cached_rate(self, cache_key: str) -> tuple[float, str] | None:
        cached = self._cache.get(cache_key)
        if cached is None:
            return None
        age = datetime.utcnow() - cached[0]
        if age > self._stale_ttl:
            return None
        return cached[1], f"{cached[2]}-stale"

    def _fetch_live_usdt_pln_rate(self) -> float | None:
        try:
            response = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "tether", "vs_currencies": "pln"},
                timeout=self._live_timeout_seconds,
                headers={"Accept": "application/json", "User-Agent": "Agent-Krypto/1.0"},
            )
            response.raise_for_status()
            payload = response.json()
            rate = float(payload.get("tether", {}).get("pln", 0.0) or 0.0)
            return rate if rate > 0 else None
        except requests.RequestException:
            return None