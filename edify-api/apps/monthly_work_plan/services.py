"""Monthly work-plan service — CD→RVP budget routing."""
from __future__ import annotations

from django.utils import timezone

from apps.core.exceptions import BadRequest, NotFoundError

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
    unit = float(data.get("unitCost", 0))
    qty = float(data.get("quantity", 1))
    line = AdminBudgetLine.objects.create(
        monthly_budget=b,
        cost_category=data.get("costCategory", "other"),
        description=data.get("description", ""),
        quantity=qty, unit_cost=unit, total_cost=unit * qty,
        justification=data.get("justification"),
        created_by_user_id=principal.user_id,
    )
    b.admin_total = (b.admin_total or 0) + line.total_cost
    b.total_amount = (b.program_total or 0) + b.admin_total
    b.save(update_fields=["admin_total", "total_amount"])
    return _serialize_line(line)


def remove_admin_line(budget_id: str, line_id: str, principal) -> dict:
    line = AdminBudgetLine.objects.filter(id=line_id, monthly_budget_id=budget_id).first()
    if line:
        b = line.monthly_budget
        b.admin_total = max(0, (b.admin_total or 0) - line.total_cost)
        b.total_amount = (b.program_total or 0) + b.admin_total
        b.save(update_fields=["admin_total", "total_amount"])
        line.delete()
    return {"ok": True}


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
