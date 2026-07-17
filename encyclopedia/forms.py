import json
import re
from datetime import datetime

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from .image_utils import process_cover_image, validate_cover_image
from .models import (
    Book,
    BookAuthor,
    BookCategory,
    Category,
    CategorySuggestionStatus,
    Edition,
    EditionBookLink,
    EditionBookLinkSuggestion,
    EditionEditor,
    EditionEditSuggestion,
    EditionPublisher,
    EditionRelation,
    EditionRelationSuggestion,
    EditionStatus,
    NameRecord,
    NameRecordKind,
    NameRecordStatus,
    Review,
    ReviewReport,
)


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ["body"]
        labels = {"body": "مراجعتك"}
        widgets = {
            "body": forms.Textarea(attrs={"rows": 3, "placeholder": "اكتب مراجعتك لهذه الطبعة…"}),
        }

    def clean_body(self):
        body = self.cleaned_data.get("body", "")
        body = strip_tags(body).strip()
        if not body:
            raise ValidationError("المراجعة لا يمكن أن تكون فارغة.")
        return body


class ReviewReplyForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ["body"]
        labels = {"body": "ردك"}
        widgets = {
            "body": forms.Textarea(attrs={"rows": 2, "placeholder": "اكتب ردك…"}),
        }

    def __init__(self, *args, edition=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.edition = edition

    def clean_body(self):
        body = self.cleaned_data.get("body", "")
        body = strip_tags(body).strip()
        if not body:
            raise ValidationError("الرد لا يمكن أن يكون فارغاً.")
        return body

    def clean(self):
        cleaned = super().clean()
        parent = self.instance.parent if self.instance.pk else None
        if parent and self.edition and parent.edition_id != self.edition.pk:
            raise ValidationError("لا يمكن الرد على مراجعة من طبعة أخرى.")
        return cleaned


class ReviewReportForm(forms.ModelForm):
    class Meta:
        model = ReviewReport
        fields = ["reason", "details"]
        labels = {
            "reason": "سبب البلاغ",
            "details": "تفاصيل إضافية",
        }
        widgets = {
            "reason": forms.Select(attrs={"required": "required", "class": "c-input"}),
            "details": forms.Textarea(
                attrs={
                    "rows": 2,
                    "placeholder": "أضف تفاصيل (اختياري)…",
                    "class": "c-input",
                }
            ),
        }


class CategorySuggestionForm(forms.Form):
    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        label="التصنيف",
        widget=forms.HiddenInput,
    )

    def __init__(self, *args, book=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.book = book

    def clean_category(self):
        category = self.cleaned_data.get("category")
        if not category:
            raise ValidationError("يرجى اختيار تصنيف موجود.")
        return category

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get("category")
        if self.book and category:
            with transaction.atomic():
                try:
                    book = Book.objects.select_for_update().get(pk=self.book.pk)
                except Book.DoesNotExist as err:
                    raise ValidationError("الكتاب غير موجود.") from err
                if book.categories.filter(pk=category.pk).exists():
                    raise ValidationError("هذا الكتاب مُدرج بالفعل ضمن هذا التصنيف.")
                if book.category_suggestions.filter(
                    final_category=category,
                    status=CategorySuggestionStatus.PENDING,
                ).exists():
                    raise ValidationError("هذا التصنيف مُقترح بالفعل لهذا الكتاب.")
        return cleaned


class CategoryRequestForm(forms.Form):
    name = forms.CharField(
        max_length=200,
        label="اسم التصنيف الجديد",
        widget=forms.TextInput(
            attrs={
                "class": "c-input",
                "placeholder": "مثال: تاريخ إسلامي",
                "autocomplete": "off",
            }
        ),
    )

    def clean_name(self):
        name = self.cleaned_data.get("name", "").strip()
        if not name:
            raise ValidationError("يرجى إدخال اسم التصنيف.")
        if Category.objects.filter(name__iexact=name).exists():
            raise ValidationError("يوجد تصنيف بهذا الاسم. اختره من القائمة.")
        return name


class EditionSubmissionForm(forms.Form):
    BOOK_ACTION_CHOICES = [
        ("existing", "اختر كتاباً موجوداً"),
        ("new", "أضف كتاباً جديداً"),
    ]

    book_action = forms.ChoiceField(
        choices=BOOK_ACTION_CHOICES,
        widget=forms.RadioSelect,
        initial="existing",
        label="الكتاب",
    )
    existing_book = forms.ModelChoiceField(
        queryset=Book.objects.all(),
        required=False,
        label="الكتاب الموجود",
        widget=forms.HiddenInput,
    )
    new_book_title = forms.CharField(
        max_length=500,
        required=False,
        label="عنوان الكتاب الجديد",
    )
    new_book_authors = forms.CharField(
        required=False,
        label="مؤلفو الكتاب الجديد",
        widget=forms.HiddenInput,
    )
    new_book_author_search = forms.CharField(
        max_length=300,
        required=False,
        label="إضافة مؤلف",
        help_text="اكتب الاسم كاملاً ثم اختر من القائمة. يمكنك إضافة أكثر من مؤلف.",
    )
    new_book_categories = forms.CharField(
        required=False,
        label="تصنيفات الكتاب",
        help_text="اختر تصنيفاً واحداً على الأقل. ابدأ بالكتابة ثم اختر من القائمة.",
        widget=forms.HiddenInput,
    )
    publishers = forms.CharField(
        required=False,
        label="الناشرون",
        widget=forms.HiddenInput,
    )
    publisher_search = forms.CharField(
        max_length=300,
        required=False,
        label="إضافة ناشر",
        help_text="اكتب اسم الناشر ثم اختر من القائمة. يمكنك إضافة أكثر من ناشر.",
    )
    year = forms.IntegerField(
        required=False,
        min_value=1000,
        max_value=2100,
        label="سنة النشر",
    )
    editors = forms.CharField(
        required=False,
        label="المحققون",
        widget=forms.HiddenInput,
    )
    editor_search = forms.CharField(
        max_length=300,
        required=False,
        label="إضافة محقق",
        help_text="اكتب الاسم كاملاً ثم اختر من القائمة. يمكنك إضافة أكثر من اسم.",
    )
    volumes = forms.CharField(
        max_length=40,
        required=False,
        label="المجلدات",
    )
    page_count = forms.IntegerField(
        required=False,
        min_value=1,
        label="عدد الصفحات",
    )
    city = forms.CharField(
        max_length=200,
        required=False,
        label="مدينة النشر",
        help_text="اختياري. تُستخدم فقط عند وجود أكثر من ناشر؛ وإلا تُعرض مدينة الناشر.",
    )
    cover_image = forms.ImageField(
        required=False,
        label="صورة الغلاف",
        help_text="اختياري. JPEG أو PNG أو WebP، بحد أقصى 2 ميجابايت.",
        error_messages={
            "invalid_image": "الملف ليس صورة صالحة.",
        },
    )
    is_best = forms.TypedChoiceField(
        choices=[("yes", "نعم"), ("no", "لا")],
        coerce=lambda x: x == "yes",
        required=True,
        label="هل هذه أفضل طبعة؟",
        help_text="اختر 'نعم' إذا كانت هذه أفضل طبعة معروفة للكتاب.",
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_book_author_search"].widget.attrs.update(
            {
                "hx-get": reverse("author_suggestions"),
                "hx-trigger": "keyup changed delay:300ms",
                "hx-target": "#id_new_book_author-suggestions",
                "hx-indicator": "#id_new_book_author-indicator",
                "autocomplete": "off",
            }
        )
        self.fields["editor_search"].widget.attrs.update(
            {
                "hx-get": reverse("editor_suggestions"),
                "hx-trigger": "keyup changed delay:300ms",
                "hx-target": "#id_editor-suggestions",
                "hx-indicator": "#id_editor-indicator",
                "autocomplete": "off",
            }
        )
        self.fields["publisher_search"].widget.attrs.update(
            {
                "hx-get": reverse("publisher_suggestions"),
                "hx-trigger": "keyup changed delay:300ms",
                "hx-target": "#id_publisher-suggestions",
                "hx-indicator": "#id_publisher-indicator",
                "autocomplete": "off",
            }
        )

    def _parse_name_json(self, raw):
        """Parse a hidden JSON field into a deduplicated list of name strings."""
        raw = (raw or "").strip()
        if not raw:
            return []
        try:
            items = json.loads(raw)
        except ValueError:
            raise ValidationError("بيانات الأسماء غير صالحة.") from None
        if not isinstance(items, list):
            raise ValidationError("بيانات الأسماء غير صالحة.")
        seen = set()
        names = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
        return names

    def clean_volumes(self):
        volumes = self.cleaned_data.get("volumes", "")
        return re.sub(r"[\s\-]", "", volumes)

    def clean_year(self):
        year = self.cleaned_data.get("year")
        if year and year > datetime.now().year + 1:
            raise ValidationError("سنة النشر لا يمكن أن تكون في المستقبل البعيد.")
        return year

    def clean_city(self):
        return self.cleaned_data.get("city", "").strip()

    def clean_new_book_authors(self):
        return self._parse_name_json(self.cleaned_data.get("new_book_authors", ""))

    def clean_publishers(self):
        names = self._parse_name_json(self.cleaned_data.get("publishers", ""))
        if not names:
            raise ValidationError("يرجى إدخال ناشر واحد على الأقل.")
        return names

    def clean_editors(self):
        return self._parse_name_json(self.cleaned_data.get("editors", ""))

    def clean_cover_image(self):
        image = self.cleaned_data.get("cover_image")
        if image:
            validate_cover_image(image)
        return image

    def clean_new_book_categories(self):
        raw = self.cleaned_data.get("new_book_categories", "").strip()
        if not raw:
            return []
        try:
            items = json.loads(raw)
        except ValueError:
            raise ValidationError("بيانات التصنيفات غير صالحة.") from None
        if not isinstance(items, list):
            raise ValidationError("بيانات التصنيفات غير صالحة.")
        seen = set()
        unique_items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            pk = item.get("id")
            if pk in seen:
                continue
            seen.add(pk)
            unique_items.append(item)
        ids = [item["id"] for item in unique_items if isinstance(item.get("id"), int)]
        categories = list(Category.objects.filter(pk__in=ids))
        if len(categories) != len(ids):
            raise ValidationError("أحد التصنيفات المختارة غير موجود.")
        category_map = {category.pk: category for category in categories}
        return [category_map[item["id"]] for item in unique_items if item["id"] in category_map]

    def clean(self):
        cleaned = super().clean()
        action = cleaned.get("book_action")

        if action == "existing":
            if not cleaned.get("existing_book"):
                self.add_error("existing_book", "يرجى اختيار كتاب موجود.")
        elif action == "new":
            if not cleaned.get("new_book_title"):
                self.add_error("new_book_title", "يرجى إدخال عنوان الكتاب.")
            authors = cleaned.get("new_book_authors") or []
            if not authors:
                self.add_error("new_book_authors", "يرجى إدخال مؤلف واحد على الأقل.")
            categories = cleaned.get("new_book_categories") or []
            if not categories:
                self.add_error("new_book_categories", "يرجى اختيار تصنيف واحد على الأقل.")
            if cleaned.get("new_book_title") and authors and Book.objects.filter(
                title=cleaned["new_book_title"],
                authors__name__in=authors,
            ).exists():
                raise ValidationError(
                    "يوجد كتاب بنفس العنوان وأحد مؤلفيه. اختره من القائمة أو غيّر البيانات."
                )

        return cleaned

    def get_book(self):
        """Return an existing or in-memory Book."""
        cleaned = self.cleaned_data
        if cleaned["book_action"] == "existing":
            return cleaned["existing_book"]
        return Book(title=cleaned["new_book_title"])

    def _assign_book_categories(self, book):
        """Persist categories for a new book in the order selected."""
        categories = list(self.cleaned_data.get("new_book_categories", []))
        BookCategory.objects.filter(book=book).delete()
        for i, category in enumerate(categories):
            BookCategory.objects.create(book=book, category=category, order=i)

    def _ensure_name_records(self, submitter, authors, publishers, editors):
        """Create NameRecord rows for names introduced by this submission.

        Existing approved/pending records are left untouched. Rejected records
        are re-opened as pending so admins can review them again. When the
        submitter is an expert, newly created or reopened records are approved
        immediately.
        """
        auto_approve = bool(submitter and getattr(submitter, "is_expert", False))

        def ensure(kind, name):
            name = name.strip()
            if not name:
                return
            defaults = {
                "status": (NameRecordStatus.APPROVED if auto_approve else NameRecordStatus.PENDING),
                "submitted_by": submitter,
            }
            if auto_approve:
                defaults["approved_by"] = submitter
                defaults["approved_at"] = timezone.now()
            record, _ = NameRecord.objects.get_or_create(
                kind=kind,
                name=name,
                defaults=defaults,
            )
            if record.status == NameRecordStatus.REJECTED:
                if auto_approve:
                    record.status = NameRecordStatus.APPROVED
                    record.approved_by = submitter
                    record.approved_at = timezone.now()
                else:
                    record.status = NameRecordStatus.PENDING
                record.submitted_by = submitter
                record.save(
                    update_fields=[
                        "status",
                        "submitted_by",
                        "approved_by",
                        "approved_at",
                    ]
                )

        for name in authors:
            ensure(NameRecordKind.AUTHOR, name)
        for name in publishers:
            ensure(NameRecordKind.PUBLISHER, name)
        for name in editors:
            ensure(NameRecordKind.EDITOR, name)

    def _name_records(self, kind, names):
        """Return NameRecord objects for the given kind and sorted names."""
        names = sorted(set(names))
        records = []
        for name in names:
            record = NameRecord.objects.filter(kind=kind, name=name).first()
            if record is None:
                record = NameRecord.objects.create(
                    kind=kind,
                    name=name,
                    status=NameRecordStatus.APPROVED,
                )
            records.append(record)
        return records

    def _assign_book_authors(self, book, authors):
        """Persist authors for a new book in alphabetical order."""
        records = self._name_records(NameRecordKind.AUTHOR, authors)
        BookAuthor.objects.filter(book=book).delete()
        for i, record in enumerate(records):
            BookAuthor.objects.create(book=book, name_record=record, order=i)

    def _assign_edition_publishers(self, edition, publishers):
        """Persist publishers for an edition in alphabetical order."""
        records = self._name_records(NameRecordKind.PUBLISHER, publishers)
        EditionPublisher.objects.filter(edition=edition).delete()
        for i, record in enumerate(records):
            EditionPublisher.objects.create(edition=edition, name_record=record, order=i)

    def _assign_edition_editors(self, edition, editors):
        """Persist editors for an edition in alphabetical order."""
        if not editors:
            EditionEditor.objects.filter(edition=edition).delete()
            return
        records = self._name_records(NameRecordKind.EDITOR, editors)
        EditionEditor.objects.filter(edition=edition).delete()
        for i, record in enumerate(records):
            EditionEditor.objects.create(edition=edition, name_record=record, order=i)

    def get_edition(self, submitter):
        """Return an in-memory Edition for duplicate checking."""
        book = self.get_book()
        cleaned = self.cleaned_data
        return Edition(
            book=book,
            year=cleaned.get("year"),
            page_count=cleaned.get("page_count"),
            city=cleaned.get("city", ""),
            volumes=cleaned.get("volumes", ""),
            cover_image=cleaned.get("cover_image"),
            status=EditionStatus.PENDING,
            is_best=cleaned.get("is_best", False),
            submitted_by=submitter,
        )

    def find_duplicates(self, edition):
        """Find approved editions that may duplicate the given edition."""
        book = edition.book
        if book.pk is None:
            return Edition.objects.none()

        publishers = self.cleaned_data.get("publishers", [])
        qs = Edition.objects.filter(book=book, status=EditionStatus.APPROVED)
        volumes = edition.volumes.strip()
        if volumes:
            return qs.filter(volumes=volumes)

        year = edition.year
        if year:
            return qs.filter(publishers__name__in=publishers, year=year).distinct()

        return qs.filter(publishers__name__in=publishers, year__isnull=True).distinct()

    def save(self, submitter):
        """Save the book (if new) and edition, returning the Edition."""
        book = self.get_book()
        is_new_book = book.pk is None
        authors = (
            self.cleaned_data.get("new_book_authors", [])
            if self.cleaned_data["book_action"] == "new"
            else []
        )
        publishers = self.cleaned_data["publishers"]
        editors = self.cleaned_data.get("editors", [])

        if is_new_book:
            book.save()
            self._assign_book_categories(book)
            self._ensure_name_records(submitter, authors, publishers, editors)
            self._assign_book_authors(book, authors)
            book.slug = book.generate_slug()
            book.save(update_fields=["slug"])
        else:
            self._ensure_name_records(submitter, [], publishers, editors)

        edition = self.get_edition(submitter)
        edition.book = book

        raw_cover = self.cleaned_data.get("cover_image")
        if raw_cover:
            edition.cover_image = process_cover_image(raw_cover)

        edition.save()
        self._assign_edition_publishers(edition, publishers)
        self._assign_edition_editors(edition, editors)

        return edition


class EditionEditSuggestionForm(forms.ModelForm):
    proposed_publishers = forms.CharField(
        required=False,
        label="الناشرون",
        widget=forms.HiddenInput,
    )
    publisher_search = forms.CharField(
        max_length=300,
        required=False,
        label="إضافة ناشر",
        help_text="اكتب اسم الناشر ثم اختر من القائمة. يمكنك إضافة أكثر من ناشر.",
    )
    proposed_editors = forms.CharField(
        required=False,
        label="المحققون",
        widget=forms.HiddenInput,
    )
    editor_search = forms.CharField(
        max_length=300,
        required=False,
        label="إضافة محقق",
        help_text="اكتب الاسم كاملاً ثم اختر من القائمة. يمكنك إضافة أكثر من اسم.",
    )
    reason = forms.CharField(
        required=False,
        label="سبب التعديل (اختياري)",
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "اشرح التعديل المقترح باختصار…"}),
    )

    class Meta:
        model = EditionEditSuggestion
        fields = [
            "year",
            "page_count",
            "city",
            "volumes",
            "cover_image",
        ]
        labels = {
            "year": "سنة النشر",
            "page_count": "عدد الصفحات",
            "city": "مدينة النشر",
            "volumes": "المجلدات",
            "cover_image": "صورة الغلاف",
        }
        help_texts = {
            "cover_image": "اختياري. JPEG أو PNG أو WebP، بحد أقصى 2 ميجابايت.",
            "city": "اختياري. عند وجود ناشر واحد يُحدّث مدينة الناشر؛ وعند وجود عدة ناشرين يُخزّن يدوياً لهذه الطبعة.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["publisher_search"].widget.attrs.update(
            {
                "hx-get": reverse("publisher_suggestions"),
                "hx-trigger": "keyup changed delay:300ms",
                "hx-target": "#id_publisher-suggestions",
                "hx-indicator": "#id_publisher-indicator",
                "autocomplete": "off",
            }
        )
        self.fields["editor_search"].widget.attrs.update(
            {
                "hx-get": reverse("editor_suggestions"),
                "hx-trigger": "keyup changed delay:300ms",
                "hx-target": "#id_editor-suggestions",
                "hx-indicator": "#id_editor-indicator",
                "autocomplete": "off",
            }
        )

    def _parse_name_json(self, raw):
        """Parse a hidden JSON field into a deduplicated list of name strings."""
        raw = (raw or "").strip()
        if not raw:
            return []
        try:
            items = json.loads(raw)
        except ValueError:
            raise ValidationError("بيانات الأسماء غير صالحة.") from None
        if not isinstance(items, list):
            raise ValidationError("بيانات الأسماء غير صالحة.")
        seen = set()
        names = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
        return names

    def clean_proposed_publishers(self):
        return self._parse_name_json(self.cleaned_data.get("proposed_publishers", ""))

    def clean_proposed_editors(self):
        return self._parse_name_json(self.cleaned_data.get("proposed_editors", ""))

    def clean_volumes(self):
        volumes = self.cleaned_data.get("volumes", "")
        return re.sub(r"[\s\-]", "", volumes)

    def clean_year(self):
        year = self.cleaned_data.get("year")
        if year and year > datetime.now().year + 1:
            raise ValidationError("سنة النشر لا يمكن أن تكون في المستقبل البعيد.")
        return year

    def clean_city(self):
        return self.cleaned_data.get("city", "").strip()

    def clean_cover_image(self):
        image = self.cleaned_data.get("cover_image")
        if image:
            validate_cover_image(image)
        return image

    def _ensure_name_records(self, submitter, publishers, editors):
        """Create NameRecord rows for any newly suggested names.

        Expert submitters get their name records approved immediately.
        """
        auto_approve = bool(submitter and getattr(submitter, "is_expert", False))

        def ensure(kind, name):
            name = name.strip()
            if not name:
                return
            defaults = {
                "status": (NameRecordStatus.APPROVED if auto_approve else NameRecordStatus.PENDING),
                "submitted_by": submitter,
            }
            if auto_approve:
                defaults["approved_by"] = submitter
                defaults["approved_at"] = timezone.now()
            record, _ = NameRecord.objects.get_or_create(
                kind=kind,
                name=name,
                defaults=defaults,
            )
            if record.status == NameRecordStatus.REJECTED:
                if auto_approve:
                    record.status = NameRecordStatus.APPROVED
                    record.approved_by = submitter
                    record.approved_at = timezone.now()
                else:
                    record.status = NameRecordStatus.PENDING
                record.submitted_by = submitter
                record.save(
                    update_fields=[
                        "status",
                        "submitted_by",
                        "approved_by",
                        "approved_at",
                    ]
                )

        for name in publishers:
            ensure(NameRecordKind.PUBLISHER, name)
        for name in editors:
            ensure(NameRecordKind.EDITOR, name)

    def save(self, commit=True):
        suggestion = super().save(commit=False)
        suggestion.proposed_publishers = self.cleaned_data.get("proposed_publishers", [])
        suggestion.proposed_editors = self.cleaned_data.get("proposed_editors", [])

        raw_cover = self.cleaned_data.get("cover_image")
        if raw_cover:
            suggestion.cover_image = process_cover_image(raw_cover)

        if commit:
            suggestion.save()
        return suggestion


class EditionBookLinkSuggestionForm(forms.ModelForm):
    edition_search = forms.CharField(
        max_length=300,
        required=False,
        label="الطبعة",
        help_text="ابدأ بعنوان الكتاب أو الناشر أو سنة النشر ثم اختر من القائمة.",
    )

    class Meta:
        model = EditionBookLinkSuggestion
        fields = ["edition", "role", "reason"]
        widgets = {
            "edition": forms.HiddenInput(),
            "reason": forms.Textarea(attrs={"rows": 2, "placeholder": "اشرح سبب الربط باختصار…"}),
        }
        labels = {
            "edition": "الطبعة",
            "role": "العلاقة",
            "reason": "سبب الربط (اختياري)",
        }

    def __init__(self, *args, book=None, **kwargs):
        self.book = book
        super().__init__(*args, **kwargs)
        self.fields["edition_search"].widget.attrs.update(
            {
                "hx-get": reverse("edition_suggestions"),
                "hx-trigger": "keyup changed delay:300ms",
                "hx-target": "#id_edition-suggestions",
                "hx-indicator": "#id_edition-indicator",
                "autocomplete": "off",
                "placeholder": "مثال: شرح بانت سعاد دار سعد الدين",
            }
        )

    def clean_edition(self):
        edition = self.cleaned_data.get("edition")
        if not edition:
            raise ValidationError("يرجى اختيار طبعة من القائمة.")
        if edition.book_id == self.book.pk:
            raise ValidationError("هذه طبعة أصلية لهذا الكتاب.")
        with transaction.atomic():
            try:
                book = Book.objects.select_for_update().get(pk=self.book.pk)
            except Book.DoesNotExist as err:
                raise ValidationError("الكتاب غير موجود.") from err
            if EditionBookLink.objects.filter(edition=edition, book=book).exists():
                raise ValidationError("هذه الطبعة مرتبطة بالفعل بهذا الكتاب.")
            if EditionBookLinkSuggestion.objects.filter(
                edition=edition, book=book, status="pending"
            ).exists():
                raise ValidationError("يوجد اقتراح ربط قيد المراجعة لهذه الطبعة.")
        return edition

    def save(self, commit=True):
        with transaction.atomic():
            suggestion = super().save(commit=False)
            suggestion.book = self.book
            if commit:
                try:
                    suggestion.save()
                except Exception:
                    raise
        return suggestion


class EditionRelationSuggestionForm(forms.ModelForm):
    TARGET_MODE_CHOICES = [
        ("existing", "اختر طبعة موجودة"),
        ("new", "أضف طبعة جديدة"),
    ]

    target_mode = forms.ChoiceField(
        choices=TARGET_MODE_CHOICES,
        widget=forms.RadioSelect,
        initial="existing",
        label="نوع الطبعة",
    )
    target_search = forms.CharField(
        max_length=300,
        required=False,
        label="الطبعة",
        help_text="ابدأ بعنوان الكتاب أو الناشر أو سنة النشر ثم اختر من القائمة.",
    )
    new_publishers = forms.CharField(
        required=False,
        label="الناشرون",
        widget=forms.HiddenInput(),
    )
    publisher_search = forms.CharField(
        max_length=300,
        required=False,
        label="إضافة ناشر",
        help_text="اكتب اسم الناشر ثم اختر من القائمة. يمكنك إضافة أكثر من ناشر.",
    )
    new_editors = forms.CharField(
        required=False,
        label="المحققون",
        widget=forms.HiddenInput(),
    )
    editor_search = forms.CharField(
        max_length=300,
        required=False,
        label="إضافة محقق",
        help_text="اكتب الاسم كاملاً ثم اختر من القائمة. يمكنك إضافة أكثر من اسم.",
    )
    new_year = forms.IntegerField(
        required=False,
        min_value=1000,
        max_value=2100,
        label="سنة النشر",
    )
    new_page_count = forms.IntegerField(
        required=False,
        min_value=1,
        label="عدد الصفحات",
    )
    new_city = forms.CharField(
        max_length=200,
        required=False,
        label="مدينة النشر",
    )
    new_volumes = forms.CharField(
        max_length=40,
        required=False,
        label="المجلدات",
    )

    class Meta:
        model = EditionRelationSuggestion
        fields = ["target", "kind", "reason"]
        widgets = {
            "target": forms.HiddenInput(),
            "reason": forms.Textarea(attrs={"rows": 2, "placeholder": "اشرح سبب الربط باختصار…"}),
        }
        labels = {
            "target": "الطبعة",
            "kind": "نوع العلاقة",
            "reason": "السبب (اختياري)",
        }

    def __init__(self, *args, source=None, **kwargs):
        self.source = source
        super().__init__(*args, **kwargs)
        hx_url = reverse("edition_suggestions")
        if source:
            hx_url += f"?book={source.book.pk}&exclude={source.public_id}&field_id=id_target&text_field_id=id_target_search"
        self.fields["target_search"].widget.attrs.update(
            {
                "hx-get": hx_url,
                "hx-trigger": "keyup changed delay:300ms",
                "hx-target": "#id_target-suggestions",
                "hx-indicator": "#id_target-indicator",
                "autocomplete": "off",
                "placeholder": "مثال: دار ابن كثير 2015",
            }
        )
        self.fields["publisher_search"].widget.attrs.update(
            {
                "hx-get": reverse("publisher_suggestions") + "?field_id=id_publisher_search",
                "hx-trigger": "keyup changed delay:300ms",
                "hx-target": "#id_publisher-suggestions",
                "hx-indicator": "#id_publisher-indicator",
                "autocomplete": "off",
                "placeholder": "مثال: دار ابن كثير",
            }
        )
        self.fields["editor_search"].widget.attrs.update(
            {
                "hx-get": reverse("editor_suggestions") + "?field_id=id_editor_search",
                "hx-trigger": "keyup changed delay:300ms",
                "hx-target": "#id_editor-suggestions",
                "hx-indicator": "#id_editor-indicator",
                "autocomplete": "off",
                "placeholder": "مثال: سناء ناهص",
            }
        )

    def _parse_name_json(self, raw):
        raw = (raw or "").strip()
        if not raw:
            return []
        try:
            items = json.loads(raw)
        except ValueError:
            raise ValidationError("بيانات الأسماء غير صالحة.") from None
        if not isinstance(items, list):
            raise ValidationError("بيانات الأسماء غير صالحة.")
        seen = set()
        names = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
        return names

    def clean_new_publishers(self):
        return self._parse_name_json(self.cleaned_data.get("new_publishers", ""))

    def clean_new_editors(self):
        return self._parse_name_json(self.cleaned_data.get("new_editors", ""))

    def clean_new_volumes(self):
        volumes = self.cleaned_data.get("new_volumes", "")
        return re.sub(r"[\s\-]", "", volumes)

    def clean_new_year(self):
        year = self.cleaned_data.get("new_year")
        if year and year > datetime.now().year + 1:
            raise ValidationError("سنة النشر لا يمكن أن تكون في المستقبل البعيد.")
        return year

    def clean_new_city(self):
        return self.cleaned_data.get("new_city", "").strip()

    def clean_target(self):
        return self.cleaned_data.get("target")

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("target_mode")
        if not self.source:
            raise ValidationError("الطبعة الأصل غير محددة.")

        with transaction.atomic():
            try:
                source = Edition.objects.select_for_update().get(pk=self.source.pk)
            except Edition.DoesNotExist as err:
                raise ValidationError("الطبعة الأصل غير موجودة.") from err

            if mode == "existing":
                target = cleaned.get("target")
                if not target:
                    self.add_error("target", "يرجى اختيار طبعة من القائمة.")
                    return cleaned
                if target.pk == source.pk:
                    self.add_error("target", "لا يمكن ربط الطبعة بنفسها.")
                if target.book_id != source.book_id:
                    self.add_error("target", "يجب أن تكون الطبعة المختارة لنفس الكتاب.")
                if EditionRelation.objects.filter(source=source, target=target).exists():
                    self.add_error("target", "هاتان الطبعتان مرتبطتان بالفعل.")
                if EditionRelationSuggestion.objects.filter(
                    source=source, target=target, status="pending"
                ).exists():
                    self.add_error(
                        "target",
                        "يوجد اقتراح علاقة قيد المراجعة لهاتين الطبعتين.",
                    )
            elif mode == "new":
                publishers = cleaned.get("new_publishers") or []
                year = cleaned.get("new_year")
                if not publishers:
                    self.add_error("new_publishers", "يرجى إدخال ناشر واحد على الأقل.")
                if not year:
                    self.add_error("new_year", "يرجى إدخال سنة النشر.")
                if publishers and year:
                    existing = (
                        Edition.objects.filter(
                            book=source.book,
                            status=EditionStatus.APPROVED,
                            year=year,
                        )
                        .filter(publishers__name__in=publishers)
                        .distinct()
                    )
                    if existing.exists():
                        raise ValidationError(
                            "يوجد طبعة معتمدة بنفس الناشر والسنة لهذا الكتاب. اخترها من القائمة."
                        )
                cleaned["target_data"] = {
                    "publishers": publishers,
                    "editors": cleaned.get("new_editors") or [],
                    "year": year,
                    "page_count": cleaned.get("new_page_count"),
                    "city": cleaned.get("new_city", ""),
                    "volumes": cleaned.get("new_volumes", ""),
                }
                cleaned["target"] = None
        return cleaned

    def save(self, commit=True):
        with transaction.atomic():
            suggestion = super().save(commit=False)
            suggestion.source = self.source
            if self.cleaned_data.get("target_mode") == "new":
                suggestion.target = None
                suggestion.target_data = self.cleaned_data.get("target_data", {})
            if commit:
                try:
                    suggestion.save()
                except Exception:
                    raise
        return suggestion
