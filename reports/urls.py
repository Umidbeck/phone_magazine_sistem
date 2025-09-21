from django.urls import path
from .views import store_report, network_report, owner_dashboard

urlpatterns = [
    path("store/", store_report, name="report_store"),
    path("network/", network_report, name="report_network"),
    path("dashboard/", owner_dashboard, name="owner_dashboard"),  # YANGI
]
