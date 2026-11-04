import logging

from django.core.paginator import Paginator
from django.db import DatabaseError, connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_safe

from shop.models import Category, StoreSettings

from .catalogue import (
    CatalogueFilters,
    filtered_products,
    product_images,
    published_products,
)

logger = logging.getLogger(__name__)


@require_safe
def home(request: HttpRequest) -> HttpResponse:
    products = published_products().order_by("-created_at", "-pk")
    return render(request, "home.html", {
        "store": StoreSettings.objects.first(),
        "categories": Category.objects.filter(active=True),
        "featured": products.filter(featured=True)[:4],
        "recent": products[:4],
    })


@require_safe
def catalogue(request: HttpRequest) -> HttpResponse:
    form = CatalogueFilters(request.GET)
    page = Paginator(filtered_products(form), 12).get_page(request.GET.get("page"))
    return render(request, "catalogue/list.html", {
        "form": form, "page": page, "store": StoreSettings.objects.first(),
    })


@require_safe
def product_detail(request: HttpRequest, slug: str) -> HttpResponse:
    product = get_object_or_404(published_products(), slug=slug)
    related = published_products().filter(category=product.category).exclude(pk=product.pk)
    return render(request, "catalogue/detail.html", {
        "product": product, "images": product_images(product),
        "related": related.order_by("-featured", "name", "pk")[:4],
        "store": StoreSettings.objects.first(),
    })


@require_safe
def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@require_safe
def readiness(request: HttpRequest) -> JsonResponse:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        logger.warning("Database readiness check failed")
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ready"})
