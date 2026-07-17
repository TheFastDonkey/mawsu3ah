"""Tests for edition-to-edition relations (photocopy/reprint)."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse

from .models import (
    EditionRelation,
    EditionRelationKind,
    EditionRelationSuggestion,
    EditionRelationSuggestionStatus,
    EditionStatus,
    Review,
)
from .test_factories import create_book, create_edition

User = get_user_model()


class EditionRelationModelTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="user@example.com", username="user", password="pass"
        )
        self.book = create_book(title="شرح بانت سعاد", author_name="ابن هشام")
        self.original = create_edition(
            book=self.book,
            publisher_name="دار سعد الدين",
            year=2015,
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        self.photocopy = create_edition(
            book=self.book,
            publisher_name="دار ابن كثير",
            year=2018,
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )

    def test_relation_creation(self):
        relation = EditionRelation.objects.create(
            source=self.original,
            target=self.photocopy,
            kind=EditionRelationKind.PHOTOCOPY,
        )
        self.assertEqual(relation.source, self.original)
        self.assertEqual(relation.target, self.photocopy)
        self.assertEqual(relation.kind, EditionRelationKind.PHOTOCOPY)
        self.assertIn(relation, self.original.related_targets.all())
        self.assertIn(relation, self.photocopy.related_sources.all())

    def test_unique_together_enforced(self):
        EditionRelation.objects.create(
            source=self.original,
            target=self.photocopy,
            kind=EditionRelationKind.PHOTOCOPY,
        )
        with self.assertRaises(IntegrityError):
            EditionRelation.objects.create(
                source=self.original,
                target=self.photocopy,
                kind=EditionRelationKind.PHOTOCOPY,
            )

    def test_suggestion_approve_creates_relation(self):
        suggestion = EditionRelationSuggestion.objects.create(
            source=self.original,
            target=self.photocopy,
            kind=EditionRelationKind.PHOTOCOPY,
            suggested_by=self.user,
            status=EditionRelationSuggestionStatus.PENDING,
        )
        admin = User.objects.create_superuser(
            email="admin@example.com", username="admin", password="pass"
        )
        suggestion.approve(admin)
        self.assertEqual(suggestion.status, EditionRelationSuggestionStatus.APPROVED)
        self.assertTrue(
            EditionRelation.objects.filter(
                source=self.original, target=self.photocopy
            ).exists()
        )


class EditionRelationSuggestionFormTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="user@example.com", username="user", password="pass"
        )
        self.other = User.objects.create_user(
            email="other@example.com", username="other", password="pass"
        )
        self.book = create_book(title="شرح بانت سعاد", author_name="ابن هشام")
        self.original = create_edition(
            book=self.book,
            publisher_name="دار سعد الدين",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        self.photocopy = create_edition(
            book=self.book,
            publisher_name="دار ابن كثير",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        self.other_book = create_book(title="كتاب آخر", author_name="مؤلف")
        self.other_edition = create_edition(
            book=self.other_book,
            publisher_name="دار أخرى",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )

    def test_valid_existing_suggestion(self):
        from .forms import EditionRelationSuggestionForm

        form = EditionRelationSuggestionForm(
            {
                "target_mode": "existing",
                "target": self.photocopy.pk,
                "kind": EditionRelationKind.PHOTOCOPY,
            },
            source=self.original,
        )
        self.assertTrue(form.is_valid())
        suggestion = form.save()
        self.assertEqual(suggestion.source, self.original)
        self.assertEqual(suggestion.target, self.photocopy)

    def test_valid_new_suggestion(self):
        from .forms import EditionRelationSuggestionForm

        form = EditionRelationSuggestionForm(
            {
                "target_mode": "new",
                "new_publishers": '[{"name": "دار ابن كثير"}]',
                "new_year": 2018,
                "kind": EditionRelationKind.PHOTOCOPY,
            },
            source=self.original,
        )
        self.assertTrue(form.is_valid())
        suggestion = form.save()
        self.assertEqual(suggestion.source, self.original)
        self.assertIsNone(suggestion.target)
        self.assertEqual(suggestion.target_data["publishers"], ["دار ابن كثير"])
        self.assertEqual(suggestion.target_data["year"], 2018)

    def test_new_suggestion_requires_publishers_and_year(self):
        from .forms import EditionRelationSuggestionForm

        form = EditionRelationSuggestionForm(
            {"target_mode": "new", "kind": EditionRelationKind.PHOTOCOPY},
            source=self.original,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("new_publishers", form.errors)
        self.assertIn("new_year", form.errors)

    def test_new_suggestion_rejects_duplicate_edition(self):
        from .forms import EditionRelationSuggestionForm

        duplicate = create_edition(
            book=self.book,
            publisher_name="دار ابن كثير",
            year=2018,
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        form = EditionRelationSuggestionForm(
            {
                "target_mode": "new",
                "new_publishers": '[{"name": "دار ابن كثير"}]',
                "new_year": duplicate.year,
                "kind": EditionRelationKind.PHOTOCOPY,
            },
            source=self.original,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("__all__", form.errors)

    def test_rejects_self_relation(self):
        from .forms import EditionRelationSuggestionForm

        form = EditionRelationSuggestionForm(
            {
                "target_mode": "existing",
                "target": self.original.pk,
                "kind": EditionRelationKind.PHOTOCOPY,
            },
            source=self.original,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("target", form.errors)

    def test_rejects_different_book(self):
        from .forms import EditionRelationSuggestionForm

        form = EditionRelationSuggestionForm(
            {
                "target_mode": "existing",
                "target": self.other_edition.pk,
                "kind": EditionRelationKind.PHOTOCOPY,
            },
            source=self.original,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("target", form.errors)

    def test_rejects_existing_relation(self):
        EditionRelation.objects.create(
            source=self.original,
            target=self.photocopy,
            kind=EditionRelationKind.PHOTOCOPY,
        )
        from .forms import EditionRelationSuggestionForm

        form = EditionRelationSuggestionForm(
            {
                "target_mode": "existing",
                "target": self.photocopy.pk,
                "kind": EditionRelationKind.PHOTOCOPY,
            },
            source=self.original,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("target", form.errors)

    def test_rejects_pending_duplicate(self):
        EditionRelationSuggestion.objects.create(
            source=self.original,
            target=self.photocopy,
            kind=EditionRelationKind.PHOTOCOPY,
            suggested_by=self.other,
            status=EditionRelationSuggestionStatus.PENDING,
        )
        from .forms import EditionRelationSuggestionForm

        form = EditionRelationSuggestionForm(
            {
                "target_mode": "existing",
                "target": self.photocopy.pk,
                "kind": EditionRelationKind.PHOTOCOPY,
            },
            source=self.original,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("target", form.errors)


class EditionRelationViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="user@example.com", username="user", password="pass"
        )
        self.book = create_book(title="شرح بانت سعاد", author_name="ابن هشام")
        self.original = create_edition(
            book=self.book,
            publisher_name="دار سعد الدين",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        self.photocopy = create_edition(
            book=self.book,
            publisher_name="دار ابن كثير",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        self.client = Client()

    def test_suggestion_form_requires_login(self):
        response = self.client.get(
            reverse(
                "suggest_edition_relation",
                kwargs={"book_slug": self.book.slug, "edition_public_id": self.original.public_id},
            )
        )
        self.assertEqual(response.status_code, 302)

    def test_get_suggestion_form(self):
        self.client.login(email="user@example.com", password="pass")
        response = self.client.get(
            reverse(
                "suggest_edition_relation",
                kwargs={"book_slug": self.book.slug, "edition_public_id": self.original.public_id},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "id_target")

    def test_post_creates_pending_existing_suggestion(self):
        self.client.login(email="user@example.com", password="pass")
        response = self.client.post(
            reverse(
                "suggest_edition_relation",
                kwargs={"book_slug": self.book.slug, "edition_public_id": self.original.public_id},
            ),
            {
                "target_mode": "existing",
                "target": self.photocopy.pk,
                "kind": EditionRelationKind.PHOTOCOPY,
            },
        )
        self.assertEqual(response.status_code, 302)
        suggestion = EditionRelationSuggestion.objects.get()
        self.assertEqual(suggestion.source, self.original)
        self.assertEqual(suggestion.target, self.photocopy)
        self.assertEqual(suggestion.status, EditionRelationSuggestionStatus.PENDING)

    def test_post_creates_pending_new_suggestion(self):
        self.client.login(email="user@example.com", password="pass")
        response = self.client.post(
            reverse(
                "suggest_edition_relation",
                kwargs={"book_slug": self.book.slug, "edition_public_id": self.original.public_id},
            ),
            {
                "target_mode": "new",
                "new_publishers": '[{"name": "دار ابن كثير"}]',
                "new_year": 2018,
                "kind": EditionRelationKind.PHOTOCOPY,
            },
        )
        self.assertEqual(response.status_code, 302)
        suggestion = EditionRelationSuggestion.objects.get()
        self.assertEqual(suggestion.source, self.original)
        self.assertIsNone(suggestion.target)
        self.assertEqual(suggestion.target_data["publishers"], ["دار ابن كثير"])
        self.assertEqual(suggestion.target_data["year"], 2018)
        self.assertEqual(suggestion.status, EditionRelationSuggestionStatus.PENDING)

    def test_approve_new_suggestion_creates_pending_target_edition(self):
        admin = User.objects.create_superuser(
            email="admin@example.com", username="admin", password="pass"
        )
        suggestion = EditionRelationSuggestion.objects.create(
            source=self.original,
            target=None,
            kind=EditionRelationKind.PHOTOCOPY,
            suggested_by=self.user,
            status=EditionRelationSuggestionStatus.PENDING,
            target_data={
                "publishers": ["دار ابن كثير"],
                "year": 2018,
            },
        )
        suggestion.approve(admin)
        self.assertIsNotNone(suggestion.target)
        self.assertEqual(suggestion.target.book, self.book)
        self.assertEqual(suggestion.target.year, 2018)
        self.assertEqual(
            suggestion.target.status, EditionStatus.PENDING
        )
        # The relation suggestion stays pending until the target edition is approved.
        self.assertEqual(
            suggestion.status, EditionRelationSuggestionStatus.PENDING
        )
        self.assertFalse(
            EditionRelation.objects.filter(
                source=self.original, target=suggestion.target
            ).exists()
        )

    def test_approving_target_edition_approves_relation_suggestion(self):
        admin = User.objects.create_superuser(
            email="admin@example.com", username="admin", password="pass"
        )
        suggestion = EditionRelationSuggestion.objects.create(
            source=self.original,
            target=None,
            kind=EditionRelationKind.PHOTOCOPY,
            suggested_by=self.user,
            status=EditionRelationSuggestionStatus.PENDING,
            target_data={
                "publishers": ["دار ابن كثير"],
                "year": 2018,
            },
        )
        suggestion.approve(admin)
        suggestion.refresh_from_db()

        target = suggestion.target
        target.status = EditionStatus.APPROVED
        target.approved_by = admin
        target.save(update_fields=["status", "approved_by"])

        suggestion.refresh_from_db()
        self.assertEqual(
            suggestion.status, EditionRelationSuggestionStatus.APPROVED
        )
        self.assertTrue(
            EditionRelation.objects.filter(
                source=self.original, target=target
            ).exists()
        )

    def test_edition_detail_shows_relation_notice_for_target(self):
        EditionRelation.objects.create(
            source=self.original,
            target=self.photocopy,
            kind=EditionRelationKind.PHOTOCOPY,
        )
        response = self.client.get(self.photocopy.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "طبعة مصورة")
        self.assertContains(response, self.original.get_absolute_url())

    def test_edition_detail_shows_related_targets_for_source(self):
        EditionRelation.objects.create(
            source=self.original,
            target=self.photocopy,
            kind=EditionRelationKind.PHOTOCOPY,
        )
        response = self.client.get(self.original.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "طبعات مصورة")
        self.assertContains(response, self.photocopy.get_absolute_url())

    def test_edition_detail_inherits_reviews(self):
        EditionRelation.objects.create(
            source=self.original,
            target=self.photocopy,
            kind=EditionRelationKind.PHOTOCOPY,
        )
        Review.objects.create(
            edition=self.original,
            user=self.user,
            body="مراجعة الأصل",
        )
        response = self.client.get(self.photocopy.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "مراجعات الطبعة الأصل")
        self.assertContains(response, "مراجعة الأصل")

    def test_book_detail_shows_relation_badge_and_hint(self):
        EditionRelation.objects.create(
            source=self.original,
            target=self.photocopy,
            kind=EditionRelationKind.PHOTOCOPY,
        )
        response = self.client.get(self.book.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "طبعة مصورة")
        self.assertContains(response, "له طبعات مصورة")

    def test_edition_suggestions_filters_by_book(self):
        other_book = create_book(title="كتاب آخر", author_name="مؤلف")
        create_edition(
            book=other_book,
            publisher_name="دار أخرى",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        response = self.client.get(
            reverse("edition_suggestions"),
            {"q": "دار", "book": self.book.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "دار سعد الدين")
        self.assertContains(response, "دار ابن كثير")
        self.assertNotContains(response, "دار أخرى")
