from __future__ import annotations

import logging
from datetime import datetime, date, timedelta
from django.db import transaction
from django.utils import timezone
from django.db.models import Q

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy
from apps.core.scoping import resolve_user_scope
from .models import (
    MONEY_MOVED_ADVANCE_STATUSES,
    WeeklyFundRequest,
    WeeklyFundRequestLine,
)

logger = logging.getLogger("edify.weekly_fund_request")


def parse_date(d_str: str) -> date:
    if isinstance(d_str, (date, datetime)):
        return d_str.date() if isinstance(d_str, datetime) else d_str
    try:
        return datetime.strptime(d_str[:10], "%Y-%m-%d").date()
    except Exception as exc:
        raise BadRequest(f"Invalid date format: {d_str}") from exc


def generate_weekly_fund_request(
    responsible_user_id: str, week_start_date_str: str
) -> WeeklyFundRequest | None:
    """Generate or update the WeeklyFundRequest for a user and week start date.

    Finds all scheduled, non-cancelled activities for that week owned by the user,
    aggregates their budget lines, and writes/updates the WeeklyFundRequest."""
    week_start = parse_date(week_start_date_str)
    # Ensure it's a Monday to keep the database constraint stable
    week_start = week_start - timedelta(days=week_start.weekday())
    week_end = week_start + timedelta(days=6)

    # 1. Find all scheduled activities for the selected week that are not cancelled
    lines = (
        ActivityScheduleCostLine.objects.filter(
            responsible_user=responsible_user_id,
            planned_date__gte=week_start,
            planned_date__lte=week_end,
            activity__scheduled_date__isnull=False,
        )
        .exclude(activity__status="cancelled")
        .select_related("activity")
    )

    total_amount = sum(line.amount for line in lines)
    fy = get_operational_fy(week_start)

    with transaction.atomic():
        # Check if request already exists
        wfr = WeeklyFundRequest.objects.filter(
            responsible_user=responsible_user_id, week_start_date=week_start
        ).first()
        if not lines.exists():
            # If no lines exist, and there is a draft request, we delete it
            if wfr and wfr.status == "pending_responsible_confirmation":
                wfr.lines.all().delete()
                wfr.delete()
            return None

        # Once a request has left the draft state (submitted, approved,
        # confirmed for advance, self-funded, disbursed, ...), a later
        # schedule/reschedule that re-triggers this sync must NEVER silently
        # rewrite its amount or delete+rebuild its line items — that would
        # let a newly-scheduled activity mutate a figure someone already
        # approved or a payment already disbursed against. This function now
        # fires automatically on every activity schedule (no manual "Generate
        # Request" step), so this guard is the difference between "auto"
        # meaning convenient and "auto" meaning finance-unsafe.
        if wfr and wfr.status != "pending_responsible_confirmation":
            return wfr

        if wfr:
            wfr.total_amount = total_amount
            wfr.save(update_fields=["total_amount", "updated_at"])
        else:
            wfr = WeeklyFundRequest.objects.create(
                fy=fy,
                week_start_date=week_start,
                week_end_date=week_end,
                responsible_user=responsible_user_id,
                total_amount=total_amount,
                status="pending_responsible_confirmation",
            )

        # Sync lines
        wfr.lines.all().delete()
        WeeklyFundRequestLine.objects.bulk_create(
            [
                WeeklyFundRequestLine(
                    weekly_fund_request=wfr,
                    activity_budget_line=line,
                    line_item_type=line.line_item_type or "other",
                    description=line.label,
                    quantity=line.quantity,
                    unit_cost=line.unit_cost,
                    total_cost=line.amount,
                    currency=line.currency,
                )
                for line in lines
            ]
        )

    return wfr


def trigger_generate_for_activity(
    activity: Activity, responsible_user_id: str | None = None
) -> None:
    """Convenience helper to auto-trigger weekly request generation on activity schedule/reschedule.

    responsible_user_id must be the SAME identifier stamped onto the activity's
    cost lines (User.id). Activity.responsible_staff_id may hold a StaffProfile
    id instead, in which case the generator's line filter matches nothing and
    the weekly request silently never materialises — so callers that know the
    scheduling principal should pass it explicitly.
    """
    owner = responsible_user_id or activity.responsible_staff_id
    if activity.scheduled_date and owner and activity.status != "cancelled":
        planned_date = activity.scheduled_date.date()
        week_start = planned_date - timedelta(days=planned_date.weekday())
        generate_weekly_fund_request(owner, week_start.isoformat())


def list_weekly_requests(query: dict, principal) -> list[dict]:
    """Retrieve a list of weekly fund requests scoped by user permissions."""
    scope = resolve_user_scope(principal)
    qs = WeeklyFundRequest.objects.all().order_by("-week_start_date")

    # If accountant or has payment permissions, they see everything ready for disbursement
    if query.get("status"):
        qs = qs.filter(status=query["status"])

    # Scope checks:
    if not scope.country_scope and scope.staff_ids:
        q = Q(responsible_user=principal.user_id)
        if scope.supervised_staff_ids:
            from apps.accounts.models import StaffProfile

            supervised_user_ids = StaffProfile.objects.filter(
                id__in=scope.supervised_staff_ids,
            ).values_list("user_id", flat=True)
            q |= Q(responsible_user__in=supervised_user_ids)
        qs = qs.filter(q)

    return [_serialize_request(r) for r in qs]


def get_weekly_request(request_id: str, principal) -> dict:
    """Retrieve details and itemized lines of a single WeeklyFundRequest."""
    wfr = WeeklyFundRequest.objects.filter(id=request_id).first()
    if not wfr:
        raise NotFoundError("Weekly fund request not found.")

    # Authorization check
    scope = resolve_user_scope(principal)
    if not scope.country_scope and wfr.responsible_user != principal.user_id:
        if scope.supervised_staff_ids:
            from apps.accounts.models import StaffProfile

            supervised_user_ids = StaffProfile.objects.filter(
                id__in=scope.supervised_staff_ids,
            ).values_list("user_id", flat=True)
            if wfr.responsible_user not in supervised_user_ids:
                raise Forbidden("You are not authorized to view this request.")
        else:
            raise Forbidden("You are not authorized to view this request.")

    return _serialize_request(wfr, include_lines=True)


# Approval routing by the OWNER's role — the mandate's finance law: a CCEO's
# weekly request is approved by their Program Lead; a PL's own field-work
# request is approved by the Country Director (a PL never self-approves);
# Project Coordinator / IA / Accountant requests route to the CD as well.
# CD/Admin-owned requests (rare) carry country authority already and go
# straight to the accountant queue.
_ROUTE_TO_PL = ("CCEO",)
_ROUTE_TO_CD = ("Program Lead", "ProjectCoordinator", "ImpactAssessment", "Accountant")
_ROUTE_DIRECT = ("CountryDirector", "Admin")


def _owner_role(wfr: WeeklyFundRequest) -> str:
    """The request owner's role, for approval routing. Prefers the role
    stamped on the request, else the owner User's active role."""
    if wfr.responsible_role:
        return wfr.responsible_role
    from apps.accounts.models import User

    owner = User.objects.filter(id=wfr.responsible_user).first()
    if not owner:
        return "CCEO"
    role = owner.active_role or ""
    if role:
        return role
    return (owner.roles or ["CCEO"])[0]


def _submission_status_for(owner_role: str) -> str:
    if owner_role in _ROUTE_TO_PL:
        return "submitted_to_pl"
    if owner_role in _ROUTE_DIRECT:
        return "confirmed_for_advance"
    return "submitted_to_cd"


def _sync_advances(wfr: WeeklyFundRequest, status: str, advance_type: str) -> None:
    now = timezone.now()
    for line in wfr.lines.select_related("activity_budget_line"):
        adv = line.activity_budget_line.advance_requests.first()
        if adv:
            adv.status = status
            adv.advance_type = advance_type
            adv.confirmed_at = now
            adv.save(
                update_fields=["status", "advance_type", "confirmed_at", "updated_at"]
            )


def request_advance(request_id: str, principal) -> dict:
    """The responsible user submits the weekly request for approval.

    Routing (owner's role, not the caller's): CCEO -> submitted_to_pl,
    PL/PC/IA/Accountant -> submitted_to_cd, CD/Admin -> straight to
    confirmed_for_advance. Only an APPROVED request reaches the accountant
    queue — submission alone never does."""
    with transaction.atomic():
        wfr = (
            WeeklyFundRequest.objects.select_for_update().filter(id=request_id).first()
        )
        if not wfr:
            raise NotFoundError("Weekly fund request not found.")
        if wfr.responsible_user != principal.user_id and not getattr(
            principal, "country_scope", False
        ):
            raise Forbidden("Only the owner can confirm this request.")
        if wfr.status not in (
            "pending_responsible_confirmation",
            "not_requested",
            # A returned request is corrected and re-submitted — without these
            # the returned_* statuses are dead ends with no way back.
            "returned_by_pl",
            "returned_by_cd",
            "returned_by_accountant",
        ):
            raise BadRequest(f"Cannot request advance in status '{wfr.status}'.")

        owner_role = _owner_role(wfr)
        wfr.status = _submission_status_for(owner_role)
        wfr.responsible_role = owner_role
        wfr.confirmed_at = timezone.now()
        wfr.save(
            update_fields=["status", "responsible_role", "confirmed_at", "updated_at"]
        )

        if wfr.status == "confirmed_for_advance":
            _sync_advances(wfr, "confirmed_for_advance", "advance")
        else:
            # Confirmed by the owner but not yet approved — the child advances
            # stay pending so the accountant's advance queue cannot see them
            # before the approval lands.
            _sync_advances(wfr, "pending_responsible_confirmation", "advance")

    _audit_weekly(principal, "weekly_fund_request.submit", wfr, {"routed": wfr.status})
    _notify_weekly_approver(wfr)
    return _serialize_request(wfr)


def _require_weekly_approver(wfr: WeeklyFundRequest, principal) -> str:
    """Validate that the caller may approve/return this request at its current
    stage. Returns the stage ('pl' or 'cd'). A user can never approve their
    own request, whatever their role."""
    if wfr.status not in ("submitted_to_pl", "submitted_to_cd"):
        raise BadRequest(f"Request is not awaiting approval (status '{wfr.status}').")
    if wfr.responsible_user == principal.user_id:
        raise Forbidden("You cannot approve your own fund request.")

    role = getattr(principal, "active_role", "")
    if wfr.status == "submitted_to_cd":
        if role not in ("CountryDirector", "Admin"):
            raise Forbidden("Only the Country Director can act on this request.")
        return "cd"

    # submitted_to_pl — the PL must actually supervise the owner.
    if role in ("CountryDirector", "Admin"):
        return "pl"  # country authority may act in the PL's place
    if role != "Program Lead":
        raise Forbidden("Only the owner's Program Lead can act on this request.")
    from apps.accounts.models import StaffSupervisorAssignment

    supervises = StaffSupervisorAssignment.objects.filter(
        supervisor__user_id=principal.user_id,
        supervisee__user_id=wfr.responsible_user,
    ).exists()
    if not supervises:
        raise Forbidden("This request belongs to another Program Lead's team.")
    return "pl"


def approve_weekly_request(request_id: str, principal) -> dict:
    """PL (for CCEO requests) or CD (for PL/PC/IA requests) approves ->
    confirmed_for_advance; the request enters the accountant's queue."""
    with transaction.atomic():
        wfr = (
            WeeklyFundRequest.objects.select_for_update().filter(id=request_id).first()
        )
        if not wfr:
            raise NotFoundError("Weekly fund request not found.")
        stage = _require_weekly_approver(wfr, principal)

        wfr.status = "confirmed_for_advance"
        wfr.save(update_fields=["status", "updated_at"])
        _sync_advances(wfr, "confirmed_for_advance", "advance")

    _audit_weekly(principal, "weekly_fund_request.approve", wfr, {"stage": stage})
    _notify_weekly_owner(
        wfr,
        "weekly_fund_request_approved",
        "Weekly fund request approved",
        f"Your weekly fund request ({wfr.week_start_date:%b %d} – "
        f"{wfr.week_end_date:%b %d}) was approved and sent to the Accountant "
        "for disbursement.",
    )
    _notify_weekly_accountants(wfr)
    return _serialize_request(wfr)


def return_weekly_request(request_id: str, data: dict, principal) -> dict:
    """Approver returns the request for correction -> returned_by_pl/_cd.
    The owner fixes the underlying schedule and re-submits (request_advance
    accepts returned_* statuses)."""
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BadRequest("A return reason is required.")
    with transaction.atomic():
        wfr = (
            WeeklyFundRequest.objects.select_for_update().filter(id=request_id).first()
        )
        if not wfr:
            raise NotFoundError("Weekly fund request not found.")
        stage = _require_weekly_approver(wfr, principal)

        wfr.status = "returned_by_pl" if stage == "pl" else "returned_by_cd"
        wfr.save(update_fields=["status", "updated_at"])
        _sync_advances(wfr, "pending_responsible_confirmation", "advance")

    _audit_weekly(
        principal, "weekly_fund_request.return", wfr, {"stage": stage, "reason": reason}
    )
    _notify_weekly_owner(
        wfr,
        "weekly_fund_request_returned",
        "Weekly fund request returned",
        f"Your weekly fund request ({wfr.week_start_date:%b %d} – "
        f"{wfr.week_end_date:%b %d}) was returned for correction. Reason: {reason}",
    )
    # The owner's "Fix Fund Request" To-Do derives automatically from the
    # returned_by_* status (command_center.todo_service._fund_request_todos).
    return _serialize_request(wfr)


def _audit_weekly(principal, action: str, wfr: WeeklyFundRequest, payload: dict):
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action=action,
            subject_kind="WeeklyFundRequest",
            subject_id=wfr.id,
            actor_id=principal.user_id,
            actor_role=getattr(principal, "active_role", None),
            success=True,
            payload={
                "week_start": wfr.week_start_date.isoformat(),
                "total": wfr.total_amount,
                **payload,
            },
        )
    except Exception:  # noqa: BLE001 - audit must never block the action
        logger.exception("weekly fund request audit log failed")


def _notify_weekly_owner(wfr: WeeklyFundRequest, event: str, title: str, body: str):
    try:
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type=event,
            category="finance",
            priority="high",
            title=title,
            body=body,
            context_type="WeeklyFundRequest",
            context_id=wfr.id,
            recipients=[wfr.responsible_user],
        )
    except Exception:  # noqa: BLE001
        logger.exception("weekly fund request owner notification failed")


def _notify_weekly_approver(wfr: WeeklyFundRequest):
    """Alert whoever must approve the freshly-submitted request."""
    try:
        from apps.accounts.models import StaffSupervisorAssignment, User
        from apps.notifications.services import WorkflowNotificationService

        if wfr.status == "submitted_to_pl":
            ids = list(
                StaffSupervisorAssignment.objects.filter(
                    supervisee__user_id=wfr.responsible_user
                ).values_list("supervisor__user_id", flat=True)
            )
        elif wfr.status == "submitted_to_cd":
            ids = list(
                User.objects.filter(
                    active_role="CountryDirector", is_active=True
                ).values_list("id", flat=True)
            )
        else:
            return
        ids = [i for i in ids if i]
        if not ids:
            return
        WorkflowNotificationService.trigger(
            event_type="weekly_fund_request_submitted",
            category="finance",
            priority="high",
            title="Weekly fund request awaiting your approval",
            body=f"A weekly fund request ({wfr.week_start_date:%b %d} – "
            f"{wfr.week_end_date:%b %d}, UGX {wfr.total_amount:,}) needs your review.",
            context_type="WeeklyFundRequest",
            context_id=wfr.id,
            recipients=ids,
        )
    except Exception:  # noqa: BLE001
        logger.exception("weekly fund request approver notification failed")


def _notify_weekly_accountants(wfr: WeeklyFundRequest):
    try:
        from apps.accounts.models import User
        from apps.notifications.services import WorkflowNotificationService

        ids = list(
            User.objects.filter(active_role="Accountant", is_active=True).values_list(
                "id", flat=True
            )
        )
        if not ids:
            return
        WorkflowNotificationService.trigger(
            event_type="weekly_fund_request_ready",
            category="finance",
            priority="high",
            title="Weekly fund request ready to disburse",
            body=f"An approved weekly fund request ({wfr.week_start_date:%b %d} – "
            f"{wfr.week_end_date:%b %d}, UGX {wfr.total_amount:,}) is ready for "
            "disbursement.",
            context_type="WeeklyFundRequest",
            context_id=wfr.id,
            recipients=ids,
        )
    except Exception:  # noqa: BLE001
        logger.exception("weekly fund request accountant notification failed")


def self_funded(request_id: str, principal) -> dict:
    """Elect self-funded reimbursement -> status self_funded."""
    with transaction.atomic():
        wfr = (
            WeeklyFundRequest.objects.select_for_update().filter(id=request_id).first()
        )
        if not wfr:
            raise NotFoundError("Weekly fund request not found.")
        if wfr.responsible_user != principal.user_id and not getattr(
            principal, "country_scope", False
        ):
            raise Forbidden("Only the owner can confirm this request.")
        if wfr.status in ("disbursed", "accounted"):
            raise BadRequest("Cannot change a disbursed request to self-funded.")

        wfr.status = "self_funded"
        wfr.confirmed_at = timezone.now()
        wfr.save(update_fields=["status", "confirmed_at", "updated_at"])

        # Also update linked AdvanceRequests status
        for line in wfr.lines.select_related("activity_budget_line"):
            adv = line.activity_budget_line.advance_requests.first()
            if adv:
                adv.status = "self_funded_pending_reimbursement"
                adv.advance_type = "self_funded"
                adv.confirmed_at = timezone.now()
                adv.save(
                    update_fields=[
                        "status",
                        "advance_type",
                        "confirmed_at",
                        "updated_at",
                    ]
                )

    return _serialize_request(wfr)


def not_requested(request_id: str, principal) -> dict:
    """Mark request as not requested yet."""
    with transaction.atomic():
        wfr = (
            WeeklyFundRequest.objects.select_for_update().filter(id=request_id).first()
        )
        if not wfr:
            raise NotFoundError("Weekly fund request not found.")
        if wfr.responsible_user != principal.user_id and not getattr(
            principal, "country_scope", False
        ):
            raise Forbidden("Only the owner can confirm this request.")
        if wfr.status in ("disbursed", "accounted"):
            raise BadRequest("Cannot cancel a disbursed request.")

        wfr.status = "not_requested"
        wfr.confirmed_at = timezone.now()
        wfr.save(update_fields=["status", "confirmed_at", "updated_at"])

        # Also update linked AdvanceRequests status
        for line in wfr.lines.select_related("activity_budget_line"):
            adv = line.activity_budget_line.advance_requests.first()
            if adv:
                adv.status = "not_requested"
                adv.advance_type = "not_requested"
                adv.confirmed_at = timezone.now()
                adv.save(
                    update_fields=[
                        "status",
                        "advance_type",
                        "confirmed_at",
                        "updated_at",
                    ]
                )

    return _serialize_request(wfr)


def disburse(request_id: str, data: dict, principal) -> dict:
    """Accountant disburses a confirmed weekly request."""
    with transaction.atomic():
        wfr = (
            WeeklyFundRequest.objects.select_for_update().filter(id=request_id).first()
        )
        if not wfr:
            raise NotFoundError("Weekly fund request not found.")
        if wfr.status != "confirmed_for_advance":
            raise BadRequest(
                "Only a confirmed request can be disbursed by the accountant."
            )

        try:
            disbursed_amount = int(data.get("amount") or wfr.total_amount)
        except (TypeError, ValueError):
            disbursed_amount = wfr.total_amount
        if disbursed_amount <= 0 or disbursed_amount > wfr.total_amount:
            raise BadRequest(
                "Disbursed amount must be positive and within the approved total."
            )
        fraction = disbursed_amount / wfr.total_amount if wfr.total_amount else 0
        now = timezone.now()

        # Cross-channel mutual exclusion: the AdvanceRequest rows are the one
        # shared money ledger every disbursement channel converges on. If any
        # child advance already has money out (disbursed directly via
        # advance_service, or mirrored by a period FundRequest), releasing
        # this weekly request would pay the same cost lines twice.
        already_moved = [
            line.activity_budget_line_id
            for line in wfr.lines.select_related("activity_budget_line")
            for adv in line.activity_budget_line.advance_requests.all()
            if adv.status in MONEY_MOVED_ADVANCE_STATUSES
        ]
        if already_moved:
            raise BadRequest(
                "Cannot disburse — money has already been released for "
                f"{len(already_moved)} of this request's budget lines through "
                "another disbursement channel."
            )

        wfr.status = "disbursed"
        wfr.disbursed_amount = disbursed_amount
        wfr.disbursed_at = now
        wfr.disbursed_by_user_id = principal.user_id
        wfr.disburse_method = data.get("method")
        wfr.disburse_reference = data.get("reference")
        wfr.save(
            update_fields=[
                "status",
                "disbursed_amount",
                "disbursed_at",
                "disbursed_by_user_id",
                "disburse_method",
                "disburse_reference",
                "updated_at",
            ]
        )

        # Also update linked AdvanceRequests status to keep them in sync.
        # Largest-remainder allocation: per-line round() drifted from the
        # parent total by up to ±1 UGX per line — the children must sum to
        # EXACTLY the disbursed amount (required reconciliation mismatch: 0).
        lines_with_adv = [
            (line, line.activity_budget_line.advance_requests.first())
            for line in wfr.lines.select_related("activity_budget_line")
        ]
        lines_with_adv = [(ln, adv) for ln, adv in lines_with_adv if adv]
        shares: dict[str, int] = {}
        if lines_with_adv:
            exact = [
                (adv.id, (ln.total_cost or 0) * fraction) for ln, adv in lines_with_adv
            ]
            floors = {adv_id: int(value) for adv_id, value in exact}
            remainder = disbursed_amount - sum(floors.values())
            by_fraction = sorted(
                exact, key=lambda item: (item[1] - int(item[1])), reverse=True
            )
            for adv_id, _value in by_fraction[: max(0, remainder)]:
                floors[adv_id] += 1
            shares = floors
        for line, adv in lines_with_adv:
            if adv:
                adv.status = "disbursed"
                adv.disbursed_amount = shares.get(adv.id, 0)
                adv.disbursed_at = now
                adv.disbursed_by_user_id = principal.user_id
                adv.disburse_method = data.get("method")
                adv.disburse_reference = data.get("reference")
                adv.save(
                    update_fields=[
                        "status",
                        "disbursed_amount",
                        "disbursed_at",
                        "disbursed_by_user_id",
                        "disburse_method",
                        "disburse_reference",
                        "updated_at",
                    ]
                )

    # Money moved — the ONLY disbursement channel that wasn't writing the
    # tamper-evident chain.
    _audit_weekly(
        principal,
        "weekly_fund_request.disburse",
        wfr,
        {
            "disbursed": wfr.disbursed_amount,
            "method": wfr.disburse_method or "",
            "reference": wfr.disburse_reference or "",
        },
    )
    return _serialize_request(wfr)


def accountant_weekly_queues() -> dict:
    """Return all weekly requests split by status for the accountant dashboard."""
    return {
        "pending_responsible_confirmation": _list_status(
            "pending_responsible_confirmation"
        ),
        "ready_for_disbursement": _list_status("confirmed_for_advance"),
        "self_funded": _list_status("self_funded"),
        "disbursed": _list_status("disbursed"),
        "not_requested": _list_status("not_requested"),
    }


def _list_status(status: str) -> list[dict]:
    qs = WeeklyFundRequest.objects.filter(status=status).order_by("-week_start_date")
    return [_serialize_request(r) for r in qs]


def _serialize_request(wfr: WeeklyFundRequest, include_lines: bool = False) -> dict:
    # Get the user name / details of the responsible owner
    from apps.accounts.models import StaffProfile

    profile = (
        StaffProfile.objects.filter(user_id=wfr.responsible_user)
        .select_related("user")
        .first()
    )
    owner_name = (
        profile.user.name if (profile and profile.user) else wfr.responsible_user
    )
    owner_initials = "".join([part[0].upper() for part in owner_name.split() if part])[
        :3
    ]

    res = {
        "id": wfr.id,
        "fy": wfr.fy,
        "weekStartDate": wfr.week_start_date.isoformat(),
        "weekEndDate": wfr.week_end_date.isoformat(),
        "responsibleUser": wfr.responsible_user,
        "responsibleUserName": owner_name,
        "responsibleUserInitials": owner_initials,
        "responsibleRole": wfr.responsible_role,
        "totalAmount": wfr.total_amount,
        "status": wfr.status,
        "disbursedAmount": wfr.disbursed_amount,
        "disbursedAt": wfr.disbursed_at.isoformat() if wfr.disbursed_at else None,
        "confirmedAt": wfr.confirmed_at.isoformat() if wfr.confirmed_at else None,
    }

    if include_lines:
        res["lines"] = [
            {
                "id": line.id,
                "lineItemType": line.line_item_type,
                "description": line.description,
                "quantity": line.quantity,
                "unitCost": line.unit_cost,
                "totalCost": line.total_cost,
                "currency": line.currency,
                "activityId": line.activity_budget_line.activity_id,
            }
            for line in wfr.lines.select_related("activity_budget_line")
        ]

    return res
