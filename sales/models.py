# sales/models.py - MUKAMMAL VERSIYA V7.0
"""
Sales Models - Savdo operatsiyalari modellari

VERSIYA: 7.0 - TASDIQLASH YO'Q, AVTOMATIK KOMISSIYA
====================================================

🎯 YANGI XUSUSIYATLAR:
═══════════════════════
1. Komissiya avtomatik beriladi va to'lanadi
2. Tasdiqlash tizimi yo'q
3. Ko'proq analytics va statistika
4. Seller performance tracking
5. Matematik aniq hisob-kitoblar

KOMISSIYA QOIDALARI:
═══════════════════
- Yangi telefon: 30% * Profit
- Eski telefon: $5 fix
- Blocked: $0
- O'sha kun qaytarish: Berilmaydi
- Boshqa kun qaytarish: Minus qilinadi

STATISTIKA:
═══════════
- Oylik sotuvlar
- Komissiya tarixchasi
- Qaytarish statistikasi
- Performance metrikalari
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

    🎯 YANGI: Avtomatik tasdiqlash
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

    # 🎯 YANGI: Approval workflow (avtomatik True)
    is_approved = models.BooleanField(
        default=True,  # 🎯 AVTOMATIK!
        help_text="Tasdiqlangan (avtomatik True)"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="approved_transactions",
        on_delete=models.SET_NULL
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # Payment status
    is_paid = models.BooleanField(
        default=True,  # 🎯 AVTOMATIK!
        help_text="To'langan (avtomatik True)"
    )
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

    🎯 YANGI VERSIYA: Avtomatik beriladi va to'lanadi!
    ══════════════════════════════════════════════════

    KOMISSIYA TURLARI:
    - profit30: 30% foyda (yangi telefonlar)
    - flat5: $5 fix (eski telefonlar)
    - none: Yo'q (bloklangan)

    STATUS:
    - is_approved: AVTOMATIK True
    - is_paid: AVTOMATIK True
    - is_deduction: Minus qilish (qaytarish)
    - is_rescinded: Bekor qilish (o'sha kun qaytarish)

    MATEMATIK FORMULA:
    ═════════════════
    Yangi: Commission = Profit * 0.30
    Eski: Commission = 5.00
    Block: Commission = 0.00
    Minus: Commission = -amount (qaytarish)
    """

    CAT_PROFIT30 = "profit30"
    CAT_FLAT5 = "flat5"
    CAT_NONE = "none"

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
        on_delete=models.PROTECT,
        related_name="seller_commissions"
    )

    # Amount (musbat yoki manfiy bo'lishi mumkin)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Komissiya summasi (+ yoki -)"
    )
    category = models.CharField(
        max_length=16,
        choices=CATEGORY_CHOICES,
        default=CAT_FLAT5
    )

    # 🎯 YANGI: Avtomatik approval va payment
    is_approved = models.BooleanField(
        default=True,  # 🎯 AVTOMATIK!
        help_text="Tasdiqlangan (avtomatik)"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="approved_commissions",
        on_delete=models.SET_NULL
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    is_paid = models.BooleanField(
        default=True,  # 🎯 AVTOMATIK!
        help_text="To'langan (avtomatik)"
    )
    paid_at = models.DateTimeField(null=True, blank=True)

    # Rescind (o'sha kun qaytarish - berilmaydi)
    is_rescinded = models.BooleanField(
        default=False,
        help_text="Bekor qilingan (o'sha kun qaytarish)"
    )
    rescinded_reason = models.CharField(max_length=120, blank=True)
    rescinded_at = models.DateTimeField(null=True, blank=True)

    # Deduction (boshqa kun qaytarish - minus qilinadi)
    is_deduction = models.BooleanField(
        default=False,
        help_text="Minus qilish (boshqa kun qaytarish)"
    )

    # Original commission link
    original_commission = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='deductions',
        help_text="Bog'liq komissiya"
    )

    # 🎯 YANGI: Analytics fieldlari
    profit_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Ushbu sotuvdan foyda"
    )
    sale_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Sotuv summasi"
    )
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Komissiya foizi (masalan: 30.00)"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["seller", "is_approved", "is_paid"]),
            models.Index(fields=["transaction", "is_deduction"]),
            models.Index(fields=["is_rescinded", "created_at"]),
            models.Index(fields=["seller", "created_at", "-amount"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        prefix = ""
        if self.is_deduction:
            prefix = "MINUS "
        elif self.is_rescinded:
            prefix = "BEKOR "
        return f"{prefix}${self.amount} [{self.get_category_display()}] - TX#{self.transaction_id}"

    @property
    def effective_amount(self):
        """
        Haqiqiy summa (hisob-kitoblar uchun)

        Qoidalar:
        - Rescinded → 0 (berilmagan)
        - Deduction → manfiy (ayirilgan)
        - Normal → musbat (berilgan)
        """
        if self.is_rescinded:
            return Decimal("0.00")
        return self.amount

    @property
    def status_display(self):
        """Status ko'rinishi"""
        if self.is_rescinded:
            return "❌ Bekor qilindi"
        elif self.is_deduction:
            return "➖ Ayirildi"
        elif self.amount < 0:
            return "➖ Minus"
        elif self.is_paid:
            return "✅ To'landi"
        else:
            return "⏳ Kutilmoqda"


class SellerStatistics(models.Model):
    """
    🎯 YANGI: Seller umumiy statistikasi
    ════════════════════════════════════

    Sotuvchi haqida to'liq ma'lumot:
    - Jami sotuvlar
    - Jami komissiya
    - O'rtacha komissiya
    - Qaytarish soni
    - Minus komissiya
    - Net komissiya (to'g'ri balance)
    """
    seller = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sales_stats"
    )

    # Sotuvlar
    total_sales_count = models.PositiveIntegerField(
        default=0,
        help_text="Jami sotuvlar soni"
    )
    total_sales_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Jami sotuv summasi"
    )

    # Komissiyalar
    total_commission_earned = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Jami ishlangan komissiya (+)"
    )
    total_commission_deducted = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Jami ayirilgan komissiya (-)"
    )
    net_commission = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Net komissiya (earned - deducted)"
    )

    # Qaytarishlar
    total_returns_count = models.PositiveIntegerField(
        default=0,
        help_text="Jami qaytarishlar soni"
    )
    same_day_returns = models.PositiveIntegerField(
        default=0,
        help_text="O'sha kun qaytarishlar"
    )
    late_returns = models.PositiveIntegerField(
        default=0,
        help_text="Kech qaytarishlar (minus komissiya)"
    )

    # O'rtachalar
    avg_sale_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="O'rtacha sotuv summasi"
    )
    avg_commission = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="O'rtacha komissiya"
    )

    # Performance
    success_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("100.00"),
        help_text="Muvaffaqiyat darajasi % (1 - qaytarish/sotuv)"
    )

    # Timestamps
    last_sale_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Oxirgi sotuv vaqti"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Seller Statistics"
        verbose_name_plural = "Seller Statistics"

    def __str__(self):
        return f"{self.seller.username} - ${self.net_commission:.2f} net"

    def update_statistics(self):
        """
        Statistikani yangilash (hisoblash)

        Bu method signal yoki cron orqali chaqiriladi
        """
        from django.db.models import Sum, Avg, Count, Q

        # Sotuvlar
        sales = self.seller.sold_transactions.filter(
            type="sale",
            is_void=False,
            is_approved=True
        )

        self.total_sales_count = sales.count()
        self.total_sales_amount = sales.aggregate(
            total=Sum('amount')
        )['total'] or Decimal("0.00")

        # Komissiyalar
        commissions = self.seller.seller_commissions.filter(
            is_rescinded=False
        )

        earned = commissions.filter(
            amount__gt=0
        ).aggregate(total=Sum('amount'))['total'] or Decimal("0.00")

        deducted = commissions.filter(
            amount__lt=0
        ).aggregate(total=Sum('amount'))['total'] or Decimal("0.00")

        self.total_commission_earned = earned
        self.total_commission_deducted = abs(deducted)
        self.net_commission = earned + deducted  # deducted allaqachon manfiy

        # Qaytarishlar
        returns = self.seller.sold_transactions.filter(
            type="sale",
            is_void=True
        )

        self.total_returns_count = returns.count()

        # Same-day vs late returns (commission orqali)
        self.same_day_returns = self.seller.seller_commissions.filter(
            is_rescinded=True,
            rescinded_reason="same_day_return"
        ).count()

        self.late_returns = self.seller.seller_commissions.filter(
            is_deduction=True,
            rescinded_reason="late_return"
        ).count()

        # O'rtachalar
        if self.total_sales_count > 0:
            self.avg_sale_amount = self.total_sales_amount / self.total_sales_count
            self.avg_commission = self.net_commission / self.total_sales_count

            # Success rate = (1 - returns/sales) * 100
            return_rate = self.total_returns_count / self.total_sales_count
            self.success_rate = (1 - return_rate) * 100
        else:
            self.avg_sale_amount = Decimal("0.00")
            self.avg_commission = Decimal("0.00")
            self.success_rate = Decimal("100.00")

        # Oxirgi sotuv
        last_sale = sales.order_by('-created_at').first()
        if last_sale:
            self.last_sale_at = last_sale.created_at

        self.save()


class ConsignmentDue(models.Model):
    """
    Konsignatsiya qarzi
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

    # Approval (konsignatsiya uchun kerak bo'lishi mumkin)
    is_approved = models.BooleanField(default=True)  # 🎯 Avtomatik
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="cons_due_approved",
        on_delete=models.SET_NULL
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # Void flag
    is_void = models.BooleanField(default=False)

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
        return f"Consignment #{self.product_id} - ${self.base_amount}"


class SellerMonthlyStat(models.Model):
    """
    Oylik sotuvchi statistikasi (leaderboard)
    """
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        default=1
    )
    month_key = models.CharField(
        max_length=7,
        db_index=True,
        help_text="Format: YYYY-MM"
    )
    sales_count = models.PositiveIntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("seller", "month_key", "store")]
        indexes = [
            models.Index(fields=["store", "month_key", "-sales_count"]),
        ]
        ordering = ["-month_key", "-sales_count"]

    def __str__(self):
        return f"{self.seller.username} - {self.store.name} - {self.month_key}: {self.sales_count} sales"


class MonthlyBonus(models.Model):
    """
    Oylik bonus
    """
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        default=1
    )
    month_key = models.CharField(
        max_length=7,
        db_index=True
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
        unique_together = [("store", "month_key")]
        indexes = [
            models.Index(fields=["store", "month_key"]),
        ]
        ordering = ["-awarded_at"]

    def __str__(self):
        return f"Bonus {self.store.name} - {self.month_key} - {self.winner.username}: ${self.amount}"


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