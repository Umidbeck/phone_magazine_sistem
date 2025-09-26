from django.urls import path
from .views import sell_view, expense_create, debt_new, debt_list, debt_pay, consignment_list, consignment_payout, \
    commission_mark_paid, commissions_list, expenses_list, expense_approve, debt_approve, debt_reject, cons_due_approve, \
    cons_due_reject, commission_approve, commission_reject, expense_reject, sell_installment, sale_return, \
    sale_return_by_tx, sale_return_by_product, debt_new_simple, consignment_new, consignment_approve, \
    consignment_reject, expense_unapprove, commission_update_amount

urlpatterns = [
    path("sell/", sell_view, name="sell"),
    path("sell/installment/", sell_installment, name="sell_installment"),
    path("sale/<int:tx_id>/return/", sale_return, name="sale_return"),

    path("expenses/new/", expense_create, name="expense_new"),
    path("expenses/", expenses_list, name="expenses_list"),
    path("expenses/<int:tx_id>/approve/", expense_approve, name="expense_approve"),
    path("expenses/<int:tx_id>/reject/", expense_reject, name="expense_reject"),
    path("expenses/<int:tx_id>/unapprove/", expense_unapprove, name="expense_unapprove"),

    path("debts/", debt_list, name="debt_list"),
    path("debts/new/", debt_new, name="debt_new"),
    path("debts/<int:tx_id>/approve/", debt_approve, name="debt_approve"),
    path("debts/<int:tx_id>/reject/", debt_reject, name="debt_reject"),
    path("debts/new-simple/", debt_new_simple, name="debt_new_simple"),
    path("debts/<uuid:group>/pay/", debt_pay, name="debt_pay"),

    path("consignment/", consignment_list, name="consignment_list"),
    path("consignment/<int:product_id>/payout/", consignment_payout, name="consignment_payout"),
    path("consignment/due/<int:product_id>/approve/", cons_due_approve, name="cons_due_approve"),
    path("consignment/due/<int:product_id>/reject/", cons_due_reject, name="cons_due_reject"),
    path("consignment/new/", consignment_new, name="consignment_new"),

    path("consignment/payout/<int:tx_id>/approve/", consignment_approve, name="consignment_approve"),
    path("consignment/payout/<int:tx_id>/reject/", consignment_reject, name="consignment_reject"),


    path("commissions/", commissions_list, name="commissions_list"),
    path("commissions/<int:commission_id>/mark-paid/", commission_mark_paid, name="commission_mark_paid"),
    path("commissions/<int:commission_id>/approve/", commission_approve, name="commission_approve"),
    path("commissions/<int:commission_id>/reject/", commission_reject, name="commission_reject"),
    path("commissions/<int:commission_id>/update-amount/", commission_update_amount, name="commission_update_amount"),

    path("sale/<int:tx_id>/return/", sale_return_by_tx, name="sale_return_tx"),
    path("sale/product/<int:product_id>/return/", sale_return_by_product, name="sale_return_product"),
]

