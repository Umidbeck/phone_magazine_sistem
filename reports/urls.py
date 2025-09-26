from django.urls import path

from sales.views import commission_update_amount
from .views import store_report, network_report, owner_dashboard, sales_log, expenses_log, profit_overview, daily_cash, \
    profit_compare

urlpatterns = [
    path("store/", store_report, name="report_store"),
    path("network/", network_report, name="report_network"),
    path("dashboard/", owner_dashboard, name="owner_dashboard"),  # YANGI

    path("", owner_dashboard, name="owner_dashboard"),
    path("sales-log/", sales_log, name="sales_log"),
    path("expenses-log/", expenses_log, name="expenses_log"),
    path("profit/", profit_overview, name="profit_overview"),

    path("daily-cash/", daily_cash, name="daily_cash"),
    path("profit-compare/", profit_compare, name="profit_compare"),
    path("commissions/<int:pk>/update-amount/", commission_update_amount, name="commission_update_amount"),

]
