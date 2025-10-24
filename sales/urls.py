# sales/urls.py - MUKAMMAL URL CONFIGURATION
"""
Sales URL routing

Barcha endpoint'lar:
- /sales/sell/ - Sotuv
- /sales/expenses/ - Rashodlar
- /sales/debts/ - Qarzlar
- /sales/commissions/ - Komissiyalar
- /sales/consignment/ - Konsignatsiya
"""
from django.urls import path

from sales.views import sell_view, sell_installment, sale_return_by_tx, sale_return_by_product, expense_create, \
    expenses_list, expense_approve, expense_reject, expense_unapprove, debt_list, debt_new, debt_new_simple, debt_pay, \
    commissions_list, commission_reject, commission_approve, commission_mark_paid, commission_update_amount, \
    consignment_list, consignment_payout, consignment_new, consignment_approve, consignment_reject, cons_due_approve, \
    cons_due_reject

app_name = "sales"

urlpatterns = [
    # ============================================
    # SELL (Sotuv)
    # ============================================
    path("sell/", sell_view, name="sell"),
    path("sell/installment/", sell_installment, name="sell_installment"),
    path("sale/<int:tx_id>/return/", sale_return_by_tx, name="sale_return_tx"),
    path("sale/product/<int:product_id>/return/", sale_return_by_product, name="sale_return_product"),

    # ============================================
    # EXPENSES (Rashodlar)
    # ============================================
    path("expenses/new/", expense_create, name="expense_new"),
    path("expenses/", expenses_list, name="expenses_list"),
    path("expenses/<int:tx_id>/approve/", expense_approve, name="expense_approve"),
    path("expenses/<int:tx_id>/reject/", expense_reject, name="expense_reject"),
    path("expenses/<int:tx_id>/unapprove/", expense_unapprove, name="expense_unapprove"),

    # ============================================
    # DEBTS (Qarzlar)
    # ============================================
    path("debts/", debt_list, name="debt_list"),
    path("debts/new/", debt_new, name="debt_new"),
    path("debts/new-simple/", debt_new_simple, name="debt_new_simple"),
    path("debts/<uuid:group>/pay/", debt_pay, name="debt_pay"),

    # ============================================
    # COMMISSIONS (Komissiyalar)
    # ============================================
    path("commissions/", commissions_list, name="commissions_list"),
    path("commissions/<int:commission_id>/approve/", commission_approve, name="commission_approve"),
    path("commissions/<int:commission_id>/reject/", commission_reject, name="commission_reject"),
    path("commissions/<int:commission_id>/mark-paid/", commission_mark_paid, name="commission_mark_paid"),
    path("commissions/<int:pk>/update-amount/", commission_update_amount, name="commission_update_amount"),

    # ============================================
    # CONSIGNMENT (Konsignatsiya)
    # ============================================
    path("consignment/", consignment_list, name="consignment_list"),
    path("consignment/<int:product_id>/payout/", consignment_payout, name="consignment_payout"),
    path("consignment/new/", consignment_new, name="consignment_new"),
    path("consignment/payout/<int:tx_id>/approve/", consignment_approve, name="consignment_approve"),
    path("consignment/payout/<int:tx_id>/reject/", consignment_reject, name="consignment_reject"),
    path("consignment/due/<int:product_id>/approve/", cons_due_approve, name="cons_due_approve"),
    path("consignment/due/<int:product_id>/reject/", cons_due_reject, name="cons_due_reject"),
]
