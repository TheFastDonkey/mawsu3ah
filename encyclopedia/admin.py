import logging

from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    ApprovalLog,
    Author,
    Book,
    BookAuthor,
    BookCategory,
    Category,
    CategoryRequest,
    CategoryRequestStatus,
    CategorySuggestion,
    Edition,
    EditionBookLink,
    EditionBookLinkSuggestion,
    EditionBookLinkSuggestionStatus,
    EditionEditor,
    EditionEditSuggestion,
    EditionPublisher,
    EditionRelation,
    EditionRelationSuggestion,
    EditionRelationSuggestionStatus,
    EditionStatus,
    EditionVote,
    Editor,
    NameRecord,
    NameRecordKind,
    NameRecordStatus,
    Publisher,
    Review,
    ReviewReport,
    ReviewVote,
)

admin_logger = logging.getLogger("mawsu3ah.admin")


class CategoryAdminForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "parent"]

    def clean_parent(self):
        parent = self.cleaned_data.get("parent")
        if parent and self.instance.pk:
            if parent.pk == self.instance.pk:
                raise forms.ValidationError("لا يكون التصنيف أصلًا لنفسه.")
            if Category.objects.filter(pk=parent.pk, path__startswith=self.instance.path).exists():
                raise forms.ValidationError("لا يٌنقل تصنيف إلى فرع فرعه.")
        return parent


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    form = CategoryAdminForm
    list_display = ["name", "parent", "level", "path", "created_at"]
    search_fields = ["name"]
    readonly_fields = ["slug", "path", "level", "created_at"]


@admin.register(CategorySuggestion)
class CategorySuggestionAdmin(admin.ModelAdmin):
    list_display = ["name", "book", "suggested_by", "status", "created_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["name", "book__title", "suggested_by__email"]
    readonly_fields = ["created_at", "resolved_at"]
    actions = ["approve_suggestions", "reject_suggestions"]

    @admin.action(description="اعتمد الاقتراحات المحددة")
    def approve_suggestions(self, request, queryset):

        now = timezone.now()
        count = 0
        for suggestion in queryset.filter(status="pending"):
            name = suggestion.name.strip()
            try:
                category = Category.objects.get(name=name)
            except Category.DoesNotExist:
                category = Category(name=name)
                category.save()
            suggestion.final_category = category
            suggestion.status = "approved"
            suggestion.resolved_by = request.user
            suggestion.resolved_at = now
            suggestion.save()
            if not suggestion.book.categories.filter(pk=category.pk).exists():
                next_order = (
                    BookCategory.objects.filter(book=suggestion.book).count()
                )
                BookCategory.objects.create(
                    book=suggestion.book,
                    category=category,
                    order=next_order,
                )
            count += 1
        self.message_user(
            request,
            f"اعتمدنا {count} اقتراح تصنيف.",
            messages.SUCCESS,
        )

    @admin.action(description="ارفض الاقتراحات المحددة")
    def reject_suggestions(self, request, queryset):
        count = queryset.filter(status="pending").update(
            status="rejected",
            resolved_by=request.user,
            resolved_at=timezone.now(),
        )
        self.message_user(
            request,
            f"رفضنا {count} اقتراح تصنيف.",
            messages.SUCCESS,
        )


@admin.register(CategoryRequest)
class CategoryRequestAdmin(admin.ModelAdmin):
    list_display = ["name", "suggested_by", "status", "created_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["name", "suggested_by__email"]
    readonly_fields = ["created_at", "resolved_at"]
    actions = ["approve_requests", "reject_requests"]

    @admin.action(description="اعتمد الطلبات المحددة")
    def approve_requests(self, request, queryset):
        now = timezone.now()
        count = 0
        for category_request in queryset.filter(status="pending"):
            name = category_request.name.strip()
            category, _created = Category.objects.get_or_create(name=name)
            category_request.final_category = category
            category_request.status = CategoryRequestStatus.APPROVED
            category_request.resolved_by = request.user
            category_request.resolved_at = now
            category_request.save()
            count += 1
        self.message_user(
            request,
            f"اعتمدنا {count} طلب تصنيف.",
            messages.SUCCESS,
        )

    @admin.action(description="ارفض الطلبات المحددة")
    def reject_requests(self, request, queryset):
        count = queryset.filter(status="pending").update(
            status=CategoryRequestStatus.REJECTED,
            resolved_by=request.user,
            resolved_at=timezone.now(),
        )
        self.message_user(
            request,
            f"رفضنا {count} طلب تصنيف.",
            messages.SUCCESS,
        )


def _category_choice_label(category):
    indent = "— " * category.level
    return f"{indent}{category.name}"


class BookAdminForm(forms.ModelForm):
    selected_categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.order_by("path"),
        required=True,
        label="التصنيفات",
    )
    primary_category = forms.ModelChoiceField(
        queryset=Category.objects.order_by("path"),
        required=True,
        label="التصنيف الأصلي",
    )

    class Meta:
        model = Book
        exclude = ["categories", "authors"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["selected_categories"].label_from_instance = _category_choice_label
        self.fields["primary_category"].label_from_instance = _category_choice_label
        if self.instance.pk:
            self.fields["selected_categories"].initial = list(
                self.instance.categories.values_list("pk", flat=True)
            )
            primary = self.instance.primary_category
            if primary:
                self.fields["primary_category"].initial = primary.pk

    def clean(self):
        cleaned = super().clean()
        selected = set(cleaned.get("selected_categories") or [])
        primary = cleaned.get("primary_category")
        if primary and primary.pk not in {c.pk for c in selected}:
            self.add_error(
                "primary_category",
                "لا بد أن يكون التصنيف الأصلي أحد التصنيفات المختارة.",
            )
        return cleaned


class BookAuthorInline(admin.TabularInline):
    model = BookAuthor
    fk_name = "book"
    extra = 1
    autocomplete_fields = ["name_record"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "name_record":
            kwargs["queryset"] = NameRecord.objects.filter(
                kind=NameRecordKind.AUTHOR,
                status=NameRecordStatus.APPROVED,
            ).order_by("name")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    form = BookAdminForm
    list_display = ["title", "display_categories", "created_at"]
    search_fields = ["title", "aliases"]
    readonly_fields = ["slug", "created_at"]
    inlines = [BookAuthorInline]

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        book = form.instance

        # Preserve alphabetical order for authors added via inlines.
        records = list(book.authors.order_by("name"))
        BookAuthor.objects.filter(book=book).delete()
        for i, record in enumerate(records):
            BookAuthor.objects.create(book=book, name_record=record, order=i)

        # Save category ordering (primary first).
        selected = list(form.cleaned_data.get("selected_categories", []))
        primary = form.cleaned_data.get("primary_category")
        if primary and primary in selected:
            selected.remove(primary)
            selected.insert(0, primary)
        BookCategory.objects.filter(book=book).delete()
        for i, category in enumerate(selected):
            BookCategory.objects.create(book=book, category=category, order=i)

        # Generate slug now that authors are persisted.
        if not book.slug:
            book.slug = book.generate_slug()
            book.save(update_fields=["slug"])

    @admin.display(description="التصنيفات")
    def display_categories(self, obj):
        return ", ".join(obj.categories.values_list("name", flat=True))


@admin.register(EditionVote)
class EditionVoteAdmin(admin.ModelAdmin):
    list_display = ["user", "edition", "book_context", "value", "created_at"]
    list_filter = ["value", "created_at"]
    search_fields = ["user__email", "edition__book__title", "book_context__title"]
    readonly_fields = ["created_at"]


class ReviewVoteInline(admin.TabularInline):
    model = ReviewVote
    extra = 0
    readonly_fields = ["created_at"]


class ReviewReportInline(admin.TabularInline):
    model = ReviewReport
    extra = 0
    readonly_fields = ["reporter", "reason", "details", "created_at", "resolved"]
    fields = readonly_fields


class HasPendingReportsFilter(admin.SimpleListFilter):
    title = "بلاغات معلقة"
    parameter_name = "pending_reports"

    def lookups(self, request, model_admin):
        return [
            ("yes", "توجد بلاغات معلقة"),
            ("no", "لا بلاغات معلقة"),
        ]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(reports__resolved=False).distinct()
        if self.value() == "no":
            return queryset.exclude(reports__resolved=False).distinct()
        return queryset


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["user", "edition", "parent", "hidden", "created_at"]
    list_filter = ["hidden", "created_at", HasPendingReportsFilter]
    search_fields = ["user__email", "body", "edition__book__title"]
    actions = ["hide_reviews", "show_reviews"]
    inlines = [ReviewVoteInline, ReviewReportInline]

    @admin.action(description="إخفاء المراجعات المحددة")
    def hide_reviews(self, request, queryset):
        count = queryset.update(hidden=True)
        admin_logger.info(
            "Admin %s hid %d review(s): %s",
            request.user,
            count,
            list(queryset.values_list("pk", flat=True)),
        )
        self.message_user(request, "أخفيت المراجعات المحددة.")

    @admin.action(description="إظهار المراجعات المحددة")
    def show_reviews(self, request, queryset):
        count = queryset.update(hidden=False)
        admin_logger.info(
            "Admin %s showed %d review(s): %s",
            request.user,
            count,
            list(queryset.values_list("pk", flat=True)),
        )
        self.message_user(request, "أظهرت المراجعات المحددة.")


@admin.register(ReviewVote)
class ReviewVoteAdmin(admin.ModelAdmin):
    list_display = ["user", "review", "value", "created_at"]
    list_filter = ["value", "created_at"]
    search_fields = ["user__email", "review__body"]
    readonly_fields = ["created_at"]


@admin.register(ReviewReport)
class ReviewReportAdmin(admin.ModelAdmin):
    list_display = ["review", "reporter", "reason", "created_at", "resolved"]
    list_filter = ["resolved", "reason", "created_at"]
    search_fields = ["review__body", "reporter__email", "details"]
    readonly_fields = ["created_at"]


@admin.register(ApprovalLog)
class ApprovalLogAdmin(admin.ModelAdmin):
    list_display = ["edition", "admin", "old_status", "new_status", "timestamp"]
    list_filter = ["new_status", "timestamp"]
    search_fields = ["edition__book__title", "admin__email", "reason"]
    readonly_fields = [
        "edition",
        "admin",
        "old_status",
        "new_status",
        "reason",
        "timestamp",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ApprovalLogInline(admin.TabularInline):
    model = ApprovalLog
    extra = 0
    readonly_fields = ["admin", "old_status", "new_status", "reason", "timestamp"]
    can_delete = False


class EditionPublisherInline(admin.TabularInline):
    model = EditionPublisher
    fk_name = "edition"
    extra = 1
    autocomplete_fields = ["name_record"]


class EditionEditorInline(admin.TabularInline):
    model = EditionEditor
    fk_name = "edition"
    extra = 1
    autocomplete_fields = ["name_record"]


class EditionBookLinkInline(admin.TabularInline):
    model = EditionBookLink
    fk_name = "edition"
    extra = 1
    autocomplete_fields = ["book"]


class EditionRelationInline(admin.TabularInline):
    model = EditionRelation
    fk_name = "source"
    extra = 1
    autocomplete_fields = ["target"]


@admin.register(EditionRelation)
class EditionRelationAdmin(admin.ModelAdmin):
    list_display = ["source", "target", "kind", "created_at"]
    list_filter = ["kind", "created_at"]
    search_fields = ["source__book__title", "target__book__title"]
    autocomplete_fields = ["source", "target"]


@admin.register(EditionBookLink)
class EditionBookLinkAdmin(admin.ModelAdmin):
    list_display = ["edition", "book", "role", "created_at"]
    list_filter = ["role", "created_at"]
    search_fields = ["edition__book__title", "book__title"]
    autocomplete_fields = ["edition", "book"]


@admin.register(Edition)
class EditionAdmin(admin.ModelAdmin):
    list_display = [
        "book",
        "display_publishers",
        "year",
        "status_badge",
        "is_best",
        "submitted_by",
        "submitted_at",
    ]
    list_filter = ["status", "is_best", "submitted_at"]
    search_fields = ["book__title", "volumes", "publishers__name", "editors__name"]
    readonly_fields = ["submitted_at", "approved_at"]
    actions = ["approve_editions", "reject_editions"]
    inlines = [
        EditionPublisherInline,
        EditionEditorInline,
        EditionBookLinkInline,
        EditionRelationInline,
        ApprovalLogInline,
    ]

    @admin.display(description="الناشرون")
    def display_publishers(self, obj):
        return "، ".join(obj.publishers.values_list("name", flat=True))

    def status_badge(self, obj):
        colors = {
            EditionStatus.PENDING: "#f9a825",
            EditionStatus.APPROVED: "#2e7d32",
            EditionStatus.REJECTED: "#c62828",
        }
        return format_html(
            '<span style="color: {};">{}</span>',
            colors.get(obj.status, "#000"),
            obj.get_status_display(),
        )

    status_badge.short_description = "الحالة"

    @admin.action(description="اعتمد الطبعات المحددة")
    def approve_editions(self, request, queryset):
        now = timezone.now()
        count = 0
        edition_ids = []
        for edition in queryset:
            old_status = edition.status
            edition.status = EditionStatus.APPROVED
            edition.approved_by = request.user
            edition.approved_at = now
            edition.save()
            ApprovalLog.objects.create(
                edition=edition,
                admin=request.user,
                old_status=old_status,
                new_status=EditionStatus.APPROVED,
            )
            edition_ids.append(edition.pk)
            count += 1
        admin_logger.info(
            "Admin %s approved %d edition(s): %s",
            request.user,
            count,
            edition_ids,
        )
        self.message_user(request, f"اعتمدنا {count} طبعة.", messages.SUCCESS)

    @admin.action(description="ارفض الطبعات المحددة")
    def reject_editions(self, request, queryset):
        if request.method == "POST" and "confirm_reject" in request.POST:
            reason = request.POST.get("rejection_reason", "").strip()
            count = 0
            edition_ids = []
            for edition in queryset:
                old_status = edition.status
                edition.status = EditionStatus.REJECTED
                edition.rejection_reason = reason
                edition.save()
                ApprovalLog.objects.create(
                    edition=edition,
                    admin=request.user,
                    old_status=old_status,
                    new_status=EditionStatus.REJECTED,
                    reason=reason,
                )
                edition_ids.append(edition.pk)
                count += 1
            admin_logger.info(
                "Admin %s rejected %d edition(s): %s reason=%r",
                request.user,
                count,
                edition_ids,
                reason,
            )
            self.message_user(request, f"رفضنا {count} طبعة.", messages.SUCCESS)
            return HttpResponseRedirect(request.get_full_path())

        context = {
            **self.admin_site.each_context(request),
            "title": "رفض طبعات",
            "editions": queryset,
            "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/encyclopedia/edition/reject_reason.html",
            context,
        )


@admin.register(NameRecord)
class NameRecordAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "status", "submitted_by", "submitted_at"]
    list_filter = ["kind", "status"]
    search_fields = ["name"]
    readonly_fields = ["submitted_at", "approved_at"]
    actions = ["approve_records", "reject_records"]
    kind = None  # override in subclass

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if self.kind is not None:
            qs = qs.filter(kind=self.kind)
        return qs

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj)
        if self.kind is not None and self.kind != NameRecordKind.PUBLISHER:
            fields = [f for f in fields if f != "city"]
        return fields

    def save_model(self, request, obj, form, change):
        if self.kind is not None and not obj.kind:
            obj.kind = self.kind
        super().save_model(request, obj, form, change)

    @admin.action(description="اعتمد الأسماء المحددة")
    def approve_records(self, request, queryset):
        now = timezone.now()
        count = queryset.update(
            status=NameRecordStatus.APPROVED,
            approved_by=request.user,
            approved_at=now,
        )
        admin_logger.info(
            "Admin %s approved %d name record(s): %s",
            request.user,
            count,
            list(queryset.values_list("pk", flat=True)),
        )
        self.message_user(request, f"اعتمدنا {count} اسم.", messages.SUCCESS)

    @admin.action(description="ارفض الأسماء المحددة")
    def reject_records(self, request, queryset):
        count = queryset.update(status=NameRecordStatus.REJECTED)
        admin_logger.info(
            "Admin %s rejected %d name record(s): %s",
            request.user,
            count,
            list(queryset.values_list("pk", flat=True)),
        )
        self.message_user(request, f"رفضنا {count} اسم.", messages.SUCCESS)


@admin.register(Author)
class AuthorAdmin(NameRecordAdmin):
    kind = NameRecordKind.AUTHOR


@admin.register(Editor)
class EditorAdmin(NameRecordAdmin):
    kind = NameRecordKind.EDITOR


@admin.register(Publisher)
class PublisherAdmin(NameRecordAdmin):
    kind = NameRecordKind.PUBLISHER


@admin.register(EditionEditSuggestion)
class EditionEditSuggestionAdmin(admin.ModelAdmin):
    list_display = ["edition", "suggested_by", "status", "created_at", "resolved_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["edition__book__title", "suggested_by__email", "suggested_by__username"]
    readonly_fields = ["created_at", "resolved_at"]
    actions = ["approve_suggestions", "reject_suggestions"]

    @admin.action(description="اعتمد الاقتراحات وطبّق التعديلات")
    def approve_suggestions(self, request, queryset):
        count = 0
        for suggestion in queryset.filter(status="pending"):
            suggestion.apply_to_edition(request.user)
            count += 1
        self.message_user(request, f"اعتمدنا {count} اقتراح تعديل.", messages.SUCCESS)

    @admin.action(description="ارفض الاقتراحات المحددة")
    def reject_suggestions(self, request, queryset):
        now = timezone.now()
        count = queryset.filter(status="pending").update(
            status="rejected",
            resolved_by=request.user,
            resolved_at=now,
        )
        self.message_user(request, f"رفضنا {count} اقتراح تعديل.", messages.SUCCESS)


@admin.register(EditionBookLinkSuggestion)
class EditionBookLinkSuggestionAdmin(admin.ModelAdmin):
    list_display = ["edition", "book", "role", "suggested_by", "status", "created_at"]
    list_filter = ["status", "role", "created_at"]
    search_fields = ["edition__book__title", "book__title", "suggested_by__email"]
    readonly_fields = ["created_at", "resolved_at"]
    actions = ["approve_suggestions", "reject_suggestions"]

    @admin.action(description="اعتمد الاقتراحات المحددة")
    def approve_suggestions(self, request, queryset):
        count = 0
        for suggestion in queryset.filter(status="pending"):
            suggestion.approve(request.user)
            count += 1
        self.message_user(
            request, f"اعتمدنا {count} اقتراح ربط.", messages.SUCCESS
        )

    @admin.action(description="ارفض الاقتراحات المحددة")
    def reject_suggestions(self, request, queryset):
        now = timezone.now()
        count = queryset.filter(status="pending").update(
            status=EditionBookLinkSuggestionStatus.REJECTED,
            resolved_by=request.user,
            resolved_at=now,
        )
        self.message_user(request, f"رفضنا {count} اقتراح ربط.", messages.SUCCESS)


@admin.register(EditionRelationSuggestion)
class EditionRelationSuggestionAdmin(admin.ModelAdmin):
    list_display = ["source", "target_display", "kind", "suggested_by", "status", "created_at"]
    list_filter = ["status", "kind", "created_at"]
    search_fields = ["source__book__title", "target__book__title", "suggested_by__email"]
    readonly_fields = ["created_at", "resolved_at"]
    actions = ["approve_suggestions", "reject_suggestions"]

    @admin.display(description="الطبعة المرتبطة")
    def target_display(self, obj):
        if obj.target:
            return str(obj.target)
        publishers = ", ".join(obj.target_data.get("publishers", []))
        year = obj.target_data.get("year")
        return f"طبعة جديدة: {publishers} {year or ''}".strip()

    @admin.action(description="اعتمد الاقتراحات المحددة")
    def approve_suggestions(self, request, queryset):
        count = 0
        for suggestion in queryset.filter(status="pending"):
            suggestion.approve(request.user)
            count += 1
        self.message_user(
            request, f"اعتمدنا {count} اقتراح علاقة.", messages.SUCCESS
        )

    @admin.action(description="ارفض الاقتراحات المحددة")
    def reject_suggestions(self, request, queryset):
        now = timezone.now()
        count = queryset.filter(status="pending").update(
            status=EditionRelationSuggestionStatus.REJECTED,
            resolved_by=request.user,
            resolved_at=now,
        )
        self.message_user(request, f"رفضنا {count} اقتراح علاقة.", messages.SUCCESS)
