from django import forms
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST, require_safe

from shop.cart import (
    MAX_QUANTITY,
    CartError,
    calculate_totals,
    cart_items,
    current_cart,
    set_quantity,
)


class AddQuantity(forms.Form):
    quantity = forms.IntegerField(min_value=1, max_value=MAX_QUANTITY)


class UpdateQuantity(forms.Form):
    quantity = forms.IntegerField(min_value=0, max_value=MAX_QUANTITY)


@require_safe
def detail(request: HttpRequest) -> HttpResponse:
    items = cart_items(current_cart(request))
    return render(request, "catalogue/cart.html", {"items": items, "totals": calculate_totals(items)})


@require_POST
def add(request: HttpRequest, product_id: int) -> HttpResponse:
    return change(request, product_id, add=True)


@require_POST
def update(request: HttpRequest, product_id: int) -> HttpResponse:
    return change(request, product_id, add=False)


def change(request: HttpRequest, product_id: int, *, add: bool) -> HttpResponse:
    form = (AddQuantity if add else UpdateQuantity)(request.POST)
    if not form.is_valid():
        messages.error(request, "Enter a valid whole-number quantity.")
    else:
        cart = current_cart(request, create=add)
        if cart is not None:
            try:
                set_quantity(cart, product_id, form.cleaned_data["quantity"], add=add)
            except CartError as error:
                messages.error(request, str(error))
            else:
                messages.success(request, "Cart updated.")
    return redirect("cart")
