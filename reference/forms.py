from django import forms
from .models import Brand, ModelName, Color, ExpenseType

class BrandForm(forms.ModelForm):
    class Meta:
        model = Brand
        fields = ["name", "is_active"]

class ModelNameForm(forms.ModelForm):
    class Meta:
        model = ModelName
        fields = ["brand", "name", "is_active"]

class ColorForm(forms.ModelForm):
    class Meta:
        model = Color
        fields = ["name", "hex_code", "is_active"]
