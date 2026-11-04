import re
from uuid import UUID

from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from shop.gateway import HOSTS, gateway
from shop.models import Order, PaymentAttempt
from shop.orders import visible_orders
from shop.payments import (
    PaymentError,
    apply_validation,
    attach_session,
    audit,
    begin,
    reconcile,
    simulate,
)
from shop.provider_http import ProviderError


@never_cache
@require_POST
def start(request: HttpRequest, reference: UUID) -> HttpResponse:
    order = get_object_or_404(Order.objects.filter(visible_orders(request)), reference=reference)
    if settings.PAYMENT_MODE not in {*HOSTS, "simulation"}:
        messages.error(request, "Online payments are currently unavailable.")
        return redirect("order", reference=reference)
    try:
        attempt, created = begin(order.pk)
        if attempt.mode == "simulation":
            simulate(attempt)
            return redirect("order", reference=reference)
    except PaymentError as error:
        messages.error(request, str(error))
        return redirect("order", reference=reference)
    if not created:
        if attempt.checkout_url:
            return redirect(attempt.checkout_url)
        messages.info(request, "Payment is awaiting verification.")
        return redirect("order", reference=reference)
    try:
        url, session = gateway().start(order, attempt)
    except ProviderError:
        audit(attempt, "session_unknown")
        messages.error(request, "Payment could not be started. The attempt is awaiting reconciliation.")
        return redirect("order", reference=reference)
    attach_session(attempt, url, session)
    return redirect(url)


def callback(request: HttpRequest, *, browser: bool) -> HttpResponse:
    if settings.PAYMENT_MODE not in HOSTS:
        return JsonResponse({"status": "unavailable"}, status=503)
    merchant = request.POST.get("tran_id", "")
    validation_id = request.POST.get("val_id", "")
    if not re.fullmatch(r"[a-f0-9]{30}", merchant) or (
        validation_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", validation_id)
    ):
        return JsonResponse({"status": "invalid"}, status=400)
    attempt = PaymentAttempt.objects.select_related("order").filter(
        merchant_reference=merchant, provider="sslcommerz", mode=settings.PAYMENT_MODE,
    ).first()
    if attempt is None:
        return JsonResponse({"status": "invalid"}, status=400)
    provider = gateway()
    try:
        outcome = (
            apply_validation(attempt, validation_id, provider.validate(validation_id))
            if validation_id else reconcile(provider, attempt)
        )
    except ProviderError:
        audit(attempt, "verification_unavailable")
        if not browser:
            return JsonResponse({"status": "unavailable"}, status=503)
        outcome = "pending"
    if browser:
        response = redirect("order", reference=attempt.order.reference)
        response.status_code = 303
        return response
    return JsonResponse({"status": outcome}, status=400 if outcome == "invalid" else 200)


@csrf_exempt
@never_cache
@require_POST
def ipn(request: HttpRequest) -> HttpResponse:
    return callback(request, browser=False)


@csrf_exempt
@never_cache
@require_POST
def payment_return(request: HttpRequest) -> HttpResponse:
    return callback(request, browser=True)
