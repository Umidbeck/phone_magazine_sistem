from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    '''Majburiy parol o'zgartirish middleware'''

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            if getattr(request.user, 'must_change_password', False):
                # Faqat password change sahifasiga ruxsat
                allowed_urls = [
                    reverse('force_password_change'),
                    reverse('logout'),
                    reverse('password_requirements'),
                ]

                if request.path not in allowed_urls:
                    return redirect('force_password_change')

        return self.get_response(request)