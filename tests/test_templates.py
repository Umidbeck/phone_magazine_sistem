from decimal import Decimal
from django.urls import reverse
from tests.factories import make_store, make_seller, make_owner, make_phone, sale, debt_out, debt_pay
from django.utils import timezone as dj_tz

def test_commissions_list_renders_amounts(db, client):
    store = make_store(); owner = make_owner(); seller = make_seller(store)
    p = make_phone(store)
    sale(store, seller, p, Decimal("500"))
    client.login(username=owner.username, password="x")
    resp = client.get(reverse("commissions_list"))
    assert resp.status_code == 200
    assert b"$5.00" in resp.content  # usd filter ko'rinyapti

def test_debt_list_renders_balance(db, client):
    store = make_store(); seller = make_seller(store)
    d = debt_out(store, seller, Decimal("500"))
    debt_pay(store, seller, d.debtor_group, Decimal("400"))
    client.login(username=seller.username, password="x")
    resp = client.get(reverse("debt_list"))
    assert resp.status_code == 200
    assert b"$100.00" in resp.content  # qolgan
