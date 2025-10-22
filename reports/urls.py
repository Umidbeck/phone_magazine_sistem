# reports/urls.py
from django.urls import path

from sales.views import commission_update_amount
from .views import profit_overview, daily_cash, \
    profit_compare, cash_transfer

urlpatterns = [
    path("profit/", profit_overview, name="profit_overview"),
    path("profit/transfer/", cash_transfer, name="cash_transfer"),

    path("daily-cash/", daily_cash, name="daily_cash"),
    path("profit-compare/", profit_compare, name="profit_compare"),
    path("commissions/<int:pk>/update-amount/", commission_update_amount, name="commission_update_amount"),


]
