# reference/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # CRUD (Owner uchun)
    path("brands/", views.brand_list, name="brand_list"),
    path("brands/new/", views.brand_form, name="brand_new"),
    path("brands/<int:pk>/edit/", views.brand_form, name="brand_edit"),

    path("models/", views.model_list, name="model_list"),
    path("models/new/", views.model_form, name="model_new"),
    path("models/<int:pk>/edit/", views.model_form, name="model_edit"),

    path("colors/", views.color_list, name="color_list"),
    path("colors/new/", views.color_form, name="color_new"),
    path("colors/<int:pk>/edit/", views.color_form, name="color_edit"),

    # Dependent select (Ajax, JSON)
    path("brands/<int:brand_id>/models-json/", views.models_by_brand_json, name="models_by_brand_json"),
]
