# inventory/views.py
import csv
from decimal import Decimal

import pandas as pd
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Right
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.translation import gettext as _
from weasyprint import HTML

from reference.models import Brand, ModelName, Color
from sales.models import Transaction
from .forms import (
    ProductCreateForm,
    BatchIntakeForm,
    BatchItemForm,
    ExcelImportForm,
)
from .models import Product, ProductImage
from .search_utils import product_search_queryset


def digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())



@login_required
def product_list(request):
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    include_archived = (request.GET.get("archived") == "1")
    try:
        store_id = int(request.GET.get("store") or 0) or None
    except ValueError:
        store_id = None

    base_qs = Product.objects.select_related("brand", "model", "store").order_by("-created_at")

    qs = product_search_queryset(
        request.user,
        q,
        base_qs=base_qs,
        for_sale=False,
        include_archived=include_archived,
        store_id=store_id,
    )

    if status:
        qs = qs.filter(status=status)

    products = list(qs[:100])
    ctx = {
        "products": products,
        "q": q,
        "status": status,
        "store_id": store_id,
        "include_archived": include_archived,
        "result_count": qs.count(),
    }
    return render(request, "inventory/product_list.html", ctx)


@login_required
def product_create(request):
    if request.method == "POST":
        form = ProductCreateForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                p: Product = form.save(commit=False)

                if request.user.is_owner:
                    # OWNER: formdan store kelishi shart
                    if not p.store_id:
                        messages.error(request, _("Select a store."))
                        return render(request, "inventory/product_create.html", {"form": form})
                else:
                    # SELLER: agar user.store bor — majburan o‘shani yozamiz
                    if getattr(request.user, "store_id", None):
                        p.store = request.user.store
                    else:
                        # Sellerda store yo‘q — formdan tanlaganini qoldiramiz (fallback)
                        if not p.store_id:
                            messages.error(request, _("Select a store."))
                            return render(request, "inventory/product_create.html", {"form": form})

                p.created_by = request.user
                p.save()
                if form.is_valid():
                    with transaction.atomic():
                        p: Product = form.save(commit=False)
                        ...
                        p.created_by = request.user
                        p.save()

                        # YANGI: rasmlarni saqlash
                        def _save_images(files, kind, set_primary=False):
                            first = True
                            for f in files:
                                pi = ProductImage.objects.create(product=p, image=f, kind=kind)
                                if set_primary and first:
                                    pi.is_primary = True
                                    pi.save(update_fields=["is_primary"])
                                    first = False

                        _save_images(request.FILES.getlist("doc_images"), "doc", set_primary=False)
                        _save_images(request.FILES.getlist("cond_images"), "cond",
                                     set_primary=True)  # birinchisi primary
                        _save_images(request.FILES.getlist("images"), "other", set_primary=False)

                    messages.success(request, _("Product added successfully."))
                    return redirect("product_create")

            messages.success(request, _("Product added successfully."))
            return redirect("product_create")
        else:
            # xatolarni ko‘rinadigan qilish
            messages.error(request, "; ".join([" ".join(v) for v in form.errors.values()]))
    else:
        form = ProductCreateForm(user=request.user)

    return render(request, "inventory/product_create.html", {"form": form})




@login_required
def move_to_repair(request, pk):
    if request.method != "POST":
        return redirect("product_list")
    qs = Product.objects.all()
    if not request.user.is_owner:
        qs = qs.filter(store=request.user.store_id)
    p = get_object_or_404(qs, pk=pk)
    p.status = "on_repair"
    p.save(update_fields=["status"])
    messages.info(request, _("Moved to repair."))
    return redirect("product_list")


@login_required
def mark_available(request, pk):
    if request.method != "POST":
        return redirect("product_list")
    qs = Product.objects.all()
    if not request.user.is_owner:
        qs = qs.filter(store=request.user.store_id)
    p = get_object_or_404(qs, pk=pk)
    p.status = "available"
    p.save(update_fields=["status"])
    messages.success(request, _("Marked available."))
    return redirect("product_list")


@login_required
def batch_intake_new(request):
    from django.forms import formset_factory

    BatchFormset = formset_factory(BatchItemForm, extra=0, min_num=1, validate_min=True)

    if request.method == "POST":
        intake_form = BatchIntakeForm(request.POST, user=request.user)
        formset = BatchFormset(request.POST)
        if intake_form.is_valid() and formset.is_valid():
            with transaction.atomic():
                intake = intake_form.save(commit=False)
                if not request.user.is_owner:
                    intake.store = request.user.store
                intake.created_by = request.user
                intake.save()

                created = 0
                for f in formset:
                    cd = f.cleaned_data
                    if not cd or not cd.get("imei_full"):
                        continue
                    p = Product(
                        store=intake.store,
                        batch=intake,
                        brand=cd.get("brand"),
                        model=cd.get("model"),
                        color=cd.get("color"),
                        year=cd.get("year") or None,
                        imei_full=cd.get("imei_full") or "",
                        has_documents=cd.get("has_documents") or False,
                        is_new=cd.get("is_new") or False,
                        ownership=cd.get("ownership"),
                        purchase_price=cd.get("purchase_price") or 0,
                        consignment_price=cd.get("consignment_price") or 0,
                        created_by=request.user,
                    )
                    p.save()
                    created += 1
            messages.success(request, _(f"Batch saved. Created: {created} items."))
            return redirect("product_list")
        else:
            messages.error(request, _("Please fix errors in the batch."))
    else:
        rows = int(request.GET.get("rows", 10))
        intake_form = BatchIntakeForm(user=request.user, initial={"rows": rows})
        from django.forms import formset_factory

        formset = formset_factory(BatchItemForm, extra=rows)()

    return render(
        request,
        "inventory/batch_intake_form.html",
        {"intake_form": intake_form, "formset": formset},
    )


@login_required
def export_products_csv(request):
    qs = Product.objects.select_related("brand", "model", "store").order_by("-created_at")
    if not request.user.is_owner:
        qs = qs.filter(store=request.user.store_id)
    if request.GET.get("archived") != "1":
        qs = qs.filter(is_archived=False)

    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="products.csv"'
    w = csv.writer(resp)
    w.writerow(
        ["Store", "Brand", "Model", "Color", "IMEI", "Ownership", "Purchase", "Consignment", "Status", "Created"]
    )
    for p in qs:
        w.writerow(
            [
                p.store.name,
                p.brand.name,
                p.model.name,
                (p.color.name if p.color else ""),
                p.imei_full,
                p.ownership,
                p.purchase_price,
                p.consignment_price,
                p.status,
                p.created_at.strftime("%Y-%m-%d %H:%M"),
            ]
        )
    return resp


@login_required
def export_sales_csv(request):
    qs = (
        Transaction.objects.select_related("store", "product", "seller")
        .filter(type="sale")
        .order_by("-created_at")
    )
    if not request.user.is_owner:
        qs = qs.filter(store=request.user.store_id)

    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="sales.csv"'
    w = csv.writer(resp)
    w.writerow(["Date", "Store", "Seller", "IMEI", "Amount", "Cost", "Profit", "Payment"])
    for t in qs:
        w.writerow(
            [
                t.created_at.strftime("%Y-%m-%d %H:%M"),
                (t.store.name if t.store else ""),
                t.seller.username,
                (t.product.imei_full if t.product_id else ""),
                t.amount,
                t.cost,
                t.profit,
                t.payment_type,
            ]
        )
    return resp


@login_required
def export_products_pdf(request):
    qs = Product.objects.select_related("brand", "model", "store").order_by("-created_at")[:300]
    if not request.user.is_owner:
        qs = qs.filter(store=request.user.store_id)
    if request.GET.get("archived") != "1":
        qs = qs.filter(is_archived=False)

    html_str = render_to_string("inventory/export_products_pdf.html", {"products": qs})
    pdf = HTML(string=html_str, base_url=request.build_absolute_uri("/")).write_pdf()
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = 'inline; filename="products.pdf"'
    return resp


@login_required
def import_excel(request):
    if request.method == "POST":
        form = ExcelImportForm(request.POST, request.FILES)
        if form.is_valid():
            store = form.cleaned_data["store"]
            if not request.user.is_owner and store != request.user.store:
                messages.error(request, _("You can only import into your own store."))
                return redirect("import_excel")

            f = request.FILES["file"]
            try:
                df = pd.read_excel(f, dtype=str)
            except Exception as e:
                messages.error(request, _("Failed to read Excel: ") + str(e))
                return redirect("import_excel")

            # mapping
            bcol = (form.cleaned_data["brand_col"] or "").strip().upper()
            mcol = (form.cleaned_data["model_col"] or "").strip().upper()
            ccol = (form.cleaned_data["color_col"] or "").strip().upper()
            icol = (form.cleaned_data["imei_col"] or "").strip().upper()
            pcol = (form.cleaned_data["price_col"] or "").strip().upper()
            own = form.cleaned_data["ownership"]

            df.columns = [str(c).strip().upper() for c in df.columns]

            created, skipped = 0, 0
            for _, row in df.iterrows():
                brand_name = (row.get(bcol) or "").strip().title() if bcol in df.columns else ""
                model_name = (row.get(mcol) or "").strip().title() if mcol in df.columns else ""
                color_name = (row.get(ccol) or "").strip().title() if ccol in df.columns else ""
                imei_full = "".join(ch for ch in (row.get(icol) or "") if ch.isdigit()) if icol in df.columns else ""
                price_val = row.get(pcol) if pcol in df.columns else ""

                if not imei_full:
                    skipped += 1
                    continue

                brand = Brand.objects.filter(name=brand_name).first() if brand_name else None
                if brand_name and not brand:
                    brand = Brand.objects.create(name=brand_name, is_active=True)

                model = None
                if model_name and brand:
                    model = ModelName.objects.filter(brand=brand, name=model_name).first()
                    if not model:
                        model = ModelName.objects.create(brand=brand, name=model_name, is_active=True)

                color = None
                if color_name:
                    color = Color.objects.filter(name=color_name).first()
                    if not color:
                        color = Color.objects.create(name=color_name, is_active=True)

                try:
                    price = Decimal(str(price_val).replace(" ", "").replace(",", "."))
                except Exception:
                    price = Decimal("0")

                kwargs = dict(
                    store=store,
                    brand=brand,
                    model=model,
                    color=color,
                    imei_full=imei_full,
                    ownership=own,
                    created_by=request.user,
                )
                if own == "owned":
                    kwargs["purchase_price"] = price
                else:
                    kwargs["consignment_price"] = price

                try:
                    Product.objects.create(**kwargs)
                    created += 1
                except Exception:
                    skipped += 1

            messages.success(request, _(f"Import finished. Created: {created}, Skipped: {skipped}"))
            return redirect("product_list")
    else:
        initial_store = request.user.store if not request.user.is_owner else None
        form = ExcelImportForm(initial={"store": initial_store})
    return render(request, "inventory/import_excel.html", {"form": form})
