# accounts/urls.py
from django.urls import path
from .views import login_view, logout_view, home

urlpatterns = [
    path("", home, name="home"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
]
