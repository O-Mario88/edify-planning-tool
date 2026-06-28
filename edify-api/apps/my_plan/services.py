"""My-plan — the caller's own plan feed (week/month/quarter/fy)."""
from __future__ import annotations

from apps.activities.models import Activity
from apps.core.fy import get_operational_fy, get_month_date_range
from apps.core.scoping import resolve_user_scope


def get(principal, query: dict) -> dict:
    """The caller's own plan feed. `period` narrows the window:
      • week    → planned_week (and optional month) in the FY
      • month   → planned_month in the FY
      • quarter → quarter in the FY
      • fy      → the whole fiscal year (no period narrowing)
    The scope (own staff id / partner id) is enforced first; period only narrows."""
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

    # Period narrowing (fy = no narrowing).
    if period == "week":
        if query.get("week"):
            qs = qs.filter(planned_week=int(query["week"]))
        if query.get("month"):
            qs = qs.filter(planned_month=int(query["month"]))
    elif period == "month":
        if query.get("month"):
            qs = qs.filter(planned_month=int(query["month"]))
    elif period == "quarter":
        if query.get("quarter"):
            qs = qs.filter(quarter=query["quarter"])
    # period == "fy" (or unknown) → whole fiscal year.

    items = [
        {
            "id": a.id,
            "activityType": a.activity_type,
            "status": a.status,
            "scheduledDate": a.scheduled_date.isoformat() if a.scheduled_date else None,
            "schoolId": a.school.school_id if a.school_id else None,
            "schoolName": a.school.name if a.school_id else None,
            "month": a.planned_month,
            "week": a.planned_week,
            "quarter": a.quarter,
            "costCents": a.est_cost_cents,
            "costMissing": a.cost_missing,
            "evidenceStatus": a.evidence_status,
        }
        for a in qs.select_related("school").order_by("planned_month", "planned_week")
    ]
    
    total_cost = sum(i["costCents"] for i in items)
    partner_planned = qs.filter(delivery_type="partner").count()
    
    return {
        "live": True,
        "period": period,
        "fy": fy,
        "currentKey": str(query.get("month") or ""),
        "summary": {
            "total": len(items),
            "costCents": total_cost,
            "partnerPlanned": partner_planned,
        },
        "groups": [],
        "items": items,
        "total": len(items),
    }
