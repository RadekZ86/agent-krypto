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
        """Calculate total portfolio value."""
        balances = self.get_balances()
        if isinstance(balances, list) and len(balances) > 0 and "error" in balances[0]:
            return balances[0]
        
        prices = self.get_ticker_price()
        if "error" in prices:
            return prices
        
        price_map = {p["symbol"]: float(p["price"]) for p in prices}
        
        # Bridge currencies for cross-conversion when no direct pair exists
        bridge_currencies = ["USDT", "USDC", "BTC", "BNB", "EUR"]
        
        total_value = 0.0
        holdings = []
        
        for balance in balances:
            asset = balance["asset"]
            # Treat Earn wrapper tokens (LD*) as their underlying asset for pricing
            price_asset = asset[2:] if asset.startswith("LD") and len(asset) > 3 else asset
            free = float(balance["free"])
            locked = float(balance["locked"])
            total = free + locked
            
            if total == 0:
                continue
            
            # Calculate value in quote currency
            value = 0.0
            if price_asset == quote_currency:
                value = total
            else:
                # Try direct pair
                symbol = f"{price_asset}{quote_currency}"
                if symbol in price_map:
                    value = total * price_map[symbol]
                else:
                    # Try reverse pair
                    reverse_symbol = f"{quote_currency}{price_asset}"
                    if reverse_symbol in price_map and price_map[reverse_symbol] > 0:
                        value = total / price_map[reverse_symbol]
                    else:
                        # Try bridge conversion: asset→bridge→quote
                        for bridge in bridge_currencies:
                            if bridge == price_asset or bridge == quote_currency:
                                continue
                            ab = f"{price_asset}{bridge}"
                            bq = f"{bridge}{quote_currency}"
                            ab_price = price_map.get(ab)
                            bq_price = price_map.get(bq)
                            if ab_price and bq_price:
                                value = total * ab_price * bq_price
                                break
                            # Try reverse bridge: bridge→asset, quote→bridge
                            ba = f"{bridge}{price_asset}"
                            qb = f"{quote_currency}{bridge}"
                            if ba in price_map and price_map[ba] > 0 and bq_price:
                                value = total / price_map[ba] * bq_price
                                break
            
            total_value += value
            holdings.append({
                "asset": asset,
                "free": free,
                "locked": locked,
                "total": total,
                "value": round(value, 2)
            })
        
        # Sort by value
        holdings.sort(key=lambda x: x["value"], reverse=True)
        
        return {
            "total_value": total_value,
            "quote_currency": quote_currency,
            "holdings": holdings
        }


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
