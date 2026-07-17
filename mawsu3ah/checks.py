"""Deployment security checks."""

from django.conf import settings
from django.core.checks import Error, Warning, register


@register(deploy=True)
def production_security_check(app_configs, **kwargs):
    """Validate that production settings are secure."""
    errors = []
    warnings = []

    secret_key = getattr(settings, "SECRET_KEY", "")
    if not secret_key or len(secret_key) < 50:
        errors.append(
            Error(
                "SECRET_KEY is missing or too short.",
                hint="Set a strong SECRET_KEY environment variable (>= 50 chars).",
                id="mawsu3ah.security.E001",
            )
        )

    if getattr(settings, "DEBUG", True):
        errors.append(
            Error(
                "DEBUG must be False in production.",
                id="mawsu3ah.security.E002",
            )
        )

    allowed_hosts = getattr(settings, "ALLOWED_HOSTS", [])
    if not allowed_hosts or "*" in allowed_hosts:
        errors.append(
            Error(
                "ALLOWED_HOSTS must be set and not contain a wildcard.",
                id="mawsu3ah.security.E003",
            )
        )

    admin_url = getattr(settings, "DJANGO_ADMIN_URL", "admin")
    if not admin_url or admin_url.lower() == "admin":
        errors.append(
            Error(
                "DJANGO_ADMIN_URL must be set to a non-default path in production.",
                id="mawsu3ah.security.E004",
            )
        )

    db_engine = settings.DATABASES.get("default", {}).get("ENGINE", "")
    if "sqlite" in db_engine:
        errors.append(
            Error(
                "SQLite must not be used as the production database.",
                id="mawsu3ah.security.E005",
            )
        )

    email_backend = getattr(settings, "EMAIL_BACKEND", "")
    if "console" in email_backend:
        errors.append(
            Error(
                "EMAIL_BACKEND is set to the console backend in production.",
                id="mawsu3ah.security.E006",
            )
        )

    if not getattr(settings, "SESSION_COOKIE_SECURE", False):
        errors.append(
            Error(
                "SESSION_COOKIE_SECURE must be True in production.",
                id="mawsu3ah.security.E007",
            )
        )

    if not getattr(settings, "CSRF_COOKIE_SECURE", False):
        errors.append(
            Error(
                "CSRF_COOKIE_SECURE must be True in production.",
                id="mawsu3ah.security.E008",
            )
        )

    csrf_origins = getattr(settings, "CSRF_TRUSTED_ORIGINS", [])
    if not csrf_origins:
        errors.append(
            Error(
                "CSRF_TRUSTED_ORIGINS must be set in production.",
                id="mawsu3ah.security.E009",
            )
        )
    else:
        for origin in csrf_origins:
            if not origin.startswith("https://") or "*" in origin:
                errors.append(
                    Error(
                        f"CSRF_TRUSTED_ORIGINS contains an invalid origin: {origin!r}.",
                        hint="Origins must use https:// and must not contain wildcards.",
                        id="mawsu3ah.security.E010",
                    )
                )

    hsts_seconds = getattr(settings, "SECURE_HSTS_SECONDS", 0)
    ssl_redirect = getattr(settings, "SECURE_SSL_REDIRECT", False)
    if hsts_seconds and not ssl_redirect:
        errors.append(
            Error(
                "SECURE_HSTS_SECONDS is set but SECURE_SSL_REDIRECT is False.",
                id="mawsu3ah.security.E011",
            )
        )

    cache_backend = settings.CACHES.get("default", {}).get("BACKEND", "")
    if "LocMemCache" in cache_backend:
        errors.append(
            Error(
                "Production cache must not be LocMemCache.",
                hint="Set REDIS_URL to use a shared cache backend for rate limiting and sessions.",
                id="mawsu3ah.security.E012",
            )
        )

    hsts_seconds = getattr(settings, "SECURE_HSTS_SECONDS", 0)
    if not hsts_seconds:
        warnings.append(
            Warning(
                "SECURE_HSTS_SECONDS is not set.",
                hint="Once HTTPS is confirmed working, set SECURE_HSTS_SECONDS to a short value, "
                     "then increase it to one year. Keep it at 0 only during initial HTTPS rollout.",
                id="mawsu3ah.security.W013",
            )
        )

    return errors + warnings
