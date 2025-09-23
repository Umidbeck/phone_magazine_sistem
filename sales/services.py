from decimal import Decimal
from django.conf import settings
from django.db.models import Sum
from inventory.models import Product
from sales.models import Transaction

def get_commission_amount(amount=None) -> Decimal:
    """
    Har bir sotuv uchun qat'iy komissiya. Default: 5.00 USD (yoki so'm).
    settings.COMMISSION_FLAT o'rnatilsa, shuni oladi.
    """
    val = getattr(settings, "COMMISSION_FLAT", Decimal("5"))
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal("5")

def calc_product_cost(product: Product) -> Decimal:
    """
    Sotuv uchun 'cost' qiymati:
      owned:       purchase_price + (shu telefonga bog'langan barcha expenses)
      consignment: consignment_price + (shu telefonga bog'langan barcha expenses)
    """
    base = Decimal("0")
    if product.ownership == "owned":
        base = Decimal(product.purchase_price or 0)
    else:
        base = Decimal(product.consignment_price or 0)

    # Ushbu telefonga bog'langan barcha xarajatlar (Transaction.type='expense')
    exp_sum = Transaction.objects.filter(
        type="expense",
        product=product,
    ).aggregate(s=Sum("amount"))["s"] or Decimal("0")

    return base + exp_sum
