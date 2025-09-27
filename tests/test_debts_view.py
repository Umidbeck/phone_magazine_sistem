from decimal import Decimal
from django.urls import reverse
from tests.factories import make_store, make_seller, debt_out

def test_debt_pay_view_blocks_overpay(db, client):
    store = make_store(); seller = make_seller(store)
    client.login(username=seller.username, password="x")
    d_out = debt_out(store, seller, Decimal("300"))
    url = reverse("debt_pay", args=[d_out.debtor_group])
    # overpay: 400
    resp = client.post(url, {
        "amount": "400.00", "payment_type": "cash", "cash_amount": "400.00", "card_amount": "0.00"
    })
    # form error -> stays on page with error message, status 200
    assert resp.status_code == 200
    assert b"To\u2018lov summasi qolgan qarzdan oshib ketdi" in resp.content
