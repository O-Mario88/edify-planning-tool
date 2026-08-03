"""Work Plan / programme-activity integrity checks (§35).

Every planned amount must trace to a dated, owned, rationalized plan. These
checks look for the specific ways a non-school programme activity could break
that promise. The Calendar and Work Plan are projections of the same Activity
queryset, so "missing from calendar/work plan" reduces to the queryset
invariants below (an activity with a date and an owner in a live status IS in
both projections by construction).
"""

from __future__ import annotations

from django.db.models import F, Q, Sum
from django.utils import timezone

from apps.activities.models import Activity

LIVE_STATUSES_Q = ~Q(status__in=("cancelled", "rejected", "deferred", "not_planned"))


def work_plan_health() -> dict:
    # Non-school programme work is identified by its PLANNING SOURCE (§1/§2),
    # not by a single activity type: the governed catalogue delivers camps and
    # conferences under workflow kind "training", and they are still Work Plan
    # activities that must be dated, owned and rationalized.
    programme = Activity.objects.filter(
        deleted_at__isnull=True, planning_source="manual_work_plan"
    ).filter(LIVE_STATUSES_Q)

    without_rationale = programme.filter(support_rationale="")
    without_date = programme.filter(planned_date__isnull=True)
    end_before_start = Activity.objects.filter(
        deleted_at__isnull=True,
        end_date__isnull=False,
        planned_date__isnull=False,
        end_date__lt=F("planned_date"),
    )
    without_owner = programme.filter(
        delivery_type="staff",
    ).filter(Q(responsible_staff_id__isnull=True) | Q(responsible_staff_id=""))
    # Planning provenance is an absolute gate for both cost-free drafts and
    # scheduled work. Treating an unstamped planned row as acceptable merely
    # postpones discovery until the row starts carrying money.
    unstamped_source = Activity.objects.filter(
        deleted_at__isnull=True,
        planning_source="",
    ).filter(LIVE_STATUSES_Q)
    # A multi-day activity that crosses a month boundary must have allocated
    # its cost lines into more than one month (§9); all-in-one-month lines on
    # a cross-month range means the allocation rule was bypassed.
    cross_month = programme.filter(
        end_date__isnull=False, planned_date__isnull=False
    ).exclude(
        end_date__month=F("planned_date__month"),
        end_date__year=F("planned_date__year"),
    )
    misallocated = [
        a.id
        for a in cross_month.annotate(total=Sum("schedule_cost_lines__amount"))
        if a.total
        and a.schedule_cost_lines.values("month", "fiscal_year").distinct().count() < 2
    ]

    checks = [
        {
            "key": "programme_activity_without_rationale",
            "label": "Programme activities without a strategic rationale",
            "status": "pass" if not without_rationale.exists() else "fail",
            "count": without_rationale.count(),
        },
        {
            "key": "programme_activity_without_date",
            "label": "Programme activities without a planned date",
            "status": "pass" if not without_date.exists() else "fail",
            "count": without_date.count(),
        },
        {
            "key": "activity_end_before_start",
            "label": "Activities whose end date precedes their start date",
            "status": "pass" if not end_before_start.exists() else "fail",
            "count": end_before_start.count(),
        },
        {
            "key": "programme_activity_without_owner",
            "label": "Staff programme activities without a responsible person",
            "status": "pass" if not without_owner.exists() else "fail",
            "count": without_owner.count(),
        },
        {
            "key": "activity_without_planning_source",
            "label": "Live activities without a planning source stamp",
            "status": "pass" if not unstamped_source.exists() else "fail",
            "count": unstamped_source.count(),
        },
        {
            "key": "cross_month_cost_not_allocated",
            "label": "Cross-month programme cost not allocated per month",
            "status": "pass" if not misallocated else "fail",
            "count": len(misallocated),
        },
    ]

    detected_at = timezone.now().isoformat()
    for check in checks:
        check.update(
            {
                "severity": (
                    "critical"
                    if check["status"] == "fail"
                    else "warning"
                    if check["status"] == "warn"
                    else "none"
                ),
                "expected": "0 unresolved issues",
                "actual": check["count"],
                "owner": (
                    "Program Lead / Country Director"
                    if check["status"] != "pass"
                    else None
                ),
                "directCorrectionAction": (
                    "/work-plan" if check["status"] != "pass" else None
                ),
                "detectedAt": detected_at,
                "resolutionStatus": "open" if check["status"] != "pass" else "resolved",
                "auditHistory": "Audit Log",
            }
        )
    return {
        "healthy": all(check["status"] != "fail" for check in checks),
        "checks": checks,
    }
