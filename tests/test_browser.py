import os
from io import StringIO
from unittest import skipUnless

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.test import override_settings
from playwright.sync_api import Page, expect, sync_playwright

from accounts.models import User


@skipUnless(os.getenv("RUN_BROWSER_TESTS") == "1", "Enable with RUN_BROWSER_TESTS=1 and install Chromium")
class BrowserTests(StaticLiveServerTestCase):
    password = "Only used inside the browser test database"

    @override_settings(DEBUG=True)
    def seed(self) -> None:
        call_command("seed_demo", stdout=StringIO())

    def navigate(self, page: Page, path: str) -> None:
        response = page.goto(self.live_server_url + path)
        assert response is not None
        self.assertTrue(response.ok)
        self.assertTrue(page.evaluate("document.documentElement.scrollWidth === window.innerWidth"), path)
        axe = os.getenv("AXE_SCRIPT")
        if axe:
            page.add_script_tag(path=axe)
            failures = page.evaluate("""async () => {
                const results = await axe.run({
                    runOnly: {type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]}
                });
                return results.violations.map(v => [v.id, v.nodes.map(n => n.target)]);
            }""")
            self.assertFalse(failures, f"{path}: {failures}")

    def sign_in(self, page: Page, email: str) -> None:
        page.goto(self.live_server_url + "/account/login/")
        page.get_by_label("Email").fill(email)
        page.get_by_label("Password").fill(self.password)
        page.get_by_role("button", name="Sign in").click()
        expect(page.get_by_role("heading", name="Your account")).to_be_visible()

    def test_responsive_layout_and_keyboard(self):
        self.seed()
        staff = User.objects.create_superuser("staff-browser@example.test", self.password)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            for width in (375, 1440):
                page = browser.new_page(viewport={"width": width, "height": 900}, bypass_csp=bool(os.getenv("AXE_SCRIPT")))
                page.set_default_timeout(5000)
                failures: list[str] = []
                page.on("pageerror", lambda error: failures.append(str(error)))
                self.navigate(page, "/")
                page.keyboard.press("Tab")
                expect(page.get_by_role("link", name="Skip to content")).to_be_focused()
                page.keyboard.press("Enter")
                expect(page.locator("main")).to_be_focused()
                self.navigate(page, "/products/")
                self.navigate(page, "/products/demo-storage-basket-natural/")
                page.get_by_role("button", name="Add to cart").click()
                self.navigate(page, "/cart/")
                self.navigate(page, "/checkout/")
                self.navigate(page, "/account/login/")
                self.sign_in(page, staff.email)
                self.navigate(page, "/account/")
                self.navigate(page, "/staff/")
                self.navigate(page, "/staff/orders/")
                self.assertFalse(failures)
                page.close()
