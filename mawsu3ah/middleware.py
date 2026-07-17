"""Project-level middleware."""

import ipaddress
import logging

from django.conf import settings
from django.http import HttpResponseForbidden
from django_ratelimit.exceptions import Ratelimited

from .views import ratelimited_error

logger = logging.getLogger("mawsu3ah.security")


def _client_ip(request):
    trust_xff = getattr(settings, "ADMIN_TRUST_X_FORWARDED_FOR", False)
    if trust_xff:
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            # The leftmost IP is the original client. The rightmost IPs are
            # the proxies closest to the application. Don't let clients inject
            # arbitrary values at the right end of the chain.
            candidate = x_forwarded_for.split(",")[0].strip()
            if _is_valid_public_ip(candidate):
                return candidate
    return request.META.get("REMOTE_ADDR")


def _is_valid_public_ip(ip):
    """Return True for a syntactically valid non-private IP address."""
    if ip is None:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_unspecified)


class TrustedProxyMiddleware:
    """
    Validate proxy-provided HTTPS signals.

    Only trust ``X-Forwarded-Proto`` when the direct connection comes from a
    configured trusted proxy IP. This prevents clients from spoofing ``https``
    and bypassing cookie security flags.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        trust_proto = getattr(settings, "TRUST_X_FORWARDED_PROTO", False)
        trusted_proxies = getattr(settings, "TRUSTED_PROXY_IPS", [])
        if trust_proto and trusted_proxies:
            remote_addr = request.META.get("REMOTE_ADDR")
            if self._is_trusted_proxy(remote_addr, trusted_proxies):
                forwarded_proto = request.META.get("HTTP_X_FORWARDED_PROTO", "").lower()
                if forwarded_proto == "https":
                    request.META["HTTPS"] = "on"
                    request.META["wsgi.url_scheme"] = "https"
                elif forwarded_proto == "http":
                    request.META["HTTPS"] = "off"
                    request.META["wsgi.url_scheme"] = "http"
        return self.get_response(request)

    @staticmethod
    def _is_trusted_proxy(remote_addr, trusted_proxies):
        if remote_addr is None:
            return False
        try:
            remote_ip = ipaddress.ip_address(remote_addr)
        except ValueError:
            return False
        for proxy in trusted_proxies:
            try:
                if "/" in proxy:
                    if remote_ip in ipaddress.ip_network(proxy, strict=False):
                        return True
                elif remote_ip == ipaddress.ip_address(proxy):
                    return True
            except ValueError:
                continue
        return False


class AdminSecurityMiddleware:
    """
    Harden admin access:
    - Block requests to the default ``/admin/`` path in production when a
      custom admin URL is configured.
    - Restrict admin access to a configured IP allow-list.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        admin_url = getattr(settings, "DJANGO_ADMIN_URL", "admin").strip("/")

        # Honeytoken / hard-coded admin path protection.
        if admin_url != "admin" and path.startswith("/admin/"):
            logger.warning(
                "Blocked request to default /admin/ path from IP %s",
                _client_ip(request),
            )
            return HttpResponseForbidden("Admin interface is not available at this location.")

        admin_prefix = f"/{admin_url}/"
        if path.startswith(admin_prefix):
            allowed_ips = getattr(settings, "ADMIN_ALLOWED_IPS", [])
            if allowed_ips:
                client_ip = _client_ip(request)
                if client_ip not in allowed_ips:
                    logger.warning(
                        "Blocked admin access from IP %s (allowed: %s)",
                        client_ip,
                        allowed_ips,
                    )
                    return HttpResponseForbidden(
                        "Admin access is restricted to authorized networks."
                    )

        return self.get_response(request)


class RateLimitMiddleware:
    """Convert django-ratelimit's Ratelimited exception into a 429 response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, Ratelimited):
            return ratelimited_error(request, exception)
        return None
