import logging
from collections.abc import Callable
from datetime import UTC, datetime
from ipaddress import ip_address

from django.conf import settings
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.crypto import salted_hmac

from . import pap
from .gateway import HOSTS

logger = logging.getLogger(__name__)

RULES = {
    "login": ("sign_in", 35, 300),
    "admin:login": ("sign_in", 35, 300),
    "register": ("register", 10, 300),
    "checkout": ("checkout", 45, 300),
    "order_submit": ("place_order", 30, 300),
    "payment_start": ("payment_start", 20, 300),
    "payment_ipn": ("payment_callback", 120, 60),
    "payment_return": ("payment_callback", 120, 60),
    "pap_return": ("payment_callback", 120, 60),
    "pap_webhook": ("pap_webhook", 240, 60),
    "guest_order_access": ("guest_link", 25, 300),
    "staff_images": ("upload", 30, 300),
}


def client_address(request: HttpRequest) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")
    hops = settings.DJANGO_FORWARDED_FOR_HOPS
    value = forwarded[-hops].strip() if 0 < hops <= len(forwarded) else request.META.get("REMOTE_ADDR", "")
    try:
        return str(ip_address(value))
    except ValueError:
        return "unknown"


def exceeds(scope: str, subject: str, limit: int, window: int) -> bool:
    end = (int(timezone.now().timestamp()) // window + 1) * window
    key = salted_hmac("ez-commerce.rate-limit", f"{scope}:{end}:{subject}", algorithm="sha256").hexdigest()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO shop_ratebucket (key, hits, expires_at)
            VALUES (%s, 1, %s)
            ON CONFLICT (key) DO UPDATE SET hits = LEAST(shop_ratebucket.hits + 1, %s)
            RETURNING hits
            """,
            [key, datetime.fromtimestamp(end, tz=UTC), limit + 1],
        )
        row = cursor.fetchone()
    return bool(row and row[0] > limit)


class SecurityBoundary:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.method == "POST":
            limit = 7 * 1024 * 1024 if request.path_info.endswith("/photos/") else 256 * 1024
            length = request.META.get("CONTENT_LENGTH", "")
            if length and (not length.isascii() or not length.isdigit() or len(length) > 10 or int(length) > limit):
                return JsonResponse({"error": "Request body is too large or invalid."}, status=413)
        response = self.get_response(request)
        if response.get("Content-Type", "").startswith("text/html"):
            form_sources = "'self'"
            if pap.enabled():
                form_sources += f" https://{pap.CHECKOUT_HOSTS['stripe']}"
                if settings.PAYMENT_MODE == "sandbox":
                    form_sources += f" https://{pap.CHECKOUT_HOSTS['sslcommerz']}"
            elif settings.PAYMENT_MODE in HOSTS:
                form_sources += f" https://{HOSTS[settings.PAYMENT_MODE]}"
            styles = "'self'"
            if request.path_info.startswith("/staff/catalogue/"):
                styles += " 'unsafe-inline'"
            response["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; "
                f"style-src {styles}; img-src 'self' data: https://res.cloudinary.com; "
                f"form-action {form_sources}; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
            )
        return response

    def process_view(self, request: HttpRequest, view_func, view_args, view_kwargs) -> HttpResponse | None:
        if request.resolver_match is None:
            return None
        view_name = request.resolver_match.view_name
        if request.method != "POST" and view_name != "pap_return":
            return None
        rule = RULES.get(view_name)
        if rule is None:
            return None
        scope, limit, window = rule
        blocked = exceeds(scope, client_address(request), limit, window)
        if not blocked and scope == "sign_in":
            identity = request.POST.get("username", "").strip().lower()[:254]
            if identity:
                blocked = exceeds("login_identity", identity, 12, window)
        if blocked:
            logger.warning("Rate limit exceeded for scope=%s", scope)
            return JsonResponse(
                {"error": "Too many requests. Please wait and try again."}, status=429,
                headers={"Retry-After": str(window)},
            )
        return None
