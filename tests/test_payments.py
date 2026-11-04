from unittest.mock import patch
from urllib.parse import parse_qs

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from shop.models import Order, PaymentAttempt, PaymentEvent
from shop.provider_http import ProviderError

from .test_checkout import fixtures, review


@override_settings(
    PAYMENT_MODE="sandbox", PUBLIC_BASE_URL="https://store.example.test",
    SSLCOMMERZ_STORE_ID="store-placeholder", SSLCOMMERZ_STORE_PASSWORD="placeholder",
)
class Payments(TestCase):
    def setUp(self):
        self.product, self.zone = fixtures()
        token = review(self.client, self.product, self.zone).context["token"]
        self.client.post(reverse("order_submit"), {"quote": token})
        self.order = Order.objects.get()
        self.start = reverse("payment_start", args=[self.order.reference])
        self.ipn = reverse("payment_ipn")
        self.hosted = "https://sandbox.sslcommerz.com/gwprocess/test"

    def initiate(self) -> PaymentAttempt:
        with patch("shop.gateway.request_json", return_value={
            "status": "SUCCESS", "GatewayPageURL": self.hosted, "sessionkey": "sandbox-session",
        }) as transport:
            self.assertEqual(self.client.post(self.start)["Location"], self.hosted)
            self.assertEqual(self.client.post(self.start)["Location"], self.hosted)
        transport.assert_called_once()
        request = transport.call_args.args[0]
        fields = parse_qs(request.data.decode())
        self.assertEqual(fields["total_amount"], ["980.00"])
        self.assertEqual(fields["currency"], ["BDT"])
        self.assertEqual(fields["ipn_url"], ["https://store.example.test/payments/ipn/"])
        return PaymentAttempt.objects.get()

    def verification(self, attempt: PaymentAttempt, **changes) -> dict:
        return {
            "status": "VALID", "tran_id": attempt.merchant_reference, "val_id": "validation-1",
            "amount": "980.00", "currency": "BDT", "currency_type": "BDT",
            "currency_amount": "980.00", "bank_tran_id": "bank-1", "risk_level": "0", **changes,
        }

    def callback(self, attempt: PaymentAttempt, validation_id: str = "validation-1"):
        return self.client.post(self.ipn, {"tran_id": attempt.merchant_reference, "val_id": validation_id})

    def test_only_independent_verified_payment_can_set_paid(self):
        attempt = self.initiate()
        self.assertEqual(Client().post(self.start).status_code, 404)
        self.assertEqual(self.client.get(reverse("payment_return")).status_code, 405)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_state, Order.PaymentState.PENDING)
        with patch("shop.gateway.request_json", return_value=self.verification(attempt)) as transport:
            self.assertJSONEqual(self.callback(attempt).content, {"status": "verified"})
            self.assertJSONEqual(self.callback(attempt).content, {"status": "verified"})
        self.assertEqual(transport.call_count, 2)
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.order.payment_state, Order.PaymentState.PAID)
        self.assertEqual(self.order.accepted_payment_id, attempt.pk)
        self.assertEqual(self.order.state, Order.State.PENDING)
        self.assertEqual((self.product.stock, self.product.reserved), (0, 0))
        self.assertEqual(PaymentEvent.objects.filter(outcome="verified").count(), 1)
        with patch("shop.gateway.request_json", return_value=self.verification(
            attempt, val_id="validation-2", bank_tran_id="second-bank",
        )):
            self.assertJSONEqual(self.callback(attempt, "validation-2").content, {"status": "review"})
        self.order.refresh_from_db()
        self.assertTrue(self.order.payment_review)

    def test_wrong_reference_and_provider_failure_keep_reservation(self):
        attempt = self.initiate()
        self.assertEqual(self.client.post(self.ipn, {"tran_id": "unknown"}).status_code, 400)
        with patch("shop.gateway.request_json", return_value=self.verification(attempt, tran_id="different")):
            self.assertEqual(self.callback(attempt).status_code, 400)
        with patch("shop.gateway.request_json", side_effect=ProviderError()):
            self.assertEqual(self.callback(attempt).status_code, 503)
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.order.payment_state, Order.PaymentState.PENDING)
        self.assertEqual(self.product.reserved, 1)

    def test_verified_mismatch_goes_to_review(self):
        attempt = self.initiate()
        with patch("shop.gateway.request_json", return_value=self.verification(attempt, amount="9.80")):
            self.assertJSONEqual(self.callback(attempt).content, {"status": "review"})
        self.order.refresh_from_db()
        attempt.refresh_from_db()
        self.assertTrue(self.order.payment_review)
        self.assertEqual(attempt.state, PaymentAttempt.State.REVIEW)
        self.assertEqual(self.order.payment_state, Order.PaymentState.PENDING)

    def test_gateway_confirmed_failure_releases_stock_and_late_capture_is_held(self):
        attempt = self.initiate()
        with patch("shop.gateway.request_json", return_value={"APIConnect": "DONE", "element": [
            {"tran_id": attempt.merchant_reference, "status": "FAILED"},
        ]}):
            self.assertJSONEqual(self.callback(attempt, "").content, {"status": "failed"})
        self.product.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual((self.product.stock, self.product.reserved), (1, 0))
        self.assertEqual(self.order.state, Order.State.CANCELLED)
        with patch("shop.gateway.request_json", return_value=self.verification(attempt)):
            self.assertJSONEqual(self.callback(attempt).content, {"status": "review"})
        self.order.refresh_from_db()
        self.assertTrue(self.order.payment_review)
        self.assertNotEqual(self.order.payment_state, Order.PaymentState.PAID)

    def test_cancelled_browser_return_uses_gateway_query(self):
        attempt = self.initiate()
        with patch("shop.gateway.request_json", return_value={"APIConnect": "DONE", "element": [
            {"tran_id": attempt.merchant_reference, "status": "CANCELLED"},
        ]}):
            response = self.client.post(reverse("payment_return"), {
                "tran_id": attempt.merchant_reference, "status": "VALID",
            })
        self.assertEqual(response.status_code, 303)
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, PaymentAttempt.State.CANCELLED)

    @override_settings(DEBUG=True, PAYMENT_MODE="simulation")
    def test_simulation_does_not_create_a_verified_payment(self):
        result = self.client.post(self.start, follow=True)
        self.assertContains(result, "Development simulation complete")
        self.order.refresh_from_db()
        self.assertEqual(PaymentAttempt.objects.get().state, PaymentAttempt.State.SIMULATED)
        self.assertEqual(self.order.payment_state, Order.PaymentState.UNPAID)
        self.assertIsNone(self.order.accepted_payment_id)
