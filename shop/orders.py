import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.core import signing
from django.db import transaction
from django.db.models import F, Q
from django.http import HttpRequest
from django.utils import timezone

from .cart import MAX_QUANTITY, calculate_totals, guest_digest
from .inventory import reserve_stock
from .models import (
    Cart,
    CartItem,
    DeliveryZone,
    InventoryReservation,
    Order,
    OrderItem,
    OrderStatusEvent,
    Product,
)

QUOTE_SALT = "shop.checkout.v1"
QUOTE_SECONDS = 15 * 60
RESERVATION_TIME = timedelta(minutes=30)
GUEST_ORDER_SESSION = "guest_order_refs"


class CheckoutError(ValueError):
    pass


@dataclass(frozen=True)
class Quote:
    cart_id: int
    items: list[CartItem]
    zone: DeliveryZone
    subtotal: int
    discount: int

    @property
    def total(self) -> int:
        return self.subtotal - self.discount + self.zone.fee

    def fingerprint(self) -> str:
        content = [
            self.zone.pk, self.zone.name, self.zone.fee,
            [
                [item.product_id, item.quantity, item.product.sku, item.product.name,
                 item.product.regular_price, item.product.unit_price]
                for item in self.items
            ],
        ]
        return hashlib.sha256(json.dumps(content, separators=(",", ":")).encode()).hexdigest()


def get_quote(cart_id: int, zone_id: int, *, lock: bool = False) -> Quote:
    zones = DeliveryZone.objects.filter(active=True)
    zone = (zones.select_for_update() if lock else zones).filter(pk=zone_id).first()
    if zone is None:
        raise CheckoutError("The selected delivery zone is no longer available.")
    items = list(CartItem.objects.filter(cart_id=cart_id).select_related("product__category").order_by("product_id"))
    if not items:
        raise CheckoutError("Your cart is empty.")
    if lock:
        products = {
            product.pk: product for product in Product.objects.select_related("category")
            .select_for_update(of=("self",)).filter(pk__in=[item.product_id for item in items]).order_by("pk")
        }
        for item in items:
            product = products.get(item.product_id)
            if product is None:
                raise CheckoutError("A product has been removed. Update your cart and try again.")
            item.product = product
    for item in items:
        if not item.product.active or not item.product.category.active or item.quantity > min(MAX_QUANTITY, item.product.available):
            raise CheckoutError(f"Availability changed for {item.product.name}. Update your cart and try again.")
    totals = calculate_totals(items)
    quote = Quote(cart_id, items, zone, totals.subtotal, totals.discount)
    if quote.subtotal > 999_999_999_999 or quote.total > 999_999_999_999:
        raise CheckoutError("The order exceeds the online checkout limit.")
    return quote


def sign_quote(quote: Quote, customer: dict[str, str]) -> str:
    return signing.dumps({
        "cart": quote.cart_id, "zone": quote.zone.pk, "key": str(uuid.uuid4()),
        "fingerprint": quote.fingerprint(), "customer": customer,
    }, salt=QUOTE_SALT)


def cart_ownership(request: HttpRequest) -> Q:
    if request.user.is_authenticated:
        return Q(user=request.user)
    digest = guest_digest(request)
    return Q(user__isnull=True, guest_digest=digest) if digest else Q(pk__in=[])


@transaction.atomic
def place_order(request: HttpRequest, token: str) -> Order:
    try:
        payload = signing.loads(token, salt=QUOTE_SALT, max_age=QUOTE_SECONDS)
    except signing.BadSignature as error:
        raise CheckoutError("This order review expired or is invalid. Review your order again.") from error
    cart = Cart.objects.select_for_update().filter(cart_ownership(request), pk=payload["cart"]).first()
    if cart is None:
        raise CheckoutError("This order review belongs to a different cart.")
    existing = Order.objects.filter(cart=cart, checkout_key=payload["key"]).first()
    if existing:
        return existing
    if cart.state != Cart.State.OPEN or (cart.expires_at is not None and cart.expires_at <= timezone.now()):
        raise CheckoutError("This cart has been closed. Open your cart and try again.")
    quote = get_quote(cart.pk, payload["zone"], lock=True)
    if quote.fingerprint() != payload["fingerprint"]:
        raise CheckoutError("Prices or delivery charges changed. Review the updated order before placing it.")
    order = Order.objects.create(
        cart=cart, user_id=cart.user_id, checkout_key=payload["key"],
        request_fingerprint=hashlib.sha256(token.encode()).hexdigest(),
        zone=quote.zone, zone_name=quote.zone.name, subtotal=quote.subtotal, discount=quote.discount,
        delivery=quote.zone.fee, total=quote.total, **payload["customer"],
    )
    expires_at = timezone.now() + RESERVATION_TIME
    for item in quote.items:
        if not reserve_stock(item.product_id, item.quantity):
            raise CheckoutError("Stock changed while placing the order. Review your cart and try again.")
        product = item.product
        line = OrderItem.objects.create(
            order=order, product=product, name=product.name, sku=product.sku, quantity=item.quantity,
            regular_unit_price=product.regular_price, charged_unit_price=product.unit_price,
        )
        InventoryReservation.objects.create(item=line, product=product, expires_at=expires_at)
    OrderStatusEvent.objects.create(order=order, actor_id=cart.user_id, current=Order.State.PENDING)
    cart.state = Cart.State.CLOSED
    cart.save(update_fields=["state", "updated_at"])
    return order


def record_guest_order(request: HttpRequest, order: Order) -> None:
    if order.user_id is None:
        refs = list(request.session.get(GUEST_ORDER_SESSION, []))
        reference = str(order.reference)
        if reference not in refs:
            request.session[GUEST_ORDER_SESSION] = [*refs[-19:], reference]


def visible_orders(request: HttpRequest) -> Q:
    refs = request.session.get(GUEST_ORDER_SESSION, [])
    guest = Q(user__isnull=True, reference__in=refs)
    return guest | Q(user=request.user) if request.user.is_authenticated else guest


def change_reservations(order: Order, state: InventoryReservation.State) -> int:
    """Transition reservations inside the transaction holding the order row lock."""
    reservations = list(
        InventoryReservation.objects.select_for_update(of=("self",)).select_related("item")
        .filter(item__order=order, state=InventoryReservation.State.HELD).order_by("product_id")
    )
    for reservation in reservations:
        quantity = reservation.item.quantity
        if state == InventoryReservation.State.CONSUMED:
            Product.objects.filter(pk=reservation.product_id).update(stock=F("stock") - quantity, reserved=F("reserved") - quantity)
        else:
            Product.objects.filter(pk=reservation.product_id).update(reserved=F("reserved") - quantity)
        reservation.state = state
        reservation.save(update_fields=["state"])
    return len(reservations)


@transaction.atomic
def expire_unpaid(order_id: int) -> bool:
    order = Order.objects.select_for_update().filter(
        pk=order_id, state=Order.State.PENDING, payment_state=Order.PaymentState.UNPAID,
    ).first()
    if order is None or order.payments.exists():
        return False
    if not InventoryReservation.objects.filter(
        item__order=order, state=InventoryReservation.State.HELD, expires_at__lte=timezone.now(),
    ).exists():
        return False
    change_reservations(order, InventoryReservation.State.RELEASED)
    order.state = Order.State.CANCELLED
    order.save(update_fields=["state", "updated_at"])
    OrderStatusEvent.objects.create(
        order=order, previous=Order.State.PENDING, current=Order.State.CANCELLED, reason="Reservation expired",
    )
    return True
