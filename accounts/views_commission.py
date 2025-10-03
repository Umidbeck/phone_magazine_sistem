# accounts/views_commission.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden
from .forms_commission import CommissionConfigForm

def owner_only(request):
    u = getattr(request, "user", None)
    return bool(u and u.is_authenticated and getattr(u, "is_owner", False))

@login_required
def commission_settings(request):
    if not owner_only(request):
        return HttpResponseForbidden()
    if request.method == "POST":
        form = CommissionConfigForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Komissiya qiymati saqlandi.")
            return redirect("commission_settings")
        messages.error(request, "Ma'lumotlarni tekshiring.")
    else:
        form = CommissionConfigForm()
    return render(request, "accounts/commission_settings.html", {"form": form})
