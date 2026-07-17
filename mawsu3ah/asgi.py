"""ASGI config for mawsu3ah."""

import os

from django.core.asgi import get_asgi_application
from dotenv import load_dotenv

load_dotenv()

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mawsu3ah.settings.prod")

application = get_asgi_application()
