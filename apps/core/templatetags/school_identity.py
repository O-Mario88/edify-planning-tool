"""Consistent operational school IDs for full pages and HTMX table fragments."""

from uuid import uuid4
from django import template
from django.utils.html import format_html

register = template.Library()


@register.simple_tag(takes_context=True)
def school_code(context, reference):
    if not reference:
        return format_html('<span class="edify-text-muted">{}</span>', "ID unavailable")
    request = context.get("request")
    if request is None:
        return ""
    refs = getattr(request, "_school_display_references", None)
    if refs is None:
        refs = request._school_display_references = {}
    token = uuid4().hex
    refs[token] = str(reference)
    return format_html('<span data-school-code-token="{}"></span>', token)


@register.simple_tag(takes_context=True)
def school_identity(context, name, reference=None, code=None, link=True):
    """Never infer identity by school name, which is not unique.

    The name is the link to the school's profile for a reader who may open
    one (owner, 2026-10-08: school names link to the profile everywhere;
    `apps.frontend.templatetags.school_links`). ``link=False`` where the tag
    already sits inside a link, or the page has decided this reader gets none.
    """
    if not reference and not code:
        return format_html("{}", name or "School not recorded")
    identifier = (
        format_html('<span class="school-list-id" title="School ID">{}</span>', code)
        if code
        else school_code(context, reference)
    )
    label = name or "School not recorded"
    if link and name:
        from apps.frontend.templatetags.school_links import linked_name

        label = linked_name(context, name, reference or code)
    return format_html(
        '<span class="school-list-identity">{} <span class="school-list-name">{}</span></span>',
        identifier,
        label,
    )
