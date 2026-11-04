from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from shop.models import Cart, CartItem, Category, Product


class CartFlows(TestCase):
    product: Product

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Kitchen", slug="kitchen")
        cls.product = Product.objects.create(
            category=category, name="Cup", slug="cup", sku="CUP", regular_price=100000, sale_price=75000, stock=4,
        )

    def test_guest_add_update_remove_and_totals_persist(self):
        add = reverse("cart_add", args=[self.product.pk])
        update = reverse("cart_update", args=[self.product.pk])
        self.assertRedirects(self.client.post(add, {"quantity": "2", "price": "1"}), reverse("cart"))
        self.assertRedirects(self.client.post(add, {"quantity": "1"}), reverse("cart"))
        self.assertContains(self.client.get(reverse("cart")), "৳3,000")
        totals = self.client.get(reverse("cart")).context["totals"]
        self.assertEqual((totals.subtotal, totals.discount, totals.merchandise), (300000, 75000, 225000))
        self.assertContains(self.client.get(reverse("home")), '<span>3</span>')
        self.assertContains(Client().get(reverse("cart")), "Your cart is empty")
        self.client.post(update, {"quantity": "1"})
        self.assertEqual(CartItem.objects.get().quantity, 1)
        self.client.post(update, {"quantity": "0"})
        self.assertFalse(CartItem.objects.exists())
        self.assertContains(self.client.get(reverse("cart")), "Your cart is empty")

    def test_invalid_and_unavailable_quantities_do_not_mutate(self):
        add = reverse("cart_add", args=[self.product.pk])
        for quantity in ("0", "-1", "1.5", "5", "99999999999"):
            self.client.post(add, {"quantity": quantity})
        self.assertFalse(CartItem.objects.exists())
        self.client.post(add, {"quantity": "4"})
        self.client.post(add, {"quantity": "1"})
        self.assertEqual(CartItem.objects.get().quantity, 4)
        self.assertEqual(self.client.get(add).status_code, 405)
        self.product.active = False
        self.product.save(update_fields=["active"])
        self.assertContains(self.client.get(reverse("cart")), "Current availability has changed")

    def test_login_merges_guest_and_account_cart_once_at_stock_limit(self):
        user = User.objects.create_user("buyer@example.test", "Long-unique-test-password")
        saved = Cart.objects.create(user=user)
        CartItem.objects.create(cart=saved, product=self.product, quantity=3)
        self.client.post(reverse("cart_add", args=[self.product.pk]), {"quantity": "2"})
        guest = Cart.objects.get(user__isnull=True)
        self.client.post(reverse("login"), {"username": user.email, "password": "Long-unique-test-password"})
        guest.refresh_from_db()
        self.assertEqual(guest.state, Cart.State.CLOSED)
        self.assertEqual(CartItem.objects.get(cart=saved).quantity, 4)
        self.assertNotIn("guest_cart", self.client.session)
        self.client.post(reverse("logout"))
        self.assertContains(self.client.get(reverse("cart")), "Your cart is empty")
        self.client.post(reverse("login"), {"username": user.email, "password": "Long-unique-test-password"})
        self.assertContains(self.client.get(reverse("cart")), "৳3,000")
        self.assertEqual(Cart.objects.filter(user=user).count(), 1)

    def test_cart_mutations_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse("cart_add", args=[self.product.pk]), {"quantity": "1"}).status_code, 403)
        self.assertFalse(Cart.objects.exists())
