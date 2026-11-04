from django.core.management.base import BaseCommand
from django.utils import timezone

from shop.models import InventoryReservation, Order
from shop.orders import expire_unpaid


class Command(BaseCommand):
    help = "Release expired reservations for orders that have never started payment."

    def handle(self, *args, **options) -> None:
        order_ids = (
            InventoryReservation.objects.filter(
                state=InventoryReservation.State.HELD, expires_at__lte=timezone.now(),
                item__order__state=Order.State.PENDING, item__order__payment_state=Order.PaymentState.UNPAID,
                item__order__payments__isnull=True,
            ).values_list("item__order_id", flat=True).order_by("item__order_id").distinct()[:100]
        )
        count = sum(expire_unpaid(order_id) for order_id in list(order_ids))
        self.stdout.write(f"Expired {count} unpaid order reservations.")
