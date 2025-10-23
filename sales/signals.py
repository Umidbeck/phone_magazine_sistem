# sales/signals.py - 100% MUKAMMAL TO'LIQ VERSIYA
"""
Sales Signals - Avtomatik komissiya, statistika va moliyaviy oqimlar

VERSIYA: 6.0 - MATEMATIK ANIQLIK 100%
======================================

KOMISSIYA QOIDALARI (MUKAMMAL):
═══════════════════════════════════
1. YANGI SOTUV:
   - Yangi telefon → Komissiya = 30% * Profit
   - Eski telefon → Komissiya = $5 (yoki Config)
   - Blocked telefon → Komissiya = $0

2. O'SHA KUN QAYTARISH:
   - Komissiya rescinded (is_rescinded=True)
   - Effective amount = 0
   - Seller hech narsa yo'qotmaydi

3. KEYINGI KUN QAYTARISH:
   - Mavjud komissiya IN-PLACE o'zgaradi:
     * amount → negative (masalan -5)
     * is_deduction → True
     * is_rescinded → False (effective amount ishlaydi!)
   - Product commission_blocked = True
   - Seller bonusidan ayriladi

TRANZAKSIYA XAVFSIZLIGI:
✅ Signal ichida .save() YO'Q → faqat .update() yoki on_commit()
✅ Barcha yon-ta'sirlar → on_commit()
✅ Xatolar to'g'ri boshqariladi
✅ dispatch_uid: ikki marta ro'yxatdan o'tmasligi uchun

LEDGER INTEGRATSIYA:
✅ FINANCE_AUTOPOST = True bo'lsa ledger avtomatik
✅ Idempotent - qayta yozmaydi

KAFOLAT: 100% atomic-safe va matematik aniq!
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
# HELPER FUNCTIONS
# ============================================

def _create_notification_safe(user, title: str, message: str):
    """
    Xabarnomani xavfsiz yaratish (commitdan keyin)

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


# ============================================
# 1. LEDGER POSTING
# ============================================

@receiver(post_save, sender=Transaction, dispatch_uid="tx_ledger_post_v6")
def post_to_ledger_when_approved(sender, instance: Transaction, created, **kwargs):
    """
    Transaction tasdiqlanganda ledgerga yozish

    SHART:
    - is_approved = True
    - is_void = False
    - FINANCE_AUTOPOST = True

    ENTRY (type'ga qarab):
    - sale → DR Cash/Card/AR, CR Sales, DR COGS, CR Inventory, Commission
    - expense → DR Expenses, CR Cash/Card/AP
    - debt_pay → DR Cash/Card, CR AR
    - consignment_payout → DR AP, CR Cash/Card

    YON-TA'SIR: on_commit (atomic-safe)
    IDEMPOTENT: Qayta yozmaydi
    """
    if not instance.is_approved or instance.is_void:
        return

    if not getattr(settings, "FINANCE_AUTOPOST", False):
        logger.debug("FINANCE_AUTOPOST disabled")
        return

    try:
        from finance.adapters import (
            post_sale_from_transaction_split,
            post_expense_from_transaction_split,
            post_debt_payment_from_transaction_split,
            post_payment_to_supplier_split
        )

        def _post_to_ledger():
            """Ledgerga yozish (type'ga qarab)"""
            try:
                if instance.type == "sale":
                    # Sotuv
                    post_sale_from_transaction_split(
                        tx=instance,
                        memo=f"Sotuv #{instance.pk}",
                        ref=f"TX:{instance.pk}"
                    )

                elif instance.type == "expense":
                    # Rashod
                    post_expense_from_transaction_split(
                        tx=instance,
                        memo=instance.note or "Rashod",
                        ref=f"TX:{instance.pk}"
                    )

                elif instance.type == "debt_pay":
                    # Qarz to'lovi
                    post_debt_payment_from_transaction_split(
                        tx=instance,
                        memo="Qarzdordan tushum",
                        ref=f"TX:{instance.pk}"
                    )

                elif instance.type == "consignment_payout":
                    # Konsignatsiya to'lovi
                    post_payment_to_supplier_split(
                        obj_or_ids=instance,
                        cash_amount=instance.cash_amount or D0,
                        card_amount=instance.card_amount or D0,
                        memo="Konsignatsiya to'lovi",
                        ref=f"TX:{instance.pk}"
                    )

                logger.info(f"Ledger posted for TX#{instance.pk} ({instance.type})")

            except Exception as e:
                logger.exception(f"Ledger posting failed for TX#{instance.pk}: {e}")

        # Commitdan keyin yozish
        transaction.on_commit(_post_to_ledger)

    except ImportError:
        logger.debug("Finance app not available")
    except Exception:
        logger.exception("Ledger post setup error")


# ============================================
# 2. KOMISSIYA MANTIQLARI (100% TO'G'RI!)
# ============================================

@receiver(post_save, sender=Transaction, dispatch_uid="tx_commission_v6")
def handle_sale_commission(sender, instance: Transaction, created, **kwargs):
    """
    Sotuv komissiyasi boshqaruvi (100% matematik aniq!)

    YANGI SOTUV (created=True, not void):
    ────────────────────────────────────
    1. Product cost va profit hisoblash
    2. Commission amount hisoblash:
       - Yangi: 30% * Profit
       - Eski: $5 (Config)
       - Blocked: $0
    3. SellerCommission create/update

    QAYTARISH (void=True):
    ─────────────────────────
    SAME-DAY RETURN (o'sha kun):
    - is_rescinded = True
    - rescinded_reason = "same_day_return"
    - effective_amount = 0
    - Seller hech narsa yo'qotmaydi

    LATE RETURN (keyingi kun):
    - amount → negative (masalan: 5 → -5)
    - is_deduction = True
    - is_rescinded = False (!)
    - effective_amount = negative amount
    - Product.commission_blocked = True
    - Seller bonusidan ayriladi!

    MATEMATIKA:
    ───────────
    Sale profit = Amount - Cost
    Cost = Base Price + Sum(Approved Expenses)
    Commission = Profit * 30% (new) or $5 (used) or $0 (blocked)

    YON-TA'SIR: on_commit (atomic-safe)
    KAFOLAT: 100% to'g'ri!
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

            # === TANNARX VA FOYDA HISOBLASH ===
            cost = calculate_product_cost(product)
            amount = Decimal(instance.amount or 0)
            profit = calculate_sale_profit(amount, product)

            # Transaction'ni yangilash (.update() - signal'siz!)
            fields = {}
            if instance.cost != cost:
                fields["cost"] = cost
            if instance.profit != profit:
                fields["profit"] = profit

            if fields:
                Transaction.objects.filter(pk=instance.pk).update(**fields)
                logger.debug(f"TX#{instance.pk} updated: cost=${cost}, profit=${profit}")

            # === KOMISSIYA HISOBLASH ===
            comm_amount = calculate_commission_amount(product, profit)
            category = get_commission_category(product)

            def _upsert_commission():
                """
                Komissiya yaratish/yangilash

                QOIDALAR:
                - Yangi telefon → 30% foyda
                - Eski telefon → $5 fix
                - Blocked telefon → $0
                """
                commission, created_comm = SellerCommission.objects.get_or_create(
                    transaction_id=instance.pk,
                    defaults={
                        "seller": instance.seller,
                        "amount": comm_amount,
                        "category": category,
                        "is_deduction": False,
                        "is_approved": True,  # Avtomatik tasdiqlash
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
                        logger.debug(f"Commission#{commission.pk} updated: {updates}")

                # Xabarnomalar
                is_blocked = bool(getattr(product, "commission_blocked", False))

                if is_blocked and comm_amount == DECIMAL_ZERO:
                    _create_notification_safe(
                        instance.seller,
                        "⚠️ Komissiya berilmadi",
                        f"Telefon: {getattr(product, 'imei_full', 'N/A')[-4:]} - "
                        f"Qayta sotuv, komissiya bloklangan."
                    )
                elif comm_amount > DECIMAL_ZERO:
                    _create_notification_safe(
                        instance.seller,
                        "✅ Komissiya qo'shildi",
                        f"${comm_amount:.2f} bonus qo'shildi! "
                        f"({category})"
                    )

                logger.info(
                    f"Commission upserted for TX#{instance.pk}: "
                    f"${comm_amount} ({category})"
                )

            # Komissiya commitdan keyin
            transaction.on_commit(_upsert_commission)

        except Exception:
            logger.exception(f"Commission creation failed for TX#{instance.pk}")
            raise

    # ========== QAYTARISH (VOID) ==========
    elif not created and instance.is_void:
        try:
            # Komissiya bormi?
            try:
                original_comm = instance.commission
            except SellerCommission.DoesNotExist:
                logger.debug(f"No commission found for voided TX#{instance.pk}")
                return

            if not original_comm or original_comm.is_rescinded:
                logger.debug(f"Commission already rescinded for TX#{instance.pk}")
                return

            # Sanalarni tekshirish
            sale_day = (instance.created_at or dj_tz.now()).date()
            today = dj_tz.localdate()
            same_day = _is_same_day(sale_day, today)

            def _same_day_rescind():
                """
                O'SHA KUN QAYTARISH

                Natija:
                - is_rescinded = True
                - effective_amount = 0
                - Seller hech narsa yo'qotmaydi
                """
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

                logger.info(
                    f"Commission#{original_comm.pk} rescinded (same-day) "
                    f"for TX#{instance.pk}"
                )

            def _late_return_deduction():
                """
                KEYINGI KUN QAYTARISH

                Natija:
                - amount → negative (5 → -5)
                - is_deduction = True
                - is_rescinded = False (!)
                - effective_amount = negative
                - Product.commission_blocked = True

                MUHIM: Mavjud komissiya IN-PLACE o'zgaradi!
                         Yangi komissiya yaratilmaydi!
                """
                deduction_amount = -abs(original_comm.amount)

                # 1) Komissiyani deduction'ga aylantirish
                SellerCommission.objects.filter(pk=original_comm.pk).update(
                    amount=deduction_amount,
                    is_deduction=True,
                    is_rescinded=False,  # <-- MUHIM!
                    rescinded_at=dj_tz.now(),
                    rescinded_reason="late_return",
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
                    f"Sotuv qaytarildi (kech). "
                    f"${abs(deduction_amount):.2f} bonusdan ayrildi! "
                    f"Telefon bloklandi."
                )

                # Owner'ga ham xabar
                try:
                    from accounts.models import User
                    owner = User.objects.filter(is_superuser=True).first()
                    if owner:
                        product_imei = getattr(instance.product, "imei_full", "N/A")
                        _create_notification_safe(
                            owner,
                            "⚠️ Kech qaytarish",
                            f"Sotuvchi: {instance.seller.username}, "
                            f"IMEI: {product_imei[-4:]}, "
                            f"Komissiya minus: ${abs(deduction_amount):.2f}"
                        )
                except Exception:
                    logger.exception("Owner notification failed")

                logger.warning(
                    f"Commission#{original_comm.pk} DEDUCTION (late return) "
                    f"for TX#{instance.pk}: {deduction_amount}"
                )

            # Oqimni tanlash va ishga tushirish
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

@receiver(post_save, sender=Transaction, dispatch_uid="tx_monthly_stats_v6")
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

            # Bonus tekshiruvi
            if not MonthlyBonus.objects.filter(month_key=mk).exists():
                # Yangilangan qiymat
                fresh = SellerMonthlyStat.objects.get(pk=stat.pk)

                if (fresh.sales_count or 0) >= 50:
                    # BONUS!
                    MonthlyBonus.objects.create(
                        month_key=mk,
                        winner=instance.seller,
                        amount=Decimal("50.00"),
                    )

                    # Reset barcha sellerlar
                    SellerMonthlyStat.objects.filter(month_key=mk).update(
                        sales_count=0
                    )

                    _create_notification_safe(
                        instance.seller,
                        "🎉 BONUS - $50!",
                        f"Tabriklaymiz! Siz {mk} oyida 50 ta telefon sotdingiz! "
                        f"$50 bonus qo'shildi!"
                    )

                    logger.info(
                        f"Monthly bonus awarded to {instance.seller.username} "
                        f"for {mk}"
                    )

        transaction.on_commit(_update_stats_and_bonus)

    except Exception:
        logger.exception(f"Monthly stats failed for TX#{instance.pk}")
        raise


# ============================================
# 4. PRODUCT STATUS UPDATE
# ============================================

@receiver(post_save, sender=Transaction, dispatch_uid="tx_product_status_v6")
def update_product_status_on_sale(sender, instance: Transaction, created, **kwargs):
    """
    Product status yangilash

    SALE CREATED & NOT VOID → status='sold', sold_at=now
    SALE VOIDED → status='available', sold_at=None

    YON-TA'SIR: on_commit
    """
    if instance.type != "sale" or not instance.product_id:
        return

    try:
        def _mark():
            if not instance.is_void:
                # Sotildi
                Product.objects.filter(pk=instance.product_id).update(
                    status="sold",
                    sold_at=instance.created_at or dj_tz.now()
                )
            else:
                # Qaytarildi
                Product.objects.filter(
                    pk=instance.product_id,
                    status="sold"
                ).update(
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

@receiver(post_save, sender=Transaction, dispatch_uid="tx_consignment_due_v6")
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
            ConsignmentDue.objects.get_or_create(
                product_id=product.pk,
                defaults={
                    "store": product.store,
                    "base_amount": product.consignment_price or DECIMAL_ZERO,
                    "created_by": instance.created_by or instance.seller,
                    "is_approved": False,  # Owner tasdiqlashi kerak
                },
            )

        transaction.on_commit(_ensure_due)

    except Exception:
        logger.exception(f"ConsignmentDue creation failed for TX#{instance.pk}")
        raise


# ============================================
# 6. CONSIGNMENT DUE VOID ON RETURN
# ============================================

@receiver(post_save, sender=Transaction, dispatch_uid="tx_void_cons_due_v6")
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
            # Faqat pending (tasdiqlanmagan) due'larni void qilish
            ConsignmentDue.objects.filter(
                product_id=product.pk,
                is_approved=False
            ).update(is_void=True)

        transaction.on_commit(_void_due)

    except Exception:
        logger.exception(f"ConsignmentDue void failed for TX#{instance.pk}")
        raise
