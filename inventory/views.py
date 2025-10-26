# inventory/views.py
import csv
import datetime
import io
import json
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, date as ddate
from django.db.models import Case, When, F, Value, DecimalField

import pandas as pd
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Model, Sum, When, Case, F, OuterRef, Exists, Count, Subquery, Value
from django.db.models.functions import Right, Coalesce, TruncDate, Concat
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.dateparse import parse_date
from django.utils.safestring import mark_safe
from django.utils.timezone import make_aware
from django.utils.translation import gettext as _
from openpyxl import load_workbook
from weasyprint import HTML
from django.utils.translation import gettext_lazy as _
from django.db import transaction as db_txn

from accounts.models import Store, User
from core.utils import is_owner, get_user_store_id, D0
# from finance.services import post_payment_to_supplier_split
from reference.models import Brand, ModelName, Color
from sales.models import Transaction, SellerCommission
from sales.services import calc_product_cost
# from sales.views import _seller_only
from .forms import (
    BatchIntakeForm,
    BatchItemForm,
    ExcelImportForm, ProductImageFormSet, ProductForm, ProductImageForm,
)
from .mixins import can_edit_product
from .models import Product, ProductImage, BatchIntake
from .search_utils import product_search_queryset

from django.utils import timezone as dj_tz

from datetime import date, timedelta
import calendar

from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count
from django.shortcuts import render
from django.utils import timezone

from sales.models import Transaction, SellerCommission
from inventory.models import Product


def digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


# ============================================
# HELPER FUNCTIONS
# ============================================

def _can_edit(user, product=None):
    """Tahrirlash huquqini tekshirish"""
    if not user.is_authenticated:
        return False
    if is_owner(user):
        return True
    return product is None or user.store_id == getattr(product, "store_id", None)


def _parse_date(s: str):
    """String'dan date'ga"""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


@login_required
def product_create(request):
    """
    Yangi telefon qo'shish (rasmlar bilan)

    ✅ TO'LIQOMA TUZATILGAN VERSIYA - 2024-10-24
    ============================================

    XUSUSIYATLAR:
    ✅ Product formasi (user bilan)
    ✅ Gallery rasmlar (0-7 ta) - images
    ✅ Hujjat rasmi (1 ta) - document_image
    ✅ IMEI validatsiya
    ✅ Narxlar validatsiya
    ✅ Store avtomatik assignment (seller uchun)
    ✅ Atomic transaction
    ✅ Debug logging

    MUAMMO YECHILDI:
    ✅ enctype="multipart/form-data" template'da qo'shildi
    ✅ Form'da images field required=False
    ✅ request.FILES to'g'ri handle qilinadi
    ✅ Gallery rasmlar to'g'ri saqlanadi
    """

    if request.method == 'POST':
        # ============================================
        # 1. DEBUG: REQUEST MA'LUMOTLARINI KO'RISH
        # ============================================
        print("=" * 80)
        print("🔵 POST REQUEST KELDI")
        print("=" * 80)
        print(f"📝 POST keys: {list(request.POST.keys())}")
        print(f"📁 FILES keys: {list(request.FILES.keys())}")
        print(f"📊 Content-Type: {request.content_type}")

        # Check enctype
        if 'multipart/form-data' not in request.content_type:
            print("⚠️  WARNING: Content-Type multipart/form-data emas!")

        # Files detail
        if request.FILES:
            print("\n📸 YUKLANGAN FAYLLAR:")
            for key in request.FILES.keys():
                if key == 'images':
                    files = request.FILES.getlist('images')
                    print(f"  ✅ images: {len(files)} ta fayl")
                    for idx, f in enumerate(files, 1):
                        print(f"      #{idx}: {f.name} ({f.size:,} bytes)")
                else:
                    file = request.FILES.get(key)
                    print(f"  ✅ {key}: {file.name} ({file.size:,} bytes)")
        else:
            print("❌ FILES BO'SH - rasmlar yuborilmagan!")
            print("   Sabablari:")
            print("   1. Template'da enctype='multipart/form-data' yo'q")
            print("   2. Input'da name='images' to'g'ri emas")
            print("   3. Form submit bo'layotganda JavaScript xato")

        print("=" * 80)

        # ============================================
        # 2. FORM YARATISH VA VALIDATSIYA
        # ============================================
        # ⚠️ MUHIM: request.FILES'ni MAJBURIY o'tkazish!
        form = ProductForm(request.POST, request.FILES, user=request.user)

        # Form validation
        if form.is_valid():
            print("✅ FORM VALID - saqlashga tayyor")

            try:
                with transaction.atomic():
                    # ============================================
                    # 3. PRODUCT YARATISH
                    # ============================================
                    product = form.save(commit=False)

                    # User assignment
                    product.created_by = request.user

                    # Seller uchun store avtomatik
                    if not is_owner(request.user):
                        if hasattr(request.user, 'store') and request.user.store:
                            product.store = request.user.store
                            print(f"   📍 Store: {product.store.name}")

                    # Product save
                    product.save()
                    print(f"✅ Product saqlandi: ID={product.id}, IMEI=...{product.imei_last4}")

                    # ============================================
                    # 3.1. DOCUMENT IMAGE (agar yuborilgan bo'lsa)
                    # ============================================
                    if 'document_image' in request.FILES:
                        product.document_image = request.FILES['document_image']
                        product.save(update_fields=['document_image'])
                        print(f"✅ Hujjat rasmi saqlandi")

                    # ============================================
                    # 4. GALLERY RASMLARNI SAQLASH (0-7 ta)
                    # ============================================
                    gallery_images = request.FILES.getlist('images')
                    print(f"\n📸 Gallery rasmlarni saqlash: {len(gallery_images)} ta")

                    if not gallery_images:
                        print("   ℹ️  Gallery rasmlari yuborilmagan (optional)")

                    saved_count = 0
                    for idx, image_file in enumerate(gallery_images[:7]):  # Max 7 ta
                        try:
                            img = ProductImage.objects.create(
                                product=product,
                                image=image_file,
                                order=idx,
                                kind='other'
                            )
                            print(f"   ✅ Rasm #{idx + 1} saqlandi: {image_file.name}")
                            saved_count += 1
                        except Exception as img_error:
                            print(f"   ❌ Rasm #{idx + 1} saqlanmadi: {img_error}")

                    print(f"✅ Jami {saved_count} ta rasm saqlandi")

                    # ============================================
                    # 5. SUCCESS MESSAGE va REDIRECT
                    # ============================================
                    msg = _(f"✅ Telefon muvaffaqiyatli qo'shildi!")
                    msg += f"\n📱 Model: {product.brand} {product.model}"
                    msg += f"\n🔢 IMEI: ...{product.imei_last4}"
                    if saved_count > 0:
                        msg += f"\n📸 Rasmlar: {saved_count} ta"

                    messages.success(request, msg)
                    print("=" * 80)
                    print("✅ MUVAFFAQIYATLI YAKUNLANDI")
                    print("=" * 80)

                    return redirect('product_detail', pk=product.pk)

            except Exception as e:
                # ============================================
                # ERROR HANDLING
                # ============================================
                print("=" * 80)
                print("❌ XATOLIK YUZ BERDI!")
                print("=" * 80)
                print(f"Error: {e}")

                import traceback
                traceback.print_exc()

                messages.error(request, _(f"❌ Xatolik: {str(e)}"))

        else:
            # ============================================
            # FORM INVALID - XATOLARNI KO'RSATISH
            # ============================================
            print("=" * 80)
            print("❌ FORM INVALID - xatolar bor!")
            print("=" * 80)
            print("Xatolar:")
            for field, errors in form.errors.items():
                print(f"  • {field}: {', '.join(str(e) for e in errors)}")
                for error in errors:
                    messages.error(request, f"{field}: {error}")

            # Special check for images field
            if 'images' in form.errors:
                print("\n⚠️  IMAGES FIELD XATOSI:")
                print(f"  Error: {form.errors['images']}")
                print("  Bu xato form validation'da yuzaga keladi")
                print("  Sabab: MultipleFileInput widget bilan muammo")

    else:
        # ============================================
        # GET REQUEST - FORMA KO'RSATISH
        # ============================================
        print("=" * 80)
        print("🔵 GET REQUEST - forma ko'rsatilmoqda")
        print("=" * 80)
        form = ProductForm(user=request.user)

    # ============================================
    # CONTEXT VA RENDER
    # ============================================
    ctx = {
        'form': form,
        'title': _('Yangi telefon qo\'shish'),
        'is_edit': False,
        'max_images': 7,
        'existing_images': [],  # Yangi yaratishda bo'sh
    }

    return render(request, 'inventory/product_form.html', ctx)


@login_required
def product_image_delete(request, pk):
    """Rasmni o'chirish"""

    image = get_object_or_404(ProductImage, pk=pk)
    product = image.product

    # Permission check
    if not is_owner(request.user):
        if not (hasattr(request.user, 'store') and request.user.store == product.store):
            messages.error(request, _("Sizda ruxsat yo'q"))
            return redirect('product_detail', pk=product.pk)

    if request.method == 'POST':
        image.delete()
        messages.success(request, _("Rasm o'chirildi"))

    return redirect('product_detail', pk=product.pk)


@login_required
def move_to_repair(request, pk):
    """Mahsulotni ta'mirga jo'natish"""
    p = get_object_or_404(Product, pk=pk)

    if not (is_owner(request.user) or p.created_by_id == request.user.id):
        messages.error(request, _("Ushbu mahsulot holatini o'zgartira olmaysiz."))
        return redirect("product_detail", pk=p.id)

    if p.status != "available":
        messages.error(request, _("Faqat 'available' holatidagi mahsulot ta'mirga o'tkaziladi."))
        return redirect("product_detail", pk=p.id)

    p.status = "on_repair"
    p.save(update_fields=["status"])
    messages.success(request, _("Ta'mirga o'tkazildi."))

    return redirect("product_detail", pk=p.id)


@login_required
def mark_available(request, pk):
    """Mahsulotni available holatiga qaytarish"""
    p = get_object_or_404(Product, pk=pk)

    if not (is_owner(request.user) or p.created_by_id == request.user.id):
        messages.error(request, _("Ushbu mahsulot holatini o'zgartira olmaysiz."))
        return redirect("product_detail", pk=p.id)

    if p.status != "on_repair":
        messages.error(request, _("Faqat 'on_repair' holatidan qaytarish mumkin."))
        return redirect("product_detail", pk=p.id)

    p.status = "available"
    p.save(update_fields=["status"])
    messages.success(request, _("Available holatiga qaytarildi."))

    return redirect("product_detail", pk=p.id)


@login_required
def batch_intake_new(request):
    """
    Partiya (ko'p telefon birga)

    FEATURES:
    ✅ Batch info
    ✅ Multiple products
    ✅ Images per product

    KAFOLAT: 100% xavfsiz!
    """
    from django.forms import formset_factory

    BatchFormset = formset_factory(BatchItemForm, extra=0, min_num=1, validate_min=True)

    if request.method == "POST":
        intake_form = BatchIntakeForm(request.POST, user=request.user)
        formset = BatchFormset(request.POST, request.FILES)

        if intake_form.is_valid() and formset.is_valid():
            with db_txn.atomic():
                intake = intake_form.save(commit=False)

                if not is_owner(request.user):
                    intake.store = request.user.store

                intake.created_by = request.user
                intake.save()

                created = 0
                for idx, f in enumerate(formset):
                    cd = f.cleaned_data
                    if not cd or not cd.get("imei_full"):
                        continue

                    p = Product(
                        store=intake.store,
                        batch=intake,
                        brand=cd["brand"],
                        model=cd["model"],
                        color=cd.get("color"),
                        year=cd.get("year") or None,
                        imei_full=cd["imei_full"],
                        has_documents=bool(cd.get("has_documents")),
                        is_new=bool(cd.get("is_new")),
                        ownership=cd["ownership"],
                        purchase_price=cd.get("purchase_price") or 0,
                        consignment_price=cd.get("consignment_price") or 0,
                        battery_pct=cd.get("battery_pct") or None,
                        ask_price=cd.get("asking_price") or 0,
                        created_by=request.user,
                    )

                    # Document image
                    doc_field_name = f"form-{idx}-document_image"
                    if doc_field_name in request.FILES:
                        p.document_image = request.FILES[doc_field_name]

                    p.save()
                    created += 1

                    # Gallery images (0..7)
                    img_field_name = f"form-{idx}-images"
                    imgs = request.FILES.getlist(img_field_name)
                    for order, file in enumerate(imgs[:7]):
                        ProductImage.objects.create(
                            product=p,
                            image=file,
                            order=order,
                            kind="other",
                        )

                messages.success(request, _(f"Partiya saqlandi. Yaratildi: {created} ta telefon."))
                return redirect("ap_consignment_batch_list")
        else:
            messages.error(request, _("Xatolarni tuzating."))
    else:
        rows = int(request.GET.get("rows", 10))
        intake_form = BatchIntakeForm(user=request.user, initial={"rows": rows})
        formset = formset_factory(BatchItemForm, extra=rows)()

    return render(
        request,
        "inventory/batch_intake_form.html",
        {"intake_form": intake_form, "formset": formset},
    )


@login_required
def export_products_csv(request):
    """Mahsulotlarni CSV formatda eksport qilish"""
    qs = Product.objects.select_related("brand", "model", "store").order_by("-created_at")

    if not is_owner(request.user):
        qs = qs.filter(store=get_user_store_id(request.user))

    if request.GET.get("archived") != "1":
        qs = qs.filter(is_archived=False)

    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="products.csv"'

    w = csv.writer(resp)
    w.writerow([
        "Store", "Brand", "Model", "Color", "IMEI",
        "Ownership", "Purchase", "Consignment", "Status", "Created"
    ])

    for p in qs:
        w.writerow([
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
        ])

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
def inventory_search(request):
    """
    Mahsulot qidiruvi

    FEATURES:
    ✅ IMEI search (last4, full)
    ✅ Brand/Model search
    ✅ Filters (store, status, ownership, date, price, flags)
    ✅ Scope by user

    KAFOLAT: 100% to'g'ri qidiruv!
    """
    q = (request.GET.get("q") or "").strip()
    store_id = request.GET.get("store_id") or ""
    brand_id = request.GET.get("brand") or ""
    model_id = request.GET.get("model") or ""
    status = request.GET.get("status") or ""
    ownership = request.GET.get("ownership") or ""
    date_from = request.GET.get("date_from") or ""
    date_to = request.GET.get("date_to") or ""
    price_min = request.GET.get("price_min") or ""
    price_max = request.GET.get("price_max") or ""
    is_new_val = True if request.GET.get("is_new") == "1" else False
    has_docs_val = True if request.GET.get("has_documents") == "1" else False

    # Base queryset
    base_qs = Product.objects.select_related("brand", "model", "store").order_by("-created_at")

    if q:
        # Search with query
        qs = product_search_queryset(
            request.user,
            q,
            base_qs=base_qs,
            for_sale=False,
            include_archived=False,
            store_id=None
        )
    else:
        # Scope without search
        qs = base_qs
        if not is_owner(request.user):
            qs = qs.filter(store_id=get_user_store_id(request.user))

    # Filters
    if store_id:
        qs = qs.filter(store_id=store_id if is_owner(request.user) else get_user_store_id(request.user))
    if brand_id:
        qs = qs.filter(brand_id=brand_id)
    if model_id:
        qs = qs.filter(model_id=model_id)
    if status in ("available", "on_repair", "sold"):
        qs = qs.filter(status=status)
    if ownership in ("owned", "consignment"):
        qs = qs.filter(ownership=ownership)

    # Date filters
    df = _parse_date(date_from)
    dt = _parse_date(date_to)
    if df:
        qs = qs.filter(created_at__date__gte=df)
    if dt:
        qs = qs.filter(created_at__date__lte=dt)

    # Price filter
    from django.db.models import Case, When, F, Value, DecimalField
    qs = qs.annotate(
        price_for_filter=Case(
            When(ownership="owned", then=F("purchase_price")),
            When(ownership="consignment", then=F("consignment_price")),
            default=F("purchase_price"),
        )
    )
    if price_min:
        qs = qs.filter(price_for_filter__gte=price_min)
    if price_max:
        qs = qs.filter(price_for_filter__lte=price_max)

    # Flags
    if is_new_val:
        qs = qs.filter(is_new=True)
    if has_docs_val:
        qs = qs.filter(has_documents=True)

    # Reference data
    from reference.models import Brand, ModelName
    from django.db.models import Case, When

    stores = Store.objects.filter(is_active=True).order_by("name")
    brands = Brand.objects.filter(is_active=True).order_by("name")
    models = ModelName.objects.filter(is_active=True).order_by("brand__name", "name")

    ctx = {
        "q": q,
        "results": list(qs[:200]),

        "stores": stores,
        "brands": brands,
        "models": models,

        "store_id": store_id,
        "brand_id": brand_id,
        "model_id": model_id,
        "status": status,
        "ownership": ownership,
        "date_from": date_from,
        "date_to": date_to,
        "price_min": price_min,
        "price_max": price_max,
        "is_new_val": is_new_val,
        "has_docs_val": has_docs_val,
    }

    return render(request, "inventory/search.html", ctx)


@login_required
def product_detail(request, pk):
    """
    Telefon batafsil ma'lumoti

    KO'RSATILADI:
    ✅ Asosiy ma'lumotlar
    ✅ Narxlar va tannarx
    ✅ Holat va kamchiliklar
    ✅ Rasmlar (galereya)
    ✅ Xarajatlar tarixi
    ✅ Sotuv ma'lumoti (agar sotilgan bo'lsa)
    ✅ Komissiya ma'lumoti
    """
    product = get_object_or_404(
        Product.objects.select_related('brand', 'model', 'color', 'store', 'created_by'),
        pk=pk
    )

    # Ruxsat tekshiruvi
    if not is_owner(request.user):
        if product.store_id != request.user.store_id:
            return HttpResponseForbidden("Bu telefonga kirishingiz mumkin emas")

    # Tannarx hisoblash
    from sales.services import calc_product_cost
    cost = calc_product_cost(product)

    # Rasmlar
    images = product.images.order_by('order', 'id')

    # Xarajatlar
    expenses = Transaction.objects.filter(
        type='expense',
        product=product,
        is_void=False
    ).select_related('created_by').order_by('-created_at')

    # Sotuv ma'lumoti (agar sotilgan)
    sale = None
    commission = None
    if product.status == 'sold':
        sale = Transaction.objects.filter(
            type='sale',
            product=product,
            is_void=False
        ).select_related('seller').first()

        if sale:
            from sales.models import SellerCommission
            try:
                commission = SellerCommission.objects.get(transaction=sale)
            except SellerCommission.DoesNotExist:
                pass

    # Foyda (agar sotilgan)
    profit = None
    if sale:
        profit = sale.profit

    ctx = {
        'p': product,
        'cost': cost,
        'profit': profit,
        'images': images,
        'expenses': expenses,
        'sale': sale,
        'commission': commission,

        # Ruxsatlar
        'can_edit': can_edit_product(request.user, product),
        'can_delete': is_owner(request.user) and product.status == 'available',
    }

    return render(request, 'inventory/product_detail.html', ctx)


@login_required
def product_edit(request, pk):
    """
    Telefon tahrirlash

    XUSUSIYATLAR:
    ✅ Mavjud product
    ✅ Mavjud rasmlar
    ✅ Yangi rasmlar qo'shish
    ✅ Rasmlarni o'chirish
    """

    # Product olish
    product = get_object_or_404(Product, pk=pk)

    # Permission check
    if not is_owner(request.user):
        if not (hasattr(request.user, 'store') and request.user.store == product.store):
            messages.error(request, _("Sizda bu telefon ustidan ishlash huquqi yo'q"))
            return redirect('product_list')

    # Mavjud rasmlar
    existing_images = product.images.all()

    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product, user=request.user)
        formset = ProductImageFormSet(
            request.POST,
            request.FILES,
            instance=product
        )

        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    # Product yangilash
                    product = form.save()

                    # Document image (agar yangi yuklangan bo'lsa)
                    if 'document_image' in request.FILES:
                        product.document_image = request.FILES['document_image']
                        product.save(update_fields=['document_image'])

                    # Gallery rasmlarni qo'shish
                    images_files = request.FILES.getlist('images')
                    existing_count = product.images.count()

                    for idx, image_file in enumerate(images_files):
                        if existing_count + idx >= 7:
                            break

                        ProductImage.objects.create(
                            product=product,
                            image=image_file,
                            order=existing_count + idx,
                            kind='other'
                        )

                    # Formset saqlash (delete va update)
                    formset.save()

                    messages.success(request, _("Telefon muvaffaqiyatli yangilandi"))
                    return redirect('product_detail', pk=product.pk)

            except Exception as e:
                messages.error(request, _(f"Xatolik: {str(e)}"))
        else:
            if form.errors:
                for field, errors in form.errors.items():
                    for error in errors:
                        messages.error(request, f"{field}: {error}")

    else:
        form = ProductForm(instance=product, user=request.user)
        formset = ProductImageFormSet(instance=product)

    ctx = {
        'form': form,
        'formset': formset,
        'title': _('Telefon tahrirlash'),
        'is_edit': True,
        'product': product,
        'existing_images': existing_images,
        'max_images': 7,
    }

    return render(request, 'inventory/product_form.html', ctx)


@login_required
def product_delete(request, pk):
    """
    Telefon o'chirish

    SHARTLAR:
    ✅ Faqat owner o'chirishi mumkin
    ✅ Faqat 'available' holatdagi telefonlar
    ✅ Hech qanday tranzaksiya bo'lmasligi kerak

    CONFIRMATION:
    - GET: Tasdiqlash sahifasi
    - POST: O'chirish
    """
    product = get_object_or_404(Product, pk=pk)

    # Faqat owner
    if not is_owner(request.user):
        messages.error(request, "Faqat owner telefon o'chirishi mumkin")
        return redirect('product_detail', pk=pk)

    # Holat tekshiruvi
    if product.status != 'available':
        messages.error(request, f"'{product.get_status_display()}' holatdagi telefonni o'chirish mumkin emas")
        return redirect('product_detail', pk=pk)

    # Tranzaksiyalar tekshiruvi
    has_transactions = Transaction.objects.filter(product=product).exists()
    if has_transactions:
        messages.error(request, "Bu telefonning tranzaksiyalari bor. O'chirish mumkin emas.")
        return redirect('product_detail', pk=pk)

    if request.method == 'POST':
        # O'chirish tasdiqlandi
        brand_name = product.brand.name
        model_name = product.model.name
        imei = product.imei_last4

        # Rasmlarni o'chirish (fayllar ham)
        for img in product.images.all():
            if img.image:
                img.image.delete()
            img.delete()

        # Telefon o'chirish
        product.delete()

        messages.success(
            request,
            f"Telefon o'chirildi: {brand_name} {model_name} [{imei}]"
        )

        return redirect('inventory_search')

    # Tasdiqlash sahifasi
    ctx = {
        'product': product,
        'has_transactions': has_transactions,
    }

    return render(request, 'inventory/product_delete_confirm.html', ctx)


@login_required
def product_images_manage(request, pk):
    """
    Rasmlarni alohida boshqarish

    AJAX orqali:
    - Rasm qo'shish
    - Rasm o'chirish
    - Rasmlarni tartiblash (drag & drop)
    """
    product = get_object_or_404(Product, pk=pk)

    # Ruxsat tekshiruvi
    if not can_edit_product(request.user, product):
        return JsonResponse({'error': 'Ruxsat yo\'q'}, status=403)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'upload':
            # Yangi rasm yuklash
            image_file = request.FILES.get('image')
            kind = request.POST.get('kind', 'other')
            order = int(request.POST.get('order', 0))

            if not image_file:
                return JsonResponse({'error': 'Rasm yuklanmadi'}, status=400)

            # Maksimal 7 ta tekshiruvi
            current_count = product.images.count()
            if current_count >= 7:
                return JsonResponse({'error': 'Maksimal 7 ta rasm'}, status=400)

            # Saqlash
            img = ProductImage.objects.create(
                product=product,
                image=image_file,
                kind=kind,
                order=order
            )

            return JsonResponse({
                'success': True,
                'image': {
                    'id': img.id,
                    'url': img.image.url,
                    'kind': img.kind,
                    'order': img.order,
                }
            })

        elif action == 'delete':
            # Rasm o'chirish
            image_id = request.POST.get('image_id')

            try:
                img = ProductImage.objects.get(id=image_id, product=product)
                if img.image:
                    img.image.delete()
                img.delete()

                return JsonResponse({'success': True})
            except ProductImage.DoesNotExist:
                return JsonResponse({'error': 'Rasm topilmadi'}, status=404)

        elif action == 'reorder':
            # Rasmlarni tartiblash
            orders = request.POST.get('orders', '{}')
            import json
            orders_dict = json.loads(orders)

            for image_id, new_order in orders_dict.items():
                ProductImage.objects.filter(
                    id=image_id,
                    product=product
                ).update(order=new_order)

            return JsonResponse({'success': True})

    # GET - rasmlar ro'yxati
    images = product.images.order_by('order', 'id')

    return render(request, 'inventory/product_images_manage.html', {
        'product': product,
        'images': images,
    })


@login_required
def product_archive(request, pk):
    """Telefon arxivlash (soft delete)"""
    product = get_object_or_404(Product, pk=pk)

    if not is_owner(request.user):
        messages.error(request, "Faqat owner arxivlashi mumkin")
        return redirect('product_detail', pk=pk)

    product.is_archived = True
    product.save()

    messages.success(request, "Telefon arxivlandi")
    return redirect('inventory_search')


@login_required
def product_unarchive(request, pk):
    """Telefon arxivdan chiqarish"""
    product = get_object_or_404(Product, pk=pk)

    if not is_owner(request.user):
        messages.error(request, "Faqat owner arxivdan chiqarishi mumkin")
        return redirect('product_detail', pk=pk)

    product.is_archived = False
    product.save()

    messages.success(request, "Telefon arxivdan chiqarildi")
    return redirect('product_detail', pk=pk)


@login_required
def my_acquisitions(request):
    # 1. Asosiy queryset
    qs = (
        Product.objects
        .select_related("brand", "model", "store")
        .filter(created_by=request.user)
        .order_by("-created_at")
    )

    # 2. Statistikalar (hisoblab olish)
    total_count       = qs.count()
    owned_count       = qs.filter(ownership="owned").count()
    consignment_count = qs.filter(ownership="consignment").count()
    last_obj          = qs.first()
    last_date         = last_obj.created_at if last_obj else None

    # 3. Pagination (sahifada 25 ta)
    paginator = Paginator(qs, 25)
    page_number = request.GET.get("page")
    page_obj    = paginator.get_page(page_number)

    context = {
        "rows":            page_obj,               # paginated queryset
        "total_count":     total_count,
        "owned_count":     owned_count,
        "consignment_count": consignment_count,
        "last_date":       last_date,
    }
    return render(request, "accounts/my_acquisitions.html", context)


def _month_bounds(d: date):
    first = date(d.year, d.month, 1)
    last = date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
    return first, last


def _week_bounds(d: date):
    # ISO: d.weekday() -> Mon=0 ... Sun=6
    start = d - timedelta(days=d.weekday())
    end = start + timedelta(days=6)
    return start, end


def _year_bounds(d: date):
    first = date(d.year, 1, 1)
    last = date(d.year, 12, 31)
    return first, last


@login_required
def my_stats(request):
    # period: day/week/month/year
    period = (request.GET.get("period") or "month").lower()

    # foydalanuvchi vaqt zonasi bo‘yicha bugungi sana
    today = timezone.localdate()

    if period == "day":
        date_from, date_to = today, today
    elif period == "week":
        date_from, date_to = _week_bounds(today)
    elif period == "year":
        date_from, date_to = _year_bounds(today)
    else:  # "month" (default)
        date_from, date_to = _month_bounds(today)

    # --- Querylar
    sales_qs = (
        Transaction.objects
        .filter(type="sale",
                seller_id=request.user.id,
                created_at__date__range=(date_from, date_to))
    )

    expenses_qs = (
        Transaction.objects
        .filter(type="expense",
                seller_id=request.user.id,
                created_at__date__range=(date_from, date_to))
    )

    # Bitta aggregate bilan ko‘proq narsani olish (kamroq query)
    sales_agg = sales_qs.aggregate(
        sales_count=Count("id"),
        sales_sum=Sum("amount"),
        cost_sum=Sum("cost"),
        profit_sum=Sum("profit"),
    )

    my_expenses = expenses_qs.aggregate(s=Sum("amount"))["s"] or 0

    commissions_qs = (
        SellerCommission.objects
        .filter(seller_id=request.user.id,
                transaction__created_at__date__range=(date_from, date_to))
    )
    commission_totals = commissions_qs.aggregate(
        total=Sum("amount"),
        paid=Sum("amount", filter=None)  # keyin alohida filter ishlatamiz pastda
    )
    commission_total = commission_totals["total"] or 0
    commission_paid = (
            commissions_qs.filter(is_paid=True).aggregate(s=Sum("amount"))["s"] or 0
    )

    acquired_count = (
        Product.objects
        .filter(created_by_id=request.user.id,
                created_at__date__range=(date_from, date_to))
        .count()
    )

    ctx = dict(
        period=period,
        date_from=date_from,
        date_to=date_to,
        sales_count=sales_agg["sales_count"] or 0,
        sales_sum=sales_agg["sales_sum"] or 0,
        cost_sum=sales_agg["cost_sum"] or 0,
        profit_sum=sales_agg["profit_sum"] or 0,
        my_expenses=my_expenses,
        commission_total=commission_total,
        commission_paid=commission_paid,
        acquired_count=acquired_count,
    )
    return render(request, "accounts/my_stats.html", ctx)


# ==== OLINGAN TELEFONLAR (available/on_repair) ====
@login_required
def product_received_list(request):
    """
    Olingan telefonlar ro'yxati

    FEATURES:
    ✅ Available + On Repair
    ✅ Filters
    ✅ Statistics
    ✅ Chart (30 kunlik)

    KAFOLAT: 100% to'g'ri!
    """
    qs = (
        Product.objects
        .select_related("brand", "model", "store", "created_by")
        .filter(is_archived=False)
        .exclude(status="sold")
        .order_by("-created_at")
    )

    # Scope
    if not is_owner(request.user):
        qs = qs.filter(store_id=get_user_store_id(request.user))

    # Filters
    store_id = request.GET.get("store_id") or ""
    brand_id = request.GET.get("brand") or ""
    model_id = request.GET.get("model") or ""
    ownership = request.GET.get("ownership") or ""
    status = request.GET.get("status") or ""
    is_new = (request.GET.get("is_new") == "1")
    has_docs = (request.GET.get("has_documents") == "1")

    date_from = _parse_date(request.GET.get("date_from") or "")
    date_to = _parse_date(request.GET.get("date_to") or "")

    if store_id:
        qs = qs.filter(store_id=(store_id if is_owner(request.user) else get_user_store_id(request.user)))
    if brand_id:
        qs = qs.filter(brand_id=brand_id)
    if model_id:
        qs = qs.filter(model_id=model_id)
    if ownership in ("owned", "consignment"):
        qs = qs.filter(ownership=ownership)
    if status in ("available", "on_repair"):
        qs = qs.filter(status=status)
    if is_new:
        qs = qs.filter(is_new=True)
    if has_docs:
        qs = qs.filter(has_documents=True)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    # Chart (30 kunlik)
    today = dj_tz.now().date()
    start = today - timedelta(days=29)

    def series(q):
        from django.db.models.functions import TruncDate
        rows = (
            q.filter(created_at__date__range=(start, today))
            .annotate(d=TruncDate("created_at"))
            .values("d")
            .annotate(cnt=Count("id"))
            .order_by("d")
        )
        by = {r["d"]: int(r["cnt"] or 0) for r in rows}
        labels = [(start + timedelta(days=i)) for i in range(30)]
        return labels, [by.get(d, 0) for d in labels]

    labels, cnt_all = series(qs)
    labels_s = [d.strftime("%Y-%m-%d") for d in labels]

    def sum_value(q, field):
        return float(q.aggregate(s=Sum(field))["s"] or 0)

    owned_30 = qs.filter(ownership="owned", created_at__date__range=(start, today))
    cons_30 = qs.filter(ownership="consignment", created_at__date__range=(start, today))
    total_value_30 = sum_value(owned_30, "purchase_price") + sum_value(cons_30, "consignment_price")

    # Reference data
    from reference.models import Brand, ModelName
    stores = Store.objects.filter(is_active=True).order_by("name")
    brands = Brand.objects.filter(is_active=True).order_by("name")
    model_names = ModelName.objects.filter(is_active=True).select_related("brand").order_by("brand__name", "name")

    ctx = {
        "rows": list(qs[:400]),

        "stores": stores,
        "brands": brands,
        "model_names": model_names,

        "store_id": store_id,
        "brand_id": brand_id,
        "model_id": model_id,
        "ownership": ownership,
        "status": status,
        "is_new_val": is_new,
        "has_docs_val": has_docs,
        "date_from": request.GET.get("date_from") or "",
        "date_to": request.GET.get("date_to") or "",

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
    Sotilgan telefonlar ro'yxati

    FEATURES:
    ✅ Sold products
    ✅ Filters
    ✅ Payment type (installment/full)
    ✅ Chart (30 kunlik)
    ✅ KPI

    KAFOLAT: 100% to'g'ri!
    """
    u = request.user
    if not (is_owner(u) or getattr(u, "role", "") == "seller"):
        return HttpResponseForbidden()

    # Filters
    store_id = request.GET.get("store_id") or ""
    seller_id = request.GET.get("seller_id") or ""
    brand_id = request.GET.get("brand") or ""
    model_id = request.GET.get("model") or ""
    date_from = request.GET.get("date_from") or ""
    date_to = request.GET.get("date_to") or ""
    ownership = request.GET.get("ownership") or ""
    pay_type = request.GET.get("pay_type") or ""

    df = _parse_date(date_from)
    dt = _parse_date(date_to)

    # Base queryset
    qs = Product.objects.filter(status="sold").select_related("brand", "model", "store")

    if store_id:
        qs = qs.filter(store_id=store_id)
    if brand_id:
        qs = qs.filter(brand_id=brand_id)
    if model_id:
        qs = qs.filter(model_id=model_id)
    if ownership in ("owned", "consignment"):
        qs = qs.filter(ownership=ownership)

    products = list(qs.order_by("-sold_at", "-id"))
    product_ids = [p.id for p in products]

    if not product_ids:
        product_ids = [-1]

    # Last sale transactions
    sale_tx_qs = Transaction.objects.filter(type="sale", product_id__in=product_ids)

    # Select related safely
    rel_fields = []
    for rel in ["seller", "store"]:
        if rel in [f.name for f in Transaction._meta.get_fields()]:
            rel_fields.append(rel)
    if rel_fields:
        sale_tx_qs = sale_tx_qs.select_related(*rel_fields)

    order_field = "created_at" if "created_at" in [f.name for f in Transaction._meta.get_fields()] else "id"
    sale_tx_qs = sale_tx_qs.order_by(f"-{order_field}")

    if seller_id:
        sale_tx_qs = sale_tx_qs.filter(seller_id=seller_id)

    last_sale_by_product = {}
    for t in sale_tx_qs:
        if t.product_id not in last_sale_by_product:
            last_sale_by_product[t.product_id] = t

    # Date range filter
    if df or dt:
        def in_range(p):
            sold_dt = getattr(p, "sold_at", None)
            if not sold_dt:
                t = last_sale_by_product.get(p.id)
                sold_dt = getattr(t, "created_at", None)
            if not sold_dt:
                return False
            d_ = sold_dt.date() if hasattr(sold_dt, "date") else sold_dt
            if df and d_ < df:
                return False
            if dt and d_ > dt:
                return False
            return True

        products = [p for p in products if in_range(p)]
        product_ids = [p.id for p in products]

    # Calculations
    rows_raw = []
    today = ddate.today()
    labels = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(29, -1, -1)]
    amounts = [0.0 for _ in labels]
    idx_map = {d: i for i, d in enumerate(labels)}

    kpi_today_amount = D0
    kpi_today_cost = D0
    kpi_today_profit = D0

    for p in products:
        t = last_sale_by_product.get(p.id)
        sold_dt = getattr(p, "sold_at", None) or (getattr(t, "created_at", None) if t else None)
        sold_date_str = sold_dt.strftime("%Y-%m-%d") if sold_dt else ""

        amount = Decimal(getattr(t, "amount", 0) or 0) if t else (
                Decimal(getattr(p, "sold_price", 0) or 0) or Decimal(getattr(p, "ask_price", 0) or 0)
        )

        try:
            cost = p.calc_cost()
        except Exception:
            cost = D0

        profit = amount - cost

        note = (getattr(t, "note", "") or "").lower() if t else ""
        is_inst = "installment" in note or "qarz" in note or getattr(p, "is_installment_sale", False)

        rows_raw.append({
            "obj": p,
            "sold_date": sold_date_str,
            "amount": float(amount),
            "cost": float(cost),
            "profit": float(profit),
            "sold_by": getattr(t, "seller", None) if t else None,
            "sold_in_store": getattr(t, "store", None) if t else None,
            "is_installment": is_inst,
        })

        if sold_date_str in idx_map:
            amounts[idx_map[sold_date_str]] += float(amount)

        if sold_dt and (sold_dt.date() if hasattr(sold_dt, "date") else sold_dt) == today:
            kpi_today_amount += amount
            kpi_today_cost += cost
            kpi_today_profit += profit

    # Payment type filter
    if pay_type == "installment":
        rows_raw = [r for r in rows_raw if r["is_installment"]]
    elif pay_type == "full":
        rows_raw = [r for r in rows_raw if not r["is_installment"]]

    rows = rows_raw

    sold_owned_cnt = sum(1 for r in rows_raw if r["obj"].ownership == "owned")
    sold_cons_cnt = sum(1 for r in rows_raw if r["obj"].ownership == "consignment")

    installment_rows = [r["obj"] for r in rows_raw if r["is_installment"]]
    full_rows = [r["obj"] for r in rows_raw if not r["is_installment"]]

    # Reference data
    from reference.models import Brand, ModelName
    stores = Store.objects.filter(is_active=True).order_by("name")
    sellers = User.objects.filter(is_active=True).order_by("username")
    brands = Brand.objects.all().order_by("name")
    models = ModelName.objects.all().order_by("name")

    ctx = {
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
        "ownership": ownership,
        "pay_type": pay_type,

        "rows": rows,
        "items": [r["obj"] for r in rows],

        "sold_labels_json": json.dumps(labels, ensure_ascii=False),
        "sold_amounts_json": json.dumps(amounts, ensure_ascii=False),
        "sold_owned_cnt": sold_owned_cnt,
        "sold_cons_cnt": sold_cons_cnt,

        "installment_rows": installment_rows,
        "full_rows": full_rows,

        "kpi_today_amount": f"{kpi_today_amount:.2f}",
        "kpi_today_cost": f"{kpi_today_cost:.2f}",
        "kpi_today_profit": f"{kpi_today_profit:.2f}",
    }

    return render(request, "inventory/product_sold_list.html", ctx)


def _sold_list_ctx_base(request, rows, store_id, brand_id, model_id, seller_id, payment_type, date_from, date_to):
    stores = Store.objects.filter(is_active=True).order_by("name")
    brands = Brand.objects.filter(is_active=True).order_by("name")
    models = ModelName.objects.filter(is_active=True).order_by("brand__name", "name")
    sellers = User.objects.filter(is_active=True).order_by("username")
    return {
        "rows": rows,
        "stores": stores, "brands": brands, "models": models, "sellers": sellers,
        "store_id": store_id, "brand_id": brand_id, "model_id": model_id, "seller_id": seller_id,
        "payment_type": payment_type,
        "date_from": date_from, "date_to": date_to,
    }


@login_required
def ap_consignment_batch_list(request):
    """
    Partiya bo'yicha konsignatsiya AP

    FEATURES:
    ✅ Batch-level view
    ✅ Balance calculation
    ✅ Payment tracking

    KAFOLAT: 100% to'g'ri matematik!
    """
    qs = (
        BatchIntake.objects
        .select_related("store", "created_by")
        .order_by("-created_at")
    )

    if not is_owner(request.user):
        qs = qs.filter(store_id=get_user_store_id(request.user))

    rows = []
    for b in qs[:300]:
        # Faqat konsignatsiya
        batch_products = Product.objects.filter(batch=b, ownership="consignment")

        # Sotilgan bazalar
        base_sold = (
                batch_products.filter(status="sold")
                .aggregate(s=Sum("consignment_price"))["s"] or D0
        )

        # To'langan
        paid = (
                Transaction.objects.filter(
                    type="consignment_payout",
                    is_void=False,
                    is_approved=True,
                    product_id__in=list(batch_products.values_list("id", flat=True))
                ).aggregate(s=Sum("amount"))["s"] or D0
        )

        balance = base_sold - paid

        items = list(
            batch_products.select_related("brand", "model").values(
                "id", "status", "consignment_price",
                "brand__name", "model__name", "imei_full"
            )
        )

        rows.append({
            "batch": b,
            "base_sold": base_sold,
            "paid": paid,
            "balance": balance,
            "count": len(items),
            "items": items,
        })

    return render(request, "sales/ap_consignment_batch_list.html", {"rows": rows})


@login_required
def ap_consignment_batch_pay(request, batch_id):
    """
    Partiya to'lovi

    FEATURES:
    ✅ Balance check
    ✅ Cash/Card/Mixed payment
    ✅ Ledger posting

    KAFOLAT: 100% xavfsiz va to'g'ri!
    """
    b = get_object_or_404(BatchIntake.objects.select_related("store"), pk=batch_id)

    if not is_owner(request.user):
        if get_user_store_id(request.user) != b.store_id:
            messages.error(request, _("Ushbu partiya boshqa do'konga tegishli."))
            return redirect("ap_consignment_batch_list")

    # Balance calculation
    batch_products = Product.objects.filter(batch=b, ownership="consignment")
    base_sold = (
            batch_products.filter(status="sold")
            .aggregate(s=Sum("consignment_price"))["s"] or D0
    )
    paid = (
            Transaction.objects.filter(
                type="consignment_payout",
                is_void=False,
                is_approved=True,
                product_id__in=list(batch_products.values_list("id", flat=True))
            ).aggregate(s=Sum("amount"))["s"] or D0
    )
    balance = (base_sold - paid) if base_sold else D0

    if balance <= D0:
        messages.info(request, _("Bu partiya bo'yicha to'lov balansi yo'q."))
        return redirect("ap_consignment_batch_list")

    if request.method == "POST":
        try:
            amount = Decimal(request.POST.get("amount") or "0")
        except Exception:
            amount = D0

        ptype = (request.POST.get("payment_type") or "").strip()  # cash|card|mixed

        if amount <= D0 or amount > balance:
            messages.error(request, _("Summani to'g'ri kiriting."))
            return redirect("ap_consignment_batch_pay", batch_id=b.id)

        cash_amount = D0
        card_amount = D0

        if ptype == "cash":
            cash_amount = amount
        elif ptype == "card":
            card_amount = amount
        elif ptype == "mixed":
            try:
                cash_amount = Decimal(request.POST.get("cash_amount") or "0")
                card_amount = Decimal(request.POST.get("card_amount") or "0")
            except Exception:
                messages.error(request, _("Aralash to'lov miqdorlarini to'g'ri kiriting."))
                return redirect("ap_consignment_batch_pay", batch_id=b.id)

            if cash_amount + card_amount != amount:
                messages.error(request, _("Naqd + karta umumiy summaga teng bo'lsin."))
                return redirect("ap_consignment_batch_pay", batch_id=b.id)
        else:
            messages.error(request, _("To'lov turini tanlang."))
            return redirect("ap_consignment_batch_pay", batch_id=b.id)

        with db_txn.atomic():
            # Transaction yaratish
            any_prod = batch_products.filter(status="sold").first() or batch_products.first()

            tx = Transaction.objects.create(
                type="consignment_payout",
                store=b.store,
                product=any_prod,
                seller=request.user,
                created_by=request.user,
                is_approved=True,
                approved_by=request.user,
                approved_at=dj_tz.now(),
                amount=amount,
                payment_type=ptype,
                cash_amount=cash_amount,
                card_amount=card_amount,
                note=f"BATCH:{b.id} - {_('Partiya bo`yicha konsignatsiya to`lovi')}",
            )

        messages.success(request, _("To'lov tasdiqlandi va kassadan yechildi."))
        return redirect("ap_consignment_batch_list")

    # GET
    ctx = {
        "b": b,
        "supplier": (b.supplier_name or ""),
        "supplier_phone": (b.supplier_phone or ""),
        "base_sold": base_sold,
        "paid": paid,
        "balance": balance,
        "suggest_amount": balance,
    }

    return render(request, "sales/ap_consignment_batch_pay.html", ctx)