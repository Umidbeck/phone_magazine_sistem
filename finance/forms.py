from django import forms
from .models import Investment

class InvestmentForm(forms.ModelForm):
    class Meta:
        model = Investment
        fields = ["date", "amount", "note"]

class KPIFilterForm(forms.Form):
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to   = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

