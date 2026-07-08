from apps.notifications.models import Notification
from apps.messaging.models import Message
from apps.core.navigation import build_sidebar_for_user

def sidebar_counts(request):
    if not request.user or not request.user.is_authenticated:
        return {
            "unread_notifications_count": 0,
            "unread_messages_count": 0,
        }
    
    try:
        notifications_count = Notification.objects.filter(recipient_id=request.user.id, status="unread").count()
    except Exception:
        notifications_count = 0

    try:
        messages_count = Message.objects.filter(recipient_id=request.user.id, status="unread").count()
    except Exception:
        messages_count = 0
        
    return {
        "unread_notifications_count": notifications_count,
        "unread_messages_count": messages_count,
    }


def sidebar_context(request):
    if not request.user or not request.user.is_authenticated:
        return {
            "sidebar_sections": [],
        }
    return {
        "sidebar_sections": build_sidebar_for_user(request.user, request.path),
    }

