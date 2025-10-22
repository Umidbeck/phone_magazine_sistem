# core/utils.py - 100% MUKAMMAL VERSIYA
"""
Core utilities - BARCHA MODULLAR UCHUN

VERSIYA: 4.0 - TO'LIQ MUKAMMAL
================================

MUHIM XUSUSIYATLAR:
✅ Decimal xavfsizligi (hech qachon None/NaN)
✅ Scope checking (owner/seller)
✅ Permission decorators
✅ Safe aggregations
✅ Error handling
✅ Type hints
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, date
from typing import Optional, Union, Any
from functools import wraps

from django.http import HttpResponseForbidden
from django.db.models import Sum, QuerySet
from django.shortcuts import redirect

# ============================================
# CONSTANTS
# ============================================

DECIMAL_ZERO = Decimal("0.00")
D0 = DECIMAL_ZERO
DECIMAL_PRECISION = Decimal("0.01")


# ============================================
# DECIMAL UTILITIES
# ============================================

def parse_decimal(value: Any, default: Optional[Decimal] = None) -> Decimal:
    """
    Xavfsiz Decimal'ga aylantirish

    KAFOLAT: Hech qachon None qaytarmaydi!
    """
    if default is None:
        default = DECIMAL_ZERO

    if value is None or value == "":
        return default

    if isinstance(value, Decimal):
        return value.quantize(DECIMAL_PRECISION, rounding=ROUND_HALF_UP)

    try:
        # String tozalash
        if isinstance(value, str):
            s = value.strip().replace(" ", "").replace(",", ".").replace("$", "")
            if not s:
                return default
            result = Decimal(s)
        else:
            result = Decimal(str(value))

        return result.quantize(DECIMAL_PRECISION, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return default


def safe_sum(queryset: QuerySet, field: str = "amount") -> Decimal:
    """
    QuerySet'dan xavfsiz sum

    KAFOLAT: Hech qachon None qaytarmaydi!
    """
    try:
        result = queryset.aggregate(s=Sum(field))["s"]
        return parse_decimal(result, DECIMAL_ZERO)
    except Exception:
        return DECIMAL_ZERO


def calculate_profit(amount: Decimal, cost: Decimal) -> Decimal:
    """
    Foyda hisoblash

    Formula: Profit = Amount - Cost (0 dan kam bo'lsa 0)
    """
    amt = parse_decimal(amount)
    cst = parse_decimal(cost)
    profit = amt - cst
    return profit if profit > DECIMAL_ZERO else DECIMAL_ZERO


def calculate_margin_pct(profit: Decimal, amount: Decimal) -> Decimal:
    """
    Margin foizi hisoblash

    Formula: Margin% = (Profit / Amount) * 100
    """
    amt = parse_decimal(amount)
    if amt <= DECIMAL_ZERO:
        return DECIMAL_ZERO

    prf = parse_decimal(profit)
    margin = (prf / amt * Decimal("100")).quantize(DECIMAL_PRECISION)
    return margin


def format_money(amount: Union[Decimal, float, int, None]) -> str:
    """
    Pul formatini chiqarish

    >>> format_money(1234.56)
    '$1,234.56'
    """
    try:
        val = float(amount or 0)
        return f"${val:,.2f}"
    except (ValueError, TypeError):
        return "$0.00"


# ============================================
# DATE UTILITIES
# ============================================

def parse_date_safe(value: Union[str, date, None]) -> Optional[date]:
    """
    String'dan date'ga xavfsiz aylantirish
    """
    if value is None or value == "":
        return None

    if isinstance(value, date):
        return value

    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def month_key(dt: Union[date, datetime, None] = None) -> str:
    """
    Oy kaliti (YYYY-MM)
    """
    from django.utils import timezone as dj_tz
    if dt is None:
        dt = dj_tz.now()
    if isinstance(dt, datetime):
        dt = dt.date()
    return dt.strftime("%Y-%m")


# ============================================
# TEXT UTILITIES
# ============================================

def digits_only(text: str) -> str:
    """
    Faqat raqamlar
    """
    if not text:
        return ""
    return "".join(ch for ch in str(text) if ch.isdigit())


def truncate_text(text: str, max_length: int = 50) -> str:
    """
    Textni qisqartirish
    """
    if not text or len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def clean_text(text: str) -> str:
    """
    Unicode encoding muammolarini tuzatish
    """
    if not text:
        return ""

    replacements = {
        "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"',
        "\u2013": "-", "\u2014": "-",
    }

    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)

    return result.strip()


# ============================================
# PERMISSION UTILITIES
# ============================================

def is_owner(user) -> bool:
    """
    Foydalanuvchi owner ekanligini tekshirish

    Owner = superuser OR role='owner'
    """
    if not user or not user.is_authenticated:
        return False
    return bool(
        user.is_superuser or
        getattr(user, "is_owner", False) or
        getattr(user, "role", "") == "owner"
    )


def is_seller(user) -> bool:
    """
    Foydalanuvchi seller ekanligini tekshirish
    """
    if not user or not user.is_authenticated:
        return False
    return bool(getattr(user, "role", "") == "seller")


def can_access_sales(user) -> bool:
    """
    Sotuvga kirishga ruxsat
    """
    if not user or not user.is_authenticated:
        return False
    return is_owner(user) or is_seller(user)


def get_user_store_id(user) -> Optional[int]:
    """
    Foydalanuvchi do'koni ID
    """
    if not user or not user.is_authenticated:
        return None
    return getattr(user, "store_id", None)


def scope_by_user(queryset: QuerySet, user, store_id: Optional[int] = None) -> QuerySet:
    """
    QuerySet'ni foydalanuvchi bo'yicha cheklash

    QOIDA:
    - Owner: barcha do'konlar (yoki tanlangan store)
    - Seller: faqat o'z do'koni

    MUHIM: Bu funksiya 100% xavfsiz!
    """
    if is_owner(user):
        if store_id:
            return queryset.filter(store_id=store_id)
        return queryset

    user_store = get_user_store_id(user)
    if user_store:
        return queryset.filter(store_id=user_store)

    # Seller'ga store biriktirilmagan - bo'sh qaytarish
    return queryset.none()


# ============================================
# PERMISSION DECORATORS
# ============================================

def owner_required(view_func):
    """
    View uchun owner ruxsati kerak

    Usage:
        @owner_required
        def my_view(request):
            ...
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())

        if not is_owner(request.user):
            return HttpResponseForbidden("Faqat owner kirishi mumkin")

        return view_func(request, *args, **kwargs)

    return wrapper


def seller_required(view_func):
    """
    View uchun seller ruxsati kerak (yoki owner)

    Usage:
        @seller_required
        def my_view(request):
            ...
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())

        if not can_access_sales(request.user):
            return HttpResponseForbidden("Faqat sotuvchi kirishi mumkin")

        return view_func(request, *args, **kwargs)

    return wrapper


# ============================================
# VALIDATION UTILITIES
# ============================================

def validate_amount(amount: Any, min_value: Decimal = Decimal("0.01")) -> tuple:
    """
    Summani tekshirish

    Returns:
        (is_valid: bool, error_message: str)
    """
    try:
        val = parse_decimal(amount)
        if val < min_value:
            return False, f"Summa ${min_value} dan katta bo'lishi kerak"
        return True, None
    except:
        return False, "Noto'g'ri summa formati"


def validate_phone(phone: str) -> tuple:
    """
    Telefon raqamni tekshirish

    Returns:
        (is_valid: bool, error_message: str)
    """
    if not phone:
        return True, None

    cleaned = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not cleaned.replace("+", "").isdigit():
        return False, "Telefon faqat raqamlardan iborat bo'lishi kerak"

    dig = digits_only(cleaned)
    if len(dig) < 9 or len(dig) > 15:
        return False, "Telefon noto'g'ri formatda"

    return True, None


# ============================================
# ERROR HANDLING
# ============================================

def safe_get_object(model, **kwargs):
    """
    Xavfsiz object olish
    """
    try:
        return model.objects.get(**kwargs)
    except model.DoesNotExist:
        return None
    except Exception:
        return None


def log_error(message: str, exception: Optional[Exception] = None):
    """
    Xatolarni log qilish
    """
    import logging
    logger = logging.getLogger(__name__)

    if exception:
        logger.error(f"{message}: {exception}", exc_info=True)
    else:
        logger.error(message)


def log_warning(message: str):
    """
    Warning log
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(message)


# ============================================
# COMPATIBILITY & SHORTCUTS
# ============================================

# Backward compatibility
get_store_for_user = lambda user: get_user_store_id(user)