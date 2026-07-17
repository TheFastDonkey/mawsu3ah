from django.contrib.auth import views as auth_views
from django.urls import path
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit

from . import views

METHOD_DECORATOR_RLIMIT = method_decorator(
    ratelimit(key="ip", rate="5/h", method="POST"),
    name="dispatch",
)

urlpatterns = [
    path("register/", views.register, name="register"),
    path(
        "verify-email/<uidb64>/<token>/",
        views.verify_email,
        name="verify_email",
    ),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("magic-link/", views.magic_link_request, name="magic_link_request"),
    path(
        "magic-link/<uidb64>/<token>/",
        views.magic_link_verify,
        name="magic_link_verify",
    ),
    path(
        "password-reset/",
        METHOD_DECORATOR_RLIMIT(
            auth_views.PasswordResetView.as_view(template_name="accounts/password_reset.html")
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        METHOD_DECORATOR_RLIMIT(
            auth_views.PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html")
        ),
        name="password_reset_done",
    ),
    path(
        "password-reset-confirm/<uidb64>/<token>/",
        METHOD_DECORATOR_RLIMIT(
            auth_views.PasswordResetConfirmView.as_view(
                template_name="accounts/password_reset_confirm.html"
            )
        ),
        name="password_reset_confirm",
    ),
    path(
        "password-reset-complete/",
        METHOD_DECORATOR_RLIMIT(
            auth_views.PasswordResetCompleteView.as_view(
                template_name="accounts/password_reset_complete.html"
            )
        ),
        name="password_reset_complete",
    ),
    path("profile/", views.profile_redirect, name="profile_redirect"),
    path("settings/", views.account_settings, name="account_settings"),
    path("profile/edit/", views.profile_edit, name="profile_edit"),
    path("contributions/", views.my_contributions, name="my_contributions"),
]
