import secrets
from datetime import timedelta, date

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils.translation import gettext as _

from inventory.models import Product
from sales.models import Transaction, SellerCommission
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




@login_required
def account_dashboard(request):
    return render(request, "accounts/account_dashboard.html", {})

@login_required
def account_stats_user(request):
    today = date.today()
    two_years_ago = today - timedelta(days=730)

    sales = Transaction.objects.filter(type="sale", created_at__date__range=(two_years_ago, today))
    expenses = Transaction.objects.filter(type="expense", created_at__date__range=(two_years_ago, today))
    if request.user.is_owner:
        # owner – o‘ziga tegishli sotuvchilik emas, umumiy ko‘rsatkichlarni istasa, Reports bo‘limidan ko‘radi.
        # Account/My stats – agar owner ham sotuv qilgan bo‘lsa (seller sifatida yozilgan bo‘lsa) ko‘rsatiladi.
        pass
    else:
        sales = sales.filter(store_id=request.user.store_id, seller=request.user)
        expenses = expenses.filter(store_id=request.user.store_id, seller=request.user)

    total_sales_count = sales.count()
    total_amount = sales.aggregate(s=Sum("amount"))["s"] or 0
    total_profit = sales.aggregate(s=Sum("profit"))["s"] or 0
    total_expenses = expenses.aggregate(s=Sum("amount"))["s"] or 0

    prods = Product.objects.filter(created_at__date__range=(two_years_ago, today))
    if not request.user.is_owner:
        prods = prods.filter(store_id=request.user.store_id, created_by=request.user)

    intake_count = prods.count()
    intake_owned_sum = prods.filter(ownership="owned").aggregate(s=Sum("purchase_price"))["s"] or 0

    # Komissiya — aniqroq uchun SellerCommission'dan
    com_qs = SellerCommission.objects.filter(transaction__in=sales)
    commission_total = com_qs.aggregate(s=Sum("amount"))["s"] or 0

    # Oy/hafta/kun bo‘yicha sotilgan son (faqat shaxsiy scope)
    def group(fmt):
        return (sales.extra(select={"k": f"to_char(created_at, '{fmt}')"})
                .values("k").annotate(c=Count("id")).order_by("k"))

    monthly = list(group("YYYY-MM"))
    weekly  = list(group("IYYY-IW"))
    daily   = list(group("YYYY-MM-DD"))

    ctx = dict(
        total_sales_count=total_sales_count,
        total_amount=total_amount,
        total_profit=total_profit,
        total_expenses=total_expenses,
        intake_count=intake_count,
        intake_owned_sum=intake_owned_sum,
        commission_total=commission_total,
        monthly=monthly, weekly=weekly, daily=daily,
    )
    return render(request, "accounts/account_stats_user.html", ctx)

@login_required
def my_sales(request):
    qs = Transaction.objects.select_related("product","store").filter(type="sale", seller=request.user).order_by("-created_at")
    return render(request, "accounts/my_sales.html", {"rows": qs[:300]})

@login_required
def my_commissions(request):
    """
    Sotuvchi har kuni nechta sotgan bo'lsa, 5$ * count qilib ko'ra oladi.
    SellerCommission asosida kunlik yig'indilar.
    """
    today = date.today()
    days = int(request.GET.get("days", 30))
    date_from = today - timedelta(days=days-1)

    qs = (SellerCommission.objects
          .filter(seller=request.user,
                  transaction__created_at__date__range=(date_from, today))
          .annotate(d=TruncDate("transaction__created_at"))
          .values("d")
          .annotate(count=Count("id"), total=Sum("amount"))
          .order_by("-d"))

    # umumiy
    grand_count = 0
    grand_total = 0
    for r in qs:
        grand_count += r["count"]
        grand_total += r["total"] or 0

    ctx = {
        "days": days,
        "rows": qs,
        "grand_count": grand_count,
        "grand_total": grand_total,
        "date_from": date_from, "date_to": today,
    }
    return render(request, "accounts/my_commissions.html", ctx)

