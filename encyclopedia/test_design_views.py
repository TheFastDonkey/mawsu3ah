"""Temporary design-exploration views for the edition detail page.

These routes (/test1, /test2, /test3) render alternative layouts for the
same edition so the team can compare directions. They are not part of the
public URL scheme and can be removed once a direction is chosen.
"""

from django.db.models import IntegerField, Prefetch, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render

from .edition_utils import annotate_edition_liked_by_expert
from .engagement_views import _edition_reviews, _voted_review_ids
from .models import BookCategory, Edition, EditionStatus, EditionVote


def _edition_context(request, pk):
    """Fetch the same data as edition_detail so variants are fair comparisons."""
    edition = get_object_or_404(
        annotate_edition_liked_by_expert(
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
                vote_score=Coalesce(Sum("votes__value"), Value(0, output_field=IntegerField()))
            )
        ),
        pk=pk,
        status=EditionStatus.APPROVED,
    )
    reviews = _edition_reviews(edition, request.user)
    review_pks = [r.pk for r in reviews]
    voted_reviews = _voted_review_ids(request.user, review_pks)
    for review in reviews:
        review.user_vote = voted_reviews.get(review.pk)

    user_vote = (
        EditionVote.objects.filter(user=request.user, edition=edition)
        .values_list("value", flat=True)
        .first()
        if request.user.is_authenticated else None
    )

    return {
        "edition": edition,
        "reviews": reviews,
        "review_form": None,
        "user_vote": user_vote,
    }


def edition_detail_variant_1(request):
    """Two-column scholarly reference layout (kept for comparison)."""
    context = _edition_context(request, 15)
    return render(request, "encyclopedia/test/edition_detail_v1.html", context)
