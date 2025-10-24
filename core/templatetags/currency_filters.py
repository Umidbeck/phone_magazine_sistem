# core/templatetags/currency_filters.py - TUZATILGAN (money.py o'rniga)
"""
Currency Template Filters - YAGONA MANBAA

MUAMMO HAL QILINDI:
❌ OLDIN: `usd` filter 2 ta joyda (currency_filters.py va money.py)
✅ HOZIR: Faqat shu faylda, money.py O'CHIRILDI

FILTERLAR:
1. usd - Desimalsiz ($ 1,234)
2. usd_decimal - Decimal bilan ($ 1,234.56)
3. usd_sign - Rangli ($sign)
4. abs_usd - Absolute value
5. currency_symbol - $ belgisi
6. format_amount - Smart format
"""

from django import template
from django.contrib.humanize.templatetags.humanize import intcomma
from decimal import Decimal

register = template.Library()


@register.filter(name='usd')
def usd(value):
    """
    Convert value to USD format without decimals

    USAGE:
        {{ amount|usd }}

    OUTPUT:
        $ 1,234

    EXAMPLES:
        1234.56 → $ 1,235
        1234.00 → $ 1,234
        0 → $ 0
        None → $ 0
    """
    if value is None:
        value = 0

    try:
        # Convert to Decimal for accurate rounding
        if not isinstance(value, Decimal):
            value = Decimal(str(value))

        # Round to nearest integer
        rounded = int(round(value, 0))

        # Add thousand separators
        formatted = intcomma(rounded)

        # Return with dollar sign
        return f'$ {formatted}'

    except (ValueError, TypeError, Exception):
        return '$ 0'


@register.filter(name='usd_decimal')
def usd_decimal(value, decimals=2):
    """
    Convert value to USD format WITH decimals

    USAGE:
        {{ amount|usd_decimal:2 }}

    OUTPUT:
        $ 1,234.56
    """
    if value is None:
        value = 0

    try:
        # Convert to Decimal
        if not isinstance(value, Decimal):
            value = Decimal(str(value))

        # Format with decimals
        format_str = f'{{:,.{decimals}f}}'
        formatted = format_str.format(float(value))

        return f'$ {formatted}'

    except (ValueError, TypeError, Exception):
        return f'$ 0.{"0" * decimals}'


@register.filter(name='usd_sign')
def usd_sign(value):
    """
    Add USD sign with color based on value

    USAGE:
        {{ amount|usd_sign }}

    OUTPUT:
        <span class="text-success">$ 1,234</span>
        <span class="text-danger">$ -1,234</span>
    """
    if value is None:
        value = 0

    try:
        if not isinstance(value, Decimal):
            value = Decimal(str(value))

        rounded = int(round(value, 0))
        formatted = intcomma(rounded)

        if value > 0:
            return f'<span class="text-success">$ {formatted}</span>'
        elif value < 0:
            return f'<span class="text-danger">$ {formatted}</span>'
        else:
            return f'<span class="text-muted">$ {formatted}</span>'

    except (ValueError, TypeError, Exception):
        return '<span class="text-muted">$ 0</span>'


@register.filter(name='abs_usd')
def abs_usd(value):
    """
    Absolute value in USD format

    USAGE:
        {{ amount|abs_usd }}

    OUTPUT:
        $ 1,234 (always positive)
    """
    if value is None:
        value = 0

    try:
        if not isinstance(value, Decimal):
            value = Decimal(str(value))

        # Get absolute value
        value = abs(value)
        rounded = int(round(value, 0))
        formatted = intcomma(rounded)

        return f'$ {formatted}'

    except (ValueError, TypeError, Exception):
        return '$ 0'


@register.simple_tag
def currency_symbol():
    """
    Return currency symbol

    USAGE:
        {% currency_symbol %}

    OUTPUT:
        $
    """
    return '$'


@register.simple_tag
def format_amount(value, show_decimals=False):
    """
    Smart format - decimals only if needed

    USAGE:
        {% format_amount amount %}
        {% format_amount amount True %}
    """
    if value is None:
        value = 0

    try:
        if not isinstance(value, Decimal):
            value = Decimal(str(value))

        # Check if has decimal part
        has_decimals = value % 1 != 0

        if show_decimals or has_decimals:
            # Show 2 decimals
            formatted = f'{float(value):,.2f}'
        else:
            # Show as integer
            rounded = int(round(value, 0))
            formatted = intcomma(rounded)

        return f'$ {formatted}'

    except (ValueError, TypeError, Exception):
        return '$ 0'


# ============================================
# ADDITIONAL FILTERS
# ============================================

@register.filter(name='percent')
def percent(value, decimals=1):
    """
    Format as percentage

    USAGE:
        {{ 0.15|percent }}      → 15.0%
        {{ 0.15|percent:2 }}    → 15.00%
    """
    if value is None:
        return '0%'

    try:
        value = float(value) * 100
        return f'{value:.{decimals}f}%'
    except (ValueError, TypeError):
        return '0%'


@register.filter(name='change_indicator')
def change_indicator(value):
    """
    Change indicator with icon

    USAGE:
        {{ change|change_indicator }}

    OUTPUT:
        ↑ +15% (green)
        ↓ -10% (red)
        → 0% (gray)
    """
    if value is None:
        return '→ 0%'

    try:
        value = float(value)

        if value > 0:
            return f'<span class="text-success">↑ +{value:.1f}%</span>'
        elif value < 0:
            return f'<span class="text-danger">↓ {value:.1f}%</span>'
        else:
            return '<span class="text-muted">→ 0%</span>'

    except (ValueError, TypeError):
        return '→ 0%'


@register.filter(name='compact_number')
def compact_number(value):
    """
    Compact number format (K, M, B)

    USAGE:
        {{ 1500|compact_number }}      → 1.5K
        {{ 1500000|compact_number }}   → 1.5M
    """
    if value is None:
        return '0'

    try:
        value = float(value)

        if value >= 1_000_000_000:
            return f'{value / 1_000_000_000:.1f}B'
        elif value >= 1_000_000:
            return f'{value / 1_000_000:.1f}M'
        elif value >= 1_000:
            return f'{value / 1_000:.1f}K'
        else:
            return f'{int(value)}'

    except (ValueError, TypeError):
        return '0'


