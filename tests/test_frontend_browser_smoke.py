from __future__ import annotations

import os
import unittest

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


BASE_URL = os.environ.get("AGENT_KRYPTO_TEST_BASE_URL", "http://127.0.0.1:8000")


class FrontendBrowserSmokeTests(unittest.TestCase):
    def test_dashboard_renders_live_values_in_browser(self) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1200})
            try:
                page.goto(BASE_URL, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_function(
                    """
                    () => {
                        const cash = document.getElementById("cash-balance")?.textContent?.trim();
                        const equity = document.getElementById("equity")?.textContent?.trim();
                        const marketRows = document.querySelectorAll("#market-table tr").length;
                        const chartButtons = document.querySelectorAll("#chart-switcher button").length;
                        return cash && cash !== "-" && equity && equity !== "-" && marketRows > 0 && chartButtons > 0;
                    }
                    """,
                    timeout=90000,
                )
            except PlaywrightTimeoutError as exc:
                screenshot_path = os.path.join(os.getcwd(), "logs", "frontend_smoke_failure.png")
                page.screenshot(path=screenshot_path, full_page=True)
                raise AssertionError(
                    f"Frontend nie wyrenderowal danych w przegladarce. Screenshot: {screenshot_path}"
                ) from exc

            cash_balance = page.locator("#cash-balance").inner_text().strip()
            equity = page.locator("#equity").inner_text().strip()
            market_rows = page.locator("#market-table tr").count()
            chart_buttons = page.locator("#chart-switcher button").count()
            status_text = page.locator("#status-line").inner_text().strip()

            self.assertNotEqual(cash_balance, "-")
            self.assertNotEqual(equity, "-")
            self.assertGreater(market_rows, 0)
            self.assertGreater(chart_buttons, 0)
            self.assertIn("Ostatnie odswiezenie", status_text)

            browser.close()


if __name__ == "__main__":
    unittest.main()