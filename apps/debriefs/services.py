"""Debriefs service — daily field debriefs + CCEO merge."""
from __future__ import annotations

from django.utils import timezone

from apps.core.exceptions import BadRequest, NotFoundError
from apps.core.fy import get_operational_fy

from .models import DailyDebrief


def submit(data: dict, principal) -> dict:
    debrief = DailyDebrief.objects.create(
        fy=get_operational_fy(),
        date=timezone.now(),
        submitted_by_user_id=principal.user_id,
        submitted_by_role=principal.active_role,
        staff_id=principal.staff_profile_id,
        partner_id=data.get("partnerId"),
        debrief_type=data.get("debriefType", "staff"),
        summary=data.get("summary"),
        what_happened=data.get("whatHappened"),
        what_went_well=data.get("whatWentWell"),
        what_did_not_go_well=data.get("whatDidNotGoWell"),
        blockers=data.get("blockers", []),
        blocker_other=data.get("blockerOther"),
        support_needed=data.get("supportNeeded"),
        recommendations=data.get("recommendations"),
        next_action=data.get("nextAction"),
        linked_school_ids=data.get("linkedSchoolIds", []),
        submitted_at=timezone.now(),
    )
    return _serialize(debrief)


def list_debriefs(principal, query: dict) -> list[dict]:
    qs = DailyDebrief.objects.filter(deleted_at__isnull=True).order_by("-date")
    if str(query.get("mine", "")).lower() == "true":
        qs = qs.filter(submitted_by_user_id=principal.user_id)
    return [_serialize(d) for d in qs]


def today(principal) -> list[dict]:
    today = timezone.now().date()
    qs = DailyDebrief.objects.filter(deleted_at__isnull=True, date__date=today, submitted_by_user_id=principal.user_id)
    return [_serialize(d) for d in qs]


def get_one(debrief_id: str, principal) -> dict:
    d = DailyDebrief.objects.filter(id=debrief_id, deleted_at__isnull=True).first()
    if not d:
        raise NotFoundError("Debrief not found.")
    return _serialize(d)


def merge_partner_debrief(data: dict, principal) -> dict:
    """CCEO merges a partner debrief -> routes up to PL/CD/IA/HR."""
    from apps.core.rbac import EdifyRole
    if principal.active_role != EdifyRole.CCEO.value:
        raise BadRequest("Only a CCEO can merge partner debriefs.")
    parent_id = data.get("parentDebriefId")
    parent = DailyDebrief.objects.filter(id=parent_id).first() if parent_id else None
    merged = DailyDebrief.objects.create(
        fy=get_operational_fy(),
        date=timezone.now(),
        submitted_by_user_id=principal.user_id,
        submitted_by_role=principal.active_role,
        debrief_type="merged",
        parent_debrief_id=parent_id,
        summary=data.get("summary"),
        what_happened=data.get("whatHappened"),
        submitted_at=timezone.now(),
    )
    if parent:
        parent.merged_into_debrief_id = merged.id
        parent.status = "merged"
        parent.save(update_fields=["merged_into_debrief_id", "status"])
    return _serialize(merged)


def _serialize(d: DailyDebrief) -> dict:
    return {
        "id": d.id,
        "fy": d.fy,
        "date": d.date.isoformat(),
        "debriefType": d.debrief_type,
        "status": d.status,
        "summary": d.summary,
        "whatHappened": d.what_happened,
        "whatWentWell": d.what_went_well,
        "whatDidNotGoWell": d.what_did_not_go_well,
        "blockers": d.blockers,
        "supportNeeded": d.support_needed,
        "nextAction": d.next_action,
        "submittedByUserId": d.submitted_by_user_id,
    }
