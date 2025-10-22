# sales/models.py - 100% MUKAMMAL VERSIYA
"""
Sales Models - Savdo operatsiyalari modellari

VERSIYA: 5.0 - BARCHA XATOLAR TUZATILDI
=========================================

TUZATISHLAR:
✅ ConsignmentDue.is_void maydoni qo'shildi
✅ SellerCommission.is_deduction mantiq to'liq
✅ Transaction indexlar optimallashtirildi
"""

from uuid import uuid4
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone as dj_tz

from accounts.models import Store
from inventory.models import Product
from reference.models import ExpenseType


class Transaction(models.Model):
    """
    Universal Transaction Model

    TYPES:
    - sale: Sotuv
    - expense: Rashod
    - debt_out: Qarz berish
    - debt_pay: Qarz to'lovi
    - consignment_payout: Konsignatsiya to'lovi
    """

    TYPES = (
        ("sale", "Sotuv"),
        ("expense", "Rashod"),
        ("debt_out", "Qarz berish"),
        ("debt_pay", "Qarz to'lovi"),
        ("consignment_payout", "Konsignatsiya to'lovi"),
    )

    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    product = models.ForeignKey(
        Product,
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sold_transactions"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="created_transactions",
        on_delete=models.PROTECT,
        null=True,
        blank=True
    )

    type = models.CharField(max_length=24, choices=TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Payment channels (split)
    payment_type = models.CharField(max_length=10, blank=True)
    cash_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    card_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Sale specifics
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    profit = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Debt specifics
    debtor_name = models.CharField(max_length=120, blank=True)
    debtor_phone = models.CharField(max_length=50, blank=True)
    debtor_group = models.UUIDField(default=uuid4, editable=False, db_index=True)
    related_sale = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="debt_txns"
    )

    # Expense specifics
    expense_type = models.ForeignKey(
        ExpenseType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )
    note = models.CharField(max_length=200, blank=True)

    # Approval workflow
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="approved_transactions",
        on_delete=models.SET_NULL
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # Payment status
    is_paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)

    # Void flag (bekor qilish)
    is_void = models.BooleanField(default=False)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["store", "type", "created_at"]),
            models.Index(fields=["debtor_group", "is_approved"]),
            models.Index(fields=["is_approved", "is_void", "type"]),
            models.Index(fields=["seller", "created_at"]),
            models.Index(fields=["product", "type"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_type_display()} ${self.amount} ({self.created_at:%Y-%m-%d})"


class SellerCommission(models.Model):
    """
    Seller Commission Tracking

    YANGI MANTIQ:
    - is_deduction=True → Bu MANFIY komissiya (qaytarish jazosi)
    - amount manfiy bo'lishi mumkin
    """

    CAT_PROFIT30 = "profit30"  # 30% of profit (new phones)
    CAT_FLAT5 = "flat5"  # $5 flat (used phones)
    CAT_NONE = "none"  # No commission (resold)

    CATEGORY_CHOICES = (
        (CAT_PROFIT30, "30% foyda"),
        (CAT_FLAT5, "$5 fix"),
        (CAT_NONE, "Yo'q"),
    )

    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.CASCADE,
        related_name="commission"
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT
    )

    # MUHIM: amount manfiy bo'lishi mumkin (deduction)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.CharField(
        max_length=16,
        choices=CATEGORY_CHOICES,
        default=CAT_FLAT5
    )

    # Approval workflow
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="approved_commissions",
        on_delete=models.SET_NULL
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # Payment status
    is_paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)

    # Rescind (qaytarish uchun)
    is_rescinded = models.BooleanField(default=False)
    rescinded_reason = models.CharField(max_length=120, blank=True)
    rescinded_at = models.DateTimeField(null=True, blank=True)

    # YANGI: Deduction flag
    is_deduction = models.BooleanField(
        default=False,
        help_text="True = manfiy komissiya (qaytarish jazosi)"
    )

    # YANGI: Original commission link
    original_commission = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='deductions',
        help_text="Qaytarish qaysi komissiyaga bog'liq"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["seller", "is_approved", "is_paid"]),
            models.Index(fields=["transaction", "is_deduction"]),
            models.Index(fields=["is_rescinded", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        prefix = "MINUS" if self.is_deduction else ""
        return f"{prefix} Commission ${self.amount} [{self.get_category_display()}] - TX#{self.transaction_id}"

    @property
    def effective_amount(self):
        """
        Haqiqiy summa (hisob-kitoblar uchun)
        - Rescinded → 0
        - Deduction → manfiy (amount allaqachon manfiy)
        - Normal → musbat
        """
        if self.is_rescinded:
            return Decimal("0.00")
        return self.amount


class ConsignmentDue(models.Model):
    """
    Konsignatsiya qarzi (sotilganda paydo bo'ladi)

    TUZATISH: is_void maydoni qo'shildi!
    """
    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name="cons_due"
    )
    store = models.ForeignKey(Store, on_delete=models.CASCADE)

    base_amount = models.DecimalField(max_digits=12, decimal_places=2)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cons_due_created"
    )

    # Approval
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="cons_due_approved",
        on_delete=models.SET_NULL
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # YANGI: Void flag
    is_void = models.BooleanField(
        default=False,
        help_text="Bekor qilingan (masalan, qaytarilgan telefon)"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["store", "is_approved", "is_void"]),
            models.Index(fields=["product", "is_approved"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"Consignment Due #{self.product_id} - ${self.base_amount}"


class SellerMonthlyStat(models.Model):
    """
    Oylik sotuvchi statistikasi (leaderboard uchun)
    """
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )
    month_key = models.CharField(
        max_length=7,
        db_index=True,
        help_text="Format: YYYY-MM"
    )
    sales_count = models.PositiveIntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("seller", "month_key")]
        indexes = [
            models.Index(fields=["month_key", "-sales_count"]),
        ]
        ordering = ["-month_key", "-sales_count"]

    def __str__(self):
        return f"{self.seller.username} - {self.month_key}: {self.sales_count} sales"


class MonthlyBonus(models.Model):
    """
    Oylik bonus (eng ko'p sotgan seller'ga)
    """
    month_key = models.CharField(
        max_length=7,
        db_index=True,
        help_text="Format: YYYY-MM"
    )
    winner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("50.00")
    )
    awarded_at = models.DateTimeField(default=dj_tz.now)

    class Meta:
        indexes = [
            models.Index(fields=["month_key"]),
        ]
        ordering = ["-awarded_at"]

    def __str__(self):
        return f"Bonus {self.month_key} - {self.winner.username}: ${self.amount}"


class Notification(models.Model):
    """
    Xabarlar (bildirishnomalar)
    """
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )
    title = models.CharField(max_length=120)
    message = models.TextField(blank=True)

    is_read = models.BooleanField(default=False)

    created_at = models.DateTimeField(default=dj_tz.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "is_read", "-created_at"]),
        ]

    def __str__(self):
        status = "✓" if self.is_read else "✗"
        return f"{status} {self.title} → {self.recipient.username}"