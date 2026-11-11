"""Sign-in security events from the Go gateway, into Edify's admin alerts.

Go owns signing in (owner brief, 2026-11-11: "All authentication and user
workflows must be handled by Go"); this application still owns
notifications. When a sign-in through the gateway reaches the failed-login
alert threshold, or escalates a lockout, the gateway posts the event here and
this endpoint raises exactly what a sign-in on the web raises: the Admin
security incident (SecurityAlertService.failed_login_threshold_reached) and
the administrators' notification
(AuthenticationLockoutService._notify_admins_of_escalation).

Server to server: it answers only the internal key (settings.EDIFY_INTERNAL_KEY)
and stays closed while no key is configured. The gateway decides; nothing
here changes an account.
"""

from __future__ import annotations

import hmac
import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .lockout_service import AuthenticationLockoutService
from .models import User

logger = logging.getLogger(__name__)

THRESHOLD = "failed_login_threshold"
ESCALATED = "lockout_escalated"
MAX_STREAK = 1000


def internal_key_refusal(request):
    """The answer to a request without the gateway's internal key, or None.
    Closed (404) while no key is configured."""
    key = getattr(settings, "EDIFY_INTERNAL_KEY", "")
    if not key:
        return JsonResponse({"ok": False, "reason": "not_configured"}, status=404)
    if not hmac.compare_digest(
        request.headers.get("X-Edify-Internal-Key", "").encode(), key.encode()
    ):
        logger.warning("refused a gateway event without the internal key")
        return JsonResponse({"ok": False}, status=403)
    return None


@csrf_exempt  # A server's key, never a browser's session.
@require_POST
def relay(request):
    refusal = internal_key_refusal(request)
    if refusal is not None:
        return refusal
    try:
        event = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "reason": "not_json"}, status=400)
    if not isinstance(event, dict):
        return JsonResponse({"ok": False, "reason": "not_an_object"}, status=400)

    kind = str(event.get("kind") or "")
    user = User.objects.filter(id=str(event.get("userId") or "")).first()
    if user is None:
        return JsonResponse({"ok": False, "reason": "no_user"}, status=400)

    if kind == THRESHOLD:
        try:
            streak = int(event.get("streak") or 0)
        except (TypeError, ValueError):
            streak = 0
        if not 0 < streak <= MAX_STREAK:
            return JsonResponse({"ok": False, "reason": "bad_streak"}, status=400)
        # The account row is read as the gateway left it, so the alert says
        # whether that failure locked it.
        AuthenticationLockoutService._raise_security_alert(user, streak)
        return JsonResponse({"ok": True}, status=200)
    if kind == ESCALATED:
        AuthenticationLockoutService._notify_admins_of_escalation(user)
        return JsonResponse({"ok": True}, status=200)
    return JsonResponse({"ok": False, "reason": "unknown_kind"}, status=400)
