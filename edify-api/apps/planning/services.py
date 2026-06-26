"""Planning service — plan authoring + scheduling + lifecycle."""
from __future__ import annotations

from datetime import datetime
from django.utils import timezone

from apps.core.exceptions import BadRequest, NotFoundError
from apps.core.fy import get_operational_fy

from .models import AnnualPlan, MonthlyPlan, MonthlyPlanActivity


def setup(query: dict, principal) -> dict:
    """Planning setup surface (region/district/fy context)."""
    fy = query.get("fy") or get_operational_fy()
    return {"fy": fy, "ownerStaffId": principal.staff_profile_id}


def core_planning(query: dict, principal) -> dict:
    return setup(query, principal)


def plan_builder(query: dict, principal) -> dict:
    fy = query.get("fy") or get_operational_fy()
    plans = MonthlyPlan.objects.filter(owner_staff_id=principal.staff_profile_id, month_iso__startswith=fy)
    return {
        "fy": fy,
        "plans": [
            {"id": p.id, "monthIso": p.month_iso, "status": p.status, "activityCount": p.activities.count()}
            for p in plans
        ],
    }


def recompute(school_id: str, principal) -> dict:
    """Recompute planning readiness for a school."""
    from apps.schools.models import School
    from apps.ssa.services import _recompute_readiness

    school = School.objects.filter(school_id=school_id).first()
    if not school:
        raise NotFoundError("School not found.")
    _recompute_readiness(school)
    return {"ok": True, "schoolId": school_id, "planningReadiness": school.planning_readiness}


def list_plans(query: dict, principal) -> list[dict]:
    fy = query.get("fy") or get_operational_fy()
    qs = MonthlyPlan.objects.filter(month_iso__startswith=fy)
    if principal.staff_profile_id:
        qs = qs.filter(owner_staff_id=principal.staff_profile_id)
    return [_serialize_plan(p) for p in qs.order_by("-month_iso")]


def get_plan(plan_id: str, principal) -> dict:
    p = MonthlyPlan.objects.filter(id=plan_id).first()
    if not p:
        raise NotFoundError("Plan not found.")
    return _serialize_plan(p, include_activities=True)


def create_plan(data: dict, principal) -> dict:
    if not principal.staff_profile_id:
        raise BadRequest("No staff profile linked to your account.")
    month_iso = data.get("monthIso")
    if not month_iso:
        raise BadRequest("monthIso is required (e.g. 2026-05).")
    plan, _ = MonthlyPlan.objects.update_or_create(
        month_iso=month_iso, owner_staff_id=principal.staff_profile_id,
        defaults={"owner_name": principal.name, "status": "draft"},
    )
    for act in data.get("activities", []):
        MonthlyPlanActivity.objects.create(
            plan=plan, kind=act.get("kind", "visit"), title=act.get("title", ""),
            week_of_month=act.get("weekOfMonth", 1), school_id=act.get("schoolId"),
            est_cost_cents=act.get("estCostCents", 0), intervention_area=act.get("interventionArea"),
            delivery_type=act.get("deliveryType"),
        )
    return _serialize_plan(plan, include_activities=True)


def submit_plan(plan_id: str, principal) -> dict:
    p = MonthlyPlan.objects.filter(id=plan_id).first()
    if not p:
        raise NotFoundError("Plan not found.")
    p.status = "submitted"
    p.submitted_at = timezone.now()
    p.save(update_fields=["status", "submitted_at"])
    return _serialize_plan(p)


def approve_plan(plan_id: str, principal) -> dict:
    p = MonthlyPlan.objects.filter(id=plan_id).first()
    if not p:
        raise NotFoundError("Plan not found.")
    p.status = "approved"
    p.approved_at = timezone.now()
    p.approved_by_id = principal.user_id
    p.save(update_fields=["status", "approved_at", "approved_by_id"])
    return _serialize_plan(p)


def return_plan(plan_id: str, data: dict, principal) -> dict:
    p = MonthlyPlan.objects.filter(id=plan_id).first()
    if not p:
        raise NotFoundError("Plan not found.")
    p.status = "returned"
    p.returned_reason = data.get("reason")
    p.save(update_fields=["status", "returned_reason"])
    return _serialize_plan(p)


def schedule_school_visit(data: dict, principal) -> dict:
    """Schedule a school visit activity (delegates to activities.create)."""
    from apps.activities.services import create as create_activity

    return create_activity({**data, "activityType": "school_visit"}, principal)


def assign_school_visit_to_partner(data: dict, principal) -> dict:
    from apps.activities.services import create as create_activity

    return create_activity({**data, "activityType": "school_visit", "deliveryType": "partner"}, principal)


def schedule_cluster_training(data: dict, principal) -> dict:
    from apps.activities.services import create as create_activity

    return create_activity({**data, "activityType": "cluster_training"}, principal)


def _serialize_plan(p: MonthlyPlan, include_activities: bool = False) -> dict:
    out = {
        "id": p.id,
        "monthIso": p.month_iso,
        "ownerStaffId": p.owner_staff_id,
        "ownerName": p.owner_name,
        "status": p.status,
        "totalCostCents": p.total_cost_cents,
        "submittedAt": p.submitted_at.isoformat() if p.submitted_at else None,
        "approvedAt": p.approved_at.isoformat() if p.approved_at else None,
    }
    if include_activities:
        out["activities"] = [
            {
                "id": a.id, "kind": a.kind, "title": a.title, "weekOfMonth": a.week_of_month,
                "schoolId": a.school_id, "estCostCents": a.est_cost_cents, "status": a.status,
            }
            for a in p.activities.all()
        ]
    return out
