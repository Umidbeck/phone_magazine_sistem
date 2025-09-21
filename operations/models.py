# operations/models.py
from django.db import models
class AuditLog(models.Model):
    who = models.CharField(max_length=120)
    action = models.CharField(max_length=60)
    entity = models.CharField(max_length=60)
    entity_id = models.CharField(max_length=60)
    before = models.TextField(blank=True)
    after = models.TextField(blank=True)
    at = models.DateTimeField(auto_now_add=True)
