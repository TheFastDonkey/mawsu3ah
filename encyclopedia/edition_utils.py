"""Helpers for edition querysets and display logic."""

from django.db.models import Exists, OuterRef

from .models import EditionVote


def annotate_edition_liked_by_expert(queryset, context_book=None):
    """Annotate an Edition queryset with a boolean ``liked_by_expert``.

    If ``context_book`` is provided, only votes cast in that book's context
    are considered. Otherwise all votes are considered.
    """
    filters = {
        "edition": OuterRef("pk"),
        "user__is_expert": True,
        "value": EditionVote.VoteValue.LIKE,
    }
    if context_book is not None:
        filters["book_context"] = context_book
    return queryset.annotate(
        liked_by_expert=Exists(
            EditionVote.objects.filter(**filters)
        )
    )


def annotate_edition_name_slugs(queryset):
    """Prefetch M2M name records used in edition templates."""
    return queryset.prefetch_related("book__authors", "publishers", "editors")


def attach_edition_user_votes(editions, user, context_book=None):
    """Attach ``user_vote`` (+1/-1/None) to each edition object in place.

    If ``context_book`` is provided, only the user's vote in that book's
    context is returned. Otherwise the primary book context is used.
    """
    edition_list = list(editions)
    if not edition_list or not user or not user.is_authenticated:
        for edition in edition_list:
            edition.user_vote = None
        return edition_list

    pks = [edition.pk for edition in edition_list]
    filters = {"user": user, "edition_id__in": pks}
    if context_book is not None:
        filters["book_context"] = context_book
    votes = dict(
        EditionVote.objects.filter(**filters).values_list("edition_id", "value")
    )
    for edition in edition_list:
        edition.user_vote = votes.get(edition.pk)
    return edition_list
