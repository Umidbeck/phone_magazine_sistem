# inventory/forms.py
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
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
    class Meta:
        model = BatchIntake
        fields = ["store", "title", "note", "supplier_name", "supplier_phone"]
        widgets = {
            "store": forms.Select(attrs={"class": "w-full rounded-xl border p-2"}),
            "title": forms.TextInput(attrs={"class": "w-full rounded-xl border p-2"}),
            "note": forms.Textarea(attrs={"class": "w-full rounded-xl border p-2", "rows": 2}),
            "supplier_name": forms.TextInput(attrs={"class": "w-full rounded-xl border p-2"}),
            "supplier_phone": forms.TextInput(attrs={"class": "w-full rounded-xl border p-2"}),
        }
        labels = {
            "store": _("Do‘kon"),
            "title": _("Sarlavha"),
            "note": _("Izoh"),
            "supplier_name": _("Yetkazib beruvchi (ism)"),
            "supplier_phone": _("Telefon"),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["store"].queryset = Store.objects.filter(is_active=True).order_by("name")
        if user and not getattr(user, "is_owner", False) and getattr(user, "store_id", None):
            self.fields["store"].initial = user.store_id
            self.fields["store"].disabled = True



class BatchItemForm(forms.Form):
    brand = forms.ModelChoiceField(queryset=Brand.objects.filter(is_active=True).order_by("name"))
    model = forms.ModelChoiceField(queryset=ModelName.objects.filter(is_active=True).order_by("name"))
    color = forms.ModelChoiceField(queryset=Color.objects.filter(is_active=True).order_by("name"), required=False)
    year  = forms.IntegerField(min_value=2000, max_value=2100, required=False)
    imei_full = forms.CharField(max_length=32)

    ownership = forms.ChoiceField(choices=Product.OWNERSHIP)
    purchase_price = forms.DecimalField(max_digits=12, decimal_places=2, required=False)
    consignment_price = forms.DecimalField(max_digits=12, decimal_places=2, required=False)

    has_documents = forms.BooleanField(required=False)
    is_new = forms.BooleanField(required=False)
    battery_pct = forms.IntegerField(min_value=0, max_value=100, required=False)
    asking_price = forms.DecimalField(max_digits=12, decimal_places=2, required=False)

    # Hujjat rasmi (1 dona, ixtiyoriy)
    document_image = forms.ImageField(required=False, widget=forms.ClearableFileInput(
        attrs={"accept": "image/*", "class": "w-full rounded-xl border p-2"}
    ))
    # Galereya rasmlari (0..7 dona, ixtiyoriy)
    images = forms.FileField(required=False, widget=MultipleFileInput(
        attrs={"accept": "image/*", "class": "w-full rounded-xl border p-2", "multiple": True}
    ), help_text=_("0–7 ta rasm"))

    def clean(self):
        cleaned = super().clean()
        ownership = cleaned.get("ownership")
        pp = cleaned.get("purchase_price") or 0
        cp = cleaned.get("consignment_price") or 0
        if ownership == "owned" and (pp is None or pp <= 0):
            self.add_error("purchase_price", _("Owned bo‘lsa ‘purchase_price’ shart."))
        if ownership == "consignment" and (cp is None or cp <= 0):
            self.add_error("consignment_price", _("Consignment bo‘lsa ‘consignment_price’ shart."))
        imei = cleaned.get("imei_full") or ""
        only_digits = "".join(ch for ch in imei if ch.isdigit())
        if len(only_digits) < 4:
            self.add_error("imei_full", _("IMEI kamida 4 ta raqam bo‘lsin."))
        cleaned["imei_full"] = only_digits
        return cleaned

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
    # 0..7 ta gallery rasm (ixtiyoriy)
    images = forms.FileField(
        required=False,
        widget=MultipleFileInput(attrs={
            "id": "id_images",
            "class": "hidden",      # UI: tashqaridan tugma/zone orqali ochamiz
            "accept": "image/*",
        }),
        help_text=_("0–7 ta rasm yuklang (ixtiyoriy).")
    )

    # Hujjat rasmi — bitta fayl (ixtiyoriy, hujjatli bo‘lsa majburiy)
    document_image = forms.ImageField(
        required=False,
        widget=ClearableFileInput(attrs={
            "id": "id_document_image",
            "class": "hidden",
            "accept": "image/*",
        }),
        help_text=_("Hujjat rasmi (ixtiyoriy, faqat 1 ta).")
    )

    class Meta:
        model = Product
        fields = [
            "store", "brand", "model", "color", "year",
            "ownership", "purchase_price", "consignment_price",
            "ask_price",
            "imei_full", "has_documents", "document_image", "is_new",
            "owner_name", "owner_phone",
            "defect", "battery_pct",
            # Agar modelda purchase_date bo'lsa, fields ro'yxatiga ham qo'sh:
            # "purchase_date",
        ]
        # Agar modelda purchase_date bo'lsa, widgetini ulash mumkin:
        widgets = {
            # "purchase_date": forms.DateInput(attrs={"type": "date"}),
            "store":  forms.Select(attrs={"class": "w-full rounded-xl border p-2"}),
            "brand":  forms.Select(attrs={"class": "w-full rounded-xl border p-2"}),
            "model":  forms.Select(attrs={"class": "w-full rounded-xl border p-2"}),
            "color":  forms.Select(attrs={"class": "w-full rounded-xl border p-2"}),
            "year":   forms.NumberInput(attrs={"class": "w-full rounded-xl border p-2", "min": 2000, "max": 2100}),
            "ownership": forms.Select(attrs={"class": "w-full rounded-xl border p-2"}),

            "purchase_price":    forms.NumberInput(attrs={"class": "w-full rounded-xl border p-2", "step": "0.01", "placeholder": "$"}),
            "consignment_price": forms.NumberInput(attrs={"class": "w-full rounded-xl border p-2", "step": "0.01", "placeholder": "$"}),
            "ask_price":         forms.NumberInput(attrs={"class": "w-full rounded-xl border p-2", "step": "0.01", "placeholder": "$"}),

            "imei_full": forms.TextInput(attrs={"class": "w-full rounded-xl border p-2"}),
            "has_documents": forms.CheckboxInput(attrs={"class": "rounded"}),
            "is_new":        forms.CheckboxInput(attrs={"class": "rounded"}),

            "owner_name":  forms.TextInput(attrs={"class": "w-full rounded-xl border p-2"}),
            "owner_phone": forms.TextInput(attrs={"class": "w-full rounded-xl border p-2"}),

            "defect":      forms.Textarea(attrs={"class": "w-full rounded-xl border p-2", "rows": 2}),
            "battery_pct": forms.NumberInput(attrs={"class": "w-full rounded-xl border p-2", "min": 0, "max": 100}),
        }
        labels = {
            "store": _("Do‘kon"),
            "brand": _("Brend"),
            "model": _("Model"),
            "color": _("Rang"),
            "year":  _("Yil"),
            "ownership": _("Egalik turi"),
            "purchase_price": _("Xarid narxi ($)"),
            "consignment_price": _("Konsignatsiya narxi ($)"),
            "ask_price": _("Sotuv (so‘ralgan) narx ($)"),
            "imei_full": _("IMEI"),
            "has_documents": _("Hujjatlari bor"),
            "document_image": _("Hujjat rasmi"),
            "is_new": _("Yangi holat"),
            "owner_name": _("Egasi (F.I.Sh)"),
            "owner_phone": _("Telefon raqami"),
            "defect": _("Nuqson"),
            "battery_pct": _("Batareya (%)"),
        }

    # ---------- Helpers ----------
    @staticmethod
    def _digits_only(s: str) -> str:
        return "".join(ch for ch in s if ch.isdigit())

    def __init__(self, *args, **kwargs):
        self._user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        # UI: Tailwind klasslari
        for name, field in self.fields.items():
            base = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = (
                base + " w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 "
                       "text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            ).strip()

        # Select queryset’lar
        self.fields["store"].queryset = Store.objects.filter(is_active=True).order_by("name")
        self.fields["brand"].queryset = Brand.objects.filter(is_active=True).order_by("name")
        self.fields["model"].queryset = ModelName.objects.filter(is_active=True).order_by("name")
        self.fields["color"].queryset = Color.objects.filter(is_active=True).order_by("name")

        # Sellerlar uchun store ni qulflash (disabled) va required=False
        if self._user and not getattr(self._user, "is_owner", False) and getattr(self._user, "store_id", None):
            self.fields["store"].initial = self._user.store_id
            self.fields["store"].disabled = True
            self.fields["store"].required = False  # disabled bo'lsa POSTda kelmasligi mumkin

        # $ ogohlantirish
        self.fields["purchase_price"].help_text    = _("Summani $ (AQSh dollari)da kiriting.")
        self.fields["consignment_price"].help_text = _("Summani $ (AQSh dollari)da kiriting.")
        self.fields["ask_price"].help_text         = _("Summani $ (AQSh dollari)da kiriting.")

    # ---------- Field validation ----------
    def clean_imei_full(self):
        v = self._digits_only(self.cleaned_data.get("imei_full") or "")
        if len(v) < 4:
            raise ValidationError(_("IMEI kamida 4 raqam bo‘lishi kerak."))
        return v

    def clean_battery_pct(self):
        v = self.cleaned_data.get("battery_pct")
        if v is None:
            return v
        try:
            iv = int(v)
        except (TypeError, ValueError):
            raise ValidationError(_("Batareya foizi butun son bo‘lishi kerak."))
        if not (0 <= iv <= 100):
            raise ValidationError(_("Batareya foizi 0–100 oralig‘ida bo‘lishi kerak."))
        return iv

    def clean_year(self):
        y = self.cleaned_data.get("year")
        if y is None:
            return y
        try:
            iy = int(y)
        except (TypeError, ValueError):
            raise ValidationError(_("Yil butun son bo‘lishi kerak."))
        if not (2000 <= iy <= 2100):
            raise ValidationError(_("Yil 2000–2100 oralig‘ida bo‘lishi kerak."))
        return iy

    def clean(self):
        cleaned = super().clean()

        ownership = cleaned.get("ownership")
        pp = cleaned.get("purchase_price") or Decimal("0")
        cp = cleaned.get("consignment_price") or Decimal("0")

        if ownership == "owned" and pp <= 0:
            self.add_error("purchase_price", _("Owned bo‘lsa xarid narxi shart."))
        if ownership == "consignment" and cp <= 0:
            self.add_error("consignment_price", _("Consignment bo‘lsa konsignatsiya narxi shart."))

        # Hujjatli bo‘lsa doc rasmi majburiy (yoki avvaldan bor)
        has_docs = bool(cleaned.get("has_documents"))
        doc = cleaned.get("document_image")
        already_has_doc = bool(getattr(self.instance, "document_image", None)) if self.instance and self.instance.pk else False
        if has_docs and not (doc or already_has_doc):
            self.add_error("document_image", _("Hujjatli telefon uchun hujjat rasmi talab qilinadi."))

        # Multiple rasmlar limiti (0..7) — mavjudlar + yangi ≤ 7
        new_files = []
        # self.files getlist ishlashi uchun MultiFileInput bor; bo'lmasa ham guard:
        if hasattr(self, "files") and "images" in getattr(self.files, "keys", lambda: [])():
            try:
                new_files = self.files.getlist("images")
            except Exception:
                new_files = []

        existing_count = 0
        if self.instance and self.instance.pk:
            existing_count = ProductImage.objects.filter(product=self.instance).count()

        if len(new_files) + existing_count > 7:
            self.add_error("images", _("Umumiy rasm soni 7 tadan oshmasligi kerak."))

        return cleaned

    # ---------- Save override ----------
    def save(self, commit=True):
        """
        - document_image kelmasa: eski faylni saqlab qolamiz
        - seller bo'lsa: store ni user’dan olamiz (view’da ham tekshirilyapti, ammo bu yerda ham safe)
        """
        instance: Product = super().save(commit=False)

        # document_image: bo'sh kelgan bo'lsa, mavjudini saqlash
        if not self.cleaned_data.get("document_image") and self.instance and self.instance.pk:
            instance.document_image = self.instance.document_image

        # sellerlar uchun store ni majburan user’dan
        if self._user and not getattr(self._user, "is_owner", False) and getattr(self._user, "store_id", None):
            instance.store_id = self._user.store_id

        if commit:
            instance.save()
            self.save_m2m()

        return instance

    # ---------- Public helper ----------
    def get_images(self):
        """0..7, bo‘sh bo‘lsa ham [] qaytaradi."""
        try:
            return self.files.getlist("images")
        except Exception:
            return []



class ProductImageForm(forms.ModelForm):
    images = forms.ImageField(
        required=False,
        label=_("Rasmlar"),
        widget=MultipleFileInput(attrs={
            "multiple": True,
            "accept": "image/*",
            "id": "id_images",
            "class": "hidden",  # templateda tugma orqali ochamiz
        })
    )
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
