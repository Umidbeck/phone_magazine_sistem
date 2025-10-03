# sales/signals.py
from decimal import Decimal
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from finance.adapters import post_sale_from_domain, post_receipt_from_debtor_domain
from finance.services import post_from_transaction
from .models import Transaction  # loyihangdagi aniq model nomi
from finance.adapters import (
    post_sale_from_transaction,
    post_expense_from_transaction,
    post_receipt_from_debtor_transaction,
    post_payment_to_supplier_transaction,
)
FINANCE_AUTOPOST = getattr(settings, "FINANCE_AUTOPOST", True)

@receiver(post_save, sender=Transaction)
def transaction_autopost(sender, instance: Transaction, created, **kwargs):
    """
    Transaction.type mapping:
      - "sale"           -> sotuv
      - "expense"        -> rashod
      - "debt_payment"   -> mijoz qarzi to'lovi (AR->Cash)
      - "supplier_payment" yoki "ap_out" -> ta'minotchiga to'lov (AP->Cash)
      - "purchase"/"stock_in" — agar inventoryni Transaction orqali kiritmasangiz, Product signalini ishlatamiz (quyida).
    """
    if not FINANCE_AUTOPOST:
        return
    try:
        t = getattr(instance, "type", "")
        # Sotuv — faqat tasdiqlanganda va void bo'lmaganda
        if t == "sale" and getattr(instance, "is_approved", False) and not getattr(instance, "is_void", False):
            sale_price = Decimal(getattr(instance, "price", "0") or 0)
            cogs = Decimal(getattr(instance, "cost", "0") or 0)
            is_cash = not bool(getattr(instance, "is_credit_sale", False))
            commission = Decimal(getattr(instance, "commission_amount", "0") or 0)
            commission_as_expense = bool(getattr(instance, "commission_as_expense", True))
            post_sale_from_transaction(
                instance,
                sale_price=sale_price, cogs=cogs, is_cash=is_cash,
                commission=commission, commission_as_expense=commission_as_expense,
                ref=f"sales.Transaction:{instance.pk}", memo="Sotuv (TX)"
            )
        elif t == "expense" and getattr(instance, "is_approved", False):
            amount = Decimal(getattr(instance, "amount", getattr(instance, "price", "0")) or 0)
            is_cash = not bool(getattr(instance, "on_credit", False))
            post_expense_from_transaction(
                instance, amount=amount, is_cash=is_cash,
                ref=f"sales.Transaction:{instance.pk}", memo="Rashod (TX)"
            )
        elif t in ("debt_payment", "ar_in"):
            amount = Decimal(getattr(instance, "amount", "0") or 0)
            post_receipt_from_debtor_transaction(
                instance, amount=amount,
                ref=f"sales.Transaction:{instance.pk}", memo="Qarzdordan tushum (TX)"
            )
        elif t in ("supplier_payment", "ap_out"):
            amount = Decimal(getattr(instance, "amount", "0") or 0)
            post_payment_to_supplier_transaction(
                instance, amount=amount,
                ref=f"sales.Transaction:{instance.pk}", memo="Ta'minotchiga to'lov (TX)"
            )
        # purchase/stock_in ni Transaction orqali kiritmasangiz — inventory signal pastda hal qiladi.
    except Exception:
        import logging; logging.getLogger(__name__).exception("transaction_autopost error")


#
# @receiver(post_save, sender=Receipt)
# def debtor_receipt_autopost(sender, instance, created, **kwargs):
#     if not FINANCE_AUTOPOST:
#         return
#     try:
#         if created or getattr(instance, "status", "") in ("received", "posted"):
#             amount = Decimal(getattr(instance, "amount", "0"))
#             post_receipt_from_debtor_domain(
#                 instance, amount=amount,
#                 ref=f"sales.Receipt:{instance.pk}",
#                 memo="Qarzdordan tushum"
#             )
#     except Exception as ex:
#         import logging; logging.getLogger(__name__).exception(ex)

@receiver(post_save, sender=Transaction)
def tx_to_ledger(sender, instance, created, **kwargs):
    try:
        # created yoki status o‘zgarganda ham chaqirilishi mumkin
        post_from_transaction(instance)
    except Exception:
        import logging; logging.getLogger(__name__).exception("tx_to_ledger error")
