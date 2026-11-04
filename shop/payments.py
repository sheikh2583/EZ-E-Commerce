import hashlib
import re
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .gateway import HOSTS, Gateway
from .models import (
    InventoryReservation,
    Order,
    OrderStatusEvent,
    PaymentAttempt,
    PaymentEvent,
)
from .orders import change_reservations

SUCCESS = {"VALID", "VALIDATED"}
TERMINAL_FAILURE = {"FAILED", "CANCELLED", "CANCEL"}


class PaymentError(ValueError):
    pass


def audit(attempt: PaymentAttempt, outcome: str, marker: str = "", reference: str = "") -> None:
    fingerprint = hashlib.sha256(f"{outcome}:{marker}:{reference}".encode()).hexdigest()
    PaymentEvent.objects.get_or_create(attempt=attempt, fingerprint=fingerprint, defaults={
        "outcome": outcome, "provider_reference": reference,
    })


@transaction.atomic
def begin(order_id: int) -> tuple[PaymentAttempt, bool]:
    order = Order.objects.select_for_update().get(pk=order_id)
    if order.state != Order.State.PENDING or order.payment_review or order.payment_state not in (
        Order.PaymentState.UNPAID, Order.PaymentState.PENDING,
    ):
        raise PaymentError("This order is not available for payment.")
    attempt = order.payments.filter(state=PaymentAttempt.State.PENDING).first()
    if attempt:
        if attempt.mode != settings.PAYMENT_MODE:
            raise PaymentError("This payment uses a different environment.")
        return attempt, False
    if not InventoryReservation.objects.filter(
        item__order=order, state=InventoryReservation.State.HELD, expires_at__gt=timezone.now(),
    ).exists():
        raise PaymentError("Your reservation expired. Please place a new order.")
    attempt = PaymentAttempt.objects.create(
        order=order, provider="sslcommerz" if settings.PAYMENT_MODE in HOSTS else "simulation",
        mode=settings.PAYMENT_MODE, merchant_reference=uuid.uuid4().hex[:30],
        amount=order.total, currency=order.currency,
    )
    order.payment_state = Order.PaymentState.PENDING
    order.save(update_fields=["payment_state", "updated_at"])
    audit(attempt, "created")
    return attempt, True


@transaction.atomic
def attach_session(attempt: PaymentAttempt, url: str, reference: str) -> None:
    updated = PaymentAttempt.objects.filter(pk=attempt.pk, state=PaymentAttempt.State.PENDING).update(
        checkout_url=url, session_reference=reference, updated_at=timezone.now(),
    )
    if updated:
        audit(attempt, "hosted_session_created")


def cancel_order(order: Order, reason: str, payment_state: Order.PaymentState) -> None:
    change_reservations(order, InventoryReservation.State.RELEASED)
    previous = order.state
    order.state = Order.State.CANCELLED
    order.payment_state = payment_state
    order.save(update_fields=["state", "payment_state", "updated_at"])
    OrderStatusEvent.objects.create(order=order, previous=previous, current=order.state, reason=reason)


@transaction.atomic
def simulate(attempt: PaymentAttempt) -> None:
    if not settings.DEBUG or settings.PAYMENT_MODE != "simulation" or attempt.mode != "simulation":
        raise PaymentError("Simulation is disabled.")
    order = Order.objects.select_for_update().get(pk=attempt.order_id)
    attempt = PaymentAttempt.objects.select_for_update().get(pk=attempt.pk)
    if attempt.state == PaymentAttempt.State.PENDING:
        attempt.state = PaymentAttempt.State.SIMULATED
        attempt.save(update_fields=["state", "updated_at"])
        cancel_order(order, "Development simulation completed", Order.PaymentState.UNPAID)
        audit(attempt, "simulation_completed")


def matches_amount(value: object, amount: int) -> bool:
    if not isinstance(value, (str, int, Decimal)) or not re.fullmatch(r"\d{1,12}(?:\.\d{1,2})?", str(value), re.ASCII):
        return False
    try:
        return Decimal(str(value)) * 100 == amount
    except InvalidOperation:
        return False


def flag_review(order: Order, attempt: PaymentAttempt, outcome: str, reference: str = "") -> None:
    if attempt.state not in (PaymentAttempt.State.VERIFIED, PaymentAttempt.State.REFUNDED):
        attempt.state = PaymentAttempt.State.REVIEW
        attempt.save(update_fields=["state", "updated_at"])
    order.payment_review = True
    order.save(update_fields=["payment_review", "updated_at"])
    audit(attempt, outcome, reference=reference)


@transaction.atomic
def apply_validation(attempt: PaymentAttempt, validation_id: str, result: dict) -> str:
    order = Order.objects.select_for_update().get(pk=attempt.order_id)
    attempt = PaymentAttempt.objects.select_for_update().get(pk=attempt.pk)
    if (
        result.get("status") not in SUCCESS or result.get("tran_id") != attempt.merchant_reference
        or result.get("val_id") != validation_id
    ):
        audit(attempt, "validation_rejected", validation_id)
        return "invalid"
    bank_id = result.get("bank_tran_id")
    if not isinstance(bank_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:/+-]{1,100}", bank_id):
        flag_review(order, attempt, "missing_provider_reference")
        return "review"
    if attempt.state in (PaymentAttempt.State.VERIFIED, PaymentAttempt.State.REFUNDED):
        if bank_id != attempt.provider_reference:
            flag_review(order, attempt, "second_capture", bank_id)
            return "review"
        return "verified"
    if (
        not matches_amount(result.get("amount"), attempt.amount) or result.get("currency") != attempt.currency
        or result.get("currency_type", attempt.currency) != attempt.currency
        or ("currency_amount" in result and not matches_amount(result["currency_amount"], attempt.amount))
        or str(result.get("risk_level")) != "0"
    ):
        flag_review(order, attempt, "amount_currency_or_risk", bank_id)
        return "review"
    if order.state != Order.State.PENDING or order.accepted_payment_id or not InventoryReservation.objects.filter(
        item__order=order, state=InventoryReservation.State.HELD,
    ).exists():
        flag_review(order, attempt, "late_or_duplicate_capture", bank_id)
        return "review"

    attempt.state = PaymentAttempt.State.VERIFIED
    attempt.provider_reference = bank_id
    attempt.verified_at = timezone.now()
    try:
        with transaction.atomic():
            attempt.save(update_fields=["state", "provider_reference", "verified_at", "updated_at"])
    except IntegrityError:
        if not PaymentAttempt.objects.filter(
            provider=attempt.provider, mode=attempt.mode, provider_reference=bank_id,
        ).exclude(pk=attempt.pk).exists():
            raise
        attempt.refresh_from_db()
        flag_review(order, attempt, "duplicate_provider_reference", bank_id)
        return "review"
    change_reservations(order, InventoryReservation.State.CONSUMED)
    order.accepted_payment = attempt
    order.payment_state = Order.PaymentState.PAID
    order.payment_review = False
    order.save(update_fields=["accepted_payment", "payment_state", "payment_review", "updated_at"])
    audit(attempt, "verified", reference=bank_id)
    return "verified"


@transaction.atomic
def apply_failure(attempt: PaymentAttempt, cancelled: bool) -> str:
    order = Order.objects.select_for_update().get(pk=attempt.order_id)
    attempt = PaymentAttempt.objects.select_for_update().get(pk=attempt.pk)
    if attempt.state != PaymentAttempt.State.PENDING:
        return "unchanged"
    attempt.state = PaymentAttempt.State.CANCELLED if cancelled else PaymentAttempt.State.FAILED
    attempt.save(update_fields=["state", "updated_at"])
    cancel_order(order, "Gateway confirmed " + attempt.state, Order.PaymentState.FAILED)
    audit(attempt, attempt.state)
    return attempt.state


def reconcile(gateway: Gateway, attempt: PaymentAttempt) -> str:
    rows = gateway.transactions(attempt.merchant_reference)
    matching = [row for row in rows if row.get("tran_id") == attempt.merchant_reference]
    successful = [row for row in matching if row.get("status") in SUCCESS]
    if successful:
        outcome = "pending"
        for row in successful:
            validation_id = str(row.get("val_id", ""))
            if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", validation_id):
                outcome = apply_validation(attempt, validation_id, gateway.validate(validation_id))
        return outcome
    if matching and len(matching) == len(rows) and all(row.get("status") in TERMINAL_FAILURE for row in matching):
        return apply_failure(attempt, all(row["status"] in ("CANCELLED", "CANCEL") for row in matching))
    return "pending"
