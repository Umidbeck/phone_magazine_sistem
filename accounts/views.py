import secrets

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils.translation import gettext as _
from .forms import StoreForm, SellerCreateForm, SellerUpdateForm
from .models import Store, User


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


def owner_only(request):
    return request.user.is_authenticated and request.user.is_owner

# ----- STORE CRUD -----
@login_required
def store_list(request):
    if not owner_only(request): return HttpResponseForbidden()
    items = Store.objects.order_by("name")
    return render(request, "accounts/store_list.html", {"items": items})

@login_required
def store_form(request, pk=None):
    if not owner_only(request): return HttpResponseForbidden()
    obj = get_object_or_404(Store, pk=pk) if pk else None
    form = StoreForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Store saved."))
        return redirect("store_list")
    return render(request, "accounts/store_form.html", {"form": form, "obj": obj})

@login_required
def store_delete(request, pk):
    if not owner_only(request): return HttpResponseForbidden()
    obj = get_object_or_404(Store, pk=pk)
    if request.method == "POST":
        obj.delete()
        messages.success(request, _("Store deleted."))
        return redirect("store_list")
    return render(request, "accounts/store_delete_confirm.html", {"obj": obj})

# ----- SELLER CRUD -----
@login_required
def seller_list(request):
    if not owner_only(request): return HttpResponseForbidden()
    users = User.objects.filter(role="seller").select_related("store").order_by("store__name","username")
    return render(request, "accounts/seller_list.html", {"items": users})

@login_required
def seller_new(request):
    if not owner_only(request): return HttpResponseForbidden()
    temp_password = None
    if request.method == "POST":
        form = SellerCreateForm(request.POST)
        if form.is_valid():
            user: User = form.save(commit=False)
            user.role = "seller"
            raw = form.cleaned_data.get("password") or secrets.token_urlsafe(8)
            temp_password = raw
            user.set_password(raw)
            user.save()
            messages.success(request, _("Seller created. Give this password to the seller: ") + raw)
            return render(request, "accounts/seller_created.html", {"user_obj": user, "password": raw})
        messages.error(request, _("Fix errors."))
    else:
        form = SellerCreateForm()
    return render(request, "accounts/seller_form.html", {"form": form})

@login_required
def seller_edit(request, pk):
    if not owner_only(request): return HttpResponseForbidden()
    obj = get_object_or_404(User, pk=pk, role="seller")
    if request.method == "POST":
        form = SellerUpdateForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, _("Seller updated."))
            return redirect("seller_list")
        messages.error(request, _("Fix errors."))
    else:
        form = SellerUpdateForm(instance=obj)
    return render(request, "accounts/seller_form.html", {"form": form, "obj": obj})

@login_required
def seller_reset_password(request, pk):
    if not owner_only(request): return HttpResponseForbidden()
    obj = get_object_or_404(User, pk=pk, role="seller")
    if request.method == "POST":
        import secrets
        raw = secrets.token_urlsafe(8)
        obj.set_password(raw); obj.save(update_fields=["password"])
        messages.success(request, _("New password: ") + raw)
        return render(request, "accounts/seller_created.html", {"user_obj": obj, "password": raw})
    return render(request, "accounts/seller_reset_confirm.html", {"obj": obj})

@login_required
def seller_delete(request, pk):
    if not owner_only(request): return HttpResponseForbidden()
    obj = get_object_or_404(User, pk=pk, role="seller")
    if request.method == "POST":
        obj.delete()
        messages.success(request, _("Seller deleted."))
        return redirect("seller_list")
    return render(request, "accounts/seller_delete_confirm.html", {"obj": obj})
