# inventory/views.py
import csv
import datetime
import io
import json
from decimal import Decimal, InvalidOperation

import pandas as pd
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Model, Sum, When, Case, F, OuterRef, Exists, Count
from django.db.models.functions import Right, Coalesce, TruncDate
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.dateparse import parse_date
from django.utils.safestring import mark_safe
from django.utils.timezone import make_aware
from django.utils.translation import gettext as _
from openpyxl import load_workbook
from weasyprint import HTML
from django.utils.translation import gettext_lazy as _

from accounts.models import Store, User
from reference.models import Brand, ModelName, Color
from sales.models import Transaction, SellerCommission
from sales.services import calc_product_cost
from sales.views import _seller_only
from .forms import (
    ProductCreateForm,
    BatchIntakeForm,
    BatchItemForm,
    ExcelImportForm, ImportExcelForm, ProductImageFormSet, ProductForm, ProductImageForm,
)
from .mixins import can_edit_product
from .models import Product, ProductImage
from .search_utils import product_search_queryset

from django.utils import timezone as dj_tz


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

    qs = (Product.objects
          .select_related("brand", "model", "store")
          .filter(status="sold")
          .order_by("-sold_at"))

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
    if not getattr(request.user, "is_owner", False):
        qs = qs.filter(store_id=request.user.store_id)

    installment_exists = Transaction.objects.filter(
        type="debt_out", product_id=OuterRef("pk"), is_void=False
    )
    qs = qs.annotate(is_installment=Exists(installment_exists))

    # Ikki ro‘yxat
    installment_rows = list(qs.filter(is_installment=True)[:500])
    full_rows = list(qs.filter(is_installment=False)[:500])

    return render(request, "inventory/product_sold_list.html", {
        "installment_rows": installment_rows,
        "full_rows": full_rows,
    })


# inventory/views.py -> product_create()
# inventory/views.py
def _can_edit(user, product=None):
    if not user.is_authenticated:
        return False
    if getattr(user, "is_owner", False):
        return True
    return product is None or user.store_id == getattr(product, "store_id", None)

@login_required
@transaction.atomic
def product_create(request, pk=None):
    instance = get_object_or_404(Product.objects.select_related("store", "brand", "model"), pk=pk) if pk else None
    if not _can_edit(request.user, instance):
        messages.error(request, "Ushbu mahsulotni tahrirlashga ruxsatingiz yo‘q.")
        return redirect("inventory:product_list")

    if request.method == "POST":
        pform = ProductForm(request.POST, request.FILES, instance=instance, user=request.user)
        if instance:
            existing_count = ProductImage.objects.filter(product=instance).count()
        else:
            existing_count = 0
        if "images" in request.FILES:
            # Agar foydalanuvchi bir nechta fayl tanlasa ham — getlist bilan olamiz
            files = request.FILES.getlist("images")
        else:
            files = []
        imgform = ProductImageForm(request.POST, request.FILES)

        # Server tomoni limit tekshiruvi (existing + yangi <= 7)
        total_after = existing_count + len(files)
        if total_after > 7:
            imgform.add_error("images", f"Umumiy rasm soni 7 tadan oshmasin. Hozir {total_after} ta bo‘lib qolyapti.")

        if pform.is_valid() and imgform.is_valid():
            # Saqlash
            product = pform.save(commit=False)
            if not getattr(request.user, "is_owner", False):
                product.store = request.user.store  # disabled bo‘lgani uchun POSTda kelmaydi
            if not product.pk:
                product.created_by = request.user
            product.save()
            pform.save_m2m()

            # Rasmlar: ixtiyoriy, lekin 7 ta limit
            for f in files:
                ProductImage.objects.create(product=product, image=f)

            messages.success(request, "Ma’lumot saqlandi.")
            return redirect("inventory:product_detail", pk=product.pk)
        else:
            messages.error(request, "Xatolarni to‘g‘rilang.")
    else:
        initial = {}
        if not getattr(request.user, "is_owner", False) and getattr(request.user, "store_id", None):
            initial["store"] = request.user.store_id
        pform = ProductForm(instance=instance, user=request.user, initial=initial)
        imgform = ProductImageForm()

    return render(request, "inventory/product_form.html", {
        "p": instance,
        "is_edit": bool(instance),
        "form": pform,
        "imgform": imgform,
        "existing_images": ProductImage.objects.filter(product=instance) if instance else [],
    })



@login_required
def move_to_repair(request, pk):
    p = get_object_or_404(Product, pk=pk)
    if not (getattr(request.user, "is_owner", False) or p.created_by_id == request.user.id):
        messages.error(request, _("Ushbu mahsulot holatini o‘zgartira olmaysiz."))
        return redirect("inventory:product_detail", pk=p.id)
    if p.status != "available":
        messages.error(request, _("Faqat 'available' holatidagi mahsulot ta’mirga o‘tkaziladi."))
        return redirect("inventory:product_detail", pk=p.id)
    p.status = "on_repair"
    p.save(update_fields=["status"])
    messages.success(request, _("Ta’mirga o‘tkazildi."))
    return redirect("inventory:product_detail", pk=p.id)


@login_required
def mark_available(request, pk):
    p = get_object_or_404(Product, pk=pk)
    if not (getattr(request.user, "is_owner", False) or p.created_by_id == request.user.id):
        messages.error(request, _("Ushbu mahsulot holatini o‘zgartira olmaysiz."))
        return redirect("inventory:product_detail", pk=p.id)
    if p.status != "on_repair":
        messages.error(request, _("Faqat 'on_repair' holatidan qaytarish mumkin."))
        return redirect("inventory:product_detail", pk=p.id)
    p.status = "available"
    p.save(update_fields=["status"])
    messages.success(request, _("Available holatiga qaytarildi."))
    return redirect("inventory:product_detail", pk=p.id)


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

def _parse_decimal(val):
    if not val: return None
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError):
        return None

def _parse_date(val):
    if not val: return None
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except ValueError:
        return None

@login_required
def home_feed(request):
    """
    Instagram-uslub feed: kartalar grid + to‘liq filtrlar.
    """
    qs = Product.objects.select_related("brand","model","store").prefetch_related("images")\
                        .filter(is_archived=False).order_by("-created_at")

    # Seller faqat o‘z do‘konini ko‘radi
    if not request.user.is_owner:
        qs = qs.filter(store_id=request.user.store_id)

    # ---- Filtrlar ----
    store_id = request.GET.get("store_id") or ""
    brand_id = request.GET.get("brand") or ""
    model_id = request.GET.get("model") or ""
    status = request.GET.get("status") or ""  # available/on_repair/sold
    is_new = request.GET.get("is_new")        # "1" bo‘lsa True
    has_docs = request.GET.get("has_documents")
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))
    price_min = _parse_decimal(request.GET.get("price_min"))
    price_max = _parse_decimal(request.GET.get("price_max"))

    if store_id:
        if request.user.is_owner:
            qs = qs.filter(store_id=store_id)
        else:
            # seller boshqa do‘kon kiritolmaydi
            qs = qs.filter(store_id=request.user.store_id)

    if brand_id:
        qs = qs.filter(brand_id=brand_id)
    if model_id:
        qs = qs.filter(model_id=model_id)
    if status in ("available","on_repair","sold"):
        qs = qs.filter(status=status)
    if is_new == "1":
        qs = qs.filter(is_new=True)
    if has_docs == "1":
        qs = qs.filter(has_documents=True)

    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    # Narx: purchase_price yoki consignment_price
    qs = qs.annotate(price=Coalesce("purchase_price", "consignment_price"))
    if price_min is not None:
        qs = qs.filter(price__gte=price_min)
    if price_max is not None:
        qs = qs.filter(price__lte=price_max)

    paginator = Paginator(qs, 18)
    page = paginator.get_page(request.GET.get("page"))

    stores = Store.objects.filter(is_active=True).order_by("name")
    brands = Brand.objects.filter(is_active=True).order_by("name")
    models = ModelName.objects.filter(is_active=True).order_by("brand__name","name")

    ctx = {
        "page": page,
        "stores": stores, "brands": brands, "models": models,
        "store_id": store_id, "brand_id": brand_id, "model_id": model_id,
        "status": status, "is_new_val": is_new == "1", "has_docs_val": has_docs == "1",
        "date_from": date_from, "date_to": date_to,
        "price_min": request.GET.get("price_min") or "", "price_max": request.GET.get("price_max") or "",
    }
    return render(request, "inventory/home_feed.html", ctx)

@login_required
def inventory_search(request):
    q = (request.GET.get("q") or "").strip()
    store_id = request.GET.get("store_id") or ""
    brand_id = request.GET.get("brand") or ""
    model_id = request.GET.get("model") or ""
    status = request.GET.get("status") or ""
    ownership = request.GET.get("ownership") or ""
    date_from = request.GET.get("date_from") or ""
    date_to   = request.GET.get("date_to") or ""
    price_min = request.GET.get("price_min") or ""
    price_max = request.GET.get("price_max") or ""
    is_new_val = True if request.GET.get("is_new") == "1" else False
    has_docs_val = True if request.GET.get("has_documents") == "1" else False

    base_qs = Product.objects.select_related("brand","model","store").order_by("-created_at")
    if q:
        qs = product_search_queryset(request.user, q, base_qs=base_qs, for_sale=False, include_archived=False, store_id=None)
    else:
        qs = base_qs
        if not request.user.is_owner:
            qs = qs.filter(store_id=request.user.store_id)

    if store_id:
        qs = qs.filter(store_id=store_id if request.user.is_owner else request.user.store_id)
    if brand_id:
        qs = qs.filter(brand_id=brand_id)
    if model_id:
        qs = qs.filter(model_id=model_id)
    if status in ("available","on_repair","sold"):
        qs = qs.filter(status=status)
    if ownership in ("owned","consignment"):
        qs = qs.filter(ownership=ownership)

    def _pdate(s):
        try: return datetime.strptime(s, "%Y-%m-%d").date()
        except: return None
    df = _pdate(date_from); dt = _pdate(date_to)
    if df: qs = qs.filter(created_at__date__gte=df)
    if dt: qs = qs.filter(created_at__date__lte=dt)

    # price va flaglar
    qs = qs.annotate(price_for_filter=Case(
        When(ownership="owned", then=F("purchase_price")),
        When(ownership="consignment", then=F("consignment_price")),
        default=F("purchase_price"),
    ))
    if price_min: qs = qs.filter(price_for_filter__gte=price_min)
    if price_max: qs = qs.filter(price_for_filter__lte=price_max)
    if is_new_val: qs = qs.filter(is_new=True)
    if has_docs_val: qs = qs.filter(has_documents=True)

    stores = Store.objects.filter(is_active=True).order_by("name")
    brands = Brand.objects.filter(is_active=True).order_by("name")
    models = ModelName.objects.filter(is_active=True).order_by("brand__name","name")

    ctx = {
        "q": q, "results": list(qs[:200]),
        "stores": stores, "brands": brands, "models": models,
        "store_id": store_id, "brand_id": brand_id, "model_id": model_id,
        "status": status, "ownership": ownership,
        "date_from": date_from, "date_to": date_to,
        "price_min": price_min, "price_max": price_max,
        "is_new_val": is_new_val, "has_docs_val": has_docs_val,
    }
    return render(request, "inventory/search.html", ctx)


@login_required
def product_detail(request, pk):
    # Cross-store viewing: hech qaysi store bo‘yicha cheklamaymiz
    p = get_object_or_404(
        Product.objects.select_related("brand","model","store").prefetch_related("images"),
        pk=pk
    )

    can_edit = (request.user.is_owner or p.created_by_id == request.user.id)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "to_repair" and p.status == "available":
            # Buni faqat owner yoki product yaratuvchisi qilsin (ixtiyoriy)
            if not can_edit:
                messages.error(request, _("You cannot change status for this product."))
            else:
                p.status = "on_repair"; p.save(update_fields=["status"])
                messages.success(request, _("Moved to repair."))
            return redirect("product_detail", pk=p.id)

        if action == "to_available" and p.status == "on_repair":
            if not can_edit:
                messages.error(request, _("You cannot change status for this product."))
            else:
                p.status = "available"; p.save(update_fields=["status"])
                messages.success(request, _("Set to available."))
            return redirect("product_detail", pk=p.id)

        if action == "sell" and p.status == "available":
            # Cross-store sell: bevosita sales/sell/ ga yo‘naltiramiz
            return redirect(f"/sales/sell/?product_id={p.id}")

    return render(request, "inventory/product_detail.html", {"p": p, "can_edit": can_edit})

@login_required
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    qs = Product.objects.select_related("brand","model","store")
    p = get_object_or_404(qs, pk=pk)
    if not can_edit_product(request.user, p):
        messages.error(request, _("You cannot edit this product."))
        return redirect("product_detail", pk=pk)

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            with transaction.atomic():
                product: Product = form.save(commit=False)
                product.updated_by = request.user
                product.save()

                # Agar yangi rasmlar yuborilsa, qo‘shamiz (eski rasmlar o‘z holida qoladi)
                existing_count = product.images.count()
                new_files = request.FILES.getlist("images")
                for idx, f in enumerate(new_files[: max(0, 7 - existing_count)]):
                    ProductImage.objects.create(
                        product=product, image=f, order=existing_count + idx
                    )
                form.save_m2m()
            messages.success(request, "Telefon ma’lumotlari yangilandi.")

        form = ProductCreateForm(request.POST, request.FILES, user=request.user, instance=p)
        if form.is_valid():
            with transaction.atomic():
                p = form.save()
                # rasmlar qo‘shish (limit form.clean’da tekshirildi)
                def _save_images(files, kind, set_primary=False):
                    first = True
                    for f in files:
                        pi = ProductImage.objects.create(product=p, image=f, kind=kind)
                        if set_primary and first:
                            pi.is_primary = True
                            pi.save(update_fields=["is_primary"])
                            first = False

                _save_images(request.FILES.getlist("doc_images"), "doc", set_primary=False)
                _save_images(request.FILES.getlist("cond_images"), "cond", set_primary=False)
                _save_images(request.FILES.getlist("images"), "other", set_primary=False)
            messages.success(request, _("Updated."))
            return redirect("product_detail", pk=p.id)
        else:
            messages.error(request, _("Fix errors."))
    else:
        form = ProductCreateForm(user=request.user, instance=p)

    return render(request, "inventory/product_form.html", {"form": form, "editing": True, "obj": p})

@login_required
def my_acquisitions(request):
    qs = Product.objects.select_related("brand","model","store")\
            .filter(created_by_id=request.user.id).order_by("-created_at")
    return render(request, "accounts/my_acquisitions.html", {"rows": qs[:500]})

@login_required
def my_stats(request):
    # period: day/week/month/year
    period = (request.GET.get("period") or "month")
    today = datetime.date.today()
    if period == "day":
        df = today
    elif period == "week":
        df = today - datetime.timedelta(days=6)
    elif period == "year":
        df = today - datetime.timedelta(days=364)
    else:  # month
        df = today - datetime.timedelta(days=29)

    sales = (Transaction.objects
             .filter(type="sale", seller_id=request.user.id, created_at__date__range=(df, today)))
    expenses = (Transaction.objects
                .filter(type="expense", seller_id=request.user.id, created_at__date__range=(df, today)))

    sales_count = sales.count()
    sales_sum = sales.aggregate(s=Sum("amount"))["s"] or 0
    cost_sum = sales.aggregate(s=Sum("cost"))["s"] or 0
    profit_sum = sales.aggregate(s=Sum("profit"))["s"] or 0

    my_expenses = expenses.aggregate(s=Sum("amount"))["s"] or 0

    commissions = (SellerCommission.objects
                   .filter(seller_id=request.user.id, transaction__created_at__date__range=(df, today)))
    commission_total = commissions.aggregate(s=Sum("amount"))["s"] or 0
    commission_paid = commissions.filter(is_paid=True).aggregate(s=Sum("amount"))["s"] or 0

    acquired_count = Product.objects.filter(created_by_id=request.user.id, created_at__date__range=(df, today)).count()

    ctx = dict(
        period=period, date_from=df, date_to=today,
        sales_count=sales_count, sales_sum=sales_sum, cost_sum=cost_sum, profit_sum=profit_sum,
        my_expenses=my_expenses,
        commission_total=commission_total, commission_paid=commission_paid,
        acquired_count=acquired_count,
    )
    return render(request, "accounts/my_stats.html", ctx)

@login_required
def import_products_excel(request):
    """
    Excel headerlar: brand, model, color, year, imei_full, ownership, purchase_price,
                     consignment_price, has_documents, is_new, defect, battery_pct, owner_name, owner_phone
    """
    from reference.models import Brand, ModelName, Color

    if request.method == "POST":
        form = ImportExcelForm(request.POST, request.FILES)
        if form.is_valid():
            store = form.cleaned_data["store"]
            data = form.cleaned_data["file"].read()
            wb = load_workbook(io.BytesIO(data))
            ws = wb.active

            header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
            expected = ["brand","model","color","year","imei_full","ownership",
                        "purchase_price","consignment_price","has_documents","is_new",
                        "defect","battery_pct","owner_name","owner_phone"]
            missing = [h for h in expected if h not in header]
            if missing:
                messages.error(request, _("Missing headers: ") + ", ".join(missing))
                return render(request, "inventory/import_products_excel.html", {"form": form})

            idx = {name: header.index(name) for name in expected}
            results, created_count = [], 0

            for i, row in enumerate(ws.iter_rows(min_row=2), start=2):
                def cell(n):
                    val = row[idx[n]].value
                    return val if val is not None else ""

                rr = {"row": i, "status": "ok", "message": ""}
                try:
                    brand_name = str(cell("brand")).strip()
                    model_name = str(cell("model")).strip()
                    color_name = str(cell("color")).strip()
                    year = cell("year")
                    imei_full = str(cell("imei_full")).strip()
                    ownership = str(cell("ownership")).strip() or "owned"
                    purchase_price = cell("purchase_price") or 0
                    consignment_price = cell("consignment_price") or 0
                    has_documents = bool(int(cell("has_documents") or 0))
                    is_new = bool(int(cell("is_new") or 0))
                    defect = str(cell("defect")).strip() or ""
                    battery_pct = cell("battery_pct") or None
                    owner_name = str(cell("owner_name")).strip() or ""
                    owner_phone = str(cell("owner_phone")).strip() or ""

                    if not brand_name or not model_name or not imei_full:
                        raise ValueError(_("brand/model/imei_full required"))

                    brand = Brand.objects.get(name__iexact=brand_name)
                    model = ModelName.objects.get(brand=brand, name__iexact=model_name)
                    color = None
                    if color_name:
                        color = Color.objects.get(name__iexact=color_name)

                    if ownership not in ("owned","consignment"):
                        raise ValueError(_("Ownership must be 'owned' or 'consignment'"))

                    p = Product(
                        store=store, brand=brand, model=model, color=color, year=year or None,
                        imei_full=imei_full, ownership=ownership,
                        purchase_price=Decimal(purchase_price or 0),
                        consignment_price=Decimal(consignment_price or 0),
                        has_documents=has_documents, is_new=is_new,
                        defect=defect or "", battery_pct=battery_pct if battery_pct not in ("", None) else None,
                        owner_name=owner_name, owner_phone=owner_phone, created_by=request.user,
                    )
                    p.save()
                    created_count += 1
                except Exception as e:
                    rr["status"] = "error"
                    rr["message"] = str(e)
                results.append(rr)

            messages.success(request, _(f"Imported: {created_count}"))
            return render(request, "inventory/import_products_result.html", {"results": results})
        else:
            messages.error(request, _("Fix form errors."))
    else:
        init = {}
        if not request.user.is_owner and getattr(request.user, "store_id", None):
            init["store"] = request.user.store_id
        form = ImportExcelForm(initial=init)

    return render(request, "inventory/import_products_excel.html", {"form": form})

# ==== OLINGAN TELEFONLAR (available/on_repair) ====
@login_required
def product_received_list(request):
    """
    Olingan telefonlar: status in ['available','on_repair'].
    Filtrlar: store, brand, model, ownership, is_new, has_documents, date_from/to
    """
    qs = (Product.objects
          .select_related("brand","model","store","created_by")
          .filter(is_archived=False)
          .exclude(status="sold")
          .order_by("-created_at"))

    # Ruxsat
    if not request.user.is_owner:
        qs = qs.filter(store_id=request.user.store_id)

    # Filtrlar
    store_id = request.GET.get("store_id") or ""
    brand_id = request.GET.get("brand") or ""
    model_id = request.GET.get("model") or ""
    ownership = request.GET.get("ownership") or ""
    status = request.GET.get("status") or ""  # available/on_repair
    is_new = True if request.GET.get("is_new") == "1" else False
    has_docs = True if request.GET.get("has_documents") == "1" else False

    def _pdate(s):
        try: return datetime.datetime.strptime(s, "%Y-%m-%d").date()
        except: return None
    date_from = _pdate(request.GET.get("date_from") or "")
    date_to   = _pdate(request.GET.get("date_to") or "")

    if store_id:
        qs = qs.filter(store_id=(store_id if request.user.is_owner else request.user.store_id))
    if brand_id:
        qs = qs.filter(brand_id=brand_id)
    if model_id:
        qs = qs.filter(model_id=model_id)
    if ownership in ("owned","consignment"):
        qs = qs.filter(ownership=ownership)
    if status in ("available","on_repair"):
        qs = qs.filter(status=status)
    if is_new:
        qs = qs.filter(is_new=True)
    if has_docs:
        qs = qs.filter(has_documents=True)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    today = dj_tz.now().date()
    start = today - datetime.timedelta(days=29)

    def series(q):
        rows = (q.filter(created_at__date__range=(start, today))
                .annotate(d=TruncDate("created_at"))
                .values("d").annotate(cnt=Count("id")).order_by("d"))
        by = {r["d"]: int(r["cnt"] or 0) for r in rows}
        labels = [(start + datetime.timedelta(days=i)) for i in range(30)]
        return labels, [by.get(d, 0) for d in labels]

    labels, cnt_all = series(qs)
    labels_s = [d.strftime("%Y-%m-%d") for d in labels]

    def sum_value(q, field):
        return float(q.aggregate(s=Sum(field))["s"] or 0)

    owned_30 = qs.filter(ownership="owned", created_at__date__range=(start, today))
    cons_30 = qs.filter(ownership="consignment", created_at__date__range=(start, today))
    total_value_30 = sum_value(owned_30, "purchase_price") + sum_value(cons_30, "consignment_price")

    # Ro‘yxatlar
    stores = Store.objects.filter(is_active=True).order_by("name")
    brands = Brand.objects.filter(is_active=True).order_by("name")
    models = ModelName.objects.filter(is_active=True).order_by("brand__name","name")

    ctx = {
        "rows": list(qs[:400]),
        "stores": stores, "brands": brands, "models": models,
        "store_id": store_id, "brand_id": brand_id, "model_id": model_id,
        "ownership": ownership, "status": status,
        "is_new_val": is_new, "has_docs_val": has_docs,
        "date_from": request.GET.get("date_from") or "", "date_to": request.GET.get("date_to") or "",
        "rec_labels_json": mark_safe(json.dumps(labels_s)),
        "rec_counts_json": mark_safe(json.dumps(cnt_all)),
        "rec_total_value_30": total_value_30,
    }
    return render(request, "inventory/product_received_list.html", ctx)


# ==== SOTILGAN TELEFONLAR ====

def _pdate(s: str):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


@login_required
def product_sold_list(request):
    """
    Sotilgan telefonlar ro‘yxati + filtrlar + mini analitika.
    *** Eʼtibor: prefetch_related("transactions") yoʻq — tranzaksiyalar alohida yigʻiladi. ***
    """
    u = request.user
    if not (getattr(u, "is_owner", False) or getattr(u, "role", "") == "seller"):
        return HttpResponseForbidden()

    # --- Filters from GET ---
    store_id = request.GET.get("store_id") or ""
    seller_id = request.GET.get("seller_id") or ""
    brand_id = request.GET.get("brand") or ""
    model_id = request.GET.get("model") or ""
    date_from = request.GET.get("date_from") or ""
    date_to   = request.GET.get("date_to") or ""

    # Bazaviy queryset (prefetchsiz)
    qs = Product.objects.filter(status="sold").select_related("brand", "model", "store")

    # Sana filterlari: sold_at mavjud bo'lsa undan, bo'lmasa sale tranzaksiya sanasidan foydalanamiz.
    # Bu uchun hozircha productlarni tanlab olib, tranzaksiyani keyin mapping qilamiz.
    if store_id:
        qs = qs.filter(store_id=store_id)
    if brand_id:
        qs = qs.filter(brand_id=brand_id)
    if model_id:
        qs = qs.filter(model_id=model_id)

    products = list(qs.order_by("-sold_at", "-id"))
    product_ids = [p.id for p in products]

    # Barcha tegishli SALE tranzaksiyalarni birdaniga olib kelamiz (eng oxirgisi kerak bo'ladi)
    sale_tx_qs = Transaction.objects.filter(type="sale", product_id__in=product_ids).select_related("sold_by", "sold_in_store").order_by("-created_at")
    # Har product uchun eng so'nggi sale tranzaksiyani map qilamiz
    last_sale_by_product = {}
    for t in sale_tx_qs:
        if t.product_id not in last_sale_by_product:
            last_sale_by_product[t.product_id] = t

    # Sana diapazoni bo'yicha filtrlash (sold_at yoki tranzaksiya created_at)
    if date_from or date_to:
        def in_range(p):
            # sold_at yoki tranzaksiya sanasi
            sold_dt = getattr(p, "sold_at", None)
            if not sold_dt:
                t = last_sale_by_product.get(p.id)
                sold_dt = getattr(t, "created_at", None)
            if not sold_dt:
                return False
            ds = sold_dt.date()
            if date_from:
                try:
                    df = make_aware(datetime.strptime(date_from, "%Y-%m-%d")).date()
                except Exception:
                    df = None
            else:
                df = None
            if date_to:
                try:
                    dt = make_aware(datetime.strptime(date_to, "%Y-%m-%d")).date()
                except Exception:
                    dt = None
            else:
                dt = None
            if df and ds < df:
                return False
            if dt and ds > dt:
                return False
            return True
        products = [p for p in products if in_range(p)]

    # Endi jadval/analitika uchun qatorlarni tayyorlaymiz
    rows = []
    owned_cnt = 0
    cons_cnt  = 0
    for p in products:
        t = last_sale_by_product.get(p.id)
        # Sana
        sold_dt = getattr(p, "sold_at", None) or (t.created_at if t else None)
        sold_date_str = sold_dt.strftime("%Y-%m-%d") if sold_dt else ""

        amount = Decimal(getattr(p, "price", 0) or 0)
        cost   = calc_product_cost(p)
        profit = amount - cost

        rows.append({
            "obj": p,
            "sold_date": sold_date_str,
            "amount": float(amount),
            "cost": float(cost),
            "profit": float(profit),
            "sold_by": getattr(t, "sold_by", None),
            "sold_in_store": getattr(t, "sold_in_store", None),
        })

        if getattr(p, "ownership", "owned") == "owned":
            owned_cnt += 1
        else:
            cons_cnt += 1

    # 30 kunlik chiziqli grafik ma'lumotlari
    from datetime import timedelta, date
    today = date.today()
    labels = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(29, -1, -1)]
    amounts = [0.0 for _ in labels]
    index_map = {d: i for i, d in enumerate(labels)}
    for r in rows:
        j = index_map.get(r["sold_date"])
        if j is not None:
            amounts[j] += r["amount"]

    # Installment vs full-paid (sizning loyihangizdagi flag/mantiqqa moslashtirilgan)
    installment_rows = []
    full_rows = []
    for p in products:
        is_inst = False
        if hasattr(p, "is_installment_sale"):
            is_inst = bool(p.is_installment_sale)
        else:
            t = last_sale_by_product.get(p.id)
            if t and t.note and "installment" in t.note.lower():
                is_inst = True
        (installment_rows if is_inst else full_rows).append(p)

    # Filtrlar uchun reference ma'lumotlar
    stores  = Store.objects.filter(is_active=True).order_by("name")
    sellers = User.objects.filter(is_active=True).order_by("username")
    brands  = Brand.objects.all().order_by("name")
    models  = ModelName.objects.all().order_by("name")

    context = {
        "stores": stores,
        "sellers": sellers,
        "brands": brands,
        "models": models,

        "store_id": store_id,
        "seller_id": seller_id,
        "brand_id": brand_id,
        "model_id": model_id,
        "date_from": date_from,
        "date_to": date_to,

        "rows": rows,
        "items": [r["obj"] for r in rows],  # agar shablonning boshqa joyi ishlatsa

        "sold_labels_json": json.dumps(labels),
        "sold_amounts_json": json.dumps(amounts),
        "sold_owned_cnt": owned_cnt,
        "sold_cons_cnt": cons_cnt,

        "installment_rows": installment_rows,
        "full_rows": full_rows,
    }
    return render(request, "inventory/product_sold_list.html", context)




def _sold_list_ctx_base(request, rows, store_id, brand_id, model_id, seller_id, payment_type, date_from, date_to):
    stores = Store.objects.filter(is_active=True).order_by("name")
    brands = Brand.objects.filter(is_active=True).order_by("name")
    models = ModelName.objects.filter(is_active=True).order_by("brand__name","name")
    sellers = User.objects.filter(is_active=True).order_by("username")
    return {
        "rows": rows,
        "stores": stores, "brands": brands, "models": models, "sellers": sellers,
        "store_id": store_id, "brand_id": brand_id, "model_id": model_id, "seller_id": seller_id,
        "payment_type": payment_type,
        "date_from": date_from, "date_to": date_to,
    }
