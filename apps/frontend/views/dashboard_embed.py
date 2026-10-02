"""Pages a dashboard carries in place (owner, 2026-09-29).

The Programme Lead's Planning Monitor and Staff Activity Log moved onto their
dashboard's This Week view and out of the sidebar ("the content in them are
not big"); the monitor took Leadership Attention's place. Each page keeps its
URL and its fragment: the dashboard section fetches the fragment, and every
request made inside the section carries ``X-Edify-Embed: dashboard`` (the
section's hx-headers, and static/js/dashboard-embed.js for the links htmx does
not own). The page answers such a request with its fragment and
``HX-Push-Url: false``, so the dashboard's address bar is never replaced by
the page's.

A Programme Lead who opens one of the pages on its own — a bookmark, an old
link, a figure's drill-down — lands on the dashboard section instead, the
page's own query carried in one dashboard parameter so the section opens on
the same filters.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from django.http import HttpResponse, QueryDict
from django.shortcuts import redirect

EMBED_HEADER = "X-Edify-Embed"
EMBED_VALUE = "dashboard"
PROGRAM_LEAD = "Program Lead"


@dataclass(frozen=True)
class EmbeddedPage:
    path: str
    #: The dashboard query parameter that carries the page's own query.
    param: str
    #: The id of the dashboard section that holds it.
    anchor: str


PLANNING_MONITOR = EmbeddedPage("/planning-monitor/", "pm", "planning-monitor")
STAFF_ACTIVITY = EmbeddedPage("/staff-activity", "sa", "staff-activity")


def is_embedded(request) -> bool:
    return request.headers.get(EMBED_HEADER) == EMBED_VALUE


def reads_on_dashboard(request) -> bool:
    """Whether this reader opened the page on its own although it lives on
    their dashboard: a Programme Lead, outside the dashboard section."""
    return getattr(request.user, "active_role", "") == PROGRAM_LEAD and not is_embedded(
        request
    )


def to_dashboard(request, page: EmbeddedPage) -> HttpResponse:
    """The dashboard section that holds the page, on the page's own query.

    The link's year becomes the dashboard's year: the dashboard has one year,
    on its title line, and the sections it carries follow it (owner,
    2026-10-02: no repeated year filter).
    """
    query = request.GET.urlencode()
    url = "/dashboard"
    if query:
        params = {page.param: query}
        year = (request.GET.get("fy") or "").strip()
        if year:
            params = {"fy": year, **params}
        url += "?" + urlencode(params)
    url += f"#{page.anchor}"
    if request.headers.get("HX-Request") == "true":
        # The browser follows a 302 inside the request and htmx would swap
        # the whole dashboard into the target; HX-Redirect moves the page.
        response = HttpResponse("")
        response["HX-Redirect"] = url
        return response
    return redirect(url)


def fragment(response: HttpResponse) -> HttpResponse:
    """A fragment answered to the dashboard section: no history entry."""
    response["HX-Push-Url"] = "false"
    return response


def carried_query(request, page: EmbeddedPage, *, fy: str = "") -> str:
    """The page's own query the dashboard carried for its section, which the
    section first fetches the page with (re-encoded, never trusted as is).

    ``fy`` is the dashboard's year. A section that reads a year reads that
    one, whatever the carried query said: the year is chosen once, on the
    dashboard's title line.
    """
    raw = request.GET.get(page.param) or ""
    query = QueryDict(raw, mutable=True)
    if fy:
        query["fy"] = fy
    return query.urlencode()
