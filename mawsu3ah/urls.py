from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from django.views.generic import TemplateView

from accounts.views import public_profile
from encyclopedia.sitemaps import BookSitemap, CategorySitemap, EditionSitemap

from . import views

sitemaps = {
    "categories": CategorySitemap,
    "books": BookSitemap,
    "editions": EditionSitemap,
}

urlpatterns = [
    path("csp-report/", views.csp_report, name="csp_report"),
    path("health/", views.health_check, name="health_check"),
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path(f"{settings.DJANGO_ADMIN_URL}/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("u/<str:username>/", public_profile, name="public_profile"),
    path("staff/", include("moderation.urls")),
    path(
        "robots.txt",
        TemplateView.as_view(template_name="robots.txt", content_type="text/plain"),
        name="robots_txt",
    ),
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
    path("", include("encyclopedia.urls")),
]

if "debug_toolbar" in settings.INSTALLED_APPS:
    urlpatterns = [path("__debug__/", include("debug_toolbar.urls"))] + urlpatterns

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler404 = "mawsu3ah.views.page_not_found"
handler429 = "mawsu3ah.views.ratelimited_error"
handler500 = "mawsu3ah.views.server_error"
