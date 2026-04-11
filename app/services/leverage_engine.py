"""Leverage decision engine + paper simulation for agent learning.

The agent learns leverage/perpetual trading on virtual money (PAPER mode).
It evaluates LONG and SHORT signals, manages simulated perpetual positions
with leverage, liquidation checks, funding fees, and tracks performance.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import LeverageSimTrade
from app.services.runtime_state import RuntimeStateService

_log = logging.getLogger(__name__)

# ── Leverage progression table (Playbook 18) ──
# consecutive_wins → allowed leverage
LEVERAGE_PROGRESSION = [
    (0, 2),    # default: 2x
    (5, 3),    # 5 wins in a row → 3x
    (10, 5),   # 10 wins → 5x
    (20, 7),   # 20 wins → 7x
    (30, 10),  # 30 wins → 10x (max for learning)
]

# Virtual balance for leverage paper trading (separate from spot paper wallet)
LEVERAGE_PAPER_BALANCE = 10_000.0  # 10,000 USDT virtual
MAX_LEVERAGE_POSITIONS = 3
FUNDING_RATE_DEFAULT = 0.0001  # 0.01% per 8h (typical)
FUNDING_INTERVAL_HOURS = 8


class LeverageEngine:
    """Evaluates leverage (perpetual) trading signals and manages paper positions."""

    def __init__(self) -> None:
        self.runtime_state = RuntimeStateService()

    # ──────────────────────────────────────────────────
    # DECISION: Should we LONG, SHORT, or CLOSE?
    # ──────────────────────────────────────────────────

    def evaluate(self, session: Session, symbol: str, feature_row: dict, perp_data: dict | None = None) -> dict | None:
        """Evaluate leverage signals for a symbol. Returns action dict or None.

        Args:
            perp_data: Optional Bybit perpetual snapshot (funding rate, OI, mark price).
        """
        profile = self.runtime_state.get_active_profile(session)

        # Only in PAPER mode + learning
        if settings.trading_mode != "PAPER":
            return None

        close = float(feature_row["close"])

        # First check: manage existing positions (close, liquidation, funding)
        existing = self._get_open_position(session, symbol)
        if existing is not None:
            return self._evaluate_exit(session, existing, feature_row, close, profile)

        # Check position limits
        open_count = self._count_open_positions(session)
        if open_count >= MAX_LEVERAGE_POSITIONS:
            return None

        # Check available margin
        available = self._available_margin(session)
        if available < 50:  # min $50 margin
            return None

        # Use real Bybit perpetual funding rate if available
        if perp_data and "funding_rate" in perp_data:
            feature_row = {**feature_row, "_perp": perp_data}

        # Evaluate LONG and SHORT independently
        long_result = self._score_long(feature_row, profile)
        short_result = self._score_short(feature_row, profile)

        # Pick the stronger signal (if any passes threshold)
        threshold = max(int(profile.get("buy_score_threshold", 6)), 7)  # leverage needs higher threshold

        best = None
        if long_result["score"] >= threshold and long_result["score"] > short_result["score"]:
            best = long_result
            best["side"] = "LONG"
        elif short_result["score"] >= threshold and short_result["score"] > long_result["score"]:
            best = short_result
            best["side"] = "SHORT"

        if best is None:
            return None

        # Determine leverage based on progression
        leverage = self._current_leverage(session)

        # Calculate position sizing (Playbook 14: 1-2% risk rule)
        risk_pct = 0.01 if leverage >= 5 else 0.02
        stop_loss_pct = float(profile.get("stop_loss", 0.03))
        margin_for_trade = min(
            available * risk_pct / (stop_loss_pct * leverage) * leverage,  # risk-adjusted
            available * 0.3,  # max 30% of available margin per trade
        )
        margin_for_trade = max(margin_for_trade, 50)  # min $50
        if margin_for_trade > available:
            return None

        notional = margin_for_trade * leverage
        quantity = notional / close

        # Liquidation price calculation (simplified, isolated margin)
        if best["side"] == "LONG":
            liq_price = close * (1 - 1 / leverage * 0.95)  # 95% of theoretical to account for fees
            tp = close * (1 + float(profile.get("profit_target", 0.04)))
            sl = close * (1 - stop_loss_pct)
        else:  # SHORT
            liq_price = close * (1 + 1 / leverage * 0.95)
            tp = close * (1 - float(profile.get("profit_target", 0.04)))
            sl = close * (1 + stop_loss_pct)

        # Open the paper position
        trade = LeverageSimTrade(
            symbol=symbol,
            side=best["side"],
            leverage=leverage,
            entry_price=close,
            quantity=quantity,
            margin_used=margin_for_trade,
            liquidation_price=liq_price,
            take_profit=tp,
            stop_loss=sl,
            decision_score=best["score"],
            decision_reason="; ".join(best["signals"]),
            status="OPEN",
            opened_at=datetime.utcnow(),
        )
        session.add(trade)
        session.flush()

        _log.info(
            "LEVERAGE PAPER %s %s %sx @ $%.2f | margin=$%.2f liq=$%.2f tp=$%.2f sl=$%.2f | score=%d",
            best["side"], symbol, leverage, close, margin_for_trade, liq_price, tp, sl, best["score"],
        )

        return {
            "action": best["side"],
            "symbol": symbol,
            "leverage": leverage,
            "price": close,
            "margin": round(margin_for_trade, 2),
            "quantity": round(quantity, 6),
            "liq_price": round(liq_price, 2),
            "score": best["score"],
            "signals": best["signals"],
        }

    # ──────────────────────────────────────────────────
    # LONG SCORING
    # ──────────────────────────────────────────────────

    def _score_long(self, f: dict, profile: dict) -> dict:
        score = 0
        signals: list[str] = []

        rsi = float(f["rsi"])
        macd = float(f["macd"])
        macd_signal = float(f["macd_signal"])
        macd_hist = float(f["macd_hist"])
        trend = str(f["trend"])
        volume_change = float(f["volume_change"])
        up_prob = float(f.get("up_probability", 50))
        bottom_prob = float(f.get("bottom_probability", 50))
        prev_macd = float(f.get("prev_macd", macd))
        prev_macd_signal = float(f.get("prev_macd_signal", macd_signal))
        close = float(f["close"])
        vwap = float(f.get("vwap", close))
        bb_position = 0.5
        bb_upper = float(f.get("bb_upper", close))
        bb_lower = float(f.get("bb_lower", close))
        if bb_upper != bb_lower and bb_lower > 0:
            bb_position = (close - bb_lower) / (bb_upper - bb_lower)

        whale_signal = str(f.get("whale_signal", "NONE"))

        # Strong trend UP required
        if trend == "UP":
            score += 3
            signals.append("Trend UP (EMA20>EMA50)")
        elif trend == "DOWN":
            score -= 3
            signals.append("KARA: Trend DOWN — LONG ryzykowny")

        # RSI sweet zone for LONG (not overbought!)
        if rsi < 35:
            score += 3
            signals.append(f"RSI mocno wyprzedany {rsi:.0f} — dobry LONG")
        elif rsi < 45:
            score += 2
            signals.append(f"RSI w strefie wyprzedania {rsi:.0f}")
        elif rsi > 75:
            score -= 3
            signals.append(f"KARA: RSI wykupiony {rsi:.0f} — zle na LONG")

        # MACD bullish crossover
        if macd > macd_signal and prev_macd <= prev_macd_signal:
            score += 3
            signals.append("MACD swiezy bullish crossover")
        elif macd > macd_signal:
            score += 1
            signals.append("MACD bullish")

        # Histogram flip
        prev_hist = float(f.get("prev_macd_hist", macd_hist))
        if macd_hist > 0 and prev_hist <= 0:
            score += 2
            signals.append("Histogram MACD flip na plus")

        # Bollinger bounce from bottom
        if bb_position <= 0.1:
            score += 3
            signals.append("Cena na dole Bollingera — LONG bounce")
        elif bb_position <= 0.25:
            score += 1
            signals.append("Cena blisko dolnej wstegi")

        # Price > VWAP
        if close > vwap and vwap > 0:
            score += 1
            signals.append("Cena > VWAP")

        # Volume
        if volume_change > 0.15:
            score += 2
            signals.append(f"Wolumen +{volume_change*100:.0f}%")

        # Probability
        if up_prob >= 62:
            score += 2
            signals.append(f"Up prob {up_prob:.0f}%")
        if bottom_prob >= 60:
            score += 2
            signals.append(f"Bottom signal {bottom_prob:.0f}%")

        # Whale
        if whale_signal == "WHALE_BUY":
            score += 3
            signals.append("🐋 Wieloryb kupuje")
        elif whale_signal == "WHALE_SELL":
            score -= 3
            signals.append("KARA: 🐋 Wieloryb sprzedaje")

        # ── Bybit perpetual signals (if available) ──
        perp = f.get("_perp")
        if perp:
            fr = perp.get("funding_rate", 0)
            fs = perp.get("funding_signal", "NEUTRAL")
            oi_trend = perp.get("oi_trend", "UNKNOWN")
            premium = perp.get("premium_pct", 0)

            # Negative funding = shorts pay longs = LONG is profitable to hold
            if fr < -0.0001:
                score += 2
                signals.append(f"Funding ujemny {fr*100:.3f}% — LONG zarabia na funding")
            elif fs == "HIGH_LONG_COST":
                score -= 2
                signals.append(f"Funding wysoki {fr*100:.3f}% — drogi LONG")

            # Rising OI + LONG = more conviction
            if oi_trend == "RISING":
                score += 1
                signals.append(f"OI rośnie {perp.get('oi_change_pct', 0):.1f}% — popyt")
            elif oi_trend == "FALLING":
                score -= 1
                signals.append("OI spada — pozycje zamykane")

            # Discount (mark < index) = long opportunity
            if premium < -0.05:
                score += 1
                signals.append(f"Dyskonto mark/index {premium:.2f}%")

        return {"score": score, "signals": signals}

    # ──────────────────────────────────────────────────
    # SHORT SCORING
    # ──────────────────────────────────────────────────

    def _score_short(self, f: dict, profile: dict) -> dict:
        score = 0
        signals: list[str] = []

        rsi = float(f["rsi"])
        macd = float(f["macd"])
        macd_signal = float(f["macd_signal"])
        macd_hist = float(f["macd_hist"])
        trend = str(f["trend"])
        volume_change = float(f["volume_change"])
        top_prob = float(f.get("top_probability", 50))
        up_prob = float(f.get("up_probability", 50))
        prev_macd = float(f.get("prev_macd", macd))
        prev_macd_signal = float(f.get("prev_macd_signal", macd_signal))
        close = float(f["close"])
        vwap = float(f.get("vwap", close))
        bb_position = 0.5
        bb_upper = float(f.get("bb_upper", close))
        bb_lower = float(f.get("bb_lower", close))
        if bb_upper != bb_lower and bb_lower > 0:
            bb_position = (close - bb_lower) / (bb_upper - bb_lower)

        whale_signal = str(f.get("whale_signal", "NONE"))

        # Trend DOWN strong for SHORT
        if trend == "DOWN":
            score += 3
            signals.append("Trend DOWN — dobry na SHORT")
        elif trend == "UP":
            score -= 3
            signals.append("KARA: Trend UP — SHORT ryzykowny")

        # RSI overbought zone for SHORT
        if rsi > 75:
            score += 3
            signals.append(f"RSI mocno wykupiony {rsi:.0f} — dobry SHORT")
        elif rsi > 65:
            score += 2
            signals.append(f"RSI w strefie wykupienia {rsi:.0f}")
        elif rsi < 30:
            score -= 3
            signals.append(f"KARA: RSI wyprzedany {rsi:.0f} — zle na SHORT")

        # MACD bearish crossover
        if macd < macd_signal and prev_macd >= prev_macd_signal:
            score += 3
            signals.append("MACD swiezy bearish crossover")
        elif macd < macd_signal:
            score += 1
            signals.append("MACD bearish")

        # Histogram flip
        prev_hist = float(f.get("prev_macd_hist", macd_hist))
        if macd_hist < 0 and prev_hist >= 0:
            score += 2
            signals.append("Histogram MACD flip na minus")

        # Bollinger touch upper band
        if bb_position >= 0.95:
            score += 3
            signals.append("Cena na gorze Bollingera — SHORT overbought")
        elif bb_position >= 0.80:
            score += 1
            signals.append("Cena blisko gornej wstegi")

        # Price < VWAP
        if close < vwap and vwap > 0:
            score += 1
            signals.append("Cena < VWAP (presja sprzedazy)")

        # Volume
        if volume_change > 0.15:
            score += 1
            signals.append(f"Wolumen +{volume_change*100:.0f}%")

        # Probability
        if top_prob >= 62:
            score += 2
            signals.append(f"Top prob {top_prob:.0f}%")
        if up_prob <= 38:
            score += 2
            signals.append(f"Niska up prob {up_prob:.0f}%")

        # Whale
        if whale_signal == "WHALE_SELL":
            score += 3
            signals.append("🐋 Wieloryb sprzedaje — SHORT signal")
        elif whale_signal == "WHALE_BUY":
            score -= 3
            signals.append("KARA: 🐋 Wieloryb kupuje — SHORT niebezpieczny")

        # ── Bybit perpetual signals (if available) ──
        perp = f.get("_perp")
        if perp:
            fr = perp.get("funding_rate", 0)
            fs = perp.get("funding_signal", "NEUTRAL")
            oi_trend = perp.get("oi_trend", "UNKNOWN")
            premium = perp.get("premium_pct", 0)

            # Positive high funding = longs crowded = good SHORT opportunity
            if fs == "HIGH_LONG_COST":
                score += 2
                signals.append(f"Funding wysoki {fr*100:.3f}% — crowded longs, SHORT profitable")
            elif fr < -0.0001:
                score -= 2
                signals.append(f"Funding ujemny {fr*100:.3f}% — SHORT kosztowny")

            # Falling OI with price drop = cascading liquidations = SHORT momentum
            if oi_trend == "FALLING":
                score += 1
                signals.append(f"OI spada {perp.get('oi_change_pct', 0):.1f}% — likwidacje")
            elif oi_trend == "RISING":
                score -= 1
                signals.append("OI rośnie — nowe pozycje, ryzykowny SHORT")

            # Premium (mark > index) = SHORT has gravity pull
            if premium > 0.05:
                score += 1
                signals.append(f"Premium mark/index +{premium:.2f}% — SHORT mean-reversion")

        return {"score": score, "signals": signals}

    # ──────────────────────────────────────────────────
    # EXIT evaluation for existing position
    # ──────────────────────────────────────────────────

    def _evaluate_exit(self, session: Session, trade: LeverageSimTrade, f: dict, close: float, profile: dict) -> dict | None:
        """Check if open leverage position should be closed."""

        # 1. Apply funding fee (simulate 8h funding)
        self._apply_funding(trade)

        # 2. Check liquidation
        if trade.side == "LONG" and close <= trade.liquidation_price:
            return self._close_position(session, trade, close, "liquidation")
        if trade.side == "SHORT" and close >= trade.liquidation_price:
            return self._close_position(session, trade, close, "liquidation")

        # 3. Check stop loss
        if trade.stop_loss:
            if trade.side == "LONG" and close <= trade.stop_loss:
                return self._close_position(session, trade, close, "stop_loss")
            if trade.side == "SHORT" and close >= trade.stop_loss:
                return self._close_position(session, trade, close, "stop_loss")

        # 4. Check take profit
        if trade.take_profit:
            if trade.side == "LONG" and close >= trade.take_profit:
                return self._close_position(session, trade, close, "take_profit")
            if trade.side == "SHORT" and close <= trade.take_profit:
                return self._close_position(session, trade, close, "take_profit")

        # 5. Signal-based exit
        rsi = float(f["rsi"])
        macd = float(f["macd"])
        macd_signal_val = float(f["macd_signal"])
        prev_macd = float(f.get("prev_macd", macd))
        prev_macd_signal = float(f.get("prev_macd_signal", macd_signal_val))
        hold_hours = (datetime.utcnow() - trade.opened_at).total_seconds() / 3600

        exit_score = 0

        if trade.side == "LONG":
            if rsi > 75:
                exit_score += 3
            if macd < macd_signal_val and prev_macd >= prev_macd_signal:
                exit_score += 3
            if float(f.get("top_probability", 50)) >= 65:
                exit_score += 2
        else:  # SHORT
            if rsi < 30:
                exit_score += 3
            if macd > macd_signal_val and prev_macd <= prev_macd_signal:
                exit_score += 3
            if float(f.get("bottom_probability", 50)) >= 65:
                exit_score += 2

        # Time-based rotation (max hold)
        max_hold = float(profile.get("max_hold_hours", 72))
        if hold_hours >= max_hold:
            exit_score += 4

        if exit_score >= 4:
            return self._close_position(session, trade, close, "signal")

        return None

    # ──────────────────────────────────────────────────
    # CLOSE position
    # ──────────────────────────────────────────────────

    def _close_position(self, session: Session, trade: LeverageSimTrade, exit_price: float, reason: str) -> dict:
        """Close a paper leverage position and calculate P&L."""
        if trade.side == "LONG":
            raw_pnl = (exit_price - trade.entry_price) / trade.entry_price * trade.margin_used * trade.leverage
        else:  # SHORT
            raw_pnl = (trade.entry_price - exit_price) / trade.entry_price * trade.margin_used * trade.leverage

        # Subtract funding fees
        pnl = raw_pnl - trade.funding_fees

        if reason == "liquidation":
            pnl = -trade.margin_used  # lose all margin on liquidation

        pnl_pct = pnl / trade.margin_used * 100 if trade.margin_used else 0

        trade.exit_price = exit_price
        trade.pnl = round(pnl, 2)
        trade.pnl_pct = round(pnl_pct, 2)
        trade.status = "LIQUIDATED" if reason == "liquidation" else "CLOSED"
        trade.close_reason = reason
        trade.closed_at = datetime.utcnow()

        _log.info(
            "LEVERAGE CLOSE %s %s %sx | entry=$%.2f exit=$%.2f | P&L=$%.2f (%.1f%%) | reason=%s | funding=$%.4f",
            trade.side, trade.symbol, trade.leverage,
            trade.entry_price, exit_price, pnl, pnl_pct, reason, trade.funding_fees,
        )

        # Feed result to learning system
        try:
            from app.services.learning import LearningService
            learning = LearningService()
            _result = "WIN" if pnl > 0 else "LOSS"
            learning.log_live_trade_result(
                session,
                symbol=trade.symbol,
                result=_result,
                profit_pct=round(pnl_pct, 2),
                market_state=f"leverage_{trade.side}_{trade.leverage}x",
                notes=f"reason={reason} entry={trade.entry_price:.2f} exit={exit_price:.2f} funding={trade.funding_fees:.4f}",
            )
        except Exception:
            _log.debug("Could not log leverage trade to learning system", exc_info=True)

        return {
            "action": f"CLOSE_{trade.side}",
            "symbol": trade.symbol,
            "leverage": trade.leverage,
            "entry_price": trade.entry_price,
            "exit_price": exit_price,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "reason": reason,
            "margin_used": trade.margin_used,
        }

    # ──────────────────────────────────────────────────
    # FUNDING FEE simulation
    # ──────────────────────────────────────────────────

    def _apply_funding(self, trade: LeverageSimTrade) -> None:
        """Simulate funding fee charges every 8 hours."""
        if trade.opened_at is None:
            return
        hours_open = (datetime.utcnow() - trade.opened_at).total_seconds() / 3600
        expected_charges = int(hours_open / FUNDING_INTERVAL_HOURS)
        notional = trade.margin_used * trade.leverage
        expected_funding = expected_charges * notional * FUNDING_RATE_DEFAULT
        if expected_funding > trade.funding_fees:
            trade.funding_fees = round(expected_funding, 6)

    # ──────────────────────────────────────────────────
    # LEVERAGE PROGRESSION (Playbook 18)
    # ──────────────────────────────────────────────────

    def _current_leverage(self, session: Session) -> float:
        """Determine allowed leverage based on consecutive winning trades."""
        recent = session.execute(
            select(LeverageSimTrade)
            .where(LeverageSimTrade.status.in_(["CLOSED", "LIQUIDATED"]))
            .order_by(LeverageSimTrade.closed_at.desc())
            .limit(50)
        ).scalars().all()

        consecutive_wins = 0
        for t in recent:
            if (t.pnl or 0) > 0:
                consecutive_wins += 1
            else:
                break

        # Check for recent loss → reduce leverage
        if recent and (recent[0].pnl or 0) < 0:
            return 2  # reset to min after any loss

        leverage = 2
        for wins_required, lev in LEVERAGE_PROGRESSION:
            if consecutive_wins >= wins_required:
                leverage = lev
        return leverage

    # ──────────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────────

    def _get_open_position(self, session: Session, symbol: str) -> LeverageSimTrade | None:
        return session.execute(
            select(LeverageSimTrade)
            .where(LeverageSimTrade.symbol == symbol, LeverageSimTrade.status == "OPEN")
        ).scalar_one_or_none()

    def _count_open_positions(self, session: Session) -> int:
        return int(session.execute(
            select(func.count(LeverageSimTrade.id)).where(LeverageSimTrade.status == "OPEN")
        ).scalar_one())

    def _available_margin(self, session: Session) -> float:
        """Calculate available margin from virtual leverage wallet."""
        used = session.execute(
            select(func.coalesce(func.sum(LeverageSimTrade.margin_used), 0.0))
            .where(LeverageSimTrade.status == "OPEN")
        ).scalar_one()
        realized = session.execute(
            select(func.coalesce(func.sum(LeverageSimTrade.pnl), 0.0))
            .where(LeverageSimTrade.status.in_(["CLOSED", "LIQUIDATED"]))
        ).scalar_one()
        return LEVERAGE_PAPER_BALANCE + float(realized) - float(used)

    # ──────────────────────────────────────────────────
    # SNAPSHOT for dashboard
    # ──────────────────────────────────────────────────

    def get_snapshot(self, session: Session) -> dict:
        """Get full leverage paper portfolio state."""
        open_trades = session.execute(
            select(LeverageSimTrade).where(LeverageSimTrade.status == "OPEN")
            .order_by(LeverageSimTrade.opened_at.desc())
        ).scalars().all()
        closed_trades = session.execute(
            select(LeverageSimTrade).where(LeverageSimTrade.status.in_(["CLOSED", "LIQUIDATED"]))
            .order_by(LeverageSimTrade.closed_at.desc()).limit(50)
        ).scalars().all()

        total_pnl = sum(t.pnl or 0 for t in closed_trades)
        wins = [t for t in closed_trades if (t.pnl or 0) > 0]
        losses = [t for t in closed_trades if (t.pnl or 0) <= 0]
        liquidations = [t for t in closed_trades if t.status == "LIQUIDATED"]
        win_rate = len(wins) / len(closed_trades) * 100 if closed_trades else 0
        available = self._available_margin(session)
        current_lev = self._current_leverage(session)

        return {
            "paper_balance": round(LEVERAGE_PAPER_BALANCE, 2),
            "available_margin": round(available, 2),
            "current_equity": round(available + sum(t.margin_used for t in open_trades), 2),
            "total_realized_pnl": round(total_pnl, 2),
            "current_leverage_level": current_lev,
            "win_rate": round(win_rate, 1),
            "total_trades": len(closed_trades),
            "wins": len(wins),
            "losses": len(losses),
            "liquidations": len(liquidations),
            "open_positions": [
                {
                    "id": t.id,
                    "symbol": t.symbol,
                    "side": t.side,
                    "leverage": t.leverage,
                    "entry_price": t.entry_price,
                    "margin_used": round(t.margin_used, 2),
                    "liquidation_price": round(t.liquidation_price, 2),
                    "take_profit": round(t.take_profit, 2) if t.take_profit else None,
                    "stop_loss": round(t.stop_loss, 2) if t.stop_loss else None,
                    "funding_fees": round(t.funding_fees, 4),
                    "opened_at": t.opened_at.isoformat() + "Z",
                    "decision_reason": t.decision_reason,
                }
                for t in open_trades
            ],
            "recent_closed": [
                {
                    "symbol": t.symbol,
                    "side": t.side,
                    "leverage": t.leverage,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "pnl": round(t.pnl or 0, 2),
                    "pnl_pct": round(t.pnl_pct or 0, 1),
                    "close_reason": t.close_reason,
                    "status": t.status,
                    "funding_fees": round(t.funding_fees, 4),
                    "closed_at": t.closed_at.isoformat() + "Z" if t.closed_at else None,
                }
                for t in closed_trades[:20]
            ],
        }
