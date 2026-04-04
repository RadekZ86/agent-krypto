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
    """Mirror a paper trade decision to all users with trading_mode=LIVE and a valid Binance key."""
    from app.models import User, UserAPIKey
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

        pair = settings.binance_symbols.get(symbol, f"{symbol}{settings.exchange_quote_currency}")
        try:
            if action == "BUY":
                allocation = settings.allocation_quote.get(symbol, 40.0)
                order = client.create_order(
                    symbol=pair,
                    side="BUY",
                    order_type="MARKET",
                    quote_quantity=allocation,
                )
            elif action == "SELL":
                balances = client.get_balances()
                held = 0.0
                if isinstance(balances, list):
                    for b in balances:
                        if b.get("asset") == symbol:
                            held = float(b.get("free", 0))
                            break
                if held <= 0:
                    logger.info("LIVE %s: brak %s do sprzedazy", user.username, symbol)
                    continue
                order = client.create_order(
                    symbol=pair,
                    side="SELL",
                    order_type="MARKET",
                    quantity=held,
                )
            else:
                continue

            if "error" in order:
                logger.warning("LIVE %s: blad zlecenia %s %s: %s", user.username, action, pair, order["error"])
                results.append({"user": user.username, "symbol": pair, "action": action, "status": "error", "detail": order["error"]})
            else:
                logger.info("LIVE %s: %s %s OK orderId=%s", user.username, action, pair, order.get("orderId"))
                results.append({"user": user.username, "symbol": pair, "action": action, "status": "ok", "order_id": order.get("orderId")})
        except Exception as exc:
            logger.exception("LIVE %s: wyjatek przy %s %s", user.username, action, pair)
            results.append({"user": user.username, "symbol": pair, "action": action, "status": "exception", "detail": str(exc)})

    return results


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