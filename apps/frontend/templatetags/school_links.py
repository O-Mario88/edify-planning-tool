"""A school's name as the way into its profile.

Owner, 2026-10-08: "schools profile is only linked to school name in the
school directory i need it linked to school names everywhere". So a school's
name is written through one tag wherever it is shown, and the tag makes it a
link for anyone the profile lets in:

    {% school_link row.school_name row.school_id %}

``ref`` is either identifier a school has, its primary key or its official
School ID; the profile resolves both (`apps.schools.services.get_one`). With
no reference, or for a reader the School pages refuse (a partner), the name is
written as it was, as text: a link is only shown to someone who can follow it
(`apps.core.permissions.can_open_url`). Whether this reader may open THIS
school is the profile's own decision, as it is for every link there already
was.

Registered as a template builtin (config.settings TEMPLATES), so a template
needs no ``{% load %}`` to use it.
"""

from __future__ import annotations

from urllib.parse import quote

from django import template
from django.utils.html import format_html

register = template.Library()

_MAY_OPEN = "_edify_may_open_school_profile"


def _may_open_profiles(context) -> bool:
    """Whether the reader may open school profiles at all, asked once a
    request however many names the page shows."""
    request = context.get("request")
    user = getattr(request, "user", None)
    if request is None or user is None or not user.is_authenticated:
        return False
    answer = getattr(request, _MAY_OPEN, None)
    if answer is None:
        from apps.core.permissions import can_open_url

        answer = bool(can_open_url(user, "/schools/0"))
        try:
            setattr(request, _MAY_OPEN, answer)
        except AttributeError:
            pass
    return answer


def linked_name(context, name, ref=None, css=""):
    """The markup ``{% school_link %}`` writes, for the other tags that
    write a school's name (`apps.core.templatetags.school_identity`)."""
    label = "" if name is None else str(name)
    reference = "" if ref is None else str(ref).strip()
    if not label or not reference or not _may_open_profiles(context):
        return format_html("{}", label)
    classes = "school-link hover:underline"
    if css:
        classes = f"{classes} {css}"
    return format_html(
        '<a href="/schools/{}" class="{}" data-school-link>{}</a>',
        quote(reference, safe=""),
        classes,
        label,
    )


@register.simple_tag(takes_context=True)
def school_link(context, name, ref=None, css=""):
    """``name`` as a link to the school's profile, or as plain text where
    there is no school to open or the reader may not open one. ``css`` adds
    classes to the link (the page's own weight or colour for a name)."""
    return linked_name(context, name, ref, css)
