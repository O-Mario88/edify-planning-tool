"""Planning service — plan authoring + scheduling + lifecycle."""

from __future__ import annotations

from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy

from .models import MonthlyPlan, MonthlyPlanActivity


def setup(query: dict, principal) -> list[dict]:
    """Planning setup surface (region/district/fy context)."""
    from django.db.models import Q
    from apps.core.enums import SsaIntervention
    from apps.activities.models import Activity
    from apps.analytics.services import _scoped_schools

    schools, scope = _scoped_schools(principal)
    fy = query.get("fy") or get_operational_fy()

    sit_scheduled_school_ids = set(
        Activity.objects.filter(
            deleted_at__isnull=True,
            fy=fy,
            activity_type="school_improvement_training",
            school_id__isnull=False,
        ).values_list("school_id", flat=True)
    )

    # Canonical decision rule (apps.ssa.services.latest_applicable_record):
    # confirmed records only — this function previously ranked weakest areas
    # from unconfirmed uploads while its sibling below required confirmed,
    # so the two planning surfaces could disagree on the same school.
    # Latest confirmed record per school ACROSS FYs (not fy-filtered): the
    # canonical rule (latest_applicable_record) and the create() gate use the
    # newest confirmed SSA regardless of FY — a school whose only confirmed
    # SSA is prior-FY still shows its weakest areas here (with staleness
    # surfaced separately via current_fy_ssa_status), instead of a blank that
    # disagreed with the scheduling gate.
    from apps.ssa.recommendation_engine import bulk_weakest

    school_weakest = {
        sid: [
            {
                "intervention": item["intervention"],
                "label": dict(SsaIntervention.choices).get(
                    item["intervention"], item["intervention"]
                ),
                "score": item["score"],
            }
            for item in items
        ]
        for sid, items in bulk_weakest([school.id for school in schools], n=2).items()
    }

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
            "secondWeakArea": second_weak_area,
        }

    not_yet_clustered_list = schools.filter(
        Q(cluster_id__isnull=True) | Q(cluster_id="")
    ).select_related("sub_county")
    not_yet_clustered_items = [
        _serialize_planning_school(s) for s in not_yet_clustered_list
    ]

    ready_to_plan_list = (
        schools.filter(cluster_id__isnull=False)
        .exclude(cluster_id="")
        .filter(current_fy_ssa_status="done", school_type="client")
        .select_related("sub_county")
    )
    ready_to_plan_items = [_serialize_planning_school(s) for s in ready_to_plan_list]

    core_school_list = (
        schools.filter(cluster_id__isnull=False)
        .exclude(cluster_id="")
        .filter(school_type__in=["core", "champion"])
        .select_related("sub_county")
    )
    core_school_items = [_serialize_planning_school(s) for s in core_school_list]

    unassessed_list = (
        schools.filter(cluster_id__isnull=False)
        .exclude(cluster_id="")
        .exclude(current_fy_ssa_status="done")
        .select_related("sub_county")
    )

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
            "items": not_yet_clustered_items,
        },
        {
            "key": "clusteredSsaRequired",
            "label": "Clustered, SSA required",
            "count": len(clustered_ssa_required_items),
            "items": clustered_ssa_required_items,
        },
        {
            "key": "sitScheduledSsaMissing",
            "label": "SIT scheduled, SSA missing",
            "count": len(sit_scheduled_items),
            "items": sit_scheduled_items,
        },
        {
            "key": "readyToPlan",
            "label": "Ready to plan",
            "count": len(ready_to_plan_items),
            "items": ready_to_plan_items,
        },
        {
            "key": "coreSchoolPlanning",
            "label": "Plan core package",
            "count": len(core_school_items),
            "items": core_school_items,
        },
    ]


def core_planning(query: dict, principal) -> list[dict]:
    return setup(query, principal)


def plan_builder(query: dict, principal) -> dict:
    from apps.schools.models import School
    from apps.clusters.models import Cluster
    from apps.ssa.models import SsaRecord
    from apps.core.enums import SsaIntervention
    from apps.analytics.services import _scoped_schools

    fy = query.get("fy") or get_operational_fy()

    # 1. Fetch schools in user scope
    scoped_schools, scope = _scoped_schools(principal)

    # 2. Filter schools that are clustered, have a current-FY SSA, and are client type
    ready_schools = (
        scoped_schools.filter(deleted_at__isnull=True, current_fy_ssa_status="done")
        .exclude(cluster_id__isnull=True)
        .exclude(cluster_id="")
        .select_related("district", "sub_county")
    )

    # Prefetch verified/confirmed SsaRecords for current FY for these schools to get weakest areas
    records = SsaRecord.objects.filter(
        school__in=ready_schools,
        fy=fy,
        verification_status="confirmed",
        deleted_at__isnull=True,
    ).prefetch_related("scores")

    school_weakest = {}
    school_ssa_score = {}
    for r in records:
        # FY-scoped by design (differs from bulk_weakest's newest-any-FY);
        # tie-break added so tied scores stop ordering nondeterministically.
        scores = sorted(
            r.scores.all().values("intervention", "score"),
            key=lambda s: (s["score"], s["intervention"]),
        )
        weakest_list = []
        for s in scores[:2]:
            code = s["intervention"]
            label = dict(SsaIntervention.choices).get(code, code)
            weakest_list.append(
                {"intervention": code, "label": label, "score": s["score"]}
            )
        school_weakest[r.school_id] = weakest_list
        school_ssa_score[r.school_id] = r.average_score

    # Fetch cluster names
    cluster_ids = set(ready_schools.values_list("cluster_id", flat=True))
    clusters_in_scope = Cluster.objects.filter(
        id__in=cluster_ids, deleted_at__isnull=True
    ).select_related("district")
    cluster_name_map = {c.id: c.name for c in clusters_in_scope}

    serialized_schools = []
    for s in ready_schools:
        weak = school_weakest.get(s.id, [])
        weakest_area = weak[0]["label"] if len(weak) > 0 else None
        second_weak_area = weak[1]["label"] if len(weak) > 1 else None

        serialized_schools.append(
            {
                "schoolId": s.school_id,
                "name": s.name,
                "schoolType": s.school_type,
                "district": s.district.name if s.district else "",
                "clusterId": s.cluster_id,
                "cluster": cluster_name_map.get(s.cluster_id, "—"),
                "subCounty": s.sub_county.name if s.sub_county else None,
                "owner": s.account_owner_name_raw or s.account_owner_id or "—",
                "ssaScore": school_ssa_score.get(s.id),
                "weakest": weak,
                "weakestArea": weakest_area,
                "secondWeakArea": second_weak_area,
                "planningReadiness": s.planning_readiness,
                "stage": s.planning_readiness,
            }
        )

    # 3. Calculate cluster statistics dynamically based on member schools' most recent confirmed SSA scores
    serialized_clusters = []
    for c in clusters_in_scope:
        # Member schools of this cluster
        member_schools = School.objects.filter(cluster_id=c.id, deleted_at__isnull=True)
        school_count = member_schools.count()

        # Most recent confirmed SsaRecord for each member school
        member_records_qs = (
            SsaRecord.objects.filter(
                school__in=member_schools,
                verification_status="confirmed",
                deleted_at__isnull=True,
            )
            .prefetch_related("scores")
            .order_by("school_id", "-date_of_ssa")
        )

        most_recent_records = {}
        for r in member_records_qs:
            if r.school_id not in most_recent_records:
                most_recent_records[r.school_id] = r

        total_score = 0.0
        record_count = 0

        interv_sums = {}
        interv_counts = {}

        for r in most_recent_records.values():
            if r.average_score is not None:
                total_score += r.average_score
                record_count += 1
            for s in r.scores.all():
                interv_sums[s.intervention] = (
                    interv_sums.get(s.intervention, 0.0) + s.score
                )
                interv_counts[s.intervention] = interv_counts.get(s.intervention, 0) + 1

        average_ssa = round(total_score / record_count, 2) if record_count > 0 else None

        weakest_cluster_interv = None
        interv_averages = []
        for code, label in SsaIntervention.choices:
            if code in interv_sums:
                avg_val = round(interv_sums[code] / interv_counts[code], 2)
                interv_averages.append(
                    {"intervention": code, "label": label, "avg": avg_val}
                )

        if interv_averages:
            interv_averages.sort(key=lambda x: x["avg"])
            weakest_cluster_interv = {
                "intervention": interv_averages[0]["intervention"],
                "label": interv_averages[0]["label"],
                "avg": interv_averages[0]["avg"],
            }

        serialized_clusters.append(
            {
                "clusterId": c.id,
                "clusterName": c.name,
                "district": c.district.name if c.district else "",
                "schoolCount": school_count,
                "averageSsa": average_ssa,
                "weakest": weakest_cluster_interv,
            }
        )

    fy_months = [
        f"{int(fy) - 1}-10",
        f"{int(fy) - 1}-11",
        f"{int(fy) - 1}-12",
        f"{fy}-01",
        f"{fy}-02",
        f"{fy}-03",
        f"{fy}-04",
        f"{fy}-05",
        f"{fy}-06",
        f"{fy}-07",
        f"{fy}-08",
        f"{fy}-09",
    ]
    plans = MonthlyPlan.objects.filter(
        owner_staff_id=principal.staff_profile_id, month_iso__in=fy_months
    )
    return {
        "fy": fy,
        "plans": [
            {
                "id": p.id,
                "monthIso": p.month_iso,
                "status": p.status,
                "activityCount": p.activities.count(),
            }
            for p in plans
        ],
        "schools": serialized_schools,
        "clusters": serialized_clusters,
    }


def recompute(school_id: str, principal) -> dict:
    """Recompute planning readiness for a school."""
    from apps.schools.models import School
    from apps.ssa.services import _recompute_readiness

    school = School.objects.filter(school_id=school_id).first()
    if not school:
        raise NotFoundError("School not found.")
    _recompute_readiness(school)
    return {
        "ok": True,
        "schoolId": school_id,
        "planningReadiness": school.planning_readiness,
    }


def list_plans(query: dict, principal) -> list[dict]:
    fy = query.get("fy") or get_operational_fy()
    fy_months = [
        f"{int(fy) - 1}-10",
        f"{int(fy) - 1}-11",
        f"{int(fy) - 1}-12",
        f"{fy}-01",
        f"{fy}-02",
        f"{fy}-03",
        f"{fy}-04",
        f"{fy}-05",
        f"{fy}-06",
        f"{fy}-07",
        f"{fy}-08",
        f"{fy}-09",
    ]
    qs = MonthlyPlan.objects.filter(month_iso__in=fy_months)

    if query.get("supervised") == "true" or query.get("team") == "true":
        from apps.accounts.models import StaffSupervisorAssignment

        if principal.staff_profile_id:
            supervised_ids = list(
                StaffSupervisorAssignment.objects.filter(
                    supervisor_id=principal.staff_profile_id
                ).values_list("supervisee_id", flat=True)
            )
            qs = qs.filter(owner_staff_id__in=supervised_ids)
        else:
            qs = qs.none()
        if query.get("status"):
            qs = qs.filter(status=query["status"])
    else:
        if principal.staff_profile_id:
            qs = qs.filter(owner_staff_id=principal.staff_profile_id)
        else:
            qs = qs.none()

    inc_acts = (
        query.get("supervised") == "true"
        or query.get("team") == "true"
        or query.get("includeActivities") == "true"
    )
    return [
        _serialize_plan(p, include_activities=inc_acts)
        for p in qs.order_by("-month_iso")
    ]


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
        month_iso=month_iso,
        owner_staff_id=principal.staff_profile_id,
        defaults={"owner_name": principal.name, "status": "draft"},
    )
    for act in data.get("activities", []):
        MonthlyPlanActivity.objects.create(
            plan=plan,
            kind=act.get("kind", "visit"),
            title=act.get("title", ""),
            week_of_month=act.get("weekOfMonth", 1),
            school_id=act.get("schoolId"),
            est_cost_cents=act.get("estCostCents", 0),
            intervention_area=act.get("interventionArea"),
            delivery_type=act.get("deliveryType"),
        )
    return _serialize_plan(plan, include_activities=True)


def _plan_owner_in_scope(plan: MonthlyPlan, principal) -> bool:
    """Whether `principal` supervises the plan's owner (or is Admin).

    A monthly plan is the owning CCEO's work. Holding budget.approve is not
    itself authority over *any* plan in the country — without this check any
    CCEO or PL could approve a peer's plan.
    """
    from apps.core.rbac import EdifyRole
    from apps.core.scoping import resolve_user_scope

    role = getattr(principal, "active_role", "")
    if role == EdifyRole.ADMIN.value:
        return True
    scope = resolve_user_scope(principal)
    owner = plan.owner_staff_id
    if owner and owner in (scope.supervised_staff_ids or []):
        return True
    # A plan owner may always move their own plan (submit), never approve it.
    return bool(owner and owner == getattr(principal, "staff_profile_id", None))


def _get_plan_or_404(plan_id: str) -> MonthlyPlan:
    p = MonthlyPlan.objects.filter(id=plan_id).first()
    if not p:
        raise NotFoundError("Plan not found.")
    return p


def submit_plan(plan_id: str, data: dict, principal) -> dict:
    p = _get_plan_or_404(plan_id)
    if p.owner_staff_id != getattr(principal, "staff_profile_id", None):
        from apps.core.rbac import EdifyRole

        if getattr(principal, "active_role", "") != EdifyRole.ADMIN.value:
            raise Forbidden("You may only submit your own monthly plan.")
    p.status = "submitted"
    p.submitted_at = timezone.now()
    p.save(update_fields=["status", "submitted_at"])
    return _serialize_plan(p)


def approve_plan(plan_id: str, data: dict, principal) -> dict:
    p = _get_plan_or_404(plan_id)
    if p.owner_staff_id == getattr(principal, "staff_profile_id", None):
        raise Forbidden("You cannot approve your own monthly plan.")
    if not _plan_owner_in_scope(p, principal):
        raise Forbidden("You may only approve plans for the staff you supervise.")
    p.status = "approved"
    p.approved_at = timezone.now()
    p.approved_by_id = principal.user_id
    p.save(update_fields=["status", "approved_at", "approved_by_id"])
    _audit_plan("plan_approve", p, principal)
    return _serialize_plan(p)


def return_plan(plan_id: str, data: dict, principal) -> dict:
    p = _get_plan_or_404(plan_id)
    if p.owner_staff_id == getattr(principal, "staff_profile_id", None):
        raise Forbidden("You cannot return your own monthly plan.")
    if not _plan_owner_in_scope(p, principal):
        raise Forbidden("You may only return plans for the staff you supervise.")
    reason = (data or {}).get("reason")
    p.status = "returned"
    p.returned_reason = reason
    p.save(update_fields=["status", "returned_reason"])
    _audit_plan("plan_return", p, principal, reason=reason)
    return _serialize_plan(p)


def _audit_plan(
    action: str, plan: MonthlyPlan, principal, reason: str | None = None
) -> None:
    from apps.audit.services import log as audit_log

    audit_log(
        action=action,
        subject_kind="MonthlyPlan",
        subject_id=plan.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=getattr(principal, "active_role", None),
        reason=reason,
        payload={
            "monthIso": plan.month_iso,
            "ownerStaffId": plan.owner_staff_id,
            "status": plan.status,
        },
    )


def schedule_school_visit(data: dict, principal) -> dict:
    """Schedule a school visit activity (delegates to activities.create)."""
    from apps.activities.services import create as create_activity

    act_type = data.get("activityType", "school_visit")
    return create_activity({**data, "activityType": act_type}, principal)


def assign_school_visit_to_partner(data: dict, principal) -> dict:
    from apps.activities.services import create as create_activity

    return create_activity(
        {**data, "activityType": "school_visit", "deliveryType": "partner"}, principal
    )


def schedule_cluster_training(data: dict, principal) -> dict:
    from apps.activities.services import create as create_activity

    return create_activity({**data, "activityType": "cluster_training"}, principal)


# The two cluster-activity kinds the spec requires the user to choose between.
CLUSTER_ACTIVITY_KINDS = {"cluster_training", "cluster_meeting"}


def schedule_cluster_activity(data: dict, principal) -> dict:
    """Schedule a cluster activity (Group Training OR Cluster Meeting).

    The selected kind drives the cost computation:
      • cluster_training (group training) → venue + facilitation + group-training
        participant meals (+ mobilisation if configured).
      • cluster_meeting → cluster-meeting participant meals ONLY (no venue, no
        facilitation, never the group-training meal rate).
    A cluster is the only target requirement. Participant counts improve the
    estimate but are optional, and the activity is always costed after saving."""
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
                "id": a.id,
                "kind": a.kind,
                "title": a.title,
                "weekOfMonth": a.week_of_month,
                "schoolId": a.school_id,
                "estCostCents": a.est_cost_cents,
                "status": a.status,
            }
            for a in p.activities.all()
        ]
    return out
