# inventory/signals.py
from django.db.models.signals import pre_save
from decimal import Decimal
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from finance.adapters import post_purchase_from_domain, post_purchase_from_product
from .models import Product  # yoki PurchaseTransaction — loyihangga moslashtir

def _digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

@receiver(pre_save, sender=Product)
def product_normalize_imei(sender, instance: Product, **kwargs):
    # Faqat raqamlar qolsin (bo‘sh joy, chiziqcha va h.k. olib tashlanadi)
    imei = _digits_only(getattr(instance, "imei_full", "")).strip()
    instance.imei_full = imei


FINANCE_AUTOPOST = getattr(settings, "FINANCE_AUTOPOST", True)

@receiver(post_save, sender=Product)
def inventory_purchase_autopost(sender, instance, created, **kwargs):
    if not FINANCE_AUTOPOST:
        return
    # Shart: faqat "yangi olingan" tovar uchun post qilish (mos shart qo'ying)
    # Quyidagi maydonlarni loyihangga moslashtir:
    try:
        if created and getattr(instance, "status", "") in ("in_stock", "purchased", "new"):
            cost = Decimal(getattr(instance, "cost_price", getattr(instance, "purchase_price", "0")))
            if cost > 0:
                # to'lov turi: agar supplier_credit True bo'lsa -> AP (qarz), aks holda naqd
                is_cash = not bool(getattr(instance, "supplier_credit", False))
                post_purchase_from_domain(
                    instance, cost=cost, is_cash=is_cash,
                    ref=f"inventory.Product:{instance.pk}",
                    memo="Olingan tovar"
                )
    except Exception as ex:
        # xatoni jim yutmasdan log qoldirish tavsiya qilinadi
        import logging; logging.getLogger(__name__).exception(ex)


FINANCE_AUTOPOST = getattr(settings, "FINANCE_AUTOPOST", True)

@receiver(post_save, sender=Product)
def product_purchase_autopost(sender, instance: Product, created, **kwargs):
    """
    Product yaratilganda yoki kirim holatiga o'tganda, inventoryga kirimni ledgerga post qiladi.
    cost_price/purchase_price maydonlaridan biri bo'lsa — ishlaydi.
    supplier_credit True bo'lsa -> AP, aks holda Cash.
    """
    if not FINANCE_AUTOPOST:
        return
    try:
        # 'status' loyihangizda mavjud va kirim holatlarini bildirsa:
        status = getattr(instance, "status", "")
        if created or status in ("in_stock", "purchased", "new"):
            cost = Decimal(getattr(instance, "cost_price", getattr(instance, "purchase_price", "0")) or 0)
            if cost > 0:
                is_cash = not bool(getattr(instance, "supplier_credit", False))
                post_purchase_from_product(
                    instance, cost=cost, is_cash=is_cash,
                    ref=f"inventory.Product:{instance.pk}", memo="Olingan tovar"
                )
    except Exception:
        import logging; logging.getLogger(__name__).exception("product_purchase_autopost error")
