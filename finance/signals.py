# finance/signals.py
from django.db.models.signals import post_migrate
from django.dispatch import receiver
from finance.services import ensure_default_accounts

@receiver(post_migrate)
def finance_post_migrate(sender, **kwargs):
    try:
        ensure_default_accounts()
    except Exception:
        # migratsiya vaqtida DB tayyor bo'lmaganda jim o'tamiz
        pass
