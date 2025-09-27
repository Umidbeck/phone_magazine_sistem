from decimal import Decimal
from tests.factories import make_store, make_seller, make_phone, sale, consignment_due
from sales.models import ConsignmentDue

def test_consignment_due_created_and_paid_flow(db):
    store = make_store(); seller = make_seller(store)
    p = make_phone(store, ownership="consignment", purchase=Decimal("350"))
    tx = sale(store, seller, p, total=Decimal("520"))
    # due yaratilgan bo'lishi kerak (signal/view safety)
    assert ConsignmentDue.objects.filter(product=p).exists()
    due = ConsignmentDue.objects.get(product=p)
    assert due.base_amount == Decimal("350")
    assert due.is_approved is True  # biz siyosatni approved bo'lganda kassaga kiritamiz (test ehtiyojiga moslashtiring)
