from datetime import timedelta
from uuid import UUID

from django.core.signing import BadSignature, Signer
from django.utils import timezone

from .models import Order

LINK_DURATION = timedelta(days=30)
LINK_SALT = "shop.guest-order.v1"


def make_token(order: Order) -> str:
    return Signer(salt=LINK_SALT).sign_object({
        "reference": str(order.reference),
        "expires": int((order.created_at + LINK_DURATION).timestamp()),
    })


def read_token(token: str) -> UUID:
    payload = Signer(salt=LINK_SALT).unsign_object(token)
    if timezone.now().timestamp() >= payload["expires"]:
        raise BadSignature("Expired order access link")
    return UUID(payload["reference"])
