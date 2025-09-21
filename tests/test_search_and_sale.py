import pytest
from decimal import Decimal
from django.urls import reverse
from django.contrib.auth import get_user_model
from accounts.models import Store
from inventory.models import Product, Brand, ModelName
from sales.models import Transaction

User = get_user_model()

@pytest.mark.django_db
def test_search_by_last4(client):
    store = Store.objects.create(name="A")
    owner = User.objects.create_user(username="o", password="x", role="owner")
    client.login(username="o", password="x")

    b = Brand.objects.create(name="Apple", is_active=True)
    m = ModelName.objects.create(brand=b, name="iPhone 12", is_active=True)
    p = Product.objects.create(store=store, brand=b, model=m, imei_full="356789012345678", ownership="owned", created_by=owner)

    url = reverse("product_list")
    resp = client.get(url, {"q": "5678"})
    assert resp.status_code == 200
    # sahifada IMEI yoki model ko'rinishi
    assert "iPhone 12" in resp.content.decode()

@pytest.mark.django_db
def test_sale_profit_and_status(client):
    store = Store.objects.create(name="S")
    seller = User.objects.create_user(username="s", password="x", role="seller", store=store)
    b = Brand.objects.create(name="Samsung", is_active=True)
    m = ModelName.objects.create(brand=b, name="A50", is_active=True)
    p = Product.objects.create(store=store, brand=b, model=m, imei_full="352099999999999", ownership="owned",
                               purchase_price=Decimal("100"), created_by=seller)

    client.login(username="s", password="x")
    url = reverse("sell")
    # pick product
    resp = client.get(url, {"product_id": p.id})
    assert resp.status_code == 200

    resp = client.post(url, {"product_id": p.id, "amount": "150", "payment_type": "cash"}, follow=True)
    assert resp.status_code == 200

    p.refresh_from_db()
    assert p.status == "sold"
    tx = Transaction.objects.get(product=p, type="sale")
    assert tx.cost == Decimal("100.00")
    assert tx.profit == Decimal("50.00")
