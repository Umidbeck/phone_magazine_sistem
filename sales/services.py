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
    base = Decimal("0")
    if product.ownership == "owned":
        base = Decimal(product.purchase_price or 0)
    else:
        base = Decimal(product.consignment_price or 0)

    exp_sum = Transaction.objects.filter(
        type="expense",
        product=product,
        is_approved=True,        # <<< faqat tasdiqlangan rashodlar
    ).aggregate(s=Sum("amount"))["s"] or Decimal("0")

    return base + exp_sum
