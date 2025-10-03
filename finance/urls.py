from django.urls import path
from . import views
from . import views_reports  # <— qo'shildi


app_name = "finance"

urlpatterns = [
    path("investments/", views.InvestmentListCreateView.as_view(), name="investment_list"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),

    # Hisobotlar
    path("reports/arap/", views_reports.ARAPReportView.as_view(), name="arap_report"),
    path("reports/commission/", views_reports.CommissionReportView.as_view(), name="commission_report"),

    # CSV eksport
    path("reports/arap.csv", views_reports.ARAPCSVView.as_view(), name="arap_csv"),
    path("reports/commission.csv", views_reports.CommissionCSVView.as_view(), name="commission_csv"),

    path("health/", views_reports.FinanceHealthView.as_view(), name="health"),
]