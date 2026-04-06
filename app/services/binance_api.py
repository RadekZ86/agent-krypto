"""Binance API integration for multi-user trading."""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from app.models import UserAPIKey


class BinanceClient:
    """Binance API client for a specific user's API key."""
    
    BASE_URL = "https://api.binance.com"
    TESTNET_URL = "https://testnet.binance.vision"
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = self.TESTNET_URL if testnet else self.BASE_URL
        self._tradeable_pairs: dict[str, list[str]] | None = None
        self._tradeable_ts: float = 0
    
    def _sign(self, params: dict) -> str:
        """Create HMAC SHA256 signature."""
        query_string = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        signed: bool = False
    ) -> dict:
        """Make API request."""
        url = f"{self.base_url}{endpoint}"
        headers = {"X-MBX-APIKEY": self.api_key}
        
        if params is None:
            params = {}
        
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["signature"] = self._sign(params)
        
        try:
            if method == "GET":
                response = requests.get(url, params=params, headers=headers, timeout=10)
            elif method == "POST":
                response = requests.post(url, params=params, headers=headers, timeout=10)
            elif method == "DELETE":
                response = requests.delete(url, params=params, headers=headers, timeout=10)
            else:
                return {"error": f"Unknown method: {method}"}
            
            if response.status_code != 200:
                return {"error": response.text, "code": response.status_code}
            
            return response.json()
        except requests.RequestException as e:
            return {"error": str(e)}
    
    # ==================== PUBLIC ENDPOINTS ====================
    
    def get_server_time(self) -> dict:
        """Get Binance server time."""
        return self._request("GET", "/api/v3/time")
    
    def get_exchange_info(self, symbol: Optional[str] = None) -> dict:
        """Get exchange trading rules and symbol info."""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/api/v3/exchangeInfo", params)
    
    def get_ticker_price(self, symbol: Optional[str] = None) -> dict | list:
        """Get latest price for symbol(s)."""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/api/v3/ticker/price", params)
    
    def get_ticker_24h(self, symbol: Optional[str] = None) -> dict | list:
        """Get 24h price change statistics."""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/api/v3/ticker/24hr", params)
    
    def get_klines(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> list:
        """Get kline/candlestick data."""
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        return self._request("GET", "/api/v3/klines", params)
    
    # ==================== ACCOUNT ENDPOINTS (SIGNED) ====================
    
    def get_account(self) -> dict:
        """Get current account information."""
        return self._request("GET", "/api/v3/account", signed=True)
    
    def get_balances(self) -> list[dict]:
        """Get account balances (non-zero only)."""
        account = self.get_account()
        if "error" in account:
            return [account]
        
        balances = account.get("balances", [])
        return [
            b for b in balances
            if float(b.get("free", 0)) > 0 or float(b.get("locked", 0)) > 0
        ]
    
    def get_open_orders(self, symbol: Optional[str] = None) -> list:
        """Get all open orders."""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/api/v3/openOrders", params, signed=True)
    
    def get_all_orders(self, symbol: str, limit: int = 50) -> list:
        """Get all orders for a symbol."""
        params = {"symbol": symbol, "limit": limit}
        return self._request("GET", "/api/v3/allOrders", params, signed=True)
    
    def get_my_trades(self, symbol: str, limit: int = 50) -> list:
        """Get trades for a symbol."""
        params = {"symbol": symbol, "limit": limit}
        return self._request("GET", "/api/v3/myTrades", params, signed=True)
    
    # ==================== TRADING ENDPOINTS (SIGNED) ====================
    
    def create_order(
        self,
        symbol: str,
        side: str,  # BUY or SELL
        order_type: str,  # LIMIT, MARKET, etc.
        quantity: Optional[float] = None,
        quote_quantity: Optional[float] = None,
        price: Optional[float] = None,
        time_in_force: str = "GTC",
        stop_price: Optional[float] = None
    ) -> dict:
        """Create a new order."""
        import math
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
        }
        
        if quantity:
            params["quantity"] = f"{quantity:.8f}"
        if quote_quantity:
            # Floor to 2 decimals to avoid exceeding available balance
            floored = math.floor(quote_quantity * 100) / 100
            params["quoteOrderQty"] = f"{floored:.2f}"
        if price:
            params["price"] = f"{price:.8f}"
        if order_type in ("LIMIT", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT"):
            params["timeInForce"] = time_in_force
        if stop_price:
            params["stopPrice"] = f"{stop_price:.8f}"
        
        return self._request("POST", "/api/v3/order", params, signed=True)
    
    def create_test_order(self, **kwargs) -> dict:
        """Test new order creation (no actual order placed)."""
        params = {
            "symbol": kwargs.get("symbol"),
            "side": kwargs.get("side"),
            "type": kwargs.get("order_type", "MARKET"),
        }
        if kwargs.get("quantity"):
            params["quantity"] = f"{kwargs['quantity']:.8f}"
        if kwargs.get("quote_quantity"):
            params["quoteOrderQty"] = f"{kwargs['quote_quantity']:.2f}"
        
        return self._request("POST", "/api/v3/order/test", params, signed=True)
    
    def cancel_order(self, symbol: str, order_id: int) -> dict:
        """Cancel an active order."""
        params = {"symbol": symbol, "orderId": order_id}
        return self._request("DELETE", "/api/v3/order", params, signed=True)
    
    def cancel_all_orders(self, symbol: str) -> dict:
        """Cancel all open orders for a symbol."""
        params = {"symbol": symbol}
        return self._request("DELETE", "/api/v3/openOrders", params, signed=True)
    
    # ==================== HELPER METHODS ====================
    
    def test_connection(self) -> tuple[bool, str]:
        """Test API connection and permissions."""
        # Test public endpoint
        time_result = self.get_server_time()
        if "error" in time_result:
            return False, f"Błąd połączenia: {time_result['error']}"
        
        # Test authenticated endpoint
        account = self.get_account()
        if "error" in account:
            return False, f"Błąd API: {account['error']}"
        
        # Get permissions
        can_trade = account.get("canTrade", False)
        can_withdraw = account.get("canWithdraw", False)
        
        perms = []
        perms.append("odczyt")
        if can_trade:
            perms.append("trading")
        if can_withdraw:
            perms.append("wypłaty")
        
        return True, f"Połączono. Uprawnienia: {', '.join(perms)}"

    def get_tradeable_pairs(self) -> dict[str, list[str]]:
        """Return {base_asset: [quote_assets]} for pairs this account can trade.
        Cached for 1 hour."""
        if self._tradeable_pairs is not None and (time.time() - self._tradeable_ts) < 3600:
            return self._tradeable_pairs

        account = self.get_account()
        if "error" in account:
            return {}
        user_perms = set(account.get("permissions", []))

        info = self.get_exchange_info()
        if "error" in info:
            return {}

        result: dict[str, list[str]] = {}
        for sym in info.get("symbols", []):
            if sym.get("status") != "TRADING":
                continue
            psets = sym.get("permissionSets", [])
            match = False
            for pset in psets:
                if isinstance(pset, list) and user_perms & set(pset):
                    match = True
                    break
            if not match:
                continue
            base = sym["baseAsset"]
            quote = sym["quoteAsset"]
            result.setdefault(base, []).append(quote)

        self._tradeable_pairs = result
        self._tradeable_ts = time.time()
        return result

    def find_best_pair(self, base_asset: str, balances: list[dict],
                       preferred_quotes: list[str] | None = None) -> tuple[str | None, str | None, float]:
        """Find the best trading pair for base_asset based on account's tradeable pairs
        and available quote balances.
        Returns (pair_symbol, quote_asset, available_quote_balance) or (None,None,0)."""
        pairs = self.get_tradeable_pairs()
        available_quotes = pairs.get(base_asset, [])
        if not available_quotes:
            return None, None, 0.0

        # Build balance map
        bal_map: dict[str, float] = {}
        for b in balances:
            asset = b.get("asset", "")
            free = float(b.get("free", 0))
            if free > 0:
                bal_map[asset] = free

        if preferred_quotes is None:
            preferred_quotes = ["PLN", "USDC", "EUR", "BTC", "ETH", "BNB", "USDT", "BUSD"]

        # Try preferred quotes first, then remaining by balance
        best_pair = None
        best_quote = None
        best_bal = 0.0
        for q in preferred_quotes:
            if q in available_quotes and bal_map.get(q, 0) > 0:
                return f"{base_asset}{q}", q, bal_map[q]

        # Fallback: any quote with positive balance
        for q in available_quotes:
            bal = bal_map.get(q, 0)
            if bal > best_bal:
                best_pair = f"{base_asset}{q}"
                best_quote = q
                best_bal = bal

        return best_pair, best_quote, best_bal

    def get_portfolio_value(self, quote_currency: str = "USDT") -> dict:
        """Calculate total portfolio value with multi-hop price resolution."""
        balances = self.get_balances()
        if isinstance(balances, list) and len(balances) > 0 and "error" in balances[0]:
            return balances[0]

        prices = self.get_ticker_price()
        if "error" in prices:
            return prices

        price_map = {p["symbol"]: float(p["price"]) for p in prices}

        # Bridge currencies for cross-conversion when no direct pair exists
        bridge_currencies = ["USDC", "USDT", "BTC", "BNB", "EUR", "ETH"]

        total_value = 0.0
        holdings = []
        unpriced: list[str] = []

        for balance in balances:
            asset = balance["asset"]
            # Treat Earn wrapper tokens (LD*) as their underlying asset for pricing
            price_asset = asset[2:] if asset.startswith("LD") and len(asset) > 3 else asset
            free = float(balance["free"])
            locked = float(balance["locked"])
            total = free + locked

            if total == 0:
                continue

            value = self._resolve_value(price_asset, total, quote_currency, price_map, bridge_currencies)
            if value == 0 and total > 0:
                unpriced.append(price_asset)

            total_value += value
            holdings.append({
                "asset": asset,
                "free": free,
                "locked": locked,
                "total": total,
                "value": round(value, 2)
            })

        # Fallback: try CoinGecko for unpriced assets
        if unpriced:
            cg_values = self._coingecko_fallback_prices(unpriced, quote_currency)
            for h in holdings:
                if h["value"] == 0 and h["total"] > 0:
                    pa = h["asset"][2:] if h["asset"].startswith("LD") and len(h["asset"]) > 3 else h["asset"]
                    cg_price = cg_values.get(pa, 0)
                    if cg_price > 0:
                        h["value"] = round(h["total"] * cg_price, 2)
                        total_value += h["value"]

        # Sort by value
        holdings.sort(key=lambda x: x["value"], reverse=True)

        return {
            "total_value": round(total_value, 2),
            "quote_currency": quote_currency,
            "holdings": holdings
        }

    def _resolve_value(self, price_asset: str, total: float, quote: str,
                       price_map: dict[str, float], bridges: list[str]) -> float:
        """Resolve asset value in quote currency via direct, 1-hop, or 2-hop bridge."""
        if price_asset == quote:
            return total

        # Direct: ASSET/QUOTE
        direct = price_map.get(f"{price_asset}{quote}")
        if direct:
            return total * direct

        # Reverse direct: QUOTE/ASSET
        rev = price_map.get(f"{quote}{price_asset}")
        if rev and rev > 0:
            return total / rev

        # 1-hop bridge: ASSET→B→QUOTE (try all directions)
        for b in bridges:
            if b == price_asset or b == quote:
                continue
            val = self._try_bridge_hop(price_asset, b, quote, total, price_map)
            if val > 0:
                return val

        # 2-hop bridge: ASSET→B1→B2→QUOTE (for Binance PL where many pairs are missing)
        for b1 in bridges:
            if b1 == price_asset or b1 == quote:
                continue
            # Get asset→b1 price
            ab1 = self._get_pair_price(price_asset, b1, price_map)
            if ab1 <= 0:
                continue
            for b2 in bridges:
                if b2 == b1 or b2 == price_asset or b2 == quote:
                    continue
                b1b2 = self._get_pair_price(b1, b2, price_map)
                if b1b2 <= 0:
                    continue
                b2q = self._get_pair_price(b2, quote, price_map)
                if b2q > 0:
                    return total * ab1 * b1b2 * b2q

        return 0.0

    @staticmethod
    def _get_pair_price(base: str, quote: str, price_map: dict[str, float]) -> float:
        """Get price of base in terms of quote, trying direct and reverse pair."""
        p = price_map.get(f"{base}{quote}")
        if p:
            return p
        rev = price_map.get(f"{quote}{base}")
        if rev and rev > 0:
            return 1.0 / rev
        return 0.0

    def _try_bridge_hop(self, asset: str, bridge: str, quote: str,
                        total: float, price_map: dict[str, float]) -> float:
        """Try ASSET→BRIDGE→QUOTE conversion in all pair directions."""
        ab = self._get_pair_price(asset, bridge, price_map)
        if ab <= 0:
            return 0.0
        bq = self._get_pair_price(bridge, quote, price_map)
        if bq <= 0:
            return 0.0
        return total * ab * bq

    @staticmethod
    def _coingecko_fallback_prices(assets: list[str], quote_currency: str) -> dict[str, float]:
        """Fetch prices from CoinGecko as last resort for unpriced assets."""
        import logging
        logger = logging.getLogger(__name__)

        # Map common symbols to CoinGecko IDs
        _SYMBOL_TO_CG = {
            "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin", "SOL": "solana",
            "XRP": "ripple", "ADA": "cardano", "DOGE": "dogecoin", "TRX": "tron",
            "AVAX": "avalanche-2", "DOT": "polkadot", "LINK": "chainlink", "TON": "the-open-network",
            "SUI": "sui", "LTC": "litecoin", "BCH": "bitcoin-cash", "ATOM": "cosmos",
            "UNI": "uniswap", "NEAR": "near", "APT": "aptos", "ETC": "ethereum-classic",
            "XLM": "stellar", "HBAR": "hedera-hashgraph", "FIL": "filecoin", "ARB": "arbitrum",
            "VET": "vechain", "ALGO": "algorand", "RENDER": "render-token", "FTM": "fantom",
            "MNT": "mantle", "KAS": "kaspa", "PEPE": "pepe", "SHIB": "shiba-inu",
            "FET": "artificial-superintelligence-alliance", "WLD": "worldcoin-wld",
            "AAVE": "aave", "OP": "optimism", "INJ": "injective-protocol", "SEI": "sei-network",
            "USUAL": "usual",
        }

        cg_quote = {"PLN": "pln", "USD": "usd", "USDT": "usd", "USDC": "usd", "EUR": "eur"}.get(quote_currency, "usd")

        ids_to_fetch = []
        symbol_to_id = {}
        for sym in assets:
            cg_id = _SYMBOL_TO_CG.get(sym)
            if cg_id:
                ids_to_fetch.append(cg_id)
                symbol_to_id[cg_id] = sym

        if not ids_to_fetch:
            return {}

        try:
            resp = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": ",".join(ids_to_fetch), "vs_currencies": cg_quote},
                timeout=8,
            )
            if resp.status_code != 200:
                logger.warning("CoinGecko fallback failed: %s", resp.status_code)
                return {}
            data = resp.json()
            result = {}
            for cg_id, sym in symbol_to_id.items():
                price = data.get(cg_id, {}).get(cg_quote, 0)
                if price > 0:
                    result[sym] = float(price)
            logger.info("CoinGecko fallback priced %d/%d assets", len(result), len(assets))
            return result
        except Exception as e:
            logger.warning("CoinGecko fallback error: %s", e)
            return {}


class BinanceService:
    """Service to manage Binance connections for multiple users."""
    
    def __init__(self):
        self._clients: dict[str, BinanceClient] = {}
    
    def get_client(self, api_key: str, api_secret: str, testnet: bool = False) -> BinanceClient:
        """Get or create Binance client for API key."""
        cache_key = f"{api_key}_{testnet}"
        if cache_key not in self._clients:
            self._clients[cache_key] = BinanceClient(
                api_key=api_key,
                api_secret=api_secret,
                testnet=testnet
            )
        return self._clients[cache_key]
    
    def clear_client(self, api_key: str, testnet: bool = False) -> None:
        """Remove cached client."""
        cache_key = f"{api_key}_{testnet}"
        if cache_key in self._clients:
            del self._clients[cache_key]
