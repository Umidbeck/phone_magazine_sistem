from django.urls import path
from .views import sell_view, expense_create, debt_new, debt_list, debt_pay, consignment_list, consignment_payout

urlpatterns = [
    path("sell/", sell_view, name="sell"),
    path("expenses/new/", expense_create, name="expense_new"),

    # Debt oqimlari
    path("debts/", debt_list, name="debt_list"),
    path("debts/new/", debt_new, name="debt_new"),
    path("debts/<int:debtor_id>/pay/", debt_pay, name="debt_pay"),

    # Consignment payout
    path("consignment/", consignment_list, name="consignment_list"),
    path("consignment/<int:product_id>/payout/", consignment_payout, name="consignment_payout"),
]
