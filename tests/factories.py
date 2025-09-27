from decimal import Decimal
from django.utils import timezone as dj_tz
from accounts.models import User, Store
from inventory.models import Product
from sales.models import Transaction, SellerCommission, ConsignmentDue
from reference.models import Brand, ModelName, Color

def make_store(name="Store A"):
    return Store.objects.create(name=name)

def make_owner(username="owner"):
    return User.objects.create_user(username=username, password="x", is_owner=True)

def make_seller(store, username="seller"):
    u = User.objects.create_user(username=username, password="x", is_owner=False)
    u.store = store
    u.save(update_fields=["store"])
    return u

def make_phone(store, imei="111111111111111", ownership="owned", purchase=Decimal("300"), brand="Apple", model="iPhone X"):
    b = Brand.objects.get_or_create(name=brand)[0]
    m = ModelName.objects.get_or_create(brand=b, name=model)[0]
    c = Color.objects.get_or_create(name="Black")[0]
    return Product.objects.create(
        store=store, brand=b, model=m, color=c,
        imei_full=imei, ownership=ownership,
        purchase_price=purchase if ownership=="owned" else None,
        consignment_price=purchase if ownership!="owned" else None,
        status="available",
    )

def sale(store, seller, product, total=Decimal("500"), cash=Decimal("500"), card=Decimal("0")):
    # sotuv — darhol approved
    cost = product.calc_cost()
    tx = Transaction.objects.create(
        type="sale", store=store, seller=seller, created_by=seller,
        product=product, amount=total, cash_amount=cash, card_amount=card,
        payment_type="cash" if cash>0 and card==0 else ("card" if card>0 and cash==0 else "mixed"),
        cost=cost, profit=(total - cost),
        is_approved=True, approved_by=seller, approved_at=dj_tz.now()
    )
    product.status="sold"; product.sold_at=dj_tz.now()
    product.save(update_fields=["status","sold_at"])
    # komissiya bo'lmasa — signal fallbackini tekshirishga yordam: safety-create
    if not hasattr(tx, "commission"):
        SellerCommission.objects.create(transaction=tx, seller=seller, amount=Decimal("5.00"))
    return tx

def debt_out(store, seller, amount, name="Customer", phone=""):
    return Transaction.objects.create(
        type="debt_out", store=store, seller=seller, created_by=seller,
        amount=amount, debtor_name=name, debtor_phone=phone, debtor_group=dj_tz.now().isoformat(),
        is_approved=True, approved_by=seller, approved_at=dj_tz.now()
    )

def debt_pay(store, seller, group, amount, cash=None, card=None):
    cash = cash if cash is not None else amount
    card = card if card is not None else Decimal("0")
    return Transaction.objects.create(
        type="debt_pay", store=store, seller=seller, created_by=seller,
        amount=amount, debtor_group=group, payment_type="cash" if card==0 else ("card" if cash==0 else "mixed"),
        cash_amount=cash, card_amount=card,
        is_approved=True, approved_by=seller, approved_at=dj_tz.now()
    )

def expense(store, seller, product, amount):
    return Transaction.objects.create(
        type="expense", store=store, seller=seller, created_by=seller,
        amount=amount, product=product,
        is_approved=True, approved_by=seller, approved_at=dj_tz.now()
    )

def consignment_due(store, seller, product, base):
    return ConsignmentDue.objects.create(
        store=store, product=product, base_amount=base,
        created_by=seller, is_approved=True, approved_by=seller, approved_at=dj_tz.now()
    )
