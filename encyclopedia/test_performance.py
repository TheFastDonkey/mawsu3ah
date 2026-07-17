"""Performance / query-count tests for public pages."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from encyclopedia.models import Category, EditionStatus, Review
from encyclopedia.test_factories import create_book, create_edition

User = get_user_model()


class QueryCountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="perf@example.com",
            username="perf",
            password="pass1234",
        )
        self.category = Category.objects.create(name="فقه")
        self.book = create_book(
            title="كتاب اختبار الأداء",
            author_name="مؤلف",
            category=self.category,
        )
        self.editions = [
            create_edition(
                book=self.book,
                publisher_name=f"دار {i}",
                year=2020 + i,
                status=EditionStatus.APPROVED,
                submitted_by=self.user,
            )
            for i in range(5)
        ]
        for edition in self.editions:
            for j in range(3):
                Review.objects.create(
                    edition=edition,
                    user=self.user,
                    body=f"مراجعة {j}",
                )

    def test_home_query_count(self):
        # Home still fetches its own category sample; the sidebar adds one more query.
        # M2M author/publisher/editor prefetch adds two extra queries.
        # The books count and members count add two extra queries.
        with self.assertNumQueries(11):
            self.client.get(reverse("home"))

    def test_book_detail_query_count(self):
        # The global sidebar adds one category tree query.
        # M2M author/publisher/editor prefetch adds two extra queries.
        # The cross-book link lookup adds one extra query.
        # Edition relation prefetch adds two extra queries.
        # Pending category suggestions add one extra query.
        with self.assertNumQueries(12):
            self.client.get(reverse("book_detail", kwargs={"slug": self.book.slug}))

    def test_edition_detail_query_count(self):
        # The global sidebar adds one category tree query.
        # M2M author/publisher/editor prefetch adds two extra queries.
        # Edition relation prefetch adds two extra queries.
        # Book categories prefetch adds one extra query.
        # Pending category suggestions add one extra query.
        with self.assertNumQueries(11):
            self.client.get(reverse("edition_detail", kwargs={"book_slug": self.book.slug, "edition_public_id": self.editions[0].public_id}))

    def test_search_query_count(self):
        # The global sidebar adds one category tree query.
        # M2M author/publisher/editor prefetch adds two extra queries.
        with self.assertNumQueries(8):
            self.client.get(reverse("search") + "?q=اختبار")
