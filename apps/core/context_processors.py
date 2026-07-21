from datetime import date

from apps.notifications.models import Notification
from apps.core.navigation import build_sidebar_for_user


def sidebar_counts(request):
    if not request.user or not request.user.is_authenticated:
        return {
            "unread_notifications_count": 0,
            "unread_messages_count": 0,
            "pd_action_required_count": 0,
            "today": date.today(),
            "current_week_number": date.today().isocalendar()[1],
        }

    today = date.today()
    try:
        # The badge must count what the drawer shows. A resolved notification
        # is history — leaving it in the badge made the number climb forever
        # and it was the only signal most users ever saw.
        notifications_count = (
            Notification.objects.filter(
                recipient_id=request.user.id, status="unread"
            )
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

    return {
        "unread_notifications_count": notifications_count,
        "unread_messages_count": messages_count,
        "pd_action_required_count": pd_count,
        "today": today,
        "current_week_number": today.isocalendar()[1],
    }


def sidebar_context(request):
    if not request.user or not request.user.is_authenticated:
        return {
            "sidebar_sections": [],
        }
    return {
        "sidebar_sections": build_sidebar_for_user(request.user, request.path),
    }
