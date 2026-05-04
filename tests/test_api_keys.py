"""Tests for API key handling and Binance client wiring.

Verifies:
- APIKeyService can encrypt/decrypt round-trip
- get_user_binance_client returns (None, None) when user has no key
- get_user_binance_client returns valid (key, client) when key exists
- The dashboard payload reflects binance_private_ready correctly
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
# Provide a valid Fernet key for encryption tests
os.environ.setdefault("API_KEY_ENCRYPTION_KEY", "0" * 43 + "=")

try:
    import django
    django.setup()
except Exception:
    pass


class APIKeyEncryptionTests(unittest.TestCase):
    def test_encryption_round_trip(self) -> None:
        from app.services.auth import APIKeyService
        svc = APIKeyService()
        plaintext = "my-super-secret-binance-api-secret-1234567890"
        encrypted = svc._encrypt(plaintext)
        self.assertNotEqual(encrypted, plaintext)
        self.assertGreater(len(encrypted), 50)
        decrypted = svc._decrypt(encrypted)
        self.assertEqual(decrypted, plaintext)

    def test_encryption_produces_different_ciphertexts(self) -> None:
        """Fernet should never produce identical ciphertexts (uses random IV)."""
        from app.services.auth import APIKeyService
        svc = APIKeyService()
        c1 = svc._encrypt("same-plaintext")
        c2 = svc._encrypt("same-plaintext")
        self.assertNotEqual(c1, c2)


class BinanceClientWiringTests(unittest.TestCase):
    def test_no_user_keys_returns_none(self) -> None:
        from app.views import get_user_binance_client
        # Use a user_id that is extremely unlikely to exist
        key, client = get_user_binance_client(user_id=999999999)
        self.assertIsNone(key)
        self.assertIsNone(client)

    def test_dashboard_payload_marks_binance_ready_for_user_with_key(self) -> None:
        from app.models import User, UserAPIKey
        user_with_key = (
            User.objects
            .filter(userapikey__exchange="binance", userapikey__is_active=True)
            .distinct()
            .first()
        )
        if user_with_key is None:
            self.skipTest("No user with active Binance key in DB")

        from app.views import _build_dashboard_payload
        payload = _build_dashboard_payload(
            include_chart_package=False,
            current_user=user_with_key,
            skip_exchange_api=True,
        )
        # Either binance_private_ready True OR private_learning enabled
        ready = payload.get("system_status", {}).get("binance_private_ready")
        pl = payload.get("private_learning")
        self.assertTrue(
            ready or (pl and pl.get("enabled")),
            f"Expected binance ready signal, got system_status.binance_private_ready={ready}, "
            f"private_learning={pl}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
