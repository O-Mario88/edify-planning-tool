"""
System health — org-wide health counts + mock-data leakage detection.

The CORE RULE: the database is the only runtime source of truth. Production must
never contain mock/demo operational data. The mock-leakage checks below surface
any signal that local-test data has leaked into a production deployment.
"""

from __future__ import annotations

import os

from django.conf import settings
from django.db.models import Count, F, Q, Sum

from apps.core.enums import PlanningReadiness
from apps.core.models import DataSource
from apps.schools.models import School


def report() -> dict:
    schools = School.objects.filter(deleted_at__isnull=True)
    # Single conditional-aggregation query (8 COUNTs → 1 pass) for the org-wide
    # health strip. bySchoolType is built from the same aggregate.
    agg = schools.aggregate(
        total=Count("id"),
        client=Count("id", filter=Q(school_type="client")),
        core=Count("id", filter=Q(school_type="core")),
        champion=Count("id", filter=Q(school_type="champion")),
        ssa_done=Count("id", filter=Q(current_fy_ssa_status="done")),
        clustered=Count("id", filter=Q(cluster_status="clustered")),
        unclustered=Count("id", filter=Q(cluster_status="unclustered")),
        planning_ready=Count(
            "id",
            filter=Q(planning_readiness__in=PlanningReadiness.planning_ready_values()),
        ),
    )
    total = agg["total"] or 0
    ssa_done = agg["ssa_done"] or 0
    data = {
        "fy": _fy(),
        "schoolsTotal": total,
        "bySchoolType": {
            "client": agg["client"],
            "core": agg["core"],
            "champion": agg["champion"],
        },
        "ssaDone": ssa_done,
        "ssaMissing": total - ssa_done,
        "clustered": agg["clustered"],
        "unclustered": agg["unclustered"],
        "planningReady": agg["planning_ready"],
    }
    data["mockDataLeakage"] = _mock_leakage()
    data["workflowIssues"] = _workflow_issues()
    data["permissionAudit"] = _permission_guards_audit()
    data["routeIntelligence"] = _route_intelligence()
    data["uiQuality"] = _ui_quality()
    data["professionalDevelopment"] = _professional_development()
    return data


def _professional_development() -> dict:
    """Professional Development checks (mandate §36) — certificate/NetSuite
    closure gates, self-approval/signoff leaks, stale-queue backlogs."""
    try:
        from apps.professional_development.health import pd_health_checks

        return pd_health_checks()
    except Exception:  # noqa: BLE001 — the health page must render regardless
        return {"checks": []}


def _ui_quality() -> dict:
    """Gold Standard UI lints (mock data, emojis, dead links, static chart
    series, uncompiled responsive variants, light-only chart grids)."""
    try:
        from apps.system_health.ui_quality import ui_quality_checks

        return ui_quality_checks()
    except Exception:  # noqa: BLE001 — the health page must render regardless
        return {"checks": []}


def _route_intelligence() -> dict:
    """Route Intelligence checks (route batches vs cost batches, location data
    quality, district-rule violations, working-day overloads) — mandate §14."""
    try:
        from apps.routes.health import route_intelligence_checks

        return route_intelligence_checks()
    except Exception:  # noqa: BLE001 — the health page must render regardless
        return {}


def _fy() -> str:
    from apps.core.fy import get_operational_fy

    return get_operational_fy()


def missing_cost_lines_count() -> int:
    """Scheduled activities carrying no budget/cost line. Broken out as its own
    function so other pages (e.g. the admin dashboard) can surface this exact
    real count without running the full `report()` (which does much more work,
    including filesystem checks)."""
    from apps.activities.models import Activity

    active = Activity.objects.filter(deleted_at__isnull=True)
    scheduled = active.exclude(
        status__in=["not_planned", "cancelled", "deferred", "rejected"]
    )
    return (
        scheduled.annotate(cost_line_count=Count("schedule_cost_lines"))
        .filter(cost_line_count=0)
        .count()
    )


def _mock_leakage() -> dict:
    """Detect mock/demo data in the runtime database. In production EVERY one of
    these should be zero/empty; a non-zero count is a critical finding."""
    # 1) Local-test records present?
    local_test_schools = School.objects.filter(
        source=DataSource.LOCAL_TEST_UPLOAD.value
    ).count()
    # 2) Mock/seed flags on in production?
    flags = {
        "isProduction": settings.IS_PRODUCTION,
        "enableMockData": getattr(settings, "ENABLE_MOCK_DATA", False),
        "enableDevSeed": getattr(settings, "ENABLE_DEV_SEED", False),
        "enableDevImports": getattr(settings, "ENABLE_DEV_IMPORTS", False),
        "partnerRoleBridge": getattr(settings, "PARTNER_ROLE_BRIDGE", False),
    }
    violations = []
    if settings.IS_PRODUCTION:
        if local_test_schools:
            violations.append(
                f"{local_test_schools} schools tagged source=local_test_upload found in production."
            )
        for flag in (
            "enableMockData",
            "enableDevSeed",
            "enableDevImports",
            "partnerRoleBridge",
        ):
            if flags[flag]:
                violations.append(f"{flag} is ON in production — must be false.")
    return {
        "localTestSchools": local_test_schools,
        "flags": flags,
        "violations": violations,
        "clean": len(violations) == 0,
    }


def _workflow_issues() -> dict:
    """Detect data/workflow + finance-integrity conditions that make a demo or
    approval chain unsafe. Every check is a DB aggregation, not a Python loop."""
    from apps.activities.models import Activity, ActivityScheduleCostLine
    from apps.budget.models import CostCatalogue
    from apps.evidence.models import EvidenceRecord

    active = Activity.objects.filter(deleted_at__isnull=True)
    scheduled = active.exclude(
        status__in=["not_planned", "cancelled", "deferred", "rejected"]
    )
    missing_cost_lines = missing_cost_lines_count()
    missing_rates = scheduled.filter(cost_missing=True).count()

    missing_evidence_files = 0
    for evidence in EvidenceRecord.objects.filter(quarantined=False).only("uri"):
        if not os.path.exists(
            os.path.join(settings.EVIDENCE_STORAGE_DIR, evidence.uri)
        ):
            missing_evidence_files += 1

    # ── Finance-integrity checks ─────────────────────────────────────────────
    # Activity total ≠ sum of its budget lines (a reconciliation break).
    line_sum_mismatch = 0
    for act in scheduled.exclude(est_cost_cents=0).only("id", "est_cost_cents"):
        line_total = sum(line.amount for line in act.schedule_cost_lines.all())
        if line_total and line_total != act.est_cost_cents:
            line_sum_mismatch += 1

    # Cluster meeting must NEVER carry venue or facilitation cost lines.
    cluster_meeting_with_venue = ActivityScheduleCostLine.objects.filter(
        activity__activity_type="cluster_meeting", cost_setting_key="venue"
    ).count()
    cluster_meeting_with_facilitation = ActivityScheduleCostLine.objects.filter(
        activity__activity_type="cluster_meeting",
        cost_setting_key="training_session_fee",
    ).count()
    # Cluster meeting must NEVER use the group-training meal rate.
    cluster_meeting_with_group_meal = ActivityScheduleCostLine.objects.filter(
        activity__activity_type="cluster_meeting",
        cost_setting_key="meals_per_participant",
    ).count()

    # Trainings (group training) without a participant count.
    training_no_participants = (
        scheduled.filter(
            activity_type__in=[
                "training",
                "cluster_training",
                "core_training",
                "school_improvement_training",
            ]
        )
        .filter(
            teachers_attended__isnull=True,
            leaders_attended__isnull=True,
            other_participants__isnull=True,
        )
        .count()
    )

    # No active CD Cost Catalogue.
    missing_active_catalogue = (
        0 if CostCatalogue.objects.filter(is_active=True).exists() else 1
    )

    # Advance disbursed before responsible confirmation (finance-safety breach).
    from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus

    early_disbursement = AdvanceRequest.objects.filter(
        status=AdvanceRequestStatus.DISBURSED,
        confirmed_at__isnull=True,
    ).count()

    # ── Staff-ownership integrity checks ─────────────────────────────────────
    from apps.schools.models import School as _School
    from apps.accounts.models import (
        StaffProfile,
        StaffSetupCandidate,
        StaffSupervisorAssignment,
    )

    unmatched_staff_schools = _School.objects.filter(
        account_owner_status="unmatched"
    ).count()
    ambiguous_staff_schools = _School.objects.filter(
        account_owner_status="ambiguous"
    ).count()
    pending_candidates = StaffSetupCandidate.objects.filter(
        status="pending_profile"
    ).count()
    # CCEOs without a PL supervisor (the chain gap that blocks PL team scope).
    cceo_ids = StaffProfile.objects.filter(
        user__active_role="CCEO", deleted_at__isnull=True
    ).values_list("id", flat=True)
    cceos_without_supervisor = sum(
        1
        for cid in cceo_ids
        if not StaffSupervisorAssignment.objects.filter(supervisee_id=cid).exists()
    )

    # ── Performance-integrity checks ─────────────────────────────────────────
    from apps.targets.performance import ACHIEVED_STATUSES as _DONE

    # Completed activities missing evidence or Activity Code (counted as achieved
    # by status but not by the strict evidence rule — a counting risk).
    done_no_evidence = (
        Activity.objects.filter(status__in=_DONE, deleted_at__isnull=True)
        .exclude(evidence_status="accepted")
        .count()
    )
    done_no_code = Activity.objects.filter(
        status__in=_DONE, deleted_at__isnull=True, salesforce_activity_id=""
    ).count()

    # ── Activity Closure & Analytics Workflow Breaks ──────────────────────────
    from apps.core.enums import ActivityStatus

    unclustered_schools = _School.objects.filter(
        cluster_status="unclustered", deleted_at__isnull=True
    ).count()
    stuck_in_planning = active.filter(status=ActivityStatus.PLANNED).count()
    partner_scheduled_missing = active.filter(
        status=ActivityStatus.ASSIGNED_TO_PARTNER
    ).count()

    # IA skipped: Closed activity where checklist shows IA not verified
    ia_skipped = (
        active.filter(status=ActivityStatus.CLOSED)
        .exclude(closure_checklist__ia_verified=True)
        .count()
    )

    # Accounts cleared before IA verified
    accounts_clearance_before_ia = (
        active.filter(closure_checklist__accounts_cleared=True)
        .exclude(status__in=[ActivityStatus.IA_VERIFIED, ActivityStatus.CLOSED])
        .count()
    )

    # Closed activity missing NetSuite ID
    netsuite_id_missing = (
        active.filter(status=ActivityStatus.CLOSED)
        .exclude(completed_snapshot__netsuite_expense_id__isnull=False)
        .count()
    )

    # Closed activity missing analytics publish confirmation
    closed_missing_analytics = (
        active.filter(status=ActivityStatus.CLOSED)
        .exclude(analytics_publish_record__status="published")
        .count()
    )

    # ── Workflow-consistency checks (clustering → planning → partner → project) ─
    from apps.clusters.models import SchoolClusterAssignment
    from apps.partners.models import Partner, PartnerAssignment
    from apps.projects.models import ProjectSchoolAssignment

    fy = _fy()
    live_schools = _School.objects.filter(deleted_at__isnull=True)

    # Clustered schools whose readiness state keeps them out of Planning.
    planning_visible_readiness = [
        "ready",
        "limited",
        "ready_for_support_planning",
        "ready_for_baseline_ssa",
    ]
    clustered_not_in_planning = (
        live_schools.filter(cluster_status="clustered")
        .exclude(planning_readiness__in=planning_visible_readiness)
        .count()
    )

    # Clustered schools with no cluster link (no cluster_id OR no assignment row).
    assigned_school_ids = SchoolClusterAssignment.objects.values_list(
        "school_id", flat=True
    )
    clustered_missing_assignment = (
        live_schools.filter(cluster_status="clustered")
        .filter(
            Q(cluster_id__isnull=True)
            | Q(cluster_id="")
            | ~Q(id__in=assigned_school_ids)
        )
        .count()
    )

    # Partner-assignment statuses. Pending = handed to partner but not yet
    # scheduled; active additionally includes partner_scheduled (mirrors
    # apps/planning/planning_service.py).
    pending_partner_statuses = [
        "assigned",
        "pending_scheduling",
        "partner_pending_schedule",
        "assigned_to_partner_pending_scheduling",
    ]
    active_partner_statuses = pending_partner_statuses + ["partner_scheduled"]

    # Partner-assigned schools still rendered actionable in Staff Planning.
    partner_assigned_still_staff_planning = PartnerAssignment.objects.filter(
        status__in=pending_partner_statuses,
        school__deleted_at__isnull=True,
        school__planning_readiness__in=PlanningReadiness.planning_ready_values(),
    ).count()

    # Partner work the partner can never see: active assignments whose partner
    # has no user link, plus partner-delivery activities with no partner set.
    partner_assignments_no_user = PartnerAssignment.objects.filter(
        status__in=active_partner_statuses, partner__user__isnull=True
    ).count()
    partner_activities_unassigned = (
        active.filter(delivery_type="partner")
        .filter(Q(assigned_partner_id__isnull=True) | Q(assigned_partner_id=""))
        .count()
    )
    partner_assignments_invisible = (
        partner_assignments_no_user + partner_activities_unassigned
    )

    # partner_scheduled activities whose assigned partner has no user link —
    # scheduled work that appears in no Partner Plan.
    partner_ids_with_user = Partner.all_objects.filter(user__isnull=False).values_list(
        "id", flat=True
    )
    partner_scheduled_no_partner_plan = (
        active.filter(
            delivery_type="partner",
            status=ActivityStatus.PARTNER_SCHEDULED,
            assigned_partner_id__isnull=False,
        )
        .exclude(assigned_partner_id="")
        .exclude(assigned_partner_id__in=partner_ids_with_user)
        .count()
    )

    # Partner-delivery activities with no staff monitor — invisible to staff
    # My Plan monitoring.
    partner_missing_monitoring = (
        active.filter(delivery_type="partner")
        .filter(Q(monitored_by_staff_id__isnull=True) | Q(monitored_by_staff_id=""))
        .count()
    )

    # Staff-delivery scheduled activities with no responsible staff — they
    # appear in nobody's My Plan.
    staff_scheduled_no_owner = (
        active.filter(delivery_type="staff", status=ActivityStatus.SCHEDULED)
        .filter(Q(responsible_staff_id__isnull=True) | Q(responsible_staff_id=""))
        .count()
    )

    # Cluster-scoped activities without a cluster.
    cluster_activity_missing_cluster = active.filter(
        activity_type__startswith="cluster", cluster__isnull=True
    ).count()

    # Project schools with no project activity this FY (missing from PC planning).
    project_school_ids = (
        ProjectSchoolAssignment.objects.filter(school__deleted_at__isnull=True)
        .values_list("school_id", flat=True)
        .distinct()
    )
    school_ids_with_project_activity = (
        active.filter(fy=fy, project_id__isnull=False, school_id__isnull=False)
        .exclude(project_id="")
        .values_list("school_id", flat=True)
    )
    project_schools_no_activity = (
        live_schools.filter(id__in=project_school_ids)
        .exclude(id__in=school_ids_with_project_activity)
        .count()
    )

    # Project activities with no responsible staff.
    project_activities_unowned = (
        active.filter(project_id__isnull=False)
        .exclude(project_id="")
        .filter(Q(responsible_staff_id__isnull=True) | Q(responsible_staff_id=""))
        .count()
    )

    # Budget lines missing their catalogue reference (unauditable pricing).
    budget_lines_missing_catalogue = (
        ActivityScheduleCostLine.objects.filter(activity__deleted_at__isnull=True)
        .filter(
            Q(catalogue_id__isnull=True)
            | Q(catalogue_id="")
            | Q(catalogue_version__isnull=True)
        )
        .count()
    )

    # Active-plan activities with no planned date.
    active_plan_missing_date = active.filter(
        status__in=[
            ActivityStatus.SCHEDULED,
            ActivityStatus.PARTNER_SCHEDULED,
            ActivityStatus.IN_PROGRESS,
        ],
        planned_date__isnull=True,
    ).count()

    # Confirmed/approved/disbursed weekly fund requests whose LIVE scheduled
    # cost lines (what a re-sync would compute right now) no longer match the
    # frozen total. generate_weekly_fund_request() deliberately stops syncing
    # a request's total/lines once it leaves the draft state
    # (pending_responsible_confirmation) — a later reschedule/cancellation in
    # that week can't silently rewrite an approved figure — so this check
    # can't just compare a request against its OWN (equally frozen) lines; it
    # has to recompute the live sum the same way the generator would.
    from apps.fund_requests.models import WeeklyFundRequest

    confirmed_wfrs_drifted = 0
    for _wfr in WeeklyFundRequest.objects.exclude(
        status="pending_responsible_confirmation"
    ).only(
        "id", "responsible_user", "week_start_date", "week_end_date", "total_amount"
    ):
        _live_sum = (
            ActivityScheduleCostLine.objects.filter(
                responsible_user=_wfr.responsible_user,
                planned_date__gte=_wfr.week_start_date,
                planned_date__lte=_wfr.week_end_date,
                activity__deleted_at__isnull=True,
            )
            .exclude(activity__status="cancelled")
            .aggregate(s=Sum("amount"))["s"]
            or 0
        )
        if _live_sum != _wfr.total_amount:
            confirmed_wfrs_drifted += 1

    # Terminal-status activities still returned by the My Plan feed (feed lacks
    # a status exclusion).
    closed_still_in_my_plan = active.filter(
        status__in=[
            ActivityStatus.CLOSED,
            ActivityStatus.CANCELLED,
            ActivityStatus.REJECTED,
        ],
        fy=fy,
    ).count()

    # ── Daily Visit Batch integrity checks ───────────────────────────────────
    from apps.daily_visit_batches.models import DailyVisitBatch
    from apps.daily_visit_batches.pricing import (
        DAILY_BATCH_ELIGIBLE_TYPES,
        REQUIRED_KEYS,
    )
    from apps.geography.models import District, SecondaryDistrictGroup

    # Districts with no primary/secondary classification yet — the root cause
    # of most "cannot schedule" errors below; actionable at
    # /admin-panel/region-district-setup.
    districts_missing_classification = District.objects.filter(
        district_type__isnull=True
    ).count()

    # Batch-eligible staff visits scheduled but never assigned a batch.
    scheduled_visits_missing_batch = scheduled.filter(
        activity_type__in=DAILY_BATCH_ELIGIBLE_TYPES,
        delivery_type="staff",
        school__isnull=False,
        daily_visit_batch__isnull=True,
    ).count()

    mixed_district_batches = 0
    unapproved_secondary_batches = 0
    batch_count_mismatch = 0
    budget_changed_after_approval = 0
    from apps.fund_requests.models import WeeklyFundRequest as _WFR

    for _batch in DailyVisitBatch.objects.all().only(
        "id", "district_type", "school_count", "responsible_user", "visit_date"
    ):
        _member_activities = (
            _batch.activities.filter(deleted_at__isnull=True)
            .exclude(status="cancelled")
            .select_related("school")
        )
        _live_district_ids = set()
        _live_types = set()
        for _a in _member_activities:
            if _a.school_id and _a.school.district_id:
                _live_district_ids.add(_a.school.district_id)
                if _a.school.district.district_type:
                    _live_types.add(_a.school.district.district_type)
        _live_count = len(_member_activities)
        if len(_live_types) > 1:
            mixed_district_batches += 1
        if _batch.district_type == "secondary" and len(_live_district_ids) > 1:
            _match = (
                SecondaryDistrictGroup.objects.filter(status="approved")
                .annotate(
                    n=Count(
                        "members__district_id",
                        distinct=True,
                        filter=Q(members__district_id__in=_live_district_ids),
                    )
                )
                .filter(n=len(_live_district_ids))
                .exists()
            )
            if not _match:
                unapproved_secondary_batches += 1
        if _live_count and _live_count != _batch.school_count:
            batch_count_mismatch += 1
            is_locked = (
                _WFR.objects.filter(
                    responsible_user=_batch.responsible_user,
                    week_start_date__lte=_batch.visit_date,
                    week_end_date__gte=_batch.visit_date,
                )
                .exclude(status="pending_responsible_confirmation")
                .exists()
            )
            if is_locked:
                budget_changed_after_approval += 1

    # Batch-linked active activities with zero cost lines.
    batch_activities_missing_lines = (
        active.filter(daily_visit_batch__isnull=False, deleted_at__isnull=True)
        .exclude(status="cancelled")
        .annotate(n=Count("schedule_cost_lines"))
        .filter(n=0)
        .count()
    )

    # Under-target batch with no reason recorded.
    under_target_missing_reason = (
        DailyVisitBatch.objects.filter(school_count__lt=F("required_target_snapshot"))
        .filter(Q(reason__isnull=True) | Q(reason=""))
        .count()
    )

    # Active Cost Catalogue missing one of the Daily Visit Batch required keys.
    _all_required_batch_keys = set(REQUIRED_KEYS["primary"]) | set(
        REQUIRED_KEYS["secondary"]
    )
    _active_cat = (
        CostCatalogue.objects.filter(is_active=True).order_by("-version").first()
    )
    if _active_cat:
        from apps.budget.models import CostSetting as _CostSetting

        _present_keys = set(
            _CostSetting.objects.filter(
                Q(catalogue=_active_cat) | Q(catalogue__isnull=True)
            ).values_list("key", flat=True)
        )
        catalogue_missing_batch_keys = len(_all_required_batch_keys - _present_keys)
    else:
        catalogue_missing_batch_keys = len(_all_required_batch_keys)

    # ── Mandate finance-law checks ───────────────────────────────────────────
    from apps.accounts.models import User as _User
    from apps.fund_requests.models import AdvanceRequest as _Adv

    # A PL's own weekly request must route to the CD — one sitting in the PL
    # queue means the approval router mis-fired (or predates the router).
    _pl_user_ids = list(
        _User.objects.filter(active_role="Program Lead").values_list("id", flat=True)
    )
    pl_requests_routed_to_pl = _WFR.objects.filter(
        status="submitted_to_pl", responsible_user__in=_pl_user_ids
    ).count()

    # Accountability submitted/cleared without its NetSuite Code — the code is
    # the accountability proof and must exist on every such row.
    accountability_missing_netsuite = (
        _Adv.objects.filter(status__in=["accountability_pending", "accounted"])
        .filter(
            Q(accountability_netsuite_id__isnull=True)
            | Q(accountability_netsuite_id="")
        )
        .count()
    )

    # Closed activities where money moved but no NetSuite Code was captured.
    closed_money_missing_netsuite = (
        active.filter(
            status=ActivityStatus.CLOSED,
            advance_requests__status__in=[
                "disbursed",
                "accountability_pending",
                "accounted",
                "reimbursed",
            ],
        )
        .filter(
            Q(advance_requests__accountability_netsuite_id__isnull=True)
            | Q(advance_requests__accountability_netsuite_id="")
        )
        .distinct()
        .count()
    )

    blockers = []
    if unclustered_schools:
        blockers.append(f"{unclustered_schools} school(s) without cluster.")
    if missing_cost_lines:
        blockers.append(
            f"{missing_cost_lines} scheduled activity(ies) without budget line."
        )
    if stuck_in_planning:
        blockers.append(f"{stuck_in_planning} activity(ies) stuck in Planning.")
    if partner_scheduled_missing:
        blockers.append(
            f"{partner_scheduled_missing} partner scheduled work missing from My Plan."
        )
    if done_no_evidence:
        blockers.append(
            f"{done_no_evidence} completed activity(ies) with evidence missing."
        )
    if done_no_code:
        blockers.append(
            f"{done_no_code} completed activity(ies) with Salesforce Activity ID missing."
        )
    if ia_skipped:
        blockers.append(
            f"{ia_skipped} closed activity(ies) where IA verification was skipped."
        )
    if accounts_clearance_before_ia:
        blockers.append(
            f"{accounts_clearance_before_ia} activity(ies) with accounts clearance processed before IA verification."
        )
    if netsuite_id_missing:
        blockers.append(
            f"{netsuite_id_missing} closed activity(ies) with NetSuite ID missing."
        )
    if closed_missing_analytics:
        blockers.append(
            f"{closed_missing_analytics} closed activity(ies) missing from analytics database."
        )

    if missing_rates:
        blockers.append(f"{missing_rates} scheduled activities are missing cost rates.")
    if missing_evidence_files:
        blockers.append(
            f"{missing_evidence_files} evidence records point to missing files."
        )
    if line_sum_mismatch:
        blockers.append(
            f"{line_sum_mismatch} activities have a total that doesn't match its budget-line sum."
        )
    if cluster_meeting_with_venue:
        blockers.append(
            f"{cluster_meeting_with_venue} cluster meeting(s) incorrectly carry a venue cost."
        )
    if cluster_meeting_with_facilitation:
        blockers.append(
            f"{cluster_meeting_with_facilitation} cluster meeting(s) incorrectly carry a facilitation fee."
        )
    if cluster_meeting_with_group_meal:
        blockers.append(
            f"{cluster_meeting_with_group_meal} cluster meeting(s) use the group-training meal rate."
        )
    if training_no_participants:
        blockers.append(
            f"{training_no_participants} training(s) have no participant count."
        )
    if missing_active_catalogue:
        blockers.append(
            "No active CD Cost Catalogue — publish one before scheduling activities."
        )
    if early_disbursement:
        blockers.append(
            f"{early_disbursement} advance(s) disbursed before responsible confirmation."
        )
    if unmatched_staff_schools:
        blockers.append(
            f"{unmatched_staff_schools} school(s) have unmatched staff — Admin setup required."
        )
    if ambiguous_staff_schools:
        blockers.append(
            f"{ambiguous_staff_schools} school(s) have ambiguous staff matches — Admin must disambiguate."
        )
    if pending_candidates:
        blockers.append(
            f"{pending_candidates} staff candidate(s) pending Admin profile setup."
        )
    if cceos_without_supervisor:
        blockers.append(
            f"{cceos_without_supervisor} CCEO(s) have no PL supervisor — PL team scope is incomplete."
        )
    if clustered_not_in_planning:
        blockers.append(
            f"{clustered_not_in_planning} clustered school(s) whose readiness state keeps them out of Planning."
        )
    if clustered_missing_assignment:
        blockers.append(
            f"{clustered_missing_assignment} clustered school(s) missing a cluster link or assignment row."
        )
    if partner_assigned_still_staff_planning:
        blockers.append(
            f"{partner_assigned_still_staff_planning} partner assignment(s) whose school still renders actionable in Staff Planning."
        )
    if partner_assignments_invisible:
        blockers.append(
            f"{partner_assignments_invisible} partner work item(s) invisible to any partner (no partner user link or no partner assigned)."
        )
    if partner_scheduled_no_partner_plan:
        blockers.append(
            f"{partner_scheduled_no_partner_plan} partner-scheduled activity(ies) missing from any Partner Plan (partner has no user link)."
        )
    if partner_missing_monitoring:
        blockers.append(
            f"{partner_missing_monitoring} partner activity(ies) with no staff monitor — invisible to My Plan monitoring."
        )
    if staff_scheduled_no_owner:
        blockers.append(
            f"{staff_scheduled_no_owner} staff scheduled activity(ies) with no responsible staff — in nobody's My Plan."
        )
    if cluster_activity_missing_cluster:
        blockers.append(
            f"{cluster_activity_missing_cluster} cluster activity(ies) not linked to a cluster."
        )
    if project_schools_no_activity:
        blockers.append(
            f"{project_schools_no_activity} project school(s) with no project activity this FY — missing from PC planning."
        )
    if project_activities_unowned:
        blockers.append(
            f"{project_activities_unowned} project activity(ies) with no responsible staff."
        )
    if budget_lines_missing_catalogue:
        blockers.append(
            f"{budget_lines_missing_catalogue} budget line(s) missing a Cost Catalogue reference."
        )
    if active_plan_missing_date:
        blockers.append(
            f"{active_plan_missing_date} active-plan activity(ies) with no planned date."
        )
    if closed_still_in_my_plan:
        blockers.append(
            f"{closed_still_in_my_plan} Terminal-status activities still returned by the My Plan feed (feed lacks a status exclusion)."
        )
    if confirmed_wfrs_drifted:
        blockers.append(
            f"{confirmed_wfrs_drifted} confirmed/approved weekly fund request(s) whose activities changed after approval — needs reconciliation."
        )
    if scheduled_visits_missing_batch:
        blockers.append(
            f"{scheduled_visits_missing_batch} staff school visit(s) scheduled without a Daily Visit Batch."
        )
    if mixed_district_batches:
        blockers.append(
            f"{mixed_district_batches} Daily Visit Batch(es) mix primary and secondary district schools."
        )
    if unapproved_secondary_batches:
        blockers.append(
            f"{unapproved_secondary_batches} secondary-district Daily Visit Batch(es) span districts with no approved group."
        )
    if batch_activities_missing_lines:
        blockers.append(
            f"{batch_activities_missing_lines} batch-linked activity(ies) have no cost-line breakdown."
        )
    if batch_count_mismatch:
        blockers.append(
            f"{batch_count_mismatch} Daily Visit Batch(es) have a stale school count (out of sync with live members)."
        )
    if under_target_missing_reason:
        blockers.append(
            f"{under_target_missing_reason} Daily Visit Batch(es) are below the CD daily target with no reason recorded."
        )
    if budget_changed_after_approval:
        blockers.append(
            f"{budget_changed_after_approval} Daily Visit Batch(es) changed after their weekly fund request left draft status."
        )
    if catalogue_missing_batch_keys:
        blockers.append(
            f"The active Cost Catalogue is missing {catalogue_missing_batch_keys} Daily Visit Batch rate(s)."
        )
    if districts_missing_classification:
        blockers.append(
            f"{districts_missing_classification} district(s) have no primary/secondary classification — school visits there cannot be scheduled."
        )
    if pl_requests_routed_to_pl:
        blockers.append(
            f"{pl_requests_routed_to_pl} PL-owned weekly fund request(s) routed to PL approval instead of CD."
        )
    if accountability_missing_netsuite:
        blockers.append(
            f"{accountability_missing_netsuite} accountability record(s) submitted/cleared without a NetSuite Code."
        )
    if closed_money_missing_netsuite:
        blockers.append(
            f"{closed_money_missing_netsuite} closed activity(ies) with disbursed money but no NetSuite Code."
        )

    # ── Core Schools package integrity (Core mandate §44) ────────────────────
    from apps.core_schools.models import CoreActivitySlot, CorePlan

    _core_active_plans = CorePlan.objects.exclude(
        status__in=["Cancelled", "cancelled", "Exited", "exited"]
    )
    core_schools_missing_plan = (
        School.objects.filter(school_type="core", deleted_at__isnull=True)
        .exclude(school_id__in=_core_active_plans.values_list("school_id", flat=True))
        .count()
    )
    core_schools_missing_cluster = (
        School.objects.filter(school_type="core", deleted_at__isnull=True)
        .filter(Q(cluster_id__isnull=True) | Q(cluster_id=""))
        .count()
    )
    _sched_slots = CoreActivitySlot.objects.filter(status__in=["Scheduled", "scheduled"])
    core_slots_scheduled_missing_activity = _sched_slots.filter(
        Q(activity_id__isnull=True) | Q(activity_id="")
    ).count()
    _linked = _sched_slots.exclude(activity_id__isnull=True).exclude(activity_id="")
    core_slot_activities_missing_budget = (
        Activity.objects.filter(
            id__in=_linked.values_list("activity_id", flat=True),
            deleted_at__isnull=True,
        )
        .annotate(_n=Count("schedule_cost_lines"))
        .filter(_n=0)
        .count()
    )
    core_duplicate_slot_activities = (
        _linked.values("activity_id").annotate(_n=Count("id")).filter(_n__gt=1).count()
    )
    _core_done = ["Completed", "Accountant Confirmed", "ia_verified", "iaVerify",
                  "accountant_confirmed"]
    core_package_complete_missing_slots = sum(
        1
        for plan in _core_active_plans.filter(
            status__in=["Package Complete", "Complete", "complete"]
        ).prefetch_related("slots")
        if sum(1 for sl in plan.slots.all() if sl.status in _core_done) < 8
    )
    _verified_slots = CoreActivitySlot.objects.filter(status__in=_core_done)
    core_verified_slots_missing_evidence = _verified_slots.filter(
        Q(evidence_uri__isnull=True) | Q(evidence_uri="")
    ).count()
    core_verified_slots_missing_sf_id = _verified_slots.filter(
        Q(salesforce_id__isnull=True) | Q(salesforce_id="")
    ).count()
    core_impact_without_baseline = _core_active_plans.filter(
        follow_up_average__isnull=False, baseline_average__isnull=True
    ).count()
    from apps.core_schools.models import CoreSchoolProfile as _CSP

    core_champion_without_verified_ssa = (
        _CSP.objects.exclude(champion_status__in=["Not Eligible", "not_eligible"])
        .filter(core_plan__baseline_average__isnull=True)
        .count()
    )

    if core_schools_missing_plan:
        blockers.append(
            f"{core_schools_missing_plan} core school(s) have no annual core package plan."
        )
    if core_slots_scheduled_missing_activity:
        blockers.append(
            f"{core_slots_scheduled_missing_activity} core package slot(s) marked Scheduled without a My Plan activity."
        )
    if core_slot_activities_missing_budget:
        blockers.append(
            f"{core_slot_activities_missing_budget} scheduled core activity(ies) missing budget lines."
        )
    if core_duplicate_slot_activities:
        blockers.append(
            f"{core_duplicate_slot_activities} activity(ies) linked to more than one core package slot."
        )
    if core_package_complete_missing_slots:
        blockers.append(
            f"{core_package_complete_missing_slots} core package(s) marked complete with unverified slots."
        )
    if core_verified_slots_missing_evidence:
        blockers.append(
            f"{core_verified_slots_missing_evidence} verified core slot(s) missing evidence."
        )
    if core_verified_slots_missing_sf_id:
        blockers.append(
            f"{core_verified_slots_missing_sf_id} verified core slot(s) missing an Activity SF ID."
        )
    if core_impact_without_baseline:
        blockers.append(
            f"{core_impact_without_baseline} core impact result(s) calculated without an annual baseline."
        )
    if core_champion_without_verified_ssa:
        blockers.append(
            f"{core_champion_without_verified_ssa} champion candidate(s) proposed without a verified SSA baseline."
        )

    return {
        "coreSchoolsMissingPlan": core_schools_missing_plan,
        "coreSchoolsMissingCluster": core_schools_missing_cluster,
        "coreSlotsScheduledMissingActivity": core_slots_scheduled_missing_activity,
        "coreSlotActivitiesMissingBudget": core_slot_activities_missing_budget,
        "coreDuplicateSlotActivities": core_duplicate_slot_activities,
        "corePackageCompleteMissingSlots": core_package_complete_missing_slots,
        "coreVerifiedSlotsMissingEvidence": core_verified_slots_missing_evidence,
        "coreVerifiedSlotsMissingSfId": core_verified_slots_missing_sf_id,
        "coreImpactWithoutBaseline": core_impact_without_baseline,
        "coreChampionWithoutVerifiedSsa": core_champion_without_verified_ssa,
        "plRequestsRoutedToPl": pl_requests_routed_to_pl,
        "accountabilityMissingNetsuite": accountability_missing_netsuite,
        "closedMoneyMissingNetsuite": closed_money_missing_netsuite,
        "unclusteredSchools": unclustered_schools,
        "scheduledActivitiesMissingCostLines": missing_cost_lines,
        "stuckInPlanning": stuck_in_planning,
        "partnerScheduledMissing": partner_scheduled_missing,
        "completedActivitiesWithoutEvidence": done_no_evidence,
        "completedActivitiesWithoutActivityCode": done_no_code,
        "iaSkipped": ia_skipped,
        "accountsClearanceBeforeIa": accounts_clearance_before_ia,
        "netsuiteIdMissing": netsuite_id_missing,
        "closedMissingAnalytics": closed_missing_analytics,
        "clusteredSchoolsNotInPlanning": clustered_not_in_planning,
        "clusteredSchoolsMissingAssignment": clustered_missing_assignment,
        "partnerAssignedStillInStaffPlanning": partner_assigned_still_staff_planning,
        "partnerAssignmentsInvisibleToPartner": partner_assignments_invisible,
        "partnerScheduledMissingFromPartnerPlan": partner_scheduled_no_partner_plan,
        "partnerScheduledMissingMonitoring": partner_missing_monitoring,
        "staffScheduledMissingOwner": staff_scheduled_no_owner,
        "clusterActivityMissingCluster": cluster_activity_missing_cluster,
        "projectSchoolsWithoutProjectActivity": project_schools_no_activity,
        "projectActivitiesUnowned": project_activities_unowned,
        "budgetLinesMissingCatalogue": budget_lines_missing_catalogue,
        "activePlanMissingDate": active_plan_missing_date,
        "closedStillInMyPlanFeed": closed_still_in_my_plan,
        "confirmedWeeklyRequestsDrifted": confirmed_wfrs_drifted,
        "scheduledVisitsMissingBatch": scheduled_visits_missing_batch,
        "mixedDistrictBatches": mixed_district_batches,
        "unapprovedSecondaryGroupBatches": unapproved_secondary_batches,
        "batchActivitiesMissingCostLines": batch_activities_missing_lines,
        "batchSchoolCountMismatch": batch_count_mismatch,
        "underTargetBatchesMissingReason": under_target_missing_reason,
        "budgetChangedAfterApprovalBypass": budget_changed_after_approval,
        "catalogueMissingDailyBatchKeys": catalogue_missing_batch_keys,
        "districtsMissingClassification": districts_missing_classification,
        "clean": len(blockers) == 0,
        "blockers": blockers,
    }


def _permission_guards_audit() -> dict:
    """Scan all URLs in the application's URL configuration to detect any routes
    missing the central require_page_permission decorator or custom role controls."""
    from django.urls import get_resolver

    resolver = get_resolver()
    unguarded_routes = []

    def _traverse(patterns, prefix=""):
        for pattern in patterns:
            pattern_str = prefix + str(pattern.pattern)

            if hasattr(pattern, "url_patterns"):
                _traverse(pattern.url_patterns, pattern_str)
            elif hasattr(pattern, "callback"):
                callback = pattern.callback

                is_drf_view = False
                view_class = getattr(callback, "cls", None)
                if view_class:
                    is_drf_view = True

                # Skip public/built-in paths
                if pattern_str.startswith("admin/"):
                    continue
                if any(
                    x in pattern_str
                    for x in ["login", "logout", "password_reset", "password_change"]
                ):
                    continue
                if pattern_str.startswith("static/") or pattern_str.startswith(
                    "media/"
                ):
                    continue
                if is_drf_view and getattr(view_class, "permission_classes", None):
                    continue

                has_guard = getattr(callback, "has_permission_guard", False)

                is_exempt = False
                callback_name = getattr(callback, "__name__", "")
                if callback_name in [
                    "switch_role_view",
                    "select2_list_view",
                    "debug_toolbar_view",
                    "ping_view",
                    "health_check",
                    "_health",
                    "stream",
                    "force_change_password_view",
                ]:
                    is_exempt = True

                if not has_guard and not is_exempt:
                    unguarded_routes.append(
                        {
                            "route": "/" + pattern_str.rstrip("$?^"),
                            "view_name": f"{callback.__module__}.{callback_name}",
                        }
                    )

    _traverse(resolver.url_patterns)

    return {
        "unguardedCount": len(unguarded_routes),
        "clean": len(unguarded_routes) == 0,
        "unguardedRoutes": unguarded_routes,
    }


__all__ = ["report", "missing_cost_lines_count"]
