from django.core.management.base import BaseCommand
from django.db import transaction
from inventory.models import Product

def digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

class Command(BaseCommand):
    help = "Backfill imei_last4 from imei_full for existing Products."

    def handle(self, *args, **opts):
        updated = 0
        with transaction.atomic():
            for p in Product.objects.all().only("id","imei_full","imei_last4"):
                full = digits_only(p.imei_full or "")
                set4 = full[-4:] if len(full) >= 4 else ""
                changed = False
                if full and p.imei_full != full:
                    p.imei_full = full
                    changed = True
                if set4 and p.imei_last4 != set4:
                    p.imei_last4 = set4
                    changed = True
                if changed:
                    p.save(update_fields=["imei_full","imei_last4"])
                    updated += 1
        self.stdout.write(self.style.SUCCESS(f"Backfilled {updated} products."))
