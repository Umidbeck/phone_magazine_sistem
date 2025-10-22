# core/mixins.py
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

class StoreScopeMixin(LoginRequiredMixin):
    """
    CBV uchun: get_queryset() store scope’ga mos bo‘lsin.
    FBVlarda shunga o‘xshash filterlar allaqachon bor — barqarorlik uchun umumlashtirildi.
    """
    store_field = "store_id"  # queryset modelida shunday maydon bo‘lishi kutiladi

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.is_authenticated:
            raise PermissionDenied
        if user.is_owner:
            return qs
        # Seller: faqat o‘z do‘koni
        return qs.filter(**{self.store_field: user.store_id})
