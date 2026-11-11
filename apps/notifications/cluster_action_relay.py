"""Cluster Action notices from the Go gateway, into Edify's notifications.

The gateway owns the Cluster Action Register (owner brief, 2026-11-11) and
decides who is told about each change; this endpoint only writes each notice
through notify_from_person, so the bell, push and email follow as for any
other notification. It is server to server: it answers only the internal key
(settings.EDIFY_INTERNAL_KEY) and stays closed while no key is configured.
Delivering the same notice twice writes it once.
"""

from __future__ import annotations

import hmac
import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.models import User

from .models import Notification
from .services import notify_from_person

logger = logging.getLogger(__name__)

CONTEXT_TYPE = "cluster_action"
MAX_TITLE = 255
MAX_BODY = 4000


@csrf_exempt  # A server's key, never a browser's session.
@require_POST
def relay(request):
    key = getattr(settings, "EDIFY_INTERNAL_KEY", "")
    if not key:
        return JsonResponse({"ok": False, "reason": "not_configured"}, status=404)
    if not hmac.compare_digest(
        request.headers.get("X-Edify-Internal-Key", "").encode(), key.encode()
    ):
        logger.warning("refused a cluster action notice without the internal key")
        return JsonResponse({"ok": False}, status=403)
    try:
        notice = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "reason": "not_json"}, status=400)

    recipient_id = str(notice.get("recipientId") or "")
    title = str(notice.get("title") or "").strip()[:MAX_TITLE]
    body = str(notice.get("body") or "").strip()[:MAX_BODY]
    event = str(notice.get("event") or "").strip()[:64]
    ref = str(notice.get("contextRef") or "").strip()[:30]
    # A notice's own id, compact, so a retried delivery is recognised.
    source_id = str(notice.get("noticeId") or "").replace("-", "")[:30]
    if not (title and event and ref and source_id):
        return JsonResponse({"ok": False, "reason": "incomplete"}, status=400)
    recipient = User.objects.filter(
        id=recipient_id, is_active=True, deleted_at__isnull=True
    ).first()
    if recipient is None:
        return JsonResponse({"ok": False, "reason": "no_recipient"}, status=400)
    sender = User.objects.filter(id=str(notice.get("senderId") or "")).first()

    if Notification.objects.filter(
        recipient_id=recipient.id,
        context_type=CONTEXT_TYPE,
        context_id=ref,
        source_event_type=event,
        source_event_id=source_id,
    ).exists():
        return JsonResponse({"ok": True, "duplicate": True}, status=200)

    _, created = notify_from_person(
        sender,
        recipient_id=recipient.id,
        context_type=CONTEXT_TYPE,
        context_id=ref,
        source_event_type=event,
        defaults={
            "recipient_role": recipient.active_role,
            "title": title,
            "body": body,
            "category": "cluster_support",
            "target_route": str(notice.get("targetRoute") or "")[:255] or None,
            "action_label": "Open cluster",
            "action_required": True,
            "source_event_id": source_id,
        },
    )
    return JsonResponse(
        {"ok": True, "created": created}, status=201 if created else 200
    )
