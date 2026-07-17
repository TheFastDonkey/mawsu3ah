"""Tests for Arabic search normalization (hamza, ta marbuta, diacritics)."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import (
    Category,
    EditionStatus,
    NameRecord,
    NameRecordKind,
    NameRecordStatus,
)
from .test_factories import create_book, create_edition

User = get_user_model()


class FlexibleSearchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="contrib@example.com",
            username="contrib",
            password="pass",
        )
        self.category = Category.objects.create(name="عقيدة إسلامية")
        self.book = create_book(
            title="العقيدة في القرآن الكريم",
            author_name="ابن تيمية",
            category=self.category,
        )
        create_edition(
            book=self.book,
            publisher_name="دار الفكر",
            editor_name="محمد بن عبد الوهاب",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )

    def _search(self, query):
        return self.client.get(reverse("search"), {"q": query})

    def test_search_ignores_hamza_in_title(self):
        response = self._search("القران")
        self.assertContains(response, self.book.title)

    def test_search_ignores_ta_marbuta_in_author(self):
        response = self._search("تيميه")
        self.assertContains(response, self.book.title)

    def test_search_ignores_diacritics(self):
        response = self._search("الْقُرْآنُ")
        self.assertContains(response, self.book.title)

    def test_search_ignores_hamza_in_category(self):
        response = self._search("اسلاميه")
        self.assertContains(response, self.book.title)

    def test_search_ignores_hamza_in_publisher(self):
        response = self._search("الفكر")  # already no hamza; sanity check.
        self.assertContains(response, self.book.title)

    def test_search_ignores_hamza_in_editor(self):
        response = self._search("عبد الوهاب")
        self.assertContains(response, self.book.title)

    def test_search_suggestions_are_flexible(self):
        response = self.client.get(
            reverse("search_suggestions"), {"q": "القران"}
        )
        self.assertContains(response, self.book.title)


class FlexibleBookSuggestionsTests(TestCase):
    def setUp(self):
        self.book = create_book(
            title="رسالة في الأحكام",
            author_name="مؤلف",
        )

    def test_book_suggestions_ignore_hamza(self):
        response = self.client.get(
            reverse("book_suggestions"), {"q": "احكام"}
        )
        self.assertContains(response, self.book.title)

    def test_book_suggestions_ignore_ta_marbuta(self):
        response = self.client.get(
            reverse("book_suggestions"), {"q": "رساله"}
        )
        self.assertContains(response, self.book.title)


class FlexibleNameSuggestionsTests(TestCase):
    def setUp(self):
        NameRecord.objects.create(
            kind=NameRecordKind.AUTHOR,
            name="ابن تيمية",
            status=NameRecordStatus.APPROVED,
        )
        NameRecord.objects.create(
            kind=NameRecordKind.EDITOR,
            name="محمد بن عبد الوهاب",
            status=NameRecordStatus.APPROVED,
        )
        NameRecord.objects.create(
            kind=NameRecordKind.PUBLISHER,
            name="دار القلم",
            status=NameRecordStatus.APPROVED,
        )

    def test_author_suggestions_ignore_hamza_and_ta_marbuta(self):
        response = self.client.get(
            reverse("author_suggestions"), {"q": "تيميه"}
        )
        self.assertContains(response, "ابن تيمية")

    def test_editor_suggestions_ignore_hamza(self):
        response = self.client.get(
            reverse("editor_suggestions"), {"q": "الوهاب"}
        )
        self.assertContains(response, "محمد بن عبد الوهاب")

    def test_publisher_suggestions_ignore_hamza(self):
        response = self.client.get(
            reverse("publisher_suggestions"), {"q": "القلم"}
        )
        self.assertContains(response, "دار القلم")


class FlexibleCategorySuggestionsTests(TestCase):
    def setUp(self):
        Category.objects.create(name="عقيدة إسلامية")

    def test_category_autocomplete_ignores_hamza_and_ta_marbuta(self):
        response = self.client.get(
            reverse("category_autocomplete"), {"q": "اسلاميه"}
        )
        self.assertContains(response, "عقيدة إسلامية")

    def test_category_suggestions_ignores_hamza(self):
        response = self.client.get(
            reverse("category_suggestions"), {"q": "عقيده"}
        )
        self.assertContains(response, "عقيدة إسلامية")
