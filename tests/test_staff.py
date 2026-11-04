from io import BytesIO, StringIO
from tempfile import TemporaryDirectory

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import User
from shop.models import (
    Category,
    DeliveryZone,
    Order,
    PaymentAttempt,
    Product,
    ProductImage,
    StoreSettings,
)

from .test_checkout import fixtures, review


class Staff(TestCase):
    def setUp(self):
        call_command("setup_roles", stdout=StringIO())
        self.admin = User.objects.create_superuser("admin@example.test")
        self.product, self.zone = fixtures()

    def test_catalogue_and_zone_forms_persist_minor_units_and_protect_history(self):
        self.client.force_login(self.admin)
        category_add = reverse("admin:shop_category_add")
        self.assertEqual(self.client.post(category_add, {
            "name": "Travel", "slug": "travel", "active": "on", "position": "2",
        }).status_code, 302)
        category = Category.objects.get(slug="travel")
        product_data = {
            "name": "Travel bag", "slug": "travel-bag", "sku": "TRAVEL-01", "description": "Canvas",
            "category": str(category.pk), "regular_price": "1299.50", "sale_price": "1099.25",
            "stock": "7", "active": "on", "featured": "on",
        }
        self.assertEqual(self.client.post(reverse("admin:shop_product_add"), product_data).status_code, 302)
        product = Product.objects.get(sku="TRAVEL-01")
        self.assertEqual((product.regular_price, product.sale_price, product.stock), (129950, 109925, 7))
        Product.objects.filter(pk=product.pk).update(reserved=3)
        change = reverse("admin:shop_product_change", args=[product.pk])
        self.assertContains(self.client.post(change, {**product_data, "stock": "1"}), "quantity currently reserved")
        self.assertEqual(self.client.post(change, {**product_data, "stock": "6", "active": ""}).status_code, 302)
        product.refresh_from_db()
        self.assertEqual((product.stock, product.reserved, product.active), (6, 3, False))
        self.assertEqual(self.client.post(reverse("admin:shop_product_delete", args=[product.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("admin:shop_deliveryzone_add"), {
            "name": "Regional", "code": "regional", "fee": "120.50", "active": "on",
        }).status_code, 302)
        zone = DeliveryZone.objects.get(code="regional")
        self.assertEqual(zone.fee, 12050)
        self.assertEqual(self.client.post(reverse("admin:shop_deliveryzone_change", args=[zone.pk]), {
            "name": "Regional", "code": "regional", "fee": "150", "active": "",
        }).status_code, 302)
        zone.refresh_from_db()
        self.assertEqual((zone.fee, zone.active), (15000, False))

    def test_store_settings_and_role_boundaries(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse("admin:shop_storesettings_add"), {
            "display_name": "Example Store", "contact_email": "store@example.test",
            "banner_title": "New collection", "low_stock_threshold": "4",
        }).status_code, 302)
        self.assertEqual(StoreSettings.objects.get().display_name, "Example Store")
        self.assertContains(self.client.get(reverse("home")), "New collection")
        staff = User.objects.create_user("catalogue@example.test", is_staff=True)
        staff.groups.add(Group.objects.get(name="Catalogue"))
        self.client.force_login(staff)
        self.assertContains(self.client.get(reverse("staff")), "Inventory")
        self.assertEqual(self.client.get(reverse("staff_orders")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:shop_deliveryzone_add")).status_code, 403)

    def test_upload_reencodes_file_and_requires_permissions(self):
        path = reverse("staff_images", args=[self.product.pk])
        self.client.force_login(User.objects.create_user("customer@example.test"))
        self.assertEqual(self.client.post(path, {}).status_code, 403)
        self.client.force_login(self.admin)
        invalid = SimpleUploadedFile("unsafe.svg", b"<svg/>", content_type="image/svg+xml")
        self.assertContains(self.client.post(path, {"photo": invalid, "alt": "Bad"}), "Upload a valid")
        output = BytesIO()
        Image.new("RGB", (8, 8), "green").save(output, "PNG")
        with TemporaryDirectory() as media, override_settings(DEBUG=True, MEDIA_ROOT=media):
            upload = SimpleUploadedFile("basket.png", output.getvalue(), content_type="image/png")
            self.assertEqual(self.client.post(path, {"photo": upload, "alt": "Basket side"}).status_code, 302)
            image = ProductImage.objects.get()
            self.assertTrue(image.asset_id.endswith(".jpg"))
            self.assertContains(self.client.get(reverse("product", args=[self.product.slug])), "Basket side")
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(reverse("staff_remove_image", args=[self.product.pk, image.pk]))
            self.assertEqual(response.status_code, 302)
            self.assertFalse(ProductImage.objects.exists())

    def test_staff_fulfillment_permissions_transitions_and_revenue(self):
        token = review(self.client, self.product, self.zone).context["token"]
        self.client.post(reverse("order_submit"), {"quote": token})
        order = Order.objects.get()
        path = reverse("staff_order", args=[order.reference])
        customer = User.objects.create_user("customer@example.test")
        self.client.force_login(customer)
        self.assertEqual(self.client.post(path, {"state": "cancelled"}).status_code, 403)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("staff_orders"), {"q": order.recipient}), order.recipient)
        self.assertContains(self.client.post(path, {"state": "confirmed"}), "Select a valid choice")
        attempt = PaymentAttempt.objects.create(
            order=order, amount=order.total, merchant_reference="verified-fixture",
            mode="live", state=PaymentAttempt.State.VERIFIED,
        )
        order.accepted_payment = attempt
        order.payment_state = Order.PaymentState.PAID
        order.save()
        self.assertEqual(self.client.post(path, {
            "state": "confirmed", "tracking_carrier": "Courier", "tracking_number": "TEST123",
        }).status_code, 302)
        order.refresh_from_db()
        self.assertEqual((order.state, order.tracking_number), (Order.State.CONFIRMED, "TEST123"))
        self.assertContains(self.client.get(reverse("staff")), "৳980")
        self.assertContains(self.client.get(path), "verified-fixture")

    def test_staff_can_cancel_unpaid_order_and_release_reservation(self):
        token = review(self.client, self.product, self.zone).context["token"]
        self.client.post(reverse("order_submit"), {"quote": token})
        order = Order.objects.get()
        self.client.force_login(self.admin)
        path = reverse("staff_order", args=[order.reference])
        self.assertEqual(self.client.post(path, {"state": "cancelled"}).status_code, 302)
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual((order.state, self.product.available), (Order.State.CANCELLED, 1))
