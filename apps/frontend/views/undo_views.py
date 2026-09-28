"""Recent changes and Undo — the doors to ``apps.planning.undo``.

Owner, 2026-09-28: "create a function for users to undo plans done by
mistake ... if a user assign schools to partner they are not supposed to
assign ... Same with assigning to project, adding a school to clusters".

Two ways in, one service behind both:

* the Undo button on the confirmation a save shows, for the mistake noticed
  at once — it reverses exactly what that save made, a whole bulk batch
  included;
* the Recent changes drawer on the Planning page, for the mistake noticed
  later in the week, whichever page it was made on.
"""

from __future__ import annotations

import json

from django.http import HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from apps.core.permissions import require_page_permission
from apps.planning.undo import UNDO_WINDOW, recent_changes, undo_many


def _drawer_context(request) -> dict:
    return {
        "changes": recent_changes(request.user),
        "window_days": UNDO_WINDOW.days,
        "drawer_size": "md",
    }


@require_page_permission("planning")
def recent_changes_drawer_view(request):
    """Your own partner, project and cluster changes from the last week."""
    return render(
        request,
        "partials/planning/recent_changes_drawer.html",
        _drawer_context(request),
    )


def _refresh_events(done) -> dict:
    """Every list that may still show what was undone refreshes in place."""
    events = {"planning-saved": True, "schools-updated": True}
    for result in done:
        for cluster_id in result.cluster_ids:
            events[f"cluster-schools-updated-{cluster_id}"] = True
        for project_id in result.project_ids:
            events[f"project-schools-updated-{project_id}"] = True
    return events


def _message(done, refused) -> str:
    if len(done) == 1 and not refused:
        return done[0].message
    parts = []
    if done:
        parts.append(f"Undone: {len(done)} change{'s' if len(done) != 1 else ''}.")
    if refused:
        shown = " ".join(refused[:2])
        more = f" ({len(refused) - 2} more)" if len(refused) > 2 else ""
        parts.append(
            f"{len(refused)} could not be undone: {shown}{more}"
            if done or len(refused) > 1
            else refused[0]
        )
    return " ".join(parts) or "Nothing was undone."


@require_POST
@require_page_permission("planning")
def undo_change_view(request):
    """Reverse one change, or the batch a save's confirmation offered.

    ``source=drawer`` answers with the refreshed Recent changes list and the
    confirmation out-of-band; otherwise the answer is the confirmation
    itself, which takes the place of the toast that offered the Undo.
    """
    kind = (request.POST.get("kind") or "").strip()
    ids = [value.strip() for value in (request.POST.get("ids") or "").split(",")]
    done, refused = undo_many(request.user, kind, [value for value in ids if value])
    toast = {
        "message": _message(done, refused),
        "tone": "" if done else "error",
    }

    if request.POST.get("source") == "drawer":
        html = render_to_string(
            "partials/planning/recent_changes_list.html",
            _drawer_context(request),
            request=request,
        ) + render_to_string("partials/planning/saved_toast.html", toast)
    else:
        html = render_to_string(
            "partials/planning/toast_card.html", toast, request=request
        )
    response = HttpResponse(html)
    if done:
        response["HX-Trigger"] = json.dumps(_refresh_events(done))
    return response
