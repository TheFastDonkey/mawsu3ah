"""Security tests for the accounts app."""

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.core.signing import TimestampSigner
from django.test import Client, TestCase, override_settings
from django.urls import reverse

User = get_user_model()


class CsrfTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="csrf@example.com",
            username="csrfuser",
            password="pass",
        )
        self.client = Client(enforce_csrf_checks=True)

    def test_login_requires_csrf(self):
        response = self.client.post(
            reverse("login"),
            {"username": self.user.email, "password": "pass"},
        )
        self.assertEqual(response.status_code, 403)

    def test_register_requires_csrf(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "newuser",
                "email": "new@example.com",
                "password1": "complexpass123",
                "password2": "complexpass123",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_magic_link_request_requires_csrf(self):
        response = self.client.post(
            reverse("magic_link_request"),
            {"email": self.user.email},
        )
        self.assertEqual(response.status_code, 403)


class RateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="ratelimit@example.com",
            username="ratelimituser",
            password="pass",
        )
        self.client = Client()

    def _fetch_csrf(self, url):
        # Prime the CSRF cookie so subsequent POSTs pass the middleware.
        self.client.get(url)

    def test_login_rate_limited_after_five_attempts_per_ip(self):
        self._fetch_csrf(reverse("login"))
        for _ in range(5):
            response = self.client.post(
                reverse("login"),
                {"username": self.user.email, "password": "wrong"},
            )
            self.assertIn(response.status_code, [200, 302])

        response = self.client.post(
            reverse("login"),
            {"username": self.user.email, "password": "wrong"},
        )
        self.assertEqual(response.status_code, 429)

    def test_login_rate_limited_per_username(self):
        self._fetch_csrf(reverse("login"))
        for _ in range(10):
            response = self.client.post(
                reverse("login"),
                {"username": self.user.email, "password": "wrong"},
            )
            self.assertIn(response.status_code, [200, 302, 429])

        response = self.client.post(
            reverse("login"),
            {"username": self.user.email, "password": "wrong"},
        )
        self.assertEqual(response.status_code, 429)

    def test_magic_link_request_rate_limited_per_email(self):
        self._fetch_csrf(reverse("magic_link_request"))
        for _ in range(3):
            response = self.client.post(
                reverse("magic_link_request"),
                {"email": self.user.email},
            )
            self.assertEqual(response.status_code, 302)

        response = self.client.post(
            reverse("magic_link_request"),
            {"email": self.user.email},
        )
        self.assertEqual(response.status_code, 429)


class MagicLinkTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="magic@example.com",
            username="magicuser",
            password="pass",
        )
        self.client = Client()

    def _request_link(self):
        self.client.post(reverse("magic_link_request"), {"email": self.user.email})
        self.user.refresh_from_db()

    def _build_url(self):
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        signer = TimestampSigner(salt="mawsu3ah:magic-link")
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = signer.sign(f"{self.user.pk}:{self.user.magic_link_nonce}")
        return reverse("magic_link_verify", kwargs={"uidb64": uid, "token": token})

    def test_magic_link_single_use(self):
        self._request_link()
        url = self._build_url()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home"))

        # Second use must fail. Log out first so we don't hit the
        # already-authenticated redirect.
        self.client.logout()
        response = self.client.get(url)
        self.assertRedirects(response, reverse("magic_link_request"))

    def test_magic_link_anti_enumeration(self):
        response = self.client.post(
            reverse("magic_link_request"),
            {"email": "does-not-exist@example.com"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_magic_link_rejected(self):
        self._request_link()
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        url = reverse(
            "magic_link_verify",
            kwargs={"uidb64": uid, "token": "invalid-token"},
        )
        response = self.client.get(url)
        self.assertRedirects(response, reverse("magic_link_request"))

    def test_disabled_user_magic_link_rejected(self):
        self._request_link()
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        url = self._build_url()
        response = self.client.get(url)
        self.assertRedirects(response, reverse("magic_link_request"))
        # Nonce remains set because the link is treated as invalid/expired.
        self.user.refresh_from_db()
        self.assertTrue(self.user.magic_link_nonce)


class LogoutTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="logout@example.com",
            username="logoutuser",
            password="pass",
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_get_logout_is_rejected(self):
        response = self.client.get(reverse("logout"))
        self.assertEqual(response.status_code, 405)

    def test_post_logout_works(self):
        response = self.client.post(reverse("logout"))
        self.assertEqual(response.status_code, 302)


class DeployCheckTests(TestCase):
    @override_settings(
        DEBUG=False,
        SECRET_KEY="x" * 60,
        ALLOWED_HOSTS=["al-kubra.com"],
        DJANGO_ADMIN_URL="manage",
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "mawsu3ah",
                "USER": "mawsu3ah",
                "PASSWORD": "mawsu3ah",
                "HOST": "localhost",
                "PORT": "5432",
            }
        },
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.dummy.DummyCache",
            }
        },
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        SESSION_COOKIE_SECURE=True,
        CSRF_COOKIE_SECURE=True,
        CSRF_TRUSTED_ORIGINS=["https://al-kubra.com"],
        SECURE_HSTS_SECONDS=0,
    )
    def test_deploy_check_passes_with_valid_production_settings(self):
        # This will raise SystemCheckError if any deployment check fails.
        call_command("check", deploy=True, fail_level="ERROR")

    @override_settings(
        DEBUG=False,
        SECRET_KEY="x" * 60,
        ALLOWED_HOSTS=["al-kubra.com"],
        DJANGO_ADMIN_URL="admin",
    )
    def test_deploy_check_fails_for_default_admin_url(self):
        with self.assertRaises(SystemCheckError):
            call_command("check", deploy=True, fail_level="ERROR")

    @override_settings(
        DEBUG=True,
        SECRET_KEY="x" * 60,
        ALLOWED_HOSTS=["al-kubra.com"],
        DJANGO_ADMIN_URL="manage",
    )
    def test_deploy_check_fails_when_debug_true(self):
        with self.assertRaises(SystemCheckError):
            call_command("check", deploy=True, fail_level="ERROR")
