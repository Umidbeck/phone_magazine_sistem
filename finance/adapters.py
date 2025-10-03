from decimal import Decimal
from typing import Optional
from django.utils import timezone
from .services import (
    post_entry_object, ensure_default_accounts,
)
from .models import Account

# --- Olinganlar (Purchase) ---
def post_purchase_from_domain(obj, *, cost, is_cash: bool, ref: str = "", memo: str = "Olingan tovar", date=None):
    """
    obj: inventorydagi obyekt (masalan Product/PurchaseTransaction)
    cost: Decimal (tannarx)
    is_cash: True -> kassa; False -> ta'minotchiga qarz (AP)
    """
    ensure_default_accounts()
    lines = [
        (Account.CODE_INVENTORY, Decimal(cost)),
        (Account.CODE_CASH if is_cash else Account.CODE_AP_SUPPLIERS, Decimal(-cost)),
    ]
    return post_entry_object(lines, obj_or_ids=obj, memo=memo, ref=ref, date=date)

# --- Rashod (Expense) ---
def post_expense_from_domain(obj, *, amount, is_cash: bool, ref: str = "", memo: str = "Rashod", date=None):
    ensure_default_accounts()
    lines = [
        (Account.CODE_EXPENSES, Decimal(amount)),
        (Account.CODE_CASH if is_cash else Account.CODE_AP_SUPPLIERS, Decimal(-amount)),
    ]
    return post_entry_object(lines, obj_or_ids=obj, memo=memo, ref=ref, date=date)

# --- Sotuv (Sale) + COGS + Komissiya ---
def post_sale_from_domain(
    obj, *, sale_price, cogs: Decimal = Decimal("0.00"),
    is_cash: bool = True,
    commission: Decimal = Decimal("0.00"),
    commission_as_expense: bool = True,
    ref: str = "", memo: str = "Sotuv", date=None
):
    ensure_default_accounts()
    lines = []

    # Daromad
    if is_cash:
        lines += [
            (Account.CODE_CASH,  Decimal(sale_price)),
            (Account.CODE_SALES, Decimal(-sale_price)),
        ]
    else:
        lines += [
            (Account.CODE_AR_CUSTOMERS, Decimal(sale_price)),
            (Account.CODE_SALES,        Decimal(-sale_price)),
        ]

    # COGS
    if cogs and Decimal(cogs) > 0:
        lines += [
            (Account.CODE_COGS,      Decimal(cogs)),
            (Account.CODE_INVENTORY, Decimal(-cogs)),
        ]

    # Komissiya (xarajat yoki daromad)
    if commission and Decimal(commission) > 0:
        if commission_as_expense:
            lines += [
                (Account.CODE_COMMISSION_EX, Decimal(commission)),
                (Account.CODE_CASH if is_cash else Account.CODE_AR_CUSTOMERS, Decimal(-commission)),
            ]
        else:
            lines += [
                (Account.CODE_CASH if is_cash else Account.CODE_AR_CUSTOMERS, Decimal(commission)),
                (Account.CODE_COMMISSION_IN, Decimal(-commission)),
            ]

    return post_entry_object(lines, obj_or_ids=obj, memo=memo, ref=ref, date=date)

# --- Qarzdordan tushum (AR -> Cash) ---
def post_receipt_from_debtor_domain(obj, *, amount, ref: str = "", memo: str = "Qarzdan tushum", date=None):
    ensure_default_accounts()
    lines = [
        (Account.CODE_CASH,        Decimal(amount)),
        (Account.CODE_AR_CUSTOMERS, Decimal(-amount)),
    ]
    return post_entry_object(lines, obj_or_ids=obj, memo=memo, ref=ref, date=date)

# --- Ta'minotchiga to'lov (AP -> Cash) ---
def post_payment_to_supplier_domain(obj, *, amount, ref: str = "", memo: str = "Ta'minotchiga to'lov", date=None):
    ensure_default_accounts()
    lines = [
        (Account.CODE_AP_SUPPLIERS, Decimal(amount)),
        (Account.CODE_CASH,         Decimal(-amount)),
    ]
    return post_entry_object(lines, obj_or_ids=obj, memo=memo, ref=ref, date=date)

# finance/adapters.py
from decimal import Decimal
from .models import Account
from .services import post_entry_object, ensure_default_accounts

# --- PURCHASE (inventoryga kirim) – Product bilan aniq ---
def post_purchase_from_product(product, *, cost, is_cash: bool, memo="Olingan tovar", ref=""):
    """
    product: inventory.models.Product (✅ sizda bor)
    cost: Decimal (tannarx), is_cash: True->Cash, False->AP
    """
    ensure_default_accounts()
    lines = [
        (Account.CODE_INVENTORY, Decimal(cost)),
        (Account.CODE_CASH if is_cash else Account.CODE_AP_SUPPLIERS, Decimal(-cost)),
    ]
    return post_entry_object(lines, obj=product, memo=memo, ref=ref)

# --- EXPENSE (rashod) – Transaction orqali ---
def post_expense_from_transaction(tx, *, amount, is_cash: bool, memo="Rashod (TX)", ref=""):
    ensure_default_accounts()
    lines = [
        (Account.CODE_EXPENSES, Decimal(amount)),
        (Account.CODE_CASH if is_cash else Account.CODE_AP_SUPPLIERS, Decimal(-amount)),
    ]
    return post_entry_object(lines, obj=tx, memo=memo, ref=ref)

# --- SALE (sotuv) – Transaction orqali ---
def post_sale_from_transaction(tx, *, sale_price, cogs=Decimal("0.00"),
                               is_cash=True, commission=Decimal("0.00"),
                               commission_as_expense=True, memo="Sotuv (TX)", ref=""):
    ensure_default_accounts()
    lines = []
    # daromad
    if is_cash:
        lines += [
            (Account.CODE_CASH,  Decimal(sale_price)),
            (Account.CODE_SALES, Decimal(-sale_price)),
        ]
    else:
        lines += [
            (Account.CODE_AR_CUSTOMERS, Decimal(sale_price)),
            (Account.CODE_SALES,        Decimal(-sale_price)),
        ]
    # cogs/inventory
    if cogs and Decimal(cogs) > 0:
        lines += [
            (Account.CODE_COGS,      Decimal(cogs)),
            (Account.CODE_INVENTORY, Decimal(-cogs)),
        ]
    # komissiya
    if commission and Decimal(commission) > 0:
        if commission_as_expense:
            lines += [
                (Account.CODE_COMMISSION_EX, Decimal(commission)),
                (Account.CODE_CASH if is_cash else Account.CODE_AR_CUSTOMERS, Decimal(-commission)),
            ]
        else:
            lines += [
                (Account.CODE_CASH if is_cash else Account.CODE_AR_CUSTOMERS, Decimal(commission)),
                (Account.CODE_COMMISSION_IN, Decimal(-commission)),
            ]
    return post_entry_object(lines, obj=tx, memo=memo, ref=ref)

# --- Debtor to'lovi (AR -> Cash) – Transaction orqali ---
def post_receipt_from_debtor_transaction(tx, *, amount, memo="Qarzdordan tushum (TX)", ref=""):
    ensure_default_accounts()
    lines = [
        (Account.CODE_CASH,        Decimal(amount)),
        (Account.CODE_AR_CUSTOMERS, Decimal(-amount)),
    ]
    return post_entry_object(lines, obj=tx, memo=memo, ref=ref)

# --- Supplier to'lovi (AP -> Cash) – Transaction orqali ---
def post_payment_to_supplier_transaction(tx, *, amount, memo="Ta'minotchiga to'lov (TX)", ref=""):
    ensure_default_accounts()
    lines = [
        (Account.CODE_AP_SUPPLIERS, Decimal(amount)),
        (Account.CODE_CASH,         Decimal(-amount)),
    ]
    return post_entry_object(lines, obj=tx, memo=memo, ref=ref)

