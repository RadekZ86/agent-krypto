from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import Event, Thread
from typing import Any, Callable

from app.config import BASE_DIR


class SchedulerService:
    def __init__(self, interval_seconds: int, run_callback: Callable[[], dict[str, Any]]) -> None:
        self.interval_seconds = interval_seconds
        self.run_callback = run_callback
        self.enabled = False
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._watchdog_thread: Thread | None = None
        self.last_run_started_at: str | None = None
        self.last_run_completed_at: str | None = None
        self.last_run_successful: bool | None = None
        self.last_error: str | None = None
        self.is_running = False
        self.current_run_started_at: str | None = None
        self.total_runs = 0
        self.history_log_path = BASE_DIR / "logs" / "scheduler_history.log"

    def start(self) -> None:
        self.enabled = True
        self._stop_event.clear()
        self._start_watchdog_thread()
        if self._thread is not None and self._thread.is_alive():
            return
        self._write_history("scheduler_start_requested", interval_seconds=self.interval_seconds)
        self._start_thread()

    def stop(self) -> None:
        self.enabled = False
        self._stop_event.set()
        self.is_running = False
        self.current_run_started_at = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=2)
        self._write_history("scheduler_stopped", total_runs=self.total_runs)

    def ensure_running(self) -> bool:
        if not self.enabled:
            return False
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop_event.clear()
        self.last_error = "Scheduler worker zostal automatycznie wznowiony po zatrzymaniu."
        self._write_history("scheduler_recovered_from_dashboard", last_error=self.last_error, total_runs=self.total_runs)
        self._start_thread()
        return True

    def run_once(self) -> None:
        self.last_run_started_at = datetime.utcnow().isoformat()
        self.current_run_started_at = self.last_run_started_at
        self.is_running = True
        self._write_history("cycle_started", started_at=self.last_run_started_at, total_runs=self.total_runs)
        try:
            result = self.run_callback()
        except Exception as exc:
            self.last_run_successful = False
            self.last_error = str(exc)
            self._write_history("cycle_failed", started_at=self.last_run_started_at, error=self.last_error, total_runs=self.total_runs)
        else:
            self.last_run_successful = True
            self.last_error = None
            self.total_runs += 1
            self._write_history(
                "cycle_completed",
                started_at=self.last_run_started_at,
                completed_at=datetime.utcnow().isoformat(),
                total_runs=self.total_runs,
                processed=int(result.get("processed", 0)) if isinstance(result, dict) else None,
            )
        finally:
            self.last_run_completed_at = datetime.utcnow().isoformat()
            self.is_running = False
            self.current_run_started_at = None

    def status(self) -> dict[str, Any]:
        thread_alive = self._thread is not None and self._thread.is_alive()
        watchdog_alive = self._watchdog_thread is not None and self._watchdog_thread.is_alive()
        active = self.enabled and thread_alive
        return {
            "enabled": self.enabled,
            "active": active,
            "thread_alive": thread_alive,
            "watchdog_alive": watchdog_alive,
            "health": "active" if active else "stale" if self.enabled else "stopped",
            "interval_seconds": self.interval_seconds,
            "is_running": self.is_running,
            "current_run_started_at": self.current_run_started_at,
            "last_run_started_at": self.last_run_started_at,
            "last_run_completed_at": self.last_run_completed_at,
            "last_run_successful": self.last_run_successful,
            "last_error": self.last_error,
            "total_runs": self.total_runs,
            "history_log_path": str(self.history_log_path),
        }

    def _start_thread(self) -> None:
        self._thread = Thread(target=self._loop, daemon=True, name="agent-krypto-scheduler")
        self._thread.start()

    def _start_watchdog_thread(self) -> None:
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            return
        self._watchdog_thread = Thread(target=self._watchdog_loop, daemon=True, name="agent-krypto-scheduler-watchdog")
        self._watchdog_thread.start()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            if self.enabled:
                self.run_once()
            if self._stop_event.wait(self.interval_seconds):
                break

    def _watchdog_loop(self) -> None:
        while not self._stop_event.wait(15):
            if self.enabled and (self._thread is None or not self._thread.is_alive()):
                self.last_error = "Watchdog wznowil scheduler po zatrzymaniu worker thread."
                self._write_history("scheduler_recovered_by_watchdog", last_error=self.last_error, total_runs=self.total_runs)
                self._start_thread()

    def _write_history(self, event: str, **payload: Any) -> None:
        self.history_log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "event": event,
            **payload,
        }
        with self.history_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True) + "\n")