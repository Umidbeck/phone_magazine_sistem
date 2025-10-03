# finance/apps.py
from django.apps import AppConfig

class FinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "finance"
    verbose_name = "Finance (Ledger & Investment)"

    def ready(self):
        # Jadval tayyor bo'lsa — hisoblarni fon rejimida yaratib qo'yamiz
        try:
            from .services import ensure_default_accounts
            ensure_default_accounts()
        except Exception:
            # Migratsiya payti yoki dastlabki ko'tarilishda xatolar bo'lishi mumkin — jim o'tamiz
            pass
