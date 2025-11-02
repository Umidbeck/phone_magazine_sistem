# sales/forms.py - MUKAMMAL VALIDATION
"""
Sales forms - To'liq validatsiya va xavfsizlik

ASOSIY QOIDALAR:
1. Har bir summa Decimal'ga aylantiriladi
2. Payment type'ga mos summalar tekshiriladi
3. Balans tekshiriladi (debt pay uchun)
4. Null/empty qiymatlar xavfsiz boshqariladi

VERSIYA: 2.0 - Encoding muammolari tuzatildi
"""

from decimal import Decimal
from typing import Optional
from uuid import UUID

from django import forms
from django.core.exceptions import ValidationError

from core.utils import parse_decimal, DECIMAL_ZERO


# ============================================
# PAYMENT CHOICES
# ============================================

PAYMENT_CHOICES = (
    ("cash", "Naqd"),
    ("card", "Karta"),
    ("mixed", "Aralash")
)


# ============================================
# SALE FORMS
# ============================================

class SaleForm(forms.Form):
    """
    To'liq to'lov (naqd/karta/aralash)
    """
    price = forms.CharField(
        label="Umumiy narx ($)",
        help_text="Telefon sotuv narxi"
    )
    payment_type = forms.ChoiceField(
        choices=PAYMENT_CHOICES,
        label="To'lov turi"
    )
    cash_amount = forms.CharField(
        required=False,
        label="Naqd ($)",
        initial="0"
    )
    card_amount = forms.CharField(
        required=False,
        label="Karta ($)",
        initial="0"
    )

    def clean_price(self):
        price = parse_decimal(self.cleaned_data.get("price"))
        if price <= DECIMAL_ZERO:
            raise ValidationError("Narx 0 dan katta bo'lishi kerak")
        return price

    def clean(self):
        cleaned = super().clean()

        price = cleaned.get("price")
        if not price:
            return cleaned

        ptype = cleaned.get("payment_type")
        cash = parse_decimal(cleaned.get("cash_amount"))
        card = parse_decimal(cleaned.get("card_amount"))

        # Payment type'ga mos summa
        if ptype == "cash":
            cash = price
            card = DECIMAL_ZERO
        elif ptype == "card":
            card = price
            cash = DECIMAL_ZERO
        elif ptype == "mixed":
            if (cash + card) != price:
                raise ValidationError("Naqd + Karta = Umumiy narx bo'lishi kerak")
        else:
            raise ValidationError("Noto'g'ri to'lov turi")

        cleaned["cash_amount"] = cash
        cleaned["card_amount"] = card

        return cleaned


class InstallmentSaleForm(forms.Form):
    """
    Bo'lib to'lash (qarz bilan)
    """
    customer_name = forms.CharField(
        label="Mijoz ismi",
        max_length=120
    )
    customer_phone = forms.CharField(
        label="Telefon",
        max_length=50,
        required=False
    )
    note = forms.CharField(
        label="Izoh",
        widget=forms.Textarea(attrs={"rows": 2}),
        required=False
    )

    total_price = forms.CharField(
        label="Umumiy narx ($)"
    )
    payment_type = forms.ChoiceField(
        choices=PAYMENT_CHOICES,
        label="To'lov turi"
    )
    upfront_cash = forms.CharField(
        label="Hozir naqd ($)",
        required=False,
        initial="0"
    )
    upfront_card = forms.CharField(
        label="Hozir karta ($)",
        required=False,
        initial="0"
    )

    def clean_total_price(self):
        total = parse_decimal(self.cleaned_data.get("total_price"))
        if total <= DECIMAL_ZERO:
            raise ValidationError("Umumiy narx 0 dan katta bo'lishi kerak")
        return total

    def clean(self):
        cleaned = super().clean()

        total = cleaned.get("total_price")
        if not total:
            return cleaned

        ptype = cleaned.get("payment_type")
        cash = parse_decimal(cleaned.get("upfront_cash"))
        card = parse_decimal(cleaned.get("upfront_card"))

        # Payment type check
        if ptype == "cash":
            card = DECIMAL_ZERO
        elif ptype == "card":
            cash = DECIMAL_ZERO
        # mixed: both can be > 0

        upfront_total = cash + card

        if upfront_total > total:
            raise ValidationError("Oldindan to'lov umumiy narxdan oshmasligi kerak")

        debt_amount = total - upfront_total

        cleaned["upfront_cash"] = cash
        cleaned["upfront_card"] = card
        cleaned["upfront_total"] = upfront_total
        cleaned["debt_amount"] = debt_amount

        return cleaned


# ============================================
# EXPENSE FORMS
# ============================================

class ExpenseForm(forms.Form):
    """
    Rashod (expense)
    """
    amount = forms.CharField(label="Summa ($)")
    note = forms.CharField(
        label="Izoh",
        widget=forms.Textarea(attrs={"rows": 2}),
        required=False
    )

    def clean_amount(self):
        amount = parse_decimal(self.cleaned_data.get("amount"))
        if amount <= DECIMAL_ZERO:
            raise ValidationError("Summa 0 dan katta bo'lishi kerak")
        return amount


# ============================================
# DEBT FORMS
# ============================================

class DebtNewForm(forms.Form):
    """
    Yangi qarz (to'liq ma'lumot bilan)
    """
    debtor_name = forms.CharField(
        label="Qarzdor ismi",
        max_length=120
    )
    debtor_phone = forms.CharField(
        label="Telefon",
        max_length=50,
        required=False
    )
    note = forms.CharField(
        label="Izoh",
        widget=forms.Textarea(attrs={"rows": 2}),
        required=False
    )
    amount = forms.CharField(label="Summa ($)")

    def clean_amount(self):
        amount = parse_decimal(self.cleaned_data.get("amount"))
        if amount <= DECIMAL_ZERO:
            raise ValidationError("Summa 0 dan katta bo'lishi kerak")
        return amount


class DebtNewSimpleForm(forms.Form):
    """
    Sodda qarz (faqat summa)
    """
    amount = forms.CharField(label="Summa ($)")
    note = forms.CharField(
        label="Izoh",
        widget=forms.Textarea(attrs={"rows": 2}),
        required=False
    )

    def clean_amount(self):
        amount = parse_decimal(self.cleaned_data.get("amount"))
        if amount <= DECIMAL_ZERO:
            raise ValidationError("Summa 0 dan katta bo'lishi kerak")
        return amount


class DebtPayForm(forms.Form):
    """
    Qarz to'lovi

    MUHIM: Balans tekshiruvi built-in
    """
    amount = forms.CharField(label="Summa ($)")
    payment_type = forms.ChoiceField(
        choices=PAYMENT_CHOICES,
        label="To'lov turi"
    )
    cash_amount = forms.CharField(
        label="Naqd ($)",
        required=False,
        initial="0"
    )
    card_amount = forms.CharField(
        label="Karta ($)",
        required=False,
        initial="0"
    )

    def __init__(self, *args, **kwargs):
        # Group (UUID) - balans tekshiruvi uchun
        self.group: Optional[UUID] = kwargs.pop("group", None)
        super().__init__(*args, **kwargs)

    def clean_amount(self):
        amount = parse_decimal(self.cleaned_data.get("amount"))
        if amount <= DECIMAL_ZERO:
            raise ValidationError("Summa 0 dan katta bo'lishi kerak")
        return amount

    def clean(self):
        cleaned = super().clean()

        amount = cleaned.get("amount")
        if not amount:
            return cleaned

        ptype = cleaned.get("payment_type")
        cash = parse_decimal(cleaned.get("cash_amount"))
        card = parse_decimal(cleaned.get("card_amount"))

        # Payment type check
        if ptype == "cash":
            cash = amount
            card = DECIMAL_ZERO
        elif ptype == "card":
            card = amount
            cash = DECIMAL_ZERO
        elif ptype == "mixed":
            if (cash + card) != amount:
                raise ValidationError("Naqd + Karta = Umumiy summa bo'lishi kerak")
        else:
            raise ValidationError("Noto'g'ri to'lov turi")

        cleaned["cash_amount"] = cash
        cleaned["card_amount"] = card

        # BALANS TEKSHIRUVI
        if self.group:
            from sales.services import calculate_debt_balance
            balance_info = calculate_debt_balance(self.group)
            remaining = balance_info["balance"]

            if amount > remaining:
                raise ValidationError(
                    f"To'lov summasi qolgan qarzdan oshib ketdi. "
                    f"Qolgan: ${remaining:.2f}"
                )

        return cleaned


# ============================================
# CONSIGNMENT FORMS
# ============================================

class ConsignmentPayoutForm(forms.Form):
    """
    Konsignatsiya to'lovi
    """
    amount = forms.CharField(label="Summa ($)")
    note = forms.CharField(
        label="Izoh",
        widget=forms.Textarea(attrs={"rows": 2}),
        required=False
    )

    def clean_amount(self):
        amount = parse_decimal(self.cleaned_data.get("amount"))
        if amount <= DECIMAL_ZERO:
            raise ValidationError("Summa 0 dan katta bo'lishi kerak")
        return amount


class ConsignmentNewForm(forms.Form):
    """
    Yangi konsignatsiya to'lovi (product'siz)
    """
    amount = forms.CharField(label="Summa ($)")
    note = forms.CharField(
        label="Izoh",
        widget=forms.Textarea(attrs={"rows": 2}),
        required=False
    )

    def clean_amount(self):
        amount = parse_decimal(self.cleaned_data.get("amount"))
        if amount <= DECIMAL_ZERO:
            raise ValidationError("Summa 0 dan katta bo'lishi kerak")
        return amount


# ============================================
# COMMISSION FORMS
# ============================================

class CommissionUpdateForm(forms.Form):
    """
    Komissiya summani o'zgartirish (owner uchun)
    """
    amount = forms.CharField(label="Yangi summa ($)")

    def clean_amount(self):
        amount = parse_decimal(self.cleaned_data.get("amount"))
        if amount < DECIMAL_ZERO:
            raise ValidationError("Summa manfiy bo'lishi mumkin emas")
        return amount

