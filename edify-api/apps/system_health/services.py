"""System health — org-wide health counts (CD/IA/Admin oversight)."""
from __future__ import annotations

from apps.core.fy import get_operational_fy
from apps.schools.models import School


def report() -> dict:
    fy = get_operational_fy()
    schools = School.objects.filter(deleted_at__isnull=True)
    return {
        "fy": fy,
        "schoolsTotal": schools.count(),
        "bySchoolType": {
            t: schools.filter(school_type=t).count()
            for t in ("client", "core", "champion")
        },
        "ssaDone": schools.filter(current_fy_ssa_status="done").count(),
        "ssaMissing": schools.exclude(current_fy_ssa_status="done").count(),
        "clustered": schools.filter(cluster_status="clustered").count(),
        "unclustered": schools.filter(cluster_status="unclustered").count(),
        "planningReady": schools.filter(planning_readiness="ready").count(),
    }
