from decimal import Decimal
from django.urls import reverse
from tests.factories import make_store, make_seller, make_owner, make_phone, sale
from sales.models import Transaction

def test_seller_can_return_only_own_store_sales(db, client):
    s1 = make_store("S1"); s2 = make_store("S2")
    a = make_seller(s1, "a"); b = make_seller(s2, "b")
    p1 = make_phone(s1); p2 = make_phone(s2)
    tx1 = sale(s1, a, p1, Decimal("500"))
    tx2 = sale(s2, b, p2, Decimal("500"))
    # a tries to return tx2 (other store)
    client.login(username="a", password="x")
    resp = client.post(reverse("sale_return_by_tx", args=[tx2.id]))
    assert resp.status_code in (302, 200)
    # should not void tx2
    tx2.refresh_from_db()
    assert tx2.is_void is False
