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

import re

# Earn wrapper tokens: strip LD prefix and trailing digits (LDSHIB2 → SHIB, LDBTC → BTC)
_EARN_ASSET_RE = re.compile(r'^LD([A-Z]{2,}?)\d*$')


def _earn_to_base_asset(asset: str) -> str:
    """Convert Binance Earn wrapper asset name to the underlying base asset.
    Examples: LDSHIB2 → SHIB, LDBTC → BTC, LDDOGE → DOGE, LDUSDC → USDC.
    Non-Earn assets are returned as-is."""
    m = _EARN_ASSET_RE.match(asset)
    if m:
        return m.group(1)
    return asset


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
        """Get account balances (non-zero only).
        Normalizes Earn token names (LDSHIB2→SHIB, LDBTC→BTC).
        Merges balances when Earn + spot share the same base asset."""
        account = self.get_account()
        if "error" in account:
            return [account]

        balances = account.get("balances", [])
        merged: dict[str, dict] = {}
        for b in balances:
            free = float(b.get("free", 0))
            locked = float(b.get("locked", 0))
            if free <= 0 and locked <= 0:
                continue
            raw_asset = b["asset"]
            clean_asset = _earn_to_base_asset(raw_asset)
            if clean_asset in merged:
                merged[clean_asset]["free"] += free
                merged[clean_asset]["locked"] += locked
            else:
                merged[clean_asset] = {"asset": clean_asset, "free": free, "locked": locked}
        return list(merged.values())

    def get_spot_free(self, asset: str) -> float:
        """Get actual spot wallet free balance for an asset (no Earn merging)."""
        account = self.get_account()
        if "error" in account:
            return 0.0
        for b in account.get("balances", []):
            if b["asset"] == asset:
                return float(b.get("free", 0))
        return 0.0

    def get_earn_flexible_position(self, asset: str) -> dict | None:
        """Get Simple Earn Flexible position for an asset.
        Returns dict with productId, totalAmount, etc., or None."""
        resp = self._request("GET", "/sapi/v1/simple-earn/flexible/position", {"asset": asset}, signed=True)
        if isinstance(resp, dict) and "error" in resp:
            return None
        rows = resp.get("rows", []) if isinstance(resp, dict) else []
        if not rows and isinstance(resp, list):
            rows = resp
        for row in rows:
            total = float(row.get("totalAmount", 0))
            if total > 0:
                return row
        return None

    def redeem_earn_flexible(self, product_id: str, amount: float | None = None, redeem_all: bool = False) -> dict:
        """Redeem from Simple Earn Flexible product to Spot wallet.
        Set redeem_all=True to redeem entire position, or specify amount."""
        params: dict[str, Any] = {"productId": product_id, "destAccount": "SPOT"}
        if redeem_all:
            params["redeemAll"] = "true"
        elif amount is not None:
            params["amount"] = self._format_quantity(amount)
        return self._request("POST", "/sapi/v1/simple-earn/flexible/redeem", params, signed=True)

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
            # Determine precision from quantity value to avoid Binance precision errors
            params["quantity"] = self._format_quantity(quantity)
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

    @staticmethod
    def _format_quantity(qty: float) -> str:
        """Format quantity with minimal necessary decimal places.
        Avoids 'too much precision' errors from Binance."""
        import math
        if qty == int(qty):
            return str(int(qty))
        # Find precision: count decimal places needed
        s = f"{qty:.8f}".rstrip("0")
        return s
    
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

    def check_margin_available(self) -> dict:
        """Check if margin/leverage trading is available for this account.
        Returns status dict with available features."""
        result = {
            "margin_available": False,
            "futures_available": False,
            "leverage_available": False,
            "reason": "",
        }
        # Check account permissions
        account = self.get_account()
        if "error" in account:
            result["reason"] = f"Blad sprawdzania konta: {account['error']}"
            return result

        perms = account.get("permissions", [])
        account_type = account.get("accountType", "")

        # Check if margin permission set exists
        has_margin_perm = "MARGIN" in perms
        
        # Try to access margin account endpoint
        margin_account = self._request("GET", "/sapi/v1/margin/account", signed=True)
        if isinstance(margin_account, dict) and "error" not in margin_account:
            result["margin_available"] = True
        
        # Try futures — check if endpoint responds
        futures_check = self._request("GET", "/fapi/v2/account", signed=True)
        if isinstance(futures_check, dict) and "error" not in futures_check:
            result["futures_available"] = True

        result["leverage_available"] = result["margin_available"] or result["futures_available"]
        
        if not result["leverage_available"]:
            result["reason"] = (
                "Handel z dźwignią (margin/futures) nie jest dostępny na tym koncie. "
                "Binance wyłączył margin i futures dla użytkowników z krajów EEA/UE (w tym Polski) "
                "od 2023 roku ze względu na regulacje MiCA. "
                "Dostępny jest wyłącznie handel Spot (natychmiastowy)."
            )
            if has_margin_perm:
                result["reason"] += " (Konto ma flagę MARGIN ale endpoint jest zablokowany.)"
        
        result["account_permissions"] = perms
        result["account_type"] = account_type
        return result

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
                       preferred_quotes: list[str] | None = None,
                       side: str = "BUY") -> tuple[str | None, str | None, float]:
        """Find the best trading pair for base_asset based on account's tradeable pairs.
        For BUY: requires positive quote balance.
        For SELL: just needs a valid pair (no quote balance needed).
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

        if side == "SELL":
            # For SELL: just find first available pair in preferred order
            for q in preferred_quotes:
                if q in available_quotes:
                    return f"{base_asset}{q}", q, bal_map.get(q, 0)
            # Fallback: any available pair
            if available_quotes:
                q = available_quotes[0]
                return f"{base_asset}{q}", q, bal_map.get(q, 0)
            return None, None, 0.0

        # BUY: need quote balance
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
            asset = balance["asset"]  # Already normalized by get_balances()
            free = float(balance["free"])
            locked = float(balance["locked"])
            total = free + locked

            if total == 0:
                continue

            value = self._resolve_value(asset, total, quote_currency, price_map, bridge_currencies)
            if value == 0 and total > 0:
                unpriced.append(asset)

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
            import logging
            _logger = logging.getLogger(__name__)
            cg_values = self._coingecko_fallback_prices(unpriced, quote_currency)
            for h in holdings:
                if h["value"] == 0 and h["total"] > 0:
                    cg_price = cg_values.get(h["asset"], 0)
                    if cg_price > 0:
                        h["value"] = round(h["total"] * cg_price, 2)
                        total_value += h["value"]
                        _logger.info("Portfolio CoinGecko fallback: %s = %.2f %s", h["asset"], h["value"], quote_currency)
                    else:
                        _logger.warning("Portfolio UNPRICED: %s (total=%.6f) - no Binance pair or CoinGecko price found", h["asset"], h["total"])

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

    def get_portfolio_with_cost_basis(self, quote_currency: str = "PLN") -> list[dict]:
        """Build portfolio with cost basis from Binance trade history.
        Returns list of holdings with avg_buy_price, current_price, pnl_value, pnl_pct."""
        import logging
        _log = logging.getLogger(__name__)
        portfolio = self.get_portfolio_value(quote_currency)
        if isinstance(portfolio, dict) and "error" in portfolio:
            return []

        holdings = portfolio.get("holdings", [])
        prices = self.get_ticker_price()
        price_map = {p["symbol"]: float(p["price"]) for p in prices} if isinstance(prices, list) else {}
        bridges = ["USDC", "USDT", "BTC", "BNB", "EUR", "ETH", "PLN"]
        stables = {"USDT", "BUSD", "FDUSD", "PLN", "EUR", "USD", "USDC"}

        tradeable = self.get_tradeable_pairs()
        result = []

        for h in holdings:
            asset = h["asset"]
            total = h["total"]
            value = h["value"]
            if total <= 0 or value < 0.01:
                continue
            if asset in stables:
                result.append({
                    "asset": asset, "total": total, "value": round(value, 2),
                    "avg_buy_price": None, "current_price": None,
                    "pnl_value": 0, "pnl_pct": 0, "is_stable": True,
                })
                continue

            # Current price in quote_currency
            current_price_q = self._resolve_value(asset, 1.0, quote_currency, price_map, bridges)

            # Compute average buy price from trade history
            avg_buy = self._compute_avg_cost(asset, quote_currency, tradeable, price_map, bridges, _log)

            pnl_value = 0.0
            pnl_pct = 0.0
            if avg_buy and avg_buy > 0 and current_price_q > 0:
                cost_basis = avg_buy * total
                pnl_value = value - cost_basis
                pnl_pct = (current_price_q - avg_buy) / avg_buy * 100

            result.append({
                "asset": asset,
                "total": round(total, 8),
                "value": round(value, 2),
                "avg_buy_price": round(avg_buy, 6) if avg_buy else None,
                "current_price": round(current_price_q, 6) if current_price_q else None,
                "pnl_value": round(pnl_value, 2),
                "pnl_pct": round(pnl_pct, 2),
                "is_stable": False,
            })

        result.sort(key=lambda x: abs(x["value"]), reverse=True)
        return result

    def _compute_avg_cost(self, asset: str, quote_currency: str,
                          tradeable: dict, price_map: dict,
                          bridges: list, logger) -> float | None:
        """Compute average cost per unit in quote_currency from Binance trade history."""
        quotes = tradeable.get(asset, [])
        if not quotes:
            return None

        total_qty = 0.0
        total_cost_q = 0.0  # total cost in quote_currency

        # Try each available pair
        for q in quotes:
            pair = f"{asset}{q}"
            try:
                trades = self.get_my_trades(pair, limit=100)
            except Exception:
                continue
            if not isinstance(trades, list):
                continue

            # Convert trade quote to portfolio quote_currency
            q_to_quote = 1.0 if q == quote_currency else self._get_pair_price(q, quote_currency, price_map)
            if q_to_quote <= 0:
                # Try bridge
                for b in bridges:
                    if b == q or b == quote_currency:
                        continue
                    qb = self._get_pair_price(q, b, price_map)
                    bqc = self._get_pair_price(b, quote_currency, price_map)
                    if qb > 0 and bqc > 0:
                        q_to_quote = qb * bqc
                        break
            if q_to_quote <= 0:
                continue

            for t in trades:
                is_buyer = t.get("isBuyer", False)
                qty = float(t.get("qty", 0))
                price_in_q = float(t.get("price", 0))
                cost_in_q = qty * price_in_q  # cost in the pair's quote currency
                cost_in_target = cost_in_q * q_to_quote

                if is_buyer:
                    total_qty += qty
                    total_cost_q += cost_in_target
                else:
                    # SELL reduces position — use FIFO-like: reduce proportionally
                    if total_qty > 0:
                        avg_so_far = total_cost_q / total_qty
                        reduce = min(qty, total_qty)
                        total_qty -= reduce
                        total_cost_q -= reduce * avg_so_far

        if total_qty > 0:
            return total_cost_q / total_qty
        return None


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
