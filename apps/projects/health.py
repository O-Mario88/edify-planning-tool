"""Project-priority and School portfolio integrity checks."""

from django.db.models import Count, Q
from django.utils import timezone

from apps.schools.models import School

from .models import (
    OPEN_PROJECT_STATUSES,
    ProjectSchoolAssignment,
    ProjectStaffAssignment,
)


def project_priority_health() -> dict:
    open_statuses = [status.value for status in OPEN_PROJECT_STATUSES]
    active_assignment_filter = Q(
        project_assignments__project__deleted_at__isnull=True,
        project_assignments__project__status__in=open_statuses,
    )
    client_overallocated = (
        School.objects.exclude(school_type="core")
        .annotate(
            active_projects=Count(
                "project_assignments",
                filter=active_assignment_filter,
            )
        )
        .filter(active_projects__gt=1)
    )
    core_overallocated = (
        School.objects.filter(school_type="core")
        .annotate(
            active_projects=Count(
                "project_assignments",
                filter=active_assignment_filter,
            )
        )
        .filter(active_projects__gt=4)
    )
    core_focus_mismatch = ProjectSchoolAssignment.objects.filter(
        project__school_focus="core",
    ).exclude(school__school_type="core")
    client_focus_mismatch = ProjectSchoolAssignment.objects.filter(
        project__school_focus="client",
        school__school_type="core",
    )
    stale_staff_priority = ProjectStaffAssignment.objects.filter(
        is_active=True,
    ).filter(
        Q(project__deleted_at__isnull=False) | ~Q(project__status__in=open_statuses)
    )
    checks = [
        (
            "project_client_school_capacity",
            "Client Schools assigned to more than one active Project",
            client_overallocated,
        ),
        (
            "project_core_school_capacity",
            "Core Schools assigned to more than four active Projects",
            core_overallocated,
        ),
        (
            "project_core_focus",
            "Non-Core Schools assigned to a Core-only Project",
            core_focus_mismatch,
        ),
        (
            "project_client_focus",
            "Core Schools assigned to a Client-only Project",
            client_focus_mismatch,
        ),
        (
            "project_staff_priority_lifecycle",
            "Active staff priorities linked to paused, closed, or deleted Projects",
            stale_staff_priority,
        ),
    ]
    detected_at = timezone.now().isoformat()
    payload = []
    for key, label, queryset in checks:
        count = queryset.count()
        payload.append(
            {
                "key": key,
                "label": label,
                "count": count,
                "status": "pass" if count == 0 else "fail",
                "severity": "none" if count == 0 else "critical",
                "expected": "0 unresolved issues",
                "actual": count,
                "owner": (
                    None
                    if count == 0
                    else "Impact Assessment / Country Director / Admin"
                ),
                "directCorrectionAction": (None if count == 0 else "/projects"),
                "detectedAt": detected_at,
                "resolutionStatus": "resolved" if count == 0 else "open",
                "auditHistory": "Audit Log",
            }
        )
    return {
        "healthy": all(check["status"] == "pass" for check in payload),
        "checks": payload,
    }


__all__ = ["project_priority_health"]
