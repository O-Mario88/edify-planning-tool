"""CD → RVP approval for the annual Work Plan.

The approval envelope is the existing CountryAnnualBudget: it already owns
the annual baseline lock, immutable RVP decision audit, and notifications.
This module only refreshes that envelope from canonical Activity cost lines
before submission; it does not create a second plan or costing ledger.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q, Sum

from apps.activities.models import Activity
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.rbac import EdifyRole


EXCLUDED_STATUSES = ("cancelled", "rejected", "deferred")
FY_MONTH_ORDER = (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9)


def _plan_queryset(fy: str):
    return Activity.objects.filter(
        deleted_at__isnull=True,
        fy=fy,
    ).exclude(status__in=EXCLUDED_STATUSES)


def readiness_issues(fy: str) -> list[str]:
    qs = _plan_queryset(fy)
    if not qs.exists():
        return ["Add at least one Activity before submitting the Work Plan."]
    issues: list[str] = []
    if qs.filter(planned_date__isnull=True, scheduled_date__isnull=True).exists():
        issues.append("Every Activity must have a planned date.")
    if qs.filter(
        Q(delivery_type="staff", responsible_staff_id__isnull=True)
        | Q(delivery_type="staff", responsible_staff_id="")
        | Q(delivery_type="partner", assigned_partner_id__isnull=True)
        | Q(delivery_type="partner", assigned_partner_id="")
    ).exists():
        issues.append("Every Activity must have a responsible Staff member or Partner.")
    if qs.filter(cost_missing=True).exists():
        issues.append(
            "Resolve all missing CD Cost Catalogue rates before submission."
        )
    return issues


def approval_context(user, fy: str) -> dict:
    from apps.monthly_work_plan.models import (
        CountryAnnualBudget,
        CountryAnnualBudgetStatus,
    )
    from apps.monthly_work_plan.services import _rvp_country_scope

    budget = CountryAnnualBudget.objects.filter(
        fy=fy,
        country_id=_rvp_country_scope(),
    ).first()
    status = budget.status if budget else CountryAnnualBudgetStatus.DRAFT
    issues = readiness_issues(fy)
    return {
        "budget": budget,
        "status": status,
        "status_label": dict(CountryAnnualBudgetStatus.choices).get(status, "Draft"),
        "review_note": budget.rvp_review_note if budget else "",
        "submitted_at": budget.submitted_at if budget else None,
        "reviewed_at": budget.rvp_reviewed_at if budget else None,
        "issues": issues,
        "ready": not issues,
        "can_submit": (
            user.active_role == EdifyRole.COUNTRY_DIRECTOR.value
            and status
            in (
                CountryAnnualBudgetStatus.DRAFT,
                CountryAnnualBudgetStatus.RETURNED_BY_RVP,
            )
        ),
        "can_decide": (
            user.active_role == EdifyRole.REGIONAL_VICE_PRESIDENT.value
            and status == CountryAnnualBudgetStatus.SUBMITTED_TO_RVP
        ),
    }


@transaction.atomic
def submit_to_rvp(fy: str, principal):
    from apps.monthly_work_plan.models import (
        CountryAnnualBudget,
        CountryAnnualBudgetStatus,
    )
    from apps.monthly_work_plan.services import (
        _rvp_audit,
        _rvp_country_scope,
        _rvp_notify,
        submit_annual_to_rvp,
    )

    if principal.active_role != EdifyRole.COUNTRY_DIRECTOR.value:
        raise Forbidden("Only the Country Director can submit the Work Plan.")
    issues = readiness_issues(fy)
    if issues:
        raise BadRequest("Work Plan is not ready: " + " ".join(issues))

    activities = list(
        _plan_queryset(fy)
        .annotate(cost_total=Sum("schedule_cost_lines__amount"))
        .only(
            "id",
            "school_id",
            "cluster_id",
            "delivery_type",
            "programme_delivery_mode",
            "planned_school_count",
            "planned_date",
            "scheduled_date",
        )
    )
    monthly = {month: 0 for month in FY_MONTH_ORDER}
    from apps.activities.models import ActivityScheduleCostLine

    line_rows = ActivityScheduleCostLine.objects.filter(
        activity__in=activities
    ).values("month").annotate(total=Sum("amount"))
    for row in line_rows:
        if row["month"] in monthly:
            monthly[row["month"]] = int(row["total"] or 0)

    program_total = sum(monthly.values())
    school_ids = {a.school_id for a in activities if a.school_id}
    planned_programme_schools = sum(
        a.planned_school_count or 0 for a in activities if not a.school_id
    )
    country_id = _rvp_country_scope()
    budget, _ = CountryAnnualBudget.objects.select_for_update().get_or_create(
        country_id=country_id,
        fy=fy,
    )
    if budget.status == CountryAnnualBudgetStatus.APPROVED_BY_RVP:
        raise BadRequest(
            "This Work Plan is already approved and its annual baseline is locked."
        )
    budget.target_schools = len(school_ids) + planned_programme_schools
    budget.target_activities = len(activities)
    budget.planned_staff_visits = sum(
        1 for a in activities if a.delivery_type == "staff"
    )
    budget.planned_partner_visits = sum(
        1 for a in activities if a.delivery_type == "partner"
    )
    budget.cluster_activities = sum(
        1
        for a in activities
        if a.cluster_id or a.programme_delivery_mode == "cluster"
    )
    budget.program_total = program_total
    budget.total_amount = (
        program_total + (budget.admin_total or 0) + (budget.special_project_total or 0)
    )
    budget.monthly_phasing = [monthly[month] for month in FY_MONTH_ORDER]
    budget.quarterly_phasing = [
        sum(budget.monthly_phasing[offset : offset + 3])
        for offset in range(0, 12, 3)
    ]
    budget.rvp_review_note = ""
    budget.save()

    budget = submit_annual_to_rvp(budget.id, principal)
    _rvp_audit(
        "annual_work_plan",
        budget.id,
        f"Country Work Plan FY {fy}",
        "submit",
        principal,
        amount=budget.total_amount,
        fy=fy,
    )
    try:
        from apps.accounts.models import User

        for recipient_id in User.objects.filter(
            active_role=EdifyRole.REGIONAL_VICE_PRESIDENT.value,
            is_active=True,
        ).values_list("id", flat=True):
            _rvp_notify(
                recipient_id,
                f"FY {fy} Work Plan ready for approval",
                "The Country Director submitted the completed Work Plan.",
                f"/work-plan?fy={fy}&view=fy",
            )
    except Exception:  # noqa: BLE001 - notification must not roll back submission
        pass
    return budget
