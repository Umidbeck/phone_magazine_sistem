# accounts/admin.py
from django.contrib import admin
from .models import User, Store
admin.site.register(User)
admin.site.register(Store)

# reference/admin.py
from django.contrib import admin
from reference.models import Brand, ModelName, Color, ExpenseType, Config
admin.site.register(Brand); admin.site.register(ModelName)
admin.site.register(Color); admin.site.register(ExpenseType); admin.site.register(Config)

# inventory/admin.py
from django.contrib import admin
from inventory.models import Product, ProductImage, BatchIntake
admin.site.register(Product); admin.site.register(ProductImage); admin.site.register(BatchIntake)

# sales/admin.py
from django.contrib import admin
from sales.models import Transaction, SellerCommission
admin.site.register(Transaction); admin.site.register(SellerCommission)

# operations/admin.py
from django.contrib import admin
from operations.models import AuditLog
admin.site.register(AuditLog)
