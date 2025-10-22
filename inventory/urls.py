# inventory/urls.py
from django.urls import path
from .views import product_create, move_to_repair, mark_available, batch_intake_new, export_products_csv, \
    export_sales_csv, export_products_pdf, import_excel, inventory_search, product_detail, product_edit, \
    my_acquisitions, my_stats, product_sold_list, product_received_list, ap_consignment_batch_list, \
    ap_consignment_batch_pay

urlpatterns = [
    path("products/received/", product_received_list, name="product_received_list"),  # <-- YANGI
    path("products/sold/", product_sold_list, name="product_sold_list"),              # <-- YANGI
    path("products/new/", product_create, name="product_create"),
    path("products/batch/new/", batch_intake_new, name="batch_intake_new"),
    path("products/<int:pk>/to-repair/", move_to_repair, name="product_to_repair"),
    path("products/<int:pk>/to-available/", mark_available, name="product_to_available"),

    path("export/products.csv", export_products_csv, name="export_products_csv"),
    path("export/sales.csv", export_sales_csv, name="export_sales_csv"),
    path("exp"
         "ort/products.pdf", export_products_pdf, name="export_products_pdf"),

    path("products/import-excel/", import_excel, name="import_excel"),
    path("products/<int:pk>/edit/", product_edit, name="product_edit"),

    path("my-acquisitions/", my_acquisitions, name="my_acquisitions"),
    path("my-stats/", my_stats, name="my_stats"),

    path("search/", inventory_search, name="inventory_search"),
    path("product/<int:pk>/", product_detail, name="product_detail"),

    path("consignment/ap/batches/", ap_consignment_batch_list, name="ap_consignment_batch_list"),
    path("consignment/ap/batches/<int:batch_id>/pay/", ap_consignment_batch_pay, name="ap_consignment_batch_pay"),
]