# accounts/urls.py
from django.urls import path

from inventory.views import my_acquisitions, my_stats
from .views import login_view, logout_view, store_list, store_form, store_delete, seller_list, seller_new, \
    seller_edit, seller_delete, my_sales, home_dashboard
from .views_commission import commission_settings
from .views_password import change_password, force_password_change, check_password_strength, password_requirements, \
    seller_reset_password

urlpatterns = [
    # path("", account_dashboard, name="account_dashboard"),
    path('', home_dashboard, name='home'),

    path("my-sales/", my_sales, name="my_sales"),
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

    # Password management
    path("password/change/", change_password, name="change_password"),
    path("password/requirements/", password_requirements, name="password_requirements"),
    path("password/force-change/", force_password_change, name="force_password_change"),
    path("password/check-strength/", check_password_strength, name="check_password_strength"),

    # Seller password reset (owner only)
    path("sellers/<int:pk>/reset-password/", seller_reset_password, name="seller_reset_password"),



    path("settings/commission/", commission_settings, name="commission_settings"),
]
