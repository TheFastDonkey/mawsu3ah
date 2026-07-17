import hashlib
import logging
import secrets

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from .forms import AccountSettingsForm, ProfileEditForm, RegistrationForm
from .tokens import email_verification_token

User = get_user_model()
logger = logging.getLogger(__name__)


@ratelimit(key="ip", rate="5/5m", method="POST")
@ratelimit(key="post:email", rate="10/h", method="POST")
def register(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        form = RegistrationForm(request.POST)
        logger.info("Registration POST received for email=%s", request.POST.get("email"))
        if form.is_valid():
            user = form.save(commit=False)
            user.email_verified = False
            user.save()
            logger.info("User created: pk=%s email=%s", user.pk, user.email)
            try:
                send_verification_email(request, user)
                logger.info("Verification email sent to %s", user.email)
            except Exception as exc:
                logger.exception("Failed to send verification email to %s", user.email)
            messages.success(
                request,
                "تم إنشاء الحساب. تحقق من بريدك الإلكتروني لتفعيل الحساب.",
            )
            return redirect("login")
        else:
            logger.warning("Registration form invalid: %s", form.errors)
    else:
        form = RegistrationForm()

    return render(request, "accounts/register.html", {"form": form})


def send_verification_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    url = request.build_absolute_uri(
        reverse("verify_email", kwargs={"uidb64": uid, "token": token})
    )
    subject = "تفعيل حسابك في الموسوعة الكبرى لأفضل طبعات الكتب"
    message = render_to_string(
        "accounts/emails/verify_email.txt",
        {"user": user, "url": url},
    )
    send_mail(subject, message, None, [user.email])


def verify_email(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and email_verification_token.check_token(user, token):
        user.email_verified = True
        user.save()
        messages.success(request, "تم تفعيل بريدك الإلكتروني بنجاح. يمكنك الآن تسجيل الدخول.")
        return redirect("login")

    messages.error(request, "رابط التفعيل غير صالح أو منتهي الصلاحية.")
    return redirect("register")


def _dummy_magic_link_work(email):
    """Perform crypto/template work comparable to send_magic_link for unknown emails."""
    signer = TimestampSigner(salt="mawsu3ah:magic-link")
    nonce = secrets.token_urlsafe(32)
    dummy = signer.sign(f"0:{nonce}")
    render_to_string(
        "accounts/emails/magic_link.txt",
        {"user": None, "url": dummy},
    )
    hashlib.sha256(email.encode("utf-8")).hexdigest()


@ratelimit(key="ip", rate="5/5m", method="POST")
@ratelimit(key="post:email", rate="3/h", method="POST")
@sensitive_post_parameters("email")
def magic_link_request(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        user = User.objects.filter(email=email).first()
        if user:
            send_magic_link(request, user)
        else:
            _dummy_magic_link_work(email)
        messages.info(
            request,
            "إذا كان البريد مسجلاً، فقد أرسلنا رابطاً للدخول.",
        )
        return redirect("magic_link_request")

    return render(request, "accounts/magic_link_request.html")


@sensitive_variables("token", "nonce")
def send_magic_link(request, user):
    signer = TimestampSigner(salt="mawsu3ah:magic-link")
    nonce = secrets.token_urlsafe(32)
    user.magic_link_nonce = nonce
    user.save(update_fields=["magic_link_nonce"])

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = signer.sign(f"{user.pk}:{nonce}")
    url = request.build_absolute_uri(
        reverse("magic_link_verify", kwargs={"uidb64": uid, "token": token})
    )
    subject = "رابط الدخول السريع إلى الموسوعة الكبرى لأفضل طبعات الكتب"
    message = render_to_string(
        "accounts/emails/magic_link.txt",
        {"user": user, "url": url},
    )
    send_mail(subject, message, None, [user.email])


@sensitive_variables("token")
def magic_link_verify(request, uidb64, token):
    if request.user.is_authenticated:
        return redirect("home")

    signer = TimestampSigner(salt="mawsu3ah:magic-link")
    try:
        signed_value = signer.unsign(token, max_age=600)
        uid = force_str(urlsafe_base64_decode(uidb64))
        pk, nonce = signed_value.split(":", 1)
        if pk != uid:
            raise ValueError("UID mismatch")
        user = User.objects.get(pk=pk, magic_link_nonce=nonce)
    except (BadSignature, SignatureExpired, ValueError, User.DoesNotExist):
        messages.error(request, "رابط الدخول غير صالح أو منتهي الصلاحية.")
        return redirect("magic_link_request")

    if not user.is_active:
        messages.error(request, "رابط الدخول غير صالح أو منتهي الصلاحية.")
        return redirect("magic_link_request")

    # Single-use: invalidate the nonce before login to prevent replay.
    user.magic_link_nonce = ""
    user.save(update_fields=["magic_link_nonce"])

    login(request, user)
    messages.success(request, "تم تسجيل الدخول بنجاح.")
    return redirect("home")


@ratelimit(key="ip", rate="5/5m", method="POST")
@ratelimit(key="post:username", rate="10/30m", method="POST")
def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect("home")
    else:
        form = AuthenticationForm()

    return render(request, "accounts/login.html", {"form": form})


@login_required
@require_POST
def logout_view(request):
    logout(request)
    return redirect("home")


@login_required
def account_settings(request):
    if request.method == "POST":
        form = AccountSettingsForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "تم تحديث إعدادات الحساب.")
            return redirect("account_settings")
    else:
        form = AccountSettingsForm(instance=request.user)

    return render(request, "accounts/settings.html", {"form": form})


def public_profile(request, username):
    profile_user = get_object_or_404(User.objects.select_related("profile"), username=username)
    tab = request.GET.get("tab", "editions")
    valid_tabs = {"editions", "reviews", "categories", "names", "suggestions"}
    if tab not in valid_tabs:
        tab = "editions"

    edition_count = profile_user.submitted_editions.filter(status="approved").count()
    review_count = profile_user.reviews.filter(parent=None, hidden=False).count()
    category_contrib_count = (
        profile_user.category_suggestions.count() + profile_user.category_requests.count()
    )
    name_count = profile_user.submitted_name_records.count()
    suggestion_count = profile_user.edition_edit_suggestions.count()

    page_number = request.GET.get("page", 1)
    context = {
        "profile_user": profile_user,
        "tab": tab,
        "edition_count": edition_count,
        "review_count": review_count,
        "category_contrib_count": category_contrib_count,
        "name_count": name_count,
        "suggestion_count": suggestion_count,
    }

    if tab == "editions":
        qs = (
            profile_user.submitted_editions.filter(status="approved")
            .select_related("book")
            .prefetch_related("book__categories")
            .order_by("-submitted_at")
        )
        paginator = Paginator(qs, 10)
        context["items"] = paginator.get_page(page_number)
    elif tab == "reviews":
        qs = (
            profile_user.reviews.filter(parent=None, hidden=False)
            .select_related("edition__book")
            .order_by("-created_at")
        )
        paginator = Paginator(qs, 10)
        context["items"] = paginator.get_page(page_number)
    elif tab == "categories":
        context["category_suggestions"] = (
            profile_user.category_suggestions.select_related("book", "final_category")
            .order_by("-created_at")[:50]
        )
        context["category_requests"] = (
            profile_user.category_requests.select_related("final_category")
            .order_by("-created_at")[:50]
        )
    elif tab == "names":
        context["name_records"] = (
            profile_user.submitted_name_records.order_by("-submitted_at")[:50]
        )
    elif tab == "suggestions":
        context["edit_suggestions"] = (
            profile_user.edition_edit_suggestions.select_related("edition__book")
            .order_by("-created_at")[:50]
        )

    return render(request, "accounts/public_profile.html", context)


@login_required
@ratelimit(key="ip", rate="10/m", method="POST")
def profile_edit(request):
    profile = request.user.profile
    if request.method == "POST":
        form = ProfileEditForm(
            request.POST, request.FILES, instance=profile
        )
        if form.is_valid():
            form.save()
            messages.success(request, "تم تحديث الملف الشخصي.")
            return redirect("public_profile", username=request.user.username)
    else:
        form = ProfileEditForm(instance=profile)

    return render(request, "accounts/profile_edit.html", {"form": form})


def profile_redirect(request):
    """Redirect the old /accounts/profile/ path to account settings."""
    return redirect("account_settings")


@login_required
def my_contributions(request):
    """List the current user's submissions and moderation requests."""
    editions = (
        request.user.submitted_editions.select_related("book")
        .prefetch_related("publishers", "editors")
        .order_by("-submitted_at")
    )
    category_suggestions = (
        request.user.category_suggestions.select_related("book", "final_category")
        .order_by("-created_at")
    )
    category_requests = (
        request.user.category_requests.select_related("final_category")
        .order_by("-created_at")
    )
    name_records = (
        request.user.submitted_name_records.order_by("-submitted_at")
    )
    edit_suggestions = (
        request.user.edition_edit_suggestions.select_related("edition__book")
        .order_by("-created_at")
    )

    pending_count = sum(
        qs.filter(status="pending").count()
        for qs in (
            editions,
            category_suggestions,
            category_requests,
            name_records,
            edit_suggestions,
        )
    )

    context = {
        "editions": editions,
        "category_suggestions": category_suggestions,
        "category_requests": category_requests,
        "name_records": name_records,
        "edit_suggestions": edit_suggestions,
        "pending_count": pending_count,
    }
    return render(request, "accounts/my_contributions.html", context)
