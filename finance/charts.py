# finance/charts.py
from datetime import timedelta, datetime
from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum
from django.core.exceptions import FieldError

from sales.models import Transaction
from finance.models import Account

DEC0 = Decimal("0")

def _drange(days=30):
    end = timezone.localdate()
    start = end - timedelta(days=days-1)
    cur = start
    out = []
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out

def _day_bounds(d):
    # har kun uchun tz-aware start/end (UTC-aware)
    start_naive = datetime.combine(d, datetime.min.time())
    start = timezone.make_aware(start_naive, timezone.get_current_timezone())
    end = start + timedelta(days=1)
    return start, end

def _filter_by_any_date(qs, start, end):
    """
    Transaction’ni (created_at | approved_at | paid_at) bo‘yicha filtrlash.
    Qaysi maydon mavjud bo‘lsa — shuni ishlatadi.
    """
    date_fields = ("created_at", "approved_at", "paid_at")
    last_err = None
    for f in date_fields:
        try:
            # sinab ko‘ramiz: agar maydon bo‘lmasa FieldError qaytadi
            return qs.filter(**{f"{f}__gte": start, f"{f}__lt": end})
        except FieldError as e:
            last_err = e
            continue
    # hech biri topilmasa — filtrlashsiz qaytaramiz (grafik 0 chiqadi)
    return qs

def sales_profit_series(days=30, store=None, user=None):
    """
    Kunlik: Transaction(type='sale', is_approved=True, is_void=False)
    Sotuv: amount, Tannarx: cost, Foyda: profit
    """
    labels, sales_vals, cost_vals, profit_vals = [], [], [], []
    for d in _drange(days):
        start, end = _day_bounds(d)

        qs = Transaction.objects.filter(
            type="sale",
            is_approved=True,
            is_void=False,
        )
        # Sana bo‘yicha xavfsiz filter
        qs = _filter_by_any_date(qs, start, end)

        # ixtiyoriy store cheklovi
        if store is not None:
            qs = qs.filter(store=store)
        elif user is not None and not getattr(user, "is_owner", False):
            qs = qs.filter(store=getattr(user, "store", None))

        agg = qs.aggregate(
            s=Sum("amount"),
            c=Sum("cost"),
            p=Sum("profit"),
        )
        labels.append(d.strftime("%m-%d"))
        sales_vals.append(agg["s"] or DEC0)
        cost_vals.append(agg["c"] or DEC0)
        profit_vals.append(agg["p"] or DEC0)

    return {"labels": labels, "sales": sales_vals, "cost": cost_vals, "profit": profit_vals}

def ledger_expense_series(days=30):
    from finance.services import _sum_account
    labels, expense_vals = [], []
    for d in _drange(days):
        val = _sum_account(Account.CODE_EXPENSES, d, d)
        labels.append(d.strftime("%m-%d"))
        expense_vals.append(val or DEC0)
    return {"labels": labels, "expense": expense_vals}
