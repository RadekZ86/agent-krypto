"""Per-symbol learning: oblicza statystyki win/loss per symbol i dostarcza adjustment
do progu zakupu (buy_score_threshold).

Zasada:
- Symbol z wysokim winrate (>= 0.55) i co najmniej 10 zamknietymi transakcjami → -1 do progu
  (bardziej "agresywny" — agent ufa temu walorowi).
- Symbol ze slabym winrate (< 0.30) → +2 do progu (zwykle slaby setup).
- Symbol "katastroficzny" (winrate < 0.15 i >= 15 trades) → +4 (praktyczny block).
- Symbol bez wystarczajacych danych → 0 (brak zmian).

Wynik jest cache'owany na 5 minut zeby nie zapychac DB w kazdym cyklu.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Dict

from django.db.models import Avg, Count, Q

from app.models import LearningLog

logger = logging.getLogger(__name__)

MIN_TRADES_FOR_PER_SYMBOL = 10
LOOKBACK_DAYS = 30
CACHE_TTL_SECONDS = 300

_cache: Dict[str, object] = {"timestamp": 0.0, "data": {}}


def _compute_per_symbol_stats() -> dict[str, dict[str, float]]:
    """Zwraca {symbol: {trades, wins, losses, win_rate, avg_pnl_pct}}."""
    cutoff = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)
    qs = (
        LearningLog.objects
        .filter(timestamp__gte=cutoff, profit_pct__isnull=False, symbol__isnull=False)
        .values("symbol")
        .annotate(
            trades=Count("id"),
            wins=Count("id", filter=Q(was_profitable=True)),
            losses=Count("id", filter=Q(was_profitable=False)),
            avg_pnl=Avg("profit_pct"),
        )
    )
    stats: dict[str, dict[str, float]] = {}
    for row in qs:
        sym = (row.get("symbol") or "").upper()
        if not sym:
            continue
        trades = int(row["trades"] or 0)
        wins = int(row["wins"] or 0)
        win_rate = (wins / trades) if trades > 0 else 0.0
        stats[sym] = {
            "trades": trades,
            "wins": wins,
            "losses": int(row["losses"] or 0),
            "win_rate": round(win_rate, 3),
            "avg_pnl_pct": round(float(row["avg_pnl"] or 0.0), 3),
        }
    return stats


def get_symbol_stats(force_refresh: bool = False) -> dict[str, dict[str, float]]:
    now = time.time()
    if not force_refresh and (now - float(_cache.get("timestamp", 0.0))) < CACHE_TTL_SECONDS:
        return _cache.get("data", {})  # type: ignore[return-value]
    try:
        data = _compute_per_symbol_stats()
        _cache["data"] = data
        _cache["timestamp"] = now
        return data
    except Exception:
        logger.exception("symbol_learning: nie udalo sie obliczyc statystyk")
        return _cache.get("data", {})  # type: ignore[return-value]


def get_symbol_threshold_adjustment(symbol: str) -> tuple[int, str | None]:
    """Zwraca (delta_to_buy_threshold, reason_or_None).

    delta > 0  → bardziej restrykcyjnie (trudniej kupic)
    delta < 0  → bardziej elastycznie (latwiej kupic)
    """
    if not symbol:
        return 0, None
    stats = get_symbol_stats()
    sym = symbol.upper()
    info = stats.get(sym)
    if not info:
        return 0, None
    trades = int(info.get("trades", 0))
    if trades < MIN_TRADES_FOR_PER_SYMBOL:
        return 0, None
    wr = float(info.get("win_rate", 0.0))
    if trades >= 15 and wr < 0.15:
        return 4, f"Per-symbol BLOCK {sym}: win_rate={wr:.0%} ({trades} trades)"
    if wr < 0.30:
        return 2, f"Per-symbol PENALTY {sym}: win_rate={wr:.0%} ({trades} trades)"
    if wr >= 0.55:
        return -1, f"Per-symbol BONUS {sym}: win_rate={wr:.0%} ({trades} trades)"
    return 0, None
