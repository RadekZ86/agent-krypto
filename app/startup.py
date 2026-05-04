from __future__ import annotations

import logging
import os
import threading
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_startup_done = False
_scheduler_lock_handle = None  # keep file descriptor alive for process lifetime


def _acquire_scheduler_lock() -> bool:
    """Acquire an exclusive file lock so only ONE Passenger worker runs the scheduler.

    Returns True if this process owns the lock, False otherwise. The lock is
    released automatically when the process exits.
    """
    global _scheduler_lock_handle
    try:
        from app.config import BASE_DIR
        lock_dir = Path(BASE_DIR) / "logs"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / "scheduler.lock"
        # Open file (created if missing); use OS-level non-blocking exclusive lock.
        fh = open(lock_path, "a+")
        try:
            import fcntl  # POSIX (FreeBSD/Linux on prod)
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            # Windows fallback: msvcrt.locking
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        # Write our PID so admins can see who owns the lock
        try:
            fh.seek(0)
            fh.truncate()
            fh.write(f"{os.getpid()}\n")
            fh.flush()
        except Exception:
            pass
        _scheduler_lock_handle = fh  # keep open for the process lifetime
        return True
    except Exception as exc:
        # Either lock taken by sibling worker or filesystem error — both mean: do not start scheduler here.
        logger.info("Scheduler lock not acquired by pid=%s: %s", os.getpid(), exc)
        return False


def on_startup():
    """Called once when Django app is ready (from AppConfig.ready).
    
    Skips DB operations during management commands like check/makemigrations/migrate.
    """
    global _startup_done
    if _startup_done:
        return
    _startup_done = True

    # Skip DB operations during management commands that don't need them
    _skip_commands = {'check', 'makemigrations', 'migrate', 'collectstatic', 'showmigrations', 'inspectdb'}
    if len(sys.argv) > 1 and sys.argv[1] in _skip_commands:
        return

    # Delay actual startup to a background thread so Django can finish loading
    def _deferred_startup():
        import time
        time.sleep(1)

        from app.services.auth import APIKeyService

        # Migrate XOR-encrypted API keys to Fernet
        try:
            api_key_service = APIKeyService()
            migrated = api_key_service.re_encrypt_from_xor()
            if migrated:
                logger.info("Security: migrated %d API keys to Fernet encryption", migrated)
        except Exception as exc:
            logger.error("API key migration failed: %s", exc)

        # Run initial cycle if no data — only the lock-owner does this to avoid 4× duplication
        scheduler_owner = _acquire_scheduler_lock()

        try:
            from app.models import MarketData, Decision
            if scheduler_owner and (not MarketData.objects.exists() or not Decision.objects.exists()):
                from app.services.agent_cycle import AgentCycle
                AgentCycle().run()
        except Exception as exc:
            logger.error("Initial cycle failed: %s", exc)

        # Start scheduler ONLY in the worker that owns the lock
        try:
            from app.config import settings
            from app import views
            if settings.scheduler_enabled and scheduler_owner:
                logger.info("Scheduler starting in pid=%s (lock owner)", os.getpid())
                views.scheduler_service.start()
            elif settings.scheduler_enabled:
                logger.info("Scheduler skipped in pid=%s (sibling worker owns the lock)", os.getpid())
        except Exception as exc:
            logger.error("Scheduler start failed: %s", exc)

        # Prewarm caches
        try:
            from app.services.bybit_market import _fetch_all_linear_tickers
            _fetch_all_linear_tickers()
        except Exception:
            pass
        try:
            from app.views import _build_dashboard_payload
            _build_dashboard_payload()
        except Exception:
            pass

    threading.Thread(target=_deferred_startup, daemon=True, name="app-startup").start()
