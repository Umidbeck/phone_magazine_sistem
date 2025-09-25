# sales/views.py
from datetime import datetime
from decimal import Decimal
from uuid import uuid4, UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_txn
from django.db.models import Q, Sum, Max, Min
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from django.utils import timezone as dj_tz

from accounts.models import User, Store
from inventory.models import Product
from .forms import (
    SaleForm,
    ExpenseForm,
    DebtNewForm,
    DebtPayForm,
    ConsignmentPayoutForm, InstallmentSaleForm, DebtNewSimpleForm,
)
from .models import Transaction, SellerCommission, ConsignmentDue


# ====== SOTUV ======
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

                # Komissiya yozuvi (5$ default, approve'ni owner qiladi)
                com_amount = SellerCommission.commission_amount()
                SellerCommission.objects.create(transaction=tx, seller=request.user, amount=com_amount)

                # Consignment bo‘lsa due kartasi
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
    Telefon bilan bog‘liq yoki umumiy rashod kiritish.
    Seller faqat o‘z do‘koni uchun (yoki product tanlagan bo‘lsa shu product),
    Owner istalgan do‘kon uchun.
    """
    q = (request.GET.get("q") or "").strip()
    products = []
    picked = None

    product_id = request.GET.get("product_id") or request.POST.get("product_id")
    if product_id:
        picked = get_object_or_404(
            Product.objects.select_related("brand", "model", "store"),
            pk=product_id
        )

    # Qidiruv (IMEI/brand/model)
    if q and not picked:
        base = Product.objects.select_related("brand", "model", "store").order_by("-created_at")
        products = list(base.filter(
            Q(imei_full__icontains=q) |
            Q(brand__name__icontains=q) |
            Q(model__name__icontains=q)
        )[:50])



    if request.method == "POST":
        form = ExpenseForm(request.POST)
        if form.is_valid():
            amount = Decimal(form.cleaned_data["amount"])
            note = form.cleaned_data.get("note", "").strip()

            # store/product aniqlash
            tx_store = None
            tx_product = None
            if picked:
                tx_store = picked.store
                tx_product = picked
            else:
                if getattr(request.user, "is_owner", False):
                    tx_store = form.cleaned_data.get("store") or request.user.store
                else:
                    tx_store = request.user.store

            with db_txn.atomic():
                Transaction.objects.create(
                    type="expense",
                    product=tx_product,
                    store=tx_store,
                    seller=request.user,
                    created_by=request.user,
                    amount=amount,
                    note=note,
                    is_approved=False,  # owner tasdiqlagach statistikaga kiradi
                )
            messages.success(request, _("Expense recorded. Waiting for approval."))
            return redirect("expenses_list")
        else:
            messages.error(request, _("Fix errors."))
    else:
        initial = {"product_id": product_id}
        form = ExpenseForm(initial=initial)

    return render(request, "sales/expense_form.html", {
        "form": form, "q": q, "products": products, "picked": picked,
    })


@login_required
def expenses_list(request):
    """
    - Seller: o‘zi kiritgan rashodlar
    - Owner: barcha do‘konlar, store bo‘yicha filter
    """
    store_id = (request.GET.get("store_id") or "").strip()
    only_approved = (request.GET.get("approved") == "1")

    qs = Transaction.objects.select_related("product", "store", "seller")\
                            .filter(type="expense").order_by("-created_at")

    if getattr(request.user, "is_owner", False):
        if store_id:
            qs = qs.filter(store_id=store_id)
    else:
        qs = qs.filter(created_by=request.user)

    if only_approved:
        qs = qs.filter(is_approved=True)

    ctx = {
        "rows": list(qs[:500]),
        "store_id": store_id,
        "only_approved": only_approved,
        "stores": list(Store.objects.order_by("name").values("id", "name")) if getattr(request.user, "is_owner",
                                                                                       False) else None,
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
    qs = Transaction.objects.filter(type="consignment_payout").select_related("product","store","created_by")
    if not getattr(request.user,"is_owner",False):
        qs = qs.filter(created_by=request.user)
    rows = []
    for t in qs.order_by("-created_at")[:400]:
        rows.append({
            "product_id": t.product_id,
            "product_name": f"{getattr(t.product.brand, 'name', '')} {getattr(t.product.model, 'name', '')}" if t.product_id else "",
            "store_name": t.store.name if t.store_id else "",
            "amount": t.amount,
        })
    return render(request, "sales/consignment_list.html", {"rows": rows})



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
                # 1) Sotuv yozuvi (umumiy narx + kassaga tushgan qismi (upfront))
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

                # 2) Agar qoldiq bo'lsa -> debt_out (qarzdorlik), sale'ga bog'laymiz
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
                        is_approved=False,  # owner tasdiqlaydi
                    )

                # 3) Komissiya yozuvi (telefon qaytib kelsa, berilmaydi — pastda return view)
                com_amount = SellerCommission.commission_amount()
                SellerCommission.objects.create(transaction=sale_tx, seller=request.user, amount=com_amount)

                # 4) Consignment due (agar consignment)
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

    with db_txn.atomic():
        tx.is_void = True
        tx.save(update_fields=["is_void"])
        p = tx.product
        if p:
            p.status = "available"
            p.save(update_fields=["status"])
        # komissiyani bloklash (to'lanmagan bo'lsa)
        if hasattr(tx, "commission") and not tx.commission.is_paid:
            tx.commission.is_approved = False
            tx.commission.save(update_fields=["is_approved"])
        # bog'liq tasdiqlanmagan qarz chiqimlarini ham void qilamiz
        Transaction.objects.filter(related_sale_id=tx.id, type="debt_out", is_approved=False).update(is_void=True)

    messages.success(request, "Sotuv qaytarildi.")
    return redirect("product_detail", pk=tx.product_id if tx.product_id else p.id)


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

