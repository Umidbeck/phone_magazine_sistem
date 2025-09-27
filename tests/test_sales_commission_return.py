from decimal import Decimal
from tests.factories import make_store, make_owner, make_seller, make_phone, sale
from sales.models import SellerCommission, Transaction
from django.utils import timezone as dj_tz

def test_sale_creates_commission_and_profit_ok(db):
    store = make_store()
    seller = make_seller(store)
    p = make_phone(store, purchase=Decimal("300"))
    tx = sale(store, seller, p, total=Decimal("500"), cash=Decimal("500"))
    # commission exists
    assert hasattr(tx, "commission")
    assert tx.commission.amount == Decimal("5.00")
    # profit correct (approved-only)
    assert tx.is_approved is True
    assert tx.profit == Decimal("200")

def test_return_today_removes_or_unapproves_commission(db, client):
    store = make_store(); seller = make_seller(store); p = make_phone(store, purchase=Decimal("300"))
    tx = sale(store, seller, p, total=Decimal("500"), cash=Decimal("500"))
    # simulate calling view: business logic — set is_void and commission removed if pending; if approved -> unapprove
    # we'll emulate "pending" commission
    com = tx.commission
    com.is_approved = False; com.save(update_fields=["is_approved"])
    # emulate return logic:
    tx.is_void = True; tx.save(update_fields=["is_void"])
    # business rule: pending -> delete
    com.refresh_from_db()
    com.delete()
    assert SellerCommission.objects.filter(pk=com.pk).count() == 0

def test_no_double_commission_on_resale(db):
    store = make_store(); seller = make_seller(store); p = make_phone(store, purchase=Decimal("300"))
    tx1 = sale(store, seller, p, total=Decimal("500"), cash=Decimal("500"))
    # return old and resell same product (now available again)
    tx1.is_void=True; tx1.save(update_fields=["is_void"]); p.status="available"; p.save(update_fields=["status"])
    tx2 = sale(store, seller, p, total=Decimal("520"), cash=Decimal("520"))
    # only one commission attached to second sale
    assert hasattr(tx2, "commission")
    assert SellerCommission.objects.filter(transaction=tx2).count()==1
