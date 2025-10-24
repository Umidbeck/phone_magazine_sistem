# accounts/views_password.py - PAROL O'ZGARTIRISH
"""
Password Change Views

XUSUSIYATLAR:
✅ change_password - Har kim o'z parolini o'zgartiradi
✅ reset_seller_password - Owner sotuvchi parolini tiklaydi
✅ Validation - eski parol, yangi parol kuchi
✅ Security - Django'ning password validation
"""

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseForbidden

from accounts.models import User
from core.utils import is_owner


# ============================================
# PAROL O'ZGARTIRISH (O'ZI UCHUN)
# ============================================

@login_required
def change_password(request):
    """
    Foydalanuvchi o'z parolini o'zgartiradi

    QOIDALAR:
    ✅ Eski parol to'g'ri bo'lishi kerak
    ✅ Yangi parol kuchli bo'lishi kerak
    ✅ Yangi parol takrorlanishi kerak
    ✅ Session saqlanadi (logout bo'lmaydi)
    """
    if request.method == 'POST':
        old_password = request.POST.get('old_password', '')
        new_password1 = request.POST.get('new_password1', '')
        new_password2 = request.POST.get('new_password2', '')

        # Eski parol tekshiruvi
        if not request.user.check_password(old_password):
            messages.error(request, "Eski parol noto'g'ri")
            return render(request, 'accounts/change_password.html')

        # Yangi parollar bir xilligini tekshirish
        if new_password1 != new_password2:
            messages.error(request, "Yangi parollar mos kelmadi")
            return render(request, 'accounts/change_password.html')

        # Yangi parol eski bilan bir xil emas
        if old_password == new_password1:
            messages.error(request, "Yangi parol eski paroldan farq qilishi kerak")
            return render(request, 'accounts/change_password.html')

        # Parol kuchi tekshiruvi
        try:
            validate_password(new_password1, request.user)
        except ValidationError as e:
            for error in e.messages:
                messages.error(request, error)
            return render(request, 'accounts/change_password.html')

        # Parol o'zgartirish
        request.user.set_password(new_password1)
        request.user.save()

        # Session saqlash (logout bo'lmasin)
        update_session_auth_hash(request, request.user)

        messages.success(request, "Parol muvaffaqiyatli o'zgartirildi!")
        return redirect('home')

    return render(request, 'accounts/change_password.html')


# ============================================
# SOTUVCHI PAROLINI TIKLASH (OWNER UCHUN)
# ============================================

@login_required
def seller_reset_password(request, pk):
    """
    Owner sotuvchi parolini tiklaydi

    FAQAT OWNER!

    Yangi parol:
    - Avtomatik generatsiya
    - Kuchli va xavfsiz
    - Owner ko'radi va sotuvchiga aytadi
    """
    # Faqat owner
    if not is_owner(request.user):
        return HttpResponseForbidden("Faqat owner sotuvchi parolini tiklashi mumkin")

    seller = get_object_or_404(User, pk=pk)

    # Faqat seller rolini
    if seller.role != 'seller':
        messages.error(request, "Faqat sotuvchilar uchun")
        return redirect('seller_list')

    # Owner o'zini tiklay olmaydi
    if seller == request.user:
        messages.error(request, "O'z parolingizni 'Parol o'zgartirish' orqali o'zgartirasiz")
        return redirect('change_password')

    if request.method == 'POST':
        # Yangi parol generatsiya
        import secrets
        import string

        # Kuchli parol: 12 belgi, harflar, raqamlar, belgilar
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        new_password = ''.join(secrets.choice(alphabet) for _ in range(12))

        # Parol o'rnatish
        seller.set_password(new_password)
        seller.save()

        # Owner'ga ko'rsatish
        messages.success(
            request,
            f"Yangi parol: <strong>{new_password}</strong><br>"
            f"Ushbu parolni {seller.get_full_name() or seller.username} ga yuboring.<br>"
            f"<span class='text-warning'>MUHIM: Parolni eslab qoling! U yana ko'rsatilmaydi.</span>"
        )

        return redirect('seller_list')

    # GET - Tasdiqlash sahifasi
    return render(request, 'accounts/seller_reset_password.html', {
        'seller': seller
    })


# ============================================
# PAROL KUCHI TEKSHIRUVI (AJAX)
# ============================================

from django.http import JsonResponse


@login_required
def check_password_strength(request):
    """
    AJAX orqali parol kuchini tekshirish

    RESPONSE:
    {
        'valid': bool,
        'errors': [],
        'strength': 'weak' | 'medium' | 'strong',
        'score': 0-100
    }
    """
    password = request.GET.get('password', '')

    if not password:
        return JsonResponse({
            'valid': False,
            'errors': ['Parol kiritilmagan'],
            'strength': 'weak',
            'score': 0
        })

    # Django validation
    errors = []
    try:
        validate_password(password, request.user)
        valid = True
    except ValidationError as e:
        valid = False
        errors = list(e.messages)

    # Kuch baholash
    score = 0

    # Uzunlik (max 40 ball)
    length = len(password)
    score += min(length * 4, 40)

    # Kichik harflar (10 ball)
    if any(c.islower() for c in password):
        score += 10

    # Katta harflar (10 ball)
    if any(c.isupper() for c in password):
        score += 10

    # Raqamlar (10 ball)
    if any(c.isdigit() for c in password):
        score += 10

    # Maxsus belgilar (20 ball)
    special_chars = "!@#$%^&*()_+-=[]{}|;:,.<>?"
    if any(c in special_chars for c in password):
        score += 20

    # Xilma-xillik (10 ball)
    unique_chars = len(set(password))
    if unique_chars >= length * 0.7:
        score += 10

    # Kuch darajasi
    if score < 40:
        strength = 'weak'
    elif score < 70:
        strength = 'medium'
    else:
        strength = 'strong'

    return JsonResponse({
        'valid': valid,
        'errors': errors,
        'strength': strength,
        'score': score
    })


# ============================================
# PAROL REQUIREMENTS (MA'LUMOT)
# ============================================

@login_required
def password_requirements(request):
    """
    Parol talablari haqida ma'lumot sahifasi

    CONTENT:
    - Minimal uzunlik
    - Harf, raqam, belgilar
    - Umumiy parollar ro'yxati
    - Misollar
    """
    from django.contrib.auth.password_validation import get_password_validators
    from django.conf import settings

    validators = get_password_validators(settings.AUTH_PASSWORD_VALIDATORS)

    requirements = []
    for validator in validators:
        help_text = validator.get_help_text()
        if help_text:
            requirements.append(help_text)

    ctx = {
        'requirements': requirements,
        'examples': {
            'weak': ['12345678', 'password', 'qwerty123'],
            'medium': ['Pass123!', 'MyPhone2024', 'Store#123'],
            'strong': ['P@ssw0rd!2024', 'MyStr0ng#Pass', 'Uz&Tek2024!']
        }
    }

    return render(request, 'accounts/password_requirements.html', ctx)


# ============================================
# FORCED PASSWORD CHANGE
# ============================================

@login_required
def force_password_change(request):
    """
    Majburiy parol o'zgartirish

    SCENARIO:
    - Birinchi kirish
    - Admin parolni tiklagan
    - Xavfsizlik sababli

    User bu sahifadan chiqishi mumkin emas!
    """
    # Agar allaqachon o'zgartirgan bo'lsa
    if not getattr(request.user, 'must_change_password', False):
        return redirect('home')

    if request.method == 'POST':
        new_password1 = request.POST.get('new_password1', '')
        new_password2 = request.POST.get('new_password2', '')

        # Validation
        if new_password1 != new_password2:
            messages.error(request, "Parollar mos kelmadi")
            return render(request, 'accounts/force_password_change.html')

        try:
            validate_password(new_password1, request.user)
        except ValidationError as e:
            for error in e.messages:
                messages.error(request, error)
            return render(request, 'accounts/force_password_change.html')

        # Parol o'rnatish
        request.user.set_password(new_password1)
        request.user.must_change_password = False
        request.user.save()

        # Session saqlash
        update_session_auth_hash(request, request.user)

        messages.success(request, "Parol muvaffaqiyatli o'rnatildi!")
        return redirect('home')

    return render(request, 'accounts/force_password_change.html')


