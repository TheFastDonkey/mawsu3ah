"""Development settings."""

import importlib.util
import os
import sys

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from .base import *

load_dotenv(BASE_DIR / ".env")

DEBUG = os.environ.get("DJANGO_DEBUG", "0").lower() in ("1", "true")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set.")

_allowed_hosts = os.environ.get("DJANGO_ALLOWED_HOSTS", "")
if _allowed_hosts:
    ALLOWED_HOSTS = [host.strip() for host in _allowed_hosts.split(",") if host.strip()]
else:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Enable debug toolbar in development, but keep it out of the test runner.
RUNNING_TESTS = "test" in sys.argv
ENABLE_DEBUG_TOOLBAR = DEBUG and not RUNNING_TESTS and os.environ.get("DISABLE_DEBUG_TOOLBAR") != "1"

if ENABLE_DEBUG_TOOLBAR and importlib.util.find_spec("debug_toolbar") is not None:
    INSTALLED_APPS = ["debug_toolbar"] + INSTALLED_APPS
    MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware"] + MIDDLEWARE
    INTERNAL_IPS = ["127.0.0.1"]

if os.environ.get("USE_SQLITE") == "1":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "mawsu3ah"),
            "USER": os.environ.get("DB_USER", "mawsu3ah"),
            "PASSWORD": os.environ.get("DB_PASSWORD"),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }
    if not DATABASES["default"]["PASSWORD"]:
        raise ImproperlyConfigured("DB_PASSWORD must be set when using PostgreSQL.")

# Email backend is controlled by .env. Defaults to console for local dev,
# set EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend to use real SMTP.
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "true").lower() == "true"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@example.com")

# Dev-only allowance so impeccable live mode can load. Guarded by DEBUG.
_impeccable_live_dev = ["http://localhost:8400"] if DEBUG else []
CONTENT_SECURITY_POLICY["DIRECTIVES"]["script-src"].extend(_impeccable_live_dev)
CONTENT_SECURITY_POLICY["DIRECTIVES"]["connect-src"].extend(_impeccable_live_dev)
