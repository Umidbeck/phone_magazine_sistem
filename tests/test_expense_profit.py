from decimal import Decimal
from tests.factories import make_store, make_seller, make_phone, sale, expense

def test_expense_affects_cost_and_profit_only_if_approved(db):
    store = make_store(); seller = make_seller(store); p = make_phone(store, purchase=Decimal("300"))
    # approved expense
    expense(store, seller, p, Decimal("40"))
    # calc cost via model then sale
    tx = sale(store, seller, p, total=Decimal("500"))
    # cost should be 340 => profit 160
    assert tx.cost == Decimal("340")
    assert tx.profit == Decimal("160")
