"""My-plan — the caller's own plan feed (week/month/quarter/fy)."""
from __future__ import annotations

from apps.activities.models import Activity
from apps.core.fy import get_operational_fy, get_month_date_range
from apps.core.scoping import resolve_user_scope


def get(principal, query: dict) -> dict:
    period = query.get("period", "month")
    fy = query.get("fy") or get_operational_fy()
    scope = resolve_user_scope(principal)
    qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
    if scope.staff_ids:
        qs = qs.filter(responsible_staff_id__in=scope.staff_ids)
    elif scope.partner_ids:
        qs = qs.filter(assigned_partner_id__in=scope.partner_ids)
    else:
        qs = qs.none()

    items = [
        {
            "id": a.id,
            "activityType": a.activity_type,
            "status": a.status,
            "scheduledDate": a.scheduled_date.isoformat() if a.scheduled_date else None,
            "schoolId": a.school.school_id if a.school_id else None,
            "month": a.planned_month,
            "week": a.planned_week,
        }
        for a in qs.select_related("school").order_by("planned_month", "planned_week")
    ]
    return {
        "period": period,
        "fy": fy,
        "items": items,
        "total": len(items),
    }
