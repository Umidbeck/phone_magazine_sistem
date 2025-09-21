# accounts/permissions.py
from django.core.exceptions import PermissionDenied

def require_owner_or_same_store(get_queryset_attr="get_queryset"):
    """
    ViewSet emas, oddiy class-based view uchun ham ishlatamiz:
    `view.get_queryset()` natijasini sellerga store bilan cheklaydi.
    """
    def decorator(view_func):
        def _wrapped(view, request, *args, **kwargs):
            if request.user.is_authenticated and request.user.is_owner():
                return view_func(view, request, *args, **kwargs)
            # Seller: view.get_queryset() bor bo‘lsa cheklaymiz
            if hasattr(view, get_queryset_attr):
                qs = getattr(view, get_queryset_attr)()
                if hasattr(qs.model, "store"):
                    view.queryset = qs.filter(store=request.user.store)
                # Aks holda, obyektni tekshirishni detail view’larda qilamiz
            return view_func(view, request, *args, **kwargs)
        return _wrapped
    return decorator
