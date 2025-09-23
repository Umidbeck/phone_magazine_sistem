from django.urls import path
from .views import product_list, product_create, move_to_repair, mark_available, batch_intake_new, export_products_csv, \
    export_sales_csv, export_products_pdf, import_excel, home_feed, inventory_search, product_detail

urlpatterns = [
    path("products/", product_list, name="product_list"),
    path("products/new/", product_create, name="product_create"),
    path("products/batch/new/", batch_intake_new, name="batch_intake_new"),
    path("products/<int:pk>/to-repair/", move_to_repair, name="product_to_repair"),
    path("products/<int:pk>/to-available/", mark_available, name="product_to_available"),

    path("export/products.csv", export_products_csv, name="export_products_csv"),
    path("export/sales.csv", export_sales_csv, name="export_sales_csv"),
    path("export/products.pdf", export_products_pdf, name="export_products_pdf"),

    path("products/import-excel/", import_excel, name="import_excel"),

    path("feed/", home_feed, name="home_feed"),
    path("search/", inventory_search, name="inventory_search"),
    path("product/<int:pk>/", product_detail, name="product_detail"),
]
