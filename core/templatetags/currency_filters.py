# core/templatetags/currency_filters.py
"""
Currency Template Filters

MAQSAD: Butun tizimda bir xil valyuta formati
FORMAT: $ 1,234 (desimalsiz, dollar belgisi bilan)

VERSIYA: 1.0
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
    Convert value to USD format WITH decimals (faqat kerak bo'lganda)

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
        return '$ 0.00'


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