from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from django.db.models import Count, Sum

from app.models import Decision, LearningLog, SignalPerformance, SimulatedTrade

logger = logging.getLogger(__name__)

# Minimum closed trades before adaptive feedback kicks in
MIN_TRADES_FOR_ADAPTATION = 30
# Minimum times a signal must fire before we trust its win rate
MIN_SIGNAL_SAMPLES = 10
# How many recent trades to use for adaptive feedback
ADAPTATION_WINDOW = 100


class LearningService:
    """Full learning pipeline: snapshot storage, signal tracking, adaptive feedback."""

    # ── Entry snapshot: store indicators at BUY time on Decision ──

    @staticmethod
    def store_entry_snapshot(decision: Decision, feature_row: dict, buy_signals: list[str]) -> None:
        """Called right after a BUY Decision is created. Persists indicators + signal list."""
        snapshot = {
            "signals": buy_signals,
            "rsi": float(feature_row.get("rsi", 0)),
            "macd_hist": float(feature_row.get("macd_hist", 0)),
            "trend": str(feature_row.get("trend", "")),
            "up_probability": float(feature_row.get("up_probability", 50)),
            "bb_position": _bb_position(feature_row),
            "close": float(feature_row.get("close", 0)),
            "volume_change": float(feature_row.get("volume_change", 0)),
            "whale_signal": str(feature_row.get("whale_signal", "NONE")),
            # HTF snapshot for learning context
            "htf_trend": str(feature_row.get("htf_trend", "")),
            "htf_rsi": float(feature_row.get("htf_rsi", 50)),
        }
        decision.signals_json = json.dumps(snapshot, ensure_ascii=False)
        # BUGFIX: persist signals_json to DB (previously mutation was lost because Decision
        # was already saved in decision_engine before this call).
        try:
            decision.save(update_fields=["signals_json"])
        except Exception:
            logger.exception("store_entry_snapshot: save failed for decision %s", getattr(decision, "id", None))

    # ── Trade result logging with full context ──

    def log_trade_result(
        self,
        trade: SimulatedTrade,
        market_state: str,
        notes: str,
        exit_feature_row: dict | None = None,
    ) -> None:
        """Log a closed paper trade with entry + exit indicators and update signal stats."""
        profit_pct = 0.0
        if trade.buy_value and trade.buy_value > 0:
            sell_val = (trade.sell_value or 0) - (trade.sell_fee or 0)
            buy_val = trade.buy_value + (trade.buy_fee or 0)
            profit_pct = (sell_val - buy_val) / buy_val * 100 if buy_val > 0 else 0.0

        hold_hours = 0.0
        if trade.opened_at and trade.closed_at:
            hold_hours = (trade.closed_at - trade.opened_at).total_seconds() / 3600

        # Retrieve entry snapshot from the BUY Decision
        entry_snapshot = {}
        entry_signals: list[str] = []
        if trade.decision_id:
            buy_decision = Decision.objects.filter(pk=trade.decision_id).first()
            if buy_decision and buy_decision.signals_json:
                try:
                    entry_snapshot = json.loads(buy_decision.signals_json)
                    entry_signals = entry_snapshot.get("signals", [])
                except (json.JSONDecodeError, TypeError):
                    pass

        was_profitable = (trade.profit or 0) > 0
        result = "WIN" if was_profitable else "LOSS"

        log_entry = LearningLog(
            decision_id=trade.decision_id,
            result=result,
            was_profitable=was_profitable,
            market_state=market_state,
            notes=notes,
            symbol=trade.symbol,
            profit_pct=round(profit_pct, 4),
            hold_hours=round(hold_hours, 2),
            entry_signals_json=json.dumps(entry_signals, ensure_ascii=False) if entry_signals else None,
            entry_rsi=entry_snapshot.get("rsi"),
            entry_macd_hist=entry_snapshot.get("macd_hist"),
            entry_trend=entry_snapshot.get("trend"),
            entry_up_prob=entry_snapshot.get("up_probability"),
            entry_bb_pos=entry_snapshot.get("bb_position"),
            exit_rsi=float(exit_feature_row.get("rsi", 0)) if exit_feature_row else None,
            exit_macd_hist=float(exit_feature_row.get("macd_hist", 0)) if exit_feature_row else None,
            exit_trend=str(exit_feature_row.get("trend", "")) if exit_feature_row else None,
            exit_up_prob=float(exit_feature_row.get("up_probability", 50)) if exit_feature_row else None,
        )
        log_entry.save()

        # Update per-signal performance stats
        self._update_signal_performance(entry_signals, was_profitable, profit_pct)

        logger.info(
            "LEARN %s: %s pnl=%.2f%% hold=%.1fh signals=%d entry_rsi=%.0f exit_rsi=%.0f",
            trade.symbol, result, profit_pct, hold_hours,
            len(entry_signals),
            entry_snapshot.get("rsi", 0),
            float(exit_feature_row.get("rsi", 0)) if exit_feature_row else 0,
        )

    def log_live_trade_result(
        self,
        symbol: str,
        result: str,
        profit_pct: float,
        market_state: str,
        notes: str,
    ) -> None:
        """Log a LIVE trade outcome for learning (no SimulatedTrade needed)."""
        LearningLog(
            decision_id=None,
            result=result,
            was_profitable=profit_pct > 0,
            market_state=market_state,
            notes=f"[LIVE {symbol}] pnl={profit_pct:.2f}% | {notes}",
            symbol=symbol,
            profit_pct=round(profit_pct, 4),
        ).save()

    # ── Signal performance tracking ──

    def _update_signal_performance(
        self, signals: list[str], was_win: bool, profit_pct: float,
    ) -> None:
        """Update win/loss stats for each signal that fired at entry."""
        for raw_signal in signals:
            # Normalize: strip emoji and numbers for grouping
            signal_name = _normalize_signal_name(raw_signal)
            if not signal_name:
                continue

            row = SignalPerformance.objects.filter(signal_name=signal_name).first()

            if row is None:
                row = SignalPerformance(
                    signal_name=signal_name,
                    total_fired=1,
                    wins=1 if was_win else 0,
                    losses=0 if was_win else 1,
                    avg_profit_pct=profit_pct,
                )
                row.save()
            else:
                row.total_fired += 1
                if was_win:
                    row.wins += 1
                else:
                    row.losses += 1
                # Running average profit
                row.avg_profit_pct = (
                    row.avg_profit_pct * (row.total_fired - 1) + profit_pct
                ) / row.total_fired
                row.save()

    # ── Adaptive feedback: compute threshold adjustments ──

    def get_adaptive_adjustments(self) -> dict[str, float] | None:
        """Compute threshold adjustments based on recent trade performance.
        Returns None if insufficient data (< MIN_TRADES_FOR_ADAPTATION trades).
        Otherwise returns dict with delta adjustments for profile thresholds."""
        recent_logs = list(LearningLog.objects.filter(profit_pct__isnull=False).order_by('-timestamp')[:ADAPTATION_WINDOW])

        if len(recent_logs) < MIN_TRADES_FOR_ADAPTATION:
            return None

        wins = [l for l in recent_logs if l.was_profitable]
        losses = [l for l in recent_logs if not l.was_profitable]
        win_rate = len(wins) / len(recent_logs)
        avg_win = sum(l.profit_pct for l in wins) / len(wins) if wins else 0
        avg_loss = sum(abs(l.profit_pct) for l in losses) / len(losses) if losses else 0

        adjustments: dict[str, float] = {}

        # buy_score_threshold: raise if losing too much, lower if winning well
        if win_rate < 0.35:
            adjustments["buy_score_threshold_delta"] = +1
        elif win_rate < 0.42:
            adjustments["buy_score_threshold_delta"] = +0.5
        elif win_rate > 0.58:
            adjustments["buy_score_threshold_delta"] = -1
        elif win_rate > 0.52:
            adjustments["buy_score_threshold_delta"] = -0.5
        else:
            adjustments["buy_score_threshold_delta"] = 0

        # profit_target: converge toward 70% of average winning trade
        if avg_win > 0:
            adjustments["suggested_profit_target"] = round(avg_win * 0.7 / 100, 4)

        # stop_loss: converge toward 80% of average losing trade
        if avg_loss > 0:
            adjustments["suggested_stop_loss"] = round(avg_loss * 0.8 / 100, 4)

        adjustments["win_rate"] = round(win_rate, 4)
        adjustments["avg_win_pct"] = round(avg_win, 4)
        adjustments["avg_loss_pct"] = round(avg_loss, 4)
        adjustments["sample_count"] = len(recent_logs)

        return adjustments

    # ── Signal quality rankings ──

    def get_signal_rankings(self) -> list[dict]:
        """Return signals ranked by win rate (only those with enough samples)."""
        rows = list(SignalPerformance.objects.filter(total_fired__gte=MIN_SIGNAL_SAMPLES).order_by('-wins'))

        rankings = []
        for r in rows:
            win_rate = r.wins / r.total_fired if r.total_fired > 0 else 0
            rankings.append({
                "signal": r.signal_name,
                "fired": r.total_fired,
                "wins": r.wins,
                "losses": r.losses,
                "win_rate": round(win_rate, 4),
                "avg_profit_pct": round(r.avg_profit_pct, 4),
            })
        rankings.sort(key=lambda x: x["win_rate"], reverse=True)
        return rankings

    def get_performance_summary(self) -> dict:
        """Quick summary of recent learning performance."""
        total = LearningLog.objects.count()
        recent_30d = LearningLog.objects.filter(
            timestamp__gte=datetime.utcnow() - timedelta(days=30)
        ).count()
        wins_30d = LearningLog.objects.filter(
            timestamp__gte=datetime.utcnow() - timedelta(days=30),
            was_profitable=True,
        ).count()
        adjustments = self.get_adaptive_adjustments()
        return {
            "total_logged_trades": total,
            "trades_last_30d": recent_30d,
            "wins_last_30d": wins_30d,
            "win_rate_30d": round(wins_30d / recent_30d, 4) if recent_30d > 0 else 0,
            "adaptive_adjustments": adjustments,
            "adaptation_active": adjustments is not None,
        }


def _bb_position(feature_row: dict) -> float | None:
    """Calculate Bollinger Band position (0 = lower band, 1 = upper band)."""
    close = float(feature_row.get("close", 0))
    bb_upper = float(feature_row.get("bb_upper", 0))
    bb_lower = float(feature_row.get("bb_lower", 0))
    if bb_upper > bb_lower > 0:
        return round((close - bb_lower) / (bb_upper - bb_lower), 4)
    return None


def _normalize_signal_name(raw: str) -> str:
    """Normalize signal name for consistent grouping.
    Strips numeric values, emoji, and trailing specifics."""
    import re
    # Remove emoji
    name = re.sub(r'[\U0001F300-\U0001F9FF]', '', raw).strip()
    # Remove numeric values in parentheses like (65.2%) or (3.4x)
    name = re.sub(r'\([^)]*\d+[^)]*\)', '', name).strip()
    # Remove trailing numbers with units like +15%, 3.2x, Score=7.5
    name = re.sub(r'[\s:=]+[\d.]+[%xσ]?\s*$', '', name).strip()
    # Collapse whitespace
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:128] if name else ""