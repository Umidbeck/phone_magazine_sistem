# sales/views_sell.py - SOTUV VIEW'LARI
"""
Sotuv operatsiyalari - To'liq to'lov va bo'lib to'lash

WORKFLOW:
1. Product tanlash (available)
2. Narx va to'lov turi kiritish
3. Transaction yaratish (avtomatik approved)
4. Komissiya yaratish (signal orqali)
5. Product status yangilash (signal orqali)
"""

from decimal import Decimal
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone as dj_tz
from django.utils.translation import gettext as _

from inventory.models import Product
from sales.forms import SaleForm, InstallmentSaleForm
from sales.models import Transaction, ConsignmentDue
from sales.services import calculate_product_cost, calculate_sale_profit
from core.utils import is_owner


@login_required
def sell_view(request):
    """
    To'liq to'lov bilan sotuv

    GET ?product_id=123
    POST: price, payment_type, cash_amount, card_amount
    """
    product_id = request.GET.get("product_id")
    if not product_id:
        messages.error(request, _("Mahsulot tanlanmagan"))
        return redirect("product_list")

    product = get_object_or_404(
        Product.objects.select_related("store", "brand", "model"),
        pk=product_id,
        status="available"
    )

    # Permission check: o'z do'koni yoki owner
    if not is_owner(request.user):
        if getattr(request.user, "store_id", None) != product.store_id:
            return HttpResponseForbidden(_("Bu mahsulot boshqa do'konga tegishli"))

    if request.method == "POST":
        form = SaleForm(request.POST)
        if form.is_valid():
            price = form.cleaned_data["price"]
            ptype = form.cleaned_data["payment_type"]
            cash = form.cleaned_data["cash_amount"]
            card = form.cleaned_data["card_amount"]

            # Tannarx va foyda
            cost = calculate_product_cost(product)
            profit = calculate_sale_profit(price, product)

            with db_transaction.atomic():
                # Transaction yaratish
                tx = Transaction.objects.create(
                    type="sale",
                    product=product,
                    store=product.store,
                    seller=request.user,
                    created_by=request.user,
                    amount=price,
                    payment_type=ptype,
                    cash_amount=cash,
                    card_amount=card,
                    cost=cost,
                    profit=profit,
                    # Avtomatik approved
                    is_approved=True,
                    approved_by=request.user,
                    approved_at=dj_tz.now()
                )

                # Product status (signal orqali ham o'zgaradi, lekin ichkarida ham qilsak yaxshi)
                product.status = "sold"
                product.sold_at = dj_tz.now()
                product.save(update_fields=["status", "sold_at"])

                # Konsignatsiya due (agar kerak bo'lsa)
                if product.ownership == "consignment":
                    ConsignmentDue.objects.get_or_create(
                        product=product,
                        defaults={
                            "store": product.store,
                            "base_amount": product.consignment_price or Decimal("0.00"),
                            "created_by": request.user,
                            "is_approved": False
                        }
                    )

            messages.success(request, _("Sotuv muvaffaqiyatli yakunlandi!"))
            return redirect("product_detail", pk=product.id)
        else:
            messages.error(request, _("Xatolarni tuzating"))
    else:
        # GET - forma ko'rsatish
        form = SaleForm(initial={
            "price": product.ask_price or Decimal("0.00"),
            "payment_type": "cash"
        })

    context = {
        "form": form,
        "product": product,
        "estimated_cost": calculate_product_cost(product),
        "estimated_profit": calculate_sale_profit(
            product.ask_price or Decimal("0.00"),
            product
        )
    }
    return render(request, "sales/sell.html", context)


@login_required
def sell_installment(request):
    """
    Bo'lib to'lash bilan sotuv

    Workflow:
    1. To'liq narx va oldindan to'lov
    2. Sale transaction yaratish
    3. Debt_out transaction yaratish (qolgan qarz uchun)
    """
    product_id = request.GET.get("product_id")
    if not product_id:
        messages.error(request, _("Mahsulot tanlanmagan"))
        return redirect("product_list")

    product = get_object_or_404(
        Product.objects.select_related("store", "brand", "model"),
        pk=product_id,
        status="available"
    )

    # Permission check
    if not is_owner(request.user):
        if getattr(request.user, "store_id", None) != product.store_id:
            return HttpResponseForbidden(_("Bu mahsulot boshqa do'konga tegishli"))

    if request.method == "POST":
        form = InstallmentSaleForm(request.POST)
        if form.is_valid():
            total_price = form.cleaned_data["total_price"]
            ptype = form.cleaned_data["payment_type"]
            upfront_cash = form.cleaned_data["upfront_cash"]
            upfront_card = form.cleaned_data["upfront_card"]
            upfront_total = form.cleaned_data["upfront_total"]
            debt_amount = form.cleaned_data["debt_amount"]
            customer_name = form.cleaned_data["customer_name"]
            customer_phone = form.cleaned_data.get("customer_phone") or ""
            note = form.cleaned_data.get("note") or ""

            # Tannarx va foyda
            cost = calculate_product_cost(product)
            profit = calculate_sale_profit(total_price, product)

            with db_transaction.atomic():
                # 1. Sale transaction
                sale_tx = Transaction.objects.create(
                    type="sale",
                    product=product,
                    store=product.store,
                    seller=request.user,
                    created_by=request.user,
                    amount=total_price,
                    payment_type=ptype,
                    cash_amount=upfront_cash,
                    card_amount=upfront_card,
                    cost=cost,
                    profit=profit,
                    debtor_name=customer_name,
                    debtor_phone=customer_phone,
                    note=note,
                    # Avtomatik approved
                    is_approved=True,
                    approved_by=request.user,
                    approved_at=dj_tz.now()
                )

                # 2. Product status
                product.status = "sold"
                product.sold_at = dj_tz.now()
                product.save(update_fields=["status", "sold_at"])

                # 3. Debt transaction (agar qarz bo'lsa)
                if debt_amount > Decimal("0.00"):
                    Transaction.objects.create(
                        type="debt_out",
                        product=product,
                        store=product.store,
                        seller=request.user,
                        created_by=request.user,
                        amount=debt_amount,
                        debtor_name=customer_name,
                        debtor_phone=customer_phone,
                        note=note,
                        related_sale=sale_tx,
                        debtor_group=sale_tx.debtor_group,  # O'sha group
                        # Avtomatik approved (sotuv bilan birga)
                        is_approved=True,
                        approved_by=request.user,
                        approved_at=dj_tz.now()
                    )

                # 4. Konsignatsiya due
                if product.ownership == "consignment":
                    ConsignmentDue.objects.get_or_create(
                        product=product,
                        defaults={
                            "store": product.store,
                            "base_amount": product.consignment_price or Decimal("0.00"),
                            "created_by": request.user,
                            "is_approved": False
                        }
                    )

            messages.success(request, _("Bo'lib to'lash sotuvi yakunlandi!"))
            return redirect("product_detail", pk=product.id)
        else:
            messages.error(request, _("Xatolarni tuzating"))
    else:
        form = InstallmentSaleForm(initial={
            "total_price": product.ask_price or Decimal("0.00"),
            "payment_type": "cash"
        })

    context = {
        "form": form,
        "product": product,
        "estimated_cost": calculate_product_cost(product),
    }
    return render(request, "sales/sell_installment.html", context)


@login_required
def sale_return_by_tx(request, tx_id):
    """
    Sotuvni qaytarish (transaction ID bo'yicha)

    Mantiq:
    1. O'sha kun qaytarish → komissiya rescinded
    2. Keyingi kun → manfiy komissiya yaratiladi
    """
    tx = get_object_or_404(
        Transaction.objects.select_related("product", "store"),
        pk=tx_id,
        type="sale",
        is_void=False
    )

    # Permission check
    if not is_owner(request.user):
        if getattr(request.user, "store_id", None) != tx.store_id:
            return HttpResponseForbidden(_("Ruxsat yo'q"))

    # Konsignatsiya payout tekshiruvi
    if tx.product_id:
        has_payout = Transaction.objects.filter(
            type="consignment_payout",
            product_id=tx.product_id,
            is_approved=True,
            is_void=False
        ).exists()

        if has_payout:
            messages.error(request, _(
                "Bu mahsulot uchun konsignatsiya to'lovi tasdiqlangan. "
                "Avval uni bekor qiling."
            ))
            return redirect("product_detail", pk=tx.product_id)

    with db_transaction.atomic():
        # Transaction void qilish
        tx.is_void = True
        tx.save(update_fields=["is_void"])

        # Product qaytarish
        if tx.product:
            tx.product.status = "available"
            tx.product.sold_at = None
            tx.product.save(update_fields=["status", "sold_at"])

        # Bog'langan debt_out'larni void qilish (pending bo'lsa)
        Transaction.objects.filter(
            related_sale=tx,
            type="debt_out",
            is_approved=False
        ).update(is_void=True)

        # Konsignatsiya due (pending)'ni o'chirish
        if tx.product and tx.product.ownership == "consignment":
            try:
                due = ConsignmentDue.objects.get(product=tx.product)
                if not due.is_approved:
                    due.delete()
            except ConsignmentDue.DoesNotExist:
                pass

    messages.success(request, _("Sotuv qaytarildi"))
    return redirect("product_detail", pk=tx.product_id if tx.product else "product_list")


@login_required
def sale_return_by_product(request, product_id):
    """
    Sotuvni qaytarish (product ID bo'yicha)

    Eng oxirgi void bo'lmagan sotuvni topib qaytaradi
    """
    product = get_object_or_404(
        Product.objects.select_related("store"),
        pk=product_id,
        status="sold"
    )

    # Permission check
    if not is_owner(request.user):
        if getattr(request.user, "store_id", None) != product.store_id:
            return HttpResponseForbidden(_("Ruxsat yo'q"))

    # Eng oxirgi sotuvni topish
    tx = Transaction.objects.filter(
        type="sale",
        product=product,
        is_void=False
    ).order_by("-created_at").first()

    if tx:
        return sale_return_by_tx(request, tx.id)
    else:
        messages.error(request, _("Sotuv topilmadi"))
        return redirect("product_detail", pk=product.id)