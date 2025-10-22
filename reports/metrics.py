# reports/metrics.py — FULL REPLACE
from datetime import datetime
from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone as dj_tz

from sales.models import Transaction, SellerCommission

DEC0 = Decimal("0.00")

def _sum(qs, field="amount") -> Decimal:
    return qs.aggregate(s=Sum(field))["s"] or DEC0

def _date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def _scope(user, qs):
    if getattr(user, "is_owner", False):
        return qs
    return qs.filter(store_id=getattr(user, "store_id", None))

def sales_qs(user, df, dt):
    qs = Transaction.objects.filter(
        type="sale", is_void=False, is_approved=True,
        created_at__date__gte=df, created_at__date__lte=dt
    )
    return _scope(user, qs)

def debt_pay_qs(user, df, dt):
    qs = Transaction.objects.filter(
        type="debt_pay", is_approved=True, is_void=False,
        created_at__date__gte=df, created_at__date__lte=dt
    )
    return _scope(user, qs)

def all_expenses_qs(user, df, dt):
    # CASH FLOW uchun barcha approved expense’lar (product bor/yo'q — farqi yo'q)
    qs = Transaction.objects.filter(
        type="expense", is_approved=True, is_void=False,
        created_at__date__gte=df, created_at__date__lte=dt
    )
    return _scope(user, qs)

def cons_payout_qs(user, df, dt):
    qs = Transaction.objects.filter(
        type="consignment_payout", is_approved=True, is_void=False,
        created_at__date__gte=df, created_at__date__lte=dt
    )
    return _scope(user, qs)

def commissions_qs(user, df, dt):
    qs = SellerCommission.objects.filter(
        is_approved=True, is_rescinded=False,
        transaction__is_void=False,
        transaction__created_at__date__gte=df,
        transaction__created_at__date__lte=dt
    )
    if not getattr(user, "is_owner", False):
        qs = qs.filter(seller_id=user.id)
    return qs

def kpi_block(user, df, dt):
    from reports.accounting import compute_kpi
    # KPI-ni faqat accounting.compute_kpi dan olamiz (yagona manba!)
    k = compute_kpi(user, df, dt, store_id=None)
    return {
        "total_sales": k.total_sales,
        "gross_profit": k.gross_profit,
        "total_expense": k.total_expense,
        "total_commission": k.total_commission,
        "total_cons_payouts": k.total_cons_payouts,
        "cash_in": k.cash_in, "card_in": k.card_in,
        "kassa_total": k.kassa_total,
        "net_profit": k.net_profit,
    }

def kassa_cash_card_period_local(user, df, dt, store_id=None):
    # IN
    s = sales_qs(user, df, dt)
    d = debt_pay_qs(user, df, dt)
    cash_in = _sum(s, "cash_amount") + _sum(d, "cash_amount")
    card_in = _sum(s, "card_amount") + _sum(d, "card_amount")

    # OUT (split bo'yicha)
    exp = all_expenses_qs(user, df, dt)
    cns = cons_payout_qs(user, df, dt)

    cash_out = _sum(exp, "cash_amount") + _sum(cns, "cash_amount")
    card_out = _sum(exp, "card_amount") + _sum(cns, "card_amount")

    # Komissiyalar: approve bo'lganda kassadan chiqadi (soddalik uchun naqd deb qabul qilamiz)
    comm = commissions_qs(user, df, dt)
    cash_out += _sum(comm, "amount")

    return {
        "cash_open": DEC0,
        "cash_delta": (cash_in - cash_out),
        "cash_close": (cash_in - cash_out),

        "card_open": DEC0,
        "card_delta": (card_in - card_out),
        "card_close": (card_in - card_out),
    }
