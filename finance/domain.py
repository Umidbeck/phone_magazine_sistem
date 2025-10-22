# finance/domain.py
from decimal import Decimal
from .services import post_entry_object, ensure_default_accounts
from .models import Account

# --- PURCHASE --------------------------------------------------------------
def post_purchase_from_domain(obj, *, cost, is_cash: bool, ref: str = "", memo: str = "Olingan tovar", date=None):
    ensure_default_accounts()
    lines = [
        (Account.CODE_INVENTORY, Decimal(cost)),
        (Account.CODE_CASH if is_cash else Account.CODE_AP_SUPPLIERS, Decimal(-cost)),
    ]
    return post_entry_object(lines, obj_or_ids=obj, memo=memo, ref=ref, date=date)

# --- EXPENSE ---------------------------------------------------------------
def post_expense_from_domain(obj, *, amount, is_cash: bool, ref: str = "", memo: str = "Rashod", date=None):
    ensure_default_accounts()
    lines = [
        (Account.CODE_EXPENSES, Decimal(amount)),
        (Account.CODE_CASH if is_cash else Account.CODE_AP_SUPPLIERS, Decimal(-amount)),
    ]
    return post_entry_object(lines, obj_or_ids=obj, memo=memo, ref=ref, date=date)

def post_expense_split_from_domain(obj, *, cash_amount=Decimal("0"), card_amount=Decimal("0"),
                                   ref: str = "", memo: str = "Rashod (split)", date=None):
    ensure_default_accounts()
    cash_amount = Decimal(cash_amount or 0)
    card_amount = Decimal(card_amount or 0)
    total = cash_amount + card_amount
    if total <= 0:
        return None
    lines = [(Account.CODE_EXPENSES, total)]
    if cash_amount > 0:
        lines.append((Account.CODE_CASH, Decimal(-cash_amount)))
    if card_amount > 0:
        lines.append((Account.CODE_CARD, Decimal(-card_amount)))
    return post_entry_object(lines, obj_or_ids=obj, memo=memo, ref=ref, date=date)

# --- SALE ------------------------------------------------------------------
def post_sale_from_domain(
    obj, *, sale_price, cogs: Decimal = Decimal("0.00"),
    is_cash: bool = True,
    commission: Decimal = Decimal("0.00"),
    commission_as_expense: bool = True,
    ref: str = "", memo: str = "Sotuv", date=None
):
    ensure_default_accounts()
    lines = []
    if is_cash:
        lines += [(Account.CODE_CASH, Decimal(sale_price)), (Account.CODE_SALES, Decimal(-sale_price))]
    else:
        lines += [(Account.CODE_AR_CUSTOMERS, Decimal(sale_price)), (Account.CODE_SALES, Decimal(-sale_price))]
    if cogs and Decimal(cogs) > 0:
        lines += [(Account.CODE_COGS, Decimal(cogs)), (Account.CODE_INVENTORY, Decimal(-cogs))]
    if commission and Decimal(commission) > 0:
        if commission_as_expense:
            lines += [(Account.CODE_COMMISSION_EX, Decimal(commission)),
                      (Account.CODE_CASH if is_cash else Account.CODE_AR_CUSTOMERS, Decimal(-commission))]
        else:
            lines += [(Account.CODE_CASH if is_cash else Account.CODE_AR_CUSTOMERS, Decimal(commission)),
                      (Account.CODE_COMMISSION_IN, Decimal(-commission))]
    return post_entry_object(lines, obj_or_ids=obj, memo=memo, ref=ref, date=date)

def post_sale_split_from_domain(obj, *, cash_amount=Decimal("0"), card_amount=Decimal("0"),
                                cogs: Decimal = Decimal("0.00"),
                                commission: Decimal = Decimal("0.00"),
                                commission_as_expense: bool = True,
                                ref: str = "", memo: str = "Sotuv (split)", date=None):
    ensure_default_accounts()
    cash_amount = Decimal(cash_amount or 0)
    card_amount = Decimal(card_amount or 0)
    total = cash_amount + card_amount
    if total <= 0:
        return None
    lines = []
    if cash_amount > 0: lines.append((Account.CODE_CASH, cash_amount))
    if card_amount > 0: lines.append((Account.CODE_CARD, card_amount))
    lines.append((Account.CODE_SALES, Decimal(-total)))
    if cogs and Decimal(cogs) > 0:
        lines += [(Account.CODE_COGS, Decimal(cogs)), (Account.CODE_INVENTORY, Decimal(-cogs))]
    if commission and Decimal(commission) > 0:
        take_from = Account.CODE_CASH if cash_amount > 0 else Account.CODE_CARD
        if commission_as_expense:
            lines += [(Account.CODE_COMMISSION_EX, Decimal(commission)), (take_from, Decimal(-commission))]
        else:
            lines += [(take_from, Decimal(commission)), (Account.CODE_COMMISSION_IN, Decimal(-commission))]
    return post_entry_object(lines, obj_or_ids=obj, memo=memo, ref=ref, date=date)

# --- AR/AP movement --------------------------------------------------------
def post_receipt_from_debtor_domain(obj, *, amount, ref: str = "", memo: str = "Qarzdan tushum", date=None):
    ensure_default_accounts()
    lines = [(Account.CODE_CASH, Decimal(amount)), (Account.CODE_AR_CUSTOMERS, Decimal(-amount))]
    return post_entry_object(lines, obj_or_ids=obj, memo=memo, ref=ref, date=date)

def post_payment_to_supplier_domain(obj, *, amount, ref: str = "", memo: str = "Ta'minotchiga to'lov", date=None):
    ensure_default_accounts()
    lines = [(Account.CODE_AP_SUPPLIERS, Decimal(amount)), (Account.CODE_CASH, Decimal(-amount))]
    return post_entry_object(lines, obj_or_ids=obj, memo=memo, ref=ref, date=date)
