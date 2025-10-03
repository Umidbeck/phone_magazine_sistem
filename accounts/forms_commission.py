# accounts/forms_commission.py
from django import forms
from reference.models import Config

class CommissionConfigForm(forms.Form):
    commission_flat = forms.DecimalField(min_value=0, max_digits=12, decimal_places=2, label="Bonus (USD)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        v = Config.objects.filter(key="commission_flat").values_list("value", flat=True).first()
        if v:
            self.fields["commission_flat"].initial = v

    def save(self):
        value_str = str(self.cleaned_data["commission_flat"])
        Config.objects.update_or_create(key="commission_flat", defaults={"value": value_str})
        return value_str
