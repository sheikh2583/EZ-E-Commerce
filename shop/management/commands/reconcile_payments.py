from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from shop.gateway import HOSTS, gateway
from shop.models import PaymentAttempt
from shop.payments import audit, reconcile
from shop.provider_http import ProviderError


class Command(BaseCommand):
    help = "Query the configured gateway for unresolved attempts."

    def handle(self, *args, **options) -> None:
        if settings.PAYMENT_MODE not in HOSTS:
            self.stdout.write("Gateway reconciliation is disabled.")
            return
        provider = gateway()
        attempts = PaymentAttempt.objects.filter(
            provider="sslcommerz", mode=settings.PAYMENT_MODE, state=PaymentAttempt.State.PENDING,
            updated_at__lt=timezone.now() - timedelta(minutes=2),
        ).order_by("updated_at")[:40]
        for attempt in attempts:
            try:
                reconcile(provider, attempt)
            except ProviderError:
                audit(attempt, "verification_unavailable")
            PaymentAttempt.objects.filter(pk=attempt.pk, state=PaymentAttempt.State.PENDING).update(
                updated_at=timezone.now(),
            )
        self.stdout.write(f"Checked {len(attempts)} payment attempts.")
