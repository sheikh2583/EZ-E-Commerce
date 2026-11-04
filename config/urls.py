from django.urls import path

from storefront import views

urlpatterns = [
    path("", views.home, name="home"),
    path("healthz", views.health, name="health"),
    path("readyz", views.readiness, name="readiness"),
]
