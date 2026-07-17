"""Security tests for the encyclopedia app."""

import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from encyclopedia.models import Category, Edition, EditionStatus, Review
from encyclopedia.test_factories import create_book, create_edition

User = get_user_model()


class CsrfTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="csrf@example.com",
            username="csrfuser",
            password="pass",
        )
        self.category = Category.objects.create(name="فقه")
        self.book = create_book(
            title="كتاب الفقه",
            author_name="ابن القيم",
            category=self.category,
        )
        self.edition = create_edition(
            book=self.book,
            publisher_name="دار الفكر",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        self.client = Client(enforce_csrf_checks=True)
        self.client.login(email=self.user.email, password="pass")

    def test_submit_edition_requires_csrf(self):
        response = self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": str(self.book.pk),
                "publishers": json.dumps([{"name": "دار طيبة"}]),
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_edition_vote_requires_csrf(self):
        response = self.client.post(reverse("edition_vote", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}))
        self.assertEqual(response.status_code, 403)

    def test_review_create_requires_csrf(self):
        response = self.client.post(
            reverse("review_create", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}),
            {"body": "تعليق"},
        )
        self.assertEqual(response.status_code, 403)


class StateChangingMethodsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="methods@example.com",
            username="methodsuser",
            password="pass",
        )
        self.category = Category.objects.create(name="فقه")
        self.book = create_book(
            title="كتاب الفقه",
            author_name="ابن القيم",
            category=self.category,
        )
        self.edition = create_edition(
            book=self.book,
            publisher_name="دار الفكر",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        self.client = Client()
        self.client.login(email=self.user.email, password="pass")

    def test_edition_vote_rejects_get(self):
        response = self.client.get(reverse("edition_vote", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}))
        self.assertEqual(response.status_code, 405)

    def test_review_create_rejects_get(self):
        response = self.client.get(reverse("review_create", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}))
        self.assertEqual(response.status_code, 405)

    def test_review_vote_rejects_get(self):
        comment = Review.objects.create(edition=self.edition, user=self.user, body="تعليق")
        response = self.client.get(reverse("review_vote", kwargs={"review_public_id": comment.public_id}))
        self.assertEqual(response.status_code, 405)


class RateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="ratelimit@example.com",
            username="ratelimituser",
            password="pass",
        )
        self.category = Category.objects.create(name="فقه")
        self.book = create_book(
            title="كتاب الفقه",
            author_name="ابن القيم",
            category=self.category,
        )
        self.edition = create_edition(
            book=self.book,
            publisher_name="دار الفكر",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        self.client = Client()
        self.client.login(email=self.user.email, password="pass")

    def _fetch_csrf(self, url):
        self.client.get(url)

    def test_edition_vote_rate_limited(self):
        self._fetch_csrf(reverse("edition_detail", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}))
        for _ in range(60):
            response = self.client.post(
                reverse("edition_vote", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id})
            )
            self.assertIn(response.status_code, [200, 429])

        response = self.client.post(reverse("edition_vote", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}))
        self.assertEqual(response.status_code, 429)

    def test_review_create_rate_limited(self):
        self._fetch_csrf(reverse("edition_detail", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}))
        for i in range(20):
            response = self.client.post(
                reverse("review_create", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}),
                {"body": f"تعليق {i}"},
            )
            self.assertIn(response.status_code, [200, 429])

        response = self.client.post(
            reverse("review_create", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}),
            {"body": "تعليق زائد"},
        )
        self.assertEqual(response.status_code, 429)

    def test_edition_submission_rate_limited(self):
        self._fetch_csrf(reverse("submit_edition"))
        for i in range(10):
            response = self.client.post(
                reverse("submit_edition"),
                {
                    "book_action": "existing",
                    "existing_book": str(self.book.pk),
                    "publishers": json.dumps([{"name": f"دار النشر {i}"}]),
                    "is_best": "no",
                },
            )
            self.assertIn(response.status_code, [302, 429])

        response = self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": str(self.book.pk),
                "publishers": json.dumps([{"name": "دار النشر زائد"}]),
                "is_best": "no",
            },
        )
        self.assertEqual(response.status_code, 429)


class SanitizationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="sanitize@example.com",
            username="sanitizeuser",
            password="pass",
        )
        self.category = Category.objects.create(name="فقه")
        self.book = create_book(
            title="كتاب الفقه",
            author_name="ابن القيم",
            category=self.category,
        )
        self.edition = create_edition(
            book=self.book,
            publisher_name="دار الفكر",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        self.client = Client()
        self.client.login(email=self.user.email, password="pass")

    def test_comment_html_is_stripped(self):
        response = self.client.post(
            reverse("review_create", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}),
            {"body": "<script>alert(1)</script> نص آمن"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "نص آمن")
        self.assertNotContains(response, "<script>")
        review = Review.objects.get()
        self.assertNotIn("<script>", review.body)

    def test_volumes_normalized(self):
        response = self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": str(self.book.pk),
                "publishers": json.dumps([{"name": "دار طيبة"}]),
                "volumes": " 123-456-789 ",
                "confirm_override": "1",
                "is_best": "no",
            },
        )
        self.assertEqual(response.status_code, 302)
        edition = Edition.objects.get(volumes="123456789")
        self.assertEqual(edition.volumes, "123456789")


class AdminSecurityMiddlewareTests(TestCase):
    def test_default_admin_path_blocked_when_custom_admin_url_set(self):
        with override_settings(DJANGO_ADMIN_URL="manage"):
            response = self.client.get("/admin/")
            self.assertEqual(response.status_code, 403)

    def test_default_admin_path_allowed_when_default_admin_url(self):
        with override_settings(DJANGO_ADMIN_URL="admin"):
            response = self.client.get("/admin/")
            # Not blocked by the middleware; unauthenticated users are
            # redirected to the admin login page.
            self.assertEqual(response.status_code, 302)
