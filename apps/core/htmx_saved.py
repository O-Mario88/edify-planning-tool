"""The answer to a drawer save that stays on the page.

Owner, 2026-10-12: "Saving everything takes too long." Every drawer save in
My Plan answered with ``<script>window.location.reload()</script>``: the
browser threw the page away and asked for it again — My Plan is 2–5 seconds
of server work and then the whole page's styling and scripts over again —
and 400 ms later the live stream's notice of the same save read the page a
second time. One save was three renders of the page.

The answer is now a call to the page's live regions (static/js/live-regions.js
``EdifyLive.saved``): the drawer closes, the regions that show the plan are
read once and swapped in place, and the stream's echo of this save is
recognised and skipped. A page with no live region reloads as before, so
nothing is left stale.
"""

from __future__ import annotations

from django.http import HttpResponse

#: Read the page's live regions again; reload only where there are none.
SAVED_SCRIPT = (
    "<script>(window.EdifyLive && window.EdifyLive.saved) "
    "? window.EdifyLive.saved() : window.location.reload();</script>"
)


def saved_in_place(trigger: str = "close-drawer") -> HttpResponse:
    """Close the drawer and bring the page up to date without reloading it."""
    response = HttpResponse(SAVED_SCRIPT)
    response["HX-Trigger"] = trigger
    return response
