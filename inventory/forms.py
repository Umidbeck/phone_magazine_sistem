from django import forms

from accounts.models import Store
from .models import Product, ProductImage, BatchIntake
from reference.models import Brand, ModelName, Color

# --- YANGI: ko‘p faylga ruxsat beradigan widget ---
class MultiFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class ProductCreateForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "store","brand","model","color","year","imei_full",
            "has_documents","is_new","defect","battery_pct",
            "ownership","purchase_price","consignment_price",
            "owner_name","owner_phone",
        ]

    # --- ESKINI ALMASHTIRING: ClearableFileInput o‘rniga MultiFileInput ---
    images = forms.FileField(
        required=False,
        widget=MultiFileInput(attrs={"multiple": True, "accept": "image/*"})
    )
    doc_images = forms.FileField(
        required=False,
        widget=MultiFileInput(attrs={"multiple": True, "accept": "image/*"})
    )
    cond_images = forms.FileField(
        required=False,
        widget=MultiFileInput(attrs={"multiple": True, "accept": "image/*"})
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user and not user.is_owner():
            self.fields["store"].initial = user.store
            self.fields["store"].disabled = True
        self.fields["brand"].queryset = Brand.objects.filter(is_active=True).order_by("name")
        self.fields["model"].queryset = ModelName.objects.filter(is_active=True).order_by("name")
        self.fields["color"].queryset = Color.objects.filter(is_active=True).order_by("name")

    def clean(self):
        data = super().clean()
        imei = (data.get("imei_full") or "").strip()
        data["imei_full"] = imei
        if len(imei) >= 4:
            self.instance.imei_last4 = imei[-4:]
        own = data.get("ownership")
        if own == "owned" and not data.get("purchase_price"):
            self.add_error("purchase_price","Owned uchun purchase_price majburiy.")
        if own == "consignment" and not data.get("consignment_price"):
            self.add_error("consignment_price","Consignment uchun consignment_price majburiy.")
        return data



class BatchIntakeForm(forms.ModelForm):
    rows = forms.IntegerField(min_value=1, max_value=50, initial=10, help_text="Nechta qator kiritasiz?")

    class Meta:
        model = BatchIntake
        fields = ["store","title","note"]

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user and not user.is_owner():
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

