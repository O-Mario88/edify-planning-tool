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
    clusters = list(
        Cluster.objects.filter(
            scope_q, deleted_at__isnull=True, status__in=["active", "needs_review"]
        )
        .select_related("district", "sub_county")
        .prefetch_related("covered_sub_counties__sub_county")
        .order_by("name")[:1000]  # safety bound
    )
    cluster_ids = [cluster.id for cluster in clusters]
    school_counts = {
        row["cluster_id"]: row["count"]
        for row in School.objects.filter(
            cluster_id__in=cluster_ids, deleted_at__isnull=True
        )
        .values("cluster_id")
        .annotate(count=Count("id"))
    }
    completed_ssa_counts = {
        row["cluster_id"]: row["count"]
        for row in School.objects.filter(
            cluster_id__in=cluster_ids,
            deleted_at__isnull=True,
            current_fy_ssa_status="done",
        )
        .values("cluster_id")
        .annotate(count=Count("id"))
    }
    out = []
    for c in clusters:
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
                "subCounties": [
                    x.sub_county.name for x in c.covered_sub_counties.all()
                ],
                "subCountyIds": [x.sub_county_id for x in c.covered_sub_counties.all()],
                "schoolCount": school_counts.get(c.id, 0),
                "schoolsWithSsa": completed_ssa_counts.get(c.id, 0),
            }
        )
    return out


def _cluster_card(c: Cluster) -> dict:
    sub_counties_list = [x.sub_county.name for x in c.covered_sub_counties.all()]
    return {
        "id": c.id,
        "name": c.name,
        "district": c.district.name if c.district_id else None,
        "status": c.status,
        "clusterType": c.cluster_type,
        "subCounty": ", ".join(sub_counties_list)
        if sub_counties_list
        else (
            (c.sub_county.name if c.sub_county_id else None)
            or c.sub_county_name
            or "District-level cluster"
        ),
        "subCounties": sub_counties_list,
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
            .filter(
                Q(sub_county_id=school.sub_county_id)
                | Q(covered_sub_counties__sub_county_id=school.sub_county_id)
            )
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

    # Sub-county is OPTIONAL. District + Name are the only hard requirements.
    subs = []
    primary = None
    if sub_ids:
        subs = list(SubCounty.objects.filter(id__in=sub_ids))
        if len(subs) != len(set(sub_ids)):
            raise BadRequest("Unknown sub-county")
        for sc in subs:
            if sc.district_id != district_id:
                raise BadRequest("sub-county does not belong to district")
        primary = next(s for s in subs if s.id == sub_ids[0])

    # Sub-county uniqueness: one active cluster per sub-county by default.
    needs_review = False
    if sub_ids:
        taken = set(
            Cluster.objects.filter(
                deleted_at__isnull=True, status__in=["active", "needs_review"]
            )
            .filter(
                Q(sub_county_id__in=sub_ids)
                | Q(covered_sub_counties__sub_county_id__in=sub_ids)
            )
            .values_list("id", flat=True)
        )
        if taken:
            if Permission.CLUSTER_OVERRIDE.value in scope.permissions and data.get(
                "overrideReason"
            ):
                needs_review = True
            else:
                raise BadRequest("An active cluster already covers this sub-county.")

    default_name = f"{primary.name} Cluster" if primary else f"{district.name} Cluster"
    cluster_name = (data.get("name") or default_name).strip()
    if Cluster.objects.filter(
        district_id=district_id,
        name__iexact=cluster_name,
        deleted_at__isnull=True,
    ).exists():
        raise BadRequest("A cluster with this name already exists in this district.")

    with transaction.atomic():
        cluster = Cluster.objects.create(
            name=cluster_name,
            region_id=region_id,
            district_id=district_id,
            sub_county=primary,
            sub_county_name=primary.name if primary else None,
            cluster_type=data.get("clusterType", "mixed"),
            status=ClusterRecordStatus.NEEDS_REVIEW
            if needs_review
            else ClusterRecordStatus.ACTIVE,
            override_reason=data.get("overrideReason"),
            responsible_staff_id=data.get("responsibleStaffId"),
            cluster_leader_name=data.get("clusterLeaderName"),
            cluster_leader_phone=data.get("clusterLeaderPhone"),
        )
        if sub_ids:
            ClusterSubCounty.objects.bulk_create(
                [
                    ClusterSubCounty(cluster=cluster, sub_county_id=sid)
                    for sid in sub_ids
                ]
            )
    return _cluster_card(cluster)


def update_cluster(cluster_id: str, data: dict, principal) -> dict:
    """Update an existing cluster details and covered sub-counties."""
    from apps.core.exceptions import NotFoundError, BadRequest, Forbidden

    cluster = Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True).first()
    if not cluster:
        raise NotFoundError("Cluster not found")

    region_id = data.get("regionId")
    district_id = data.get("districtId")
    if district_id:
        district = District.objects.filter(id=district_id).first()
        if not district:
            raise BadRequest("Unknown district")
        if region_id and district.region_id != region_id:
            raise BadRequest("district does not belong to region")
        cluster.district = district
        if not region_id:
            region_id = district.region_id
        cluster.region_id = region_id

    scope = resolve_user_scope(principal)
    if (
        district_id
        and not scope.country_scope
        and district_id not in scope.district_ids
    ):
        raise Forbidden("District outside your scope")

    if "name" in data:
        cluster.name = data["name"]
    if "clusterType" in data:
        cluster.cluster_type = data["clusterType"]
    if "clusterLeaderName" in data:
        cluster.cluster_leader_name = data["clusterLeaderName"]
    if "clusterLeaderPhone" in data:
        cluster.cluster_leader_phone = data["clusterLeaderPhone"]
    if "responsibleStaffId" in data:
        cluster.responsible_staff_id = data["responsibleStaffId"]

    # Sub-counties
    if "subCountyIds" in data:
        sub_ids = list(dict.fromkeys(data["subCountyIds"]))
        subs = list(SubCounty.objects.filter(id__in=sub_ids))
        for sc in subs:
            if sc.district_id != cluster.district_id:
                raise BadRequest("sub-county does not belong to district")

        with transaction.atomic():
            # Delete old joins
            ClusterSubCounty.objects.filter(cluster=cluster).delete()
            # Set primary
            if subs:
                cluster.sub_county = subs[0]
                cluster.sub_county_name = subs[0].name
                # Create new joins
                ClusterSubCounty.objects.bulk_create(
                    [
                        ClusterSubCounty(cluster=cluster, sub_county_id=sid)
                        for sid in sub_ids
                    ]
                )
            else:
                cluster.sub_county = None
                cluster.sub_county_name = None
            cluster.save()
    else:
        cluster.save()

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
        "clusterType": data.get("clusterType", "mixed"),
        "responsibleStaffId": data.get("responsibleStaffId"),
        "clusterLeaderName": data.get("clusterLeaderName"),
        "clusterLeaderPhone": data.get("clusterLeaderPhone"),
    }
    # Only pass sub-county if the school actually has one.
    if school.sub_county_id:
        payload["subCountyId"] = school.sub_county_id
    return create_cluster(payload, principal)


def set_school_cluster_membership(school, cluster, assigned_by: str):
    """Apply the only supported operational cluster-membership transition.

    ``School.cluster_id`` is the canonical membership source used by scope,
    planning, activities and analytics. ``SchoolClusterAssignment`` is kept as
    a deterministic compatibility/audit projection for older records; readers
    must never use it to decide membership. The school row is locked so two
    concurrent assignments cannot leave competing cluster records behind.
    """
    if cluster and (cluster.deleted_at or cluster.status != ClusterRecordStatus.ACTIVE):
        raise BadRequest("A school can only be assigned to an active cluster.")
    if cluster and school.district_id != cluster.district_id:
        raise BadRequest("A school can only be assigned within its own district.")

    with transaction.atomic():
        school = School.objects.select_for_update().get(pk=school.pk)
        target_cluster_id = cluster.id if cluster else None
        school.cluster_id = target_cluster_id
        school.cluster_status = "clustered" if target_cluster_id else "unclustered"
        # ``School.save`` derives quality/readiness using the canonical pointer;
        # include those derived fields so the UI cannot retain a stale badge.
        school.save(
            update_fields=[
                "cluster_id",
                "cluster_status",
                "planning_readiness",
                "data_quality_score",
                "data_quality_status",
                "updated_at",
            ]
        )
        assignments = SchoolClusterAssignment.objects.select_for_update().filter(
            school=school
        )
        assignments.delete()
        if cluster:
            SchoolClusterAssignment.objects.create(
                school=school, cluster=cluster, assigned_by=assigned_by
            )
    return school


def sync_school_cluster_assignment(school, cluster, assigned_by: str):
    """Compatibility wrapper for legacy callers.

    New callers should use :func:`set_school_cluster_membership`; keeping this
    wrapper prevents a stale assignment row from becoming an alternate source
    of truth while existing integrations migrate.
    """
    return set_school_cluster_membership(school, cluster, assigned_by)


def assign_school(school_id: str, data: dict, principal) -> dict:
    """Assign a school to a cluster (POST /schools/:id/cluster + /clusters/assign)."""
    cluster_id = data.get("clusterId")
    if not cluster_id:
        raise BadRequest("clusterId is required.")
    scope = resolve_user_scope(principal)
    schools = school_queryset(scope)
    school = (schools or School.objects.none()).filter(school_id=school_id).first()
    if not school:
        raise NotFoundError("School not found or outside your scope.")
    cluster = Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True).first()
    if not cluster:
        raise NotFoundError("Cluster not found.")
    scope_q, _ = _scope_filter(principal)
    if not Cluster.objects.filter(scope_q, id=cluster.id).exists():
        raise Forbidden("Cluster outside your scope.")
    school = set_school_cluster_membership(school, cluster, principal.user_id)
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
        School.objects.filter(cluster_id=cluster.id, deleted_at__isnull=True)
        .select_related("district", "sub_county", "parish")
        .prefetch_related("ssa_records__scores", "activities")
        .order_by("name")
    )

    # Query completed cluster activities to compute attendance rate
    from apps.activities.models import Activity

    cluster_activities = list(
        Activity.objects.filter(
            cluster=cluster,
            status="completed",
            activity_type__in=[
                "cluster_meeting",
                "training",
                "cluster_training",
                "core_training",
            ],
            deleted_at__isnull=True,
        )
    )
    total_meetings = sum(
        1 for a in cluster_activities if a.activity_type == "cluster_meeting"
    )
    total_trainings = sum(
        1
        for a in cluster_activities
        if a.activity_type in ["training", "cluster_training", "core_training"]
    )

    out = []
    for s in schools:
        # Canonical decision rule: confirmed SSA only (see
        # apps.ssa.services.latest_applicable_record) — cluster intelligence
        # previously ranked weakest areas from unverified uploads.
        latest_ssa = (
            s.ssa_records.filter(
                deleted_at__isnull=True, verification_status="confirmed"
            )
            .order_by("-date_of_ssa", "-created_at")
            .first()
        )
        avg_score = None
        weakest_label = "None"
        struggling = []
        rec_action = "No recommended action (no SSA)"

        if latest_ssa:
            avg_score = latest_ssa.average_score
            scores = sorted(
                list(latest_ssa.scores.all()),
                key=lambda x: (x.score, x.intervention),
            )
            if scores:
                weakest_label = scores[0].get_intervention_display()
                weakest_key = scores[0].intervention
                for idx, x in enumerate(scores):
                    if idx < 3 or x.score < 5.5:
                        struggling.append(
                            f"{x.get_intervention_display()}: {x.score:.1f}"
                        )
                if weakest_key == "leadership":
                    rec_action = "Schedule leadership-focused cluster training."
                else:
                    rec_action = f"Schedule {weakest_label}-focused school visit."

        # Fetch last completed visit
        last_visit = (
            s.activities.filter(
                activity_type="school_visit",
                status="completed",
                deleted_at__isnull=True,
            )
            .order_by("-planned_date")
            .first()
        )
        last_visit_date = (
            last_visit.planned_date.strftime("%Y-%m-%d")
            if last_visit and last_visit.planned_date
            else "Never"
        )

        # Fetch last completed training
        last_training = (
            s.activities.filter(
                activity_type__in=["training", "school_improvement_training"],
                status="completed",
                deleted_at__isnull=True,
            )
            .order_by("-planned_date")
            .first()
        )
        last_training_date = (
            last_training.planned_date.strftime("%Y-%m-%d")
            if last_training and last_training.planned_date
            else "Never"
        )

        # Assigned staff
        assigned_staff = "Unassigned"
        if s.account_owner_id:
            assigned_staff = s.account_owner_name_raw or s.account_owner_id

        # Calculate school-specific attendance counts
        attended_meetings = sum(
            1
            for a in cluster_activities
            if a.activity_type == "cluster_meeting"
            and s.id in (a.attended_school_ids or [])
        )
        attended_trainings = sum(
            1
            for a in cluster_activities
            if a.activity_type in ["training", "cluster_training", "core_training"]
            and s.id in (a.attended_school_ids or [])
        )

        out.append(
            {
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
                "meetings_attended": attended_meetings,
                "total_meetings": total_meetings,
                "trainings_attended": attended_trainings,
                "total_trainings": total_trainings,
            }
        )
    return out


def cluster_detail(cluster_id: str, principal) -> dict:
    cluster = Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True).first()
    if not cluster:
        raise NotFoundError("Cluster not found.")

    schools = School.objects.filter(cluster_id=cluster.id, deleted_at__isnull=True)
    school_count = schools.count()

    # Calculate average SSA
    latest_ssas = []
    for s in schools:
        latest = (
            s.ssa_records.filter(deleted_at__isnull=True)
            .order_by("-date_of_ssa")
            .first()
        )
        if latest and latest.average_score is not None:
            latest_ssas.append(latest.average_score)
    avg_ssa = round(sum(latest_ssas) / len(latest_ssas), 1) if latest_ssas else None

    # Last meeting
    last_meeting = (
        cluster.activities.filter(
            activity_type="cluster_meeting", status="completed", deleted_at__isnull=True
        )
        .order_by("-planned_date")
        .first()
    )
    last_meeting_str = (
        last_meeting.planned_date.strftime("%Y-%m-%d")
        if last_meeting and last_meeting.planned_date
        else "Never"
    )

    # Last training
    last_training = (
        cluster.activities.filter(
            activity_type__in=["training", "school_improvement_training"],
            status="completed",
            deleted_at__isnull=True,
        )
        .order_by("-planned_date")
        .first()
    )
    last_training_str = (
        last_training.planned_date.strftime("%Y-%m-%d")
        if last_training and last_training.planned_date
        else "Never"
    )

    assigned_staff = "Unassigned"
    if cluster.responsible_staff_id:
        from apps.accounts.models import StaffProfile

        staff = StaffProfile.objects.filter(
            staff_id=cluster.responsible_staff_id
        ).first()
        if staff:
            assigned_staff = staff.user.name if staff.user else staff.staff_id

    return {
        "id": cluster.id,
        "name": cluster.name,
        "status": cluster.status,
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

    schools = School.objects.filter(cluster_id=cluster.id, deleted_at__isnull=True)

    # Collect all scores for latest SSAs of the schools
    from apps.core.enums import SsaIntervention

    intervention_scores = {key.value: [] for key in SsaIntervention}

    for s in schools:
        latest = (
            s.ssa_records.filter(deleted_at__isnull=True)
            .order_by("-date_of_ssa")
            .first()
        )
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

        results.append(
            {
                "intervention": key.value,
                "label": label,
                "avg": avg,
                "schoolsBelowThreshold": below_count,
                "recommendedAction": rec,
            }
        )

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
    schools = School.objects.filter(cluster_id=cluster.id, deleted_at__isnull=True)
    from apps.core.enums import SsaIntervention

    intervention_scores = {key.value: [] for key in SsaIntervention}
    for s in schools:
        latest = (
            s.ssa_records.filter(deleted_at__isnull=True)
            .order_by("-date_of_ssa")
            .first()
        )
        if latest:
            for score in latest.scores.all():
                if score.score is not None:
                    intervention_scores[score.intervention].append(score.score)
    results = []
    for key in SsaIntervention:
        scores = intervention_scores[key.value]
        avg = round(sum(scores) / len(scores), 1) if scores else 0.0
        below_count = sum(1 for x in scores if x < 5.5)
        results.append(
            {
                "intervention": key.value,
                "label": key.label,
                "avg": avg,
                "schoolsBelowThreshold": below_count,
            }
        )
    return results


def cluster_activity_impact(cluster_id: str, principal) -> list[dict]:
    cluster = Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True).first()
    if not cluster:
        raise NotFoundError("Cluster not found.")

    activities = cluster.activities.filter(
        status="completed", deleted_at__isnull=True
    ).order_by("-planned_date")

    from apps.activities.services import calculate_activity_impact

    out = []
    for a in activities:
        impact = calculate_activity_impact(a)
        out.append(
            {
                "id": a.id,
                "activityType": a.activity_type,
                "plannedDate": a.planned_date.isoformat() if a.planned_date else None,
                "focusIntervention": a.focus_intervention,
                "activityPurposeText": a.activity_purpose_text,
                "expectedOutcome": a.expected_outcome,
                "impact": impact,
            }
        )
    return out


def cluster_intelligence(cluster_id: str, principal) -> dict:
    """Per-cluster intelligence surface."""
    cluster = Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True).first()
    if not cluster:
        raise NotFoundError("Cluster not found.")
    schools = School.objects.filter(cluster_id=cluster.id, deleted_at__isnull=True)
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

    # Resolve user scope to filter clusters
    scope_q, scope = _scope_filter(principal)

    clusters = (
        Cluster.objects.filter(scope_q, deleted_at__isnull=True, status="active")
        .select_related("district", "sub_county")
        .prefetch_related("covered_sub_counties__sub_county")
    )

    out = []
    for c in clusters:
        schools = School.objects.filter(cluster_id=c.id, deleted_at__isnull=True)
        total_schools = schools.count()
        ssa_done = schools.filter(current_fy_ssa_status="done").count()
        ssa_missing = total_schools - ssa_done
        ssa_coverage_pct = (
            round((ssa_done / total_schools) * 100, 1) if total_schools > 0 else 0.0
        )

        ready_for_planning = schools.filter(
            planning_readiness="ready_for_support_planning"
        ).count()
        needing_baseline = schools.filter(
            planning_readiness="ready_for_baseline_ssa"
        ).count()
        needing_cleanup = schools.exclude(data_quality_status="Clean").count()

        # Activities for this cluster
        acts = Activity.objects.filter(cluster=c, deleted_at__isnull=True)

        meetings_completed = acts.filter(
            activity_type__in=["cluster_meeting"],
            status__in=["ia_verified", "closed", "accountant_confirmed"],
        ).count()

        meetings_scheduled = acts.filter(
            activity_type__in=["cluster_meeting"],
            status__in=[
                "scheduled",
                "partner_scheduled",
                "assigned_to_partner",
                "evidence_uploaded",
                "in_progress",
                "awaiting_ia_verification",
            ],
        ).count()

        trainings_completed = acts.filter(
            activity_type__in=["cluster_training", "school_improvement_training"],
            status__in=["ia_verified", "closed", "accountant_confirmed"],
        ).count()

        # Last completed meeting date
        last_meet = (
            acts.filter(
                activity_type__in=["cluster_meeting"],
                status__in=["ia_verified", "closed", "accountant_confirmed"],
            )
            .order_by("-scheduled_date")
            .first()
        )
        last_meeting_date = (
            last_meet.scheduled_date.isoformat()
            if last_meet and last_meet.scheduled_date
            else None
        )

        # Next scheduled meeting date
        next_meet = (
            acts.filter(
                activity_type__in=["cluster_meeting"],
                status__in=[
                    "scheduled",
                    "partner_scheduled",
                    "assigned_to_partner",
                    "evidence_uploaded",
                    "in_progress",
                    "awaiting_ia_verification",
                ],
            )
            .order_by("scheduled_date")
            .first()
        )
        next_scheduled_meeting_date = (
            next_meet.scheduled_date.isoformat()
            if next_meet and next_meet.scheduled_date
            else None
        )

        met_this_quarter = meetings_completed > 0 or meetings_scheduled > 0

        # Schools not visited / trained / neither
        visited_school_ids = set(
            Activity.objects.filter(
                school__in=schools,
                activity_type="school_visit",
                status__in=["ia_verified", "closed", "accountant_confirmed"],
                deleted_at__isnull=True,
            ).values_list("school_id", flat=True)
        )
        schools_not_visited = max(0, total_schools - len(visited_school_ids))

        trained_school_ids = set(
            Activity.objects.filter(
                school__in=schools,
                activity_type__in=[
                    "school_training",
                    "core_training",
                    "project_activity",
                ],
                status__in=["ia_verified", "closed", "accountant_confirmed"],
                deleted_at__isnull=True,
            ).values_list("school_id", flat=True)
        )
        schools_not_trained = max(0, total_schools - len(trained_school_ids))

        neither_count = max(
            0, total_schools - len(visited_school_ids.union(trained_school_ids))
        )

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
            recommendation_reason = (
                f"{schools_not_visited} schools haven't been visited."
            )
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
                "subCounty": (c.sub_county.name if c.sub_county else "")
                or c.sub_county_name
                or "",
                "schoolsCount": total_schools,
                "schoolsWithSsa": ssa_done,
                "schoolsWithoutSsa": ssa_missing,
                "ssaCoveragePct": ssa_coverage_pct,
                "readySchoolsCount": ready_for_planning,
                "needingBaselineCount": needing_baseline,
                "needingCleanupCount": needing_cleanup,
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


class ClusterDashboardService:
    @staticmethod
    def get_dashboard_data(request, user) -> dict:
        from apps.activities.models import Activity

        scope = resolve_user_scope(user)

        # 1. Base scoped query
        base_qs = Cluster.objects.filter(deleted_at__isnull=True, status="active")
        if not scope.country_scope and scope.district_ids:
            base_qs = base_qs.filter(district_id__in=scope.district_ids)

        # 2. Filters from request
        q = request.GET.get("q", "").strip()
        fy = request.GET.get("fy", "2026").strip()
        district_id = request.GET.get("district", "").strip()
        sub_county_id = request.GET.get("sub_county", "").strip()
        staff_id = request.GET.get("staff", "").strip()
        ssa_status = request.GET.get("ssa_status", "").strip()
        cluster_risk = request.GET.get("cluster_risk", "").strip()
        activity_status = request.GET.get("activity_status", "").strip()

        # Apply filters to queryset
        filtered_qs = base_qs
        if q:
            filtered_qs = filtered_qs.filter(
                Q(name__icontains=q) | Q(district__name__icontains=q)
            )
        if district_id:
            filtered_qs = filtered_qs.filter(district_id=district_id)
        if sub_county_id:
            filtered_qs = filtered_qs.filter(sub_county_id=sub_county_id)
        if staff_id:
            staff_cluster_ids = (
                School.objects.filter(
                    account_owner_id=staff_id, deleted_at__isnull=True
                )
                .exclude(cluster_id__isnull=True)
                .exclude(cluster_id="")
                .values("cluster_id")
            )
            filtered_qs = filtered_qs.filter(
                Q(responsible_staff_id=staff_id) | Q(id__in=staff_cluster_ids)
            ).distinct()

        # Get all planning info
        planning_list = cluster_planning(user)
        planning_map = {p["id"]: p for p in planning_list}

        # Build Card viewmodels for filtered list
        cards = []
        for c in filtered_qs.select_related("district", "sub_county"):
            schools = School.objects.filter(cluster_id=c.id, deleted_at__isnull=True)
            schools_count = schools.count()

            assigned_staff_ids = (
                schools.exclude(account_owner_id__isnull=True)
                .exclude(account_owner_id="")
                .values_list("account_owner_id", flat=True)
                .distinct()
            )
            staff_count = len(assigned_staff_ids)

            latest_ssas = []
            for s in schools:
                latest = (
                    s.ssa_records.filter(deleted_at__isnull=True)
                    .order_by("-date_of_ssa")
                    .first()
                )
                if latest and latest.average_score is not None:
                    latest_ssas.append(latest.average_score)
            avg_ssa = (
                round(sum(latest_ssas) / len(latest_ssas), 1) if latest_ssas else None
            )

            acts = Activity.objects.filter(cluster=c, deleted_at__isnull=True)

            last_meeting = (
                acts.filter(activity_type="cluster_meeting", status="completed")
                .order_by("-planned_date")
                .first()
            )
            last_meeting_date = (
                last_meeting.planned_date.strftime("%d %b %Y")
                if last_meeting and last_meeting.planned_date
                else "Never"
            )

            last_training = (
                acts.filter(
                    activity_type__in=[
                        "training",
                        "school_improvement_training",
                        "cluster_training",
                    ],
                    status="completed",
                )
                .order_by("-planned_date")
                .first()
            )
            last_training_date = (
                last_training.planned_date.strftime("%d %b %Y")
                if last_training and last_training.planned_date
                else "Never"
            )

            meeting_count_fy = acts.filter(
                activity_type="cluster_meeting", status="completed", fy=fy
            ).count()

            weakest = cluster_weakest_interventions(c.id, user)
            planning_info = planning_map.get(c.id, {})

            from apps.frontend.views.cluster_views import get_cluster_risk

            risk = get_cluster_risk(c, planning_info, avg_ssa)

            if risk == "critical":
                next_action = "Schedule training"
            elif risk == "needs_attention":
                next_action = "Monitor progress"
            else:
                next_action = "Continue support"

            # Build sub-county display: show all covered sub-counties, or
            # "District-level cluster" if none selected.
            covered = list(
                c.covered_sub_counties.values_list("sub_county__name", flat=True)
            )
            if covered:
                sub_county_display = ", ".join(covered)
            elif c.sub_county:
                sub_county_display = c.sub_county.name
            elif c.sub_county_name:
                sub_county_display = c.sub_county_name
            else:
                sub_county_display = "District-level cluster"

            cards.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "district": c.district.name if c.district else "Unknown",
                    "sub_county": sub_county_display,
                    "schools_count": schools_count,
                    "staff_count": staff_count,
                    "avg_ssa": avg_ssa,
                    "last_meeting_date": last_meeting_date,
                    "last_training_date": last_training_date,
                    "weakest_interventions": weakest,
                    "all_intervention_scores": cluster_intervention_summary(c.id, user),
                    "risk": risk,
                    "next_action": next_action,
                    "planning": planning_info,
                    "meeting_count_fy": meeting_count_fy,
                    "cluster_leader_name": c.cluster_leader_name or "Not Assigned",
                    "cluster_leader_phone": c.cluster_leader_phone or "Not Entered",
                }
            )

        # Apply calculated filters in Python
        if ssa_status:
            if ssa_status == "done":
                cards = [
                    c
                    for c in cards
                    if c["planning"].get("schoolsWithSsa", 0) == c["schools_count"]
                ]
            elif ssa_status == "not_done":
                cards = [
                    c
                    for c in cards
                    if c["planning"].get("schoolsWithSsa", 0) < c["schools_count"]
                ]

        if cluster_risk:
            cards = [c for c in cards if c["risk"] == cluster_risk]

        if activity_status:
            if activity_status == "pending":
                cards = [
                    c
                    for c in cards
                    if c["planning"].get("meetingsScheduledThisFy", 0) > 0
                ]
            elif activity_status == "completed":
                cards = [c for c in cards if c["planning"].get("meetingsThisFy", 0) > 0]

        # Calculate KPIs
        total_clusters = len(cards)
        schools_in_clusters = sum(c["schools_count"] for c in cards)
        without_ssa = sum(
            1
            for c in cards
            if c["planning"].get("schoolsWithSsa", 0) < c["schools_count"]
        )
        needing_training = sum(
            1
            for c in cards
            if c["risk"] == "critical"
            or (c["avg_ssa"] is not None and c["avg_ssa"] < 5.5)
        )
        not_met_this_quarter = sum(
            1 for c in cards if not c["planning"].get("metThisQuarter", True)
        )

        ssas = [c["avg_ssa"] for c in cards if c["avg_ssa"] is not None]
        avg_cluster_ssa = round(sum(ssas) / len(ssas), 1) if ssas else 0.0

        from apps.core.enums import SsaIntervention

        interv_totals = {key.value: [] for key in SsaIntervention}
        for c in cards:
            for item in c["weakest_interventions"]:
                if item["avg"] is not None:
                    interv_totals[item["intervention"]].append(item["avg"])

        weakest_name = "None"
        weakest_avg = 0.0
        lowest_val = 99.0
        for key in SsaIntervention:
            vals = interv_totals[key.value]
            if vals:
                avg = sum(vals) / len(vals)
                if avg < lowest_val:
                    lowest_val = avg
                    weakest_name = key.label
                    weakest_avg = round(avg, 1)

        pending_activities = sum(
            c["planning"].get("meetingsScheduledThisFy", 0) for c in cards
        )

        kpis = {
            "total_clusters": total_clusters,
            "schools_in_clusters": schools_in_clusters,
            "without_ssa": without_ssa,
            "needing_training": needing_training,
            "not_met_this_quarter": not_met_this_quarter,
            "avg_ssa": avg_cluster_ssa,
            "weakest_intervention": weakest_name,
            "weakest_avg": weakest_avg,
            "pending_activities": pending_activities,
        }

        kpi_strip_items = [
            {
                "label": "Total Clusters",
                "value": str(total_clusters),
                "raw_value": total_clusters,
                "helper": "Active",
                "icon": "school",
                "variant": "primary",
            },
            {
                "label": "Schools in Clusters",
                "value": f"{schools_in_clusters:,}",
                "raw_value": schools_in_clusters,
                "helper": f"Across {total_clusters} clusters",
                "icon": "school",
                "variant": "success",
            },
            {
                "label": "Without Current SSA",
                "value": str(without_ssa),
                "raw_value": without_ssa,
                "helper": f"{round(without_ssa * 100 / total_clusters) if total_clusters > 0 else 0}% of total",
                "icon": "warning",
                "variant": "danger",
            },
            {
                "label": "Needing Group Training",
                "value": str(needing_training),
                "raw_value": needing_training,
                "helper": f"{round(needing_training * 100 / total_clusters) if total_clusters > 0 else 0}% of total",
                "icon": "target",
                "variant": "warning",
            },
            {
                "label": "Not Met This Quarter",
                "value": str(not_met_this_quarter),
                "raw_value": not_met_this_quarter,
                "helper": f"{round(not_met_this_quarter * 100 / total_clusters) if total_clusters > 0 else 0}% of total",
                "icon": "calendar",
                "variant": "warning",
            },
            {
                "label": "Average Cluster SSA",
                "value": f"{avg_cluster_ssa:.1f}",
                "raw_value": avg_cluster_ssa,
                "helper": "Out of 10.0",
                "icon": "chart",
                "variant": "blue",
            },
            {
                "label": "Weakest Intervention",
                "value": weakest_name,
                "raw_value": 0,
                "helper": f"Avg {weakest_avg:.1f}",
                "icon": "warning",
                "variant": "danger",
            },
            {
                "label": "Pending Activities",
                "value": str(pending_activities),
                "raw_value": pending_activities,
                "helper": "This quarter",
                "icon": "check",
                "variant": "info",
            },
        ]

        critical_count = sum(1 for c in cards if c["risk"] == "critical")
        attention_count = sum(1 for c in cards if c["risk"] == "needs_attention")
        healthy_count = sum(1 for c in cards if c["risk"] == "healthy")

        risk_counts = {
            "critical": critical_count,
            "needs_attention": attention_count,
            "healthy": healthy_count,
        }

        return {
            "cards": cards,
            "kpis": kpis,
            "kpi_strip_items": kpi_strip_items,
            "risk_counts": risk_counts,
        }


class ClusterPlanningService:
    @staticmethod
    def get_cluster_schools(cluster_id: str, user) -> list[dict]:
        return cluster_schools(cluster_id, user)


class ClusterActionPlannerService:
    @staticmethod
    def schedule_activity(data: dict, user) -> dict:
        from apps.activities.services import create as create_activity

        # Ensure we have active cost catalogue
        from apps.budget.costing_service import active_catalogue

        catalogue = active_catalogue(data.get("fy", "2026"))
        if not catalogue:
            raise BadRequest(
                "Active Cost Catalogue required before cluster activity can be scheduled."
            )

        act_dict = create_activity(data, user)

        # If assigned partner, make sure PartnerAssignment is created
        partner_id = data.get("assignedPartnerId")
        if partner_id:
            from apps.partners.models import PartnerAssignment

            PartnerAssignment.objects.create(
                cluster_id=data.get("clusterId"),
                partner_id=partner_id,
                assigning_staff_id=user.staff_profile_id or user.id,
                purpose=data.get("activityPurposeText"),
                focus_intervention=data.get("focusIntervention"),
                expected_activity_type=data.get("activityType"),
                status="partner_pending_schedule",
            )

        return act_dict


class ClusterImpactService:
    @staticmethod
    def get_impact_data(cluster_id: str, focus_intervention: str, user) -> dict | None:
        from apps.frontend.views.cluster_views import get_cluster_impact_data

        return get_cluster_impact_data(cluster_id, focus_intervention, user)


class ClusterRecommendationService:
    @staticmethod
    def get_recommendation(cluster_id: str, user) -> dict | None:
        planning_list = cluster_planning(user)
        planning = next((p for p in planning_list if p["id"] == cluster_id), None)
        if not planning:
            return None
        return {
            "headline": planning.get(
                "recommendationHeadline", "Continue standard support"
            ),
            "reason": planning.get(
                "recommendationReason",
                "Cluster has solid SSA scores and frequent meetings.",
            ),
            "activity_label": planning.get(
                "recommendationActivityLabel", "Schedule Visit"
            ),
            "focus_intervention": planning.get(
                "recommendationFocusIntervention", "leadership"
            ),
        }


class ClusterCostPreviewService:
    @staticmethod
    def preview_cost(
        activity_type: str, participants: int, cluster_id: str, fy: str = "2026"
    ) -> dict:
        from apps.frontend.views.cluster_views import _get_cost_preview_data

        return _get_cost_preview_data(activity_type, participants, cluster_id)


class ClusterMyPlanSyncService:
    """Ensures a cluster activity is attributable to a user's My Plan.

    An Activity row appears on a user's My Plan when its `responsible_staff_id`
    (or, for partner delivery, `assigned_partner_id`) falls within the user's
    resolved scope (see `apps.core.scoping.resolve_user_scope`). Cluster
    activities created via `ClusterActionPlannerService.schedule_activity` are
    already attributed at creation time, so in the normal flow no sync is
    needed. This service exists for flows that build or adopt an Activity
    outside that path and need to (re)attribute it to a specific owner so it
    surfaces on their My Plan.

    The operation is idempotent: calling it on an already-attributed activity
    is a no-op. It never creates a duplicate Activity — only updates ownership
    fields on the supplied instance.
    """

    @staticmethod
    def sync_to_my_plan(activity, user) -> bool:
        """Attribute `activity` to `user`'s My Plan.

        Returns True if any change was applied, False if the activity was
        already attributable to the user. The activity is saved only when a
        change is made.

        For staff delivery, sets `responsible_staff_id` to the user's staff
        profile id (falling back to the user id). For partner delivery, the
        activity is attributed via `assigned_partner_id` and is left untouched
        unless the user has no partner linkage, in which case we still set the
        responsible staff so the activity is traceable.
        """
        if activity is None or user is None:
            return False

        owner_id = None
        if getattr(user, "staff_profile_id", None):
            owner_id = user.staff_profile_id
        elif getattr(user, "staff_profile", None) and user.staff_profile:
            owner_id = user.staff_profile.staff_id or user.id
        else:
            owner_id = user.id

        changed = False
        # Partner-delivered activities are scoped by assigned_partner_id; only
        # touch staff ownership if it is genuinely missing.
        if getattr(activity, "delivery_type", None) == "partner":
            if not activity.assigned_partner_id and not activity.responsible_staff_id:
                activity.responsible_staff_id = owner_id
                changed = True
        else:
            if activity.responsible_staff_id != owner_id:
                activity.responsible_staff_id = owner_id
                changed = True

        if changed:
            activity.save(update_fields=["responsible_staff_id"])
        return changed


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
    "ClusterDashboardService",
    "ClusterPlanningService",
    "ClusterActionPlannerService",
    "ClusterImpactService",
    "ClusterRecommendationService",
    "ClusterCostPreviewService",
    "ClusterMyPlanSyncService",
]
