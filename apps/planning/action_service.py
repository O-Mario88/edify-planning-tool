"""Sending, tracking and closing school actions.

Four things happen when somebody presses "Send to <staff>", and they must
happen together or not at all: the TeamAction is written, the recipient is
notified, a contextual message thread carries the ask in the recipient's own
words, and the audit chain records who delegated what to whom. `send_action`
does all four inside one transaction, and the school leaves the urgent card
only because the TeamAction row now exists — not as a separate step that could
succeed while the record failed.

The reverse direction is `resolve_due_actions`, which re-reads each condition
from its source of truth and closes what is genuinely fixed. Resolution is
therefore something the system *observes*. A recipient cannot make a school's
missing SSA go away by marking a row done; they make it go away by doing the
SSA, and the sweep notices.
"""

from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.planning.action_models import (
    ACTIVE_STATES,
    ActionPriority,
    ActionState,
    TeamAction,
)

logger = logging.getLogger(__name__)


class ActionError(Exception):
    """Refusal to create or transition an action. Carries a message meant for
    the person who pressed the button, not a stack trace."""


# How long the recipient has, by severity. Deliberately short: these are the
# schools already flagged as needing urgent attention, so a fortnight's grace
# would make "urgent" meaningless. Overridable per send.
DEFAULT_DUE_DAYS = {"critical": 3, "high": 5, "warning": 7, "normal": 10}

# What the recipient is being asked to do, and where they do it. Keyed by the
# issue types `urgent_attention.resolve_urgent_issue` emits, so a new issue
# type that forgets to register here fails loudly in the send path rather than
# quietly producing an action with no route.
ISSUE_PLAYBOOK: dict[str, dict[str, str]] = {
    "no_ssa": {
        "action": "Complete a School Self-Assessment",
        "route": "/planning/schedule-modal?school_id={school_ref}",
        "why": "No confirmed SSA exists for this school this financial year, "
        "so no intervention performance can be determined.",
    },
    "low_ssa": {
        "action": "Schedule a coaching visit",
        "route": "/planning/schedule-modal?school_id={school_ref}",
        "why": "The school's SSA scores place it below the acceptable band.",
    },
    "no_visit_or_training": {
        "action": "Schedule the school's visit and training",
        "route": "/planning/schedule-modal?school_id={school_ref}",
        "why": "A verified SSA exists but none of the required support has "
        "been completed.",
    },
    "no_training": {
        "action": "Schedule the school's training",
        "route": "/planning/schedule-modal?school_id={school_ref}",
        "why": "The school has had no completed training this financial year.",
    },
    "no_visit": {
        "action": "Schedule the school's visit",
        "route": "/planning/schedule-modal?school_id={school_ref}",
        "why": "The school has had no completed visit this financial year.",
    },
    "intervention_critical": {
        "action": "Act on the school's critical intervention area",
        "route": "/schools/{school_pk}",
        "why": "The school's weakest intervention area is in the Critical band.",
    },
    "intervention_warning": {
        "action": "Act on the school's weak intervention area",
        "route": "/schools/{school_pk}",
        "why": "The school's weakest intervention area is in the Warning band.",
    },
    "intervention_follow_up": {
        "action": "Follow up on the school's intervention areas",
        "route": "/schools/{school_pk}",
        "why": "The school's intervention areas need follow-up.",
    },
}

# Conditions the system can settle by querying. Everything outside this set
# needs a human to say why it is closed, and says so in the audit trail.
SYSTEM_VERIFIABLE = frozenset(ISSUE_PLAYBOOK) - {"intervention_follow_up"}


# ── Who is responsible ───────────────────────────────────────────────────────


class ResponsibleActorService:
    """Answers "whose school is this?".

    Assignment is the only answer that counts. A school with no assigned staff
    member has no responsible actor, and the correct response to that is to
    refuse the send and say so — inventing a recipient (the sender, their
    supervisor, whoever is nearest) would manufacture an accountability record
    against someone who never agreed to own the work.
    """

    @staticmethod
    def for_school(school_id: str, *, within_staff_ids=None):
        """Return the (StaffProfile, role) that owns this school, or (None, "").

        `within_staff_ids` restricts the answer to the sender's own span of
        control, so a PL delegating always delegates to one of their own team
        rather than to whoever happens to hold the assignment.
        """
        from apps.accounts.models import StaffSchoolAssignment

        qs = StaffSchoolAssignment.objects.filter(school_id=school_id)
        if within_staff_ids is not None:
            qs = qs.filter(staff_id__in=within_staff_ids)
        assignment = qs.select_related("staff__user").order_by("created_at").first()
        if not assignment or not assignment.staff or not assignment.staff.user_id:
            return None, ""
        staff = assignment.staff
        # Role is a User attribute, not a StaffProfile one — the profile holds
        # employment facts, the user holds what they are currently acting as.
        return staff, getattr(getattr(staff, "user", None), "active_role", "") or ""


# ── Sending ──────────────────────────────────────────────────────────────────


def _due_date(severity: str, days: int | None) -> "timezone.datetime.date":
    from datetime import timedelta

    span = days if days is not None else DEFAULT_DUE_DAYS.get(severity, 5)
    return timezone.localdate() + timedelta(days=span)


def _priority_for(severity: str) -> str:
    if severity == "critical":
        return ActionPriority.URGENT
    if severity == "high":
        return ActionPriority.HIGH
    return ActionPriority.NORMAL


@transaction.atomic
def send_action(
    *,
    sender,
    school,
    issue: dict,
    fy: str,
    recipient_staff=None,
    note: str = "",
    due_days: int | None = None,
    month_of_fy: int | None = None,
    within_staff_ids=None,
) -> TeamAction:
    """Delegate one urgent condition. Raises ActionError instead of half-doing it.

    `issue` is a row from `urgent_attention.resolve_urgent_issue` — it already
    carries the condition key, severity and issue type, so nothing is
    recomputed here and the two can never disagree about what was sent.
    """
    issue_type = issue.get("key") or ""
    key = issue.get("condition_key") or ""
    if not key:
        raise ActionError("This issue has no condition key and cannot be tracked.")

    playbook = ISSUE_PLAYBOOK.get(issue_type)
    if not playbook:
        raise ActionError(
            f"'{issue_type}' has no defined follow-up action, so it cannot be "
            "delegated. Register it in ISSUE_PLAYBOOK first."
        )

    resolved_role = ""
    if recipient_staff is None:
        recipient_staff, resolved_role = ResponsibleActorService.for_school(
            school.id, within_staff_ids=within_staff_ids
        )
    if not recipient_staff or not recipient_staff.user_id:
        raise ActionError(
            "This school has no assigned staff member, so there is nobody to "
            "hold responsible. Assign the school first."
        )

    # The idempotency check. Doing it before the write turns the common case
    # (a double-click, or PL and IA both looking at the same card) into a
    # clear answer rather than a database error page.
    existing = TeamAction.objects.filter(
        condition_key=key, state__in=ACTIVE_STATES
    ).first()
    if existing:
        raise ActionError(
            f"Already sent to {_name_of(existing.recipient_id)} on "
            f"{existing.created_at:%-d %b}. It is tracked under Actions Sent."
        )

    severity = issue.get("severity") or "critical"
    recipient_role = (
        resolved_role
        or getattr(getattr(recipient_staff, "user", None), "active_role", "")
        or ""
    )
    school_ref = getattr(school, "school_id", "") or school.id
    route = playbook["route"].format(school_ref=school_ref, school_pk=school.id)

    # Chain a recurrence to whatever closed last time, so "third time this
    # year" is answerable without reopening and overwriting a closed record.
    previous = (
        TeamAction.objects.filter(condition_key=key)
        .exclude(state__in=ACTIVE_STATES)
        .order_by("-created_at")
        .first()
    )

    try:
        action = TeamAction.objects.create(
            condition_key=key,
            issue_type=issue_type,
            severity=severity,
            school_id=school.id,
            fy=fy,
            month_of_fy=month_of_fy,
            related_ssa_id=issue.get("related_ssa_id") or None,
            related_activity_id=issue.get("related_activity_id") or None,
            sender_id=getattr(sender, "id", "") or "",
            sender_role=getattr(sender, "active_role", "") or "",
            recipient_id=recipient_staff.user_id,
            recipient_role=recipient_role,
            requested_action=playbook["action"],
            workflow_route=route,
            message=note.strip(),
            priority=_priority_for(severity),
            due_date=_due_date(severity, due_days),
            state=ActionState.OPEN,
            detected_at=timezone.now(),
            supersedes_id=previous.id if previous else None,
        )
    except IntegrityError as exc:
        # The partial unique index caught a race the pre-check could not: two
        # senders inside overlapping transactions. Same outcome, same message.
        raise ActionError(
            "Someone else just sent this same issue. It is tracked under "
            "Actions Sent."
        ) from exc

    _announce(action, sender=sender, school=school, issue=issue, playbook=playbook)
    return action


def _announce(action: TeamAction, *, sender, school, issue, playbook) -> None:
    """Notification, contextual message and audit event for a new action.

    Runs inside `send_action`'s transaction on purpose. The mandate's point is
    that a transient notification must never be the only responsibility record;
    the corollary is that a TeamAction the recipient was never told about is
    just as broken, so these are not best-effort side effects.
    """
    from apps.audit.services import log
    from apps.messaging.services import workflow_message
    from apps.notifications.models import Notification

    sender_name = getattr(sender, "name", None) or "A colleague"
    why = issue.get("detail") or playbook["why"]
    due = (
        action.due_date.strftime("%-d %b") if action.due_date else "as soon as possible"
    )
    body = (
        f"{sender_name} asked you to {playbook['action'].lower()} at "
        f"{school.name}. {why} Due {due}."
    )

    Notification.objects.update_or_create(
        recipient_id=action.recipient_id,
        context_type="TeamAction",
        context_id=action.id,
        source_event_type="school_action_assigned",
        defaults={
            "recipient_role": action.recipient_role,
            "title": f"Action required: {school.name}",
            "body": body,
            "category": "planning",
            # Straight to the work, not to a dashboard the recipient then has
            # to search. A responsibility without a route is a scavenger hunt.
            "target_route": action.workflow_route,
            "action_label": action.requested_action,
            "action_required": True,
            "priority": action.priority,
            "status": "unread",
            "source_event_id": action.id,
            "read_at": None,
        },
    )

    workflow_message(
        context_type="School",
        context_id=school.id,
        subject=f"Urgent action: {school.name}",
        body=body + (f"\n\n{action.message}" if action.message else ""),
        recipient_ids=[action.recipient_id],
        category="planning",
        priority=action.priority,
        sender_id=getattr(sender, "id", None),
    )

    log(
        action="school_action.sent",
        subject_kind="TeamAction",
        subject_id=action.id,
        actor_id=getattr(sender, "id", None),
        actor_role=getattr(sender, "active_role", None),
        payload={
            "condition_key": action.condition_key,
            "issue_type": action.issue_type,
            "school_id": action.school_id,
            "recipient_id": action.recipient_id,
            "due_date": str(action.due_date),
        },
    )


def _name_of(user_id: str) -> str:
    from apps.accounts.models import User

    return (
        User.objects.filter(id=user_id).values_list("name", flat=True).first()
        or "a colleague"
    )


# ── Lifecycle ────────────────────────────────────────────────────────────────


def _transition(action: TeamAction, state: str, actor, *, fields=None, **extra):
    from apps.audit.services import log

    action.state = state
    for attr, value in extra.items():
        setattr(action, attr, value)
    action.save(update_fields=["state", "updated_at", *(fields or [])])
    log(
        action=f"school_action.{state}",
        subject_kind="TeamAction",
        subject_id=action.id,
        actor_id=getattr(actor, "id", None),
        actor_role=getattr(actor, "active_role", None),
        payload={"condition_key": action.condition_key},
    )
    return action


def acknowledge(action: TeamAction, actor) -> TeamAction:
    if action.state != ActionState.OPEN:
        return action
    return _transition(
        action,
        ActionState.ACKNOWLEDGED,
        actor,
        fields=["acknowledged_at"],
        acknowledged_at=timezone.now(),
    )


def start(action: TeamAction, actor) -> TeamAction:
    if action.state not in (
        ActionState.OPEN,
        ActionState.ACKNOWLEDGED,
        ActionState.BLOCKED,
        ActionState.OVERDUE,
    ):
        return action
    return _transition(
        action,
        ActionState.IN_PROGRESS,
        actor,
        fields=["started_at"],
        started_at=action.started_at or timezone.now(),
    )


def block(action: TeamAction, actor, reason: str) -> TeamAction:
    reason = (reason or "").strip()
    if not reason:
        raise ActionError("Say what is blocking this before marking it blocked.")
    return _transition(
        action,
        ActionState.BLOCKED,
        actor,
        fields=["blocked_reason"],
        blocked_reason=reason,
    )


def return_to_sender(action: TeamAction, actor, reason: str) -> TeamAction:
    """Decline ownership. The condition returns to the unassigned queue.

    This is the honest alternative to sitting on an action that was misrouted.
    Because RETURNED is not an active state, the school reappears on the
    urgent card for someone to route correctly — which is the point.
    """
    reason = (reason or "").strip()
    if not reason:
        raise ActionError("Say why you are returning this before sending it back.")
    if action.state not in ACTIVE_STATES:
        raise ActionError("This action is already closed.")
    _transition(
        action,
        ActionState.RETURNED,
        actor,
        fields=["returned_reason", "resolved_at"],
        returned_reason=reason,
        resolved_at=timezone.now(),
    )
    _notify(
        action.sender_id,
        title="Action returned",
        body=(
            f"{getattr(actor, 'name', 'The recipient')} returned "
            f"{action.requested_action.lower()} at {_school_name(action.school_id)}: "
            f"{reason}"
        ),
        action_id=action.id,
        route="/planning/actions-sent",
        event="school_action_returned",
    )
    return action


def cancel(action: TeamAction, actor, reason: str = "") -> TeamAction:
    """Withdraw an action you sent. Only the sender may — a recipient who
    disagrees returns it, which keeps their reason on the record."""
    if getattr(actor, "id", None) != action.sender_id and getattr(
        actor, "active_role", ""
    ) not in ("Admin", "CountryDirector"):
        raise ActionError("Only the person who sent this action can cancel it.")
    if action.state not in ACTIVE_STATES:
        raise ActionError("This action is already closed.")
    _transition(
        action,
        ActionState.CANCELLED,
        actor,
        fields=["returned_reason", "resolved_at"],
        returned_reason=(reason or "").strip(),
        resolved_at=timezone.now(),
    )
    _notify(
        action.recipient_id,
        title="Action withdrawn",
        body=(
            f"{getattr(actor, 'name', 'The sender')} withdrew "
            f"{action.requested_action.lower()} at {_school_name(action.school_id)}."
        ),
        action_id=action.id,
        route="/planning/my-actions",
        event="school_action_cancelled",
    )
    return action


def resolve_manually(action: TeamAction, actor, reason: str) -> TeamAction:
    """Close a condition no query can settle.

    Refused outright for system-verifiable conditions. "No SSA" is closed by
    doing an SSA; letting anyone assert otherwise would let the queue be
    cleared without a single school being helped, which is precisely the
    failure this system exists to prevent.
    """
    if action.issue_type in SYSTEM_VERIFIABLE:
        raise ActionError(
            f"'{action.issue_type}' is verified from the record and closes on "
            "its own once the work is done. It cannot be marked resolved by hand."
        )
    reason = (reason or "").strip()
    if not reason:
        raise ActionError("A manual resolution needs a reason.")
    return _transition(
        action,
        ActionState.RESOLVED,
        actor,
        fields=["resolved_at", "manual_resolution_reason", "resolved_by_system"],
        resolved_at=timezone.now(),
        manual_resolution_reason=reason,
        resolved_by_system=False,
    )


def _school_name(school_id: str) -> str:
    from apps.schools.models import School

    return (
        School.objects.filter(id=school_id).values_list("name", flat=True).first()
        or "the school"
    )


def _notify(recipient_id, *, title, body, action_id, route, event) -> None:
    from apps.notifications.models import Notification

    if not recipient_id:
        return
    Notification.objects.update_or_create(
        recipient_id=recipient_id,
        context_type="TeamAction",
        context_id=action_id,
        source_event_type=event,
        defaults={
            "title": title,
            "body": body,
            "category": "planning",
            "target_route": route,
            "priority": "high",
            "status": "unread",
            "source_event_id": action_id,
            "read_at": None,
        },
    )


# ── Closing the loop ─────────────────────────────────────────────────────────


def condition_still_holds(action: TeamAction) -> bool:
    """Re-read the source of truth. True means the problem is still there.

    Delegates to the same resolver the card uses rather than reimplementing
    the checks — two definitions of "has an SSA" would eventually disagree,
    and the disagreement would show up as actions that never close.
    """
    from apps.planning.urgent_attention import _TRAINING_TYPES, _VISIT_TYPES
    from apps.ssa.models import SsaRecord
    from apps.targets.my_targets import IA_VERIFIED_STATUSES

    if action.issue_type not in SYSTEM_VERIFIABLE:
        return True  # not ours to settle; a human closes it

    has_ssa = SsaRecord.objects.filter(
        school_id=action.school_id,
        fy=action.fy,
        verification_status="confirmed",
        deleted_at__isnull=True,
    ).exists()

    if action.issue_type == "no_ssa":
        return not has_ssa

    from apps.activities.models import Activity

    def _done(kinds) -> bool:
        return Activity.objects.filter(
            school_id=action.school_id,
            activity_type__in=kinds,
            fy=action.fy,
            status__in=IA_VERIFIED_STATUSES,
            deleted_at__isnull=True,
        ).exists()

    if action.issue_type == "no_visit":
        return not _done(_VISIT_TYPES)
    if action.issue_type == "no_training":
        return not _done(_TRAINING_TYPES)
    if action.issue_type == "no_visit_or_training":
        return not (_done(_VISIT_TYPES) or _done(_TRAINING_TYPES))

    if action.issue_type in (
        "low_ssa",
        "intervention_critical",
        "intervention_warning",
    ):
        # An intervention condition clears when the school's score in THAT
        # area leaves the band that raised it. Comparing against the school's
        # current weakest area instead would close the action the moment some
        # other area became worse, which is not the same thing at all.
        return _intervention_still_weak(action)

    return True


def _intervention_still_weak(action: TeamAction) -> bool:
    from apps.core.enums import ssa_score_band
    from apps.ssa.recommendation_engine import prioritized_interventions
    from apps.schools.models import School

    school = School.objects.filter(id=action.school_id).first()
    if not school:
        return False  # the school is gone; nothing left to act on

    area = ""
    for part in action.condition_key.split("|"):
        if part.startswith("area:"):
            area = part[5:]
            break

    ranked = prioritized_interventions(school, n=20) or []
    if not ranked:
        return False
    if area:
        match = next((r for r in ranked if r.get("intervention") == area), None)
        if match is None:
            return False  # that area no longer ranks as a problem
        score = match.get("score")
    else:
        score = ranked[0].get("score")

    if score is None:
        return True
    band = ssa_score_band(score)[0]
    if action.issue_type == "intervention_warning":
        return band in ("Critical", "Warning")
    return band == "Critical"


def resolve_due_actions(*, limit: int | None = None) -> dict:
    """Close every active action whose condition has genuinely cleared.

    Idempotent and safe to run often. Returns counts rather than logging into
    the void so the management command and System Health can both report it.
    """
    from apps.audit.services import log

    qs = TeamAction.objects.filter(state__in=ACTIVE_STATES).order_by("created_at")
    if limit:
        qs = qs[:limit]

    checked = resolved = 0
    for action in qs:
        checked += 1
        try:
            if condition_still_holds(action):
                continue
        except Exception:  # noqa: BLE001
            # One school with bad data must not stop the sweep for everyone.
            logger.exception("Could not evaluate action %s", action.id)
            continue
        action.state = ActionState.RESOLVED
        action.resolved_at = timezone.now()
        action.resolved_by_system = True
        action.save(
            update_fields=["state", "resolved_at", "resolved_by_system", "updated_at"]
        )
        resolved += 1
        log(
            action="school_action.auto_resolved",
            subject_kind="TeamAction",
            subject_id=action.id,
            payload={
                "condition_key": action.condition_key,
                "issue_type": action.issue_type,
            },
        )
        _notify(
            action.sender_id,
            title="Action resolved",
            body=(
                f"{action.requested_action} at {_school_name(action.school_id)} "
                "is done — the record now confirms it."
            ),
            action_id=action.id,
            route="/planning/actions-sent",
            event="school_action_resolved",
        )
    return {"checked": checked, "resolved": resolved}


def mark_overdue_actions() -> dict:
    """Flip past-due actions to OVERDUE and tell both parties.

    Kept separate from escalation: being late is the recipient's business,
    escalating is the sender's decision. Collapsing them would escalate every
    action that slipped by a day.
    """
    today = timezone.localdate()
    qs = TeamAction.objects.filter(
        state__in=[
            ActionState.OPEN,
            ActionState.ACKNOWLEDGED,
            ActionState.IN_PROGRESS,
            ActionState.BLOCKED,
        ],
        due_date__lt=today,
    )
    count = 0
    for action in qs:
        action.state = ActionState.OVERDUE
        action.save(update_fields=["state", "updated_at"])
        count += 1
        _notify(
            action.recipient_id,
            title="Action overdue",
            body=(
                f"{action.requested_action} at {_school_name(action.school_id)} "
                f"was due {action.due_date:%-d %b}."
            ),
            action_id=action.id,
            route=action.workflow_route,
            event="school_action_overdue",
        )
        _notify(
            action.sender_id,
            title="Action overdue",
            body=(
                f"{_name_of(action.recipient_id)} has not completed "
                f"{action.requested_action.lower()} at "
                f"{_school_name(action.school_id)}."
            ),
            action_id=action.id,
            route="/planning/actions-sent",
            event="school_action_overdue_sender",
        )
    return {"overdue": count}


def escalate(action: TeamAction, actor, to_user_id: str = "") -> TeamAction:
    """Raise an overdue action to the sender's supervisor.

    Escalation does not move ownership. The recipient still owes the work; one
    more person now knows they owe it.
    """
    if action.state not in ACTIVE_STATES:
        raise ActionError("This action is already closed.")
    target = to_user_id or _supervisor_of(action.sender_id)
    if not target:
        raise ActionError("No supervisor is recorded above the sender to escalate to.")
    _transition(
        action,
        ActionState.ESCALATED,
        actor,
        fields=["escalated_at", "escalated_to_id"],
        escalated_at=timezone.now(),
        escalated_to_id=target,
    )
    _notify(
        target,
        title="Escalated action",
        body=(
            f"{action.requested_action} at {_school_name(action.school_id)} is "
            f"overdue with {_name_of(action.recipient_id)}."
        ),
        action_id=action.id,
        route="/planning/actions-sent",
        event="school_action_escalated",
    )
    return action


def _supervisor_of(user_id: str) -> str:
    """The direct reporting line above a user, via the supervisor join table.

    Returns "" rather than guessing when there is no line recorded — escalating
    to an arbitrary senior person would put a demand on someone's desk that
    nothing in the org chart says is theirs.
    """
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    staff = StaffProfile.objects.filter(user_id=user_id).first()
    if not staff:
        return ""
    link = (
        StaffSupervisorAssignment.objects.filter(supervisee_id=staff.id)
        .select_related("supervisor__user")
        .order_by("created_at")
        .first()
    )
    return getattr(getattr(link, "supervisor", None), "user_id", "") or ""
