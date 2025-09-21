import pytest
from django.urls import reverse
from django.contrib.auth import get_user_model
from accounts.models import Store
from inventory.models import Product, Brand, ModelName

User = get_user_model()

@pytest.mark.django_db
def test_seller_cannot_access_other_store(client):
    s1 = Store.objects.create(name="S1")
    s2 = Store.objects.create(name="S2")
    seller = User.objects.create_user(username="s", password="x", role="seller", store=s1)
    owner = User.objects.create_user(username="o", password="x", role="owner")

    b = Brand.objects.create(name="Apple", is_active=True)
    m = ModelName.objects.create(brand=b, name="X", is_active=True)
    p_other = Product.objects.create(store=s2, brand=b, model=m, imei_full="350000000000000", ownership="owned", created_by=owner)

    client.login(username="s", password="x")
    url = reverse("sell")
    # seller qidirsa, s2 dagi product chiqmasligi kerak
    resp = client.get(url, {"q": "0000"})
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "350000000000000" not in content