# core/templatetags/money.py
from django import template
register = template.Library()

@register.filter
def usd(val):
    try:
        return f"${float(val):,.2f}"
    except Exception:
        return "$0.00"
