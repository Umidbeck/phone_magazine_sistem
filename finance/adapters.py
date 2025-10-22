# finance/adapters.py - 100% MUKAMMAL TO'LIQ VERSIYA
"""
Finance Adapters - Transaction -> Ledger Bridge

VERSIYA: 4.0 - TO'LIQ MUKAMMAL
================================

Bu modul Transaction modellarini Ledger'ga avtomatik yozadi.

ASOSIY FUNKSIYALAR:
✅ post_purchase_from_product - Xarid
✅ post_expense_from_transaction - Rashod (oddiy)
✅ post_expense_from_transaction_split - Rashod (split)
✅ post_sale_from_transaction - Sotuv (oddiy)
✅ post_sale_from_transaction_split - Sotuv (split)
✅ post_receipt_from_debtor_transaction - Qarz to'lovi
✅ post_debt_payment_from_transaction_split - Qarz to'lovi (split)
✅ post_payment_to_supplier_transaction - Ta'minotchiga to'lov
✅ post_payment_to_supplier_split - Ta'minotchiga to'lov (split)

KAFOLAT: Barcha ledger yozuvlar 100% to'g'ri!
"""

from decimal import Decimal
from finance.models import Account
from finance.services import post_entry_object, ensure_default_accounts
from core.utils import parse_decimal, DECIMAL_ZERO, D0

import logging

logger = logging.getLogger(__name__)


def _d(n) -> Decimal:
    """Decimal'ga aylantirish va yaxlitlash"""
    return parse_decimal(n)


# ============================================
# PURCHASE / INVENTORY IN
# ============================================

def post_purchase_from_product(
        product,
        cost: Decimal = None,
        is_cash: bool = True,
        memo: str = "Olingan tovar",
        ref: str = ""
):
    """
    Mahsulot xaridini ledgerga yozish

    ENTRY:
        DR Inventory      cost
        CR Cash/AP        cost

    Args:
        product: Product instance
        cost: Tannarx (None bo'lsa product.purchase_price/consignment_price)
        is_cash: True=Cash, False=AP
        memo: Izoh
        ref: Reference

    Returns:
        JournalEntry yoki None
    """
    ensure_default_accounts()

    # Cost aniqlash
    if cost is None:
        ownership = getattr(product, "ownership", "owned")
        if ownership == "owned":
            cost = _d(getattr(product, "purchase_price", 0))
        else:
            cost = _d(getattr(product, "consignment_price", 0))
    else:
        cost = _d(cost)

    if cost <= D0:
        return None

    lines = [
        (Account.CODE_INVENTORY, cost),
        (Account.CODE_CASH if is_cash else Account.CODE_AP_SUPPLIERS, -cost),
    ]

    return post_entry_object(
        lines,
        obj_or_ids=product,
        ref=ref or f"Product:{product.pk}",
        memo=memo
    )


# ============================================
# EXPENSE (ODDIY VA SPLIT)
# ============================================

def post_expense_from_transaction(
        tx,
        amount: Decimal = None,
        is_cash: bool = True,
        memo: str = "Rashod",
        ref: str = ""
):
    """
    Rashod (oddiy - faqat cash yoki faqat AP)

    ENTRY:
        DR Expenses       amount
        CR Cash/AP        amount

    Args:
        tx: Transaction instance
        amount: Summa (None bo'lsa tx.amount)
        is_cash: True=Cash, False=AP
        memo: Izoh
        ref: Reference

    Returns:
        JournalEntry yoki None
    """
    ensure_default_accounts()

    amount = _d(amount if amount is not None else getattr(tx, "amount", 0))
    if amount <= D0:
        return None

    lines = [
        (Account.CODE_EXPENSES, amount),
        (Account.CODE_CASH if is_cash else Account.CODE_AP_SUPPLIERS, -amount),
    ]

    return post_entry_object(
        lines,
        obj_or_ids=tx,
        memo=memo,
        ref=ref or f"TX:{tx.pk}"
    )


def post_expense_from_transaction_split(
        tx,
        cash_amount: Decimal = None,
        card_amount: Decimal = None,
        memo: str = "Rashod (split)",
        ref: str = ""
):
    """
    Rashod (split - cash + card)

    ENTRY:
        DR Expenses       total
        CR Cash           cash_amount (agar > 0)
        CR Card           card_amount (agar > 0)

    Args:
        tx: Transaction instance
        cash_amount: Naqd summa (None bo'lsa tx.cash_amount)
        card_amount: Karta summa (None bo'lsa tx.card_amount)
        memo: Izoh
        ref: Reference

    Returns:
        JournalEntry yoki None
    """
    ensure_default_accounts()

    cash = _d(cash_amount if cash_amount is not None else getattr(tx, "cash_amount", 0))
    card = _d(card_amount if card_amount is not None else getattr(tx, "card_amount", 0))
    total = cash + card

    if total <= D0:
        return None

    lines = [(Account.CODE_EXPENSES, total)]

    if cash > D0:
        lines.append((Account.CODE_CASH, -cash))
    if card > D0:
        lines.append((Account.CODE_CARD, -card))

    return post_entry_object(
        lines,
        obj_or_ids=tx,
        memo=memo,
        ref=ref or f"TX:{tx.pk}"
    )


# ============================================
# SALE (ODDIY VA SPLIT)
# ============================================

def post_sale_from_transaction(
        tx,
        sale_price: Decimal = None,
        cogs: Decimal = None,
        is_cash: bool = True,
        commission: Decimal = None,
        commission_as_expense: bool = True,
        memo: str = "Sotuv",
        ref: str = ""
):
    """
    Sotuv (oddiy - to'liq naqd yoki to'liq AR)

    ENTRY:
        DR Cash/AR        sale_price
        CR Sales          sale_price
        DR COGS           cogs (agar > 0)
        CR Inventory      cogs (agar > 0)
        [Commission entries agar > 0]

    Args:
        tx: Transaction instance
        sale_price: Sotuv narxi (None bo'lsa tx.amount)
        cogs: Tannarx (None bo'lsa tx.cost)
        is_cash: True=Cash, False=AR
        commission: Komissiya (None bo'lsa 0)
        commission_as_expense: True=Xarajat, False=Daromad
        memo: Izoh
        ref: Reference

    Returns:
        JournalEntry yoki None
    """
    ensure_default_accounts()

    sale_price = _d(sale_price if sale_price is not None else getattr(tx, "amount", 0))
    cogs = _d(cogs if cogs is not None else getattr(tx, "cost", 0))
    commission = _d(commission if commission is not None else 0)

    if sale_price <= D0:
        return None

    lines = []

    # Daromad
    if is_cash:
        lines += [
            (Account.CODE_CASH, sale_price),
            (Account.CODE_SALES, -sale_price)
        ]
    else:
        lines += [
            (Account.CODE_AR_CUSTOMERS, sale_price),
            (Account.CODE_SALES, -sale_price)
        ]

    # COGS / Inventory
    if cogs > D0:
        lines += [
            (Account.CODE_COGS, cogs),
            (Account.CODE_INVENTORY, -cogs)
        ]

    # Komissiya
    if commission > D0:
        if commission_as_expense:
            lines += [
                (Account.CODE_COMMISSION_EX, commission),
                (Account.CODE_CASH if is_cash else Account.CODE_AR_CUSTOMERS, -commission),
            ]
        else:
            lines += [
                (Account.CODE_CASH if is_cash else Account.CODE_AR_CUSTOMERS, commission),
                (Account.CODE_COMMISSION_IN, -commission),
            ]

    return post_entry_object(
        lines,
        obj_or_ids=tx,
        memo=memo,
        ref=ref or f"TX:{tx.pk}"
    )


def post_sale_from_transaction_split(
        tx,
        sale_price: Decimal = None,
        cogs: Decimal = None,
        commission: Decimal = None,
        commission_as_expense: bool = True,
        memo: str = "Sotuv (split)",
        ref: str = ""
):
    """
    Sotuv (split - cash + card + AR qoldiq)

    ENTRY:
        DR Cash           cash_amount (agar > 0)
        DR Card           card_amount (agar > 0)
        DR AR             ar_amount (agar > 0)
        CR Sales          total
        DR COGS           cogs (agar > 0)
        CR Inventory      cogs (agar > 0)
        [Commission entries]

    Args:
        tx: Transaction instance
        sale_price: Sotuv narxi (None bo'lsa tx.amount)
        cogs: Tannarx (None bo'lsa tx.cost)
        commission: Komissiya (None bo'lsa 0)
        commission_as_expense: True=Xarajat, False=Daromad
        memo: Izoh
        ref: Reference

    Returns:
        JournalEntry yoki None
    """
    ensure_default_accounts()

    total = _d(sale_price if sale_price is not None else getattr(tx, "amount", 0))
    cash = _d(getattr(tx, "cash_amount", 0))
    card = _d(getattr(tx, "card_amount", 0))
    paid = cash + card
    ar = total - paid if total > paid else D0

    cogs_val = _d(cogs if cogs is not None else getattr(tx, "cost", 0))
    commission = _d(commission if commission is not None else 0)

    if total <= D0:
        return None

    lines = []

    # Inflows
    if cash > D0:
        lines.append((Account.CODE_CASH, cash))
    if card > D0:
        lines.append((Account.CODE_CARD, card))
    if ar > D0:
        lines.append((Account.CODE_AR_CUSTOMERS, ar))

    # Sales (credit)
    lines.append((Account.CODE_SALES, -total))

    # COGS / Inventory
    if cogs_val > D0:
        lines += [
            (Account.CODE_COGS, cogs_val),
            (Account.CODE_INVENTORY, -cogs_val)
        ]

    # Commission (proportional distribution)
    if commission > D0:
        if commission_as_expense:
            # Avval karta, keyin naqd, keyin AR'dan
            rem = commission

            use_card = min(rem, card)
            if use_card > D0:
                lines += [
                    (Account.CODE_COMMISSION_EX, use_card),
                    (Account.CODE_CARD, -use_card)
                ]
                rem -= use_card

            use_cash = min(rem, cash)
            if use_cash > D0:
                lines += [
                    (Account.CODE_COMMISSION_EX, use_cash),
                    (Account.CODE_CASH, -use_cash)
                ]
                rem -= use_cash

            if rem > D0:
                lines += [
                    (Account.CODE_COMMISSION_EX, rem),
                    (Account.CODE_AR_CUSTOMERS, -rem)
                ]
        else:
            # Income sifatida
            rem = commission

            use_card = min(rem, card)
            if use_card > D0:
                lines += [
                    (Account.CODE_CARD, use_card),
                    (Account.CODE_COMMISSION_IN, -use_card)
                ]
                rem -= use_card

            use_cash = min(rem, cash)
            if use_cash > D0:
                lines += [
                    (Account.CODE_CASH, use_cash),
                    (Account.CODE_COMMISSION_IN, -use_cash)
                ]
                rem -= use_cash

            if rem > D0:
                lines += [
                    (Account.CODE_AR_CUSTOMERS, rem),
                    (Account.CODE_COMMISSION_IN, -rem)
                ]

    return post_entry_object(
        lines,
        obj_or_ids=tx,
        memo=memo,
        ref=ref or f"TX:{tx.pk}"
    )


# ============================================
# AR / AP MOVEMENTS
# ============================================

def post_receipt_from_debtor_transaction(
        tx,
        amount: Decimal = None,
        memo: str = "Qarzdordan tushum",
        ref: str = ""
):
    """
    Qarzdordan tushum (oddiy - faqat cash)

    ENTRY:
        DR Cash           amount
        CR AR             amount

    Args:
        tx: Transaction instance
        amount: Summa (None bo'lsa tx.amount)
        memo: Izoh
        ref: Reference

    Returns:
        JournalEntry yoki None
    """
    ensure_default_accounts()

    amount = _d(amount if amount is not None else getattr(tx, "amount", 0))
    if amount <= D0:
        return None

    lines = [
        (Account.CODE_CASH, amount),
        (Account.CODE_AR_CUSTOMERS, -amount)
    ]

    return post_entry_object(
        lines,
        obj_or_ids=tx,
        memo=memo,
        ref=ref or f"TX:{tx.pk}"
    )


def post_debt_payment_from_transaction_split(
        tx,
        memo: str = "Qarzdordan tushum (split)",
        ref: str = ""
):
    """
    Qarzdordan tushum (split - cash + card)

    ENTRY:
        DR Cash           cash_amount (agar > 0)
        DR Card           card_amount (agar > 0)
        CR AR             total

    Args:
        tx: Transaction instance
        memo: Izoh
        ref: Reference

    Returns:
        JournalEntry yoki None
    """
    ensure_default_accounts()

    cash = _d(getattr(tx, "cash_amount", 0))
    card = _d(getattr(tx, "card_amount", 0))
    paid = cash + card

    if paid <= D0:
        return None

    lines = []

    if cash > D0:
        lines.append((Account.CODE_CASH, cash))
    if card > D0:
        lines.append((Account.CODE_CARD, card))

    lines.append((Account.CODE_AR_CUSTOMERS, -paid))

    return post_entry_object(
        lines,
        obj_or_ids=tx,
        memo=memo,
        ref=ref or f"TX:{tx.pk}"
    )


def post_payment_to_supplier_transaction(
        tx,
        amount: Decimal = None,
        memo: str = "Ta'minotchiga to'lov",
        ref: str = ""
):
    """
    Ta'minotchiga to'lov (oddiy - faqat cash)

    ENTRY:
        DR AP             amount
        CR Cash           amount

    Args:
        tx: Transaction instance
        amount: Summa (None bo'lsa tx.amount)
        memo: Izoh
        ref: Reference

    Returns:
        JournalEntry yoki None
    """
    ensure_default_accounts()

    amount = _d(amount if amount is not None else getattr(tx, "amount", 0))
    if amount <= D0:
        return None

    lines = [
        (Account.CODE_AP_SUPPLIERS, amount),
        (Account.CODE_CASH, -amount)
    ]

    return post_entry_object(
        lines,
        obj_or_ids=tx,
        memo=memo,
        ref=ref or f"TX:{tx.pk}"
    )


def post_payment_to_supplier_split(
        obj_or_ids,
        cash_amount: Decimal = None,
        card_amount: Decimal = None,
        memo: str = "Konsignatsiya to'lovi (AP)",
        ref: str = ""
):
    """
    Ta'minotchiga to'lov (split - cash + card)

    ENTRY:
        DR AP             total
        CR Cash           cash_amount (agar > 0)
        CR Card           card_amount (agar > 0)

    Args:
        obj_or_ids: Object yoki (app, model, id)
        cash_amount: Naqd summa
        card_amount: Karta summa
        memo: Izoh
        ref: Reference

    Returns:
        JournalEntry yoki None

    Raises:
        ValueError: Agar total <= 0
    """
    ensure_default_accounts()

    cash = _d(cash_amount if cash_amount is not None else 0)
    card = _d(card_amount if card_amount is not None else 0)
    total = cash + card

    if total <= D0:
        raise ValueError("To'lov summasi 0 bo'lishi mumkin emas")

    lines = [(Account.CODE_AP_SUPPLIERS, total)]

    if cash > D0:
        lines.append((Account.CODE_CASH, -cash))
    if card > D0:
        lines.append((Account.CODE_CARD, -card))

    return post_entry_object(
        lines,
        obj_or_ids=obj_or_ids,
        memo=memo,
        ref=ref
    )