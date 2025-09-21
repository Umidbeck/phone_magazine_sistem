from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction as db_tx
from django.db.models import Q
from django.utils.translation import gettext as _
from inventory.models import Product
from inventory.search_utils import product_search_q
from .models import Transaction, SellerCommission
from .forms import SaleForm, ExpenseForm
from .services import sum_product_expenses, get_commission_amount


def digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

@login_required
def sell_view(request):
    base_qs = Product.objects.select_related("brand","model","store")
    if not request.user.is_owner():
        base_qs = base_qs.filter(store=request.user.store_id)

    q = (request.GET.get("q") or "").strip()
    picked_id = request.GET.get("product_id")
    products, picked = [], None

    if picked_id:
        picked = get_object_or_404(base_qs, pk=picked_id)

    if q and not picked:
        q_digits = digits_only(q)
        if q_digits and len(q_digits) == 4 and q_digits == q:
            products = list(
                base_qs.annotate(last4=Right("imei_full", 4))
                       .filter(last4__iexact=q_digits, status="available")
                       .order_by("-created_at")[:50]
            )
        else:
            products = list(
                base_qs.filter(
                    Q(imei_full__icontains=q_digits) |
                    Q(brand__name__icontains=q) |
                    Q(model__name__icontains=q),
                    status="available"
                ).order_by("-created_at")[:50]
            )

    if request.method == "POST":
        form = SaleForm(request.POST)
        if form.is_valid():
            pid = form.cleaned_data["product_id"]
            amount: Decimal = form.cleaned_data["amount"]
            payment_type = form.cleaned_data["payment_type"]

            product = get_object_or_404(base_qs, pk=pid)

            if product.status != "available":
                messages.error(request, _("Product is not available for sale."))
                return redirect("sell")

            # cost = base price + expenses
            base = product.purchase_price if product.ownership == "owned" else product.consignment_price
            expenses = sum_product_expenses(product.id)
            cost = (base + expenses).quantize(Decimal("0.01"))
            profit = (amount - cost).quantize(Decimal("0.01"))

            with db_tx.atomic():
                tx = Transaction.objects.create(
                    store=product.store,
                    product=product,
                    seller=request.user,
                    type="sale",
                    amount=amount,
                    payment_type=payment_type,
                    cost=cost,
                    profit=profit,
                )

                commission_amt = get_commission_amount(amount)
                SellerCommission.objects.create(transaction=tx, seller=request.user, amount=commission_amt)

                product.status = "sold"
                product.save(update_fields=["status"])

            messages.success(request, _("Sold. Profit: %(p)s, Commission: %(c)s") % {"p": profit, "c": commission_amt})
            return redirect("sell")
        else:
            # form error
            messages.error(request, "; ".join([" ".join(v) for v in form.errors.values()]))

    else:
        form = SaleForm(initial={"payment_type": "cash"})
        if picked:
            form.fields["product_id"].initial = picked.id

    return render(request, "sales/sell.html", {
        "q": q,
        "products": products,
        "picked": picked,
        "form": form,
    })

@login_required
def expense_create(request):
    pqs = Product.objects.select_related("brand","model","store")
    if not request.user.is_owner():
        pqs = pqs.filter(store=request.user.store_id)

    q = (request.GET.get("q") or "").strip()
    picked_id = request.GET.get("product_id")
    picked, products = None, []

    if picked_id:
        picked = get_object_or_404(pqs, pk=picked_id)

    if q and not picked:
        q_digits = digits_only(q)
        if q_digits and len(q_digits) == 4 and q_digits == q:
            products = list(
                pqs.annotate(last4=Right("imei_full", 4))
                   .filter(last4__iexact=q_digits)
                   .order_by("-created_at")[:50]
            )
        else:
            products = list(
                pqs.filter(
                    Q(imei_full__icontains=q_digits) |
                    Q(brand__name__icontains=q) |
                    Q(model__name__icontains=q)
                ).order_by("-created_at")[:50]
            )

    if request.method == "POST":
        form = ExpenseForm(request.POST)
        if form.is_valid():
            product_id = form.cleaned_data.get("product_id")
            expense_type = form.cleaned_data["expense_type"]
            amount: Decimal = form.cleaned_data["amount"]
            note = form.cleaned_data.get("note", "")

            product = None
            if product_id:
                product = get_object_or_404(pqs, pk=product_id)

            Transaction.objects.create(
                store=(product.store if product else (request.user.store if not request.user.is_owner() else None)),
                product=product,
                seller=request.user,
                type="expense",
                amount=amount,
                expense_type=expense_type,
                note=note,
            )
            messages.success(request, _("Expense saved."))
            return redirect("expense_new")
        else:
            messages.error(request, "; ".join([" ".join(v) for v in form.errors.values()]))

    else:
        init = {}
        if picked:
            init["product_id"] = picked.id
        form = ExpenseForm(initial=init)

    return render(request, "sales/expense_form.html", {
        "q": q, "products": products, "picked": picked, "form": form
    })

from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction as db_tx
from django.db.models import Q, Sum, F
from django.utils.translation import gettext as _
from django.core.cache import cache

from inventory.models import Product
from .models import Transaction, SellerCommission
from .forms import SaleForm, ExpenseForm, DebtNewForm, DebtPayForm, ConsignmentPayoutForm
from .services import sum_product_expenses, get_commission_amount

# ---- DEBT HELPERS ----
def debt_balance_qs(base_qs):
    """
    note format: 'debtor: <name>' — shu bo'yicha guruhlab balans hisoblaymiz:
    balance = SUM(debt_out.amount) - SUM(debt_pay.amount)
    """
    out = base_qs.filter(type="debt_out").values("note").annotate(total=Sum("amount"))
    pay = base_qs.filter(type="debt_pay").values("note").annotate(total=Sum("amount"))

    # note (debtor key) bo‘yicha birlashtirish:
    out_map = {x["note"]: x["total"] or Decimal("0") for x in out}
    pay_map = {x["note"]: x["total"] or Decimal("0") for x in pay}

    rows = []
    keys = set(out_map.keys()) | set(pay_map.keys())
    for k in keys:
        balance = (out_map.get(k, Decimal("0")) - pay_map.get(k, Decimal("0"))).quantize(Decimal("0.01"))
        if balance != 0:
            rows.append({"debtor_note": k, "balance": balance})
    # katta-kichik tartib
    rows.sort(key=lambda r: r["balance"], reverse=True)
    return rows

# ---- CONSIGNMENT HELPERS ----
def consignment_due_qs(base_p):
    """
    Consignment bo‘lgan va sotilgan productlar uchun:
      due = product.consignment_price - SUM(consignment_payout.amount)
    """
    sold_cons = base_p.filter(ownership="consignment", status="sold")

    payouts = (
        Transaction.objects.filter(type="consignment_payout", product_id__in=sold_cons.values("id"))
        .values("product_id").annotate(total=Sum("amount"))
    )
    pay_map = {x["product_id"]: (x["total"] or Decimal("0")) for x in payouts}

    rows = []
    for p in sold_cons:
        total_paid = pay_map.get(p.id, Decimal("0"))
        due = (p.consignment_price - total_paid).quantize(Decimal("0.01"))
        if due > 0:
            rows.append({"product": p, "due": due, "paid": total_paid})
    # katta-kichik
    rows.sort(key=lambda r: r["due"], reverse=True)
    return rows

# ---- DEBT LIST ----
@login_required
def debt_list(request):
    qs = Transaction.objects
    if not request.user.is_owner():
        qs = qs.filter(store_id=request.user.store_id)

    # cache key (store ga bog'lash maqsadga muvofiq)
    cache_key = f"report:debts:store={request.user.store_id if not request.user.is_owner() else 'all'}"
    rows = cache.get(cache_key)
    if rows is None:
        rows = debt_balance_qs(qs)
        cache.set(cache_key, rows, 300)

    return render(request, "sales/debt_list.html", {"rows": rows})

# ---- DEBT NEW (debt_out) ----
@login_required
def debt_new(request):
    if request.method == "POST":
        form = DebtNewForm(request.POST)
        if form.is_valid():
            debtor = form.cleaned_data["debtor_name"].strip()
            amount: Decimal = form.cleaned_data["amount"]
            note = f"debtor: {debtor}"
            Transaction.objects.create(
                store=(request.user.store if not request.user.is_owner() else None),
                seller=request.user,
                type="debt_out",
                amount=amount,
                note=note,
            )
            # keshni buzamiz
            cache.delete_pattern("report:debts:*")
            messages.success(request, _("Debt recorded."))
            return redirect("debt_list")
        else:
            messages.error(request, _("Invalid debt data."))
    else:
        form = DebtNewForm()
    return render(request, "sales/debt_new.html", {"form": form})

# ---- DEBT PAY ----
@login_required
def debt_pay(request, debtor_id):
    """
    Ui'da 'debtor_name' string o'rniga bir oddiy index bo'lsin deb id bilan keladi.
    Aslida debtor — rows[debtor_id]['debtor_note']. Shartli soddalashtirish.
    Productionda Debtor modeli ajratish tavsiya etiladi.
    """
    # mavjud ro'yxat
    qs = Transaction.objects
    if not request.user.is_owner():
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
                store=(request.user.store if not request.user.is_owner() else None),
                seller=request.user,
                type="debt_pay",
                amount=amount,
                note=row["debtor_note"],
            )
            cache.delete_pattern("report:debts:*")
            messages.success(request, _("Debt payment saved."))
            return redirect("debt_list")
        else:
            messages.error(request, _("Invalid data."))
    else:
        form = DebtPayForm()

    return render(request, "sales/debt_pay.html", {"form": form, "debtor_label": row["debtor_note"], "balance": row["balance"]})

# ---- CONSIGNMENT LIST ----
@login_required
def consignment_list(request):
    pqs = Product.objects.select_related("brand","model","store")
    if not request.user.is_owner():
        pqs = pqs.filter(store_id=request.user.store_id)

    # cache
    cache_key = f"report:consignment_due:store={request.user.store_id if not request.user.is_owner() else 'all'}"
    rows = cache.get(cache_key)
    if rows is None:
        rows = consignment_due_qs(pqs)
        cache.set(cache_key, rows, 300)

    return render(request, "sales/consignment_list.html", {"rows": rows})

# ---- CONSIGNMENT PAYOUT ----
@login_required
def consignment_payout(request, product_id):
    qs = Product.objects.select_related("store")
    if not request.user.is_owner():
        qs = qs.filter(store_id=request.user.store_id)
    p = get_object_or_404(qs, pk=product_id)
    if p.ownership != "consignment" or p.status != "sold":
        messages.error(request, _("Not eligible for consignment payout."))
        return redirect("consignment_list")

    if request.method == "POST":
        form = ConsignmentPayoutForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data["amount"]
            note = form.cleaned_data.get("note","")
            Transaction.objects.create(
                store=p.store,
                product=p,
                seller=request.user,
                type="consignment_payout",
                amount=amount,
                note=note,
            )
            cache.delete_pattern("report:consignment_due:*")
            messages.success(request, _("Consignment payout recorded."))
            return redirect("consignment_list")
        else:
            messages.error(request, _("Invalid data."))
    else:
        form = ConsignmentPayoutForm()

    return render(request, "sales/consignment_payout.html", {"form": form, "product": p})
