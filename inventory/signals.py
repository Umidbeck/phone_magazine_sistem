# inventory/signals.py
from django.db.models.signals import pre_save
from django.dispatch import receiver
from .models import Product

def _digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

@receiver(pre_save, sender=Product)
def product_normalize_imei(sender, instance: Product, **kwargs):
    # Faqat raqamlar qolsin (bo‘sh joy, chiziqcha va h.k. olib tashlanadi)
    imei = _digits_only(getattr(instance, "imei_full", "")).strip()
    instance.imei_full = imei
