from decimal import Decimal
from django.db.models import Sum
from inventory.models import Product
from .models import Transaction, SellerCommission
from reference.models import Config

def sum_product_expenses(product_id: int) -> Decimal:
    total = (
        Transaction.objects.filter(type="expense", product_id=product_id)
        .aggregate(s=Sum("amount"))["s"]
        or Decimal("0")
    )
    return total

def get_commission_amount(sale_amount: Decimal) -> Decimal:
    # Config: commission_mode (fixed|percent), commission_value (5|1.5 ...)
    mode = Config.objects.filter(key="commission_mode").values_list("value", flat=True).first() or "fixed"
    val_s = Config.objects.filter(key="commission_value").values_list("value", flat=True).first() or "5"
    val = Decimal(val_s)
    if mode == "percent":
        return (sale_amount * val / Decimal("100")).quantize(Decimal("0.01"))
    return val.quantize(Decimal("0.01"))
