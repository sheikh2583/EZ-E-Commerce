import base64
import hashlib
import hmac
import json
import re
import time
from collections.abc import Mapping
from uuid import UUID

from django.conf import settings
from django.db.models import F
from django.utils import timezone

from . import pap
from .models import PapPayment, PapWebhookEvent
from .payments import audit
from .provider_http import ProviderError

PAYMENT_EVENTS = ("payment.created", "payment.processing", "payment.succeeded", "payment.failed", "payment.expired")


def verify(raw_body: bytes, headers: Mapping[str, str]) -> tuple[UUID, dict] | None:
    header_id = headers.get("webhook-id", "")
    event_id = pap.payment_uuid(header_id)
    timestamp = headers.get("webhook-timestamp", "")
    signatures = headers.get("webhook-signature", "")
    if (event_id is None or not re.fullmatch(r"[0-9]{10,11}", timestamp)
            or abs(time.time() - int(timestamp)) > 300 or len(signatures) > 512):
        return None

    secret = base64.b64decode(settings.LCT_WEBHOOK_SECRET.removeprefix("whsec_"), validate=True)
    signed = f"{header_id}.{timestamp}.".encode() + raw_body
    digest = hmac.digest(secret, signed, hashlib.sha256)
    if not any(
        re.fullmatch(r"v1,[A-Za-z0-9+/]{43}=", signature)
        and hmac.compare_digest(digest, base64.b64decode(signature[3:]))
        for signature in signatures.split()
    ):
        return None
    try:
        event = json.loads(raw_body.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    if (not isinstance(event, dict) or event.get("id") != header_id or event.get("apiVersion") != "2026-11-04"
            or event.get("environment") != settings.PAYMENT_MODE or event.get("merchantId") != settings.LCT_MERCHANT_ID):
        return None
    return event_id, event


def process_inbox() -> int:
    events = list(PapWebhookEvent.objects.filter(
        mode=settings.PAYMENT_MODE, merchant_id=settings.LCT_MERCHANT_ID, processed_at__isnull=True,
    ).order_by(F("checked_at").asc(nulls_first=True), "received_at")[:40])
    for event in events:
        data = event.payload.get("data")
        payment_id = pap.payment_uuid(data.get("id")) if isinstance(data, dict) else None
        payment = None
        if event.payload.get("type") in PAYMENT_EVENTS and payment_id is not None:
            payment = PapPayment.objects.select_related("attempt__order").filter(
                payment_id=payment_id, attempt__mode=event.mode,
            ).first()
        if payment is not None:
            try:
                pap.reconcile(payment)
            except ProviderError:
                audit(payment.attempt, "verification_unavailable")
                PapWebhookEvent.objects.filter(pk=event.pk, processed_at__isnull=True).update(checked_at=timezone.now())
                continue
        PapWebhookEvent.objects.filter(pk=event.pk, processed_at__isnull=True).update(processed_at=timezone.now())
    return len(events)
