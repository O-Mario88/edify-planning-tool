"""Home — the phone's first tab and the native app's start page.

The figures and rows are built by apps.command_center.home_service from the
services that own them; these views only render them. The page is drawn
without the To-Do queue, which then loads into it from /home/queue.
"""

from django.shortcuts import render
from django.views.decorators.cache import never_cache

from apps.core.permissions import require_page_permission


@never_cache
@require_page_permission("home")
def home_view(request):
    from apps.command_center.home_service import build_home

    return render(
        request, "pages/home/index.html", build_home(request.user, request.path)
    )


@never_cache
@require_page_permission("home")
def home_queue_view(request):
    """Priority actions, plus the To-Do figures swapped into their tiles."""
    from apps.command_center.home_service import build_home_queue

    return render(request, "partials/home/queue.html", build_home_queue(request.user))
