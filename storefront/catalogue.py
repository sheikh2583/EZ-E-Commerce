from django import forms
from django.core.files.storage import default_storage
from django.db.models import Case, F, IntegerField, QuerySet, Value, When
from django.db.models.functions import Coalesce
from django.templatetags.static import static

from shop.models import Category, Product, ProductImage

CATEGORY_ART = {"home", "kitchen", "desk", "travel", "bath", "garden"}


class CatalogueFilters(forms.Form):
    q = forms.CharField(label="Search", required=False, max_length=100)
    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(active=True), to_field_name="slug", required=False,
        empty_label="All categories",
    )
    min_price = forms.DecimalField(
        label="Min price (৳)", required=False, min_value=0, max_digits=12, decimal_places=2,
    )
    max_price = forms.DecimalField(
        label="Max price (৳)", required=False, min_value=0, max_digits=12, decimal_places=2,
    )
    sort = forms.ChoiceField(required=False, choices=[
        ("", "Recommended"), ("newest", "Newest"), ("price-asc", "Price, low to high"),
        ("price-desc", "Price, high to low"),
    ])

    def clean(self) -> dict:
        data = super().clean() or {}
        low, high = data.get("min_price"), data.get("max_price")
        if low is not None and high is not None and low > high:
            self.add_error("max_price", "Maximum price must be at least the minimum.")
        return data


def published_products() -> QuerySet[Product]:
    return (
        Product.objects.filter(active=True, category__active=True)
        .select_related("category").prefetch_related("images")
    )


def filtered_products(form: CatalogueFilters) -> QuerySet[Product]:
    products = published_products().annotate(effective_price=Coalesce("sale_price", "regular_price"))
    if not form.is_valid():
        return products.none()
    filters = form.cleaned_data
    query = filters["q"]
    if query:
        products = products.filter(name__icontains=query)
    if filters["category"] is not None:
        products = products.filter(category=filters["category"])
    if filters["min_price"] is not None:
        products = products.filter(effective_price__gte=int(filters["min_price"] * 100))
    if filters["max_price"] is not None:
        products = products.filter(effective_price__lte=int(filters["max_price"] * 100))
    if filters["sort"] == "price-asc":
        return products.order_by("effective_price", "pk")
    if filters["sort"] == "price-desc":
        return products.order_by("-effective_price", "pk")
    if query and filters["sort"] != "newest":
        return products.annotate(relevance=Case(
            When(name__iexact=query, then=Value(0)),
            When(name__istartswith=query, then=Value(1)),
            default=Value(2), output_field=IntegerField(),
        )).order_by("relevance", "name", "pk")
    return products.order_by(F("created_at").desc(), "-pk")


def category_image(category: Category) -> str:
    key = category.slug if category.slug in CATEGORY_ART else "home"
    return static(f"catalogue/{key}.svg")


def image_url(image: ProductImage) -> str:
    return default_storage.url(image.asset_id)


def product_images(product: Product) -> list[tuple[str, str]]:
    images = list(product.images.all())
    if images:
        return [(image_url(image), image.alt) for image in images]
    return [(category_image(product.category), "Illustration for the " + product.category.name + " collection")]
