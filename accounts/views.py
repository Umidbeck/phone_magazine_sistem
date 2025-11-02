# accounts/views.py
import json
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
from django.utils import timezone as dj_tz
from core.utils import parse_decimal, is_owner, DECIMAL_ZERO as D0, is_seller

from inventory.models import Product
from sales.models import Transaction, SellerCommission, SellerMonthlyStat
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
def home_dashboard(request):
    """
    Asosiy dashboard

    ROUTING:
    - Owner/Manager → owner_dashboard
    - Seller → seller_dashboard
    - Other → basic_dashboard
    """
    user = request.user

    if is_owner(user):
        return owner_dashboard(request)
    elif is_seller(user):
        return seller_dashboard(request)
    else:
        return basic_dashboard(request)


# ============================================
# SELLER DASHBOARD
# ============================================

@login_required
def seller_dashboard(request):
    """
    Sotuvchi dashboard (faqat o'z DO'KONI bo'yicha)
    """
    user = request.user
    store_id = getattr(user, 'store_id', None)  # muhimi shu

    today = dj_tz.now().date()
    week_ago = today - timedelta(days=7)
    month_start = today.replace(day=1)

    # === TODAY STATS (faqat o'z do'koni) ===
    today_sales = Transaction.objects.filter(
        type='sale',
        seller=user,
        is_approved=True,
        is_void=False,
        created_at__date=today,
        store_id=store_id,               # <-- do'kon cheklovi
    )

    today_count = today_sales.count()
    today_amount = parse_decimal(today_sales.aggregate(s=Sum('amount'))['s'] or D0)
    today_profit = parse_decimal(today_sales.aggregate(s=Sum('profit'))['s'] or D0)

    # === WEEK STATS ===
    week_sales = Transaction.objects.filter(
        type='sale',
        seller=user,
        is_approved=True,
        is_void=False,
        created_at__date__gte=week_ago,
        store_id=store_id,               # <-- do'kon cheklovi
    )
    week_count = week_sales.count()
    week_amount = parse_decimal(week_sales.aggregate(s=Sum('amount'))['s'] or D0)

    # === MONTH STATS ===
    month_sales = Transaction.objects.filter(
        type='sale',
        seller=user,
        is_approved=True,
        is_void=False,
        created_at__date__gte=month_start,
        store_id=store_id,               # <-- do'kon cheklovi
    )
    month_count = month_sales.count()
    month_amount = parse_decimal(month_sales.aggregate(s=Sum('amount'))['s'] or D0)

    # === COMMISSIONS (faqat sotuvchining o'zi) ===
    commissions = SellerCommission.objects.filter(
        seller=user,
        is_approved=True,
        is_rescinded=False,
        # Agar komissiya ham do'kon bo'yicha saqlansa, qo'shing:
        # store_id=store_id,
    )
    total_commission = parse_decimal(commissions.aggregate(s=Sum('amount'))['s'] or D0)
    unpaid_commission = parse_decimal(
        commissions.filter(is_paid=False, amount__gt=0).aggregate(s=Sum('amount'))['s'] or D0
    )
    pending_commission = parse_decimal(
        SellerCommission.objects.filter(
            seller=user,
            is_approved=False,
            is_rescinded=False,
            # agar kerak bo'lsa: store_id=store_id,
        ).aggregate(s=Sum('amount'))['s'] or D0
    )

    # === RECENT SALES (faqat o'z do'koni) ===
    recent_sales = list(
        Transaction.objects.filter(
            type='sale',
            seller=user,
            is_approved=True,
            is_void=False,  # ⚠️ Qaytarilgan telefonlarni o'chirish
            store_id=store_id,            # <-- do'kon cheklovi
        ).select_related(
            'product__brand',
            'product__model',
            'store'
        ).order_by('-created_at')[:10]
    )

    # === MONTHLY RANKING (faqat shu do'kon ichida) ===
    month_key = today.strftime("%Y-%m")

    # Variant A: SellerMonthlyStat da store bor (tavsiya etiladi)
    my_stat = SellerMonthlyStat.objects.filter(
        seller=user,
        month_key=month_key,
        store_id=store_id,               # <-- do'kon cheklovi
    ).first()
    my_sales_count = my_stat.sales_count if my_stat else 0

    leaderboard = list(
        SellerMonthlyStat.objects.filter(
            month_key=month_key,
            store_id=store_id,           # <-- do'kon cheklovi
        ).select_related('seller').order_by('-sales_count')[:5]
    )

    my_rank = None
    for idx, stat in enumerate(leaderboard, 1):
        if stat.seller_id == user.id:
            my_rank = idx
            break

    # === 7 KUNLIK CHART (faqat o'z do'koni) ===
    chart_data = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_sales = Transaction.objects.filter(
            type='sale',
            seller=user,
            is_approved=True,
            is_void=False,
            created_at__date=day,
            store_id=store_id,            # <-- do'kon cheklovi
        )
        count = day_sales.count()
        amount = parse_decimal(day_sales.aggregate(s=Sum('amount'))['s'] or D0)

        chart_data.append({
            'date': day.strftime("%d.%m"),
            'count': count,
            'amount': float(amount),
        })

    # === AVAILABLE PHONES (o'z do'koni) ===
    available_phones = Product.objects.filter(
        status='available',
        store_id=store_id                # allaqachon shunday edi, yaxshi
    ).count()

    context = {
        'user_type': 'seller',

        # Today
        'today_count': today_count,
        'today_amount': today_amount,
        'today_profit': today_profit,

        # Week
        'week_count': week_count,
        'week_amount': week_amount,

        # Month
        'month_count': month_count,
        'month_amount': month_amount,

        # Commissions
        'total_commission': total_commission,
        'unpaid_commission': unpaid_commission,
        'pending_commission': pending_commission,

        # Recent
        'recent_sales': recent_sales,

        # Ranking
        'my_sales_count': my_sales_count,
        'my_rank': my_rank,
        'leaderboard': leaderboard,
        'target': 50,
        'progress': (my_sales_count / 50 * 100) if my_sales_count < 50 else 100,

        # Chart
        'chart_data': json.dumps(chart_data),

        # Inventory
        'available_phones': available_phones,
    }

    return render(request, 'accounts/dashboard_seller.html', context)


# ============================================
# OWNER DASHBOARD
# ============================================

def owner_dashboard(request):
    """
    Owner/Manager dashboard

    STATS:
    - Umumiy sotuvlar
    - Foyda
    - Kassa balansi
    - Inventory
    - Seller performance
    - Recent activities
    """
    today = dj_tz.now().date()
    week_ago = today - timedelta(days=7)
    month_start = today.replace(day=1)

    # Store filter
    store_id = request.GET.get('store_id')
    if store_id and store_id.isdigit():
        store_id = int(store_id)
    else:
        store_id = None

    stores = Store.objects.filter(is_active=True).order_by('name')

    # Scope helper
    def _scope(qs):
        return qs.filter(store_id=store_id) if store_id else qs

    # === TODAY STATS ===
    today_sales = _scope(Transaction.objects.filter(
        type='sale',
        is_approved=True,
        is_void=False,
        created_at__date=today
    ))

    today_count = today_sales.count()
    today_amount = parse_decimal(today_sales.aggregate(s=Sum('amount'))['s'] or D0)
    today_profit = parse_decimal(today_sales.aggregate(s=Sum('profit'))['s'] or D0)

    today_expenses = _scope(Transaction.objects.filter(
        type='expense',
        is_approved=True,
        is_void=False,
        product__isnull=True,
        created_at__date=today
    ))
    today_expense = parse_decimal(today_expenses.aggregate(s=Sum('amount'))['s'] or D0)

    # === WEEK STATS ===
    week_sales = _scope(Transaction.objects.filter(
        type='sale',
        is_approved=True,
        is_void=False,
        created_at__date__gte=week_ago
    ))

    week_count = week_sales.count()
    week_amount = parse_decimal(week_sales.aggregate(s=Sum('amount'))['s'] or D0)
    week_profit = parse_decimal(week_sales.aggregate(s=Sum('profit'))['s'] or D0)

    # === MONTH STATS ===
    month_sales = _scope(Transaction.objects.filter(
        type='sale',
        is_approved=True,
        is_void=False,
        created_at__date__gte=month_start
    ))

    month_count = month_sales.count()
    month_amount = parse_decimal(month_sales.aggregate(s=Sum('amount'))['s'] or D0)
    month_profit = parse_decimal(month_sales.aggregate(s=Sum('profit'))['s'] or D0)

    # === KASSA ===
    from finance.services import compute_cash_balance
    cash_data = compute_cash_balance(request.user, today, store_id)

    total_cash = cash_data['cash_closing'] + cash_data['card_closing']

    # === INVENTORY ===
    inventory_qs = _scope(Product.objects.all())

    total_inventory = inventory_qs.count()
    available_inventory = inventory_qs.filter(status='available').count()
    sold_today = inventory_qs.filter(status='sold', sold_at__date=today).count()

    inventory_value = parse_decimal(
        inventory_qs.filter(status='available').aggregate(
            total=Sum('purchase_price')
        )['total'] or D0
    )

    # === SELLER PERFORMANCE (MONTH) ===
    month_key = today.strftime("%Y-%m")
    seller_stats = list(
        SellerMonthlyStat.objects.filter(
            month_key=month_key
        ).select_related('seller').order_by('-sales_count')[:10]
    )

    # === RECENT ACTIVITIES ===
    recent_sales = list(
        _scope(Transaction.objects.filter(
            type='sale',
            is_approved=True,
            is_void=False  # ⚠️ Qaytarilgan telefonlarni o'chirish
        )).select_related(
            'seller',
            'product__brand',
            'product__model',
            'store'
        ).order_by('-created_at')[:15]
    )

    # === PENDING APPROVALS ===
    pending_commissions = SellerCommission.objects.filter(
        is_approved=False,
        is_rescinded=False
    )
    if store_id:
        pending_commissions = pending_commissions.filter(transaction__store_id=store_id)

    pending_count = pending_commissions.count()

    # === 30 KUNLIK CHART (SALES + PROFIT) ===
    chart_data = []
    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        day_sales = _scope(Transaction.objects.filter(
            type='sale',
            is_approved=True,
            is_void=False,
            created_at__date=day
        ))

        amount = parse_decimal(day_sales.aggregate(s=Sum('amount'))['s'] or D0)
        profit = parse_decimal(day_sales.aggregate(s=Sum('profit'))['s'] or D0)

        chart_data.append({
            'date': day.strftime("%d.%m"),
            'sales': float(amount),
            'profit': float(profit)
        })

    # === TOP BRANDS (MONTH) ===
    top_brands = list(
        _scope(Transaction.objects.filter(
            type='sale',
            is_approved=True,
            is_void=False,
            created_at__date__gte=month_start
        )).values(
            'product__brand__name'
        ).annotate(
            count=Count('id'),
            total=Sum('amount')
        ).order_by('-count')[:5]
    )

    context = {
        'user_type': 'owner',

        # Filters
        'stores': stores,
        'store_id': str(store_id or ''),

        # Today
        'today_count': today_count,
        'today_amount': today_amount,
        'today_profit': today_profit,
        'today_expense': today_expense,

        # Week
        'week_count': week_count,
        'week_amount': week_amount,
        'week_profit': week_profit,

        # Month
        'month_count': month_count,
        'month_amount': month_amount,
        'month_profit': month_profit,

        # Kassa
        'cash_balance': cash_data['cash_closing'],
        'card_balance': cash_data['card_closing'],
        'total_cash': total_cash,

        # Inventory
        'total_inventory': total_inventory,
        'available_inventory': available_inventory,
        'sold_today': sold_today,
        'inventory_value': inventory_value,

        # Sellers
        'seller_stats': seller_stats,

        # Recent
        'recent_sales': recent_sales,

        # Pending
        'pending_count': pending_count,

        # Chart
        'chart_data': json.dumps(chart_data),

        # Top brands
        'top_brands': top_brands,
    }

    return render(request, 'accounts/dashboard_owner.html', context)


# ============================================
# BASIC DASHBOARD
# ============================================

def basic_dashboard(request):
    """
    Oddiy foydalanuvchi uchun dashboard
    """
    context = {
        'user_type': 'basic',
    }
    return render(request, 'core/dashboard_basic.html', context)


def owner_only(request):
    return request.user.is_authenticated and request.user.is_owner

# ----- STORE CRUD -----
@login_required
def store_list(request):
    if not owner_only(request):
        return HttpResponseForbidden()

    items = Store.objects.order_by("name")

    # Statistika hisoblash
    active_count = items.filter(is_active=True).count()
    inactive_count = items.filter(is_active=False).count()

    return render(request, "accounts/store_list.html", {
        "items": items,
        "active_count": active_count,
        "inactive_count": inactive_count,
    })

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
def my_sales(request):
    period = (request.GET.get("period") or "month")
    today = date.today()
    if period == "day":
        df = today
    elif period == "week":
        df = today - timedelta(days=6)
    elif period == "year":
        df = today - timedelta(days=364)
    else:
        df = today - timedelta(days=29)

    qs = (Transaction.objects
          .select_related("product", "product__brand", "product__model", "store", "seller", "commission")
          .filter(type="sale", seller_id=request.user.id,
                  is_void=False,  # ⚠️ MUHIM: Qaytarilgan telefonlarni o'chirish!
                  created_at__date__range=(df, today))
          .order_by("-created_at"))

    total_amount = qs.aggregate(s=Sum("amount"))["s"] or 0
    total_profit = qs.aggregate(s=Sum("profit"))["s"] or 0

    ctx = dict(
        rows=list(qs[:1000]),
        total_amount=total_amount,
        total_profit=total_profit,
        date_from=df, date_to=today, period=period,
    )
    return render(request, "my_sales.html", ctx)