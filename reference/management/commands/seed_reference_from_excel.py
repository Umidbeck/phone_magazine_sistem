from django.core.management.base import BaseCommand
from django.db import transaction
import pandas as pd
from reference.models import Brand, ModelName, Color

class Command(BaseCommand):
    help = "Seed Brand/Model/Color from Excel (columns: BREND, MADEL, RANGI)"

    def add_arguments(self, parser):
        parser.add_argument("path", type=str)

    @transaction.atomic
    @transaction.atomic
    def handle(self, *args, **opts):
        def safe_str(val):
            return '' if pd.isna(val) else str(val).strip()

        df = pd.read_excel(opts["path"], dtype=str)
        df.columns = [str(c).strip().upper() for c in df.columns]
        brand_col = "BREND" if "BREND" in df.columns else None
        model_col = "MADEL" if "MADEL" in df.columns else None
        color_col = "RANGI" if "RANGI" in df.columns else None

        brands, models, colors = {}, set(), set()

        for _, row in df.iterrows():
            b = safe_str(row.get(brand_col)).title()
            m = safe_str(row.get(model_col)).title()
            c = safe_str(row.get(color_col)).title()

            if b:
                brands[b] = True
                if m:
                    models.add((b, m))
            if c:
                colors.add(c)

        for b in brands.keys():
            Brand.objects.get_or_create(name=b, defaults={"is_active": True})

        for b, m in models:
            brand = Brand.objects.get(name=b)
            ModelName.objects.get_or_create(brand=brand, name=m, defaults={"is_active": True})

        for c in colors:
            Color.objects.get_or_create(name=c, defaults={"is_active": True})

        self.stdout.write(self.style.SUCCESS("Seed completed."))
