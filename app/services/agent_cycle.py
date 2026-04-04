from __future__ import annotations

from threading import Lock

from sqlalchemy.orm import Session

from app.config import settings
from app.services.decision_engine import DecisionEngine
from app.services.indicators import IndicatorService
from app.services.learning import LearningService
from app.services.market_data import MarketDataService
from app.services.wallet import WalletService


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