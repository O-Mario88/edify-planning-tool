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
def school_identity(context, name, reference=None, code=None):
    """Never infer identity by school name, which is not unique."""
    if not reference and not code:
        return format_html("{}", name or "School not recorded")
    identifier = (
        format_html('<span class="school-list-id" title="School ID">{}</span>', code)
        if code
        else school_code(context, reference)
    )
    return format_html(
        '<span class="school-list-identity">{} <span class="school-list-name">{}</span></span>',
        identifier,
        name or "School not recorded",
    )
