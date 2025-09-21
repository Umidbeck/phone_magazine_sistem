from django.core.management.base import BaseCommand
from django.core import management
from django.utils import timezone
from pathlib import Path

class Command(BaseCommand):
    help = "Dump JSON of all apps into backups/<ts>.json"

    def handle(self, *args, **opts):
        ts = timezone.now().strftime("%Y%m%d_%H%M%S")
        outdir = Path("backups"); outdir.mkdir(exist_ok=True)
        out = outdir / f"backup_{ts}.json"
        with out.open("w", encoding="utf-8") as f:
            management.call_command("dumpdata", indent=2, stdout=f)
        self.stdout.write(self.style.SUCCESS(f"Saved: {out}"))
