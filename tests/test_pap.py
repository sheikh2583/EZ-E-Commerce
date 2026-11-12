import base64
import hmac
import json
import time
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from shop.models import Order, PapPayment, PapWebhookEvent, PaymentAttempt, PaymentEvent
from shop.provider_http import ProviderError

from .test_checkout import fixtures, review

KEY = b"a" * 32
MERCHANT = str(uuid4())
GRANT = str(uuid4())


@override_settings(
    PAYMENT_PROVIDER="pap", PAYMENT_MODE="sandbox", PUBLIC_BASE_URL="https://store.example.test",
    LCT_API_KEY="sk_sandbox_fixture", LCT_CHECKOUT_PROVIDER="sslcommerz", LCT_ONE_TIME_GRANT_ID=GRANT,
    LCT_MERCHANT_ID=MERCHANT, LCT_WEBHOOK_SECRET="whsec_" + base64.b64encode(KEY).decode(),
)
class PapPayments(TestCase):
    def setUp(self):
        self.product, zone = fixtures()
        token = review(self.client, self.product, zone).context["token"]
        self.client.post(reverse("order_submit"), {"quote": token})
        self.order = Order.objects.get()
        self.start = reverse("payment_start", args=[self.order.reference])
        self.return_path = reverse("pap_return", args=[self.order.reference])
        self.webhook = reverse("pap_webhook")
        self.payment_id = str(uuid4())
        self.hosted = "https://sandbox.sslcommerz.com/example-checkout"
        self.session = {"paymentId": self.payment_id, "state": "open", "checkoutUrl": self.hosted}

    def payment(self, status="requires_action", **changes):
        return {
            "id": self.payment_id, "orderReference": str(self.order.reference), "status": status,
            "amountMinor": self.order.total, "currency": "BDT", **changes,
        }

    def initiate(self):
        with patch("shop.pap.request_json", side_effect=[self.payment(), self.session]):
            self.assertRedirects(self.client.post(self.start), self.hosted, fetch_redirect_response=False)
        return PapPayment.objects.get()

    def event(self, event_type="payment.succeeded", **changes):
        return {
            "id": str(uuid4()), "type": event_type, "apiVersion": "2026-11-04", "merchantId": MERCHANT,
            "environment": "sandbox", "data": {"id": self.payment_id}, **changes,
        }

    def deliver(self, event, *, age=0, tamper=False):
        body = json.dumps(event).encode()
        timestamp = str(int(time.time()) - age)
        signature = hmac.digest(KEY, f"{event['id']}.{timestamp}.".encode() + body, "sha256")
        wrong_signature = base64.b64encode(b"b" * 32).decode()
        signatures = f"v1,{wrong_signature} v1,{base64.b64encode(signature).decode()}"
        return Client(enforce_csrf_checks=True).post(
            self.webhook, body + (b" " if tamper else b""), content_type="application/json",
            headers={"webhook-id": event["id"], "webhook-timestamp": timestamp, "webhook-signature": signatures},
        )

    def test_bdt_checkout_reuses_durable_keys_after_timeouts(self):
        with patch("shop.pap.request_json", side_effect=[
            ProviderError(), self.payment(), ProviderError(), ProviderError(404), self.session, self.session,
        ]) as transport:
            self.assertRedirects(self.client.post(self.start), reverse("order", args=[self.order.reference]))
            self.assertRedirects(self.client.post(self.start), reverse("order", args=[self.order.reference]))
            self.assertRedirects(self.client.post(self.start), self.hosted, fetch_redirect_response=False)
            self.assertRedirects(self.client.post(self.start), self.hosted, fetch_redirect_response=False)

        first, create, open_checkout, lookup, retry_checkout, resume = (call.args[0] for call in transport.call_args_list)
        payment = PapPayment.objects.get()
        self.assertEqual(first.full_url, "https://sandbox-pap.ezassist.me/v1/payments")
        self.assertEqual(first.get_header("Authorization"), f"Bearer {settings.LCT_API_KEY}")
        self.assertEqual(first.get_header("Idempotency-key"), str(payment.payment_key))
        self.assertEqual(create.get_header("Idempotency-key"), str(payment.payment_key))
        self.assertEqual(first.data, create.data)
        self.assertEqual(json.loads(create.data), {
            "capabilityGrantId": GRANT, "orderReference": str(self.order.reference),
            "amountMinor": 98000, "currency": "BDT",
        })
        self.assertEqual(open_checkout.full_url, first.full_url + f"/{self.payment_id}/sslcommerz-checkout")
        self.assertEqual(json.loads(open_checkout.data), {"returnUrl": settings.PUBLIC_BASE_URL + self.return_path})
        self.assertEqual(open_checkout.data, retry_checkout.data)
        self.assertEqual(open_checkout.get_header("Idempotency-key"), str(payment.checkout_key))
        self.assertEqual(retry_checkout.get_header("Idempotency-key"), str(payment.checkout_key))
        self.assertEqual([lookup.method, resume.method], ["GET", "GET"])
        self.assertEqual(PaymentAttempt.objects.count(), 1)

    @override_settings(LCT_CHECKOUT_PROVIDER="stripe", LCT_API_KEY="sk_live_fixture", PAYMENT_MODE="live")
    def test_live_stripe_checkout_and_verified_return(self):
        hosted = "https://checkout.stripe.com/c/pay/session"
        session = {"paymentId": self.payment_id, "state": "ready", "checkoutUrl": hosted}
        with patch("shop.pap.request_json", side_effect=[self.payment(), session, self.payment("succeeded")]) as transport:
            self.assertRedirects(self.client.post(self.start), hosted, fetch_redirect_response=False)
            self.assertEqual(Client().get(self.return_path).status_code, 404)
            self.assertEqual(self.client.get(self.return_path, {"payment_id": str(uuid4())}).status_code, 400)
            response = self.client.get(self.return_path, {"payment_id": self.payment_id})
            self.assertEqual(response.status_code, 303)

        checkout = transport.call_args_list[1].args[0]
        self.assertEqual(checkout.full_url, f"https://pap.ezassist.me/v1/payments/{self.payment_id}/checkout")
        url = settings.PUBLIC_BASE_URL + self.return_path
        self.assertEqual(json.loads(checkout.data), {"successUrl": url, "cancelUrl": url})
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.order.payment_state, Order.PaymentState.PAID)
        self.assertEqual((self.product.stock, self.product.reserved), (0, 0))

    def test_browser_cancel_stays_pending_until_gateway_confirms_expiry(self):
        self.initiate()
        with patch("shop.pap.request_json", side_effect=[self.payment(), self.session, self.session, self.payment()]):
            self.assertEqual(self.client.get(self.return_path, {"checkout_cancelled": "1"}).status_code, 303)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_state, Order.PaymentState.PENDING)
        with patch("shop.pap.request_json", return_value=self.payment("expired")):
            self.assertEqual(self.client.get(self.return_path).status_code, 303)
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.order.state, Order.State.CANCELLED)
        self.assertEqual((self.product.stock, self.product.reserved), (1, 0))

    def test_success_with_wrong_amount_goes_to_review(self):
        self.initiate()
        with patch("shop.pap.request_json", return_value=self.payment("succeeded", amountMinor=980)):
            self.assertEqual(self.client.get(self.return_path).status_code, 303)
        self.order.refresh_from_db()
        self.assertTrue(self.order.payment_review)
        self.assertIsNone(self.order.accepted_payment_id)

    def test_untrusted_checkout_host_is_rejected(self):
        with patch("shop.pap.request_json", side_effect=[
            self.payment(), {**self.session, "checkoutUrl": "https://sandbox.sslcommerz.com.invalid/example"},
        ]):
            self.assertRedirects(self.client.post(self.start), reverse("order", args=[self.order.reference]))

    def test_webhook_verification_and_duplicate_delivery(self):
        self.initiate()
        challenge = self.event("webhook.endpoint_verification", data={"challenge": "fixture-token"})
        self.assertEqual(self.deliver(challenge)["x-lct-webhook-challenge"], "fixture-token")
        event = self.event()
        self.assertEqual(self.deliver(event, tamper=True).status_code, 401)
        self.assertEqual(self.deliver(event, age=301).status_code, 401)
        self.assertEqual(self.deliver(self.event(environment="production")).status_code, 401)
        self.assertEqual(self.deliver(self.event(merchantId=str(uuid4()))).status_code, 401)
        self.assertEqual(self.deliver(event).status_code, 204)
        self.assertEqual(self.deliver(event).status_code, 204)
        self.assertEqual(PapWebhookEvent.objects.count(), 1)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_state, Order.PaymentState.PENDING)

        with patch("shop.pap.request_json", side_effect=ProviderError(503)):
            call_command("reconcile_payments", stdout=StringIO())
        self.assertIsNone(PapWebhookEvent.objects.get().processed_at)
        with patch("shop.pap.request_json", return_value=self.payment("succeeded")) as transport:
            call_command("reconcile_payments", stdout=StringIO())
            call_command("reconcile_payments", stdout=StringIO())
        transport.assert_called_once()
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_state, Order.PaymentState.PAID)
        self.assertEqual(PaymentEvent.objects.filter(outcome="verified").count(), 1)
        self.assertIsNotNone(PapWebhookEvent.objects.get().processed_at)

    @override_settings(LCT_CHECKOUT_PROVIDER="stripe", LCT_API_KEY="sk_live_fixture", PAYMENT_MODE="live")
    def test_live_webhook_accepts_production_events_and_reconciles_live_payment(self):
        hosted = "https://checkout.stripe.com/c/pay/session"
        session = {"paymentId": self.payment_id, "state": "ready", "checkoutUrl": hosted}
        with patch("shop.pap.request_json", side_effect=[self.payment(), session]):
            self.assertRedirects(self.client.post(self.start), hosted, fetch_redirect_response=False)

        challenge = self.event(
            "webhook.endpoint_verification", environment="production", data={"challenge": "live-fixture"},
        )
        self.assertEqual(self.deliver(challenge)["x-lct-webhook-challenge"], "live-fixture")
        self.assertEqual(self.deliver(self.event()).status_code, 401)
        self.assertEqual(self.deliver(self.event(environment="production")).status_code, 204)
        self.assertEqual(PapWebhookEvent.objects.get().mode, "live")

        with patch("shop.pap.request_json", return_value=self.payment("succeeded")) as transport:
            call_command("reconcile_payments", stdout=StringIO())
        self.assertEqual(transport.call_args.args[0].full_url, f"https://pap.ezassist.me/v1/payments/{self.payment_id}")
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_state, Order.PaymentState.PAID)

    def test_reconciliation_checks_provider_when_return_and_webhook_are_missing(self):
        self.initiate()
        PaymentAttempt.objects.update(updated_at=timezone.now() - timedelta(minutes=3))
        with patch("shop.pap.request_json", side_effect=[
            self.payment(), self.session, {**self.session, "state": "verified"}, self.payment("succeeded"),
        ]) as transport:
            call_command("reconcile_payments", stdout=StringIO())
        refresh = transport.call_args_list[2].args[0]
        self.assertEqual(refresh.method, "POST")
        self.assertTrue(refresh.full_url.endswith("/sslcommerz-checkout/reconcile"))
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_state, Order.PaymentState.PAID)
