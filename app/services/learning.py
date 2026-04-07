from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import LearningLog, SimulatedTrade


class LearningService:
    def log_trade_result(
        self,
        session: Session,
        trade: SimulatedTrade,
        market_state: str,
        notes: str,
    ) -> None:
        session.add(
            LearningLog(
                decision_id=trade.decision_id,
                result="WIN" if (trade.profit or 0) > 0 else "LOSS",
                was_profitable=(trade.profit or 0) > 0,
                market_state=market_state,
                notes=notes,
            )
        )

    def log_live_trade_result(
        self,
        session: Session,
        symbol: str,
        result: str,
        profit_pct: float,
        market_state: str,
        notes: str,
    ) -> None:
        """Log a LIVE trade outcome for learning (no SimulatedTrade needed)."""
        session.add(
            LearningLog(
                decision_id=None,
                result=result,
                was_profitable=profit_pct > 0,
                market_state=market_state,
                notes=f"[LIVE {symbol}] pnl={profit_pct:.2f}% | {notes}",
            )
        )