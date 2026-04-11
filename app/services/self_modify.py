"""Self-modification engine — allows the AI agent to adjust its own parameters.

Only callable by the designated admin user. Supports:
  - Adjusting profile thresholds (buy_score_threshold, profit_target, stop_loss, etc.)
  - Setting agent mode
  - Viewing / resetting signal performance
  - Viewing learning stats & adaptive state
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import RuntimeSetting, SignalPerformance
from app.services.learning import LearningService
from app.services.runtime_state import RuntimeStateService

logger = logging.getLogger(__name__)

# Only this email can trigger self-modification
ADMIN_EMAIL = "zajcu1986@wp.pl"

# Keys that can be overridden per-profile via RuntimeSetting
ALLOWED_OVERRIDES = {
    "buy_score_threshold": (1, 10, int),
    "profit_target": (0.005, 0.15, float),
    "stop_loss": (0.005, 0.15, float),
    "max_hold_hours": (1, 168, int),
    "max_trades_per_day": (1, 9999, int),
    "max_open_positions": (1, 9999, int),
    "exploration_rate": (0.0, 0.5, float),
    "allocation_scale": (0.1, 3.0, float),
}


def is_admin(user) -> bool:
    """Check if user is the designated admin."""
    if user is None:
        return False
    return getattr(user, "email", None) == ADMIN_EMAIL


def execute_command(session: Session, cmd: dict, user) -> dict:
    """Execute a self-modification command. Returns result dict.

    cmd format: {"tool": "...", "params": {...}}
    Supported tools:
      - set_param        : {"key": "buy_score_threshold", "value": 5}
      - get_params        : {}
      - set_agent_mode    : {"mode": "normal"}
      - get_learning_stats: {}
      - get_signal_ranking: {}
      - reset_signal_stats: {}
      - get_adaptive_state: {}
    """
    if not is_admin(user):
        return {"ok": False, "error": "Brak uprawnień do modyfikacji agenta."}

    tool = cmd.get("tool", "")
    params = cmd.get("params", {})

    try:
        if tool == "set_param":
            return _set_param(session, params)
        elif tool == "get_params":
            return _get_params(session)
        elif tool == "set_agent_mode":
            return _set_agent_mode(session, params)
        elif tool == "get_learning_stats":
            return _get_learning_stats(session)
        elif tool == "get_signal_ranking":
            return _get_signal_ranking(session)
        elif tool == "reset_signal_stats":
            return _reset_signal_stats(session)
        elif tool == "get_adaptive_state":
            return _get_adaptive_state(session)
        else:
            return {"ok": False, "error": f"Nieznane narzędzie: {tool}"}
    except Exception as exc:
        logger.exception("Self-modify error: tool=%s", tool)
        return {"ok": False, "error": str(exc)}


# ── Parameter override via RuntimeSetting ──

def _set_param(session: Session, params: dict) -> dict:
    key = params.get("key", "")
    value = params.get("value")
    if key not in ALLOWED_OVERRIDES:
        return {"ok": False, "error": f"Parametr '{key}' nie jest modyfikowalny. Dozwolone: {list(ALLOWED_OVERRIDES.keys())}"}

    min_val, max_val, cast = ALLOWED_OVERRIDES[key]
    try:
        value = cast(value)
    except (TypeError, ValueError):
        return {"ok": False, "error": f"Nieprawidłowa wartość dla {key}: {value}"}

    if not (min_val <= value <= max_val):
        return {"ok": False, "error": f"{key} musi być w zakresie [{min_val}, {max_val}], podano: {value}"}

    override_key = f"override_{key}"
    row = session.execute(
        select(RuntimeSetting).where(RuntimeSetting.key == override_key)
    ).scalar_one_or_none()

    if row is None:
        session.add(RuntimeSetting(key=override_key, value=str(value)))
    else:
        row.value = str(value)
    session.commit()

    logger.info("SELF-MODIFY: %s = %s (by admin)", key, value)
    return {"ok": True, "message": f"Ustawiono {key} = {value}", "key": key, "value": value}


def _get_params(session: Session) -> dict:
    runtime = RuntimeStateService()
    profile = runtime.get_active_profile(session)

    # Show any manual overrides on top
    overrides = {}
    for key in ALLOWED_OVERRIDES:
        override_key = f"override_{key}"
        row = session.execute(
            select(RuntimeSetting).where(RuntimeSetting.key == override_key)
        ).scalar_one_or_none()
        if row:
            overrides[key] = row.value

    return {
        "ok": True,
        "active_profile": profile,
        "manual_overrides": overrides,
    }


def _set_agent_mode(session: Session, params: dict) -> dict:
    mode = params.get("mode", "").strip().lower()
    runtime = RuntimeStateService()
    try:
        result = runtime.set_agent_mode(session, mode)
        return {"ok": True, "message": f"Tryb agenta zmieniony na: {result}"}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


# ── Learning stats ──

def _get_learning_stats(session: Session) -> dict:
    learning = LearningService()
    summary = learning.get_performance_summary(session)
    return {"ok": True, **summary}


def _get_signal_ranking(session: Session) -> dict:
    learning = LearningService()
    rankings = learning.get_signal_rankings(session)
    return {"ok": True, "signals": rankings, "count": len(rankings)}


def _reset_signal_stats(session: Session) -> dict:
    deleted = session.execute(select(SignalPerformance)).scalars().all()
    count = len(deleted)
    for row in deleted:
        session.delete(row)
    session.commit()
    logger.info("SELF-MODIFY: reset %d signal stats (by admin)", count)
    return {"ok": True, "message": f"Zresetowano statystyki {count} sygnałów."}


def _get_adaptive_state(session: Session) -> dict:
    learning = LearningService()
    adjustments = learning.get_adaptive_adjustments(session)
    runtime = RuntimeStateService()
    profile = runtime.get_active_profile(session)
    return {
        "ok": True,
        "adaptive_active": adjustments is not None,
        "adjustments": adjustments,
        "current_profile": {
            "id": profile.get("id"),
            "buy_score_threshold": profile.get("buy_score_threshold"),
            "profit_target": profile.get("profit_target"),
            "stop_loss": profile.get("stop_loss"),
            "_adaptive": profile.get("_adaptive", False),
            "_win_rate": profile.get("_win_rate", 0),
            "_sample_count": profile.get("_sample_count", 0),
        },
    }


def apply_overrides_to_profile(session: Session, profile: dict) -> dict:
    """Apply any manual admin overrides stored in RuntimeSetting to the profile."""
    for key, (min_val, max_val, cast) in ALLOWED_OVERRIDES.items():
        override_key = f"override_{key}"
        row = session.execute(
            select(RuntimeSetting).where(RuntimeSetting.key == override_key)
        ).scalar_one_or_none()
        if row is not None:
            try:
                val = cast(row.value)
                if min_val <= val <= max_val:
                    profile[key] = val
            except (TypeError, ValueError):
                pass
    return profile
