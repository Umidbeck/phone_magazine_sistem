# accounts/forms.py
from django import forms
from .models import Store, User

class StoreForm(forms.ModelForm):
    class Meta:
        model = Store
        fields = ["name", "is_active"]

class SellerCreateForm(forms.ModelForm):
    # Owner sellerga vaqtincha parol beradi (ko‘rsatib yuboramiz)
    password = forms.CharField(required=False, help_text="Qoldirsangiz, avtomatik yaratiladi.")
    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "store", "is_active"]

    def clean(self):
        cleaned = super().clean()
        # Seller roli majburiy va do‘kon tanlangan bo‘lsin
        cleaned["role"] = "seller"
        if not cleaned.get("store"):
            self.add_error("store", "Store tanlang.")
        return cleaned

class SellerUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "store", "is_active"]
