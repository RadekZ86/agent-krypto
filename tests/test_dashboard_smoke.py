from __future__ import annotations

import json
import os
import re
import unittest
from pathlib import Path
from urllib.request import urlopen


BASE_URL = os.environ.get("AGENT_KRYPTO_TEST_BASE_URL", "http://127.0.0.1:8000")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_JS_PATH = PROJECT_ROOT / "app" / "static" / "app.js"
INDEX_TEMPLATE_PATH = PROJECT_ROOT / "app" / "templates" / "index.html"


def fetch_json(path: str) -> dict:
    with urlopen(f"{BASE_URL}{path}", timeout=60) as response:
        return json.load(response)


def fetch_text(path: str) -> str:
    with urlopen(f"{BASE_URL}{path}", timeout=60) as response:
        return response.read().decode("utf-8")


class DashboardSmokeTests(unittest.TestCase):
    DYNAMIC_IDS = {
        "cycle-running-counter",
        "last-cycle-counter",
        "next-cycle-counter",
        "live-quote-age-counter",
        "last-decision-counter",
    }

    def test_dashboard_api_returns_wallet_market_and_config(self) -> None:
        payload = fetch_json("/api/dashboard")

        self.assertIn("wallet", payload)
        self.assertIn("market", payload)
        self.assertIn("config", payload)
        self.assertGreater(len(payload["market"]), 0)
        self.assertIn("cash_balance", payload["wallet"])
        self.assertIn("chart_focus_symbol", payload)
        self.assertIn("scheduler", payload["system_status"])
        self.assertIn("is_running", payload["system_status"]["scheduler"])
        self.assertIn("decision_timestamp", payload["market"][0])

    def test_chart_package_endpoint_returns_points(self) -> None:
        payload = fetch_json("/api/chart-package?symbol=BTC")

        self.assertEqual(payload["symbol"], "BTC")
        self.assertGreater(len(payload.get("points", [])), 0)
        self.assertIn("summary", payload)

    def test_chart_history_endpoint_returns_full_history_payload(self) -> None:
        payload = fetch_json("/api/chart-history?symbol=BTC")

        self.assertEqual(payload["symbol"], "BTC")
        self.assertGreater(len(payload.get("points", [])), 365)
        self.assertIn("summary", payload)
        self.assertIn("history_source", payload["summary"])
        self.assertIn("points_count", payload["summary"])

    def test_index_html_uses_versioned_static_assets(self) -> None:
        html = fetch_text("/")

        self.assertIn("/static/app.js?v=", html)
        self.assertIn("/static/styles.css?v=", html)

    def test_index_response_disables_html_cache(self) -> None:
        with urlopen(f"{BASE_URL}/", timeout=60) as response:
            cache_control = response.headers.get("Cache-Control", "")

        self.assertIn("no-store", cache_control)

    def test_dom_ids_referenced_in_app_js_exist_in_index_template(self) -> None:
        app_js = APP_JS_PATH.read_text(encoding="utf-8")
        html = INDEX_TEMPLATE_PATH.read_text(encoding="utf-8")

        referenced_ids = set(re.findall(r'getElementById\("([^"]+)"\)', app_js))
        missing_ids = sorted(
            identifier
            for identifier in referenced_ids
            if identifier not in self.DYNAMIC_IDS and f'id="{identifier}"' not in html
        )

        self.assertEqual(missing_ids, [], f"Brakujace id w index.html: {missing_ids}")


if __name__ == "__main__":
    unittest.main()