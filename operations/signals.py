# operations/signals.py
from decimal import Decimal
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from finance.adapters import post_expense_from_domain, post_payment_to_supplier_domain
from .models import AuditLog  # loyihangdagi model

FINANCE_AUTOPOST = getattr(settings, "FINANCE_AUTOPOST", True)

@receiver(post_save, sender=AuditLog)
def expense_autopost(sender, instance, created, **kwargs):
    if not FINANCE_AUTOPOST:
        return
    try:
        if created or getattr(instance, "status", "") in ("approved", "posted"):
            amount = Decimal(getattr(instance, "amount", "0"))
            is_cash = not bool(getattr(instance, "on_credit", False))
            post_expense_from_domain(
                instance, amount=amount, is_cash=is_cash,
                ref=f"operations.Expense:{instance.pk}",
                memo=getattr(instance, "category", "Rashod")
            )
    except Exception as ex:
        import logging; logging.getLogger(__name__).exception(ex)

@receiver(post_save, sender=AuditLog)
def supplier_payment_autopost(sender, instance, created, **kwargs):
    if not FINANCE_AUTOPOST:
        return
    try:
        if created or getattr(instance, "status", "") in ("paid", "posted"):
            amount = Decimal(getattr(instance, "amount", "0"))
            post_payment_to_supplier_domain(
                instance, amount=amount,
                ref=f"operations.SupplierPayment:{instance.pk}",
                memo="Ta'minotchiga to'lov"
            )
    except Exception as ex:
        import logging; logging.getLogger(__name__).exception(ex)