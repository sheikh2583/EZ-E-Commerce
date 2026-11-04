import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Q, Sum
from django.http import HttpRequest
from django.utils import timezone

from .models import Cart, CartItem, Product

GUEST_CART_KEY = "guest_cart"
MAX_QUANTITY = 10_000


class CartError(ValueError):
    pass


@dataclass(frozen=True)
class CartTotals:
    subtotal: int
    discount: int

    @property
    def merchandise(self) -> int:
        return self.subtotal - self.discount


def cart_items(cart: Cart | None) -> list[CartItem]:
    if cart is None:
        return []
    return list(
        CartItem.objects.filter(cart=cart).select_related("product__category")
        .prefetch_related("product__images").order_by("pk")
    )


def calculate_totals(items: list[CartItem]) -> CartTotals:
    subtotal = sum(item.quantity * item.product.regular_price for item in items)
    charged = sum(item.quantity * item.product.unit_price for item in items)
    return CartTotals(subtotal=subtotal, discount=subtotal - charged)


def guest_digest(request: HttpRequest, *, create: bool = False) -> str:
    token = request.session.get(GUEST_CART_KEY)
    if not token and create:
        token = secrets.token_urlsafe(32)
        request.session[GUEST_CART_KEY] = token
    return hashlib.sha256(token.encode()).hexdigest() if token else ""


def current_cart(request: HttpRequest, *, create: bool = False) -> Cart | None:
    if request.user.is_authenticated:
        lookup = Cart.objects.filter(state=Cart.State.OPEN, user=request.user)
        return lookup.get_or_create(defaults={"state": Cart.State.OPEN, "user": request.user})[0] if create else lookup.first()

    digest = guest_digest(request, create=create)
    if not digest:
        return None
    now = timezone.now()
    lookup = Cart.objects.filter(state=Cart.State.OPEN, user__isnull=True, guest_digest=digest)
    if not create:
        return lookup.filter(expires_at__gt=now).first()
    with transaction.atomic():
        lookup.filter(expires_at__lte=now).update(state=Cart.State.CLOSED)
        cart, _ = lookup.get_or_create(defaults={
            "state": Cart.State.OPEN, "user": None, "guest_digest": digest,
            "expires_at": now + timedelta(days=30),
        })
    return cart


@transaction.atomic
def set_quantity(cart: Cart, product_id: int, quantity: int, *, add: bool = False) -> None:
    locked = Cart.objects.select_for_update().get(pk=cart.pk)
    if locked.state != Cart.State.OPEN:
        raise CartError("This cart has been closed. Open your cart and try again.")
    current = CartItem.objects.filter(cart=locked, product_id=product_id)
    if not add and quantity == 0:
        current.delete()
        return
    product = Product.objects.select_related("category").select_for_update(of=("self",)).filter(pk=product_id).first()
    if product is None or not product.active or not product.category.active:
        raise CartError("This product is no longer available.")
    item = current.first()
    if add and item:
        quantity += item.quantity
    if not 1 <= quantity <= min(product.available, MAX_QUANTITY):
        raise CartError(f"Only {min(product.available, MAX_QUANTITY)} units are available for this product.")
    current.update_or_create(defaults={"quantity": quantity}, cart=locked, product=product)


@transaction.atomic
def merge_guest_cart(request: HttpRequest) -> None:
    digest = guest_digest(request)
    if not digest:
        return
    guest = Cart.objects.filter(
        state=Cart.State.OPEN, user__isnull=True, guest_digest=digest, expires_at__gt=timezone.now(),
    ).first()
    if guest:
        personal = current_cart(request, create=True)
        assert personal is not None
        locked = {
            cart.pk: cart for cart in Cart.objects.select_for_update()
            .filter(Q(pk=guest.pk) | Q(pk=personal.pk)).order_by("pk")
        }
        guest, personal = locked[guest.pk], locked[personal.pk]
        if guest.state == Cart.State.OPEN and personal.state == Cart.State.OPEN:
            guest_items = list(CartItem.objects.filter(cart=guest).order_by("product_id"))
            for item in guest_items:
                product = Product.objects.select_related("category").select_for_update(of=("self",)).get(pk=item.product_id)
                if not product.active or not product.category.active or not product.available:
                    continue
                saved = CartItem.objects.filter(cart=personal, product=product).first()
                quantity = min(item.quantity + (saved.quantity if saved else 0), product.available, MAX_QUANTITY)
                CartItem.objects.update_or_create(cart=personal, product=product, defaults={"quantity": quantity})
            guest.state = Cart.State.CLOSED
            guest.save(update_fields=["state", "updated_at"])
    request.session.pop(GUEST_CART_KEY, None)


def cart_indicator(request: HttpRequest) -> dict[str, int]:
    cart = current_cart(request)
    if cart is None:
        return {"cart_count": 0}
    count = CartItem.objects.filter(cart=cart).aggregate(total=Sum("quantity"))["total"]
    return {"cart_count": count or 0}
