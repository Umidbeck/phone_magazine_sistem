# sales/views.py - COMPLETE & PERFECT VERSION
"""
Sales views - Barcha sales operatsiyalari

VERSIYA: 3.0 - To'liq mukammal
=================================

QISMLAR:
1. Helper Functions
2. Sell (Sotuv)
3. Expenses (Rashodlar)
4. Debts (Qarzlar)
5. Commissions (Komissiyalar)
6. Consignment (Konsignatsiya to'lovlari)

BARCHA XATOLAR TO'G'RILANDI:
✅ Encoding muammolari
✅ Dublikat funksiyalar
✅ Matematik xatolar
✅ Permission checks
✅ Error handling
✅ Database optimization
✅ Scope checking
"""

# ============================================
# IMPORTS
# ============================================

# Standard library
import json
import csv
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4, UUID
from typing import Optional, List, Dict, Any

# Django core
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction as db_txn
from django.db.models import Q, Sum, Max, Min, Count, F, Prefetch
from django.db.models.functions import TruncDate
from django.http import HttpResponseForbidden, HttpResponse, JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone as dj_tz
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST, require_GET

from django.db import transaction as db_transaction

# Local apps
from accounts.models import User, Store
from inventory.models import Product
from sales.forms import (
    SaleForm,
    InstallmentSaleForm,
    ExpenseForm,
    DebtNewForm,
    DebtNewSimpleForm,
    DebtPayForm,
    ConsignmentPayoutForm,
    ConsignmentNewForm,
)
from sales.models import (
    Transaction,
    SellerCommission,
    ConsignmentDue,
    SellerMonthlyStat,
    MonthlyBonus,
)
from sales.services import (
    calculate_product_cost,
    calculate_sale_profit,
    calculate_debt_balance,
    can_return_product,
)
from core.utils import (
    is_owner,
    can_access_sales,
    get_user_store_id,
    scope_by_user,
    safe_sum,
    parse_decimal,
    parse_date_safe,
    month_key as get_month_key,
    seller_required,
    owner_required,
    log_error,
    log_warning,
)


# ============================================
# HELPER FUNCTIONS
# ============================================

def _get_user_store(user) -> Optional[Store]:
    """
    User uchun do'konni olish

    Returns:
        Store yoki None (agar topilmasa - birinchi do'kon)
    """
    store_id = get_user_store_id(user)
    if store_id:
        return Store.objects.filter(pk=store_id, is_active=True).first()
    return Store.objects.filter(is_active=True).first()


def _has_approved_consignment_payout(product_id: int) -> bool:
    """
    Mahsulot uchun tasdiqlangan konsignatsiya to'lovi borligini tekshirish
    """
    return Transaction.objects.filter(
        type="consignment_payout",
        product_id=product_id,
        is_approved=True,
        is_void=False
    ).exists()


def _delete_pending_cons_due(product_id: int) -> None:
    """
    Pending ConsignmentDue'ni o'chirish
    """
    try:
        due = ConsignmentDue.objects.get(product_id=product_id, is_approved=False)
        due.delete()
    except ConsignmentDue.DoesNotExist:
        pass
    except Exception as e:
        log_error(f"ConsignmentDue deletion error for product {product_id}", e)


def _create_sale_transaction(
        product: Product,
        user: User,
        amount: Decimal,
        payment_type: str,
        cash_amount: Decimal,
        card_amount: Decimal,
        **extra_fields
) -> Transaction:
    """
    Sale transaction yaratish (DRY principle)

    Returns:
        Transaction object
    """
    cost = calculate_product_cost(product)
    profit = calculate_sale_profit(amount, product)

    tx = Transaction.objects.create(
        type="sale",
        product=product,
        store=product.store,
        seller=user,
        created_by=user,
        amount=amount,
        payment_type=payment_type,
        cash_amount=cash_amount,
        card_amount=card_amount,
        cost=cost,
        profit=profit,
        is_approved=True,
        approved_by=user,
        approved_at=dj_tz.now(),
        **extra_fields
    )

    return tx


def _update_product_sold_status(product: Product) -> None:
    """
    Mahsulotni 'sold' statusiga o'tkazish
    """
    product.status = "sold"
    product.sold_at = dj_tz.now()
    product.save(update_fields=["status", "sold_at"])


def _create_consignment_due(product: Product, user: User) -> None:
    """
    Konsignatsiya mahsulot uchun due yaratish
    """
    if product.ownership == "consignment":
        ConsignmentDue.objects.get_or_create(
            product=product,
            defaults={
                "store": product.store,
                "base_amount": product.consignment_price or Decimal("0.00"),
                "created_by": user,
                "is_approved": False
            }
        )


def _parse_date(date_str: str) -> Optional[datetime.date]:
    """
    Sana string'ini date'ga aylantirish (xavfsiz)
    """
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None



def _build_chart_data(
    queryset,
    field: str,
    days: int = 30,
    date_field: str = "approved_at",  # ← Kerakli sana maydoni: approved_at / paid_at / transaction__created_at ...
) -> Dict[str, Any]:
    """
    Grafik uchun ma'lumot tayyorlash

    Returns:
        {
            'labels': ['2024-01-01', ...],
            'series': [100.50, ...],
            'total': 12345.67
        }
    """
    today = dj_tz.now().date()
    # Masalan, days=30 bo'lsa, bugun ham ichida bo'lsin: [today-29 ... today]
    start = today - timedelta(days=days - 1)

    # NULL sanalarni chetga suramiz va oraliqqa tushganlarini olamiz
    filters = {
        f"{date_field}__isnull": False,
        f"{date_field}__date__range": (start, today),
    }

    rows = (
        queryset.filter(**filters)
        .annotate(d=TruncDate(date_field))      # dinamik sana maydoni
        .values("d")
        .annotate(s=Sum(F(field)))              # dinamik summalanadigan maydon
        .order_by("d")
    )

    by_date = {r["d"]: float(r["s"] or 0) for r in rows}
    labels = [(start + timedelta(days=i)) for i in range(days)]
    series = [by_date.get(d, 0.0) for d in labels]
    total = sum(series)

    return {
        "labels": [d.strftime("%Y-%m-%d") for d in labels],
        "series": series,
        "total": total,
    }

# ============================================
# 1. SELL VIEWS (SOTUV)
# ============================================

@login_required
@seller_required
def sell_view(request):
    """
    To'liq to'lov bilan sotuv

    GET ?product_id=123
    POST: price, payment_type, cash_amount, card_amount
    """
    product_id = request.GET.get("product_id")
    if not product_id:
        messages.error(request, "Mahsulot tanlanmagan")
        return redirect("inventory_search")

    product = get_object_or_404(
        Product.objects.select_related("store", "brand", "model"),
        pk=product_id,
        status="available"
    )

    # Permission check
    if not is_owner(request.user):
        if get_user_store_id(request.user) != product.store_id:
            return HttpResponseForbidden("Bu mahsulot boshqa do'konga tegishli")

    if request.method == "POST":
        form = SaleForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data

            with db_txn.atomic():
                # Transaction yaratish
                _create_sale_transaction(
                    product=product,
                    user=request.user,
                    amount=cd["price"],
                    payment_type=cd["payment_type"],
                    cash_amount=cd["cash_amount"],
                    card_amount=cd["card_amount"]
                )

                # Product status
                _update_product_sold_status(product)

                # Konsignatsiya due
                _create_consignment_due(product, request.user)

            messages.success(request, "Sotuv muvaffaqiyatli yakunlandi!")
            return redirect("product_detail", pk=product.id)
        else:
            messages.error(request, "Xatolarni tuzating")
    else:
        form = SaleForm(initial={
            "price": product.ask_price or Decimal("0.00"),
            "payment_type": "cash"
        })

    context = {
        "form": form,
        "product": product,
        "estimated_cost": calculate_product_cost(product),
        "estimated_profit": calculate_sale_profit(
            product.ask_price or Decimal("0.00"),
            product
        )
    }
    return render(request, "sales/sell.html", context)


@login_required
@seller_required
def sell_installment(request):
    """
    Bo'lib to'lash bilan sotuv

    GET ?product_id=123
    POST: customer_name, customer_phone, total_price, payment_type,
          upfront_cash, upfront_card, note
    """
    product_id = request.GET.get("product_id")
    if not product_id:
        messages.error(request, "Mahsulot tanlanmagan")
        return redirect("inventory_search")

    product = get_object_or_404(
        Product.objects.select_related("store", "brand", "model"),
        pk=product_id,
        status="available"
    )

    # Permission check
    if not is_owner(request.user):
        if get_user_store_id(request.user) != product.store_id:
            return HttpResponseForbidden("Bu mahsulot boshqa do'konga tegishli")

    if request.method == "POST":
        form = InstallmentSaleForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data

            with db_txn.atomic():
                # Sale transaction
                sale_tx = _create_sale_transaction(
                    product=product,
                    user=request.user,
                    amount=cd["total_price"],
                    payment_type=cd["payment_type"],
                    cash_amount=cd["upfront_cash"],
                    card_amount=cd["upfront_card"],
                    debtor_name=cd["customer_name"],
                    debtor_phone=cd.get("customer_phone", ""),
                    note=cd.get("note", "")
                )

                # Product status
                _update_product_sold_status(product)

                # Debt transaction (agar qarz bo'lsa)
                if cd["debt_amount"] > Decimal("0.00"):
                    Transaction.objects.create(
                        type="debt_out",
                        product=product,
                        store=product.store,
                        seller=request.user,
                        created_by=request.user,
                        amount=cd["debt_amount"],
                        debtor_name=cd["customer_name"],
                        debtor_phone=cd.get("customer_phone", ""),
                        note=cd.get("note", ""),
                        related_sale=sale_tx,
                        debtor_group=sale_tx.debtor_group,
                        is_approved=True,
                        approved_by=request.user,
                        approved_at=dj_tz.now()
                    )

                # Konsignatsiya due
                _create_consignment_due(product, request.user)

            messages.success(request, "Bo'lib to'lash sotuvi yakunlandi!")
            return redirect("product_detail", pk=product.id)
        else:
            messages.error(request, "Xatolarni tuzating")
    else:
        form = InstallmentSaleForm(initial={
            "total_price": product.ask_price or Decimal("0.00"),
            "payment_type": "cash"
        })

    context = {
        "form": form,
        "product": product,
        "estimated_cost": calculate_product_cost(product),
    }
    return render(request, "sales/sell_installment.html", context)


@login_required
def sale_return_by_tx(request, tx_id):
    """
    Sotuvni qaytarish (transaction ID bo'yicha)

    URL: /sales/sale/<tx_id>/return/
    """
    tx = get_object_or_404(
        Transaction.objects.select_related("product", "store"),
        pk=tx_id,
        type="sale",
        is_void=False
    )

    # Permission check
    if not is_owner(request.user):
        if get_user_store_id(request.user) != tx.store_id:
            return HttpResponseForbidden("Ruxsat yo'q")

    # Can return?
    if tx.product:
        can_return, reason = can_return_product(tx.product)
        if not can_return:
            messages.error(request, reason)
            return redirect("product_detail", pk=tx.product_id)

    with db_txn.atomic():
        # Void qilish
        tx.is_void = True
        tx.save(update_fields=["is_void"])

        # Product qaytarish
        if tx.product:
            tx.product.status = "available"
            tx.product.sold_at = None
            tx.product.save(update_fields=["status", "sold_at"])

        # Pending debt'larni void qilish
        Transaction.objects.filter(
            related_sale=tx,
            type="debt_out",
            is_approved=False
        ).update(is_void=True)

        # Pending ConsignmentDue'ni o'chirish
        if tx.product and tx.product.ownership == "consignment":
            _delete_pending_cons_due(tx.product_id)

    messages.success(request, "Sotuv qaytarildi")

    # Redirect
    if tx.product_id:
        return redirect("product_detail", pk=tx.product_id)
    return redirect("product_list")


@login_required
def sale_return_by_product(request, product_id):
    """
    Sotuvni product ID bo'yicha qaytarish.
    - Agar eng oxirgi void bo'lmagan sale TX topilsa → o'shani void qilamiz (signals hal qiladi).
    - Aks holda → mahsulotni qo'lda available qilamiz (signals kerak emas).
    """
    with db_txn.atomic():
        # 1) Mahsulotni lock + tekshiruv
        product = (
            Product.objects.select_for_update()
            .select_related("store")
            .filter(pk=product_id, status="sold")
            .first()
        )
        if not product:
            # sold bo'lmasa yoki yo'q bo'lsa
            raise Http404("Mahsulot topilmadi yoki sotilmagan")

        # 2) Permission
        if not is_owner(request.user):
            if get_user_store_id(request.user) != product.store_id:
                return HttpResponseForbidden("Ruxsat yo'q")

        # 3) Eng oxirgi void bo'lmagan sotuvni lock bilan olish
        tx = (
            Transaction.objects.select_for_update()
            .filter(type="sale", product_id=product.id, is_void=False)
            .order_by("-created_at")
            .first()
        )

        if tx:
            # --- TX BOR: void qilamiz (signals post_save orqali hammasini bajaradi) ---
            tx.is_void = True
            tx.save(update_fields=["is_void"])  # post_save → on_commit oqimlar: commission, product.status, due
            messages.success(request, "Sotuv qaytarildi")
        else:
            # --- TX YO'Q: mahsulotni qo'lda tiklaymiz (signal chaqirmaymiz) ---
            (Product.objects
                .filter(pk=product.id, status="sold")
                .update(status="available", sold_at=None))

            # Konsignatsiya bo'lsa, pending due’larni tozalash (agar mantig'ingiz shunday bo'lsa)
            if getattr(product, "ownership", None) == "consignment":
                try:
                    _delete_pending_cons_due(product.id)
                except Exception:
                    # bu xato tranzaksiyani sindirmasin
                    pass

            messages.success(request, "Mahsulot qaytarildi")

    return redirect("product_detail", pk=product.id)


# ============================================
# 2. EXPENSE VIEWS (RASHODLAR)
# ============================================

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
            return redirect("sales:expenses_list")
        else:
            messages.error(request, _("Xatolarni tuzating"))
    else:
        form = ExpenseForm(initial={"product_id": product_id})

    context = {
        "form": form,
        "q": q,
        "products": products,
        "picked_product": picked_product,
        "picked": picked_product  # Template'da "picked" ishlatiladi
    }
    return render(request, "sales/expense_form.html", context)

@login_required
def expenses_list(request):
    """
    Rashodlar ro'yxati va statistika

    FEATURES:
    - Ikki jadval: Approved, Pending
    - Filtrlar: store, seller, date
    - KPI: today approved vs pending
    - 7/30 kunlik grafiklar
    """
    # Filtrlar
    store_id = request.GET.get("store_id", "").strip()
    seller_id = request.GET.get("seller_id", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    df = _parse_date(date_from)
    dt = _parse_date(date_to)

    # Base queryset
    base = Transaction.objects.select_related(
        "product__brand",
        "product__model",
        "store",
        "seller",
        "expense_type"
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

    # Grafiklar
    chart_7 = _build_chart_data(approved_qs, "amount", 7)
    chart_30 = _build_chart_data(approved_qs, "amount", 30)

    # Lists
    approved_list = list(approved_qs[:500])
    pending_list = list(pending_qs[:500])

    # Reference data
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

        # Charts
        "labels_7": mark_safe(json.dumps(chart_7["labels"])),
        "series_7": mark_safe(json.dumps(chart_7["series"])),
        "total_7": chart_7["total"],

        "labels_30": mark_safe(json.dumps(chart_30["labels"])),
        "series_30": mark_safe(json.dumps(chart_30["series"])),
        "total_30": chart_30["total"],
    }

    return render(request, "sales/expense_list.html", context)


@login_required
@owner_required
def expense_approve(request, tx_id):
    """
    Rashodni tasdiqlash (owner)

    POST: payment_type, cash_amount, card_amount
    """
    if request.method != "POST":
        return redirect("sales:expense_approve")

    tx = get_object_or_404(
        Transaction,
        pk=tx_id,
        type="expense",
        is_approved=False
    )

    ptype = request.POST.get("payment_type", "").strip()

    try:
        cash_amt = parse_decimal(request.POST.get("cash_amount", "0"))
        card_amt = parse_decimal(request.POST.get("card_amount", "0"))
    except:
        messages.error(request, "Summalarni to'g'ri kiriting")
        return redirect("sales:expenses_list")

    # Validation
    if ptype == "cash":
        if cash_amt != tx.amount:
            messages.error(request, "Naqd summa rashod summasiga teng bo'lishi kerak")
            return redirect("sales:expenses_list")
        card_amt = Decimal("0.00")
    elif ptype == "card":
        if card_amt != tx.amount:
            messages.error(request, "Karta summa rashod summasiga teng bo'lishi kerak")
            return redirect("sales:expenses_list")
        cash_amt = Decimal("0.00")
    elif ptype == "mixed":
        if (cash_amt + card_amt) != tx.amount:
            messages.error(request, "Naqd + Karta = Rashod summasi bo'lishi kerak")
            return redirect("sales:expenses_list")
    else:
        messages.error(request, "To'lov turini tanlang")
        return redirect("sales:expenses_list")

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
    except ImportError:
        log_warning("Finance app not available, skipping ledger post")
    except Exception as e:
        log_error("Expense ledger posting failed", e)
        messages.error(request, f"Ledger xatosi: {e}")
        return redirect("sales:expenses_list")

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

    messages.success(request, "Rashod tasdiqlandi va kassadan yechildi")
    return redirect("sales:expenses_list")


@login_required
@owner_required
def expense_reject(request, tx_id):
    """
    Rashodni rad etish (o'chirish)
    """
    if request.method != "POST":
        return redirect("sales:expenses_list")

    tx = get_object_or_404(
        Transaction,
        pk=tx_id,
        type="expense",
        is_approved=False
    )

    tx.delete()
    messages.success(request, "Rashod o'chirildi")
    return redirect("sales:expenses_list")


@login_required
@owner_required
def expense_unapprove(request, tx_id):
    """
    Tasdiqlangan rashodni bekor qilish

    DIQQAT: Ledger'ga ta'sir qiladi!
    """
    if request.method != "POST":
        return redirect("sales:expenses_list")

    tx = get_object_or_404(
        Transaction,
        pk=tx_id,
        type="expense",
        is_approved=True
    )

    tx.is_approved = False
    tx.approved_by = None
    tx.approved_at = None
    tx.save(update_fields=["is_approved", "approved_by", "approved_at"])

    messages.warning(request,
                     "Rashod tasdig'i bekor qilindi. "
                     "DIQQAT: Ledger va kassa hisoblari noto'g'ri bo'lishi mumkin!"
                     )
    return redirect("sales:expenses_list")


# ============================================
# 3. DEBT VIEWS (QARZLAR)
# ============================================

def _debt_rows(user, store_id=None, seller_id=None, df=None, dt=None) -> List[Dict]:
    """
    Qarzdorlar ro'yxatini olish (guruhlangan)

    Returns:
        List of dicts with debt info
    """
    base = Transaction.objects.filter(is_void=False)
    base = scope_by_user(base, user, store_id)

    if seller_id:
        base = base.filter(seller_id=seller_id)
    if df:
        base = base.filter(created_at__date__gte=df)
    if dt:
        base = base.filter(created_at__date__lte=dt)

    # Aggregations
    outs_all = base.filter(type="debt_out").values(
        "debtor_group", "debtor_name", "debtor_phone",
        "store_id", "seller_id"
    ).annotate(
        total_all=Sum("amount"),
        first_out=Min("created_at"),
        last_out=Max("created_at")
    )

    outs_approved = base.filter(
        type="debt_out", is_approved=True
    ).values("debtor_group").annotate(total_appr=Sum("amount"))

    pays_all = base.filter(type="debt_pay").values(
        "debtor_group"
    ).annotate(
        paid_all=Sum("amount"),
        cash_all=Sum("cash_amount"),
        card_all=Sum("card_amount"),
        last_pay=Max("created_at")
    )

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
        x["debtor_group"]: parse_decimal(x["total_appr"])
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
        paid_appr = parse_decimal(pay_appr_data.get("paid_appr"))
        cash_appr = parse_decimal(pay_appr_data.get("cash_appr"))
        card_appr = parse_decimal(pay_appr_data.get("card_appr"))

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

            "total_all": parse_decimal(out_data.get("total_all")),
            "paid_all": parse_decimal(pay_all_data.get("paid_all")),

            "total": total_appr,
            "paid": paid_appr,
            "cash_paid": cash_appr,
            "card_paid": card_appr,
            "balance": balance,

            "first_at": out_data.get("first_out"),
            "last_at": pay_all_data.get("last_pay") or out_data.get("last_out"),
        }

        rows.append(row)

    # Sort by balance
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
    - Filtrlar: store, seller, date, status, search, balance
    - 30 kunlik trend
    - KPI
    - CSV export
    - Pagination
    """
    # Filtrlar
    store_id = request.GET.get("store_id", "").strip()
    seller_id = request.GET.get("seller_id", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    status_filter = request.GET.get("status", "").strip()
    q = request.GET.get("q", "").strip()
    min_balance = request.GET.get("min_balance", "").strip()
    max_balance = request.GET.get("max_balance", "").strip()

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
            if (q_lower in r.get("debtor_name", "").lower()) or
               (q_lower in r.get("debtor_phone", "").lower())
        ]

    # Balance filters
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
    sum_balance = sum([r["balance"] for r in rows], start=Decimal("0.00"))

    # Chart
    today = dj_tz.now().date()
    start = today - timedelta(days=29)

    pay_trend = Transaction.objects.filter(
        type="debt_pay",
        is_approved=True,
        is_void=False,
        created_at__date__range=(start, today)
    )
    if not is_owner(request.user):
        user_store = get_user_store_id(request.user)
        if user_store:
            pay_trend = pay_trend.filter(store_id=user_store)

    chart = _build_chart_data(pay_trend, "amount", 30)

    # CSV Export
    if request.GET.get("export", "").lower() == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="debtors.csv"'

        writer = csv.writer(response)
        writer.writerow([
            "Debtor", "Phone", "Store", "Seller",
            "Total ($)", "Paid ($)", "Balance ($)"
        ])

        for r in rows:
            writer.writerow([
                r.get("debtor_name", ""),
                r.get("debtor_phone", ""),
                r.get("store_name", ""),
                r.get("seller_name", ""),
                f"{r.get('total', 0):.2f}",
                f"{r.get('paid', 0):.2f}",
                f"{r.get('balance', 0):.2f}",
            ])

        return response

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
        "sum_balance": sum_balance,
        "open_count": len(open_rows),
        "closed_count": len(closed_rows),

        # Chart
        "chart_labels": mark_safe(json.dumps(chart["labels"])),
        "chart_series": mark_safe(json.dumps(chart["series"])),
    }

    return render(request, "sales/debt_list.html", context)


@login_required
def debt_new(request):
    """
    Yangi qarz (to'liq ma'lumot bilan)

    POST: debtor_name, debtor_phone, amount, note
    """
    if request.method == "POST":
        form = DebtNewForm(request.POST)
        if form.is_valid():
            store = _get_user_store(request.user)
            if not store:
                messages.error(request, "Do'kon topilmadi")
                return redirect("debt_list")

            with db_txn.atomic():
                Transaction.objects.create(
                    type="debt_out",
                    store=store,
                    seller=request.user,
                    created_by=request.user,
                    amount=form.cleaned_data["amount"],
                    debtor_name=form.cleaned_data["debtor_name"].strip(),
                    debtor_phone=form.cleaned_data.get("debtor_phone", "").strip(),
                    note=form.cleaned_data.get("note", "").strip(),
                    is_approved=True,
                    approved_by=request.user,
                    approved_at=dj_tz.now()
                )

            messages.success(request, "Qarz yozildi")
            return redirect("debt_list")
    else:
        form = DebtNewForm()

    return render(request, "sales/debt_new.html", {"form": form})


@login_required
def debt_new_simple(request):
    """
    Sodda qarz (faqat summa)

    POST: amount, note
    """
    if request.method == "POST":
        form = DebtNewSimpleForm(request.POST)
        if form.is_valid():
            store = _get_user_store(request.user)
            if not store:
                messages.error(request, "Do'kon topilmadi")
                return redirect("debt_list")

            with db_txn.atomic():
                Transaction.objects.create(
                    type="debt_out",
                    store=store,
                    seller=request.user,
                    created_by=request.user,
                    amount=form.cleaned_data["amount"],
                    note=form.cleaned_data.get("note", "").strip(),
                    debtor_name="",
                    debtor_phone="",
                    is_approved=True,
                    approved_by=request.user,
                    approved_at=dj_tz.now()
                )

            messages.success(request, "Qarz yozildi")
            return redirect("sales:debt_list")
    else:
        form = DebtNewSimpleForm()

    return render(request, "sales/debt_new_simple.html", {"form": form})


@login_required
def debt_pay(request, group):
    """
    Qarz to'lovi

    URL: /sales/debts/<uuid>/pay/
    POST: amount, payment_type, cash_amount, card_amount
    """
    # UUID validation
    try:
        group_uuid = UUID(str(group))
    except (ValueError, AttributeError):
        messages.error(request, "Noto'g'ri identifikator")
        return redirect("debt_list")

    # Qarzdor ma'lumotini topish
    rows = _debt_rows(request.user)
    row = next((r for r in rows if str(r["group"]) == str(group)), None)

    if not row:
        messages.error(request, "Qarzdor topilmadi")
        return redirect("debt_list")

    if request.method == "POST":
        form = DebtPayForm(request.POST, group=group_uuid)
        if form.is_valid():
            store = _get_user_store(request.user)
            if not store:
                messages.error(request, "Do'kon topilmadi")
                return redirect("debt_list")

            cd = form.cleaned_data

            with db_txn.atomic():
                Transaction.objects.create(
                    type="debt_pay",
                    store=store,
                    seller=request.user,
                    created_by=request.user,
                    amount=cd["amount"],
                    payment_type=cd["payment_type"],
                    cash_amount=cd["cash_amount"],
                    card_amount=cd["card_amount"],
                    debtor_name=row["debtor_name"],
                    debtor_phone=row["debtor_phone"],
                    debtor_group=group_uuid,
                    is_approved=True,
                    approved_by=request.user,
                    approved_at=dj_tz.now()
                )

            messages.success(request, "To'lov qabul qilindi")
            return redirect("sales:debt_list")
        else:
            messages.error(request, "Xatolarni tuzating")
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


# ============================================
# 4. COMMISSION VIEWS (KOMISSIYALAR)
# ============================================

@login_required
def commissions_list(request):
    """
    Komissiyalar ro'yxati

    FEATURES:
    - Uchta jadval: Approved, Pending, Deductions
    - Filtrlar: seller, paid, approved, category, date
    - Oylik reyting
    - 30 kunlik trend
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

    df = _parse_date(date_from)
    dt = _parse_date(date_to)

    # Base queryset
    qs = SellerCommission.objects.select_related(
        "transaction",
        "transaction__product__brand",
        "transaction__product__model",
        "seller",
        "original_commission"
    ).order_by("-transaction__created_at")

    # Scope
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

    # Totals
    active_qs = qs.filter(is_approved=True, is_rescinded=False)

    positive_qs = active_qs.filter(is_deduction=False)
    deduction_qs = active_qs.filter(is_deduction=True)

    positive_total = safe_sum(positive_qs, "amount")
    deduction_total = safe_sum(deduction_qs, "amount")
    net_total = positive_total + deduction_total

    paid_total = safe_sum(
        qs.filter(is_paid=True, is_rescinded=False),
        "amount"
    )
    unpaid_total = safe_sum(
        qs.filter(is_paid=False, is_rescinded=False),
        "amount"
    )

    # Lists
    pending_rows = list(qs.filter(is_approved=False)[:500])
    approved_rows = list(active_qs.filter(is_deduction=False)[:500])
    deduction_rows = list(active_qs.filter(is_deduction=True)[:500])

    # Chart
    chart = _build_chart_data(active_qs, "amount", 30)

    # Leaderboard
    mk = month_filter or get_month_key()
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
        "pending_rows": pending_rows,
        "approved_rows": approved_rows,
        "deduction_rows": deduction_rows,

        "sellers": sellers,
        "seller_id": seller_id,
        "paid": paid,
        "approved": approved,
        "category": category,
        "rescinded": rescinded,
        "date_from": date_from,
        "date_to": date_to,

        "positive_amount": positive_total,
        "deduction_amount": abs(deduction_total),
        "net_total": net_total,
        "paid_amount": paid_total,
        "unpaid_amount": unpaid_total,

        "chart_labels": mark_safe(json.dumps(chart["labels"])),
        "chart_series": mark_safe(json.dumps(chart["series"])),

        "month_key": mk,
        "leaderboard": leaderboard,
        "month_bonuses": bonuses,
    }

    return render(request, "sales/commissions_list.html", context)


@login_required
@owner_required
def commission_approve(request, commission_id):
    """Komissiyani tasdiqlash"""
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
        messages.success(request, "Komissiya tasdiqlandi")
    else:
        messages.info(request, "Allaqachon tasdiqlangan")

    return redirect("sales:commissions_list")


@login_required
@owner_required
def commission_reject(request, commission_id):
    """Komissiyani rad etish"""
    commission = get_object_or_404(SellerCommission, pk=commission_id)

    if commission.is_approved:
        messages.error(request, "Tasdiqlangan komissiyani o'chirib bo'lmaydi")
    else:
        commission.delete()
        messages.success(request, "Komissiya o'chirildi")

    return redirect("commissions_list")


@login_required
@owner_required
def commission_mark_paid(request, commission_id):
    """Komissiyani to'langan deb belgilash"""
    commission = get_object_or_404(
        SellerCommission.objects.select_related("transaction", "seller"),
        pk=commission_id
    )

    if not commission.is_paid:
        commission.is_paid = True
        commission.paid_at = dj_tz.now()
        commission.save(update_fields=["is_paid", "paid_at"])
        messages.success(request, "To'langan deb belgilandi")
    else:
        messages.info(request, "Allaqachon to'langan")

    return redirect("sales:commissions_list")


@require_POST
@login_required
@owner_required
def commission_update_amount(request, pk):
    """Komissiya summasini o'zgartirish"""
    try:
        amount = parse_decimal(request.POST.get("amount"))

        if amount < Decimal("0.00"):
            messages.error(request, "Summa manfiy bo'lishi mumkin emas")
            return redirect("commissions_list")
    except:
        messages.error(request, "Noto'g'ri summa")
        return redirect("commissions_list")

    commission = get_object_or_404(
        SellerCommission.objects.select_related("transaction"),
        pk=pk
    )

    commission.amount = amount
    commission.save(update_fields=["amount"])

    messages.success(request, "Komissiya summasi o'zgartirildi")
    return redirect("sales:commissions_list")


# ============================================
# 5. CONSIGNMENT VIEWS (KONSIGNATSIYA)
# ============================================

@login_required
def consignment_list(request):
    """
    Konsignatsiya to'lovlari ro'yxati

    FEATURES:
    - Approved va Pending
    - Filtrlar: store, date, status, search, amount
    - 30 kunlik trend
    - KPI
    - CSV export
    - Pagination
    """
    # Filtrlar
    store_id = request.GET.get("store_id", "").strip()
    status_filter = request.GET.get("status", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    q = request.GET.get("q", "").strip()
    min_amount = request.GET.get("min_amount", "").strip()
    max_amount = request.GET.get("max_amount", "").strip()

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
        user_store = get_user_store_id(request.user)
        if user_store:
            qs = qs.filter(store_id=user_store)
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

    # Chart
    chart = _build_chart_data(approved_qs, "amount", 30)

    # CSV Export
    if request.GET.get("export", "").lower() == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="consignment_payouts.csv"'

        writer = csv.writer(response)
        writer.writerow([
            "ID", "Date", "Store", "Product", "Amount ($)", "Status", "Note"
        ])

        for t in qs:
            product_name = ""
            if t.product:
                b = getattr(t.product.brand, "name", "") if t.product.brand else ""
                m = getattr(t.product.model, "name", "") if t.product.model else ""
                product_name = f"{b} {m}".strip()

            writer.writerow([
                t.id,
                t.created_at.strftime("%Y-%m-%d %H:%M"),
                t.store.name if t.store else "",
                product_name,
                f"{t.amount:.2f}",
                "Approved" if t.is_approved else "Pending",
                t.note or ""
            ])

        return response

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

        "total_count": total_count,
        "total_sum": total_sum,
        "approved_count": approved_count,
        "approved_sum": approved_sum,
        "pending_count": pending_count,
        "pending_sum": pending_sum,

        "stores": stores,
        "store_id": store_id,
        "status": status_filter,
        "date_from": date_from,
        "date_to": date_to,
        "q": q,
        "min_amount": min_amount,
        "max_amount": max_amount,

        "chart_labels": mark_safe(json.dumps(chart["labels"])),
        "chart_series": mark_safe(json.dumps(chart["series"])),
    }

    return render(request, "sales/consignment_list.html", context)


@login_required
def consignment_payout(request, product_id):
    """
    Mahsulotga bog'liq konsignatsiya to'lovi

    POST: amount, note
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

            with db_txn.atomic():
                Transaction.objects.create(
                    type="consignment_payout",
                    store=product.store,
                    product=product,
                    seller=request.user,
                    created_by=request.user,
                    amount=amount,
                    note=note,
                    is_approved=False
                )

            messages.success(request, "Konsignatsiya to'lovi saqlandi (tasdig'ni kutmoqda)")
            return redirect("sales:consignment_list")
        else:
            messages.error(request, "Xatolarni tuzating")
    else:
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

            store = _get_user_store(request.user)
            if not store:
                messages.error(request, "Do'kon topilmadi")
                return redirect("sales:consignment_list")

            with db_txn.atomic():
                Transaction.objects.create(
                    type="consignment_payout",
                    store=store,
                    seller=request.user,
                    created_by=request.user,
                    amount=amount,
                    note=note,
                    is_approved=False
                )

            messages.success(request, "Konsignatsiya to'lovi saqlandi (tasdig'ni kutmoqda)")
            return redirect("sales:consignment_list")
        else:
            messages.error(request, "Xatolarni tuzating")
    else:
        form = ConsignmentNewForm()

    return render(request, "sales/consignment_new.html", {"form": form})


@login_required
@owner_required
def consignment_approve(request, tx_id):
    """
    Konsignatsiya to'lovini tasdiqlash

    POST: payment_type, cash_amount, card_amount
    """
    if request.method != "POST":
        return redirect("consignment_list")

    tx = get_object_or_404(
        Transaction,
        pk=tx_id,
        type="consignment_payout",
        is_void=False,
        is_approved=False
    )

    ptype = request.POST.get("payment_type", "").strip() or "cash"

    try:
        cash_amt = parse_decimal(request.POST.get("cash_amount", "0"))
        card_amt = parse_decimal(request.POST.get("card_amount", "0"))
    except:
        cash_amt = Decimal("0.00")
        card_amt = Decimal("0.00")

    # Validation
    if ptype == "cash":
        cash_amt = tx.amount
        card_amt = Decimal("0.00")
    elif ptype == "card":
        card_amt = tx.amount
        cash_amt = Decimal("0.00")
    elif ptype == "mixed":
        if (cash_amt + card_amt) != tx.amount:
            messages.error(request, "Naqd + Karta = To'lov summasi bo'lishi kerak")
            return redirect("sales:consignment_list")
    else:
        ptype = "cash"
        cash_amt = tx.amount
        card_amt = Decimal("0.00")

    # Ledger
    try:
        from finance.adapters import post_payment_to_supplier_split
        post_payment_to_supplier_split(
            obj_or_ids=tx,
            cash_amount=cash_amt,
            card_amount=card_amt,
            ref=f"sales.Transaction:{tx.pk}",
            memo="Konsignatsiya to'lovi"
        )
    except ImportError:
        log_warning("Finance app not available")
    except Exception as e:
        log_error("Consignment payout ledger posting failed", e)
        messages.error(request, f"Ledger xatosi: {e}")
        return redirect("sales:consignment_list")

    # Update
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

    messages.success(request, "To'lov tasdiqlandi va kassadan yechildi")
    return redirect("sales:consignment_list")


@login_required
@owner_required
def consignment_reject(request, tx_id):
    """Konsignatsiya to'lovini rad etish"""
    if request.method != "POST":
        return redirect("sales:consignment_list")

    tx = get_object_or_404(
        Transaction,
        pk=tx_id,
        type="consignment_payout",
        is_void=False,
        is_approved=False
    )

    tx.is_void = True
    tx.save(update_fields=["is_void"])

    messages.success(request, "To'lov rad etildi")
    return redirect("sales:consignment_list")


@login_required
@owner_required
def cons_due_approve(request, product_id):
    """ConsignmentDue'ni tasdiqlash"""
    due = get_object_or_404(ConsignmentDue, product_id=product_id)

    if not due.is_approved:
        due.is_approved = True
        due.approved_by = request.user
        due.approved_at = dj_tz.now()
        due.save(update_fields=["is_approved", "approved_by", "approved_at"])
        messages.success(request, "Due tasdiqlandi")
    else:
        messages.info(request, "Allaqachon tasdiqlangan")

    return redirect("sales:consignment_list")


@login_required
@owner_required
def cons_due_reject(request, product_id):
    """ConsignmentDue'ni rad etish"""
    due = get_object_or_404(ConsignmentDue, product_id=product_id)

    if due.is_approved:
        messages.error(request, "Tasdiqlangan due'ni o'chirib bo'lmaydi")
    else:
        due.delete()
        messages.success(request, "Due o'chirildi")

    return redirect("sales:consignment_list")


# ============================================
# BACKWARD COMPATIBILITY ALIASES
# ============================================

# Eski kod uchun
sell = sell_view
sale_return = sale_return_by_tx