import re
from typing import ClassVar
from uuid import UUID

from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.signing import BadSignature
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import (
    require_http_methods,
    require_POST,
    require_safe,
)

from shop.cart import calculate_totals, cart_items, current_cart
from shop.guest_access import read_token
from shop.models import Address, DeliveryZone, Order, PaymentAttempt
from shop.orders import (
    CheckoutError,
    get_quote,
    place_order,
    record_guest_order,
    sign_quote,
    visible_orders,
)

from .templatetags.store_format import bdt


class ZoneChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj: DeliveryZone) -> str:
        return f"{obj.name} ({bdt(obj.fee)})"


class CheckoutForm(forms.Form):
    recipient = forms.CharField(label="Full name", max_length=120, widget=forms.TextInput(attrs={"autocomplete": "name"}))
    email = forms.EmailField(max_length=254, widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    phone = forms.CharField(
        max_length=25, help_text="Enter a Bangladeshi mobile number.",
        widget=forms.TextInput(attrs={"type": "tel", "autocomplete": "tel"}),
    )
    address_line = forms.CharField(label="Street address", max_length=250, widget=forms.TextInput(attrs={"autocomplete": "street-address"}))
    locality = forms.CharField(label="City or locality", max_length=100, widget=forms.TextInput(attrs={"autocomplete": "address-level2"}))
    postcode = forms.CharField(max_length=12, required=False, widget=forms.TextInput(attrs={"autocomplete": "postal-code"}))
    zone = ZoneChoice(label="Delivery zone", queryset=DeliveryZone.objects.filter(active=True), empty_label="Select a zone")
    notes = forms.CharField(label="Order notes", required=False, max_length=500, widget=forms.Textarea(attrs={"rows": 3}))
    customer_fields: ClassVar = ("recipient", "email", "phone", "address_line", "locality", "postcode", "notes")

    def clean_phone(self) -> str:
        phone = re.sub(r"[\s()-]", "", self.cleaned_data["phone"])
        if not re.fullmatch(r"(?:\+?88)?01[3-9]\d{8}", phone, flags=re.ASCII):
            raise forms.ValidationError("Enter a valid Bangladeshi mobile number.")
        return "+88" + phone[-11:]

    def customer_data(self) -> dict[str, str]:
        return {field: self.cleaned_data[field] for field in self.customer_fields}


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def checkout(request: HttpRequest) -> HttpResponse:
    cart = current_cart(request)
    items = cart_items(cart)
    if cart is None or not items:
        return redirect("cart")

    addresses = Address.objects.none()
    initial: dict[str, str | int | None] = {}
    if request.user.is_authenticated:
        initial = {"recipient": request.user.get_full_name(), "email": request.user.email}
        addresses = Address.objects.filter(user=request.user).select_related("zone")
        selected = request.GET.get("address", "")
        if selected.isascii() and selected.isdigit() and len(selected) < 19:
            address = addresses.filter(pk=int(selected)).first()
            if address is not None:
                initial.update(recipient=address.recipient, phone=address.phone, address_line=address.line,
                               locality=address.locality, postcode=address.postcode, zone=address.zone_id)

    form = CheckoutForm(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST" and form.is_valid():
        customer = form.customer_data()
        try:
            quote = get_quote(cart.pk, form.cleaned_data["zone"].pk)
        except CheckoutError as error:
            form.add_error(None, str(error))
        else:
            return render(request, "catalogue/checkout_review.html", {
                "quote": quote, "customer": customer, "token": sign_quote(quote, customer),
            })
    return render(request, "catalogue/checkout.html", {
        "form": form, "addresses": addresses, "totals": calculate_totals(items),
    })


@never_cache
@require_POST
def submit(request: HttpRequest) -> HttpResponse:
    try:
        order = place_order(request, request.POST.get("quote", ""))
    except CheckoutError as error:
        messages.error(request, str(error))
        return redirect("checkout")
    record_guest_order(request, order)
    return redirect("order", reference=order.reference)


@never_cache
@require_safe
def order_detail(request: HttpRequest, reference: UUID) -> HttpResponse:
    order = get_object_or_404(
        Order.objects.filter(visible_orders(request)).prefetch_related("items", "status_events"),
        reference=reference,
    )
    return render(request, "catalogue/order.html", {
        "order": order,
        "payment_mode": settings.PAYMENT_MODE,
        "sandbox_paid": bool(order.accepted_payment and order.accepted_payment.mode == "sandbox"),
        "simulated": order.payments.filter(state=PaymentAttempt.State.SIMULATED).exists(),
    })


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def guest_order_access(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return render(request, "catalogue/guest_access.html")
    token = request.POST.get("token", "")
    if len(token) > 512:
        raise Http404
    try:
        reference = read_token(token)
    except BadSignature:
        raise Http404 from None
    order = get_object_or_404(Order, reference=reference, user__isnull=True)
    record_guest_order(request, order)
    return redirect("order", reference=reference)
