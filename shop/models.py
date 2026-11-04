import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    active = models.BooleanField(default=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "name", "pk"]
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, models.PROTECT, related_name="products")
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=150, unique=True)
    sku = models.CharField(max_length=50, unique=True)
    description = models.TextField()
    regular_price = models.PositiveBigIntegerField()
    sale_price = models.PositiveBigIntegerField(null=True, blank=True)
    stock = models.PositiveIntegerField(default=0)
    reserved = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(regular_price__gt=0) & (
                    Q(sale_price__isnull=True) | Q(sale_price__gt=0, sale_price__lt=F("regular_price"))
                ),
                name="product_valid_prices",
            ),
            models.CheckConstraint(condition=Q(reserved__lte=F("stock")), name="product_valid_stock"),
        ]
        indexes = [
            models.Index(fields=["category", "regular_price", "id"], condition=Q(active=True), name="product_active_category"),
            models.Index(fields=["-created_at", "-id"], condition=Q(active=True), name="product_active_recent"),
        ]

    @property
    def unit_price(self) -> int:
        return self.sale_price if self.sale_price is not None else self.regular_price

    @property
    def available(self) -> int:
        return self.stock - self.reserved

    def __str__(self) -> str:
        return self.name


class ProductImage(models.Model):
    product = models.ForeignKey(Product, models.CASCADE, related_name="images")
    asset_id = models.CharField(max_length=255, unique=True)
    alt = models.CharField(max_length=180)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["product", "position"], name="product_image_position_unique")
        ]


class DeliveryZone(models.Model):
    name = models.CharField(max_length=100)
    code = models.SlugField(unique=True)
    fee = models.PositiveBigIntegerField()
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name", "pk"]

    def __str__(self) -> str:
        return self.name


class StoreSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    display_name = models.CharField(max_length=100, default="Storefront")
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    contact_address = models.TextField(blank=True)
    banner_title = models.CharField(max_length=160, blank=True)
    banner_body = models.TextField(blank=True)
    low_stock_threshold = models.PositiveSmallIntegerField(default=5)

    class Meta:
        verbose_name_plural = "store settings"
        constraints = [models.CheckConstraint(condition=Q(id=1), name="store_single_settings_row")]

    def __str__(self) -> str:
        return self.display_name


class Address(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, models.CASCADE, related_name="addresses")
    label = models.CharField(max_length=80)
    recipient = models.CharField(max_length=120)
    phone = models.CharField(max_length=25)
    line = models.CharField(max_length=250)
    locality = models.CharField(max_length=100)
    postcode = models.CharField(max_length=12, blank=True)
    zone = models.ForeignKey(DeliveryZone, models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["label", "pk"]

    def __str__(self) -> str:
        return self.label


class Cart(models.Model):
    class State(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True)
    guest_digest = models.CharField(max_length=64, blank=True)
    state = models.CharField(max_length=12, choices=State, default=State.OPEN)
    expires_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user"], condition=Q(state="open"), name="open_cart_per_user"),
            models.UniqueConstraint(
                fields=["guest_digest"],
                condition=Q(state="open", user__isnull=True) & ~Q(guest_digest=""),
                name="open_cart_per_guest",
            ),
        ]


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, models.CASCADE)
    quantity = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["cart", "product"], name="cart_product_unique"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="cart_quantity_positive"),
        ]


class Order(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        PROCESSING = "processing", "Processing"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    class PaymentState(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PENDING = "pending", "Pending verification"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    reference = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True, related_name="orders")
    cart = models.ForeignKey(Cart, models.PROTECT)
    checkout_key = models.UUIDField()
    request_fingerprint = models.CharField(max_length=64)
    recipient = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=25)
    address_line = models.CharField(max_length=250)
    locality = models.CharField(max_length=100)
    postcode = models.CharField(max_length=12, blank=True)
    notes = models.TextField(blank=True)
    zone = models.ForeignKey(DeliveryZone, models.SET_NULL, null=True)
    zone_name = models.CharField(max_length=100)
    subtotal = models.PositiveBigIntegerField()
    discount = models.PositiveBigIntegerField(default=0)
    delivery = models.PositiveBigIntegerField()
    total = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, default="BDT")
    state = models.CharField(max_length=16, choices=State, default=State.PENDING)
    payment_state = models.CharField(max_length=16, choices=PaymentState, default=PaymentState.UNPAID)
    accepted_payment = models.OneToOneField("PaymentAttempt", models.PROTECT, null=True, blank=True, related_name="+")
    payment_review = models.BooleanField(default=False)
    tracking_number = models.CharField(max_length=120, blank=True)
    tracking_carrier = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["cart", "checkout_key"], name="order_checkout_key_unique"),
            models.CheckConstraint(
                condition=Q(discount__lte=F("subtotal"), total=F("subtotal") - F("discount") + F("delivery")),
                name="order_totals_match",
            ),
            models.CheckConstraint(
                condition=~Q(payment_state__in=["paid", "refunded"]) | Q(accepted_payment__isnull=False),
                name="order_paid_requires_payment",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="order_customer_recent"),
            models.Index(fields=["state", "-created_at"], name="order_state_recent"),
        ]

    def __str__(self) -> str:
        return str(self.reference)


class OrderItem(models.Model):
    order = models.ForeignKey(Order, models.PROTECT, related_name="items")
    product = models.ForeignKey(Product, models.SET_NULL, null=True)
    name = models.CharField(max_length=150)
    sku = models.CharField(max_length=50)
    quantity = models.PositiveIntegerField()
    regular_unit_price = models.PositiveBigIntegerField()
    charged_unit_price = models.PositiveBigIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order", "sku"], name="order_sku_unique"),
            models.CheckConstraint(
                condition=Q(quantity__gt=0, charged_unit_price__lte=F("regular_unit_price")),
                name="order_item_valid_amounts",
            ),
        ]


class InventoryReservation(models.Model):
    class State(models.TextChoices):
        HELD = "held", "Held"
        CONSUMED = "consumed", "Consumed"
        RELEASED = "released", "Released"
        RESTOCKED = "restocked", "Restocked"

    item = models.OneToOneField(OrderItem, models.PROTECT, related_name="reservation")
    product = models.ForeignKey(Product, models.PROTECT)
    state = models.CharField(max_length=12, choices=State, default=State.HELD)
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=["expires_at"], condition=Q(state="held"), name="reservation_held_expiry")
        ]


class PaymentAttempt(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        VERIFIED = "verified", "Verified"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        REVIEW = "review", "Review"
        REFUNDED = "refunded", "Refunded"
        SIMULATED = "simulated", "Simulated"

    order = models.ForeignKey(Order, models.PROTECT, related_name="payments")
    provider = models.CharField(max_length=30)
    mode = models.CharField(max_length=12)
    merchant_reference = models.CharField(max_length=30, unique=True)
    provider_reference = models.CharField(max_length=100, null=True, blank=True)
    session_reference = models.CharField(max_length=255, blank=True)
    checkout_url = models.URLField(max_length=1000, blank=True)
    amount = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, default="BDT")
    state = models.CharField(max_length=16, choices=State, default=State.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["order"], condition=Q(state__in=["pending", "review"]), name="payment_inflight_per_order",
            ),
            models.UniqueConstraint(fields=["provider", "mode", "provider_reference"], name="payment_provider_ref_unique"),
        ]


class PaymentEvent(models.Model):
    attempt = models.ForeignKey(PaymentAttempt, models.PROTECT, related_name="events")
    fingerprint = models.CharField(max_length=64)
    outcome = models.CharField(max_length=40)
    provider_reference = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["attempt", "fingerprint"], name="payment_event_unique")
        ]


class OrderStatusEvent(models.Model):
    order = models.ForeignKey(Order, models.PROTECT, related_name="status_events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, models.SET_NULL, null=True)
    previous = models.CharField(max_length=16, blank=True)
    current = models.CharField(max_length=16)
    reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Notification(models.Model):
    class State(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENDING = "sending", "Sending"
        ACCEPTED = "accepted", "Accepted"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"
        UNKNOWN = "unknown", "Unknown"
        SUPPRESSED = "suppressed", "Suppressed"

    order = models.ForeignKey(Order, models.PROTECT, related_name="notifications")
    event_key = models.CharField(max_length=100)
    channel = models.CharField(max_length=12)
    recipient = models.CharField(max_length=254)
    template = models.CharField(max_length=50)
    state = models.CharField(max_length=12, choices=State, default=State.QUEUED)
    provider_reference = models.CharField(max_length=150, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField()
    lease_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event_key", "channel", "recipient"], name="notification_event_channel_unique")
        ]
        indexes = [
            models.Index(fields=["next_attempt_at"], condition=Q(state="queued"), name="notification_queue_due")
        ]


class RateBucket(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    hits = models.PositiveIntegerField()
    expires_at = models.DateTimeField(db_index=True)
