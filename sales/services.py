# services.py
from decimal import Decimal
from django.conf import settings
from django.db.models import Sum

from reference.models import Config
from inventory.models import Product
from sales.models import Transaction

def get_commission_amount(amount=None) -> Decimal:
    """
    Dinamik komissiya: 1) DB(Config.commission_flat), 2) settings.COMMISSION_FLAT, 3) default=5
    """
    try:
        row = Config.objects.filter(key="commission_flat").values_list("value", flat=True).first()
        if row is not None and str(row).strip() != "":
            return Decimal(str(row))
    except Exception:
        pass

    val = getattr(settings, "COMMISSION_FLAT", None)
    if val is not None:
        try:
            return Decimal(str(val))
        except Exception:
            pass

    return Decimal("5")

def calc_product_cost(product: Product) -> Decimal:
    """
    Mavjud hisoblash: o'zimizniki/komissiya bo'lsa mos ravishda baza narx + tasdiqlangan expense jamlanadi.
    """
    base = Decimal("0")
    ownership = getattr(product, "ownership", "owned")
    if ownership == "owned":
        base = Decimal(product.purchase_price or 0)
    else:
        base = Decimal(getattr(product, "consignment_price", 0) or 0)

    exp_sum = Transaction.objects.filter(
        type="expense",
        product=product,
        is_approved=True,
    ).aggregate(s=Sum("amount"))["s"] or Decimal("0")

    return base + exp_sum
