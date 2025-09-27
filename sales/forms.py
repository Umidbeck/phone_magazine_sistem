# sales/forms.py
from django import forms
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db.models import Sum

from accounts.models import Store
from sales.models import Transaction


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
    amount = forms.DecimalField(min_value=Decimal("0.01"), decimal_places=2)
    payment_type = forms.ChoiceField(choices=(("cash","Naqd"),("card","Karta"),("mixed","Aralash")))
    cash_amount = forms.DecimalField(required=False, decimal_places=2, min_value=Decimal("0"), initial=Decimal("0"))
    card_amount = forms.DecimalField(required=False, decimal_places=2, min_value=Decimal("0"), initial=Decimal("0"))

    def __init__(self, *args, **kwargs):
        # group (UUID) keladi – qolgan balansni hisoblash uchun
        self.group = kwargs.pop("group", None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()

        amount = cleaned.get("amount") or Decimal("0")
        ptype  = cleaned.get("payment_type")
        cash   = cleaned.get("cash_amount") or Decimal("0")
        card   = cleaned.get("card_amount") or Decimal("0")

        # 1) payment_type ga mos summalar tekshiruvi
        if ptype == "cash":
            card = Decimal("0")
            cleaned["card_amount"] = card
        elif ptype == "card":
            cash = Decimal("0")
            cleaned["cash_amount"] = cash
        # mixed bo'lsa, ikkalasi ham bo'lishi mumkin

        # 2) cash+card = amount bo'lsin
        if (cash + card) != amount:
            raise ValidationError("Naqd + Karta summasi umumiy to‘lovga teng bo‘lishi kerak.")

        # 3) Qolgan balansdan ortiq bo‘lmasin (server-side qoidasi)
        if self.group:
            out_total = (Transaction.objects
                         .filter(type="debt_out", debtor_group=self.group, is_void=False)
                         .aggregate(s=Sum("amount"))["s"] or Decimal("0"))
            pay_total = (Transaction.objects
                         .filter(type="debt_pay", debtor_group=self.group, is_void=False)
                         .aggregate(s=Sum("amount"))["s"] or Decimal("0"))
            # E’tibor: bu yerda APPROVED sharti qo‘ymayapmiz, chunki endi hammasi darhol approved bo‘ladi.
            remaining = Decimal(out_total) - Decimal(pay_total)
            if remaining < Decimal("0"):
                remaining = Decimal("0")
            if amount > remaining:
                raise ValidationError(f"To‘lov summasi qolgan qarzdan oshib ketdi. Qolgan: ${remaining:.2f}")

        return cleaned


class ConsignmentPayoutForm(forms.Form):
    amount = forms.CharField()
    note = forms.CharField(required=False)
    def clean_amount(self): return parse_amount(self.cleaned_data["amount"])
