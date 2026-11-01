from django.conf import settings
from django.contrib.admin import AdminSite
from django.contrib.admin.forms import AdminAuthenticationForm
from django_otp.admin import OTPAdminSite


class ContestAdminSite(OTPAdminSite):
    if not settings.REQUIRE_ADMIN_MFA:
        login_form = AdminAuthenticationForm
        login_template = "admin/login.html"

    def has_permission(self, request):
        if settings.REQUIRE_ADMIN_MFA:
            return super().has_permission(request)
        return AdminSite.has_permission(self, request)
