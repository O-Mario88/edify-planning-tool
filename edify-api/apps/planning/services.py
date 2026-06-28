"""Planning service — plan authoring + scheduling + lifecycle."""
from __future__ import annotations

from datetime import datetime
from django.utils import timezone

from apps.core.exceptions import BadRequest, NotFoundError
from apps.core.fy import get_operational_fy

from .models import AnnualPlan, MonthlyPlan, MonthlyPlanActivity


def setup(query: dict, principal) -> list[dict]:
    """Planning setup surface (region/district/fy context)."""
    from django.db.models import Q
    from apps.core.enums import SsaIntervention
    from apps.schools.models import School
    from apps.activities.models import Activity
    from apps.analytics.services import _scoped_schools

    schools, scope = _scoped_schools(principal)
    fy = query.get("fy") or get_operational_fy()

    sit_scheduled_school_ids = set(
        Activity.objects.filter(
            deleted_at__isnull=True,
            fy=fy,
            activity_type="school_improvement_training",
            school_id__isnull=False
        ).values_list("school_id", flat=True)
    )

    from apps.ssa.models import SsaRecord
    records = SsaRecord.objects.filter(school__in=schools, fy=fy, deleted_at__isnull=True).prefetch_related("scores")
    
    school_weakest = {}
    for r in records:
        scores = sorted(r.scores.all().values("intervention", "score"), key=lambda s: s["score"])
        weakest_list = []
        for s in scores[:2]:
            code = s["intervention"]
            label = dict(SsaIntervention.choices).get(code, code)
            weakest_list.append({
                "intervention": code,
                "label": label,
                "score": s["score"]
            })
        school_weakest[r.school_id] = weakest_list

    def _serialize_planning_school(school):
        weak = school_weakest.get(school.id, [])
        weakest_area = weak[0]["label"] if len(weak) > 0 else None
        second_weak_area = weak[1]["label"] if len(weak) > 1 else None
        
        return {
            "schoolId": school.school_id,
            "name": school.name,
            "schoolType": school.school_type,
            "districtId": school.district_id,
            "subCounty": school.sub_county.name if school.sub_county else None,
            "owner": school.account_owner_name_raw or school.account_owner_id or "—",
            "ssaStatus": school.current_fy_ssa_status,
            "planningReadiness": school.planning_readiness,
            "stage": school.planning_readiness,
            "weakest": weak,
            "weakestArea": weakest_area,
            "secondWeakArea": second_weak_area
        }

    not_yet_clustered_list = schools.filter(Q(cluster_id__isnull=True) | Q(cluster_id="")).select_related("sub_county")
    not_yet_clustered_items = [_serialize_planning_school(s) for s in not_yet_clustered_list]
    
    ready_to_plan_list = schools.filter(cluster_id__isnull=False).exclude(cluster_id="").filter(current_fy_ssa_status="done", school_type="client").select_related("sub_county")
    ready_to_plan_items = [_serialize_planning_school(s) for s in ready_to_plan_list]
    
    core_school_list = schools.filter(cluster_id__isnull=False).exclude(cluster_id="").filter(school_type__in=["core", "champion"]).select_related("sub_county")
    core_school_items = [_serialize_planning_school(s) for s in core_school_list]
    
    unassessed_list = schools.filter(cluster_id__isnull=False).exclude(cluster_id="").exclude(current_fy_ssa_status="done").select_related("sub_county")
    
    sit_scheduled_items = []
    clustered_ssa_required_items = []
    
    for s in unassessed_list:
        if s.id in sit_scheduled_school_ids:
            sit_scheduled_items.append(_serialize_planning_school(s))
        else:
            clustered_ssa_required_items.append(_serialize_planning_school(s))

    return [
        {
            "key": "notYetClustered",
            "label": "Not clustered",
            "count": len(not_yet_clustered_items),
            "items": not_yet_clustered_items
        },
        {
            "key": "clusteredSsaRequired",
            "label": "Clustered, SSA required",
            "count": len(clustered_ssa_required_items),
            "items": clustered_ssa_required_items
        },
        {
            "key": "sitScheduledSsaMissing",
            "label": "SIT scheduled, SSA missing",
            "count": len(sit_scheduled_items),
            "items": sit_scheduled_items
        },
        {
            "key": "readyToPlan",
            "label": "Ready to plan",
            "count": len(ready_to_plan_items),
            "items": ready_to_plan_items
        },
        {
            "key": "coreSchoolPlanning",
            "label": "Plan core package",
            "count": len(core_school_items),
            "items": core_school_items
        }
    ]


def core_planning(query: dict, principal) -> list[dict]:
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


# The two cluster-activity kinds the spec requires the user to choose between.
CLUSTER_ACTIVITY_KINDS = {"cluster_training", "cluster_meeting"}


def schedule_cluster_activity(data: dict, principal) -> dict:
    """Schedule a cluster activity (Group Training OR Cluster Meeting).

    The user MUST choose the kind — this drives the cost computation:
      • cluster_training (group training) → venue + facilitation + group-training
        participant meals (+ mobilisation if configured).
      • cluster_meeting → cluster-meeting participant meals ONLY (no venue, no
        facilitation, never the group-training meal rate).
    Both require a cluster + an expected participant count > 0, enforced by the
    central CostingService.assert_schedulable before the activity is created."""
    from apps.activities.services import create as create_activity
    from apps.core.exceptions import BadRequest

    kind = data.get("activityType")
    if kind not in CLUSTER_ACTIVITY_KINDS:
        raise BadRequest(
            "Choose a cluster activity kind: 'cluster_training' (Group Training) "
            "or 'cluster_meeting' (Cluster Meeting)."
        )
    if not data.get("clusterId"):
        raise BadRequest("A cluster is required for a cluster activity.")
    return create_activity({**data, "activityType": kind}, principal)


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
