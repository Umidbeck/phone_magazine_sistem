# finance/views.py (tegishli qismini ko'chiring)
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.contrib import messages

from .models import Investment
from .forms import InvestmentForm, KPIFilterForm
from .services import post_investment, kpis_advanced
from .charts import sales_profit_series, ledger_expense_series

class InvestmentListCreateView(LoginRequiredMixin, TemplateView):
    template_name = "finance/investment_list.html"
    success_url = reverse_lazy("finance:investment_list")

    def get(self, request, *args, **kwargs):
        form = InvestmentForm()
        items = Investment.objects.order_by("-date", "-id")
        return render(request, self.template_name, {"form": form, "items": items})

    def post(self, request, *args, **kwargs):
        form = InvestmentForm(request.POST)
        items = Investment.objects.order_by("-date", "-id")
        if form.is_valid():
            post_investment(
                amount=form.cleaned_data["amount"],
                note=form.cleaned_data.get("note") or "Investitsiya",
                date=form.cleaned_data["date"],
            )
            messages.success(request, "Investitsiya qo‘shildi.")
            return redirect(self.success_url)
        return render(request, self.template_name, {"form": form, "items": items})

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "finance/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = KPIFilterForm(self.request.GET or None)
        date_from = date_to = None
        if form.is_valid():
            date_from = form.cleaned_data.get("date_from")
            date_to   = form.cleaned_data.get("date_to")
        ctx["form"] = form
        ctx["kpi"]  = kpis_advanced(date_from=date_from, date_to=date_to)

        user = self.request.user if self.request.user.is_authenticated else None
        store = getattr(user, "store", None) if user and not getattr(user, "is_owner", False) else None
        ctx["series_sales"]   = sales_profit_series(30, store=store, user=user)
        ctx["series_expense"] = ledger_expense_series(30)
        return ctx
