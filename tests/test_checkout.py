from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from shop.models import Category, DeliveryZone, InventoryReservation, Order, Product

CUSTOMER = {
    "recipient": "Test Shopper", "email": "shopper@example.test", "phone": "01700000000",
    "address_line": "Test address", "locality": "Dhaka", "notes": "Test notes",
}


def fixtures() -> tuple[Product, DeliveryZone]:
    category = Category.objects.create(name="Home", slug="home")
    product = Product.objects.create(
        category=category, name="Basket", slug="basket", sku="BASKET",
        regular_price=100000, sale_price=90000, stock=1,
    )
    zone = DeliveryZone.objects.create(name="Central", code="central", fee=8000)
    return product, zone


def review(client: Client, product: Product, zone: DeliveryZone):
    client.post(reverse("cart_add", args=[product.pk]), {"quantity": "1"})
    return client.post(reverse("checkout"), {**CUSTOMER, "zone": str(zone.pk), "total": "1"})


class Checkout(TestCase):
    def setUp(self):
        self.product, self.zone = fixtures()

    def test_guest_order_replay_privacy_price_snapshots_and_release(self):
        confirmation = review(self.client, self.product, self.zone)
        self.assertContains(confirmation, "৳980")
        token = confirmation.context["token"]
        created = self.client.post(reverse("order_submit"), {"quote": token, "total": "1"})
        order = Order.objects.get()
        location = reverse("order", args=[order.reference])
        self.assertRedirects(created, location)
        self.assertRedirects(self.client.post(reverse("order_submit"), {"quote": token}), location)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual((order.total, order.discount, order.phone), (98000, 10000, "+8801700000000"))
        self.assertEqual(Client().get(location).status_code, 404)
        self.assertEqual(Client().post(reverse("order_submit"), {"quote": token})["Location"], reverse("checkout"))
        self.zone.fee = 15000
        self.zone.save()
        Product.objects.filter(pk=self.product.pk).update(regular_price=150000, sale_price=None)
        order.refresh_from_db()
        self.assertEqual((order.delivery, order.items.get().charged_unit_price), (8000, 90000))
        self.product.refresh_from_db()
        self.assertEqual(self.product.available, 0)
        InventoryReservation.objects.update(expires_at=timezone.now())
        from shop.orders import expire_unpaid
        self.assertTrue(expire_unpaid(order.pk))
        self.assertFalse(expire_unpaid(order.pk))
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual((order.state, self.product.available), (Order.State.CANCELLED, 1))

    def test_account_order_is_listed_and_other_users_cannot_read_it(self):
        customer = User.objects.create_user("buyer@example.test")
        other = User.objects.create_user("other@example.test")
        self.client.force_login(customer)
        token = review(self.client, self.product, self.zone).context["token"]
        self.client.post(reverse("order_submit"), {"quote": token})
        order = Order.objects.get(user=customer)
        location = reverse("order", args=[order.reference])
        self.assertContains(self.client.get(reverse("account")), location)
        self.assertContains(self.client.get(reverse("order_history")), location)
        self.client.force_login(other)
        self.assertEqual(self.client.get(location).status_code, 404)

    def test_changed_price_and_tampered_quote_require_a_new_review(self):
        token = review(self.client, self.product, self.zone).context["token"]
        response = self.client.post(reverse("order_submit"), {"quote": token + "modified"}, follow=True)
        self.assertContains(response, "expired or is invalid")
        Product.objects.filter(pk=self.product.pk).update(sale_price=85000)
        response = self.client.post(reverse("order_submit"), {"quote": token}, follow=True)
        self.assertContains(response, "Prices or delivery charges changed")
        self.assertFalse(Order.objects.exists())


class ConcurrentCheckout(TransactionTestCase):
    def test_two_carts_cannot_purchase_the_last_unit(self):
        product, zone = fixtures()
        clients = (Client(), Client())
        tokens = [review(client, product, zone).context["token"] for client in clients]
        barrier = Barrier(2, timeout=5)

        def place(client: Client, token: str) -> str:
            try:
                barrier.wait()
                response = client.post(reverse("order_submit"), {"quote": token})
                self.assertEqual(response.status_code, 302)
                return response["Location"]
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first, second = [executor.submit(place, client, token) for client, token in zip(clients, tokens, strict=True)]
            results = [first.result(timeout=10), second.result(timeout=10)]
        self.assertEqual(Order.objects.count(), 1)
        self.assertCountEqual(results, [reverse("checkout"), reverse("order", args=[Order.objects.get().reference])])
        product.refresh_from_db()
        self.assertEqual((product.stock, product.reserved, product.available), (1, 1, 0))
