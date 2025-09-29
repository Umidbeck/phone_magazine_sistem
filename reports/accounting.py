# reports/accounting.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional, Dict, Any, Iterable

from django.db.models import Sum, Q
from django.utils import timezone as dj_tz

from sales.models import Transaction, SellerCommission
from inventory.models import Product

DEC0 = Decimal("0.00")

def _scope(user, qs, store_id: Optional[int] = None):
    """
    Owner bo'lsa: store_id berilsa shu do'kon, bo'lmasa hammasi.
    Seller bo'lsa: faqat o'z do'koni.
    """
    if getattr(user, "is_owner", False):
        if store_id:
            return qs.filter(store_id=store_id)
        return qs
    return qs.filter(store_id=getattr(user, "store_id", None))

def _sum(qs, field: str) -> Decimal:
    return qs.aggregate(s=Sum(field))["s"] or DEC0

@dataclass
class Kpi:
    # Savdodan chiqadigan metrikalar
    total_sales: Decimal
    gross_profit: Decimal
    # Period rashod/komissiya/consignment (faqat approved)
    total_expense: Decimal
    total_commission: Decimal
    total_cons_payouts: Decimal
    # Kassa kirimlari (approved debt pay ham kiritiladi)
    cash_in: Decimal
    card_in: Decimal
    # Yakuniy kassa (siyosat: approved bo'lganda ayriladi)
    kassa_total: Decimal
    # Net profit (consignment payout net profitga kiritilmaydi)
    net_profit: Decimal

def _sales_qs(user, df, dt, store_id=None):
    qs = Transaction.objects.filter(
        type="sale", is_void=False, is_approved=True,
        created_at__date__gte=df, created_at__date__lte=dt
    )
    return _scope(user, qs, store_id)

def _period_expense_qs(user, df, dt, store_id=None):
    qs = Transaction.objects.filter(
        type="expense", is_approved=True, product__isnull=True,
        created_at__date__gte=df, created_at__date__lte=dt
    )
    return _scope(user, qs, store_id)

def _debt_pay_qs(user, df, dt, store_id=None):
    qs = Transaction.objects.filter(
        type="debt_pay", is_approved=True,
        created_at__date__gte=df, created_at__date__lte=dt
    )
    return _scope(user, qs, store_id)

def _cons_payout_qs(user, df, dt, store_id=None):
    qs = Transaction.objects.filter(
        type="consignment_payout", is_approved=True,
        created_at__date__gte=df, created_at__date__lte=dt
    )
    return _scope(user, qs, store_id)

def _commissions_qs(user, df, dt, store_id=None):
    qs = (SellerCommission.objects
          .select_related("transaction")
          .filter(is_approved=True,
                  transaction__is_void=False,
                  transaction__created_at__date__gte=df,
                  transaction__created_at__date__lte=dt))
    if getattr(user, "is_owner", False):
        if store_id:
            qs = qs.filter(transaction__store_id=store_id)
    else:
        qs = qs.filter(seller_id=user.id)
    return qs

def compute_kpi(user, df, dt, store_id: Optional[int] = None) -> Kpi:
    s = _sales_qs(user, df, dt, store_id)
    e = _period_expense_qs(user, df, dt, store_id)
    d = _debt_pay_qs(user, df, dt, store_id)
    cns = _cons_payout_qs(user, df, dt, store_id)
    com = _commissions_qs(user, df, dt, store_id)

    total_sales   = _sum(s, "amount")
    gross_profit  = _sum(s, "profit")
    total_expense = _sum(e, "amount")
    cons_payouts  = _sum(cns, "amount")
    total_comm    = _sum(com, "amount")

    sales_cash = _sum(s, "cash_amount")
    sales_card = _sum(s, "card_amount")
    debt_cash  = _sum(d, "cash_amount")
    debt_card  = _sum(d, "card_amount")

    cash_in = sales_cash + debt_cash
    card_in = sales_card + debt_card

    # Kassa siyosati: approved bo‘lganda kassadan ayriladi
    kassa_total = (cash_in + card_in) - total_expense - cons_payouts - total_comm

    # Net profit: consignment payout NETga kirmaydi (hisob-kitob item)
    net_profit = gross_profit - total_expense - total_comm

    return Kpi(
        total_sales=total_sales,
        gross_profit=gross_profit,
        total_expense=total_expense,
        total_commission=total_comm,
        total_cons_payouts=cons_payouts,
        cash_in=cash_in,
        card_in=card_in,
        kassa_total=kassa_total,
        net_profit=net_profit,
    )

# ---- Qarzdorlar (balans) ----
@dataclass
class DebtTotals:
    total: Decimal
    paid: Decimal
    cash_paid: Decimal
    card_paid: Decimal
    balance: Decimal

def compute_debts_total(user, df, dt, store_id: Optional[int] = None) -> DebtTotals:
    base = Transaction.objects.filter(is_void=False,
                                      created_at__date__gte=df, created_at__date__lte=dt)
    base = _scope(user, base, store_id)
    out = base.filter(type="debt_out", is_approved=True).aggregate(s=Sum("amount"))["s"] or DEC0
    pay = base.filter(type="debt_pay", is_approved=True).aggregate(
        paid=Sum("amount"), cash=Sum("cash_amount"), card=Sum("card_amount")
    )
    paid = pay.get("paid") or DEC0
    cash = pay.get("cash") or DEC0
    card = pay.get("card") or DEC0
    bal = (out - paid)
    return DebtTotals(out, paid, cash, card, bal)

# ---- Olinganlar (kirim/inventory) ----
@dataclass
class IncomingTotals:
    count: int
    owned_value: Decimal
    consignment_value: Decimal
    all_value: Decimal

def compute_incoming(user, df, dt, store_id: Optional[int] = None) -> IncomingTotals:
    """
    Kirim: df..dt oralig'ida yaratilgan yoki 'available' bo‘lgan mahsulotlar.
    Agar alohida “kirim” tranzaksiyasi yo‘q bo‘lsa, Product yaratilish sanasi asosida olish mumkin.
    """
    qs = Product.objects.filter(created_at__date__gte=df, created_at__date__lte=dt)
    if getattr(user, "is_owner", False):
        if store_id: qs = qs.filter(store_id=store_id)
    else:
        qs = qs.filter(store_id=getattr(user, "store_id", None))

    owned_val = _sum(qs.filter(ownership="owned"), "purchase_price")
    cons_val  = _sum(qs.filter(ownership="consignment"), "consignment_price")
    cnt = qs.count()
    return IncomingTotals(count=cnt, owned_value=owned_val, consignment_value=cons_val,
                          all_value=(owned_val + cons_val))

# ---- Kassa kunma-kun va oyma-oy (grafik/taqqoslash uchun) ----
def daily_kassa_series(user, start: date, end: date, store_id: Optional[int] = None):
    """
    Har kuni '0 dan boshlansin' prinsipi: har kuni kiritmalar-chiqarishlar alohida hisoblanadi.
    """
    cur = start
    rows = []
    while cur <= end:
        df = cur
        dt = cur
        k = compute_kpi(user, df, dt, store_id)
        rows.append({
            "date": cur,
            "cash_in": k.cash_in,
            "card_in": k.card_in,
            "kassa": k.kassa_total,
            "net_profit": k.net_profit,
        })
        cur += timedelta(days=1)
    return rows

def monthly_profit_compare(user, start_month: date, months: int, store_id: Optional[int] = None):
    """
    Oxirgi N oy bo‘yicha net_profit, kassa_totalni taqqoslash.
    start_month – oyning 1-sanasiga tekislab yuboring.
    """
    res = []
    year = start_month.year
    month = start_month.month
    for i in range(months):
        df = date(year, month, 1)
        if month == 12:
            dt = date(year, 12, 31)
        else:
            dt = date(year, month+1, 1) - timedelta(days=1)
        k = compute_kpi(user, df, dt, store_id)
        res.append({"year": year, "month": month, "kassa": k.kassa_total, "net_profit": k.net_profit})
        # back one month
        if month == 1:
            month = 12; year -= 1
        else:
            month -= 1
    return list(reversed(res))


def monthly_breakdown(user, start_month: date, months: int, store_id: Optional[int] = None):
    """
    Oyma-oy kengaytirilgan KPI: savdo, gross, period expense, commission, consignment payouts,
    cash_in, card_in, kassa_total, net_profit.
    start_month: oyning 1-sanasiga tekislangan sanani bering (masalan, today.replace(day=1))
    months: nechta oy orqaga (masalan, 24)
    """
    res = []
    y, m = start_month.year, start_month.month
    for _ in range(months):
        df = date(y, m, 1)
        if m == 12:
            dt = date(y, 12, 31)
        else:
            dt = date(y, m + 1, 1) - timedelta(days=1)

        k = compute_kpi(user, df, dt, store_id)
        res.append({
            "year": y, "month": m,
            "total_sales": k.total_sales,
            "gross_profit": k.gross_profit,
            "total_expense": k.total_expense,
            "total_commission": k.total_commission,
            "total_cons_payouts": k.total_cons_payouts,
            "cash_in": k.cash_in, "card_in": k.card_in,
            "kassa_total": k.kassa_total, "net_profit": k.net_profit,
        })

        # oldingi oyga o‘tamiz
        if m == 1:
            m = 12; y -= 1
        else:
            m -= 1
    return list(reversed(res))
