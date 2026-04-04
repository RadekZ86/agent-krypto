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
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
        }
        
        if quantity:
            params["quantity"] = f"{quantity:.8f}"
        if quote_quantity:
            params["quoteOrderQty"] = f"{quote_quantity:.2f}"
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
    
    def get_portfolio_value(self, quote_currency: str = "USDT") -> dict:
        """Calculate total portfolio value."""
        balances = self.get_balances()
        if isinstance(balances, list) and len(balances) > 0 and "error" in balances[0]:
            return balances[0]
        
        prices = self.get_ticker_price()
        if "error" in prices:
            return prices
        
        price_map = {p["symbol"]: float(p["price"]) for p in prices}
        
        total_value = 0.0
        holdings = []
        
        for balance in balances:
            asset = balance["asset"]
            free = float(balance["free"])
            locked = float(balance["locked"])
            total = free + locked
            
            if total == 0:
                continue
            
            # Calculate value in quote currency
            if asset == quote_currency:
                value = total
            else:
                symbol = f"{asset}{quote_currency}"
                if symbol in price_map:
                    value = total * price_map[symbol]
                else:
                    # Try reverse pair
                    reverse_symbol = f"{quote_currency}{asset}"
                    if reverse_symbol in price_map and price_map[reverse_symbol] > 0:
                        value = total / price_map[reverse_symbol]
                    else:
                        value = 0
            
            total_value += value
            holdings.append({
                "asset": asset,
                "free": free,
                "locked": locked,
                "total": total,
                "value": value
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
    
    def __init__(self, api_key_service):
        self.api_key_service = api_key_service
        self._clients: dict[int, BinanceClient] = {}
    
    def get_client(self, api_key: UserAPIKey) -> BinanceClient:
        """Get or create Binance client for API key."""
        if api_key.id not in self._clients:
            secret = self.api_key_service.get_decrypted_secret(api_key)
            self._clients[api_key.id] = BinanceClient(
                api_key=api_key.api_key,
                api_secret=secret,
                testnet=api_key.is_testnet
            )
        return self._clients[api_key.id]
    
    def clear_client(self, api_key_id: int) -> None:
        """Remove cached client."""
        if api_key_id in self._clients:
            del self._clients[api_key_id]
