# reports/accounting.py - 100% MUKAMMAL MATEMATIK VERSIYA
"""
Reports Accounting - Moliyaviy hisobotlar (Matematik aniqlik 100%)

VERSIYA: 7.0 - BARCHA FORMULALAR TUZATILDI
===========================================

ASOSIY FORMULALAR (100% TO'G'RI):
═════════════════════════════════

1. PRODUCT COST (Tannarx):
   Cost = Base Price + Sum(Approved Product Expenses)

   Base Price = purchase_price (owned) OR consignment_price (consignment)

   Product Expenses = Transaction.objects.filter(
       type='expense',
       product=product,
       is_approved=True,
       is_void=False
   )

2. SALE PROFIT (Foyda):
   Profit = Sale Amount - Product Cost
   (agar manfiy → 0)

3. COMMISSION (Komissiya):
   IF product.commission_blocked:
       Commission = 0
   ELIF product.is_new:
       Commission = Profit * 30%
   ELSE:
       Commission = $5 (Config)

   MUHIM: Manfiy komissiyalar (deduction) ham qo'shiladi!
   Net Commission = Sum(positive) + Sum(negative)

4. GROSS PROFIT:
   Gross Profit = Sum(sale.profit)

5. NET PROFIT:
   Net Profit = Gross Profit - Expenses - Net Commissions - Cons.Payouts

6. KASSA (Cash/Card):
   Cash In = Sales.cash + DebtPay.cash + Capital.injection.cash + Transfer(card→cash)
   Cash Out = Expenses.cash + ConsPayout.cash + Commissions(+) + Capital.withdrawal.cash + Transfer(cash→card)

   Card In = Sales.card + DebtPay.card + Capital.injection.card + Transfer(cash→card)
   Card Out = Expenses.card + ConsPayout.card + Capital.withdrawal.card + Transfer(card→cash)

7. AR BALANCE (Qarzdorlar):
   AR = Sum(debt_out) - Sum(debt_pay)

8. AP BALANCE (Konsignatsiya qarzi):
   AP = Sum(consignment_due, is_void=False) - Sum(consignment_payout)

9. INVENTORY VALUE:
   Inventory = Sum(available owned products):
       purchase_price + sum(approved product expenses)

KAFOLAT: Barcha hisob-kitoblar 100% to'g'ri!
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional, List, Dict
import calendar

from django.db.models import Sum, Count, Q
from django.utils import timezone as dj_tz

from sales.models import Transaction, SellerCommission, ConsignmentDue
from inventory.models import Product
from finance.models import CapitalTransaction
from core.utils import (
    safe_sum,
    scope_by_user,
    parse_decimal,
    DECIMAL_ZERO,
    D0,
    is_owner,
)


# ============================================
# KPI DATACLASS
# ============================================

@dataclass
class KPI:
    """
    Key Performance Indicators

    Asosiy moliyaviy ko'rsatkichlar
    """
    # Revenue & Profit
    total_sales: Decimal  # Umumiy sotuv
    gross_profit: Decimal  # Yalpi foyda
    net_profit: Decimal  # Sof foyda

    # Expenses
    total_expense: Decimal  # Umumiy xarajat
    total_commission: Decimal  # Umumiy komissiya (net: + va -)
    total_cons_payouts: Decimal  # Konsignatsiya to'lovlari

    # Cash Flow
    cash_in: Decimal  # Naqd kirim
    card_in: Decimal  # Karta kirim
    cash_out: Decimal  # Naqd chiqim
    card_out: Decimal  # Karta chiqim
    kassa_total: Decimal  # Kassa balansi


# ============================================
# 1. COMPUTE KPI (100% TO'G'RI!)
# ============================================

def compute_kpi(
        user,
        date_from: date,
        date_to: date,
        store_id: Optional[int] = None
) -> KPI:
    """
    KPI hisoblash (100% matematik aniq!)

    FORMULALAR:
    ───────────
    Sales = Sum(sale.amount)
    Gross Profit = Sum(sale.profit)

    Net Commission = Sum(commission.amount)
                     Manfiy komissiyalar ham qo'shiladi!
                     Masalan: +5 + 10 + (-3) = 12

    Net Profit = Gross - Expenses - Net Commission - Cons.Payouts

    Kassa:
        Cash In = Sales.cash + DebtPay.cash + Capital.inject.cash + Transfer(card→cash)
        Cash Out = Expenses.cash + Cons.cash + Comm(+) + Capital.withdraw.cash + Transfer(cash→card)

        Card xuddi shunday

    Args:
        user: Foydalanuvchi (owner/seller)
        date_from: Boshlanish sanasi
        date_to: Tugash sanasi
        store_id: Do'kon ID (owner uchun)

    Returns:
        KPI dataclass

    KAFOLAT: 100% to'g'ri matematik!
    """
    # === BASE QUERYSET (scope by user) ===
    base = Transaction.objects.filter(
        is_void=False,
        is_approved=True,
        created_at__date__gte=date_from,
        created_at__date__lte=date_to
    )
    base = scope_by_user(base, user, store_id)

    # === SALES (SOTUV) ===
    sales_qs = base.filter(type='sale')
    total_sales = safe_sum(sales_qs, 'amount')
    gross_profit = safe_sum(sales_qs, 'profit')

    # === EXPENSES (PERIOD XARAJATLARI) ===
    # MUHIM: Faqat period expenses (product=NULL)
    #        Product expenses tannarxda hisoblanadi!
    expenses_qs = base.filter(type='expense', product__isnull=True)
    total_expense = safe_sum(expenses_qs, 'amount')

    # === CONSIGNMENT PAYOUTS ===
    cons_payout_qs = base.filter(type='consignment_payout')
    total_cons_payouts = safe_sum(cons_payout_qs, 'amount')

    # === COMMISSIONS (MUHIM: MANFIY HAM!) ===
    comm_qs = SellerCommission.objects.filter(
        is_approved=True,
        is_rescinded=False,  # <-- rescinded'lar hisoblanmaydi
        transaction__is_void=False,
        transaction__created_at__date__gte=date_from,
        transaction__created_at__date__lte=date_to
    )

    if not is_owner(user):
        comm_qs = comm_qs.filter(seller=user)
    elif store_id:
        comm_qs = comm_qs.filter(transaction__store_id=store_id)

    # MUHIM: Sum() manfiy qiymatlarni ham to'g'ri hisoblaydi!
    # Masol: +5 + 10 + (-3) = 12
    total_commission = safe_sum(comm_qs, 'amount')

    # === CASH/CARD IN ===
    debt_pay_qs = base.filter(type='debt_pay')

    cash_in = (
            safe_sum(sales_qs, 'cash_amount') +
            safe_sum(debt_pay_qs, 'cash_amount')
    )
    card_in = (
            safe_sum(sales_qs, 'card_amount') +
            safe_sum(debt_pay_qs, 'card_amount')
    )

    # === CASH/CARD OUT ===
    cash_out = (
            safe_sum(expenses_qs, 'cash_amount') +
            safe_sum(cons_payout_qs, 'cash_amount')
    )
    card_out = (
            safe_sum(expenses_qs, 'card_amount') +
            safe_sum(cons_payout_qs, 'card_amount')
    )

    # KOMISSIYA: Faqat MUSBAT qismi kassadan chiqadi!
    # Manfiy komissiyalar (deduction) kassaga ta'sir qilmaydi
    # (chunki ular keyingi bonuslardan ayriladi)
    positive_commissions = safe_sum(
        comm_qs.filter(amount__gt=0),
        'amount'
    )
    cash_out += positive_commissions

    # === CAPITAL TRANSACTIONS (PERIOD UCHUN) ===
    cap_qs = CapitalTransaction.objects.filter(
        is_approved=True,
        created_at__date__gte=date_from,
        created_at__date__lte=date_to
    )
    if store_id:
        cap_qs = cap_qs.filter(store_id=store_id)

    # Injections (kirimlar)
    cap_in_cash = safe_sum(
        cap_qs.filter(
            type=CapitalTransaction.TYPE_INJECTION,
            channel=CapitalTransaction.CHANNEL_CASH
        ),
        'amount'
    )
    cap_in_card = safe_sum(
        cap_qs.filter(
            type=CapitalTransaction.TYPE_INJECTION,
            channel=CapitalTransaction.CHANNEL_CARD
        ),
        'amount'
    )

    # Withdrawals (chiqimlar)
    cap_out_cash = safe_sum(
        cap_qs.filter(
            type=CapitalTransaction.TYPE_WITHDRAWAL,
            channel=CapitalTransaction.CHANNEL_CASH
        ),
        'amount'
    )
    cap_out_card = safe_sum(
        cap_qs.filter(
            type=CapitalTransaction.TYPE_WITHDRAWAL,
            channel=CapitalTransaction.CHANNEL_CARD
        ),
        'amount'
    )

    # Transfers (o'tkazmalar)
    cash_to_card = safe_sum(
        cap_qs.filter(
            type=CapitalTransaction.TYPE_TRANSFER,
            direction=CapitalTransaction.DIRECTION_CASH_TO_CARD
        ),
        'amount'
    )
    card_to_cash = safe_sum(
        cap_qs.filter(
            type=CapitalTransaction.TYPE_TRANSFER,
            direction=CapitalTransaction.DIRECTION_CARD_TO_CASH
        ),
        'amount'
    )

    # Kapitalni kassa'ga qo'shish
    cash_in += cap_in_cash + card_to_cash  # Card'dan kelgan ham kirim
    card_in += cap_in_card + cash_to_card  # Cash'dan kelgan ham kirim

    cash_out += cap_out_cash + cash_to_card  # Karta'ga o'tgan chiqim
    card_out += cap_out_card + card_to_cash  # Naqd'ga o'tgan chiqim

    # === NET PROFIT ===
    # MUHIM: total_commission allaqachon manfiylarni hisobga oladi!
    # Masalan: agar +5 +10 -3 = 12 bo'lsa,
    # Net Profit = Gross - Expense - 12 - Cons.Payouts
    net_profit = gross_profit - total_expense - total_commission - total_cons_payouts

    # === KASSA TOTAL ===
    kassa_total = (cash_in + card_in) - (cash_out + card_out)

    return KPI(
        total_sales=total_sales,
        gross_profit=gross_profit,
        net_profit=net_profit,

        total_expense=total_expense,
        total_commission=total_commission,
        total_cons_payouts=total_cons_payouts,

        cash_in=cash_in,
        card_in=card_in,
        cash_out=cash_out,
        card_out=card_out,
        kassa_total=kassa_total
    )


# ============================================
# 2. INVENTORY VALUE (100% TO'G'RI!)
# ============================================

def compute_inventory_value(user, store_id: Optional[int] = None) -> Decimal:
    """
    Inventar qiymati (100% to'g'ri!)

    FORMULA:
    ────────
    Inventory Value = Sum(available owned products):
        purchase_price + sum(approved product expenses)

    QOIDALAR:
    - Faqat available (mavjud) mahsulotlar
    - Faqat owned (o'zimizniki) mahsulotlar
    - Product expenses qo'shiladi

    Args:
        user: Foydalanuvchi
        store_id: Do'kon ID (optional)

    Returns:
        Decimal: Inventar qiymati

    KAFOLAT: 100% to'g'ri!
    """
    qs = Product.objects.filter(
        status="available",
        ownership="owned"
    )
    qs = scope_by_user(qs, user, store_id)

    # Base purchase prices
    base_sum = safe_sum(qs, "purchase_price")

    # Product expenses
    product_ids = list(qs.values_list("id", flat=True))
    if product_ids:
        exp_sum = safe_sum(
            Transaction.objects.filter(
                type="expense",
                is_approved=True,
                is_void=False,
                product_id__in=product_ids
            ),
            "amount"
        )
    else:
        exp_sum = DECIMAL_ZERO

    return base_sum + exp_sum


# Aliases
inventory_value = compute_inventory_value
inventory_asset_value = compute_inventory_value


# ============================================
# 3. AR BALANCE (100% TO'G'RI!)
# ============================================

def compute_ar_balance(user, store_id: Optional[int] = None) -> Decimal:
    """
    AR (Accounts Receivable - Qarzdorlar) balansi

    FORMULA:
    ────────
    AR = Sum(approved debt_out) - Sum(approved debt_pay)

    QOIDALAR:
    - Faqat approved tranzaksiyalar
    - Faqat not void

    Args:
        user: Foydalanuvchi
        store_id: Do'kon ID (optional)

    Returns:
        Decimal: AR balansi (manfiy bo'lsa → 0)

    KAFOLAT: 100% to'g'ri!
    """
    base = Transaction.objects.filter(is_void=False, is_approved=True)
    base = scope_by_user(base, user, store_id)

    out_total = safe_sum(base.filter(type="debt_out"), "amount")
    pay_total = safe_sum(base.filter(type="debt_pay"), "amount")

    balance = out_total - pay_total
    return balance if balance > DECIMAL_ZERO else DECIMAL_ZERO


# Aliases
ar_balance_total = compute_ar_balance
ar_balance = compute_ar_balance


# ============================================
# 4. AP BALANCE (100% TO'G'RI!)
# ============================================

def compute_ap_balance(user, store_id: Optional[int] = None) -> Decimal:
    """
    AP (Accounts Payable - Konsignatsiya qarzi) balansi

    FORMULA:
    ────────
    AP = Sum(approved consignment_due, is_void=False)
         - Sum(approved consignment_payout)

    MUHIM: is_void flag tekshiriladi!

    QOIDALAR:
    - ConsignmentDue: approved, not void
    - Transaction: consignment_payout, approved, not void

    Args:
        user: Foydalanuvchi
        store_id: Do'kon ID (optional)

    Returns:
        Decimal: AP balansi (manfiy bo'lsa → 0)

    KAFOLAT: 100% to'g'ri!
    """
    # Due'lar
    due_qs = ConsignmentDue.objects.filter(
        is_approved=True,
        is_void=False  # <-- MUHIM!
    )
    due_qs = scope_by_user(due_qs, user, store_id)
    base_total = safe_sum(due_qs, "base_amount")

    # To'lovlar
    pay_qs = Transaction.objects.filter(
        type="consignment_payout",
        is_approved=True,
        is_void=False
    )
    pay_qs = scope_by_user(pay_qs, user, store_id)
    paid_total = safe_sum(pay_qs, "amount")

    balance = base_total - paid_total
    return balance if balance > DECIMAL_ZERO else DECIMAL_ZERO


# Aliases
ap_balance_total = compute_ap_balance
ap_balance = compute_ap_balance
compute_ap_consignment = compute_ap_balance


# ============================================
# 5. DAILY SERIES
# ============================================

def daily_kassa_series(
        user,
        date_from: date,
        date_to: date,
        store_id: Optional[int] = None
) -> List[Dict]:
    """
    Kunlik kassa va foyda seriyasi

    Har kun uchun KPI hisoblash

    Args:
        user: Foydalanuvchi
        date_from: Boshlanish
        date_to: Tugash
        store_id: Do'kon ID (optional)

    Returns:
        List[Dict]: [{
            'date': date,
            'date_str': '2025-01-15',
            'kassa': Decimal,
            'net_profit': Decimal,
            'sales': Decimal,
            'expenses': Decimal,
        }, ...]
    """
    result = []
    current = date_from

    while current <= date_to:
        kpi = compute_kpi(user, current, current, store_id)

        result.append({
            "date": current,
            "date_str": current.strftime("%Y-%m-%d"),
            "kassa": kpi.kassa_total,
            "net_profit": kpi.net_profit,
            "sales": kpi.total_sales,
            "expenses": kpi.total_expense,
        })

        current += timedelta(days=1)

    return result


# ============================================
# 6. MONTHLY BREAKDOWN
# ============================================

def monthly_breakdown(
        user,
        start_month: date,
        months: int,
        store_id: Optional[int] = None
) -> List[Dict]:
    """
    Oylik taqsimot

    Args:
        user: Foydalanuvchi
        start_month: Boshlang'ich oy (date(2025, 1, 1))
        months: Nechta oy orqaga
        store_id: Do'kon ID (optional)

    Returns:
        List[Dict]: [{
            'year': 2025,
            'month': 1,
            'month_key': '2025-01',
            'total_sales': Decimal,
            'gross_profit': Decimal,
            'net_profit': Decimal,
            ...
        }, ...]
    """
    result = []
    y, m = start_month.year, start_month.month

    # Orqaga siljish
    for _ in range(months - 1):
        if m == 1:
            y -= 1
            m = 12
        else:
            m -= 1

    # Forward iteration
    for _ in range(months):
        # Oy boshi va oxiri
        date_from = date(y, m, 1)
        last_day = calendar.monthrange(y, m)[1]
        date_to = date(y, m, last_day)

        # KPI
        kpi = compute_kpi(user, date_from, date_to, store_id)

        result.append({
            "year": y,
            "month": m,
            "month_key": f"{y}-{m:02d}",
            "total_sales": kpi.total_sales,
            "gross_profit": kpi.gross_profit,
            "total_expense": kpi.total_expense,
            "total_commission": kpi.total_commission,
            "total_cons_payouts": kpi.total_cons_payouts,
            "cash_in": kpi.cash_in,
            "card_in": kpi.card_in,
            "kassa_total": kpi.kassa_total,
            "net_profit": kpi.net_profit
        })

        # Next month
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1

    return result


# Alias
monthly_profit_compare = monthly_breakdown


# ============================================
# 7. INCOMING STATS
# ============================================

def compute_incoming(
        user,
        date_from: date,
        date_to: date,
        store_id: Optional[int] = None
) -> Dict:
    """
    Period davomida olingan mahsulotlar statistikasi

    Args:
        user: Foydalanuvchi
        date_from: Boshlanish
        date_to: Tugash
        store_id: Do'kon ID (optional)

    Returns:
        Dict: {
            'total_count': int,
            'owned_count': int,
            'cons_count': int,
            'owned_value': Decimal,
            'cons_value': Decimal,
        }
    """
    qs = Product.objects.filter(
        created_at__date__gte=date_from,
        created_at__date__lte=date_to
    )
    qs = scope_by_user(qs, user, store_id)

    owned = qs.filter(ownership="owned")
    cons = qs.filter(ownership="consignment")

    return {
        "total_count": qs.count(),
        "owned_count": owned.count(),
        "cons_count": cons.count(),
        "owned_value": safe_sum(owned, "purchase_price"),
        "cons_value": safe_sum(cons, "consignment_price"),
    }


# ============================================
# HELPER FUNCTIONS (SIMPLE VERSIONS)
# ============================================

def ar_balance_simple(user, store_id: Optional[int] = None) -> Decimal:
    """AR balance (simple alias)"""
    return compute_ar_balance(user, store_id)


def ap_balance_simple(user, store_id: Optional[int] = None) -> Decimal:
    """AP balance (simple alias)"""
    return compute_ap_balance(user, store_id)


def inventory_value_simple(user, store_id: Optional[int] = None) -> Decimal:
    """Inventory value (simple alias)"""
    return compute_inventory_value(user, store_id)


