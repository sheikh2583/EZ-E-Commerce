import logging

from django.db import DatabaseError, connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_safe

logger = logging.getLogger(__name__)


@require_safe
def home(request: HttpRequest) -> HttpResponse:
    return render(request, "home.html")


@require_safe
def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@require_safe
def readiness(request: HttpRequest) -> JsonResponse:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        logger.warning("Database readiness check failed")
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ready"})
