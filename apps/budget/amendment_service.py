"""Budget Amendment lifecycle (§4.5) — the sanctioned change path for
finance-locked activities.

request → (accountant/CD review) → approve+apply | return | reject.

Apply moves the activity and its EXISTING cost lines to the new date/period
without the delete-recreate the snapshot lock forbids: line identity,
amounts, catalogue provenance and any linked AdvanceRequest survive intact —
only the period stamps move. Historical weekly requests are left untouched
(money already moved through them); live budget rollups recompute from the
lines' new period fields automatically.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy, get_quarter_for_date

from .models import BudgetAmendment, BudgetAmendmentStatus

REVIEWER_ROLES = ("Accountant", "CountryDirector", "Admin")


def _audit(principal, action: str, amendment: BudgetAmendment, payload: dict) -> None:
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action=action,
            subject_kind="BudgetAmendment",
            subject_id=amendment.id,
            actor_id=principal.user_id,
            actor_role=getattr(principal, "active_role", ""),
            success=True,
            payload={"activity_id": amendment.activity_id, **payload},
        )
    except Exception:  # pragma: no cover
        pass


def request_amendment(activity_id: str, data: dict, principal) -> BudgetAmendment:
    """Owner/staff requests a date/period change for a finance-locked activity."""
    from apps.activities.models import Activity
    from apps.activities.services import _assert_in_scope, _parse_date

    activity = Activity.objects.filter(id=activity_id, deleted_at__isnull=True).first()
    if not activity:
        raise NotFoundError("Activity not found.")
    _assert_in_scope(activity, principal)

    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BadRequest("An amendment requires a reason.")
    new_date = _parse_date(data["newDate"])

    # REG-02 — moving a locked activity's date is still scheduling; it must
    # respect the same Sunday/holiday/blackout/leave gate as every other
    # scheduling surface, checked here (at request time) so the requester
    # gets immediate feedback instead of a silent reviewer-side rejection.
    from apps.core.calendar_policy import (
        SchedulingPolicyService,
        resolve_scheduling_user,
    )

    check_staff_id = activity.responsible_staff_id or activity.monitored_by_staff_id
    resp_user = resolve_scheduling_user(check_staff_id) if check_staff_id else None
    avail = SchedulingPolicyService.check(resp_user, new_date)
    if avail["status"] == "blocked":
        raise BadRequest("Scheduling blocked: " + " · ".join(avail["blockers"]))

    if BudgetAmendment.objects.filter(
        activity=activity,
        status__in=[
            BudgetAmendmentStatus.SUBMITTED,
            BudgetAmendmentStatus.UNDER_REVIEW,
            BudgetAmendmentStatus.APPROVED,
        ],
    ).exists():
        raise BadRequest("An amendment for this activity is already in review.")

    original_amount = sum(line.amount for line in activity.schedule_cost_lines.all())
    amendment = BudgetAmendment.objects.create(
        activity=activity,
        original_date=activity.planned_date,
        new_date=new_date.date(),
        original_amount=original_amount,
        original_fy=activity.fy,
        original_quarter=activity.quarter,
        new_fy=get_operational_fy(new_date),
        new_quarter=get_quarter_for_date(new_date),
        reason=reason,
        requested_by=principal.user_id,
    )
    _audit(
        principal,
        "budget_amendment.submitted",
        amendment,
        {"new_date": amendment.new_date.isoformat(), "reason": reason},
    )
    try:
        from apps.accounts.models import User
        from apps.notifications.services import WorkflowNotificationService

        accountants = list(
            User.objects.filter(
                status="active",
                deleted_at__isnull=True,
                roles__contains=["Accountant"],
            ).values_list("id", flat=True)
        )
        if accountants:
            WorkflowNotificationService.trigger(
                event_type="budget_amendment_submitted",
                category="finance",
                priority="normal",
                title="Budget amendment awaiting review",
                body=f"A locked activity requests a move to {amendment.new_date}.",
                context_type="activity",
                context_id=activity.id,
                recipients=accountants,
            )
    except Exception:  # pragma: no cover
        pass
    return amendment


def _get_reviewable(amendment_id: str, principal) -> BudgetAmendment:
    amendment = (
        BudgetAmendment.objects.select_for_update().filter(id=amendment_id).first()
    )
    if not amendment:
        raise NotFoundError("Amendment not found.")
    if getattr(principal, "active_role", "") not in REVIEWER_ROLES:
        raise Forbidden("Only the Accountant, CD or Admin may review amendments.")
    if amendment.requested_by == principal.user_id:
        raise BadRequest("You cannot review your own amendment.")
    if amendment.status not in (
        BudgetAmendmentStatus.SUBMITTED,
        BudgetAmendmentStatus.UNDER_REVIEW,
    ):
        raise BadRequest(
            f"An amendment in status '{amendment.status}' can no longer be reviewed."
        )
    return amendment


def approve_amendment(amendment_id: str, data: dict, principal) -> BudgetAmendment:
    """Approve AND apply: move the activity + its existing cost lines to the
    new period. No line is deleted or re-created — the confirmed/disbursed
    snapshot and its advances survive with only period stamps changed."""
    from datetime import datetime, time, timedelta, timezone as dt_tz

    with transaction.atomic():
        amendment = _get_reviewable(amendment_id, principal)
        activity = amendment.activity

        new_day = amendment.new_date

        # REG-02 — re-check at apply time: calendar policy (e.g. a holiday
        # declared after the amendment was requested) may have changed since
        # request_amendment() first validated this date.
        from apps.core.calendar_policy import (
            SchedulingPolicyService,
            resolve_scheduling_user,
        )

        check_staff_id = activity.responsible_staff_id or activity.monitored_by_staff_id
        resp_user = resolve_scheduling_user(check_staff_id) if check_staff_id else None
        avail = SchedulingPolicyService.check(resp_user, new_day)
        if avail["status"] == "blocked":
            raise BadRequest(
                "Scheduling blocked: "
                + " · ".join(avail["blockers"])
                + " Ask the requester to submit a new amendment with a different date."
            )

        new_dt = datetime.combine(new_day, time(9, 0), tzinfo=dt_tz.utc)
        week_start = new_day - timedelta(days=new_day.weekday())
        week_end = week_start + timedelta(days=6)

        activity.scheduled_date = new_dt
        activity.planned_date = new_day
        activity.fy = amendment.new_fy or activity.fy
        activity.fiscal_year = amendment.new_fy or activity.fiscal_year
        activity.quarter = amendment.new_quarter or activity.quarter
        activity.month = new_day.month
        activity.week_start_date = week_start
        activity.week_end_date = week_end
        activity.save(
            update_fields=[
                "scheduled_date",
                "planned_date",
                "fy",
                "fiscal_year",
                "quarter",
                "month",
                "week_start_date",
                "week_end_date",
                "updated_at",
            ]
        )
        activity.schedule_cost_lines.update(
            planned_date=new_day,
            week_start_date=week_start,
            week_end_date=week_end,
            month=new_day.month,
            quarter=amendment.new_quarter or activity.quarter,
            fiscal_year=amendment.new_fy or activity.fy,
        )

        amendment.status = BudgetAmendmentStatus.APPLIED
        amendment.reviewed_by = principal.user_id
        amendment.review_note = data.get("note") or ""
        amendment.applied_at = timezone.now()
        amendment.save(
            update_fields=[
                "status",
                "reviewed_by",
                "review_note",
                "applied_at",
                "updated_at",
            ]
        )
    _audit(
        principal,
        "budget_amendment.applied",
        amendment,
        {"new_date": amendment.new_date.isoformat()},
    )
    return amendment


def return_amendment(amendment_id: str, data: dict, principal) -> BudgetAmendment:
    with transaction.atomic():
        amendment = _get_reviewable(amendment_id, principal)
        amendment.status = BudgetAmendmentStatus.RETURNED
        amendment.reviewed_by = principal.user_id
        amendment.review_note = data.get("note") or ""
        amendment.save(
            update_fields=["status", "reviewed_by", "review_note", "updated_at"]
        )
    _audit(principal, "budget_amendment.returned", amendment, {})
    return amendment


def reject_amendment(amendment_id: str, data: dict, principal) -> BudgetAmendment:
    with transaction.atomic():
        amendment = _get_reviewable(amendment_id, principal)
        amendment.status = BudgetAmendmentStatus.REJECTED
        amendment.reviewed_by = principal.user_id
        amendment.review_note = data.get("note") or ""
        amendment.save(
            update_fields=["status", "reviewed_by", "review_note", "updated_at"]
        )
    _audit(principal, "budget_amendment.rejected", amendment, {})
    return amendment
