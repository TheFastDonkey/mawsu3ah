"""URL configuration for the moderation dashboard."""

from django.urls import path

from . import views

app_name = "moderation"

urlpatterns = [
    path("", views.moderation_dashboard, name="moderation_dashboard"),
    path("queue/", views.moderation_queue, name="moderation_queue"),
    # Backward-compatible edition-only action URLs.
    path(
        "queue/<int:pk>/approve/",
        views.approve_item,
        {"item_type": "edition"},
        name="approve_edition",
    ),
    path(
        "queue/<int:pk>/reject/",
        views.reject_item,
        {"item_type": "edition"},
        name="reject_edition",
    ),
    # Generic action URLs for every moderation item type.
    path(
        "<slug:item_type>/<int:pk>/approve/",
        views.approve_item,
        name="approve_item",
    ),
    path(
        "<slug:item_type>/<int:pk>/reject/",
        views.reject_item,
        name="reject_item",
    ),
    path("comments/", views.moderation_comments, name="moderation_comments"),
    path(
        "comments/<uuid:review_public_id>/hide-toggle/",
        views.review_hide_toggle,
        name="review_hide_toggle",
    ),
    path("reports/", views.report_queue, name="report_queue"),
    path(
        "reports/<uuid:review_public_id>/dismiss/",
        views.dismiss_reports,
        name="dismiss_reports",
    ),
]
