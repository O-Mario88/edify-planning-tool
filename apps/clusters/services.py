"""
Clusters service — ports the legacy clusters.service business logic.

Scope-constrained list, sub-county-unique create, school assignment, eligibility,
recommendations, and per-cluster intelligence. Sub-county uniqueness (§10): one
active cluster per sub-county by default — a 2nd requires CLUSTER_OVERRIDE.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Count, Q

from apps.core.enums import ClusterRecordStatus
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.rbac import Permission
from apps.core.scoping import resolve_user_scope, school_queryset
from apps.geography.models import District, SubCounty
from apps.schools.models import School

from .models import Cluster, ClusterSubCounty, SchoolClusterAssignment


def _scope_filter(principal):
    """Returns a Q to constrain clusters to the user's districts (unless country
    scope). Mirrors the legacy `where.districtId = { in: scope.districtIds }`."""
    scope = resolve_user_scope(principal)
    if scope.country_scope or scope.can_view_summary_only:
        return Q(), scope
    if scope.district_ids:
        return Q(district_id__in=scope.district_ids), scope
    return Q(district_id__in=["__none__"]), scope


def list_clusters(principal) -> list[dict]:
    """List active/needs_review clusters within scope, with school counts + SSA."""
    scope_q, scope = _scope_filter(principal)
    qs = (
        Cluster.objects.filter(scope_q, deleted_at__isnull=True, status__in=["active", "needs_review"])
        .select_related("district", "sub_county")
        .prefetch_related("covered_sub_counties__sub_county")
        .annotate(school_count=Count("assignments", filter=Q(assignments__school__deleted_at__isnull=True)))
        .order_by("name")[:1000]  # safety bound
    )
    out = []
    for c in qs:
        ssa_done = c.assignments.filter(school__deleted_at__isnull=True, school__current_fy_ssa_status="done").count()
        out.append(
            {
                "id": c.id,
                "name": c.name,
                "clusterType": c.cluster_type,
                "status": c.status,
                "district": {"name": c.district.name} if c.district_id else None,
                "subCounty": {"name": c.sub_county.name} if c.sub_county_id else None,
                "subCountyName": c.sub_county_name,
                "responsibleStaffId": c.responsible_staff_id,
                "clusterLeaderName": c.cluster_leader_name,
                "clusterLeaderPhone": c.cluster_leader_phone,
                "subCounties": [x.sub_county.name for x in c.covered_sub_counties.all()],
                "subCountyIds": [x.sub_county_id for x in c.covered_sub_counties.all()],
                "schoolCount": c.school_count,
                "schoolsWithSsa": ssa_done,
            }
        )
    return out


def _cluster_card(c: Cluster) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "district": c.district.name if c.district_id else None,
        "status": c.status,
        "clusterType": c.cluster_type,
        "subCounty": (c.sub_county.name if c.sub_county_id else None) or c.sub_county_name,
        "subCounties": [x.sub_county.name for x in c.covered_sub_counties.all()],
        "clusterLeaderName": c.cluster_leader_name,
        "clusterLeaderPhone": c.cluster_leader_phone,
        "schoolCount": getattr(c, "school_count", 0),
    }


def recommendations(school_id: str, principal) -> dict:
    """Cluster recommendations for a school (same sub-county + district)."""
    scope = resolve_user_scope(principal)
    base = school_queryset(scope)
    qs = base if base is not None else School.objects.all()
    school = qs.filter(school_id=school_id).select_related("sub_county").first()
    if not school:
        raise NotFoundError("School not found or outside scope")

    active = Q(deleted_at__isnull=True, status="active")
    same_sub: list[Cluster] = []
    if school.sub_county_id:
        same_sub = list(
            Cluster.objects.filter(active)
            .filter(Q(sub_county_id=school.sub_county_id) | Q(covered_sub_counties__sub_county_id=school.sub_county_id))
            .distinct()
            .select_related("district", "sub_county")
            .prefetch_related("covered_sub_counties__sub_county")
            .annotate(school_count=Count("assignments"))
        )
    same_sub_ids = {c.id for c in same_sub}
    same_district = [
        c
        for c in Cluster.objects.filter(active, district_id=school.district_id)
        .exclude(id__in=same_sub_ids)
        .select_related("district", "sub_county")
        .prefetch_related("covered_sub_counties__sub_county")
        .annotate(school_count=Count("assignments"))
    ]

    return {
        "schoolId": school_id,
        "district": school.district_id,
        "subCounty": school.sub_county.name if school.sub_county_id else None,
        "sameSubCounty": [_cluster_card(c) for c in same_sub],
        "sameDistrict": [_cluster_card(c) for c in same_district],
        "canCreate": Permission.CLUSTER_ASSIGN.value in scope.permissions,
        "hint": (
            f"No eligible cluster exists for this school's sub-county ({school.sub_county.name}). Create one."
            if not same_sub and school.sub_county_id
            else None
        ),
    }


def eligible_for_school(school_id: str, principal) -> dict:
    r = recommendations(school_id, principal)
    return {
        "schoolId": school_id,
        "subCounty": r["subCounty"],
        "eligible": r["sameSubCounty"],
        "districtAlternatives": r["sameDistrict"],
        "canCreate": r["canCreate"],
        "hint": r["hint"],
    }


def create_cluster(data: dict, principal) -> dict:
    """Create a cluster. Validates district↔region, sub-county↔district, and the
    sub-county uniqueness rule (override requires CLUSTER_OVERRIDE)."""
    region_id = data.get("regionId")
    district_id = data.get("districtId")
    district = District.objects.filter(id=district_id).first()
    if not district or district.region_id != region_id:
        raise BadRequest("district does not belong to region")

    scope = resolve_user_scope(principal)
    if not scope.country_scope and district_id not in scope.district_ids:
        raise Forbidden("District outside your scope")

    sub_ids = []
    if data.get("subCountyIds"):
        sub_ids = list(dict.fromkeys(data["subCountyIds"]))
    elif data.get("subCountyId"):
        sub_ids = [data["subCountyId"]]
    if not sub_ids:
        raise BadRequest("At least one sub-county is required")

    subs = list(SubCounty.objects.filter(id__in=sub_ids))
    if len(subs) != len(set(sub_ids)):
        raise BadRequest("Unknown sub-county")
    for sc in subs:
        if sc.district_id != district_id:
            raise BadRequest("sub-county does not belong to district")
    primary = next(s for s in subs if s.id == sub_ids[0])

    # Sub-county uniqueness: one active cluster per sub-county by default.
    needs_review = False
    taken = set(
        Cluster.objects.filter(deleted_at__isnull=True, status__in=["active", "needs_review"])
        .filter(Q(sub_county_id__in=sub_ids) | Q(covered_sub_counties__sub_county_id__in=sub_ids))
        .values_list("id", flat=True)
    )
    if taken:
        if Permission.CLUSTER_OVERRIDE.value in scope.permissions and data.get("overrideReason"):
            needs_review = True
        else:
            raise BadRequest("An active cluster already covers this sub-county.")

    with transaction.atomic():
        cluster = Cluster.objects.create(
            name=data.get("name") or f"{primary.name} Cluster",
            region_id=region_id,
            district_id=district_id,
            sub_county=primary,
            sub_county_name=primary.name,
            cluster_type=data.get("clusterType", "mixed"),
            status=ClusterRecordStatus.NEEDS_REVIEW if needs_review else ClusterRecordStatus.ACTIVE,
            override_reason=data.get("overrideReason"),
            responsible_staff_id=data.get("responsibleStaffId"),
            cluster_leader_name=data.get("clusterLeaderName"),
            cluster_leader_phone=data.get("clusterLeaderPhone"),
        )
        ClusterSubCounty.objects.bulk_create(
            [ClusterSubCounty(cluster=cluster, sub_county_id=sid) for sid in sub_ids]
        )
    return _cluster_card(cluster)


def create_from_school(data: dict, principal) -> dict:
    """Create a cluster seeded from a school (uses the school's geography)."""
    school = School.objects.filter(school_id=data.get("schoolId")).first()
    if not school:
        raise BadRequest("Unknown school.")
    payload = {
        "name": data.get("name") or f"{school.name} Cluster",
        "regionId": school.region_id,
        "districtId": school.district_id,
        "subCountyId": school.sub_county_id,
        "clusterType": data.get("clusterType", "mixed"),
        "responsibleStaffId": data.get("responsibleStaffId"),
        "clusterLeaderName": data.get("clusterLeaderName"),
        "clusterLeaderPhone": data.get("clusterLeaderPhone"),
    }
    return create_cluster(payload, principal)


def assign_school(school_id: str, data: dict, principal) -> dict:
    """Assign a school to a cluster (POST /schools/:id/cluster + /clusters/assign)."""
    cluster_id = data.get("clusterId")
    if not cluster_id:
        raise BadRequest("clusterId is required.")
    school = School.objects.filter(school_id=school_id).first()
    if not school:
        raise NotFoundError("School not found.")
    cluster = Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True).first()
    if not cluster:
        raise NotFoundError("Cluster not found.")
    SchoolClusterAssignment.objects.update_or_create(
        school=school, cluster=cluster, defaults={"assigned_by": principal.user_id}
    )
    # Update the school's denormalized cluster pointer + status.
    school.cluster_id = cluster.id
    school.cluster_status = "clustered"
    school.save(update_fields=["cluster_id", "cluster_status", "updated_at"])
    return {"ok": True, "schoolId": school.school_id, "clusterId": cluster.id}


def assign(data: dict, principal) -> dict:
    """POST /clusters/assign — body {schoolId, clusterId}."""
    return assign_school(data.get("schoolId", ""), data, principal)


def cluster_schools(cluster_id: str, principal) -> list[dict]:
    """Schools in a cluster, enriched with 14 requested properties."""
    cluster = Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True).first()
    if not cluster:
        raise NotFoundError("Cluster not found.")
    schools = (
        School.objects.filter(cluster_assignments__cluster=cluster, deleted_at__isnull=True)
        .select_related("district", "sub_county", "parish")
        .prefetch_related("ssa_records__scores", "activities")
        .order_by("name")
    )
    out = []
    for s in schools:
        latest_ssa = s.ssa_records.filter(deleted_at__isnull=True).order_by("-date_of_ssa").first()
        avg_score = None
        weakest_label = "None"
        struggling = []
        rec_action = "No recommended action (no SSA)"

        if latest_ssa:
            avg_score = latest_ssa.average_score
            scores = sorted(list(latest_ssa.scores.all()), key=lambda x: x.score)
            if scores:
                weakest_label = scores[0].get_intervention_display()
                weakest_key = scores[0].intervention
                for idx, x in enumerate(scores):
                    if idx < 3 or x.score < 5.5:
                        struggling.append(f"{x.get_intervention_display()}: {x.score:.1f}")
                if weakest_key == "leadership":
                    rec_action = "Schedule leadership-focused cluster training."
                else:
                    rec_action = f"Schedule {weakest_label}-focused school visit."

        # Fetch last completed visit
        last_visit = s.activities.filter(activity_type="school_visit", status="completed", deleted_at__isnull=True).order_by("-planned_date").first()
        last_visit_date = last_visit.planned_date.strftime("%Y-%m-%d") if last_visit and last_visit.planned_date else "Never"

        # Fetch last completed training
        last_training = s.activities.filter(activity_type__in=["training", "school_improvement_training"], status="completed", deleted_at__isnull=True).order_by("-planned_date").first()
        last_training_date = last_training.planned_date.strftime("%Y-%m-%d") if last_training and last_training.planned_date else "Never"

        # Assigned staff
        assigned_staff = "Unassigned"
        if s.account_owner_id:
            assigned_staff = s.account_owner_name_raw or s.account_owner_id

        out.append({
            "id": s.id,
            "schoolId": s.school_id,
            "name": s.name,
            "district": s.district.name if s.district_id else None,
            "subCounty": s.sub_county.name if s.sub_county_id else None,
            "parish": s.parish.name if s.parish_id else None,
            "schoolType": s.school_type,
            "assignedStaff": assigned_staff,
            "currentSsaAverage": avg_score,
            "weakestSsaIntervention": weakest_label,
            "topStrugglingInterventions": struggling,
            "lastVisitDate": last_visit_date,
            "lastTrainingDate": last_training_date,
            "planningStatus": s.planning_readiness,
            "ssaStatus": s.current_fy_ssa_status,
            "recommendedAction": rec_action,
        })
    return out


def cluster_detail(cluster_id: str, principal) -> dict:
    cluster = Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True).first()
    if not cluster:
        raise NotFoundError("Cluster not found.")

    schools = School.objects.filter(cluster_assignments__cluster=cluster, deleted_at__isnull=True)
    school_count = schools.count()

    # Calculate average SSA
    latest_ssas = []
    for s in schools:
        latest = s.ssa_records.filter(deleted_at__isnull=True).order_by("-date_of_ssa").first()
        if latest and latest.average_score is not None:
            latest_ssas.append(latest.average_score)
    avg_ssa = round(sum(latest_ssas) / len(latest_ssas), 1) if latest_ssas else None

    # Last meeting
    last_meeting = cluster.activities.filter(activity_type="cluster_meeting", status="completed", deleted_at__isnull=True).order_by("-planned_date").first()
    last_meeting_str = last_meeting.planned_date.strftime("%Y-%m-%d") if last_meeting and last_meeting.planned_date else "Never"

    # Last training
    last_training = cluster.activities.filter(activity_type__in=["training", "school_improvement_training"], status="completed", deleted_at__isnull=True).order_by("-planned_date").first()
    last_training_str = last_training.planned_date.strftime("%Y-%m-%d") if last_training and last_training.planned_date else "Never"

    assigned_staff = "Unassigned"
    if cluster.responsible_staff_id:
        from apps.accounts.models import StaffProfile
        staff = StaffProfile.objects.filter(staff_id=cluster.responsible_staff_id).first()
        if staff:
            assigned_staff = staff.user.name if staff.user else staff.staff_id

    return {
        "id": cluster.id,
        "name": cluster.name,
        "district": {"name": cluster.district.name} if cluster.district else None,
        "subCounty": {"name": cluster.sub_county.name} if cluster.sub_county else None,
        "schoolCount": school_count,
        "assignedStaff": assigned_staff,
        "averageSsa": avg_ssa,
        "lastMeeting": last_meeting_str,
        "lastTraining": last_training_str,
    }


def cluster_weakest_interventions(cluster_id: str, principal) -> list[dict]:
    cluster = Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True).first()
    if not cluster:
        raise NotFoundError("Cluster not found.")

    schools = School.objects.filter(cluster_assignments__cluster=cluster, deleted_at__isnull=True)

    # Collect all scores for latest SSAs of the schools
    from apps.core.enums import SsaIntervention
    intervention_scores = {key.value: [] for key in SsaIntervention}

    for s in schools:
        latest = s.ssa_records.filter(deleted_at__isnull=True).order_by("-date_of_ssa").first()
        if latest:
            for score in latest.scores.all():
                if score.score is not None:
                    intervention_scores[score.intervention].append(score.score)

    results = []
    for key in SsaIntervention:
        scores = intervention_scores[key.value]
        avg = round(sum(scores) / len(scores), 1) if scores else None
        below_count = sum(1 for x in scores if x < 5.5)

        # Recommended action based on intervention key
        label = key.label
        if key.value == "leadership":
            rec = "Schedule leadership-focused cluster training."
        else:
            rec = f"Schedule {label}-focused cluster training or school visits."

        results.append({
            "intervention": key.value,
            "label": label,
            "avg": avg,
            "schoolsBelowThreshold": below_count,
            "recommendedAction": rec,
        })

    # Filter out interventions with no scores to prevent ranking empty data, but fallback if empty
    scored = [r for r in results if r["avg"] is not None]
    if not scored:
        # Fallback if no SSAs recorded yet
        scored = results[:4]
        for item in scored:
            item["avg"] = 0.0
        return scored

    # Sort ascending by average score
    scored.sort(key=lambda x: x["avg"])
    return scored[:4]


def cluster_intervention_summary(cluster_id: str, principal) -> list[dict]:
    cluster = Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True).first()
    if not cluster:
        raise NotFoundError("Cluster not found.")
    schools = School.objects.filter(cluster_assignments__cluster=cluster, deleted_at__isnull=True)
    from apps.core.enums import SsaIntervention
    intervention_scores = {key.value: [] for key in SsaIntervention}
    for s in schools:
        latest = s.ssa_records.filter(deleted_at__isnull=True).order_by("-date_of_ssa").first()
        if latest:
            for score in latest.scores.all():
                if score.score is not None:
                    intervention_scores[score.intervention].append(score.score)
    results = []
    for key in SsaIntervention:
        scores = intervention_scores[key.value]
        avg = round(sum(scores) / len(scores), 1) if scores else 0.0
        below_count = sum(1 for x in scores if x < 5.5)
        results.append({
            "intervention": key.value,
            "label": key.label,
            "avg": avg,
            "schoolsBelowThreshold": below_count,
        })
    return results


def cluster_activity_impact(cluster_id: str, principal) -> list[dict]:
    cluster = Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True).first()
    if not cluster:
        raise NotFoundError("Cluster not found.")

    activities = cluster.activities.filter(
        status="completed",
        deleted_at__isnull=True
    ).order_by("-planned_date")

    from apps.activities.services import calculate_activity_impact

    out = []
    for a in activities:
        impact = calculate_activity_impact(a)
        out.append({
            "id": a.id,
            "activityType": a.activity_type,
            "plannedDate": a.planned_date.isoformat() if a.planned_date else None,
            "focusIntervention": a.focus_intervention,
            "activityPurposeText": a.activity_purpose_text,
            "expectedOutcome": a.expected_outcome,
            "impact": impact,
        })
    return out


def cluster_intelligence(cluster_id: str, principal) -> dict:
    """Per-cluster intelligence surface."""
    cluster = Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True).first()
    if not cluster:
        raise NotFoundError("Cluster not found.")
    schools = School.objects.filter(cluster_assignments__cluster=cluster, deleted_at__isnull=True)
    total = schools.count()
    ssa_done = schools.filter(current_fy_ssa_status="done").count()
    return {
        "id": cluster.id,
        "name": cluster.name,
        "schoolCount": total,
        "coverage": round((ssa_done / total * 100), 1) if total else 0.0,
        "schoolsWithSsa": ssa_done,
        "subCounties": [x.sub_county.name for x in cluster.covered_sub_counties.all()],
        "clusterType": cluster.cluster_type,
    }


def sub_counties_without_clusters(principal) -> list[dict]:
    """Gap board: sub-counties in scope with no active cluster."""
    scope_q, scope = _scope_filter(principal)
    covered = set(
        ClusterSubCounty.objects.filter(
            cluster__deleted_at__isnull=True, cluster__status="active"
        ).values_list("sub_county_id", flat=True)
    )
    qs = SubCounty.objects.all()
    if not scope.country_scope and scope.district_ids:
        qs = qs.filter(district_id__in=scope.district_ids)
    return [
        {"id": s.id, "name": s.name, "districtId": s.district_id}
        for s in qs.exclude(id__in=covered).order_by("name")[:500]
    ]


def cluster_planning(principal) -> list[dict]:
    """Per-cluster planning intelligence (cadence, SSA, coverage)."""
    from apps.activities.models import Activity
    from apps.core.enums import ActivityStatus
    from django.utils import timezone
    from apps.core.enums import ActivityType

    # Resolve user scope to filter clusters
    scope_q, scope = _scope_filter(principal)

    clusters = (
        Cluster.objects.filter(scope_q, deleted_at__isnull=True, status="active")
        .select_related("district", "sub_county")
        .prefetch_related("covered_sub_counties__sub_county")
    )

    out = []
    for c in clusters:
        schools = School.objects.filter(cluster_assignments__cluster=c, deleted_at__isnull=True)
        total_schools = schools.count()
        ssa_done = schools.filter(current_fy_ssa_status="done").count()

        # Activities for this cluster
        acts = Activity.objects.filter(cluster=c, deleted_at__isnull=True)
        
        meetings_completed = acts.filter(
            activity_type__in=["cluster_meeting"],
            status__in=["completed", "ia_verified", "accountant_confirmed"]
        ).count()
        
        meetings_scheduled = acts.filter(
            activity_type__in=["cluster_meeting"],
            status__in=["scheduled", "partner_scheduled", "assigned_to_partner", "evidence_uploaded", "in_progress", "awaiting_ia_verification"]
        ).count()

        trainings_completed = acts.filter(
            activity_type__in=["cluster_training", "school_improvement_training"],
            status__in=["completed", "ia_verified", "accountant_confirmed"]
        ).count()

        # Last completed meeting date
        last_meet = acts.filter(
            activity_type__in=["cluster_meeting"],
            status__in=["completed", "ia_verified", "accountant_confirmed"]
        ).order_by("-scheduled_date").first()
        last_meeting_date = last_meet.scheduled_date.isoformat() if last_meet and last_meet.scheduled_date else None

        # Next scheduled meeting date
        next_meet = acts.filter(
            activity_type__in=["cluster_meeting"],
            status__in=["scheduled", "partner_scheduled", "assigned_to_partner", "evidence_uploaded", "in_progress", "awaiting_ia_verification"]
        ).order_by("scheduled_date").first()
        next_scheduled_meeting_date = next_meet.scheduled_date.isoformat() if next_meet and next_meet.scheduled_date else None

        met_this_quarter = (meetings_completed > 0 or meetings_scheduled > 0)

        # Schools not visited / trained / neither
        visited_school_ids = set(
            Activity.objects.filter(
                school__in=schools,
                activity_type="school_visit",
                status__in=["completed", "ia_verified", "accountant_confirmed"],
                deleted_at__isnull=True
            ).values_list("school_id", flat=True)
        )
        schools_not_visited = max(0, total_schools - len(visited_school_ids))

        trained_school_ids = set(
            Activity.objects.filter(
                school__in=schools,
                activity_type__in=["school_training", "core_training", "project_activity"],
                status__in=["completed", "ia_verified", "accountant_confirmed"],
                deleted_at__isnull=True
            ).values_list("school_id", flat=True)
        )
        schools_not_trained = max(0, total_schools - len(trained_school_ids))

        neither_count = max(0, total_schools - len(visited_school_ids.union(trained_school_ids)))

        if meetings_completed == 0:
            gap_cat = "no_meetings_this_fy"
        elif not met_this_quarter:
            gap_cat = "not_met_this_quarter"
        elif schools_not_visited > 0:
            gap_cat = "schools_not_visited"
        elif schools_not_trained > 0:
            gap_cat = "schools_not_trained"
        else:
            gap_cat = "on_track"

        recommendation_headline = None
        recommendation_reason = None
        recommendation_activity_label = None
        recommendation_focus_intervention = None

        if gap_cat == "no_meetings_this_fy":
            recommendation_headline = "No cluster meetings held this FY"
            recommendation_reason = "Organize the first cluster meeting to align plans."
            recommendation_activity_label = "Schedule Cluster Meeting"
        elif gap_cat == "not_met_this_quarter":
            recommendation_headline = "No cluster meeting this quarter"
            recommendation_reason = "Keep up the quarterly cadence."
            recommendation_activity_label = "Schedule Cluster Meeting"
        elif gap_cat == "schools_not_visited":
            recommendation_headline = "Schools need visits"
            recommendation_reason = f"{schools_not_visited} schools haven't been visited."
            recommendation_activity_label = "Schedule Visit"
        elif gap_cat == "schools_not_trained":
            recommendation_headline = "Schools need training"
            recommendation_reason = f"{schools_not_trained} schools need training."
            recommendation_activity_label = "Schedule Training"

        out.append(
            {
                "id": c.id,
                "clusterName": c.name,
                "district": c.district.name if c.district else "",
                "subCounty": (c.sub_county.name if c.sub_county else "") or c.sub_county_name or "",
                "schoolsCount": total_schools,
                "schoolsWithSsa": ssa_done,
                "meetingsThisFy": meetings_completed,
                "meetingsScheduledThisFy": meetings_scheduled,
                "trainingsThisFy": trainings_completed,
                "lastMeetingDate": last_meeting_date,
                "nextScheduledMeetingDate": next_scheduled_meeting_date,
                "metThisQuarter": met_this_quarter,
                "schoolsNotVisited": schools_not_visited,
                "schoolsNotTrained": schools_not_trained,
                "schoolsNeitherVisitNorTraining": neither_count,
                "gapCategory": gap_cat,
                "recommendationHeadline": recommendation_headline,
                "recommendationReason": recommendation_reason,
                "recommendationActivityLabel": recommendation_activity_label,
                "recommendationFocusIntervention": recommendation_focus_intervention,
            }
        )
    return out


__all__ = [
    "list_clusters",
    "recommendations",
    "eligible_for_school",
    "create_cluster",
    "create_from_school",
    "assign_school",
    "assign",
    "cluster_schools",
    "cluster_detail",
    "cluster_weakest_interventions",
    "cluster_intervention_summary",
    "cluster_activity_impact",
    "cluster_intelligence",
    "sub_counties_without_clusters",
    "cluster_planning",
]
