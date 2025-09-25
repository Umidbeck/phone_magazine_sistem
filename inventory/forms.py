from decimal import Decimal

from django import forms
from django.forms.widgets import ClearableFileInput

from accounts.models import Store
from .models import Product, ProductImage, BatchIntake
from reference.models import Brand, ModelName, Color

# --- YANGI: ko‘p faylga ruxsat beradigan widget ---
class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


def digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

class ProductCreateForm(forms.ModelForm):
    # multi-upload (create/edit ikkalasida ishlaydi)
    doc_images = forms.FileField(
        widget=MultipleFileInput(),
        required=False,
        label="Dokument rasmlari"
    )

    # 2) Holat rasmlari – bir nechta
    cond_images = forms.FileField(
        widget=MultipleFileInput(),
        required=False,
        label="Holat rasmlari"
    )

    # 3) Asosiy rasm – bir nechta (agar kerak boʻlsa)
    image = forms.FileField(
        widget=MultipleFileInput(),
        required=False,
        label="Asosiy rasm"
    )

    class Meta:
        model = Product
        fields = [
            "store", "brand", "model", "color", "year",
            "imei_full", "has_documents", "is_new",
            "defect", "battery_pct",
            "ownership", "purchase_price", "consignment_price",
            "owner_name", "owner_phone",
        ]

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        # Owner bo‘lmasa store ni o‘qish uchun chiqarsin, saqlaganda baribir user.store’ga majbur qilamiz
        self.fields["store"].queryset = Store.objects.filter(is_active=True)
        self.fields["brand"].queryset = Brand.objects.filter(is_active=True)
        self.fields["model"].queryset = ModelName.objects.filter(is_active=True)
        self.fields["color"].queryset = Color.objects.filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        # 7 ta rasm limiti: mavjud + yangi <= 7
        instance = getattr(self, "instance", None)
        existing = 0
        if instance and instance.pk:
            existing = ProductImage.objects.filter(product=instance).count()

        new_count = 0
        for key in ("doc_images", "cond_images", "images"):
            files = self.files.getlist(key)
            new_count += len(files)

        if existing + new_count > 7:
            raise forms.ValidationError("Rasm cheklovi: jami 7 tadan oshmasin (mavjud + yangi).")
        return cleaned

    def clean_imei_full(self):
        v = digits_only(self.cleaned_data.get("imei_full") or "")
        if len(v) < 4:
            raise forms.ValidationError("IMEI kamida 4 raqam bo‘lishi kerak.")
        return v

    def clean(self):
        cleaned = super().clean()
        ownership = cleaned.get("ownership")
        pp = cleaned.get("purchase_price") or Decimal("0")
        cp = cleaned.get("consignment_price") or Decimal("0")
        if ownership == "owned" and pp <= 0:
            self.add_error("purchase_price", "Owned uchun purchase_price majburiy.")
        if ownership == "consignment" and cp <= 0:
            self.add_error("consignment_price", "Consignment uchun consignment_price majburiy.")
        return cleaned


class BatchIntakeForm(forms.ModelForm):
    rows = forms.IntegerField(min_value=1, max_value=50, initial=10, help_text="Nechta qator kiritasiz?")

    class Meta:
        model = BatchIntake
        fields = ["store","title","note"]

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user and not user.is_owner:
            self.fields["store"].initial = user.store
            self.fields["store"].disabled = True


class BatchItemForm(forms.Form):
    brand = forms.ModelChoiceField(queryset=Brand.objects.filter(is_active=True).order_by("name"), required=False)
    model = forms.ModelChoiceField(queryset=ModelName.objects.filter(is_active=True).order_by("name"), required=False)
    color = forms.ModelChoiceField(queryset=Color.objects.filter(is_active=True).order_by("name"), required=False)
    year = forms.IntegerField(required=False)
    imei_full = forms.CharField(required=False, max_length=20)
    ownership = forms.ChoiceField(choices=Product.OWNERSHIP, initial="owned")
    purchase_price = forms.DecimalField(required=False, max_digits=12, decimal_places=2)
    consignment_price = forms.DecimalField(required=False, max_digits=12, decimal_places=2)
    has_documents = forms.BooleanField(required=False)
    is_new = forms.BooleanField(required=False)

class ExcelImportForm(forms.Form):
    file = forms.FileField(help_text="Excel (.xlsx)")
    store = forms.ModelChoiceField(queryset=Store.objects.filter(is_active=True).order_by("name"))
    # ixtiyoriy mapping: ustun nomlari mos tushsa, avtomatik.
    brand_col = forms.CharField(required=False, initial="BREND")
    model_col = forms.CharField(required=False, initial="MADEL")
    color_col = forms.CharField(required=False, initial="RANGI")
    imei_col  = forms.CharField(required=False, initial="IMEI")
    price_col = forms.CharField(required=False, initial="NARX")  # purchase or consign decide below
    ownership = forms.ChoiceField(choices=Product.OWNERSHIP, initial="owned")

class ImportExcelForm(forms.Form):
    file = forms.FileField()
    store = forms.ModelChoiceField(queryset=Store.objects.filter(is_active=True))

