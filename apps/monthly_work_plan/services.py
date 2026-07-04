"""Monthly work-plan service — CD→RVP budget routing."""
from __future__ import annotations

from django.utils import timezone

from apps.core.exceptions import NotFoundError

from .models import AdminBudgetLine, MonthlyWorkPlanBudget, MonthlyWorkPlanBudgetStatus


def list_budgets(query: dict) -> list[dict]:
    qs = MonthlyWorkPlanBudget.objects.all().order_by("-month_key")
    if query.get("fy"):
        qs = qs.filter(fy=query["fy"])
    return [_serialize(b) for b in qs]


def get_one(budget_id: str) -> dict:
    b = MonthlyWorkPlanBudget.objects.filter(id=budget_id).first()
    if not b:
        raise NotFoundError("Monthly work-plan budget not found.")
    data = _serialize(b)
    data["adminLines"] = [_serialize_line(l) for l in b.admin_lines.all()]
    return data


def add_admin_line(budget_id: str, data: dict, principal) -> dict:
    b = MonthlyWorkPlanBudget.objects.filter(id=budget_id).first()
    if not b:
        raise NotFoundError("Monthly work-plan budget not found.")
    # Integer-cents money: unit_cost is whole UGX; quantity may be fractional
    # (e.g. 1.5 days). total_cost = round(unit_cost × quantity) in UGX.
    unit = int(data.get("unitCost", 0))
    qty = data.get("quantity", 1)
    from decimal import Decimal

    qty_dec = Decimal(str(qty))
    total = int((qty_dec * unit).to_integral_value())
    line = AdminBudgetLine.objects.create(
        monthly_budget=b,
        cost_category=data.get("costCategory", "other"),
        description=data.get("description", ""),
        quantity=qty_dec, unit_cost=unit, total_cost=total,
        justification=data.get("justification"),
        created_by_user_id=principal.user_id,
    )
    recompute_totals(b)
    return _serialize_line(line)


def remove_admin_line(budget_id: str, line_id: str, principal) -> dict:
    line = AdminBudgetLine.objects.filter(id=line_id, monthly_budget_id=budget_id).first()
    if line:
        b = line.monthly_budget
        line.delete()
        recompute_totals(b)
    return {"ok": True}


def recompute_totals(b: MonthlyWorkPlanBudget) -> MonthlyWorkPlanBudget:
    """Recompute admin_total + total_amount from the admin lines. program_total is
    the auto-aggregated activity-budget-line sum (set by recompute_program_total)."""
    from django.db.models import Sum

    agg = b.admin_lines.aggregate(total=Sum("total_cost"))["total"] or 0
    b.admin_total = int(agg)
    b.total_amount = (b.program_total or 0) + b.admin_total
    b.save(update_fields=["admin_total", "total_amount"])
    return b


def recompute_program_total(b: MonthlyWorkPlanBudget) -> MonthlyWorkPlanBudget:
    """Sum the persisted ActivityScheduleCostLine amounts for the budget's month
    (the auto-generated program portion). The month_key is 'YYYY-MM'."""
    from apps.activities.models import ActivityScheduleCostLine
    from django.db.models import Sum

    try:
        year, month = b.month_key.split("-")
        year_i, month_i = int(year), int(month)
    except (ValueError, AttributeError):
        return b
    program = ActivityScheduleCostLine.objects.filter(
        activity__deleted_at__isnull=True,
        activity__fy=b.fy,
        activity__planned_month=month_i,
    ).aggregate(total=Sum("amount"))["total"] or 0
    b.program_total = int(program)
    b.activity_count = (
        ActivityScheduleCostLine.objects.filter(
            activity__deleted_at__isnull=True,
            activity__fy=b.fy,
            activity__planned_month=month_i,
        ).values("activity").distinct().count()
    )
    b.total_amount = b.program_total + (b.admin_total or 0)
    b.save(update_fields=["program_total", "activity_count", "total_amount"])
    return b


def submit_to_rvp(budget_id: str, principal) -> dict:
    return _transition(budget_id, MonthlyWorkPlanBudgetStatus.SUBMITTED_TO_RVP, principal, field="submitted_at", actor_field="submitted_by_user_id")


def rvp_approve(budget_id: str, data: dict, principal) -> dict:
    return _transition(budget_id, MonthlyWorkPlanBudgetStatus.APPROVED_BY_RVP, principal, field="rvp_reviewed_at", actor_field="rvp_reviewed_by_user_id")


def rvp_return(budget_id: str, data: dict, principal) -> dict:
    b = _transition(budget_id, MonthlyWorkPlanBudgetStatus.RETURNED_BY_RVP, principal, field="rvp_reviewed_at", actor_field="rvp_reviewed_by_user_id")
    b.rvp_review_note = data.get("note")
    b.save(update_fields=["rvp_review_note"])
    return _serialize(b)


def mark_sent_to_accountant(budget_id: str, principal) -> dict:
    return _transition(budget_id, MonthlyWorkPlanBudgetStatus.SENT_TO_ACCOUNTANT, principal, field="sent_to_accountant_at")


def _transition(budget_id: str, status: str, principal, *, field: str | None = None, actor_field: str | None = None) -> MonthlyWorkPlanBudget:
    b = MonthlyWorkPlanBudget.objects.filter(id=budget_id).first()
    if not b:
        raise NotFoundError("Monthly work-plan budget not found.")
    b.status = status
    now = timezone.now()
    if field:
        setattr(b, field, now)
    if actor_field:
        setattr(b, actor_field, principal.user_id)
    b.save()
    return b


def _serialize(b: MonthlyWorkPlanBudget) -> dict:
    return {
        "id": b.id, "fy": b.fy, "monthKey": b.month_key,
        "status": b.status, "programTotal": b.program_total,
        "adminTotal": b.admin_total, "totalAmount": b.total_amount,
        "activityCount": b.activity_count,
        "submittedAt": b.submitted_at.isoformat() if b.submitted_at else None,
        "rvpReviewedAt": b.rvp_reviewed_at.isoformat() if b.rvp_reviewed_at else None,
    }


def _serialize_line(l: AdminBudgetLine) -> dict:
    return {
        "id": l.id, "costCategory": l.cost_category, "description": l.description,
        "quantity": l.quantity, "unitCost": l.unit_cost, "totalCost": l.total_cost,
        "justification": l.justification,
    }
