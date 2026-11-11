import json
import logging
from urllib.parse import urlsplit
from urllib.request import Request
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction

from .models import Order, PapPayment, PaymentAttempt
from .payments import accept_capture, apply_failure, audit, flag_review
from .provider_http import ProviderError, request_json

API_BASES = {
    "sandbox": "https://sandbox-pap.ezassist.me/v1",
    "live": "https://pap.ezassist.me/v1",
}
CHECKOUT_HOSTS = {"stripe": "checkout.stripe.com", "sslcommerz": "sandbox.sslcommerz.com"}
CHECKOUT_PATHS = {"stripe": "checkout", "sslcommerz": "sslcommerz-checkout"}
READY_STATES = {"stripe": "ready", "sslcommerz": "open"}
logger = logging.getLogger(__name__)


def enabled() -> bool:
    return settings.PAYMENT_PROVIDER == "pap" and settings.PAYMENT_MODE in API_BASES


def payment_uuid(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = UUID(value)
    except ValueError:
        return None
    return parsed if str(parsed) == value else None


def request(path: str, *, body: dict | None = None, key: UUID | None = None, method: str = "GET") -> dict:
    headers = {"Authorization": f"Bearer {settings.LCT_API_KEY}", "Accept": "application/json"}
    if key is not None:
        headers["Idempotency-Key"] = str(key)
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    try:
        return request_json(Request(API_BASES[settings.PAYMENT_MODE] + path, data=data, headers=headers, method=method))
    except ProviderError as error:
        if error.request_id and error.status != 404:
            logger.warning("PAP request failed with HTTP %s (request %s)", error.status, error.request_id)
        raise


def matches_payment(attempt: PaymentAttempt, result: dict) -> bool:
    return (
        result.get("orderReference") == str(attempt.order.reference)
        and type(result.get("amountMinor")) is int
        and result["amountMinor"] == attempt.amount
        and result.get("currency") == attempt.currency
    )


def ensure_payment(payment: PapPayment) -> UUID:
    if payment.payment_id is not None:
        return payment.payment_id
    attempt = payment.attempt
    result = request("/payments", method="POST", key=payment.payment_key, body={
        "capabilityGrantId": str(payment.grant_id),
        "orderReference": str(attempt.order.reference),
        "amountMinor": attempt.amount,
        "currency": attempt.currency,
    })
    payment_id = payment_uuid(result.get("id"))
    if payment_id is None or not matches_payment(attempt, result):
        raise ProviderError()
    try:
        with transaction.atomic():
            saved = PapPayment.objects.filter(pk=payment.pk, payment_id__isnull=True).update(payment_id=payment_id)
    except IntegrityError:
        raise ProviderError() from None
    if not saved:
        payment.refresh_from_db(fields=["payment_id"])
        if payment.payment_id != payment_id:
            raise ProviderError()
    payment.payment_id = payment_id
    return payment_id


def checkout_path(payment: PapPayment, payment_id: UUID) -> str:
    return f"/payments/{payment_id}/{CHECKOUT_PATHS[payment.checkout_provider]}"


def get_checkout(path: str) -> dict | None:
    try:
        return request(path)
    except ProviderError as error:
        if error.status != 404:
            raise
        return None


def hosted_url(payment: PapPayment, payment_id: UUID, result: dict) -> str | None:
    if result.get("paymentId") != str(payment_id):
        raise ProviderError()
    if result.get("state") != READY_STATES[payment.checkout_provider]:
        return None
    url = result.get("checkoutUrl")
    if not isinstance(url, str) or len(url) > 4096 or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise ProviderError()
    try:
        parsed = urlsplit(url)
    except ValueError:
        raise ProviderError() from None
    if parsed.scheme != "https" or parsed.netloc != CHECKOUT_HOSTS[payment.checkout_provider] or not parsed.path:
        raise ProviderError()
    return url


def start_checkout(payment: PapPayment) -> str | None:
    payment_id = ensure_payment(payment)
    path = checkout_path(payment, payment_id)
    result = get_checkout(path) if payment.checkout_requested else None
    if result is None:
        PapPayment.objects.filter(pk=payment.pk).update(checkout_requested=True)
        body = {"returnUrl": payment.return_url} if payment.checkout_provider == "sslcommerz" else {
            "successUrl": payment.return_url, "cancelUrl": payment.return_url,
        }
        result = request(path, method="POST", body=body, key=payment.checkout_key)
    url = hosted_url(payment, payment_id, result)
    if url:
        audit(payment.attempt, "hosted_session_created")
    return url


@transaction.atomic
def apply_status(attempt: PaymentAttempt, payment_id: UUID, result: dict) -> str:
    order = Order.objects.select_for_update().get(pk=attempt.order_id)
    attempt = PaymentAttempt.objects.select_for_update().get(pk=attempt.pk)
    attempt.order = order
    reference = str(payment_id)
    if result.get("id") != reference:
        raise ProviderError()
    status = result.get("status")
    if not matches_payment(attempt, result):
        if status == "succeeded":
            flag_review(order, attempt, "pap_payment_mismatch", reference)
            return "review"
        raise ProviderError()
    if status == "succeeded":
        return accept_capture(order, attempt, reference)
    if status in ("failed", "expired"):
        return apply_failure(attempt, cancelled=status == "expired")
    if not isinstance(status, str) or not status:
        raise ProviderError()
    return "pending"


def reconcile(payment: PapPayment, *, refresh_checkout: bool = False) -> str:
    payment_id = ensure_payment(payment)
    path = f"/payments/{payment_id}"
    result = request(path)
    outcome = apply_status(payment.attempt, payment_id, result)
    if outcome != "pending" or not refresh_checkout or not payment.checkout_requested:
        return outcome

    session_path = checkout_path(payment, payment_id)
    session = get_checkout(session_path)
    if session is None:
        return outcome
    if session.get("paymentId") != str(payment_id):
        raise ProviderError()
    body: dict[str, str] | None = {} if payment.checkout_provider == "stripe" else None
    request(session_path + "/reconcile", method="POST", body=body)
    return apply_status(payment.attempt, payment_id, request(path))
