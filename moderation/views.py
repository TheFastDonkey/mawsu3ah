"""Staff-only moderation dashboard views."""

import logging
from collections import Counter

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import models
from django.db.models import Count, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from encyclopedia.models import (
    ApprovalLog,
    BookCategory,
    Category,
    CategoryRequest,
    CategoryRequestStatus,
    CategorySuggestion,
    CategorySuggestionStatus,
    Edition,
    EditionBookLinkSuggestion,
    EditionBookLinkSuggestionStatus,
    EditionEditSuggestion,
    EditionEditSuggestionStatus,
    EditionRelationSuggestion,
    EditionRelationSuggestionStatus,
    EditionStatus,
    NameRecord,
    NameRecordKind,
    NameRecordStatus,
    Review,
)

admin_logger = logging.getLogger("mawsu3ah.admin")

# Human-readable labels used in the dashboard filters and item badges.
ITEM_TYPE_LABELS = {
    "edition": "طبعات جديدة",
    "edit": "تعديلات طبعات",
    "link": "روابط طبعة بكتاب",
    "relation": "علاقات بين طبعات",
    "category_suggestion": "اقتراحات تصنيفات",
    "category_request": "طلبات تصنيفات جديدة",
    "name_record": "أسماء مرجعية",
}


def _find_duplicates(edition):
    """Find approved editions that may duplicate the given edition."""
    book = edition.book
    qs = Edition.objects.filter(book=book, status=EditionStatus.APPROVED)
    volumes = (edition.volumes or "").strip()
    if volumes:
        return qs.filter(volumes=volumes)

    publishers = list(edition.publishers.values_list("pk", flat=True))
    if edition.year and publishers:
        return qs.filter(year=edition.year, publishers__in=publishers).distinct()
    if edition.year:
        return qs.filter(year=edition.year)
    if publishers:
        return qs.filter(publishers__in=publishers).distinct()
    return qs.filter(year__isnull=True)


def _edition_detail_title(edition):
    authors = "، ".join(a.name for a in edition.book.authors.all())
    return f"{edition.book.title} — {authors}"


def _edition_publishers_str(edition):
    return "، ".join(p.name for p in edition.publishers.all()) or "—"


def _build_edition_item(edition):
    publishers = _edition_publishers_str(edition)
    parts = [f"طبعة {publishers}"]
    if edition.year:
        parts.append(str(edition.year))
    if edition.volumes:
        parts.append(f"المجلدات {edition.volumes}")
    return {
        "type": "edition",
        "type_label": ITEM_TYPE_LABELS["edition"],
        "pk": edition.pk,
        "obj": edition,
        "title": _edition_detail_title(edition),
        "description": " · ".join(parts),
        "submitter": edition.submitted_by,
        "timestamp": edition.submitted_at,
        "detail_url": edition.get_absolute_url(),
        "approve_url": reverse(
            "moderation:approve_item", kwargs={"item_type": "edition", "pk": edition.pk}
        ),
        "reject_url": reverse(
            "moderation:reject_item", kwargs={"item_type": "edition", "pk": edition.pk}
        ),
        "extra": {"duplicates": list(_find_duplicates(edition)[:5])},
    }


def _build_edit_item(suggestion):
    edition = suggestion.edition
    changes = []
    if suggestion.year is not None:
        changes.append(f"السنة: {suggestion.year}")
    if suggestion.page_count is not None:
        changes.append(f"عدد الصفحات: {suggestion.page_count}")
    if suggestion.city:
        changes.append(f"المدينة: {suggestion.city}")
    if suggestion.volumes:
        changes.append(f"المجلدات: {suggestion.volumes}")
    if suggestion.proposed_publishers:
        changes.append(
            "الناشرون: " + "، ".join(str(p) for p in suggestion.proposed_publishers)
        )
    if suggestion.proposed_editors:
        changes.append(
            "المحققون: " + "، ".join(str(e) for e in suggestion.proposed_editors)
        )
    return {
        "type": "edit",
        "type_label": ITEM_TYPE_LABELS["edit"],
        "pk": suggestion.pk,
        "obj": suggestion,
        "title": f"تعديل مقترح لـ {_edition_detail_title(edition)}",
        "description": " · ".join(changes) or "لا توجد تفاصيل إضافية.",
        "submitter": suggestion.suggested_by,
        "timestamp": suggestion.created_at,
        "detail_url": edition.get_absolute_url(),
        "approve_url": reverse(
            "moderation:approve_item", kwargs={"item_type": "edit", "pk": suggestion.pk}
        ),
        "reject_url": reverse(
            "moderation:reject_item", kwargs={"item_type": "edit", "pk": suggestion.pk}
        ),
        "extra": None,
    }


def _build_link_item(suggestion):
    role_label = dict(EditionBookLinkSuggestion._meta.get_field("role").choices).get(
        suggestion.role, suggestion.role
    )
    return {
        "type": "link",
        "type_label": ITEM_TYPE_LABELS["link"],
        "pk": suggestion.pk,
        "obj": suggestion,
        "title": f"ربط {_edition_detail_title(suggestion.edition)} بكتاب {suggestion.book.title}",
        "description": f"العلاقة: {role_label}",
        "submitter": suggestion.suggested_by,
        "timestamp": suggestion.created_at,
        "detail_url": suggestion.edition.get_absolute_url(),
        "approve_url": reverse(
            "moderation:approve_item", kwargs={"item_type": "link", "pk": suggestion.pk}
        ),
        "reject_url": reverse(
            "moderation:reject_item", kwargs={"item_type": "link", "pk": suggestion.pk}
        ),
        "extra": None,
    }


def _build_relation_item(suggestion):
    kind_label = dict(EditionRelationSuggestion._meta.get_field("kind").choices).get(
        suggestion.kind, suggestion.kind
    )
    if suggestion.target_id:
        title = f"علاقة {kind_label} بين {_edition_detail_title(suggestion.source)} و{_edition_detail_title(suggestion.target)}"
    else:
        publishers = "، ".join(suggestion.target_data.get("publishers", []))
        year = suggestion.target_data.get("year")
        title = f"علاقة {kind_label}: طبعة جديدة ({publishers} {year or ''}) ← {_edition_detail_title(suggestion.source)}"
    return {
        "type": "relation",
        "type_label": ITEM_TYPE_LABELS["relation"],
        "pk": suggestion.pk,
        "obj": suggestion,
        "title": title,
        "description": suggestion.reason or "",
        "submitter": suggestion.suggested_by,
        "timestamp": suggestion.created_at,
        "detail_url": suggestion.source.get_absolute_url(),
        "approve_url": reverse(
            "moderation:approve_item",
            kwargs={"item_type": "relation", "pk": suggestion.pk},
        ),
        "reject_url": reverse(
            "moderation:reject_item",
            kwargs={"item_type": "relation", "pk": suggestion.pk},
        ),
        "extra": None,
    }


def _build_category_suggestion_item(suggestion):
    return {
        "type": "category_suggestion",
        "type_label": ITEM_TYPE_LABELS["category_suggestion"],
        "pk": suggestion.pk,
        "obj": suggestion,
        "title": f"إضافة تصنيف «{suggestion.name}» إلى {suggestion.book.title}",
        "description": suggestion.reason or "",
        "submitter": suggestion.suggested_by,
        "timestamp": suggestion.created_at,
        "detail_url": suggestion.book.get_absolute_url(),
        "approve_url": reverse(
            "moderation:approve_item",
            kwargs={"item_type": "category_suggestion", "pk": suggestion.pk},
        ),
        "reject_url": reverse(
            "moderation:reject_item",
            kwargs={"item_type": "category_suggestion", "pk": suggestion.pk},
        ),
        "extra": None,
    }


def _build_category_request_item(request_obj):
    return {
        "type": "category_request",
        "type_label": ITEM_TYPE_LABELS["category_request"],
        "pk": request_obj.pk,
        "obj": request_obj,
        "title": f"طلب تصنيف جديد: {request_obj.name}",
        "description": "",
        "submitter": request_obj.suggested_by,
        "timestamp": request_obj.created_at,
        "detail_url": reverse("category_list"),
        "approve_url": reverse(
            "moderation:approve_item",
            kwargs={"item_type": "category_request", "pk": request_obj.pk},
        ),
        "reject_url": reverse(
            "moderation:reject_item",
            kwargs={"item_type": "category_request", "pk": request_obj.pk},
        ),
        "extra": None,
    }


def _build_name_record_item(record):
    kind_label = dict(NameRecordKind.choices).get(record.kind, record.kind)
    return {
        "type": "name_record",
        "type_label": ITEM_TYPE_LABELS["name_record"],
        "pk": record.pk,
        "obj": record,
        "title": f"{kind_label}: {record.name}",
        "description": "",
        "submitter": record.submitted_by,
        "timestamp": record.submitted_at,
        "detail_url": (
            reverse("author_detail", kwargs={"slug": record.slug})
            if record.kind == NameRecordKind.AUTHOR
            else reverse("editor_detail", kwargs={"slug": record.slug})
            if record.kind == NameRecordKind.EDITOR
            else reverse("publisher_detail", kwargs={"slug": record.slug})
        ),
        "approve_url": reverse(
            "moderation:approve_item",
            kwargs={"item_type": "name_record", "pk": record.pk},
        ),
        "reject_url": reverse(
            "moderation:reject_item",
            kwargs={"item_type": "name_record", "pk": record.pk},
        ),
        "extra": None,
    }


def _fetch_pending_items():
    """Return a unified list of all pending moderation items, newest first."""
    items = []

    editions = (
        Edition.objects.filter(status=EditionStatus.PENDING)
        .select_related("book", "submitted_by")
        .prefetch_related("book__authors", "publishers")
        .order_by("submitted_at")
    )
    for edition in editions:
        items.append(_build_edition_item(edition))

    edit_suggestions = (
        EditionEditSuggestion.objects.filter(status=EditionEditSuggestionStatus.PENDING)
        .select_related("edition__book", "suggested_by")
        .prefetch_related("edition__book__authors")
        .order_by("-created_at")
    )
    for suggestion in edit_suggestions:
        items.append(_build_edit_item(suggestion))

    link_suggestions = (
        EditionBookLinkSuggestion.objects.filter(
            status=EditionBookLinkSuggestionStatus.PENDING
        )
        .select_related("edition__book", "book", "suggested_by")
        .prefetch_related("edition__book__authors")
        .order_by("-created_at")
    )
    for suggestion in link_suggestions:
        items.append(_build_link_item(suggestion))

    relation_suggestions = (
        EditionRelationSuggestion.objects.filter(
            status=EditionRelationSuggestionStatus.PENDING
        )
        .select_related("source__book", "target__book", "suggested_by")
        .prefetch_related("source__book__authors", "target__book__authors")
        .order_by("-created_at")
    )
    for suggestion in relation_suggestions:
        items.append(_build_relation_item(suggestion))

    category_suggestions = (
        CategorySuggestion.objects.filter(status=CategorySuggestionStatus.PENDING)
        .select_related("book", "suggested_by")
        .order_by("-created_at")
    )
    for suggestion in category_suggestions:
        items.append(_build_category_suggestion_item(suggestion))

    category_requests = (
        CategoryRequest.objects.filter(status=CategoryRequestStatus.PENDING)
        .select_related("suggested_by")
        .order_by("-created_at")
    )
    for request_obj in category_requests:
        items.append(_build_category_request_item(request_obj))

    name_records = (
        NameRecord.objects.filter(status=NameRecordStatus.PENDING)
        .select_related("submitted_by")
        .order_by("-submitted_at")
    )
    for record in name_records:
        items.append(_build_name_record_item(record))

    items.sort(key=lambda x: x["timestamp"] or timezone.now(), reverse=True)
    return items


@staff_member_required
@login_required
def moderation_dashboard(request):
    """Unified moderation dashboard showing all pending requests with filters."""
    all_items = _fetch_pending_items()
    counts = dict.fromkeys(ITEM_TYPE_LABELS, 0)
    counts.update(Counter(item["type"] for item in all_items))
    type_filter = request.GET.get("type")

    if type_filter and type_filter in ITEM_TYPE_LABELS:
        items = [item for item in all_items if item["type"] == type_filter]
    else:
        items = all_items
        type_filter = "all"

    paginator = Paginator(items, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "moderation/dashboard.html",
        {
            "page_obj": page_obj,
            "count": paginator.count,
            "total_count": len(all_items),
            "type_filter": type_filter,
            "counts": counts,
            "type_labels": ITEM_TYPE_LABELS,
        },
    )


# The old queue view now renders the unified dashboard.
moderation_queue = moderation_dashboard


def _approve_edition(edition, admin_user):
    old_status = edition.status
    now = timezone.now()
    edition.status = EditionStatus.APPROVED
    edition.approved_by = admin_user
    edition.approved_at = now
    edition.save()
    ApprovalLog.objects.create(
        edition=edition,
        admin=admin_user,
        old_status=old_status,
        new_status=EditionStatus.APPROVED,
    )


def _reject_edition(edition, admin_user, reason=""):
    old_status = edition.status
    edition.status = EditionStatus.REJECTED
    edition.rejection_reason = reason
    edition.save()
    ApprovalLog.objects.create(
        edition=edition,
        admin=admin_user,
        old_status=old_status,
        new_status=EditionStatus.REJECTED,
        reason=reason,
    )


def _approve_category_suggestion(suggestion, admin_user):
    now = timezone.now()
    name = suggestion.name.strip()
    category, _created = Category.objects.get_or_create(name=name)
    suggestion.final_category = category
    suggestion.status = CategorySuggestionStatus.APPROVED
    suggestion.resolved_by = admin_user
    suggestion.resolved_at = now
    suggestion.save()
    if not suggestion.book.categories.filter(pk=category.pk).exists():
        next_order = BookCategory.objects.filter(book=suggestion.book).count()
        BookCategory.objects.create(
            book=suggestion.book,
            category=category,
            order=next_order,
        )


def _approve_category_request(request_obj, admin_user):
    now = timezone.now()
    category, _created = Category.objects.get_or_create(name=request_obj.name.strip())
    request_obj.final_category = category
    request_obj.status = CategoryRequestStatus.APPROVED
    request_obj.resolved_by = admin_user
    request_obj.resolved_at = now
    request_obj.save()


def _reject_suggestion(obj, admin_user, reason=""):
    """Generic reject for suggestion-like objects that have status/resolved fields."""
    obj.status = "rejected"
    obj.resolved_by = admin_user
    obj.resolved_at = timezone.now()
    update_fields = ["status", "resolved_by", "resolved_at"]
    if reason and hasattr(obj, "admin_note"):
        obj.admin_note = reason
        update_fields.append("admin_note")
    obj.save(update_fields=update_fields)


def _approve_name_record(record, admin_user):
    record.status = NameRecordStatus.APPROVED
    record.approved_by = admin_user
    record.approved_at = timezone.now()
    record.save(update_fields=["status", "approved_by", "approved_at"])


def _reject_name_record(record, admin_user, reason=""):
    record.status = NameRecordStatus.REJECTED
    record.rejected_by = admin_user
    record.rejected_at = timezone.now()
    record.save(update_fields=["status", "rejected_by", "rejected_at"])


_APPROVE_HANDLERS = {
    "edition": (Edition, EditionStatus.PENDING, _approve_edition),
    "edit": (EditionEditSuggestion, EditionEditSuggestionStatus.PENDING, lambda obj, user: obj.apply_to_edition(user)),
    "link": (EditionBookLinkSuggestion, EditionBookLinkSuggestionStatus.PENDING, lambda obj, user: obj.approve(user)),
    "relation": (EditionRelationSuggestion, EditionRelationSuggestionStatus.PENDING, lambda obj, user: obj.approve(user)),
    "category_suggestion": (CategorySuggestion, CategorySuggestionStatus.PENDING, _approve_category_suggestion),
    "category_request": (CategoryRequest, CategoryRequestStatus.PENDING, _approve_category_request),
    "name_record": (NameRecord, NameRecordStatus.PENDING, _approve_name_record),
}

_REJECT_HANDLERS = {
    "edition": (Edition, EditionStatus.PENDING, _reject_edition),
    "edit": (EditionEditSuggestion, EditionEditSuggestionStatus.PENDING, _reject_suggestion),
    "link": (EditionBookLinkSuggestion, EditionBookLinkSuggestionStatus.PENDING, _reject_suggestion),
    "relation": (EditionRelationSuggestion, EditionRelationSuggestionStatus.PENDING, _reject_suggestion),
    "category_suggestion": (CategorySuggestion, CategorySuggestionStatus.PENDING, _reject_suggestion),
    "category_request": (CategoryRequest, CategoryRequestStatus.PENDING, _reject_suggestion),
    "name_record": (NameRecord, NameRecordStatus.PENDING, _reject_name_record),
}


def _resolve_item(request, item_type, pk, handlers, action_label):
    if item_type not in handlers:
        messages.error(request, "نوع الطلب غير معروف.")
        return redirect("moderation:moderation_dashboard")

    model, pending_status, handler = handlers[item_type]
    obj = get_object_or_404(model, pk=pk, status=pending_status)
    reason = request.POST.get("rejection_reason", "").strip()

    if action_label == "reject":
        handler(obj, request.user, reason)
    else:
        handler(obj, request.user)

    arabic_action = "اعتماد" if action_label == "approve" else "رفض"
    admin_logger.info(
        "Admin %s %s %s %s via dashboard",
        request.user,
        action_label,
        item_type,
        obj.pk,
    )
    messages.success(request, f"تم {arabic_action} الطلب بنجاح.")
    return redirect("moderation:moderation_dashboard")


@ratelimit(key="user", rate="60/m", method="POST")
@require_POST
@staff_member_required
@login_required
def approve_item(request, item_type, pk):
    """Approve any pending moderation item from the dashboard."""
    return _resolve_item(request, item_type, pk, _APPROVE_HANDLERS, "approve")


@ratelimit(key="user", rate="60/m", method="POST")
@require_POST
@staff_member_required
@login_required
def reject_item(request, item_type, pk):
    """Reject any pending moderation item from the dashboard."""
    return _resolve_item(request, item_type, pk, _REJECT_HANDLERS, "reject")


@staff_member_required
@login_required
def moderation_comments(request):
    """List reviews for moderation, newest first."""
    reviews = (
        Review.objects.select_related("user", "edition", "edition__book")
        .annotate(vote_score=Coalesce(Sum("votes__value"), 0))
        .order_by("-created_at")
    )
    paginator = Paginator(reviews, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "moderation/comments.html",
        {
            "page_obj": page_obj,
            "count": paginator.count,
        },
    )


@ratelimit(key="user", rate="60/m", method="POST")
@require_POST
@staff_member_required
@login_required
def review_hide_toggle(request, review_public_id):
    """Hide or unhide a review from the moderation dashboard."""
    review = get_object_or_404(
        Review.objects.select_related("edition"),
        public_id=review_public_id,
    )
    if review.hidden:
        review.hidden = False
        review.hidden_by = None
        review.hidden_at = None
        action = "unhid"
    else:
        review.hidden = True
        review.hidden_by = request.user
        review.hidden_at = timezone.now()
        action = "hid"
    review.save()
    admin_logger.info(
        "Admin %s %s review %s via dashboard",
        request.user,
        action,
        review.pk,
    )
    return redirect("moderation:moderation_comments")


@staff_member_required
@login_required
def report_queue(request):
    """List reviews with unresolved reports, ordered by report count."""
    reviews = (
        Review.objects.filter(reports__resolved=False)
        .select_related("user", "edition", "edition__book")
        .annotate(
            report_count=Count("reports", filter=models.Q(reports__resolved=False)),
            latest_report=models.Max("reports__created_at", filter=models.Q(reports__resolved=False)),
        )
        .order_by("-report_count", "-latest_report")
    )
    paginator = Paginator(reviews, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "moderation/report_queue.html",
        {
            "page_obj": page_obj,
            "count": paginator.count,
        },
    )


@ratelimit(key="user", rate="60/m", method="POST")
@require_POST
@staff_member_required
@login_required
def dismiss_reports(request, review_public_id):
    """Mark all reports on a review as resolved."""
    review = get_object_or_404(
        Review.objects.select_related("edition"),
        public_id=review_public_id,
    )
    now = timezone.now()
    count = review.reports.filter(resolved=False).update(
        resolved=True,
        resolved_by=request.user,
        resolved_at=now,
    )
    admin_logger.info(
        "Admin %s dismissed %d report(s) for review %s via dashboard",
        request.user,
        count,
        review.pk,
    )
    return redirect("moderation:report_queue")
