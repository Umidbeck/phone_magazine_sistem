# sales/views_expense.py - RASHOD VIEW'LARI
"""
Rashod (expense) operatsiyalari

WORKFLOW:
1. Rashod yaratish (product bilan yoki product'siz)
2. Owner tasdiqlaydi (payment channel tanlab)
3. Tasdiqlanganda ledgerga yoziladi
4. Kassadan ayriladi

MUHIM:
- Product'siz expense → period expense (P&L'ga kiradi)
- Product bilan expense → COGS'ga kiradi (product tannarxini oshiradi)
"""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q
from django.db.models.functions import TruncDate
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone as dj_tz
from django.utils.translation import gettext as _
from django.db import transaction as db_transaction

from inventory.models import Product
from sales.forms import ExpenseForm
from sales.models import Transaction
from accounts.models import Store, User
from core.utils import is_owner, scope_by_user, safe_sum
from datetime import timedelta, datetime


@login_required
def expense_create(request):
    """
    Yangi rashod yaratish

    GET ?product_id=123 → product'ga bog'lash (COGS)
    POST: amount, note

    COGS vs Period Expense:
    - product_id mavjud → COGS (product tannarxiga qo'shiladi)
    - product_id yo'q → Period expense (P&L'ga kiradi)
    """
    # Product qidirish (optional)
    q = (request.GET.get("q") or "").strip()
    products = []
    picked_product = None

    product_id = request.GET.get("product_id") or request.POST.get("product_id")
    if product_id:
        try:
            picked_product = Product.objects.select_related(
                "brand", "model", "store"
            ).get(pk=product_id)
        except Product.DoesNotExist:
            messages.warning(request, _("Mahsulot topilmadi"))

    # Qidiruv (agar picked_product yo'q bo'lsa)
    if q and not picked_product:
        from core.utils import digits_only
        q_digits = digits_only(q)

        base = Product.objects.select_related("brand", "model", "store")
        base = scope_by_user(base, request.user)

        products = list(base.filter(
            Q(imei_full__icontains=q_digits) |
            Q(brand__name__icontains=q) |
            Q(model__name__icontains=q)
        ).order_by("-created_at")[:50])

    if request.method == "POST":
        form = ExpenseForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data["amount"]
            note = form.cleaned_data.get("note", "").strip()

            # Store aniqlash
            if picked_product:
                expense_store = picked_product.store
            else:
                # User'ning do'koni yoki default
                expense_store = getattr(request.user, "store", None)
                if not expense_store:
                    expense_store = Store.objects.first()

            with db_transaction.atomic():
                Transaction.objects.create(
                    type="expense",
                    product=picked_product,
                    store=expense_store,
                    seller=request.user,
                    created_by=request.user,
                    amount=amount,
                    note=note,
                    is_approved=False  # Owner tasdiqlashi kerak
                )

            messages.success(request, _(
                "Rashod saqlandi. Owner tasdig'ini kutmoqda."
            ))
            return redirect("expenses_list")
        else:
            messages.error(request, _("Xatolarni tuzating"))
    else:
        form = ExpenseForm(initial={"product_id": product_id})

    context = {
        "form": form,
        "q": q,
        "products": products,
        "picked_product": picked_product
    }
    return render(request, "sales/expense_form.html", context)


@login_required
def expenses_list(request):
    """
    Rashodlar ro'yxati va statistika

    FEATURES:
    - Ikki jadval: Approved va Pending
    - Filtrlar: store, seller, date, status
    - KPI kartalar: Today approved vs pending
    - 7/30 kunlik grafik
    """
    # Filtrlar
    store_id = request.GET.get("store_id", "").strip()
    seller_id = request.GET.get("seller_id", "").strip()
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
    base = Transaction.objects.select_related(
        "product", "store", "seller", "expense_type",
        "product__brand", "product__model"
    ).filter(type="expense").order_by("-created_at")

    # Scope
    if not is_owner(request.user):
        base = base.filter(created_by=request.user)
    else:
        if store_id:
            base = base.filter(store_id=store_id)
        if seller_id:
            base = base.filter(seller_id=seller_id)

    if df:
        base = base.filter(created_at__date__gte=df)
    if dt:
        base = base.filter(created_at__date__lte=dt)

    # Approved vs Pending
    approved_qs = base.filter(is_approved=True)
    pending_qs = base.filter(is_approved=False)

    # KPI - Today
    today = dj_tz.now().date()
    today_approved = safe_sum(
        approved_qs.filter(created_at__date=today),
        "amount"
    )
    today_pending = safe_sum(
        pending_qs.filter(created_at__date=today),
        "amount"
    )

    # Grafik ma'lumotlari (30 kun)
    def _series(qs, days=30):
        start = today - timedelta(days=days - 1)
        rows = (
            qs.filter(created_at__date__range=(start, today))
            .annotate(d=TruncDate("created_at"))
            .values("d")
            .annotate(s=Sum("amount"))
            .order_by("d")
        )
        by_date = {r["d"]: float(r["s"] or 0) for r in rows}
        labels = [(start + timedelta(days=i)) for i in range(days)]
        series = [by_date.get(d, 0.0) for d in labels]
        total = sum(series)
        return labels, series, total

    labels_30, approved_30, total_approved_30 = _series(approved_qs, 30)
    _, pending_30, total_pending_30 = _series(pending_qs, 30)
    labels_7, approved_7, total_approved_7 = _series(approved_qs, 7)
    _, pending_7, total_pending_7 = _series(pending_qs, 7)

    # Lists
    approved_list = list(approved_qs[:500])
    pending_list = list(pending_qs[:500])

    # Filters for template
    stores = None
    sellers = None
    if is_owner(request.user):
        stores = Store.objects.filter(is_active=True).order_by("name")
        sellers = User.objects.filter(is_active=True).order_by("username")

    context = {
        "approved": approved_list,
        "pending": pending_list,

        "stores": stores,
        "sellers": sellers,
        "store_id": store_id,
        "seller_id": seller_id,
        "date_from": date_from,
        "date_to": date_to,

        # KPI
        "today_approved": today_approved,
        "today_pending": today_pending,

        # Series
        "labels_7": [d.strftime("%Y-%m-%d") for d in labels_7],
        "approved_7": approved_7,
        "pending_7": pending_7,
        "total_approved_7": total_approved_7,
        "total_pending_7": total_pending_7,

        "labels_30": [d.strftime("%Y-%m-%d") for d in labels_30],
        "approved_30": approved_30,
        "pending_30": pending_30,
        "total_approved_30": total_approved_30,
        "total_pending_30": total_pending_30,
    }

    return render(request, "sales/expenses_list.html", context)


@login_required
def expense_approve(request, tx_id):
    """
    Rashodini tasdiqlash (owner)

    POST: payment_type, cash_amount, card_amount

    Workflow:
    1. Payment channel tanlanadi
    2. Ledgerga yoziladi
    3. Transaction approved bo'ladi
    """
    if not is_owner(request.user):
        return HttpResponseForbidden(_("Faqat owner tasdiqlashi mumkin"))

    tx = get_object_or_404(
        Transaction,
        pk=tx_id,
        type="expense",
        is_approved=False
    )

    if request.method != "POST":
        return redirect("expenses_list")

    ptype = (request.POST.get("payment_type") or "").strip()

    try:
        cash_amt = Decimal(request.POST.get("cash_amount") or "0")
        card_amt = Decimal(request.POST.get("card_amount") or "0")
    except:
        messages.error(request, _("Summalarni to'g'ri kiriting"))
        return redirect("expenses_list")

    # Validation
    if ptype == "cash":
        if cash_amt != tx.amount:
            messages.error(request, _("Naqd summa rashod summasiga teng bo'lishi kerak"))
            return redirect("expenses_list")
        card_amt = Decimal("0.00")
    elif ptype == "card":
        if card_amt != tx.amount:
            messages.error(request, _("Karta summa rashod summasiga teng bo'lishi kerak"))
            return redirect("expenses_list")
        cash_amt = Decimal("0.00")
    elif ptype == "mixed":
        if (cash_amt + card_amt) != tx.amount:
            messages.error(request, _("Naqd + Karta = Rashod summasi bo'lishi kerak"))
            return redirect("expenses_list")
    else:
        messages.error(request, _("To'lov turini tanlang"))
        return redirect("expenses_list")

    # Ledgerga yozish
    try:
        from finance.adapters import (
            post_expense_from_transaction,
            post_expense_from_transaction_split
        )

        if ptype == "cash":
            post_expense_from_transaction(
                tx,
                amount=tx.amount,
                is_cash=True,
                memo="Rashod (Naqd)"
            )
        elif ptype == "card":
            post_expense_from_transaction_split(
                tx,
                cash_amount=Decimal("0.00"),
                card_amount=tx.amount,
                memo="Rashod (Karta)"
            )
        else:  # mixed
            post_expense_from_transaction_split(
                tx,
                cash_amount=cash_amt,
                card_amount=card_amt,
                memo="Rashod (Aralash)"
            )
    except Exception as e:
        messages.error(request, f"Ledger xatosi: {e}")
        return redirect("expenses_list")

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

    messages.success(request, _("Rashod tasdiqlandi va kassadan yechildi"))
    return redirect("expenses_list")


@login_required
def expense_reject(request, tx_id):
    """
    Rashodini rad etish (o'chirish)
    """
    if not is_owner(request.user):
        return HttpResponseForbidden(_("Faqat owner rad eta oladi"))

    tx = get_object_or_404(
        Transaction,
        pk=tx_id,
        type="expense",
        is_approved=False
    )

    if request.method == "POST":
        tx.delete()
        messages.success(request, _("Rashod o'chirildi"))

    return redirect("expenses_list")


@login_required
def expense_unapprove(request, tx_id):
    """
    Tasdiqlangan rashodini bekor qilish

    DIQQAT: Bu ledger'ni buzadi!
    Faqat xato holatlarda ishlatilishi kerak
    """
    if not is_owner(request.user):
        return HttpResponseForbidden(_("Faqat owner bekor qila oladi"))

    tx = get_object_or_404(
        Transaction,
        pk=tx_id,
        type="expense",
        is_approved=True
    )

    if request.method == "POST":
        tx.is_approved = False
        tx.approved_by = None
        tx.approved_at = None
        tx.save(update_fields=["is_approved", "approved_by", "approved_at"])

        messages.warning(request, _(
            "Rashod tasdig'i bekor qilindi. "
            "DIQQAT: Ledger va kassa hisoblari noto'g'ri bo'lishi mumkin!"
        ))

    return redirect("expenses_list")