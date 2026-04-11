from __future__ import annotations

import logging
from time import sleep

from sqlalchemy.exc import OperationalError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import RuntimeSetting

logger = logging.getLogger(__name__)


class RuntimeStateService:
    def get_agent_mode(self, session: Session) -> str:
        mode = self._get_value(session, "agent_mode", settings.default_agent_mode)
        return mode if mode in settings.agent_mode_profiles else settings.default_agent_mode

    def set_agent_mode(self, session: Session, mode: str) -> str:
        normalized = mode.strip().lower()
        if normalized not in settings.agent_mode_profiles:
            raise ValueError(f"Nieznany tryb agenta: {mode}")
        self._set_value(session, "agent_mode", normalized)
        return normalized

    def get_display_currency(self, session: Session) -> str:
        currency = self._get_value(session, "display_currency", settings.display_currency).upper()
        return currency or settings.display_currency

    def get_active_profile(self, session: Session) -> dict[str, object]:
        """Return the agent profile with adaptive adjustments applied on top."""
        mode = self.get_agent_mode(session)
        profile = settings.agent_mode_profiles.get(mode, settings.agent_mode_profiles[settings.default_agent_mode]).copy()
        profile["id"] = mode

        # Apply adaptive feedback from learning data
        try:
            from app.services.learning import LearningService
            learning = LearningService()
            adjustments = learning.get_adaptive_adjustments(session)
            if adjustments is not None:
                # Adjust buy_score_threshold (clamp to 2..8)
                delta = adjustments.get("buy_score_threshold_delta", 0)
                if delta:
                    base_threshold = int(profile["buy_score_threshold"])
                    profile["buy_score_threshold"] = max(2, min(8, base_threshold + int(delta)))

                # Adjust profit_target (clamp to 1%..8%)
                suggested_pt = adjustments.get("suggested_profit_target")
                if suggested_pt and 0.01 <= suggested_pt <= 0.08:
                    base_pt = float(profile["profit_target"])
                    # Blend: 70% base + 30% suggested (gradual adaptation)
                    profile["profit_target"] = round(base_pt * 0.7 + suggested_pt * 0.3, 4)

                # Adjust stop_loss (clamp to 1.5%..10%)
                suggested_sl = adjustments.get("suggested_stop_loss")
                if suggested_sl and 0.015 <= suggested_sl <= 0.10:
                    base_sl = float(profile["stop_loss"])
                    profile["stop_loss"] = round(base_sl * 0.7 + suggested_sl * 0.3, 4)

                profile["_adaptive"] = True
                profile["_win_rate"] = adjustments.get("win_rate", 0)
                profile["_sample_count"] = adjustments.get("sample_count", 0)
                logger.debug(
                    "Adaptive profile: threshold=%s pt=%.3f sl=%.3f win_rate=%.1f%% samples=%d",
                    profile["buy_score_threshold"],
                    float(profile["profit_target"]),
                    float(profile["stop_loss"]),
                    adjustments.get("win_rate", 0) * 100,
                    adjustments.get("sample_count", 0),
                )
        except Exception:
            logger.debug("Adaptive feedback unavailable, using static profile")

        return profile

    def _get_value(self, session: Session, key: str, default: str) -> str:
        row = session.execute(select(RuntimeSetting).where(RuntimeSetting.key == key)).scalar_one_or_none()
        return row.value if row is not None else default

    def _set_value(self, session: Session, key: str, value: str) -> None:
        row = session.execute(select(RuntimeSetting).where(RuntimeSetting.key == key)).scalar_one_or_none()
        if row is None:
            row = RuntimeSetting(key=key, value=value)
            session.add(row)
        else:
            row.value = value
        for attempt in range(3):
            try:
                session.commit()
                return
            except OperationalError:
                session.rollback()
                if attempt == 2:
                    raise
                sleep(0.4 * (attempt + 1))
                row = session.execute(select(RuntimeSetting).where(RuntimeSetting.key == key)).scalar_one_or_none()
                if row is None:
                    row = RuntimeSetting(key=key, value=value)
                    session.add(row)
                else:
                    row.value = value