import hashlib
import logging

from django.apps import AppConfig
from django.contrib.auth.signals import user_logged_in, user_login_failed

security_logger = logging.getLogger("mawsu3ah.security")


def _log_login_failed(sender, credentials, request, **kwargs):
    # Redact the identifier rather than logging the raw username/email.
    identifier = credentials.get("username", "unknown") or "unknown"
    security_logger.info(
        "Failed login attempt from %s for hashed_user=%s",
        _redact_ip(_client_ip(request)),
        _short_hash(identifier),
    )


def _log_login_success(sender, request, user, **kwargs):
    security_logger.info(
        "Successful login for user_pk=%s from %s",
        user.pk,
        _redact_ip(_client_ip(request)),
    )


def _client_ip(request):
    if request is None:
        return "unknown"
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _redact_ip(ip):
    """Return a redacted representation of an IP address.

    IPv4: keep the first two octets and mask the rest (e.g. 192.168.x.x).
    IPv6: keep the first 64 bits (first 4 hextets) and hash the remainder.
    Unknown values and non-IP strings are hashed.
    """
    if not ip or ip == "unknown":
        return "unknown"

    if ":" in ip:
        # IPv6 (or IPv4-mapped IPv6). Keep the first 64 bits / 4 hextets.
        parts = ip.split(":")
        prefix = ":".join(parts[:4]) if len(parts) >= 4 else parts[0]
        remainder = ip[len(prefix) :]
        return f"{prefix}:{_short_hash(remainder)}"

    parts = ip.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return f"{parts[0]}.{parts[1]}.x.x"

    return _short_hash(ip)


def _short_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        user_login_failed.connect(_log_login_failed)
        user_logged_in.connect(_log_login_success)
