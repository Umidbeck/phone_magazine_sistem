from django.db import models
from django.utils import timezone

class Account(models.Model):
    """
    Hisoblar reestri (Chart of Accounts).
    """
    # Kategoriyalar: Asset, Liability, Equity, Revenue, Expense
    CAT_ASSET = "asset"
    CAT_LIAB  = "liability"
    CAT_EQU   = "equity"
    CAT_REV   = "revenue"
    CAT_EXP   = "expense"
    CATEGORY_CHOICES = [
        (CAT_ASSET, "Asset"),
        (CAT_LIAB, "Liability"),
        (CAT_EQU,  "Equity"),
        (CAT_REV,  "Revenue"),
        (CAT_EXP,  "Expense"),
    ]

    # Standart hisoblar uchun kodlar
    CODE_CASH          = "1000"
    CODE_INVENTORY     = "1100"
    CODE_AR_CUSTOMERS  = "1200"
    CODE_AP_SUPPLIERS  = "2000"
    CODE_OWNER_EQUITY  = "3000"
    CODE_SALES         = "4000"
    CODE_COMMISSION_IN = "4100"  # agar komissiyani daromad sifatida tasniflasak
    CODE_COGS          = "5000"
    CODE_EXPENSES      = "5100"
    CODE_COMMISSION_EX = "5200"  # agar komissiyani xarajat sifatida tasniflasak

    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=128)
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES)

    def __str__(self):
        return f"{self.code} — {self.name}"


class JournalEntry(models.Model):
    """
    Bitta xo'jalik operatsiyasi (masalan: sotib olish, sotish, rashod, investitsiya).
    """
    created_at = models.DateTimeField(default=timezone.now)
    date = models.DateField(default=timezone.now)
    memo = models.CharField(max_length=255, blank=True)
    ref = models.CharField(max_length=64, blank=True)  # masalan document/tranzaksiya id

    def __str__(self):
        return f"JE#{self.pk} {self.date} {self.memo or ''}"


class JournalLine(models.Model):
    """
    Double-entry yozuvi: har JE uchun kamida 2 qator (debet / kredit).
    """
    entry = models.ForeignKey(JournalEntry, related_name="lines", on_delete=models.CASCADE)
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    # Debet (+) / Kredit (-) summani bitta maydonda "signed" saqlaymiz
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    # ixtiyoriy bog'lanishlar
    object_app = models.CharField(max_length=32, blank=True)
    object_model = models.CharField(max_length=32, blank=True)
    object_id = models.CharField(max_length=64, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["account", "entry"]),
            models.Index(fields=["object_app", "object_model", "object_id"]),
        ]


class Investment(models.Model):
    """
    Do'kon egasidan (yoki investor) kelgan kapital kiritmalarini qayd etamiz.
    """
    created_at = models.DateTimeField(default=timezone.now)
    date = models.DateField(default=timezone.now)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    note = models.CharField(max_length=255, blank=True)

    # JE bilan bog'laymiz (auditing uchun)
    journal_entry = models.OneToOneField(JournalEntry, null=True, blank=True, on_delete=models.SET_NULL)
