"""Tests for edition cover image uploads."""

import json
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from encyclopedia.image_utils import process_cover_image, validate_cover_image
from encyclopedia.models import Category, Edition, EditionStatus
from encyclopedia.test_factories import create_book, create_edition

User = get_user_model()


def _image_file(name="cover.jpg", color=(0, 100, 0), fmt="JPEG", size=(100, 150)):
    image = Image.new("RGB", size, color)
    buf = BytesIO()
    image.save(buf, format=fmt)
    buf.seek(0)
    content_type = f"image/{fmt.lower()}"
    if fmt == "JPEG":
        content_type = "image/jpeg"
    return SimpleUploadedFile(name, buf.read(), content_type=content_type)


class EditionImageUploadTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="uploader@example.com",
            username="uploader",
            password="pass1234",
        )
        self.category = Category.objects.create(name="فقه")
        self.book = create_book(
            title="كتاب تجريبي",
            author_name="مؤلف",
            category=self.category,
        )

    def test_submit_edition_with_cover_image(self):
        self.client.login(email="uploader@example.com", password="pass1234")
        cover = _image_file()
        response = self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": self.book.pk,
                "publishers": json.dumps([{"name": "دار تجريبية"}]),
                "cover_image": cover,
                "is_best": "no",
            },
        )
        self.assertRedirects(response, reverse("home"))
        edition = Edition.objects.filter(
            edition_publishers__name_record__name="دار تجريبية"
        ).first()
        self.assertIsNotNone(edition)
        self.assertEqual(edition.status, EditionStatus.PENDING)
        self.assertTrue(edition.cover_image)
        self.assertIn("editions/covers/", edition.cover_image.path)

    def test_invalid_image_file_rejected(self):
        self.client.login(email="uploader@example.com", password="pass1234")
        fake = SimpleUploadedFile(
            "fake.jpg",
            b"this is not an image",
            content_type="image/jpeg",
        )
        response = self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": self.book.pk,
                "publishers": json.dumps([{"name": "دار أخرى"}]),
                "cover_image": fake,
                "is_best": "no",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "الملف ليس صورة صالحة")
        self.assertFalse(
            Edition.objects.filter(edition_publishers__name_record__name="دار أخرى").exists()
        )

    def test_unsupported_image_format_rejected(self):
        self.client.login(email="uploader@example.com", password="pass1234")
        gif = _image_file(name="cover.gif", fmt="GIF")
        gif.content_type = "image/gif"
        response = self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": self.book.pk,
                "publishers": json.dumps([{"name": "دار GIF"}]),
                "cover_image": gif,
                "is_best": "no",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "يُسمح فقط")
        self.assertFalse(
            Edition.objects.filter(edition_publishers__name_record__name="دار GIF").exists()
        )

    def test_author_detail_shows_first_cover_image(self):
        edition = create_edition(
            book=self.book,
            publisher_name="دار معروضة",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        edition.cover_image.save(
            "cover.jpg",
            _image_file(),
            save=True,
        )
        author = self.book.authors.first()
        response = self.client.get(
            reverse("author_detail", kwargs={"slug": author.slug})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, edition.cover_image.url)
        self.assertContains(response, "book-list__cover")

    def test_edition_detail_shows_cover_image(self):
        edition = create_edition(
            book=self.book,
            publisher_name="دار معروضة",
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        edition.cover_image.save(
            "cover.jpg",
            _image_file(),
            save=True,
        )
        response = self.client.get(
            reverse("edition_detail", kwargs={"book_slug": self.book.slug, "edition_public_id": edition.public_id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, edition.cover_image.url)

    def test_duplicate_confirmation_preserves_cover_image(self):
        create_edition(
            book=self.book,
            publisher_name="دار تجريبية",
            year=2020,
            status=EditionStatus.APPROVED,
            submitted_by=self.user,
        )
        self.client.login(email="uploader@example.com", password="pass1234")

        # First submission triggers duplicate confirmation.
        cover = _image_file()
        response = self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": self.book.pk,
                "publishers": json.dumps([{"name": "دار تجريبية"}]),
                "year": 2020,
                "cover_image": cover,
                "is_best": "no",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "طبعات مشابهة موجودة")

        # Confirm override; the cover image should be preserved from temporary storage.
        temp_path = response.context.get("temp_cover_image")
        self.assertTrue(temp_path)
        response = self.client.post(
            reverse("submit_edition"),
            {
                "book_action": "existing",
                "existing_book": self.book.pk,
                "publishers": json.dumps([{"name": "دار تجريبية"}]),
                "year": 2020,
                "confirm_override": "1",
                "temp_cover_image": temp_path,
                "is_best": "no",
            },
        )
        self.assertRedirects(response, reverse("home"))
        edition = Edition.objects.filter(
            book=self.book,
            edition_publishers__name_record__name="دار تجريبية",
            status=EditionStatus.PENDING,
        ).latest("pk")
        self.assertTrue(edition.cover_image)


class CoverImageUtilsTests(TestCase):
    def test_validate_accepts_valid_small_image(self):
        image = _image_file()
        # Should not raise.
        validate_cover_image(image)

    def test_validate_rejects_huge_dimensions(self):
        image = _image_file(name="huge.jpg", size=(3000, 3000))
        with self.assertRaises(ValidationError):
            validate_cover_image(image)

    def test_validate_rejects_unsupported_format(self):
        image = _image_file(name="cover.gif", fmt="GIF")
        image.content_type = "image/gif"
        with self.assertRaises(ValidationError):
            validate_cover_image(image)

    def test_process_resizes_large_image_to_fit(self):
        image = _image_file(name="big.jpg", size=(1600, 2400))
        processed = process_cover_image(image)

        with Image.open(processed) as img:
            width, height = img.size

        self.assertLessEqual(width, 800)
        self.assertLessEqual(height, 1200)
        self.assertEqual(width, 800)
        self.assertEqual(height, 1200)

    def test_process_preserves_aspect_ratio(self):
        image = _image_file(name="wide.jpg", size=(2000, 1500))
        processed = process_cover_image(image)

        with Image.open(processed) as img:
            width, height = img.size

        self.assertLessEqual(width, 800)
        self.assertLessEqual(height, 1200)
        self.assertEqual(width, 800)
        self.assertEqual(height, 600)

    def test_process_does_not_upscale_small_image(self):
        image = _image_file(name="small.jpg", size=(100, 150))
        processed = process_cover_image(image)

        with Image.open(processed) as img:
            width, height = img.size

        self.assertEqual(width, 100)
        self.assertEqual(height, 150)

    def test_process_output_name_starts_with_cover_and_has_allowed_extension(self):
        image = _image_file(name="input.jpg")
        processed = process_cover_image(image)
        self.assertTrue(processed.name.startswith("cover_"))
        self.assertTrue(processed.name.endswith(".jpg"))

    def test_process_keeps_png_transparency(self):
        image = _image_file(name="input.png", fmt="PNG", size=(100, 150))
        image.content_type = "image/png"
        # Make it RGBA.
        rgba = Image.new("RGBA", (100, 150), (0, 100, 0, 128))
        buf = BytesIO()
        rgba.save(buf, format="PNG")
        buf.seek(0)
        image = SimpleUploadedFile("input.png", buf.read(), content_type="image/png")

        processed = process_cover_image(image)
        self.assertTrue(processed.name.endswith(".png"))

        with Image.open(processed) as img:
            self.assertIn(img.mode, ("RGBA", "P"))

    def test_process_normalizes_exif_orientation(self):
        # Create a portrait image that declares a 90-degree rotation.
        img = Image.new("RGB", (100, 150), color=(0, 100, 0))
        img.exif = Image.Exif()
        img.exif[0x0112] = 6  # Rotate 90 CCW.
        buf = BytesIO()
        img.save(buf, format="JPEG", exif=img.exif)
        buf.seek(0)
        image = SimpleUploadedFile("oriented.jpg", buf.read(), content_type="image/jpeg")

        processed = process_cover_image(image)

        with Image.open(processed) as img:
            width, height = img.size

        # Orientation normalized -> landscape dimensions.
        self.assertEqual(width, 150)
        self.assertEqual(height, 100)
