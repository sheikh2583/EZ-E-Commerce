from decimal import Decimal
from typing import ClassVar

from django import forms
from django.contrib import admin
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from storefront.templatetags.store_format import bdt

from .models import Category, DeliveryZone, Product, StoreSettings


class ProductForm(forms.ModelForm):
    regular_price = forms.DecimalField(label="Regular price (৳)", min_value=Decimal("0.01"), max_digits=10, decimal_places=2)
    sale_price = forms.DecimalField(label="Sale price (৳)", min_value=Decimal("0.01"), max_digits=10, decimal_places=2, required=False)

    class Meta:
        model = Product
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ("regular_price", "sale_price"):
            value = self.initial.get(field)
            if value is not None:
                self.initial[field] = Decimal(value) / 100

    def clean_regular_price(self) -> int:
        return int(self.cleaned_data["regular_price"] * 100)

    def clean_sale_price(self) -> int | None:
        price = self.cleaned_data["sale_price"]
        return int(price * 100) if price is not None else None

    def clean_stock(self) -> int:
        stock = self.cleaned_data["stock"]
        if stock < self.instance.reserved:
            raise forms.ValidationError("Stock cannot be lower than the quantity currently reserved.")
        return stock


class ZoneForm(forms.ModelForm):
    fee = forms.DecimalField(label="Delivery fee (৳)", min_value=0, max_digits=10, decimal_places=2)

    class Meta:
        model = DeliveryZone
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "fee" in self.initial:
            self.initial["fee"] = Decimal(self.initial["fee"]) / 100

    def clean_fee(self) -> int:
        return int(self.cleaned_data["fee"] * 100)


class PreserveHistory(admin.ModelAdmin):
    def has_delete_permission(self, request: HttpRequest, obj=None) -> bool:
        return False


@admin.register(Category)
class CategoryAdmin(PreserveHistory):
    list_display = ("name", "active", "position")
    list_filter = ("active",)
    search_fields = ("name", "slug")
    prepopulated_fields: ClassVar = {"slug": ("name",)}


@admin.register(Product)
class ProductAdmin(PreserveHistory):
    form = ProductForm
    list_display = ("name", "sku", "category", "price_display", "stock", "reserved", "active", "featured")
    list_filter = ("active", "featured", "category")
    list_select_related = ("category",)
    search_fields = ("name", "sku")
    prepopulated_fields: ClassVar = {"slug": ("name",)}
    fields = ("name", "slug", "sku", "category", "description", "regular_price", "sale_price",
              "stock", "reserved", "active", "featured", "images_link")
    readonly_fields = ("reserved", "images_link")

    def get_object(self, request: HttpRequest, object_id: str, from_field: str | None = None):
        product = super().get_object(request, object_id, from_field)
        if product is not None and request.method == "POST":
            return Product.objects.select_for_update().filter(pk=product.pk).first()
        return product

    @admin.display(description="Price")
    def price_display(self, obj: Product) -> str:
        return bdt(obj.unit_price)

    @admin.display(description="Product photos")
    def images_link(self, obj: Product) -> str:
        if not obj.pk:
            return "Save the product to upload photos."
        return format_html('<a href="{}">Manage photos</a>', reverse("staff_images", args=[obj.pk]))


@admin.register(DeliveryZone)
class DeliveryZoneAdmin(PreserveHistory):
    form = ZoneForm
    list_display = ("name", "code", "display_fee", "active")
    list_filter = ("active",)
    prepopulated_fields: ClassVar = {"code": ("name",)}

    @admin.display(description="Fee")
    def display_fee(self, zone: DeliveryZone) -> str:
        return bdt(zone.fee)


@admin.register(StoreSettings)
class StoreSettingsAdmin(PreserveHistory):
    list_display = ("display_name", "contact_email", "contact_phone", "low_stock_threshold")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return super().has_add_permission(request) and not StoreSettings.objects.exists()
