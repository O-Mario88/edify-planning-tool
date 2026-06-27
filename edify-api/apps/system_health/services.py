"""
System health — org-wide health counts + mock-data leakage detection.

The CORE RULE: the database is the only runtime source of truth. Production must
never contain mock/demo operational data. The mock-leakage checks below surface
any signal that local-test data has leaked into a production deployment.
"""
from __future__ import annotations

import os

from django.conf import settings
from django.db.models import Count

from apps.core.models import DataSource
from apps.schools.models import School


def report() -> dict:
    schools = School.objects.filter(deleted_at__isnull=True)
    data = {
        "fy": _fy(),
        "schoolsTotal": schools.count(),
        "bySchoolType": {t: schools.filter(school_type=t).count() for t in ("client", "core", "champion")},
        "ssaDone": schools.filter(current_fy_ssa_status="done").count(),
        "ssaMissing": schools.exclude(current_fy_ssa_status="done").count(),
        "clustered": schools.filter(cluster_status="clustered").count(),
        "unclustered": schools.filter(cluster_status="unclustered").count(),
        "planningReady": schools.filter(planning_readiness="ready").count(),
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
    """Detect data/workflow conditions that make a demo or approval chain unsafe."""
    from apps.activities.models import Activity
    from apps.evidence.models import EvidenceRecord

    active = Activity.objects.filter(deleted_at__isnull=True)
    scheduled = active.exclude(status__in=["not_planned", "cancelled", "deferred", "rejected"])
    missing_cost_lines = scheduled.annotate(cost_line_count=Count("schedule_cost_lines")).filter(cost_line_count=0).count()
    missing_rates = scheduled.filter(cost_missing=True).count()

    missing_evidence_files = 0
    for evidence in EvidenceRecord.objects.filter(quarantined=False).only("uri"):
        if not os.path.exists(os.path.join(settings.EVIDENCE_STORAGE_DIR, evidence.uri)):
            missing_evidence_files += 1

    blockers = []
    if missing_cost_lines:
        blockers.append(f"{missing_cost_lines} scheduled activities have no persisted cost lines.")
    if missing_rates:
        blockers.append(f"{missing_rates} scheduled activities are missing cost rates.")
    if missing_evidence_files:
        blockers.append(f"{missing_evidence_files} evidence records point to missing files.")

    return {
        "scheduledActivitiesMissingCostLines": missing_cost_lines,
        "scheduledActivitiesMissingRates": missing_rates,
        "evidenceFilesMissingOnDisk": missing_evidence_files,
        "clean": len(blockers) == 0,
        "blockers": blockers,
    }


__all__ = ["report"]
