from collections import Counter

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django_otp.admin import OTPAdminAuthenticationForm, OTPAdminSite
from django_otp.plugins.otp_email.admin import EmailDeviceAdmin
from django_otp.plugins.otp_email.models import EmailDevice
from django_otp.plugins.otp_totp.admin import TOTPDeviceAdmin
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_ratelimit.decorators import ratelimit

from .models import Profile, User


class Mawsu3ahAdminAuthenticationForm(OTPAdminAuthenticationForm):
    """Admin login form with Arabic OTP error messages."""

    otp_error_messages = {
        **OTPAdminAuthenticationForm.otp_error_messages,
        "token_required": "أدخل رمز التحقق.",
        "invalid_token": "الرمز غير صحيح، تأكد منه.",
        "challenge_exception": "حدث خطأ أثناء إرسال الرمز: {0}",
        "not_interactive": "طريقة التحقق المختارة لا تدعم إرسال الرمز.",
        "verification_not_allowed": "التحقق من الرمز معطل حاليًّا.",
    }

    def _handle_challenge(self, device):
        try:
            return super()._handle_challenge(device)
        except ValidationError as err:
            if isinstance(device, EmailDevice):
                raise ValidationError(
                    "أرسلناالرمز إلى بريدك.",
                    code="challenge_message",
                ) from err
            raise


class Mawsu3ahAdminSite(OTPAdminSite):
    """Custom admin site that surfaces pending moderation requests on the dashboard."""

    index_template = "admin/dashboard_index.html"
    login_template = "admin/otp_login.html"
    login_form = Mawsu3ahAdminAuthenticationForm

    @method_decorator(ratelimit(key="ip", rate="10/m", method=["GET", "POST"]))
    @method_decorator(ratelimit(key="post:username", rate="5/m", method="POST"))
    def login(self, request, extra_context=None):
        return super().login(request, extra_context=extra_context)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "moderation/",
                self.admin_view(self.moderation_dashboard_view),
                name="moderation_dashboard",
            ),
            path(
                "moderation/approve/<str:item_type>/<int:pk>/",
                self.admin_view(self.approve_item_view),
                name="approve_item",
            ),
            path(
                "moderation/reject/<str:item_type>/<int:pk>/",
                self.admin_view(self.reject_item_view),
                name="reject_item",
            ),
        ]
        return custom + urls

    def index(self, request, extra_context=None):
        from moderation.views import ITEM_TYPE_LABELS, _fetch_pending_items

        all_items = _fetch_pending_items()
        counts = dict.fromkeys(ITEM_TYPE_LABELS, 0)
        counts.update(Counter(item["type"] for item in all_items))
        extra_context = extra_context or {}
        extra_context.update(
            {
                "pending_total": len(all_items),
                "pending_counts": counts,
                "pending_labels": ITEM_TYPE_LABELS,
            }
        )
        return super().index(request, extra_context=extra_context)

    def moderation_dashboard_view(self, request):
        from moderation.views import ITEM_TYPE_LABELS, _fetch_pending_items

        all_items = _fetch_pending_items()
        counts = dict.fromkeys(ITEM_TYPE_LABELS, 0)
        counts.update(Counter(item["type"] for item in all_items))
        type_filter = request.GET.get("type")

        if type_filter and type_filter in ITEM_TYPE_LABELS:
            items = [item for item in all_items if item["type"] == type_filter]
        else:
            items = all_items
            type_filter = "all"

        paginator = Paginator(items, 25)
        page_obj = paginator.get_page(request.GET.get("page"))

        context = {
            **self.each_context(request),
            "title": "طلبات المراجعة المعلقة",
            "page_obj": page_obj,
            "count": paginator.count,
            "total_count": len(all_items),
            "type_filter": type_filter,
            "counts": counts,
            "type_labels": ITEM_TYPE_LABELS,
        }
        return render(request, "admin/moderation_dashboard.html", context)

    def _resolve_admin_item(self, request, item_type, pk, action_label):
        from moderation.views import _APPROVE_HANDLERS, _REJECT_HANDLERS

        handlers = _APPROVE_HANDLERS if action_label == "approve" else _REJECT_HANDLERS
        if item_type not in handlers:
            messages.error(request, "نوع الطلب غير معروف.")
            return redirect("admin:moderation_dashboard")

        model, pending_status, handler = handlers[item_type]
        obj = get_object_or_404(model, pk=pk, status=pending_status)
        reason = request.POST.get("rejection_reason", "").strip()

        if action_label == "reject":
            handler(obj, request.user, reason)
        else:
            handler(obj, request.user)

        arabic_action = "اعتماد" if action_label == "approve" else "رفض"
        messages.success(request, f"تم {arabic_action} الطلب بنجاح.")
        return redirect("admin:moderation_dashboard")

    @method_decorator(require_POST)
    def approve_item_view(self, request, item_type, pk):
        return self._resolve_admin_item(request, item_type, pk, "approve")

    @method_decorator(require_POST)
    def reject_item_view(self, request, item_type, pk):
        return self._resolve_admin_item(request, item_type, pk, "reject")


admin.site = Mawsu3ahAdminSite()
admin.sites.site = admin.site

admin.site.register(Group)
admin.site.register(EmailDevice, EmailDeviceAdmin)
admin.site.register(TOTPDevice, TOTPDeviceAdmin)


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = "الملف الشخصي"


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ["username", "email", "is_expert", "email_verified", "reputation", "is_staff"]
    list_filter = ["is_expert", "email_verified", "is_staff", "is_superuser", "groups"]
    search_fields = ["username", "email"]
    ordering = ["username"]
    inlines = [ProfileInline]
    fieldsets = UserAdmin.fieldsets + (
        (
            "Profile",
            {"fields": ("email_verified", "is_expert", "expert_flair", "reputation", "flairs")},
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "email", "password1", "password2"),
            },
        ),
    )
