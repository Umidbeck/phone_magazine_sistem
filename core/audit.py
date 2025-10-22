# core/audit.py
from .models import AuditLog

def write_audit(request, action: str, obj, changes: dict = None):
    try:
        AuditLog.objects.create(
            actor=(request.user if request and request.user.is_authenticated else None),
            action=action,
            object_type=obj.__class__.__name__,
            object_id=str(getattr(obj, "pk", "") or getattr(obj, "id", "")),
            changes=changes or {},
            ip=(request.META.get("REMOTE_ADDR") if request else None),
            ua=(request.META.get("HTTP_USER_AGENT") if request else ""),
        )
    except Exception:
        # Audit xatolari funksionallikka ta'sir qilmasin
        pass
