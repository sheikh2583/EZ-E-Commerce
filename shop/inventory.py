from django.db.models import F

from .models import Product


def reserve_stock(product_id: int, quantity: int) -> bool:
    if quantity < 1:
        raise ValueError("Stock reservation quantity must be positive.")
    return bool(
        Product.objects.filter(pk=product_id, active=True, stock__gte=F("reserved") + quantity)
        .update(reserved=F("reserved") + quantity)
    )
