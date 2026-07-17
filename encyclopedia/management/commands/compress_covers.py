"""Management command to re-process existing edition cover images."""

import mimetypes

from django.core.files.base import ContentFile, File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from encyclopedia.image_utils import process_cover_image
from encyclopedia.models import Edition, EditionEditSuggestion


class Command(BaseCommand):
    help = "Re-compress and resize all existing edition cover images."

    def handle(self, *args, **options):
        processed = 0
        skipped = 0
        failed = 0

        for model in (Edition, EditionEditSuggestion):
            qs = model.objects.exclude(cover_image="").exclude(cover_image__isnull=True)

            for instance in qs.iterator():
                old_name = instance.cover_image.name
                try:
                    with default_storage.open(old_name) as original:
                        data = original.read()

                    raw_file = File(
                        ContentFile(data),
                        name=old_name.split("/")[-1],
                    )
                    raw_file.content_type = mimetypes.guess_type(old_name)[0] or ""

                    processed_file = process_cover_image(raw_file)
                    instance.cover_image.save(
                        processed_file.name,
                        processed_file,
                        save=False,
                    )
                    instance.save(update_fields=["cover_image"])

                    if old_name != instance.cover_image.name:
                        default_storage.delete(old_name)

                    processed += 1
                    self.stdout.write(f"OK: {old_name} -> {instance.cover_image.name}")
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    self.stderr.write(f"FAIL: {old_name}: {exc}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Processed: {processed}, skipped: {skipped}, failed: {failed}."
            )
        )
