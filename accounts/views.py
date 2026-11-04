from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import (
    require_http_methods,
    require_POST,
    require_safe,
)

from shop.cart import merge_guest_cart
from shop.models import Address, Order

from .forms import AddressForm, LoginForm, ProfileForm, RegistrationForm
from .models import User


class CustomerLogin(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True
    http_method_names = ["get", "head", "post", "options"]

    def form_valid(self, form: AuthenticationForm) -> HttpResponse:
        response = super().form_valid(form)
        merge_guest_cart(self.request)
        return response


@require_http_methods(["GET", "HEAD", "POST"])
def register(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("account")
    form = RegistrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
        except IntegrityError:
            if not User.objects.filter(email__iexact=form.cleaned_data["email"]).exists():
                raise
            form.add_error("email", "An account already uses this email address.")
        else:
            login(request, user)
            merge_guest_cart(request)
            return redirect("account")
    return render(request, "accounts/form.html", {"form": form, "title": "Create account", "submit": "Create account"})


@never_cache
@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def account(request: HttpRequest) -> HttpResponse:
    assert isinstance(request.user, User)
    form = ProfileForm(request.POST if request.method == "POST" else None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile updated.")
        return redirect("account")
    return render(request, "accounts/account.html", {
        "form": form, "addresses": Address.objects.filter(user=request.user).select_related("zone"),
        "orders": Order.objects.filter(user=request.user)[:5],
    })


@never_cache
@login_required
@require_safe
def order_history(request: HttpRequest) -> HttpResponse:
    assert isinstance(request.user, User)
    orders = Order.objects.filter(user=request.user)
    page = Paginator(orders, 20).get_page(request.GET.get("page"))
    return render(request, "accounts/orders.html", {"page": page})


@never_cache
@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def edit_address(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    address = get_object_or_404(Address, pk=pk, user=request.user) if pk is not None else None
    form = AddressForm(request.POST if request.method == "POST" else None, instance=address)
    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        entry.user_id = request.user.pk
        entry.save()
        messages.success(request, "Address saved.")
        return redirect("account")
    return render(request, "accounts/form.html", {
        "form": form, "title": "Edit address" if address else "Add address", "submit": "Save address",
    })


@login_required
@require_POST
def delete_address(request: HttpRequest, pk: int) -> HttpResponse:
    get_object_or_404(Address, pk=pk, user=request.user).delete()
    messages.success(request, "Address removed.")
    return redirect("account")


@login_required
@require_safe
def staff_home(request: HttpRequest) -> HttpResponse:
    if not request.user.is_staff or not any(
        request.user.has_perm(permission)
        for permission in ("shop.view_order", "shop.view_product", "shop.view_storesettings")
    ):
        raise PermissionDenied
    return render(request, "accounts/staff.html")
