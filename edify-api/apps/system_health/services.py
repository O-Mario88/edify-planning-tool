"""
System health — org-wide health counts + mock-data leakage detection.

The CORE RULE: the database is the only runtime source of truth. Production must
never contain mock/demo operational data. The mock-leakage checks below surface
any signal that local-test data has leaked into a production deployment.
"""
from __future__ import annotations

import os

from django.conf import settings
from django.db.models import Count, Q

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
        planning_ready=Count("id", filter=Q(planning_readiness="ready")),
    )
    total = agg["total"] or 0
    ssa_done = agg["ssa_done"] or 0
    data = {
        "fy": _fy(),
        "schoolsTotal": total,
        "bySchoolType": {"client": agg["client"], "core": agg["core"], "champion": agg["champion"]},
        "ssaDone": ssa_done,
        "ssaMissing": total - ssa_done,
        "clustered": agg["clustered"],
        "unclustered": agg["unclustered"],
        "planningReady": agg["planning_ready"],
    }
    data["mockDataLeakage"] = _mock_leakage()
    data["workflowIssues"] = _workflow_issues()
    return data


def _fy() -> str:
    from apps.core.fy import get_operational_fy
    return get_operational_fy()


def _mock_leakage() -> dict:
    """Detect mock/demo data in the runtime database. In production EVERY one of
    these should be zero/empty; a non-zero count is a critical finding."""
    # 1) Local-test records present?
    local_test_schools = School.objects.filter(source=DataSource.LOCAL_TEST_UPLOAD.value).count()
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
            violations.append(f"{local_test_schools} schools tagged source=local_test_upload found in production.")
        for flag in ("enableMockData", "enableDevSeed", "enableDevImports", "partnerRoleBridge"):
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
    scheduled = active.exclude(status__in=["not_planned", "cancelled", "deferred", "rejected"])
    missing_cost_lines = scheduled.annotate(cost_line_count=Count("schedule_cost_lines")).filter(cost_line_count=0).count()
    missing_rates = scheduled.filter(cost_missing=True).count()

    missing_evidence_files = 0
    for evidence in EvidenceRecord.objects.filter(quarantined=False).only("uri"):
        if not os.path.exists(os.path.join(settings.EVIDENCE_STORAGE_DIR, evidence.uri)):
            missing_evidence_files += 1

    # ── Finance-integrity checks ─────────────────────────────────────────────
    # Activity total ≠ sum of its budget lines (a reconciliation break).
    line_sum_mismatch = 0
    for act in scheduled.exclude(est_cost_cents=0).only("id", "est_cost_cents"):
        line_total = sum(l.amount for l in act.schedule_cost_lines.all())
        if line_total and line_total != act.est_cost_cents:
            line_sum_mismatch += 1

    # Cluster meeting must NEVER carry venue or facilitation cost lines.
    cluster_meeting_with_venue = ActivityScheduleCostLine.objects.filter(
        activity__activity_type="cluster_meeting", cost_setting_key="venue"
    ).count()
    cluster_meeting_with_facilitation = ActivityScheduleCostLine.objects.filter(
        activity__activity_type="cluster_meeting", cost_setting_key="training_session_fee"
    ).count()
    # Cluster meeting must NEVER use the group-training meal rate.
    cluster_meeting_with_group_meal = ActivityScheduleCostLine.objects.filter(
        activity__activity_type="cluster_meeting", cost_setting_key="meals_per_participant"
    ).count()

    # Trainings (group training) without a participant count.
    training_no_participants = scheduled.filter(
        activity_type__in=["training", "cluster_training", "core_training", "school_improvement_training"]
    ).filter(teachers_attended__isnull=True, leaders_attended__isnull=True, other_participants__isnull=True).count()

    # No active CD Cost Catalogue.
    missing_active_catalogue = 0 if CostCatalogue.objects.filter(is_active=True).exists() else 1

    # Advance disbursed before responsible confirmation (finance-safety breach).
    from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus
    early_disbursement = AdvanceRequest.objects.filter(
        status=AdvanceRequestStatus.DISBURSED,
        confirmed_at__isnull=True,
    ).count()

    # ── Staff-ownership integrity checks ─────────────────────────────────────
    from apps.schools.models import School as _School
    from apps.accounts.models import StaffProfile, StaffSetupCandidate, StaffSupervisorAssignment
    from django.db.models import Count

    unmatched_staff_schools = _School.objects.filter(account_owner_status="unmatched").count()
    ambiguous_staff_schools = _School.objects.filter(account_owner_status="ambiguous").count()
    pending_candidates = StaffSetupCandidate.objects.filter(status="pending_profile").count()
    # CCEOs without a PL supervisor (the chain gap that blocks PL team scope).
    cceo_ids = StaffProfile.objects.filter(
        user__active_role="CCEO", deleted_at__isnull=True
    ).values_list("id", flat=True)
    cceos_without_supervisor = sum(
        1 for cid in cceo_ids
        if not StaffSupervisorAssignment.objects.filter(supervisee_id=cid).exists()
    )

    blockers = []
    if missing_cost_lines:
        blockers.append(f"{missing_cost_lines} scheduled activities have no persisted cost lines.")
    if missing_rates:
        blockers.append(f"{missing_rates} scheduled activities are missing cost rates.")
    if missing_evidence_files:
        blockers.append(f"{missing_evidence_files} evidence records point to missing files.")
    if line_sum_mismatch:
        blockers.append(f"{line_sum_mismatch} activities have a total that doesn't match its budget-line sum.")
    if cluster_meeting_with_venue:
        blockers.append(f"{cluster_meeting_with_venue} cluster meeting(s) incorrectly carry a venue cost.")
    if cluster_meeting_with_facilitation:
        blockers.append(f"{cluster_meeting_with_facilitation} cluster meeting(s) incorrectly carry a facilitation fee.")
    if cluster_meeting_with_group_meal:
        blockers.append(f"{cluster_meeting_with_group_meal} cluster meeting(s) use the group-training meal rate.")
    if training_no_participants:
        blockers.append(f"{training_no_participants} training(s) have no participant count.")
    if missing_active_catalogue:
        blockers.append("No active CD Cost Catalogue — publish one before scheduling activities.")
    if early_disbursement:
        blockers.append(f"{early_disbursement} advance(s) disbursed before responsible confirmation.")
    if unmatched_staff_schools:
        blockers.append(f"{unmatched_staff_schools} school(s) have unmatched staff — Admin setup required.")
    if ambiguous_staff_schools:
        blockers.append(f"{ambiguous_staff_schools} school(s) have ambiguous staff matches — Admin must disambiguate.")
    if pending_candidates:
        blockers.append(f"{pending_candidates} staff candidate(s) pending Admin profile setup.")
    if cceos_without_supervisor:
        blockers.append(f"{cceos_without_supervisor} CCEO(s) have no PL supervisor — PL team scope is incomplete.")

    return {
        "scheduledActivitiesMissingCostLines": missing_cost_lines,
        "scheduledActivitiesMissingRates": missing_rates,
        "evidenceFilesMissingOnDisk": missing_evidence_files,
        "activityTotalLineSumMismatch": line_sum_mismatch,
        "clusterMeetingWithVenue": cluster_meeting_with_venue,
        "clusterMeetingWithFacilitation": cluster_meeting_with_facilitation,
        "clusterMeetingWithGroupMealRate": cluster_meeting_with_group_meal,
        "trainingWithoutParticipants": training_no_participants,
        "missingActiveCatalogue": missing_active_catalogue,
        "earlyDisbursement": early_disbursement,
        "unmatchedStaffSchools": unmatched_staff_schools,
        "ambiguousStaffSchools": ambiguous_staff_schools,
        "pendingStaffCandidates": pending_candidates,
        "cceosWithoutSupervisor": cceos_without_supervisor,
        "clean": len(blockers) == 0,
        "blockers": blockers,
    }


__all__ = ["report"]
