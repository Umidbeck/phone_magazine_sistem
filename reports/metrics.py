# reports/metrics.py
from datetime import datetime
from decimal import Decimal
from django.db.models import Sum, Q
from django.utils import timezone as dj_tz

from sales.models import Transaction, SellerCommission

DEC0 = Decimal("0")

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

def period_expenses_qs(user, df, dt):
    # product=NULL bo‘lgan approved rashodlar
    qs = Transaction.objects.filter(
        type="expense", is_approved=True, product__isnull=True,
        created_at__date__gte=df, created_at__date__lte=dt
    )
    return _scope(user, qs)

def debt_pay_qs(user, df, dt):
    qs = Transaction.objects.filter(
        type="debt_pay", is_approved=True,
        created_at__date__gte=df, created_at__date__lte=dt
    )
    return _scope(user, qs)

def cons_payout_qs(user, df, dt):
    qs = Transaction.objects.filter(
        type="consignment_payout", is_approved=True,
        created_at__date__gte=df, created_at__date__lte=dt
    )
    return _scope(user, qs)

def commissions_qs(user, df, dt):
    qs = (SellerCommission.objects
          .select_related("transaction")
          .filter(is_approved=True,
                  transaction__is_void=False,
                  transaction__created_at__date__gte=df,
                  transaction__created_at__date__lte=dt))
    if not getattr(user, "is_owner", False):
        qs = qs.filter(seller_id=user.id)
    return qs

def kpi_block(user, df, dt):
    s = sales_qs(user, df, dt)
    e = period_expenses_qs(user, df, dt)
    d = debt_pay_qs(user, df, dt)
    cns = cons_payout_qs(user, df, dt)
    com = commissions_qs(user, df, dt)

    total_sales   = _sum(s, "amount")
    gross_profit  = _sum(s, "profit")
    total_expense = _sum(e, "amount")
    total_comm    = _sum(com, "amount")
    cons_payouts  = _sum(cns, "amount")

    sales_cash = _sum(s, "cash_amount")
    sales_card = _sum(s, "card_amount")
    debt_cash  = _sum(d, "cash_amount")
    debt_card  = _sum(d, "card_amount")

    cash_in = sales_cash + debt_cash
    card_in = sales_card + debt_card

    # KASSA: siz tanlagan siyosat = komissiya tasdiqlanganda kassadan ayiramiz
    kassa_total = (cash_in + card_in) - total_expense - cons_payouts - total_comm

    # NET PROFIT: cons_payouts bu yerga kiritilmaydi
    net_profit = gross_profit - total_expense - total_comm

    return {
        "total_sales": total_sales,
        "gross_profit": gross_profit,
        "total_expense": total_expense,
        "total_commission": total_comm,
        "total_cons_payouts": cons_payouts,

        "cash_in": cash_in,
        "card_in": card_in,
        "kassa_total": kassa_total,

        "net_profit": net_profit,
    }
