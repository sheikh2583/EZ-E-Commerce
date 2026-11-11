import re
from uuid import UUID

from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from shop import pap, pap_webhooks
from shop.gateway import HOSTS, gateway
from shop.models import Order, PapPayment, PapWebhookEvent, PaymentAttempt
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
    if attempt.provider == "pap":
        try:
            url = pap.start_checkout(attempt.pap_payment)
        except ProviderError:
            audit(attempt, "session_unknown")
            messages.error(request, "Payment could not be opened. Please try again shortly.")
        else:
            if url:
                return redirect(url)
            messages.info(request, "Payment is awaiting verification.")
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
    if settings.PAYMENT_MODE not in HOSTS or settings.PAYMENT_PROVIDER != "sslcommerz":
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


@csrf_exempt
@never_cache
@require_http_methods(["GET", "POST"])
def pap_return(request: HttpRequest, reference: UUID) -> HttpResponse:
    if request.method == "POST":
        # A cross-site POST may omit the session cookie. Resume with a top-level GET.
        return HttpResponse(status=303, headers={"Location": reverse("pap_return", args=[reference])})
    order = get_object_or_404(Order.objects.filter(visible_orders(request)), reference=reference)
    if pap.enabled():
        payment = PapPayment.objects.select_related("attempt__order").filter(
            attempt__order=order, attempt__mode=settings.PAYMENT_MODE, payment_id__isnull=False,
        ).first()
        if payment is not None:
            supplied_id = request.GET.get("payment_id")
            if supplied_id is not None and supplied_id != str(payment.payment_id):
                return JsonResponse({"status": "invalid"}, status=400)
            try:
                pap.reconcile(payment, refresh_checkout=True)
            except ProviderError:
                audit(payment.attempt, "verification_unavailable")
    response = redirect("order", reference=reference)
    response.status_code = 303
    return response


@csrf_exempt
@never_cache
@require_POST
def pap_webhook(request: HttpRequest) -> HttpResponse:
    if not pap.enabled():
        return JsonResponse({"status": "unavailable"}, status=503)
    verified = pap_webhooks.verify(request.body, request.headers)
    if verified is None:
        return JsonResponse({"status": "invalid"}, status=401)
    event_id, event = verified
    if event.get("type") == "webhook.endpoint_verification":
        data = event.get("data")
        challenge = data.get("challenge") if isinstance(data, dict) else None
        if not isinstance(challenge, str) or len(challenge) > 1024 or not challenge.isascii() or not challenge.isprintable():
            return JsonResponse({"status": "invalid"}, status=400)
        return HttpResponse(status=204, headers={"x-lct-webhook-challenge": challenge})
    PapWebhookEvent.objects.get_or_create(id=event_id, defaults={
        "mode": settings.PAYMENT_MODE, "merchant_id": settings.LCT_MERCHANT_ID, "payload": event,
    })
    return HttpResponse(status=204)
