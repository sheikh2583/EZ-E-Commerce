from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from storefront import cart, checkout, payment, staff, views

admin.site.site_header = "Store management"
admin.site.site_title = "Store management"
admin.site.index_title = "Catalogue and store settings"

urlpatterns = [
    path("", views.home, name="home"),
    path("products/", views.catalogue, name="catalogue"),
    path("products/<slug:slug>/", views.product_detail, name="product"),
    path("cart/", cart.detail, name="cart"),
    path("cart/add/<int:product_id>/", cart.add, name="cart_add"),
    path("cart/update/<int:product_id>/", cart.update, name="cart_update"),
    path("checkout/", checkout.checkout, name="checkout"),
    path("checkout/place/", checkout.submit, name="order_submit"),
    path("orders/<uuid:reference>/", checkout.order_detail, name="order"),
    path("orders/access/", checkout.guest_order_access, name="guest_order_access"),
    path("orders/<uuid:reference>/pay/", payment.start, name="payment_start"),
    path("payments/ipn/", payment.ipn, name="payment_ipn"),
    path("payments/return/", payment.payment_return, name="payment_return"),
    path("payments/pap/return/<uuid:reference>/", payment.pap_return, name="pap_return"),
    path("payments/pap/webhook/", payment.pap_webhook, name="pap_webhook"),
    path("account/", include("accounts.urls")),
    path("staff/", staff.dashboard, name="staff"),
    path("staff/orders/", staff.orders, name="staff_orders"),
    path("staff/orders/<uuid:reference>/", staff.order_detail, name="staff_order"),
    path("staff/products/<int:pk>/photos/", staff.images, name="staff_images"),
    path("staff/products/<int:pk>/photos/<int:photo_id>/remove/", staff.remove_image, name="staff_remove_image"),
    path("staff/catalogue/", admin.site.urls),
    path("healthz", views.health, name="health"),
    path("readyz", views.readiness, name="readiness"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
