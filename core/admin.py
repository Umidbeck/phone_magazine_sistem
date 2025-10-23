# core/admin.py

from django.contrib import admin
from django.utils.html import format_html

from core.utils import format_currency


class CurrencyAdminMixin:
    """
    Mixin for ModelAdmin to format currency fields

    USAGE:
        class TransactionAdmin(CurrencyAdminMixin, admin.ModelAdmin):
            currency_fields = ['amount', 'profit']
    """

    currency_fields = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add currency display methods
        for field in self.currency_fields:
            method_name = f'{field}_display'

            def make_display(field_name):
                def display_method(obj):
                    value = getattr(obj, field_name, None)
                    if value is None:
                        return '$ 0'
                    formatted = format_currency(value)

                    # Color based on value
                    if value > 0:
                        color = 'green'
                    elif value < 0:
                        color = 'red'
                    else:
                        color = 'gray'

                    return format_html(
                        '<span style="color: {}; font-weight: bold;">{}</span>',
                        color,
                        formatted
                    )

                display_method.short_description = field_name.replace('_', ' ').title()
                return display_method

            setattr(self, method_name, make_display(field))

            # Add to list_display if not already there
            if hasattr(self, 'list_display'):
                if method_name not in self.list_display and field in self.list_display:
                    list_display_list = list(self.list_display)
                    idx = list_display_list.index(field)
                    list_display_list[idx] = method_name
                    self.list_display = tuple(list_display_list)