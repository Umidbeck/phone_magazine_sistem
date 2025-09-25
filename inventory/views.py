# inventory/views.py
import csv
import datetime
import io
from decimal import Decimal, InvalidOperation

import pandas as pd
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Model, Sum, When, Case, F
from django.db.models.functions import Right, Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from openpyxl import load_workbook
from weasyprint import HTML

from accounts.models import Store, User
from reference.models import Brand, ModelName, Color
from sales.models import Transaction, SellerCommission
from .forms import (
    ProductCreateForm,
    BatchIntakeForm,
    BatchItemForm,
    ExcelImportForm, ImportExcelForm,
)
from .mixins import can_edit_product
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
    instance = None
    edit_id = request.GET.get("edit")
    if edit_id:
        # edit rejimi uchun instance
        qs = Product.objects.all()
        if not request.user.is_owner:
            qs = qs.filter(created_by_id=request.user.id)
        instance = get_object_or_404(qs.select_related("brand","model","store"), pk=edit_id)

    if request.method == "POST":
        # edit bo‘lsa POST ichidan ham instance id kelsa olish mumkin
        if request.POST.get("id"):
            qs = Product.objects.all()
            if not request.user.is_owner:
                qs = qs.filter(created_by_id=request.user.id)
            instance = get_object_or_404(qs, pk=request.POST.get("id"))

        form = ProductCreateForm(request.POST, request.FILES, user=request.user, instance=instance)
        if form.is_valid():
            with transaction.atomic():
                p: Product = form.save(commit=False)

                # Store siyosati
                if request.user.is_owner:
                    if not p.store_id:
                        messages.error(request, _("Select a store."))
                        return render(request, "inventory/product_create.html", {"form": form})
                else:
                    # seller — tayinlangan bo‘lsa majburiy o‘sha, bo‘lmasa formdan
                    if getattr(request.user, "store_id", None):
                        p.store = request.user.store
                    elif not p.store_id:
                        messages.error(request, _("Select a store."))
                        return render(request, "inventory/product_create.html", {"form": form})

                if not instance:
                    p.created_by = request.user  # faqat yangi yaratilganda
                p.save()

                # Rasmlar
                def _save_images(files, kind, set_primary=False):
                    first = True
                    for f in files:
                        pi = ProductImage.objects.create(product=p, image=f, kind=kind)
                        if set_primary and first:
                            pi.is_primary = True
                            pi.save(update_fields=["is_primary"])
                            first = False

                _save_images(request.FILES.getlist("doc_images"), "doc", set_primary=False)
                _save_images(request.FILES.getlist("cond_images"), "cond", set_primary=True if not instance else False)
                _save_images(request.FILES.getlist("images"), "other", set_primary=False)

            messages.success(request, _("Saved successfully."))
            if instance:
                return redirect("product_detail", pk=p.id)
            return redirect("product_create")
        else:
            messages.error(request, "; ".join([" ".join(v) for v in form.errors.values()]))
    else:
        form = ProductCreateForm(user=request.user, instance=instance)

    return render(request, "inventory/product_create.html", {"form": form, "editing": bool(instance), "obj": instance})





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
    qs = Product.objects.select_related("brand","model","store")
    p = get_object_or_404(qs, pk=pk)
    if not can_edit_product(request.user, p):
        messages.error(request, _("You cannot edit this product."))
        return redirect("product_detail", pk=pk)

    if request.method == "POST":
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

    return render(request, "inventory/product_create.html", {"form": form, "editing": True, "obj": p})

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
    }
    return render(request, "inventory/product_received_list.html", ctx)


# ==== SOTILGAN TELEFONLAR ====
# inventory/views.py
@login_required
def product_sold_list(request):
    """
    1) Transaction(type='sale') (is_void=False, product!=NULL)
    2) Fallback: Product(status='sold')
    """
    df = parse_date(request.GET.get("date_from") or "")
    dt = parse_date(request.GET.get("date_to") or "")
    store_id = request.GET.get("store_id") if getattr(request.user, "is_owner", False) else None
    seller_id = request.GET.get("seller_id") or ""

    tx_qs = (Transaction.objects
             .select_related("product", "product__brand", "product__model", "store", "seller")
             .filter(type="sale", is_void=False, product__isnull=False))
    p_qs = (Product.objects.select_related("brand", "model", "store").filter(status="sold"))

    if not getattr(request.user, "is_owner", False):
        tx_qs = tx_qs.filter(store_id=request.user.store_id)
        p_qs = p_qs.filter(store_id=request.user.store_id)
    elif store_id:
        tx_qs = tx_qs.filter(store_id=store_id)
        p_qs = p_qs.filter(store_id=store_id)

    if seller_id:
        tx_qs = tx_qs.filter(seller_id=seller_id)

    if df:
        tx_qs = tx_qs.filter(created_at__date__gte=df)
        p_qs = p_qs.filter(sold_at__date__gte=df)
    if dt:
        tx_qs = tx_qs.filter(created_at__date__lte=dt)
        p_qs = p_qs.filter(sold_at__date__lte=dt)

    tx_map = {t.product_id: t for t in tx_qs}
    rows = [{"p": t.product, "tx": t} for t in tx_qs]
    rows += [{"p": p, "tx": None} for p in p_qs.exclude(id__in=tx_map.keys())[:400]]
    rows.sort(key=lambda r: (r["tx"].created_at if r["tx"] else (r["p"].sold_at or r["p"].updated_at)), reverse=True)
    rows = rows[:400]

    stores = Store.objects.order_by("name") if getattr(request.user, "is_owner", False) else None
    sellers = User.objects.filter(is_active=True).order_by("username") if getattr(request.user, "is_owner", False) else None

    return render(request, "inventory/product_sold_list.html", {
        "rows": rows, "stores": stores, "sellers": sellers,
        "store_id": store_id or "", "seller_id": seller_id or "",
        "date_from": request.GET.get("date_from") or "", "date_to": request.GET.get("date_to") or "",
    })



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
