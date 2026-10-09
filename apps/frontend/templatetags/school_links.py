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


# ── The other names that have a profile ─────────────────────────────────────
# Owner, 2026-10-09: "clicking the cluster name or school name or district
# name ... can open the profile? The name should be a link to the profile
# irrespective of where they are clicked from." The same rule as a school's
# name, for everything else the platform has a profile of: one tag each, text
# where there is nothing to open or the reader may not open it.
_PROFILES = {
    "cluster": "/clusters/",
    "district": "/districts/",
    "sub_region": "/sub-regions/",
    "partner": "/partners/",
    "staff": "/staff/",
}


def _may_open(context, kind: str) -> bool:
    """Whether the reader may open profiles of this kind at all, asked once a
    request however many names the page shows."""
    request = context.get("request")
    user = getattr(request, "user", None)
    if request is None or user is None or not user.is_authenticated:
        return False
    key = f"_edify_may_open_{kind}_profile"
    answer = getattr(request, key, None)
    if answer is None:
        from apps.core.permissions import can_open_url

        answer = bool(can_open_url(user, f"{_PROFILES[kind]}0"))
        try:
            setattr(request, key, answer)
        except AttributeError:
            pass
    return answer


def _profile_link(context, kind, name, ref, css, empty=""):
    label = "" if name is None else str(name)
    reference = "" if ref is None else str(ref).strip()
    if not label:
        # What the page writes where there is no name (a dash).
        return format_html("{}", empty)
    if not reference or not _may_open(context, kind):
        return format_html("{}", label)
    classes = "profile-link hover:underline"
    if css:
        classes = f"{classes} {css}"
    return format_html(
        '<a href="{}{}" class="{}" data-profile-link="{}">{}</a>',
        _PROFILES[kind],
        quote(reference, safe=""),
        classes,
        kind,
        label,
    )


@register.simple_tag(takes_context=True)
def cluster_link(context, name, ref=None, css="", empty=""):
    """A cluster's name as the way into its profile."""
    return _profile_link(context, "cluster", name, ref, css, empty)


@register.simple_tag(takes_context=True)
def district_link(context, name, ref=None, css="", empty=""):
    """A district's name as the way into its profile."""
    return _profile_link(context, "district", name, ref, css, empty)


@register.simple_tag(takes_context=True)
def sub_region_link(context, name, ref=None, css="", empty=""):
    """A sub-region's name as the way into its profile."""
    return _profile_link(context, "sub_region", name, ref, css, empty)


@register.simple_tag(takes_context=True)
def partner_link(context, name, ref=None, css="", empty=""):
    """A partner organisation's name as the way into its profile."""
    return _profile_link(context, "partner", name, ref, css, empty)


@register.simple_tag(takes_context=True)
def staff_link(context, name, ref=None, css="", empty=""):
    """A staff member's name as the way into their profile (``ref`` is the
    person's user id or staff id; the profile resolves both)."""
    return _profile_link(context, "staff", name, ref, css, empty)
