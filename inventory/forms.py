from decimal import Decimal

from django import forms

from accounts.models import Store
from .models import Product, ProductImage, BatchIntake
from reference.models import Brand, ModelName, Color

# --- YANGI: ko‘p faylga ruxsat beradigan widget ---
class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


def digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

class ProductCreateForm(forms.ModelForm):
    # Doim barcha do‘konlar — so‘ngra __init__ da role bo‘yicha majburiylikni sozlaymiz
    store = forms.ModelChoiceField(
        queryset=Store.objects.all().order_by("name"),
        required=False,
        label="Store"
    )

    # YANGI: rasmlar
    doc_images = forms.FileField(
        required=False, widget=MultipleFileInput, label="Document photos"
    )
    cond_images = forms.FileField(
        required=False, widget=MultipleFileInput, label="Condition photos"
    )
    images = forms.FileField(
        required=False, widget=MultipleFileInput, label="Other photos"
    )
    class Meta:
        model = Product
        fields = [
            "store", "brand", "model", "color", "year",
            "imei_full", "has_documents", "is_new", "defect", "battery_pct",
            "ownership", "purchase_price", "consignment_price",
            "owner_name", "owner_phone",
        ]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        # Reference querysetlar
        self.fields["brand"].queryset = Brand.objects.all().order_by("name")
        self.fields["model"].queryset = ModelName.objects.all().order_by("name")
        self.fields["color"].queryset = Color.objects.all().order_by("name")

        # STORE majburiyligi — rolega qarab
        if user and getattr(user, "is_owner", False):
            # OWNER: majburiy tanlash
            self.fields["store"].required = True
        else:
            # SELLER:
            if getattr(user, "store_id", None):
                # Sellerning do‘koni bor: select ko‘rsatiladi (bosilishi mumkin),
                # lekin saqlashda baribir user.store yoziladi.
                self.fields["store"].initial = user.store
                self.fields["store"].required = False
            else:
                # Sellerning do‘koni yo‘q: majburiy tanlash kerak (fallback)
                self.fields["store"].required = True

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

