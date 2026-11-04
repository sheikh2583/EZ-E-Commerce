from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from shop.models import Category, Product, ProductImage


class Catalogue(TestCase):
    @classmethod
    @override_settings(DEBUG=True)
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())

    def test_home_exposes_featured_recent_and_active_categories(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Everyday essentials")
        self.assertContains(response, "Featured finds")
        self.assertContains(response, "New arrivals")
        self.assertContains(response, "Shop by category")
        self.assertEqual(len(response.context["categories"]), 6)

    def test_filters_combine_and_sort_by_effective_price(self):
        response = self.client.get(reverse("catalogue"), {
            "q": "stoneware", "category": "kitchen", "min_price": "1050", "max_price": "1200",
            "sort": "price-desc",
        })
        self.assertEqual(response.status_code, 200)
        products = list(response.context["page"])
        self.assertGreaterEqual(len(products), 2)
        prices = [product.unit_price for product in products]
        self.assertEqual(prices, sorted(prices, reverse=True))
        self.assertTrue(all(105000 <= price <= 120000 for price in prices))
        self.assertTrue(all(p.category.slug == "kitchen" and "stoneware" in p.name.lower() for p in products))

    def test_invalid_filters_show_an_error_and_no_products(self):
        response = self.client.get(reverse("catalogue"), {"min_price": "10", "max_price": "5"})
        self.assertContains(response, "Maximum price must be at least the minimum")
        self.assertContains(response, "No products found")

    def test_pagination_has_stable_unique_pages_and_preserves_filters(self):
        first = self.client.get(reverse("catalogue"), {"category": "desk"})
        second = self.client.get(reverse("catalogue"), {"category": "desk", "page": "2"})
        first_ids = {product.pk for product in first.context["page"]}
        second_ids = {product.pk for product in second.context["page"]}
        self.assertEqual((len(first_ids), len(second_ids)), (12, 8))
        self.assertTrue(first_ids.isdisjoint(second_ids))
        self.assertContains(first, "category=desk&amp;page=2")

    def test_detail_renders_gallery_prices_and_availability(self):
        product = Product.objects.filter(stock=0).first()
        assert product is not None
        ProductImage.objects.create(product=product, asset_id="products/a.png", alt="Front view")
        ProductImage.objects.create(product=product, asset_id="products/b.png", alt="Back view", position=1)
        response = self.client.get(reverse("product", args=[product.slug]))
        self.assertContains(response, "Out of stock")
        self.assertContains(response, "Front view")
        self.assertContains(response, "Back view")
        self.assertContains(response, f"৳{product.unit_price // 100:,}")

    def test_inactive_products_or_categories_are_not_public(self):
        product = Product.objects.get(sku="DEMO-001")
        product.active = False
        product.save(update_fields=["active"])
        self.assertEqual(self.client.get(reverse("product", args=[product.slug])).status_code, 404)
        Category.objects.filter(pk=product.category_id).update(active=False)
        response = self.client.get(reverse("catalogue"))
        self.assertEqual(response.context["page"].paginator.count, 100)
