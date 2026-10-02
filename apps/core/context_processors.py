from datetime import date

from django.conf import settings
from django.core.cache import cache

from apps.notifications.models import Notification
from apps.core.navigation import (
    SIDEBAR_DISCLOSURE_FROM,
    build_analytics_sections,
    build_mobile_nav_for_user,
    build_sidebar_for_user,
    build_workspace,
)


def sidebar_counts(request):
    # `shell_today` is the top bar's date and belongs to the shell alone. It
    # used to read `today`, a name pages also use for their own purposes: the
    # Target Distribution view passes `today` as an ISO string, the date filter
    # printed nothing for it, and the top bar there read "- Week 40"
    # (2026-10-01). `today` stays for the templates that already use it.
    if not request.user or not request.user.is_authenticated:
        return {
            "unread_notifications_count": 0,
            "unread_messages_count": 0,
            "pd_action_required_count": 0,
            "today": date.today(),
            "shell_today": date.today(),
            "current_week_number": date.today().isocalendar()[1],
        }

    today = date.today()
    cache_key = f"edify:sidebar-counts:v1:{request.user.id}"
    if not getattr(settings, "IS_TESTING", False):
        try:
            cached = cache.get(cache_key)
        except Exception:  # cache degradation must not block page navigation
            cached = None
        if isinstance(cached, dict):
            return {
                **cached,
                "today": today,
                "shell_today": today,
                "current_week_number": today.isocalendar()[1],
            }
    try:
        # The badge must count what the drawer shows. A resolved notification
        # is history — leaving it in the badge made the number climb forever
        # and it was the only signal most users ever saw.
        notifications_count = (
            Notification.objects.filter(recipient_id=request.user.id, status="unread")
            .exclude(resolved_at__isnull=False)
            .count()
        )
    except Exception:
        notifications_count = 0

    try:
        from apps.messaging.services import unread_thread_count

        messages_count = unread_thread_count(request.user)
    except Exception:
        messages_count = 0

    try:
        from apps.professional_development.services import StaffPDService

        pd_count = StaffPDService.action_required(request.user)["count"]
    except Exception:
        pd_count = 0

    counts = {
        "unread_notifications_count": notifications_count,
        "unread_messages_count": messages_count,
        "pd_action_required_count": pd_count,
    }
    if not getattr(settings, "IS_TESTING", False):
        try:
            cache.set(cache_key, counts, timeout=5)
        except Exception:  # page remains correct through the database fallback
            pass

    return {
        **counts,
        "today": today,
        "shell_today": today,
        "current_week_number": today.isocalendar()[1],
    }


def sidebar_context(request):
    if not request.user or not request.user.is_authenticated:
        return {
            "sidebar_sections": [],
            "analytics_sections": [],
            "mobile_nav": [],
            "in_analytics_workspace": False,
        }

    analytics_sections = build_analytics_sections(request.user, request.path)
    workspace = build_workspace(request.user, request.path)
    sidebar_sections = build_sidebar_for_user(request.user, request.path)
    return {
        "sidebar_sections": sidebar_sections,
        # A long menu gets a "Find a page" field (components/sidebar.html);
        # the same threshold decides whether its groups start closed.
        "sidebar_is_long": sum(len(sec["items"]) for sec in sidebar_sections)
        > SIDEBAR_DISCLOSURE_FROM,
        # Phone navigation, resolved from the sections just built rather than
        # from a second pass over the registry.
        "mobile_nav": build_mobile_nav_for_user(
            request.user, request.path, sections=sidebar_sections
        ),
        "analytics_sections": analytics_sections,
        # The workspace this page belongs to, if any — build_workspace already
        # withholds it when there is nowhere else to switch to, since a
        # one-section strip is decoration rather than navigation.
        "workspace": workspace,
        "in_analytics_workspace": bool(workspace and workspace["key"] == "analytics"),
    }
