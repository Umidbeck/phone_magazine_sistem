from decimal import Decimal
from django.db import transaction, OperationalError, ProgrammingError
from django.utils import timezone
from .models import Account, JournalEntry, JournalLine, Investment

# --- DEFAULTS (bitta joyda) -------------------------------------------  # NEW
ACCOUNT_DEFAULTS = {
    Account.CODE_CASH:          ("Kassa / Naqd",                      Account.CAT_ASSET),
    Account.CODE_INVENTORY:     ("Inventar (Telefonlar, tannarx)",    Account.CAT_ASSET),
    Account.CODE_AR_CUSTOMERS:  ("Mijozlardan olinadigan (AR)",       Account.CAT_ASSET),
    Account.CODE_AP_SUPPLIERS:  ("Ta'minotchilarga qarz (AP)",        Account.CAT_LIAB),
    Account.CODE_OWNER_EQUITY:  ("Egasi kapitali (Equity)",           Account.CAT_EQU),
    Account.CODE_SALES:         ("Sotuv daromadi",                    Account.CAT_REV),
    Account.CODE_COMMISSION_IN: ("Komissiya daromadi",                Account.CAT_REV),
    Account.CODE_COGS:          ("COGS — Tannarx",                    Account.CAT_EXP),
    Account.CODE_EXPENSES:      ("Rashod/Xarajatlar",                 Account.CAT_EXP),
    Account.CODE_COMMISSION_EX: ("Komissiya xarajati",                Account.CAT_EXP),
}

def ensure_default_accounts():                                        # (avval ham bor edi)
    """
    Barcha zarur hisoblar mavjud bo‘lishini ta'minlaydi.
    """
    try:
        for code, (name, cat) in ACCOUNT_DEFAULTS.items():
            Account.objects.get_or_create(code=code, defaults={"name": name, "category": cat})
    except (OperationalError, ProgrammingError):
        # Jadval migratsiya bo'lmasdan chaqirilsa — jim chiqamiz (apps.ready() bosqichi uchun)
        pass

def _get_account(code):                                               # NEW
    """
    Keltirilgan kod bo‘yicha hisobni xavfsiz qaytaradi.
    Yo‘q bo‘lsa, DEFAULTS bo‘yicha yaratadi. Agar umuman topib bo‘lmasa — None.
    """
    ensure_default_accounts()
    try:
        return Account.objects.get(code=code)
    except Account.DoesNotExist:
        name_cat = ACCOUNT_DEFAULTS.get(code)
        if not name_cat:
            return None
        name, cat = name_cat
        obj, _ = Account.objects.get_or_create(code=code, defaults={"name": name, "category": cat})
        return obj
    except (OperationalError, ProgrammingError):
        return None

# ----------------- POST FUNKSIYALAR (sizda allaqachon bor) --------------------
# ... post_entry, post_investment, post_purchase, post_sale, ... (o'zgartirmang) ...

# ----------------- KPI / BALANCE FUNKSIYALARNI XAVFSIZ QILAMIZ ----------------

def _sum_account(code, date_from=None, date_to=None):                 # PATCH
    """
    Berilgan hisob bo‘yicha period ichidagi (yoki umumiy) yig‘indini qaytaradi.
    Hisob yo‘q bo‘lsa, 0 qaytaradi (xato tashlamaydi).
    """
    acc = _get_account(code)  # <-- endi xavfsiz
    if not acc:
        return Decimal("0.00")
    try:
        qs = JournalLine.objects.filter(account=acc)
        if date_from:
            qs = qs.filter(entry__date__gte=date_from)
        if date_to:
            qs = qs.filter(entry__date__lte=date_to)
        return qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    except (OperationalError, ProgrammingError):
        return Decimal("0.00")

def balances_as_of(date_to=None):                                     # PATCH
    """
    Ma'lum sanagacha balans qoldiqlari (Cash, Inventory, AR, AP).
    Hisoblar bo'lmasa ham 0 qaytadi.
    """
    def upto(code):
        return _sum_account(code, None, date_to)

    cash      = upto(Account.CODE_CASH)
    inventory = upto(Account.CODE_INVENTORY)
    ar        = upto(Account.CODE_AR_CUSTOMERS)
    ap        = upto(Account.CODE_AP_SUPPLIERS)

    return {
        "cash": cash,
        "inventory": inventory,
        "ar": ar,
        "ap": ap,
        "active": inventory,   # sizning ta’rifingiz bo‘yicha
        "passive": cash,
    }

def pnl_for_period(date_from=None, date_to=None):                      # PATCH
    """
    Daromad-xarajat (P&L) hisobi: period ichida.
    """
    sales   = _sum_account(Account.CODE_SALES,         date_from, date_to) * Decimal("-1")
    cogs    = _sum_account(Account.CODE_COGS,          date_from, date_to)
    exp     = _sum_account(Account.CODE_EXPENSES,      date_from, date_to)
    com_ex  = _sum_account(Account.CODE_COMMISSION_EX, date_from, date_to)
    com_in  = _sum_account(Account.CODE_COMMISSION_IN, date_from, date_to) * Decimal("-1")

    gross_profit = sales - cogs
    net_profit   = gross_profit - exp - com_ex + com_in

    return {
        "sales": sales, "cogs": cogs,
        "expenses": exp, "commission_expense": com_ex, "commission_income": com_in,
        "gross_profit": gross_profit, "net_profit": net_profit,
    }

def kpis_advanced(date_from=None, date_to=None):                       # PATCH
    """
    Dashboard KPI: balans (as_of) + P&L (period) + nisbiy ko‘rsatkichlar.
    """
    # AUTOINIT (ikki chora – ortiqcha bo‘lsa ham zarar qilmaydi)
    ensure_default_accounts()

    bal = balances_as_of(date_to)
    pnl = pnl_for_period(date_from, date_to)

    active = bal["active"]
    passive = bal["passive"]
    sales = pnl["sales"]
    cogs  = pnl["cogs"]
    gross_profit = pnl["gross_profit"]
    net_profit   = pnl["net_profit"]

    # 0 bo‘linishni oldini olamiz
    gross_margin_pct = (gross_profit / sales * 100) if sales else Decimal("0")
    net_margin_pct   = (net_profit / sales * 100)   if sales else Decimal("0")
    inventory_turnover = (cogs / active) if active else Decimal("0")
    cash_to_inventory  = (passive / active) if active else Decimal("0")

    return {
        "balances": bal,
        "pnl": pnl,
        "ratios": {
            "gross_margin_pct": gross_margin_pct,
            "net_margin_pct": net_margin_pct,
            "inventory_turnover": inventory_turnover,
            "cash_to_inventory": cash_to_inventory,
        }
    }

def ensure_default_accounts():
    defaults = [
        (Account.CODE_CASH,         "Kassa / Naqd",                     Account.CAT_ASSET),
        (Account.CODE_INVENTORY,    "Inventar (Telefonlar, tannarx)",   Account.CAT_ASSET),
        (Account.CODE_AR_CUSTOMERS, "Mijozlardan olinadigan (AR)",      Account.CAT_ASSET),
        (Account.CODE_AP_SUPPLIERS, "Ta'minotchilarga qarz (AP)",       Account.CAT_LIAB),
        (Account.CODE_OWNER_EQUITY, "Egasi kapitali (Equity)",          Account.CAT_EQU),
        (Account.CODE_SALES,        "Sotuv daromadi",                   Account.CAT_REV),
        (Account.CODE_COMMISSION_IN,"Komissiya daromadi",               Account.CAT_REV),
        (Account.CODE_COGS,         "COGS — Tannarx",                   Account.CAT_EXP),
        (Account.CODE_EXPENSES,     "Rashod/Xarajatlar",                Account.CAT_EXP),
        (Account.CODE_COMMISSION_EX,"Komissiya xarajati",               Account.CAT_EXP),
    ]
    for code, name, cat in defaults:
        Account.objects.get_or_create(code=code, defaults={"name": name, "category": cat})


# ---- Double-entry post ----
@transaction.atomic
def post_entry(lines, memo="", ref="", date=None):
    """
    lines: [(account_code, signed_amount), ...]  signed_amount:
      Debet = +, Kredit = -   (masalan DR 100.00 -> +100; CR 100.00 -> -100)
    """
    ensure_default_accounts()
    date = date or timezone.now().date()
    je = JournalEntry.objects.create(date=date, memo=memo, ref=ref)
    total = Decimal("0")
    for code, signed in lines:
        acc = Account.objects.get(code=code)
        JournalLine.objects.create(entry=je, account=acc, amount=Decimal(signed))
        total += Decimal(signed)
    # double-entry tekshiruv: summa 0 bo'lishi shart
    if total != 0:
        raise ValueError(f"Journal not balanced: total={total}")
    return je

# ---- Operatsiyalar ----
def post_investment(amount, note="Investitsiya", date=None):
    # DR Cash, CR Owner Equity
    je = post_entry(
        lines=[
            (Account.CODE_CASH,         +amount),
            (Account.CODE_OWNER_EQUITY, -amount),
        ],
        memo=note,
        date=date,
    )
    inv = Investment.objects.create(amount=amount, date=date or timezone.now().date(), note=note, journal_entry=je)
    return inv

def post_purchase(cost, cash=True, ref="", memo="Olingan tovar"):
    # Sotib olish: DR Inventory, CR Cash YOKI CR AP (ta'minotchiga qarz)
    if cash:
        lines = [
            (Account.CODE_INVENTORY, +cost),
            (Account.CODE_CASH,      -cost),
        ]
    else:
        lines = [
            (Account.CODE_INVENTORY, +cost),
            (Account.CODE_AP_SUPPLIERS, -cost),
        ]
    return post_entry(lines, memo=memo, ref=ref)

def post_expense(amount, cash=True, ref="", memo="Rashod"):
    if cash:
        lines = [
            (Account.CODE_EXPENSES, +amount),
            (Account.CODE_CASH,     -amount),
        ]
    else:
        lines = [
            (Account.CODE_EXPENSES, +amount),
            (Account.CODE_AP_SUPPLIERS, -amount),
        ]
    return post_entry(lines, memo=memo, ref=ref)

def post_sale(sale_price, cogs, is_cash=True, commission=Decimal("0.00"), commission_as_expense=True, ref="", memo="Sotuv"):
    """
    Sotish:
      - Daromad: DR Cash/AR, CR Sales
      - Tannarx: DR COGS, CR Inventory
      - Komissiya: xarajat yoki daromad sifatida tasniflash mumkin (parametr)
    """
    lines = []
    # Daromad qismi
    if is_cash:
        lines += [
            (Account.CODE_CASH,  +sale_price),
            (Account.CODE_SALES, -sale_price),
        ]
    else:
        lines += [
            (Account.CODE_AR_CUSTOMERS, +sale_price),
            (Account.CODE_SALES,        -sale_price),
        ]
    # Tannarx chiqarish
    if cogs and cogs > 0:
        lines += [
            (Account.CODE_COGS,      +cogs),
            (Account.CODE_INVENTORY, -cogs),
        ]
    # Komissiya
    if commission and commission > 0:
        if commission_as_expense:
            lines += [
                (Account.CODE_COMMISSION_EX, +commission),
                (Account.CODE_CASH if is_cash else Account.CODE_AR_CUSTOMERS, -commission),
            ]
        else:
            # masalan marketplace’dan komissiya daromadi bo’lsa
            lines += [
                (Account.CODE_CASH if is_cash else Account.CODE_AR_CUSTOMERS, +commission),
                (Account.CODE_COMMISSION_IN, -commission),
            ]
    return post_entry(lines, memo=memo, ref=ref)

def post_receipt_from_debtor(amount, ref="", memo="Qarzdan tushum"):
    # Mijoz qarzini to'ladi: DR Cash, CR AR
    return post_entry([
        (Account.CODE_CASH,        +amount),
        (Account.CODE_AR_CUSTOMERS, -amount),
    ], memo=memo, ref=ref)

def post_payment_to_supplier(amount, ref="", memo="Ta'minotchiga to'lov"):
    # Ta'minotchiga qarzni to'ladik: DR AP, CR Cash
    return post_entry([
        (Account.CODE_AP_SUPPLIERS, +amount),
        (Account.CODE_CASH,         -amount),
    ], memo=memo, ref=ref)

# ---- Balans va KPI ----
from django.db.models import Sum

def account_balance(code):
    ensure_default_accounts()
    acc = Account.objects.get(code=code)
    agg = JournalLine.objects.filter(account=acc).aggregate(total=Sum("amount"))
    return agg["total"] or Decimal("0.00")

def kpis(date_from=None, date_to=None):
    """
    Dashboard uchun asosiy metrikalar.
    Active/Passive (SIZNING TA’RIFINGIZGA MOS):
      - Active = Inventar qiymati (tannarx bo‘yicha)
      - Passive = Naqd (kassa)
    Qo‘shimcha: Debtorlar, Kreditorlar, Foyda (GP/NP)
    """
    ensure_default_accounts()

    cash      = account_balance(Account.CODE_CASH)
    inventory = account_balance(Account.CODE_INVENTORY)
    ar        = account_balance(Account.CODE_AR_CUSTOMERS)
    ap        = account_balance(Account.CODE_AP_SUPPLIERS)
    sales     = account_balance(Account.CODE_SALES) * Decimal("-1")  # revenue kredit sifatida manfiy bo’ladi
    cogs      = account_balance(Account.CODE_COGS)
    expenses  = account_balance(Account.CODE_EXPENSES)
    com_exp   = account_balance(Account.CODE_COMMISSION_EX)
    com_inc   = account_balance(Account.CODE_COMMISSION_IN) * Decimal("-1")

    gross_profit = sales - cogs
    net_profit   = gross_profit - expenses - com_exp + com_inc

    return {
        "active_inventory": inventory,  # Active (siz aytgandek: tovar bilan band)
        "passive_cash": cash,           # Passive (naqd qoldiq)
        "debtors_ar": ar,
        "store_debts_ap": ap,
        "sales_revenue": sales,
        "cogs": cogs,
        "expenses": expenses,
        "commission_expense": com_exp,
        "commission_income": com_inc,
        "gross_profit": gross_profit,
        "net_profit": net_profit,
    }


def _object_triplet(obj_or_ids, app_label=None, model_name=None, object_id=None):
    """
    obj_or_ids: model instance yoki (app_label, model_name, object_id) trio
    """
    if obj_or_ids is None:
        return ("", "", "")
    if hasattr(obj_or_ids, "_meta"):
        return (
            obj_or_ids._meta.app_label,
            obj_or_ids._meta.model_name,
            str(getattr(obj_or_ids, "pk", "")),
        )
    if app_label and model_name and object_id is not None:
        return (app_label, model_name, str(object_id))
    if isinstance(obj_or_ids, (tuple, list)) and len(obj_or_ids) == 3:
        return (str(obj_or_ids[0]), str(obj_or_ids[1]), str(obj_or_ids[2]))
    return ("", "", "")

def _already_posted(obj_or_ids):
    from .models import JournalLine
    app_label, model_name, oid = _object_triplet(obj_or_ids)
    if not app_label or not model_name or not oid:
        return False
    return JournalLine.objects.filter(
        object_app=app_label, object_model=model_name, object_id=oid
    ).exists()

@transaction.atomic
def post_entry_object(lines, obj_or_ids=None, memo="", ref="", date=None):
    """
    post_entry() ga o‘xshaydi, lekin barcha qatorlarga object link qo‘shadi
    va dublikatni to‘xtatadi (idempotent).
    """
    if _already_posted(obj_or_ids):
        # allaqachon post qilingan — hech narsa qilmaymiz
        return None

    ensure_default_accounts()
    date = date or timezone.now().date()
    je = JournalEntry.objects.create(date=date, memo=memo, ref=ref)
    total = Decimal("0")
    app_label, model_name, oid = _object_triplet(obj_or_ids)

    for code, signed in lines:
        acc = Account.objects.get(code=code)
        JournalLine.objects.create(
            entry=je,
            account=acc,
            amount=Decimal(signed),
            object_app=app_label,
            object_model=model_name,
            object_id=oid,
        )
        total += Decimal(signed)

    if total != 0:
        raise ValueError(f"Journal not balanced: total={total}")
    return je


def _sum_account(code, date_from=None, date_to=None):
    """
    JournalEntry.date bo‘yicha filterlab bitta hisobni yig‘adi.
    Debet(+) / Kredit(-) sifatida saqlangan summalarni to‘playdi.
    """
    acc = Account.objects.get(code=code)
    qs = JournalLine.objects.filter(account=acc)
    if date_from:
        qs = qs.filter(entry__date__gte=date_from)
    if date_to:
        qs = qs.filter(entry__date__lte=date_to)
    return qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

def balances_as_of(date_to=None):
    """
    Balans hisobi: ma’lum sanadagi qoldiq (boshlang‘ichdan to sanagacha).
    """
    def upto(code):
        return _sum_account(code, None, date_to)

    cash      = upto(Account.CODE_CASH)
    inventory = upto(Account.CODE_INVENTORY)
    ar        = upto(Account.CODE_AR_CUSTOMERS)
    ap        = upto(Account.CODE_AP_SUPPLIERS)

    return {
        "cash": cash,
        "inventory": inventory,
        "ar": ar,
        "ap": ap,
        "active": inventory,
        "passive": cash,
    }

def pnl_for_period(date_from=None, date_to=None):
    """
    Daromad-xarajat hisobi faqat period ichida.
    """
    sales   = _sum_account(Account.CODE_SALES, date_from, date_to) * Decimal("-1")
    cogs    = _sum_account(Account.CODE_COGS, date_from, date_to)
    exp     = _sum_account(Account.CODE_EXPENSES, date_from, date_to)
    com_ex  = _sum_account(Account.CODE_COMMISSION_EX, date_from, date_to)
    com_in  = _sum_account(Account.CODE_COMMISSION_IN, date_from, date_to) * Decimal("-1")

    gross_profit = sales - cogs
    net_profit   = gross_profit - exp - com_ex + com_in

    return {
        "sales": sales,
        "cogs": cogs,
        "expenses": exp,
        "commission_expense": com_ex,
        "commission_income": com_in,
        "gross_profit": gross_profit,
        "net_profit": net_profit,
    }

def kpis_advanced(date_from=None, date_to=None):
    """
    Dashboard: balans (as_of date_to) + P&L (period) + koeffitsientlar.
    """
    bal = balances_as_of(date_to)
    pnl = pnl_for_period(date_from, date_to)

    # Ko‘rsatkichlar
    active = bal["active"]           # Inventar
    passive = bal["passive"]         # Kassa
    ar = bal["ar"]
    ap = bal["ap"]

    sales = pnl["sales"]
    cogs  = pnl["cogs"]
    gross_profit = pnl["gross_profit"]
    net_profit   = pnl["net_profit"]

    # nisbiy ko‘rsatkichlar (0 divisiondan himoya)
    gross_margin_pct = (gross_profit / sales * 100) if sales else Decimal("0")
    net_margin_pct   = (net_profit / sales * 100) if sales else Decimal("0")
    inventory_turnover = (cogs / active) if active else Decimal("0")   # soddalashtirilgan
    cash_to_inventory  = (passive / active) if active else Decimal("0")

    return {
        "balances": bal,
        "pnl": pnl,
        "ratios": {
            "gross_margin_pct": gross_margin_pct,
            "net_margin_pct": net_margin_pct,
            "inventory_turnover": inventory_turnover,
            "cash_to_inventory": cash_to_inventory,
        }
    }


def ar_ap_breakdown(date_to=None):
    """
    Ledgerdan mijoz qarzlari (AR) va do'kon qarzlari (AP) detali.
    """
    def lines_for(code):
        acc = Account.objects.get(code=code)
        qs = JournalLine.objects.filter(account=acc)
        if date_to:
            qs = qs.filter(entry__date__lte=date_to)
        return qs.values("object_app", "object_model", "object_id").annotate(total=Sum("amount")).order_by("-total")

    return {
        "AR": list(lines_for(Account.CODE_AR_CUSTOMERS)),
        "AP": list(lines_for(Account.CODE_AP_SUPPLIERS)),
    }

# --- Transaction -> Ledger “bridge” (xohlasangiz yoqasiz) ---
from decimal import Decimal

def post_from_transaction(tx):
    """
    sales.models.Transaction obyektidan ledgerga post qilish.
    Bu yerda *type* maydoniga mos mapping aniq kiritilgan.
    Faqat mavjud model `Transaction` bilan ishlaydi.
    """
    from .adapters import (
        post_sale_from_domain, post_expense_from_domain,
        post_receipt_from_debtor_domain, post_payment_to_supplier_domain,
        post_purchase_from_domain,
    )

    t = getattr(tx, "type", "")
    amt = Decimal(getattr(tx, "amount", getattr(tx, "price", "0")) or 0)

    # 1) sale
    if t == "sale" and getattr(tx, "is_approved", False) and not getattr(tx, "is_void", False):
        sale_price = Decimal(getattr(tx, "price", "0") or 0)
        cogs = Decimal(getattr(tx, "cost", "0") or 0)
        # kredit sotuvi bo‘lsa Transaction’da belgi bo‘lishi mumkin (masalan is_credit_sale)
        is_cash = not bool(getattr(tx, "is_credit_sale", False))
        commission = Decimal(getattr(tx, "commission_amount", "0") or 0)
        commission_as_expense = bool(getattr(tx, "commission_as_expense", True))
        return post_sale_from_domain(
            tx, sale_price=sale_price, cogs=cogs, is_cash=is_cash,
            commission=commission, commission_as_expense=commission_as_expense,
            ref=f"sales.Transaction:{tx.pk}", memo="Sotuv (TX)"
        )

    # 2) expense
    if t == "expense" and getattr(tx, "is_approved", False):
        is_cash = not bool(getattr(tx, "on_credit", False))
        return post_expense_from_domain(
            tx, amount=amt, is_cash=is_cash, ref=f"sales.Transaction:{tx.pk}", memo="Rashod (TX)"
        )

    # 3) debtor payment (qarzdordan tushum)
    if t in ("debt_payment", "ar_in"):
        return post_receipt_from_debtor_domain(
            tx, amount=amt, ref=f"sales.Transaction:{tx.pk}", memo="Qarzdordan tushum (TX)"
        )

    # 4) supplier payment (AP)
    if t in ("supplier_payment", "ap_out"):
        return post_payment_to_supplier_domain(
            tx, amount=amt, ref=f"sales.Transaction:{tx.pk}", memo="Ta'minotchiga to'lov (TX)"
        )

    # 5) purchase (inventoryga kirim) — agar Transaction orqali ham saqlansa
    if t in ("purchase", "stock_in"):
        # Product bilan bog'liq bo‘lsa costni tan narx deb olamiz
        cost = Decimal(getattr(tx, "cost", "0") or 0)
        is_cash = not bool(getattr(tx, "supplier_credit", False))
        return post_purchase_from_domain(
            tx, cost=cost, is_cash=is_cash, ref=f"sales.Transaction:{tx.pk}", memo="Olingan tovar (TX)"
        )

    return None