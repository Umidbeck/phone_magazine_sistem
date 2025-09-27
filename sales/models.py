# sales/models.py
from uuid import uuid4

from django.db import models
from django.conf import settings
from decimal import Decimal

from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import Store
from inventory.models import Product
from reference.models import ExpenseType, Config


class Transaction(models.Model):
    TYPES = (
        ("sale","sale"),
        ("expense","expense"),
        ("debt_out","debt_out"),   # qarz chiqim (telefon bo‘lib to‘lashda qoldiq)
        ("debt_pay","debt_pay"),   # qarzdorning to‘lovi
        ("consignment_payout","consignment_payout"),
    )

    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.SET_NULL)
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    type = models.CharField(max_length=24, choices=TYPES)

    # Umumiy summa (sale / expense / etc.)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # To‘lov turlari (sale va debt_pay uchun ishlatamiz)
    payment_type = models.CharField(max_length=10, blank=True)  # 'cash'|'card'|'mixed'|'' (expense/pay uchun shart emas)
    cash_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    card_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Sotuvlar uchun:
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    profit = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Qarzdorlik bilan bog‘liq
    debtor_name = models.CharField(max_length=120, blank=True)
    debtor_phone = models.CharField(max_length=50, blank=True)
    note = models.CharField(max_length=200, blank=True)
    debtor_group = models.UUIDField(default=uuid4, editable=False, db_index=True)
    related_sale = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="debt_txns")

    # Xarajatlar uchun:
    expense_type = models.ForeignKey(ExpenseType, null=True, blank=True, on_delete=models.SET_NULL)

    # Tasdiqlash oqimi
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="transactions_created",
                                   on_delete=models.PROTECT, null=True, blank=True)
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    related_name="transactions_approved", on_delete=models.SET_NULL)
    approved_at = models.DateTimeField(null=True, blank=True)

    # Qo‘shimcha holatlar
    is_paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)

    # Sotuv bekor qilinganmi (return/void) -> statistikadan chiqaramiz, komissiya berilmaydi
    is_void = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["store","type","created_at"]),
            models.Index(fields=["debtor_group"]),
        ]

    def __str__(self):
        return f"{self.type} {self.amount} ({self.created_at:%Y-%m-%d})"


class SellerCommission(models.Model):
    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE, related_name="commission")
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    is_paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)

    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    related_name="commissions_approved", on_delete=models.SET_NULL)
    approved_at = models.DateTimeField(null=True, blank=True)

    @staticmethod
    def commission_amount() -> Decimal:
        from reference.models import Config
        mode = Config.objects.filter(key="commission_mode").values_list("value", flat=True).first() or "fixed"
        val = Config.objects.filter(key="commission_value").values_list("value", flat=True).first() or "5"
        return Decimal(val)

class ConsignmentDue(models.Model):
    """
    Komissiyaga (consignment) olingan telefon SOTILGAN paytda avtomatik ochiladigan “due” kartasi.
    Shu karta bo‘yicha Transaction(type='consignment_payout') yig‘iladi.
    """
    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name="cons_due")
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    base_amount = models.DecimalField(max_digits=12, decimal_places=2)  # product.consignment_price

    # Tasdiqlash oqimi (kartani ochish/aktivlashtirish uchun)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cons_due_created")
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="cons_due_approved",
        on_delete=models.SET_NULL
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"ConsDue {self.product_id} base={self.base_amount}"




@receiver(post_save, sender=Transaction)
def _ensure_commission_on_sale(sender, instance: Transaction, created, **kwargs):
    if not created or instance.type != "sale" or instance.is_void:
        return
    if hasattr(instance, "commission"):
        return
    from decimal import Decimal
    raw = SellerCommission.commission_amount()
    amt = raw if isinstance(raw, Decimal) else Decimal(str(raw or "5"))
    if amt <= 0: amt = Decimal("5.00")
    SellerCommission.objects.create(transaction=instance, seller=instance.seller, amount=amt)
