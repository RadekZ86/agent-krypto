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

# Throttle repeated skip-log entries so we don't spam the DB / dashboard
import time as _time
_skip_log_cache: dict[tuple, float] = {}  # (username, action, reason_key) -> epoch
_SKIP_LOG_INTERVAL = 1800.0  # seconds (30 min)


def _should_log_skip(username: str, action: str, reason_key: str) -> bool:
    """Return True if this skip should be logged (throttled to once per 30 min per key)."""
    key = (username, action, reason_key)
    now = _time.time()
    last = _skip_log_cache.get(key, 0.0)
    if now - last >= _SKIP_LOG_INTERVAL:
        _skip_log_cache[key] = now
        return True
    return False


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
                # Pre-check: does user have ANY quote currency above min order?
                bal_map = {b["asset"]: float(b.get("free", 0)) for b in balances if float(b.get("free", 0)) > 0}
                has_usable_funds = any(
                    bal_map.get(q, 0) >= _MIN_ORDER.get(q, 5.0)
                    for q in _BRIDGE_QUOTES
                )
                if not has_usable_funds:
                    if _should_log_skip(user.username, "BUY", "no_funds"):
                        held_summary = ", ".join(f"{k}={v:.4f}" for k, v in sorted(bal_map.items()) if v > 0.001)
                        logger.info("LIVE %s: brak wystarczajacych srodkow do zakupu (pomin. %s) [%s]", user.username, symbol, held_summary)
                        session.add(LiveOrderLog(
                            username=user.username, symbol=symbol, action="BUY", status="skip",
                            detail=f"brak srodkow - ponizej min. zleceń ({held_summary[:200]})",
                        ))
                    continue
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
                    if _should_log_skip(user.username, "SELL", f"no_hold_{symbol}"):
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
                    if _should_log_skip(user.username, "SELL", f"dust_{symbol}"):
                        logger.info("LIVE %s: %s ilosc %.8f ponizej minQty dla %s (dust)", user.username, symbol, held, pair)
                        session.add(LiveOrderLog(username=user.username, symbol=pair, action="SELL", status="skip", detail=f"qty {held:.8f} < minQty (dust)"))
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


# All quote currencies we can trade through, ordered by preference.
_BRIDGE_QUOTES = ["PLN", "USDC", "USDT", "EUR", "BTC", "ETH", "BNB"]

# Min order values per quote currency (Binance minNotional / practical min)
_MIN_ORDER = {
    "PLN": 25.0, "USDC": 5.0, "USDT": 5.0, "EUR": 5.0, "BTC": 0.0001,
    "ETH": 0.003, "BNB": 0.05, "BRL": 10.0, "JPY": 500.0, "MXN": 100.0,
}

# Cache for symbol LOT_SIZE info
_lot_size_cache: dict[str, tuple[float, float]] = {}


def _floor_to_step_size(client, pair: str, qty: float) -> float:
    """Floor quantity to the pair's LOT_SIZE stepSize and check minQty.
    Returns a properly rounded float matching Binance precision."""
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
        # Calculate precision from step_size (e.g. 1.0 → 0 decimals, 0.01 → 2)
        precision = max(0, -int(math.floor(math.log10(step_size)))) if step_size < 1 else 0
        floored = math.floor(qty / step_size) * step_size
        floored = round(floored, precision)  # Remove floating-point noise
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
    """Execute a LIVE BUY for a symbol.
    Strategy:
      1. Direct buy — find any quote the user has balance in (preferred order).
      2. Bridge buy — convert any held currency → needed quote → ALT.
    Returns result dict or None if nothing to report."""
    from app.models import LiveOrderLog

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

    # ---------- 1. DIRECT BUY: user already has a quote currency ----------
    # Try preferred quotes first, then any available
    tried_quotes = set()
    for q in list(_BRIDGE_QUOTES) + [x for x in alt_quotes if x not in _BRIDGE_QUOTES]:
        if q in tried_quotes or q not in alt_quotes:
            continue
        tried_quotes.add(q)
        qbal = bal_map.get(q, 0.0)
        min_order = _MIN_ORDER.get(q, 5.0)
        if qbal < min_order:
            continue
        alt_pair = f"{symbol}{q}"
        allocation = _get_allocation(user, qbal)
        if allocation < min_order:
            allocation = min_order
        if allocation > qbal:
            allocation = qbal
        return _place_buy_order(client, session, user, alt_pair, q, allocation)

    # ---------- 2. BRIDGE BUY: convert held currency → needed quote → ALT ----------
    # For every quote the ALT accepts, check if we can buy that quote with something we hold
    for target_quote in _BRIDGE_QUOTES:
        if target_quote not in alt_quotes:
            continue  # ALT doesn't trade against this quote

        # What can we buy target_quote WITH?
        target_buy_quotes = tradeable_pairs.get(target_quote, [])  # e.g. USDC can be bought with PLN, BRL, MXN

        # Try each source currency the user holds
        for source_currency in _BRIDGE_QUOTES:
            if source_currency == target_quote:
                continue
            if source_currency not in target_buy_quotes:
                continue  # Can't buy target_quote with source_currency
            source_bal = bal_map.get(source_currency, 0.0)
            source_min = _MIN_ORDER.get(source_currency, 5.0)
            if source_bal < source_min:
                continue

            # === BRIDGE: source_currency → target_quote → ALT ===
            src_allocation = _get_allocation(user, source_bal)
            if src_allocation < source_min:
                src_allocation = source_min
            if src_allocation > source_bal:
                src_allocation = source_bal

            convert_pair = f"{target_quote}{source_currency}"
            logger.info("LIVE %s: bridge %s via %s->%s->%s (%.4f %s)",
                        user.username, symbol, source_currency, target_quote, symbol,
                        src_allocation, source_currency)

            step1 = client.create_order(
                symbol=convert_pair,
                side="BUY",
                order_type="MARKET",
                quote_quantity=src_allocation,
            )
            if "error" in step1:
                logger.warning("LIVE %s: bridge step1 %s error: %s", user.username, convert_pair, step1["error"])
                session.add(LiveOrderLog(
                    username=user.username, symbol=convert_pair, action="BUY", status="error",
                    detail=f"bridge step1: {str(step1['error'])[:400]}", allocation=src_allocation, quote_currency=source_currency,
                ))
                continue  # Try next source

            # Calculate received amount
            bridge_received = float(step1.get("executedQty", 0))
            if bridge_received <= 0:
                for fill in step1.get("fills", []):
                    bridge_received += float(fill.get("qty", 0))
            if bridge_received <= 0:
                logger.warning("LIVE %s: bridge step1 %s: 0 received", user.username, convert_pair)
                session.add(LiveOrderLog(
                    username=user.username, symbol=convert_pair, action="BUY", status="error",
                    detail="bridge: 0 received", allocation=src_allocation, quote_currency=source_currency,
                ))
                continue

            logger.info("LIVE %s: bridge step1 OK: %.6f %s za %.4f %s",
                        user.username, bridge_received, target_quote, src_allocation, source_currency)
            session.add(LiveOrderLog(
                username=user.username, symbol=convert_pair, action="BUY", status="ok",
                detail=f"bridge step1: {bridge_received:.6f} {target_quote}",
                order_id=str(step1.get("orderId", "")),
                allocation=src_allocation, quote_currency=source_currency,
            ))

            # Step 2: Buy ALT with bridge currency
            alt_pair = f"{symbol}{target_quote}"
            result = _place_buy_order(client, session, user, alt_pair, target_quote, bridge_received)
            if result and result.get("status") == "ok":
                result["detail"] = f"bridge {source_currency}->{target_quote}->{symbol}"
            return result

    # Nothing worked
    held_summary = ", ".join(f"{k}={v:.4f}" for k, v in sorted(bal_map.items()) if v > 0.001)
    logger.info("LIVE %s: nie mozna kupic %s (brak pary/srodkow) held=[%s]", user.username, symbol, held_summary)
    session.add(LiveOrderLog(
        username=user.username, symbol=symbol, action="BUY", status="skip",
        detail=f"brak pary lub srodkow ({held_summary[:200]})",
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