# reports/views.py
import datetime
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import Sum, Count
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils.translation import gettext as _

from accounts.models import Store, User
from inventory.models import Product
from sales.models import Transaction, SellerCommission
from django.db.models import F


@login_required
def store_report(request):
    period = (request.GET.get("period") or "30").strip()  # 7/30/90/365/custom
    today = date.today()
    if period.isdigit():
        days = int(period)
        date_from = today - timedelta(days=days)
        date_to = today
    else:
        date_from = today - timedelta(days=30)
        date_to = today

    store_id = request.GET.get("store")
    stores = Store.objects.filter(is_active=True).order_by("name")
    if not request.user.is_owner:
        store_id = request.user.store_id

    qs = Transaction.objects.filter(created_at__date__gte=date_from, created_at__date__lte=date_to)

    if store_id:
        qs = qs.filter(store_id=store_id)

    sales_sum = qs.filter(type="sale").aggregate(s=Sum("amount"))["s"] or Decimal("0")
    cost_sum = qs.filter(type="sale").aggregate(s=Sum("cost"))["s"] or Decimal("0")
    profit_sum = qs.filter(type="sale").aggregate(s=Sum("profit"))["s"] or Decimal("0")
    expense_sum = qs.filter(type="expense").aggregate(s=Sum("amount"))["s"] or Decimal("0")

    ctx = {
        "stores": stores,
        "store_id": int(store_id) if store_id else None,
        "date_from": date_from,
        "date_to": date_to,
        "sales_sum": sales_sum,
        "cost_sum": cost_sum,
        "profit_sum": profit_sum,
        "expense_sum": expense_sum,
    }
    return render(request, "reports/store_report.html", ctx)


@login_required
def network_report(request):
    period = int((request.GET.get("period") or "30"))
    today = date.today()
    date_from = today - timedelta(days=period)

    qs = Transaction.objects.filter(created_at__date__gte=date_from, created_at__date__lte=today, type="sale")
    if not request.user.is_owner:
        qs = qs.filter(store_id=request.user.store_id)

    cache_key = f"netreport:{'all' if request.user.is_owner else request.user.store_id}:{period}"
    cached = cache.get(cache_key)
    if cached:
        return render(request, "reports/network_report.html", cached)

    # TOP stores (amount bo‘yicha)
    top_stores = list(qs.values("store__name").annotate(s=Sum("amount")).order_by("-s")[:5])

    # Transaction -> product -> brand/model bo‘yicha amount yig‘amiz
    top_brands = list(
        qs.values("product__brand__name").annotate(s=Sum("amount")).order_by("-s")[:5]
    )
    top_models = list(
        qs.values("product__brand__name", "product__model__name").annotate(s=Sum("amount")).order_by("-s")[:5]
    )

    ctx = {
        "period": period,
        "top_stores": top_stores,
        "top_brands": top_brands,
        "top_models": top_models,
        "date_from": date_from,
        "date_to": today,
    }
    cache.set(cache_key, ctx, 300)
    return render(request, "reports/network_report.html", ctx)


@login_required
def owner_dashboard(request):
    if not request.user.is_owner:
        return render(request, "reports/dashboard.html", {"error": _("Only owner.")})

    days = int(request.GET.get("days", 30))
    today = date.today()
    date_from = today - timedelta(days=days - 1)

    sales = (Transaction.objects
              .filter(type="sale", created_at__date__range=(date_from, today)))
    expenses = (Transaction.objects
                .filter(type="expense", created_at__date__range=(date_from, today)))

    sales_sum = sales.aggregate(s=Sum("amount"))["s"] or 0
    cost_sum  = sales.aggregate(s=Sum("cost"))["s"] or 0
    profit_sum = sales.aggregate(s=Sum("profit"))["s"] or 0

    # ---------- Daily chart (UNIVERSAL) ----------
    rows = (sales.annotate(d=TruncDate("created_at"))  # 2023-09-23
            .values("d")
            .annotate(s=Sum("amount"))
            .order_by("d"))
    labels = [r["d"].strftime("%Y-%m-%d") for r in rows]
    series = [r["s"] for r in rows]

    # ---------- Toplar ----------
    top_stores = list(
        sales.values("store__name")
             .annotate(s=Sum("amount"))
             .order_by("-s")[:10]
    )
    top_brands = list(
        sales.values("product__brand__name")
             .annotate(s=Sum("amount"))
             .order_by("-s")[:10]
    )
    top_models = list(
        sales.values("product__brand__name", "product__model__name")
             .annotate(s=Sum("amount"))
             .order_by("-s")[:10]
    )

    # ---------- Qarzlar ----------
    debts_out  = (Transaction.objects.filter(type="debt_out")
                  .aggregate(s=Sum("amount"))["s"] or 0)
    debts_pay  = (Transaction.objects.filter(type="debt_pay")
                  .aggregate(s=Sum("amount"))["s"] or 0)
    debts_unpaid = debts_out - debts_pay

    # ---------- Konsignment va komissiya ----------
    cons_payouts_sum = (Transaction.objects
                        .filter(type="consignment_payout",
                                created_at__date__range=(date_from, today))
                        .aggregate(s=Sum("amount"))["s"] or 0)

    commission_sum = (SellerCommission.objects
                      .filter(transaction__created_at__date__range=(date_from, today))
                      .aggregate(s=Sum("amount"))["s"] or 0)

    net_profit = (profit_sum or 0) - (commission_sum or 0) - (cons_payouts_sum or 0)

    # ---------- Xarajalar tahlili ----------
    exp_by_store = list(
        expenses.values("store__name")
                .annotate(s=Sum("amount"))
                .order_by("-s")[:10]
    )
    exp_by_seller = list(
        expenses.values("seller__username")
                .annotate(s=Sum("amount"))
                .order_by("-s")[:10]
    )
    exp_by_type = list(
        expenses.values("expense_type__name")
                .annotate(s=Sum("amount"))
                .order_by("-s")[:10]
    )

    ctx = dict(
        days=days, date_from=date_from, date_to=today,
        sales_sum=sales_sum, cost_sum=cost_sum, profit_sum=profit_sum,
        labels=labels, series=series,
        top_stores=top_stores, top_brands=top_brands, top_models=top_models,
        debts_unpaid=debts_unpaid,
        cons_payouts_sum=cons_payouts_sum,
        commission_sum=commission_sum,
        net_profit=net_profit,
        exp_by_store=exp_by_store,
        exp_by_seller=exp_by_seller,
        exp_by_type=exp_by_type,
    )
    return render(request, "reports/dashboard.html", ctx)

@login_required
def sales_log(request):
    if not request.user.is_owner:
        return render(request, "reports/sales_log.html", {"error": _("Only owner.")})

    store_id = request.GET.get("store_id") or ""
    seller_id = request.GET.get("seller_id") or ""
    date_from = request.GET.get("date_from") or ""
    date_to   = request.GET.get("date_to") or ""

    qs = Transaction.objects.select_related("product","store","seller","product__brand","product__model")\
            .filter(type="sale").order_by("-created_at")

    if store_id:
        qs = qs.filter(store_id=store_id)
    if seller_id:
        qs = qs.filter(seller_id=seller_id)

    def _pdate(s):
        try: return datetime.strptime(s, "%Y-%m-%d").date()
        except: return None

    df = _pdate(date_from); dt = _pdate(date_to)
    if df: qs = qs.filter(created_at__date__gte=df)
    if dt: qs = qs.filter(created_at__date__lte=dt)

    total_amount = qs.aggregate(s=Sum("amount"))["s"] or 0
    total_profit = qs.aggregate(s=Sum("profit"))["s"] or 0

    ctx = {
        "rows": qs[:500],  # paginate xohlasangiz qo‘shamiz
        "stores": Store.objects.order_by("name"),
        "sellers": User.objects.filter(role="seller").order_by("username"),
        "store_id": store_id, "seller_id": seller_id,
        "date_from": date_from, "date_to": date_to,
        "total_amount": total_amount, "total_profit": total_profit,
    }
    return render(request, "reports/sales_log.html", ctx)



@login_required
def expenses_log(request):
    if not request.user.is_owner:
        return render(request, "reports/expenses_log.html", {"error": _("Only owner.")})

    store_id = request.GET.get("store_id") or ""
    seller_id = request.GET.get("seller_id") or ""
    date_from = request.GET.get("date_from") or ""
    date_to   = request.GET.get("date_to") or ""
    include_commissions = request.GET.get("include_commissions") == "1"

    # Faqat expense yozuvlari
    qs = (Transaction.objects
          .select_related("product","store","seller","expense_type","product__brand","product__model")
          .filter(type="expense")
          .order_by("-created_at"))

    if store_id:
        qs = qs.filter(store_id=store_id)
    if seller_id:
        qs = qs.filter(seller_id=seller_id)

    def _pdate(s):
        try: return datetime.strptime(s, "%Y-%m-%d").date()
        except: return None

    df = _pdate(date_from); dt = _pdate(date_to)
    if df: qs = qs.filter(created_at__date__gte=df)
    if dt: qs = qs.filter(created_at__date__lte=dt)

    # Asosiy total (faqat expense)
    total = qs.aggregate(s=Sum("amount"))["s"] or 0

    # Komissiyalarni xohlasak qo‘shamiz (har sotuv uchun $5)
    commission_rows = []
    commission_total = 0
    if include_commissions:
        com_qs = (SellerCommission.objects
                  .select_related("transaction","seller","transaction__store","transaction__product",
                                  "transaction__product__brand","transaction__product__model")
                  .all()
                  .order_by("-transaction__created_at"))

        if store_id:
            com_qs = com_qs.filter(transaction__store_id=store_id)
        if seller_id:
            com_qs = com_qs.filter(seller_id=seller_id)
        if df:
            com_qs = com_qs.filter(transaction__created_at__date__gte=df)
        if dt:
            com_qs = com_qs.filter(transaction__created_at__date__lte=dt)

        # “synthetic” qatorlar: expenses jadvaliga o‘xshash ko‘rinishda
        for c in com_qs[:1000]:  # ko‘p bo‘lsa paginate qilamiz
            row = {
                "created_at": c.transaction.created_at,
                "store": c.transaction.store,
                "seller": c.seller,
                "expense_type_name": _("Commission"),
                "product": c.transaction.product,
                "amount": c.amount,
                "note": _("Seller commission"),
                "is_commission": True,
            }
            commission_rows.append(row)
            commission_total += c.amount or 0

    # Template uchun oddiy ro‘yxat (expense rows)
    expense_rows = []
    for r in qs[:1000]:
        expense_rows.append({
            "created_at": r.created_at,
            "store": r.store,
            "seller": r.seller,
            "expense_type_name": r.expense_type.name if r.expense_type else "-",
            "product": r.product,
            "amount": r.amount,
            "note": r.note or "",
            "is_commission": False,
        })

    # Ikkisini qo‘shib, sanasi bo‘yicha kamayish tartibida beramiz
    all_rows = expense_rows + commission_rows
    all_rows.sort(key=lambda x: x["created_at"], reverse=True)

    ctx = {
        "rows": all_rows,
        "stores": Store.objects.order_by("name"),
        "sellers": User.objects.filter(role="seller").order_by("username"),
        "store_id": store_id, "seller_id": seller_id,
        "date_from": date_from, "date_to": date_to,
        "include_commissions": include_commissions,
        "total": total + (commission_total if include_commissions else 0),
        "expense_total": total,
        "commission_total": commission_total,
    }
    return render(request, "reports/expenses_log.html", ctx)


