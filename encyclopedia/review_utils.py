from collections import defaultdict

from django.db.models import IntegerField, Sum, Value
from django.db.models.functions import Coalesce

from .models import Review


def attach_review_glance(editions, limit=2):
    """Attach review_count and review_bubbles to each edition for card/list previews.

    Uses a single extra query: fetch all visible reviews for the given editions,
    then pick the top ``limit`` per edition and count the rest in Python.
    """
    edition_list = list(editions)
    if not edition_list:
        return edition_list

    edition_ids = [edition.pk for edition in edition_list]

    reviews = (
        Review.objects.filter(
            edition_id__in=edition_ids, hidden=False, parent__isnull=True
        )
        .select_related("user")
        .annotate(vote_score=Coalesce(Sum("votes__value"), Value(0, output_field=IntegerField())))
        .order_by("edition_id", "-user__is_expert", "-vote_score", "-created_at")
    )

    bubbles_by_edition = defaultdict(list)
    counts = defaultdict(int)
    for review in reviews:
        counts[review.edition_id] += 1
        if len(bubbles_by_edition[review.edition_id]) < limit:
            bubbles_by_edition[review.edition_id].append(review)

    for edition in edition_list:
        edition.review_count = counts.get(edition.pk, 0)
        edition.review_bubbles = bubbles_by_edition.get(edition.pk, [])

    return edition_list
