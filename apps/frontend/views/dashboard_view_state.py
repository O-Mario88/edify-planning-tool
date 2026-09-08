"""Which view of a role's home dashboard to show: the map or the work.

Every leadership dashboard has two views under a fixed header, KPI strip and
attention band (owner, 2026-09-05): **Map** and **Operations** (the CCEO's
second view is the week). A view is a real URL (`?view=map`) so deep links
and the back button work; a tab click swaps only the view container.

The platform remembers the last view a person chose, per role, in a cookie —
a Country Director who prefers the table lands on the table next time. A
cookie rather than a model because it is a convenience, not a record: losing
it costs one click.
"""

from __future__ import annotations

from urllib.parse import urlencode

VIEW_COOKIE_PREFIX = "edify_dashboard_view_"
VIEW_COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def resolve_dashboard_view(
    request,
    *,
    role_key: str,
    default: str,
    allowed: tuple[str, ...] = ("map", "operations"),
) -> tuple[str, bool]:
    """Return ``(view, explicit)``: the view to render, and whether the request
    named it (so the response should remember it)."""
    asked = (request.GET.get("view") or "").strip().lower()
    if asked in allowed:
        return asked, True
    remembered = (
        (request.COOKIES.get(f"{VIEW_COOKIE_PREFIX}{role_key}") or "").strip().lower()
    )
    if remembered in allowed:
        return remembered, False
    return default, False


def remember_dashboard_view(response, *, role_key: str, view: str):
    response.set_cookie(
        f"{VIEW_COOKIE_PREFIX}{role_key}",
        view,
        max_age=VIEW_COOKIE_MAX_AGE,
        samesite="Lax",
        httponly=True,
    )
    return response


def dashboard_view_tabs(
    request,
    *,
    active: str,
    panel_id: str,
    view_template: str,
    tabs: list[tuple[str, str, str]],
    base_url: str = "/dashboard",
    keep: tuple[str, ...] = ("fy", "month", "activity_type"),
) -> dict:
    """The context the shared tab rail renders: one real URL per view, carrying
    the dashboard's own filters so a tab never resets the period."""
    carried = [(k, request.GET.get(k)) for k in keep if request.GET.get(k)]
    out = []
    for key, label, description in tabs:
        query = urlencode([*carried, ("view", key)])
        out.append(
            {
                "key": key,
                "label": label,
                "description": description,
                "url": f"{base_url}?{query}",
                "active": key == active,
            }
        )
    return {
        "panel_id": panel_id,
        "view_template": view_template,
        "active": active,
        "tabs": out,
    }
