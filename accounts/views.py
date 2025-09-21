from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils.translation import gettext as _

def login_view(request):
    if request.method == "POST":
        u, p = request.POST.get("username"), request.POST.get("password")
        user = authenticate(request, username=u, password=p)
        if user:
            login(request, user)
            messages.success(request, _("Welcome, %(name)s!") % {"name": user.get_full_name() or user.username})
            return redirect("home")
        messages.error(request, _("Invalid username or password."))
    return render(request, "accounts/login.html")

def logout_view(request):
    logout(request)
    messages.info(request, _("You have been logged out."))
    return redirect("login")

@login_required
def home(request):
    # Minimal bosh sahifa: inventar ro'yxatiga link + tez tugmalar
    return render(request, "accounts/home.html")
