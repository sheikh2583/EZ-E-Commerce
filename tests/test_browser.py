import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO, StringIO
from tempfile import TemporaryDirectory
from unittest import skipUnless
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.db import connections
from django.test import override_settings
from PIL import Image
from playwright.sync_api import Page, Route, expect, sync_playwright

from accounts.models import User
from shop.guest_access import make_token
from shop.models import (
    DeliveryZone,
    Notification,
    Order,
    PaymentAttempt,
    Product,
    ProductImage,
)


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
            browser = playwright.chromium.launch(args=["--host-resolver-rules=MAP sandbox.sslcommerz.com ~NOTFOUND"])
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

    def database[T](self, query: Callable[[], T]) -> T:
        def run() -> T:
            try:
                return query()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as worker:
            return worker.submit(run).result(timeout=5)

    def register(self, page: Page) -> None:
        page.goto(self.live_server_url + "/account/register/")
        page.get_by_label("Email").fill("registered-browser@example.test")
        page.get_by_label("First name").fill("Alex")
        page.locator("#id_password1").fill(self.password)
        page.locator("#id_password2").fill(self.password)
        page.get_by_role("button", name="Create account").click()
        expect(page.get_by_role("heading", name="Your account")).to_be_visible()

    def place_order(self, page: Page, *, guest: bool) -> Order:
        page.goto(self.live_server_url)
        page.get_by_label("Search products").fill("basket")
        page.get_by_role("button", name="Search").click()
        page.get_by_role("link", name="Home Storage basket · Natural", exact=False).click()
        page.get_by_role("button", name="Add to cart").click()
        page.get_by_role("link", name="Browse", exact=True).click()
        page.get_by_label("Search", exact=False).first.fill("Ceramic vase")
        page.get_by_role("button", name="Apply filters").click()
        page.get_by_role("link", name="Home Ceramic vase · Natural", exact=False).click()
        page.get_by_role("button", name="Add to cart").click()
        expect(page.get_by_role("link", name="Cart 2")).to_be_visible()
        page.reload()
        page.get_by_label("Quantity for Storage basket").fill("2")
        page.locator(".cart-item").filter(has_text="Storage basket").get_by_role("button", name="Update").click()
        expect(page.get_by_role("link", name="Cart 3")).to_be_visible()
        page.get_by_role("link", name="Go to checkout").click()
        page.get_by_label("Full name").fill("Browser Shopper")
        if guest:
            page.get_by_label("Email").fill("guest-browser@example.test")
        page.get_by_label("Phone").fill("01700000000")
        page.get_by_label("Street address").fill("8 Example Road")
        page.get_by_label("City or locality").fill("Dhaka")
        page.get_by_label("Delivery zone").select_option(label="Inside Dhaka (৳80)")
        page.get_by_role("button", name="Review order").click()
        expect(page.get_by_text("Delivery · Inside Dhaka")).to_be_visible()
        expect(page.locator(".total")).to_contain_text("৳2,655.50")
        page.get_by_role("button", name="Place order").click()
        expect(page.get_by_role("heading", name="Your order")).to_be_visible()
        expect(page.get_by_text("Unpaid", exact=True)).to_be_visible()
        order = self.database(lambda: Order.objects.select_related("user").get())
        self.assertEqual((order.delivery, order.total, self.database(order.items.count)), (8000, 265550, 2))
        return order

    def pay_with_provider_fixture(self, page: Page, order: Order) -> None:
        gateway_host = "https://sandbox.sslcommerz.com"
        calls: list[str] = []

        def gateway_response(request):
            path = urlsplit(request.full_url).path
            calls.append(path)
            if path.endswith("/api.php"):
                fields = parse_qs(request.data.decode())
                self.assertEqual(fields["total_amount"], ["2655.50"])
                self.assertEqual(fields["currency"], ["BDT"])
                return {"status": "SUCCESS", "sessionkey": "browser-fixture", "GatewayPageURL": gateway_host + "/fixture"}
            validation = parse_qs(urlsplit(request.full_url).query)["val_id"][0]
            attempt = PaymentAttempt.objects.get(order=order)
            return {
                "status": "VALID", "tran_id": attempt.merchant_reference, "val_id": validation,
                "amount": "2655.50", "currency": "BDT", "currency_type": "BDT",
                "bank_tran_id": "fixture-bank-reference", "risk_level": "0",
            }

        def fixture_page(route: Route) -> None:
            if route.request.url.endswith("/fixture"):
                route.fulfill(status=200, content_type="text/html", body=(
                    '<html lang="en"><head><title>Provider fixture</title></head>'
                    '<body><h1>SSLCOMMERZ provider fixture</h1>'
                    '<a href="/fixture-complete">Complete test payment</a></body></html>'
                ))
                return
            attempt = self.database(lambda: PaymentAttempt.objects.get(order=order))
            response = page.request.post(
                self.live_server_url + "/payments/return/",
                form={"tran_id": attempt.merchant_reference, "val_id": "browser-validated"},
                max_redirects=0,
            )
            self.assertEqual(response.status, 303)
            route.fulfill(status=303, headers={"Location": self.live_server_url + response.headers["location"]})

        payment_start = self.live_server_url + f"/orders/{order.reference}/pay/"

        def handoff(route: Route) -> None:
            response = route.fetch(max_redirects=0)
            self.assertEqual(response.status, 302)
            self.assertEqual(response.headers["location"], gateway_host + "/fixture")
            route.fulfill(status=200, content_type="text/html", body=(
                '<html lang="en"><head><title>Test handoff</title></head>'
                f'<body><a href="{gateway_host}/fixture">Open the provider fixture</a></body></html>'
            ))

        page.route(payment_start, handoff)
        page.route(gateway_host + "/fixture*", fixture_page)
        with patch("shop.gateway.request_json", side_effect=gateway_response):
            page.get_by_role("button", name="Continue to secure payment").click()
            page.get_by_role("link", name="Open the provider fixture").click()
            expect(page.get_by_role("heading", name="SSLCOMMERZ provider fixture")).to_be_visible()
            page.get_by_role("link", name="Complete test payment").click()
            expect(page.get_by_text("Sandbox payment verified. No money was charged.")).to_be_visible()
        page.unroute(gateway_host + "/fixture*", fixture_page)
        page.unroute(payment_start, handoff)
        self.database(order.refresh_from_db)
        self.assertEqual(order.payment_state, Order.PaymentState.PAID)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.database(lambda: Notification.objects.filter(order=order, template="paid").count()), 2)

    def staff_journey(self, page: Page, order: Order) -> None:
        self.sign_in(page, "staff-journey@example.test")
        self.navigate(page, "/staff/")
        expect(page.get_by_text("Verified live revenue")).to_be_visible()
        page.get_by_role("link", name="Catalogue and settings").click()
        page.get_by_role("link", name="Products", exact=True).click()
        page.get_by_role("link", name="Add product").click()
        for field, value in (
            ("name", "Browser product"), ("sku", "BROWSER-01"), ("description", "Browser test product"),
            ("regular_price", "1099.50"), ("stock", "10"),
        ):
            page.locator(f"#id_{field}").fill(value)
        page.locator("#id_slug").fill("browser-product")
        page.locator("#id_category").select_option(label="Home")
        page.get_by_role("button", name="Save", exact=True).click()
        page.locator("#result_list").get_by_role("link", name="Browser product", exact=True).click()
        page.locator("#id_stock").fill("15")
        page.get_by_role("button", name="Save and continue editing").click()
        product = self.database(lambda: Product.objects.get(sku="BROWSER-01"))
        self.assertEqual((product.stock, product.regular_price), (15, 109950))
        page.get_by_role("link", name="Manage photos").click()
        png = BytesIO()
        Image.new("RGB", (8, 8), "blue").save(png, "PNG")
        page.locator("#id_photo").set_input_files({"name": "browser.png", "mimeType": "image/png", "buffer": png.getvalue()})
        page.get_by_label("Image description").fill("Browser product front")
        page.get_by_role("button", name="Upload photo").click()
        expect(page.get_by_text("Photo uploaded.")).to_be_visible()
        self.assertTrue(self.database(lambda: ProductImage.objects.filter(product=product).exists()))

        self.navigate(page, "/staff/catalogue/shop/deliveryzone/add/")
        page.locator("#id_name").fill("Browser zone")
        page.locator("#id_fee").fill("130.25")
        expect(page.locator("#id_code")).to_have_value("browser-zone")
        page.get_by_role("button", name="Save", exact=True).click()
        expect(page.get_by_text("was added successfully", exact=False)).to_be_visible()
        zone = self.database(lambda: DeliveryZone.objects.get(name="Browser zone"))
        self.assertEqual((zone.code, zone.fee), ("browser-zone", 13025))
        self.navigate(page, "/staff/orders/")
        page.get_by_label("Search orders").fill(str(order.reference))
        page.get_by_role("button", name="Filter orders").click()
        page.get_by_role("row").filter(has_text=str(order.reference)).get_by_role("link").click()
        expect(page.get_by_text("fixture-bank-reference", exact=False).first).to_be_visible()
        page.get_by_label("Order status").select_option("confirmed")
        page.get_by_label("Tracking carrier").fill("Test courier")
        page.get_by_label("Tracking number").fill("TEST-TRACK-01")
        page.get_by_role("button", name="Save order").click()
        expect(page.get_by_text("Order updated.")).to_be_visible()
        self.database(order.refresh_from_db)
        self.assertEqual((order.state, order.tracking_number), (Order.State.CONFIRMED, "TEST-TRACK-01"))

    @override_settings(PAYMENT_PROVIDER="sslcommerz", PAYMENT_MODE="sandbox", PUBLIC_BASE_URL="https://store.example.test")
    def test_guest_checkout_and_staff_journey(self):
        self.seed()
        User.objects.create_superuser("staff-journey@example.test", self.password)
        with TemporaryDirectory() as media_root, override_settings(DEBUG=True, MEDIA_ROOT=media_root):
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(args=["--host-resolver-rules=MAP sandbox.sslcommerz.com ~NOTFOUND"])
                guest = browser.new_page(viewport={"width": 390, "height": 844})
                guest.set_default_timeout(5000)
                order = self.place_order(guest, guest=True)
                self.pay_with_provider_fixture(guest, order)
                staff = browser.new_page(viewport={"width": 1440, "height": 900})
                staff.set_default_timeout(5000)
                self.staff_journey(staff, order)
                recovered = browser.new_page()
                recovered.set_default_timeout(5000)
                recovered.goto(self.live_server_url + "/orders/access/#" + make_token(order))
                expect(recovered.get_by_text("TEST-TRACK-01", exact=False)).to_be_visible()

    @override_settings(PAYMENT_PROVIDER="sslcommerz", PAYMENT_MODE="sandbox", PUBLIC_BASE_URL="https://store.example.test")
    def test_registered_checkout_and_order_history(self):
        self.seed()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=["--host-resolver-rules=MAP sandbox.sslcommerz.com ~NOTFOUND"])
            page = browser.new_page()
            page.set_default_timeout(5000)
            self.register(page)
            order = self.place_order(page, guest=False)
            assert order.user is not None
            self.assertEqual(order.user.email, "registered-browser@example.test")
            self.pay_with_provider_fixture(page, order)
            page.get_by_role("link", name="Account", exact=True).click()
            page.get_by_role("link", name="View order history").click()
            expect(page.get_by_role("heading", name="Order history")).to_be_visible()
            expect(page.locator(".address-list a").first).to_have_attribute("href", f"/orders/{order.reference}/")
