# finance/diagnostics.py
from decimal import Decimal
from django.db.models import Sum
from django.core.exceptions import FieldDoesNotExist
from finance.models import Account, JournalLine
from sales.models import Transaction

def check_accounts_exist():
    missing = []
    for code in (
        Account.CODE_CASH, Account.CODE_INVENTORY,
        Account.CODE_AR_CUSTOMERS, Account.CODE_AP_SUPPLIERS,
        Account.CODE_OWNER_EQUITY, Account.CODE_SALES, Account.CODE_COGS,
        Account.CODE_EXPENSES, Account.CODE_COMMISSION_EX, Account.CODE_COMMISSION_IN,
    ):
        if not Account.objects.filter(code=code).exists():
            missing.append(code)
    return missing

def check_journal_balanced():
    """
    Jurnal bo‘yicha umumiy yig‘indi 0 bo‘lishi kerak (Debet-kredit).
    """
    total = JournalLine.objects.aggregate(s=Sum("amount"))["s"] or Decimal("0")
    return total

def check_transaction_fields():
    """
    Transaction modelida qaysi sana maydonlari borligini bildiradi.
    """
    fields = Transaction._meta.get_fields()
    names = [f.name for f in fields]
    present = [f for f in ("created_at","approved_at","paid_at") if f in names]
    return present
