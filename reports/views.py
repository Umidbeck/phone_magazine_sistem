# reports/views.py
import datetime
from datetime import date, timedelta
from decimal import Decimal

from dateutil.utils import today
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncDate, TruncDay, TruncWeek, TruncMonth
from django.shortcuts import render
from django.utils.translation import gettext as _

from accounts.models import Store, User
from inventory.models import Product
from sales.models import Transaction, SellerCommission
from django.db.models import F
from django.utils import timezone as dj_tz


@login_required
def store_report(request):
    # parametrlar
    period = int(request.GET.get("period") or 30)
    store_id = (request.GET.get("store") or "").strip()

    today = date.today()
    date_from = today - timedelta(days=period-1)

    stores = Store.objects.filter(is_active=True).order_by("name")
    tx_exp = Transaction.objects.filter(type="expense", is_approved=True, created_at__date__range=(date_from, today))
    tx_cons = Transaction.objects.filter(type="consignment_payout", is_approved=True,
                                         created_at__date__range=(date_from, today))

    commission_total = SellerCommission.objects.filter(is_approved=True,
                                                       transaction__created_at__date__range=(date_from,
                                                                                             today)).aggregate(
        s=Sum("amount"))["s"] or 0
    commission_paid = SellerCommission.objects.filter(is_approved=True, is_paid=True,
                                                      transaction__created_at__date__range=(date_from,
                                                                                            today)).aggregate(
        s=Sum("amount"))["s"] or 0

    tx_sales = Transaction.objects.filter(type="sale", created_at__date__range=(date_from, today))
    if store_id:
        tx_sales = tx_sales.filter(store_id=store_id)

    # sotilganlar soni / summalar
    sold_count = tx_sales.count()
    sales_sum = tx_sales.aggregate(s=Sum("amount"))["s"] or 0
    cost_sum = tx_sales.aggregate(s=Sum("cost"))["s"] or 0
    profit_sum = tx_sales.aggregate(s=Sum("profit"))["s"] or 0

    # xarajatlar (store bo‘yicha)
    exp = Transaction.objects.filter(type="expense",
                                     created_at__date__range=(date_from, today))
    if store_id:
        exp = exp.filter(store_id=store_id)
    expense_sum = exp.aggregate(s=Sum("amount"))["s"] or 0

    # komissiya (paid/unpaid)
    comm = SellerCommission.objects.filter(transaction__created_at__date__range=(date_from, today))
    if store_id:
        comm = comm.filter(transaction__store_id=store_id)
    commission_sum = comm.aggregate(s=Sum("amount"))["s"] or 0
    commission_paid = comm.filter(is_paid=True).aggregate(s=Sum("amount"))["s"] or 0

    # consignment payouts (agar bitta Transaction turida bo‘lsa)
    cons_payouts = Transaction.objects.filter(type="consignment_payout",
                                              created_at__date__range=(date_from, today))
    if store_id:
        cons_payouts = cons_payouts.filter(store_id=store_id)
    cons_payouts_sum = cons_payouts.aggregate(s=Sum("amount"))["s"] or 0

    # inv holati (hozirgi vaqtda)
    inv_qs = Product.objects.filter(is_archived=False).exclude(status="sold")
    if store_id:
        inv_qs = inv_qs.filter(store_id=store_id)
    inv_count = inv_qs.count()

    # olinganlar soni (period ichida yaratilgan)
    acquired_qs = Product.objects.filter(created_at__date__range=(date_from, today))
    if store_id:
        acquired_qs = acquired_qs.filter(store_id=store_id)
    acquired_count = acquired_qs.count()

    # sotuvchilar kesimi (TOP)
    top_sellers = (tx_sales.values("seller__username")
                   .annotate(cnt=Count("id"), s=Sum("amount"), p=Sum("profit"))
                   .order_by("-s")[:10])

    # brend/model insight (tezkor)
    top_brands = (tx_sales.values("product__brand__name")
                  .annotate(s=Sum("amount"))
                  .order_by("-s")[:10])
    top_models = (tx_sales.values("product__brand__name", "product__model__name")
                  .annotate(cnt=Count("id"), s=Sum("amount"))
                  .order_by("-cnt")[:10])

    # net profit (aniq)
    net_profit = (profit_sum or 0) - (expense_sum or 0) - (commission_sum or 0) - (cons_payouts_sum or 0)

    ctx = dict(
        stores=stores,
        store_id=store_id and int(store_id) or "",
        date_from=date_from, date_to=today, period=period,

        sales_sum=sales_sum, cost_sum=cost_sum, profit_sum=profit_sum,
        expense_sum=expense_sum, commission_sum=commission_sum,
        commission_paid=commission_paid, cons_payouts_sum=cons_payouts_sum,

        sold_count=sold_count, acquired_count=acquired_count, inv_count=inv_count,
        top_sellers=top_sellers, top_brands=top_brands, top_models=top_models,
        net_profit=net_profit,
    )
    return render(request, "store_report.html", ctx)


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
    days = int(request.GET.get("days") or 30)
    today = date.today()
    date_from = today - timedelta(days=days-1)

    tx_sales = Transaction.objects.filter(type="sale", created_at__date__range=(date_from, today))
    tx_exp = Transaction.objects.filter(type="expense", is_approved=True, created_at__date__range=(date_from, today))
    tx_cons = Transaction.objects.filter(type="consignment_payout", is_approved=True,
                                         created_at__date__range=(date_from, today))

    commission_total = SellerCommission.objects.filter(is_approved=True,
                                                       transaction__created_at__date__range=(date_from,
                                                                                             today)).aggregate(
        s=Sum("amount"))["s"] or 0
    commission_paid = SellerCommission.objects.filter(is_approved=True, is_paid=True,
                                                      transaction__created_at__date__range=(date_from,
                                                                                            today)).aggregate(
        s=Sum("amount"))["s"] or 0

    sales_sum   = tx_sales.aggregate(s=Sum("amount"))["s"] or 0
    cost_sum    = tx_sales.aggregate(s=Sum("cost"))["s"] or 0
    profit_sum  = tx_sales.aggregate(s=Sum("profit"))["s"] or 0
    expense_sum = tx_exp.aggregate(s=Sum("amount"))["s"] or 0
    commission_total = SellerCommission.objects.filter(transaction__created_at__date__range=(date_from, today)).aggregate(s=Sum("amount"))["s"] or 0
    commission_paid  = SellerCommission.objects.filter(transaction__created_at__date__range=(date_from, today), is_paid=True).aggregate(s=Sum("amount"))["s"] or 0
    cons_payouts_sum = tx_cons.aggregate(s=Sum("amount"))["s"] or 0
    net_profit = (profit_sum or 0) - (expense_sum or 0) - (commission_total or 0) - (cons_payouts_sum or 0)

    def daily_series(qs, field="amount"):
        rows = (qs.annotate(d=TruncDate("created_at")).values("d").annotate(s=Sum(field)).order_by("d"))
        by_date = {r["d"]: float(r["s"] or 0) for r in rows}
        labels, series = [], []
        for i in range(days):
            d = date_from + timedelta(days=i)
            labels.append(d.strftime("%Y-%m-%d"))
            series.append(by_date.get(d, 0.0))
        return labels, series

    labels, sales_series = daily_series(tx_sales, "amount")
    _, profit_series = daily_series(tx_sales, "profit")
    _, expense_series = daily_series(tx_exp, "amount")
    rows_comm = (SellerCommission.objects
                 .filter(transaction__created_at__date__range=(date_from, today))
                 .annotate(d=TruncDate("transaction__created_at"))
                 .values("d").annotate(s=Sum("amount")).order_by("d"))
    by_date_comm = {r["d"]: float(r["s"] or 0) for r in rows_comm}
    commission_series = [by_date_comm.get(date_from + timedelta(days=i), 0.0) for i in range(days)]

    ctx = dict(
        days=days, date_from=date_from, date_to=today,
        sales_sum=sales_sum, cost_sum=cost_sum, profit_sum=profit_sum,
        expense_sum=expense_sum, net_profit=net_profit,
        commission_total=commission_total, commission_paid=commission_paid, cons_payouts_sum=cons_payouts_sum,
        labels=labels, series=sales_series, profit_series=profit_series, expense_series=expense_series, commission_series=commission_series,
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
    tx_exp = Transaction.objects.filter(type="expense", is_approved=True, created_at__date__range=(date_from, today))
    tx_cons = Transaction.objects.filter(type="consignment_payout", is_approved=True,
                                         created_at__date__range=(date_from, today))

    commission_total = SellerCommission.objects.filter(is_approved=True,
                                                       transaction__created_at__date__range=(date_from,
                                                                                             today)).aggregate(
        s=Sum("amount"))["s"] or 0
    commission_paid = SellerCommission.objects.filter(is_approved=True, is_paid=True,
                                                      transaction__created_at__date__range=(date_from,
                                                                                            today)).aggregate(
        s=Sum("amount"))["s"] or 0

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


@login_required
def profit_overview(request):
    """
    Kassa formulasi (siz aytgandek):
      KASSA = (sotilgan telefonlar narxi) - (tasdiqlangan rashodlar) - (komissiya 5$) + (tasdiqlangan qarzdor to'lovlari)

    Sotuvchi (owner emas) faqat o'z do'koni bo'yicha ko'radi.
    Owner istasa bir yoki ko'p do'konni tanlab ko'radi.
    """
    period = (request.GET.get("period") or "month").lower()
    if period not in ("day", "week", "month"):
        period = "month"
    try:
        days = max(7, min(int(request.GET.get("days") or "730"), 730))
    except Exception:
        days = 730

    end_date = dj_tz.now().date()
    start_date = end_date - timedelta(days=days - 1)

    # ===== Store filtri (rolga qarab)
    if getattr(request.user, "is_owner", False):
        store_ids = [int(s) for s in request.GET.getlist("stores") if s.isdigit()]
        store_q = Q()
        if store_ids:
            store_q = Q(store_id__in=store_ids)
        stores = Store.objects.order_by("name")
    else:
        store_ids = []
        store_q = Q(store_id=request.user.store_id)
        stores = Store.objects.filter(pk=request.user.store_id)

    trunc = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}[period]

    # ===== Guruhlangan metrikalar (grafik/jadval uchun)
    sales_qs = (
        Transaction.objects.filter(type="sale", is_void=False, created_at__date__range=(start_date, end_date))
        .filter(store_q)
        .annotate(p=trunc("created_at"))
        .values("p")
        .annotate(sales_sum=Sum("amount"), profit_sum=Sum("profit"))
        .order_by("p")
    )
    expense_qs = (
        Transaction.objects.filter(type="expense", is_void=False, is_approved=True, created_at__date__range=(start_date, end_date))
        .filter(store_q)
        .annotate(p=trunc("created_at"))
        .values("p")
        .annotate(expense_sum=Sum("amount"))
        .order_by("p")
    )
    cons_qs = (
        Transaction.objects.filter(type="consignment_payout", is_void=False, is_approved=True, created_at__date__range=(start_date, end_date))
        .filter(store_q)
        .annotate(p=trunc("created_at"))
        .values("p")
        .annotate(cons_sum=Sum("amount"))
        .order_by("p")
    )
    comm_qs = (
        SellerCommission.objects.filter(is_approved=True, transaction__is_void=False,
                                        transaction__created_at__date__range=(start_date, end_date))
        .filter(transaction__store_id__in=store_ids if (getattr(request.user, "is_owner", False) and store_ids)
                else ([request.user.store_id] if not getattr(request.user, "is_owner", False) else Store.objects.values_list("id", flat=True)))
        .annotate(p=trunc("transaction__created_at"))
        .values("p")
        .annotate(comm_sum=Sum("amount"))
        .order_by("p")
    )

    s_map = {row["p"].date() if hasattr(row["p"], "date") else row["p"]: row for row in sales_qs}
    e_map = {row["p"].date() if hasattr(row["p"], "date") else row["p"]: row for row in expense_qs}
    c_map = {row["p"].date() if hasattr(row["p"], "date") else row["p"]: row for row in cons_qs}
    k_map = {row["p"].date() if hasattr(row["p"], "date") else row["p"]: row for row in comm_qs}

    # Fallback komissiya: tasdiqlangan sotuvlar soni * 5
    if not k_map:
        sale_cnt = (
            Transaction.objects.filter(type="sale", is_void=False, is_approved=True, created_at__date__range=(start_date, end_date))
            .filter(store_q)
            .annotate(p=trunc("created_at"))
            .values("p")
            .annotate(cnt=Count("id"))
        )
        for r in sale_cnt:
            key = r["p"].date() if hasattr(r["p"], "date") else r["p"]
            k_map[key] = {"comm_sum": Decimal(r["cnt"]) * Decimal("5")}

    # Bucketlar
    step = {"day": 1, "week": 7, "month": 30}[period]
    cur = start_date
    rows = []
    tot_sales = tot_profit = tot_exp = tot_comm = tot_cons = Decimal("0")
    while cur <= end_date:
        key = cur
        s = s_map.get(key, {}); e = e_map.get(key, {}); k = k_map.get(key, {}); c = c_map.get(key, {})
        sales_sum = Decimal(s.get("sales_sum") or 0)
        profit_sum = Decimal(s.get("profit_sum") or 0)
        expense_sum = Decimal(e.get("expense_sum") or 0)
        comm_sum = Decimal(k.get("comm_sum") or 0)
        cons_sum = Decimal(c.get("cons_sum") or 0)

        # Net foyda (klassik): profit - expense - commission - consignment payout
        net = profit_sum - expense_sum - comm_sum - cons_sum

        tot_sales += sales_sum; tot_profit += profit_sum
        tot_exp += expense_sum; tot_comm += comm_sum; tot_cons += cons_sum

        rows.append({
            "period": key,
            "sales": sales_sum,
            "profit": profit_sum,
            "expense": expense_sum,
            "commission": comm_sum,
            "consignment": cons_sum,
            "net": net,
        })
        cur += timedelta(days=step)

    def _kassa_breakdown(date_from, date_to, store_filter_q: Q):
        # Sotuv tushumlari (void emas)
        sale_aggr = (Transaction.objects
                     .filter(type="sale", is_void=False, created_at__date__range=(date_from, date_to))
                     .filter(store_filter_q)
                     .aggregate(cash=Sum("cash_amount"), card=Sum("card_amount")))
        # Qarzdorlardan tushum (faqat APPROVED)
        debt_aggr = (Transaction.objects
                     .filter(type="debt_pay", is_void=False, is_approved=True,
                             created_at__date__range=(date_from, date_to))
                     .filter(store_filter_q)
                     .aggregate(cash=Sum("cash_amount"), card=Sum("card_amount")))
        # Rashod (faqat APPROVED)
        exp_aggr = (Transaction.objects
                    .filter(type="expense", is_void=False, is_approved=True,
                            created_at__date__range=(date_from, date_to))
                    .filter(store_filter_q)
                    .aggregate(total=Sum("amount")))

        cash_in = Decimal(sale_aggr["cash"] or 0) + Decimal(debt_aggr["cash"] or 0)
        card_in = Decimal(sale_aggr["card"] or 0) + Decimal(debt_aggr["card"] or 0)
        exp_out = Decimal(exp_aggr["total"] or 0)
        return cash_in, card_in, exp_out

    cash_in, card_in, exp_out = _kassa_breakdown(start_date, end_date, store_q)

    # Komissiya: approved komissiyalar summasi, bo‘lmasa fallback 5$ * approved sale count
    comm_total = (SellerCommission.objects
                  .filter(is_approved=True, transaction__is_void=False,
                          transaction__created_at__date__range=(start_date, end_date))
                  .filter(
        transaction__store_id__in=store_ids if (getattr(request.user, "is_owner", False) and store_ids)
        else (
            [request.user.store_id] if not getattr(request.user, "is_owner", False) else Store.objects.values_list("id",
                                                                                                                   flat=True)))
                  .aggregate(total=Sum("amount"))["total"] or 0)
    if not comm_total:
        appr_sale_count = (Transaction.objects
                           .filter(type="sale", is_void=False, is_approved=True,
                                   created_at__date__range=(start_date, end_date))
                           .filter(store_q).count())
        comm_total = Decimal(appr_sale_count) * Decimal("5")

    kassa_total = cash_in + card_in - exp_out - Decimal(comm_total)

    context = {
        "period": period, "days": days, "start_date": start_date, "end_date": end_date,
        "rows": rows,
        "total_sales": tot_sales, "total_profit": tot_profit,
        "total_expense": tot_exp, "total_commission": tot_comm, "total_cons": tot_cons,
        "total_net": tot_profit - tot_exp - tot_comm - tot_cons,
        "stores": stores, "store_ids": store_ids,
        "cash_in": cash_in,
        "card_in": card_in,
        "kassa_total": kassa_total,
    }
    return render(request, "reports/profit_overview.html", context)


