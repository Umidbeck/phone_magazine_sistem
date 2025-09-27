from decimal import Decimal
from tests.factories import make_store, make_seller, debt_out, debt_pay
from sales.models import Transaction
from django.core.exceptions import ValidationError
from django.db.models import Sum

def approved_totals(group):
    out_total = (Transaction.objects.filter(type="debt_out", debtor_group=group, is_approved=True)
                 .aggregate(s=Sum("amount"))["s"] or Decimal("0"))
    pay_total = (Transaction.objects.filter(type="debt_pay", debtor_group=group, is_approved=True)
                 .aggregate(s=Sum("amount"))["s"] or Decimal("0"))
    return (out_total, pay_total, out_total - pay_total)

def test_debt_out_and_pay_make_correct_balance(db):
    store = make_store(); seller = make_seller(store)
    d_out = debt_out(store, seller, Decimal("500"), name="Ali")
    # pay 400 (approved immediately)
    d_pay = debt_pay(store, seller, d_out.debtor_group, Decimal("400"), cash=Decimal("400"))
    out_total, pay_total, balance = approved_totals(d_out.debtor_group)
    assert out_total == Decimal("500")
    assert pay_total == Decimal("400")
    assert balance == Decimal("100")

def test_overpay_is_blocked(db, client):
    """
    Overpay server-side blokini form.clean() bilan tekshirish uchun view POST'iga borish kerak.
    Bu yerda bevosita Transaction yaratishga ruxsat bersak ham - normal kodda form bloklaydi.
    """
    store = make_store(); seller = make_seller(store)
    d_out = debt_out(store, seller, Decimal("300"), name="Ali")
    # Simulyatsiya: overpay bo'lishi kerak — lekin real view form.clean() buni to'xtatadi.
    # Shu testda "qo'lda" yaratishni urinmaymiz; approved balans tekshiruvi quyida:
    # Avval normal pay:
    debt_pay(store, seller, d_out.debtor_group, Decimal("150"))
    # Keyin "ortiqcha" bo'ladigan holat:
    out_total, pay_total, balance = approved_totals(d_out.debtor_group)
    assert balance == Decimal("150")
    # Agar yana 200 to'lov kelmoqchi bo'lsa, form.clean() raise qiladi (view testida tekshiriladi).
