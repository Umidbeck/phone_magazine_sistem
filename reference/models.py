# reference/models.py
from django.db import models

class Brand(models.Model):
    name = models.CharField(max_length=60, unique=True)
    is_active = models.BooleanField(default=True)
    def __str__(self): return self.name

class ModelName(models.Model):
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="models")
    name = models.CharField(max_length=80)
    is_active = models.BooleanField(default=True)
    class Meta: unique_together = ("brand","name")
    def __str__(self): return f"{self.brand.name} {self.name}"

class Color(models.Model):
    name = models.CharField(max_length=40, unique=True)
    hex_code = models.CharField(max_length=7, blank=True)  # #RRGGBB
    is_active = models.BooleanField(default=True)
    def __str__(self): return self.name

class ExpenseType(models.Model):
    name = models.CharField(max_length=40, unique=True)  # ustaga, ta’mir, transport, reklama, boshqa
    is_active = models.BooleanField(default=True)
    def __str__(self): return self.name

class Config(models.Model):
    key = models.CharField(max_length=64, unique=True)
    value = models.CharField(max_length=256)
    def __str__(self): return f"{self.key}={self.value}"


