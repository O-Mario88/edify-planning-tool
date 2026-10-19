"""The answer to a drawer save that stays on the page.

Owner, 2026-10-12: "Saving everything takes too long." Every drawer save in
My Plan answered with ``<script>window.location.reload()</script>``: the
browser threw the page away and asked for it again — My Plan is 2–5 seconds
of server work and then the whole page's styling and scripts over again —
and 400 ms later the live stream's notice of the same save read the page a
second time. One save was three renders of the page. From 2026-10-12 a save
read the page's live regions once instead.

Owner, 2026-10-14: "behave like salesforce where a user has to refresh for
the data to be updated", and asked whether one's own save should still show
at once: "everything is updated upon refresh icon clicked. so that the save,
reschedule, schedule, complete, cancel... functionalities can be fast". So a
save now reads nothing: the drawer closes, a confirmation says it is saved,
and the page shows what it showed until Refresh (the browser's, or the
installed app's beside Back and Forward). static/js/live-regions.js no
longer follows the plan either.
"""

from __future__ import annotations

from django.http import HttpResponse
from django.template.loader import render_to_string

#: What the confirmation says.
SAVED_MESSAGE = "Saved. Press Refresh to see it on the page."


def saved_in_place(trigger: str = "close-drawer") -> HttpResponse:
    """Close the drawer and say it is saved; the page is read again only when
    the reader presses Refresh."""
    response = HttpResponse(
        render_to_string(
            "partials/planning/saved_toast.html", {"message": SAVED_MESSAGE}
        )
    )
    response["HX-Trigger"] = trigger
    return response


def saved_and_reloaded(trigger: str = "close-drawer") -> HttpResponse:
    """Close the drawer and read the whole page again: the money desks, left
    reloading on purpose when everything else moved to Refresh (PR #265). A
    finance row still showing its old state after its money moved invites a
    second disbursement or clearance on it."""
    response = HttpResponse("")
    response["HX-Trigger"] = trigger
    response["HX-Refresh"] = "true"
    return response
