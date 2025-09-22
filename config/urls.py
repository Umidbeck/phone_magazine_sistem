"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf.urls.i18n import i18n_patterns
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('i18n/', include('django.conf.urls.i18n')),  # til almashtirish formasi uchun
]

# Default til uchun prefix kerak bo‘lmasa, settings.LANGUAGE_CODE bilan ishlaydi
urlpatterns += i18n_patterns(
    path('admin/', admin.site.urls),

    # Accounts (login/home va hk)
    path('', include('accounts.urls')),

    # Inventory
    path('inventory/', include('inventory.urls')),

    # Sales
    path('sales/', include('sales.urls')),

    # Reference
    path('reference/', include('reference.urls')),

    # Reports
    path('reports/', include('reports.urls')),
    prefix_default_language=False,
)

# Media fayllar (rasm) dev rejimda
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)