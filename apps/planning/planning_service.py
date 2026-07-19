from django.db.models import Count, Q
from apps.core.fy import get_operational_fy
from apps.core.enums import ActivityStatus, SsaIntervention
from apps.schools.models import School
from apps.clusters.models import Cluster
from apps.activities.models import Activity
from apps.partners.models import PartnerAssignment
from apps.accounts.models import StaffProfile
from apps.ssa.models import SsaRecord
from apps.ssa.presentation import build_ssa_score_summary
from apps.core_schools.models import CoreActivitySlot
from apps.core_schools.services import CORE_SLOT_DONE_STATUSES


class PlanningReadinessService:
    @staticmethod
    def get_school_readiness(
        school, has_catalogue, has_scheduled, partner_assignment, weakest_area
    ):
        # 1. Cluster check
        if not school.cluster_id:
            return {
                "planningReadiness": "Cluster Required",
                "recommendedAction": "Add to Cluster",
                "reason": "Unclustered schools block activity scheduling.",
                "availableActions": ["Add to Cluster"],
                "blockedActions": [
                    "Schedule visit",
                    "Schedule training",
                ],
            }

        # 2. Blockers (Data Cleanup Required)
        blocked_fields = []
        if not school.district_id:
            blocked_fields.append("District")
        if not school.sub_county_id:
            blocked_fields.append("Sub-county")
        if not school.account_owner_id:
            blocked_fields.append("Responsible staff")
        if not school.school_id:
            blocked_fields.append("School ID")

        if blocked_fields:
            return {
                "planningReadiness": "Data Cleanup Required",
                "recommendedAction": f"Complete operational details: {', '.join(blocked_fields)}.",
                "reason": f"Operational details missing: {', '.join(blocked_fields)}.",
                "availableActions": ["Fix Data"],
                "blockedActions": [
                    "Schedule visit",
                    "Schedule training",
                ],
            }

        # 3. Cost Catalogue Required
        if not has_catalogue:
            return {
                "planningReadiness": "Cost Catalogue Required",
                "recommendedAction": "Ask CD/Admin to activate Cost Catalogue",
                "reason": "Active CD Cost Catalogue is missing.",
                "availableActions": [],
                "blockedActions": [
                    "Schedule visit",
                    "Schedule training",
                ],
            }

        # 4. Already Scheduled / In My Plan
        if has_scheduled:
            return {
                "planningReadiness": "In My Plan",
                "recommendedAction": "Open My Plan",
                "reason": "This school already has an activity scheduled for this slot.",
                "availableActions": ["Open My Plan"],
                "blockedActions": [
                    "Schedule visit",
                    "Schedule training",
                ],
            }

        # 5. Assigned to Partner / Partner Pending Schedule
        if partner_assignment:
            status = partner_assignment.status
            if status == "partner_scheduled":
                return {
                    "planningReadiness": "In My Plan",
                    "recommendedAction": "Open My Plan",
                    "reason": "Activity is scheduled by partner.",
                    "availableActions": ["Open My Plan"],
                    "blockedActions": [
                        "Schedule visit",
                        "Schedule training",
                    ],
                }
            elif status in (
                "assigned",
                "pending_scheduling",
                "partner_pending_schedule",
                "assigned_to_partner_pending_scheduling",
            ):
                return {
                    "planningReadiness": "Partner Pending Schedule",
                    "recommendedAction": "Monitor Partner Scheduling",
                    "reason": "Partner has received assignment but not scheduled yet.",
                    "availableActions": ["Monitor Partner Scheduling"],
                    "blockedActions": [
                        "Schedule visit",
                        "Schedule training",
                    ],
                }

        from apps.planning.recommendation_services import PlanningRecommendationService

        return PlanningRecommendationService.get_recommendation(
            school, has_catalogue, has_scheduled, partner_assignment
        )


class ClusterRecommendationService:
    @staticmethod
    def get_cluster_recommendation(
        cluster, avg_ssa, weakest_interventions, school_count, assessed_count
    ):
        coverage_pct = (assessed_count / school_count * 100) if school_count > 0 else 0
        if coverage_pct < 50:
            return {
                "recommendedAction": "Schedule Cluster SSA Collection / Data Review Meeting",
                "reason": "This cluster has low SSA coverage. Collecting baseline data should happen before intervention impact can be measured.",
                "availableActions": [
                    "Schedule Cluster Meeting + SSA Review",
                    "Schedule Cluster Training + SSA Collection",
                    "Assign Partner SSA Collection",
                ],
            }

        weakest = (
            weakest_interventions[0] if weakest_interventions else "Teaching & Learning"
        )
        return {
            "recommendedAction": f"Schedule {weakest} Cluster Training",
            "reason": f"{weakest} is the lowest average intervention score across schools in this cluster.",
            "availableActions": [
                "Schedule Cluster Training",
                "Schedule Cluster Meeting",
                "Assign Partner",
                "View Cluster SSA Profile",
            ],
        }


class PlanningDashboardService:
    @staticmethod
    def get_dashboard_data(principal, filters: dict):
        fy = filters.get("fy") or get_operational_fy()
        district_id = filters.get("district")
        sub_county_id = filters.get("sub_county")
        staff_id = filters.get("staff")
        school_type = filters.get("school_type")
        readiness = filters.get("planning_readiness")
        ssa_status = filters.get("ssa_status")
        cluster_status = filters.get("cluster_status")
        partner_id = filters.get("partner")
        search_q = filters.get("q")
        active_tab = filters.get(
            "tab", "client"
        )  # client, core, clusters, partner, scheduled

        # 1. Base Queryset for schools (scope-scoped)
        from apps.analytics.services import _scoped_schools

        schools_qs, scope = _scoped_schools(principal)

        # Apply filters
        if district_id and district_id != "All":
            schools_qs = schools_qs.filter(district_id=district_id)
        if sub_county_id and sub_county_id != "All":
            schools_qs = schools_qs.filter(sub_county_id=sub_county_id)
        if staff_id and staff_id != "All":
            schools_qs = schools_qs.filter(account_owner_id=staff_id)
        if school_type and school_type != "All":
            schools_qs = schools_qs.filter(school_type=school_type)
        if readiness and readiness != "All":
            schools_qs = schools_qs.filter(planning_readiness=readiness)
        if ssa_status and ssa_status != "All":
            schools_qs = schools_qs.filter(current_fy_ssa_status=ssa_status)
        if cluster_status and cluster_status != "All":
            schools_qs = schools_qs.filter(cluster_status=cluster_status)
        if partner_id and partner_id != "All":
            schools_qs = schools_qs.filter(
                activities__assigned_partner_id=partner_id,
                activities__deleted_at__isnull=True,
            ).distinct()
        if search_q:
            schools_qs = schools_qs.filter(
                Q(name__icontains=search_q)
                | Q(school_id__icontains=search_q)
                | Q(district__name__icontains=search_q)
            )

        # Get active/scheduled school IDs in this FY
        active_activities_school_ids = (
            Activity.objects.filter(deleted_at__isnull=True, fy=fy)
            .exclude(status__in=["cancelled", "deferred", "not_planned", "planned"])
            .values_list("school_id", flat=True)
        )

        active_partner_school_ids = PartnerAssignment.objects.filter(
            status__in=[
                "assigned",
                "pending_scheduling",
                "partner_pending_schedule",
                "assigned_to_partner_pending_scheduling",
                "partner_scheduled",
            ]
        ).values_list("school_id", flat=True)

        exclude_school_ids = set(active_activities_school_ids).union(
            set(active_partner_school_ids)
        )

        # Tab-specific filters for the table view
        if active_tab == "client":
            table_schools_qs = schools_qs.filter(school_type="client").exclude(
                id__in=exclude_school_ids
            )
        elif active_tab == "core":
            table_schools_qs = schools_qs.filter(
                school_type__in=["core", "champion"]
            ).exclude(id__in=exclude_school_ids)
        elif active_tab == "partner":
            partner_school_ids = PartnerAssignment.objects.filter(
                status__in=[
                    "assigned",
                    "pending_scheduling",
                    "partner_pending_schedule",
                    "assigned_to_partner_pending_scheduling",
                    "partner_scheduled",
                ]
            ).values_list("school_id", flat=True)
            table_schools_qs = schools_qs.filter(id__in=partner_school_ids)
        elif active_tab == "scheduled":
            scheduled_school_ids = Activity.objects.filter(
                deleted_at__isnull=True,
                status__in=[
                    "planned",
                    "scheduled",
                    "partner_scheduled",
                    "in_progress",
                    "completed",
                    "ia_verified",
                ],
                fy=fy,
            ).values_list("school_id", flat=True)
            table_schools_qs = schools_qs.filter(id__in=scheduled_school_ids)
        else:
            table_schools_qs = schools_qs

        # 2. Pagination and query based on active tab
        try:
            page = int(filters.get("page", 1))
        except ValueError:
            page = 1
        try:
            per_page = int(filters.get("per_page", 10))
        except ValueError:
            per_page = 10

        paginated_clusters = []
        schools_data = []

        from apps.budget.costing_service import active_catalogue

        has_catalogue = active_catalogue() is not None

        if active_tab == "clusters":
            scoped_cluster_ids = list(
                schools_qs.exclude(Q(cluster_id__isnull=True) | Q(cluster_id=""))
                .values_list("cluster_id", flat=True)
                .distinct()
            )

            scheduled_cluster_ids = (
                Activity.objects.filter(
                    deleted_at__isnull=True,
                    fy=fy,
                    activity_type__in=["cluster_meeting", "cluster_training"],
                    cluster_id__isnull=False,
                )
                .exclude(status="cancelled")
                .values_list("cluster_id", flat=True)
                .distinct()
            )

            ready_clusters_qs = Cluster.objects.filter(
                id__in=scoped_cluster_ids, deleted_at__isnull=True
            ).exclude(id__in=scheduled_cluster_ids)

            if search_q:
                ready_clusters_qs = ready_clusters_qs.filter(name__icontains=search_q)
            if district_id and district_id != "All":
                ready_clusters_qs = ready_clusters_qs.filter(district_id=district_id)

            total_schools_count = ready_clusters_qs.count()
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            clusters_slice = list(
                ready_clusters_qs.select_related("district").order_by("name")[
                    start_idx:end_idx
                ]
            )

            for c in clusters_slice:
                member_schools = School.objects.filter(
                    cluster_id=c.id, deleted_at__isnull=True
                )
                member_records = (
                    SsaRecord.objects.filter(
                        school__in=member_schools,
                        verification_status="confirmed",
                        deleted_at__isnull=True,
                    )
                    .prefetch_related("scores")
                    .order_by("school_id", "-date_of_ssa")
                )

                latest_recs = {}
                for r in member_records:
                    if r.school_id not in latest_recs:
                        latest_recs[r.school_id] = r

                tot_score = sum(
                    r.average_score for r in latest_recs.values() if r.average_score
                )
                rec_cnt = sum(1 for r in latest_recs.values() if r.average_score)
                avg_ssa = round(tot_score / rec_cnt * 10) if rec_cnt > 0 else 0

                # Find weakest interventions
                interv_sums = {}
                interv_counts = {}
                for r in latest_recs.values():
                    for score in r.scores.all():
                        interv_sums[score.intervention] = (
                            interv_sums.get(score.intervention, 0) + score.score
                        )
                        interv_counts[score.intervention] = (
                            interv_counts.get(score.intervention, 0) + 1
                        )

                interv_averages = []
                for code, label in SsaIntervention.choices:
                    if code in interv_sums:
                        avg_val = interv_sums[code] / interv_counts[code]
                        interv_averages.append((code, label, avg_val))

                interv_averages.sort(key=lambda x: x[2])
                weakest_intervs = [item[1] for item in interv_averages[:4]]

                rec_details = ClusterRecommendationService.get_cluster_recommendation(
                    cluster=c,
                    avg_ssa=avg_ssa,
                    weakest_interventions=weakest_intervs,
                    school_count=member_schools.count(),
                    assessed_count=rec_cnt,
                )

                paginated_clusters.append(
                    {
                        "id": c.id,
                        "name": c.name,
                        "district": c.district.name if c.district else "Unknown",
                        "avg_ssa": avg_ssa,
                        "weakest_interventions": weakest_intervs,
                        "school_count": member_schools.count(),
                        "readiness": "Ready"
                        if member_schools.count() > 0
                        else "No Schools",
                        "recommendedAction": rec_details["recommendedAction"],
                        "reason": rec_details["reason"],
                        "availableActions": rec_details["availableActions"],
                    }
                )
        else:
            total_schools_count = table_schools_qs.count()
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            paginated_schools = list(
                table_schools_qs.select_related("district", "sub_county").order_by(
                    "name"
                )[start_idx:end_idx]
            )

            # Retrieve latest confirmed SSA records
            school_ids = [s.id for s in paginated_schools]
            ssa_records = (
                SsaRecord.objects.filter(
                    school_id__in=school_ids,
                    fy=fy,
                    verification_status="confirmed",
                    deleted_at__isnull=True,
                )
                .prefetch_related("scores")
                .order_by("school_id", "-date_of_ssa")
            )

            latest_school_ssa = {}
            for r in ssa_records:
                if r.school_id not in latest_school_ssa:
                    latest_school_ssa[r.school_id] = r

            # Resolve weakest interventions
            weakest_map = {}
            ssa_summary_map = {}
            for sch_id, record in latest_school_ssa.items():
                scores = [
                    {"intervention": score.intervention, "score": score.score}
                    for score in record.scores.all()
                ]
                ssa_summary_map[sch_id] = build_ssa_score_summary(scores)
                scores = sorted(
                    scores,
                    key=lambda x: x["score"],
                )
                weakest_list = []
                for s in scores[:3]:
                    code = s["intervention"]
                    label = dict(SsaIntervention.choices).get(code, code)
                    weakest_list.append(
                        {"code": code, "label": label, "score": s["score"]}
                    )
                weakest_map[sch_id] = weakest_list

            # Resolve partner assignments
            assignments = PartnerAssignment.objects.filter(
                school_id__in=school_ids
            ).select_related("partner")
            assignment_map = {a.school_id: a for a in assignments}

            # Schools store an owner as either a StaffProfile ID or a User ID,
            # depending on the source that assigned it. Build a display-name
            # map for both ID spaces once for this page instead of resolving
            # staff inside the school loop.
            owner_ids = {
                school.account_owner_id
                for school in paginated_schools
                if school.account_owner_id
            }
            staff_names_by_owner_id = {}
            if owner_ids:
                for staff in (
                    StaffProfile.objects.filter(deleted_at__isnull=True)
                    .filter(Q(id__in=owner_ids) | Q(user_id__in=owner_ids))
                    .select_related("user")
                ):
                    if staff.user_id and staff.user.name:
                        staff_names_by_owner_id[staff.id] = staff.user.name
                        staff_names_by_owner_id[staff.user_id] = staff.user.name

            # Resolve scheduled activities
            # A school can have historical activities from the same financial
            # year.  Only an active activity can be opened from Planning for a
            # reschedule; choosing an unordered historical record made the
            # action appear to fail for some schools.
            scheduled_activities = (
                Activity.objects.filter(
                    school_id__in=school_ids, deleted_at__isnull=True, fy=fy
                )
                .exclude(
                    status__in=[
                        ActivityStatus.COMPLETED,
                        ActivityStatus.CLOSED,
                        ActivityStatus.REJECTED,
                        ActivityStatus.RESCHEDULED,
                        ActivityStatus.CANCELLED,
                        ActivityStatus.DEFERRED,
                    ]
                )
                .order_by("-planned_date", "-created_at")
            )

            scheduled_map = {}
            for act in scheduled_activities:
                s_id = act.school_id
                if s_id not in scheduled_map:
                    scheduled_map[s_id] = []
                scheduled_map[s_id].append(act)

            completed_visits_by_school = dict(
                Activity.objects.filter(
                    school_id__in=school_ids,
                    activity_type__in=[
                        "school_visit",
                        "core_visit",
                        "baseline_ssa_visit",
                    ],
                    status="completed",
                    deleted_at__isnull=True,
                )
                .values("school_id")
                .annotate(count=Count("id"))
                .values_list("school_id", "count")
            )
            completed_trainings_by_school = dict(
                Activity.objects.filter(
                    school_id__in=school_ids,
                    activity_type__in=["training", "core_training"],
                    status="completed",
                    deleted_at__isnull=True,
                )
                .values("school_id")
                .annotate(count=Count("id"))
                .values_list("school_id", "count")
            )

            # Cluster delivery stores attendance as a school-id array, so it
            # needs one bounded query and a small in-memory tally instead of
            # a query for every school row.
            wanted_school_ids = set(school_ids)
            cluster_attendance = Activity.objects.filter(
                activity_type__in=["cluster_training", "cluster_meeting"],
                status="completed",
                deleted_at__isnull=True,
                attended_school_ids__overlap=list(wanted_school_ids),
            ).values_list("attended_school_ids", flat=True)
            for attended_school_ids in cluster_attendance:
                for attended_school_id in attended_school_ids or []:
                    if attended_school_id in wanted_school_ids:
                        completed_trainings_by_school[attended_school_id] = (
                            completed_trainings_by_school.get(attended_school_id, 0) + 1
                        )

            # Serialize Schools
            for s in paginated_schools:
                weak = weakest_map.get(s.id, [])
                ssa_summary = ssa_summary_map.get(s.id, {})
                weakest_area = weak[0]["label"] if len(weak) > 0 else "—"
                weakest_code = weak[0]["code"] if len(weak) > 0 else None

                has_scheduled = s.id in scheduled_map
                partner_assignment = assignment_map.get(s.id)

                readiness_details = PlanningReadinessService.get_school_readiness(
                    school=s,
                    has_catalogue=has_catalogue,
                    has_scheduled=has_scheduled,
                    partner_assignment=partner_assignment,
                    weakest_area=weakest_area,
                )

                schools_data.append(
                    {
                        "id": s.id,
                        "schoolId": s.school_id,
                        "name": s.name,
                        "district": s.district.name if s.district else "—",
                        "subCounty": s.sub_county.name if s.sub_county else "—",
                        "shippingAddress": s.shipping_address or "—",
                        "cluster": s.cluster_id or "—",
                        "schoolType": s.get_school_type_display(),
                        "ssaStatus": s.ssa_readiness_state,
                        "weakestIntervention": weakest_area,
                        "weakestInterventionCode": weakest_code,
                        "weakestInterventions": weak,
                        "hasSsaScores": ssa_summary.get("has_scores", False),
                        "ssaAverage": ssa_summary.get("average_score"),
                        "ssaAverageTone": ssa_summary.get("average_tone", "neutral"),
                        "ssaGroups": ssa_summary.get("groups", []),
                        "planningReadiness": readiness_details["planningReadiness"],
                        "planning_readiness": readiness_details["planningReadiness"],
                        "recommendedAction": readiness_details["recommendedAction"],
                        "recommended_action": readiness_details["recommendedAction"],
                        "reason": readiness_details["reason"],
                        "availableActions": readiness_details["availableActions"],
                        "available_actions": readiness_details["availableActions"],
                        "blockedActions": readiness_details["blockedActions"],
                        "blocked_actions": readiness_details["blockedActions"],
                        "cost_ready": has_catalogue,
                        "my_plan_status": scheduled_map[s.id][0].status
                        if has_scheduled and len(scheduled_map[s.id]) > 0
                        else None,
                        "isScheduled": has_scheduled,
                        "scheduledActivityId": scheduled_map[s.id][0].id
                        if has_scheduled and len(scheduled_map[s.id]) > 0
                        else None,
                        "blockedReason": readiness_details["reason"]
                        if readiness_details["blockedActions"]
                        else None,
                        "ownerId": s.account_owner_id,
                        "ownerName": staff_names_by_owner_id.get(s.account_owner_id)
                        or s.account_owner_name_raw
                        or "Unassigned",
                        "schoolContact": s.primary_contact_name or "—",
                        "phone": s.primary_contact_phone
                        or s.school_phone
                        or "No phone",
                        "enrolment": s.enrollment,
                        "visitCount": completed_visits_by_school.get(s.id, 0),
                        "trainingCount": completed_trainings_by_school.get(s.id, 0),
                        "data_quality_score": s.data_quality_score,
                        "data_quality_status": s.data_quality_status,
                        "currentPartnerType": partner_assignment.partner.name
                        if partner_assignment and partner_assignment.partner
                        else "None",
                    }
                )

        # Resolve cluster name mapping
        cluster_ids = [s["cluster"] for s in schools_data if s["cluster"] != "—"]
        cluster_name_map = {}
        if cluster_ids:
            clusters_objs = Cluster.objects.filter(id__in=cluster_ids)
            cluster_name_map = {c.id: c.name for c in clusters_objs}
        for s in schools_data:
            if s["cluster"] != "—":
                s["clusterName"] = cluster_name_map.get(s["cluster"], s["cluster"])
            else:
                s["clusterName"] = "—"

        # 5. Compute KPI Cards Metrics
        from apps.analytics.services import _scoped_schools

        base_schools_qs, scope = _scoped_schools(principal)

        all_school_ids = list(base_schools_qs.values_list("id", flat=True))
        cost_blocked_count = (
            0
            if has_catalogue
            else base_schools_qs.exclude(
                Q(cluster_id__isnull=True) | Q(cluster_id="")
            ).count()
        )

        cleanup_qs = base_schools_qs.exclude(
            Q(cluster_id__isnull=True) | Q(cluster_id="")
        ).filter(
            Q(district_id__isnull=True)
            | Q(sub_county_id__isnull=True)
            | Q(account_owner_id__isnull=True)
            | Q(school_id__isnull=True)
            | Q(school_id="")
        )
        data_cleanup_count = cleanup_qs.count()
        clean_schools_qs = base_schools_qs.exclude(
            Q(cluster_id__isnull=True) | Q(cluster_id="")
        ).exclude(id__in=cleanup_qs.values_list("id", flat=True))

        scheduled_schools_ids_fy = set(
            Activity.objects.filter(deleted_at__isnull=True, fy=fy)
            .exclude(status="cancelled")
            .values_list("school_id", flat=True)
        )

        partner_pending_ids = set(
            PartnerAssignment.objects.filter(
                status__in=[
                    "assigned",
                    "pending_scheduling",
                    "partner_pending_schedule",
                    "assigned_to_partner_pending_scheduling",
                ]
            ).values_list("school_id", flat=True)
        )

        ready_for_support_count = 0
        baseline_required_count = 0

        schools_with_ssa_ids = set(
            SsaRecord.objects.filter(
                school_id__in=all_school_ids,
                verification_status="confirmed",
                deleted_at__isnull=True,
            ).values_list("school_id", flat=True)
        )

        for s in clean_schools_qs:
            if s.id in scheduled_schools_ids_fy or s.id in partner_pending_ids:
                continue
            if s.id in schools_with_ssa_ids:
                ready_for_support_count += 1
            else:
                baseline_required_count += 1

        partner_pending_schedule_count = PartnerAssignment.objects.filter(
            status__in=[
                "assigned",
                "pending_scheduling",
                "partner_pending_schedule",
                "assigned_to_partner_pending_scheduling",
            ]
        ).count()

        in_my_plan_count = Activity.objects.filter(
            deleted_at__isnull=True,
            status__in=["scheduled", "in_progress", "completed", "ia_verified"],
            fy=fy,
        ).count()

        core_package_gaps_count = (
            base_schools_qs.filter(school_type__in=["core", "champion"])
            .exclude(
                activities__status__in=["completed", "ia_verified"], activities__fy=fy
            )
            .distinct()
            .count()
        )

        scoped_cluster_ids = list(
            base_schools_qs.exclude(Q(cluster_id__isnull=True) | Q(cluster_id=""))
            .values_list("cluster_id", flat=True)
            .distinct()
        )
        planned_cluster_ids = Activity.objects.filter(
            cluster_id__in=scoped_cluster_ids, deleted_at__isnull=True, fy=fy
        ).values_list("cluster_id", flat=True)
        clusters_needing_action_count = len(
            set(scoped_cluster_ids) - set(planned_cluster_ids)
        )

        kpis = {
            "total_ready": ready_for_support_count,
            "ready_pct": 100,
            "without_ssa": baseline_required_count,
            "without_ssa_pct": 100,
            "unclustered": base_schools_qs.filter(
                Q(cluster_id__isnull=True) | Q(cluster_id="")
            ).count(),
            "unclustered_pct": 100,
            "cluster_activities_needed": clusters_needing_action_count,
            "cluster_needed_pct": 100,
            "core_pending": core_package_gaps_count,
            "core_pending_pct": 100,
            "partner_pending": partner_pending_schedule_count,
            "partner_pending_pct": 100,
            "scheduled_this_week": in_my_plan_count,
            "scheduled_this_week_pct": 100,
            "completion_rate": 100,
        }

        kpi_strip_items = [
            {
                "label": "Ready for Support",
                "value": str(ready_for_support_count),
                "raw_value": ready_for_support_count,
                "helper": "Clustered & SSA active",
                "icon": "school",
                "variant": "success",
            },
            {
                "label": "SSA Required",
                "value": str(baseline_required_count),
                "raw_value": baseline_required_count,
                "helper": "No current SSA",
                "icon": "warning",
                "variant": "danger",
            },
            {
                "label": "Clusters Needing Action",
                "value": str(clusters_needing_action_count),
                "raw_value": clusters_needing_action_count,
                "helper": "Missing cluster action",
                "icon": "users",
                "variant": "warning",
            },
            {
                "label": "Core Package Gaps",
                "value": str(core_package_gaps_count),
                "raw_value": core_package_gaps_count,
                "helper": "Core schools gaps",
                "icon": "target",
                "variant": "danger",
            },
            {
                "label": "Partner Pending Schedule",
                "value": str(partner_pending_schedule_count),
                "raw_value": partner_pending_schedule_count,
                "helper": "Partner awaiting schedule",
                "icon": "briefcase",
                "variant": "info",
            },
            {
                "label": "In My Plan",
                "value": str(in_my_plan_count),
                "raw_value": in_my_plan_count,
                "helper": "Scheduled activities",
                "icon": "calendar",
                "variant": "blue",
            },
            {
                "label": "Cost Blocked",
                "value": str(cost_blocked_count),
                "raw_value": cost_blocked_count,
                "helper": "Missing Cost Catalogue",
                "icon": "warning",
                "variant": "danger",
            },
            {
                "label": "Data Cleanup Required",
                "value": str(data_cleanup_count),
                "raw_value": data_cleanup_count,
                "helper": "Missing operational fields",
                "icon": "school",
                "variant": "purple",
            },
        ]

        # 6. Cluster Planning List
        clusters_in_scope = Cluster.objects.filter(
            id__in=scoped_cluster_ids, deleted_at__isnull=True
        ).select_related("district")
        cluster_planning_data = []
        for c in clusters_in_scope[:3]:
            member_schools = School.objects.filter(
                cluster_id=c.id, deleted_at__isnull=True
            )
            member_records = (
                SsaRecord.objects.filter(
                    school__in=member_schools,
                    verification_status="confirmed",
                    deleted_at__isnull=True,
                )
                .prefetch_related("scores")
                .order_by("school_id", "-date_of_ssa")
            )

            latest_recs = {}
            for r in member_records:
                if r.school_id not in latest_recs:
                    latest_recs[r.school_id] = r

            tot_score = sum(
                r.average_score for r in latest_recs.values() if r.average_score
            )
            rec_cnt = sum(1 for r in latest_recs.values() if r.average_score)
            avg_ssa = round(tot_score / rec_cnt * 10) if rec_cnt > 0 else 0

            # Find weakest interventions
            interv_sums = {}
            interv_counts = {}
            for r in latest_recs.values():
                for score in r.scores.all():
                    interv_sums[score.intervention] = (
                        interv_sums.get(score.intervention, 0) + score.score
                    )
                    interv_counts[score.intervention] = (
                        interv_counts.get(score.intervention, 0) + 1
                    )

            interv_averages = []
            for code, label in SsaIntervention.choices:
                if code in interv_sums:
                    avg_val = interv_sums[code] / interv_counts[code]
                    interv_averages.append((code, label, avg_val))

            interv_averages.sort(key=lambda x: x[2])
            weakest_intervs = [item[1] for item in interv_averages[:4]]

            cluster_planning_data.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "avg_ssa": avg_ssa,
                    "weakest_interventions": weakest_intervs,
                    "school_count": member_schools.count(),
                }
            )

        # 7. Core Schools Summary counts
        core_schools_qs = schools_qs.filter(school_type__in=["core", "champion"])
        core_no_ssa = core_schools_qs.exclude(current_fy_ssa_status="done").count()
        core_1st_visit_pending = (
            core_schools_qs.exclude(
                activities__activity_type="school_visit",
                activities__status__in=["completed", "ia_verified"],
                activities__fy=fy,
            )
            .distinct()
            .count()
        )

        core_1st_training_pending = (
            core_schools_qs.exclude(
                activities__activity_type__in=[
                    "training",
                    "school_improvement_training",
                    "cluster_training",
                ],
                activities__status__in=["completed", "ia_verified"],
                activities__fy=fy,
            )
            .distinct()
            .count()
        )

        # Real signal: the school's 2nd-sequence visit/training slot on its
        # active Core Plan (CoreActivitySlot), not yet in a "done" status.
        # Schools with no Core Plan (or no 2nd slot yet) simply don't count —
        # an honest zero, not a fabricated offset of the 1st-round count.
        core_school_op_ids = list(core_schools_qs.values_list("school_id", flat=True))
        core_2nd_visit_pending = (
            CoreActivitySlot.objects.filter(
                core_plan__school_id__in=core_school_op_ids,
                activity_type="visit",
                sequence_number=2,
            )
            .exclude(status__in=CORE_SLOT_DONE_STATUSES)
            .count()
        )
        core_2nd_training_pending = (
            CoreActivitySlot.objects.filter(
                core_plan__school_id__in=core_school_op_ids,
                activity_type="training",
                sequence_number=2,
            )
            .exclude(status__in=CORE_SLOT_DONE_STATUSES)
            .count()
        )

        core_summary = {
            "no_ssa": core_no_ssa,
            "first_visit_pending": core_1st_visit_pending,
            "first_training_pending": core_1st_training_pending,
            "second_visit_pending": core_2nd_visit_pending,
            "second_training_pending": core_2nd_training_pending,
        }

        return {
            "schools": schools_data,
            "clusters": paginated_clusters,
            "kpis": kpis,
            "kpi_strip_items": kpi_strip_items,
            "cluster_planning": cluster_planning_data,
            "core_summary": core_summary,
            "total_count": total_schools_count,
            "page": page,
            "per_page": per_page,
            "total_pages": (total_schools_count + per_page - 1) // per_page,
            "active_tab": active_tab,
        }
