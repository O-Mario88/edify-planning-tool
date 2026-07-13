from apps.notifications.models import Notification
from apps.messaging.models import Message
from apps.core.navigation import build_sidebar_for_user


def sidebar_counts(request):
    if not request.user or not request.user.is_authenticated:
        return {
            "unread_notifications_count": 0,
            "unread_messages_count": 0,
            "pd_action_required_count": 0,
        }

    try:
        notifications_count = Notification.objects.filter(
            recipient_id=request.user.id, status="unread"
        ).count()
    except Exception:
        notifications_count = 0

    try:
        messages_count = Message.objects.filter(
            recipient_id=request.user.id, status="unread"
        ).count()
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
    }


def sidebar_context(request):
    if not request.user or not request.user.is_authenticated:
        return {
            "sidebar_sections": [],
        }
    return {
        "sidebar_sections": build_sidebar_for_user(request.user, request.path),
    }
