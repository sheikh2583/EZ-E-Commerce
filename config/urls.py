from django.urls import include, path

from accounts.views import staff_home
from storefront import views

urlpatterns = [
    path("", views.home, name="home"),
    path("account/", include("accounts.urls")),
    path("staff/", staff_home, name="staff"),
    path("healthz", views.health, name="health"),
    path("readyz", views.readiness, name="readiness"),
]
