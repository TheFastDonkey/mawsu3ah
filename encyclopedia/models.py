import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models.signals import m2m_changed
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


def unique_slug(model_class, value, field="slug"):
    """Generate a unique slug for a model, appending -2, -3, ... on collisions."""
    base = slugify(value, allow_unicode=True)
    if not base:
        base = "entry"
    candidate = base
    counter = 1
    while model_class.objects.filter(**{field: candidate}).exists():
        counter += 1
        candidate = f"{base}-{counter}"
    return candidate


class Category(models.Model):
    name = models.CharField(max_length=200, unique=True, verbose_name="اسم التصنيف")
    slug = models.SlugField(max_length=220, unique=True, allow_unicode=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
        verbose_name="التصنيف الأصلي",
    )
    path = models.CharField(
        max_length=500,
        db_index=True,
        editable=False,
        default="",
        verbose_name="المسار",
    )
    level = models.PositiveSmallIntegerField(
        default=0,
        editable=False,
        verbose_name="المستوى",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "تصنيف"
        verbose_name_plural = "تصنيفات"
        ordering = ["path"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Category, self.name)

        old_path = None
        old_level = None
        if self.pk:
            old = (
                Category.objects.filter(pk=self.pk)
                .values("path", "level", "parent_id")
                .first()
            )
            if old:
                old_path = old["path"]
                old_level = old["level"]

        if self.parent_id:
            parent = Category.objects.filter(pk=self.parent_id).only("path", "level").first()
            if parent:
                self.level = parent.level + 1
                parent_path = parent.path
            else:
                self.level = 0
                parent_path = ""
        else:
            self.level = 0
            parent_path = ""

        if self.pk:
            self.path = f"{parent_path}{self.pk}/"
        else:
            self.path = ""

        super().save(*args, **kwargs)

        if not self.path:
            self.path = f"{parent_path}{self.pk}/"
            super().save(update_fields=["path"])
        elif old_path is not None and old_path != self.path:
            self._rebuild_descendants(old_path, old_level)

    def _rebuild_descendants(self, old_path, old_level):
        descendants = Category.objects.filter(path__startswith=old_path).exclude(pk=self.pk)
        for descendant in descendants:
            suffix = descendant.path[len(old_path):]
            Category.objects.filter(pk=descendant.pk).update(
                path=self.path + suffix,
                level=self.level + (descendant.level - old_level),
            )

    def clean(self):
        super().clean()
        if self.parent_id:
            if self.parent_id == self.pk:
                raise ValidationError("لا يكون التصنيف أصلًا لنفسه.")
            if self.pk and Category.objects.filter(
                pk=self.parent_id, path__startswith=self.path
            ).exists():
                raise ValidationError(
                    "لا يٌنقل تصنيف إلى فرع فرعه."
                )

    @property
    def ancestors(self):
        if not self.path or self.level == 0:
            return Category.objects.none()
        ancestor_ids = [int(part) for part in self.path.split("/") if part]
        ancestor_ids.pop()  # remove self
        return Category.objects.filter(pk__in=ancestor_ids).order_by("path")

    @property
    def descendants(self):
        return Category.objects.filter(path__startswith=self.path).exclude(pk=self.pk)

    @property
    def is_root(self):
        return self.parent_id is None

    @property
    def is_leaf(self):
        return not self.children.exists()

    def get_url_path(self):
        slugs = [ancestor.slug for ancestor in self.ancestors]
        slugs.append(self.slug)
        return "/".join(slugs)

    def get_absolute_url(self):
        return reverse(
            "category_detail", kwargs={"category_path": self.get_url_path()}
        )


class BookCategory(models.Model):
    book = models.ForeignKey(
        "Book",
        on_delete=models.CASCADE,
        related_name="book_categories",
        verbose_name="الكتاب",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="book_categories",
        verbose_name="التصنيف",
    )
    order = models.PositiveSmallIntegerField(
        default=0,
        verbose_name="الترتيب",
        help_text="0 هو التصنيف الرئيسي المستخدم في مسارات التنقل.",
    )

    class Meta:
        verbose_name = "تصنيف كتاب"
        verbose_name_plural = "تصنيفات الكتب"
        ordering = ["book", "order"]
        unique_together = [["book", "category"]]

    def __str__(self):
        return f"{self.book} ← {self.category}"


class BookAuthor(models.Model):
    book = models.ForeignKey(
        "Book",
        on_delete=models.CASCADE,
        related_name="book_authors",
        verbose_name="الكتاب",
    )
    name_record = models.ForeignKey(
        "NameRecord",
        on_delete=models.CASCADE,
        related_name="book_author_links",
        verbose_name="المؤلف",
    )
    order = models.PositiveSmallIntegerField(
        default=0,
        verbose_name="الترتيب",
    )

    class Meta:
        verbose_name = "مؤلف الكتاب"
        verbose_name_plural = "مؤلفو الكتاب"
        ordering = ["book", "order"]
        unique_together = [["book", "name_record"]]

    def __str__(self):
        return f"{self.book} ← {self.name_record}"


class EditionPublisher(models.Model):
    edition = models.ForeignKey(
        "Edition",
        on_delete=models.CASCADE,
        related_name="edition_publishers",
        verbose_name="الطبعة",
    )
    name_record = models.ForeignKey(
        "NameRecord",
        on_delete=models.CASCADE,
        related_name="edition_publisher_links",
        verbose_name="الناشر",
    )
    order = models.PositiveSmallIntegerField(
        default=0,
        verbose_name="الترتيب",
    )

    class Meta:
        verbose_name = "ناشر الطبعة"
        verbose_name_plural = "ناشرو الطبعة"
        ordering = ["edition", "order"]
        unique_together = [["edition", "name_record"]]

    def __str__(self):
        return f"{self.edition} ← {self.name_record}"


class EditionEditor(models.Model):
    edition = models.ForeignKey(
        "Edition",
        on_delete=models.CASCADE,
        related_name="edition_editors",
        verbose_name="الطبعة",
    )
    name_record = models.ForeignKey(
        "NameRecord",
        on_delete=models.CASCADE,
        related_name="edition_editor_links",
        verbose_name="المحقق",
    )
    order = models.PositiveSmallIntegerField(
        default=0,
        verbose_name="الترتيب",
    )

    class Meta:
        verbose_name = "محقق الطبعة"
        verbose_name_plural = "محققو الطبعة"
        ordering = ["edition", "order"]
        unique_together = [["edition", "name_record"]]

    def __str__(self):
        return f"{self.edition} ← {self.name_record}"


class Book(models.Model):
    title = models.CharField(max_length=500, verbose_name="العنوان")
    authors = models.ManyToManyField(
        "NameRecord",
        through=BookAuthor,
        related_name="authored_books",
        verbose_name="المؤلفون",
    )
    categories = models.ManyToManyField(
        Category,
        through=BookCategory,
        related_name="books",
        verbose_name="التصنيفات",
    )
    aliases = models.TextField(
        blank=True,
        verbose_name="أسماء بديلة",
        help_text="أسماء بديلة مفصولة بفواصل.",
    )
    disambiguation = models.TextField(
        blank=True,
        verbose_name="توضيح التباس",
        help_text="ملاحظة قصيرة للتمييز بين الكتب المتشابهة.",
    )
    slug = models.SlugField(
        max_length=520,
        unique=True,
        allow_unicode=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "كتاب"
        verbose_name_plural = "كتب"
        ordering = ["title"]

    def __str__(self):
        authors = self.authors.order_by("name").values_list("name", flat=True)
        return " — ".join([self.title, "، ".join(authors)])

    def save(self, *args, **kwargs):
        if not self.slug and self.pk:
            self.slug = self.generate_slug()
        super().save(*args, **kwargs)

    def generate_slug(self):
        authors = list(self.authors.order_by("name").values_list("name", flat=True))
        base = f"{self.title} {authors[0]}" if len(authors) == 1 else self.title
        return unique_slug(Book, base)

    def get_absolute_url(self):
        return reverse("book_detail", kwargs={"slug": self.slug})

    @property
    def primary_category(self):
        cached = getattr(self, "_prefetched_objects_cache", {})
        if "book_categories" in cached:
            ordered = sorted(self.book_categories.all(), key=lambda bc: bc.order)
            return ordered[0].category if ordered else None
        bc = BookCategory.objects.filter(book=self, order=0).select_related("category").first()
        return bc.category if bc else None

    @property
    def alias_list(self):
        return [a.strip() for a in self.aliases.split(",") if a.strip()]


class EditionStatus(models.TextChoices):
    PENDING = "pending", "يًراجع"
    APPROVED = "approved", "معتمد"
    REJECTED = "rejected", "مرفوض"


class Edition(models.Model):
    public_id = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True, db_index=True
    )
    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name="editions",
        verbose_name="الكتاب",
    )
    publishers = models.ManyToManyField(
        "NameRecord",
        through=EditionPublisher,
        related_name="published_editions",
        verbose_name="الناشرون",
    )
    year = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        validators=[
            MinValueValidator(1000),
            MaxValueValidator(2100),
        ],
        verbose_name="سنة النشر",
    )
    editors = models.ManyToManyField(
        "NameRecord",
        through=EditionEditor,
        related_name="edited_editions",
        verbose_name="المحققون",
        blank=True,
    )
    page_count = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name="عدد الصفحات",
    )
    city = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="مدينة النشر",
        help_text="مدينة النشر (لا تُكتب إلا عند وجود أكثر من ناشر).",
    )
    volumes = models.CharField(
        max_length=40,
        blank=True,
        verbose_name="المجلدات",
    )
    cover_image = models.ImageField(
        upload_to="editions/covers/%Y/%m/",
        blank=True,
        null=True,
        verbose_name="صورة الغلاف",
        help_text="صورة للطبعة (JPEG أو PNG أو WebP، بحد أقصى 2 ميجابايت).",
    )
    status = models.CharField(
        max_length=20,
        choices=EditionStatus.choices,
        default=EditionStatus.PENDING,
        db_index=True,
        verbose_name="الحالة",
    )
    is_best = models.BooleanField(
        default=False,
        verbose_name="هل هذه أفضل طبعة؟",
        help_text="إذا كنت خبيراً واخترت 'نعم'، ستظهر شارة 'رشحها خبير' على الطبعة.",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="submitted_editions",
        verbose_name="مقدم الطلب",
    )
    submitted_at = models.DateTimeField(
        auto_now_add=True, db_index=True, verbose_name="تاريخ التقديم"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_editions",
        verbose_name="اعتمدها",
    )
    approved_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="تاريخ الاعتماد",
    )
    rejection_reason = models.TextField(
        blank=True,
        verbose_name="سبب الرفض",
    )

    class Meta:
        verbose_name = "طبعة"
        verbose_name_plural = "طبعات"
        ordering = ["-submitted_at"]

    def __str__(self):
        publishers = self.publishers.order_by("name").values_list("name", flat=True)
        publisher_str = "، ".join(publishers)
        parts = [str(self.book), f"طبعة {publisher_str}"]
        if self.year:
            parts.append(str(self.year))
        return " — ".join(parts)

    def get_absolute_url(self):
        return reverse(
            "edition_detail",
            kwargs={"book_slug": self.book.slug, "edition_public_id": self.public_id},
        )

    @property
    def city_display(self):
        """Return the edition's manual city override, or the first publisher's city."""
        if self.city:
            return self.city
        prefetched = getattr(self, "_prefetched_objects_cache", {}).get("publishers")
        if prefetched is not None:
            first = prefetched[0] if prefetched else None
            return first.city if first else ""
        link = self.edition_publishers.select_related("name_record").order_by("order").first()
        return link.name_record.city if link else ""


class EditionVote(models.Model):
    class VoteValue(models.IntegerChoices):
        LIKE = 1, "إعجاب"
        DISLIKE = -1, "عدم إعجاب"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="edition_votes",
        verbose_name="المستخدم",
    )
    edition = models.ForeignKey(
        Edition,
        on_delete=models.CASCADE,
        related_name="votes",
        verbose_name="الطبعة",
    )
    book_context = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name="context_votes",
        verbose_name="سياق التصويت",
    )
    value = models.SmallIntegerField(
        choices=VoteValue.choices,
        default=VoteValue.LIKE,
        verbose_name="التصويت",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["user", "edition", "book_context"]
        verbose_name = "تصويت بطبعة"
        verbose_name_plural = "تصويتات بالطبعات"
        indexes = [
            models.Index(fields=["edition", "book_context"]),
        ]

    def __str__(self):
        return f"{self.user} ← {self.edition} ({self.value})"


class Review(models.Model):
    public_id = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True, db_index=True
    )
    edition = models.ForeignKey(
        Edition,
        on_delete=models.CASCADE,
        related_name="reviews",
        verbose_name="الطبعة",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reviews",
        verbose_name="المستخدم",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies",
        verbose_name="المراجعة الأصلية",
    )
    body = models.TextField(verbose_name="المراجعة")
    hidden = models.BooleanField(default=False, db_index=True, verbose_name="مخفي")
    hidden_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hidden_reviews",
        verbose_name="أخفاها",
    )
    hidden_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="تاريخ الإخفاء",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="تاريخ النشر")
    edited_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="تاريخ التعديل",
    )
    depth = models.PositiveIntegerField(default=0, db_index=True, verbose_name="العمق")

    @property
    def is_edited(self):
        return self.edited_at is not None

    class Meta:
        verbose_name = "مراجعة"
        verbose_name_plural = "مراجعات"
        ordering = ["-created_at"]

    def __str__(self):
        return f"مراجعة {self.user} على {self.edition}"

    def save(self, *args, **kwargs):
        if self.parent_id is None:
            self.depth = 0
        elif self.parent_id and self._state.adding:
            # On new rows compute depth from the parent. When updating we keep
            # the existing value unless the parent changed.
            parent_depth = Review.objects.filter(pk=self.parent_id).values_list(
                "depth", flat=True
            ).first()
            self.depth = (parent_depth or 0) + 1
        elif self.parent_id and self.pk:
            current_parent_id = Review.objects.filter(pk=self.pk).values_list(
                "parent_id", flat=True
            ).first()
            if current_parent_id != self.parent_id:
                parent_depth = Review.objects.filter(pk=self.parent_id).values_list(
                    "depth", flat=True
                ).first()
                self.depth = (parent_depth or 0) + 1
        super().save(*args, **kwargs)

class ReviewVote(models.Model):
    class VoteValue(models.IntegerChoices):
        LIKE = 1, "إعجاب"
        DISLIKE = -1, "عدم إعجاب"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="review_votes",
    )
    review = models.ForeignKey(
        Review,
        on_delete=models.CASCADE,
        related_name="votes",
    )
    value = models.SmallIntegerField(
        choices=VoteValue.choices,
        default=VoteValue.LIKE,
        verbose_name="التصويت",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["user", "review"]
        verbose_name = "تصويت بمراجعة"
        verbose_name_plural = "تصويتات بمراجعات"

    def __str__(self):
        return f"{self.user} ← مراجعة {self.review.id} ({self.value})"


class ReviewReport(models.Model):
    REASON_CHOICES = [
        ("inappropriate", "محتوى غير لائق"),
        ("harassment", "إساءة"),
        ("offtopic", "غير ذي صلة"),
        ("spam", "إزعاج / إعلانات"),
        ("other", "سبب آخر"),
    ]
    review = models.ForeignKey(
        Review,
        on_delete=models.CASCADE,
        related_name="reports",
        verbose_name="المراجعة",
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="review_reports",
        verbose_name="المُبلّغ",
    )
    reason = models.CharField(
        max_length=20,
        choices=REASON_CHOICES,
        verbose_name="السبب",
    )
    details = models.TextField(blank=True, verbose_name="تفاصيل")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإبلاغ")
    resolved = models.BooleanField(default=False, verbose_name="تم الحل")
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_review_reports",
        verbose_name="حلّه",
    )
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ الحل")

    class Meta:
        unique_together = ["review", "reporter"]
        verbose_name = "بلاغ عن مراجعة"
        verbose_name_plural = "بلاغات عن المراجعات"
        ordering = ["-created_at"]

    def __str__(self):
        return f"بلاغ {self.reporter} على مراجعة {self.review_id}"


class CategorySuggestionStatus(models.TextChoices):
    PENDING = "pending", "يُراجع"
    APPROVED = "approved", "معتمد"
    REJECTED = "rejected", "مرفوض"


class CategorySuggestion(models.Model):
    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name="category_suggestions",
        verbose_name="الكتاب",
    )
    suggested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="category_suggestions",
        verbose_name="مقدّم الاقتراح",
    )
    name = models.CharField(max_length=200, verbose_name="اسم التصنيف المقترح")
    reason = models.TextField(blank=True, verbose_name="السبب")
    status = models.CharField(
        max_length=20,
        choices=CategorySuggestionStatus.choices,
        default=CategorySuggestionStatus.PENDING,
        db_index=True,
        verbose_name="الحالة",
    )
    final_category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="suggestions",
        verbose_name="التصنيف النهائي",
    )
    admin_note = models.TextField(blank=True, verbose_name="ملاحظة المشرف")
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_category_suggestions",
        verbose_name="عالجه",
    )
    resolved_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="تاريخ المعالجة",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ التقديم")

    class Meta:
        verbose_name = "اقتراح تصنيف"
        verbose_name_plural = "اقتراحات التصنيفات"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ← {self.book}"


class CategorySuggestionVote(models.Model):
    class VoteValue(models.IntegerChoices):
        LIKE = 1, "إعجاب"
        DISLIKE = -1, "عدم إعجاب"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="category_suggestion_votes",
        verbose_name="المستخدم",
    )
    suggestion = models.ForeignKey(
        CategorySuggestion,
        on_delete=models.CASCADE,
        related_name="votes",
        verbose_name="اقتراح التصنيف",
    )
    value = models.SmallIntegerField(
        choices=VoteValue.choices,
        default=VoteValue.LIKE,
        verbose_name="التصويت",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["user", "suggestion"]
        verbose_name = "تصويت على اقتراح تصنيف"
        verbose_name_plural = "تصويتات على اقتراحات التصنيفات"
        indexes = [
            models.Index(fields=["suggestion"]),
        ]

    def __str__(self):
        return f"{self.user} ← {self.suggestion} ({self.value})"


class CategoryRequestStatus(models.TextChoices):
    PENDING = "pending", "يٌراجع"
    APPROVED = "approved", "معتمد"
    REJECTED = "rejected", "مرفوض"


class CategoryRequest(models.Model):
    name = models.CharField(max_length=200, verbose_name="اسم التصنيف المطلوب")
    suggested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="category_requests",
        verbose_name="مقدّم الطلب",
    )
    status = models.CharField(
        max_length=20,
        choices=CategoryRequestStatus.choices,
        default=CategoryRequestStatus.PENDING,
        db_index=True,
        verbose_name="الحالة",
    )
    final_category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requests",
        verbose_name="التصنيف النهائي",
    )
    admin_note = models.TextField(blank=True, verbose_name="ملاحظة المشرف")
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_category_requests",
        verbose_name="عالجه",
    )
    resolved_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="تاريخ المعالجة",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ التقديم")

    class Meta:
        verbose_name = "طلب تصنيف جديد"
        verbose_name_plural = "طلبات تصنيف جديد"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "suggested_by"],
                condition=models.Q(status="pending"),
                name="unique_pending_category_request_per_user",
            ),
        ]

    def __str__(self):
        return self.name


class ApprovalLog(models.Model):
    edition = models.ForeignKey(
        Edition,
        on_delete=models.CASCADE,
        related_name="approval_logs",
        verbose_name="الطبعة",
    )
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="approval_logs",
        verbose_name="المشرف",
    )
    old_status = models.CharField(
        max_length=20,
        choices=EditionStatus.choices,
        verbose_name="الحالة القديمة",
    )
    new_status = models.CharField(
        max_length=20,
        choices=EditionStatus.choices,
        verbose_name="الحالة الجديدة",
    )
    reason = models.TextField(blank=True, verbose_name="السبب")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="التاريخ")

    class Meta:
        verbose_name = "سجل اعتماد"
        verbose_name_plural = "سجلات الاعتماد"
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.edition}: {self.old_status} → {self.new_status}"


class EditionEditSuggestionStatus(models.TextChoices):
    PENDING = "pending", "قيد المراجعة"
    APPROVED = "approved", "معتمد"
    REJECTED = "rejected", "مرفوض"


class EditionEditSuggestion(models.Model):
    edition = models.ForeignKey(
        Edition,
        on_delete=models.CASCADE,
        related_name="edit_suggestions",
        verbose_name="الطبعة",
    )
    suggested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="edition_edit_suggestions",
        verbose_name="مقدّم الاقتراح",
    )
    status = models.CharField(
        max_length=20,
        choices=EditionEditSuggestionStatus.choices,
        default=EditionEditSuggestionStatus.PENDING,
        db_index=True,
        verbose_name="الحالة",
    )
    proposed_publishers = models.JSONField(
        default=list,
        blank=True,
        verbose_name="الناشرون المقترحون",
    )
    proposed_editors = models.JSONField(
        default=list,
        blank=True,
        verbose_name="المحققون المقترحون",
    )
    year = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        validators=[
            MinValueValidator(1000),
            MaxValueValidator(2100),
        ],
        verbose_name="سنة النشر",
    )
    page_count = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name="الصفحات",
    )
    city = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="مدينة النشر",
        help_text="مدينة النشر (لا تُكتب إلا عند وجود أكثر من ناشر).",
    )
    volumes = models.CharField(
        max_length=40,
        blank=True,
        verbose_name="المجلدات",
    )
    cover_image = models.ImageField(
        upload_to="editions/covers/%Y/%m/",
        blank=True,
        null=True,
        verbose_name="صورة الغلاف",
    )
    admin_note = models.TextField(
        blank=True,
        verbose_name="ملاحظة المشرف",
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_edition_edit_suggestions",
        verbose_name="عالجه",
    )
    resolved_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="تاريخ المعالجة",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="تاريخ التقديم",
    )

    class Meta:
        verbose_name = "اقتراح تعديل طبعة"
        verbose_name_plural = "اقتراحات تعديل الطبعات"
        ordering = ["-created_at"]

    def __str__(self):
        return f"تعديل مقترح لـ {self.edition}"

    def apply_to_edition(self, admin_user):
        """Apply the proposed changes to the linked edition and mark approved."""
        from django.utils import timezone

        with transaction.atomic():
            edition = Edition.objects.select_for_update().filter(
                pk=self.edition_id
            ).first()
            if edition is None:
                raise Edition.DoesNotExist("الطبعة المرتبطة غير موجودة.")

            # Apply publisher/editor changes first so we can determine publisher count.
            self._apply_names(
                edition,
                NameRecordKind.PUBLISHER,
                self.proposed_publishers,
                EditionPublisher,
            )
            self._apply_names(
                edition,
                NameRecordKind.EDITOR,
                self.proposed_editors,
                EditionEditor,
            )

            if self.year is not None:
                edition.year = self.year
            if self.page_count is not None:
                edition.page_count = self.page_count
            if self.volumes:
                edition.volumes = self.volumes

            if self.city:
                if edition.publishers.count() == 1:
                    publisher = edition.publishers.first()
                    publisher.city = self.city
                    publisher.save(update_fields=["city"])
                else:
                    edition.city = self.city

            if self.cover_image:
                edition.cover_image = self.cover_image

            edition.save()

            self.status = EditionEditSuggestionStatus.APPROVED
            self.resolved_by = admin_user
            self.resolved_at = timezone.now()
            self.save(update_fields=["status", "resolved_by", "resolved_at"])

    def _apply_names(self, edition, kind, names, through_model):
        if not names:
            return
        records = []
        for name in sorted(set(names)):
            record = NameRecord.objects.filter(kind=kind, name=name).first()
            if record is None:
                record = NameRecord.objects.create(
                    kind=kind,
                    name=name,
                    status=NameRecordStatus.APPROVED,
                )
            records.append(record)
        through_model.objects.filter(edition=edition).delete()
        for i, record in enumerate(records):
            through_model.objects.create(edition=edition, name_record=record, order=i)


class EditionBookLinkRole(models.TextChoices):
    COMMENTARY = "commentary", "شرح أو حاشية"
    ANTHOLOGY = "anthology", "مجموعة"


class EditionBookLink(models.Model):
    edition = models.ForeignKey(
        Edition,
        on_delete=models.CASCADE,
        related_name="book_links",
        verbose_name="الطبعة",
    )
    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name="edition_links",
        verbose_name="الكتاب",
    )
    role = models.CharField(
        max_length=20,
        choices=EditionBookLinkRole.choices,
        default=EditionBookLinkRole.COMMENTARY,
        verbose_name="العلاقة",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ربط طبعة بكتاب"
        verbose_name_plural = "روابط الطبعات بالكتب"
        unique_together = [["edition", "book"]]
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["book", "role"]),
        ]

    def __str__(self):
        return f"{self.edition} ← {self.book} ({self.role})"


class EditionBookLinkSuggestionStatus(models.TextChoices):
    PENDING = "pending", "يٌراجع"
    APPROVED = "approved", "معتمد"
    REJECTED = "rejected", "مرفوض"


class EditionBookLinkSuggestion(models.Model):
    edition = models.ForeignKey(
        Edition,
        on_delete=models.CASCADE,
        related_name="book_link_suggestions",
        verbose_name="الطبعة",
    )
    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name="book_link_suggestions",
        verbose_name="الكتاب",
    )
    role = models.CharField(
        max_length=20,
        choices=EditionBookLinkRole.choices,
        default=EditionBookLinkRole.COMMENTARY,
        verbose_name="العلاقة",
    )
    reason = models.TextField(blank=True, verbose_name="السبب")
    suggested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="book_link_suggestions",
        verbose_name="مقدّم الاقتراح",
    )
    status = models.CharField(
        max_length=20,
        choices=EditionBookLinkSuggestionStatus.choices,
        default=EditionBookLinkSuggestionStatus.PENDING,
        db_index=True,
        verbose_name="الحالة",
    )
    admin_note = models.TextField(blank=True, verbose_name="ملاحظة المشرف")
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_book_link_suggestions",
        verbose_name="عالجه",
    )
    resolved_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="تاريخ المعالجة",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ التقديم")

    class Meta:
        verbose_name = "اقتراح ربط طبعة بكتاب"
        verbose_name_plural = "اقتراحات ربط الطبعات بالكتب"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["edition", "book", "suggested_by"],
                condition=models.Q(status="pending"),
                name="unique_pending_book_link_suggestion_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.edition} ← {self.book} ({self.role})"

    def approve(self, admin_user):
        from django.db.models import Q
        from django.utils import timezone

        with transaction.atomic():
            # Lock the linked edition and book so concurrent approve calls cannot
            # create duplicate EditionBookLink rows.
            Edition.objects.select_for_update().filter(
                Q(pk=self.edition_id) | Q(pk=self.book_id)
            )
            Book.objects.select_for_update().filter(pk=self.book_id)

            EditionBookLink.objects.get_or_create(
                edition=self.edition,
                book=self.book,
                defaults={"role": self.role},
            )
            self.status = EditionBookLinkSuggestionStatus.APPROVED
            self.resolved_by = admin_user
            self.resolved_at = timezone.now()
            self.save(update_fields=["status", "resolved_by", "resolved_at"])


class EditionRelationKind(models.TextChoices):
    PHOTOCOPY = "photocopy", "طبعة مصورة"
    REPRINT = "reprint", "إعادة طبع"


class EditionRelation(models.Model):
    source = models.ForeignKey(
        Edition,
        on_delete=models.CASCADE,
        related_name="related_targets",
        verbose_name="الطبعة الأصل",
    )
    target = models.ForeignKey(
        Edition,
        on_delete=models.CASCADE,
        related_name="related_sources",
        verbose_name="الطبعة المرتبطة",
    )
    kind = models.CharField(
        max_length=20,
        choices=EditionRelationKind.choices,
        default=EditionRelationKind.PHOTOCOPY,
        verbose_name="نوع العلاقة",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "علاقة بين طبعتين"
        verbose_name_plural = "علاقات بين الطبعات"
        unique_together = [["source", "target", "kind"]]
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["source", "kind"]),
            models.Index(fields=["target", "kind"]),
        ]

    def __str__(self):
        return f"{self.target} ← {self.source} ({self.kind})"


class EditionRelationSuggestionStatus(models.TextChoices):
    PENDING = "pending", "يٌراجع"
    APPROVED = "approved", "معتمد"
    REJECTED = "rejected", "مرفوض"


class EditionRelationSuggestion(models.Model):
    source = models.ForeignKey(
        Edition,
        on_delete=models.CASCADE,
        related_name="relation_suggestions",
        verbose_name="الطبعة الأصل",
    )
    target = models.ForeignKey(
        Edition,
        on_delete=models.CASCADE,
        related_name="target_relation_suggestions",
        verbose_name="الطبعة المرتبطة",
        null=True,
        blank=True,
    )
    target_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="بيانات الطبعة الجديدة",
        help_text="تُستخدم عند اقتراح طبعة غير موجودة.",
    )
    kind = models.CharField(
        max_length=20,
        choices=EditionRelationKind.choices,
        default=EditionRelationKind.PHOTOCOPY,
        verbose_name="نوع العلاقة",
    )
    reason = models.TextField(blank=True, verbose_name="السبب")
    suggested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="edition_relation_suggestions",
        verbose_name="مقدّم الاقتراح",
    )
    status = models.CharField(
        max_length=20,
        choices=EditionRelationSuggestionStatus.choices,
        default=EditionRelationSuggestionStatus.PENDING,
        db_index=True,
        verbose_name="الحالة",
    )
    admin_note = models.TextField(blank=True, verbose_name="ملاحظة المشرف")
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_edition_relation_suggestions",
        verbose_name="عالجه",
    )
    resolved_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="تاريخ المعالجة",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ التقديم")

    class Meta:
        verbose_name = "اقتراح علاقة بين طبعتين"
        verbose_name_plural = "اقتراحات علاقات بين الطبعات"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "target", "kind", "suggested_by"],
                condition=models.Q(status="pending"),
                name="unique_pending_edition_relation_suggestion_per_user",
            ),
        ]

    def __str__(self):
        if self.target_id:
            return f"{self.target} ← {self.source} ({self.kind})"
        publishers = ", ".join(self.target_data.get("publishers", []))
        year = self.target_data.get("year")
        return f"طبعة جديدة: {publishers} {year or ''} ← {self.source} ({self.kind})"

    def clean(self):
        if self.source_id and self.target_id and self.source_id == self.target_id:
            raise ValidationError("لا يمكن ربط الطبعة بنفسها.")

    def _ensure_name_record(self, kind, name):
        name = name.strip()
        if not name:
            return None
        auto_approve = bool(
            self.suggested_by and getattr(self.suggested_by, "is_expert", False)
        )
        defaults = {
            "status": (
                NameRecordStatus.APPROVED
                if auto_approve
                else NameRecordStatus.PENDING
            ),
            "submitted_by": self.suggested_by,
        }
        if auto_approve:
            defaults["approved_by"] = self.suggested_by
            defaults["approved_at"] = timezone.now()
        record, _ = NameRecord.objects.get_or_create(
            kind=kind,
            name=name,
            defaults=defaults,
        )
        if record.status == NameRecordStatus.REJECTED:
            if auto_approve:
                record.status = NameRecordStatus.APPROVED
                record.approved_by = self.suggested_by
                record.approved_at = timezone.now()
            else:
                record.status = NameRecordStatus.PENDING
            record.submitted_by = self.suggested_by
            record.save(
                update_fields=[
                    "status",
                    "submitted_by",
                    "approved_by",
                    "approved_at",
                ]
            )
        return record

    def _assign_names(self, edition, kind, names, through_model):
        names = sorted({n.strip() for n in names if n.strip()})
        records = [r for r in (self._ensure_name_record(kind, n) for n in names) if r]
        through_model.objects.filter(edition=edition).delete()
        for i, record in enumerate(records):
            through_model.objects.create(edition=edition, name_record=record, order=i)

    def _create_target_edition(self):
        from django.utils import timezone

        data = self.target_data
        is_expert = bool(
            self.suggested_by and getattr(self.suggested_by, "is_expert", False)
        )
        status = (
            EditionStatus.APPROVED
            if is_expert
            else EditionStatus.PENDING
        )
        edition = Edition.objects.create(
            book=self.source.book,
            year=data.get("year"),
            page_count=data.get("page_count"),
            city=data.get("city", ""),
            volumes=data.get("volumes", ""),
            status=status,
            submitted_by=self.suggested_by,
        )
        if is_expert:
            edition.approved_by = self.suggested_by
            edition.approved_at = timezone.now()
            edition.save(update_fields=["approved_by", "approved_at"])
        self._assign_names(
            edition, NameRecordKind.PUBLISHER, data.get("publishers", []), EditionPublisher
        )
        self._assign_names(
            edition, NameRecordKind.EDITOR, data.get("editors", []), EditionEditor
        )
        return edition

    def approve(self, admin_user):
        from django.utils import timezone

        with transaction.atomic():
            # Lock the source edition to prevent concurrent approvals from race
            # creating duplicate relations or target editions.
            source = (
                Edition.objects.select_for_update()
                .filter(pk=self.source_id)
                .first()
            )
            if source is None:
                raise Edition.DoesNotExist("الطبعة الأصل غير موجودة.")

            target = self.target
            if target is None:
                target = self._create_target_edition()
                self.target = target
                self.save(update_fields=["target"])
                if target.status != EditionStatus.APPROVED:
                    # Non-expert suggestions create a pending target that must be
                    # approved before the relation can be published.
                    return

            if target.status != EditionStatus.APPROVED:
                # The target edition is not yet approved; only approved editions
                # can participate in a public relation.
                return

            EditionRelation.objects.get_or_create(
                source=source,
                target=target,
                defaults={"kind": self.kind},
            )
            self.status = EditionRelationSuggestionStatus.APPROVED
            self.resolved_by = admin_user
            self.resolved_at = timezone.now()
            self.save(update_fields=["status", "resolved_by", "resolved_at"])


@receiver(models.signals.post_save, sender=Edition)
def _approve_pending_relation_suggestions(sender, instance, created, **kwargs):
    """When a pending edition (created by a relation suggestion) is approved,
    automatically approve any pending relation suggestions pointing to it.
    """
    if created or instance.status != EditionStatus.APPROVED:
        return
    pending = EditionRelationSuggestion.objects.filter(
        target=instance,
        status=EditionRelationSuggestionStatus.PENDING,
    )
    for suggestion in pending:
        suggestion.approve(instance.approved_by or suggestion.suggested_by)


class NameRecordStatus(models.TextChoices):
    PENDING = "pending", "يٌراجع"
    APPROVED = "approved", "معتمد"
    REJECTED = "rejected", "مرفوض"


class NameRecordKind(models.TextChoices):
    AUTHOR = "author", "مؤلف"
    EDITOR = "editor", "محقق"
    PUBLISHER = "publisher", "ناشر"


class NameRecord(models.Model):
    kind = models.CharField(
        max_length=20,
        choices=NameRecordKind.choices,
        verbose_name="النوع",
    )
    name = models.CharField(max_length=300, verbose_name="الاسم")
    slug = models.SlugField(
        max_length=320,
        allow_unicode=True,
        blank=True,
        verbose_name="الslug",
    )
    status = models.CharField(
        max_length=20,
        choices=NameRecordStatus.choices,
        default=NameRecordStatus.PENDING,
        db_index=True,
        verbose_name="الحالة",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_name_records",
        verbose_name="مقدم الطلب",
    )
    city = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="مدينة النشر",
        help_text="مدينة النشر (لا تُكتب إلا عند وجود أكثر من ناشر).",
    )
    submitted_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ التقديم")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_name_records",
        verbose_name="اعتمدها",
    )
    approved_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="تاريخ الاعتماد",
    )
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rejected_name_records",
        verbose_name="رفضها",
    )
    rejected_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="تاريخ الرفض",
    )

    class Meta:
        verbose_name = "اسم مرجعي"
        verbose_name_plural = "أسماء مرجعية"
        ordering = ["kind", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "name"],
                name="unique_name_record_kind_name",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(
                NameRecord,
                self.name,
                field="slug",
            )
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Author(NameRecord):
    class Meta:
        proxy = True
        verbose_name = "مؤلف"
        verbose_name_plural = "مؤلفون"
        ordering = ["name"]


class Editor(NameRecord):
    class Meta:
        proxy = True
        verbose_name = "محقق"
        verbose_name_plural = "محققون"
        ordering = ["name"]


class Publisher(NameRecord):
    class Meta:
        proxy = True
        verbose_name = "ناشر"
        verbose_name_plural = "ناشرون"
        ordering = ["name"]


@receiver(m2m_changed, sender=Book.categories.through)
def assign_book_category_order(sender, instance, action, pk_set, **kwargs):
    """Renumber a book's category links so the first added stays primary."""
    if action != "post_add" or not pk_set:
        return
    for i, bc in enumerate(instance.book_categories.order_by("order", "id")):
        if bc.order != i:
            bc.order = i
            bc.save(update_fields=["order"])
