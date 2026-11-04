import json
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class ProviderError(RuntimeError):
    def __init__(self, status: int | None = None):
        super().__init__("Provider request failed")
        self.status = status


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
        raise ProviderError(error.code) from None
    except (URLError, OSError, ValueError):
        raise ProviderError() from None
    if not isinstance(result, dict):
        raise ProviderError()
    return result
