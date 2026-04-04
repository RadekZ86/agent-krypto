from __future__ import annotations

from time import sleep

from sqlalchemy.exc import OperationalError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import RuntimeSetting


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
        mode = self.get_agent_mode(session)
        profile = settings.agent_mode_profiles.get(mode, settings.agent_mode_profiles[settings.default_agent_mode]).copy()
        profile["id"] = mode
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