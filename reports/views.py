from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.shortcuts import render
from django.db.models import Sum
from django.utils.translation import gettext as _
from accounts.models import Store
from inventory.models import Product
from sales.models import Transaction

@login_required
def store_report(request):
    # Sana oralig'i
    period = (request.GET.get("period") or "30").strip()  # 7/30/90/365/custom
    today = date.today()
    if period.isdigit():
        days = int(period)
        date_from = today - timedelta(days=days)
        date_to = today
    else:
        # TODO: custom from/to
        date_from = today - timedelta(days=30)
        date_to = today

    store_id = request.GET.get("store")
    stores = Store.objects.filter(is_active=True).order_by("name")
    if not request.user.is_owner():
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
        "date_from": date_from, "date_to": date_to,
        "sales_sum": sales_sum, "cost_sum": cost_sum,
        "profit_sum": profit_sum, "expense_sum": expense_sum,
    }
    return render(request, "reports/store_report.html", ctx)

@login_required
def network_report(request):
    # period (kun)
    period = int((request.GET.get("period") or "30"))
    today = date.today()
    date_from = today - timedelta(days=period)

    qs = Transaction.objects.filter(created_at__date__gte=date_from, created_at__date__lte=today, type="sale")
    if not request.user.is_owner():
        qs = qs.filter(store_id=request.user.store_id)

    cache_key = f"netreport:{'all' if request.user.is_owner() else request.user.store_id}:{period}"
    cached = cache.get(cache_key)
    if cached:
        return render(request, "reports/network_report.html", cached)

    # TOP stores
    top_stores = list(qs.values("store__name").annotate(s=Sum("amount")).order_by("-s")[:5])

    # TOP brands/models
    # Transaction->Product via FK; transaction.product_id bilan join qilamiz
    prod_qs = Product.objects.filter(id__in=qs.values("product_id"))
    top_brands = list(prod_qs.values("brand__name").annotate(s=Sum("purchase_price")).order_by("-s")[:5])
    # brand kesimida sotuv summasi kerak bo'lsa, transactiondan group qilib join qilish murakkab — soddaroq variant:
    # product_id bo'yicha transaction.amount’larni yig’ib brand’ga ko‘tarish uchun alohida join kerak.
    # Minimal: model bo‘yicha product count
    top_models = list(prod_qs.values("brand__name","model__name").annotate(cnt=Sum(1)).order_by("-cnt")[:5])

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
    """Owner uchun umumiy panel. Seller kirsa — faqat o‘z dukoni doirasida ko‘radi."""
    days = int((request.GET.get("days") or "30"))
    today = date.today()
    date_from = today - timedelta(days=days-1)

    base = Transaction.objects.filter(
        type="sale",
        created_at__date__gte=date_from,
        created_at__date__lte=today,
    )
    if not request.user.is_owner():
        base = base.filter(store_id=request.user.store_id)

    cache_key = f"owner_dash:{'all' if request.user.is_owner() else request.user.store_id}:{days}"
    cached = cache.get(cache_key)
    if cached:
        return render(request, "reports/dashboard.html", cached)

    # --- Time series (kunlik sotuv summasi) ---
    # Eslatma: bu soddalashtirilgan Python tarafda to‘ldirish — DB grouping bilan ham qilsa bo‘ladi.
    sales_by_day_map = dict(
        base.values("created_at__date").annotate(s=Sum("amount")).values_list("created_at__date","s")
    )
    labels, series = [], []
    for i in range(days):
        d = date_from + timedelta(days=i)
        labels.append(d.isoformat())
        series.append(float(sales_by_day_map.get(d, Decimal("0")) or 0))

    # --- TOP stores (amount bo‘yicha) ---
    top_stores = list(
        base.values("store__name").annotate(s=Sum("amount")).order_by("-s")[:5]
    )

    # --- TOP brands/models (amount bo‘yicha, to‘liq join) ---
    # Transaction -> product -> brand/model
    top_brands = list(
        base.values("product__brand__name").annotate(s=Sum("amount")).order_by("-s")[:5]
    )
    top_models = list(
        base.values("product__brand__name","product__model__name")
            .annotate(s=Sum("amount")).order_by("-s")[:5]
    )

    ctx = {
        "days": days,
        "date_from": date_from, "date_to": today,
        "labels": labels, "series": series,
        "top_stores": top_stores,
        "top_brands": top_brands,
        "top_models": top_models,
        "is_owner": request.user.is_owner(),
    }
    cache.set(cache_key, ctx, 300)
    return render(request, "reports/dashboard.html", ctx)