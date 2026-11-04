from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from shop.models import Product, RateBucket
from shop.security import client_address

from .test_checkout import fixtures


class SecurityChecks(TestCase):
    @override_settings(DJANGO_FORWARDED_FOR_HOPS=0)
    def test_forged_forwarded_header_is_ignored_without_trusted_proxy(self):
        request = RequestFactory().get("/", REMOTE_ADDR="192.0.2.4", HTTP_X_FORWARDED_FOR="198.51.100.3")
        self.assertEqual(client_address(request), "192.0.2.4")

    @override_settings(DJANGO_FORWARDED_FOR_HOPS=1)
    def test_trusted_proxy_selection_ignores_untrusted_prefix(self):
        request = RequestFactory().get("/", REMOTE_ADDR="192.0.2.4", HTTP_X_FORWARDED_FOR="198.51.100.3, 203.0.113.2")
        self.assertEqual(client_address(request), "203.0.113.2")

    def test_login_identity_limit_survives_source_ip_changes_and_expires(self):
        for attempt in range(13):
            response = self.client.post(
                reverse("login"), {"username": "rate-limit@example.test", "password": "wrong"},
                REMOTE_ADDR=f"192.0.2.{attempt + 1}",
            )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "300")
        self.assertFalse(any("rate-limit@example.test" in key for key in RateBucket.objects.values_list("key", flat=True)))
        RateBucket.objects.update(expires_at=timezone.now())
        call_command("prune_rate_limits", stdout=StringIO())
        self.assertFalse(RateBucket.objects.exists())

    def test_large_bodies_are_rejected_and_sandbox_form_target_is_allowed(self):
        response = self.client.post(reverse("payment_ipn"), "a" * 300000, content_type="text/plain")
        self.assertEqual(response.status_code, 413)
        with override_settings(PAYMENT_MODE="sandbox"):
            response = self.client.get(reverse("home"))
        policy = response["Content-Security-Policy"]
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertIn("form-action 'self' https://sandbox.sslcommerz.com", policy)
        self.assertNotIn("unsafe-inline", policy)
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    @override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True, SECURE_HSTS_SECONDS=31536000)
    def test_secure_cookies_and_output_escaping(self):
        product, _ = fixtures()
        Product.objects.filter(pk=product.pk).update(description="<script>alert(1)</script>")
        response = self.client.get(reverse("product", args=[product.slug]), secure=True)
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertTrue(response.cookies["csrftoken"]["secure"])
        self.assertIn("max-age=31536000", response["Strict-Transport-Security"])
        response = self.client.post(reverse("cart_add", args=[product.pk]), {"quantity": "1"}, secure=True)
        self.assertTrue(response.cookies["sessionid"]["secure"])
        self.assertTrue(response.cookies["sessionid"]["httponly"])

    @override_settings(DEBUG=True)
    def test_catalogue_query_budget_and_search_parameterization(self):
        call_command("seed_demo", stdout=StringIO())
        with CaptureQueriesContext(connection) as sql:
            response = self.client.get(reverse("catalogue"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["page"].object_list), 12)
        self.assertLessEqual(len(sql), 7)
        probe = self.client.get(reverse("catalogue"), {"q": "' OR 1=1 --"})
        self.assertContains(probe, "No products found")
        self.assertEqual(Product.objects.count(), 120)
