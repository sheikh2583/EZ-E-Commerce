import json
import re
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class ProviderError(RuntimeError):
    def __init__(self, status: int | None = None, request_id: str | None = None):
        super().__init__("Provider request failed")
        self.status = status
        self.request_id = request_id


class RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(request: Request) -> dict:
    try:
        with build_opener(RejectRedirects()).open(request, timeout=8) as response:
            content = response.read(131_073)
        if len(content) > 131_072:
            raise ProviderError()
        result = json.loads(content, parse_float=Decimal)
    except HTTPError as error:
        request_id = None
        try:
            with error:
                body = json.loads(error.read(4096))
            value = body.get("requestId") if isinstance(body, dict) else None
            if isinstance(value, str) and re.fullmatch(r"[0-9a-f-]{36}", value):
                request_id = value
        except (OSError, ValueError, RecursionError):
            pass
        raise ProviderError(error.code, request_id) from None
    except (URLError, OSError, ValueError, RecursionError):
        raise ProviderError() from None
    if not isinstance(result, dict):
        raise ProviderError()
    return result
