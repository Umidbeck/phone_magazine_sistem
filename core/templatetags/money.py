from decimal import Decimal, ROUND_HALF_UP
from django import template
register = template.Library()


Q = Decimal("0.01")


@register.filter
def usd(val):
    try:
        d = (Decimal(val).quantize(Q, rounding=ROUND_HALF_UP))
        # Optional: locale/spacing
        return f"${d:,.2f}"
    except Exception:
        return "$0.00"