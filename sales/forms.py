from django import forms
from decimal import Decimal

from accounts.models import Store
from inventory.models import Product
from reference.models import ExpenseType

PAYMENT_CHOICES = (("cash","Cash"),("card","Card"),("mixed","Mixed"))

class SaleForm(forms.Form):
    product_id = forms.IntegerField(widget=forms.HiddenInput())
    amount = forms.DecimalField(min_value=Decimal("0.01"), decimal_places=2)
    payment_type = forms.ChoiceField(choices=PAYMENT_CHOICES)

class ExpenseForm(forms.Form):
    product_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    store = forms.ModelChoiceField(                  # <-- YANGI
        queryset=Store.objects.filter(is_active=True),
        required=False
    )
    amount = forms.DecimalField(max_digits=12, decimal_places=2, required=True)
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def clean(self):
        cleaned = super().clean()
        product_id = cleaned.get("product_id")
        store = cleaned.get("store")
        # Agar product tanlanmagan bo'lsa, store majburiy bo'lsin (Owner uchun)
        if not product_id and not store:
            raise forms.ValidationError("Do'konni tanlang yoki telefon tanlang.")
        return cleaned


# ---- DEBT ----
class DebtNewForm(forms.Form):
    debtor_name = forms.CharField(max_length=120)
    amount = forms.DecimalField(min_value=Decimal("0.01"), decimal_places=2)
    note = forms.CharField(required=False, max_length=200, widget=forms.TextInput())

class DebtPayForm(forms.Form):
    amount = forms.DecimalField(min_value=Decimal("0.01"), decimal_places=2)
    note = forms.CharField(required=False, max_length=200, widget=forms.TextInput())

# ---- CONSIGNMENT PAYOUT ----
class ConsignmentPayoutForm(forms.Form):
    amount = forms.DecimalField(min_value=Decimal("0.01"), decimal_places=2)
    note = forms.CharField(required=False, max_length=200, widget=forms.TextInput())
