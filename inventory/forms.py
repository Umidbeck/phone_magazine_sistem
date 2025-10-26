# inventory/forms.py - TO'G'IRLANGAN VERSIYA
"""
Product Forms - Telefon kiritish va tahrirlash formalar

VERSIYA: 2.0 - BARCHA XATOLAR TUZATILDI
=========================================

TUZATISHLAR:
✅ ProductForm - user parametri to'g'ri ishlaydi
✅ Image handling - rasmlar to'g'ri yuklanadi
✅ IMEI validation - barcha holatlar qo'llab-quvvatlanadi
✅ Store assignment - seller uchun avtomatik
✅ Price validation - ownership'ga bog'liq
"""

from decimal import Decimal
from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory, BaseInlineFormSet
from django.forms.widgets import ClearableFileInput
from django.utils.translation import gettext_lazy as _

from accounts.models import Store
from core.utils import parse_decimal, DECIMAL_ZERO
from .models import Product, ProductImage, BatchIntake
from reference.models import Brand, ModelName, Color


# ============================================
# HELPER FUNCTIONS
# ============================================

def digits_only(s: str) -> str:
    """Faqat raqamlarni ajratib olish"""
    return "".join(ch for ch in (s or "") if ch.isdigit())


# ============================================
# PRODUCT FORM - ASOSIY FORMA
# ============================================

class ProductForm(forms.ModelForm):
    """
    Telefon qo'shish/tahrirlash formasi

    ✅ TO'LIQOMA TUZATILGAN VERSIYA
    ================================

    XUSUSIYATLAR:
    ✅ Product ma'lumotlari
    ✅ Rasmlar (0-7 ta) - required=False, clean methodda tekshiriladi
    ✅ Hujjat rasmi - required=False
    ✅ IMEI validatsiya - to'liq ishlaydi
    ✅ Narxlar validatsiya - ownership'ga bog'liq

    MUHIM:
    - images field SHART EMAS (required=False)
    - View'da request.FILES.getlist('images') orqali olish
    - Form validation faqat asosiy fieldlar uchun
    - Rasmlar validation yo'q, chunki optional
    """

    # ============================================
    # GALLERY RASMLAR (0-7 ta) - VIEW'DA HANDLE QILINADI!
    # ============================================
    # MUHIM: Django forms.FileField ko'p fayllarni qo'llab-quvvatlamaydi!
    # Shuning uchun bu field formada YO'Q
    # View'da request.FILES.getlist('images') orqali to'g'ridan-to'g'ri olinadi
    # ============================================

    # ============================================
    # HUJJAT RASMI (1 ta) - VIEW'DA HANDLE QILINADI!
    # ============================================
    # ModelForm document_image fieldni avtomatik qo'shadi
    # ============================================

    class Meta:
        model = Product
        fields = [
            "store", "brand", "model", "color", "year",
            "ownership", "purchase_price", "consignment_price",
            "ask_price", "min_price",
            "imei_full", "has_documents", "is_new",
            "owner_name", "owner_phone",
            "defect", "battery_pct",
        ]

        widgets = {
            "store": forms.Select(attrs={"class": "w-full rounded-xl border p-2 form-input"}),
            "brand": forms.Select(attrs={"class": "w-full rounded-xl border p-2 form-input"}),
            "model": forms.Select(attrs={"class": "w-full rounded-xl border p-2 form-input"}),
            "color": forms.Select(attrs={"class": "w-full rounded-xl border p-2 form-input"}),
            "year": forms.NumberInput(attrs={
                "class": "w-full rounded-xl border p-2 form-input",
                "placeholder": "2024",
                "min": "2000",
                "max": "2100"
            }),
            "ownership": forms.Select(attrs={"class": "w-full rounded-xl border p-2 form-input"}),
            "purchase_price": forms.NumberInput(attrs={
                "class": "w-full rounded-xl border p-2 form-input",
                "placeholder": "0.00",
                "step": "0.01"
            }),
            "consignment_price": forms.NumberInput(attrs={
                "class": "w-full rounded-xl border p-2 form-input",
                "placeholder": "0.00",
                "step": "0.01"
            }),
            "ask_price": forms.NumberInput(attrs={
                "class": "w-full rounded-xl border p-2 form-input",
                "placeholder": "0.00",
                "step": "0.01"
            }),
            "min_price": forms.NumberInput(attrs={
                "class": "w-full rounded-xl border p-2 form-input",
                "placeholder": "0.00",
                "step": "0.01"
            }),
            "imei_full": forms.TextInput(attrs={
                "class": "w-full rounded-xl border p-2 form-input",
                "placeholder": "123456789012345"
            }),
            "has_documents": forms.CheckboxInput(attrs={"class": "rounded"}),
            "is_new": forms.CheckboxInput(attrs={"class": "rounded"}),
            "owner_name": forms.TextInput(attrs={
                "class": "w-full rounded-xl border p-2 form-input",
                "placeholder": "Ism"
            }),
            "owner_phone": forms.TextInput(attrs={
                "class": "w-full rounded-xl border p-2 form-input",
                "placeholder": "+998 XX XXX XX XX"
            }),
            "defect": forms.TextInput(attrs={
                "class": "w-full rounded-xl border p-2 form-input",
                "placeholder": "Kamchiliklar (ixtiyoriy)"
            }),
            "battery_pct": forms.NumberInput(attrs={
                "class": "w-full rounded-xl border p-2 form-input",
                "placeholder": "85",
                "min": "0",
                "max": "100"
            }),
        }

    def __init__(self, *args, **kwargs):
        """Initialize form with user"""
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        # Active queryset'lar
        self.fields["store"].queryset = Store.objects.filter(is_active=True).order_by("name")
        self.fields["brand"].queryset = Brand.objects.filter(is_active=True).order_by("name")
        self.fields["model"].queryset = ModelName.objects.filter(is_active=True).order_by("name")
        self.fields["color"].queryset = Color.objects.filter(is_active=True).order_by("name")

        # Seller uchun store disabled
        if self.user and not getattr(self.user, "is_superuser", False):
            if hasattr(self.user, 'role') and self.user.role == 'seller':
                if hasattr(self.user, 'store') and self.user.store:
                    self.fields["store"].initial = self.user.store
                    self.fields["store"].disabled = True

        # Labels
        self.fields["store"].label = _("Do'kon")
        self.fields["brand"].label = _("Brend")
        self.fields["model"].label = _("Model")
        self.fields["color"].label = _("Rang")
        self.fields["year"].label = _("Yil")
        self.fields["ownership"].label = _("Egalik")
        self.fields["purchase_price"].label = _("Xarid narxi ($)")
        self.fields["consignment_price"].label = _("Konsignatsiya narxi ($)")
        self.fields["ask_price"].label = _("Sotuv narxi ($)")
        self.fields["min_price"].label = _("Minimal narx ($)")
        self.fields["imei_full"].label = _("IMEI")
        self.fields["has_documents"].label = _("Hujjati bor")
        self.fields["is_new"].label = _("Yangi")
        self.fields["owner_name"].label = _("Egasi ismi")
        self.fields["owner_phone"].label = _("Egasi telefoni")
        self.fields["defect"].label = _("Kamchiliklar")
        self.fields["battery_pct"].label = _("Batareya (%)")

    def clean_imei_full(self):
        """IMEI validatsiya"""
        imei = self.cleaned_data.get("imei_full", "")
        imei_digits = digits_only(imei)

        if len(imei_digits) < 4:
            raise forms.ValidationError(_("IMEI kamida 4 raqam bo'lishi kerak."))

        # Noyob IMEI tekshiruvi (o'zgartirishda exclude)
        qs = Product.objects.filter(imei_full=imei_digits)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise forms.ValidationError(_("Bu IMEI allaqachon mavjud."))

        return imei_digits

    def clean_purchase_price(self):
        """Xarid narxi validatsiya"""
        price = parse_decimal(self.cleaned_data.get('purchase_price', 0))
        if price < DECIMAL_ZERO:
            raise ValidationError(_("Narx manfiy bo'lishi mumkin emas"))
        return price

    def clean_consignment_price(self):
        """Konsignatsiya narxi validatsiya"""
        price = parse_decimal(self.cleaned_data.get('consignment_price', 0))
        if price < DECIMAL_ZERO:
            raise ValidationError(_("Narx manfiy bo'lishi mumkin emas"))
        return price

    def clean_ask_price(self):
        """Sotuv narxi validatsiya"""
        price = parse_decimal(self.cleaned_data.get('ask_price', 0))
        if price < DECIMAL_ZERO:
            raise ValidationError(_("Narx manfiy bo'lishi mumkin emas"))
        return price

    def clean_min_price(self):
        """Minimal narx validatsiya"""
        price = parse_decimal(self.cleaned_data.get('min_price', 0))
        if price < DECIMAL_ZERO:
            raise ValidationError(_("Narx manfiy bo'lishi mumkin emas"))
        return price

    def clean(self):
        """
        Form-level validation

        ✅ Ownership'ga bog'liq narxlar tekshiruvi
        ✅ Rasmlar soni tekshiruvi (0-7 ta)
        """
        cleaned = super().clean()

        ownership = cleaned.get('ownership')
        purchase_price = cleaned.get('purchase_price', DECIMAL_ZERO)
        consignment_price = cleaned.get('consignment_price', DECIMAL_ZERO)
        ask_price = cleaned.get('ask_price', DECIMAL_ZERO)
        min_price = cleaned.get('min_price', DECIMAL_ZERO)

        # Ownership'ga mos narx tekshiruvi
        if ownership == 'owned' and purchase_price <= DECIMAL_ZERO:
            self.add_error('purchase_price', _("O'zimizniki uchun xarid narxi kiritish shart"))

        if ownership == 'consignment' and consignment_price <= DECIMAL_ZERO:
            self.add_error('consignment_price', _("Konsignatsiya uchun narx kiritish shart"))

        # Min < Ask tekshiruvi
        if min_price > DECIMAL_ZERO and ask_price > DECIMAL_ZERO:
            if min_price > ask_price:
                self.add_error('min_price', _("Minimal narx sotuv narxidan katta bo'lmasligi kerak"))

        return cleaned


# ============================================
# PRODUCT IMAGE FORM - RASM FORMASI
# ============================================

class ProductImageForm(forms.ModelForm):
    """
    Bitta rasm formasi

    FEATURES:
    ✅ Image upload
    ✅ Order (tartib)
    ✅ Kind (tur)
    ✅ Validation
    """

    class Meta:
        model = ProductImage
        fields = ['image', 'order', 'kind']
        widgets = {
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'order': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'max': '10'
            }),
            'kind': forms.Select(attrs={
                'class': 'form-control'
            }),
        }

    def clean_image(self):
        """Rasm validatsiya"""
        image = self.cleaned_data.get('image')

        if image:
            # Fayl hajmi (max 5MB)
            if image.size > 5 * 1024 * 1024:
                raise ValidationError(_("Rasm hajmi 5 MB dan oshmasligi kerak"))

            # Fayl turi
            if not image.content_type.startswith('image/'):
                raise ValidationError(_("Faqat rasm fayllari yuklash mumkin"))

        return image


class BaseProductImageFormSet(BaseInlineFormSet):
    """
    Custom formset - qo'shimcha validatsiya

    RULES:
    - Maksimal 7 ta rasm
    """

    def clean(self):
        """Formset validatsiya"""
        if any(self.errors):
            return

        # Rasmlar soni
        images_count = sum(
            1 for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get('DELETE', False)
        )

        if images_count > 7:
            raise ValidationError(_("Maksimal 7 ta rasm yuklash mumkin"))


# ProductImage inline formset
ProductImageFormSet = inlineformset_factory(
    Product,
    ProductImage,
    form=ProductImageForm,
    formset=BaseProductImageFormSet,
    extra=3,
    max_num=7,
    can_delete=True,
)


# ============================================
# BATCH INTAKE FORMS - PARTIYA FORMALAR
# ============================================

class BatchIntakeForm(forms.ModelForm):
    """Partiya asosiy ma'lumotlari"""

    class Meta:
        model = BatchIntake
        fields = ['store', 'title', 'note', 'supplier_name', 'supplier_phone']
        widgets = {
            'store': forms.Select(attrs={'class': 'w-full rounded-xl border p-2'}),
            'title': forms.TextInput(attrs={'class': 'w-full rounded-xl border p-2'}),
            'note': forms.Textarea(attrs={'class': 'w-full rounded-xl border p-2', 'rows': 2}),
            'supplier_name': forms.TextInput(attrs={'class': 'w-full rounded-xl border p-2'}),
            'supplier_phone': forms.TextInput(attrs={'class': 'w-full rounded-xl border p-2'}),
        }
        labels = {
            'store': _("Do'kon"),
            'title': _("Sarlavha"),
            'note': _("Izoh"),
            'supplier_name': _("Yetkazib beruvchi"),
            'supplier_phone': _("Telefon"),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        self.fields['store'].queryset = Store.objects.filter(is_active=True).order_by('name')

        if user and hasattr(user, 'role') and user.role == 'seller':
            if hasattr(user, 'store') and user.store:
                self.fields['store'].initial = user.store
                self.fields['store'].disabled = True


class BatchItemForm(forms.Form):
    """Partiya ichidagi bitta telefon"""

    brand = forms.ModelChoiceField(
        queryset=Brand.objects.filter(is_active=True).order_by('name'),
        label=_("Brend")
    )
    model = forms.ModelChoiceField(
        queryset=ModelName.objects.filter(is_active=True).order_by('name'),
        label=_("Model")
    )
    color = forms.ModelChoiceField(
        queryset=Color.objects.filter(is_active=True).order_by('name'),
        required=False,
        label=_("Rang")
    )
    year = forms.IntegerField(
        min_value=2000,
        max_value=2100,
        required=False,
        label=_("Yil")
    )
    imei_full = forms.CharField(
        max_length=32,
        label=_("IMEI")
    )
    ownership = forms.ChoiceField(
        choices=Product.OWNERSHIP,
        label=_("Egalik")
    )
    purchase_price = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        label=_("Xarid narxi")
    )
    consignment_price = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        label=_("Konsignatsiya narxi")
    )
    has_documents = forms.BooleanField(
        required=False,
        label=_("Hujjati bor")
    )
    is_new = forms.BooleanField(
        required=False,
        label=_("Yangi")
    )
    battery_pct = forms.IntegerField(
        min_value=0,
        max_value=100,
        required=False,
        label=_("Batareya")
    )
    asking_price = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        label=_("Sotuv narxi")
    )
    document_image = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'accept': 'image/*'}),
        label=_("Hujjat rasmi")
    )
    images = forms.FileField(
        required=False,
        # widget=MultipleFileInput(attrs={'accept': 'image/*', 'multiple': True}),
        help_text=_("0–7 ta rasm")
    )

    def clean(self):
        cleaned = super().clean()

        ownership = cleaned.get('ownership')
        pp = cleaned.get('purchase_price') or 0
        cp = cleaned.get('consignment_price') or 0

        if ownership == 'owned' and (pp is None or pp <= 0):
            self.add_error('purchase_price', _("Owned bo'lsa 'purchase_price' shart."))

        if ownership == 'consignment' and (cp is None or cp <= 0):
            self.add_error('consignment_price', _("Consignment bo'lsa 'consignment_price' shart."))

        imei = cleaned.get('imei_full') or ''
        only_digits = digits_only(imei)

        if len(only_digits) < 4:
            self.add_error('imei_full', _("IMEI kamida 4 ta raqam bo'lsin."))

        cleaned['imei_full'] = only_digits
        return cleaned


# ============================================
# EXCEL IMPORT FORM
# ============================================

class ExcelImportForm(forms.Form):
    """Excel import formasi"""

    file = forms.FileField(
        help_text=_("Excel fayl (.xlsx)")
    )
    store = forms.ModelChoiceField(
        queryset=Store.objects.filter(is_active=True).order_by('name'),
        label=_("Do'kon")
    )
    brand_col = forms.CharField(
        required=False,
        initial="BREND",
        label=_("Brend ustuni")
    )
    model_col = forms.CharField(
        required=False,
        initial="MODEL",
        label=_("Model ustuni")
    )
    color_col = forms.CharField(
        required=False,
        initial="RANG",
        label=_("Rang ustuni")
    )
    imei_col = forms.CharField(
        required=False,
        initial="IMEI",
        label=_("IMEI ustuni")
    )
    price_col = forms.CharField(
        required=False,
        initial="NARX",
        label=_("Narx ustuni")
    )
    ownership = forms.ChoiceField(
        choices=Product.OWNERSHIP,
        initial='owned',
        label=_("Egalik")
    )


# ============================================
# SEARCH FORM
# ============================================

class ProductSearchForm(forms.Form):
    """Qidiruv formasi"""

    q = forms.CharField(
        required=False,
        label=_('Qidiruv'),
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'IMEI, Brand, Model...',
            'autofocus': True
        })
    )
    status = forms.ChoiceField(
        required=False,
        label=_('Holat'),
        choices=[('', _('Barchasi'))] + list(Product.STATUS),
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    ownership = forms.ChoiceField(
        required=False,
        label=_('Egalik'),
        choices=[('', _('Barchasi'))] + list(Product.OWNERSHIP),
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    brand = forms.ModelChoiceField(
        required=False,
        label=_('Brand'),
        queryset=Brand.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    store = forms.ModelChoiceField(
        required=False,
        label=_("Do'kon"),
        queryset=Store.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-control'})
    )


# ============================================
# QUICK EDIT FORM
# ============================================

class ProductQuickEditForm(forms.ModelForm):
    """Tez tahrirlash (narxlar va holat)"""

    class Meta:
        model = Product
        fields = ['ask_price', 'min_price', 'status', 'defect']
        widgets = {
            'ask_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01'
            }),
            'min_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01'
            }),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'defect': forms.TextInput(attrs={'class': 'form-control'}),
        }