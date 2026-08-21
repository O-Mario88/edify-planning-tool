"""Integrity checks for the strategic-priority and milestone cascade."""

from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    MilestoneAllocation,
    MilestoneProgressCredit,
    PriorityMilestone,
    StrategicPriority,
)


def priority_health() -> dict:
    no_milestones = (
        StrategicPriority.objects.filter(cycle__isnull=False)
        .annotate(milestone_count=Count("milestones"))
        .filter(milestone_count=0)
    )
    active_undefined = PriorityMilestone.objects.filter(active=True).filter(
        Q(requires_definition=True)
        | ~Q(definition_status="approved")
        | Q(metric_definition__isnull=True)
    )
    automatic_without_source = (
        PriorityMilestone.objects.filter(
            active=True,
        )
        .exclude(progress_source__in=["manual_evidence", "needs_definition"])
        .filter(
            Q(metric_definition__isnull=True)
            | Q(metric_definition__canonical_service="")
        )
    )
    activity_without_rule = (
        PriorityMilestone.objects.filter(
            active=True,
            progress_source__in=["activity", "activity_catalogue"],
        )
        .annotate(
            rule_count=Count("activity_rules", filter=Q(activity_rules__active=True))
        )
        .filter(rule_count=0)
    )
    duplicate_credit = (
        MilestoneProgressCredit.objects.filter(reversed_at__isnull=True)
        .values("rule_id", "activity_id")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )
    approved_without_periods = (
        MilestoneAllocation.objects.filter(status="approved")
        .annotate(period_count=Count("period_targets"))
        .filter(period_count=0)
    )
    missing_ide = PriorityMilestone.objects.filter(code="IDE").exclude(
        activity_rules__active=True
    )
    checks = [
        ("priority_without_milestone", "Priority without milestone", no_milestones),
        (
            "active_undefined_milestone",
            "Active milestone still Needs Definition",
            active_undefined,
        ),
        (
            "automatic_without_source",
            "Automatic milestone without a canonical source",
            automatic_without_source,
        ),
        (
            "activity_without_catalogue_rule",
            "Activity milestone without a Catalogue rule",
            activity_without_rule,
        ),
        (
            "duplicate_milestone_credit",
            "Duplicate milestone progress credit",
            duplicate_credit,
        ),
        (
            "allocation_without_period_targets",
            "Approved allocation missing period targets",
            approved_without_periods,
        ),
    ]
    payload = [
        {
            "key": key,
            "label": label,
            "count": qs.count(),
            "status": "pass" if not qs.exists() else "fail",
        }
        for key, label, qs in checks
    ]
    payload.append(
        {
            "key": "missing_ide_catalogue_mapping",
            "label": "IDE milestone awaiting an approved Catalogue mapping",
            "count": missing_ide.count(),
            "status": "warn" if missing_ide.exists() else "pass",
        }
    )
    detected_at = timezone.now().isoformat()
    for row in payload:
        row.update(
            {
                "severity": (
                    "critical"
                    if row["status"] == "fail"
                    else "warning"
                    if row["status"] == "warn"
                    else "none"
                ),
                "expected": "0 unresolved issues",
                "actual": row["count"],
                "owner": (
                    "RVP / Country Director" if row["status"] != "pass" else None
                ),
                "directCorrectionAction": (
                    "/strategic-priorities" if row["status"] != "pass" else None
                ),
                "detectedAt": detected_at,
                "resolutionStatus": ("open" if row["status"] != "pass" else "resolved"),
                "auditHistory": "Audit Log",
            }
        )
    return {
        "healthy": all(row["status"] != "fail" for row in payload),
        "checks": payload,
    }
