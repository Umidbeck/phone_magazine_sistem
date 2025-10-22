# sales/views_debt.py - QARZ VIEW'LARI
"""
Qarz (debt) operatsiyalari - AR (Accounts Receivable)

WORKFLOW:
1. Qarz yozish (debt_out) → avtomatik approved
2. Qarz to'lovi (debt_pay) → balans tekshirish, avtomatik approved
3. Qarzdorlar ro'yxati → guruhlangan ko'rinish

MUHIM:
- Har qarz guruhi UUID bilan belgilanadi
- Balance = SUM(approved debt_out) - SUM(approved debt_pay)
"""

import json
from uuid import UUID
from decimal import Decimal
from datetime import timedelta, datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Min, Max, Q
from django.db.models.functions import TruncDate
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render, get_object_or_404
from django.utils import timezone as dj_tz
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.db import transaction as db_transaction
from django.core.paginator import Paginator

from sales.forms import DebtNewForm, DebtNewSimpleForm, DebtPayForm
from sales.models import Transaction
from accounts.models import Store, User
from core.utils import is_owner, scope_by_user, safe_sum, parse_decimal
from sales.services import calculate_debt_balance


def _get_user_store(user):
    """User do'konini olish"""
    store = getattr(user, "store", None)
    if not store:
        store = Store.objects.first()
    return store


def _debt_rows(user, store_id=None, seller_id=None, df=None, dt=None):
    """
    Qarzdorlar ro'yxatini olish (guruhlangan)

    Returns:
        list: [
            {
                'group': UUID,
                'debtor_name': str,
                'debtor_phone': str,
                'total': Decimal,  # approved debt_out
                'paid': Decimal,   # approved debt_pay
                'balance': Decimal,
                'first_at': datetime,
                'last_at': datetime,
                ...
            },
            ...
        ]
    """
    base = Transaction.objects.filter(is_void=False)
    base = scope_by_user(base, user, store_id)

    if seller_id:
        base = base.filter(seller_id=seller_id)
    if df:
        base = base.filter(created_at__date__gte=df)
    if dt:
        base = base.filter(created_at__date__lte=dt)

    # Debt out aggregation (all)
    outs_all = base.filter(type="debt_out").values(
        "debtor_group", "debtor_name", "debtor_phone",
        "store_id", "seller_id"
    ).annotate(
        total_all=Sum("amount"),
        first_out=Min("created_at"),
        last_out=Max("created_at")
    )

    # Debt out (approved only)
    outs_approved = base.filter(
        type="debt_out", is_approved=True
    ).values("debtor_group").annotate(total_appr=Sum("amount"))

    # Debt pay (all)
    pays_all = base.filter(type="debt_pay").values(
        "debtor_group"
    ).annotate(
        paid_all=Sum("amount"),
        cash_all=Sum("cash_amount"),
        card_all=Sum("card_amount"),
        last_pay=Max("created_at")
    )

    # Debt pay (approved only)
    pays_approved = base.filter(
        type="debt_pay", is_approved=True
    ).values("debtor_group").annotate(
        paid_appr=Sum("amount"),
        cash_appr=Sum("cash_amount"),
        card_appr=Sum("card_amount")
    )

    # Maps
    out_all_map = {x["debtor_group"]: x for x in outs_all}
    out_appr_map = {
        x["debtor_group"]: x["total_appr"] or Decimal("0.00")
        for x in outs_approved
    }
    pay_all_map = {x["debtor_group"]: x for x in pays_all}
    pay_appr_map = {x["debtor_group"]: x for x in pays_approved}

    # Store/Seller names
    store_names = dict(Store.objects.values_list("id", "name"))
    seller_names = dict(User.objects.values_list("id", "username"))

    # Build rows
    rows = []
    all_groups = set(out_all_map.keys()) | set(pay_all_map.keys())

    for group_id in all_groups:
        out_data = out_all_map.get(group_id, {})
        pay_all_data = pay_all_map.get(group_id, {})
        pay_appr_data = pay_appr_map.get(group_id, {})

        # Approved totals
        total_appr = out_appr_map.get(group_id, Decimal("0.00"))
        paid_appr = pay_appr_data.get("paid_appr") or Decimal("0.00")
        cash_appr = pay_appr_data.get("cash_appr") or Decimal("0.00")
        card_appr = pay_appr_data.get("card_appr") or Decimal("0.00")

        balance = total_appr - paid_appr
        if balance < Decimal("0.00"):
            balance = Decimal("0.00")

        row = {
            "group": group_id,
            "debtor_name": out_data.get("debtor_name") or "—",
            "debtor_phone": out_data.get("debtor_phone") or "",
            "store_id": out_data.get("store_id"),
            "store_name": store_names.get(out_data.get("store_id"), "—"),
            "seller_id": out_data.get("seller_id"),
            "seller_name": seller_names.get(out_data.get("seller_id"), "—"),

            # All (display)
            "total_all": out_data.get("total_all") or 0,
            "paid_all": pay_all_data.get("paid_all") or 0,

            # Approved (metrics)
            "total": total_appr,
            "paid": paid_appr,
            "cash_paid": cash_appr,
            "card_paid": card_appr,
            "balance": balance,

            "first_at": out_data.get("first_out"),
            "last_at": pay_all_data.get("last_pay") or out_data.get("last_out"),
        }

        rows.append(row)

    # Sort by balance (high to low)
    rows.sort(
        key=lambda r: (r["balance"], r["last_at"] or r["first_at"]),
        reverse=True
    )

    return rows


@login_required
def debt_list(request):
    """
    Qarzdorlar ro'yxati

    FEATURES:
    - Guruhlangan ko'rinish
    - Filtrlar: store, seller, date, status, search, balance range
    - 30 kunlik debt_pay trendi
    - KPI: total, paid, balance, open/closed count
    - CSV export
    """
    # Filtrlar
    store_id = request.GET.get("store_id", "").strip()
    seller_id = request.GET.get("seller_id", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    status_filter = request.GET.get("status", "").strip()  # open/closed/all
    q = request.GET.get("q", "").strip()
    min_balance = request.GET.get("min_balance", "").strip()
    max_balance = request.GET.get("max_balance", "").strip()

    def _parse_date(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except:
            return None

    df = _parse_date(date_from)
    dt = _parse_date(date_to)

    # Rows
    rows = _debt_rows(
        request.user,
        store_id=store_id if is_owner(request.user) else None,
        seller_id=seller_id if is_owner(request.user) else None,
        df=df,
        dt=dt
    )

    # Search filter
    if q:
        q_lower = q.lower()
        rows = [
            r for r in rows
            if (q_lower in (r.get("debtor_name", "") or "").lower()) or
               (q_lower in (r.get("debtor_phone", "") or "").lower())
        ]

    # Balance range filter
    try:
        min_bal = Decimal(min_balance) if min_balance else None
    except:
        min_bal = None
    try:
        max_bal = Decimal(max_balance) if max_balance else None
    except:
        max_bal = None

    if min_bal is not None:
        rows = [r for r in rows if r["balance"] >= min_bal]
    if max_bal is not None:
        rows = [r for r in rows if r["balance"] <= max_bal]

    # Status filter
    if status_filter == "open":
        rows = [r for r in rows if r["balance"] > Decimal("0.00")]
    elif status_filter == "closed":
        rows = [r for r in rows if r["balance"] <= Decimal("0.00")]

    # KPI
    open_rows = [r for r in rows if r["balance"] > Decimal("0.00")]
    closed_rows = [r for r in rows if r["balance"] <= Decimal("0.00")]

    sum_total = sum([r["total"] for r in rows], start=Decimal("0.00"))
    sum_paid = sum([r["paid"] for r in rows], start=Decimal("0.00"))
    sum_cash = sum([r["cash_paid"] for r in rows], start=Decimal("0.00"))
    sum_card = sum([r["card_paid"] for r in rows], start=Decimal("0.00"))
    sum_balance = sum([r["balance"] for r in rows], start=Decimal("0.00"))

    open_balance_total = sum(
        [r["balance"] for r in open_rows],
        start=Decimal("0.00")
    )

    # 30 day trend (approved debt_pay)
    today = dj_tz.now().date()
    start = today - timedelta(days=29)

    pay_trend = Transaction.objects.filter(
        type="debt_pay",
        is_approved=True,
        is_void=False,
        created_at__date__range=(start, today)
    )
    if not is_owner(request.user):
        pay_trend = pay_trend.filter(store_id=request.user.store_id)

    trend_rows = (
        pay_trend.annotate(d=TruncDate("created_at"))
        .values("d")
        .annotate(s=Sum("amount"))
        .order_by("d")
    )
    by_date = {r["d"]: float(r["s"] or 0) for r in trend_rows}
    labels = [(start + timedelta(days=i)) for i in range(30)]
    series = [by_date.get(d, 0.0) for d in labels]

    # CSV Export
    if request.GET.get("export", "").lower() == "csv":
        import csv
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="debtors.csv"'
        w = csv.writer(resp)
        w.writerow([
            "Debtor", "Phone", "Store", "Seller",
            "Total ($)", "Paid ($)", "Cash ($)", "Card ($)", "Balance ($)"
        ])
        for r in rows:
            w.writerow([
                r.get("debtor_name", ""),
                r.get("debtor_phone", ""),
                r.get("store_name", ""),
                r.get("seller_name", ""),
                f"{r.get('total', 0):.2f}",
                f"{r.get('paid', 0):.2f}",
                f"{r.get('cash_paid', 0):.2f}",
                f"{r.get('card_paid', 0):.2f}",
                f"{r.get('balance', 0):.2f}",
            ])
        return resp

    # Pagination
    paginator = Paginator(rows, 50)
    page = paginator.get_page(request.GET.get("page"))

    # Reference data
    stores = None
    sellers = None
    if is_owner(request.user):
        stores = Store.objects.filter(is_active=True).order_by("name")
        sellers = User.objects.filter(is_active=True).order_by("username")

    context = {
        "page": page,
        "stores": stores,
        "sellers": sellers,

        "store_id": store_id,
        "seller_id": seller_id,
        "date_from": date_from,
        "date_to": date_to,
        "status": status_filter,
        "q": q,
        "min_balance": min_balance,
        "max_balance": max_balance,

        # KPI
        "sum_total": sum_total,
        "sum_paid": sum_paid,
        "sum_cash": sum_cash,
        "sum_card": sum_card,
        "sum_balance": sum_balance,
        "open_count": len(open_rows),
        "closed_count": len(closed_rows),
        "open_balance_total": open_balance_total,

        # Chart
        "chart_labels": mark_safe(json.dumps(
            [d.strftime("%Y-%m-%d") for d in labels]
        )),
        "chart_series": mark_safe(json.dumps(series)),
    }

    return render(request, "sales/debt_list.html", context)


@login_required
def debt_new(request):
    """
    Yangi qarz (to'liq ma'lumot bilan)

    POST: debtor_name, debtor_phone, amount, note

    Avtomatik approved (kassaga darhol ta'sir qiladi)
    """
    if request.method == "POST":
        form = DebtNewForm(request.POST)
        if form.is_valid():
            store = _get_user_store(request.user)

            with db_transaction.atomic():
                Transaction.objects.create(
                    type="debt_out",
                    store=store,
                    seller=request.user,
                    created_by=request.user,
                    amount=form.cleaned_data["amount"],
                    debtor_name=form.cleaned_data["debtor_name"].strip(),
                    debtor_phone=form.cleaned_data.get("debtor_phone", "").strip(),
                    note=form.cleaned_data.get("note", "").strip(),
                    # Avtomatik approved
                    is_approved=True,
                    approved_by=request.user,
                    approved_at=dj_tz.now()
                )

            messages.success(request, _("Qarz yozildi"))
            return redirect("debt_list")
    else:
        form = DebtNewForm()

    return render(request, "sales/debt_new.html", {"form": form})


@login_required
def debt_new_simple(request):
    """
    Sodda qarz (faqat summa)

    POST: amount, note

    debtor_name va phone bo'sh qoladi
    """
    if request.method == "POST":
        form = DebtNewSimpleForm(request.POST)
        if form.is_valid():
            store = _get_user_store(request.user)

            with db_transaction.atomic():
                Transaction.objects.create(
                    type="debt_out",
                    store=store,
                    seller=request.user,
                    created_by=request.user,
                    amount=form.cleaned_data["amount"],
                    note=form.cleaned_data.get("note", "").strip(),
                    debtor_name="",
                    debtor_phone="",
                    # Avtomatik approved
                    is_approved=True,
                    approved_by=request.user,
                    approved_at=dj_tz.now()
                )

            messages.success(request, _("Qarz yozildi"))
            return redirect("debt_list")
    else:
        form = DebtNewSimpleForm()

    return render(request, "sales/debt_new_simple.html", {"form": form})


@login_required
def debt_pay(request, group):
    """
    Qarz to'lovi

    URL: /debts/<uuid>/pay/
    POST: amount, payment_type, cash_amount, card_amount

    MUHIM: Balans tekshiriladi (form validation)
    """
    # UUID validation
    try:
        group_uuid = UUID(str(group))
    except:
        messages.error(request, _("Noto'g'ri identifikator"))
        return redirect("debt_list")

    # Qarzdor ma'lumotini topish
    rows = _debt_rows(request.user)
    row = next((r for r in rows if str(r["group"]) == str(group)), None)

    if not row:
        messages.error(request, _("Qarzdor topilmadi"))
        return redirect("debt_list")

    if request.method == "POST":
        # Form'ga group uzatish (balans tekshiruvi uchun)
        form = DebtPayForm(request.POST, group=group_uuid)
        if form.is_valid():
            store = _get_user_store(request.user)

            with db_transaction.atomic():
                Transaction.objects.create(
                    type="debt_pay",
                    store=store,
                    seller=request.user,
                    created_by=request.user,
                    amount=form.cleaned_data["amount"],
                    payment_type=form.cleaned_data["payment_type"],
                    cash_amount=form.cleaned_data["cash_amount"],
                    card_amount=form.cleaned_data["card_amount"],
                    debtor_name=row["debtor_name"],
                    debtor_phone=row["debtor_phone"],
                    debtor_group=group_uuid,
                    # Avtomatik approved
                    is_approved=True,
                    approved_by=request.user,
                    approved_at=dj_tz.now()
                )

            messages.success(request, _("To'lov qabul qilindi"))
            return redirect("debt_list")
        else:
            messages.error(request, _("Xatolarni tuzating"))
    else:
        form = DebtPayForm(
            initial={
                "amount": row["balance"],
                "payment_type": "cash"
            },
            group=group_uuid
        )

    context = {
        "form": form,
        "debtor_label": f"{row['debtor_name']} — {row['store_name']} / {row['seller_name']}",
        "balance": row["balance"]
    }

    return render(request, "sales/debt_pay.html", context)

