from __future__ import annotations

import logging
from threading import Lock

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.services.decision_engine import DecisionEngine
from app.services.indicators import IndicatorService
from app.services.learning import LearningService
from app.services.market_data import MarketDataService
from app.services.wallet import WalletService

logger = logging.getLogger(__name__)


def _mirror_to_live_users(session: Session, symbol: str, action: str, market_price: float) -> list[dict]:
    """Mirror a paper trade decision to all users with trading_mode=LIVE and a valid Binance key.
    Auto-detects available trading pairs and adjusts allocation to user's balance.
    Supports bridge-buy: PLN → USDC → ALT when no direct pair exists."""
    from app.models import User, UserAPIKey, LiveOrderLog
    from app.services.auth import APIKeyService
    from app.services.binance_api import BinanceService

    api_key_service = APIKeyService()
    binance_service = BinanceService()

    live_users = session.execute(
        select(User).where(User.trading_mode == "LIVE", User.is_active == True)
    ).scalars().all()

    results = []
    for user in live_users:
        keys = api_key_service.get_user_api_keys(session, user.id)
        trade_key = next(
            (k for k in keys if k.is_active and not k.is_testnet and k.permissions in ("trade", "trading")),
            None,
        )
        if trade_key is None:
            continue

        api_secret = api_key_service.get_decrypted_secret(trade_key)
        if not api_secret:
            continue

        client = binance_service.get_client(
            api_key=trade_key.api_key,
            api_secret=api_secret,
            testnet=trade_key.is_testnet,
        )

        try:
            balances = client.get_balances()
            if isinstance(balances, list) and len(balances) > 0 and "error" in balances[0]:
                logger.warning("LIVE %s: blad pobierania salda: %s", user.username, balances[0]["error"])
                continue

            if action == "BUY":
                order_result = _execute_live_buy(client, session, user, symbol, balances)
                if order_result is not None:
                    results.append(order_result)
            elif action == "SELL":
                held = 0.0
                for b in balances:
                    if b.get("asset") == symbol:
                        held = float(b.get("free", 0))
                        break
                if held <= 0:
                    logger.info("LIVE %s: brak %s do sprzedazy", user.username, symbol)
                    continue

                # Find a pair to sell on
                pair, quote_asset, _ = client.find_best_pair(symbol, balances)
                if pair is None:
                    # Fallback to configured pair
                    pair = settings.binance_symbols.get(symbol, f"{symbol}{settings.exchange_quote_currency}")

                # Adjust quantity to LOT_SIZE stepSize to avoid Filter failure
                sell_qty = _floor_to_step_size(client, pair, held)
                if sell_qty <= 0:
                    logger.info("LIVE %s: %s ilosc %.8f ponizej minQty dla %s", user.username, symbol, held, pair)
                    session.add(LiveOrderLog(username=user.username, symbol=pair, action="SELL", status="skip", detail=f"qty {held:.8f} < minQty"))
                    continue

                order = client.create_order(
                    symbol=pair,
                    side="SELL",
                    order_type="MARKET",
                    quantity=sell_qty,
                )

                if "error" in order:
                    logger.warning("LIVE %s: blad zlecenia SELL %s: %s", user.username, pair, order["error"])
                    results.append({"user": user.username, "symbol": pair, "action": "SELL", "status": "error", "detail": order["error"]})
                    session.add(LiveOrderLog(username=user.username, symbol=pair, action="SELL", status="error", detail=str(order["error"])[:500]))
                else:
                    logger.info("LIVE %s: SELL %s OK orderId=%s", user.username, pair, order.get("orderId"))
                    results.append({"user": user.username, "symbol": pair, "action": "SELL", "status": "ok", "order_id": order.get("orderId")})
                    session.add(LiveOrderLog(username=user.username, symbol=pair, action="SELL", status="ok", order_id=str(order.get("orderId", ""))))
        except Exception as exc:
            logger.exception("LIVE %s: wyjatek przy %s %s", user.username, action, symbol)
            results.append({"user": user.username, "symbol": symbol, "action": action, "status": "exception", "detail": str(exc)})
            session.add(LiveOrderLog(username=user.username, symbol=symbol, action=action, status="exception", detail=str(exc)[:500]))

    return results


# Bridge currencies to try when direct pair is not available or has no balance.
# Order: try direct PLN first, then USDC (most altcoin pairs on Binance PL), then EUR, BTC, BNB.
_BRIDGE_QUOTES = ["PLN", "USDC", "EUR", "BTC", "BNB"]

# Min order values per quote currency (Binance minNotional)
_MIN_ORDER = {"PLN": 25.0, "USDC": 5.0, "EUR": 5.0, "BTC": 0.0001, "BNB": 0.01}

# Cache for symbol LOT_SIZE info
_lot_size_cache: dict[str, tuple[float, float]] = {}


def _floor_to_step_size(client, pair: str, qty: float) -> float:
    """Floor quantity to the pair's LOT_SIZE stepSize and check minQty."""
    import math
    if pair not in _lot_size_cache:
        info = client.get_exchange_info(symbol=pair)
        min_qty = 0.00000001
        step_size = 0.00000001
        for sym in info.get("symbols", []):
            if sym["symbol"] == pair:
                for f in sym.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        min_qty = float(f["minQty"])
                        step_size = float(f["stepSize"])
                        break
                break
        _lot_size_cache[pair] = (min_qty, step_size)

    min_qty, step_size = _lot_size_cache[pair]
    if qty < min_qty:
        return 0.0
    if step_size > 0:
        floored = math.floor(qty / step_size) * step_size
        return floored if floored >= min_qty else 0.0
    return qty


def _get_allocation(user, quote_bal: float) -> float:
    """Calculate trade allocation from user settings."""
    alloc_mode = getattr(user, 'live_alloc_mode', None) or 'percent'
    alloc_value = getattr(user, 'live_alloc_value', None)
    if alloc_value is None:
        alloc_value = 10.0
    if alloc_mode == 'max':
        return quote_bal
    elif alloc_mode == 'fixed':
        return min(alloc_value, quote_bal)
    else:
        return quote_bal * (alloc_value / 100.0)


def _execute_live_buy(client, session: Session, user, symbol: str, balances: list[dict]) -> dict | None:
    """Execute a LIVE BUY for a symbol, including bridge-buy logic.
    Returns result dict or None if nothing to report."""
    from app.models import LiveOrderLog

    # 1. Try direct buy (find_best_pair already checks balance)
    pair, quote_asset, quote_bal = client.find_best_pair(symbol, balances)

    if pair is not None and quote_bal > 0:
        allocation = _get_allocation(user, quote_bal)
        min_order = _MIN_ORDER.get(quote_asset, 5.0)
        if allocation >= min_order:
            return _place_buy_order(client, session, user, pair, quote_asset, allocation)
        elif quote_bal >= min_order:
            return _place_buy_order(client, session, user, pair, quote_asset, min_order)
        # else: balance too low for this pair, try bridge below

    # 2. Try bridge-buy: convert user's available currency → bridge quote → ALT
    tradeable_pairs = client.get_tradeable_pairs()
    alt_quotes = tradeable_pairs.get(symbol, [])
    if not alt_quotes:
        logger.info("LIVE %s: brak dostepnej pary dla %s", user.username, symbol)
        session.add(LiveOrderLog(username=user.username, symbol=symbol, action="BUY", status="skip", detail="brak pary na gieldzie"))
        return {"user": user.username, "symbol": symbol, "action": "BUY", "status": "skip", "detail": "no tradeable pair"}

    # Build balance map
    bal_map: dict[str, float] = {}
    for b in balances:
        free = float(b.get("free", 0))
        if free > 0:
            bal_map[b["asset"]] = free

    # Try each bridge: find a currency user HAS that can be converted to a quote the ALT accepts
    for bridge_quote in _BRIDGE_QUOTES:
        if bridge_quote not in alt_quotes:
            continue  # ALT doesn't trade against this quote

        bridge_bal = bal_map.get(bridge_quote, 0.0)
        min_order = _MIN_ORDER.get(bridge_quote, 5.0)

        if bridge_bal >= min_order:
            # User already has this bridge currency with enough balance
            alt_pair = f"{symbol}{bridge_quote}"
            allocation = _get_allocation(user, bridge_bal)
            if allocation < min_order:
                allocation = min_order
            if allocation > bridge_bal:
                allocation = bridge_bal
            return _place_buy_order(client, session, user, alt_pair, bridge_quote, allocation)

        # Check if we can convert PLN → bridge_quote (e.g. PLN → USDC)
        if bridge_quote == "PLN":
            continue  # PLN is source, not target
        pln_bal = bal_map.get("PLN", 0.0)
        if pln_bal < 25.0:
            continue  # Not enough PLN
        # Check if bridge_quote can be bought with PLN (e.g. USDCPLN exists)
        bridge_pln_quotes = tradeable_pairs.get(bridge_quote, [])
        if "PLN" not in bridge_pln_quotes:
            continue

        # === BRIDGE BUY: PLN → bridge_quote → ALT ===
        pln_allocation = _get_allocation(user, pln_bal)
        if pln_allocation < 25.0:
            pln_allocation = min(25.0, pln_bal)
        if pln_allocation < 25.0:
            continue

        logger.info("LIVE %s: bridge buy %s via PLN->%s (%.2f PLN)", user.username, symbol, bridge_quote, pln_allocation)

        # Step 1: Buy bridge quote with PLN
        convert_pair = f"{bridge_quote}PLN"
        step1 = client.create_order(
            symbol=convert_pair,
            side="BUY",
            order_type="MARKET",
            quote_quantity=pln_allocation,
        )
        if "error" in step1:
            logger.warning("LIVE %s: bridge step1 %s error: %s", user.username, convert_pair, step1["error"])
            session.add(LiveOrderLog(
                username=user.username, symbol=convert_pair, action="BUY", status="error",
                detail=f"bridge step1: {str(step1['error'])[:400]}", allocation=pln_allocation, quote_currency="PLN",
            ))
            continue  # Try next bridge

        # Calculate how much bridge currency we received
        bridge_received = float(step1.get("executedQty", 0))
        if bridge_received <= 0:
            for fill in step1.get("fills", []):
                bridge_received += float(fill.get("qty", 0))
        if bridge_received <= 0:
            logger.warning("LIVE %s: bridge step1 %s: 0 received", user.username, convert_pair)
            session.add(LiveOrderLog(
                username=user.username, symbol=convert_pair, action="BUY", status="error",
                detail="bridge: 0 received", allocation=pln_allocation, quote_currency="PLN",
            ))
            continue

        logger.info("LIVE %s: bridge step1 OK: %.4f %s za %.2f PLN", user.username, bridge_received, bridge_quote, pln_allocation)
        session.add(LiveOrderLog(
            username=user.username, symbol=convert_pair, action="BUY", status="ok",
            detail=f"bridge step1: {bridge_received:.4f} {bridge_quote}",
            order_id=str(step1.get("orderId", "")),
            allocation=pln_allocation, quote_currency="PLN",
        ))

        # Step 2: Buy ALT with bridge currency
        alt_pair = f"{symbol}{bridge_quote}"
        result = _place_buy_order(client, session, user, alt_pair, bridge_quote, bridge_received)
        if result and result.get("status") == "ok":
            result["detail"] = f"bridge PLN->{bridge_quote}->{symbol}"
        return result

    # Nothing worked
    logger.info("LIVE %s: nie mozna kupic %s (brak pary/srodkow)", user.username, symbol)
    session.add(LiveOrderLog(
        username=user.username, symbol=symbol, action="BUY", status="skip",
        detail=f"brak pary lub srodkow (PLN={bal_map.get('PLN', 0):.2f})",
    ))
    return {"user": user.username, "symbol": symbol, "action": "BUY", "status": "skip", "detail": "no viable pair"}


def _place_buy_order(client, session: Session, user, pair: str, quote_asset: str, allocation: float) -> dict:
    """Place a market buy order and log the result."""
    from app.models import LiveOrderLog

    order = client.create_order(
        symbol=pair,
        side="BUY",
        order_type="MARKET",
        quote_quantity=allocation,
    )
    if "error" in order:
        logger.warning("LIVE %s: blad zlecenia BUY %s: %s", user.username, pair, order["error"])
        session.add(LiveOrderLog(
            username=user.username, symbol=pair, action="BUY", status="error",
            detail=str(order["error"])[:500], allocation=allocation, quote_currency=quote_asset,
        ))
        return {"user": user.username, "symbol": pair, "action": "BUY", "status": "error", "detail": order["error"]}
    else:
        logger.info("LIVE %s: BUY %s OK orderId=%s alloc=%.4f %s", user.username, pair, order.get("orderId"), allocation, quote_asset)
        session.add(LiveOrderLog(
            username=user.username, symbol=pair, action="BUY", status="ok",
            order_id=str(order.get("orderId", "")), allocation=allocation, quote_currency=quote_asset,
        ))
        return {"user": user.username, "symbol": pair, "action": "BUY", "status": "ok", "order_id": order.get("orderId")}


class AgentCycle:
    def __init__(self) -> None:
        self.market_data = MarketDataService()
        self.indicators = IndicatorService()
        self.decision_engine = DecisionEngine()
        self.wallet = WalletService()
        self.learning = LearningService()
        self._lock = Lock()

    def run(self, session: Session, symbols: list[str] | None = None) -> dict[str, object]:
        with self._lock:
            symbols_to_process = symbols or settings.tracked_symbols
            results: list[dict[str, object]] = []

            for symbol in symbols_to_process:
                market_snapshot = self.market_data.update_symbol(session, symbol)
                session.flush()
                feature_row = self.indicators.compute_for_symbol(session, symbol)
                if feature_row is None:
                    continue

                decision = self.decision_engine.evaluate(session, symbol, feature_row)
                execution = self.wallet.execute_decision(session, decision, float(feature_row["close"]))

                # Mirror BUY/SELL to real Binance for LIVE users
                if decision.decision in ("BUY", "SELL"):
                    try:
                        live_results = _mirror_to_live_users(
                            session, symbol, decision.decision, float(feature_row["close"])
                        )
                        if live_results:
                            logger.info("Live mirror for %s %s: %s", symbol, decision.decision, live_results)
                    except Exception:
                        logger.exception("Live mirror error for %s", symbol)

                if execution and execution["action"] == "SELL":
                    trade = session.execute(
                        select_trade_for_learning(symbol)
                    ).scalars().first()
                    if trade is not None:
                        self.learning.log_trade_result(
                            session,
                            trade,
                            market_state=str(feature_row["trend"]),
                            notes=decision.reason,
                        )

                results.append(
                    {
                        "symbol": symbol,
                        "source": market_snapshot["source"],
                        "decision": decision.decision,
                        "confidence": decision.confidence,
                        "reason": decision.reason,
                        "execution": execution,
                        "up_probability": feature_row.get("up_probability"),
                        "bottom_probability": feature_row.get("bottom_probability"),
                        "top_probability": feature_row.get("top_probability"),
                    }
                )

            session.commit()
            return {"symbols": results, "processed": len(results)}


def select_trade_for_learning(symbol: str):
    from sqlalchemy import desc, select

    from app.models import SimulatedTrade

    return (
        select(SimulatedTrade)
        .where(SimulatedTrade.symbol == symbol, SimulatedTrade.status == "CLOSED")
        .order_by(desc(SimulatedTrade.closed_at))
        .limit(1)
    )