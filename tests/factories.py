# tests/factories.py
import uuid
from decimal import Decimal
from django.utils import timezone

from inventory.models import Product, Brand, ModelName, Color
from sales.models import Transaction
from accounts.models import User
from accounts.models import Store

def make_store(name="S"):
    return Store.objects.create(name=name)

def make_owner(username="o"):
    # owner rolidagi foydalanuvchi
    return User.objects.create_user(username=username, password="x", role="owner")

def make_seller(store, username="s"):
    return User.objects.create_user(username=username, password="x", role="seller", store=store)

def make_phone(store, ownership="owned", purchase: Decimal | None = None, **extra):
    # ... brand/model yaratish qismi o‘zingizdagi kabi ...
    last4 = f"{random.randint(0, 9999):04d}"
    imei = f"35{random.randint(2000000000000, 2999999999999)}"  # 15 xonali bo‘lsin
    imei = imei[:-4] + last4  # har chaqiriqda farq qiladi

    kwargs = dict(
        store=store, brand=b, model=m,
        imei_full=imei,
        ownership=ownership,
        created_by=extra.get("created_by") or seller_or_owner_object,
    )
    if purchase is not None:
        kwargs["purchase_price"] = purchase
    kwargs.update(extra)
    return Product.objects.create(**kwargs)

def debt_out(store, seller, amount: Decimal, name: str | None = None):
    return Transaction.objects.create(
        store=store,
        type="debt_out",      # 'tx_type' EMAS
        amount=amount,
        created_at=timezone.now(),
        # agar sizda "counterparty/name" maydoni yo‘q bo‘lsa, name'ni yubormang
    )

def debt_pay(store, seller, amount: Decimal):
    return Transaction.objects.create(
        store=store,
        type="debt_pay",
        amount=amount,
        created_at=timezone.now(),
    )

# tests/factories.py

import uuid
from decimal import Decimal
from django.utils import timezone


from inventory.models import Product, Brand, ModelName
from sales.models import Transaction  # agar sizda shunday model bo‘lsa

# Mavjud helperlaringiz: make_store, make_seller, make_owner, make_phone, debt_out, debt_pay ...
# Ularga tegmang, faqat yetishmayotganlarini qo‘shamiz.

def sale(store, seller, product: Product, total: Decimal,
         cash: Decimal | None = None,
         card: Decimal | None = None,
         transfer: Decimal | None = None,
         approved: bool = True):
    # Faqat sizda bor maydonlarni ishlating:
    tx = Transaction.objects.create(
        store=store,
        product=product,
        type="sale",          # agar sizda nomi boshqacha bo‘lsa moslang: masalan kind="sale"
        amount=total,         # agar maydon nomi 'total' bo‘lsa, shuni yozing
        created_at=timezone.now(),
    )

    # Product holatini yangilash
    try:
        product.status = "sold"          # sizda enum bo‘lsa moslang
        product.sale_price = total       # maydon bo‘lmasa o‘chirib tashlang
        product.save(update_fields=["status", "sale_price"])
    except Exception:
        pass

    return tx

def expense(store, seller, product, amount: Decimal, note: str = ""):
    return Transaction.objects.create(
        store=store,
        type="expense",
        product=product,
        amount=amount,
        created_at=timezone.now(),
    )

def consignment_due(store, seller, product, payout: Decimal):
    return Transaction.objects.create(
        store=store,
        type="consignment_due",
        product=product,
        amount=payout,
        created_at=timezone.now(),
    )

