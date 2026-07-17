"""Base Django settings for mawsu3ah."""

import os
from pathlib import Path

from csp.constants import NONCE, SELF

BASE_DIR = Path(__file__).resolve().parent.parent.parent

INSTALLED_APPS = [
    "accounts.apps.AccountsConfig",
    "encyclopedia.apps.EncyclopediaConfig",
    "moderation.apps.ModerationConfig",
    "django.contrib.admin",
    "django.contrib.sitemaps",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_email",
    "csp",
]

MIDDLEWARE = [
    "mawsu3ah.middleware.TrustedProxyMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "mawsu3ah.middleware.AdminSecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "csp.middleware.CSPMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "mawsu3ah.middleware.RateLimitMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "mawsu3ah.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.media",
                "mawsu3ah.context_processors.sidebar",
            ],
        },
    },
]

WSGI_APPLICATION = "mawsu3ah.wsgi.application"

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ar"
TIME_ZONE = "Asia/Riyadh"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOG_FILE = os.environ.get("LOG_FILE", "")

_log_handlers = ["console"]
if LOG_FILE:
    _log_handlers.append("file")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {
            "format": "{levelname} {asctime} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "loggers": {
        "django.request": {
            "handlers": _log_handlers,
            "level": "WARNING",
            "propagate": False,
        },
        "mawsu3ah.security": {
            "handlers": _log_handlers,
            "level": "INFO",
            "propagate": False,
        },
        "mawsu3ah.admin": {
            "handlers": _log_handlers,
            "level": "INFO",
            "propagate": False,
        },
        "accounts": {
            "handlers": _log_handlers,
            "level": "INFO",
            "propagate": False,
        },
    },
}

if LOG_FILE:
    LOGGING["handlers"]["file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": LOG_FILE,
        "maxBytes": 5 * 1024 * 1024,  # 5 MB
        "backupCount": 5,
        "formatter": "simple",
    }

# Admin URL configuration
DJANGO_ADMIN_URL = os.environ.get("DJANGO_ADMIN_URL", "admin").strip("/")
ADMIN_ALLOWED_IPS = [
    ip.strip() for ip in os.environ.get("ADMIN_ALLOWED_IPS", "").split(",") if ip.strip()
]

# Proxy trust: only honor X-Forwarded-Proto when the direct client is a
# known trusted proxy. TRUST_X_FORWARDED_PROTO alone is not enough.
TRUST_X_FORWARDED_PROTO = (
    os.environ.get("TRUST_X_FORWARDED_PROTO", "false").lower() == "true"
)
TRUSTED_PROXY_IPS = [
    ip.strip() for ip in os.environ.get("TRUSTED_PROXY_IPS", "").split(",") if ip.strip()
]

# Session / CSRF cookie hardening
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14  # 2 weeks

CSRF_COOKIE_HTTPONLY = True  # JS reads the token from a server-rendered <meta> tag
CSRF_COOKIE_SAMESITE = "Lax"

SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

# Rate limiting
RATELIMIT_ENABLE = True
RATELIMIT_USE_CACHE = "default"

# Caching (default in-memory; override via REDIS_URL in production)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

if os.environ.get("REDIS_URL"):
    CACHES["default"] = {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ["REDIS_URL"],
    }

# Content Security Policy
# Lucide icons are loaded from a pinned, SRI-protected CDN URL in base.html.
LUCIDE_CDN_URL = "https://unpkg.com/lucide@0.469.0/dist/umd/lucide.min.js"

CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": [SELF],
        "script-src": [SELF, NONCE, LUCIDE_CDN_URL],
        "style-src": [SELF, NONCE, "https://fonts.googleapis.com"],
        "style-src-elem": [SELF, NONCE, "https://fonts.googleapis.com"],
        "font-src": [SELF, "https://fonts.gstatic.com"],
        "img-src": [SELF, "data:"],
        "connect-src": [SELF],
        "frame-ancestors": [SELF],
        "form-action": [SELF],
        "base-uri": [SELF],
        "report-uri": ["/csp-report/"],
        "upgrade-insecure-requests": False,
    }
}

# Contact / outbound email
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "admin@example.com")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@example.com")

# Email-based OTP for the admin site
# Tokens are sent via Django's email backend and are valid for 5 minutes.
OTP_EMAIL_SENDER = DEFAULT_FROM_EMAIL
OTP_EMAIL_SUBJECT = "رمز الدخول إلى لوحة إدارة الموسوعة"
OTP_EMAIL_TOKEN_VALIDITY = 300  # seconds
OTP_EMAIL_BODY_TEMPLATE_PATH = "otp/email/token.txt"
OTP_EMAIL_BODY_HTML_TEMPLATE_PATH = "otp/email/token.html"
