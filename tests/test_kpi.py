from decimal import Decimal
from tests.factories import make_store, make_seller, make_phone, sale, debt_out, debt_pay, expense
from reports.accounting import compute_kpi

def test_kpi_approved_only_flow(db):
    store = make_store(); seller = make_seller(store)
    p = make_phone(store, purchase=Decimal("300"))
    # sale 500 (approved), expense 40 (approved), profit=160
    sale(store, seller, p, total=Decimal("500"))
    expense(store, seller, p, Decimal("40"))

    # debt: out 200, pay 150
    d = debt_out(store, seller, Decimal("200"))
    debt_pay(store, seller, d.debtor_group, Decimal("150"))

    kpi = compute_kpi(store_id=store.id)  # sizning funksiya signaturangizga moslang
    # kassa kirimi: sale cash 500 + debt_pay 150
    assert kpi["cash_in"] >= Decimal("650")  # agar card yo'q deb faraz qildik
    # profit ~160
    assert kpi["profit"] >= Decimal("160")
