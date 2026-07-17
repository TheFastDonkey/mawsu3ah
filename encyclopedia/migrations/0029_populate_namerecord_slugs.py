from django.db import migrations
from django.utils.text import slugify


def populate_namerecord_slugs(apps, schema_editor):
    """Fill blank slugs for NameRecord entries so detail URLs work."""
    NameRecord = apps.get_model("encyclopedia", "NameRecord")

    for record in NameRecord.objects.filter(slug=""):
        base = slugify(record.name, allow_unicode=True) or "entry"
        candidate = base
        counter = 1
        while NameRecord.objects.filter(slug=candidate).exclude(pk=record.pk).exists():
            counter += 1
            candidate = f"{base}-{counter}"
        record.slug = candidate
        record.save(update_fields=["slug"])


def reverse_populate(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("encyclopedia", "0028_namerecord_rejected_at_namerecord_rejected_by"),
    ]

    operations = [
        migrations.RunPython(
            populate_namerecord_slugs,
            reverse_code=reverse_populate,
        ),
    ]
