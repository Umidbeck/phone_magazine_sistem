from django.urls import path
from .views import store_report, network_report, owner_dashboard, sales_log, expenses_log

urlpatterns = [
    path("store/", store_report, name="report_store"),
    path("network/", network_report, name="report_network"),
    path("dashboard/", owner_dashboard, name="owner_dashboard"),  # YANGI

    path("", owner_dashboard, name="owner_dashboard"),
    path("sales-log/", sales_log, name="sales_log"),
    path("expenses-log/", expenses_log, name="expenses_log"),
]
