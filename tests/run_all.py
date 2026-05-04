"""Run all backend tests in a single process.

Usage:
    .venv\\Scripts\\python.exe tests\\run_all.py

Or via PowerShell helper:
    scripts\\run_agent_krypto_tests.ps1
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "agent_krypto.settings")
os.environ.setdefault("API_KEY_ENCRYPTION_KEY", "0" * 43 + "=")

try:
    import django
    django.setup()
except Exception as e:
    print(f"Warning: Django setup failed: {e}", file=sys.stderr)


def main() -> int:
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(PROJECT_ROOT / "tests"), pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
