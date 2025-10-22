# finance/urls.py
from django.urls import path
from . import views
from .views import financial_dashboard, capital_inject, capital_withdraw, capital_movements_log

app_name = "finance"

urlpatterns = [
    path("investments/", views.InvestmentListCreateView.as_view(), name="investment_list"),
    # path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("dashboard/", financial_dashboard, name="dashboard"),
    path("capital/inject/", capital_inject, name="capital_inject"),
    path("capital/withdraw/", capital_withdraw, name="capital_withdraw"),
    path("capital/movements/", capital_movements_log, name="capital_movements_log"),
]