# sales/views_commission.py - KOMISSIYA VIEW'LARI
"""
Komissiya boshqaruvi

FEATURES:
1. Komissiyalar ro'yxati (approved/pending/deduction)
2. Oylik reyting va bonus
3. Komissiya summani o'zgartirish (owner)
4. To'langan belgilash
5. Tasdiqlash/Rad etish

YANGI MANTIQ:
- Deduction (manfiy komissiya) alohida ko'rsatiladi
- Net total = Positive - |Negative|
"""

import json
from decimal import Decimal
from datetime import timedelta, datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count
from django.db.models.functions import TruncDate
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone as dj_tz
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from sales.models import SellerCommission, Transaction, SellerMonthlyStat, MonthlyBonus
from accounts.models import User
from core.utils import is_owner, safe_sum, month_key


@login_required
def commissions_list(request):
    """
    Komissiyalar ro'yxati va statistika

    FEATURES:
    - Uchta jadval: Approved, Pending, Deductions
    - Filtrlar: seller, paid, approved, category, date
    - Oylik reyting
    - 30 kunlik trend
    - Net total (positive - negative)
    """
    # Filtrlar
    seller_id = request.GET.get("seller_id", "").strip()
    paid = request.GET.get("paid", "").strip()
    approved = request.GET.get("approved", "").strip()
    category = request.GET.get("category", "").strip()
    rescinded = request.GET.get("rescinded", "").strip()
    month_filter = request.GET.get("month", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    def _parse_date(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except:
            return None

    df = _parse_date(date_from)
    dt = _parse_date(date_to)

    # Base queryset
    qs = SellerCommission.objects.select_related(
        "transaction",
        "transaction__product",
        "transaction__product__brand",
        "transaction__product__model",
        "seller",
        "original_commission"
    ).order_by("-transaction__created_at")

    # Scope by user
    if not is_owner(request.user):
        qs = qs.filter(seller=request.user)
    elif seller_id:
        qs = qs.filter(seller_id=seller_id)

    # Filters
    if paid == "1":
        qs = qs.filter(is_paid=True)
    elif paid == "0":
        qs = qs.filter(is_paid=False)

    if approved == "1":
        qs = qs.filter(is_approved=True)
    elif approved == "0":
        qs = qs.filter(is_approved=False)

    if category in [
        SellerCommission.CAT_PROFIT30,
        SellerCommission.CAT_FLAT5,
        SellerCommission.CAT_NONE
    ]:
        qs = qs.filter(category=category)

    if rescinded == "1":
        qs = qs.filter(is_rescinded=True)
    elif rescinded == "0":
        qs = qs.filter(is_rescinded=False)

    if df:
        qs = qs.filter(transaction__created_at__date__gte=df)
    if dt:
        qs = qs.filter(transaction__created_at__date__lte=dt)

    # TOTALS (approved, not rescinded)
    active_qs = qs.filter(is_approved=True, is_rescinded=False)

    # Positive vs Negative
    positive_qs = active_qs.filter(is_deduction=False)
    deduction_qs = active_qs.filter(is_deduction=True)

    positive_total = safe_sum(positive_qs, "amount")
    deduction_total = safe_sum(deduction_qs, "amount")  # Bu manfiy
    net_total = positive_total + deduction_total  # Manfiy qo'shiladi

    paid_total = safe_sum(
        qs.filter(is_paid=True, is_rescinded=False),
        "amount"
    )
    unpaid_total = safe_sum(
        qs.filter(is_paid=False, is_rescinded=False),
        "amount"
    )

    # Lists (for tables)
    pending_rows = list(qs.filter(is_approved=False)[:500])
    approved_rows = list(active_qs.filter(is_deduction=False)[:500])
    deduction_rows = list(active_qs.filter(is_deduction=True)[:500])

    # 30 day trend (approved commissions)
    today = dj_tz.now().date()
    start = today - timedelta(days=29)

    trend = (
        active_qs.filter(
            transaction__created_at__date__range=(start, today)
        )
        .annotate(d=TruncDate("transaction__created_at"))
        .values("d")
        .annotate(s=Sum("amount"))
        .order_by("d")
    )
    by_date = {r["d"]: float(r["s"] or 0) for r in trend}
    labels = [(start + timedelta(days=i)) for i in range(30)]
    series = [by_date.get(d, 0.0) for d in labels]

    # Oylik reyting
    mk = month_filter or month_key()
    leaderboard = list(
        SellerMonthlyStat.objects
        .filter(month_key=mk)
        .select_related("seller")
        .order_by("-sales_count", "seller__username")
    )

    bonuses = list(
        MonthlyBonus.objects
        .filter(month_key=mk)
        .select_related("winner")
        .order_by("-awarded_at")
    )

    # Reference data
    sellers = None
    if is_owner(request.user):
        sellers = User.objects.filter(is_active=True).order_by("username")

    context = {
        # Data
        "pending_rows": pending_rows,
        "approved_rows": approved_rows,
        "deduction_rows": deduction_rows,

        # Filters
        "sellers": sellers,
        "seller_id": seller_id,
        "paid": paid,
        "approved": approved,
        "category": category,
        "rescinded": rescinded,
        "date_from": date_from,
        "date_to": date_to,

        # Totals
        "positive_amount": positive_total,
        "deduction_amount": abs(deduction_total),  # Display as positive
        "net_total": net_total,
        "paid_amount": paid_total,
        "unpaid_amount": unpaid_total,

        # Chart
        "chart_labels": mark_safe(json.dumps(
            [d.strftime("%Y-%m-%d") for d in labels]
        )),
        "chart_series": mark_safe(json.dumps(series)),

        # Leaderboard
        "month_key": mk,
        "leaderboard": leaderboard,
        "month_bonuses": bonuses,
    }

    return render(request, "sales/commissions_list.html", context)


@login_required
def commission_approve(request, commission_id):
    """
    Komissiyani tasdiqlash (owner)
    """
    if not is_owner(request.user):
        return HttpResponseForbidden(_("Faqat owner tasdiqlashi mumkin"))

    commission = get_object_or_404(SellerCommission, pk=commission_id)

    if not commission.is_approved:
        commission.is_approved = True
        commission.approved_by = request.user
        commission.approved_at = dj_tz.now()
        commission.save(update_fields=[
            "is_approved",
            "approved_by",
            "approved_at"
        ])
        messages.success(request, _("Komissiya tasdiqlandi"))
    else:
        messages.info(request, _("Allaqachon tasdiqlangan"))

    return redirect("commissions_list")


@login_required
def commission_reject(request, commission_id):
    """
    Komissiyani rad etish (o'chirish)
    """
    if not is_owner(request.user):
        return HttpResponseForbidden(_("Faqat owner rad eta oladi"))

    commission = get_object_or_404(SellerCommission, pk=commission_id)

    if commission.is_approved:
        messages.error(request, _(
            "Tasdiqlangan komissiyani bu yerda o'chirib bo'lmaydi"
        ))
    else:
        commission.delete()
        messages.success(request, _("Komissiya o'chirildi"))

    return redirect("commissions_list")


@login_required
def commission_mark_paid(request, commission_id):
    """
    Komissiyani to'langan deb belgilash (owner)
    """
    if not is_owner(request.user):
        return HttpResponseForbidden(_("Faqat owner belgilashi mumkin"))

    commission = get_object_or_404(
        SellerCommission.objects.select_related("transaction", "seller"),
        pk=commission_id
    )

    if not commission.is_paid:
        commission.is_paid = True
        commission.paid_at = dj_tz.now()
        commission.save(update_fields=["is_paid", "paid_at"])
        messages.success(request, _("To'langan deb belgilandi"))
    else:
        messages.info(request, _("Allaqachon to'langan"))

    return redirect("commissions_list")


@require_POST
@login_required
def commission_update_amount(request, pk):
    """
    Komissiya summasini o'zgartirish (owner)

    POST: amount

    DIQQAT: Bu faqat xato holatlarda ishlatilishi kerak!
    """
    if not is_owner(request.user):
        return HttpResponseForbidden(_("Faqat owner o'zgartirishi mumkin"))

    try:
        from core.utils import parse_decimal
        amount = parse_decimal(request.POST.get("amount"))

        if amount < Decimal("0.00"):
            messages.error(request, _("Summa manfiy bo'lishi mumkin emas"))
            return redirect("commissions_list")
    except:
        messages.error(request, _("Noto'g'ri summa"))
        return redirect("commissions_list")

    commission = get_object_or_404(
        SellerCommission.objects.select_related("transaction"),
        pk=pk
    )

    commission.amount = amount
    commission.save(update_fields=["amount"])

    messages.success(request, _("Komissiya summasi o'zgartirildi"))
    return redirect("commissions_list")