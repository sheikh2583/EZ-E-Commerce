from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.CustomerLogin.as_view(), name="login"),
    path("register/", views.register, name="register"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("", views.account, name="account"),
    path("addresses/add/", views.edit_address, name="address_add"),
    path("addresses/<int:pk>/", views.edit_address, name="address_edit"),
    path("addresses/<int:pk>/delete/", views.delete_address, name="address_delete"),
]
