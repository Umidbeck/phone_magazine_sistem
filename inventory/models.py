# inventory/models.py
from decimal import Decimal

from django.db import models
from django.conf import settings
from django.db.models import Index, Sum
from django.db.models.functions import Right  # <<— MUHIM
from accounts.models import Store
from reference.models import Brand, ModelName, Color
from django import VERSION as DJANGO_VER

class BatchIntake(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    title = models.CharField(max_length=120, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title or f"Intake #{self.id} — {self.store.name}"

class Product(models.Model):
    OWNERSHIP = (("owned","Owned"),("consignment","Consignment"))
    STATUS = (("available","Available"),("on_repair","On Repair"),("sold","Sold"))

    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    batch = models.ForeignKey('BatchIntake', null=True, blank=True, on_delete=models.SET_NULL)

    brand = models.ForeignKey(Brand, on_delete=models.PROTECT)
    model = models.ForeignKey(ModelName, on_delete=models.PROTECT)
    color = models.ForeignKey(Color, on_delete=models.SET_NULL, null=True, blank=True)

    year = models.PositiveSmallIntegerField(null=True, blank=True)
    imei_full = models.CharField(max_length=32, unique=True)  # faqat raqam saqlaymiz
    imei_last4 = models.CharField(max_length=4, db_index=True, default='0000')

    has_documents = models.BooleanField(default=False)
    is_new = models.BooleanField(default=False)
    defect = models.CharField(max_length=120, blank=True)
    battery_pct = models.PositiveSmallIntegerField(null=True, blank=True)

    ownership = models.CharField(max_length=12, choices=OWNERSHIP)
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    consignment_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    owner_name = models.CharField(max_length=80, blank=True)
    owner_phone = models.CharField(max_length=20, blank=True)

    status = models.CharField(max_length=20,
                              choices=(("available", "available"), ("on_repair", "on_repair"), ("sold", "sold")),
                              default="available")
    # YANGI:
    sold_at = models.DateTimeField(null=True, blank=True)  # sotilganda to‘ldiriladi

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='products_created'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_archived = models.BooleanField(default=False)

    def calc_cost(self) -> Decimal:
        """
        Sotuv uchun cost:
          base = purchase_price (owned) yoki consignment_price (consignment)
          + shu productga biriktirilgan tasdiqlangan barcha expense (Transaction.type='expense', is_approved=True)
        """
        from sales.models import Transaction  # circular importdan qochish
        base = Decimal(self.purchase_price or 0) if self.ownership == "owned" else Decimal(self.consignment_price or 0)
        exp = Transaction.objects.filter(
            type="expense", product_id=self.id, is_approved=True
        ).aggregate(s=Sum("amount"))["s"] or Decimal("0")
        return (base + exp).quantize(Decimal("0.01"))

    # inventory/models.py (Product ichida)
    def save(self, *args, **kwargs):
        if getattr(self, "imei_full", None):
            self.imei_full = "".join(ch for ch in self.imei_full if ch.isdigit())
            if hasattr(self, "imei_last4") and len(self.imei_full) >= 4:
                self.imei_last4 = self.imei_full[-4:]
        super().save(*args, **kwargs)

    class Meta:
        indexes = [
            # brand/model/status tez koʻrinishi uchun
            models.Index(fields=["brand", "model", "status", "created_at"]),
        ]

        # PostgreSQL + Django 3.2+ boʻlsa funksional indeks ham qoʻshamiz
        if (
                DJANGO_VER >= (3, 2) and
                "postgresql" in settings.DATABASES["default"]["ENGINE"]
        ):
            indexes.append(
                models.Index(
                    name="idx_product_imei_last4",
                    expressions=[Right("imei_full", 4)]
                )
            )

    def __str__(self): return f"{self.brand} {self.model} {self.imei_full[-4:]}"

class ProductImage(models.Model):
    TYPE = (("doc","Document"),("cond","Condition"),("other","Other"))
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="stores/%Y/%m/%d")
    kind = models.CharField(max_length=8, choices=TYPE, default="other")
    is_primary = models.BooleanField(default=False)
    checksum = models.CharField(max_length=64, db_index=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
