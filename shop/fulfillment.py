from django.db import transaction

from .models import InventoryReservation, Order, OrderStatusEvent, PaymentAttempt
from .notifications import enqueue_state
from .orders import change_reservations

NEXT_STATE = {
    Order.State.PENDING: Order.State.CONFIRMED,
    Order.State.CONFIRMED: Order.State.PROCESSING,
    Order.State.PROCESSING: Order.State.SHIPPED,
    Order.State.SHIPPED: Order.State.DELIVERED,
}


class FulfillmentError(ValueError):
    pass


def choices(order: Order) -> list[tuple[str, str]]:
    state = Order.State(order.state)
    available = [(state.value, state.label)]
    if order.payment_state == Order.PaymentState.PAID and not order.payment_review:
        next_state = NEXT_STATE.get(state)
        if next_state:
            available.append((next_state.value, next_state.label))
    if state == Order.State.PENDING and order.payment_state in (Order.PaymentState.UNPAID, Order.PaymentState.FAILED):
        available.append((Order.State.CANCELLED.value, Order.State.CANCELLED.label))
    return available


@transaction.atomic
def update_order(order_id: int, actor_id: int, *, state: str, tracking_carrier: str, tracking_number: str) -> None:
    order = Order.objects.select_for_update().get(pk=order_id)
    if state not in {value for value, _ in choices(order)}:
        raise FulfillmentError("This transition is not available for the current order and payment states.")
    previous = order.state
    if state == Order.State.CANCELLED and state != previous:
        if order.payments.filter(state__in=(PaymentAttempt.State.PENDING, PaymentAttempt.State.REVIEW)).exists():
            raise FulfillmentError("Reconcile the payment before cancelling this order.")
        change_reservations(order, InventoryReservation.State.RELEASED)
    tracking_changed = (order.tracking_carrier, order.tracking_number) != (tracking_carrier, tracking_number)
    if state == previous and not tracking_changed:
        return
    order.state = state
    order.tracking_carrier = tracking_carrier
    order.tracking_number = tracking_number
    order.save(update_fields=["state", "tracking_carrier", "tracking_number", "updated_at"])
    event = OrderStatusEvent.objects.create(
        order=order, actor_id=actor_id, previous=previous, current=state,
        reason="Tracking updated" if previous == state else "Staff updated order status",
    )
    if previous != state:
        enqueue_state(order, event.pk)
