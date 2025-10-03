# finance/management/commands/finance_bootstrap.py
from django.core.management.base import BaseCommand
from finance.services import ensure_default_accounts

class Command(BaseCommand):
    help = "Create default ledger accounts if missing."

    def handle(self, *args, **options):
        ensure_default_accounts()
        self.stdout.write(self.style.SUCCESS("Finance: default accounts ensured."))
