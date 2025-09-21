# sales/models.py
from django.db import models
from django.conf import settings
from decimal import Decimal
from accounts.models import Store
from inventory.models import Product
from reference.models import ExpenseType, Config

class Transaction(models.Model):
    TYPES = (
        ("sale","sale"), ("expense","expense"),
        ("debt_out","debt_out"), ("debt_pay","debt_pay"),
        ("consignment_payout","consignment_payout"),
    )
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.SET_NULL)
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    type = models.CharField(max_length=24, choices=TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_type = models.CharField(max_length=10, blank=True)  # cash/card/mixed
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    profit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    expense_type = models.ForeignKey(ExpenseType, null=True, blank=True, on_delete=models.SET_NULL)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["store","type","created_at"])]

class SellerCommission(models.Model):
    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE, related_name="commission")
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    @staticmethod
    def commission_amount() -> Decimal:
        mode = Config.objects.filter(key="commission_mode").values_list("value", flat=True).first() or "fixed"
        val = Config.objects.filter(key="commission_value").values_list("value", flat=True).first() or "5"
        if mode == "percent":
            # foiz hisoblashni sotuv paytida amountga nisbatan qo‘llaymiz
            return Decimal(val)  # bu foiz, real hisob view’da
        return Decimal(val)
