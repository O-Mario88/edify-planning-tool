"""System Health contribution: the directory data-quality queues.

Phase 1b of the operations roadmap. Every red number here leads to an
actionable queue with an owner — the Data Quality Center for school
issues and duplicates, the assignment surfaces for capacity — because a
dashboard that only shows red numbers is not an exception system.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone


def data_quality_health() -> dict:
    from apps.realtime.models import ScheduledJobExecution
    from apps.schools.data_quality import data_quality_summary

    summary = data_quality_summary()
    now = timezone.now()
    checks = []
    if summary["critical"]:
        checks.append(
            {
                "key": "dq_critical_open",
                "severity": "critical",
                "component": "School data quality",
                "current_state": f"{summary['critical']} critical open issue(s)",
                "expected_state": "0 critical (unclustered operating schools)",
                "last_check": now.isoformat(),
                "owner": "ImpactAssessment",
                "recommended_action": (
                    "Work the Data Quality Center queue — critical issues "
                    "block planning eligibility."
                ),
                "resolution_link": "/admin-panel/data-quality-center",
            }
        )
    if summary["missingCoordinates"]:
        checks.append(
            {
                "key": "dq_missing_coordinates",
                "severity": "warning",
                "component": "School coordinates",
                "current_state": (
                    f"{summary['missingCoordinates']} operating school(s) "
                    "without usable coordinates"
                ),
                "expected_state": (
                    "Every operating school locatable — the route-"
                    "optimisation precondition (roadmap Phase 4)"
                ),
                "last_check": now.isoformat(),
                "owner": "CCEO",
                "recommended_action": (
                    "Capture GPS on the next visit or set a geo point in "
                    "Route Intelligence."
                ),
                "resolution_link": "/admin-panel/data-quality-center",
            }
        )
    if summary["pendingDuplicatePairs"]:
        checks.append(
            {
                "key": "dq_duplicates_pending",
                "severity": "warning",
                "component": "Duplicate schools",
                "current_state": (
                    f"{summary['pendingDuplicatePairs']} proposed duplicate "
                    "pair(s) awaiting a human decision"
                ),
                "expected_state": "Every proposed pair resolved",
                "last_check": now.isoformat(),
                "owner": "ImpactAssessment",
                "recommended_action": (
                    "Review in the duplicate queue — detection proposes, "
                    "people decide; unresolved pairs distort portfolios "
                    "and targets."
                ),
                "resolution_link": "/data-quality/duplicates",
            }
        )
    if summary["overCapacityStaff"]:
        checks.append(
            {
                "key": "dq_over_capacity_staff",
                "severity": "warning",
                "component": "Portfolio capacity",
                "current_state": (
                    f"{summary['overCapacityStaff']} staff carrying more "
                    "direct schools than their governed capacity"
                ),
                "expected_state": (
                    "Portfolios within StaffSupportCapacity — overload is "
                    "surfaced for rebalancing, never for discipline"
                ),
                "last_check": now.isoformat(),
                "owner": "CountryDirector",
                "recommended_action": (
                    "Rebalance portfolios or adjust the governed capacity; "
                    "partner assignment is the overflow route."
                ),
                "resolution_link": "/staff",
            }
        )
    scan_recent = ScheduledJobExecution.objects.filter(
        job_name="data_quality_scan",
        status="success",
        started_at__gte=now - timedelta(hours=26),
    ).exists()
    if not scan_recent:
        checks.append(
            {
                "key": "dq_scan_stale",
                "severity": "warning",
                "component": "Data-quality scan",
                "current_state": "No successful scan in 26h",
                "expected_state": "Nightly scan at 03:00",
                "last_check": now.isoformat(),
                "owner": "Admin",
                "recommended_action": (
                    "Check the data_quality_scan job in scheduler health."
                ),
                "resolution_link": "/system-health",
            }
        )
    return {"checks": checks, "summary": summary}
