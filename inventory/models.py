from decimal import Decimal
from django.db import models
from django.conf import settings
from django.db.models import Sum
from accounts.models import Store
from reference.models import Brand, ModelName, Color


class Product(models.Model):
    """Mahsulot modeli - Telefonlar"""

    OWNERSHIP = (
        ('owned', 'O\'zimizniki'),
        ('consignment', 'Konsignatsiya')
    )

    STATUS = (
        ('available', 'Mavjud'),
        ('on_repair', 'Ta\'mirda'),
        ('sold', 'Sotilgan')
    )

    # Asosiy maydonlar
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    batch = models.ForeignKey(
        'BatchIntake',
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    brand = models.ForeignKey(Brand, on_delete=models.PROTECT)
    model = models.ForeignKey(ModelName, on_delete=models.PROTECT)
    color = models.ForeignKey(Color, on_delete=models.SET_NULL, null=True, blank=True)

    year = models.PositiveSmallIntegerField(null=True, blank=True)
    imei_full = models.CharField(max_length=32, unique=True)
    imei_last4 = models.CharField(max_length=4, db_index=True, default='0000')

    # Hujjatlar
    has_documents = models.BooleanField(default=False)
    document_image = models.ImageField(upload_to='docs/', blank=True, null=True)

    # Holat
    is_new = models.BooleanField(default=False)
    defect = models.CharField(max_length=120, blank=True)
    battery_pct = models.PositiveSmallIntegerField(null=True, blank=True)

    # Narxlar (USD $)
    ownership = models.CharField(max_length=12, choices=OWNERSHIP)
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    consignment_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    ask_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    min_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sold_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # Egasi (konsignatsiya uchun)
    owner_name = models.CharField(max_length=80, blank=True)
    owner_phone = models.CharField(max_length=20, blank=True)

    # Status
    status = models.CharField(max_length=20, choices=STATUS, default='available')
    sold_at = models.DateTimeField(null=True, blank=True)

    # YANGI - Komissiya bloki
    commission_blocked = models.BooleanField(
        default=False,
        help_text="Qayta sotishda komissiya berilmaydi"
    )

    # Audit
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='products_created'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_archived = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=['brand', 'model', 'status', 'created_at']),
            models.Index(fields=['imei_last4']),
            models.Index(fields=['store', 'status']),
        ]

    def __str__(self):
        return f"{self.brand} {self.model} {self.imei_full[-4:]}"

    def calc_cost(self) -> Decimal:
        """Mahsulot tannarxini hisoblash"""
        from sales.models import Transaction

        # Base narx
        if self.ownership == 'owned':
            base = Decimal(self.purchase_price or 0)
        else:
            base = Decimal(self.consignment_price or 0)

        # Approved expenses
        exp = Transaction.objects.filter(
            type='expense',
            product_id=self.id,
            is_approved=True,
            is_void=False
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')

        return (base + exp).quantize(Decimal('0.01'))

    def save(self, *args, **kwargs):
        """IMEI normalizatsiya"""
        if self.imei_full:
            self.imei_full = ''.join(ch for ch in self.imei_full if ch.isdigit())
            if len(self.imei_full) >= 4:
                self.imei_last4 = self.imei_full[-4:]
        super().save(*args, **kwargs)


class ProductImage(models.Model):
    """Mahsulot rasmlari (0-7 ta)"""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='products/')
    order = models.PositiveIntegerField(default=0)

    TYPE = (
        ('doc', 'Hujjat'),
        ('cond', 'Holat'),
        ('other', 'Boshqa')
    )
    kind = models.CharField(max_length=8, choices=TYPE, default='other', blank=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"Rasm #{self.order} - {self.product_id}"


class BatchIntake(models.Model):
    """Partiya (bir vaqtda olingan telefonlar guruhi)"""
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    title = models.CharField(max_length=120, blank=True)
    note = models.TextField(blank=True)

    supplier_name = models.CharField(max_length=120, blank=True)
    supplier_phone = models.CharField(max_length=50, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title or f"Partiya #{self.id} - {self.store.name}"
