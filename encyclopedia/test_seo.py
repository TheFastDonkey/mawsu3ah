"""Tests for SEO pages: robots.txt and sitemap.xml."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from encyclopedia.models import Category, EditionStatus
from encyclopedia.test_factories import create_book, create_edition

User = get_user_model()


class SEOPageTests(TestCase):
    def test_robots_txt(self):
        response = self.client.get(reverse("robots_txt"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertContains(response, "User-agent:")
        self.assertContains(response, "Sitemap:")

    def test_sitemap_xml(self):
        user = User.objects.create_user(
            email="sitemap@example.com",
            username="sitemap",
            password="pass1234",
        )
        category = Category.objects.create(name="عقيدة")
        book = create_book(
            title="كتاب في الخريطة",
            author_name="مؤلف",
            category=category,
        )
        edition = create_edition(
            book=book,
            publisher_name="دار الخريطة",
            status=EditionStatus.APPROVED,
            submitted_by=user,
        )

        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/xml")
        self.assertContains(response, reverse("category_detail", kwargs={"category_path": category.get_url_path()}))
        self.assertContains(response, reverse("book_detail", kwargs={"slug": book.slug}))
        self.assertContains(response, reverse("edition_detail", kwargs={"book_slug": book.slug, "edition_public_id": edition.public_id}))
