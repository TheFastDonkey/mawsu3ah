"""Template context processors shared across the project."""

from django.db.models import Count, OuterRef, Q, Subquery, Value


def sidebar(request):
    """Provide category data for the site-wide sidebar menu."""
    from encyclopedia.models import Book, Category, EditionStatus

    def _approved_book_count_subquery():
        return Subquery(
            Book.objects.filter(
                categories__path__startswith=OuterRef("path"),
                editions__status=EditionStatus.APPROVED,
            )
            .order_by()  # Clear Book Meta ordering so GROUP BY works on PostgreSQL
            .annotate(_group=Value(1))
            .values("_group")
            .annotate(c=Count("id", distinct=True))
            .values("c")
        )

    def _arabic_sort_key(name):
        # Normalize leading alif variants so categories that start with
        # أ/إ/آ sort alongside ا, giving a clean أ-to-ي order.
        if name and name[0] in ("أ", "إ", "آ", "ٱ"):
            return "ا" + name[1:]
        return name

    categories = list(
        Category.objects.filter(
            Q(parent__isnull=True) | Q(parent__parent__isnull=True)
        )
        .annotate(subtree_book_count=_approved_book_count_subquery())
    )
    categories.sort(key=lambda c: _arabic_sort_key(c.name))

    roots = []
    children_map = {}
    for category in categories:
        category.sidebar_children = []
        if category.parent_id is None:
            roots.append(category)
        else:
            children_map.setdefault(category.parent_id, []).append(category)

    for root in roots:
        root.sidebar_children = children_map.get(root.pk, [])

    return {"sidebar_roots": roots}
