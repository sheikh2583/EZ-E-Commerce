from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from threading import Barrier
from uuid import uuid4

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connections, transaction
from django.db.models import ProtectedError
from django.test import TestCase, TransactionTestCase, override_settings

from shop.inventory import reserve_stock
from shop.models import (
    Cart,
    CartItem,
    Category,
    Order,
    OrderItem,
    PaymentAttempt,
    Product,
)


class DatabaseModels(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Kitchen", slug="kitchen")
        self.product = Product.objects.create(
            category=self.category, name="Cup", slug="cup", sku="CUP", regular_price=80000, stock=2,
        )
        self.cart = Cart.objects.create(guest_digest="guest-one")
        self.order_fields = {
            "cart": self.cart, "checkout_key": uuid4(), "subtotal": 80000,
            "discount": 1000, "delivery": 8000, "total": 87000,
        }

    def test_constraints_are_enforced_in_postgresql(self):
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=1)
        order = Order.objects.create(**self.order_fields)
        PaymentAttempt.objects.create(order=order, merchant_reference="test1", amount=order.total)
        invalid = (
            lambda: Product.objects.filter(pk=self.product.pk).update(reserved=3),
            lambda: Product.objects.filter(pk=self.product.pk).update(sale_price=90000),
            lambda: Cart.objects.create(guest_digest="guest-one"),
            lambda: CartItem.objects.create(cart=self.cart, product=self.product, quantity=2),
            lambda: Order.objects.filter(pk=order.pk).update(total=1),
            lambda: Order.objects.filter(pk=order.pk).update(payment_state=Order.PaymentState.PAID),
            lambda: Order.objects.create(**self.order_fields),
            lambda: PaymentAttempt.objects.create(order=order, merchant_reference="test2", amount=order.total),
        )
        for operation in invalid:
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()

    def test_order_items_remain_after_product_edits_or_deletion(self):
        order = Order.objects.create(**self.order_fields)
        item = OrderItem.objects.create(
            order=order, product=self.product, name="Cup", sku="CUP", quantity=1,
            regular_unit_price=80000, charged_unit_price=79000,
        )
        with self.assertRaises(ProtectedError):
            order.delete()
        self.product.delete()
        item.refresh_from_db()
        self.assertIsNone(item.product_id)
        self.assertEqual((item.name, item.charged_unit_price), ("Cup", 79000))

    def test_rollback_restores_stock_and_order_state(self):
        with self.assertRaisesRegex(ValueError, "abort"), transaction.atomic():
            self.assertTrue(reserve_stock(self.product.pk, 2))
            Order.objects.create(**self.order_fields)
            raise ValueError("abort")
        self.product.refresh_from_db()
        self.assertEqual(self.product.available, 2)
        self.assertFalse(Order.objects.exists())

    @override_settings(DEBUG=True)
    def test_seed_is_repeatable_and_preserves_existing_changes(self):
        call_command("seed_demo", stdout=StringIO())
        Product.objects.filter(sku="DEMO-001").update(name="Updated manually")
        call_command("seed_demo", stdout=StringIO())
        fixtures = Product.objects.filter(sku__startswith="DEMO-")
        self.assertEqual(fixtures.count(), 120)
        self.assertEqual(fixtures.get(sku="DEMO-001").name, "Updated manually")

    @override_settings(DEBUG=False)
    def test_seed_is_disabled_outside_debug(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())


class HostedDemoSeed(TestCase):
    @override_settings(DEBUG=False, PAYMENT_MODE="sandbox")
    def test_seed_requires_explicit_sandbox_flag(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())
        call_command("seed_demo", allow_hosted_demo=True, stdout=StringIO())
        self.assertEqual(Product.objects.count(), 120)

    @override_settings(DEBUG=False, PAYMENT_MODE="disabled", DEMO_CATALOGUE=False)
    def test_disabled_payments_require_hosted_demo_marker(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", allow_hosted_demo=True, stdout=StringIO())
        with override_settings(DEMO_CATALOGUE=True):
            call_command("seed_demo", allow_hosted_demo=True, stdout=StringIO())
        self.assertEqual(Product.objects.count(), 120)

    @override_settings(DEBUG=False, PAYMENT_MODE="live", DEMO_CATALOGUE=True)
    def test_seed_cannot_run_in_live_mode(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", allow_hosted_demo=True, stdout=StringIO())


class InventoryConcurrency(TransactionTestCase):
    def test_only_one_connection_can_claim_the_last_unit(self):
        category = Category.objects.create(name="Desk", slug="desk")
        product = Product.objects.create(
            category=category, name="Tray", slug="tray", sku="TRAY", regular_price=100, stock=1,
        )
        start = Barrier(2, timeout=5)

        def attempt() -> bool:
            try:
                start.wait()
                with transaction.atomic():
                    return reserve_stock(product.pk, 1)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(attempt)
            second = executor.submit(attempt)
            self.assertEqual(sorted([first.result(timeout=10), second.result(timeout=10)]), [False, True])
        product.refresh_from_db()
        self.assertEqual((product.stock, product.reserved, product.available), (1, 1, 0))
