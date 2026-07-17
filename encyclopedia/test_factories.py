"""Test helpers for creating books and editions after the multi-creator refactor."""

from .models import (
    Book,
    BookAuthor,
    Edition,
    EditionEditor,
    EditionPublisher,
    NameRecord,
    NameRecordKind,
    NameRecordStatus,
)


def create_name_record(kind, name):
    record, _ = NameRecord.objects.get_or_create(
        kind=kind,
        name=name,
        defaults={"status": NameRecordStatus.APPROVED},
    )
    return record


def create_book(title, author_name, category=None):
    book = Book.objects.create(title=title)
    author = create_name_record(NameRecordKind.AUTHOR, author_name)
    BookAuthor.objects.create(book=book, name_record=author, order=0)
    if category is not None:
        book.categories.add(category)
    book.slug = book.generate_slug()
    book.save(update_fields=["slug"])
    return book


def create_edition(book, publisher_name, editor_name="", **kwargs):
    edition = Edition.objects.create(book=book, **kwargs)
    publisher = create_name_record(NameRecordKind.PUBLISHER, publisher_name)
    EditionPublisher.objects.create(edition=edition, name_record=publisher, order=0)
    if editor_name:
        editor = create_name_record(NameRecordKind.EDITOR, editor_name)
        EditionEditor.objects.create(edition=edition, name_record=editor, order=0)
    return edition
