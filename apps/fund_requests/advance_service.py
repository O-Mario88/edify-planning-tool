"""Weekly advance-request lifecycle — auto-created from budget lines, gated on
responsible-user confirmation before the Accountant may disburse.

Flow:
  Activity scheduled → CostingService writes budget lines → this service auto-
  creates one AdvanceRequest per line (PENDING_RESPONSIBLE_CONFIRMATION).
  Responsible user chooses: Request Advance / Use Own Funds / Do Not Request.
  → Advance confirmed: Accountant may disburse → accountability closes the loop.
  → Self-funded: no disbursement; after completion + approval, reimbursement.

The responsible user is the scheduler/owner (CCEO/PL/IA/CD). The Accountant
cannot disburse before confirmation — the spec's core finance-safety rule.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.activities.models import Activity
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError

from .models import AdvanceRequest, AdvanceRequestStatus


# ── Auto-creation (called by the CostingService when budget lines are written)
def sync_for_activity(activity: Activity, responsible_user_id: str | None) -> None:
    """Create/update AdvanceRequests to mirror an activity's budget lines.

    One AdvanceRequest per ActivityScheduleCostLine (idempotent via the
    uniq_advance_per_budget_line constraint). Cleared lines drop their requests;
    new lines get a fresh PENDING_RESPONSIBLE_CONFIRMATION request. Already-
    confirmed/disbursed requests for a line are preserved (a reschedule re-prices
    the line; we refresh amount but do not reset a confirmed/disbursed advance)."""
    responsible = responsible_user_id or activity.responsible_staff_id
    lines = list(activity.schedule_cost_lines.all())
    line_ids = {line.id for line in lines}

    # The bulk-delete + per-line create/update must be atomic: a failure midway
    # would leave the advance-request set inconsistent with the activity's
    # budget lines (some deleted, some not yet recreated).
    with transaction.atomic():
        # Drop requests for budget lines that no longer exist — UNLESS the advance is
        # already disbursed/accounted/reimbursed (those are past cancellation and the
        # financial record must persist for audit/reconciliation).
        AdvanceRequest.objects.filter(activity=activity).exclude(
            budget_line_id__in=line_ids
        ).exclude(
            status__in=[
                AdvanceRequestStatus.DISBURSED,
                AdvanceRequestStatus.ACCOUNTED,
                AdvanceRequestStatus.REIMBURSED,
            ]
        ).delete()

        for line in lines:
            adv = AdvanceRequest.objects.filter(budget_line=line).first()
            # month/week: activity.planned_month/.planned_week are only
            # populated when a caller happens to pass them explicitly at
            # schedule time and are otherwise silently wrong — activity.month
            # is set reliably by costing_service.apply_to_activity from the
            # same scheduled_date, so use that + a week-of-month derived from
            # it (the same formula used throughout the app for this).
            week = (
                min(5, (activity.planned_date.day - 1) // 7 + 1)
                if activity.planned_date
                else None
            )
            if adv is None:
                AdvanceRequest.objects.create(
                    activity=activity,
                    budget_line=line,
                    responsible_user_id=responsible,
                    fy=activity.fy,
                    quarter=activity.quarter,
                    month=activity.month,
                    week=week,
                    planned_date=activity.scheduled_date,
                    amount=line.amount,
                    status=AdvanceRequestStatus.PENDING_RESPONSIBLE_CONFIRMATION,
                )
            else:
                # Refresh mutable fields (amount may change on reschedule).
                adv.amount = line.amount
                adv.responsible_user_id = responsible or adv.responsible_user_id
                adv.fy, adv.quarter = activity.fy, activity.quarter
                adv.month, adv.week = activity.month, week
                adv.planned_date = activity.scheduled_date
                adv.save(
                    update_fields=[
                        "amount",
                        "responsible_user_id",
                        "fy",
                        "quarter",
                        "month",
                        "week",
                        "planned_date",
                        "updated_at",
                    ]
                )


# ── Responsible-user confirmation ────────────────────────────────────────────
def _get_for_owner(advance_id: str, principal) -> AdvanceRequest:
    adv = AdvanceRequest.objects.filter(id=advance_id).first()
    if not adv:
        raise NotFoundError("Advance request not found.")
    # The responsible user confirms their OWN advances. Country-scope roles
    # (Admin/CD) may also act (operational override).
    if principal.user_id != adv.responsible_user_id and not getattr(
        principal, "country_scope", False
    ):
        raise Forbidden("Only the responsible user can confirm this advance request.")
    return adv


def confirm_advance(advance_id: str, principal) -> dict:
    """Responsible user requests an advance → CONFIRMED_FOR_ADVANCE (Accountant may disburse)."""
    adv = _get_for_owner(advance_id, principal)
    if adv.status not in (
        AdvanceRequestStatus.PENDING_RESPONSIBLE_CONFIRMATION,
        AdvanceRequestStatus.RETURNED,
    ):
        raise BadRequest(f"Cannot confirm an advance in status '{adv.status}'.")
    adv.status = AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE
    adv.advance_type = "advance"
    adv.confirmed_at = timezone.now()
    adv.save(update_fields=["status", "advance_type", "confirmed_at", "updated_at"])
    return _serialize(adv)


def self_funded(advance_id: str, principal) -> dict:
    """Responsible user elects to use own funds → SELF_FUNDED_PENDING_REIMBURSEMENT
    (no advance disbursement; reimbursement opens after completion + approval)."""
    adv = _get_for_owner(advance_id, principal)
    if adv.status in (
        AdvanceRequestStatus.DISBURSED,
        AdvanceRequestStatus.ACCOUNTED,
        AdvanceRequestStatus.REIMBURSED,
    ):
        raise BadRequest(f"Cannot change a {adv.status} advance to self-funded.")
    adv.status = AdvanceRequestStatus.SELF_FUNDED_PENDING_REIMBURSEMENT
    adv.advance_type = "self_funded"
    adv.confirmed_at = timezone.now()
    adv.save(update_fields=["status", "advance_type", "confirmed_at", "updated_at"])
    return _serialize(adv)


def not_requested(advance_id: str, principal) -> dict:
    """Responsible user declines funds → NOT_REQUESTED (budget stays visible for
    planning; Accountant does not disburse)."""
    adv = _get_for_owner(advance_id, principal)
    if adv.status in (
        AdvanceRequestStatus.DISBURSED,
        AdvanceRequestStatus.ACCOUNTED,
        AdvanceRequestStatus.REIMBURSED,
    ):
        raise BadRequest(f"Cannot cancel a {adv.status} advance.")
    adv.status = AdvanceRequestStatus.NOT_REQUESTED
    adv.advance_type = "not_requested"
    adv.confirmed_at = timezone.now()
    adv.save(update_fields=["status", "advance_type", "confirmed_at", "updated_at"])
    return _serialize(adv)


# ── Accountant actions ───────────────────────────────────────────────────────
def disburse(advance_id: str, data: dict, principal) -> dict:
    """Accountant disburses a CONFIRMED advance. GUARDED: may NOT disburse before
    the responsible user confirms (the finance-safety rule)."""
    adv = AdvanceRequest.objects.filter(id=advance_id).first()
    if not adv:
        raise NotFoundError("Advance request not found.")
    if adv.status not in (
        AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE,
        AdvanceRequestStatus.SUBMITTED_TO_ACCOUNTANT,
    ):
        raise BadRequest(
            f"Cannot disburse an advance in status '{adv.status}'. The responsible "
            "user must confirm the advance first."
        )
    adv.disbursed_amount = int(data.get("amount", adv.amount))
    adv.disbursed_at = timezone.now()
    adv.disbursed_by_user_id = principal.user_id
    adv.disburse_method = data.get("method")
    adv.disburse_reference = data.get("reference")
    adv.status = AdvanceRequestStatus.DISBURSED
    adv.save(
        update_fields=[
            "disbursed_amount",
            "disbursed_at",
            "disbursed_by_user_id",
            "disburse_method",
            "disburse_reference",
            "status",
            "updated_at",
        ]
    )
    return _serialize(adv)


def submit_accountability(advance_id: str, data: dict, principal) -> dict:
    """After a disbursed activity is executed, the RESPONSIBLE USER submits
    accountability: actual spend, returned amount, a variance explanation when
    the numbers don't reconcile, and the NetSuite Code — their proof that the
    expense record was entered into NetSuite. The Accountant then reviews
    (approve_accountability) — submission never self-closes.

    NetSuite Code is accountability proof and is REQUIRED here; it is not the
    Activity Salesforce ID (program proof), which lives on the Activity."""
    adv = AdvanceRequest.objects.filter(id=advance_id).first()
    if not adv:
        raise NotFoundError("Advance request not found.")
    if adv.status != AdvanceRequestStatus.DISBURSED:
        raise BadRequest("Accountability applies to a disbursed advance.")
    if adv.responsible_user_id and adv.responsible_user_id != principal.user_id:
        if getattr(principal, "active_role", "") not in ("CountryDirector", "Admin"):
            raise Forbidden("Only the responsible user can submit accountability.")

    netsuite_id = (data.get("netsuiteId") or "").strip()
    if not netsuite_id:
        raise BadRequest(
            "NetSuite Code is required — accountability is incomplete without "
            "proof the expense was entered into NetSuite."
        )
    accounted = int(data.get("amountSpent", 0) or 0)
    returned = int(data.get("amountReturned", 0) or 0)
    expected = adv.disbursed_amount or adv.amount or 0
    variance_note = (data.get("varianceNote") or "").strip()
    if accounted + returned != expected and not variance_note:
        raise BadRequest(
            f"Spent + returned (UGX {accounted + returned:,}) does not match the "
            f"disbursed amount (UGX {expected:,}) — a variance explanation is required."
        )

    adv.accounted_amount = accounted
    adv.returned_amount = returned
    adv.accountability_netsuite_id = netsuite_id
    adv.accountability_submitted_at = timezone.now()
    adv.last_note = variance_note[:512] if variance_note else adv.last_note
    adv.status = AdvanceRequestStatus.ACCOUNTABILITY_PENDING
    adv.save(
        update_fields=[
            "accounted_amount",
            "returned_amount",
            "accountability_netsuite_id",
            "accountability_submitted_at",
            "last_note",
            "status",
            "updated_at",
        ]
    )
    return _serialize(adv)


def approve_accountability(advance_id: str, principal) -> dict:
    """Accountant final-clears the accountability → ACCOUNTED.

    Hard gates: the NetSuite Code must be present (no code = accountability
    incomplete), and the activity must be IA-verified — the Accountant never
    final-clears program work whose quality IA has not confirmed."""
    adv = AdvanceRequest.objects.filter(id=advance_id).select_related("activity").first()
    if not adv:
        raise NotFoundError("Advance request not found.")
    if adv.status != AdvanceRequestStatus.ACCOUNTABILITY_PENDING:
        raise BadRequest("Nothing to approve — advance is not pending accountability.")
    if not (adv.accountability_netsuite_id or "").strip():
        raise BadRequest(
            "Cannot clear — no NetSuite Code on this accountability submission."
        )
    activity = adv.activity
    ia_verified = activity.ia_verification_status == "confirmed" or activity.status in (
        "ia_verified",
        "closed",
    )
    if not ia_verified:
        raise BadRequest(
            "Cannot final-clear — IA has not verified this activity yet. "
            "Finance clearance requires IA verification."
        )
    adv.accountability_reviewed_at = timezone.now()
    adv.status = AdvanceRequestStatus.ACCOUNTED
    adv.save(update_fields=["accountability_reviewed_at", "status", "updated_at"])
    return _serialize(adv)


# ── Reimbursement (self-funded path) ─────────────────────────────────────────
def submit_reimbursement(advance_id: str, data: dict, principal) -> dict:
    """A self-funded, completed + approved activity → responsible user claims."""
    adv = AdvanceRequest.objects.filter(id=advance_id).first()
    if not adv:
        raise NotFoundError("Advance request not found.")
    if adv.status != AdvanceRequestStatus.SELF_FUNDED_PENDING_REIMBURSEMENT:
        raise BadRequest("Only a self-funded advance can submit a reimbursement claim.")
    if not (data.get("netsuiteId") or "").strip():
        raise BadRequest(
            "NetSuite Code is required — a reimbursement claim is accountability "
            "and needs proof the expense was entered into NetSuite."
        )
    adv.accounted_amount = int(data.get("amountSpent", adv.amount))
    adv.accountability_netsuite_id = data.get("netsuiteId")
    adv.accountability_submitted_at = timezone.now()
    adv.status = AdvanceRequestStatus.REIMBURSEMENT_SUBMITTED
    adv.save(
        update_fields=[
            "accounted_amount",
            "accountability_netsuite_id",
            "accountability_submitted_at",
            "status",
            "updated_at",
        ]
    )
    return _serialize(adv)


def reimburse(advance_id: str, data: dict, principal) -> dict:
    """Accountant reimburses an approved claim → REIMBURSED."""
    adv = AdvanceRequest.objects.filter(id=advance_id).first()
    if not adv:
        raise NotFoundError("Advance request not found.")
    if adv.status != AdvanceRequestStatus.REIMBURSEMENT_SUBMITTED:
        raise BadRequest("Only a submitted reimbursement claim can be reimbursed.")
    adv.disbursed_amount = int(data.get("amount", adv.accounted_amount or adv.amount))
    adv.disbursed_at = timezone.now()
    adv.disbursed_by_user_id = principal.user_id
    adv.disburse_method = data.get("method")
    adv.disburse_reference = data.get("reference")
    adv.status = AdvanceRequestStatus.REIMBURSED
    adv.save(
        update_fields=[
            "disbursed_amount",
            "disbursed_at",
            "disbursed_by_user_id",
            "disburse_method",
            "disburse_reference",
            "status",
            "updated_at",
        ]
    )
    return _serialize(adv)


# ── Accountant dashboard queues ──────────────────────────────────────────────
def accountant_queues() -> dict:
    """The five Accountant queues. Each is a flat list of serialized advances."""
    return {
        "pending_responsible_confirmation": _list(
            AdvanceRequestStatus.PENDING_RESPONSIBLE_CONFIRMATION
        ),
        "ready_for_disbursement": _list(AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE),
        "self_funded": _list(AdvanceRequestStatus.SELF_FUNDED_PENDING_REIMBURSEMENT),
        "accountability_pending": _list(AdvanceRequestStatus.ACCOUNTABILITY_PENDING),
        "ready_for_reimbursement": _list(AdvanceRequestStatus.REIMBURSEMENT_SUBMITTED),
        "disbursed": _list(AdvanceRequestStatus.DISBURSED),
        "accounted": _list(AdvanceRequestStatus.ACCOUNTED),
    }


def _list(status: str) -> list[dict]:
    qs = AdvanceRequest.objects.filter(status=status).select_related(
        "activity", "budget_line"
    )
    return [_serialize(a) for a in qs]


def _serialize(adv: AdvanceRequest) -> dict:
    return {
        "id": adv.id,
        "activityId": adv.activity_id,
        "budgetLineId": adv.budget_line_id,
        "responsibleUserId": adv.responsible_user_id,
        "fy": adv.fy,
        "quarter": adv.quarter,
        "month": adv.month,
        "week": adv.week,
        "amount": adv.amount,
        "status": adv.status,
        "advanceType": adv.advance_type,
        "disbursedAmount": adv.disbursed_amount,
        "disbursedAt": adv.disbursed_at.isoformat() if adv.disbursed_at else None,
        "accountedAmount": adv.accounted_amount,
        "returnedAmount": adv.returned_amount,
        "accountabilityNetsuiteId": adv.accountability_netsuite_id,
        "confirmedAt": adv.confirmed_at.isoformat() if adv.confirmed_at else None,
    }


__all__ = [
    "sync_for_activity",
    "confirm_advance",
    "self_funded",
    "not_requested",
    "disburse",
    "submit_accountability",
    "approve_accountability",
    "submit_reimbursement",
    "reimburse",
    "accountant_queues",
]
