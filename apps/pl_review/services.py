"""PL review queue — CCEO completions routed to the supervising PL."""
from __future__ import annotations

from django.utils import timezone

from apps.activities.models import Activity
from apps.core.exceptions import BadRequest, NotFoundError


def queue(principal) -> list[dict]:
    """Activities submitted_to_pl awaiting the PL's confirmation."""
    from apps.activities.services import _serialize

    qs = Activity.objects.filter(deleted_at__isnull=True, status="submitted_to_pl").order_by("-updated_at")
    return [_serialize(a) for a in qs.select_related("school")]


def confirm(activity_id: str, principal) -> dict:
    """PL confirms a CCEO completion -> routes to IA verification."""
    from apps.activities.services import _serialize

    a = Activity.objects.filter(id=activity_id, deleted_at__isnull=True).first()
    if not a:
        raise NotFoundError("Activity not found.")
    if a.status != "submitted_to_pl":
        raise BadRequest("Activity is not awaiting PL review.")
    a.status = "awaiting_ia_verification"
    a.pl_reviewed_at = timezone.now()
    a.pl_reviewed_by = principal.user_id
    a.save(update_fields=["status", "pl_reviewed_at", "pl_reviewed_by", "updated_at"])
    return _serialize(a)


def return_activity(activity_id: str, data: dict, principal) -> dict:
    """PL returns a completion to the CCEO for correction."""
    from apps.activities.services import _serialize

    a = Activity.objects.filter(id=activity_id, deleted_at__isnull=True).first()
    if not a:
        raise NotFoundError("Activity not found.")
    if a.status != "submitted_to_pl":
        raise BadRequest("Activity is not awaiting PL review.")
    a.status = "returned_by_pl"
    a.pl_review_note = data.get("reason")
    a.pl_reviewed_at = timezone.now()
    a.pl_reviewed_by = principal.user_id
    a.save(update_fields=["status", "pl_review_note", "pl_reviewed_at", "pl_reviewed_by", "updated_at"])
    return _serialize(a)
