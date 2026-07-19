"""Monthly work-plan service — CD→RVP budget routing."""

from __future__ import annotations

from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError

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
    data["adminLines"] = [_serialize_line(line) for line in b.admin_lines.all()]
    return data


def add_admin_line(budget_id: str, data: dict, principal) -> dict:
    b = MonthlyWorkPlanBudget.objects.filter(id=budget_id).first()
    if not b:
        raise NotFoundError("Monthly work-plan budget not found.")
    # Service-level callers used by scheduled/admin jobs may provide a narrow
    # principal stub with no role. Browser/API principals always have one and
    # must be a CD or Admin.
    role = getattr(principal, "active_role", None)
    if role is not None and role not in ("CountryDirector", "Admin"):
        raise Forbidden("Only the Country Director can add a country admin budget.")
    if b.status not in (
        MonthlyWorkPlanBudgetStatus.DRAFT_GENERATED,
        MonthlyWorkPlanBudgetStatus.CD_REVIEW,
        MonthlyWorkPlanBudgetStatus.ADMIN_PLAN_ADDED,
        MonthlyWorkPlanBudgetStatus.RETURNED_BY_RVP,
    ):
        raise BadRequest("This country budget is locked and can no longer be changed.")
    description = (data.get("description") or "").strip()
    if not description:
        raise BadRequest("Enter a clear description for the admin budget item.")
    # Integer-cents money: unit_cost is whole UGX; quantity may be fractional
    # (e.g. 1.5 days). total_cost = round(unit_cost × quantity) in UGX.
    try:
        unit = int(data.get("unitCost", 0))
    except (TypeError, ValueError) as exc:
        raise BadRequest("Unit cost must be a whole UGX amount.") from exc
    qty = data.get("quantity", 1)
    from decimal import Decimal

    try:
        qty_dec = Decimal(str(qty))
    except Exception as exc:  # noqa: BLE001 - normalize a form validation error
        raise BadRequest("Quantity must be a number.") from exc
    if unit < 0 or qty_dec <= 0:
        raise BadRequest("Unit cost and quantity must be greater than zero.")
    total = int((qty_dec * unit).to_integral_value())
    line = AdminBudgetLine.objects.create(
        monthly_budget=b,
        cost_category=(data.get("costCategory") or "other").strip() or "other",
        description=description,
        quantity=qty_dec,
        unit_cost=unit,
        total_cost=total,
        justification=data.get("justification"),
        created_by_user_id=principal.user_id,
    )
    recompute_totals(b)
    if b.status != MonthlyWorkPlanBudgetStatus.ADMIN_PLAN_ADDED:
        b.status = MonthlyWorkPlanBudgetStatus.ADMIN_PLAN_ADDED
        b.save(update_fields=["status", "updated_at"])
    return _serialize_line(line)


def remove_admin_line(budget_id: str, line_id: str, principal) -> dict:
    line = AdminBudgetLine.objects.filter(
        id=line_id, monthly_budget_id=budget_id
    ).first()
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
    (the auto-generated program portion). The month_key is 'YYYY-MM'.

    Filters on the cost LINE's own `month` field, not `Activity.planned_month`
    — the latter is never populated by the scheduling flow (activities carry
    their period on the cost line: month/quarter/fiscal_year/planned_date),
    so filtering on it silently zeroes this rollup."""
    from apps.activities.models import ActivityScheduleCostLine
    from django.db.models import Sum

    try:
        year, month = b.month_key.split("-")
        int(year)  # validate the year segment; only month_i is needed downstream
        month_i = int(month)
    except (ValueError, AttributeError):
        return b
    lines = ActivityScheduleCostLine.objects.filter(
        activity__deleted_at__isnull=True,
        activity__fy=b.fy,
        month=month_i,
    ).exclude(activity__status__in=["cancelled", "rejected"])
    program = lines.aggregate(total=Sum("amount"))["total"] or 0
    b.program_total = int(program)
    b.activity_count = lines.values("activity").distinct().count()
    b.total_amount = b.program_total + (b.admin_total or 0)
    b.save(update_fields=["program_total", "activity_count", "total_amount"])
    return b


def submit_to_rvp(budget_id: str, principal) -> dict:
    return _transition(
        budget_id,
        MonthlyWorkPlanBudgetStatus.SUBMITTED_TO_RVP,
        principal,
        field="submitted_at",
        actor_field="submitted_by_user_id",
    )


def _rvp_country_scope() -> str:
    """The operating country every budget row is tagged with.

    Canonical convention is the full country name ("Uganda") — the value
    every real write path uses (country_budget_service._get_or_create_budget,
    apps/realtime/jobs.py's monthly cron, apps/command_center's To-Do
    filters). The old "UG" code default silently mismatched all of those,
    making _assert_rvp_can_decide reject every real budget and the RVP
    dashboard's budget lists filter to nothing. A deployment overriding
    settings.COUNTRY_ID must use the full name too.
    """
    from django.conf import settings

    return getattr(settings, "COUNTRY_ID", "Uganda") or "Uganda"


def _assert_rvp_can_decide(b: MonthlyWorkPlanBudget) -> None:
    """§13 guards: the budget must belong to the RVP's country scope and must
    actually be sitting in the RVP queue — never approve a draft or an already
    decided budget."""
    if (b.country_id or _rvp_country_scope()) != _rvp_country_scope():
        raise Forbidden("This budget belongs to a country outside your region.")
    if b.status != MonthlyWorkPlanBudgetStatus.SUBMITTED_TO_RVP:
        raise BadRequest(
            f"Budget is '{b.get_status_display()}' — only budgets submitted to "
            "the RVP can be approved or returned."
        )


def _rvp_audit(
    decision_type,
    subject_id,
    subject_label,
    action,
    principal,
    reason="",
    amount=0,
    fy="",
):
    from apps.monthly_work_plan.models import RVPApprovalDecision

    RVPApprovalDecision.objects.create(
        decision_type=decision_type,
        subject_id=subject_id,
        subject_label=subject_label[:255],
        action=action,
        reason=(reason or "")[:512],
        decided_by=principal.user_id,
        amount=amount or 0,
        fy=fy or "",
    )


def _rvp_notify(recipient_id, title, body, route):
    try:
        from apps.notifications.models import Notification

        Notification.objects.create(
            recipient_id=recipient_id,
            title=title,
            body=body,
            category="country_budget",
            context_type="rvp_decision",
            target_route=route,
            action_label="Open",
            action_required=True,
            priority="high",
        )
    except Exception:  # noqa: BLE001 — notification is supportive, not blocking
        pass


def rvp_approve(budget_id: str, data: dict, principal) -> dict:
    b = MonthlyWorkPlanBudget.objects.filter(id=budget_id).first()
    if not b:
        raise NotFoundError("Monthly work-plan budget not found.")
    _assert_rvp_can_decide(b)
    b = _transition(
        budget_id,
        MonthlyWorkPlanBudgetStatus.APPROVED_BY_RVP,
        principal,
        field="rvp_reviewed_at",
        actor_field="rvp_reviewed_by_user_id",
    )
    _rvp_audit(
        "monthly_budget",
        b.id,
        f"Country Monthly Budget {b.month_key}",
        "approve",
        principal,
        amount=b.total_amount,
        fy=b.fy,
    )
    if b.submitted_by_user_id:
        _rvp_notify(
            b.submitted_by_user_id,
            "Monthly budget approved by RVP",
            f"The {b.month_key} country budget was approved — the "
            "Accountant can now receive the allocation.",
            "/country-budget",
        )
    return _serialize(b)


def rvp_return(budget_id: str, data: dict, principal) -> dict:
    note = (data.get("note") or "").strip()
    if not note:
        raise BadRequest("A return reason is required.")
    b = MonthlyWorkPlanBudget.objects.filter(id=budget_id).first()
    if not b:
        raise NotFoundError("Monthly work-plan budget not found.")
    _assert_rvp_can_decide(b)
    b = _transition(
        budget_id,
        MonthlyWorkPlanBudgetStatus.RETURNED_BY_RVP,
        principal,
        field="rvp_reviewed_at",
        actor_field="rvp_reviewed_by_user_id",
    )
    b.rvp_review_note = note
    b.save(update_fields=["rvp_review_note"])
    _rvp_audit(
        "monthly_budget",
        b.id,
        f"Country Monthly Budget {b.month_key}",
        "return",
        principal,
        reason=note,
        amount=b.total_amount,
        fy=b.fy,
    )
    if b.submitted_by_user_id:
        _rvp_notify(
            b.submitted_by_user_id,
            "Monthly budget returned by RVP",
            note,
            "/country-budget",
        )
    return _serialize(b)


# ── Country Annual Budget (§14) ──────────────────────────────────────────────
def submit_annual_to_rvp(budget_id: str, principal):
    from apps.monthly_work_plan.models import (
        CountryAnnualBudget,
        CountryAnnualBudgetStatus,
    )

    b = CountryAnnualBudget.objects.filter(id=budget_id).first()
    if not b:
        raise NotFoundError("Annual budget not found.")
    if b.status == CountryAnnualBudgetStatus.APPROVED_BY_RVP:
        raise BadRequest("Approved annual budget is locked.")
    b.status = CountryAnnualBudgetStatus.SUBMITTED_TO_RVP
    b.submitted_at = timezone.now()
    b.submitted_by_user_id = principal.user_id
    b.save(update_fields=["status", "submitted_at", "submitted_by_user_id"])
    return b


def rvp_annual_decide(budget_id: str, action: str, data: dict, principal):
    from apps.monthly_work_plan.models import (
        CountryAnnualBudget,
        CountryAnnualBudgetStatus,
    )

    b = CountryAnnualBudget.objects.filter(id=budget_id).first()
    if not b:
        raise NotFoundError("Annual budget not found.")
    if (b.country_id or _rvp_country_scope()) != _rvp_country_scope():
        raise Forbidden("This annual budget is outside your region.")
    if b.status != CountryAnnualBudgetStatus.SUBMITTED_TO_RVP:
        raise BadRequest("Only a submitted annual budget can be decided.")
    if action == "approve":
        b.status = CountryAnnualBudgetStatus.APPROVED_BY_RVP
        b.baseline_locked_at = timezone.now()  # baseline locked on approval
    elif action == "return":
        reason = (data.get("note") or "").strip()
        if not reason:
            raise BadRequest("A return reason is required.")
        b.status = CountryAnnualBudgetStatus.RETURNED_BY_RVP
        b.rvp_review_note = reason
    else:
        raise BadRequest("Unknown annual budget action.")
    b.rvp_reviewed_at = timezone.now()
    b.rvp_reviewed_by_user_id = principal.user_id
    b.save()
    _rvp_audit(
        "annual_budget",
        b.id,
        f"Country Annual Budget FY {b.fy}",
        action,
        principal,
        reason=b.rvp_review_note or "",
        amount=b.total_amount,
        fy=b.fy,
    )
    if b.submitted_by_user_id:
        _rvp_notify(
            b.submitted_by_user_id,
            f"Annual budget {'approved' if action == 'approve' else 'returned'} by RVP",
            b.rvp_review_note or "Annual baseline locked.",
            "/country-budget",
        )
    return b


def update_annual_budget(budget_id: str, data: dict, principal):
    """§21 — an approved annual baseline can never be edited silently: any
    reallocation requires the formal amendment cycle (RVP return → CD revises
    → resubmit → RVP approves)."""
    from apps.monthly_work_plan.models import (
        CountryAnnualBudget,
        CountryAnnualBudgetStatus,
    )

    b = CountryAnnualBudget.objects.filter(id=budget_id).first()
    if not b:
        raise NotFoundError("Annual budget not found.")
    if b.status == CountryAnnualBudgetStatus.APPROVED_BY_RVP:
        raise BadRequest(
            "Approved annual budget is locked — request a formal budget "
            "amendment (RVP return and resubmission) instead of editing it."
        )
    for field in (
        "program_total",
        "admin_total",
        "special_project_total",
        "target_schools",
        "target_activities",
        "expected_impact",
        "strategic_priorities",
    ):
        if field in data:
            setattr(b, field, data[field])
    b.total_amount = (
        (b.program_total or 0) + (b.admin_total or 0) + (b.special_project_total or 0)
    )
    b.save()
    return b


def create_strategy_note(data: dict, principal):
    """§23 — accountable executive guidance: note + CD notification; the CD
    To-Do derives live from open notes."""
    from apps.monthly_work_plan.models import StrategyNote

    instruction = (data.get("instruction") or "").strip()
    if not instruction:
        raise BadRequest("Strategy note instruction is required.")
    note = StrategyNote.objects.create(
        author_id=principal.user_id,
        priority_label=(data.get("priority") or "General")[:128],
        scope=(data.get("scope") or "Regional")[:128],
        instruction=instruction,
        expected_outcome=data.get("expected_outcome") or "",
        responsible_cd_id=data.get("responsible_cd_id") or None,
        deadline=data.get("deadline") or None,
        review_date=data.get("review_date") or None,
    )
    if note.responsible_cd_id:
        _rvp_notify(
            note.responsible_cd_id,
            "New strategic guidance from RVP",
            instruction[:300],
            "/dashboard",
        )
    _rvp_audit(
        "strategy_note",
        note.id,
        note.priority_label,
        "create",
        principal,
        reason=instruction[:512],
    )
    return note


def mark_sent_to_accountant(budget_id: str, principal) -> dict:
    return _transition(
        budget_id,
        MonthlyWorkPlanBudgetStatus.SENT_TO_ACCOUNTANT,
        principal,
        field="sent_to_accountant_at",
    )


def _transition(
    budget_id: str,
    status: str,
    principal,
    *,
    field: str | None = None,
    actor_field: str | None = None,
) -> MonthlyWorkPlanBudget:
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
        "id": b.id,
        "fy": b.fy,
        "monthKey": b.month_key,
        "status": b.status,
        "programTotal": b.program_total,
        "adminTotal": b.admin_total,
        "totalAmount": b.total_amount,
        "activityCount": b.activity_count,
        "submittedAt": b.submitted_at.isoformat() if b.submitted_at else None,
        "rvpReviewedAt": b.rvp_reviewed_at.isoformat() if b.rvp_reviewed_at else None,
    }


def _serialize_line(line: AdminBudgetLine) -> dict:
    return {
        "id": line.id,
        "costCategory": line.cost_category,
        "description": line.description,
        "quantity": line.quantity,
        "unitCost": line.unit_cost,
        "totalCost": line.total_cost,
        "justification": line.justification,
    }
