"""Tests for the staff moderation dashboard."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from encyclopedia.models import (
    ApprovalLog,
    Category,
    CategoryRequest,
    CategoryRequestStatus,
    CategorySuggestion,
    CategorySuggestionStatus,
    EditionBookLinkSuggestion,
    EditionBookLinkSuggestionStatus,
    EditionEditSuggestion,
    EditionEditSuggestionStatus,
    EditionRelationKind,
    EditionRelationSuggestion,
    EditionRelationSuggestionStatus,
    EditionStatus,
    NameRecord,
    NameRecordKind,
    NameRecordStatus,
    Review,
    ReviewReport,
)
from encyclopedia.test_factories import (
    create_book as _factory_create_book,
)
from encyclopedia.test_factories import (
    create_edition as _factory_create_edition,
)

User = get_user_model()


def _create_book(title="كتاب تجريبي"):
    return _factory_create_book(title=title, author_name="مؤلف")


def _create_edition(book, publisher_name="دار تجريبية", status=EditionStatus.PENDING, **kwargs):
    return _factory_create_edition(
        book, publisher_name=publisher_name, status=status, **kwargs
    )


class ModerationQueueTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@example.com",
            username="admin",
            password="adminpass",
            is_staff=True,
        )
        self.user = User.objects.create_user(
            email="user@example.com",
            username="user",
            password="userpass",
        )
        self.category = Category.objects.create(name="فقه")
        self.book = _create_book()
        self.book.categories.add(self.category)
        self.pending = _create_edition(
            self.book, publisher_name="دار تجريبية", status=EditionStatus.PENDING, submitted_by=self.user
        )

    def test_queue_requires_staff(self):
        response = self.client.get(reverse("moderation:moderation_queue"))
        self.assertEqual(response.status_code, 302)

        self.client.login(email="user@example.com", password="userpass")
        response = self.client.get(reverse("moderation:moderation_queue"))
        self.assertEqual(response.status_code, 302)

    def test_queue_lists_pending_editions(self):
        self.client.login(email="admin@example.com", password="adminpass")
        response = self.client.get(reverse("moderation:moderation_queue"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.pending.publishers.first().name)

    def test_approve_edition(self):
        self.client.login(email="admin@example.com", password="adminpass")
        with self.assertLogs("mawsu3ah.admin", level="INFO"):
            response = self.client.post(
                reverse("moderation:approve_edition", kwargs={"pk": self.pending.pk})
            )
        self.assertRedirects(response, reverse("moderation:moderation_dashboard"))
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, EditionStatus.APPROVED)
        self.assertEqual(self.pending.approved_by, self.admin)
        self.assertIsNotNone(self.pending.approved_at)
        self.assertTrue(
            ApprovalLog.objects.filter(
                edition=self.pending,
                new_status=EditionStatus.APPROVED,
            ).exists()
        )

    def test_reject_edition(self):
        self.client.login(email="admin@example.com", password="adminpass")
        with self.assertLogs("mawsu3ah.admin", level="INFO"):
            response = self.client.post(
                reverse("moderation:reject_edition", kwargs={"pk": self.pending.pk}),
                {"rejection_reason": "مكرر"},
            )
        self.assertRedirects(response, reverse("moderation:moderation_dashboard"))
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, EditionStatus.REJECTED)
        self.assertEqual(self.pending.rejection_reason, "مكرر")
        self.assertTrue(
            ApprovalLog.objects.filter(
                edition=self.pending,
                new_status=EditionStatus.REJECTED,
                reason="مكرر",
            ).exists()
        )


class ModerationCommentsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@example.com",
            username="admin",
            password="adminpass",
            is_staff=True,
        )
        self.user = User.objects.create_user(
            email="user@example.com",
            username="user",
            password="userpass",
        )
        self.book = _create_book()
        self.edition = _create_edition(
            self.book, publisher_name="دار", status=EditionStatus.APPROVED, submitted_by=self.user
        )
        self.comment = Review.objects.create(
            edition=self.edition,
            user=self.user,
            body="مراجعة تجريبية",
        )

    def test_comments_list_requires_staff(self):
        self.client.login(email="user@example.com", password="userpass")
        response = self.client.get(reverse("moderation:moderation_comments"))
        self.assertEqual(response.status_code, 302)

    def test_hide_comment(self):
        self.client.login(email="admin@example.com", password="adminpass")
        with self.assertLogs("mawsu3ah.admin", level="INFO"):
            response = self.client.post(
                reverse(
                    "moderation:review_hide_toggle",
                    kwargs={"review_public_id": self.comment.public_id},
                )
            )
        self.assertRedirects(response, reverse("moderation:moderation_comments"))
        self.comment.refresh_from_db()
        self.assertTrue(self.comment.hidden)
        self.assertEqual(self.comment.hidden_by, self.admin)
        self.assertIsNotNone(self.comment.hidden_at)

    def test_unhide_comment(self):
        self.comment.hidden = True
        self.comment.hidden_by = self.admin
        self.comment.hidden_at = timezone.now()
        self.comment.save()

        self.client.login(email="admin@example.com", password="adminpass")
        with self.assertLogs("mawsu3ah.admin", level="INFO"):
            response = self.client.post(
                reverse(
                    "moderation:review_hide_toggle",
                    kwargs={"review_public_id": self.comment.public_id},
                )
            )
        self.assertRedirects(response, reverse("moderation:moderation_comments"))
        self.comment.refresh_from_db()
        self.assertFalse(self.comment.hidden)
        self.assertIsNone(self.comment.hidden_by)
        self.assertIsNone(self.comment.hidden_at)


class ReportQueueTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@example.com",
            username="admin",
            password="adminpass",
            is_staff=True,
        )
        self.user = User.objects.create_user(
            email="user@example.com",
            username="user",
            password="userpass",
        )
        self.book = _create_book()
        self.edition = _create_edition(
            self.book, publisher_name="دار", status=EditionStatus.APPROVED, submitted_by=self.user
        )
        self.review = Review.objects.create(
            edition=self.edition,
            user=self.user,
            body="مراجعة تجريبية",
        )

    def test_report_queue_requires_staff(self):
        self.client.login(email="user@example.com", password="userpass")
        response = self.client.get(reverse("moderation:report_queue"))
        self.assertEqual(response.status_code, 302)

    def test_report_queue_lists_reported_reviews(self):
        ReviewReport.objects.create(
            review=self.review,
            reporter=self.user,
            reason="spam",
        )
        self.client.login(email="admin@example.com", password="adminpass")
        response = self.client.get(reverse("moderation:report_queue"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.review.body)
        self.assertContains(response, "1 بلاغ")

    def test_dismiss_reports_resolves_them(self):
        report = ReviewReport.objects.create(
            review=self.review,
            reporter=self.user,
            reason="spam",
        )
        self.client.login(email="admin@example.com", password="adminpass")
        with self.assertLogs("mawsu3ah.admin", level="INFO"):
            response = self.client.post(
                reverse("moderation:dismiss_reports", kwargs={"review_public_id": self.review.public_id})
            )
        self.assertRedirects(response, reverse("moderation:report_queue"))
        report.refresh_from_db()
        self.assertTrue(report.resolved)
        self.assertEqual(report.resolved_by, self.admin)
        self.assertIsNotNone(report.resolved_at)


class UnifiedDashboardTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@example.com",
            username="admin",
            password="adminpass",
            is_staff=True,
        )
        self.user = User.objects.create_user(
            email="user@example.com",
            username="user",
            password="userpass",
        )
        self.book = _create_book()
        self.approved_edition = _create_edition(
            self.book, publisher_name="دار معتمدة", status=EditionStatus.APPROVED, submitted_by=self.user
        )

    def _login_admin(self):
        self.client.login(email="admin@example.com", password="adminpass")

    def test_dashboard_requires_staff(self):
        response = self.client.get(reverse("moderation:moderation_dashboard"))
        self.assertEqual(response.status_code, 302)

        self.client.login(email="user@example.com", password="userpass")
        response = self.client.get(reverse("moderation:moderation_dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_lists_all_pending_types(self):
        pending_edition = _create_edition(
            self.book, status=EditionStatus.PENDING, submitted_by=self.user
        )
        EditionEditSuggestion.objects.create(
            edition=self.approved_edition,
            suggested_by=self.user,
            year=2025,
        )
        other_book = _create_book(title="كتاب آخر")
        EditionBookLinkSuggestion.objects.create(
            edition=self.approved_edition,
            book=other_book,
            suggested_by=self.user,
        )
        EditionRelationSuggestion.objects.create(
            source=self.approved_edition,
            target=self.approved_edition,
            kind=EditionRelationKind.PHOTOCOPY,
            suggested_by=self.user,
        )
        CategorySuggestion.objects.create(
            book=self.book,
            suggested_by=self.user,
            name="تصنيف مقترح",
        )
        CategoryRequest.objects.create(
            suggested_by=self.user,
            name="تصنيف جديد مطلوب",
        )
        NameRecord.objects.create(
            name="اسم مجهول",
            kind=NameRecordKind.AUTHOR,
            status=NameRecordStatus.PENDING,
            submitted_by=self.user,
        )

        self._login_admin()
        response = self.client.get(reverse("moderation:moderation_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, pending_edition.publishers.first().name)
        self.assertContains(response, "تعديل مقترح")
        self.assertContains(response, other_book.title)
        self.assertContains(response, "طبعة مصورة")
        self.assertContains(response, "تصنيف مقترح")
        self.assertContains(response, "تصنيف جديد مطلوب")
        self.assertContains(response, "اسم مجهول")

    def test_dashboard_filter_by_type(self):
        pending_edition = _create_edition(
            self.book, publisher_name="دار المرشحة", status=EditionStatus.PENDING, submitted_by=self.user
        )
        suggestion = CategorySuggestion.objects.create(
            book=self.book,
            suggested_by=self.user,
            name="تصنيف فريد",
        )

        self._login_admin()
        response = self.client.get(
            reverse("moderation:moderation_dashboard") + "?type=category_suggestion"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, suggestion.name)
        self.assertNotContains(response, pending_edition.publishers.first().name)


class GenericApproveRejectTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@example.com",
            username="admin",
            password="adminpass",
            is_staff=True,
        )
        self.user = User.objects.create_user(
            email="user@example.com",
            username="user",
            password="userpass",
        )
        self.book = _create_book()
        self.approved_edition = _create_edition(
            self.book, status=EditionStatus.APPROVED, submitted_by=self.user
        )
        self.client.login(email="admin@example.com", password="adminpass")

    def test_approve_name_record(self):
        record = NameRecord.objects.create(
            name="مؤلف جديد",
            kind=NameRecordKind.AUTHOR,
            status=NameRecordStatus.PENDING,
            submitted_by=self.user,
        )
        with self.assertLogs("mawsu3ah.admin", level="INFO"):
            response = self.client.post(
                reverse(
                    "moderation:approve_item",
                    kwargs={"item_type": "name_record", "pk": record.pk},
                )
            )
        self.assertRedirects(response, reverse("moderation:moderation_dashboard"))
        record.refresh_from_db()
        self.assertEqual(record.status, NameRecordStatus.APPROVED)
        self.assertEqual(record.approved_by, self.admin)
        self.assertIsNotNone(record.approved_at)

    def test_reject_name_record(self):
        record = NameRecord.objects.create(
            name="ناشر مرفوض",
            kind=NameRecordKind.PUBLISHER,
            status=NameRecordStatus.PENDING,
            submitted_by=self.user,
        )
        with self.assertLogs("mawsu3ah.admin", level="INFO"):
            response = self.client.post(
                reverse(
                    "moderation:reject_item",
                    kwargs={"item_type": "name_record", "pk": record.pk},
                ),
                {"rejection_reason": "غير مناسب"},
            )
        self.assertRedirects(response, reverse("moderation:moderation_dashboard"))
        record.refresh_from_db()
        self.assertEqual(record.status, NameRecordStatus.REJECTED)
        self.assertEqual(record.rejected_by, self.admin)
        self.assertIsNotNone(record.rejected_at)

    def test_approve_category_suggestion(self):
        suggestion = CategorySuggestion.objects.create(
            book=self.book,
            suggested_by=self.user,
            name="عقيدة",
        )
        with self.assertLogs("mawsu3ah.admin", level="INFO"):
            response = self.client.post(
                reverse(
                    "moderation:approve_item",
                    kwargs={"item_type": "category_suggestion", "pk": suggestion.pk},
                )
            )
        self.assertRedirects(response, reverse("moderation:moderation_dashboard"))
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, CategorySuggestionStatus.APPROVED)
        self.assertEqual(suggestion.resolved_by, self.admin)
        self.assertTrue(self.book.categories.filter(name="عقيدة").exists())

    def test_reject_category_suggestion(self):
        suggestion = CategorySuggestion.objects.create(
            book=self.book,
            suggested_by=self.user,
            name="عقيدة",
        )
        with self.assertLogs("mawsu3ah.admin", level="INFO"):
            response = self.client.post(
                reverse(
                    "moderation:reject_item",
                    kwargs={"item_type": "category_suggestion", "pk": suggestion.pk},
                ),
                {"rejection_reason": "غير ملائم"},
            )
        self.assertRedirects(response, reverse("moderation:moderation_dashboard"))
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, CategorySuggestionStatus.REJECTED)
        self.assertEqual(suggestion.admin_note, "غير ملائم")

    def test_approve_category_request(self):
        request_obj = CategoryRequest.objects.create(
            suggested_by=self.user,
            name="أصول الفقه",
        )
        with self.assertLogs("mawsu3ah.admin", level="INFO"):
            response = self.client.post(
                reverse(
                    "moderation:approve_item",
                    kwargs={"item_type": "category_request", "pk": request_obj.pk},
                )
            )
        self.assertRedirects(response, reverse("moderation:moderation_dashboard"))
        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, CategoryRequestStatus.APPROVED)
        self.assertTrue(Category.objects.filter(name="أصول الفقه").exists())

    def test_approve_edit_suggestion(self):
        suggestion = EditionEditSuggestion.objects.create(
            edition=self.approved_edition,
            suggested_by=self.user,
            year=2025,
            proposed_publishers=["دار جديدة"],
        )
        with self.assertLogs("mawsu3ah.admin", level="INFO"):
            response = self.client.post(
                reverse(
                    "moderation:approve_item",
                    kwargs={"item_type": "edit", "pk": suggestion.pk},
                )
            )
        self.assertRedirects(response, reverse("moderation:moderation_dashboard"))
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, EditionEditSuggestionStatus.APPROVED)
        self.approved_edition.refresh_from_db()
        self.assertEqual(self.approved_edition.year, 2025)
        self.assertTrue(
            self.approved_edition.publishers.filter(name="دار جديدة").exists()
        )

    def test_approve_link_suggestion(self):
        other_book = _create_book(title="كتاب شرح")
        suggestion = EditionBookLinkSuggestion.objects.create(
            edition=self.approved_edition,
            book=other_book,
            suggested_by=self.user,
        )
        with self.assertLogs("mawsu3ah.admin", level="INFO"):
            response = self.client.post(
                reverse(
                    "moderation:approve_item",
                    kwargs={"item_type": "link", "pk": suggestion.pk},
                )
            )
        self.assertRedirects(response, reverse("moderation:moderation_dashboard"))
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, EditionBookLinkSuggestionStatus.APPROVED)
        self.assertTrue(
            self.approved_edition.book_links.filter(book=other_book).exists()
        )

    def test_approve_relation_suggestion_existing_target(self):
        target = _create_edition(
            self.book, publisher_name="دار الهدف", status=EditionStatus.APPROVED, submitted_by=self.user
        )
        suggestion = EditionRelationSuggestion.objects.create(
            source=self.approved_edition,
            target=target,
            kind=EditionRelationKind.PHOTOCOPY,
            suggested_by=self.user,
        )
        with self.assertLogs("mawsu3ah.admin", level="INFO"):
            response = self.client.post(
                reverse(
                    "moderation:approve_item",
                    kwargs={"item_type": "relation", "pk": suggestion.pk},
                )
            )
        self.assertRedirects(response, reverse("moderation:moderation_dashboard"))
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, EditionRelationSuggestionStatus.APPROVED)
        self.assertTrue(
            self.approved_edition.related_targets.filter(target=target).exists()
        )

    def test_approve_relation_suggestion_new_target(self):
        suggestion = EditionRelationSuggestion.objects.create(
            source=self.approved_edition,
            kind=EditionRelationKind.REPRINT,
            suggested_by=self.user,
            target_data={
                "publishers": ["دار جديدة"],
                "year": 2020,
            },
        )
        with self.assertLogs("mawsu3ah.admin", level="INFO"):
            response = self.client.post(
                reverse(
                    "moderation:approve_item",
                    kwargs={"item_type": "relation", "pk": suggestion.pk},
                )
            )
        self.assertRedirects(response, reverse("moderation:moderation_dashboard"))
        suggestion.refresh_from_db()
        self.assertIsNotNone(suggestion.target)
        # Generated target editions start pending for non-expert suggestions;
        # the relation only publishes once the target edition is approved.
        self.assertEqual(suggestion.target.status, EditionStatus.PENDING)
        self.assertEqual(suggestion.status, EditionRelationSuggestionStatus.PENDING)
        self.assertFalse(
            self.approved_edition.related_targets.filter(target=suggestion.target).exists()
        )

        # Now approve the generated target edition.
        target = suggestion.target
        target.status = EditionStatus.APPROVED
        target.approved_by = self.admin
        target.approved_at = timezone.now()
        target.save(update_fields=["status", "approved_by", "approved_at"])

        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, EditionRelationSuggestionStatus.APPROVED)
        self.assertTrue(
            self.approved_edition.related_targets.filter(target=target).exists()
        )
