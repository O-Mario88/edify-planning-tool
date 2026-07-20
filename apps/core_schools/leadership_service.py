"""Core-school health for leadership.

The CD dashboard showed "Core Schools On Track" and "Core Schools Behind" as
KPIs and linked both to /core-schools — a page gated to CCEO/PL/IA/Admin, so
the CD clicked a number and got a 403. The RVP had no core-school metric at
all. Meanwhile the §26 completion gate (a slot needs BOTH a Salesforce ID and
evidence before it can complete) silently stalls packages, and that stall was
invisible above the field tier.

This is the read-only leadership lens: package progress, baseline→follow-up
movement, and exactly which gate each stalled slot is stuck behind. It grants
no new write powers — CD and RVP still cannot edit a core plan or override the
gate, which is the correct division of labour.
"""

from __future__ import annotations

from apps.core.enums import ssa_score_band
from apps.core.fy import get_operational_fy
from apps.core.scoping import resolve_user_scope, scoped_school_queryset

from .models import CoreActivitySlot, CorePlan


# The nine slots in a package: 1 assessment + 4 visits + 4 trainings.
PACKAGE_SLOTS = 9


def core_school_health(principal, query: dict | None = None) -> dict:
    query = query or {}
    fy = query.get("fy") or get_operational_fy()
    scope = resolve_user_scope(principal)

    schools = scoped_school_queryset(scope)
    if schools is None:
        return _empty(fy, scope)
    # CorePlan.school_id holds the *operational* School.school_id code, not the
    # primary key — see apps.core_schools.services, which looks schools up by
    # `School.objects.filter(school_id=...)` throughout.
    school_map = {
        s["school_id"]: s
        for s in schools.values("id", "name", "school_id", "district_id", "region_id")
        if s["school_id"]
    }
    if not school_map:
        return _empty(fy, scope)

    plans = list(CorePlan.objects.filter(school_id__in=list(school_map), fy=fy))
    if not plans:
        return _empty(fy, scope)

    plan_ids = [p.id for p in plans]
    slots = list(CoreActivitySlot.objects.filter(core_plan_id__in=plan_ids))
    slots_by_plan: dict[str, list] = {}
    for s in slots:
        slots_by_plan.setdefault(s.core_plan_id, []).append(s)

    district_names = _district_names(
        {s["district_id"] for s in school_map.values() if s["district_id"]}
    )

    rows, stalled = [], []
    for plan in plans:
        info = school_map.get(plan.school_id, {})
        plan_slots = slots_by_plan.get(plan.id, [])
        done = sum(1 for s in plan_slots if s.status == "Completed")
        blocked = [s for s in plan_slots if _gate_blocker(s)]

        movement = None
        if plan.baseline_average is not None and plan.follow_up_average is not None:
            movement = round(plan.follow_up_average - plan.baseline_average, 2)

        row = {
            "planId": plan.id,
            "schoolId": info.get("id"),
            "name": info.get("name", "—"),
            "code": plan.school_id,
            "district": district_names.get(info.get("district_id"), "—"),
            "status": plan.status,
            "slotsDone": done,
            "slotsTotal": len(plan_slots) or PACKAGE_SLOTS,
            "progressPct": round(100 * done / (len(plan_slots) or PACKAGE_SLOTS)),
            "visits": f"{plan.visits_completed}/{plan.visits_target}",
            "trainings": f"{plan.trainings_completed}/{plan.trainings_target}",
            "assessmentDone": bool(plan.assessment_completed),
            "baseline": plan.baseline_average,
            "followUp": plan.follow_up_average,
            "movement": movement,
            "baselineBand": (
                ssa_score_band(plan.baseline_average)
                if plan.baseline_average is not None
                else None
            ),
            "followUpBand": (
                ssa_score_band(plan.follow_up_average)
                if plan.follow_up_average is not None
                else None
            ),
            "blockedCount": len(blocked),
            "onTrack": done >= (len(plan_slots) or PACKAGE_SLOTS) - 2 and not blocked,
        }
        rows.append(row)

        for slot in blocked:
            stalled.append(
                {
                    "school": row["name"],
                    "district": row["district"],
                    "slot": f"{slot.activity_type.title()} {slot.sequence_number}",
                    "intervention": slot.intervention,
                    "blocker": _gate_blocker(slot),
                    "assignedTo": slot.assigned_staff_name
                    or slot.assigned_partner_name
                    or "Unassigned",
                }
            )

    rows.sort(key=lambda r: (r["onTrack"], r["progressPct"]))
    show_identity = scope.can_view_school_level_detail

    improved = [r for r in rows if r["movement"] is not None and r["movement"] > 0]
    declined = [r for r in rows if r["movement"] is not None and r["movement"] < 0]

    return {
        "fy": fy,
        "canViewSchoolDetail": show_identity,
        "plans": rows if show_identity else [],
        "districts": _district_rollup(rows),
        "stalledSlots": stalled if show_identity else [],
        "totalPlans": len(rows),
        "onTrackCount": sum(1 for r in rows if r["onTrack"]),
        "behindCount": sum(1 for r in rows if not r["onTrack"]),
        "blockedSlotCount": len(stalled),
        "measuredCount": len(improved) + len(declined),
        "improvedCount": len(improved),
        "declinedCount": len(declined),
        "avgMovement": (
            round(
                sum(r["movement"] for r in improved + declined)
                / len(improved + declined),
                2,
            )
            if (improved or declined)
            else None
        ),
        "empty": False,
    }


def _gate_blocker(slot) -> str | None:
    """Why this slot cannot complete — the §26 gate, made visible.

    Returns None for slots that are already complete or not yet due to be.
    """
    if slot.status == "Completed":
        return None
    # Only a slot that has actually been worked can be "stalled at the gate".
    worked = slot.status in ("In Progress", "Evidence Uploaded", "Completion Started")
    if not worked:
        return None
    has_sf = bool((slot.salesforce_id or "").strip())
    has_evidence = bool((slot.evidence_uri or "").strip())
    if not has_sf and not has_evidence:
        return "Needs Salesforce ID and evidence"
    if not has_sf:
        return "Needs Salesforce ID"
    if not has_evidence:
        return "Needs evidence"
    return None


def _district_rollup(rows: list[dict]) -> list[dict]:
    buckets: dict[str, dict] = {}
    for r in rows:
        key = r["district"] or "—"
        b = buckets.setdefault(
            key,
            {
                "district": key,
                "planCount": 0,
                "onTrack": 0,
                "behind": 0,
                "blockedSlots": 0,
            },
        )
        b["planCount"] += 1
        b["onTrack"] += 1 if r["onTrack"] else 0
        b["behind"] += 0 if r["onTrack"] else 1
        b["blockedSlots"] += r["blockedCount"]
    return sorted(buckets.values(), key=lambda b: -b["behind"])


def _district_names(district_ids) -> dict[str, str]:
    ids = [d for d in district_ids if d]
    if not ids:
        return {}
    try:
        from apps.geography.models import District

        return {
            d["id"]: d["name"]
            for d in District.objects.filter(id__in=ids).values("id", "name")
        }
    except Exception:  # noqa: BLE001
        return {}


def _empty(fy: str, scope) -> dict:
    return {
        "fy": fy,
        "canViewSchoolDetail": scope.can_view_school_level_detail,
        "plans": [],
        "districts": [],
        "stalledSlots": [],
        "totalPlans": 0,
        "onTrackCount": 0,
        "behindCount": 0,
        "blockedSlotCount": 0,
        "measuredCount": 0,
        "improvedCount": 0,
        "declinedCount": 0,
        "avgMovement": None,
        "empty": True,
    }


__all__ = ["core_school_health", "PACKAGE_SLOTS"]
