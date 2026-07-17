"""Project-level view handlers."""

import json
import logging

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage
from django.http import HttpResponse, HttpResponseServerError, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt
from django_ratelimit.core import is_ratelimited
from django_ratelimit.decorators import ratelimit

from .forms import ContactForm

csp_logger = logging.getLogger("mawsu3ah.csp")

RATELIMITED_TEXT = (
    "تم تجاوز الحد المسموح. يرجى الانتظار قليلاً والمحاولة مرة أخرى."
)


@csrf_exempt
@ratelimit(key="ip", rate="10/m", method="POST")
def csp_report(request):
    """Accept Content-Security-Policy violation reports from browsers."""
    if request.method != "POST":
        return HttpResponse(status=405)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        payload = {}
    report = payload.get("csp-report", {})
    csp_logger.warning("CSP violation: %s", report)
    return HttpResponse(status=204)


def ratelimited_error(request, exception):
    """Return a 429 response suitable for both full pages and HTMX swaps."""
    if request.headers.get("HX-Request") == "true":
        html = render_to_string(
            "components/core/alert.html",
            {"message": RATELIMITED_TEXT, "type": "warning"},
        )
        return HttpResponse(html, status=429)

    html = render_to_string(
        "429.html",
        {"message": RATELIMITED_TEXT},
    )
    return HttpResponse(html, status=429)


def health_check(request):
    """Lightweight health check for load balancers and orchestrators."""
    return JsonResponse({"status": "ok"})


def page_not_found(request, exception):
    """Custom 404 handler."""
    return render(
        request,
        "404.html",
        {"message": "لم نجد الصفحة التي تبحث عنها."},
        status=404,
    )


def server_error(request):
    """Custom 500 handler.

    Uses render_to_string so a template/context failure during the original
    request does not cascade into another exception.
    """
    html = render_to_string("500.html", {})
    return HttpResponseServerError(html)


def about(request):
    """Static about-us page."""
    return render(request, "pages/about.html")


def contact(request):
    """Contact form page.

    Sends an email to the configured contact address on valid POST and shows
    an inline message when the rate limit is exceeded.
    """
    if request.method == "POST":
        form = ContactForm(request.POST)
        ratelimited = is_ratelimited(
            request,
            group="contact",
            key="user_or_ip",
            rate="5/m",
            increment=True,
            method=is_ratelimited.ALL,
        )
        if ratelimited:
            messages.error(
                request,
                "تم تجاوز الحد المسموح به. يرجى الانتظار قليلاً والمحاولة مرة أخرى.",
            )
        elif form.is_valid():
            name = form.cleaned_data["name"]
            email = form.cleaned_data["email"]
            subject = form.cleaned_data["subject"]
            message = form.cleaned_data["message"]
            body = f"من: {name} <{email}>\n\n{message}"
            EmailMessage(
                subject=f"[تواصل] {subject}",
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[settings.CONTACT_EMAIL],
                reply_to=[email],
            ).send()
            messages.success(request, "تم إرسال رسالتك، شكراً لتواصلك معنا.")
            return redirect("contact")
    else:
        initial = {}
        if request.user.is_authenticated:
            initial["name"] = request.user.get_full_name() or request.user.username
            initial["email"] = request.user.email
        form = ContactForm(initial=initial)

    return render(
        request,
        "pages/contact.html",
        {"form": form, "contact_email": settings.CONTACT_EMAIL},
    )
