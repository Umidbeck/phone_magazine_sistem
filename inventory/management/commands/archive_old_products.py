from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from inventory.models import Product

class Command(BaseCommand):
    help = "Mark products older than 24 months as archived."

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(days=24*30)  # taxminan 24 oy
        qs = Product.objects.filter(created_at__lt=cutoff, is_archived=False)
        updated = qs.update(is_archived=True)
        self.stdout.write(self.style.SUCCESS(f"Archived {updated} products."))
