from django import forms
from decimal import Decimal
from inventory.models import Product
from reference.models import ExpenseType

PAYMENT_CHOICES = (("cash","Cash"),("card","Card"),("mixed","Mixed"))

class SaleForm(forms.Form):
    product_id = forms.IntegerField(widget=forms.HiddenInput())
    amount = forms.DecimalField(min_value=Decimal("0.01"), decimal_places=2)
    payment_type = forms.ChoiceField(choices=PAYMENT_CHOICES)

class ExpenseForm(forms.Form):
    product_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    expense_type = forms.ModelChoiceField(queryset=ExpenseType.objects.filter(is_active=True).order_by("name"))
    amount = forms.DecimalField(min_value=Decimal("0.01"), decimal_places=2)
    note = forms.CharField(required=False, max_length=200, widget=forms.TextInput())

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
