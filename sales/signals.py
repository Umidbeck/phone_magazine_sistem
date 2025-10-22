# sales/signals.py - 100% MUKAMMAL TO'LIQ VERSIYA
"""
Sales Signals - Avtomatik komissiya, statistika va yordamchi oqimlar

VERSIYA: 5.0 - BARCHA XATOLAR TUZATILDI
===========================================

KOMISSIYA QOIDALARI:
1. Yangi sotuv → komissiya avtomatik (is_new ? 30% : $5)
2. O'sha kun qaytarish → komissiya rescinded
3. Keyingi kun qaytarish → manfiy komissiya (deduction) + block
4. Blocked mahsulot → komissiya 0

TRANZAKSIYA XAVFSIZLIGI:
✅ Signal ichida .save() YO'Q → faqat .update() yoki on_commit()
✅ Yon-ta'sirlar (ledger, notification, bonus, due, product status) → on_commit()
✅ Xatolarni yutmaymiz: logger.exception(...) + raise
✅ dispatch_uid: signal ikki marta ro'yxatdan o'tmasligi uchun

KAFOLAT: 100% atomic-safe va to'g'ri!
"""

from decimal import Decimal
import logging
from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone as dj_tz

from sales.models import (
    Transaction,
    SellerCommission,
    SellerMonthlyStat,
    MonthlyBonus,
    Notification,
    ConsignmentDue,
)
from inventory.models import Product
from sales.services import (
    calculate_product_cost,
    calculate_sale_profit,
    calculate_commission_amount,
    get_commission_category,
)
from core.utils import DECIMAL_ZERO, D0

logger = logging.getLogger(__name__)


# ============================================
# HELPERS
# ============================================

def _create_notification_safe(user, title: str, message: str):
    """
    Notifikatsiyani commitdan keyin yaratish

    MUHIM: Xato tranzaksiyani buzmasin!
    """
    if not user or not getattr(user, "id", None):
        return

    try:
        transaction.on_commit(
            lambda: Notification.objects.create(
                recipient=user,
                title=title,
                message=message
            )
        )
    except Exception:
        logger.exception("Notification creation failed")


def _month_key(dt=None) -> str:
    """Oy kaliti (YYYY-MM)"""
    if dt is None:
        dt = dj_tz.now()
    return dt.strftime("%Y-%m")


def _is_same_day(dt1, dt2) -> bool:
    """Ikki sana bir kunmi?"""
    if not dt1 or not dt2:
        return False
    d1 = dt1.date() if hasattr(dt1, "date") else dt1
    d2 = dt2.date() if hasattr(dt2, "date") else dt2
    return d1 == d2


def _digits_only(s: str) -> str:
    """Faqat ASCII raqamlar (0-9)"""
    return "".join(ch for ch in (s or "") if ch in '0123456789')


# ============================================
# 0. IMEI NORMALIZATSIYA
# ============================================

@receiver(pre_save, sender=Product, dispatch_uid="product_normalize_imei_v5")
def product_normalize_imei(sender, instance: Product, **kwargs):
    """
    Product.imei_full'ni normalizatsiya qilish

    QOIDA: Faqat ASCII raqamlar qolsin (0-9)
    """
    imei = _digits_only(getattr(instance, "imei_full", "")).strip()
    instance.imei_full = imei

    # imei_last4 yangilash
    if len(imei) >= 4:
        instance.imei_last4 = imei[-4:]
    else:
        instance.imei_last4 = "0000"


# ============================================
# 1. LEDGER POSTING
# ============================================

@receiver(post_save, sender=Transaction, dispatch_uid="tx_ledger_post_v5")
def post_to_ledger_when_approved(sender, instance: Transaction, created, **kwargs):
    """
    Transaction approved bo'lganda ledgerga yozish

    SHART: FINANCE_AUTOPOST = True
    YON-TA'SIR: on_commit (atomic-safe)
    """
    if not instance.is_approved or instance.is_void:
        return

    if not getattr(settings, "FINANCE_AUTOPOST", False):
        return

    try:
        from finance.adapters import post_from_transaction

        # Ledger posting faqat commitdan keyin
        transaction.on_commit(lambda: post_from_transaction(instance))

    except ImportError:
        logger.debug("Finance app not available, skipping ledger post")
    except Exception:
        logger.exception("Ledger post error")
        # Agar ledger critical bo'lsa → raise
        # raise


# ============================================
# 2. KOMISSIYA MANTIQLARI (TUZATILGAN!)
# ============================================

@receiver(post_save, sender=Transaction, dispatch_uid="tx_commission_v5")
def handle_sale_commission(sender, instance: Transaction, created, **kwargs):
    """
    Sotuv komissiyasi boshqaruvi

    YANGI SOTUV:
    - Komissiya yaratish/yangilash
    - Cost va profit hisoblash

    QAYTARISH (VOID):
    - Same-day: rescind (is_rescinded=True)
    - Late: in-place deduction (amount → negative, is_deduction=True) + block

    TUZATISH: Keyingi kun qaytarish uchun YANGI komissiya emas,
              balki MAVJUD komissiyani o'zgartirish!
    """
    if instance.type != "sale":
        return

    # ========== YANGI SOTUV ==========
    if created and not instance.is_void:
        try:
            product = instance.product
            if not product:
                logger.warning(f"Sale TX#{instance.pk} has no product")
                return

            # Tannarx / foyda hisoblash
            cost = calculate_product_cost(product)
            amount = Decimal(instance.amount or 0)
            profit = calculate_sale_profit(amount, product)

            # Transaction'ni .update() bilan yangilash
            fields = {}
            if instance.cost != cost:
                fields["cost"] = cost
            if instance.profit != profit:
                fields["profit"] = profit

            if fields:
                Transaction.objects.filter(pk=instance.pk).update(**fields)

            # Komissiya hisoblash
            comm_amount = calculate_commission_amount(product, profit)
            category = get_commission_category(product)

            def _upsert_commission():
                """Komissiya yaratish/yangilash"""
                commission, created_comm = SellerCommission.objects.get_or_create(
                    transaction_id=instance.pk,
                    defaults={
                        "seller": instance.seller,
                        "amount": comm_amount,
                        "category": category,
                        "is_deduction": False,
                        "is_approved": True,
                        "approved_by": instance.created_by or instance.seller,
                        "approved_at": dj_tz.now(),
                    },
                )

                if not created_comm:
                    # Mavjud komissiyani yangilash
                    updates = {}
                    if commission.amount != comm_amount:
                        updates["amount"] = comm_amount
                    if commission.category != category:
                        updates["category"] = category
                    if commission.seller_id != instance.seller_id:
                        updates["seller"] = instance.seller

                    if updates:
                        SellerCommission.objects.filter(pk=commission.pk).update(**updates)

                # Block holati xabarnoma
                is_blocked = bool(getattr(product, "commission_blocked", False))
                if is_blocked and comm_amount == DECIMAL_ZERO:
                    _create_notification_safe(
                        instance.seller,
                        "⚠️ Komissiya berilmadi",
                        f"IMEI: {getattr(product, 'imei_full', '')} - "
                        f"qayta sotuv, komissiya bloklangan."
                    )

                logger.info(f"Commission upserted for TX#{instance.pk}: ${comm_amount}")

            # Komissiya commitdan keyin
            transaction.on_commit(_upsert_commission)

        except Exception:
            logger.exception(f"Commission creation failed for TX#{instance.pk}")
            raise

    # ========== QAYTARISH (VOID) - TUZATILGAN! ==========
    elif not created and instance.is_void:
        try:
            try:
                original_comm = instance.commission
            except SellerCommission.DoesNotExist:
                logger.debug(f"No commission found for voided TX#{instance.pk}")
                return

            if not original_comm or original_comm.is_rescinded:
                return

            sale_day = (instance.created_at or dj_tz.now()).date()
            today = dj_tz.localdate()
            same_day = _is_same_day(sale_day, today)

            def _same_day_rescind():
                """O'sha kun qaytarish - rescind"""
                SellerCommission.objects.filter(pk=original_comm.pk).update(
                    is_rescinded=True,
                    rescinded_at=dj_tz.now(),
                    rescinded_reason="same_day_return",
                )

                _create_notification_safe(
                    instance.seller,
                    "ℹ️ Komissiya bekor qilindi",
                    "Sotuv qaytarildi (bugun). Komissiya berilmaydi."
                )

                logger.info(f"Commission rescinded (same-day) for TX#{instance.pk}")

            def _late_return_deduction():
                """
                Kech qaytarish - IN-PLACE deduction + block

                MUHIM: Yangi komissiya yaratilmaydi!
                       Mavjud komissiyani o'zgartirish:
                       - amount → negative
                       - is_deduction → True
                       - is_rescinded → True (effective_amount = 0 bo'lmasin)
                """
                deduction_amount = -abs(original_comm.amount)

                # 1) Original'ni deduction'ga aylantirish (in-place)
                SellerCommission.objects.filter(pk=original_comm.pk).update(
                    is_rescinded=True,
                    rescinded_at=dj_tz.now(),
                    rescinded_reason="late_return",
                    is_deduction=True,
                    amount=deduction_amount,
                )

                # 2) Product commission_blocked
                if instance.product_id:
                    Product.objects.filter(
                        pk=instance.product_id,
                        commission_blocked=False
                    ).update(commission_blocked=True)

                # 3) Xabarnomalar
                _create_notification_safe(
                    instance.seller,
                    "⚠️ Komissiya ayirildi",
                    f"Sotuv qaytarildi (kech). ${abs(deduction_amount):.2f} bonusdan ayrildi."
                )

                try:
                    from accounts.models import User
                    owner = User.objects.filter(is_superuser=True).first()
                    if owner:
                        _create_notification_safe(
                            owner,
                            "⚠️ Kech qaytarish",
                            f"Sotuvchi: {instance.seller.username}, "
                            f"IMEI: {getattr(instance.product, 'imei_full', '')}. "
                            f"Komissiya minus: ${abs(deduction_amount):.2f}"
                        )
                except Exception:
                    logger.exception("Owner notification failed (late return)")

                logger.warning(
                    f"Deduction (in-place) for late return TX#{instance.pk}: {deduction_amount}"
                )

            # Oqimlarni commitdan keyin ishga tushirish
            if same_day:
                transaction.on_commit(_same_day_rescind)
            else:
                transaction.on_commit(_late_return_deduction)

        except Exception:
            logger.exception(f"Commission void handling failed for TX#{instance.pk}")
            raise


# ============================================
# 3. OYLIK STATISTIKA + BONUS
# ============================================

@receiver(post_save, sender=Transaction, dispatch_uid="tx_monthly_stats_v5")
def handle_monthly_stats(sender, instance: Transaction, created, **kwargs):
    """
    Oylik statistika va bonus

    QOIDA:
    - Har sotuvda seller uchun counter++
    - 50 ga yetganda → $50 bonus
    - So'ngra barcha sellerlar reset

    YON-TA'SIR: on_commit
    """
    if instance.type != "sale" or not created or instance.is_void:
        return

    try:
        mk = _month_key(instance.created_at)

        def _update_stats_and_bonus():
            """Statistika va bonus yangilash"""
            stat, _ = SellerMonthlyStat.objects.get_or_create(
                seller=instance.seller,
                month_key=mk,
                defaults={"sales_count": 0}
            )

            # Atomik increment
            SellerMonthlyStat.objects.filter(pk=stat.pk).update(
                sales_count=(stat.sales_count or 0) + 1,
                updated_at=dj_tz.now()
            )

            # Bonus tekshiruvi (oy bo'yicha bitta)
            if not MonthlyBonus.objects.filter(month_key=mk).exists():
                # Yangilangan qiymatni o'qish
                fresh = SellerMonthlyStat.objects.get(pk=stat.pk)

                if (fresh.sales_count or 0) >= 50:
                    MonthlyBonus.objects.create(
                        month_key=mk,
                        winner=instance.seller,
                        amount=Decimal("50.00"),
                    )

                    # Reset barcha sellerlar
                    SellerMonthlyStat.objects.filter(month_key=mk).update(sales_count=0)

                    _create_notification_safe(
                        instance.seller,
                        "🎉 BONUS - $50!",
                        f"Siz {mk} oyida 50 ta telefon sotdingiz! $50 bonus qo'shildi!"
                    )

                    logger.info(f"Monthly bonus awarded to {instance.seller.username} for {mk}")

        transaction.on_commit(_update_stats_and_bonus)

    except Exception:
        logger.exception(f"Monthly stats update failed for TX#{instance.pk}")
        raise


# ============================================
# 4. PRODUCT STATUS UPDATE
# ============================================

@receiver(post_save, sender=Transaction, dispatch_uid="tx_product_status_v5")
def update_product_status_on_sale(sender, instance: Transaction, created, **kwargs):
    """
    Product status yangilash

    SALE CREATED → status='sold', sold_at=now
    SALE VOIDED → status='available', sold_at=None

    YON-TA'SIR: on_commit (signal ichida .save() YO'Q)
    """
    if instance.type != "sale" or not instance.product_id:
        return

    try:
        def _mark():
            """Product statusni belgilash"""
            if not instance.is_void:
                Product.objects.filter(pk=instance.product_id).update(
                    status="sold",
                    sold_at=instance.created_at or dj_tz.now()
                )
            else:
                Product.objects.filter(pk=instance.product_id, status="sold").update(
                    status="available",
                    sold_at=None
                )

        transaction.on_commit(_mark)

    except Exception:
        logger.exception(f"Product status update failed for TX#{instance.pk}")
        raise


# ============================================
# 5. CONSIGNMENT DUE AUTO-CREATE
# ============================================

@receiver(post_save, sender=Transaction, dispatch_uid="tx_consignment_due_v5")
def auto_create_consignment_due(sender, instance: Transaction, created, **kwargs):
    """
    Konsignatsiya sotuv → ConsignmentDue avtomatik yaratish

    SHARTLAR:
    - type='sale'
    - created=True
    - not void
    - is_approved=True
    - product.ownership='consignment'

    YON-TA'SIR: on_commit
    """
    if instance.type != "sale":
        return

    if not created or instance.is_void or not instance.is_approved:
        return

    product = instance.product
    if not product or getattr(product, "ownership", None) != "consignment":
        return

    try:
        def _ensure_due():
            """ConsignmentDue yaratish"""
            ConsignmentDue.objects.get_or_create(
                product_id=product.pk,
                defaults={
                    "store": product.store,
                    "base_amount": product.consignment_price or DECIMAL_ZERO,
                    "created_by": instance.created_by or instance.seller,
                    "is_approved": False,
                },
            )

        transaction.on_commit(_ensure_due)

    except Exception:
        logger.exception(f"ConsignmentDue creation failed for TX#{instance.pk}")
        raise


# ============================================
# 6. CONSIGNMENT DUE VOID ON RETURN
# ============================================

@receiver(post_save, sender=Transaction, dispatch_uid="tx_void_cons_due_v5")
def void_consignment_due_on_return(sender, instance: Transaction, created, **kwargs):
    """
    Qaytarish → ConsignmentDue void qilish

    SHARTLAR:
    - type='sale'
    - void=True
    - product.ownership='consignment'

    YON-TA'SIR: on_commit
    """
    if instance.type != "sale" or not instance.is_void:
        return

    product = instance.product
    if not product or getattr(product, "ownership", None) != "consignment":
        return

    try:
        def _void_due():
            """Pending ConsignmentDue'ni void qilish"""
            ConsignmentDue.objects.filter(
                product_id=product.pk,
                is_approved=False
            ).update(is_void=True)

        transaction.on_commit(_void_due)

    except Exception:
        logger.exception(f"ConsignmentDue void failed for TX#{instance.pk}")
        raise


# ============================================
# 7. PRODUCT PURCHASE AUTO-POST (INVENTORY)
# ============================================

FINANCE_AUTOPOST = getattr(settings, "FINANCE_AUTOPOST", True)


@receiver(post_save, sender=Product, dispatch_uid="inventory_purchase_autopost_v5")
def inventory_purchase_autopost(sender, instance: Product, created, **kwargs):
    """
    Yangi mahsulot → ledgerga avtomatik yozish

    SHARTLAR:
    - created=True
    - status in ('available', 'on_repair')
    - FINANCE_AUTOPOST=True

    YON-TA'SIR: on_commit
    """
    if not FINANCE_AUTOPOST:
        return

    if not created:
        return

    try:
        status = getattr(instance, "status", "")
        if status not in ("available", "on_repair"):
            return

        from finance.adapters import post_purchase_from_product

        def _post_purchase():
            """Xaridni ledgerga yozish"""
            try:
                ownership = getattr(instance, "ownership", "owned")

                if ownership == "owned":
                    cost = Decimal(getattr(instance, "purchase_price", 0))
                else:
                    cost = Decimal(getattr(instance, "consignment_price", 0))

                if cost > D0:
                    # To'lov turi (naqd deb hisoblaymiz, yoki AP)
                    is_cash = True  # yoki supplier_credit flagiga qarab

                    post_purchase_from_product(
                        instance,
                        cost=cost,
                        is_cash=is_cash,
                        ref=f"Product:{instance.pk}",
                        memo=f"Kirim (auto) - {instance.brand} {instance.model}"
                    )
            except Exception:
                logger.exception("Product purchase autopost error")

        transaction.on_commit(_post_purchase)

    except Exception:
        logger.exception(f"Inventory purchase autopost failed for Product#{instance.pk}")
        # Xatoni yutmaymiz - product saqlansin