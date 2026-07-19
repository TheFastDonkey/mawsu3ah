"""Project-level tests for error pages, static pages, and logging."""

import logging
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.core import mail
from django.test import RequestFactory, TestCase
from django.urls import reverse

from encyclopedia.models import Category, EditionStatus
from encyclopedia.test_factories import create_book, create_edition

from . import context_processors, views


class SidebarContextTests(TestCase):
    def test_sidebar_context_includes_root_categories_with_counts(self):
        root = Category.objects.create(name="فقه")
        child = Category.objects.create(name="فقه الحنفي", parent=root)
        book = create_book(title="كتاب", author_name="مؤلف")
        book.categories.add(root)
        create_edition(
            book=book,
            publisher_name="دار",
            year=2020,
            status=EditionStatus.APPROVED,
        )

        request = RequestFactory().get("/")
        context = context_processors.sidebar(request)
        roots = context["sidebar_roots"]

        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0].pk, root.pk)
        self.assertEqual(roots[0].subtree_book_count, 1)
        self.assertEqual(len(roots[0].sidebar_children), 1)
        self.assertEqual(roots[0].sidebar_children[0].pk, child.pk)
        self.assertEqual(roots[0].sidebar_children[0].subtree_book_count, 0)

    def test_sidebar_context_returns_empty_list_when_no_categories(self):
        request = RequestFactory().get("/")
        context = context_processors.sidebar(request)
        self.assertEqual(context["sidebar_roots"], [])

    def test_sidebar_limits_roots_and_children(self):
        roots = [Category.objects.create(name=f"أصل {i}") for i in range(12)]
        for root in roots:
            for j in range(10):
                Category.objects.create(name=f"فرع {root.name} {j}", parent=root)

        request = RequestFactory().get("/")
        context = context_processors.sidebar(request)
        returned_roots = context["sidebar_roots"]

        self.assertEqual(len(returned_roots), context_processors.MAX_SIDEBAR_ROOTS)
        for root in returned_roots:
            self.assertLessEqual(len(root.sidebar_children), context_processors.MAX_SIDEBAR_CHILDREN_PER_ROOT)

    def test_sidebar_renders_on_home_page(self):
        Category.objects.create(name="عقيدة")
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "عقيدة")
        self.assertContains(response, "كل التصنيفات")
        self.assertContains(response, "القائمة الجانبية")


class ErrorPageTests(TestCase):
    def test_404_page_uses_custom_template(self):
        response = self.client.get("/this-page-does-not-exist/")
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")

    def test_500_view_returns_server_error(self):
        request = RequestFactory().get("/")
        response = views.server_error(request)
        self.assertEqual(response.status_code, 500)


class HealthCheckTests(TestCase):
    def test_health_endpoint_returns_ok(self):
        response = self.client.get(reverse("health_check"))
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"status": "ok"})


class SecurityLoggingTests(TestCase):
    def test_failed_login_is_logged(self):
        with self.assertLogs("mawsu3ah.security", level="INFO") as cm:
            self.client.post(
                reverse("login"),
                {"username": "nobody@example.com", "password": "wrong"},
            )
        self.assertTrue(
            any("Failed login attempt" in message for message in cm.output),
            cm.output,
        )

    def test_successful_login_is_logged(self):
        from django.contrib.auth import get_user_model

        user_model = get_user_model()
        user = user_model.objects.create_user(
            email="logger@example.com",
            username="logger",
            password="testpass123",
        )
        with self.assertLogs("mawsu3ah.security", level="INFO") as cm:
            self.client.post(
                reverse("login"),
                {"username": user.email, "password": "testpass123"},
            )
        self.assertTrue(
            any("Successful login" in message for message in cm.output),
            cm.output,
        )


class LoggingConfigurationTests(TestCase):
    def test_expected_loggers_are_configured(self):
        for name in ["mawsu3ah.security", "mawsu3ah.admin", "django.request"]:
            logger = logging.getLogger(name)
            self.assertNotEqual(logger.level, logging.NOTSET)


class DevelopmentSettingsTests(TestCase):
    """Validate that dev.py refuses to start without required secrets."""

    def _run_import(self, env_updates):
        project_root = Path(__file__).resolve().parent.parent
        project_root_str = str(project_root)
        script = f"""
import os
import sys
sys.path.insert(0, {project_root_str!r})
from django.core.exceptions import ImproperlyConfigured
try:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mawsu3ah.settings.dev')
    import django
    django.setup()
except ImproperlyConfigured as exc:
    print('IMPROPERLY_CONFIGURED:', exc)
except Exception as exc:
    print('ERROR:', type(exc).__name__, exc)
"""
        env = os.environ.copy()
        # Clear dev variables that might leak from the running process.
        for key in ("DJANGO_SECRET_KEY", "DB_PASSWORD", "USE_SQLITE"):
            env.pop(key, None)
        env.update(env_updates)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=project_root,
            env=env,
            timeout=30,
        )
        return result

    def test_missing_secret_key_raises(self):
        result = self._run_import({"DB_PASSWORD": "secret", "USE_SQLITE": "1"})
        self.assertIn(
            "IMPROPERLY_CONFIGURED: DJANGO_SECRET_KEY must be set.",
            result.stdout + result.stderr,
        )

    def test_missing_db_password_raises_for_postgres(self):
        result = self._run_import({
            "DJANGO_SECRET_KEY": "x" * 60,
            "USE_SQLITE": "0",
        })
        self.assertIn(
            "IMPROPERLY_CONFIGURED: DB_PASSWORD must be set when using PostgreSQL.",
            result.stdout + result.stderr,
        )

    def test_sqlite_does_not_require_db_password(self):
        result = self._run_import({
            "DJANGO_SECRET_KEY": "x" * 60,
            "USE_SQLITE": "1",
        })
        output = result.stdout + result.stderr
        self.assertNotIn("IMPROPERLY_CONFIGURED", output)
        self.assertNotIn("ERROR", output)


class StaticPageTests(TestCase):
    def test_about_page_renders(self):
        response = self.client.get(reverse("about"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/about.html")
        self.assertContains(response, "من نحن")
        self.assertContains(response, reverse("contact"))

    def test_contact_page_renders_form(self):
        response = self.client.get(reverse("contact"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/contact.html")
        self.assertContains(response, "أرسل رسالة")
        self.assertIn("form", response.context)

    def test_contact_form_prefills_authenticated_user(self):
        from django.contrib.auth import get_user_model

        user_model = get_user_model()
        user = user_model.objects.create_user(
            email="contact@example.com",
            username="contactuser",
            password="testpass123",
            first_name="Test",
            last_name="User",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("contact"))
        self.assertEqual(
            response.context["form"].initial["name"], user.username
        )
        self.assertEqual(response.context["form"].initial["email"], "contact@example.com")

    def test_contact_form_sends_email_and_redirects(self):
        response = self.client.post(
            reverse("contact"),
            {
                "name": "Test User",
                "email": "user@example.com",
                "subject": "Hello",
                "message": "This is a test message with enough length.",
            },
        )
        self.assertRedirects(response, reverse("contact"))
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.subject, "[تواصل] Hello")
        self.assertIn("Test User <user@example.com>", sent.body)
        self.assertIn("This is a test message", sent.body)
        self.assertEqual(sent.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(sent.to, [settings.CONTACT_EMAIL])
        self.assertEqual(sent.reply_to, ["user@example.com"])

    def test_contact_form_rejects_empty_message(self):
        response = self.client.post(
            reverse("contact"),
            {
                "name": "Test User",
                "email": "user@example.com",
                "subject": "Hello",
                "message": "   ",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/contact.html")
        self.assertFormError(
            response.context["form"],
            "message",
            ["الرسالة لا يمكن أن تكون فارغة."],
        )
