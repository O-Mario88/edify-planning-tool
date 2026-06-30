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
        w_val = query.get("week")
        m_val = query.get("month")
        if w_val:
            qs = qs.filter(planned_week=int(w_val))
        if m_val:
            qs = qs.filter(planned_month=int(m_val))
    elif period == "month":
        m_val = query.get("month")
        if m_val:
            qs = qs.filter(planned_month=int(m_val))
    elif period == "quarter":
        q_val = query.get("quarter")
        if q_val:
            qs = qs.filter(quarter=q_val)
    # period == "fy" (or unknown) → whole fiscal year.

    items = []
    for a in qs.select_related("school", "cluster").order_by("planned_month", "planned_week"):
        items.append({
            "id": a.id,
            "activityType": a.activity_type,
            "status": a.status,
            "scheduledDate": a.scheduled_date.isoformat() if a.scheduled_date else None,
            "schoolId": a.school.school_id if a.school else None,
            "schoolName": a.school.name if a.school else None,
            "school": {
                "id": a.school.id,
                "schoolId": a.school.school_id,
                "name": a.school.name,
            } if a.school else None,
            "clusterId": a.cluster_id,
            "cluster": {
                "id": a.cluster.id,
                "name": a.cluster.name,
            } if a.cluster else None,
            "fy": a.fy,
            "quarter": a.quarter,
            "plannedMonth": a.planned_month,
            "plannedWeek": a.planned_week,
            "month": a.planned_month,
            "week": a.planned_week,
            "responsibleStaffId": a.responsible_staff_id,
            "assignedPartnerId": a.assigned_partner_id,
            "deliveryType": a.delivery_type,
            "evidenceStatus": a.evidence_status,
            "paymentStatus": a.payment_status,
            "salesforceActivityId": a.salesforce_activity_id,
            "rescheduleCount": a.reschedule_count,
            "lastReason": a.last_reason,
            "estCostCents": a.est_cost_cents,
            "costCents": a.est_cost_cents,
            "costMissing": a.cost_missing,
        })
    
    total_cost = sum(i["estCostCents"] for i in items)
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
