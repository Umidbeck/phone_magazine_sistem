from decimal import Decimal

from django import forms
from django.forms import inlineformset_factory
from django.forms.widgets import ClearableFileInput

from accounts.models import Store
from .models import Product, ProductImage, BatchIntake
from reference.models import Brand, ModelName, Color
from django.utils.translation import gettext_lazy as _

# --- YANGI: ko‘p faylga ruxsat beradigan widget ---
class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


def digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

class ProductCreateForm(forms.ModelForm):
    from django.forms.widgets import FileInput
    class MultipleFileInput(FileInput):
        allow_multiple_selected = True

    doc_images = forms.FileField(widget=MultipleFileInput(), required=False, label="Dokument rasmlari")
    cond_images = forms.FileField(widget=MultipleFileInput(), required=False, label="Holat rasmlari")
    images     = forms.FileField(widget=MultipleFileInput(), required=False, label="Asosiy rasm(lar)")

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
        # queryset’larni sizning model holatingizga moslang
        # (Brand/ModelName/Color/Store active bo‘lsa, filter qiling)


        self.fields["store"].queryset = Store.objects.filter(is_active=True)
        self.fields["brand"].queryset = Brand.objects.filter(is_active=True)
        self.fields["model"].queryset = ModelName.objects.filter(is_active=True)
        self.fields["color"].queryset = Color.objects.filter(is_active=True)

    def clean_imei_full(self):
        v = digits_only(self.cleaned_data.get("imei_full") or "")
        if len(v) < 4:
            raise forms.ValidationError("IMEI kamida 4 raqam bo‘lishi kerak.")
        return v

    def clean(self):
        cleaned = super().clean()
        # Rasm limiti
        instance = getattr(self, "instance", None)
        existing = 0
        if instance and instance.pk:
            existing = ProductImage.objects.filter(product=instance).count()

        new_count = 0
        for key in ("doc_images", "cond_images", "images"):  # <-- Faqat shu 3 ta nom
            files = self.files.getlist(key)
            new_count += len(files)

        if existing + new_count > 7:
            raise forms.ValidationError("Rasm cheklovi: jami 7 tadan oshmasin (mavjud + yangi).")

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


class ProductForm(forms.ModelForm):
    images = forms.FileField(
        required=False,
        widget=MultipleFileInput(  # ← o‘z multiple widget
            attrs={
                "class": "w-full rounded-xl border p-2",
                "accept": "image/*",
            }
        ),
        help_text="0–7 ta rasm yuklang (ixtiyoriy)."
    )

    # Hujjat uchun bitta rasm – ImageField, multiple emas
    document_image = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={
                "class": "w-full rounded-xl border p-2",
                "accept": "image/*",
            }
        ),
        help_text="Hujjat rasmi (ixtiyoriy, faqat 1 ta)."
    )
    class Meta:
        model = Product
        fields = [
            "store", "brand", "model", "color", "year",
            "ownership", "purchase_price", "consignment_price",
            "imei_full", "has_documents", "is_new",
            "owner_name", "owner_phone",
            "defect", "battery_pct","document_image",
        ]
        widgets = {
            "purchase_date": forms.DateInput(attrs={"type": "date"}),
            "store": forms.Select(attrs={"class": "w-full rounded-xl border p-2"}),
            "brand": forms.Select(attrs={"class": "w-full rounded-xl border p-2"}),
            "model": forms.Select(attrs={"class": "w-full rounded-xl border p-2"}),
            "color": forms.Select(attrs={"class": "w-full rounded-xl border p-2"}),
            "year": forms.NumberInput(attrs={"class": "w-full rounded-xl border p-2", "min": 2000, "max": 2100}),
            "ownership": forms.Select(attrs={"class": "w-full rounded-xl border p-2"}),
            "purchase_price": forms.NumberInput(attrs={"class": "w-full rounded-xl border p-2", "step": "0.01"}),
            "consignment_price": forms.NumberInput(attrs={"class": "w-full rounded-xl border p-2", "step": "0.01"}),
            "imei_full": forms.TextInput(attrs={"class": "w-full rounded-xl border p-2"}),
            "has_documents": forms.CheckboxInput(attrs={"class": "rounded"}),
            "is_new": forms.CheckboxInput(attrs={"class": "rounded"}),
            "owner_name": forms.TextInput(attrs={"class": "w-full rounded-xl border p-2"}),
            "owner_phone": forms.TextInput(attrs={"class": "w-full rounded-xl border p-2"}),
            "defect": forms.Textarea(attrs={"class": "w-full rounded-xl border p-2", "rows": 2}),
            "battery_pct": forms.NumberInput(attrs={"class": "w-full rounded-xl border p-2", "min": 0, "max": 100}),
        }
        labels = {
            "store": _("Do‘kon"),
            "brand": _("Brend"),
            "model": _("Model"),
            "color": _("Rang"),
            "year":  _("Yil"),
            "ownership": _("Egalik turi"),
            "purchase_price": _("Xarid narxi"),
            "consignment_price": _("Konsignatsiya narxi"),
            "imei_full": _("IMEI"),
            "has_documents": _("Hujjatlari bor"),
            "is_new": _("Yangi holat"),
            "owner_name": _("Egasi (F.I.Sh)"),
            "owner_phone": _("Telefon raqami"),
            "defect": _("Nuqson"),
            "battery_pct": _("Batareya (%)"),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        # faqat aktiv ma’lumotnomalar
        self.fields["store"].queryset = Store.objects.filter(is_active=True).order_by("name")
        self.fields["brand"].queryset = Brand.objects.filter(is_active=True).order_by("name")
        self.fields["model"].queryset = ModelName.objects.filter(is_active=True).order_by("name")
        self.fields["color"].queryset = Color.objects.filter(is_active=True).order_by("name")

        # seller bo‘lsa do‘kon maydoni qulflanadi
        if user and not getattr(user, "is_owner", False) and getattr(user, "store_id", None):
            self.fields["store"].initial = user.store_id
            self.fields["store"].disabled = True

        self.fields["document_image"].required = False

        # Seller bo‘lsa store’ni ko‘rsatamiz, lekin tahrirlatmaymiz
        if user and not getattr(user, "is_owner", False):
            self.fields["store"].initial = getattr(user, "store", None)
            self.fields["store"].disabled = True

    def clean_imei_full(self):
        v = digits_only(self.cleaned_data.get("imei_full") or "")
        if len(v) < 4:
            raise forms.ValidationError(_("IMEI kamida 4 raqam bo‘lishi kerak."))
        return v

    def clean(self):
        cleaned = super().clean()
        ownership = cleaned.get("ownership")
        pp = cleaned.get("purchase_price") or Decimal("0")
        cp = cleaned.get("consignment_price") or Decimal("0")
        if ownership == "owned" and pp <= 0:
            self.add_error("purchase_price", _("Owned bo‘lsa xarid narxi shart."))
        if ownership == "consignment" and cp <= 0:
            self.add_error("consignment_price", _("Consignment bo‘lsa konsignatsiya narxi shart."))
        return cleaned


class ProductImageForm(forms.ModelForm):
    class Meta:
        model = ProductImage
        # MUHIM: modeldagi nom 'kind', 'type' emas
        fields = ["image", "kind"]
        widgets = {
            "image": forms.ClearableFileInput(attrs={"class": "w-full rounded-xl border p-2", "accept": "image/*"}),
            "kind": forms.Select(attrs={"class": "w-full rounded-xl border p-2"}),
        }
        labels = {
            "image": _("Rasm"),
            "kind":  _("Turi (doc/cond/other)"),
        }


ProductImageFormSet = inlineformset_factory(
    parent_model=Product,
    model=ProductImage,
    form=ProductImageForm,
    extra=7,
    max_num=7,
    can_delete=True,
)
