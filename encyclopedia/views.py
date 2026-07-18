import json
import mimetypes
import uuid
from pathlib import PurePath

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile, File
from django.core.files.storage import default_storage
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import (
    Case,
    CharField,
    Count,
    IntegerField,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django_ratelimit.decorators import ratelimit

from accounts.models import User

from .edition_utils import annotate_edition_liked_by_expert, attach_edition_user_votes
from .forms import (
    CategoryRequestForm,
    CategorySuggestionForm,
    EditionBookLinkSuggestionForm,
    EditionEditSuggestionForm,
    EditionRelationSuggestionForm,
    EditionSubmissionForm,
)
from .image_utils import is_safe_temp_cover_path, process_cover_image
from .models import (
    ApprovalLog,
    Author,
    Book,
    Category,
    CategoryRequest,
    CategorySuggestion,
    CategorySuggestionStatus,
    CategorySuggestionVote,
    Edition,
    EditionBookLink,
    EditionBookLinkRole,
    EditionBookLinkSuggestionStatus,
    EditionRelation,
    EditionRelationSuggestionStatus,
    EditionStatus,
    Editor,
    NameRecord,
    NameRecordKind,
    NameRecordStatus,
    Publisher,
)
from .review_utils import attach_review_glance
from .search import search_books
from .text_utils import normalize_arabic

NAMES_LIST_PAGE_SIZE = 50


def _book_category_suggestions(book, user):
    """Return pending category suggestions for a book, annotated with vote score and user vote."""
    suggestions = (
        book.category_suggestions.filter(
            status=CategorySuggestionStatus.PENDING,
        )
        .exclude(final_category__in=book.categories.all())
        .select_related("final_category")
        .annotate(
            vote_score=Coalesce(
                Sum("votes__value"),
                Value(0, output_field=IntegerField()),
            ),
        )
    )

    if user and user.is_authenticated:
        user_votes = {
            vote.suggestion_id: vote.value
            for vote in CategorySuggestionVote.objects.filter(suggestion__in=suggestions, user=user)
        }
        for suggestion in suggestions:
            suggestion.user_vote = user_votes.get(suggestion.pk)

    return suggestions


def _approve_edition(edition, user):
    """Auto-approve an edition submitted by an expert user and log the change."""
    if edition.status == EditionStatus.APPROVED:
        return
    old_status = edition.status
    edition.status = EditionStatus.APPROVED
    edition.approved_by = user
    edition.approved_at = timezone.now()
    edition.save(update_fields=["status", "approved_by", "approved_at"])
    ApprovalLog.objects.create(
        edition=edition,
        admin=user,
        old_status=old_status,
        new_status=EditionStatus.APPROVED,
    )


def home(request):
    categories = Category.objects.all()[:8]
    editions = annotate_edition_liked_by_expert(
        Edition.objects.select_related("book", "submitted_by")
        .prefetch_related("book__authors", "publishers", "editors")
        .filter(status=EditionStatus.APPROVED)
        .annotate(vote_score=Coalesce(Sum("votes__value"), Value(0, output_field=IntegerField())))
        .order_by("-submitted_at")[:6]
    )
    approved_editions_count = Edition.objects.filter(status=EditionStatus.APPROVED).count()
    experts_count = User.objects.filter(is_expert=True).count()
    members_count = User.objects.filter(is_active=True).count()
    books_count = (
        Book.objects.filter(editions__status=EditionStatus.APPROVED).values("id").distinct().count()
    )
    editions = attach_review_glance(editions)
    editions = attach_edition_user_votes(editions, request.user)
    return render(
        request,
        "home.html",
        {
            "categories": categories,
            "editions": editions,
            "approved_editions_count": approved_editions_count,
            "experts_count": experts_count,
            "members_count": members_count,
            "books_count": books_count,
        },
    )


def _resolve_category(slug):
    if not slug:
        return None
    return Category.objects.filter(slug=slug).first()


def search(request):
    query = (request.GET.get("q") or "").strip()
    category_slug = request.GET.get("category")
    category = _resolve_category(category_slug)

    if query:
        results = search_books(query, category_slug=category_slug)
    else:
        results = Book.objects.filter(editions__status=EditionStatus.APPROVED).distinct()
        if category:
            results = results.filter(categories__path__startswith=category.path)
        results = results.annotate(
            total_score=Coalesce(
                Sum("editions__votes__value"), Value(0, output_field=IntegerField())
            )
        ).order_by("-total_score", "title")

    paginator = Paginator(results, 12)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    categories = Category.objects.order_by("path")

    return render(
        request,
        "encyclopedia/search_results.html",
        {
            "query": query,
            "category_slug": category_slug,
            "page_obj": page_obj,
            "categories": categories,
            "count": paginator.count,
        },
    )


def search_suggestions(request):
    query = (request.GET.get("q") or "").strip()
    books = []
    if query:
        results = search_books(query)
        books = list(results[:3])
    return render(
        request,
        "encyclopedia/search_suggestions.html",
        {
            "query": query,
            "books": books,
        },
    )


def _name_suggestions(request, kind, field_id, param_name):
    query = (request.GET.get("q") or request.GET.get(param_name) or "").strip()
    field_id = request.GET.get("field_id") or field_id
    suggestions = []
    if query:
        norm_query = normalize_arabic(query)
        candidates = (
            NameRecord.objects.filter(
                kind=kind,
                status=NameRecordStatus.APPROVED,
            )
            .values_list("name", flat=True)
            .distinct()
            .order_by("name")
        )
        suggestions = [
            name for name in candidates if norm_query in normalize_arabic(name)
        ][:10]
    return render(
        request,
        "encyclopedia/partials/field_suggestions.html",
        {
            "query": query,
            "suggestions": suggestions,
            "field_id": field_id,
        },
    )


@ratelimit(key="ip", rate="30/m")
def author_suggestions(request):
    return _name_suggestions(
        request, NameRecordKind.AUTHOR, "id_new_book_author_search", "new_book_author_search"
    )


@ratelimit(key="ip", rate="30/m")
def editor_suggestions(request):
    return _name_suggestions(request, NameRecordKind.EDITOR, "id_editor_search", "editor_search")


@ratelimit(key="ip", rate="30/m")
def publisher_suggestions(request):
    return _name_suggestions(
        request, NameRecordKind.PUBLISHER, "id_publisher_search", "publisher_search"
    )


@ratelimit(key="ip", rate="30/m")
def edition_suggestions(request):
    query = (request.GET.get("q") or request.GET.get("edition_search") or "").strip()
    book_pk = request.GET.get("book")
    exclude_public_id = request.GET.get("exclude")
    editions = []
    if query:
        norm_query = normalize_arabic(query)
        candidates = (
            Edition.objects.filter(status=EditionStatus.APPROVED)
            .select_related("book")
            .prefetch_related("publishers")
            .order_by("-submitted_at")
        )
        if book_pk:
            candidates = candidates.filter(book_id=book_pk)
        if exclude_public_id:
            candidates = candidates.exclude(public_id=exclude_public_id)
        for edition in candidates:
            parts = [edition.book.title]
            parts.extend(edition.publishers.values_list("name", flat=True))
            if edition.year:
                parts.append(str(edition.year))
            if edition.volumes:
                parts.append(edition.volumes)
            text = " ".join(str(p) for p in parts)
            if norm_query in normalize_arabic(text):
                editions.append(edition)
            if len(editions) >= 5:
                break
    return render(
        request,
        "encyclopedia/partials/edition_suggestions.html",
        {
            "query": query,
            "editions": editions,
            "field_id": request.GET.get("field_id", "id_edition"),
            "text_field_id": request.GET.get("text_field_id", "id_edition_search"),
        },
    )


@ratelimit(key="ip", rate="30/m")
def book_suggestions(request):
    query = (request.GET.get("q") or request.GET.get("existing_book_search") or "").strip()
    books = []
    if query:
        norm_query = normalize_arabic(query)
        candidates = (
            Book.objects.prefetch_related("authors")
            .order_by("title")
            .distinct()
        )
        for book in candidates:
            if norm_query in normalize_arabic(book.title):
                books.append(book)
                continue
            for author in book.authors.all():
                if norm_query in normalize_arabic(author.name):
                    books.append(book)
                    break
            if len(books) >= 5:
                break
        books = books[:5]
    return render(
        request,
        "encyclopedia/partials/book_suggestions.html",
        {
            "query": query,
            "books": books,
        },
    )


def author_detail(request, slug):
    record = get_object_or_404(NameRecord, slug=slug, kind=NameRecordKind.AUTHOR)
    first_cover = (
        Edition.objects.filter(
            book=OuterRef("pk"),
            status=EditionStatus.APPROVED,
        )
        .exclude(cover_image="")
        .order_by("-is_best", "-submitted_at")
        .values("cover_image")[:1]
    )
    books = (
        Book.objects.filter(
            authors=record,
            editions__status=EditionStatus.APPROVED,
        )
        .prefetch_related("authors")
        .annotate(
            approved_edition_count=Count(
                "editions",
                filter=Q(editions__status=EditionStatus.APPROVED),
            ),
            first_cover_image=Subquery(first_cover),
        )
        .distinct()
        .order_by("title")
    )
    return render(
        request,
        "encyclopedia/author_detail.html",
        {"record": record, "books": books},
    )


def editor_detail(request, slug):
    record = get_object_or_404(NameRecord, slug=slug, kind=NameRecordKind.EDITOR)
    editions = annotate_edition_liked_by_expert(
        Edition.objects.filter(
            editors=record,
            status=EditionStatus.APPROVED,
        )
        .select_related("book", "submitted_by")
        .prefetch_related("book__authors", "publishers", "editors")
        .annotate(vote_score=Coalesce(Sum("votes__value"), Value(0, output_field=IntegerField())))
        .order_by("-vote_score", "-submitted_at")
    )
    return render(
        request,
        "encyclopedia/editor_detail.html",
        {
            "record": record,
            "editions": attach_edition_user_votes(attach_review_glance(editions), request.user),
        },
    )


def publisher_detail(request, slug):
    record = get_object_or_404(NameRecord, slug=slug, kind=NameRecordKind.PUBLISHER)
    editions = annotate_edition_liked_by_expert(
        Edition.objects.filter(
            publishers=record,
            status=EditionStatus.APPROVED,
        )
        .select_related("book", "submitted_by")
        .prefetch_related("book__authors", "publishers", "editors")
        .annotate(vote_score=Coalesce(Sum("votes__value"), Value(0, output_field=IntegerField())))
        .order_by("-vote_score", "-submitted_at")
    )
    return render(
        request,
        "encyclopedia/publisher_detail.html",
        {
            "record": record,
            "editions": attach_edition_user_votes(attach_review_glance(editions), request.user),
        },
    )


def author_list(request):
    authors = (
        Author.objects.filter(status=NameRecordStatus.APPROVED)
        .annotate(
            book_count=Count(
                "authored_books",
                filter=Q(authored_books__editions__status=EditionStatus.APPROVED),
                distinct=True,
            )
        )
        .filter(book_count__gt=0)
        .order_by("name")
    )
    paginator = Paginator(authors, NAMES_LIST_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "encyclopedia/author_list.html",
        {"page_obj": page_obj},
    )


def publisher_list(request):
    publishers = (
        Publisher.objects.filter(status=NameRecordStatus.APPROVED)
        .annotate(
            edition_count=Count(
                "published_editions",
                filter=Q(published_editions__status=EditionStatus.APPROVED),
                distinct=True,
            )
        )
        .filter(edition_count__gt=0)
        .order_by("name")
    )
    paginator = Paginator(publishers, NAMES_LIST_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "encyclopedia/publisher_list.html",
        {"page_obj": page_obj},
    )


def editor_list(request):
    editors = (
        Editor.objects.filter(status=NameRecordStatus.APPROVED)
        .annotate(
            edition_count=Count(
                "edited_editions",
                filter=Q(edited_editions__status=EditionStatus.APPROVED),
                distinct=True,
            )
        )
        .filter(edition_count__gt=0)
        .order_by("name")
    )
    paginator = Paginator(editors, NAMES_LIST_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "encyclopedia/editor_list.html",
        {"page_obj": page_obj},
    )


def category_list(request):
    categories = Category.objects.prefetch_related("children").order_by("path")
    roots = [category for category in categories if category.parent_id is None]

    count_map = {}
    for category in categories:
        count_map[category.pk] = (
            Book.objects.filter(
                categories__path__startswith=category.path,
                editions__status=EditionStatus.APPROVED,
            )
            .distinct()
            .count()
        )
        category.subtree_book_count = count_map[category.pk]
        category.approved_book_count = category.subtree_book_count

    for category in categories:
        cache = getattr(category, "_prefetched_objects_cache", {})
        for child in cache.get("children", []):
            child.subtree_book_count = count_map.get(child.pk, 0)
            child.approved_book_count = child.subtree_book_count

    return render(
        request,
        "encyclopedia/category_list.html",
        {"categories": roots, "roots": roots},
    )


def category_detail(request, category_path):
    segments = [segment for segment in (category_path or "").split("/") if segment]
    if not segments:
        raise Http404

    target_slug = segments[-1]
    category = get_object_or_404(Category, slug=target_slug)

    ancestor_slugs = [ancestor.slug for ancestor in category.ancestors]
    if ancestor_slugs != segments[:-1]:
        raise Http404

    books = (
        Book.objects.filter(
            categories__path__startswith=category.path,
            editions__status=EditionStatus.APPROVED,
        )
        .prefetch_related("authors")
        .annotate(
            approved_edition_count=Count(
                "editions",
                filter=Q(editions__status=EditionStatus.APPROVED),
            )
        )
        .distinct()
        .order_by("title")
    )
    children = category.children.all()
    return render(
        request,
        "encyclopedia/category_detail.html",
        {
            "category": category,
            "ancestors": category.ancestors,
            "children": children,
            "books": books,
        },
    )


@ratelimit(key="ip", rate="30/m")
def category_autocomplete(request):
    query = (request.GET.get("q") or "").strip()
    categories = []
    if query:
        norm_query = normalize_arabic(query)
        categories = [
            category
            for category in Category.objects.order_by("path")
            if norm_query in normalize_arabic(category.name)
        ][:10]
    for category in categories:
        category.url_path = category.get_url_path()
    return render(
        request,
        "encyclopedia/partials/category_autocomplete_results.html",
        {
            "categories": categories,
            "query": query,
        },
    )


@ratelimit(key="ip", rate="30/m")
def category_suggestions(request):
    query = (request.GET.get("new_book_category_search") or request.GET.get("q") or "").strip()
    categories = []
    if query:
        norm_query = normalize_arabic(query)
        categories = [
            category
            for category in Category.objects.order_by("path")
            if norm_query in normalize_arabic(category.name)
        ][:10]
    for category in categories:
        category.url_path = category.get_url_path()
    return render(
        request,
        "encyclopedia/partials/category_chip_suggestions.html",
        {
            "categories": categories,
            "query": query,
        },
    )


@ratelimit(key="ip", rate="30/h", method="POST")
@ratelimit(key="user", rate="10/h", method="POST")
@login_required
def request_category(request):
    if request.method == "POST":
        form = CategoryRequestForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data["name"]
            with transaction.atomic():
                category_request, created = CategoryRequest.objects.get_or_create(
                    name=name,
                    defaults={"suggested_by": request.user},
                )
                if not created:
                    category_request.suggested_by = request.user
                    category_request.save(update_fields=["suggested_by"])

            if settings.ADMINS:
                subject = f"طلب تصنيف جديد: {category_request.name}"
                body = render_to_string(
                    "encyclopedia/emails/category_request.txt",
                    {
                        "category_request": category_request,
                        "user": request.user,
                        "url": request.build_absolute_uri(
                            reverse("admin:encyclopedia_categoryrequest_changelist")
                        ),
                    },
                )
                send_mail(
                    subject=subject,
                    message=body,
                    from_email=settings.DEFAULT_FROM_EMAIL or None,
                    recipient_list=[email for _name, email in settings.ADMINS],
                    fail_silently=True,
                )

            return render(
                request,
                "encyclopedia/partials/category_request_success.html",
            )
    else:
        form = CategoryRequestForm()

    return render(
        request,
        "encyclopedia/partials/category_request_form.html",
        {"form": form},
    )


def book_detail(request, slug):
    book = get_object_or_404(
        Book.objects.prefetch_related("categories", "authors"),
        slug=slug,
    )
    expert_first = request.GET.get("expert_first") == "1"
    original_only = request.GET.get("original_only") == "1"

    editions = (
        Edition.objects.filter(
            Q(book=book) | Q(book_links__book=book),
            status=EditionStatus.APPROVED,
        )
        .select_related("submitted_by", "book")
        .prefetch_related(
            "publishers",
            "editors",
            "book__authors",
            Prefetch(
                "related_targets",
                queryset=EditionRelation.objects.select_related("target"),
            ),
            Prefetch(
                "related_sources",
                queryset=EditionRelation.objects.select_related("source"),
            ),
        )
        .annotate(
            link_role=Case(
                When(book=book, then=Value("primary")),
                default=Subquery(
                    EditionBookLink.objects.filter(edition=OuterRef("pk"), book=book).values(
                        "role"
                    )[:1]
                ),
                output_field=CharField(),
            ),
            vote_score=Coalesce(
                Sum("votes__value", filter=Q(votes__book_context=book)),
                Value(0, output_field=IntegerField()),
            ),
        )
        .distinct()
    )
    editions = annotate_edition_liked_by_expert(editions, context_book=book)

    if original_only:
        editions = editions.exclude(
            link_role__in=[
                EditionBookLinkRole.COMMENTARY,
                EditionBookLinkRole.ANTHOLOGY,
            ]
        )

    if expert_first:
        editions = editions.order_by(
            "-is_best",
            "-liked_by_expert",
            "-vote_score",
            "-submitted_at",
        )
    else:
        editions = editions.order_by("-vote_score", "-submitted_at")

    has_pending_link_suggestion = False
    if request.user.is_authenticated:
        has_pending_link_suggestion = book.book_link_suggestions.filter(
            suggested_by=request.user,
            status=EditionBookLinkSuggestionStatus.PENDING,
        ).exists()

    return render(
        request,
        "encyclopedia/book_detail.html",
        {
            "book": book,
            "editions": attach_edition_user_votes(
                attach_review_glance(editions), request.user, context_book=book
            ),
            "expert_first": expert_first,
            "original_only": original_only,
            "category_suggestions": _book_category_suggestions(book, request.user),
            "has_pending_link_suggestion": has_pending_link_suggestion,
            "context_book": book,
        },
    )


@ratelimit(key="ip", rate="30/h", method="POST")
@ratelimit(key="user", rate="10/h", method="POST")
@login_required
def suggest_category(request, slug):
    book = get_object_or_404(Book, slug=slug)
    if request.method == "POST":
        form = CategorySuggestionForm(request.POST, book=book)
        if form.is_valid():
            category = form.cleaned_data["category"]
            with transaction.atomic():
                suggestion, created = CategorySuggestion.objects.get_or_create(
                    book=book,
                    final_category=category,
                    defaults={
                        "name": category.name,
                        "suggested_by": request.user,
                    },
                )
                vote, _ = CategorySuggestionVote.objects.get_or_create(
                    suggestion=suggestion,
                    user=request.user,
                    defaults={"value": CategorySuggestionVote.VoteValue.LIKE},
                )

            response = render(
                request,
                "encyclopedia/partials/category_suggestion_success.html",
                {"book": book},
            )
            response["HX-Trigger"] = "refreshCategoryKicker"
            return response
    else:
        form = CategorySuggestionForm(book=book)

    return render(
        request,
        "encyclopedia/partials/category_suggestion_form.html",
        {"book": book, "form": form},
    )


def book_categories_kicker(request, slug):
    book = get_object_or_404(Book, slug=slug)
    return render(
        request,
        "encyclopedia/partials/book_categories_kicker.html",
        {
            "book": book,
            "category_suggestions": _book_category_suggestions(book, request.user),
        },
    )


@ratelimit(key="ip", rate="30/h", method="POST")
@ratelimit(key="user", rate="10/h", method="POST")
@login_required
def suggest_edition_link(request, slug):
    book = get_object_or_404(Book, slug=slug)
    if request.method == "POST":
        form = EditionBookLinkSuggestionForm(request.POST, book=book)
        if form.is_valid():
            with transaction.atomic():
                suggestion = form.save(commit=False)
                suggestion.book = book
                suggestion.suggested_by = request.user
                suggestion.status = "pending"
                suggestion.save()
                approved = False
                if request.user.is_expert:
                    suggestion.approve(request.user)
                    approved = True
            return render(
                request,
                "encyclopedia/partials/edition_link_suggestion_success.html",
                {"book": book, "approved": approved},
            )
    else:
        form = EditionBookLinkSuggestionForm(book=book)

    return render(
        request,
        "encyclopedia/partials/edition_link_suggestion_form.html",
        {"book": book, "form": form},
    )


@ratelimit(key="ip", rate="30/h", method="POST")
@ratelimit(key="user", rate="10/h", method="POST")
@login_required
def suggest_edition_relation(request, book_slug, edition_public_id):
    source = get_object_or_404(
        Edition.objects.select_related("book").prefetch_related("publishers"),
        public_id=edition_public_id,
        book__slug=book_slug,
    )
    if request.method == "POST":
        form = EditionRelationSuggestionForm(request.POST, source=source)
        if form.is_valid():
            with transaction.atomic():
                suggestion = form.save(commit=False)
                suggestion.source = source
                suggestion.suggested_by = request.user
                suggestion.status = "pending"
                suggestion.save()
                if request.user.is_expert:
                    suggestion.approve(request.user)
                    suggestion.refresh_from_db()
            if (
                request.user.is_expert
                and suggestion.status == EditionRelationSuggestionStatus.APPROVED
            ):
                messages.success(
                    request,
                    "اٌعتمد اقتراح العلاقة مباشرةً لأنك خبير.",
                )
            else:
                messages.success(
                    request,
                    "تسلمنا اقتراحك وستراجعه الإدارة.",
                )
            return redirect(source.get_absolute_url())
    else:
        form = EditionRelationSuggestionForm(source=source)

    return render(
        request,
        "encyclopedia/suggest_edition_relation.html",
        {"source": source, "form": form},
    )


def _store_temp_cover_image(request, uploaded_file):
    """Store an uploaded cover image temporarily, tied to the user's session.

    The generated path is saved in the session so submit_edition can verify
    that any temp_cover_image value submitted on confirmation belongs to the
    current user and was created during the same duplicate-check flow.
    """
    ext = PurePath(uploaded_file.name).suffix or ".jpg"
    file_name = f"{uuid.uuid4().hex}{ext}"
    path = default_storage.save(
        f"tmp/covers/{file_name}",
        File(uploaded_file),
    )
    request.session["pending_cover"] = path
    request.session.modified = True
    return path


def _pop_pending_cover_path(request):
    """Return the stored pending cover path and clear it from the session."""
    return request.session.pop("pending_cover", None)


@ratelimit(key="ip", rate="30/h", method="POST")
@ratelimit(key="user", rate="10/h", method="POST")
@login_required
def submit_edition(request):
    temp_cover_image = None
    prefill_book = None

    if request.method == "POST":
        if request.POST.get("confirm_override"):
            form = EditionSubmissionForm(request.POST, request.FILES)
            posted_temp_path = request.POST.get("temp_cover_image", "").strip()
            temp_path = None
            if form.is_valid():
                with transaction.atomic():
                    edition = form.save(request.user)
                    if not edition.cover_image:
                        expected_path = _pop_pending_cover_path(request)
                        if expected_path and is_safe_temp_cover_path(expected_path):
                            if (
                                posted_temp_path == expected_path
                                and default_storage.exists(expected_path)
                            ):
                                temp_path = expected_path
                                with default_storage.open(temp_path) as temp_file:
                                    raw_data = temp_file.read()
                                raw_file = File(
                                    ContentFile(raw_data),
                                    name=PurePath(temp_path).name,
                                )
                                raw_file.content_type = (
                                    mimetypes.guess_type(temp_path)[0] or ""
                                )
                                processed = process_cover_image(raw_file)
                                edition.cover_image.save(
                                    processed.name, processed, save=True
                                )
                                default_storage.delete(temp_path)
                            else:
                                # The submitted temp path does not match the one
                                # stored in this session; discard it.
                                if default_storage.exists(expected_path):
                                    default_storage.delete(expected_path)
                    if request.user.is_expert:
                        _approve_edition(edition, request.user)

                if request.user.is_expert:
                    messages.success(
                        request,
                        "نٌشرت الطبعة مباشرةً لأنك خبير.",
                    )
                else:
                    messages.success(
                        request,
                        "استلمنا طلب إضافة الطبعة، وستراجعه الإدارة.",
                    )
                return redirect("home")
        else:
            form = EditionSubmissionForm(request.POST, request.FILES)
            if form.is_valid():
                edition = form.get_edition(request.user)
                duplicates = form.find_duplicates(edition)
                if duplicates.exists():
                    uploaded_cover = form.cleaned_data.get("cover_image")
                    if uploaded_cover:
                        temp_cover_image = _store_temp_cover_image(request, uploaded_cover)
                    return render(
                        request,
                        "encyclopedia/submit_edition_confirm.html",
                        {
                            "form": form,
                            "duplicates": duplicates,
                            "temp_cover_image": temp_cover_image,
                        },
                    )
                with transaction.atomic():
                    edition = form.save(request.user)
                    if request.user.is_expert:
                        _approve_edition(edition, request.user)

                if request.user.is_expert:
                    messages.success(
                        request,
                        "نٌشرت الطبعة مباشرةً لأنك خبير.",
                    )
                else:
                    messages.success(
                        request,
                        "استلمنا طلب إضافة الطبعة، وستراجعه الإدارة.",
                    )
                return redirect("home")
    else:
        initial = {}
        prefill_book = None
        book_pk = request.GET.get("book")
        if book_pk:
            try:
                prefill_book = Book.objects.get(pk=int(book_pk))
                initial = {"book_action": "existing", "existing_book": prefill_book}
            except (ValueError, Book.DoesNotExist):
                pass
        form = EditionSubmissionForm(initial=initial)

    return render(
        request,
        "encyclopedia/submit_edition.html",
        {"form": form, "prefill_book": prefill_book},
    )


@ratelimit(key="ip", rate="30/h", method="POST")
@ratelimit(key="user", rate="10/h", method="POST")
@login_required
def suggest_edition_edit(request, book_slug, edition_public_id):
    edition = get_object_or_404(
        Edition.objects.select_related("book").prefetch_related("publishers", "editors"),
        public_id=edition_public_id,
        book__slug=book_slug,
        status=EditionStatus.APPROVED,
    )

    if request.method == "POST":
        form = EditionEditSuggestionForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                suggestion = form.save(commit=False)
                suggestion.edition = edition
                suggestion.suggested_by = request.user
                suggestion.status = "pending"
                suggestion.save()
                form._ensure_name_records(
                    request.user,
                    suggestion.proposed_publishers,
                    suggestion.proposed_editors,
                )
                if request.user.is_expert:
                    suggestion.apply_to_edition(request.user)

            if request.user.is_expert:
                messages.success(
                    request,
                    "تعدلت الطبعة مباشرةً لأنك خبير.",
                )
            else:
                messages.success(
                    request,
                    "تسلمنا اقتراح التعديل، وستراجعه الإدارة.",
                )
            return redirect(edition.get_absolute_url())
    else:
        initial = {
            "proposed_publishers": json.dumps(
                [{"name": name} for name in edition.publishers.values_list("name", flat=True)]
            ),
            "proposed_editors": json.dumps(
                [{"name": name} for name in edition.editors.values_list("name", flat=True)]
            ),
            "year": edition.year,
            "page_count": edition.page_count,
            "city": edition.city,
            "volumes": edition.volumes,
        }
        form = EditionEditSuggestionForm(initial=initial)

    return render(
        request,
        "encyclopedia/suggest_edition_edit.html",
        {"form": form, "edition": edition},
    )
