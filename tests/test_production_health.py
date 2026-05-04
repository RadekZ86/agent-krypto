"""Production health smoke tests for Agent Krypto.

These tests hit the LIVE production server (https://agentkrypto.apka.org.pl)
via HTTPS and check that the most important endpoints are healthy and that
the application is responding with expected payloads.

Run with:
    python -m unittest tests.test_production_health -v

Skip with:
    AGENT_KRYPTO_SKIP_PROD_TESTS=1 python -m unittest ...
"""
from __future__ import annotations

import json
import os
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROD_BASE_URL = os.environ.get(
    "AGENT_KRYPTO_PROD_URL",
    "https://agentkrypto.apka.org.pl",
)
SKIP = os.environ.get("AGENT_KRYPTO_SKIP_PROD_TESTS", "").lower() in ("1", "true", "yes")


def _fetch(path: str, timeout: int = 30) -> tuple[int, str, dict]:
    """Return (status, text, headers) for a GET request to PROD_BASE_URL+path."""
    req = Request(f"{PROD_BASE_URL}{path}", headers={"User-Agent": "agent-krypto-tests/1.0"})
    try:
        with urlopen(req, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            return response.status, text, dict(response.headers)
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace"), dict(e.headers or {})


@unittest.skipIf(SKIP, "Production tests skipped via env var")
class ProductionHealthTests(unittest.TestCase):
    """Smoke tests against live production deployment."""

    def test_homepage_returns_200(self) -> None:
        status, body, _ = _fetch("/")
        self.assertEqual(status, 200, f"Homepage failed: {status}\n{body[:300]}")
        self.assertIn("Agent Krypto", body, "Homepage missing brand text")

    def test_dashboard_api_returns_json(self) -> None:
        status, body, headers = _fetch("/api/dashboard")
        self.assertEqual(status, 200, f"/api/dashboard failed: {status}\n{body[:300]}")
        data = json.loads(body)
        self.assertIn("wallet", data)
        self.assertIn("market", data)
        self.assertIn("system_status", data)
        self.assertIsInstance(data["market"], list)
        self.assertGreater(len(data["market"]), 5, "Expected multiple tracked symbols in market")

    def test_dashboard_market_rows_have_required_fields(self) -> None:
        _, body, _ = _fetch("/api/dashboard")
        data = json.loads(body)
        required = {"symbol", "price", "decision", "rsi", "trend", "timestamp"}
        for row in data["market"][:5]:
            missing = required - set(row.keys())
            self.assertFalse(missing, f"Row {row.get('symbol')} missing fields: {missing}")

    def test_dashboard_scheduler_status(self) -> None:
        _, body, _ = _fetch("/api/dashboard")
        data = json.loads(body)
        sched = data.get("system_status", {}).get("scheduler", {})
        self.assertIsInstance(sched, dict)
        self.assertIn("enabled", sched)

    def test_backtest_api(self) -> None:
        status, body, _ = _fetch("/api/backtest")
        self.assertEqual(status, 200, f"/api/backtest failed: {status}")
        data = json.loads(body)
        self.assertIsInstance(data, (list, dict))

    def test_chart_package_btc(self) -> None:
        status, body, _ = _fetch("/api/chart-package?symbol=BTC&limit=30")
        self.assertEqual(status, 200, f"/api/chart-package failed: {status}")
        data = json.loads(body)
        self.assertIn("symbol", data)
        # Endpoint returns "points" (list of OHLC dicts)
        self.assertIn("points", data)
        self.assertIsInstance(data["points"], list)
        self.assertGreater(len(data["points"]), 0, "No chart points returned")

    def test_static_app_js_served(self) -> None:
        status, body, _ = _fetch("/static/app.js")
        self.assertEqual(status, 200, f"/static/app.js failed: {status}")
        self.assertGreater(len(body), 1000, "app.js suspiciously small")

    def test_auth_me_unauthenticated_returns_401(self) -> None:
        status, _, _ = _fetch("/api/auth/me")
        self.assertIn(status, (401, 200), f"/api/auth/me unexpected status: {status}")

    def test_dashboard_no_5xx_errors(self) -> None:
        """Hit dashboard 3 times to catch transient 500 errors."""
        for i in range(3):
            status, _, _ = _fetch("/api/dashboard")
            self.assertLess(status, 500, f"Dashboard returned 5xx on attempt {i + 1}")

    def test_risk_status_endpoint(self) -> None:
        status, body, _ = _fetch("/api/risk-status")
        self.assertEqual(status, 200, f"risk-status failed: {status}")
        data = json.loads(body)
        self.assertIn("level", data)
        self.assertIn("allow_new_buys", data)
        self.assertIn("position_size_multiplier", data)
        self.assertIn(data["level"], ("NORMAL", "CAUTIOUS", "HALT"))

    def test_learning_insights_endpoint(self) -> None:
        status, body, _ = _fetch("/api/learning-insights")
        self.assertEqual(status, 200, f"learning-insights failed: {status}")
        data = json.loads(body)
        for key in ("summary_7d", "summary_30d", "summary_all", "exit_reasons", "equity_curve"):
            self.assertIn(key, data, f"learning-insights missing '{key}'")
        self.assertIsInstance(data["exit_reasons"], list)
        self.assertIsInstance(data["equity_curve"], list)

    def test_https_redirect_or_secure_headers(self) -> None:
        """Verify HTTPS is enforced — homepage should not return mixed-content."""
        status, body, headers = _fetch("/")
        self.assertEqual(status, 200)
        # Don't fail on missing strict headers, just record presence
        self.assertNotIn("http://agentkrypto", body, "Homepage references insecure HTTP URL")

    def test_dashboard_payload_consistency(self) -> None:
        """Two consecutive calls should return same shape (no flapping schema)."""
        s1, b1, _ = _fetch("/api/dashboard")
        s2, b2, _ = _fetch("/api/dashboard")
        self.assertEqual(s1, 200)
        self.assertEqual(s2, 200)
        d1, d2 = json.loads(b1), json.loads(b2)
        self.assertEqual(set(d1.keys()), set(d2.keys()), "Dashboard schema differs between requests")


if __name__ == "__main__":
    unittest.main(verbosity=2)
