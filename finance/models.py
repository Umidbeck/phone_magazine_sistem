# finance/models.py - TUZATILGAN VERSIYA
"""
Finance Models - Moliyaviy modellar

VERSIYA: 5.0 - KASSA O'TKAZMA QOBILIYATI
==========================================

MODELLAR:
✅ Account - Hisob rejasi
✅ JournalEntry - Jurnal yozuv
✅ JournalLine - Jurnal qatori
✅ CapitalTransaction - Kapital harakati (YANGI: transfer qo'shildi!)
✅ Investment - Investitsiya
"""

from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone as dj_tz

from accounts.models import Store


class Account(models.Model):
    """
    Hisob rejasi (Chart of Accounts)
    """
    # Account codes
    CODE_CASH = "1000"
    CODE_CARD = "1010"
    CODE_INVENTORY = "1100"
    CODE_AR_CUSTOMERS = "1200"
    CODE_AP_SUPPLIERS = "2000"
    CODE_OWNER_EQUITY = "3000"
    CODE_SALES = "4000"
    CODE_COMMISSION_IN = "4100"
    CODE_COGS = "5000"
    CODE_EXPENSES = "5100"
    CODE_COMMISSION_EX = "5200"

    CATEGORY_CHOICES = (
        ("asset", "Aktiv"),
        ("liability", "Majburiyat"),
        ("equity", "Kapital"),
        ("revenue", "Daromad"),
        ("expense", "Xarajat"),
    )

    code = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    description = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]
        indexes = [
            models.Index(fields=["category", "code"]),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


class JournalEntry(models.Model):
    """
    Jurnal yozuv (Double-entry accounting)
    """
    date = models.DateField(default=dj_tz.now)
    memo = models.CharField(max_length=200, blank=True)
    ref = models.CharField(max_length=50, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["date", "-created_at"]),
            models.Index(fields=["ref"]),
        ]

    def __str__(self):
        return f"JE#{self.pk} - {self.date} - {self.memo[:50]}"


class JournalLine(models.Model):
    """
    Jurnal qatori
    """
    entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name="lines"
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Debit = musbat, Credit = manfiy"
    )

    # Object linking (generic foreign key alternative)
    object_app = models.CharField(max_length=50, blank=True, db_index=True)
    object_model = models.CharField(max_length=50, blank=True, db_index=True)
    object_id = models.CharField(max_length=50, blank=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["entry", "account"]),
            models.Index(fields=["object_app", "object_model", "object_id"]),
        ]

    def __str__(self):
        sign = "DR" if self.amount > 0 else "CR"
        return f"{sign} {self.account.code}: ${abs(self.amount):.2f}"


class CapitalTransaction(models.Model):
    """
    Kapital harakati

    TYPES:
    - injection: Owner investitsiya kiritadi
    - withdrawal: Owner pul oladi
    - transfer: Naqd ↔ Karta o'tkazma

    CHANNELS:
    - cash: Naqd
    - card: Karta
    - both: Aralash (transfer uchun)

    WITHDRAWAL SOURCES:
    - profit: Foydadan yechish
    - capital: Kapitaldan yechish
    """

    TYPE_INJECTION = "injection"
    TYPE_WITHDRAWAL = "withdrawal"
    TYPE_TRANSFER = "transfer"

    TYPE_CHOICES = (
        (TYPE_INJECTION, "Investitsiya"),
        (TYPE_WITHDRAWAL, "Yechish"),
        (TYPE_TRANSFER, "O'tkazma"),
    )

    CHANNEL_CASH = "cash"
    CHANNEL_CARD = "card"
    CHANNEL_BOTH = "both"

    CHANNEL_CHOICES = (
        (CHANNEL_CASH, "Naqd"),
        (CHANNEL_CARD, "Karta"),
        (CHANNEL_BOTH, "Ikkala"),
    )

    DIRECTION_CASH_TO_CARD = "cash_to_card"
    DIRECTION_CARD_TO_CASH = "card_to_cash"

    DIRECTION_CHOICES = (
        (DIRECTION_CASH_TO_CARD, "Naqd → Karta"),
        (DIRECTION_CARD_TO_CASH, "Karta → Naqd"),
    )

    # ✅ WITHDRAWAL SOURCE - Qayerdan yechiladi
    SOURCE_PROFIT = "profit"
    SOURCE_CAPITAL = "capital"

    SOURCE_CHOICES = (
        (SOURCE_PROFIT, "Foydadan"),
        (SOURCE_CAPITAL, "Kapitaldan"),
    )

    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)

    # Transfer uchun
    direction = models.CharField(
        max_length=20,
        choices=DIRECTION_CHOICES,
        blank=True,
        help_text="Faqat transfer uchun"
    )

    # ✅ Withdrawal uchun - Qayerdan yechiladi
    withdrawal_source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        blank=True,
        help_text="Faqat withdrawal uchun - foydadan yoki kapitaldan"
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.CharField(max_length=200, blank=True)

    # Approval
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="approved_capital_txns",
        on_delete=models.SET_NULL
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="created_capital_txns",
        on_delete=models.PROTECT
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["type", "is_approved", "created_at"]),
            models.Index(fields=["store", "created_at"]),
        ]

    def __str__(self):
        return f"{self.get_type_display()} - ${self.amount} ({self.get_channel_display()})"


class Investment(models.Model):
    """
    Investitsiya (owner capital injection)
    """
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField(default=dj_tz.now)
    note = models.TextField(blank=True)

    journal_entry = models.OneToOneField(
        JournalEntry,
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"Investment ${self.amount} - {self.date}"