"""Sitemap definitions for public catalogue pages."""

from django.contrib.sitemaps import Sitemap

from .models import Book, Category, Edition, EditionStatus


class CategorySitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.6

    def items(self):
        return Category.objects.all()


class BookSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.8

    def items(self):
        return Book.objects.filter(editions__status=EditionStatus.APPROVED).distinct()

    def lastmod(self, obj):
        latest = (
            obj.editions.filter(status=EditionStatus.APPROVED).order_by("-submitted_at").first()
        )
        if latest:
            return latest.submitted_at
        return None


class EditionSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.7

    def items(self):
        return Edition.objects.filter(status=EditionStatus.APPROVED)

    def lastmod(self, obj):
        return obj.submitted_at
