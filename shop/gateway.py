from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit
from urllib.request import Request

from django.conf import settings
from django.urls import reverse

from .models import Order, PaymentAttempt
from .provider_http import ProviderError, request_json

HOSTS = {"sandbox": "sandbox.sslcommerz.com", "live": "securepay.sslcommerz.com"}


@dataclass(frozen=True)
class Gateway:
    mode: str
    store_id: str
    store_password: str
    public_base: str

    @property
    def host(self) -> str:
        return HOSTS[self.mode]

    def request(self, path: str, fields: dict[str, str], *, post: bool = False) -> dict:
        data = urlencode({"store_id": self.store_id, "store_passwd": self.store_password, **fields})
        url = f"https://{self.host}/{path}"
        if post:
            return request_json(Request(url, data=data.encode(), headers={
                "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json",
            }))
        return request_json(Request(f"{url}?{data}", headers={"Accept": "application/json"}))

    def start(self, order: Order, attempt: PaymentAttempt) -> tuple[str, str]:
        callback = self.public_base + reverse("payment_return")
        major, minor = divmod(attempt.amount, 100)
        body = self.request("gwprocess/v4/api.php", {
            "total_amount": f"{major}.{minor:02}", "currency": attempt.currency,
            "tran_id": attempt.merchant_reference,
            "success_url": callback, "fail_url": callback, "cancel_url": callback,
            "ipn_url": self.public_base + reverse("payment_ipn"),
            "cus_name": order.recipient[:50], "cus_email": order.email,
            "cus_add1": order.address_line[:50], "cus_city": order.locality[:50],
            "cus_postcode": order.postcode, "cus_country": "Bangladesh", "cus_phone": order.phone,
            "shipping_method": "NO", "product_name": "Online store order",
            "product_category": "Retail", "product_profile": "physical-goods",
        }, post=True)
        url, session = body.get("GatewayPageURL"), body.get("sessionkey")
        if body.get("status") != "SUCCESS" or not isinstance(session, str) or not 1 <= len(session) <= 255:
            raise ProviderError()
        if not isinstance(url, str) or len(url) > 1000:
            raise ProviderError()
        try:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.netloc != self.host or not parsed.path.startswith("/"):
                raise ProviderError()
        except ValueError:
            raise ProviderError() from None
        return url, session

    def validate(self, validation_id: str) -> dict:
        return self.request("validator/api/validationserverAPI.php", {
            "val_id": validation_id, "v": "1", "format": "json",
        })

    def transactions(self, merchant_reference: str) -> list[dict]:
        result = self.request("validator/api/merchantTransIDvalidationAPI.php", {
            "tran_id": merchant_reference, "v": "1", "format": "json",
        })
        rows = result.get("element")
        if result.get("APIConnect") != "DONE" or not isinstance(rows, list):
            raise ProviderError()
        return [row for row in rows if isinstance(row, dict)]


def gateway() -> Gateway:
    return Gateway(settings.PAYMENT_MODE, settings.SSLCOMMERZ_STORE_ID,
                   settings.SSLCOMMERZ_STORE_PASSWORD, settings.PUBLIC_BASE_URL)
