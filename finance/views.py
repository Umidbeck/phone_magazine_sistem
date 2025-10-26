# finance/views.py (tegishli qismini ko'chiring)
from django.core.paginator import Paginator
from django.db.models import Sum
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.contrib import messages

from .models import Investment
from .forms import InvestmentForm, KPIFilterForm
from .services import post_investment
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


# finance/views.py - CAPITAL MANAGEMENT & DASHBOARD
from decimal import Decimal
from datetime import date, timedelta, datetime, time

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction, models
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect
from django.utils import timezone as dj_tz, timezone

from finance.models import CapitalTransaction
from finance.services import compute_balance_sheet, compute_cash_balance
from reports.accounting import compute_kpi, monthly_breakdown
from accounts.models import Store


@login_required
def financial_dashboard(request):
    """
    TO'LIQ MOLIYAVIY DASHBOARD

    Ko'rsatiladi:
    - Balance Sheet (Balans hisoboti)
    - Kassa (Naqd/Karta)
    - Foyda tendensiyasi
    - Oylik foyda grafigi
    """
    if not getattr(request.user, "is_owner", False):
        return HttpResponseForbidden("Faqat egaga ruxsat")

    today = dj_tz.now().date()

    # Filters
    store_id = None
    stores = Store.objects.order_by("name")
    s = (request.GET.get("store_id") or "").strip()
    if s.isdigit():
        store_id = int(s)

    # Balance Sheet (bugungi holat)
    bs = compute_balance_sheet(request.user, today, store_id)

    # Kassa (bugungi)
    cash_data = compute_cash_balance(request.user, today, store_id)

    # Period KPI (30 kun)
    df = today - timedelta(days=29)
    dt = today
    kpi_30d = compute_kpi(request.user, df, dt, store_id)

    # Oylik breakdown (12 oy)
    start_month = today.replace(day=1)
    monthly_data = monthly_breakdown(request.user, start_month, 12, store_id)

    # Graph data
    months_labels = [f"{m['year']}-{m['month']:02d}" for m in monthly_data]
    net_profit_series = [float(m['net_profit']) for m in monthly_data]
    gross_profit_series = [float(m['gross_profit']) for m in monthly_data]
    sales_series = [float(m['total_sales']) for m in monthly_data]

    # Capital movements (oxirgi 20)
    capital_movements = CapitalTransaction.objects.select_related("created_by", "store").order_by("-created_at")[:20]

    ctx = {
        # Balance Sheet
        "bs": bs,

        # Kassa
        "cash": cash_data,

        # Period KPI
        "kpi_30d": kpi_30d,
        "period_days": 30,
        "date_from": df,
        "date_to": dt,

        # Filters
        "stores": stores,
        "store_id": str(store_id or ""),

        # Graphs
        "months_labels": months_labels,
        "net_profit_series": net_profit_series,
        "gross_profit_series": gross_profit_series,
        "sales_series": sales_series,

        # Capital movements
        "capital_movements": capital_movements,
    }

    return render(request, "finance/dashboard.html", ctx)


@login_required
def capital_inject(request):
    """Kapital kiritish (Owner investitsiya qiladi)"""
    if not getattr(request.user, "is_owner", False):
        return HttpResponseForbidden("Faqat egaga ruxsat")

    if request.method == "POST":
        try:
            amount = Decimal(request.POST.get("amount") or "0")
            channel = request.POST.get("channel", CapitalTransaction.CHANNEL_CASH)
            note = (request.POST.get("note") or "").strip()
            store_id = request.POST.get("store_id")

            if amount <= 0:
                messages.error(request, "Summa 0 dan katta bo'lishi kerak")
                return redirect("dashboard")

            store = None
            if store_id and store_id.isdigit():
                store = Store.objects.get(pk=int(store_id))

            with transaction.atomic():
                cap_txn = CapitalTransaction.objects.create(
                    type=CapitalTransaction.TYPE_INJECTION,
                    store=store,
                    amount=amount,
                    channel=channel,
                    note=note or "Qo'shimcha investitsiya",
                    created_by=request.user,
                    is_approved=True,
                    approved_by=request.user,
                    approved_at=dj_tz.now(),
                )

            messages.success(request, f"${amount} investitsiya kiritildi ({cap_txn.get_channel_display()})")
            return redirect("finance:dashboard")

        except Exception as e:
            messages.error(request, f"Xatolik: {e}")
            return redirect("finance:dashboard")

    # GET
    stores = Store.objects.order_by("name")
    return render(request, "finance/capital_inject.html", {"stores": stores})


@login_required
def capital_withdraw(request):
    """Pul yechish (Owner foydadan yoki kapitaldan oladi)"""
    if not getattr(request.user, "is_owner", False):
        return HttpResponseForbidden("Faqat egaga ruxsat")

    if request.method == "POST":
        try:
            amount = Decimal(request.POST.get("amount") or "0")
            channel = request.POST.get("channel", CapitalTransaction.CHANNEL_CASH)
            source = request.POST.get("source", CapitalTransaction.SOURCE_PROFIT)  # ✅ To'g'rilandi
            note = (request.POST.get("note") or "").strip()
            store_id = request.POST.get("store_id")

            if amount <= 0:
                messages.error(request, "Summa 0 dan katta bo'lishi kerak")
                return redirect("finance:dashboard")

            store = None
            if store_id and store_id.isdigit():
                store = Store.objects.get(pk=int(store_id))

            # Balansni tekshirish
            bs = compute_balance_sheet(request.user, dj_tz.now().date(), store.id if store else None)

            # ✅ Source bo'yicha tekshirish
            if source == CapitalTransaction.SOURCE_PROFIT:
                if amount > bs.retained_earnings:
                    messages.error(request, f"Yetarli foyda yo'q. Mavjud: ${bs.retained_earnings}")
                    return redirect("finance:dashboard")
            elif source == CapitalTransaction.SOURCE_CAPITAL:
                if amount > bs.owner_equity:
                    messages.error(request, f"Yetarli kapital yo'q. Mavjud: ${bs.owner_equity}")
                    return redirect("finance:dashboard")

            # Kassada pul borligini tekshirish
            cash_data = compute_cash_balance(request.user, dj_tz.now().date(), store.id if store else None)
            if channel == CapitalTransaction.CHANNEL_CASH:
                if amount > cash_data["cash_closing"]:
                    messages.error(request, f"Kassada yetarli naqd yo'q. Mavjud: ${cash_data['cash_closing']}")
                    return redirect("finance:dashboard")
            elif channel == CapitalTransaction.CHANNEL_CARD:
                if amount > cash_data["card_closing"]:
                    messages.error(request, f"Kartada yetarli pul yo'q. Mavjud: ${cash_data['card_closing']}")
                    return redirect("finance:dashboard")

            with transaction.atomic():
                cap_txn = CapitalTransaction.objects.create(
                    type=CapitalTransaction.TYPE_WITHDRAWAL,
                    store=store,
                    amount=amount,
                    channel=channel,
                    withdrawal_source=source,
                    note=note or f"Pul yechish ({source})",
                    created_by=request.user,
                    is_approved=True,
                    approved_by=request.user,
                    approved_at=dj_tz.now(),
                )

            # ✅ Display text to'g'rilandi
            source_text = "foydadan" if source == CapitalTransaction.SOURCE_PROFIT else "kapitaldan"
            messages.success(request,
                             f"${amount} yechildi ({cap_txn.get_channel_display()}, {source_text})")
            return redirect("finance:dashboard")

        except Exception as e:
            messages.error(request, f"Xatolik: {e}")
            return redirect("finance:dashboard")

    # GET - balansni ko'rsatish
    bs = compute_balance_sheet(request.user, dj_tz.now().date(), None)
    cash_data = compute_cash_balance(request.user, dj_tz.now().date(), None)
    stores = Store.objects.order_by("name")

    ctx = {
        "bs": bs,
        "cash": cash_data,
        "stores": stores,
    }
    return render(request, "finance/capital_withdraw.html", ctx)


def _parse_iso_date(s: str) -> date | None:
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def _inclusive_bounds(d_from, d_to):
    # Naive datetime -> TZ-aware (start of day / end of day)
    start_naive = datetime.combine(d_from, time.min)
    end_naive = datetime.combine(d_to, time.max)

    start_dt = timezone.make_aware(start_naive, timezone.get_current_timezone())
    end_dt   = timezone.make_aware(end_naive,   timezone.get_current_timezone())
    return start_dt, end_dt


@login_required
def capital_movements_log(request):
    """Kapital harakatlari tarixi"""
    if not getattr(request.user, "is_owner", False):
        return HttpResponseForbidden("Faqat egaga ruxsat")

    # --- Defaults: this month (local TZ)
    today = timezone.localdate()
    month_start = date(today.year, today.month, 1)

    # --- Filters (raw)
    store_id = (request.GET.get("store_id") or "").strip()
    type_filter = (request.GET.get("type") or "").strip()
    date_from_raw = (request.GET.get("date_from") or "").strip()
    date_to_raw = (request.GET.get("date_to") or "").strip()

    # --- Resolve dates
    d_from = _parse_iso_date(date_from_raw) or month_start
    d_to = _parse_iso_date(date_to_raw) or today
    if d_from > d_to:
        # swap if user sent reversed
        d_from, d_to = d_to, d_from
    start_dt, end_dt = _inclusive_bounds(d_from, d_to)

    # --- Base queryset
    qs = (
        CapitalTransaction.objects
        .select_related("created_by", "store")
        .filter(created_at__range=(start_dt, end_dt))
        .order_by("-created_at", "-id")
    )

    # --- Store filter
    if store_id.isdigit():
        qs = qs.filter(store_id=int(store_id))
    elif store_id:  # non-digit input -> ignore silently
        store_id = ""

    # --- Type filter (validate against model constants)
    valid_types = {CapitalTransaction.TYPE_INJECTION, CapitalTransaction.TYPE_WITHDRAWAL}
    if type_filter not in valid_types:
        type_filter = ""
    else:
        qs = qs.filter(type=type_filter)

    # --- Totals on filtered set
    total_injections = qs.filter(type=CapitalTransaction.TYPE_INJECTION).aggregate(s=Sum("amount"))["s"] or Decimal("0")
    total_withdrawals = qs.filter(type=CapitalTransaction.TYPE_WITHDRAWAL).aggregate(s=Sum("amount"))["s"] or Decimal("0")
    net_capital_change = total_injections - total_withdrawals

    # --- Pagination (100 per page)
    paginator = Paginator(qs, 100)
    page_obj = paginator.get_page(request.GET.get("page"))

    stores = Store.objects.order_by("name")

    ctx = {
        "movements": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,

        "stores": stores,
        "store_id": store_id,
        "type": type_filter,
        "date_from": d_from.isoformat(),
        "date_to": d_to.isoformat(),

        "total_injections": total_injections,
        "total_withdrawals": total_withdrawals,
        "net_capital_change": net_capital_change,
        "net_capital_change_abs" : abs(net_capital_change),
    }
    return render(request, "finance/capital_movements_log.html", ctx)
