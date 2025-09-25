# sales/forms.py
from django import forms
from decimal import Decimal, InvalidOperation
from accounts.models import Store


def parse_amount(val):
    if val in (None, ""):
        return Decimal("0")
    s = str(val).strip().replace(" ", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        raise forms.ValidationError("Noto‘g‘ri summa")

PAYMENT_CHOICES = (("cash","Naqd"), ("card","Karta"), ("mixed","Aralash"))


class SaleForm(forms.Form):
    price = forms.CharField(label="Umumiy narx")
    payment_type = forms.ChoiceField(choices=PAYMENT_CHOICES, required=True)
    cash_amount = forms.CharField(required=False)
    card_amount = forms.CharField(required=False)

    def clean(self):
        cd = super().clean()
        price = parse_amount(cd.get("price"))
        cd["price"] = price

        ptype = cd.get("payment_type")
        cash = parse_amount(cd.get("cash_amount"))
        card = parse_amount(cd.get("card_amount"))

        if ptype == "cash":
            card = Decimal("0")
        elif ptype == "card":
            cash = Decimal("0")
        # mixed bo'lsa ikkalasi ham bo'lishi mumkin

        if (cash + card) != price:
            raise forms.ValidationError("Naqd + Karta = Umumiy narx bo‘lishi shart")

        cd["cash_amount"] = cash
        cd["card_amount"] = card
        return cd


class InstallmentSaleForm(forms.Form):
    customer_name = forms.CharField(label="Mijoz ismi", required=True)
    customer_phone = forms.CharField(label="Telefon", required=False)
    note = forms.CharField(label="Izoh", required=False)

    total_price = forms.CharField(label="Umumiy narx")
    payment_type = forms.ChoiceField(choices=PAYMENT_CHOICES, required=True)
    upfront_cash = forms.CharField(label="Hozir naqd", required=False)
    upfront_card = forms.CharField(label="Hozir karta", required=False)

    def clean(self):
        cd = super().clean()
        total = parse_amount(cd.get("total_price"))
        cd["total_price"] = total

        ptype = cd.get("payment_type")
        cash = parse_amount(cd.get("upfront_cash"))
        card = parse_amount(cd.get("upfront_card"))

        if ptype == "cash":
            card = Decimal("0")
        elif ptype == "card":
            cash = Decimal("0")

        if (cash + card) > total:
            raise forms.ValidationError("Hozir berilgan summa umumiy narxdan oshmasligi kerak")

        cd["upfront_cash"] = cash
        cd["upfront_card"] = card
        cd["upfront_total"] = (cash + card)
        cd["debt_amount"] = (total - (cash + card))
        return cd


class ExpenseForm(forms.Form):
    amount = forms.CharField()
    note = forms.CharField(required=False)
    store = forms.ModelChoiceField(queryset=Store.objects.all(), required=False)
    def clean_amount(self): return parse_amount(self.cleaned_data["amount"])


class DebtNewForm(forms.Form):
    debtor_name = forms.CharField()
    debtor_phone = forms.CharField(required=False)
    note = forms.CharField(required=False)
    amount = forms.CharField()
    def clean_amount(self): return parse_amount(self.cleaned_data["amount"])


class DebtNewSimpleForm(forms.Form):
    amount = forms.CharField(label="Summa")
    note = forms.CharField(label="Izoh", required=False)
    def clean_amount(self): return parse_amount(self.cleaned_data["amount"])



class DebtPayForm(forms.Form):
    payment_type = forms.ChoiceField(choices=PAYMENT_CHOICES, required=True)
    cash_amount = forms.CharField(required=False)
    card_amount = forms.CharField(required=False)
    def clean(self):
        cd = super().clean()
        p = cd.get("payment_type")
        cash = parse_amount(cd.get("cash_amount"))
        card = parse_amount(cd.get("card_amount"))
        if p == "cash": card = Decimal("0")
        elif p == "card": cash = Decimal("0")
        if (cash + card) <= 0:
            raise forms.ValidationError("To‘lov summasini kiriting")
        cd["cash_amount"], cd["card_amount"], cd["amount"] = cash, card, cash+card
        return cd


class ConsignmentPayoutForm(forms.Form):
    amount = forms.CharField()
    note = forms.CharField(required=False)
    def clean_amount(self): return parse_amount(self.cleaned_data["amount"])
