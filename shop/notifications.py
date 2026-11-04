import json
import logging
from datetime import timedelta
from urllib.request import Request

from django.conf import settings
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .guest_access import make_token
from .models import Notification, Order
from .provider_http import ProviderError, request_json

logger = logging.getLogger(__name__)

SUBJECTS = {
    "placed": "Order received",
    "paid": "Payment verified",
    "confirmed": "Order confirmed",
    "shipped": "Order shipped",
    "delivered": "Order delivered",
    "cancelled": "Order cancelled",
    "admin_placed": "New order received",
}
STATE_TEMPLATES = {"confirmed", "shipped", "delivered", "cancelled"}


def enqueue(order: Order, event_key: str, template: str) -> None:
    recipients = [("email", order.email), ("sms", order.phone)]
    if template == "admin_placed":
        recipients = [("email", settings.NOTIFICATION_ADMIN_EMAIL), ("sms", settings.NOTIFICATION_ADMIN_PHONE)]
    for channel, recipient in recipients:
        if recipient:
            Notification.objects.get_or_create(
                order=order, event_key=event_key, channel=channel, recipient=recipient,
                defaults={"template": template, "next_attempt_at": timezone.now()},
            )


def enqueue_state(order: Order, event_id: int) -> None:
    if order.state in STATE_TEMPLATES:
        enqueue(order, f"status:{event_id}", order.state)


def message(job: Notification) -> tuple[str, str]:
    title = SUBJECTS[job.template]
    order = job.order
    if job.channel == "sms":
        return title, f"{title}. Order reference {order.reference}."
    link = ""
    if settings.PUBLIC_BASE_URL:
        if job.template == "admin_placed":
            path = reverse("staff_order", args=[order.reference])
        elif order.user_id:
            path = reverse("order", args=[order.reference])
        else:
            path = reverse("guest_order_access") + "#" + make_token(order)
        link = settings.PUBLIC_BASE_URL + path
    text = render_to_string("notifications/order.txt", {
        "order": order, "title": title, "link": link, "sandbox": job.template == "paid" and settings.PAYMENT_MODE == "sandbox",
    })
    return title, text


def provider_configured(channel: str) -> bool:
    if channel == "email":
        return bool(settings.RESEND_API_KEY and settings.RESEND_FROM)
    return bool(settings.MIMSMS_API_KEY and settings.MIMSMS_USERNAME and settings.MIMSMS_SENDER)


def send(job: Notification) -> str:
    title, text = message(job)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if job.channel == "email":
        headers.update({
            "Authorization": f"Bearer {settings.RESEND_API_KEY}",
            "Idempotency-Key": f"ezcommerce-notification/{job.pk}",
        })
        url = "https://api.resend.com/emails"
        body = {"from": settings.RESEND_FROM, "to": [job.recipient], "subject": title, "text": text}
    else:
        url = "https://api.mimsms.com/api/V2/SMS"
        body = {
            "apiKey": settings.MIMSMS_API_KEY, "userName": settings.MIMSMS_USERNAME,
            "senderName": settings.MIMSMS_SENDER, "transactionType": "T",
            "mobileNumber": job.recipient.removeprefix("+"), "message": text,
        }
    response = request_json(Request(url, data=json.dumps(body).encode(), headers=headers))
    if job.channel == "email":
        reference = response.get("id")
    else:
        code = str(response.get("statusCode", ""))
        if code != "200":
            raise ProviderError(int(code) if code.isascii() and code.isdigit() and len(code) == 3 else None)
        reference = response.get("trackingId") or response.get("trxnId")
        if not reference and isinstance(response.get("data"), list):
            reference = next(
                (row.get("trackingId") for row in response["data"] if isinstance(row, dict) and row.get("trackingId")),
                None,
            )
    if not isinstance(reference, str) or not 1 <= len(reference) <= 150:
        raise ProviderError()
    return reference


@transaction.atomic
def claim() -> Notification | None:
    now = timezone.now()
    job = Notification.objects.select_for_update(skip_locked=True).filter(
        state=Notification.State.QUEUED, next_attempt_at__lte=now,
    ).order_by("next_attempt_at", "pk").first()
    if job:
        job.state = Notification.State.SENDING
        job.attempts += 1
        job.lease_until = now + timedelta(minutes=2)
        job.save(update_fields=["state", "attempts", "lease_until", "updated_at"])
    return job


def process(job: Notification) -> str:
    reference = ""
    next_attempt = job.next_attempt_at
    now = timezone.now()
    if not provider_configured(job.channel):
        state = Notification.State.SUPPRESSED
    else:
        try:
            reference = send(job)
        except ProviderError as error:
            clear_failure = error.status is not None and 400 <= error.status < 500 and error.status not in (408, 409, 429)
            retryable = error.status == 429 or (job.channel == "email" and not clear_failure and error.status != 409)
            if retryable and job.attempts < 4 and now - job.created_at < timedelta(hours=22):
                state = Notification.State.QUEUED
                next_attempt = now + timedelta(minutes=2 ** job.attempts)
            else:
                state = Notification.State.FAILED if clear_failure or error.status == 429 else Notification.State.UNKNOWN
            logger.warning("Notification %s outcome=%s provider_status=%s", job.pk, state, error.status)
        else:
            state = Notification.State.ACCEPTED
    Notification.objects.filter(
        pk=job.pk, state=Notification.State.SENDING, attempts=job.attempts, lease_until=job.lease_until,
    ).update(state=state, provider_reference=reference, lease_until=None, next_attempt_at=next_attempt, updated_at=now)
    return state


def mark_expired_leases() -> int:
    return Notification.objects.filter(
        state=Notification.State.SENDING, lease_until__lte=timezone.now(),
    ).update(state=Notification.State.UNKNOWN, lease_until=None, updated_at=timezone.now())
