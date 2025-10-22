# sales/views_consignment.py - KONSIGNATSIYA VIEW'LARI
"""
Konsignatsiya to'lovlari (AP - Accounts Payable)

WORKFLOW:
1. Mahsulot sotilganda ConsignmentDue yaratiladi (avtomatik)
2. Owner ConsignmentDue'ni tasdiqlaydi
3. Payout yaratiladi (owner tomonidan)
4. Payout tasdiqlanganda kassadan chiqariladi

TYPES:
1. Product-based payout (mahsulotga bog'liq)
2. General payout (umumiy to'lov)
"""

import json
from decimal import Decimal
from datetime import timedelta, datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Sum, Q
from django.db.models.functions import TruncDate
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone as dj_tz
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.db import transaction as db_transaction

from sales.forms import ConsignmentPayoutForm, ConsignmentNewForm
from sales.models import Transaction, ConsignmentDue
from inventory.models import Product
from accounts.models import Store
from core.utils import is_owner, scope_by_user, safe_sum


@login_required
def consignment_list(request):
    """
    Konsignatsiya to'lovlari ro'yxati

    FEATURES:
    - Approved va Pending to'lovlar
    - Filtrlar: store, date, status, search, amount range
    - 30 kunlik trend
    - KPI: total, approved, pending
    - CSV export
    - Pagination
    """
    # Filtrlar
    store_id = request.GET.get("store_id", "").strip()
    status_filter = request.GET.get("status", "").strip()  # approved/pending/all
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    q = request.GET.get("q", "").strip()
    min_amount = request.GET.get("min_amount", "").strip()
    max_amount = request.GET.get("max_amount", "").strip()

    def _parse_date(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except:
            return None

    df = _parse_date(date_from)
    dt = _parse_date(date_to)

    # Base queryset
    qs = Transaction.objects.select_related(
        "store",
        "product__brand",
        "product__model"
    ).filter(
        type="consignment_payout",
        is_void=False
    ).order_by("-created_at")

    # Scope
    if not is_owner(request.user):
        qs = qs.filter(store_id=request.user.store_id)
    elif store_id:
        qs = qs.filter(store_id=store_id)

    # Filters
    if status_filter == "approved":
        qs = qs.filter(is_approved=True)
    elif status_filter == "pending":
        qs = qs.filter(is_approved=False)

    if df:
        qs = qs.filter(created_at__date__gte=df)
    if dt:
        qs = qs.filter(created_at__date__lte=dt)

    if q:
        qs = qs.filter(
            Q(note__icontains=q) |
            Q(product__imei_full__icontains=q) |
            Q(product__brand__name__icontains=q) |
            Q(product__model__name__icontains=q)
        )

    # Amount range
    try:
        min_amt = Decimal(min_amount) if min_amount else None
    except:
        min_amt = None
    try:
        max_amt = Decimal(max_amount) if max_amount else None
    except:
        max_amt = None

    if min_amt is not None:
        qs = qs.filter(amount__gte=min_amt)
    if max_amt is not None:
        qs = qs.filter(amount__lte=max_amt)

    # KPI
    total_count = qs.count()
    total_sum = safe_sum(qs, "amount")

    approved_qs = qs.filter(is_approved=True)
    pending_qs = qs.filter(is_approved=False)

    approved_count = approved_qs.count()
    approved_sum = safe_sum(approved_qs, "amount")

    pending_count = pending_qs.count()
    pending_sum = safe_sum(pending_qs, "amount")

    # 30 day trend (approved)
    today = dj_tz.now().date()
    start = today - timedelta(days=29)

    trend = (
        approved_qs.filter(created_at__date__range=(start, today))
        .annotate(d=TruncDate("created_at"))
        .values("d")
        .annotate(s=Sum("amount"))
        .order_by("d")
    )
    by_date = {r["d"]: float(r["s"] or 0) for r in trend}
    labels = [(start + timedelta(days=i)) for i in range(30)]
    series = [by_date.get(d, 0.0) for d in labels]

    # CSV Export
    if request.GET.get("export", "").lower() == "csv":
        import csv
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="consignment_payouts.csv"'
        w = csv.writer(resp)
        w.writerow([
            "ID", "Date", "Store", "Product", "Amount ($)", "Status", "Note"
        ])
        for t in qs:
            product_name = ""
            if t.product:
                b = getattr(t.product.brand, "name", "") if t.product.brand else ""
                m = getattr(t.product.model, "name", "") if t.product.model else ""
                product_name = f"{b} {m}".strip()

            w.writerow([
                t.id,
                t.created_at.strftime("%Y-%m-%d %H:%M"),
                t.store.name if t.store else "",
                product_name,
                f"{t.amount:.2f}",
                "Approved" if t.is_approved else "Pending",
                t.note or ""
            ])
        return resp

    # Pagination
    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get("page"))

    # Table rows
    rows = []
    for t in page_obj.object_list:
        product_name = ""
        if t.product:
            b = getattr(t.product.brand, "name", "") if t.product.brand else ""
            m = getattr(t.product.model, "name", "") if t.product.model else ""
            product_name = f"{b} {m}".strip()

        rows.append({
            "id": t.id,
            "approved": t.is_approved,
            "created_at": t.created_at,
            "store_name": t.store.name if t.store else "",
            "product_name": product_name,
            "amount": t.amount,
            "note": t.note or ""
        })

    # Reference data
    stores = None
    if is_owner(request.user):
        stores = Store.objects.filter(is_active=True).order_by("name")

    context = {
        "rows": rows,
        "page_obj": page_obj,

        # KPI
        "total_count": total_count,
        "total_sum": total_sum,
        "approved_count": approved_count,
        "approved_sum": approved_sum,
        "pending_count": pending_count,
        "pending_sum": pending_sum,

        # Filters
        "stores": stores,
        "store_id": store_id,
        "status": status_filter,
        "date_from": date_from,
        "date_to": date_to,
        "q": q,
        "min_amount": min_amount,
        "max_amount": max_amount,

        # Chart
        "chart_labels": mark_safe(json.dumps(
            [d.strftime("%Y-%m-%d") for d in labels]
        )),
        "chart_series": mark_safe(json.dumps(series)),
    }

    return render(request, "sales/consignment_list.html", context)


@login_required
def consignment_payout(request, product_id):
    """
    Mahsulotga bog'liq konsignatsiya to'lovi

    POST: amount, note

    Owner tasdig'ini kutadi
    """
    product = get_object_or_404(
        Product.objects.select_related("store"),
        pk=product_id
    )

    if request.method == "POST":
        form = ConsignmentPayoutForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data["amount"]
            note = form.cleaned_data.get("note", "").strip()

            with db_transaction.atomic():
                Transaction.objects.create(
                    type="consignment_payout",
                    store=product.store,
                    product=product,
                    seller=request.user,
                    created_by=request.user,
                    amount=amount,
                    note=note,
                    is_approved=False  # Owner tasdiqlaydi
                )

            messages.success(request, _(
                "Konsignatsiya to'lovi saqlandi (tasdig'ni kutmoqda)"
            ))
            return redirect("consignment_list")
        else:
            messages.error(request, _("Xatolarni tuzating"))
    else:
        # Initial amount = consignment_price
        form = ConsignmentPayoutForm(initial={
            "amount": product.consignment_price or Decimal("0.00")
        })

    context = {
        "form": form,
        "product": product
    }
    return render(request, "sales/consignment_payout.html", context)


@login_required
def consignment_new(request):
    """
    Umumiy konsignatsiya to'lovi (product'siz)

    POST: amount, note
    """
    if request.method == "POST":
        form = ConsignmentNewForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data["amount"]
            note = form.cleaned_data.get("note", "").strip()

            # Store
            store = getattr(request.user, "store", None)
            if not store:
                store = Store.objects.first()

            with db_transaction.atomic():
                Transaction.objects.create(
                    type="consignment_payout",
                    store=store,
                    seller=request.user,
                    created_by=request.user,
                    amount=amount,
                    note=note,
                    is_approved=False  # Owner tasdiqlaydi
                )

            messages.success(request, _(
                "Konsignatsiya to'lovi saqlandi (tasdig'ni kutmoqda)"
            ))
            return redirect("consignment_list")
        else:
            messages.error(request, _("Xatolarni tuzating"))
    else:
        form = ConsignmentNewForm()

    return render(request, "sales/consignment_new.html", {"form": form})


@login_required
def consignment_approve(request, tx_id):
    """
    Konsignatsiya to'lovini tasdiqlash (owner)

    POST: payment_type, cash_amount, card_amount (optional)

    Tasdiqlanganda kassadan chiqariladi va ledgerga yoziladi
    """
    if not is_owner(request.user):
        return HttpResponseForbidden(_("Faqat owner tasdiqlashi mumkin"))

    if request.method != "POST":
        return redirect("consignment_list")

    tx = get_object_or_404(
        Transaction,
        pk=tx_id,
        type="consignment_payout",
        is_void=False,
        is_approved=False
    )

    # Payment channel
    ptype = request.POST.get("payment_type", "").strip() or "cash"

    try:
        from core.utils import parse_decimal
        cash_amt = parse_decimal(request.POST.get("cash_amount", "0"))
        card_amt = parse_decimal(request.POST.get("card_amount", "0"))
    except:
        cash_amt = Decimal("0.00")
        card_amt = Decimal("0.00")

    # Default: all cash
    if ptype == "cash":
        cash_amt = tx.amount
        card_amt = Decimal("0.00")
    elif ptype == "card":
        card_amt = tx.amount
        cash_amt = Decimal("0.00")
    elif ptype == "mixed":
        if (cash_amt + card_amt) != tx.amount:
            messages.error(request, _(
                "Naqd + Karta = To'lov summasi bo'lishi kerak"
            ))
            return redirect("consignment_list")
    else:
        # Default cash
        ptype = "cash"
        cash_amt = tx.amount
        card_amt = Decimal("0.00")

    # Ledgerga yozish
    try:
        from finance.adapters import post_payment_to_supplier_split
        post_payment_to_supplier_split(
            obj_or_ids=tx,
            cash_amount=cash_amt,
            card_amount=card_amt,
            ref=f"sales.Transaction:{tx.pk}",
            memo="Konsignatsiya to'lovi"
        )
    except Exception as e:
        messages.error(request, f"Ledger xatosi: {e}")
        return redirect("consignment_list")

    # Transaction yangilash
    tx.payment_type = ptype
    tx.cash_amount = cash_amt
    tx.card_amount = card_amt
    tx.is_approved = True
    tx.approved_by = request.user
    tx.approved_at = dj_tz.now()
    tx.save(update_fields=[
        "payment_type", "cash_amount", "card_amount",
        "is_approved", "approved_by", "approved_at"
    ])

    messages.success(request, _("To'lov tasdiqlandi va kassadan yechildi"))
    return redirect("consignment_list")


@login_required
def consignment_reject(request, tx_id):
    """
    Konsignatsiya to'lovini rad etish
    """
    if not is_owner(request.user):
        return HttpResponseForbidden(_("Faqat owner rad eta oladi"))

    if request.method != "POST":
        return redirect("consignment_list")

    tx = get_object_or_404(
        Transaction,
        pk=tx_id,
        type="consignment_payout",
        is_void=False,
        is_approved=False
    )

    # Void qilish (soft delete)
    tx.is_void = True
    tx.save(update_fields=["is_void"])

    messages.success(request, _("To'lov rad etildi"))
    return redirect("consignment_list")


@login_required
def cons_due_approve(request, product_id):
    """
    ConsignmentDue'ni tasdiqlash (owner)

    Bu faqat metrika - payout alohida yaratiladi
    """
    if not is_owner(request.user):
        return HttpResponseForbidden(_("Faqat owner tasdiqlashi mumkin"))

    due = get_object_or_404(ConsignmentDue, product_id=product_id)

    if not due.is_approved:
        due.is_approved = True
        due.approved_by = request.user
        due.approved_at = dj_tz.now()
        due.save(update_fields=["is_approved", "approved_by", "approved_at"])
        messages.success(request, _("Due tasdiqlandi"))
    else:
        messages.info(request, _("Allaqachon tasdiqlangan"))

    return redirect("consignment_list")


@login_required
def cons_due_reject(request, product_id):
    """
    ConsignmentDue'ni rad etish (o'chirish)
    """
    if not is_owner(request.user):
        return HttpResponseForbidden(_("Faqat owner rad eta oladi"))

    due = get_object_or_404(ConsignmentDue, product_id=product_id)

    if due.is_approved:
        messages.error(request, _(
            "Tasdiqlangan due'ni bu yerda o'chirib bo'lmaydi"
        ))
    else:
        due.delete()
        messages.success(request, _("Due o'chirildi"))

    return redirect("consignment_list")