from django import template
from django.urls import reverse
from django.utils.html import escape, mark_safe

from encyclopedia.models import NameRecord, NameRecordKind, NameRecordStatus

register = template.Library()


_NAME_KIND_MAP = {
    "author": NameRecordKind.AUTHOR,
    "editor": NameRecordKind.EDITOR,
    "publisher": NameRecordKind.PUBLISHER,
}


@register.simple_tag(takes_context=True)
def name_link(context, name, kind, slug=None):
    """Return a clickable link for a name if it maps to a name page.

    If *slug* is provided (even an empty string), it is used directly and no
    database lookup happens. If *slug* is omitted, the tag falls back to
    looking up an approved NameRecord once per request.
    """
    name = (name or "").strip()
    if not name:
        return ""

    name_record_kind = _NAME_KIND_MAP.get(kind)
    if name_record_kind is None:
        return escape(name)

    resolved_slug = slug
    if resolved_slug is None:
        request = context.get("request")
        if request is not None:
            cache = getattr(request, "_name_record_link_cache", None)
            if cache is None:
                cache = {
                    (record["kind"], record["name"]): record["slug"]
                    for record in NameRecord.objects.filter(
                        status=NameRecordStatus.APPROVED
                    ).values("kind", "name", "slug")
                }
                request._name_record_link_cache = cache
            resolved_slug = cache.get((name_record_kind, name))

    if not resolved_slug:
        return escape(name)

    if kind == "author":
        url = reverse("author_detail", kwargs={"slug": resolved_slug})
    elif kind == "editor":
        url = reverse("editor_detail", kwargs={"slug": resolved_slug})
    elif kind == "publisher":
        url = reverse("publisher_detail", kwargs={"slug": resolved_slug})
    else:
        return escape(name)

    return mark_safe(f'<a href="{escape(url)}">{escape(name)}</a>')


@register.simple_tag(takes_context=True)
def name_links(context, records, kind, separator="، "):
    """Render a list of NameRecords as linked names separated by *separator*."""
    records = list(records)
    if not records:
        return ""

    name_record_kind = _NAME_KIND_MAP.get(kind)
    if name_record_kind is None:
        return separator.join(escape(record.name) for record in records)

    links = []
    for record in records:
        resolved_slug = record.slug
        if not resolved_slug:
            resolved_slug = name_link(context, record.name, kind)
            if resolved_slug:
                links.append(resolved_slug)
            else:
                links.append(escape(record.name))
            continue

        if kind == "author":
            url = reverse("author_detail", kwargs={"slug": resolved_slug})
        elif kind == "editor":
            url = reverse("editor_detail", kwargs={"slug": resolved_slug})
        elif kind == "publisher":
            url = reverse("publisher_detail", kwargs={"slug": resolved_slug})
        else:
            links.append(escape(record.name))
            continue

        links.append(mark_safe(f'<a href="{escape(url)}">{escape(record.name)}</a>'))

    return mark_safe(separator.join(links))


@register.filter
def get_item(dictionary, key):
    """Return dictionary[key] for use in templates."""
    try:
        return dictionary.get(key)
    except AttributeError:
        return None


@register.inclusion_tag("components/core/user_name.html")
def user_name(user=None):
    """Render a user's display name plus any expert flair badge."""
    return {"user": user}


@register.inclusion_tag("components/core/avatar.html")
def avatar(user=None, size="md"):
    """Render a user's avatar (image or initials fallback)."""
    return {"user": user, "size": size}
