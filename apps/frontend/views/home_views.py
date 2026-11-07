"""Home — the phone's first tab and the native app's start page.

The figures and rows are built by apps.command_center.home_service from the
services that own them; these views only render them. The page is drawn
without the To-Do queue, which then loads into it from /home/queue.
"""

from django.shortcuts import render
from django.views.decorators.cache import cache_control, never_cache

from apps.core.permissions import require_page_permission


# Revalidated on every open, never kept by a shared cache, and allowed into
# the back/forward cache (2026-10-24): `no-store` kept it out, so going back
# to Home in the phone app rebuilt it every time. A restored Home brings its
# rows up to date itself (partials/home/queue.html).
@cache_control(private=True, no_cache=True, max_age=0, must_revalidate=True)
@require_page_permission("home")
def home_view(request):
    from apps.command_center.home_service import build_home
    from apps.partners.member_scope import MEMBER_HOME_URL, is_team_member

    # Home reads the whole organisation's queue. A partner's team member
    # schedules their own schools, so they start there (owner, 2026-11-06).
    if is_team_member(request.user):
        from django.shortcuts import redirect

        return redirect(MEMBER_HOME_URL)

    return render(
        request, "pages/home/index.html", build_home(request.user, request.path)
    )


@never_cache
@require_page_permission("home")
def home_queue_view(request):
    """Priority actions, plus the To-Do figures swapped into their tiles."""
    from apps.command_center.home_service import build_home_queue
    from apps.partners.member_scope import is_team_member

    if is_team_member(request.user):
        from django.http import HttpResponse

        return HttpResponse(status=204)

    return render(request, "partials/home/queue.html", build_home_queue(request.user))


@never_cache
@require_page_permission("home")
def home_todo_figures_view(request):
    """The To-Do figures and count, for a role whose Priority actions are its
    own list (build_home_queue)."""
    from apps.command_center.home_service import build_home_todo_figures
    from apps.partners.member_scope import is_team_member

    if is_team_member(request.user):
        from django.http import HttpResponse

        return HttpResponse(status=204)

    return render(
        request,
        "partials/home/todo_figures.html",
        build_home_todo_figures(request.user),
    )
