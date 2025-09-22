# accounts/urls.py
from django.urls import path
from .views import login_view, logout_view, home, store_list, store_form, store_delete, seller_list, seller_new, \
    seller_edit, seller_delete, seller_reset_password

urlpatterns = [
    path("", home, name="home"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
# Stores
    path("stores/", store_list, name="store_list"),
    path("stores/new/", store_form, name="store_new"),
    path("stores/<int:pk>/edit/", store_form, name="store_edit"),
    path("stores/<int:pk>/delete/", store_delete, name="store_delete"),

    # Sellers
    path("sellers/", seller_list, name="seller_list"),
    path("sellers/new/", seller_new, name="seller_new"),
    path("sellers/<int:pk>/edit/", seller_edit, name="seller_edit"),
    path("sellers/<int:pk>/delete/", seller_delete, name="seller_delete"),
    path("sellers/<int:pk>/reset-password/", seller_reset_password, name="seller_reset_password"),
]
