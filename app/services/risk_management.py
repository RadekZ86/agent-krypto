"""Risk Management Service — capital preservation for trading agent.

Responsibilities:
- Max daily loss circuit breaker (halt trading for 24h if portfolio down > threshold)
- Loss streak cooldown (pause after N consecutive losses)
- Correlation with BTC (risk-off when BTC dumps)
- Return risk-adjusted multiplier for position sizing
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Literal

from app.config import settings
from app.models import SimulatedTrade
from app.services.market_data import LiveQuoteService, load_latest_market_row

logger = logging.getLogger(__name__)

# ── Risk parameters (tunable) ──
MAX_DAILY_LOSS_PCT = 0.03          # halt trading if portfolio equity down >3% in 24h
LOSS_STREAK_LIMIT = 4              # cooldown after 4 consecutive losses (was 3)
LOSS_STREAK_COOLDOWN_HOURS = 3     # pause duration after streak (was 6)
BTC_RISK_OFF_THRESHOLD = -0.02     # BTC dropped >2% in 1h => risk-off
BTC_STRONG_DUMP_THRESHOLD = -0.04  # BTC dropped >4% in 1h => hard stop on new buys
MAX_POSITIONS_RISK_ON = 6          # normal mode position cap
MAX_POSITIONS_RISK_OFF = 2         # during risk-off, only hold existing


RiskLevel = Literal["NORMAL", "CAUTIOUS", "RISK_OFF", "HALT"]


class RiskManager:
    """Evaluates portfolio health and market conditions, returns risk directives."""

    def __init__(self) -> None:
        self.live_quotes = LiveQuoteService()

    # ── Public API ──
    def assess(self) -> dict:
        """Run all checks. Returns:
        {
            "level": "NORMAL|CAUTIOUS|RISK_OFF|HALT",
            "allow_new_buys": bool,
            "position_size_multiplier": 0.0-1.0,
            "reasons": [str],
            "btc_change_1h_pct": float | None,
        }
        """
        reasons: list[str] = []
        level: RiskLevel = "NORMAL"
        allow_new_buys = True
        size_mult = 1.0

        # 1. Max daily loss circuit breaker
        daily_loss_pct = self._daily_loss_pct()
        if daily_loss_pct is not None and daily_loss_pct <= -MAX_DAILY_LOSS_PCT:
            level = "HALT"
            allow_new_buys = False
            size_mult = 0.0
            reasons.append(
                f"STOP: dzienny spadek portfela {daily_loss_pct*100:.1f}% "
                f"(prog {-MAX_DAILY_LOSS_PCT*100:.0f}%)"
            )

        # 2. Loss streak cooldown
        streak, last_loss_at = self._current_loss_streak()
        if streak >= LOSS_STREAK_LIMIT and last_loss_at is not None:
            elapsed = (datetime.utcnow() - last_loss_at).total_seconds() / 3600
            if elapsed < LOSS_STREAK_COOLDOWN_HOURS:
                if level != "HALT":
                    level = "HALT"
                allow_new_buys = False
                size_mult = 0.0
                reasons.append(
                    f"Pauza {LOSS_STREAK_COOLDOWN_HOURS}h po {streak} stratach z rzedu "
                    f"(zostalo {LOSS_STREAK_COOLDOWN_HOURS - elapsed:.1f}h)"
                )

        # 3. BTC correlation / risk-off
        btc_change = self._btc_change_1h_pct()
        if btc_change is not None:
            if btc_change <= BTC_STRONG_DUMP_THRESHOLD:
                if level != "HALT":
                    level = "RISK_OFF"
                allow_new_buys = False
                size_mult = min(size_mult, 0.0)
                reasons.append(f"BTC gwaltownie spada ({btc_change*100:.2f}% / 1h) - zablokowane nowe kupna")
            elif btc_change <= BTC_RISK_OFF_THRESHOLD:
                if level == "NORMAL":
                    level = "CAUTIOUS"
                size_mult = min(size_mult, 0.5)
                reasons.append(f"BTC spada ({btc_change*100:.2f}% / 1h) - alokacja x0.5")

        return {
            "level": level,
            "allow_new_buys": allow_new_buys,
            "position_size_multiplier": round(size_mult, 3),
            "reasons": reasons,
            "btc_change_1h_pct": round(btc_change * 100, 3) if btc_change is not None else None,
            "daily_loss_pct": round(daily_loss_pct * 100, 2) if daily_loss_pct is not None else None,
            "loss_streak": streak,
        }

    # ── Internals ──
    def _daily_loss_pct(self) -> float | None:
        """Calculate today's realized P&L as % of starting balance."""
        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        trades = list(SimulatedTrade.objects.filter(closed_at__gte=start, status="CLOSED"))
        if not trades:
            return None
        realized = sum(float(t.profit or 0.0) for t in trades)
        baseline = float(settings.starting_balance_quote) or 1000.0
        if baseline <= 0:
            return None
        return realized / baseline

    def _current_loss_streak(self) -> tuple[int, datetime | None]:
        """Count consecutive losing trades from most recent closed trade backwards."""
        trades = list(
            SimulatedTrade.objects.filter(status="CLOSED").order_by("-closed_at")[:20]
        )
        streak = 0
        last_loss_at: datetime | None = None
        for t in trades:
            if (t.profit or 0.0) < 0:
                streak += 1
                if last_loss_at is None:
                    last_loss_at = t.closed_at
            else:
                break
        return streak, last_loss_at

    def _btc_change_1h_pct(self) -> float | None:
        """BTC price change over last hour (fraction, e.g. -0.02 = -2%)."""
        try:
            quote = self.live_quotes.get_quote("BTC")
            current = float(quote["price"]) if quote else None
        except Exception:
            current = None

        if current is None:
            row = load_latest_market_row("BTC")
            if row is None:
                return None
            current = float(row.close)

        # Get price from ~1h ago via historical row
        try:
            from app.models import MarketData
            hour_ago = datetime.utcnow() - timedelta(hours=1, minutes=5)
            past = MarketData.objects.filter(
                symbol="BTC",
                timestamp__lte=datetime.utcnow() - timedelta(minutes=50),
                timestamp__gte=hour_ago - timedelta(minutes=30),
            ).order_by("-timestamp").first()
        except Exception:
            past = None

        if past is None:
            return None
        past_price = float(past.close)
        if past_price <= 0:
            return None
        return (current - past_price) / past_price
