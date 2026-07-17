"""Tests for multiple categories per book and user category suggestions."""

import json

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from .admin import CategoryAdminForm, CategoryRequestAdmin, CategorySuggestionAdmin
from .forms import EditionSubmissionForm
from .models import (
    BookCategory,
    Category,
    CategoryRequest,
    CategoryRequestStatus,
    CategorySuggestion,
    CategorySuggestionStatus,
    CategorySuggestionVote,
    EditionStatus,
)
from .test_factories import create_book, create_edition

User = get_user_model()


class MultipleCategoriesTests(TestCase):
    def setUp(self):
        self.category_a = Category.objects.create(name="فقه")
        self.category_b = Category.objects.create(name="عقيدة")
        self.book = create_book(title="كتاب مشترك", author_name="مؤلف")

    def test_book_can_have_multiple_categories(self):
        self.book.categories.add(self.category_a)
        self.book.categories.add(self.category_b)
        self.assertEqual(self.book.categories.count(), 2)

    def test_primary_category_is_order_zero(self):
        self.book.categories.add(self.category_b)
        self.book.categories.add(self.category_a)
        # Re-fetch to ensure ordering reflects insertion order.
        ordered = [
            bc.category
            for bc in self.book.book_categories.order_by("order")
        ]
        self.assertEqual(ordered, [self.category_b, self.category_a])
        self.assertEqual(self.book.primary_category, self.category_b)

    def test_cannot_add_duplicate_category(self):
        self.book.categories.add(self.category_a)
        with self.assertRaises(IntegrityError):
            BookCategory.objects.create(book=self.book, category=self.category_a, order=1)


class SubmissionFormCategoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="contrib@example.com",
            username="contrib",
            password="pass",
        )
        self.cat_a = Category.objects.create(name="فقه")
        self.cat_b = Category.objects.create(name="عقيدة")

    def _category_payload(self, *categories):
        return json.dumps(
            [{"id": category.pk, "name": category.name} for category in categories]
        )

    def _payload(self, **overrides):
        defaults = {
            "book_action": "new",
            "existing_book": "",
            "new_book_title": "كتاب جديد",
            "new_book_authors": json.dumps([{"name": "مؤلف جديد"}]),
            "new_book_categories": self._category_payload(self.cat_a, self.cat_b),
            "publishers": json.dumps([{"name": "دار تجريب"}]),
            "year": "",
            "editors": "",
            "page_count": "",
            "city": "",
            "volumes": "",
            "is_best": "no",
        }
        defaults.update(overrides)
        return defaults

    def test_new_book_with_multiple_categories(self):
        form = EditionSubmissionForm(self._payload())
        self.assertTrue(form.is_valid())
        edition = form.save(self.user)
        book = edition.book
        self.assertEqual(book.categories.count(), 2)
        ordered = [bc.category for bc in book.book_categories.order_by("order")]
        self.assertEqual(ordered, [self.cat_a, self.cat_b])

    def test_unknown_category_rejected(self):
        form = EditionSubmissionForm(
            self._payload(
                new_book_categories=json.dumps([{"id": 9999, "name": "غير موجود"}]),
            )
        )
        self.assertFalse(form.is_valid())
        self.assertIn("new_book_categories", form.errors)

    def test_at_least_one_category_required(self):
        form = EditionSubmissionForm(
            self._payload(new_book_categories=""),
        )
        self.assertFalse(form.is_valid())
        self.assertIn("new_book_categories", form.errors)


class CategoryDetailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="contrib@example.com",
            username="contrib",
            password="pass",
        )
        self.primary = Category.objects.create(name="فقه")
        self.secondary = Category.objects.create(name="عقيدة")
        self.book = create_book(title="كتاب مشترك", author_name="مؤلف")
        self.book.categories.add(self.primary)
        self.book.categories.add(self.secondary)
        create_edition(
            book=self.book,
            publisher_name="دار الفكر",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )

    def test_category_detail_lists_book_with_secondary_category(self):
        response = self.client.get(
            reverse(
                "category_detail",
                kwargs={"category_path": self.secondary.get_url_path()},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.book.title)


class SearchCategoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="contrib@example.com",
            username="contrib",
            password="pass",
        )
        self.primary = Category.objects.create(name="فقه")
        self.secondary = Category.objects.create(name="حديث")
        self.book = create_book(title="صحيح البخاري", author_name="البخاري")
        self.book.categories.add(self.primary)
        self.book.categories.add(self.secondary)
        create_edition(
            book=self.book,
            publisher_name="دار الفكر",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )

    def test_search_filter_includes_secondary_category(self):
        response = self.client.get(
            reverse("search"),
            {"q": "البخاري", "category": self.secondary.slug},
        )
        self.assertContains(response, self.book.title)


class CategoryAutocompleteTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="فقه")
        Category.objects.create(name="عقيدة")
        Category.objects.create(name="تفسير")

    def test_autocomplete_returns_matching_categories(self):
        response = self.client.get(
            reverse("category_autocomplete"), {"q": "فق"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "فقه")
        self.assertNotContains(response, "عقيدة")

    def test_autocomplete_empty_query_returns_empty(self):
        response = self.client.get(reverse("category_autocomplete"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "فقه")

    def test_autocomplete_no_match_shows_request_link(self):
        response = self.client.get(
            reverse("category_autocomplete"), {"q": "غير موجود"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "اقترح")

    def test_autocomplete_exposes_url_path(self):
        response = self.client.get(
            reverse("category_autocomplete"), {"q": "فق"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("url_path", response.context["categories"][0].__dict__)
        self.assertEqual(
            response.context["categories"][0].url_path,
            self.category.get_url_path(),
        )


class CategorySuggestionsTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="فقه")
        Category.objects.create(name="عقيدة")
        Category.objects.create(name="تفسير")

    def test_suggestions_return_matching_categories(self):
        response = self.client.get(
            reverse("category_suggestions"), {"q": "فق"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "فقه")
        self.assertNotContains(response, "عقيدة")
        self.assertContains(response, "category-chip-suggestion")

    def test_suggestions_empty_query_returns_empty(self):
        response = self.client.get(reverse("category_suggestions"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "فقه")

    def test_suggestions_no_match_shows_request_link(self):
        response = self.client.get(
            reverse("category_suggestions"), {"q": "غير موجود"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "اطلب تصنيفاً جديداً")

    def test_suggestions_expose_url_path(self):
        root = Category.objects.create(name="اللغة")
        child = Category.objects.create(name="النحو", parent=root)
        response = self.client.get(
            reverse("category_suggestions"), {"q": "نح"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("url_path", response.context["categories"][0].__dict__)
        self.assertEqual(
            response.context["categories"][0].url_path,
            child.get_url_path(),
        )


class CategorySuggestionTests(TestCase):
    def setUp(self):
        cache.clear()
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
        self.book = create_book(title="كتاب الفقه", author_name="ابن القيم")
        self.book.categories.add(self.category)
        self.client = Client()

    def test_authenticated_user_can_view_form(self):
        self.client.login(email="contrib@example.com", password="pass")
        response = self.client.get(
            reverse("suggest_category", kwargs={"slug": self.book.slug})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "category")
        self.assertContains(response, 'name="q"')

    def test_autocomplete_input_sends_query(self):
        self.client.login(email="contrib@example.com", password="pass")
        response = self.client.get(
            reverse("category_autocomplete"), {"q": "فق"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.category.name)

    def test_anonymous_user_is_redirected(self):
        response = self.client.get(
            reverse("suggest_category", kwargs={"slug": self.book.slug})
        )
        self.assertEqual(response.status_code, 302)

    def test_suggest_existing_category_creates_pending_suggestion_with_self_like(self):
        new_category = Category.objects.create(name="تفسير")
        self.client.login(email="contrib@example.com", password="pass")
        response = self.client.post(
            reverse("suggest_category", kwargs={"slug": self.book.slug}),
            {"category": str(new_category.pk)},
        )
        self.assertEqual(response.status_code, 200)
        suggestion = CategorySuggestion.objects.get()
        self.assertEqual(suggestion.name, "تفسير")
        self.assertEqual(suggestion.final_category, new_category)
        self.assertEqual(suggestion.book, self.book)
        self.assertEqual(suggestion.suggested_by, self.user)
        self.assertEqual(suggestion.status, CategorySuggestionStatus.PENDING)
        self.assertTrue(
            CategorySuggestionVote.objects.filter(
                suggestion=suggestion, user=self.user, value=1
            ).exists()
        )
        self.assertEqual(response["HX-Trigger"], "refreshCategoryKicker")

    def test_suggest_already_linked_category_fails(self):
        self.client.login(email="contrib@example.com", password="pass")
        response = self.client.post(
            reverse("suggest_category", kwargs={"slug": self.book.slug}),
            {"category": str(self.category.pk)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CategorySuggestion.objects.exists())
        self.assertContains(response, "مُدرج بالفعل")

    def test_suggest_category_does_not_send_email_to_admins(self):
        new_category = Category.objects.create(name="تفسير")
        with self.settings(ADMINS=[("Admin", "admin@example.com")]):
            self.client.login(email="contrib@example.com", password="pass")
            self.client.post(
                reverse("suggest_category", kwargs={"slug": self.book.slug}),
                {"category": str(new_category.pk)},
            )
        self.assertEqual(len(mail.outbox), 0)

    def test_suggest_category_rate_limited(self):
        new_category = Category.objects.create(name="تفسير")
        self.client.login(email="contrib@example.com", password="pass")
        for _i in range(10):
            response = self.client.post(
                reverse("suggest_category", kwargs={"slug": self.book.slug}),
                {"category": str(new_category.pk)},
            )
            self.assertIn(response.status_code, [200, 429])
        response = self.client.post(
            reverse("suggest_category", kwargs={"slug": self.book.slug}),
            {"category": str(new_category.pk)},
        )
        self.assertEqual(response.status_code, 429)


class CategorySuggestionVoteTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="contrib@example.com",
            username="contrib",
            password="pass",
        )
        self.category = Category.objects.create(name="فقه")
        self.book = create_book(title="كتاب الفقه", author_name="ابن القيم")
        self.book.categories.add(self.category)
        self.client = Client()

    def _vote(self, user, suggestion, vote):
        self.client.login(email=user.email, password="pass")
        return self.client.post(
            reverse("category_suggestion_vote", kwargs={"pk": suggestion.pk}),
            {"vote": vote},
        )

    def test_kicker_shows_pending_suggestion(self):
        new_category = Category.objects.create(name="تفسير")
        CategorySuggestion.objects.create(
            book=self.book,
            suggested_by=self.user,
            name="تفسير",
            final_category=new_category,
            status=CategorySuggestionStatus.PENDING,
        )
        response = self.client.get(self.book.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, new_category.name)
        self.assertContains(response, "category-chip--unverified")

    def test_kicker_hides_rejected_suggestion(self):
        new_category = Category.objects.create(name="تفسير")
        CategorySuggestion.objects.create(
            book=self.book,
            suggested_by=self.user,
            name="تفسير",
            final_category=new_category,
            status=CategorySuggestionStatus.REJECTED,
        )
        response = self.client.get(self.book.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "category-chip--unverified")

    def test_suggest_duplicate_pending_category_fails(self):
        new_category = Category.objects.create(name="تفسير")
        CategorySuggestion.objects.create(
            book=self.book,
            suggested_by=self.user,
            name="تفسير",
            final_category=new_category,
            status=CategorySuggestionStatus.PENDING,
        )
        User.objects.create_user(
            email="other@example.com",
            username="other",
            password="pass",
        )
        self.client.login(email="other@example.com", password="pass")
        response = self.client.post(
            reverse("suggest_category", kwargs={"slug": self.book.slug}),
            {"category": str(new_category.pk)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "مُقترح بالفعل")
        self.assertEqual(CategorySuggestion.objects.count(), 1)

    def test_likes_promote_suggestion_to_approved_with_expert(self):
        new_category = Category.objects.create(name="تفسير")
        suggestion = CategorySuggestion.objects.create(
            book=self.book,
            suggested_by=None,
            name="تفسير",
            final_category=new_category,
            status=CategorySuggestionStatus.PENDING,
        )
        voters = [
            User.objects.create_user(
                email=f"voter{i}@example.com",
                username=f"voter{i}",
                password="pass",
            )
            for i in range(2)
        ]
        expert = User.objects.create_user(
            email="expert@example.com",
            username="expert",
            password="pass",
            is_expert=True,
        )
        voters.append(expert)
        for voter in voters:
            response = self._vote(voter, suggestion, "like")
            self.assertEqual(response.status_code, 204)
            self.assertEqual(response["HX-Trigger"], "refreshCategoryKicker")

        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, CategorySuggestionStatus.APPROVED)
        self.assertIn(new_category, self.book.categories.all())

    def test_non_expert_likes_do_not_auto_approve(self):
        new_category = Category.objects.create(name="تفسير")
        suggestion = CategorySuggestion.objects.create(
            book=self.book,
            suggested_by=None,
            name="تفسير",
            final_category=new_category,
            status=CategorySuggestionStatus.PENDING,
        )
        voters = [
            User.objects.create_user(
                email=f"voter{i}@example.com",
                username=f"voter{i}",
                password="pass",
            )
            for i in range(3)
        ]
        for voter in voters:
            response = self._vote(voter, suggestion, "like")
            self.assertEqual(response.status_code, 204)

        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, CategorySuggestionStatus.PENDING)
        self.assertNotIn(new_category, self.book.categories.all())

    def test_dislikes_reject_suggestion(self):
        new_category = Category.objects.create(name="تفسير")
        suggestion = CategorySuggestion.objects.create(
            book=self.book,
            suggested_by=None,
            name="تفسير",
            final_category=new_category,
            status=CategorySuggestionStatus.PENDING,
        )
        voters = [
            User.objects.create_user(
                email=f"voter{i}@example.com",
                username=f"voter{i}",
                password="pass",
            )
            for i in range(3)
        ]
        for voter in voters:
            response = self._vote(voter, suggestion, "dislike")
            self.assertEqual(response.status_code, 204)

        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, CategorySuggestionStatus.REJECTED)
        self.assertNotIn(new_category, self.book.categories.all())

    def test_vote_toggles(self):
        new_category = Category.objects.create(name="تفسير")
        suggestion = CategorySuggestion.objects.create(
            book=self.book,
            suggested_by=None,
            name="تفسير",
            final_category=new_category,
            status=CategorySuggestionStatus.PENDING,
        )
        self.client.login(email="contrib@example.com", password="pass")
        self.client.post(
            reverse("category_suggestion_vote", kwargs={"pk": suggestion.pk}),
            {"vote": "like"},
        )
        self.assertEqual(suggestion.votes.filter(value=1).count(), 1)
        self.client.post(
            reverse("category_suggestion_vote", kwargs={"pk": suggestion.pk}),
            {"vote": "like"},
        )
        self.assertEqual(suggestion.votes.count(), 0)

    def test_anonymous_vote_returns_sign_in_prompt(self):
        new_category = Category.objects.create(name="تفسير")
        suggestion = CategorySuggestion.objects.create(
            book=self.book,
            suggested_by=self.user,
            name="تفسير",
            final_category=new_category,
            status=CategorySuggestionStatus.PENDING,
        )
        response = self.client.post(
            reverse("category_suggestion_vote", kwargs={"pk": suggestion.pk}),
            {"vote": "like"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("login"))


class CategoryListPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="contrib@example.com",
            username="contrib",
            password="pass",
        )
        self.category = Category.objects.create(name="فقه")

    def test_category_list_page_renders(self):
        response = self.client.get(reverse("category_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.category.name)
        self.assertContains(response, "اقترح تصنيفاً")

    def test_anonymous_suggest_button_links_to_login(self):
        response = self.client.get(reverse("category_list"))
        self.assertContains(response, "اقترح تصنيفاً")
        self.assertContains(response, reverse("login"))

    def test_authenticated_user_can_load_request_form(self):
        self.client.login(email="contrib@example.com", password="pass")
        response = self.client.get(reverse("request_category"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "name")

    def test_anonymous_user_request_form_redirects(self):
        response = self.client.get(reverse("request_category"))
        self.assertEqual(response.status_code, 302)


class CategoryRequestTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="contrib@example.com",
            username="contrib",
            password="pass",
        )
        self.client = Client()

    def test_request_new_category_creates_pending_request(self):
        self.client.login(email="contrib@example.com", password="pass")
        response = self.client.post(
            reverse("request_category"),
            {"name": "تاريخ إسلامي"},
        )
        self.assertEqual(response.status_code, 200)
        request_obj = CategoryRequest.objects.get()
        self.assertEqual(request_obj.name, "تاريخ إسلامي")
        self.assertEqual(request_obj.suggested_by, self.user)
        self.assertEqual(request_obj.status, CategoryRequestStatus.PENDING)

    def test_request_duplicate_existing_category_fails(self):
        Category.objects.create(name="فقه")
        self.client.login(email="contrib@example.com", password="pass")
        response = self.client.post(
            reverse("request_category"),
            {"name": "فقه"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CategoryRequest.objects.exists())
        self.assertContains(response, "يوجد تصنيف بهذا الاسم")

    def test_request_category_sends_email_to_admins(self):
        with self.settings(ADMINS=[("Admin", "admin@example.com")]):
            self.client.login(email="contrib@example.com", password="pass")
            self.client.post(
                reverse("request_category"),
                {"name": "تاريخ إسلامي"},
            )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("تاريخ إسلامي", mail.outbox[0].subject)


class CategorySuggestionAdminTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            email="admin@example.com",
            username="admin",
            password="pass",
        )
        self.user = User.objects.create_user(
            email="contrib@example.com",
            username="contrib",
            password="pass",
        )
        self.category = Category.objects.create(name="فقه")
        self.book = create_book(title="كتاب الفقه", author_name="ابن القيم")
        self.book.categories.add(self.category)
        self.site = AdminSite()
        self.modeladmin = CategorySuggestionAdmin(CategorySuggestion, self.site)
        self.factory = RequestFactory()

    def _setup_request(self, method="post", data=None):
        request = self.factory.post("/admin/encyclopedia/categorysuggestion/", data or {})
        request.user = self.admin_user
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    def test_approve_existing_category_links_it(self):
        new_category = Category.objects.create(name="عقيدة")
        suggestion = CategorySuggestion.objects.create(
            book=self.book,
            suggested_by=self.user,
            name="عقيدة",
            final_category=new_category,
        )
        request = self._setup_request()
        queryset = CategorySuggestion.objects.filter(pk=suggestion.pk)
        self.modeladmin.approve_suggestions(request, queryset)
        self.assertEqual(Category.objects.filter(name="عقيدة").count(), 1)
        self.assertIn(new_category, self.book.categories.all())

    def test_approve_new_category_creates_it(self):
        suggestion = CategorySuggestion.objects.create(
            book=self.book,
            suggested_by=self.user,
            name="تفسير",
        )
        request = self._setup_request()
        queryset = CategorySuggestion.objects.filter(pk=suggestion.pk)
        self.modeladmin.approve_suggestions(request, queryset)
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, CategorySuggestionStatus.APPROVED)
        category = Category.objects.get(name="تفسير")
        self.assertIn(category, self.book.categories.all())

    def test_reject_suggestion(self):
        suggestion = CategorySuggestion.objects.create(
            book=self.book,
            suggested_by=self.user,
            name="مرفوض",
        )
        request = self._setup_request()
        queryset = CategorySuggestion.objects.filter(pk=suggestion.pk)
        self.modeladmin.reject_suggestions(request, queryset)
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, CategorySuggestionStatus.REJECTED)
        self.assertEqual(suggestion.resolved_by, self.admin_user)


class CategoryRequestAdminTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            email="admin@example.com",
            username="admin",
            password="pass",
        )
        self.user = User.objects.create_user(
            email="contrib@example.com",
            username="contrib",
            password="pass",
        )
        self.site = AdminSite()
        self.modeladmin = CategoryRequestAdmin(CategoryRequest, self.site)
        self.factory = RequestFactory()

    def _setup_request(self, method="post", data=None):
        request = self.factory.post("/admin/encyclopedia/categoryrequest/", data or {})
        request.user = self.admin_user
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    def test_approve_request_creates_category(self):
        category_request = CategoryRequest.objects.create(
            name="تاريخ إسلامي",
            suggested_by=self.user,
        )
        request = self._setup_request()
        queryset = CategoryRequest.objects.filter(pk=category_request.pk)
        self.modeladmin.approve_requests(request, queryset)
        category_request.refresh_from_db()
        self.assertEqual(category_request.status, CategoryRequestStatus.APPROVED)
        self.assertTrue(Category.objects.filter(name="تاريخ إسلامي").exists())

    def test_reject_request(self):
        category_request = CategoryRequest.objects.create(
            name="مرفوض",
            suggested_by=self.user,
        )
        request = self._setup_request()
        queryset = CategoryRequest.objects.filter(pk=category_request.pk)
        self.modeladmin.reject_requests(request, queryset)
        category_request.refresh_from_db()
        self.assertEqual(category_request.status, CategoryRequestStatus.REJECTED)
        self.assertEqual(category_request.resolved_by, self.admin_user)


class HierarchicalCategoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="contrib@example.com",
            username="contrib",
            password="pass",
        )

    def test_root_category_has_level_zero_and_id_path(self):
        root = Category.objects.create(name="اللغة العربية")
        self.assertEqual(root.level, 0)
        self.assertEqual(root.path, f"{root.pk}/")
        self.assertTrue(root.is_root)
        self.assertTrue(root.is_leaf)

    def test_nested_category_sets_level_and_path(self):
        root = Category.objects.create(name="اللغة العربية")
        child = Category.objects.create(name="النحو والصرف", parent=root)
        grandchild = Category.objects.create(name="الصرف", parent=child)
        self.assertEqual(child.level, 1)
        self.assertEqual(child.path, f"{root.pk}/{child.pk}/")
        self.assertEqual(grandchild.level, 2)
        self.assertEqual(grandchild.path, f"{root.pk}/{child.pk}/{grandchild.pk}/")
        self.assertFalse(root.is_leaf)
        self.assertTrue(grandchild.is_leaf)

    def test_ancestors_and_descendants(self):
        root = Category.objects.create(name="اللغة العربية")
        child = Category.objects.create(name="النحو", parent=root)
        grandchild = Category.objects.create(name="الإعراب", parent=child)
        other = Category.objects.create(name="عقيدة")
        self.assertEqual(list(grandchild.ancestors), [root, child])
        self.assertEqual(list(child.ancestors), [root])
        self.assertEqual(list(root.ancestors), [])
        self.assertIn(grandchild, set(child.descendants))
        self.assertIn(child, set(root.descendants))
        self.assertNotIn(other, set(root.descendants))

    def test_moving_category_updates_descendant_paths(self):
        root_a = Category.objects.create(name="أ")
        root_b = Category.objects.create(name="ب")
        child = Category.objects.create(name="ابن", parent=root_a)
        grandchild = Category.objects.create(name="حفيد", parent=child)
        child.parent = root_b
        child.save()
        child.refresh_from_db()
        grandchild.refresh_from_db()
        self.assertEqual(child.path, f"{root_b.pk}/{child.pk}/")
        self.assertEqual(grandchild.path, f"{root_b.pk}/{child.pk}/{grandchild.pk}/")
        self.assertEqual(child.level, 1)
        self.assertEqual(grandchild.level, 2)

    def test_cycle_prevention_self_parent(self):
        root = Category.objects.create(name="أ")
        with self.assertRaises(ValidationError):
            root.parent = root
            root.clean()

    def test_cycle_prevention_descendant_parent(self):
        root = Category.objects.create(name="أ")
        child = Category.objects.create(name="ابن", parent=root)
        grandchild = Category.objects.create(name="حفيد", parent=child)
        with self.assertRaises(ValidationError):
            root.parent = grandchild
            root.clean()

    def test_admin_form_prevents_descendant_parent(self):
        root = Category.objects.create(name="أ")
        child = Category.objects.create(name="ابن", parent=root)
        grandchild = Category.objects.create(name="حفيد", parent=child)
        form = CategoryAdminForm(instance=root, data={"name": root.name, "parent": grandchild.pk})
        self.assertFalse(form.is_valid())
        self.assertIn("parent", form.errors)

    def test_get_url_path_and_absolute_url(self):
        root = Category.objects.create(name="اللغة العربية")
        child = Category.objects.create(name="النحو والصرف", parent=root)
        expected_path = f"{root.slug}/{child.slug}"
        self.assertEqual(child.get_url_path(), expected_path)
        self.assertEqual(
            child.get_absolute_url(),
            reverse("category_detail", kwargs={"category_path": expected_path}),
        )


class HierarchicalCategoryDetailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="contrib@example.com",
            username="contrib",
            password="pass",
        )
        self.root = Category.objects.create(name="اللغة العربية")
        self.child = Category.objects.create(name="النحو", parent=self.root)
        self.grandchild = Category.objects.create(name="الإعراب", parent=self.child)
        self.book = create_book(title="كتاب النحو", author_name="نحوي")
        self.book.categories.add(self.grandchild)
        create_edition(
            book=self.book,
            publisher_name="دار الفكر",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )

    def test_root_category_detail_includes_subtree_books(self):
        response = self.client.get(
            reverse("category_detail", kwargs={"category_path": self.root.get_url_path()})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.book.title)
        self.assertIn(self.child, response.context["children"])

    def test_nested_category_detail_renders(self):
        response = self.client.get(
            reverse("category_detail", kwargs={"category_path": self.grandchild.get_url_path()})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.book.title)
        self.assertEqual(list(response.context["ancestors"]), [self.root, self.child])

    def test_invalid_ancestor_path_returns_404(self):
        response = self.client.get(
            reverse(
                "category_detail",
                kwargs={"category_path": f"{self.root.slug}/غير-صحيح/{self.child.slug}"},
            )
        )
        self.assertEqual(response.status_code, 404)


class HierarchicalCategoryListTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="contrib@example.com",
            username="contrib",
            password="pass",
        )
        self.root = Category.objects.create(name="اللغة العربية")
        self.child = Category.objects.create(name="النحو", parent=self.root)
        self.grandchild = Category.objects.create(name="الإعراب", parent=self.child)
        self.book = create_book(title="كتاب النحو", author_name="نحوي")
        self.book.categories.add(self.grandchild)
        create_edition(
            book=self.book,
            publisher_name="دار الفكر",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )

    def test_category_list_builds_tree_and_subtree_counts(self):
        response = self.client.get(reverse("category_list"))
        self.assertEqual(response.status_code, 200)
        roots = response.context["roots"]
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0].subtree_book_count, 1)
        self.assertEqual(len(list(roots[0].children.all())), 1)


class HierarchicalSearchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="contrib@example.com",
            username="contrib",
            password="pass",
        )
        self.root = Category.objects.create(name="اللغة العربية")
        self.child = Category.objects.create(name="النحو", parent=self.root)
        self.book = create_book(title="كتاب النحو", author_name="نحوي")
        self.book.categories.add(self.child)
        create_edition(
            book=self.book,
            publisher_name="دار الفكر",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )

    def test_search_filter_by_parent_includes_child_books(self):
        response = self.client.get(
            reverse("search"),
            {"category": self.root.slug},
        )
        self.assertContains(response, self.book.title)

    def test_search_by_parent_name_finds_child_category_books(self):
        response = self.client.get(
            reverse("search"),
            {"q": "اللغة العربية"},
        )
        self.assertContains(response, self.book.title)
