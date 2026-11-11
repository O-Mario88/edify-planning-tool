"""Account changes made in the Go gateway, followed up here.

Go owns account administration (owner brief, 2026-11-11: "User creation,
invitations and account lifecycle. Roles and permission management."). Two
consequences of an account change still belong to parts of this application
that have not moved, and the gateway posts the event here so they happen
exactly as they do after a change on the web:

- ``roles_changed``: the person's open planned days are re-priced at the post
  they now hold (apps/admin_users/services.py _reprice_planned_days).
- ``account_deleted``: an organisation whose login it was is released to set
  up again, and the person's web sessions end (delete_user).
- ``staff_changed``: a staff profile or a reporting line changed, so cached
  analytics are filed afresh (apps.hr.accountability_cache, which this
  application advances on every such save of its own). The two kinds above
  change staff too, and advance it as well.

Server to server: it answers only the internal key (settings.EDIFY_INTERNAL_KEY)
and stays closed while no key is configured. Nothing here changes the account
itself; Go already has.
"""

from __future__ import annotations

import json
import logging

from django.contrib.sessions.models import Session
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.admin_users.services import _reprice_planned_days

from .models import User
from .security_event_relay import internal_key_refusal

logger = logging.getLogger(__name__)

ROLES_CHANGED = "roles_changed"
ACCOUNT_DELETED = "account_deleted"
STAFF_CHANGED = "staff_changed"


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
    if kind == STAFF_CHANGED:
        _advance_analytics_revision()
        return JsonResponse({"ok": True}, status=200)
    user = User.all_objects.filter(id=str(event.get("userId") or "")).first()
    if user is None:
        return JsonResponse({"ok": False, "reason": "no_user"}, status=400)

    if kind == ROLES_CHANGED:
        if user.deleted_at is not None:
            return JsonResponse({"ok": False, "reason": "deleted"}, status=400)
        _reprice_planned_days(user.id)
        _advance_analytics_revision()
        return JsonResponse({"ok": True}, status=200)
    if kind == ACCOUNT_DELETED:
        if user.deleted_at is None:
            return JsonResponse({"ok": False, "reason": "not_deleted"}, status=400)
        unlinked = _release_organisation_login(user)
        _end_web_sessions(user)
        _advance_analytics_revision()
        return JsonResponse({"ok": True, "partnerLoginOf": unlinked}, status=200)
    return JsonResponse({"ok": False, "reason": "unknown_kind"}, status=400)


def _advance_analytics_revision() -> None:
    """What a staff or reporting-line save does here (accountability_cache
    .changed): cached analytics are filed under a new revision. A cache that
    cannot be reached loses only the optimisation."""
    from uuid import uuid4

    from django.core.cache import cache

    from apps.hr.accountability_cache import KEY

    try:
        cache.set(KEY, uuid4().hex, timeout=None)
    except Exception:  # noqa: BLE001 - the change itself is already committed
        logger.warning("Analytics revision not advanced", exc_info=True)


def _release_organisation_login(user) -> list[str]:
    """An organisation whose login is removed has no login: it goes back to
    the administrators' list of logins to set up (delete_user), and the
    release is audited beside the gateway's deletion row."""
    from apps.audit.services import log as audit_log
    from apps.partners.models import Partner, PartnerUserSetupStatus

    unlinked = list(Partner.all_objects.filter(user=user).values_list("id", flat=True))
    if unlinked:
        Partner.all_objects.filter(id__in=unlinked).update(
            user=None, user_setup_status=PartnerUserSetupStatus.PENDING
        )
        audit_log(
            action="admin.partner_login_released",
            subject_kind="user",
            subject_id=user.id,
            actor_id="system",
            actor_role="System",
            payload={"partnerLoginOf": unlinked},
        )
    return unlinked


def _end_web_sessions(user) -> None:
    for session in Session.objects.all():
        if session.get_decoded().get("_auth_user_id") == user.id:
            session.delete()
