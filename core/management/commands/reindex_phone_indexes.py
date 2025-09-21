from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = "Rebuild important indexes (PostgreSQL)."

    def handle(self, *args, **opts):
        sqls = [
            'REINDEX INDEX CONCURRENTLY IF EXISTS idx_product_imei_last4;',
        ]
        with connection.cursor() as c:
            for s in sqls:
                try:
                    c.execute(s)
                    self.stdout.write(self.style.SUCCESS(f"OK: {s}"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"ERR: {s} -> {e}"))
