from django.urls import path

from . import engagement_views, views

urlpatterns = [
    path("", views.home, name="home"),
    path("submit/", views.submit_edition, name="submit_edition"),
    path("search/", views.search, name="search"),
    path("search/suggestions/", views.search_suggestions, name="search_suggestions"),
    path("suggestions/authors/", views.author_suggestions, name="author_suggestions"),
    path("suggestions/editors/", views.editor_suggestions, name="editor_suggestions"),
    path("suggestions/publishers/", views.publisher_suggestions, name="publisher_suggestions"),
    path("suggestions/books/", views.book_suggestions, name="book_suggestions"),
    path("suggestions/categories/", views.category_suggestions, name="category_suggestions"),
    path("suggestions/editions/", views.edition_suggestions, name="edition_suggestions"),
    path("authors/", views.author_list, name="author_list"),
    path("authors/<str:slug>/", views.author_detail, name="author_detail"),
    path("editors/", views.editor_list, name="editor_list"),
    path("editors/<str:slug>/", views.editor_detail, name="editor_detail"),
    path("publishers/", views.publisher_list, name="publisher_list"),
    path("publishers/<str:slug>/", views.publisher_detail, name="publisher_detail"),
    path("categories/", views.category_list, name="category_list"),
    path("categories/autocomplete/", views.category_autocomplete, name="category_autocomplete"),
    path("categories/request/", views.request_category, name="request_category"),
    path("categories/<path:category_path>/", views.category_detail, name="category_detail"),
    # Edition pages nested under their book.
    path(
        "books/<str:book_slug>/<uuid:edition_public_id>/",
        engagement_views.edition_detail,
        name="edition_detail",
    ),
    path(
        "books/<str:book_slug>/<uuid:edition_public_id>/vote/",
        engagement_views.edition_vote,
        name="edition_vote",
    ),
    path(
        "books/<str:book_slug>/<uuid:edition_public_id>/voters/",
        engagement_views.edition_votes,
        name="edition_votes",
    ),
    path(
        "books/<str:book_slug>/<uuid:edition_public_id>/edit/",
        views.suggest_edition_edit,
        name="suggest_edition_edit",
    ),
    path(
        "books/<str:book_slug>/<uuid:edition_public_id>/reviews/",
        engagement_views.review_create,
        name="review_create",
    ),
    path(
        "books/<str:book_slug>/<uuid:edition_public_id>/reviews/<uuid:review_public_id>/reply/",
        engagement_views.review_reply_create,
        name="review_reply_create",
    ),
    path("books/<str:slug>/suggest-category/", views.suggest_category, name="suggest_category"),
    path("books/<str:slug>/categories/kicker/", views.book_categories_kicker, name="book_categories_kicker"),
    path("books/<str:slug>/suggest-link/", views.suggest_edition_link, name="suggest_edition_link"),
    path(
        "books/<str:book_slug>/<uuid:edition_public_id>/suggest-relation/",
        views.suggest_edition_relation,
        name="suggest_edition_relation",
    ),
    path("books/<str:slug>/", views.book_detail, name="book_detail"),
    # Legacy redirects from the old /editions/<pk>/ namespace.
    path(
        "editions/<int:pk>/",
        engagement_views.edition_detail_legacy_redirect,
        name="edition_detail_legacy",
    ),
    path(
        "editions/<int:pk>/voters/",
        engagement_views.edition_votes_legacy_redirect,
        name="edition_votes_legacy",
    ),
    path(
        "reviews/<uuid:review_public_id>/edit/",
        engagement_views.review_edit,
        name="review_edit",
    ),
    path(
        "reviews/<uuid:review_public_id>/vote/",
        engagement_views.review_vote,
        name="review_vote",
    ),
    path(
        "category-suggestions/<int:pk>/vote/",
        engagement_views.category_suggestion_vote,
        name="category_suggestion_vote",
    ),
    path(
        "reviews/<uuid:review_public_id>/hide/",
        engagement_views.review_hide_toggle,
        name="review_hide_toggle",
    ),
    path(
        "reviews/<uuid:review_public_id>/delete/",
        engagement_views.review_delete,
        name="review_delete",
    ),
    path(
        "reviews/<uuid:review_public_id>/report/",
        engagement_views.review_report_create,
        name="review_report_create",
    ),
]
