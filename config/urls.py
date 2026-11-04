from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

from accounts.views import staff_home
from storefront import cart, views

urlpatterns = [
    path("", views.home, name="home"),
    path("products/", views.catalogue, name="catalogue"),
    path("products/<slug:slug>/", views.product_detail, name="product"),
    path("cart/", cart.detail, name="cart"),
    path("cart/add/<int:product_id>/", cart.add, name="cart_add"),
    path("cart/update/<int:product_id>/", cart.update, name="cart_update"),
    path("account/", include("accounts.urls")),
    path("staff/", staff_home, name="staff"),
    path("healthz", views.health, name="health"),
    path("readyz", views.readiness, name="readiness"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
