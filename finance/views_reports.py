# finance/views_reports.py
import csv
from django.http import HttpResponse
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin

from .diagnostics import check_accounts_exist, check_journal_balanced, check_transaction_fields
from .forms import KPIFilterForm
from .reports import ar_breakdown, ap_breakdown, commission_breakdown
from .services import ensure_default_accounts


class ARAPReportView(LoginRequiredMixin, TemplateView):
    template_name = "finance/arap_report.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = KPIFilterForm(self.request.GET or None)
        date_from = date_to = None
        if form.is_valid():
            date_from = form.cleaned_data.get("date_from")
            date_to   = form.cleaned_data.get("date_to")

        ctx["form"] = form
        ctx["ar_rows"] = ar_breakdown(date_to=date_to, date_from=date_from)
        ctx["ap_rows"] = ap_breakdown(date_to=date_to, date_from=date_from)
        return ctx


class CommissionReportView(LoginRequiredMixin, TemplateView):
    template_name = "finance/commission_report.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = KPIFilterForm(self.request.GET or None)
        date_from = date_to = None
        if form.is_valid():
            date_from = form.cleaned_data.get("date_from")
            date_to   = form.cleaned_data.get("date_to")

        ctx["form"]  = form
        ctx["rows"]  = commission_breakdown(date_from=date_from, date_to=date_to)
        return ctx


# -------- CSV export helpers --------

class ARAPCSVView(LoginRequiredMixin, TemplateView):
    """
    GET ?kind=ar|ap&date_from=...&date_to=...
    """
    def get(self, request, *args, **kwargs):
        form = KPIFilterForm(request.GET or None)
        date_from = date_to = None
        if form.is_valid():
            date_from = form.cleaned_data.get("date_from")
            date_to   = form.cleaned_data.get("date_to")

        kind = request.GET.get("kind", "ar")
        rows = ar_breakdown(date_to=date_to, date_from=date_from) if kind == "ar" else ap_breakdown(date_to=date_to, date_from=date_from)

        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{kind.upper()}_report.csv"'
        w = csv.writer(resp)
        w.writerow(["Object", "Amount"])
        for r in rows:
            w.writerow([r["object"], r["amount"]])
        return resp


class CommissionCSVView(LoginRequiredMixin, TemplateView):
    """
    GET ?date_from=...&date_to=...
    """
    def get(self, request, *args, **kwargs):
        form = KPIFilterForm(request.GET or None)
        date_from = date_to = None
        if form.is_valid():
            date_from = form.cleaned_data.get("date_from")
            date_to   = form.cleaned_data.get("date_to")

        rows = commission_breakdown(date_from=date_from, date_to=date_to)
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="commission_report.csv"'
        w = csv.writer(resp)
        w.writerow(["Object", "Commission Income", "Commission Expense", "Net"])
        for r in rows:
            w.writerow([r["object"], r["income"], r["expense"], r["net"]])
        return resp

class FinanceHealthView(TemplateView):
    template_name = "finance/health.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ensure_default_accounts()
        ctx["missing_accounts"] = check_accounts_exist()
        ctx["journal_total"] = check_journal_balanced()
        ctx["tx_date_fields"] = check_transaction_fields()
        return ctx