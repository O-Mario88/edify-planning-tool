"""The brief page: a role's brief with its links, and the channel it is sent on.

The bell notice and the text message both open this page. It builds the brief
again from the live figures, so it is never older than the page a line links
to. It is not in the sidebar (owner, 2026-10-02: the sidebar does not grow).
"""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.briefs import builder, delivery
from apps.core.permissions import require_page_permission

PAGE_URL = "/brief"


@require_page_permission("brief")
@require_http_methods(["GET"])
def brief_view(request):
    """The reader's brief for the role they are working in."""
    kinds = builder.kinds_for(request.user)
    active = next(
        (
            kind
            for kind in kinds
            if builder.BRIEF_ROLES[kind] == request.user.active_role
        ),
        None,
    )
    kind = request.GET.get("kind")
    if kind not in kinds:
        kind = active or (kinds[0] if kinds else None)
    today = timezone.localdate()
    brief = builder.build(kind, request.user, today) if kind else None
    channel = getattr(request.user, "brief_channel", delivery.CHANNEL_APP)
    return render(
        request,
        "pages/briefs/index.html",
        {
            "kind": kind,
            "brief_name": builder.BRIEF_NAMES.get(kind, "Brief"),
            "brief": brief,
            "today": today,
            "channels": [
                {**option, "chosen": option["channel"] == channel}
                for option in delivery.channels_open_to(request.user)
            ],
        },
    )


@require_page_permission("brief")
@require_http_methods(["POST"])
def brief_channel_view(request):
    """Save where the reader's brief is sent."""
    if delivery.set_channel(request.user, request.POST.get("channel") or ""):
        messages.success(request, "Saved. Your next brief will follow this choice.")
    else:
        messages.error(request, "That channel is not available on your account.")
    return redirect(PAGE_URL)
