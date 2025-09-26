# sales/views.py
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4, UUID

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_txn
from django.db.models import Q, Sum, Max, Min
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from django.utils import timezone as dj_tz
from django.views.decorators.http import require_POST

from accounts.models import User, Store
from inventory.models import Product
from .forms import (
    SaleForm,
    ExpenseForm,
    DebtNewForm,
    DebtPayForm,
    ConsignmentPayoutForm, InstallmentSaleForm, DebtNewSimpleForm, parse_amount,
)
from .models import Transaction, SellerCommission, ConsignmentDue


# ====== SOTUV ======
def _can_award_commission(product: Product) -> bool:
    # Produkt tarixida qachondir sale bo'lsa (hatto void bo'lsa ham), endi yangi komissiya bermaymiz
    return not Transaction.objects.filter(type="sale", product_id=product.id).exists()


@login_required
def sell_view(request):
    product_id = request.GET.get("product_id")
    p = get_object_or_404(Product.objects.select_related("store"), pk=product_id, status="available")
    if request.method == "POST":
        form = SaleForm(request.POST)
        if form.is_valid():
            price = form.cleaned_data["price"]
            cash = form.cleaned_data["cash_amount"]
            card = form.cleaned_data["card_amount"]
            ptype = form.cleaned_data["payment_type"]

            cost = p.calc_cost()
            profit = (price - cost)

            with db_txn.atomic():
                tx = Transaction.objects.create(
                    type="sale",
                    product=p,
                    store=p.store,
                    seller=request.user,
                    created_by=request.user,
                    amount=price,
                    payment_type=ptype,
                    cash_amount=cash,
                    card_amount=card,
                    cost=cost,
                    profit=profit,
                    is_approved=True if getattr(request.user,"is_owner",False) else False,
                    approved_by=(request.user if getattr(request.user,"is_owner",False) else None),
                    approved_at=(dj_tz.now() if getattr(request.user,"is_owner",False) else None),
                )
                p.status = "sold"
                p.sold_at = dj_tz.now()
                p.save(update_fields=["status","sold_at"])

                if _can_award_commission(p):
                    com_amount = SellerCommission.commission_amount()
                    SellerCommission.objects.create(transaction=tx, seller=request.user, amount=com_amount)

                if p.ownership == "consignment":
                    ConsignmentDue.objects.get_or_create(
                        product=p,
                        defaults=dict(store=p.store, base_amount=p.consignment_price,
                                      created_by=request.user, is_approved=False)
                    )

            messages.success(request, "Sotuv saqlandi.")
            return redirect("product_detail", pk=p.id)
        else:
            messages.error(request, "Xatolarni tuzating.")
    else:
        form = SaleForm(initial={"payment_type":"cash"})
    return render(request, "sales/sell.html", {"form": form, "product": p})



# ====== RASHODLAR ======
@login_required
def expense_create(request):
    """
    Yangi rashod: store/seller formdan talab qilinmaydi. Product tanlansa — shu productga bog'lanadi
    (approved bo'lganda COGS ichida hisoblanadi, period expensega KIRMAYDI).
    """
    q = (request.GET.get("q") or "").strip()
    products, picked = [], None

    product_id = request.GET.get("product_id") or request.POST.get("product_id")
    if product_id:
        picked = get_object_or_404(Product.objects.select_related("brand","model","store"), pk=product_id)

    if q and not picked:
        base = Product.objects.select_related("brand", "model", "store").order_by("-created_at")
        products = list(base.filter(
            Q(imei_full__icontains=q) | Q(brand__name__icontains=q) | Q(model__name__icontains=q)
        )[:50])

    if request.method == "POST":
        form = ExpenseForm(request.POST)
        if form.is_valid():
            amount = Decimal(form.cleaned_data["amount"])
            note = form.cleaned_data.get("note", "").strip()

            if picked:
                tx_store, tx_product = picked.store, picked
            else:
                tx_store = request.user.store if not getattr(request.user, "is_owner", False) else (request.user.store or Store.objects.first())
                tx_product = None

            with db_txn.atomic():
                Transaction.objects.create(
                    type="expense",
                    product=tx_product,
                    store=tx_store,
                    seller=request.user,
                    created_by=request.user,
                    amount=amount,
                    note=note,
                    is_approved=False,  # owner tasdiqlaydi
                )
            messages.success(request, "Expense recorded. Waiting for approval.")
            return redirect("expenses_list")
        else:
            messages.error(request, "Fix errors.")
    else:
        form = ExpenseForm(initial={"product_id": product_id})

    return render(request, "sales/expense_form.html", {"form": form, "q": q, "products": products, "picked": picked})


from django.db.models.functions import TruncDate

@login_required
def expenses_list(request):
    """
    Ikki jadval: Approved va Pending (rejected – bu yerda delete).
    Statistika: Today/7/30 kun – jami va kunlik bo‘linish.
    Katta kartalar: Today Approved ($) vs Today Pending ($).
    Filter: sana oralig‘i, store (owner), seller (owner), approved flag (ixtiyoriy).
    """
    store_id = (request.GET.get("store_id") or "").strip()
    seller_id = (request.GET.get("seller_id") or "").strip() if getattr(request.user, "is_owner", False) else ""
    date_from = request.GET.get("date_from") or ""
    date_to   = request.GET.get("date_to") or ""

    def _pdate(s):
        try: return datetime.strptime(s, "%Y-%m-%d").date()
        except: return None

    df = _pdate(date_from); dt = _pdate(date_to)

    base = (Transaction.objects
            .select_related("product","store","seller","expense_type","product__brand","product__model")
            .filter(type="expense")
            .order_by("-created_at"))

    # Akses
    if getattr(request.user, "is_owner", False):
        if store_id: base = base.filter(store_id=store_id)
        if seller_id: base = base.filter(seller_id=seller_id)
    else:
        base = base.filter(created_by=request.user)

    if df: base = base.filter(created_at__date__gte=df)
    if dt: base = base.filter(created_at__date__lte=dt)

    approved_qs   = base.filter(is_approved=True)
    pending_qs    = base.filter(is_approved=False)

    # Katta kartalar – bugungi kunlik
    today = dj_tz.now().date()
    today_appr = approved_qs.filter(created_at__date=today).aggregate(s=Sum("amount"))["s"] or 0
    today_pend = pending_qs.filter(created_at__date=today).aggregate(s=Sum("amount"))["s"] or 0

    # Statistika (7 va 30 kun)
    def _series(qs, days=7):
        start = today - timedelta(days=days-1)
        rows = (qs.filter(created_at__date__range=(start, today))
                  .annotate(d=TruncDate("created_at")).values("d").annotate(s=Sum("amount")).order_by("d"))
        by = {r["d"]: float(r["s"] or 0) for r in rows}
        labels = [(start + timedelta(days=i)) for i in range(days)]
        series = [by.get(d, 0.0) for d in labels]
        return labels, series, sum(series)

    labels7, appr7, total_appr7 = _series(approved_qs, 7)
    _, pend7, total_pend7 = _series(pending_qs, 7)
    labels30, appr30, total_appr30 = _series(approved_qs, 30)
    _, pend30, total_pend30 = _series(pending_qs, 30)

    ctx = {
        "approved": list(approved_qs[:500]),
        "pending": list(pending_qs[:500]),
        "stores": list(Store.objects.order_by("name").values("id","name")) if getattr(request.user,"is_owner",False) else None,
        "sellers": list(User.objects.order_by("username").values("id","username")) if getattr(request.user,"is_owner",False) else None,
        "store_id": store_id, "seller_id": seller_id,
        "date_from": date_from, "date_to": date_to,

        # katta kartalar
        "today_approved": today_appr,
        "today_pending": today_pend,

        # series/statistika
        "labels7": [d.strftime("%Y-%m-%d") for d in labels7],
        "appr7": appr7, "pend7": pend7,
        "labels30": [d.strftime("%Y-%m-%d") for d in labels30],
        "appr30": appr30, "pend30": pend30,
        "total_appr7": total_appr7, "total_pend7": total_pend7,
        "total_appr30": total_appr30, "total_pend30": total_pend30,
    }
    return render(request, "sales/expense_list.html", ctx)


@login_required
def expense_approve(request, tx_id):
    if not getattr(request.user, "is_owner", False):
        messages.error(request, _("Only owner can approve."))
        return redirect("expenses_list")

    tx = get_object_or_404(Transaction, pk=tx_id, type="expense")
    if not tx.is_approved:
        tx.is_approved = True
        tx.approved_by = request.user
        tx.approved_at = dj_tz.now()
        tx.save(update_fields=["is_approved", "approved_by", "approved_at"])
        messages.success(request, _("Expense approved."))
    else:
        messages.info(request, _("Already approved."))
    return redirect("expenses_list")


@login_required
def expense_reject(request, tx_id):
    if not getattr(request.user, "is_owner", False):
        messages.error(request, _("Only owner can reject."))
        return redirect("expenses_list")

    tx = get_object_or_404(Transaction, pk=tx_id, type="expense")
    if tx.is_approved:
        messages.error(request, _("Approved expense cannot be rejected here."))
    else:
        tx.delete()
        messages.success(request, _("Expense rejected (deleted)."))
    return redirect("expenses_list")


# ====== QARZDORLAR ======


def _debt_cache_key(user):
    return f"report:debts:{'all' if user.is_owner else user.store_id}"

def _current_store_for(user):
    """
    Foydalanuvchidan do‘konni aniqlaydi.
    Sellerlarda user.store bor. Ownerda bo‘lmasa — birinchi do‘konni olamiz.
    """
    if getattr(user, "store_id", None):
        return user.store
    return Store.objects.first()


def _debt_rows(user, store_id=None, seller_id=None, df=None, dt=None):
    # Bazaviy queryset
    base = Transaction.objects.filter(is_void=False)

    # Akses
    if not getattr(user, "is_owner", False):
        base = base.filter(store_id=user.store_id)
    elif store_id:
        base = base.filter(store_id=store_id)

    if seller_id:
        base = base.filter(seller_id=seller_id)
    if df: base = base.filter(created_at__date__gte=df)
    if dt: base = base.filter(created_at__date__lte=dt)

    # Qarzni chiqarish (debt_out) — ko‘rsatish uchun hammasi
    outs_all = base.filter(type="debt_out").values(
        "debtor_group","debtor_name","debtor_phone","store_id","seller_id"
    ).annotate(
        total_all=Sum("amount"),
        first_at=Min("created_at"),
        last_out=Max("created_at"),
    )

    # Approved chiqargan qarz (jami)
    outs_appr = base.filter(type="debt_out", is_approved=True).values("debtor_group").annotate(
        total=Sum("amount")
    )
    out_map = {x["debtor_group"]: Decimal(x["total"] or 0) for x in outs_appr}

    # To‘lovlar
    pays_all = base.filter(type="debt_pay").values("debtor_group").annotate(
        paid_all=Sum("amount"), last_pay=Max("created_at"),
        cash_all=Sum("cash_amount"), card_all=Sum("card_amount"),
    )
    all_map = {x["debtor_group"]: x for x in pays_all}

    pays_appr = base.filter(type="debt_pay", is_approved=True).values("debtor_group").annotate(
        paid=Sum("amount"), cash_paid=Sum("cash_amount"), card_paid=Sum("card_amount"),
    )
    appr_map = {x["debtor_group"]: x for x in pays_appr}

    store_names = dict(Store.objects.values_list("id","name"))
    seller_names = dict(User.objects.values_list("id","username"))

    rows = []
    for o in outs_all:
        gid = o["debtor_group"]
        app_p = appr_map.get(gid, {}) or {}
        all_p = all_map.get(gid, {}) or {}

        total = out_map.get(gid, Decimal("0"))
        paid = Decimal(app_p.get("paid") or 0)
        balance = total - paid

        rows.append({
            "group": gid,
            "debtor_name": o["debtor_name"] or "Qarzdor",
            "debtor_phone": o["debtor_phone"] or "",
            "store_name": store_names.get(o["store_id"], "-"),
            "seller_name": seller_names.get(o["seller_id"], "-"),
            "total": total,                      # Jami (approved debt_out)
            "paid": paid,                        # To‘langan (approved debt_pay)
            "balance": balance,                  # Qolgan
            "cash_paid": app_p.get("cash_paid") or 0,
            "card_paid": app_p.get("card_paid") or 0,
            "total_all": o["total_all"] or 0,    # Ko‘rsatilish uchun
            "paid_all": all_p.get("paid_all") or 0,
            "cash_all": all_p.get("cash_all") or 0,
            "card_all": all_p.get("card_all") or 0,
            "last_at": all_p.get("last_pay") or o["last_out"],
        })

    # Qatorlar tartibi
    rows.sort(key=lambda r: (r["balance"], r["last_at"]), reverse=True)
    return rows


def debt_balance_qs(base_qs):
    """
    balance = SUM(approved debt_out) - SUM(approved debt_pay)
    """
    out = base_qs.filter(type="debt_out", is_approved=True).values("debtor_group","debtor_name").annotate(total=Sum("amount"))
    pay = base_qs.filter(type="debt_pay", is_approved=True).values("debtor_group").annotate(total=Sum("amount"))

    out_map = {x["debtor_group"]: (x["total"] or Decimal("0")) for x in out}
    name_map = {x["debtor_group"]: x["debtor_name"] for x in out}
    pay_map = {x["debtor_group"]: (x["total"] or Decimal("0")) for x in pay}

    rows = []
    keys = set(out_map.keys()) | set(pay_map.keys())
    for k in keys:
        total = out_map.get(k, Decimal("0"))
        paid = pay_map.get(k, Decimal("0"))
        balance = (total - paid).quantize(Decimal("0.01"))
        if balance != 0:
            rows.append({"group": k, "debtor_name": name_map.get(k, "-"), "total": total, "paid": paid, "balance": balance})
    rows.sort(key=lambda r: r["balance"], reverse=True)
    return rows


def debt_rows_qs(user, store_id=None, seller_id=None, status=None, date_from=None, date_to=None):
    """
    Qarzdorlar:
    - Ko'rsatish: barcha debt_out/pay (tasdiqlangan bo'lsin-bo'lmasin)
    - Balans: faqat APPROVED yozuvlar bo'yicha
    """
    base = Transaction.objects.filter(is_void=False)
    if not getattr(user, "is_owner", False):
        base = base.filter(store_id=user.store_id)
    elif store_id:
        base = base.filter(store_id=store_id)
    if seller_id:
        base = base.filter(seller_id=seller_id)
    if date_from:
        base = base.filter(created_at__date__gte=date_from)
    if date_to:
        base = base.filter(created_at__date__lte=date_to)

    outs_all = base.filter(type="debt_out").values(
        "debtor_group","debtor_name","debtor_phone","store_id","seller_id"
    ).annotate(
        total_all=Sum("amount"),
        first_at=Min("created_at"),
        last_out=Max("created_at"),
    )

    outs_appr = base.filter(type="debt_out", is_approved=True).values("debtor_group").annotate(
        total_appr=Sum("amount"))
    out_appr_map = {x["debtor_group"]: x["total_appr"] or Decimal("0") for x in outs_appr}

    pays_all = base.filter(type="debt_pay").values("debtor_group").annotate(
        paid_all=Sum("amount"),
        last_pay=Max("created_at"),
        cash_all=Sum("cash_amount"),
        card_all=Sum("card_amount"),
    )
    pay_all_map = {x["debtor_group"]: x for x in pays_all}

    pays_appr = base.filter(type="debt_pay", is_approved=True).values("debtor_group").annotate(
        paid_appr=Sum("amount"),
        cash_appr=Sum("cash_amount"), card_appr=Sum("card_amount"))
    pay_appr_map = {x["debtor_group"]: x for x in pays_appr}

    # id=>name xaritalar
    store_names = dict(Store.objects.values_list("id","name"))
    seller_names = dict(User.objects.values_list("id","username"))

    rows = []
    for o in outs_all:
        gid = o["debtor_group"]
        all_p = pay_all_map.get(gid, {})
        appr_p = pay_appr_map.get(gid, {})

        total_appr = out_appr_map.get(gid, Decimal("0"))
        paid_appr = appr_p.get("paid_appr") or Decimal("0")
        balance = total_appr - paid_appr

        rows.append({
            "debtor_group": gid,
            "debtor_name": o["debtor_name"],
            "debtor_phone": o["debtor_phone"],
            "store_id": o["store_id"],
            "store_name": store_names.get(o["store_id"], "-"),
            "seller_id": o["seller_id"],
            "seller_name": seller_names.get(o["seller_id"], "-"),

            # ko‘rsatish
            "total_all": o["total_all"] or 0,
            "paid_all": all_p.get("paid_all") or 0,
            "cash_all": all_p.get("cash_all") or 0,
            "card_all": all_p.get("card_all") or 0,

            # statistika (approved)
            "total": total_appr,
            "paid": paid_appr,
            "cash_paid": appr_p.get("cash_appr") or 0,
            "card_paid": appr_p.get("card_appr") or 0,

            "balance": balance,
            "first_at": o["first_at"],
            "last_at": all_p.get("last_pay") or o["last_out"],
        })

    if status == "open":
        rows = [r for r in rows if r["balance"] > 0]
    elif status == "closed":
        rows = [r for r in rows if r["balance"] <= 0]

    rows.sort(key=lambda r: (r["balance"], r["last_at"] or r["first_at"]), reverse=True)
    return rows



@login_required
def debt_list(request):
    store_id = request.GET.get("store_id") if getattr(request.user,"is_owner",False) else None
    seller_id = request.GET.get("seller_id") or None
    df = parse_date(request.GET.get("date_from") or "")
    dt = parse_date(request.GET.get("date_to") or "")
    rows = _debt_rows(request.user, store_id, seller_id, df, dt)
    return render(request, "sales/debt_list.html", {
        "rows": rows,
        "stores": Store.objects.order_by("name") if getattr(request.user,"is_owner",False) else None,
        "sellers": User.objects.order_by("username") if getattr(request.user,"is_owner",False) else None,
        "store_id": store_id or "", "seller_id": seller_id or "",
        "date_from": request.GET.get("date_from") or "", "date_to": request.GET.get("date_to") or "",
    })

@login_required
def debt_new_simple(request):
    # Yangi qarz: store MUST NOT NULL + debtor_group MUST NOT NULL
    if request.method == "POST":
        form = DebtNewSimpleForm(request.POST)
        if form.is_valid():
            store = _current_store_for(request.user)
            if store is None:
                messages.error(request, "Do‘kon topilmadi. Iltimos, avval kamida bitta do‘kon yarating.")
                return redirect("debt_list")
            with db_txn.atomic():
                Transaction.objects.create(
                    type="debt_out",
                    store=store,                # <<<<<< MUHIM
                    seller=request.user,        # <<<<<< MUHIM (avtomatik)
                    created_by=request.user,
                    amount=form.cleaned_data["amount"],
                    note=form.cleaned_data.get("note") or "",
                    debtor_name="",
                    debtor_phone="",
                    debtor_group=uuid4(),       # <<<<<< MUHIM: keyingi to‘lovlar bir guruhda yig‘iladi
                    is_approved=False,          # egasi tasdiqlaydi
                )
            messages.success(request, "Yangi qarz saqlandi (tasdiq kutilmoqda).")
            return redirect("debt_list")
        messages.error(request, "Xatolarni tuzating.")
    else:
        form = DebtNewSimpleForm()
    return render(request, "sales/debt_new_simple.html", {"form": form})



@login_required
def debt_new(request):
    if request.method == "POST":
        form = DebtNewForm(request.POST)
        if form.is_valid():
            debtor = form.cleaned_data["debtor_name"].strip()
            amount: Decimal = form.cleaned_data["amount"]
            group_id = uuid4()

            Transaction.objects.create(
                store=(request.user.store if not request.user.is_owner else request.user.store),
                # owner ham odatda o'z store'iga yozadi; agar ko'p store bo'lsa, alohida form bilan tanlov qo'shishingiz mumkin
                seller=request.user,
                created_by=request.user,
                type="debt_out",
                amount=amount,
                debtor_name=debtor,
                debtor_group=group_id,
                is_approved=False,
            )
            messages.success(request, _("Debt recorded (awaiting approval)."))
            return redirect("debt_list")
        else:
            messages.error(request, _("Invalid debt data."))
    else:
        form = DebtNewForm()
    return render(request, "sales/debt_new.html", {"form": form})


@login_required
def debt_pay(request, group):
    # group — UUID bo‘lishi kerak
    try:
        UUID(str(group))
    except Exception:
        messages.error(request, "Noto‘g‘ri identifikator.")
        return redirect("debt_list")

    rows = _debt_rows(request.user)
    row = next((r for r in rows if str(r["group"]) == str(group)), None)
    if not row:
        messages.error(request, "Qarzdor topilmadi.")
        return redirect("debt_list")

    if request.method == "POST":
        form = DebtPayForm(request.POST)
        if form.is_valid():
            store = _current_store_for(request.user)
            if store is None:
                messages.error(request, "Do‘kon topilmadi.")
                return redirect("debt_list")
            with db_txn.atomic():
                Transaction.objects.create(
                    type="debt_pay",
                    store=store,                 # <<<<<< MUHIM
                    seller=request.user,
                    created_by=request.user,
                    amount=form.cleaned_data["amount"],
                    payment_type=form.cleaned_data["payment_type"],
                    cash_amount=form.cleaned_data["cash_amount"],
                    card_amount=form.cleaned_data["card_amount"],
                    debtor_name=row["debtor_name"],
                    debtor_phone=row["debtor_phone"],
                    debtor_group=group,          # to‘g‘ri guruhga qo‘shilsin
                    is_approved=False,           # egasi tasdiqlasa statistikaga kiradi
                )
            messages.success(request, "To‘lov saqlandi (tasdiq kutilmoqda).")
            return redirect("debt_list")
        messages.error(request, "Xatolarni tuzating.")
    else:
        form = DebtPayForm(initial={"payment_type":"cash"})

    return render(request, "sales/debt_pay.html", {
        "form": form,
        "debtor_label": f"{row['debtor_name']} — {row['store_name']} / {row['seller_name']}",
        "balance": row["balance"]
    })





@login_required
def debt_approve(request, tx_id):
    if not getattr(request.user, "is_owner", False):
        messages.error(request, _("Only owner can approve."))
        return redirect("debt_list")
    tx = get_object_or_404(Transaction, pk=tx_id, type__in=["debt_out","debt_pay"])
    if not tx.is_approved:
        tx.is_approved = True
        tx.approved_by = request.user
        tx.approved_at = dj_tz.now()
        tx.save(update_fields=["is_approved","approved_by","approved_at"])
        messages.success(request, _("Debt entry approved."))
    else:
        messages.info(request, _("Already approved."))
    return redirect("debt_list")


@login_required
def debt_reject(request, tx_id):
    if not getattr(request.user, "is_owner", False):
        messages.error(request, _("Only owner can reject."))
        return redirect("debt_list")
    tx = get_object_or_404(Transaction, pk=tx_id, type__in=["debt_out","debt_pay"])
    if tx.is_approved:
        messages.error(request, _("Approved entry cannot be rejected here."))
    else:
        tx.delete()
        messages.success(request, _("Debt entry rejected (deleted)."))
    return redirect("debt_list")


# ====== CONSIGNMENT DUE (do‘kon qarzlari) ======

@login_required
def consignment_list(request):
    """
    Consignment payouts: filter + statistika.
    """
    from django.db.models.functions import TruncDate
    store_id = request.GET.get("store_id") if getattr(request.user,"is_owner",False) else None
    df = parse_date(request.GET.get("date_from") or "")
    dt = parse_date(request.GET.get("date_to") or "")

    qs = (Transaction.objects
          .select_related("product","store","created_by")
          .filter(type="consignment_payout")
          .order_by("-created_at"))

    if not getattr(request.user,"is_owner",False):
        qs = qs.filter(store_id=request.user.store_id)
    elif store_id:
        qs = qs.filter(store_id=store_id)

    if df: qs = qs.filter(created_at__date__gte=df)
    if dt: qs = qs.filter(created_at__date__lte=dt)

    # Statistika (bugungi/7/30)
    today = dj_tz.now().date()
    today_sum = qs.filter(created_at__date=today, is_approved=True).aggregate(s=Sum("amount"))["s"] or 0

    def _sum_days(days):
        start = today - timedelta(days=days-1)
        return qs.filter(created_at__date__range=(start,today), is_approved=True).aggregate(s=Sum("amount"))["s"] or 0

    stats = {
        "today": today_sum,
        "week": _sum_days(7),
        "month": _sum_days(30),
    }

    rows = []
    for t in qs[:400]:
        rows.append({
            "id": t.id,
            "approved": t.is_approved,
            "created_at": t.created_at,
            "store": t.store,
            "product": t.product,
            "amount": t.amount,
            "note": t.note or "",
        })

    stores = Store.objects.order_by("name") if getattr(request.user,"is_owner",False) else None
    return render(request, "sales/consignment_list.html", {
        "rows": rows, "stores": stores, "store_id": store_id or "",
        "date_from": request.GET.get("date_from") or "", "date_to": request.GET.get("date_to") or "",
        "stats": stats,
    })




@login_required
def cons_due_approve(request, product_id):
    if not request.user.is_owner:
        messages.error(request, _("Only owner can approve."))
        return redirect("consignment_list")
    due = get_object_or_404(ConsignmentDue, product_id=product_id)
    if not due.is_approved:
        due.is_approved = True
        due.approved_by = request.user
        due.approved_at = dj_tz.now()
        due.save(update_fields=["is_approved","approved_by","approved_at"])
        messages.success(request, _("Consignment due approved."))
    else:
        messages.info(request, _("Already approved."))
    return redirect("consignment_list")


@login_required
def cons_due_reject(request, product_id):
    if not request.user.is_owner:
        messages.error(request, _("Only owner can reject."))
        return redirect("consignment_list")
    due = get_object_or_404(ConsignmentDue, product_id=product_id)
    if due.is_approved:
        messages.error(request, _("Approved due cannot be rejected here."))
    else:
        due.delete()
        messages.success(request, _("Consignment due rejected (deleted)."))
    return redirect("consignment_list")




@login_required
def consignment_payout(request, product_id):
    # Consignment payout — summa kiritish ishlamayotgan bo'lsa, CharField parser buni hal qiladi
    from inventory.models import Product
    p = get_object_or_404(Product.objects.select_related("store"), pk=product_id)
    if request.method == "POST":
        form = ConsignmentPayoutForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data["amount"]
            note = form.cleaned_data.get("note") or ""
            with db_txn.atomic():
                Transaction.objects.create(
                    type="consignment_payout",
                    store=p.store,
                    product=p,
                    seller=request.user,
                    created_by=request.user,
                    amount=amount,
                    note=note,
                    is_approved=False,  # owner tasdiqlaydi
                )
            messages.success(request, "Consignment payout saqlandi (tasdiqni kutmoqda).")
            return redirect("consignment_list")
        else:
            messages.error(request, "Xatolarni tuzating.")
    else:
        form = ConsignmentPayoutForm()
    return render(request, "sales/consignment_payout.html", {"form": form, "product": p})


# ====== KOMISSIYA ======

@login_required
def commissions_list(request):
    seller_id = (request.GET.get("seller_id") or "").strip()
    paid = (request.GET.get("paid") or "").strip()  # "", "1", "0"
    approved = (request.GET.get("approved") or "").strip()  # "", "1", "0"
    date_from = (request.GET.get("date_from") or "").strip()
    date_to   = (request.GET.get("date_to") or "").strip()

    qs = SellerCommission.objects.select_related("transaction", "transaction__product", "seller").order_by("-transaction__created_at")

    if not getattr(request.user, "is_owner", False):
        qs = qs.filter(seller_id=request.user.id)

    if seller_id and getattr(request.user, "is_owner", False):
        qs = qs.filter(seller_id=seller_id)

    if paid == "1":
        qs = qs.filter(is_paid=True)
    elif paid == "0":
        qs = qs.filter(is_paid=False)

    if approved == "1":
        qs = qs.filter(is_approved=True)
    elif approved == "0":
        qs = qs.filter(is_approved=False)

    def _pdate(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except Exception:
            return None

    df = _pdate(date_from)
    dt = _pdate(date_to)
    if df:
        qs = qs.filter(transaction__created_at__date__gte=df)
    if dt:
        qs = qs.filter(transaction__created_at__date__lte=dt)

    totals = qs.aggregate(
        total_amount=Sum("amount"),
        paid_amount=Sum("amount", filter=Q(is_paid=True)),
        unpaid_amount=Sum("amount", filter=Q(is_paid=False)),
    )

    sellers = []
    if getattr(request.user, "is_owner", False):
        sellers = list(User.objects.filter(is_active=True).order_by("username").values("id","username"))

    ctx = dict(
        rows=list(qs[:500]),
        total_amount=totals.get("total_amount") or 0,
        paid_amount=totals.get("paid_amount") or 0,
        unpaid_amount=totals.get("unpaid_amount") or 0,
        sellers=sellers,
        seller_id=seller_id, paid=paid, approved=approved,
        date_from=date_from, date_to=date_to,
    )
    approved_rows = list(qs.filter(is_approved=True)[:500])
    pending_rows = list(qs.filter(is_approved=False)[:500])
    ctx.update({"approved_rows": approved_rows, "pending_rows": pending_rows})
    return render(request, "sales/commissions_list.html", ctx)


@login_required
def commission_mark_paid(request, commission_id):
    if not getattr(request.user, "is_owner", False):
        messages.error(request, _("Only owner."))
        return redirect("commissions_list")
    com = get_object_or_404(SellerCommission.objects.select_related("transaction","seller"), pk=commission_id)
    if not com.is_paid:
        com.is_paid = True
        com.paid_at = dj_tz.now()
        com.save(update_fields=["is_paid","paid_at"])
        messages.success(request, _("Marked as paid."))
    else:
        messages.info(request, _("Already paid."))
    return redirect("commissions_list")


@login_required
def commission_approve(request, commission_id):
    if not getattr(request.user, "is_owner", False):
        messages.error(request, _("Only owner."))
        return redirect("commissions_list")
    com = get_object_or_404(SellerCommission, pk=commission_id)
    if not com.is_approved:
        com.is_approved = True
        com.approved_by = request.user
        com.approved_at = dj_tz.now()
        com.save(update_fields=["is_approved","approved_by","approved_at"])
        messages.success(request, _("Commission approved."))
    else:
        messages.info(request, _("Already approved."))
    return redirect("commissions_list")


@login_required
def commission_reject(request, commission_id):
    if not getattr(request.user, "is_owner", False):
        messages.error(request, _("Only owner."))
        return redirect("commissions_list")
    com = get_object_or_404(SellerCommission, pk=commission_id)
    if com.is_approved:
        messages.error(request, _("Approved commission cannot be rejected here."))
    else:
        com.delete()
        messages.success(request, _("Commission rejected (deleted)."))
    return redirect("commissions_list")

@login_required
def sell_installment(request):
    product_id = request.GET.get("product_id")
    p = get_object_or_404(Product.objects.select_related("store"), pk=product_id, status="available")
    if request.method == "POST":
        form = InstallmentSaleForm(request.POST)
        if form.is_valid():
            total = form.cleaned_data["total_price"]
            upfront_cash = form.cleaned_data["upfront_cash"]
            upfront_card = form.cleaned_data["upfront_card"]
            ptype = form.cleaned_data["payment_type"]
            upfront_total = form.cleaned_data["upfront_total"]
            debt_amount = form.cleaned_data["debt_amount"]

            customer_name = form.cleaned_data["customer_name"]
            customer_phone = form.cleaned_data["customer_phone"]
            note = form.cleaned_data["note"]

            cost = p.calc_cost()
            profit = (total - cost)

            with db_txn.atomic():
                sale_tx = Transaction.objects.create(
                    type="sale",
                    product=p,
                    store=p.store,
                    seller=request.user,
                    created_by=request.user,
                    amount=total,
                    payment_type=ptype,
                    cash_amount=upfront_cash,
                    card_amount=upfront_card,
                    cost=cost,
                    profit=profit,
                    is_approved=True if getattr(request.user,"is_owner",False) else False,
                    approved_by=(request.user if getattr(request.user,"is_owner",False) else None),
                    approved_at=(dj_tz.now() if getattr(request.user,"is_owner",False) else None),
                    debtor_name=customer_name,
                    debtor_phone=customer_phone or "",
                    note=note or "",
                )
                p.status = "sold"
                p.sold_at = dj_tz.now()
                p.save(update_fields=["status","sold_at"])

                if debt_amount > 0:
                    Transaction.objects.create(
                        type="debt_out",
                        product=p,
                        store=p.store,
                        seller=request.user,
                        created_by=request.user,
                        amount=debt_amount,
                        debtor_name=customer_name,
                        debtor_phone=customer_phone or "",
                        note=note or "",
                        related_sale=sale_tx,
                        is_approved=False,
                    )

                if _can_award_commission(p):
                    com_amount = SellerCommission.commission_amount()
                    SellerCommission.objects.create(transaction=sale_tx, seller=request.user, amount=com_amount)

                if p.ownership == "consignment":
                    ConsignmentDue.objects.get_or_create(
                        product=p,
                        defaults=dict(store=p.store, base_amount=p.consignment_price,
                                      created_by=request.user, is_approved=False)
                    )

            messages.success(request, "Bo‘lib to‘lash sotuvi saqlandi (qarz yozildi).")
            return redirect("product_detail", pk=p.id)
        else:
            messages.error(request, "Xatolarni tuzating.")
    else:
        form = InstallmentSaleForm(initial={"payment_type":"cash"})
    return render(request, "sales/sell_installment.html", {"form": form, "product": p})



@login_required
def sale_return(request, tx_id):
    tx = get_object_or_404(Transaction.objects.select_related("product"), pk=tx_id, type="sale", is_void=False)
    if not getattr(request.user,"is_owner",False):
        messages.error(request, "Faqat do‘kon egasi sotuvni qaytara oladi.")
        return redirect("product_detail", pk=tx.product_id)

    with db_txn.atomic():
        tx.is_void = True
        tx.save(update_fields=["is_void"])

        # Productni qayta available
        p = tx.product
        if p:
            p.status = "available"
            p.save(update_fields=["status"])

        # Komissiya bo‘lsa, tasdiqlanmagan qilib/yo‘q qilish
        if hasattr(tx, "commission"):
            com = tx.commission
            if com.is_paid:
                messages.warning(request, "Komissiya allaqachon to‘langan — qaytarishdan so‘ng qayta hisob-kitob talab etiladi.")
            else:
                com.is_approved = False
                com.save(update_fields=["is_approved"])

        # Shu sotuvga bog‘langan debt_out larni ham void qilamiz
        Transaction.objects.filter(related_sale_id=tx.id, type="debt_out", is_approved=False).update(is_void=True)

    messages.success(request, "Sotuv qaytarildi (statistikadan chiqarildi).")
    return redirect("product_detail", pk=tx.product_id)

@login_required
def sale_return_by_tx(request, tx_id):
    tx = get_object_or_404(Transaction.objects.select_related("product"), pk=tx_id, type="sale", is_void=False)
    if not getattr(request.user,"is_owner",False):
        messages.error(request, "Faqat do‘kon egasi sotuvni qaytara oladi.")
        return redirect("product_detail", pk=tx.product_id)

    today = dj_tz.now().date()
    sale_day = tx.created_at.date()

    with db_txn.atomic():
        tx.is_void = True
        tx.save(update_fields=["is_void"])
        p = tx.product
        if p:
            p.status = "available"
            p.save(update_fields=["status"])

        if hasattr(tx, "commission"):
            com = tx.commission
            if com.is_paid:
                messages.warning(request, "Komissiya allaqachon to‘langan — qayta hisob talab etiladi.")
            else:
                if sale_day == today:
                    com.delete()
                    messages.info(request, "Bugungi qaytarish: $5 komissiya bekor qilindi.")
                else:
                    com.is_approved = False
                    com.save(update_fields=["is_approved"])
                    messages.info(request, "Kechagi/oldingi kun qaytarildi: keyingi sotuvda yangi komissiya berilmaydi.")

        Transaction.objects.filter(related_sale_id=tx.id, type="debt_out", is_approved=False).update(is_void=True)

    return redirect("product_detail", pk=tx.product_id if tx.product_id else (p.id if p else 0))


@login_required
def sale_return_by_product(request, product_id):
    p = get_object_or_404(Product, pk=product_id, status="sold")
    if not getattr(request.user,"is_owner",False):
        messages.error(request, "Faqat do‘kon egasi qaytara oladi.")
        return redirect("product_detail", pk=p.id)

    # Agar tranzaksiya topilmasa ham, mahsulotni qayta available qilamiz
    with db_txn.atomic():
        # so'nggi sale tx ni topishga urinib ko'ramiz
        tx = (Transaction.objects
              .filter(type="sale", product_id=p.id, is_void=False)
              .order_by("-created_at")
              .first())
        if tx:
            return sale_return_by_tx(request, tx.id)

        # tx yo'q — minimal rollback
        p.status = "available"
        p.save(update_fields=["status"])
        messages.success(request, "Mahsulot qaytarildi (Transaction topilmadi, product holati tiklandi).")
    return redirect("product_detail", pk=p.id)


class ConsignmentNewForm(forms.Form):
    amount = forms.CharField()
    note = forms.CharField(required=False)
    def clean_amount(self): return parse_amount(self.cleaned_data["amount"])

@login_required
def consignment_new(request):
    if request.method == "POST":
        form = ConsignmentNewForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data["amount"]
            note = form.cleaned_data.get("note") or ""
            # store/seller avtomatik
            store = request.user.store if not request.user.is_owner else (request.user.store or Store.objects.first())
            with db_txn.atomic():
                Transaction.objects.create(
                    type="consignment_payout",
                    store=store,
                    seller=request.user,
                    created_by=request.user,
                    amount=amount,
                    note=note,
                    is_approved=False,  # tasdiqlanganda kassa/foydadan ayriladi
                )
            messages.success(request, _("Consignment payout created (awaiting approval)."))
            return redirect("consignment_list")
        messages.error(request, _("Fix errors."))
    else:
        form = ConsignmentNewForm()
    return render(request, "sales/consignment_new.html", {"form": form})

@login_required
def consignment_approve(request, tx_id):
    if not getattr(request.user, "is_owner", False):
        messages.error(request, "Only owner can approve.")
        return redirect("consignment_list")
    tx = get_object_or_404(Transaction, pk=tx_id, type="consignment_payout")
    if not tx.is_approved:
        tx.is_approved = True
        tx.approved_by = request.user
        tx.approved_at = dj_tz.now()
        tx.save(update_fields=["is_approved","approved_by","approved_at"])
        messages.success(request, "Consignment payout approved.")
    else:
        messages.info(request, "Already approved.")
    return redirect("consignment_list")

@login_required
def consignment_reject(request, tx_id):
    if not getattr(request.user, "is_owner", False):
        messages.error(request, "Only owner can reject.")
        return redirect("consignment_list")
    tx = get_object_or_404(Transaction, pk=tx_id, type="consignment_payout")
    if tx.is_approved:
        messages.error(request, "Approved payout cannot be rejected here.")
    else:
        tx.delete()
        messages.success(request, "Consignment payout rejected (deleted).")
    return redirect("consignment_list")



@login_required
def expense_unapprove(request, tx_id):
    if not getattr(request.user, "is_owner", False):
        messages.error(request, "Only owner can unapprove.")
        return redirect("expenses_list")
    tx = get_object_or_404(Transaction, pk=tx_id, type="expense")
    if tx.is_approved:
        tx.is_approved = False
        tx.approved_by = None
        tx.approved_at = None
        tx.save(update_fields=["is_approved", "approved_by", "approved_at"])
        messages.success(request, "Expense moved back to pending.")
    else:
        messages.info(request, "Expense is already pending.")
    return redirect("expenses_list")

@require_POST
@login_required
def commission_update_amount(request, pk):
    if not getattr(request.user, "is_owner", False):
        messages.error(request, "Only owner can edit commission.")
        return redirect("commissions_list")
    try:
        amt = Decimal(request.POST.get("amount") or "0")
        if amt <= 0: raise ValueError()
    except Exception:
        messages.error(request, "Invalid amount.")
        return redirect("commissions_list")

    c = get_object_or_404(SellerCommission.objects.select_related("transaction"), pk=pk)
    c.amount = amt
    c.save(update_fields=["amount"])
    messages.success(request, "Commission amount updated.")
    return redirect("commissions_list")


