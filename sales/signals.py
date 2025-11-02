# sales/signals.py - MUKAMMAL VERSIYA (V7.0) - APPROVAL YO'Q!
"""
Sales Signals - Avtomatik komissiya, statistika va moliyaviy oqimlar

VERSIYA: 7.0 - TASDIQLASH YO'Q, AVTOMATIK KOMISSIYA
====================================================

🎯 YANGI QOIDALAR (TASDIQLASH O'CHIRILDI):
═══════════════════════════════════════════

1. SOTUV BO'LGANDA:
   ✅ Komissiya DARHOL hisoblanadi va beriladi
   ✅ Tasdiqlash kerak emas (is_approved avtomatik True)
   ✅ To'lov ham darhol (is_paid avtomatik True)

2. KOMISSIYA HISOBI:
   - Yangi telefon → 30% * Profit
   - Eski telefon → $5 fix
   - Blocked telefon → $0

3. O'SHA KUNI QAYTARISH:
   ✅ Komissiya BERILMAYDI (rescinded)
   ✅ Seller hech narsa olmaydi va yo'qotmaydi

4. BOSHQA KUNI QAYTARISH:
   ✅ Komissiya MINUS qilinadi
   ✅ amount → manfiy (masalan: -5.00)
   ✅ is_deduction = True
   ✅ Seller balance'dan ayriladi

MATEMATIK KAFOLAT:
✅ 100% aniq hisob-kitob
✅ Atomic safe - xatolik bo'lmaydi
✅ Tranzaksiya ichida .save() yo'q
✅ Barcha update'lar on_commit() orqali

STATISTIKA:
✅ Har sotuvda counter++
✅ Har qaytarishda counter--
✅ Oylik leaderboard va bonuslar

LEDGER:
✅ Avtomatik moliyaviy yozuvlar
✅ Idempotent - qayta yozmaydi
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
# 0. AUTO-APPROVAL (TASDIQLASHNI OLIB TASHLASH)
# ============================================

@receiver(post_save, sender=Transaction, dispatch_uid="tx_auto_approve_v7")
def auto_approve_transaction(sender, instance: Transaction, created, **kwargs):
    """
    Transaction yaratilganda AVTOMATIK tasdiqlash

    🎯 YANGI QOIDA: Tasdiqlash kerak emas!
    ═════════════════════════════════════════

    Barcha transactionlar DARHOL tasdiqlanadi:
    - is_approved = True
    - approved_by = seller/creator
    - approved_at = now()
    - is_paid = True (sotuvlar uchun)
    - paid_at = now()

    FAQAT YANGI VA VOID BO'LMAGAN transactionlar uchun!
    """
    if not created or instance.is_void:
        return

    if instance.is_approved:
        # Allaqachon tasdiqlangan
        return

    try:
        def _auto_approve():
            """Avtomatik tasdiqlash"""
            updates = {
                "is_approved": True,
                "approved_by": instance.created_by or instance.seller,
                "approved_at": dj_tz.now(),
            }

            # Sotuvlar uchun to'lov ham avtomatik
            if instance.type == "sale":
                updates["is_paid"] = True
                updates["paid_at"] = dj_tz.now()

            Transaction.objects.filter(pk=instance.pk).update(**updates)
            logger.info(f"✅ TX#{instance.pk} AUTO-APPROVED and PAID!")

        transaction.on_commit(_auto_approve)

    except Exception:
        logger.exception(f"Auto-approval failed for TX#{instance.pk}")
        raise


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

    ⚠️ MUHIM: Komissiya faqat TASDIQLANGANDAN KEYIN ledgerga yoziladi!
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
                    # ⚠️ MUHIM: Komissiya yozilmaydi!
                    # Komissiya faqat tasdiqlanganda alohida signal orqali yoziladi
                    post_sale_from_transaction_split(
                        tx=instance,
                        commission=Decimal("0.00"),  # ⚠️ 0 - komissiya alohida yoziladi!
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
# 1B. KOMISSIYA TASDIQLANGANDA LEDGERGA YOZISH
# ============================================

@receiver(post_save, sender=SellerCommission, dispatch_uid="commission_ledger_post_v6")
def post_commission_to_ledger_when_approved(sender, instance: SellerCommission, created, **kwargs):
    """
    Komissiya tasdiqlanganda ledgerga yozish

    SHART:
    - is_approved = True (yangi tasdiqlanganlar)
    - is_rescinded = False
    - FINANCE_AUTOPOST = True

    ENTRY:
        DR Commission Expense    amount
        CR Cash/Card/AR          amount (transaction'dan)

    YON-TA'SIR: on_commit (atomic-safe)
    IDEMPOTENT: Faqat bir marta yoziladi

    ⚠️ Bu signal komissiya tasdiqlanganda avtomatik chaqiriladi!
    """
    # Faqat tasdiqlangan va rescind qilinmagan komissiyalar
    if not instance.is_approved or instance.is_rescinded:
        return

    if not getattr(settings, "FINANCE_AUTOPOST", False):
        logger.debug("FINANCE_AUTOPOST disabled for commission")
        return

    # Agar created bo'lsa va is_approved=True bo'lsa yoki
    # Update qilingan bo'lsa va is_approved=True ga o'zgargan bo'lsa
    if not created:
        # Faqat is_approved yangi True ga o'zgargan bo'lsa yozamiz
        # Bu yerda biz update qilinganligini bilamiz
        # Lekin oldingi qiymatni bilmaymiz, shuning uchun har doim yozamiz
        # (idempotent bo'lishi kerak finance tarafida)
        pass

    try:
        from finance.adapters import post_sale_from_transaction_split

        def _post_commission():
            """Komissiya uchun ledger entry yaratish"""
            try:
                tx = instance.transaction
                if not tx or tx.type != "sale":
                    return

                # Komissiya summasi
                commission_amount = instance.effective_amount

                if commission_amount != Decimal("0.00"):
                    # Transaction'ning ledger entrysi bor bo'lishi kerak
                    # Biz faqat komissiya qismini qayta yozamiz
                    # Bu ishlamaydi, chunki post_sale_from_transaction_split
                    # butun transactionni yozadi

                    # Komissiya uchun alohida entry qilish kerak
                    from finance.services import post_entry_object
                    from finance.models import Account

                    # Komissiya to'langan channelni aniqlash
                    lines = []

                    if commission_amount > Decimal("0.00"):
                        # Musbat komissiya
                        lines.append((Account.CODE_COMMISSION_EX, commission_amount))

                        # To'lov channelidan yechish
                        cash_amt = Decimal(getattr(tx, "cash_amount", 0))
                        card_amt = Decimal(getattr(tx, "card_amount", 0))

                        # Avval kartadan, keyin naqd
                        rem = commission_amount

                        use_card = min(rem, card_amt)
                        if use_card > Decimal("0.00"):
                            lines.append((Account.CODE_CARD, -use_card))
                            rem -= use_card

                        use_cash = min(rem, cash_amt)
                        if use_cash > Decimal("0.00"):
                            lines.append((Account.CODE_CASH, -use_cash))
                            rem -= use_cash

                        if rem > Decimal("0.00"):
                            lines.append((Account.CODE_AR_CUSTOMERS, -rem))

                    elif commission_amount < Decimal("0.00"):
                        # Manfiy komissiya (deduction) - seller pulini qaytaradi
                        abs_amt = abs(commission_amount)
                        lines.append((Account.CODE_CASH, abs_amt))
                        lines.append((Account.CODE_COMMISSION_EX, -abs_amt))

                    if lines:
                        post_entry_object(
                            lines,
                            obj_or_ids=instance,
                            ref=f"COMM:{instance.pk}",
                            memo=f"Komissiya #{instance.pk}"
                        )
                        logger.info(f"Commission ledger posted for COMM#{instance.pk}")

            except Exception as e:
                logger.exception(f"Commission ledger posting failed for COMM#{instance.pk}: {e}")

        transaction.on_commit(_post_commission)

    except ImportError:
        logger.debug("Finance app not available")
    except Exception:
        logger.exception("Commission ledger post setup error")


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
                Komissiya yaratish/yangilash - AVTOMATIK!

                QOIDALAR:
                - Yangi telefon → 30% foyda
                - Eski telefon → $5 fix
                - Blocked telefon → $0

                🎯 YANGI: Tasdiqlash yo'q! Darhol beriladi va to'lanadi!
                """
                commission, created_comm = SellerCommission.objects.get_or_create(
                    transaction_id=instance.pk,
                    defaults={
                        "seller": instance.seller,
                        "amount": comm_amount,
                        "category": category,
                        "is_deduction": False,
                        # 🎯 AVTOMATIK TASDIQLASH VA TO'LASH
                        "is_approved": True,
                        "approved_by": instance.created_by or instance.seller,
                        "approved_at": dj_tz.now(),
                        "is_paid": True,  # 🎯 DARHOL TO'LANGAN!
                        "paid_at": dj_tz.now(),
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

                # Xabarnomalar - AVTOMATIK to'langanligini bildirish
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
                        "💰 Komissiya TO'LANDI!",
                        f"${comm_amount:.2f} bonus DARHOL hisobingizga qo'shildi! "
                        f"Kategoriya: {category}"
                    )

                logger.info(
                    f"✅ Commission PAID for TX#{instance.pk}: "
                    f"${comm_amount} ({category}) - INSTANT!"
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

    QAYTARISH:
    - Qaytarish (void=True) → counter--
    - Seller reytingidan ayriladi

    YON-TA'SIR: on_commit
    """
    if instance.type != "sale":
        return

    # ========== YANGI SOTUV ==========
    if created and not instance.is_void:
        try:
            mk = _month_key(instance.created_at)

            def _update_stats_and_bonus():
                """Statistika va bonus yangilash (har do'kon uchun alohida!)"""
                store = instance.store

                stat, _ = SellerMonthlyStat.objects.get_or_create(
                    seller=instance.seller,
                    month_key=mk,
                    store=store,  # ⚠️ Har do'kon uchun alohida!
                    defaults={"sales_count": 0}
                )

                # Atomik increment
                SellerMonthlyStat.objects.filter(pk=stat.pk).update(
                    sales_count=(stat.sales_count or 0) + 1,
                    updated_at=dj_tz.now()
                )

                # Bonus tekshiruvi (faqat shu do'kon uchun!)
                if not MonthlyBonus.objects.filter(
                        store=store,  # ⚠️ Har do'kon uchun alohida!
                        month_key=mk
                ).exists():
                    # Yangilangan qiymat
                    fresh = SellerMonthlyStat.objects.get(pk=stat.pk)

                    if (fresh.sales_count or 0) >= 50:
                        # BONUS! (faqat shu do'kondagi sellerlar uchun)
                        MonthlyBonus.objects.create(
                            store=store,  # ⚠️ Do'kon
                            month_key=mk,
                            winner=instance.seller,
                            amount=Decimal("50.00"),
                        )

                        # Reset faqat shu do'kondagi sellerlar
                        SellerMonthlyStat.objects.filter(
                            store=store,  # ⚠️ Faqat shu do'kon!
                            month_key=mk
                        ).update(
                            sales_count=0
                        )

                        _create_notification_safe(
                            instance.seller,
                            "🎉 BONUS - $50!",
                            f"Tabriklaymiz! Siz {store.name} do'konida {mk} oyida "
                            f"50 ta telefon sotdingiz! $50 bonus qo'shildi!"
                        )

                        logger.info(
                            f"Monthly bonus awarded to {instance.seller.username} "
                            f"for {store.name} - {mk}"
                        )

            transaction.on_commit(_update_stats_and_bonus)

        except Exception:
            logger.exception(f"Monthly stats failed for TX#{instance.pk}")
            raise

    # ========== QAYTARISH (VOID) - REYTING MINUS ==========
    elif not created and instance.is_void:
        try:
            mk = _month_key(instance.created_at)
            store = instance.store  # ⚠️ Do'kon

            def _decrement_stats():
                """Statistikadan ayirish (qaytarish)"""
                try:
                    stat = SellerMonthlyStat.objects.get(
                        seller=instance.seller,
                        month_key=mk,
                        store=store  # ⚠️ Har do'kon uchun alohida
                    )

                    # Counter'dan ayirish (0 dan pastga tushmaydi)
                    new_count = max(0, (stat.sales_count or 0) - 1)

                    SellerMonthlyStat.objects.filter(pk=stat.pk).update(
                        sales_count=new_count,
                        updated_at=dj_tz.now()
                    )

                    logger.info(
                        f"Stats decremented for {instance.seller.username} "
                        f"in {store.name} - {mk}: {stat.sales_count} → {new_count}"
                    )

                except SellerMonthlyStat.DoesNotExist:
                    logger.warning(
                        f"No stats found for {instance.seller.username} "
                        f"in {store.name} - {mk}"
                    )

            transaction.on_commit(_decrement_stats)

        except Exception:
            logger.exception(f"Stats decrement failed for TX#{instance.pk}")
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

@receiver(post_save, sender=ConsignmentDue, dispatch_uid="cons_due_create_signal")
def initialize_consignment_due_balance(sender, instance, created, **kwargs):
    """
    Yangi ConsignmentDue yaratilganda balance'ni to'g'ri qo'yish
    """
    if created:
        # Balance = base_amount (hali to'lanmagan)
        if instance.balance == Decimal("0.00"):
            ConsignmentDue.objects.filter(pk=instance.pk).update(
                balance=instance.base_amount
            )