import json
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from shop.guest_access import make_token
from shop.models import Notification, Order
from shop.notifications import claim, mark_expired_leases, message, process
from shop.provider_http import ProviderError

from .test_checkout import fixtures, review


@override_settings(NOTIFICATION_ADMIN_EMAIL="orders@example.test", NOTIFICATION_ADMIN_PHONE="")
class Notifications(TestCase):
    def setUp(self):
        product, zone = fixtures()
        self.token = review(self.client, product, zone).context["token"]
        self.client.post(reverse("order_submit"), {"quote": self.token})
        self.order = Order.objects.get()

    def claim_channel(self, channel: str) -> Notification:
        Notification.objects.exclude(channel=channel).update(next_attempt_at=timezone.now() + timedelta(days=1))
        job = claim()
        assert job is not None
        self.assertEqual(job.channel, channel)
        return job

    def test_enqueue_deduplicates_order_and_admin_notifications(self):
        self.client.post(reverse("order_submit"), {"quote": self.token})
        self.assertEqual(Notification.objects.filter(template="placed").count(), 2)
        self.assertEqual(Notification.objects.filter(template="admin_placed").count(), 1)
        self.assertTrue(Notification.objects.filter(recipient="orders@example.test").exists())

    @override_settings(RESEND_API_KEY="", RESEND_FROM="")
    def test_missing_credentials_suppress_instead_of_claiming_delivery(self):
        job = self.claim_channel("email")
        with patch("shop.notifications.request_json") as transport:
            self.assertEqual(process(job), Notification.State.SUPPRESSED)
            transport.assert_not_called()
        job.refresh_from_db()
        self.assertEqual(job.state, Notification.State.SUPPRESSED)

    @override_settings(RESEND_API_KEY="fixture", RESEND_FROM="store@example.test",
                       PUBLIC_BASE_URL="https://store.example.test")
    def test_email_timeout_retries_with_same_payload_and_idempotency_key(self):
        job = self.claim_channel("email")
        Notification.objects.exclude(pk=job.pk).update(next_attempt_at=timezone.now() + timedelta(days=1))
        with patch("shop.notifications.request_json", side_effect=[ProviderError(), {"id": "email-ref"}]) as transport:
            self.assertEqual(process(job), Notification.State.QUEUED)
            self.assertIsNone(claim())
            Notification.objects.filter(pk=job.pk).update(next_attempt_at=timezone.now())
            retry = claim()
            assert retry is not None
            self.assertEqual(process(retry), Notification.State.ACCEPTED)
        first, second = (call.args[0] for call in transport.call_args_list)
        self.assertEqual(first.data, second.data)
        self.assertEqual(first.get_header("Idempotency-key"), second.get_header("Idempotency-key"))
        self.assertIn("Order reference", json.loads(first.data)["text"])
        job.refresh_from_db()
        self.assertEqual((job.provider_reference, job.state), ("email-ref", Notification.State.ACCEPTED))

    @override_settings(MIMSMS_API_KEY="fixture", MIMSMS_USERNAME="test@example.test", MIMSMS_SENDER="sender")
    def test_sms_acceptance_and_ambiguous_failure_are_distinct(self):
        job = self.claim_channel("sms")
        with patch("shop.notifications.request_json", return_value={"statusCode": "200", "trackingId": "sms-ref"}) as transport:
            self.assertEqual(process(job), Notification.State.ACCEPTED)
        self.assertEqual(json.loads(transport.call_args.args[0].data)["mobileNumber"], "8801700000000")
        Notification.objects.filter(pk=job.pk).update(state=Notification.State.QUEUED)
        retry = claim()
        assert retry is not None
        with patch("shop.notifications.request_json", side_effect=ProviderError()):
            self.assertEqual(process(retry), Notification.State.UNKNOWN)
        self.assertIsNone(claim())

    def test_expired_worker_lease_is_not_resent_automatically(self):
        job = self.claim_channel("email")
        Notification.objects.filter(pk=job.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
        self.assertEqual(mark_expired_leases(), 1)
        self.assertEqual(Notification.objects.get(pk=job.pk).state, Notification.State.UNKNOWN)

    @override_settings(PUBLIC_BASE_URL="https://store.example.test")
    def test_signed_guest_link_restores_access_and_expires(self):
        job = Notification.objects.get(order=self.order, channel="email", template="placed")
        token = make_token(self.order)
        path = reverse("guest_order_access")
        self.assertIn("https://store.example.test" + path + "#" + token, message(job)[1])
        fresh = Client()
        self.assertContains(fresh.post(path, {"token": token}, follow=True), "Your order")
        self.assertEqual(Client().post(path, {"token": token + "invalid"}).status_code, 404)
        Order.objects.filter(pk=self.order.pk).update(created_at=timezone.now() - timedelta(days=31))
        self.order.refresh_from_db()
        self.assertEqual(Client().post(path, {"token": make_token(self.order)}).status_code, 404)
