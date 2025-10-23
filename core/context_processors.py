def i18n_flags(request):
    return {
        "lang_code": getattr(getattr(request, "LANGUAGE_CODE", None), "lower", lambda: "")() or request.LANGUAGE_CODE
    }


# core/context_processors.py
"""
Global Context Processors

MAQSAD: Barcha template'larda currency ma'lumotlari
"""

from django.conf import settings


def currency_context(request):
    """
    Add currency settings to all templates

    USAGE in templates:
        {{ CURRENCY }}
        {{ CURRENCY_SYMBOL }}
        {{ CURRENCY_NAME }}
    """
    return {
        'CURRENCY': getattr(settings, 'CURRENCY', 'USD'),
        'CURRENCY_SYMBOL': getattr(settings, 'CURRENCY_SYMBOL', '$'),
        'CURRENCY_NAME': getattr(settings, 'CURRENCY_NAME', 'Dollar'),
    }

