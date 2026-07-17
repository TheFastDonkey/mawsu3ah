import json
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core import mail
from django.core.cache import cache
from django.db import IntegrityError
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from .admin import EditionAdmin, EditionEditSuggestionAdmin
from .forms import EditionSubmissionForm
from .models import (
    ApprovalLog,
    Book,
    BookAuthor,
    Category,
    Edition,
    EditionBookLink,
    EditionBookLinkRole,
    EditionBookLinkSuggestion,
    EditionBookLinkSuggestionStatus,
    EditionEditSuggestion,
    EditionEditSuggestionStatus,
    EditionRelation,
    EditionRelationKind,
    EditionRelationSuggestion,
    EditionRelationSuggestionStatus,
    EditionStatus,
    EditionVote,
    NameRecord,
    NameRecordKind,
    NameRecordStatus,
    Review,
    ReviewReport,
    ReviewVote,
)
from .test_factories import create_book, create_edition

User = get_user_model()


class ModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="user@example.com",
            username="user",
            password="pass",
        )
        self.category = Category.objects.create(name="فقه")
        self.book = create_book(
            title="كتاب الفقه",
            author_name="ابن القيم",
            category=self.category,
        )

    def test_category_slug_allows_arabic(self):
        self.assertEqual(self.category.slug, "فقه")

    def test_book_slug_is_unique(self):
        first = create_book(title="كتاب الفقه", author_name="ابن القيم")
        second = create_book(title="كتاب الفقه", author_name="ابن القيم")
        self.assertNotEqual(first.slug, second.slug)

    def test_edition_default_status_pending(self):
        edition = create_edition(
            book=self.book,
            publisher_name="دار الفكر",
            submitted_by=self.user,
        )
        self.assertEqual(edition.status, EditionStatus.PENDING)

    def test_like_uniqueness(self):
        edition = create_edition(
            book=self.book,
            publisher_name="دار الفكر",
            submitted_by=self.user,
        )
        EditionVote.objects.create(user=self.user, edition=edition, book_context=edition.book)
        with self.assertRaises(IntegrityError):
            EditionVote.objects.create(user=self.user, edition=edition, book_context=edition.book)

    def test_comment_like_uniqueness(self):
        edition = create_edition(
            book=self.book,
            publisher_name="دار الفكر",
            submitted_by=self.user,
        )
        comment = Review.objects.create(
            edition=edition,
            user=self.user,
            body="تعليق",
        )
        ReviewVote.objects.create(user=self.user, review=comment)
        with self.assertRaises(IntegrityError):
            ReviewVote.objects.create(user=self.user, review=comment)


class AdminActionTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            email="admin@example.com",
            username="admin",
            password="pass",
        )
        self.category = Category.objects.create(name="عقيدة")
        self.book = create_book(
            title="العقيدة",
            author_name="الآجري",
            category=self.category,
        )
        self.edition = create_edition(
            book=self.book,
            publisher_name="دار الرسالة",
            submitted_by=self.admin_user,
        )
        self.site = AdminSite()
        self.modeladmin = EditionAdmin(Edition, self.site)
        self.factory = RequestFactory()

    def _setup_request(self, method="post", data=None):
        request = self.factory.post("/admin/encyclopedia/edition/", data or {})
        request.user = self.admin_user
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    def test_approve_action(self):
        request = self._setup_request()
        queryset = Edition.objects.filter(pk=self.edition.pk)
        self.modeladmin.approve_editions(request, queryset)
        self.edition.refresh_from_db()
        self.assertEqual(self.edition.status, EditionStatus.APPROVED)
        self.assertEqual(self.edition.approved_by, self.admin_user)
        self.assertIsNotNone(self.edition.approved_at)
        self.assertEqual(ApprovalLog.objects.count(), 1)

    def test_reject_action_intermediate_page(self):
        request = self._setup_request()
        queryset = Edition.objects.filter(pk=self.edition.pk)
        response = self.modeladmin.reject_editions(request, queryset)
        self.assertEqual(response.status_code, 200)
        self.edition.refresh_from_db()
        self.assertEqual(self.edition.status, EditionStatus.PENDING)

    def test_reject_action_confirms(self):
        request = self._setup_request(
            data={"confirm_reject": "1", "rejection_reason": "ناقص"},
        )
        queryset = Edition.objects.filter(pk=self.edition.pk)
        response = self.modeladmin.reject_editions(request, queryset)
        self.assertEqual(response.status_code, 302)
        self.edition.refresh_from_db()
        self.assertEqual(self.edition.status, EditionStatus.REJECTED)
        self.assertEqual(self.edition.rejection_reason, "ناقص")
        self.assertEqual(ApprovalLog.objects.count(), 1)


class SubmissionFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="contrib@example.com",
            username="contrib",
            password="pass",
        )
        self.category = Category.objects.create(name="حديث")
        self.book = create_book(
            title="صحيح البخاري",
            author_name="البخاري",
            category=self.category,
        )

    def make_existing_payload(self, **overrides):
        defaults = {
            "book_action": "existing",
            "existing_book": str(self.book.pk),
            "publishers": json.dumps([{"name": "دار ابن كثير"}]),
            "year": "",
            "editors": "",
            "page_count": "",
            "city": "",
            "volumes": "",
            "is_best": "no",
        }
        defaults.update(overrides)
        return defaults

    def test_existing_book_valid(self):
        form = EditionSubmissionForm(self.make_existing_payload())
        self.assertTrue(form.is_valid())

    def test_new_book_duplicate_title_author(self):
        payload = self.make_existing_payload(
            book_action="new",
            existing_book="",
            new_book_title="صحيح البخاري",
            new_book_authors=json.dumps([{"name": "البخاري"}]),
            new_book_categories=json.dumps(
                [{"id": self.category.pk, "name": self.category.name}]
            ),
        )
        form = EditionSubmissionForm(payload)
        self.assertFalse(form.is_valid())

    def test_save_existing_book(self):
        form = EditionSubmissionForm(self.make_existing_payload())
        self.assertTrue(form.is_valid())
        edition = form.save(self.user)
        self.assertEqual(edition.book, self.book)
        self.assertEqual(edition.status, EditionStatus.PENDING)

    def test_save_new_book(self):
        payload = self.make_existing_payload(
            book_action="new",
            existing_book="",
            new_book_title="صحيح مسلم",
            new_book_authors=json.dumps([{"name": "مسلم"}]),
            new_book_categories=json.dumps(
                [{"id": self.category.pk, "name": self.category.name}]
            ),
        )
        form = EditionSubmissionForm(payload)
        self.assertTrue(form.is_valid())
        edition = form.save(self.user)
        self.assertEqual(edition.book.title, "صحيح مسلم")
        self.assertEqual(Book.objects.count(), 2)
        self.assertIn(self.category, edition.book.categories.all())

    def test_duplicate_detection_by_volumes(self):
        approved = create_edition(
            book=self.book,
            publisher_name="دار ابن كثير",
            volumes="123456789",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        form = EditionSubmissionForm(self.make_existing_payload(volumes="123456789"))
        self.assertTrue(form.is_valid())
        edition = form.get_edition(self.user)
        duplicates = form.find_duplicates(edition)
        self.assertIn(approved, duplicates)

    def test_is_best_default_false(self):
        form = EditionSubmissionForm(self.make_existing_payload())
        self.assertTrue(form.is_valid())
        self.assertFalse(form.cleaned_data["is_best"])
        edition = form.save(self.user)
        self.assertFalse(edition.is_best)

    def test_is_best_true(self):
        form = EditionSubmissionForm(self.make_existing_payload(is_best="yes"))
        self.assertTrue(form.is_valid())
        self.assertTrue(form.cleaned_data["is_best"])
        edition = form.save(self.user)
        self.assertTrue(edition.is_best)


class SubmissionViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="contrib@example.com",
            username="contrib",
            password="pass",
        )
        self.client = Client()
        self.client.login(email="contrib@example.com", password="pass")
        self.category = Category.objects.create(name="تفسير")
        self.book = create_book(
            title="تفسير ابن كثير",
            author_name="ابن كثير",
            category=self.category,
        )

    def test_get_submission_form(self):
        response = self.client.get(reverse("submit_edition"))
        self.assertEqual(response.status_code, 200)

    def test_get_submission_form_prefills_book(self):
        response = self.client.get(
            reverse("submit_edition"), {"book": str(self.book.pk)}
        )
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form["book_action"].value(), "existing")
        self.assertEqual(form["existing_book"].value(), self.book.pk)
        self.assertEqual(response.context["prefill_book"], self.book)
        self.assertContains(response, self.book.title)

    def test_get_submission_form_ignores_invalid_book(self):
        response = self.client.get(reverse("submit_edition"), {"book": "999999"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context.get("prefill_book"))

    def test_prefilled_book_form_locks_book_choice(self):
        response = self.client.get(
            reverse("submit_edition"), {"book": str(self.book.pk)}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "أضف كتاباً جديداً")
        self.assertNotContains(response, 'id="id_existing_book_search"')
        self.assertContains(response, self.book.title)
        self.assertContains(response, 'name="book_action"')
        self.assertContains(response, 'name="existing_book"')

    def test_submit_existing_book(self):
        response = self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": str(self.book.pk),
                "publishers": json.dumps([{"name": "دار طيبة"}]),
                "year": "",
                "editors": "",
                "page_count": "",
                "city": "",
                "volumes": "",
                "is_best": "no",
            },
        )
        self.assertRedirects(response, reverse("home"))
        self.assertEqual(Edition.objects.count(), 1)

    def test_submit_is_best_saves_flag(self):
        response = self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": str(self.book.pk),
                "publishers": json.dumps([{"name": "دار طيبة"}]),
                "year": "",
                "editors": "",
                "page_count": "",
                "city": "",
                "volumes": "",
                "is_best": "yes",
            },
        )
        self.assertRedirects(response, reverse("home"))
        edition = Edition.objects.first()
        self.assertTrue(edition.is_best)

    def test_submit_is_best_does_not_create_vote(self):
        response = self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": str(self.book.pk),
                "publishers": json.dumps([{"name": "دار طيبة"}]),
                "year": "",
                "editors": "",
                "page_count": "",
                "city": "",
                "volumes": "",
                "is_best": "yes",
            },
        )
        self.assertRedirects(response, reverse("home"))
        self.assertEqual(Edition.objects.count(), 1)
        self.assertEqual(EditionVote.objects.count(), 0)

    def test_submit_shows_duplicate_warning(self):
        create_edition(
            book=self.book,
            publisher_name="دار طيبة",
            year=2020,
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        response = self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": str(self.book.pk),
                "publishers": json.dumps([{"name": "دار طيبة"}]),
                "year": "2020",
                "editors": "",
                "page_count": "",
                "city": "",
                "volumes": "",
                "is_best": "no",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "تنبيه")
        self.assertEqual(Edition.objects.count(), 1)

    def test_confirm_override_saves_duplicate(self):
        create_edition(
            book=self.book,
            publisher_name="دار طيبة",
            year=2020,
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        response = self.client.post(
            reverse("submit_edition"),
            {
                "confirm_override": "1",
                "book_action": "existing",
                "existing_book": str(self.book.pk),
                "publishers": json.dumps([{"name": "دار طيبة"}]),
                "year": "2020",
                "editors": "",
                "page_count": "",
                "city": "",
                "volumes": "",
                "is_best": "no",
            },
        )
        self.assertRedirects(response, reverse("home"))
        self.assertEqual(Edition.objects.count(), 2)

    def _new_book_payload(self, **overrides):
        defaults = {
            "book_action": "new",
            "new_book_title": "كتاب جديد",
            "new_book_authors": json.dumps([{"name": "مؤلف جديد"}]),
            "new_book_categories": json.dumps(
                [{"id": self.category.pk, "name": self.category.name}]
            ),
            "publishers": json.dumps([{"name": "ناشر جديد"}]),
            "year": "",
            "editors": "",
            "page_count": "",
            "city": "",
            "volumes": "",
            "is_best": "no",
        }
        defaults.update(overrides)
        return defaults

    def test_submit_new_book_creates_author_record(self):
        response = self.client.post(
            reverse("submit_edition"),
            self._new_book_payload(),
        )
        self.assertRedirects(response, reverse("home"))
        record = NameRecord.objects.get(
            kind=NameRecordKind.AUTHOR, name="مؤلف جديد"
        )
        self.assertEqual(record.status, NameRecordStatus.PENDING)
        self.assertEqual(record.submitted_by, self.user)

    def test_submit_edition_creates_editor_and_publisher_records(self):
        response = self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": str(self.book.pk),
                "publishers": json.dumps([{"name": "ناشر جديد"}]),
                "year": "",
                "editors": json.dumps([{"name": "محقق جديد"}]),
                "page_count": "",
                "city": "",
                "volumes": "",
                "is_best": "no",
            },
        )
        self.assertRedirects(response, reverse("home"))
        publisher = NameRecord.objects.get(
            kind=NameRecordKind.PUBLISHER, name="ناشر جديد"
        )
        editor = NameRecord.objects.get(
            kind=NameRecordKind.EDITOR, name="محقق جديد"
        )
        self.assertEqual(publisher.status, NameRecordStatus.PENDING)
        self.assertEqual(editor.status, NameRecordStatus.PENDING)

    def test_submit_existing_book_does_not_create_author_record(self):
        author_count_before = NameRecord.objects.filter(kind=NameRecordKind.AUTHOR).count()
        self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": str(self.book.pk),
                "publishers": json.dumps([{"name": "ناشر جديد"}]),
                "year": "",
                "editors": "",
                "page_count": "",
                "city": "",
                "volumes": "",
                "is_best": "no",
            },
        )
        self.assertEqual(
            NameRecord.objects.filter(kind=NameRecordKind.AUTHOR).count(),
            author_count_before,
        )

    def test_submit_does_not_duplicate_approved_name_record(self):
        NameRecord.objects.create(
            kind=NameRecordKind.PUBLISHER,
            name="ناشر معتمد",
            status=NameRecordStatus.APPROVED,
        )
        self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": str(self.book.pk),
                "publishers": json.dumps([{"name": "ناشر معتمد"}]),
                "year": "",
                "editors": "",
                "page_count": "",
                "city": "",
                "volumes": "",
                "is_best": "no",
            },
        )
        record = NameRecord.objects.get(
            kind=NameRecordKind.PUBLISHER, name="ناشر معتمد"
        )
        self.assertEqual(record.status, NameRecordStatus.APPROVED)
        self.assertEqual(
            NameRecord.objects.filter(
                kind=NameRecordKind.PUBLISHER, name="ناشر معتمد"
            ).count(),
            1,
        )

    def test_submit_does_not_duplicate_pending_name_record(self):
        other_user = User.objects.create_user(
            email="other@example.com", username="other", password="pass"
        )
        NameRecord.objects.create(
            kind=NameRecordKind.EDITOR,
            name="محقق موجود",
            status=NameRecordStatus.PENDING,
            submitted_by=other_user,
        )
        self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": str(self.book.pk),
                "publishers": json.dumps([{"name": "ناشر جديد"}]),
                "year": "",
                "editors": json.dumps([{"name": "محقق موجود"}]),
                "page_count": "",
                "city": "",
                "volumes": "",
                "is_best": "no",
            },
        )
        record = NameRecord.objects.get(
            kind=NameRecordKind.EDITOR, name="محقق موجود"
        )
        self.assertEqual(record.status, NameRecordStatus.PENDING)
        self.assertEqual(record.submitted_by, other_user)

    def test_submit_reopens_rejected_name_record(self):
        NameRecord.objects.create(
            kind=NameRecordKind.PUBLISHER,
            name="ناشر مرفوض",
            status=NameRecordStatus.REJECTED,
        )
        self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": str(self.book.pk),
                "publishers": json.dumps([{"name": "ناشر مرفوض"}]),
                "year": "",
                "editors": "",
                "page_count": "",
                "city": "",
                "volumes": "",
                "is_best": "no",
            },
        )
        record = NameRecord.objects.get(
            kind=NameRecordKind.PUBLISHER, name="ناشر مرفوض"
        )
        self.assertEqual(record.status, NameRecordStatus.PENDING)
        self.assertEqual(record.submitted_by, self.user)

    def test_confirm_override_creates_name_records(self):
        create_edition(
            book=self.book,
            publisher_name="دار طيبة",
            year=2020,
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        response = self.client.post(
            reverse("submit_edition"),
            {
                "confirm_override": "1",
                "book_action": "existing",
                "existing_book": str(self.book.pk),
                "publishers": json.dumps([{"name": "دار طيبة"}]),
                "year": "2020",
                "editors": json.dumps([{"name": "محقق جديد"}]),
                "page_count": "",
                "city": "",
                "volumes": "",
                "is_best": "no",
            },
        )
        self.assertRedirects(response, reverse("home"))
        self.assertTrue(
            NameRecord.objects.filter(
                kind=NameRecordKind.EDITOR, name="محقق جديد"
            ).exists()
        )

    def test_submit_page_has_no_add_name_button(self):
        response = self.client.get(reverse("submit_edition"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "أضف جديداً")
        self.assertNotContains(response, "names/add/")
        self.assertContains(
            response, "الأسماء الجديدة (مؤلف/محقق/ناشر) تُرسل تلقائيًا للمراجعة"
        )


class BookSuggestionTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="فقه")
        self.book = create_book(
            title="كتاب الفقه",
            author_name="ابن القيم",
            category=self.category,
        )

    def test_book_suggestions_empty_without_query(self):
        response = self.client.get(reverse("book_suggestions"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.book.title)

    def test_book_suggestions_match_by_title(self):
        response = self.client.get(
            reverse("book_suggestions"), {"q": "الفقه"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.book.title)
        self.assertContains(response, self.book.authors.first().name)

    def test_book_suggestions_match_by_author(self):
        response = self.client.get(
            reverse("book_suggestions"), {"q": "ابن القيم"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.book.title)

    def test_book_suggestions_limit_to_five(self):
        for i in range(6):
            create_book(
                title=f"كتاب {i}",
                author_name="مؤلف عام",
            )
        response = self.client.get(
            reverse("book_suggestions"), {"q": "كتاب"}
        )
        self.assertEqual(response.status_code, 200)
        # All 6 match, but the view caps results at 5.
        for i in range(5):
            self.assertContains(response, f"كتاب {i}")


class PublicPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="contrib@example.com",
            username="contrib",
            password="pass",
        )
        self.expert = User.objects.create_user(
            email="expert@example.com",
            username="expert",
            password="pass",
            is_expert=True,
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
            year=2022,
            editor_name="محمد",
            page_count=300,
            city="بيروت",
            volumes="123-456",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )

    def test_home_page(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.book.title)
        self.assertContains(response, self.edition.publishers.first().name)

    def test_category_list(self):
        response = self.client.get(reverse("category_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.category.name)

    def test_category_detail(self):
        response = self.client.get(
            reverse(
                "category_detail",
                kwargs={"category_path": self.category.get_url_path()},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.book.title)

    def test_category_detail_hides_books_without_approved_editions(self):
        pending_book = create_book(
            title="كتاب معلق",
            author_name="مؤلف مجهول",
            category=self.category,
        )
        create_edition(
            book=pending_book,
            publisher_name="دار الرحمة",
            status=EditionStatus.PENDING,
            submitted_by=self.user,
        )
        response = self.client.get(
            reverse(
                "category_detail",
                kwargs={"category_path": self.category.get_url_path()},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, pending_book.title)

    def test_book_detail(self):
        response = self.client.get(reverse("book_detail", kwargs={"slug": self.book.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.book.title)
        self.assertContains(response, self.edition.publishers.first().name)
        self.assertContains(response, self.user.username)

    def test_book_detail_shows_suggest_edition_button_for_authenticated_user(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("book_detail", kwargs={"slug": self.book.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "اقترح طبعة")
        self.assertContains(
            response,
            f"{reverse('submit_edition')}?book={self.book.pk}",
        )

    def test_book_detail_shows_login_link_for_suggest_edition_when_anonymous(self):
        response = self.client.get(reverse("book_detail", kwargs={"slug": self.book.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "اقترح طبعة")
        self.assertContains(response, f"{reverse('login')}?next=")

    def test_book_detail_orders_editions_by_likes(self):
        popular = create_edition(
            book=self.book,
            publisher_name="دار طيبة",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        EditionVote.objects.create(user=self.user, edition=popular, book_context=popular.book)
        response = self.client.get(reverse("book_detail", kwargs={"slug": self.book.slug}))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        popular_index = content.index(popular.publishers.first().name)
        edition_index = content.index(self.edition.publishers.first().name)
        self.assertLess(popular_index, edition_index)

    def test_search_by_title(self):
        response = self.client.get(reverse("search"), {"q": "الفقه"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.book.title)

    def test_search_by_publisher(self):
        response = self.client.get(reverse("search"), {"q": "الفكر"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.book.title)

    def test_search_category_filter(self):
        other_category = Category.objects.create(name="حديث")
        other_book = create_book(
            title="صحيح البخاري",
            author_name="البخاري",
            category=other_category,
        )
        create_edition(
            book=other_book,
            publisher_name="دار الفكر",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        response = self.client.get(
            reverse("search"),
            {"q": "الفكر", "category": self.category.slug},
        )
        self.assertContains(response, self.book.title)
        self.assertNotContains(response, other_book.title)

    def test_search_suggestions(self):
        response = self.client.get(reverse("search_suggestions"), {"q": "الفقه"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.book.title)
        self.assertContains(response, "عرض كل النتائج")

    def test_search_no_results(self):
        response = self.client.get(reverse("search"), {"q": "غير موجود"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "لا توجد نتائج مطابقة")

    def test_expert_badge_on_book_detail(self):
        create_edition(
            book=self.book,
            publisher_name="دار الخبراء",
            status=EditionStatus.APPROVED,
            is_best=True,
            submitted_by=self.expert,
        )
        response = self.client.get(reverse("book_detail", kwargs={"slug": self.book.slug}))
        self.assertContains(response, "رشحها خبير")

    def test_expert_no_badge_when_not_best(self):
        create_edition(
            book=self.book,
            publisher_name="دار الخبراء",
            status=EditionStatus.APPROVED,
            is_best=False,
            submitted_by=self.expert,
        )
        response = self.client.get(reverse("book_detail", kwargs={"slug": self.book.slug}))
        self.assertNotContains(response, "رشحها خبير")

    def test_expert_like_badge_on_book_detail(self):
        EditionVote.objects.create(user=self.expert, edition=self.edition, book_context=self.edition.book)
        response = self.client.get(reverse("book_detail", kwargs={"slug": self.book.slug}))
        self.assertContains(response, "أعجب بها خبير")

    def test_book_detail_expert_first_sort_prefers_expert_liked(self):
        expert_liked = create_edition(
            book=self.book,
            publisher_name="دار التفضيل",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        EditionVote.objects.create(user=self.expert, edition=expert_liked, book_context=expert_liked.book)
        EditionVote.objects.create(user=self.user, edition=self.edition, book_context=self.edition.book)
        response = self.client.get(
            reverse("book_detail", kwargs={"slug": self.book.slug}),
            {"expert_first": "1"},
        )
        content = response.content.decode()
        expert_liked_index = content.index(expert_liked.publishers.first().name)
        normal_index = content.index(self.edition.publishers.first().name)
        self.assertLess(expert_liked_index, normal_index)


class EngagementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="user@example.com",
            username="user",
            password="pass",
        )
        self.expert = User.objects.create_user(
            email="expert@example.com",
            username="expert",
            password="pass",
            is_expert=True,
        )
        self.staff = User.objects.create_user(
            email="staff@example.com",
            username="staff",
            password="pass",
            is_staff=True,
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
            year=2022,
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        self.client = Client()

    def test_edition_detail_approved_only(self):
        response = self.client.get(reverse("edition_detail", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.edition.publishers.first().name)

    def test_edition_detail_hides_pending(self):
        pending = create_edition(
            book=self.book,
            publisher_name="دار معلقة",
            status=EditionStatus.PENDING,
            submitted_by=self.user,
        )
        response = self.client.get(reverse("edition_detail", kwargs={"book_slug": self.book.slug, "edition_public_id": pending.public_id}))
        self.assertEqual(response.status_code, 404)

    def test_edition_vote(self):
        self.client.login(email="user@example.com", password="pass")
        response = self.client.post(
            reverse("edition_vote", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}),
            {"vote": "like"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(EditionVote.objects.filter(user=self.user, edition=self.edition, value=1).exists())
        self.assertContains(response, "1")

        response = self.client.post(
            reverse("edition_vote", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}),
            {"vote": "like"},
        )
        self.assertFalse(EditionVote.objects.filter(user=self.user, edition=self.edition).exists())

    def test_edition_vote_dislike(self):
        self.client.login(email="user@example.com", password="pass")
        url = reverse("edition_vote", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id})

        response = self.client.post(url, {"vote": "dislike"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(EditionVote.objects.filter(user=self.user, edition=self.edition, value=-1).exists())
        self.assertContains(response, "-1")

        response = self.client.post(url, {"vote": "dislike"})
        self.assertFalse(EditionVote.objects.filter(user=self.user, edition=self.edition).exists())

    def test_edition_vote_switch(self):
        self.client.login(email="user@example.com", password="pass")
        url = reverse("edition_vote", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id})

        self.client.post(url, {"vote": "like"})
        self.assertEqual(EditionVote.objects.get(user=self.user, edition=self.edition).value, 1)

        self.client.post(url, {"vote": "dislike"})
        self.assertEqual(EditionVote.objects.get(user=self.user, edition=self.edition).value, -1)

    def test_anonymous_like_prompts_sign_in(self):
        response = self.client.post(reverse("edition_vote", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "سجّل الدخول")

    def test_review_create(self):
        self.client.login(email="user@example.com", password="pass")
        response = self.client.post(
            reverse("review_create", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}),
            {"body": "طبعة ممتازة"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Review.objects.filter(edition=self.edition, user=self.user).exists())
        self.assertContains(response, "طبعة ممتازة")

    def test_anonymous_sees_reply_and_report_buttons(self):
        review = Review.objects.create(edition=self.edition, user=self.expert, body="مراجعة")
        Review.objects.create(edition=self.edition, user=self.user, body="تعليق", parent=review)
        response = self.client.get(reverse("edition_detail", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}))
        self.assertContains(response, "تعليق")
        self.assertContains(response, "رد")
        self.assertContains(response, "إبلاغ")

    def test_anonymous_comment_prompts_sign_in(self):
        response = self.client.post(
            reverse("review_create", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}),
            {"body": "تعليق"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "سجّل الدخول")
        self.assertEqual(Review.objects.count(), 0)

    def test_review_vote(self):
        self.client.login(email="user@example.com", password="pass")
        comment = Review.objects.create(edition=self.edition, user=self.expert, body="تعليق")
        response = self.client.post(reverse("review_vote", kwargs={"review_public_id": comment.public_id}), {"vote": "like"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ReviewVote.objects.filter(user=self.user, review=comment, value=1).exists())

        response = self.client.post(reverse("review_vote", kwargs={"review_public_id": comment.public_id}), {"vote": "like"})
        self.assertFalse(ReviewVote.objects.filter(user=self.user, review=comment).exists())

    def test_review_vote_dislike(self):
        self.client.login(email="user@example.com", password="pass")
        comment = Review.objects.create(edition=self.edition, user=self.expert, body="تعليق")
        url = reverse("review_vote", kwargs={"review_public_id": comment.public_id})

        response = self.client.post(url, {"vote": "dislike"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ReviewVote.objects.filter(user=self.user, review=comment, value=-1).exists())
        self.assertContains(response, "-1")

        response = self.client.post(url, {"vote": "dislike"})
        self.assertFalse(ReviewVote.objects.filter(user=self.user, review=comment).exists())

    def test_expert_badge_on_comment(self):
        Review.objects.create(edition=self.edition, user=self.expert, body="تعليق خبير")
        response = self.client.get(reverse("edition_detail", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}))
        self.assertContains(response, "تعليق خبير")
        self.assertContains(response, "خبير")

    def test_book_detail_expert_first_sort(self):
        expert_edition = create_edition(
            book=self.book,
            publisher_name="دار الخبراء",
            status=EditionStatus.APPROVED,
            is_best=True,
            submitted_by=self.expert,
        )
        EditionVote.objects.create(user=self.user, edition=self.edition, book_context=self.edition.book)
        response = self.client.get(
            reverse("book_detail", kwargs={"slug": self.book.slug}),
            {"expert_first": "1"},
        )
        content = response.content.decode()
        expert_index = content.index(expert_edition.publishers.first().name)
        normal_index = content.index(self.edition.publishers.first().name)
        self.assertLess(expert_index, normal_index)

    def test_expert_first_sort_ignores_non_best_expert(self):
        non_best_expert = create_edition(
            book=self.book,
            publisher_name="دار الخبراء",
            status=EditionStatus.APPROVED,
            is_best=False,
            submitted_by=self.expert,
        )
        EditionVote.objects.create(user=self.user, edition=self.edition, book_context=self.edition.book)
        response = self.client.get(
            reverse("book_detail", kwargs={"slug": self.book.slug}),
            {"expert_first": "1"},
        )
        content = response.content.decode()
        normal_index = content.index(self.edition.publishers.first().name)
        non_best_index = content.index(non_best_expert.publishers.first().name)
        self.assertLess(normal_index, non_best_index)

    def test_book_detail_shows_vote_buttons(self):
        response = self.client.get(reverse("book_detail", kwargs={"slug": self.book.slug}))
        self.assertContains(response, f"edition-vote-buttons-{self.edition.public_id}")

    def test_book_detail_highlights_user_vote(self):
        EditionVote.objects.create(user=self.user, edition=self.edition, value=1, book_context=self.edition.book)
        self.client.login(email="user@example.com", password="pass")
        response = self.client.get(reverse("book_detail", kwargs={"slug": self.book.slug}))
        self.assertContains(response, "vote-button--like is-active")
        self.assertNotContains(response, "vote-button--dislike is-active")

    def test_legacy_edition_detail_redirect(self):
        response = self.client.get(
            reverse("edition_detail_legacy", kwargs={"pk": self.edition.pk})
        )
        self.assertRedirects(
            response,
            reverse(
                "edition_detail",
                kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id},
            ),
            status_code=301,
        )

    def test_legacy_edition_votes_redirect(self):
        response = self.client.get(
            reverse("edition_votes_legacy", kwargs={"pk": self.edition.pk})
        )
        self.assertRedirects(
            response,
            reverse(
                "edition_votes",
                kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id},
            ),
            status_code=301,
        )

    def test_edition_votes_view_lists_voters(self):
        EditionVote.objects.create(user=self.expert, edition=self.edition, book_context=self.edition.book)
        EditionVote.objects.create(user=self.user, edition=self.edition, book_context=self.edition.book)
        response = self.client.get(
            reverse("edition_votes", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.expert.username)
        self.assertContains(response, self.user.username)

    def test_edition_votes_view_hides_pending(self):
        pending = create_edition(
            book=self.book,
            publisher_name="دار معلقة",
            status=EditionStatus.PENDING,
            submitted_by=self.user,
        )
        response = self.client.get(reverse("edition_votes", kwargs={"book_slug": self.book.slug, "edition_public_id": pending.public_id}))
        self.assertEqual(response.status_code, 404)

    def test_staff_hide_unhide_comment(self):
        self.client.login(email="staff@example.com", password="pass")
        comment = Review.objects.create(edition=self.edition, user=self.user, body="تعليق")
        response = self.client.post(reverse("review_hide_toggle", kwargs={"review_public_id": comment.public_id}))
        self.assertEqual(response.status_code, 200)
        comment.refresh_from_db()
        self.assertTrue(comment.hidden)
        self.assertEqual(comment.hidden_by, self.staff)
        self.assertIsNotNone(comment.hidden_at)

        response = self.client.post(reverse("review_hide_toggle", kwargs={"review_public_id": comment.public_id}))
        comment.refresh_from_db()
        self.assertFalse(comment.hidden)
        self.assertIsNone(comment.hidden_by)
        self.assertIsNone(comment.hidden_at)

    def test_hidden_comment_not_visible_to_public(self):
        Review.objects.create(
            edition=self.edition,
            user=self.user,
            body="تعليق مخفي",
            hidden=True,
            hidden_by=self.staff,
        )
        response = self.client.get(reverse("edition_detail", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}))
        self.assertNotContains(response, "تعليق مخفي")
        self.assertContains(response, "لا توجد مراجعات بعد")

    def test_non_staff_cannot_hide_comment(self):
        self.client.login(email="user@example.com", password="pass")
        comment = Review.objects.create(edition=self.edition, user=self.user, body="تعليق")
        response = self.client.post(reverse("review_hide_toggle", kwargs={"review_public_id": comment.public_id}))
        self.assertEqual(response.status_code, 403)
        comment.refresh_from_db()
        self.assertFalse(comment.hidden)

    def test_review_reply_create(self):
        self.client.login(email="user@example.com", password="pass")
        review = Review.objects.create(edition=self.edition, user=self.expert, body="مراجعة")
        response = self.client.post(
            reverse(
                "review_reply_create",
                kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id, "review_public_id": review.public_id},
            ),
            {"body": "رد تجريبي"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Review.objects.filter(parent=review, body="رد تجريبي").exists())
        self.assertContains(response, "رد تجريبي")

    def test_nested_reply(self):
        self.client.login(email="user@example.com", password="pass")
        review = Review.objects.create(edition=self.edition, user=self.expert, body="مراجعة")
        reply = Review.objects.create(
            edition=self.edition, user=self.user, body="رد أول", parent=review
        )
        response = self.client.post(
            reverse(
                "review_reply_create",
                kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id, "review_public_id": reply.public_id},
            ),
            {"body": "رد ثانٍ"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Review.objects.filter(parent=reply, body="رد ثانٍ").exists())
        nested = Review.objects.get(parent=reply, body="رد ثانٍ")
        self.assertEqual(nested.depth, 2)

    def test_reply_to_comment_htmx_renders_parent_comment(self):
        self.client.login(email="user@example.com", password="pass")
        review = Review.objects.create(edition=self.edition, user=self.expert, body="مراجعة")
        comment = Review.objects.create(
            edition=self.edition, user=self.user, body="تعليق", parent=review
        )
        response = self.client.post(
            reverse(
                "review_reply_create",
                kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id, "review_public_id": comment.public_id},
            ),
            {"body": "رد على التعليق"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("رد على التعليق", content)
        self.assertIn(f'id="review-{comment.public_id}"', content)
        self.assertIn(
            f'id="review-{Review.objects.get(body="رد على التعليق").public_id}"', content
        )

    def test_descendant_count_includes_nested_replies(self):
        review = Review.objects.create(edition=self.edition, user=self.expert, body="مراجعة")
        Review.objects.create(edition=self.edition, user=self.user, body="تعليق 1", parent=review)
        comment2 = Review.objects.create(
            edition=self.edition, user=self.user, body="تعليق 2", parent=review
        )
        Review.objects.create(
            edition=self.edition, user=self.user, body="رد متداخل", parent=comment2
        )
        response = self.client.get(reverse("edition_detail", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}))
        self.assertContains(response, "تعليقات (3)")

    def test_unlimited_depth_reply_chain(self):
        self.client.login(email="user@example.com", password="pass")
        review = Review.objects.create(edition=self.edition, user=self.expert, body="مراجعة")
        parent = review
        for i in range(5):
            response = self.client.post(
                reverse(
                    "review_reply_create",
                    kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id, "review_public_id": parent.public_id},
                ),
                {"body": f"رد {i + 1}"},
            )
            self.assertEqual(response.status_code, 200)
            parent = Review.objects.get(body=f"رد {i + 1}")
            self.assertEqual(parent.depth, i + 1)

    def test_review_sort_by_expert_and_likes(self):
        normal_review = Review.objects.create(
            edition=self.edition, user=self.user, body="مراجعة عادية"
        )
        ReviewVote.objects.create(user=self.user, review=normal_review)
        expert_review = Review.objects.create(
            edition=self.edition, user=self.expert, body="مراجعة خبير"
        )

        response = self.client.get(reverse("edition_detail", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}))
        content = response.content.decode()
        expert_index = content.index("مراجعة خبير")
        normal_index = content.index("مراجعة عادية")
        self.assertLess(expert_index, normal_index)

        ReviewVote.objects.create(user=self.staff, review=normal_review)
        ReviewVote.objects.create(user=self.user, review=expert_review)
        ReviewVote.objects.create(user=self.staff, review=expert_review)

        response = self.client.get(reverse("edition_detail", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}))
        content = response.content.decode()
        expert_index = content.index("مراجعة خبير")
        normal_index = content.index("مراجعة عادية")
        self.assertLess(expert_index, normal_index)

    def test_reply_like_toggle(self):
        self.client.login(email="user@example.com", password="pass")
        review = Review.objects.create(edition=self.edition, user=self.expert, body="مراجعة")
        reply = Review.objects.create(
            edition=self.edition, user=self.user, body="رد", parent=review
        )
        response = self.client.post(reverse("review_vote", kwargs={"review_public_id": reply.public_id}))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ReviewVote.objects.filter(user=self.user, review=reply).exists())

    def test_owner_can_edit_review_htmx(self):
        self.client.login(email="user@example.com", password="pass")
        review = Review.objects.create(edition=self.edition, user=self.user, body="مراجعة قبل التعديل")
        response = self.client.post(
            reverse("review_edit", kwargs={"review_public_id": review.public_id}),
            {"body": "مراجعة بعد التعديل"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        review.refresh_from_db()
        self.assertEqual(review.body, "مراجعة بعد التعديل")
        self.assertIsNotNone(review.edited_at)
        self.assertContains(response, "مراجعة بعد التعديل")
        self.assertContains(response, "تم التعديل في")

    def test_owner_can_edit_reply_htmx(self):
        self.client.login(email="user@example.com", password="pass")
        review = Review.objects.create(edition=self.edition, user=self.expert, body="مراجعة")
        reply = Review.objects.create(
            edition=self.edition, user=self.user, body="رد قبل التعديل", parent=review
        )
        response = self.client.post(
            reverse("review_edit", kwargs={"review_public_id": reply.public_id}),
            {"body": "رد بعد التعديل"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        reply.refresh_from_db()
        self.assertEqual(reply.body, "رد بعد التعديل")
        self.assertIsNotNone(reply.edited_at)
        self.assertContains(response, "رد بعد التعديل")
        self.assertContains(response, "تم التعديل في")

    def test_non_owner_cannot_edit_review(self):
        self.client.login(email="user@example.com", password="pass")
        review = Review.objects.create(edition=self.edition, user=self.expert, body="مراجعة")
        response = self.client.post(
            reverse("review_edit", kwargs={"review_public_id": review.public_id}),
            {"body": "تعديل غير مصرح"},
        )
        self.assertEqual(response.status_code, 403)
        review.refresh_from_db()
        self.assertEqual(review.body, "مراجعة")
        self.assertIsNone(review.edited_at)

    def test_anonymous_edit_prompts_sign_in(self):
        review = Review.objects.create(edition=self.edition, user=self.user, body="مراجعة")
        response = self.client.post(
            reverse("review_edit", kwargs={"review_public_id": review.public_id}),
            {"body": "تعديل"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "سجّل الدخول")
        review.refresh_from_db()
        self.assertEqual(review.body, "مراجعة")
        self.assertIsNone(review.edited_at)

    def test_owner_can_delete_review_htmx(self):
        self.client.login(email="user@example.com", password="pass")
        review = Review.objects.create(edition=self.edition, user=self.user, body="مراجعة للحذف")
        response = self.client.post(
            reverse("review_delete", kwargs={"review_public_id": review.public_id}),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Review.objects.filter(pk=review.pk).exists())
        self.assertNotContains(response, "للحذف")
        self.assertContains(response, "لا توجد مراجعات بعد")

    def test_owner_can_delete_reply_htmx(self):
        self.client.login(email="user@example.com", password="pass")
        review = Review.objects.create(edition=self.edition, user=self.expert, body="مراجعة")
        reply = Review.objects.create(
            edition=self.edition, user=self.user, body="رد", parent=review
        )
        response = self.client.post(
            reverse("review_delete", kwargs={"review_public_id": reply.public_id}),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Review.objects.filter(pk=reply.pk).exists())
        self.assertTrue(Review.objects.filter(pk=review.pk).exists())

    def test_deleting_review_cascades_replies_htmx(self):
        self.client.login(email="user@example.com", password="pass")
        review = Review.objects.create(edition=self.edition, user=self.user, body="مراجعة للحذف")
        Review.objects.create(edition=self.edition, user=self.expert, body="رد للحذف", parent=review)
        response = self.client.post(
            reverse("review_delete", kwargs={"review_public_id": review.public_id}),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Review.objects.filter(edition=self.edition).count(), 0)
        self.assertNotContains(response, "للحذف")

    def test_owner_delete_review_redirects_without_htmx(self):
        self.client.login(email="user@example.com", password="pass")
        review = Review.objects.create(edition=self.edition, user=self.user, body="مراجعة")
        response = self.client.post(reverse("review_delete", kwargs={"review_public_id": review.public_id}))
        self.assertRedirects(response, reverse("edition_detail", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}))
        self.assertFalse(Review.objects.filter(pk=review.pk).exists())

    def test_non_owner_cannot_delete_review(self):
        self.client.login(email="user@example.com", password="pass")
        review = Review.objects.create(edition=self.edition, user=self.expert, body="مراجعة")
        response = self.client.post(reverse("review_delete", kwargs={"review_public_id": review.public_id}))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Review.objects.filter(pk=review.pk).exists())

    def test_anonymous_delete_prompts_sign_in(self):
        review = Review.objects.create(edition=self.edition, user=self.user, body="مراجعة")
        response = self.client.post(reverse("review_delete", kwargs={"review_public_id": review.public_id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "سجّل الدخول")
        self.assertTrue(Review.objects.filter(pk=review.pk).exists())

    def test_authenticated_user_can_report_review(self):
        other = User.objects.create_user(
            email="other@example.com",
            username="other",
            password="pass",
        )
        review = Review.objects.create(edition=self.edition, user=other, body="مراجعة للإبلاغ")
        self.client.login(email="user@example.com", password="pass")
        response = self.client.post(
            reverse("review_report_create", kwargs={"review_public_id": review.public_id}),
            {"reason": "spam", "details": "إعلان"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            ReviewReport.objects.filter(
                review=review, reporter=self.user, reason="spam"
            ).exists()
        )
        self.assertContains(response, "تم إرسال البلاغ")

    def test_duplicate_report_blocked(self):
        other = User.objects.create_user(
            email="other@example.com",
            username="other",
            password="pass",
        )
        review = Review.objects.create(edition=self.edition, user=other, body="مراجعة للإبلاغ")
        ReviewReport.objects.create(review=review, reporter=self.user, reason="spam")
        self.client.login(email="user@example.com", password="pass")
        response = self.client.post(
            reverse("review_report_create", kwargs={"review_public_id": review.public_id}),
            {"reason": "harassment", "details": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "تم الإبلاغ")
        self.assertEqual(ReviewReport.objects.filter(review=review, reporter=self.user).count(), 1)

    def test_cannot_report_own_review(self):
        review = Review.objects.create(edition=self.edition, user=self.user, body="مراجعتي")
        self.client.login(email="user@example.com", password="pass")
        response = self.client.post(
            reverse("review_report_create", kwargs={"review_public_id": review.public_id}),
            {"reason": "spam"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ReviewReport.objects.exists())

    def test_anonymous_report_prompts_sign_in(self):
        review = Review.objects.create(edition=self.edition, user=self.user, body="مراجعة للإبلاغ")
        response = self.client.post(
            reverse("review_report_create", kwargs={"review_public_id": review.public_id}),
            {"reason": "spam"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "سجّل الدخول")
        self.assertFalse(ReviewReport.objects.exists())

    @override_settings(
        ADMINS=[("Admin", "admin@example.com")],
        DEFAULT_FROM_EMAIL="noreply@example.com",
    )
    def test_report_sends_email(self):
        other = User.objects.create_user(
            email="other@example.com",
            username="other",
            password="pass",
        )
        review = Review.objects.create(edition=self.edition, user=other, body="مراجعة للإبلاغ")
        self.client.login(email="user@example.com", password="pass")
        response = self.client.post(
            reverse("review_report_create", kwargs={"review_public_id": review.public_id}),
            {"reason": "inappropriate", "details": "تفاصيل"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("بلاغ جديد", mail.outbox[0].subject)


class NameListViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="contrib@example.com",
            username="contrib",
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
            editor_name="محقق الاختبار",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        self.author_record = self.book.authors.first()
        self.publisher_record = self.edition.publishers.first()
        self.editor_record = self.edition.editors.first()

    def test_author_list_renders(self):
        response = self.client.get(reverse("author_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.author_record.name)
        self.assertContains(response, reverse("author_detail", kwargs={"slug": self.author_record.slug}))

    def test_publisher_list_renders(self):
        response = self.client.get(reverse("publisher_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.publisher_record.name)
        self.assertContains(response, reverse("publisher_detail", kwargs={"slug": self.publisher_record.slug}))

    def test_author_list_hides_pending_records(self):
        NameRecord.objects.create(
            kind=NameRecordKind.AUTHOR,
            name="مؤلف معلق",
            status=NameRecordStatus.PENDING,
        )
        response = self.client.get(reverse("author_list"))
        self.assertNotContains(response, "مؤلف معلق")

    def test_publisher_list_hides_pending_records(self):
        NameRecord.objects.create(
            kind=NameRecordKind.PUBLISHER,
            name="ناشر معلق",
            status=NameRecordStatus.PENDING,
        )
        response = self.client.get(reverse("publisher_list"))
        self.assertNotContains(response, "ناشر معلق")

    def test_author_list_paginates(self):
        for i in range(1, 4):
            book = create_book(
                title=f"كتاب تجريبي {i}",
                author_name=f"مؤلف تجريبي {i}",
                category=self.category,
            )
            create_edition(
                book=book,
                publisher_name=f"دار تجريبية {i}",
                status=EditionStatus.APPROVED,
                submitted_by=self.user,
            )
        with patch("encyclopedia.views.NAMES_LIST_PAGE_SIZE", 2):
            # The setUp author (ابن القيم) sorts first, so page 1 is that + new author 1.
            response = self.client.get(reverse("author_list"))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, self.author_record.name)
            self.assertContains(response, "مؤلف تجريبي 1")
            self.assertNotContains(response, "مؤلف تجريبي 2")
            self.assertNotContains(response, "مؤلف تجريبي 3")
            self.assertContains(response, "?page=2")

            response = self.client.get(reverse("author_list"), {"page": "2"})
            self.assertContains(response, "مؤلف تجريبي 2")
            self.assertContains(response, "مؤلف تجريبي 3")
            self.assertNotContains(response, "مؤلف تجريبي 1")

    def test_publisher_list_paginates(self):
        for i in range(1, 4):
            book = create_book(
                title=f"كتاب ناشر {i}",
                author_name=f"مؤلف ناشر {i}",
                category=self.category,
            )
            create_edition(
                book=book,
                publisher_name=f"دار ناشر {i}",
                status=EditionStatus.APPROVED,
                submitted_by=self.user,
            )
        with patch("encyclopedia.views.NAMES_LIST_PAGE_SIZE", 2):
            # The setUp publisher (دار الفكر) sorts first, so page 1 is that + new publisher 1.
            response = self.client.get(reverse("publisher_list"))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, self.publisher_record.name)
            self.assertContains(response, "دار ناشر 1")
            self.assertNotContains(response, "دار ناشر 2")
            self.assertNotContains(response, "دار ناشر 3")
            self.assertContains(response, "?page=2")

            response = self.client.get(reverse("publisher_list"), {"page": "2"})
            self.assertContains(response, "دار ناشر 2")
            self.assertContains(response, "دار ناشر 3")
            self.assertNotContains(response, "دار ناشر 1")

    def test_editor_list_renders(self):
        response = self.client.get(reverse("editor_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.editor_record.name)
        self.assertContains(response, reverse("editor_detail", kwargs={"slug": self.editor_record.slug}))

    def test_editor_list_hides_pending_records(self):
        NameRecord.objects.create(
            kind=NameRecordKind.EDITOR,
            name="محقق معلق",
            status=NameRecordStatus.PENDING,
        )
        response = self.client.get(reverse("editor_list"))
        self.assertNotContains(response, "محقق معلق")

    def test_editor_list_paginates(self):
        for i in range(1, 4):
            book = create_book(
                title=f"كتاب محقق {i}",
                author_name=f"مؤلف محقق {i}",
                category=self.category,
            )
            create_edition(
                book=book,
                publisher_name=f"دار محقق {i}",
                editor_name=f"محقق تجريبي {i}",
                status=EditionStatus.APPROVED,
                submitted_by=self.user,
            )
        with patch("encyclopedia.views.NAMES_LIST_PAGE_SIZE", 2):
            # The setUp editor (محقق الاختبار) sorts first, so page 1 is that + new editor 1.
            response = self.client.get(reverse("editor_list"))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, self.editor_record.name)
            self.assertContains(response, "محقق تجريبي 1")
            self.assertNotContains(response, "محقق تجريبي 2")
            self.assertNotContains(response, "محقق تجريبي 3")
            self.assertContains(response, "?page=2")

            response = self.client.get(reverse("editor_list"), {"page": "2"})
            self.assertContains(response, "محقق تجريبي 2")
            self.assertContains(response, "محقق تجريبي 3")
            self.assertNotContains(response, "محقق تجريبي 1")


class ExpertFlairTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="user@example.com",
            username="user",
            password="pass",
        )
        self.expert = User.objects.create_user(
            email="expert@example.com",
            username="expert",
            password="pass",
            is_expert=True,
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
            submitted_by=self.expert,
        )
        self.client = Client()

    def test_default_expert_label(self):
        self.assertEqual(self.expert.expert_label, "خبير")

    def test_custom_expert_label(self):
        self.expert.expert_flair = "باحث"
        self.expert.save()
        self.assertEqual(self.expert.expert_label, "باحث")

    def test_non_expert_has_no_label(self):
        self.assertEqual(self.user.expert_label, "")

    def test_custom_flair_on_book_detail(self):
        self.expert.expert_flair = "باحث"
        self.expert.save()
        response = self.client.get(reverse("book_detail", kwargs={"slug": self.book.slug}))
        self.assertContains(response, "باحث")
        self.assertContains(response, self.expert.username)

    def test_custom_flair_on_edition_detail(self):
        self.expert.expert_flair = "مراجع"
        self.expert.save()
        response = self.client.get(reverse("edition_detail", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}))
        self.assertContains(response, "مراجع")
        self.assertContains(response, self.expert.username)

    def test_custom_flair_on_comment(self):
        self.expert.expert_flair = "محقق"
        self.expert.save()
        Review.objects.create(edition=self.edition, user=self.expert, body="تعليق")
        response = self.client.get(reverse("edition_detail", kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id}))
        self.assertContains(response, "محقق")

    def test_custom_flair_on_nav_user(self):
        self.client.login(email="expert@example.com", password="pass")
        self.expert.expert_flair = "ناشر موثوق"
        self.expert.save()
        response = self.client.get(reverse("home"))
        self.assertContains(response, "ناشر موثوق")
        self.assertContains(response, self.expert.username)


class MultiCreatorTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="contrib@example.com",
            username="contrib",
            password="pass",
        )
        self.client = Client()
        self.client.login(email="contrib@example.com", password="pass")
        self.category = Category.objects.create(name="فقه")

    def _approved_author(self, name):
        record, _ = NameRecord.objects.get_or_create(
            kind=NameRecordKind.AUTHOR,
            name=name,
            defaults={"status": NameRecordStatus.APPROVED},
        )
        return record

    def test_new_book_two_authors_sorted_alphabetically(self):
        response = self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "new",
                "new_book_title": "كتاب مشترك",
                "new_book_authors": json.dumps([
                    {"name": "زيد"},
                    {"name": "أحمد"},
                ]),
                "new_book_categories": json.dumps(
                    [{"id": self.category.pk, "name": self.category.name}]
                ),
                "publishers": json.dumps([{"name": "دار تجريب"}]),
                "is_best": "no",
            },
        )
        self.assertRedirects(response, reverse("home"))
        book = Book.objects.get(title="كتاب مشترك")
        author_names = list(
            book.book_authors.order_by("order").values_list("name_record__name", flat=True)
        )
        self.assertEqual(author_names, ["أحمد", "زيد"])

    def test_new_edition_two_publishers(self):
        book = create_book(title="كتاب ناشرين", author_name="مؤلف", category=self.category)
        response = self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": str(book.pk),
                "publishers": json.dumps([
                    {"name": "دار ب"},
                    {"name": "دار أ"},
                ]),
                "is_best": "no",
            },
        )
        self.assertRedirects(response, reverse("home"))
        edition = Edition.objects.latest("pk")
        publisher_names = list(
            edition.edition_publishers.order_by("order").values_list("name_record__name", flat=True)
        )
        self.assertEqual(publisher_names, ["دار أ", "دار ب"])

    def test_duplicate_detection_with_second_publisher_same_year(self):
        book = create_book(title="كتاب مكرر", author_name="مؤلف", category=self.category)
        create_edition(
            book=book,
            publisher_name="الناشر الأوّل",
            year=2020,
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        response = self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": str(book.pk),
                "publishers": json.dumps([
                    {"name": "الناشر الأوّل"},
                    {"name": "الناشر الثاني"},
                ]),
                "year": "2020",
                "is_best": "no",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "طبعات مشابهة موجودة")
        self.assertEqual(Edition.objects.filter(book=book).count(), 1)

    def test_search_finds_book_by_second_author(self):
        book = create_book(title="كتاب مؤلفين", author_name="مؤلف أول", category=self.category)
        second = self._approved_author("مؤلف ثانٍ")
        BookAuthor.objects.create(book=book, name_record=second, order=1)
        create_edition(
            book=book,
            publisher_name="دار البحث",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        response = self.client.get(reverse("search"), {"q": "مؤلف ثانٍ"})
        self.assertContains(response, book.title)

    def test_author_detail_shows_book_where_author_is_second(self):
        book = create_book(title="كتاب مؤلفين", author_name="مؤلف أول", category=self.category)
        second = self._approved_author("مؤلف ثانٍ")
        BookAuthor.objects.create(book=book, name_record=second, order=1)
        create_edition(
            book=book,
            publisher_name="دار البحث",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        response = self.client.get(reverse("author_detail", kwargs={"slug": second.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, book.title)


class EditionEditSuggestionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="contrib@example.com",
            username="contrib",
            password="pass",
        )
        self.admin_user = User.objects.create_superuser(
            email="admin@example.com",
            username="admin",
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
            editor_name="محقق أول",
            year=2010,
            page_count=300,
            city="دمشق",
            volumes="1",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        self.url = reverse(
            "suggest_edition_edit",
            kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id},
        )

    def _payload(self, **overrides):
        defaults = {
            "proposed_publishers": json.dumps([{"name": "دار الفكر"}]),
            "proposed_editors": json.dumps([{"name": "محقق أول"}]),
            "year": "2015",
            "page_count": "350",
            "city": "الرياض",
            "volumes": "2",
        }
        defaults.update(overrides)
        return defaults

    def test_login_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_get_prefills_form(self):
        self.client.login(email="contrib@example.com", password="pass")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "دار الفكر")
        self.assertContains(response, "دمشق")
        self.assertContains(response, "2010")

    def test_post_creates_pending_suggestion(self):
        self.client.login(email="contrib@example.com", password="pass")
        response = self.client.post(self.url, self._payload())
        self.assertEqual(response.status_code, 302)
        suggestion = EditionEditSuggestion.objects.get()
        self.assertEqual(suggestion.edition, self.edition)
        self.assertEqual(suggestion.suggested_by, self.user)
        self.assertEqual(suggestion.status, "pending")
        self.assertEqual(suggestion.year, 2015)
        self.assertEqual(suggestion.page_count, 350)
        self.assertEqual(suggestion.city, "الرياض")
        self.assertEqual(suggestion.volumes, "2")

    def test_post_creates_pending_name_records(self):
        self.client.login(email="contrib@example.com", password="pass")
        response = self.client.post(
            self.url,
            self._payload(
                proposed_publishers=json.dumps([{"name": "ناشر جديد"}]),
                proposed_editors=json.dumps([{"name": "محقق جديد"}]),
            ),
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            NameRecord.objects.filter(
                kind=NameRecordKind.PUBLISHER, name="ناشر جديد", status="pending"
            ).exists()
        )
        self.assertTrue(
            NameRecord.objects.filter(
                kind=NameRecordKind.EDITOR, name="محقق جديد", status="pending"
            ).exists()
        )

    def test_cannot_edit_unapproved_edition(self):
        self.edition.status = EditionStatus.PENDING
        self.edition.save(update_fields=["status"])
        self.client.login(email="contrib@example.com", password="pass")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_admin_approve_applies_changes(self):
        suggestion = EditionEditSuggestion.objects.create(
            edition=self.edition,
            suggested_by=self.user,
            proposed_publishers=["دار المعرفة"],
            proposed_editors=["محقق ثانٍ"],
            year=2020,
            page_count=400,
            city="القاهرة",
            volumes="3",
        )
        suggestion.apply_to_edition(self.admin_user)
        self.edition.refresh_from_db()
        self.assertEqual(self.edition.year, 2020)
        self.assertEqual(self.edition.page_count, 400)
        self.assertEqual(self.edition.volumes, "3")
        publishers = list(self.edition.publishers.values_list("name", flat=True))
        self.assertEqual(publishers, ["دار المعرفة"])
        publisher = self.edition.publishers.first()
        self.assertEqual(publisher.city, "القاهرة")
        editors = list(self.edition.editors.values_list("name", flat=True))
        self.assertEqual(editors, ["محقق ثانٍ"])
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, "approved")
        self.assertEqual(suggestion.resolved_by, self.admin_user)
        self.assertIsNotNone(suggestion.resolved_at)

    def test_admin_approve_action(self):
        suggestion = EditionEditSuggestion.objects.create(
            edition=self.edition,
            suggested_by=self.user,
            proposed_publishers=["دار المعرفة"],
            year=2020,
        )
        site = AdminSite()
        modeladmin = EditionEditSuggestionAdmin(EditionEditSuggestion, site)
        request = RequestFactory().post("/admin/encyclopedia/editioneditsuggestion/")
        request.user = self.admin_user
        request.session = {}
        request._messages = FallbackStorage(request)
        queryset = EditionEditSuggestion.objects.filter(pk=suggestion.pk)
        modeladmin.approve_suggestions(request, queryset)
        suggestion.refresh_from_db()
        self.edition.refresh_from_db()
        self.assertEqual(suggestion.status, "approved")
        self.assertEqual(self.edition.year, 2020)

    def test_admin_reject_action(self):
        suggestion = EditionEditSuggestion.objects.create(
            edition=self.edition,
            suggested_by=self.user,
            year=2020,
        )
        site = AdminSite()
        modeladmin = EditionEditSuggestionAdmin(EditionEditSuggestion, site)
        request = RequestFactory().post("/admin/encyclopedia/editioneditsuggestion/")
        request.user = self.admin_user
        request.session = {}
        request._messages = FallbackStorage(request)
        queryset = EditionEditSuggestion.objects.filter(pk=suggestion.pk)
        modeladmin.reject_suggestions(request, queryset)
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, "rejected")
        self.assertEqual(suggestion.resolved_by, self.admin_user)


class EditionBookLinkTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="user@example.com",
            username="user",
            password="pass",
        )
        self.admin_user = User.objects.create_user(
            email="admin@example.com",
            username="admin",
            password="pass",
            is_staff=True,
        )
        self.category = Category.objects.create(name="أدب")
        self.original_book = create_book(
            title="بانت سعاد",
            author_name="كعب بن زهير",
            category=self.category,
        )
        self.commentary_book = create_book(
            title="شرح بانت سعاد",
            author_name="جمال الدين ابن هشام",
            category=self.category,
        )
        self.original_edition = create_edition(
            book=self.original_book,
            publisher_name="دار الأصل",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        self.commentary_edition = create_edition(
            book=self.commentary_book,
            publisher_name="دار سعد الدين",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        self.client = Client()

    def test_linked_edition_appears_on_original_book_page(self):
        EditionBookLink.objects.create(
            edition=self.commentary_edition,
            book=self.original_book,
            role=EditionBookLinkRole.COMMENTARY,
        )
        response = self.client.get(
            reverse("book_detail", kwargs={"slug": self.original_book.slug})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.commentary_book.title)

    def test_voting_on_linked_edition_is_context_specific(self):
        EditionBookLink.objects.create(
            edition=self.commentary_edition,
            book=self.original_book,
            role=EditionBookLinkRole.COMMENTARY,
        )
        self.client.login(email="user@example.com", password="pass")

        # Vote on the commentary edition from the original book's page.
        response = self.client.post(
            reverse(
                "edition_vote",
                kwargs={
                    "book_slug": self.commentary_book.slug,
                    "edition_public_id": self.commentary_edition.public_id,
                },
            ),
            {"vote": "like", "context_book": self.original_book.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1")

        # Primary context score should be unaffected.
        commentary_context_vote = EditionVote.objects.filter(
            edition=self.commentary_edition,
            book_context=self.commentary_book,
        ).first()
        self.assertIsNone(commentary_context_vote)

        original_context_vote = EditionVote.objects.get(
            edition=self.commentary_edition,
            book_context=self.original_book,
        )
        self.assertEqual(original_context_vote.value, 1)

    def test_original_only_filter_hides_linked_editions(self):
        EditionBookLink.objects.create(
            edition=self.commentary_edition,
            book=self.original_book,
            role=EditionBookLinkRole.COMMENTARY,
        )
        response = self.client.get(
            reverse("book_detail", kwargs={"slug": self.original_book.slug}),
            {"original_only": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.commentary_book.title)
        self.assertContains(response, self.original_edition.publishers.first().name)

    def test_suggest_edition_link_creates_pending_suggestion(self):
        self.client.login(email="user@example.com", password="pass")
        response = self.client.post(
            reverse(
                "suggest_edition_link",
                kwargs={"slug": self.original_book.slug},
            ),
            {
                "edition": self.commentary_edition.pk,
                "role": EditionBookLinkRole.COMMENTARY,
                "reason": "أفضل شرح",
            },
        )
        self.assertEqual(response.status_code, 200)
        suggestion = EditionBookLinkSuggestion.objects.get(
            edition=self.commentary_edition,
            book=self.original_book,
        )
        self.assertEqual(suggestion.status, EditionBookLinkSuggestionStatus.PENDING)

    def test_admin_approve_link_suggestion_creates_link(self):
        suggestion = EditionBookLinkSuggestion.objects.create(
            edition=self.commentary_edition,
            book=self.original_book,
            role=EditionBookLinkRole.COMMENTARY,
            suggested_by=self.user,
        )
        site = AdminSite()
        from .admin import EditionBookLinkSuggestionAdmin

        modeladmin = EditionBookLinkSuggestionAdmin(EditionBookLinkSuggestion, site)
        request = RequestFactory().post("/admin/encyclopedia/editionbooklinksuggestion/")
        request.user = self.admin_user
        request.session = {}
        request._messages = FallbackStorage(request)
        queryset = EditionBookLinkSuggestion.objects.filter(pk=suggestion.pk)
        modeladmin.approve_suggestions(request, queryset)
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, EditionBookLinkSuggestionStatus.APPROVED)
        self.assertTrue(
            EditionBookLink.objects.filter(
                edition=self.commentary_edition,
                book=self.original_book,
            ).exists()
        )


class ExpertAutoApprovalTests(TestCase):
    def setUp(self):
        cache.clear()
        self.regular = User.objects.create_user(
            email="regular@example.com",
            username="regular",
            password="pass",
        )
        self.expert = User.objects.create_user(
            email="expert@example.com",
            username="expert",
            password="pass",
            is_expert=True,
        )
        self.client = Client()
        self.category = Category.objects.create(name="أدب")
        self.book = create_book(
            title="كتاب التجربة",
            author_name="مؤلف التجربة",
            category=self.category,
        )
        self.edition = create_edition(
            book=self.book,
            publisher_name="دار الأصل",
            year=2010,
            status=EditionStatus.APPROVED,
            submitted_by=self.regular,
        )

    def _login(self, user):
        self.client.login(email=user.email, password="pass")

    def test_non_expert_edition_submission_is_pending(self):
        self._login(self.regular)
        self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": str(self.book.pk),
                "publishers": json.dumps([{"name": "دار المستخدم"}]),
                "year": "",
                "editors": "",
                "page_count": "",
                "city": "",
                "volumes": "",
                "is_best": "no",
            },
        )
        edition = Edition.objects.get(publishers__name="دار المستخدم")
        self.assertEqual(edition.status, EditionStatus.PENDING)
        self.assertEqual(ApprovalLog.objects.filter(edition=edition).count(), 0)

    def test_expert_edition_submission_is_approved(self):
        self._login(self.expert)
        self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": str(self.book.pk),
                "publishers": json.dumps([{"name": "دار الخبير"}]),
                "year": "2022",
                "editors": "",
                "page_count": "",
                "city": "",
                "volumes": "",
                "is_best": "no",
            },
        )
        edition = Edition.objects.get(publishers__name="دار الخبير")
        self.assertEqual(edition.status, EditionStatus.APPROVED)
        self.assertEqual(edition.approved_by, self.expert)
        self.assertIsNotNone(edition.approved_at)
        self.assertEqual(
            ApprovalLog.objects.filter(
                edition=edition,
                new_status=EditionStatus.APPROVED,
            ).count(),
            1,
        )

    def test_non_expert_edit_suggestion_is_pending(self):
        self._login(self.regular)
        response = self.client.post(
            reverse(
                "suggest_edition_edit",
                kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id},
            ),
            {
                "proposed_publishers": json.dumps([{"name": "دار الأصل"}]),
                "proposed_editors": json.dumps([]),
                "year": "2015",
                "page_count": "",
                "city": "",
                "volumes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        suggestion = EditionEditSuggestion.objects.get()
        self.assertEqual(suggestion.status, EditionEditSuggestionStatus.PENDING)
        self.edition.refresh_from_db()
        self.assertEqual(self.edition.year, 2010)

    def test_expert_edit_suggestion_is_applied(self):
        self._login(self.expert)
        response = self.client.post(
            reverse(
                "suggest_edition_edit",
                kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id},
            ),
            {
                "proposed_publishers": json.dumps([{"name": "دار الأصل"}]),
                "proposed_editors": json.dumps([]),
                "year": "2015",
                "page_count": "",
                "city": "",
                "volumes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        suggestion = EditionEditSuggestion.objects.get()
        self.assertEqual(suggestion.status, EditionEditSuggestionStatus.APPROVED)
        self.assertEqual(suggestion.resolved_by, self.expert)
        self.edition.refresh_from_db()
        self.assertEqual(self.edition.year, 2015)

    def test_non_expert_link_suggestion_is_pending(self):
        other_book = create_book(
            title="كتاب آخر", author_name="مؤلف آخر", category=self.category
        )
        other_edition = create_edition(
            book=other_book,
            publisher_name="دار أخرى",
            status=EditionStatus.APPROVED,
            submitted_by=self.regular,
        )
        self._login(self.regular)
        response = self.client.post(
            reverse("suggest_edition_link", kwargs={"slug": self.book.slug}),
            {
                "edition": other_edition.pk,
                "role": EditionBookLinkRole.COMMENTARY,
                "reason": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        suggestion = EditionBookLinkSuggestion.objects.get()
        self.assertEqual(suggestion.status, EditionBookLinkSuggestionStatus.PENDING)
        self.assertFalse(
            EditionBookLink.objects.filter(
                edition=other_edition, book=self.book
            ).exists()
        )

    def test_expert_link_suggestion_is_approved(self):
        other_book = create_book(
            title="كتاب الخبير", author_name="مؤلف الخبير", category=self.category
        )
        other_edition = create_edition(
            book=other_book,
            publisher_name="دار الخبير",
            status=EditionStatus.APPROVED,
            submitted_by=self.expert,
        )
        self._login(self.expert)
        response = self.client.post(
            reverse("suggest_edition_link", kwargs={"slug": self.book.slug}),
            {
                "edition": other_edition.pk,
                "role": EditionBookLinkRole.COMMENTARY,
                "reason": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "تم اعتماد")
        suggestion = EditionBookLinkSuggestion.objects.get()
        self.assertEqual(suggestion.status, EditionBookLinkSuggestionStatus.APPROVED)
        self.assertEqual(suggestion.resolved_by, self.expert)
        self.assertTrue(
            EditionBookLink.objects.filter(
                edition=other_edition, book=self.book
            ).exists()
        )

    def test_non_expert_relation_suggestion_is_pending(self):
        target = create_edition(
            book=self.book,
            publisher_name="دار الهدف",
            year=2018,
            status=EditionStatus.APPROVED,
            submitted_by=self.regular,
        )
        self._login(self.regular)
        self.client.post(
            reverse(
                "suggest_edition_relation",
                kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id},
            ),
            {
                "target_mode": "existing",
                "target": target.pk,
                "kind": EditionRelationKind.PHOTOCOPY,
            },
        )
        suggestion = EditionRelationSuggestion.objects.get()
        self.assertEqual(suggestion.status, EditionRelationSuggestionStatus.PENDING)
        self.assertFalse(
            EditionRelation.objects.filter(source=self.edition, target=target).exists()
        )

    def test_expert_relation_suggestion_is_approved(self):
        target = create_edition(
            book=self.book,
            publisher_name="دار الهدف",
            year=2018,
            status=EditionStatus.APPROVED,
            submitted_by=self.regular,
        )
        self._login(self.expert)
        response = self.client.post(
            reverse(
                "suggest_edition_relation",
                kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id},
            ),
            {
                "target_mode": "existing",
                "target": target.pk,
                "kind": EditionRelationKind.PHOTOCOPY,
            },
        )
        self.assertEqual(response.status_code, 302)
        suggestion = EditionRelationSuggestion.objects.get()
        self.assertEqual(suggestion.status, EditionRelationSuggestionStatus.APPROVED)
        self.assertEqual(suggestion.resolved_by, self.expert)
        self.assertTrue(
            EditionRelation.objects.filter(source=self.edition, target=target).exists()
        )

    def test_expert_new_relation_suggestion_creates_approved_target_edition(self):
        self._login(self.expert)
        response = self.client.post(
            reverse(
                "suggest_edition_relation",
                kwargs={"book_slug": self.book.slug, "edition_public_id": self.edition.public_id},
            ),
            {
                "target_mode": "new",
                "new_publishers": json.dumps([{"name": "دار جديدة"}]),
                "new_year": 2020,
                "kind": EditionRelationKind.REPRINT,
            },
        )
        self.assertEqual(response.status_code, 302)
        suggestion = EditionRelationSuggestion.objects.get()
        self.assertIsNotNone(suggestion.target)
        self.assertEqual(suggestion.target.status, EditionStatus.APPROVED)
        self.assertEqual(suggestion.target.approved_by, self.expert)
        self.assertEqual(
            suggestion.status, EditionRelationSuggestionStatus.APPROVED
        )
        self.assertTrue(
            EditionRelation.objects.filter(
                source=self.edition, target=suggestion.target
            ).exists()
        )

    def test_expert_new_book_submission_approves_author_record(self):
        self._login(self.expert)
        self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "new",
                "new_book_title": "كتاب الخبير الجديد",
                "new_book_authors": json.dumps([{"name": "مؤلف الخبير"}]),
                "new_book_categories": json.dumps(
                    [{"id": self.category.pk, "name": self.category.name}]
                ),
                "publishers": json.dumps([{"name": "ناشر الخبير"}]),
                "year": "",
                "editors": "",
                "page_count": "",
                "city": "",
                "volumes": "",
                "is_best": "no",
            },
        )
        author = NameRecord.objects.get(
            kind=NameRecordKind.AUTHOR, name="مؤلف الخبير"
        )
        self.assertEqual(author.status, NameRecordStatus.APPROVED)
        self.assertEqual(author.approved_by, self.expert)
        self.assertIsNotNone(author.approved_at)

    def test_expert_edition_submission_approves_new_name_records(self):
        self._login(self.expert)
        self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": str(self.book.pk),
                "publishers": json.dumps([{"name": "ناشر الخبير"}]),
                "editors": json.dumps([{"name": "محقق الخبير"}]),
                "year": "",
                "page_count": "",
                "city": "",
                "volumes": "",
                "is_best": "no",
            },
        )
        publisher = NameRecord.objects.get(
            kind=NameRecordKind.PUBLISHER, name="ناشر الخبير"
        )
        editor = NameRecord.objects.get(
            kind=NameRecordKind.EDITOR, name="محقق الخبير"
        )
        self.assertEqual(publisher.status, NameRecordStatus.APPROVED)
        self.assertEqual(editor.status, NameRecordStatus.APPROVED)
        self.assertEqual(publisher.approved_by, self.expert)
        self.assertEqual(editor.approved_by, self.expert)
