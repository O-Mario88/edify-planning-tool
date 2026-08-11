"""Taking partner work back, safely, from whatever state it is in.

One entry point. The workflow it runs is decided by the record's current
state, not by which button the reader found — an unscheduled handover and a
half-delivered visit are different problems, and a single destructive action
for both is how evidence gets lost and budgets go stale.

    awaiting schedule      → withdraw outright, UGX 0, no activity ever existed
    scheduled, unlocked    → recall: cancel the activity, budget unwinds
    scheduled, locked      → recall + formal budget amendment, snapshot intact
    in progress            → suspend and review, never an outright withdrawal
    evidence in / IA       → quality review, payment held, evidence preserved
    paid or closed         → refused; disputes and reopenings are other things

Nothing here deletes. The assignment, the activity, its cost lines and its
evidence are the record of what was asked for and what happened, and a record
that can be removed is not a record.

The financial work is delegated, not reimplemented: `activities.services.cancel`
already retains cost lines as history, drops un-moved advance requests, keeps
the ones whose money has moved, and re-syncs the weekly and monthly drafts.
Writing a second unwinding here would give the platform two answers about what
a cancelled activity costs.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError
from apps.partners.models import PartnerAssignment
from apps.partners.withdrawal_models import (
    REASON_ATTRIBUTION,
    RESTRICTED_PARTNER_MESSAGE,
    RESTRICTED_REASONS,
    PartnerAssignmentWithdrawal,
    WithdrawalDisposition,
    WithdrawalKind,
    WithdrawalReason,
    WithdrawalState,
)

REASON_MIN_LENGTH = 20
REASON_MAX_LENGTH = 600

# Activity states, grouped by what a withdrawal may still do to them.
_NOT_STARTED_STATUSES = ("planned", "scheduled", "partner_scheduled", "rescheduled")
_IN_PROGRESS_STATUSES = ("in_progress", "completion_started")
_EVIDENCE_STATUSES = (
    "evidence_uploaded",
    "evidence_accepted",
    "submitted_to_pl",
    "returned_by_pl",
    "salesforce_id_required",
    "awaiting_ia_verification",
    "returned_by_ia",
)
_IA_CLEARED_STATUSES = ("ia_verified", "accountant_confirmed")
_CLOSED_STATUSES = ("completed", "closed")

# Payment states past which ordinary withdrawal is never offered: the money has
# moved or the record has left finance, and rewriting either is not a
# supervision decision.
_PAID_STATUSES = ("paid", "disbursed", "netsuite_accountability", "closed")


# ── What is possible right now ───────────────────────────────────────────────
def resolve_kind(assignment, activity=None) -> str:
    """Which controlled workflow this record's state permits.

    Pure and side-effect free, so the page, the confirm step and the service
    all ask the same question and cannot disagree about the answer. The page
    showing "Recall" while the service performs an outright withdrawal is the
    class of bug this exists to make impossible.
    """
    activity = activity if activity is not None else assignment.scheduled_activity

    if assignment.status == PartnerAssignment.STATUS_RETURNED_TO_STAFF:
        # The partner has already handed it back; there is nothing to take.
        return WithdrawalKind.BLOCKED
    if activity is None:
        return WithdrawalKind.WITHDRAW_UNSCHEDULED

    status = activity.status or ""
    if status in _PAID_STATUSES or (activity.payment_status or "") in _PAID_STATUSES:
        return WithdrawalKind.BLOCKED
    if status in _CLOSED_STATUSES:
        return WithdrawalKind.BLOCKED
    if status in _IA_CLEARED_STATUSES:
        return WithdrawalKind.PAYMENT_HOLD
    if status in _EVIDENCE_STATUSES or (activity.evidence_status or "") not in (
        "",
        "none",
    ):
        return WithdrawalKind.QUALITY_REVIEW
    if status in _IN_PROGRESS_STATUSES:
        return WithdrawalKind.SUSPEND_IN_PROGRESS
    if status in _NOT_STARTED_STATUSES:
        return WithdrawalKind.RECALL_SCHEDULED
    return WithdrawalKind.BLOCKED


def is_financially_locked(activity) -> bool:
    """True when money has moved or been committed against this activity.

    Locked does not mean untouchable — it means the amount may not be silently
    rewritten. A locked recall still happens; it just produces a formal budget
    amendment instead of a quiet unwinding.
    """
    if activity is None:
        return False
    if (activity.payment_status or "none") not in ("none", "pending", "pending_ia"):
        return True

    from apps.fund_requests.models import MONEY_MOVED_ADVANCE_STATUSES, AdvanceRequest

    return AdvanceRequest.objects.filter(
        activity_id=activity.id, status__in=MONEY_MOVED_ADVANCE_STATUSES
    ).exists()


# ── Authority ────────────────────────────────────────────────────────────────
def assert_may_withdraw(principal, assignment, kind: str) -> str:
    """Who may do this, to this, right now. Returns the acting role.

    The rule the spec turns on: a CCEO may withdraw their own school's work
    only while it is still unscheduled. Once a partner has committed to a date
    the CCEO must ask their Program Lead, because cancelling work a partner has
    planned around is a decision with consequences beyond one school.
    """
    from apps.core.permissions import has_permission
    from apps.core.rbac import EdifyRole, Permission
    from apps.core.scoping import owner_ids, resolve_user_scope

    role = getattr(principal, "active_role", "") or ""
    if getattr(principal, "is_superuser", False) or role == EdifyRole.ADMIN.value:
        return role

    # The coarse gate first: does this role do withdrawals at all. Checked
    # server-side rather than inferred from which button rendered, because a
    # hidden control is not a permission.
    if not has_permission(principal, Permission.PARTNER_ASSIGNMENT_WITHDRAW.value):
        raise Forbidden("Your role cannot withdraw partner assignments.")

    if role == EdifyRole.COUNTRY_DIRECTOR.value:
        return role

    from apps.planning.oversight_service import _both_id_spaces

    own = _both_id_spaces(set(owner_ids(principal)))
    scope = resolve_user_scope(principal)
    supervised = _both_id_spaces(set(scope.supervised_staff_ids or []))

    managing = {assignment.monitoring_staff_id, assignment.assigning_staff_id} - {
        None,
        "",
    }

    if role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
        if not managing & (own | supervised):
            raise Forbidden(
                "This assignment belongs to another team. Ask the Program Lead "
                "who supervises it."
            )
        return role

    if role == EdifyRole.CCEO.value:
        if not managing & own:
            raise Forbidden("This assignment is not yours to withdraw.")
        if kind != WithdrawalKind.WITHDRAW_UNSCHEDULED:
            raise Forbidden(
                "The partner has already scheduled this. Request withdrawal "
                "from your Program Lead rather than cancelling their planned "
                "work directly."
            )
        return role

    raise Forbidden("Your role cannot withdraw partner assignments.")


# ── Impact preview ───────────────────────────────────────────────────────────
def preview(principal, assignment_id: str) -> dict:
    """What confirming would actually do, computed on the server.

    Every number here is read from the record rather than estimated, because
    the point of the preview is that nobody confirms a budget change they have
    not seen.
    """
    assignment = _load(assignment_id)
    activity = assignment.scheduled_activity
    kind = resolve_kind(assignment, activity)
    locked = is_financially_locked(activity)

    cost = 0
    if activity is not None:
        from django.db.models import Sum

        from apps.activities.models import ActivityScheduleCostLine

        cost = (
            ActivityScheduleCostLine.objects.filter(activity=activity).aggregate(
                t=Sum("amount")
            )["t"]
            or 0
        )

    return {
        "assignment_id": assignment.id,
        "kind": kind,
        "kind_label": WithdrawalKind(kind).label
        if kind in WithdrawalKind.values
        else kind,
        "available": kind != WithdrawalKind.BLOCKED,
        "school": getattr(assignment.school, "name", "") or "",
        "partner": getattr(assignment.partner, "name", "") or "",
        "activity_type": (
            getattr(activity, "activity_type", "")
            or assignment.expected_activity_type
            or ""
        ),
        "support_slot": _slot_label(assignment),
        "assignment_status": assignment.status,
        "activity_status": getattr(activity, "status", "") or "",
        "evidence_status": getattr(activity, "evidence_status", "") or "",
        "ia_status": getattr(activity, "ia_verification_status", "") or "",
        "payment_status": getattr(activity, "payment_status", "") or "",
        "scheduled_date": getattr(activity, "planned_date", None),
        "planned_cost": int(cost),
        "financially_locked": locked,
        # The three questions somebody is actually deciding on.
        "activity_will_be_cancelled": kind == WithdrawalKind.RECALL_SCHEDULED,
        "budget_amendment_required": locked and kind == WithdrawalKind.RECALL_SCHEDULED,
        "budget_removed": 0
        if (locked or kind == WithdrawalKind.WITHDRAW_UNSCHEDULED)
        else int(cost),
        "slot_will_reopen": kind
        in (WithdrawalKind.WITHDRAW_UNSCHEDULED, WithdrawalKind.RECALL_SCHEDULED),
        "fy": getattr(activity, "fy", "") or "",
        "month": getattr(activity, "planned_month", None),
        "quarter": getattr(activity, "quarter", "") or "",
    }


def _slot_label(assignment) -> str:
    """The support requirement this assignment holds, in words."""
    bits = [assignment.support_type or assignment.expected_activity_type or "Support"]
    if assignment.visit_number:
        bits.append(f"Visit {assignment.visit_number}")
    if assignment.training_number:
        bits.append(f"Training {assignment.training_number}")
    return " · ".join(b for b in bits if b)


def _load(assignment_id: str) -> PartnerAssignment:
    assignment = (
        PartnerAssignment.objects.select_related(
            "school", "partner", "scheduled_activity"
        )
        .filter(id=assignment_id)
        .first()
    )
    if assignment is None:
        raise NotFoundError("Assignment not found.")
    return assignment


# ── Validation ───────────────────────────────────────────────────────────────
def _validate(data: dict) -> tuple[str, str, str, str]:
    reason_category = ((data or {}).get("reason_category") or "").strip()
    if reason_category not in WithdrawalReason.values:
        raise BadRequest("Choose a reason category.")

    explanation = ((data or {}).get("partner_facing_reason") or "").strip()
    if len(explanation) < REASON_MIN_LENGTH:
        raise BadRequest(
            "Explain briefly why this work is being withdrawn and what should "
            f"happen next (at least {REASON_MIN_LENGTH} characters)."
        )
    if len(explanation) > REASON_MAX_LENGTH:
        raise BadRequest(f"Keep the explanation under {REASON_MAX_LENGTH} characters.")

    disposition = ((data or {}).get("disposition") or "").strip()
    if disposition not in WithdrawalDisposition.values:
        raise BadRequest("Choose what happens to this support next.")

    internal_note = ((data or {}).get("internal_note") or "").strip()
    return reason_category, explanation, disposition, internal_note


def partner_facing_text(reason_category: str, explanation: str) -> str:
    """What the partner is told.

    A safeguarding or conduct concern is withheld — the partner is told the
    work has stopped and who to contact, and the substance travels through the
    restricted route rather than an ordinary notification that lands in a queue
    several people can read.
    """
    if reason_category in RESTRICTED_REASONS:
        return RESTRICTED_PARTNER_MESSAGE
    return explanation


# ── The decision ─────────────────────────────────────────────────────────────
def withdraw(assignment_id: str, data: dict, principal) -> PartnerAssignmentWithdrawal:
    """Take the work back, and record everything that happened because of it.

    One transaction. If any step fails the assignment stays exactly as it was,
    no replacement exists and nothing was announced — a half-applied withdrawal
    would leave a school with no owner and a partner with no instruction.

    Idempotent by construction: a second call while a withdrawal is open
    returns the existing record rather than opening a second one. Two open
    withdrawals would each claim the support slot, and the database constraint
    refuses that anyway; this turns the race into an answer.
    """
    reason_category, explanation, disposition, internal_note = _validate(data)
    replacement_partner_id = ((data or {}).get("replacement_partner_id") or "").strip()

    if (
        disposition == WithdrawalDisposition.REASSIGN_PARTNER
        and not replacement_partner_id
    ):
        raise BadRequest("Choose the partner this support is going to.")

    with transaction.atomic():
        # of=("self",) locks the assignment row only. school and
        # scheduled_activity are nullable, so select_related makes them LEFT
        # OUTER JOINs and Postgres refuses FOR UPDATE on the nullable side of
        # one — the lock we want is on the assignment anyway.
        assignment = (
            PartnerAssignment.objects.select_for_update(of=("self",))
            .select_related("school", "partner", "scheduled_activity")
            .filter(id=assignment_id)
            .first()
        )
        if assignment is None:
            raise NotFoundError("Assignment not found.")

        existing = PartnerAssignmentWithdrawal.objects.filter(
            assignment=assignment, state__in=OPEN_STATES
        ).first()
        if existing is not None:
            return existing

        activity = assignment.scheduled_activity
        if activity is not None:
            # Locked so a partner cannot start work, upload evidence or be paid
            # in the gap between deciding and recording.
            from apps.activities.models import Activity

            activity = Activity.objects.select_for_update().get(pk=activity.pk)

        kind = resolve_kind(assignment, activity)
        if kind == WithdrawalKind.BLOCKED:
            raise ConflictError(
                "This work can no longer be withdrawn. Paid and closed activities "
                "are settled through a dispute or a reopening, not a withdrawal."
            )
        acting_role = assert_may_withdraw(principal, assignment, kind)

        if replacement_partner_id:
            _assert_replacement_eligible(assignment, replacement_partner_id)

        locked = is_financially_locked(activity)
        original_cost = _cost_of(activity)

        withdrawal = PartnerAssignmentWithdrawal.objects.create(
            assignment=assignment,
            linked_activity=activity,
            school=assignment.school,
            partner=assignment.partner,
            requested_by=getattr(principal, "id", "") or "",
            requested_by_role=acting_role,
            responsible_cceo_id=assignment.monitoring_staff_id
            or assignment.assigning_staff_id,
            kind=kind,
            reason_category=reason_category,
            partner_facing_reason=partner_facing_text(reason_category, explanation),
            internal_note=internal_note,
            attribution=REASON_ATTRIBUTION[reason_category],
            disposition=disposition,
            assignment_state_at_withdrawal=assignment.status,
            activity_state_at_withdrawal=getattr(activity, "status", "") or "",
            financial_state_at_withdrawal="locked" if locked else "unlocked",
            original_planned_cost=original_cost,
            state=_initial_state(kind),
        )

        _perform(withdrawal, assignment, activity, principal, replacement_partner_id)

    if withdrawal.state in OPEN_STATES:
        # A hold stops work and opens a review; nothing is released and
        # nobody is told the assignment has gone, because it has not.
        return withdrawal

    _announce(withdrawal, principal)
    return withdrawal


def _perform(
    withdrawal, assignment, activity, principal, replacement_partner_id=""
) -> None:
    """Carry out a withdrawal that has already been recorded and authorised.

    Shared by the direct path and the approve-a-request path so the two cannot
    diverge. Before this existed the approval route hit `withdraw`'s
    idempotence guard — the request record was already open, so the guard
    returned it and the withdrawal silently did not happen.

    Must be called inside the caller's transaction, with the assignment locked.
    """
    kind = withdrawal.kind

    # Suspension, quality review and payment hold stop the work and open a
    # decision; they do not release the slot, because the school may still be
    # owed the rest of this very activity and a replacement now would
    # duplicate it.
    if kind in (
        WithdrawalKind.SUSPEND_IN_PROGRESS,
        WithdrawalKind.QUALITY_REVIEW,
        WithdrawalKind.PAYMENT_HOLD,
    ):
        _hold(assignment, activity, withdrawal)
        return

    if kind == WithdrawalKind.RECALL_SCHEDULED and activity is not None:
        _recall_activity(
            activity,
            withdrawal,
            principal,
            locked=withdrawal.financial_state_at_withdrawal == "locked",
        )

    assignment.status = PartnerAssignment.STATUS_RETURNED_TO_STAFF
    assignment.return_reason_category = _mapped_return_reason(
        withdrawal.reason_category
    )
    assignment.return_reason = withdrawal.partner_facing_reason
    assignment.returned_at = timezone.now()
    assignment.returned_by = getattr(principal, "id", "") or ""
    assignment.save(
        update_fields=[
            "status",
            "return_reason_category",
            "return_reason",
            "returned_at",
            "returned_by",
            "updated_at",
        ]
    )

    if withdrawal.disposition == WithdrawalDisposition.REASSIGN_PARTNER:
        withdrawal.replacement_assignment = _create_replacement(
            assignment, replacement_partner_id, principal
        )
        withdrawal.state = WithdrawalState.REASSIGNED
    elif withdrawal.disposition == WithdrawalDisposition.RETURN_TO_PLANNING:
        withdrawal.state = WithdrawalState.RETURNED_TO_PLANNING
    elif withdrawal.disposition == WithdrawalDisposition.ESCALATE:
        withdrawal.state = WithdrawalState.ESCALATED
    else:
        withdrawal.state = WithdrawalState.EFFECTIVE

    withdrawal.effective_at = timezone.now()
    withdrawal.save(
        update_fields=["replacement_assignment", "state", "effective_at", "updated_at"]
    )


OPEN_STATES = (
    WithdrawalState.REQUESTED,
    WithdrawalState.UNDER_REVIEW,
    WithdrawalState.APPROVED,
    WithdrawalState.SUSPENDED,
)


def _initial_state(kind: str) -> str:
    """A hold opens a review; a withdrawal takes effect immediately.

    Operational control cannot wait for an acknowledgement — a partner must
    stop working when told to, and the conversation happens afterwards.
    """
    if kind in (
        WithdrawalKind.SUSPEND_IN_PROGRESS,
        WithdrawalKind.QUALITY_REVIEW,
        WithdrawalKind.PAYMENT_HOLD,
    ):
        return WithdrawalState.SUSPENDED
    return WithdrawalState.APPROVED


def _cost_of(activity) -> int:
    if activity is None:
        return 0
    from django.db.models import Sum

    from apps.activities.models import ActivityScheduleCostLine

    return int(
        ActivityScheduleCostLine.objects.filter(activity=activity).aggregate(
            t=Sum("amount")
        )["t"]
        or 0
    )


def _recall_activity(activity, withdrawal, principal, *, locked: bool) -> None:
    """Cancel the partner's activity through the canonical transition.

    Delegated to `activities.services.cancel`, which retains the cost lines as
    the historical snapshot, deletes advance requests whose money has not
    moved, preserves the ones whose money has, and re-syncs the weekly and
    monthly drafts so the amount leaves every live funding surface. A second
    implementation here would give the platform two answers about what a
    cancelled activity costs.

    When the money IS locked the amount is not silently unwound: the activity
    still stops, and the difference goes to a budget amendment that somebody
    has to approve.
    """
    from apps.activities import services as activity_services

    # `already_authorised`: `assert_may_withdraw` above is the authority for
    # this decision, and it deliberately lets a Programme Lead recall a
    # supervised CCEO's scheduled work. The activity service's own
    # direct-portfolio guard would refuse that, so the two would disagree about
    # a power the platform grants on purpose.
    activity_services.cancel(
        activity.id,
        {"reason": f"Partner withdrawal: {withdrawal.get_reason_category_display()}"},
        principal,
        already_authorised=True,
    )

    if locked:
        withdrawal.budget_amendment = _request_amendment(
            activity, withdrawal, principal
        )
        withdrawal.save(update_fields=["budget_amendment", "updated_at"])


def _request_amendment(activity, withdrawal, principal):
    """A formal adjustment, because the approved amount may not be rewritten."""
    try:
        from apps.budget import amendment_service

        return amendment_service.request_amendment(
            activity.id,
            {
                "reason": (
                    f"Partner work withdrawn ({withdrawal.get_reason_category_display()}). "
                    f"{withdrawal.partner_facing_reason}"
                ),
                "new_date": None,
            },
            principal,
        )
    except Exception:  # noqa: BLE001
        # The withdrawal itself must not fail because finance refused the
        # amendment shape; the health check reports a locked withdrawal with no
        # amendment so it is chased rather than lost.
        return None


def _hold(assignment, activity, withdrawal) -> None:
    """Stop further work without releasing the slot or touching the money."""
    if activity is None:
        return
    from apps.activities.models import Activity

    Activity.objects.filter(pk=activity.pk).update(
        last_reason=f"On hold — {withdrawal.get_kind_display()}",
        updated_at=timezone.now(),
    )


def _mapped_return_reason(reason_category: str) -> str:
    """Reuse the partner-return vocabulary where the two genuinely overlap.

    The assignment already carries `return_reason_category` from the partner's
    own return path, and staff triaging a queue read that column. Where a
    withdrawal reason has no counterpart it maps to OTHER and the full reason
    stays on the withdrawal record, which is the authoritative one.
    """
    from apps.partners.models import PartnerReturnReason

    overlap = {
        WithdrawalReason.CAPACITY: PartnerReturnReason.CAPACITY,
        WithdrawalReason.SCHOOL_UNAVAILABLE: PartnerReturnReason.SCHOOL_UNAVAILABLE,
        WithdrawalReason.OUT_OF_SCOPE: PartnerReturnReason.OUT_OF_SCOPE,
        WithdrawalReason.DUPLICATE_ASSIGNMENT: PartnerReturnReason.DUPLICATE,
        WithdrawalReason.INCORRECT_ASSIGNMENT: PartnerReturnReason.INCORRECT_DETAILS,
        WithdrawalReason.DISTANCE: PartnerReturnReason.DISTANCE,
        WithdrawalReason.SAFETY: PartnerReturnReason.SAFETY,
    }
    return overlap.get(reason_category, PartnerReturnReason.OTHER)


def _assert_replacement_eligible(assignment, replacement_partner_id: str) -> None:
    """The replacement must be a partner who can actually take this on.

    Refuses the same partner the work is being taken from — reassigning to the
    partner who just failed to deliver reads as a mistake, and where it is
    genuinely intended (correction after review) that is a different decision
    with a different record.
    """
    from apps.partners.models import Partner

    if replacement_partner_id == assignment.partner_id:
        raise BadRequest(
            "That is the partner this work is being taken from. Choose another, "
            "or return the support to planning."
        )

    partner = Partner.objects.filter(
        id=replacement_partner_id, deleted_at__isnull=True
    ).first()
    if partner is None:
        raise NotFoundError("That partner no longer exists.")
    if not partner.active_status:
        raise BadRequest(f"{partner.name} is not currently active.")

    # One live assignment per support slot. Without this a school could end up
    # with two partners both believing they own the same visit, and both
    # eventually billing for it.
    clash = (
        PartnerAssignment.objects.filter(
            school_id=assignment.school_id,
            partner_id=replacement_partner_id,
            support_type=assignment.support_type,
            visit_number=assignment.visit_number,
            training_number=assignment.training_number,
        )
        .exclude(status=PartnerAssignment.STATUS_RETURNED_TO_STAFF)
        .exclude(id=assignment.id)
        .exists()
    )
    if clash:
        raise ConflictError(
            f"{partner.name} already holds this support slot at this school."
        )


def _create_replacement(assignment, replacement_partner_id: str, principal):
    """A new assignment for the same support requirement, carrying no cost.

    The slot identifiers are copied because they ARE the requirement's
    identity — same school, same support type, same visit or training number,
    same project. That is what makes this a replacement rather than a second
    entitlement.

    Deliberately NOT copied: the scheduled date, the scheduled activity and
    anything financial. The price depends on who schedules it and when, so it
    cannot exist until the new partner picks a date and their own rate is
    fetched from the catalogue.
    """
    return PartnerAssignment.objects.create(
        school=assignment.school,
        cluster=assignment.cluster,
        partner_id=replacement_partner_id,
        assigning_staff_id=getattr(principal, "id", "")
        or assignment.assigning_staff_id,
        monitoring_staff_id=assignment.monitoring_staff_id
        or assignment.assigning_staff_id,
        assignment_mode=assignment.assignment_mode,
        catalogue_item=assignment.catalogue_item,
        source_ssa=assignment.source_ssa,
        source_activity=assignment.source_activity,
        project=assignment.project,
        purpose=assignment.purpose,
        focus_intervention=assignment.focus_intervention,
        purpose_of_visit=assignment.purpose_of_visit,
        expected_activity_type=assignment.expected_activity_type,
        support_type=assignment.support_type,
        visit_number=assignment.visit_number,
        training_number=assignment.training_number,
        catalogue_snapshot=assignment.catalogue_snapshot,
        status=PartnerAssignment.STATUS_ASSIGNED,
        replaces_assignment=assignment,
        reassignment_sequence=(assignment.reassignment_sequence or 0) + 1,
    )


def _announce(withdrawal, principal) -> None:
    """Tell everyone the decision affects, after it is committed.

    After commit on purpose: a notification announcing a withdrawal that then
    rolled back would have a partner stop work that is still theirs.
    """
    from apps.audit.services import log as audit_log

    audit_log(
        action="partner.assignment_withdrawn",
        subject_kind="PartnerAssignmentWithdrawal",
        subject_id=withdrawal.id,
        actor_id=withdrawal.requested_by or "unknown",
        actor_role=withdrawal.requested_by_role,
        success=True,
        payload={
            "assignment_id": withdrawal.assignment_id,
            "activity_id": withdrawal.linked_activity_id,
            "partner_id": withdrawal.partner_id,
            "school_id": withdrawal.school_id,
            "kind": withdrawal.kind,
            "reason_category": withdrawal.reason_category,
            "attribution": withdrawal.attribution,
            "disposition": withdrawal.disposition,
            "original_planned_cost": withdrawal.original_planned_cost,
            "replacement_assignment_id": withdrawal.replacement_assignment_id,
            "financial_state": withdrawal.financial_state_at_withdrawal,
        },
    )

    _notify_partner(withdrawal)
    _notify_staff(withdrawal)
    if withdrawal.replacement_assignment_id:
        _notify_replacement_partner(withdrawal)


def _notify_partner(withdrawal) -> None:
    """The outgoing partner, told what stopped and why — safely.

    `partner_facing_reason` is already the redacted text for restricted
    reasons, so nothing here has to remember to filter it a second time.
    """
    from apps.notifications.models import Notification
    from apps.partners.models import Partner

    partner = Partner.objects.filter(id=withdrawal.partner_id).first()
    if partner is None or not partner.user_id:
        return

    school = getattr(withdrawal.school, "name", "") or "an assigned school"
    Notification.objects.update_or_create(
        recipient_id=partner.user_id,
        context_type="PartnerAssignmentWithdrawal",
        context_id=withdrawal.id,
        source_event_type=f"partner_withdrawal.{withdrawal.kind}",
        defaults={
            "recipient_role": "Partner",
            "title": f"{withdrawal.get_kind_display()} — {school}",
            "body": (
                f"{withdrawal.partner_facing_reason}\n\n"
                "Please stop further work on this assignment."
            ),
            "category": "planning",
            "target_route": "/partner/assignments",
            "action_label": "View assignment",
            "action_required": False,
            "priority": "high",
            "status": "unread",
            "read_at": None,
        },
    )


def _notify_staff(withdrawal) -> None:
    """The managing CCEO, who now owns a school with support to re-arrange."""
    from apps.accounts.models import StaffProfile
    from apps.notifications.models import Notification

    staff_id = withdrawal.responsible_cceo_id
    if not staff_id:
        return
    profile = (
        StaffProfile.objects.filter(id=staff_id).select_related("user").first()
        or StaffProfile.objects.filter(user_id=staff_id).select_related("user").first()
    )
    if profile is None or not profile.user_id:
        return

    school = getattr(withdrawal.school, "name", "") or "a school"
    onward = withdrawal.get_disposition_display()
    Notification.objects.update_or_create(
        recipient_id=profile.user_id,
        context_type="PartnerAssignmentWithdrawal",
        context_id=withdrawal.id,
        source_event_type=f"partner_withdrawal_staff.{withdrawal.kind}",
        defaults={
            "recipient_role": "CCEO",
            "title": f"Partner work withdrawn — {school}",
            "body": (
                f"{withdrawal.get_kind_display()} for {school}. "
                f"{withdrawal.partner_facing_reason}\n\nNext: {onward}."
            ),
            "category": "planning",
            "target_route": "/partner-oversight/",
            "action_label": onward,
            "action_required": withdrawal.disposition
            == WithdrawalDisposition.RETURN_TO_PLANNING,
            "priority": "normal",
            "status": "unread",
            "read_at": None,
        },
    )


def _notify_replacement_partner(withdrawal) -> None:
    """The incoming partner, who has a school to schedule and no cost yet."""
    from apps.notifications.models import Notification

    replacement = withdrawal.replacement_assignment
    partner = getattr(replacement, "partner", None)
    if partner is None or not partner.user_id:
        return

    school = getattr(replacement.school, "name", "") or "a school"
    Notification.objects.update_or_create(
        recipient_id=partner.user_id,
        context_type="PartnerAssignment",
        context_id=replacement.id,
        source_event_type="partner_assignment.replacement",
        defaults={
            "recipient_role": "Partner",
            "title": f"New assignment — {school}",
            "body": (
                f"{school} has been assigned to you. Please set a date; the "
                "cost is calculated from your rate when you schedule."
            ),
            "category": "planning",
            "target_route": "/partner/assignments",
            "action_label": "Schedule",
            "action_required": True,
            "priority": "normal",
            "status": "unread",
            "read_at": None,
        },
    )


# ── The CCEO's request, and the PL's answer ──────────────────────────────────
def request_withdrawal(
    assignment_id: str, data: dict, principal
) -> PartnerAssignmentWithdrawal:
    """A CCEO asks their Program Lead to take back work a partner has planned.

    The CCEO owns the school and usually notices the problem first, but
    cancelling work a partner has already scheduled affects that partner's
    week and the country's budget, so the decision sits one level up. This
    records the ask; it changes no activity and moves no money.
    """
    from apps.core.rbac import EdifyRole

    reason_category, explanation, disposition, internal_note = _validate(data)

    with transaction.atomic():
        assignment = (
            PartnerAssignment.objects.select_for_update(of=("self",))
            .select_related("school", "partner", "scheduled_activity")
            .filter(id=assignment_id)
            .first()
        )
        if assignment is None:
            raise NotFoundError("Assignment not found.")

        existing = PartnerAssignmentWithdrawal.objects.filter(
            assignment=assignment, state__in=OPEN_STATES
        ).first()
        if existing is not None:
            return existing

        activity = assignment.scheduled_activity
        kind = resolve_kind(assignment, activity)
        if kind == WithdrawalKind.BLOCKED:
            raise ConflictError(
                "This work can no longer be withdrawn. Paid and closed "
                "activities are settled through a dispute, not a withdrawal."
            )
        if kind == WithdrawalKind.WITHDRAW_UNSCHEDULED:
            raise BadRequest(
                "The partner has not scheduled this yet, so you can withdraw it "
                "yourself rather than asking."
            )

        # Scope only — the CCEO is asking, not deciding, so the
        # already-scheduled refusal in assert_may_withdraw does not apply.
        _assert_owns(principal, assignment)

        withdrawal = PartnerAssignmentWithdrawal.objects.create(
            assignment=assignment,
            linked_activity=activity,
            school=assignment.school,
            partner=assignment.partner,
            requested_by=getattr(principal, "id", "") or "",
            requested_by_role=getattr(principal, "active_role", "")
            or EdifyRole.CCEO.value,
            responsible_cceo_id=assignment.monitoring_staff_id
            or assignment.assigning_staff_id,
            supervising_pl_id=_supervisor_of(
                assignment.monitoring_staff_id or assignment.assigning_staff_id
            ),
            kind=kind,
            reason_category=reason_category,
            partner_facing_reason=partner_facing_text(reason_category, explanation),
            internal_note=internal_note,
            attribution=REASON_ATTRIBUTION[reason_category],
            disposition=disposition,
            assignment_state_at_withdrawal=assignment.status,
            activity_state_at_withdrawal=getattr(activity, "status", "") or "",
            financial_state_at_withdrawal=(
                "locked" if is_financially_locked(activity) else "unlocked"
            ),
            original_planned_cost=_cost_of(activity),
            state=WithdrawalState.REQUESTED,
        )

    _notify_reviewer(withdrawal)
    return withdrawal


def _assert_owns(principal, assignment) -> None:
    from apps.core.permissions import has_permission
    from apps.core.rbac import Permission
    from apps.core.scoping import owner_ids

    if not has_permission(principal, Permission.PARTNER_ASSIGNMENT_WITHDRAW.value):
        raise Forbidden("Your role cannot request partner withdrawals.")

    from apps.planning.oversight_service import _both_id_spaces

    own = _both_id_spaces(set(owner_ids(principal)))
    managing = {assignment.monitoring_staff_id, assignment.assigning_staff_id} - {
        None,
        "",
    }
    if not managing & own:
        raise Forbidden("This assignment is not yours to withdraw.")


def _supervisor_of(staff_id: str | None) -> str | None:
    if not staff_id:
        return None
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    profile = (
        StaffProfile.objects.filter(id=staff_id).first()
        or StaffProfile.objects.filter(user_id=staff_id).first()
    )
    if profile is None:
        return None
    link = StaffSupervisorAssignment.objects.filter(supervisee_id=profile.id).first()
    return link.supervisor_id if link else None


def review_request(
    withdrawal_id: str, data: dict, principal
) -> PartnerAssignmentWithdrawal:
    """The Program Lead decides a request their CCEO raised.

    Approving performs the withdrawal the CCEO asked for, under the PL's
    authority — the CCEO could not have done it themselves, which is the whole
    point of routing it here.
    """
    from apps.core.permissions import has_permission
    from apps.core.rbac import Permission

    decision = ((data or {}).get("decision") or "").strip()
    if decision not in ("approve", "reject"):
        raise BadRequest("Approve or reject the request.")

    if not has_permission(principal, Permission.PARTNER_WITHDRAWAL_REVIEW.value):
        raise Forbidden("Only a supervising Program Lead may decide this.")

    withdrawal = (
        PartnerAssignmentWithdrawal.objects.filter(id=withdrawal_id)
        .select_related("assignment")
        .first()
    )
    if withdrawal is None:
        raise NotFoundError("Withdrawal request not found.")
    if withdrawal.state != WithdrawalState.REQUESTED:
        # Already decided. Reporting the existing decision beats a second one.
        return withdrawal

    assert_may_withdraw(principal, withdrawal.assignment, withdrawal.kind)

    if decision == "reject":
        withdrawal.state = WithdrawalState.REJECTED
        withdrawal.approved_by = getattr(principal, "id", "") or ""
        withdrawal.approved_at = timezone.now()
        withdrawal.internal_note = (
            f"{withdrawal.internal_note}\n\nRejected: "
            f"{((data or {}).get('note') or '').strip()}"
        ).strip()
        withdrawal.save(
            update_fields=[
                "state",
                "approved_by",
                "approved_at",
                "internal_note",
                "updated_at",
            ]
        )
        return withdrawal

    # Approving decides and performs in one transaction, so the queue can
    # never show an approved request that did not actually happen.
    replacement_partner_id = ((data or {}).get("replacement_partner_id") or "").strip()
    if (
        withdrawal.disposition == WithdrawalDisposition.REASSIGN_PARTNER
        and not replacement_partner_id
    ):
        raise BadRequest("Choose the partner this support is going to.")

    with transaction.atomic():
        assignment = (
            PartnerAssignment.objects.select_for_update(of=("self",))
            .select_related("school", "partner", "scheduled_activity")
            .get(pk=withdrawal.assignment_id)
        )
        activity = assignment.scheduled_activity
        if activity is not None:
            from apps.activities.models import Activity

            activity = Activity.objects.select_for_update().get(pk=activity.pk)
        if replacement_partner_id:
            _assert_replacement_eligible(assignment, replacement_partner_id)

        withdrawal.approved_by = getattr(principal, "id", "") or ""
        withdrawal.approved_at = timezone.now()
        withdrawal.save(update_fields=["approved_by", "approved_at", "updated_at"])

        _perform(withdrawal, assignment, activity, principal, replacement_partner_id)

    _announce(withdrawal, principal)
    return withdrawal


def _notify_reviewer(withdrawal) -> None:
    """Put the request on the supervising PL's desk."""
    from apps.accounts.models import StaffProfile
    from apps.notifications.models import Notification

    if not withdrawal.supervising_pl_id:
        return
    profile = (
        StaffProfile.objects.filter(id=withdrawal.supervising_pl_id)
        .select_related("user")
        .first()
    )
    if profile is None or not profile.user_id:
        return

    school = getattr(withdrawal.school, "name", "") or "a school"
    Notification.objects.update_or_create(
        recipient_id=profile.user_id,
        context_type="PartnerAssignmentWithdrawal",
        context_id=withdrawal.id,
        source_event_type="partner_withdrawal.requested",
        defaults={
            "recipient_role": "Program Lead",
            "title": f"Withdrawal requested — {school}",
            "body": (
                f"{withdrawal.get_reason_category_display()}. "
                f"{withdrawal.partner_facing_reason}"
            ),
            "category": "planning",
            "target_route": "/partner-oversight/?queue=withdrawal_requests",
            "action_label": "Review request",
            "action_required": True,
            "priority": "high",
            "status": "unread",
            "read_at": None,
        },
    )


# ── Holding a partner off new work ───────────────────────────────────────────
def place_hold(partner_id: str, data: dict, principal):
    """Stop new assignments reaching a partner. Touch nothing they already hold.

    Separate from withdrawal on purpose, and the separation is the safety: a
    single "suspend partner" control that also cancelled live work would strip
    support from every school they serve in one click, and tell a partner
    part-way through a visit by way of a cancelled activity.

    Each existing assignment still has to be reviewed on its own merits, with
    its own reason and its own record. This only closes the door to new ones.
    """
    from apps.core.permissions import has_permission
    from apps.core.rbac import Permission
    from apps.partners.models import Partner
    from apps.partners.withdrawal_models import PartnerHold

    if not has_permission(principal, Permission.PARTNER_HOLD.value):
        raise Forbidden("Your role cannot hold a partner from new assignments.")

    reason_category = ((data or {}).get("reason_category") or "").strip()
    if reason_category not in WithdrawalReason.values:
        raise BadRequest("Choose a reason category.")
    reason = ((data or {}).get("reason") or "").strip()
    if len(reason) < REASON_MIN_LENGTH:
        raise BadRequest(f"Explain the hold (at least {REASON_MIN_LENGTH} characters).")

    effective_from = (data or {}).get("effective_from") or timezone.localdate()
    review_on = (data or {}).get("review_on")
    if not review_on:
        # A hold with no review date is a quiet offboarding. Requiring one
        # forces somebody to come back to the decision rather than letting it
        # harden into permanence by inattention.
        raise BadRequest(
            "Set a review date. A hold with no review date becomes a permanent "
            "block nobody ever decided to make."
        )

    partner = Partner.objects.filter(id=partner_id, deleted_at__isnull=True).first()
    if partner is None:
        raise NotFoundError("Partner not found.")

    with transaction.atomic():
        existing = PartnerHold.objects.filter(
            partner=partner, lifted_at__isnull=True
        ).first()
        if existing is not None:
            return existing

        hold = PartnerHold.objects.create(
            partner=partner,
            reason_category=reason_category,
            reason=reason,
            internal_note=((data or {}).get("internal_note") or "").strip(),
            requested_by=getattr(principal, "id", "") or "",
            requested_by_role=getattr(principal, "active_role", "") or "",
            effective_from=effective_from,
            review_on=review_on,
        )

    from apps.audit.services import log as audit_log

    audit_log(
        action="partner.hold_placed",
        subject_kind="PartnerHold",
        subject_id=hold.id,
        actor_id=hold.requested_by or "unknown",
        actor_role=hold.requested_by_role,
        success=True,
        payload={
            "partner_id": partner.id,
            "reason_category": reason_category,
            "review_on": str(review_on),
            # Stated explicitly so the audit record shows what this did NOT do.
            "existing_assignments_affected": 0,
        },
    )
    return hold


def lift_hold(partner_id: str, principal):
    """Let new assignments reach this partner again."""
    from apps.core.permissions import has_permission
    from apps.core.rbac import Permission
    from apps.partners.withdrawal_models import PartnerHold

    if not has_permission(principal, Permission.PARTNER_HOLD.value):
        raise Forbidden("Your role cannot lift a partner hold.")

    hold = PartnerHold.objects.filter(
        partner_id=partner_id, lifted_at__isnull=True
    ).first()
    if hold is None:
        raise NotFoundError("This partner is not on hold.")

    hold.lifted_at = timezone.now()
    hold.lifted_by = getattr(principal, "id", "") or ""
    hold.save(update_fields=["lifted_at", "lifted_by", "updated_at"])
    return hold


def assert_partner_accepts_new_work(partner_id: str) -> None:
    """Refuse a new assignment to a partner who is on hold.

    Called at assignment creation. Enforced here rather than by hiding the
    partner from a dropdown, because a hidden option is not a rule — the
    direct route, the API and a bulk action all reach the same check.
    """
    from apps.partners.withdrawal_models import PartnerHold

    hold = (
        PartnerHold.objects.filter(partner_id=partner_id, lifted_at__isnull=True)
        .select_related("partner")
        .first()
    )
    if hold is None:
        return
    raise ConflictError(
        f"{hold.partner.name} is on hold for new assignments until "
        f"{hold.review_on:%-d %b %Y}. Their existing work is unaffected."
    )
