# accounts/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models

class Store(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)
    def __str__(self): return self.name

class User(AbstractUser):
    ROLE_CHOICES = (("owner","Owner"),("seller","Seller"))
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="seller")
    store = models.ForeignKey(Store, null=True, blank=True, on_delete=models.SET_NULL)
    def is_owner(self): return self.role == "owner"
