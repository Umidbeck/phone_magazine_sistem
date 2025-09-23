# sales/views.py
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction as db_tx
from django.db.models import Q, Sum
from django.db.models.functions import Right
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from inventory.models import Product
from inventory.search_utils import digits_only, product_search_queryset
from django.db import transaction as db_txn

from .forms import (
    SaleForm,
    ExpenseForm,
    DebtNewForm,
    DebtPayForm,
    ConsignmentPayoutForm,
)
from .models import Transaction, SellerCommission
from .services import get_commission_amount, calc_product_cost


@login_required
def sell_view(request):
    product_id = request.GET.get("product_id") or request.POST.get("product_id")
    picked = None
    if product_id:
        picked = get_object_or_404(Product.objects.select_related("store","brand","model"), pk=product_id)

    if request.method == "POST":
        form = SaleForm(request.POST)
        if not picked:
            messages.error(request, _("Select a product first."))
            return redirect("inventory_search")

        if picked.status != "available":
            messages.error(request, _("Product is not available for sale."))
            return redirect("product_detail", pk=picked.id)

        if form.is_valid():
            with db_txn.atomic():
                amount = Decimal(form.cleaned_data["amount"])
                pay_type = form.cleaned_data["payment_type"]

                # cost / profit
                cost = calc_product_cost(picked)
                profit = amount - cost

                tx = Transaction.objects.create(
                    type="sale",
                    product=picked,
                    store=picked.store,    # foyda shu do'kon hisobiga
                    seller=request.user,    # sotgan kim bo'lsa shu
                    amount=amount,
                    payment_type=pay_type,
                    cost=cost,
                    profit=profit,
                )

                picked.status = "sold"
                picked.save(update_fields=["status"])

                # Komissiya (har bir sotuvga 5$)
                com_amount = get_commission_amount(amount)
                SellerCommission.objects.create(
                    transaction=tx,
                    seller=request.user,
                    amount=com_amount,
                )

                messages.success(request, _("Sale recorded."))
                return redirect("product_detail", pk=picked.id)
        else:
            messages.error(request, _("Fix errors."))
    else:
        form = SaleForm(initial={"product_id": product_id})

    return render(request, "sales/sell.html", {"form": form, "picked": picked, "q": ""})







@login_required
def expense_create(request):
    q = (request.GET.get("q") or "").strip()
    products = []
    picked = None

    product_id = request.GET.get("product_id") or request.POST.get("product_id")
    if product_id:
        picked = get_object_or_404(
            Product.objects.select_related("brand", "model", "store"), pk=product_id
        )

    if q and not picked:
        base = Product.objects.select_related("brand", "model", "store").order_by("-created_at")
        if q.isdigit() and len(q) <= 4:
            products = list(base.filter(imei_suffix=q))
        else:
            products = list(base.filter(
                Q(imei_full__icontains=q) |
                Q(brand__name__icontains=q) |
                Q(model__name__icontains=q)
            )[:50])

    if request.method == "POST":
        form = ExpenseForm(request.POST)
        if form.is_valid():
            amount = Decimal(form.cleaned_data["amount"])
            note = form.cleaned_data.get("note") or ""

            # STORE:
            if picked:
                store = picked.store
            else:
                # Owner/seller product tanlamagan bo'lsa formdagi store ishlatiladi
                store = form.cleaned_data.get("store") or getattr(request.user, "store", None)

            if store is None:
                messages.error(request, _("Do'kon aniqlanmadi. Iltimos, store tanlang yoki product tanlang."))
                return render(request, "sales/expense_form.html", {
                    "form": form, "q": q, "products": products, "picked": picked
                })

            Transaction.objects.create(
                type="expense",
                amount=amount,
                note=note,
                product=picked,         # None bo‘lishi mumkin
                store=store,            # <-- ENDI MAJBURIY BERILYAPTI
                seller=request.user,
                expense_type=None,      # endi ishlatilmaydi
            )
            messages.success(request, _("Expense saved."))
            return redirect("expense_new")
        else:
            messages.error(request, _("Fix errors."))
    else:
        # GET — agar product tanlangan bo'lsa, store maydonini avtomatik yashirib yuboramiz (templateda)
        initial = {"product_id": product_id}
        form = ExpenseForm(initial=initial)

    return render(request, "sales/expense_form.html", {
        "form": form,
        "q": q,
        "products": products,
        "picked": picked,
    })


# ======= DEBT / CONSIGNMENT =======

def _debt_cache_key(user):
    return f"report:debts:{'all' if user.is_owner else user.store_id}"


def _cons_due_cache_key(user):
    return f"report:consignment_due:{'all' if user.is_owner else user.store_id}"


def debt_balance_qs(base_qs):
    """
    note format: 'debtor: <name>'
    balance = SUM(debt_out.amount) - SUM(debt_pay.amount)
    """
    out = base_qs.filter(type="debt_out").values("note").annotate(total=Sum("amount"))
    pay = base_qs.filter(type="debt_pay").values("note").annotate(total=Sum("amount"))

    out_map = {x["note"]: (x["total"] or Decimal("0")) for x in out}
    pay_map = {x["note"]: (x["total"] or Decimal("0")) for x in pay}

    rows = []
    keys = set(out_map.keys()) | set(pay_map.keys())
    for k in keys:
        balance = (out_map.get(k, Decimal("0")) - pay_map.get(k, Decimal("0"))).quantize(Decimal("0.01"))
        if balance != 0:
            rows.append({"debtor_note": k, "balance": balance})
    rows.sort(key=lambda r: r["balance"], reverse=True)
    return rows


def consignment_due_qs(base_p):
    """
    Consignment bo‘lgan va sotilgan productlar uchun:
      due = product.consignment_price - SUM(consignment_payout.amount)
    """
    sold_cons = base_p.filter(ownership="consignment", status="sold")

    payouts = (
        Transaction.objects.filter(type="consignment_payout", product_id__in=sold_cons.values("id"))
        .values("product_id")
        .annotate(total=Sum("amount"))
    )
    pay_map = {x["product_id"]: (x["total"] or Decimal("0")) for x in payouts}

    rows = []
    for p in sold_cons:
        total_paid = pay_map.get(p.id, Decimal("0"))
        due = (p.consignment_price - total_paid).quantize(Decimal("0.01"))
        if due > 0:
            rows.append({"product": p, "due": due, "paid": total_paid})
    rows.sort(key=lambda r: r["due"], reverse=True)
    return rows


@login_required
def debt_list(request):
    qs = Transaction.objects
    if not request.user.is_owner:
        qs = qs.filter(store_id=request.user.store_id)

    cache_key = _debt_cache_key(request.user)
    rows = cache.get(cache_key)
    if rows is None:
        rows = debt_balance_qs(qs)
        cache.set(cache_key, rows, 300)

    return render(request, "sales/debt_list.html", {"rows": rows})


@login_required
def debt_new(request):
    if request.method == "POST":
        form = DebtNewForm(request.POST)
        if form.is_valid():
            debtor = form.cleaned_data["debtor_name"].strip()
            amount: Decimal = form.cleaned_data["amount"]
            note = f"debtor: {debtor}"
            Transaction.objects.create(
                store=(request.user.store if not request.user.is_owner else None),
                seller=request.user,
                type="debt_out",
                amount=amount,
                note=note,
            )
            cache.delete(_debt_cache_key(request.user))
            messages.success(request, _("Debt recorded."))
            return redirect("debt_list")
        else:
            messages.error(request, _("Invalid debt data."))
    else:
        form = DebtNewForm()
    return render(request, "sales/debt_new.html", {"form": form})


@login_required
def debt_pay(request, debtor_id):
    qs = Transaction.objects
    if not request.user.is_owner:
        qs = qs.filter(store_id=request.user.store_id)
    rows = debt_balance_qs(qs)
    try:
        row = rows[debtor_id]
    except IndexError:
        messages.error(request, _("Debtor not found."))
        return redirect("debt_list")

    if request.method == "POST":
        form = DebtPayForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data["amount"]
            Transaction.objects.create(
                store=(request.user.store if not request.user.is_owner else None),
                seller=request.user,
                type="debt_pay",
                amount=amount,
                note=row["debtor_note"],
            )
            cache.delete(_debt_cache_key(request.user))
            messages.success(request, _("Debt payment saved."))
            return redirect("debt_list")
        else:
            messages.error(request, _("Invalid data."))
    else:
        form = DebtPayForm()

    return render(
        request,
        "sales/debt_pay.html",
        {"form": form, "debtor_label": row["debtor_note"], "balance": row["balance"]},
    )


@login_required
def consignment_list(request):
    pqs = Product.objects.select_related("brand", "model", "store")
    if not request.user.is_owner:
        pqs = pqs.filter(store_id=request.user.store_id)

    cache_key = _cons_due_cache_key(request.user)
    rows = cache.get(cache_key)
    if rows is None:
        rows = consignment_due_qs(pqs)
        cache.set(cache_key, rows, 300)

    return render(request, "sales/consignment_list.html", {"rows": rows})


@login_required
def consignment_payout(request, product_id):
    qs = Product.objects.select_related("store")
    if not request.user.is_owner:
        qs = qs.filter(store_id=request.user.store_id)
    p = get_object_or_404(qs, pk=product_id)
    if p.ownership != "consignment" or p.status != "sold":
        messages.error(request, _("Not eligible for consignment payout."))
        return redirect("consignment_list")

    if request.method == "POST":
        form = ConsignmentPayoutForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data["amount"]
            note = form.cleaned_data.get("note", "")
            Transaction.objects.create(
                store=p.store,
                product=p,
                seller=request.user,
                type="consignment_payout",
                amount=amount,
                note=note,
            )
            cache.delete(_cons_due_cache_key(request.user))
            messages.success(request, _("Consignment payout recorded."))
            return redirect("consignment_list")
        else:
            messages.error(request, _("Invalid data."))
    else:
        form = ConsignmentPayoutForm()

    return render(request, "sales/consignment_payout.html", {"form": form, "product": p})
