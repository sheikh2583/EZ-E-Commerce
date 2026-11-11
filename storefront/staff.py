import uuid

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Max, Q, Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import (
    require_http_methods,
    require_POST,
    require_safe,
)

from accounts.models import User
from shop.fulfillment import FulfillmentError, choices, update_order
from shop.media import ImageError, delete_image, sanitized_image, store_image
from shop.models import Order, PaymentAttempt, Product, ProductImage, StoreSettings


def require_staff(request: HttpRequest, *permissions: str) -> None:
    if not request.user.is_staff or not request.user.has_perms(permissions):
        raise PermissionDenied


@never_cache
@login_required
@require_safe
def dashboard(request: HttpRequest) -> HttpResponse:
    require_staff(request)
    can_orders = request.user.has_perm("shop.view_order")
    can_products = request.user.has_perm("shop.view_product")
    can_settings = request.user.has_perm("shop.view_storesettings")
    if not any((can_orders, can_products, can_settings)):
        raise PermissionDenied
    context: dict[str, object] = {}
    if can_orders:
        orders = Order.objects.all()
        context["order_metrics"] = {
            "Total orders": orders.count(),
            "Pending orders": orders.filter(state=Order.State.PENDING).count(),
            "Completed orders": orders.filter(state=Order.State.DELIVERED).count(),
        }
        context["revenue"] = orders.filter(
            payment_state=Order.PaymentState.PAID, accepted_payment__mode="live",
            accepted_payment__state=PaymentAttempt.State.VERIFIED,
        ).aggregate(total=Sum("total"))["total"] or 0
        context["review_count"] = orders.filter(payment_review=True).count()
    if can_products:
        settings_row = StoreSettings.objects.first()
        threshold = settings_row.low_stock_threshold if settings_row else 5
        context["product_count"] = Product.objects.count()
        context["low_stock"] = Product.objects.filter(active=True, stock__lte=F("reserved") + threshold).order_by("stock", "pk")[:20]
    return render(request, "staff/dashboard.html", context)


@never_cache
@login_required
@require_safe
def orders(request: HttpRequest) -> HttpResponse:
    require_staff(request, "shop.view_order")
    results = Order.objects.all()
    query = request.GET.get("q", "").strip()[:120]
    state = request.GET.get("state", "")
    if query:
        by = Q(email__icontains=query) | Q(recipient__icontains=query) | Q(tracking_number__icontains=query)
        try:
            by |= Q(reference=uuid.UUID(query))
        except ValueError:
            pass
        results = results.filter(by)
    if state in Order.State.values:
        results = results.filter(state=state)
    if request.GET.get("review") == "1":
        results = results.filter(payment_review=True)
    page = Paginator(results, 25).get_page(request.GET.get("page"))
    return render(request, "staff/orders.html", {"page": page, "states": Order.State.choices, "q": query, "state": state})


class StatusForm(forms.Form):
    state = forms.ChoiceField(label="Order status")
    tracking_carrier = forms.CharField(required=False, max_length=120)
    tracking_number = forms.CharField(required=False, max_length=120)

    def __init__(self, order: Order, *args, **kwargs):
        super().__init__(*args, **kwargs)
        state = self.fields["state"]
        assert isinstance(state, forms.ChoiceField)
        state.choices = choices(order)
        self.initial.update(state=order.state, tracking_carrier=order.tracking_carrier, tracking_number=order.tracking_number)


@never_cache
@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def order_detail(request: HttpRequest, reference: uuid.UUID) -> HttpResponse:
    require_staff(request, "shop.view_order")
    order = get_object_or_404(
        Order.objects.prefetch_related("items", "payments__events", "payments__pap_payment", "status_events"),
        reference=reference,
    )
    can_change = request.user.has_perm("shop.change_order")
    if request.method == "POST" and not can_change:
        raise PermissionDenied
    form = StatusForm(order, request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        assert isinstance(request.user, User)
        try:
            update_order(order.pk, request.user.pk, **form.cleaned_data)
        except FulfillmentError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Order updated.")
            return redirect("staff_order", reference=reference)
    return render(request, "staff/order.html", {"order": order, "form": form if can_change else None})


class PhotoForm(forms.Form):
    photo = forms.FileField()
    alt = forms.CharField(label="Image description", max_length=180)

    def clean_photo(self) -> bytes:
        try:
            return sanitized_image(self.cleaned_data["photo"])
        except ImageError as error:
            raise forms.ValidationError(str(error)) from error


@never_cache
@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def images(request: HttpRequest, pk: int) -> HttpResponse:
    require_staff(request, "shop.view_product", "shop.add_productimage")
    product = get_object_or_404(Product, pk=pk)
    form = PhotoForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
    )
    if request.method == "POST" and form.is_valid():
        try:
            asset = store_image(form.cleaned_data["photo"])
        except ImageError as error:
            form.add_error("photo", str(error))
        else:
            try:
                with transaction.atomic():
                    product = Product.objects.select_for_update().get(pk=pk)
                    position = product.images.aggregate(last=Max("position"))["last"]
                    ProductImage.objects.create(
                        product=product, asset_id=asset, alt=form.cleaned_data["alt"],
                        position=0 if position is None else position + 1,
                    )
            except Exception:
                delete_image(asset)
                raise
            messages.success(request, "Photo uploaded.")
            return redirect("staff_images", pk=pk)
    return render(request, "staff/images.html", {"product": product, "form": form})


@login_required
@require_POST
def remove_image(request: HttpRequest, pk: int, photo_id: int) -> HttpResponse:
    require_staff(request, "shop.delete_productimage")
    with transaction.atomic():
        photo = get_object_or_404(ProductImage.objects.select_for_update(), pk=photo_id, product_id=pk)
        asset = photo.asset_id
        photo.delete()
        transaction.on_commit(lambda: delete_image(asset))
    messages.success(request, "Photo removed.")
    return redirect("staff_images", pk=pk)
