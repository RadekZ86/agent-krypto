"""Bybit V5 API integration — unified spot + linear perpetual (leverage) trading."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Optional

import requests

_log = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
# Client
# ────────────────────────────────────────────────────────────


class BybitClient:
    """Bybit V5 REST API client.  Supports *spot* and *linear* (USDT perps)."""

    MAINNET_URL = "https://api.bybit.com"
    TESTNET_URL = "https://api-testnet.bybit.com"
    RECV_WINDOW = "5000"

    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = self.TESTNET_URL if testnet else self.MAINNET_URL

    # ── auth helpers ──────────────────────────────────────────

    def _sign(self, timestamp: str, payload: str) -> str:
        """HMAC-SHA256 signature:  timestamp + api_key + recv_window + payload"""
        param_str = f"{timestamp}{self.api_key}{self.RECV_WINDOW}{payload}"
        return hmac.new(
            self.api_secret.encode("utf-8"),
            param_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _headers(self, timestamp: str, signature: str) -> dict[str, str]:
        return {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": signature,
            "X-BAPI-RECV-WINDOW": self.RECV_WINDOW,
            "Content-Type": "application/json",
        }

    # ── generic request ───────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        signed: bool = False,
    ) -> dict:
        url = f"{self.base_url}{path}"
        if params is None:
            params = {}

        ts = str(int(time.time() * 1000))

        try:
            if method == "GET":
                qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
                sig = self._sign(ts, qs) if signed else ""
                headers = self._headers(ts, sig) if signed else {}
                resp = requests.get(url, params=params, headers=headers, timeout=10)
            else:  # POST
                body = json.dumps(params)
                sig = self._sign(ts, body) if signed else ""
                headers = self._headers(ts, sig) if signed else {}
                resp = requests.post(url, data=body, headers=headers, timeout=10)

            data = resp.json()
            if data.get("retCode", -1) != 0:
                return {"error": data.get("retMsg", "Unknown Bybit error"), "retCode": data.get("retCode")}
            return data.get("result", data)
        except requests.RequestException as exc:
            return {"error": str(exc)}

    # ══════════════════════════════════════════════════════════
    # PUBLIC  (market data)
    # ══════════════════════════════════════════════════════════

    def get_server_time(self) -> dict:
        return self._request("GET", "/v5/market/time")

    def get_tickers(self, category: str = "linear", symbol: str | None = None) -> dict:
        p: dict[str, str] = {"category": category}
        if symbol:
            p["symbol"] = symbol
        return self._request("GET", "/v5/market/tickers", p)

    def get_klines(
        self,
        symbol: str,
        interval: str = "60",
        limit: int = 200,
        category: str = "linear",
        start: int | None = None,
        end: int | None = None,
    ) -> dict:
        """interval: 1,3,5,15,30,60,120,240,360,720,D,W,M"""
        p: dict[str, Any] = {"category": category, "symbol": symbol, "interval": interval, "limit": limit}
        if start:
            p["start"] = start
        if end:
            p["end"] = end
        return self._request("GET", "/v5/market/kline", p)

    def get_instruments_info(self, category: str = "linear", symbol: str | None = None) -> dict:
        p: dict[str, str] = {"category": category}
        if symbol:
            p["symbol"] = symbol
        return self._request("GET", "/v5/market/instruments-info", p)

    def get_funding_rate_history(self, symbol: str, category: str = "linear", limit: int = 10) -> dict:
        return self._request("GET", "/v5/market/funding/history", {
            "category": category, "symbol": symbol, "limit": limit,
        })

    def get_open_interest(self, symbol: str, interval_time: str = "1h", category: str = "linear", limit: int = 10) -> dict:
        return self._request("GET", "/v5/market/open-interest", {
            "category": category, "symbol": symbol, "intervalTime": interval_time, "limit": limit,
        })

    def get_recent_trades(self, symbol: str, category: str = "linear", limit: int = 50) -> dict:
        return self._request("GET", "/v5/market/recent-trade", {
            "category": category, "symbol": symbol, "limit": limit,
        })

    # ══════════════════════════════════════════════════════════
    # ACCOUNT  (wallet, positions)
    # ══════════════════════════════════════════════════════════

    def get_wallet_balance(self, account_type: str = "UNIFIED") -> dict:
        """accountType: UNIFIED, CONTRACT, SPOT, FUND"""
        return self._request("GET", "/v5/account/wallet-balance", {"accountType": account_type}, signed=True)

    def get_positions(self, category: str = "linear", symbol: str | None = None) -> dict:
        p: dict[str, str] = {"category": category}
        if symbol:
            p["symbol"] = symbol
        return self._request("GET", "/v5/position/list", p, signed=True)

    def get_account_info(self) -> dict:
        return self._request("GET", "/v5/account/info", signed=True)

    def get_fee_rate(self, category: str = "linear", symbol: str | None = None) -> dict:
        p: dict[str, str] = {"category": category}
        if symbol:
            p["symbol"] = symbol
        return self._request("GET", "/v5/account/fee-rate", p, signed=True)

    # ══════════════════════════════════════════════════════════
    # LEVERAGE / MARGIN
    # ══════════════════════════════════════════════════════════

    def set_leverage(self, symbol: str, buy_leverage: str, sell_leverage: str, category: str = "linear") -> dict:
        return self._request("POST", "/v5/position/set-leverage", {
            "category": category,
            "symbol": symbol,
            "buyLeverage": buy_leverage,
            "sellLeverage": sell_leverage,
        }, signed=True)

    def switch_margin_mode(self, symbol: str, trade_mode: int = 0, category: str = "linear") -> dict:
        """trade_mode: 0 = cross margin, 1 = isolated margin"""
        return self._request("POST", "/v5/position/switch-isolated", {
            "category": category,
            "symbol": symbol,
            "tradeMode": trade_mode,
            "buyLeverage": "10",
            "sellLeverage": "10",
        }, signed=True)

    def switch_position_mode(self, category: str = "linear", mode: int = 0) -> dict:
        """mode: 0 = one-way, 3 = hedge"""
        return self._request("POST", "/v5/position/switch-mode", {
            "category": category,
            "mode": mode,
        }, signed=True)

    # ══════════════════════════════════════════════════════════
    # TRADING
    # ══════════════════════════════════════════════════════════

    def place_order(
        self,
        symbol: str,
        side: str,               # Buy / Sell
        order_type: str,          # Market / Limit
        qty: str,
        category: str = "linear",
        price: str | None = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
        take_profit: str | None = None,
        stop_loss: str | None = None,
        leverage: str | None = None,
        position_idx: int = 0,
    ) -> dict:
        """Place spot or linear order.  For linear, set leverage first."""
        if leverage:
            lev_res = self.set_leverage(symbol, leverage, leverage, category)
            if "error" in lev_res:
                _log.warning("set_leverage %s %sx: %s", symbol, leverage, lev_res["error"])

        p: dict[str, Any] = {
            "category": category,
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "qty": qty,
            "timeInForce": time_in_force if order_type == "Limit" else "IOC",
            "positionIdx": position_idx,
        }
        if price and order_type == "Limit":
            p["price"] = price
        if reduce_only:
            p["reduceOnly"] = True
        if take_profit:
            p["takeProfit"] = take_profit
        if stop_loss:
            p["stopLoss"] = stop_loss
        return self._request("POST", "/v5/order/create", p, signed=True)

    def cancel_order(self, symbol: str, order_id: str, category: str = "linear") -> dict:
        return self._request("POST", "/v5/order/cancel", {
            "category": category,
            "symbol": symbol,
            "orderId": order_id,
        }, signed=True)

    def cancel_all_orders(self, category: str = "linear", symbol: str | None = None) -> dict:
        p: dict[str, str] = {"category": category}
        if symbol:
            p["symbol"] = symbol
        return self._request("POST", "/v5/order/cancel-all", p, signed=True)

    def get_open_orders(self, category: str = "linear", symbol: str | None = None) -> dict:
        p: dict[str, str] = {"category": category}
        if symbol:
            p["symbol"] = symbol
        return self._request("GET", "/v5/order/realtime", p, signed=True)

    def get_order_history(self, category: str = "linear", symbol: str | None = None, limit: int = 50) -> dict:
        p: dict[str, Any] = {"category": category, "limit": limit}
        if symbol:
            p["symbol"] = symbol
        return self._request("GET", "/v5/order/history", p, signed=True)

    def get_closed_pnl(self, category: str = "linear", symbol: str | None = None, limit: int = 50) -> dict:
        p: dict[str, Any] = {"category": category, "limit": limit}
        if symbol:
            p["symbol"] = symbol
        return self._request("GET", "/v5/position/closed-pnl", p, signed=True)

    # ══════════════════════════════════════════════════════════
    # HIGH-LEVEL HELPERS
    # ══════════════════════════════════════════════════════════

    def test_connection(self) -> tuple[bool, str]:
        """Test API connectivity and permissions."""
        ts = self.get_server_time()
        if "error" in ts:
            return False, f"Błąd połączenia: {ts['error']}"

        info = self.get_account_info()
        if "error" in info:
            return False, f"Błąd API: {info['error']}"

        uta = info.get("unifiedMarginStatus", 0)
        margin_mode = info.get("marginMode", "?")
        perms = []
        if uta in (3, 4):
            perms.append("Unified Trading Account")
        perms.append(f"marginMode={margin_mode}")

        return True, f"Połączono z Bybit. {', '.join(perms)}"

    def get_portfolio_value(self, quote_currency: str = "USDT") -> dict:
        """Get combined wallet + positions value."""
        wallet = self.get_wallet_balance("UNIFIED")
        if "error" in wallet:
            return wallet

        accounts = wallet.get("list", [])
        if not accounts:
            return {"error": "Brak danych portfela"}

        acc = accounts[0]
        total_equity = float(acc.get("totalEquity", 0))
        total_wallet = float(acc.get("totalWalletBalance", 0))
        total_pnl = float(acc.get("totalPerpUPL", 0))
        available = float(acc.get("totalAvailableBalance", 0))

        holdings = []
        for coin in acc.get("coin", []):
            asset = coin.get("coin", "")
            equity = float(coin.get("equity", 0))
            wallet_bal = float(coin.get("walletBalance", 0))
            usd_value = float(coin.get("usdValue", 0))
            unrealized = float(coin.get("unrealisedPnl", 0))
            if equity <= 0 and usd_value <= 0:
                continue
            holdings.append({
                "asset": asset,
                "free": float(coin.get("availableToWithdraw", 0)),
                "locked": wallet_bal - float(coin.get("availableToWithdraw", 0)),
                "total": equity,
                "value": round(usd_value, 2),
                "unrealized_pnl": round(unrealized, 2),
            })

        holdings.sort(key=lambda x: x["value"], reverse=True)

        return {
            "total_value": round(total_equity, 2),
            "total_wallet": round(total_wallet, 2),
            "total_unrealized_pnl": round(total_pnl, 2),
            "available_balance": round(available, 2),
            "quote_currency": "USDT",  # Bybit unified uses USD-equivalent
            "holdings": holdings,
        }

    def get_open_positions_summary(self) -> list[dict]:
        """Get summary of all open perpetual positions."""
        pos = self.get_positions("linear")
        if "error" in pos:
            return []

        result = []
        for p in pos.get("list", []):
            size = float(p.get("size", 0))
            if size == 0:
                continue
            result.append({
                "symbol": p.get("symbol", ""),
                "side": p.get("side", ""),
                "size": size,
                "leverage": p.get("leverage", "1"),
                "entry_price": float(p.get("avgPrice", 0)),
                "mark_price": float(p.get("markPrice", 0)),
                "unrealized_pnl": float(p.get("unrealisedPnl", 0)),
                "liq_price": float(p.get("liqPrice", 0) or 0),
                "take_profit": p.get("takeProfit", ""),
                "stop_loss": p.get("stopLoss", ""),
                "position_value": float(p.get("positionValue", 0)),
                "margin_mode": "cross" if p.get("tradeMode", 0) == 0 else "isolated",
            })
        return result

    def get_leverage_info(self, symbol: str) -> dict:
        """Get current leverage and max leverage for a symbol."""
        info = self.get_instruments_info("linear", symbol)
        if "error" in info:
            return info

        instruments = info.get("list", [])
        if not instruments:
            return {"error": f"Symbol {symbol} nie znaleziony"}

        inst = instruments[0]
        max_leverage = float(inst.get("leverageFilter", {}).get("maxLeverage", 100))
        min_leverage = float(inst.get("leverageFilter", {}).get("minLeverage", 1))

        # Get current position leverage
        pos = self.get_positions("linear", symbol)
        current_leverage = "1"
        if not isinstance(pos, dict) or "error" not in pos:
            for p in pos.get("list", []):
                if p.get("symbol") == symbol:
                    current_leverage = p.get("leverage", "1")
                    break

        return {
            "symbol": symbol,
            "current_leverage": current_leverage,
            "max_leverage": max_leverage,
            "min_leverage": min_leverage,
            "min_order_qty": inst.get("lotSizeFilter", {}).get("minOrderQty", "0"),
            "tick_size": inst.get("priceFilter", {}).get("tickSize", "0"),
        }

    def get_trading_history(self, category: str = "linear", limit: int = 50) -> list[dict]:
        """Get recent closed P&L — used for agent learning."""
        pnl = self.get_closed_pnl(category, limit=limit)
        if "error" in pnl:
            return []
        result = []
        for row in pnl.get("list", []):
            result.append({
                "symbol": row.get("symbol", ""),
                "side": row.get("side", ""),
                "qty": float(row.get("qty", 0)),
                "entry_price": float(row.get("avgEntryPrice", 0)),
                "exit_price": float(row.get("avgExitPrice", 0)),
                "closed_pnl": float(row.get("closedPnl", 0)),
                "leverage": row.get("leverage", "1"),
                "created_time": row.get("createdTime", ""),
                "updated_time": row.get("updatedTime", ""),
            })
        return result


# ────────────────────────────────────────────────────────────
# Service (multi-user client cache)
# ────────────────────────────────────────────────────────────


class BybitService:
    """Manage Bybit client instances for multiple users."""

    def __init__(self) -> None:
        self._clients: dict[str, BybitClient] = {}

    def get_client(self, api_key: str, api_secret: str, testnet: bool = False) -> BybitClient:
        cache_key = f"{api_key}_{testnet}"
        if cache_key not in self._clients:
            self._clients[cache_key] = BybitClient(api_key, api_secret, testnet)
        return self._clients[cache_key]

    def clear_client(self, api_key: str, testnet: bool = False) -> None:
        cache_key = f"{api_key}_{testnet}"
        self._clients.pop(cache_key, None)
