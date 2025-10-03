# accounts/urls.py
from django.urls import path

from inventory.views import my_acquisitions, my_stats
from .views import login_view, logout_view, home, store_list, store_form, store_delete, seller_list, seller_new, \
    seller_edit, seller_delete, seller_reset_password, account_dashboard, account_stats_user, my_sales, my_commissions
from .views_commission import commission_settings

urlpatterns = [
    # path("", account_dashboard, name="account_dashboard"),
    path("", home, name="home"),

    path("my-sales/", my_sales, name="my_sales"),
    path("my-acquisitions/", my_acquisitions, name="my_acquisitions"),
    path("my-stats/", my_stats, name="my_stats"),
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

    path("account/my-commissions/", my_commissions, name="my_commissions"),

    path("account/", account_dashboard, name="account_dashboard"),
    path("account/stats/", account_stats_user, name="account_stats_user"),

    path("settings/commission/", commission_settings, name="commission_settings"),
]
