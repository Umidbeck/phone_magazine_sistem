from django.db import models
from django.conf import settings

class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=40)  # created/updated/deleted/sold/expense/commission/payout/debt_out/debt_pay
    object_type = models.CharField(max_length=50)  # Product/Transaction/Brand/...
    object_id = models.CharField(max_length=64)
    changes = models.JSONField(default=dict, blank=True)  # diff yoki payload
    ip = models.GenericIPAddressField(null=True, blank=True)
    ua = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["object_type","object_id","created_at"])]
