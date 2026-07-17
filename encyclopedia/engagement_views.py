from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Exists, F, IntegerField, OuterRef, Prefetch, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from .forms import ReviewForm, ReviewReplyForm, ReviewReportForm
from .models import (
    Book,
    BookCategory,
    CategorySuggestion,
    CategorySuggestionStatus,
    CategorySuggestionVote,
    Edition,
    EditionRelation,
    EditionStatus,
    EditionVote,
    NameRecord,
    Review,
    ReviewReport,
    ReviewVote,
)
from .views import _book_category_suggestions


def _edition_reviews(edition, user):
    qs = edition.reviews.select_related("user").annotate(vote_score=Coalesce(Sum("votes__value"), Value(0, output_field=IntegerField())))
    if not user.is_staff:
        qs = qs.filter(hidden=False)

    if user.is_authenticated:
        reported_qs = ReviewReport.objects.filter(
            review=OuterRef("pk"), reporter=user, resolved=False
        )
        qs = qs.annotate(reported_by_user=Exists(reported_qs))
    else:
        qs = qs.annotate(reported_by_user=Exists(ReviewReport.objects.none()))

    reviews = list(qs)

    review_pks = [r.pk for r in reviews]
    voted_reviews = _voted_review_ids(user, review_pks)
    for review in reviews:
        review.user_vote = voted_reviews.get(review.pk)
        review.children = []

    by_parent = {}
    top_level = []
    for review in reviews:
        if review.parent_id is None:
            top_level.append(review)
        else:
            by_parent.setdefault(review.parent_id, []).append(review)

    def attach_children(review):
        children = by_parent.get(review.pk, [])
        children.sort(key=lambda c: c.created_at)
        for child in children:
            attach_children(child)
        review.children = children

    def set_descendant_count(review):
        count = 0
        for child in review.children:
            count += 1 + set_descendant_count(child)
        review.descendant_count = count
        return count

    for review in top_level:
        attach_children(review)
        set_descendant_count(review)

    top_level.sort(
        key=lambda r: (
            not r.user.is_expert,
            -r.vote_score,
            -r.created_at.timestamp(),
        )
    )
    return top_level


def _voted_review_ids(user, review_pks):
    if not user.is_authenticated:
        return {}
    return dict(
        ReviewVote.objects.filter(user=user, review_id__in=review_pks).values_list(
            "review_id", "value"
        )
    )


def _voted_edition_ids(user, edition_pks):
    if not user.is_authenticated:
        return {}
    return dict(
        EditionVote.objects.filter(user=user, edition_id__in=edition_pks).values_list(
            "edition_id", "value"
        )
    )


def _detail_edition_queryset():
    """Return an Edition queryset annotated for the edition detail page."""
    return (
        Edition.objects.select_related("book", "submitted_by")
        .prefetch_related(
            Prefetch(
                "book__book_categories",
                queryset=BookCategory.objects.select_related("category").order_by("order"),
            ),
            "book__authors",
            "publishers",
            "editors",
        )
        .annotate(
            vote_score=Coalesce(
                Sum("votes__value", filter=Q(votes__book_context=F("book"))),
                Value(0, output_field=IntegerField()),
            ),
            liked_by_expert=Exists(
                EditionVote.objects.filter(
                    edition=OuterRef("pk"),
                    user__is_expert=True,
                    value=EditionVote.VoteValue.LIKE,
                    book_context=OuterRef("book"),
                )
            ),
        )
    )


def _detail_edition_for_render(edition_public_id):
    """Fetch an edition annotated for the detail page and attach expert-like flag."""
    edition = _detail_edition_queryset().get(public_id=edition_public_id)
    edition.liked_by_expert = EditionVote.objects.filter(
        edition=edition,
        user__is_expert=True,
        value=EditionVote.VoteValue.LIKE,
        book_context=edition.book,
    ).exists()
    return edition


def _edition_url_kwargs(edition):
    """Return URL kwargs for edition-scoped routes."""
    return {"book_slug": edition.book.slug, "edition_public_id": edition.public_id}


def edition_detail(request, book_slug, edition_public_id):
    edition = get_object_or_404(
        Edition.objects.select_related("book", "submitted_by")
        .prefetch_related(
            Prefetch(
                "book__book_categories",
                queryset=BookCategory.objects.select_related("category").order_by("order"),
            ),
            "book__categories",
            "book__authors",
            Prefetch(
                "publishers",
                queryset=NameRecord.objects.order_by("edition_publisher_links__order"),
            ),
            "editors",
            Prefetch(
                "related_targets",
                queryset=EditionRelation.objects.select_related("target").prefetch_related(
                    Prefetch(
                        "target__publishers",
                        queryset=NameRecord.objects.order_by("edition_publisher_links__order"),
                    )
                ),
            ),
            Prefetch(
                "related_sources",
                queryset=EditionRelation.objects.select_related("source").prefetch_related(
                    Prefetch(
                        "source__publishers",
                        queryset=NameRecord.objects.order_by("edition_publisher_links__order"),
                    )
                ),
            ),
        )
        .annotate(
            vote_score=Coalesce(
                Sum("votes__value", filter=Q(votes__book_context=F("book"))),
                Value(0, output_field=IntegerField()),
            ),
            liked_by_expert=Exists(
                EditionVote.objects.filter(
                    edition=OuterRef("pk"),
                    user__is_expert=True,
                    value=EditionVote.VoteValue.LIKE,
                    book_context=OuterRef("book"),
                )
            ),
        ),
        public_id=edition_public_id,
        book__slug=book_slug,
        status=EditionStatus.APPROVED,
    )

    reviews = _edition_reviews(edition, request.user)
    review_pks = [r.pk for r in reviews]
    voted_reviews = _voted_review_ids(request.user, review_pks)
    for review in reviews:
        review.user_vote = voted_reviews.get(review.pk)

    inherited_reviews = []
    for relation in edition.related_sources.all():
        inherited_reviews.extend(_edition_reviews(relation.source, request.user))

    user_vote = None
    if request.user.is_authenticated:
        user_vote = (
            EditionVote.objects.filter(
                user=request.user, edition=edition, book_context=edition.book
            )
            .values_list("value", flat=True)
            .first()
        )

    review_form = ReviewForm()

    return render(
        request,
        "encyclopedia/edition_detail.html",
        {
            "edition": edition,
            "reviews": reviews,
            "inherited_reviews": inherited_reviews,
            "review_form": review_form,
            "user_vote": user_vote,
            "category_suggestions": _book_category_suggestions(edition.book, request.user),
        },
    )


def edition_votes(request, book_slug, edition_public_id):
    edition = get_object_or_404(
        Edition,
        public_id=edition_public_id,
        book__slug=book_slug,
        status=EditionStatus.APPROVED,
    )
    votes = edition.votes.select_related("user").order_by("-created_at")
    return render(
        request,
        "encyclopedia/partials/edition_votes.html",
        {
            "edition": edition,
            "votes": votes,
        },
    )


def edition_detail_legacy_redirect(request, pk):
    edition = get_object_or_404(
        Edition, pk=pk, status=EditionStatus.APPROVED
    )
    return redirect(
        "edition_detail",
        book_slug=edition.book.slug,
        edition_public_id=edition.public_id,
        permanent=True,
    )


def edition_votes_legacy_redirect(request, pk):
    edition = get_object_or_404(
        Edition, pk=pk, status=EditionStatus.APPROVED
    )
    return redirect(
        "edition_votes",
        book_slug=edition.book.slug,
        edition_public_id=edition.public_id,
        permanent=True,
    )


def _set_vote(vote_model, obj_field, user, obj, value):
    """Create, update or remove a user's vote on an object.

    Returns the new user vote value (1, -1 or None).
    """
    try:
        vote = vote_model.objects.get(user=user, **{obj_field: obj})
    except vote_model.DoesNotExist:
        vote = None

    if vote is None:
        vote_model.objects.create(user=user, **{obj_field: obj}, value=value)
        return value

    if vote.value == value:
        vote.delete()
        return None

    vote.value = value
    vote.save(update_fields=["value"])
    return value


@ratelimit(key="ip", rate="120/m", method="POST")
@ratelimit(key="user_or_ip", rate="60/m", method="POST")
@require_POST
def edition_vote(request, book_slug, edition_public_id):
    edition = get_object_or_404(
        Edition,
        public_id=edition_public_id,
        book__slug=book_slug,
        status=EditionStatus.APPROVED,
    )

    if not request.user.is_authenticated:
        return render(
            request,
            "encyclopedia/partials/sign_in_prompt.html",
            {"next": reverse("edition_detail", kwargs=_edition_url_kwargs(edition))},
        )

    context_book = edition.book
    context_book_pk = request.POST.get("context_book")
    if context_book_pk:
        try:
            candidate = Book.objects.get(pk=int(context_book_pk))
        except (ValueError, Book.DoesNotExist):
            candidate = None
        if candidate and (
            candidate == edition.book
            or edition.book_links.filter(book=candidate).exists()
        ):
            context_book = candidate

    vote_value = request.POST.get("vote")
    value = (
        EditionVote.VoteValue.DISLIKE
        if vote_value == "dislike"
        else EditionVote.VoteValue.LIKE
    )

    vote = EditionVote.objects.filter(
        user=request.user, edition=edition, book_context=context_book
    ).first()
    if vote is None:
        EditionVote.objects.create(
            user=request.user,
            edition=edition,
            book_context=context_book,
            value=value,
        )
        user_vote = value
    elif vote.value == value:
        vote.delete()
        user_vote = None
    else:
        vote.value = value
        vote.save(update_fields=["value"])
        user_vote = value

    edition.vote_score = (
        EditionVote.objects.filter(edition=edition, book_context=context_book)
        .aggregate(score=Coalesce(Sum("value"), 0))["score"]
    )

    return render(
        request,
        "encyclopedia/partials/edition_vote_buttons.html",
        {
            "edition": edition,
            "user_vote": user_vote,
            "context_book": context_book,
        },
    )


@ratelimit(key="ip", rate="60/m", method="POST")
@ratelimit(key="user_or_ip", rate="20/m", method="POST")
@require_POST
def review_create(request, book_slug, edition_public_id):
    edition = get_object_or_404(
        Edition,
        public_id=edition_public_id,
        book__slug=book_slug,
        status=EditionStatus.APPROVED,
    )

    if not request.user.is_authenticated:
        return render(
            request,
            "encyclopedia/partials/sign_in_prompt.html",
            {"next": reverse("edition_detail", kwargs=_edition_url_kwargs(edition))},
        )

    form = ReviewForm(request.POST)
    if form.is_valid():
        review = form.save(commit=False)
        review.edition = edition
        review.user = request.user
        review.save()
        form = ReviewForm()

    reviews = _edition_reviews(edition, request.user)
    review_pks = [r.pk for r in reviews]
    voted_reviews = _voted_review_ids(request.user, review_pks)
    for review in reviews:
        review.user_vote = voted_reviews.get(review.pk)

    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        return render(
            request,
            "encyclopedia/partials/comment_list.html",
            {
                "edition": edition,
                "reviews": reviews,
                "review_form": form,
            },
        )
    return render(
        request,
        "encyclopedia/edition_detail.html",
        {
            "edition": _detail_edition_for_render(edition.public_id),
            "reviews": reviews,
            "review_form": form,
            "user_vote": (
                EditionVote.objects.filter(
                    user=request.user, edition=edition, book_context=edition.book
                )
                .values_list("value", flat=True)
                .first()
                if request.user.is_authenticated else None
            ),
            "category_suggestions": _book_category_suggestions(edition.book, request.user),
        },
    )


@ratelimit(key="ip", rate="60/m", method="POST")
@ratelimit(key="user_or_ip", rate="20/m", method="POST")
@require_POST
def review_reply_create(request, book_slug, edition_public_id, review_public_id):
    edition = get_object_or_404(
        Edition,
        public_id=edition_public_id,
        book__slug=book_slug,
        status=EditionStatus.APPROVED,
    )

    if not request.user.is_authenticated:
        return render(
            request,
            "encyclopedia/partials/sign_in_prompt.html",
            {"next": reverse("edition_detail", kwargs=_edition_url_kwargs(edition))},
        )

    parent = get_object_or_404(Review, public_id=review_public_id, edition=edition)

    form = ReviewReplyForm(request.POST, edition=edition)
    if form.is_valid():
        reply = form.save(commit=False)
        reply.edition = edition
        reply.user = request.user
        reply.parent = parent
        reply.save()
        form = ReviewReplyForm()

    reviews = _edition_reviews(edition, request.user)
    review_pks = [r.pk for r in reviews]
    voted_reviews = _voted_review_ids(request.user, review_pks)
    for review in reviews:
        review.user_vote = voted_reviews.get(review.pk)

    parent_review = _find_review_in_tree(reviews, review_public_id)

    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx and parent_review is not None:
        return render(
            request,
            "encyclopedia/partials/comment_item.html",
            {
                "review": parent_review,
                "edition": edition,
            },
        )
    return render(
        request,
        "encyclopedia/edition_detail.html",
        {
            "edition": _detail_edition_for_render(edition.public_id),
            "reviews": reviews,
            "review_form": ReviewForm(),
            "user_vote": (
                EditionVote.objects.filter(
                    user=request.user, edition=edition, book_context=edition.book
                )
                .values_list("value", flat=True)
                .first()
                if request.user.is_authenticated else None
            ),
            "category_suggestions": _book_category_suggestions(edition.book, request.user),
        },
    )


def _find_review_in_tree(reviews, public_id):
    for review in reviews:
        if review.public_id == public_id:
            return review
        found = _find_review_in_tree(review.children, public_id)
        if found is not None:
            return found
    return None


@ratelimit(key="ip", rate="60/m", method="POST")
@ratelimit(key="user", rate="30/m", method="POST")
@require_POST
def review_edit(request, review_public_id):
    review = get_object_or_404(Review, public_id=review_public_id)

    if not request.user.is_authenticated:
        return render(
            request,
            "encyclopedia/partials/sign_in_prompt.html",
            {"next": reverse("edition_detail", kwargs=_edition_url_kwargs(review.edition))},
        )

    if request.user != review.user:
        return HttpResponseForbidden()

    form = ReviewForm(request.POST, instance=review)
    if form.is_valid():
        review = form.save(commit=False)
        review.edited_at = timezone.now()
        review.save()

    reviews = _edition_reviews(review.edition, request.user)
    review = _find_review_in_tree(reviews, review.public_id)
    if review is None:
        review = get_object_or_404(Review, public_id=review_public_id)
        review.vote_score = review.votes.aggregate(score=Coalesce(Sum("value"), 0))["score"]
        review.user_vote = (
            ReviewVote.objects.filter(user=request.user, review=review)
            .values_list("value", flat=True)
            .first()
        )

    return render(
        request,
        "encyclopedia/partials/comment_item.html",
        {
            "review": review,
            "edition": review.edition,
        },
    )


@ratelimit(key="ip", rate="120/m", method="POST")
@ratelimit(key="user_or_ip", rate="60/m", method="POST")
@require_POST
def review_vote(request, review_public_id):
    review = get_object_or_404(Review, public_id=review_public_id)

    if not request.user.is_authenticated:
        return render(
            request,
            "encyclopedia/partials/sign_in_prompt.html",
            {"next": reverse("edition_detail", kwargs=_edition_url_kwargs(review.edition))},
        )

    vote_value = request.POST.get("vote")
    value = (
        ReviewVote.VoteValue.DISLIKE
        if vote_value == "dislike"
        else ReviewVote.VoteValue.LIKE
    )

    user_vote = _set_vote(ReviewVote, "review", request.user, review, value)
    review.vote_score = review.votes.aggregate(score=Coalesce(Sum("value"), 0))["score"]

    return render(
        request,
        "encyclopedia/partials/review_vote_buttons.html",
        {
            "review": review,
            "user_vote": user_vote,
        },
    )


@ratelimit(key="ip", rate="120/m", method="POST")
@ratelimit(key="user", rate="60/m", method="POST")
@require_POST
def category_suggestion_vote(request, pk):
    if not request.user.is_authenticated:
        try:
            suggestion = CategorySuggestion.objects.get(
                pk=pk,
                status=CategorySuggestionStatus.PENDING,
            )
        except CategorySuggestion.DoesNotExist:
            return HttpResponse(status=404)
        return render(
            request,
            "encyclopedia/partials/sign_in_prompt.html",
            {"next": suggestion.book.get_absolute_url()},
        )

    vote_value = request.POST.get("vote")
    value = (
        CategorySuggestionVote.VoteValue.DISLIKE
        if vote_value == "dislike"
        else CategorySuggestionVote.VoteValue.LIKE
    )

    with transaction.atomic():
        try:
            suggestion = CategorySuggestion.objects.select_for_update().get(
                pk=pk,
                status=CategorySuggestionStatus.PENDING,
            )
        except CategorySuggestion.DoesNotExist:
            return HttpResponse(status=404)

        _set_vote(CategorySuggestionVote, "suggestion", request.user, suggestion, value)

        score = (
            CategorySuggestionVote.objects.filter(suggestion=suggestion)
            .aggregate(score=Coalesce(Sum("value"), 0))
            ["score"]
        )

        has_expert_like = suggestion.votes.filter(
            user__is_expert=True, value=CategorySuggestionVote.VoteValue.LIKE
        ).exists()
        if score >= 3 and has_expert_like:
            category = suggestion.final_category
            if category and not suggestion.book.categories.filter(pk=category.pk).exists():
                BookCategory.objects.create(
                    book=suggestion.book,
                    category=category,
                    order=BookCategory.objects.filter(book=suggestion.book).count(),
                )
            suggestion.status = CategorySuggestionStatus.APPROVED
            suggestion.resolved_at = timezone.now()
            suggestion.save(update_fields=["status", "resolved_at"])
        elif score <= -3:
            suggestion.status = CategorySuggestionStatus.REJECTED
            suggestion.resolved_at = timezone.now()
            suggestion.save(update_fields=["status", "resolved_at"])

    response = HttpResponse(status=204)
    response["HX-Trigger"] = "refreshCategoryKicker"
    return response


@ratelimit(key="ip", rate="120/m", method="POST")
@ratelimit(key="user", rate="60/m", method="POST")
@require_POST
def review_hide_toggle(request, review_public_id):
    if not request.user.is_staff:
        return HttpResponseForbidden()

    review = get_object_or_404(Review, public_id=review_public_id)

    if review.hidden:
        review.hidden = False
        review.hidden_by = None
        review.hidden_at = None
    else:
        review.hidden = True
        review.hidden_by = request.user
        review.hidden_at = timezone.now()
    review.save()

    reviews = _edition_reviews(review.edition, request.user)
    review = _find_review_in_tree(reviews, review.public_id)
    if review is None:
        review = get_object_or_404(Review, public_id=review_public_id)
        review.vote_score = review.votes.aggregate(score=Coalesce(Sum("value"), 0))["score"]
        review.user_vote = (
            ReviewVote.objects.filter(user=request.user, review=review)
            .values_list("value", flat=True)
            .first()
        )

    return render(
        request,
        "encyclopedia/partials/comment_item.html",
        {
            "review": review,
            "edition": review.edition,
        },
    )


@ratelimit(key="ip", rate="60/m", method="POST")
@ratelimit(key="user_or_ip", rate="30/m", method="POST")
@require_POST
def review_delete(request, review_public_id):
    review = get_object_or_404(Review, public_id=review_public_id)
    edition = review.edition

    if not request.user.is_authenticated:
        return render(
            request,
            "encyclopedia/partials/sign_in_prompt.html",
            {"next": reverse("edition_detail", kwargs=_edition_url_kwargs(edition))},
        )

    if request.user != review.user and not request.user.is_staff:
        return HttpResponseForbidden()

    is_top_level = review.parent_id is None
    review.delete()

    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        if is_top_level:
            reviews = _edition_reviews(edition, request.user)
            review_pks = [r.pk for r in reviews]
            voted_reviews = _voted_review_ids(request.user, review_pks)
            for r in reviews:
                r.user_vote = voted_reviews.get(r.pk)
            return render(
                request,
                "encyclopedia/partials/comment_list.html",
                {
                    "edition": edition,
                    "reviews": reviews,
                    "review_form": ReviewForm(),
                },
            )
        return HttpResponse(status=200)

    return redirect("edition_detail", **(_edition_url_kwargs(edition)))


@ratelimit(key="ip", rate="30/m", method="POST")
@ratelimit(key="user_or_ip", rate="10/m", method="POST")
@require_POST
def review_report_create(request, review_public_id):
    review = get_object_or_404(Review, public_id=review_public_id)

    if not request.user.is_authenticated:
        return render(
            request,
            "encyclopedia/partials/sign_in_prompt.html",
            {"next": reverse("edition_detail", kwargs=_edition_url_kwargs(review.edition))},
        )

    if request.user == review.user:
        return HttpResponseForbidden()

    form = ReviewReportForm(request.POST)
    if form.is_valid():
        report = form.save(commit=False)
        report.review = review
        report.reporter = request.user
        try:
            with transaction.atomic():
                report.save()
        except IntegrityError:
            return render(
                request,
                "encyclopedia/partials/report_success.html",
                {"already_reported": True},
            )

        subject = f"بلاغ جديد عن مراجعة #{review.pk}"
        body = render_to_string(
            "encyclopedia/emails/report_review.txt",
            {
                "review": review,
                "report": report,
                "reporter": request.user,
                "url": request.build_absolute_uri(
                    reverse("edition_detail", kwargs=_edition_url_kwargs(review.edition))
                ),
            },
        )
        if settings.ADMINS:
            recipient_list = [email for _name, email in settings.ADMINS]
            send_mail(
                subject=subject,
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL or None,
                recipient_list=recipient_list,
                fail_silently=True,
            )

        return render(
            request,
            "encyclopedia/partials/report_success.html",
            {"already_reported": False},
        )

    return render(
        request,
        "encyclopedia/partials/report_form.html",
        {
            "review": review,
            "form": form,
        },
    )
