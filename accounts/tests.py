import io
import os

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from encyclopedia.models import (
    CategoryRequest,
    CategorySuggestion,
    EditionEditSuggestion,
    EditionStatus,
    NameRecord,
    NameRecordKind,
)
from encyclopedia.test_factories import create_book, create_edition

from .models import Profile

User = get_user_model()


def _build_image(ext="jpeg", size=(400, 400), color=(0, 113, 50)):
    image = io.BytesIO()
    img = Image.new("RGB", size, color)
    img.save(image, format=ext.upper() if ext != "jpg" else "JPEG")
    image.seek(0)
    content_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[ext]
    return InMemoryUploadedFile(
        image,
        field_name="avatar",
        name=f"avatar.{ext}",
        content_type=content_type,
        size=image.getbuffer().nbytes,
        charset=None,
    )


class ProfileModelTests(TestCase):
    def test_profile_created_on_user_creation(self):
        user = User.objects.create_user(email="u1@example.com", username="u1", password="pass")
        self.assertTrue(Profile.objects.filter(user=user).exists())

    def test_str(self):
        user = User.objects.create_user(email="u2@example.com", username="u2", password="pass")
        self.assertEqual(str(user.profile), "ملف u2")


class ProfileViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="viewer@example.com", username="viewer", password="pass"
        )
        self.target = User.objects.create_user(
            email="target@example.com", username="target", password="pass"
        )

    def test_public_profile_requires_no_login(self):
        response = self.client.get(reverse("public_profile", kwargs={"username": self.target.username}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.target.username)

    def test_public_profile_invalid_tab_defaults_to_editions(self):
        response = self.client.get(
            reverse("public_profile", kwargs={"username": self.target.username}) + "?tab=invalid"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["tab"], "editions")

    def test_profile_edit_requires_login(self):
        response = self.client.get(reverse("profile_edit"))
        self.assertEqual(response.status_code, 302)

    def test_profile_edit_updates_fields(self):
        self.client.login(email="viewer@example.com", password="pass")
        response = self.client.post(
            reverse("profile_edit"),
            {
                "bio": "نبذة قصيرة",
                "location": "الرياض",
                "website": "https://example.com",
                "twitter_x": "https://x.com/test",
                "telegram": "",
                "facebook": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.bio, "نبذة قصيرة")
        self.assertEqual(self.user.profile.location, "الرياض")

    def test_profile_edit_avatar_upload_and_resize(self):
        self.client.login(email="viewer@example.com", password="pass")
        image = _build_image("png", size=(800, 600))
        response = self.client.post(reverse("profile_edit"), {"avatar": image})
        self.assertEqual(response.status_code, 302)
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.avatar)
        with self.user.profile.avatar.open() as img_file:
            img = Image.open(img_file)
            self.assertEqual(img.size, (400, 400))

    def test_profile_edit_rejects_oversized_file(self):
        self.client.login(email="viewer@example.com", password="pass")
        # Random 1200×1200 noise produces a PNG well over 2 MB.
        image = io.BytesIO()
        img = Image.frombytes("RGB", (1200, 1200), os.urandom(1200 * 1200 * 3))
        img.save(image, format="PNG")
        image.seek(0)
        large = InMemoryUploadedFile(
            image,
            field_name="avatar",
            name="huge.png",
            content_type="image/png",
            size=image.getbuffer().nbytes,
            charset=None,
        )
        response = self.client.post(reverse("profile_edit"), {"avatar": large})
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "avatar", "حجم الصورة يجب ألا يتجاوز 2 ميجابايت.")

    def test_profile_edit_rejects_non_image(self):
        self.client.login(email="viewer@example.com", password="pass")
        bad = InMemoryUploadedFile(
            io.BytesIO(b"not an image"),
            field_name="avatar",
            name="bad.txt",
            content_type="text/plain",
            size=12,
            charset=None,
        )
        response = self.client.post(reverse("profile_edit"), {"avatar": bad})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)

    def test_account_settings_requires_login(self):
        response = self.client.get(reverse("account_settings"))
        self.assertEqual(response.status_code, 302)

    def test_account_settings_updates_username(self):
        self.client.login(email="viewer@example.com", password="pass")
        response = self.client.post(
            reverse("account_settings"),
            {"username": "viewer_new", "email": "viewer@example.com"},
        )
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "viewer_new")

    def test_old_profile_redirect(self):
        self.client.login(email="viewer@example.com", password="pass")
        response = self.client.get(reverse("profile_redirect"))
        self.assertRedirects(response, reverse("account_settings"))

    def test_public_profile_suggestions_tab(self):
        book = create_book(title="كتاب تجريبي", author_name="مؤلف تجريبي")
        edition = create_edition(
            book=book,
            publisher_name="دار تجريبية",
            status=EditionStatus.APPROVED,
            submitted_by=self.target,
        )
        EditionEditSuggestion.objects.create(
            edition=edition,
            suggested_by=self.target,
            year=2020,
        )
        response = self.client.get(
            reverse("public_profile", kwargs={"username": self.target.username}) + "?tab=suggestions"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, book.title)
        self.assertContains(response, "2020")


class MyContributionsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="contributor@example.com", username="contributor", password="pass"
        )
        self.other = User.objects.create_user(
            email="other@example.com", username="other", password="pass"
        )
        self.book = create_book(title="كتاب تجريبي", author_name="مؤلف تجريبي")

    def test_requires_login(self):
        response = self.client.get(reverse("my_contributions"))
        self.assertEqual(response.status_code, 302)

    def test_lists_user_editions(self):
        edition = create_edition(
            book=self.book,
            publisher_name="دار تجريبية",
            submitted_by=self.user,
        )
        self.client.login(email="contributor@example.com", password="pass")
        response = self.client.get(reverse("my_contributions"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.book.title)
        self.assertContains(response, edition.publishers.first().name)
        self.assertContains(response, "قيد المراجعة")
        self.assertEqual(response.context["pending_count"], 1)

    def test_hides_other_users_contributions(self):
        create_edition(
            book=self.book,
            publisher_name="دار أخرى",
            submitted_by=self.other,
        )
        self.client.login(email="contributor@example.com", password="pass")
        response = self.client.get(reverse("my_contributions"))
        self.assertNotContains(response, "دار أخرى")

    def test_lists_category_suggestions_and_requests(self):
        CategorySuggestion.objects.create(
            book=self.book,
            suggested_by=self.user,
            name="تصنيف مقترح",
        )
        CategoryRequest.objects.create(
            suggested_by=self.user,
            name="تصنيف جديد",
        )
        self.client.login(email="contributor@example.com", password="pass")
        response = self.client.get(reverse("my_contributions"))
        self.assertContains(response, "تصنيف مقترح")
        self.assertContains(response, "تصنيف جديد")

    def test_lists_name_records(self):
        NameRecord.objects.create(
            kind=NameRecordKind.AUTHOR,
            name="مؤلف جديد",
            submitted_by=self.user,
        )
        self.client.login(email="contributor@example.com", password="pass")
        response = self.client.get(reverse("my_contributions"))
        self.assertContains(response, "مؤلف جديد")
        self.assertContains(response, "مؤلف")

    def test_empty_state(self):
        self.client.login(email="contributor@example.com", password="pass")
        response = self.client.get(reverse("my_contributions"))
        self.assertContains(response, "لم تقدّم أي مساهمات بعد")
        self.assertContains(response, reverse("submit_edition"))

    def test_lists_edit_suggestions(self):
        edition = create_edition(
            book=self.book,
            publisher_name="دار تجريبية",
            status=EditionStatus.APPROVED,
            submitted_by=self.other,
        )
        EditionEditSuggestion.objects.create(
            edition=edition,
            suggested_by=self.user,
            year=2020,
        )
        self.client.login(email="contributor@example.com", password="pass")
        response = self.client.get(reverse("my_contributions"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.book.title)
        self.assertContains(response, "2020")
        self.assertEqual(response.context["pending_count"], 1)
