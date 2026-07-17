"""Search helpers for books and editions.

Production uses PostgreSQL full-text search and ranking. A lightweight
fallback is provided for environments without PostgreSQL; it scores matches
in Python so results still feel relevant-first.

Both paths normalize Arabic text so searches are forgiving of hamza
variants, ta marbuta vs ha, and diacritics/tashkeel.
"""

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db import connection
from django.db.models import Exists, OuterRef, Prefetch, TextField, Value
from django.db.models.expressions import RawSQL
from django.db.models.functions import Cast, Lower, Replace

from .models import Book, Category, Edition, EditionStatus
from .text_utils import normalize_arabic

_WEIGHTS = {
    "title": 4,
    "author": 3,
    "category": 2,
    "aliases": 2,
    "publisher": 1,
    "editor": 1,
}

# Replacements used to mirror normalize_arabic() inside PostgreSQL queries.
_DIACRITICS = (
    "\u0610\u0611\u0612\u0613\u0614\u0615\u0616\u0617\u0618\u0619\u061A"
    "\u064B\u064C\u064D\u064E\u064F\u0650\u0651\u0652\u0653\u0654\u0655"
    "\u0656\u0657\u0658\u0659\u065A\u065B\u065C\u065D\u065E\u065F\u0670"
    "\u0640"
)
_NORMALIZATION_PAIRS = (
    [(char, "") for char in _DIACRITICS]
    + [
        ("آ", "ا"),
        ("أ", "ا"),
        ("إ", "ا"),
        ("ٱ", "ا"),
        ("ؤ", "و"),
        ("ئ", "ي"),
        ("ء", ""),
        ("ة", "ه"),
    ]
)


def _approved_editions_prefetch():
    return Prefetch(
        "editions",
        queryset=Edition.objects.filter(status=EditionStatus.APPROVED),
    )


def _annotate_approved_exists(queryset):
    approved_exists = Exists(
        Edition.objects.filter(
            book=OuterRef("pk"),
            status=EditionStatus.APPROVED,
        )
    )
    return queryset.annotate(has_approved_edition=approved_exists).filter(has_approved_edition=True)


def _norm_sql(field_name):
    """Return a Django expression that normalizes *field_name* in SQL."""
    expr = Lower(field_name)
    for old, new in _NORMALIZATION_PAIRS:
        expr = Replace(expr, Value(old), Value(new))
    # Cast to TextField so SearchVector can combine CharField and TextField
    # sources without PostgreSQL "mixed types" errors.
    return Cast(expr, output_field=TextField())


def _postgres_search(query, category_slug=None):
    ancestor_names_sql = """
        SELECT string_agg(c2.name, ' ')
        FROM encyclopedia_bookcategory bc
        JOIN encyclopedia_category c1 ON bc.category_id = c1.id
        JOIN encyclopedia_category c2 ON c1.path LIKE c2.path || '%%' AND c1.id != c2.id
        WHERE bc.book_id = encyclopedia_book.id
    """
    search_query = SearchQuery(normalize_arabic(query), config="arabic")
    qs = Book.objects.annotate(
        ancestor_names=RawSQL(ancestor_names_sql, []),
    )
    vector = (
        SearchVector(_norm_sql("title"), weight="A", config="arabic")
        + SearchVector(_norm_sql("authors__name"), weight="A", config="arabic")
        + SearchVector(_norm_sql("aliases"), weight="B", config="arabic")
        + SearchVector(_norm_sql("categories__name"), weight="B", config="arabic")
        + SearchVector(_norm_sql("ancestor_names"), weight="B", config="arabic")
        + SearchVector(_norm_sql("editions__publishers__name"), weight="C", config="arabic")
        + SearchVector(_norm_sql("editions__editors__name"), weight="C", config="arabic")
    )
    qs = qs.annotate(rank=SearchRank(vector, search_query))
    qs = _annotate_approved_exists(qs)
    qs = qs.filter(rank__gt=0.001).distinct().order_by("-rank", "title")
    if category_slug:
        category = Category.objects.filter(slug=category_slug).first()
        if category:
            qs = qs.filter(categories__path__startswith=category.path)
    return qs


def _fallback_search(query, category_slug=None):
    norm_query = normalize_arabic(query)
    qs = Book.objects.all()
    qs = _annotate_approved_exists(qs)
    if category_slug:
        category = Category.objects.filter(slug=category_slug).first()
        if category:
            qs = qs.filter(categories__path__startswith=category.path)

    books = list(
        qs.prefetch_related(
            _approved_editions_prefetch(),
            "categories",
            "authors",
            "editions__publishers",
            "editions__editors",
        )
        .distinct()
    )
    for book in books:
        score = 0
        if norm_query in normalize_arabic(book.title):
            score += _WEIGHTS["title"]
        for author in book.authors.all():
            if norm_query in normalize_arabic(author.name):
                score += _WEIGHTS["author"]
                break
        for category in book.categories.all():
            if norm_query in normalize_arabic(category.name):
                score += _WEIGHTS["category"]
            else:
                for ancestor in category.ancestors:
                    if norm_query in normalize_arabic(ancestor.name):
                        score += _WEIGHTS["category"]
                        break
        if book.aliases and norm_query in normalize_arabic(book.aliases):
            score += _WEIGHTS["aliases"]
        for edition in book.editions.all():
            if edition.status != EditionStatus.APPROVED:
                continue
            for publisher in edition.publishers.all():
                if norm_query in normalize_arabic(publisher.name):
                    score += _WEIGHTS["publisher"]
                    break
            for editor in edition.editors.all():
                if norm_query in normalize_arabic(editor.name):
                    score += _WEIGHTS["editor"]
                    break
        book.search_score = score

    books = [book for book in books if book.search_score > 0]
    books.sort(key=lambda b: (-b.search_score, b.title))
    return books


def search_books(query, category_slug=None):
    """Return books matching *query*, ordered by relevance.

    The return value is either a Django QuerySet (PostgreSQL) or a list of
    Book instances (fallback). Both support slicing and the Paginator.
    """
    query = (query or "").strip()
    if not query:
        qs = Book.objects.prefetch_related("authors")
        qs = _annotate_approved_exists(qs)
        if category_slug:
            category = Category.objects.filter(slug=category_slug).first()
            if category:
                qs = qs.filter(categories__path__startswith=category.path)
        return qs.order_by("title")

    if connection.vendor == "postgresql":
        return _postgres_search(query, category_slug)
    return _fallback_search(query, category_slug)
