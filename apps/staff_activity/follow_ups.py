"""Manager follow-ups from the Staff Activity Log (owner, 2026-09-29; §9).

The routes follow the supervision model the rest of the platform uses:

* A manager (a Programme Lead with their officers) follows up with a person
  they supervise. The person is told, and the follow-up is on their To-Do
  list until it is resolved.
* A Country Director who sees a concern about an officer sends it to the
  officer's Programme Lead — never around them. The Lead acknowledges it and
  follows up with the officer; the Director watches it resolve.

A follow-up is support. Nothing here marks anyone absent, lowers a score or
opens a performance plan.

Every transition is written to the audit chain and to the follow-up's own
history. Notifications go through the platform's notification service
(idempotent per follow-up), and are resolved when the follow-up is.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import (
    OPEN_STATUSES,
    FollowUpPriority,
    FollowUpRoute,
    FollowUpStatus,
    FollowUpTrigger,
    StaffUsageFollowUp,
)

logger = logging.getLogger(__name__)

NOTIFY_EVENT = "staff_activity.follow_up"
CONTEXT_TYPE = "StaffUsageFollowUp"

# Conditions the platform can see resolve on its own (§9.5): the person signs
# in, or does the kind of work the follow-up asked about. A follow-up about a
# conversation, training or a usability problem is closed by a person.
AUTO_RESOLVE = {
    FollowUpTrigger.NO_LOGIN: "login",
    FollowUpTrigger.LOW_ENGAGEMENT: "action",
    FollowUpTrigger.PLANNING_NOT_DONE: "Planning",
    FollowUpTrigger.EVIDENCE_NOT_DONE: "Evidence",
}

# What each party may do, by state. "assignee" is who the follow-up is sent
# to; "creator" who sent it.
TRANSITIONS = {
    "acknowledge": {
        "label": "Acknowledge",
        "from": (FollowUpStatus.SENT, FollowUpStatus.ESCALATED),
        "to": FollowUpStatus.ACKNOWLEDGED,
        "by": "assignee",
    },
    "schedule_support": {
        "label": "Support scheduled",
        "from": (
            FollowUpStatus.SENT,
            FollowUpStatus.ACKNOWLEDGED,
            FollowUpStatus.WAITING_FOR_STAFF,
        ),
        "to": FollowUpStatus.SUPPORT_SCHEDULED,
        "by": "manager",
    },
    "wait_for_staff": {
        "label": "Waiting for staff",
        "from": (
            FollowUpStatus.SENT,
            FollowUpStatus.ACKNOWLEDGED,
            FollowUpStatus.SUPPORT_SCHEDULED,
        ),
        "to": FollowUpStatus.WAITING_FOR_STAFF,
        "by": "manager",
    },
    "return": {
        "label": "Return for clarification",
        "from": (FollowUpStatus.SENT, FollowUpStatus.ACKNOWLEDGED),
        "to": FollowUpStatus.RETURNED,
        "by": "assignee",
        "note_required": True,
    },
    "resend": {
        "label": "Send again",
        "from": (FollowUpStatus.RETURNED,),
        "to": FollowUpStatus.SENT,
        "by": "creator",
        "note_required": True,
    },
    "escalate": {
        "label": "Escalate to the Country Director",
        "from": (
            FollowUpStatus.SENT,
            FollowUpStatus.ACKNOWLEDGED,
            FollowUpStatus.SUPPORT_SCHEDULED,
            FollowUpStatus.WAITING_FOR_STAFF,
        ),
        "to": FollowUpStatus.ESCALATED,
        "by": "creator",
        "route": FollowUpRoute.MANAGER_TO_STAFF,
        "note_required": True,
    },
    "resolve": {
        "label": "Resolve",
        "from": OPEN_STATUSES,
        "to": FollowUpStatus.RESOLVED_BY_MANAGER,
        "by": "manager",
        "note_required": True,
    },
    "close": {
        "label": "Close",
        "from": (
            FollowUpStatus.RESOLVED_BY_ACTIVITY,
            FollowUpStatus.RESOLVED_BY_MANAGER,
        ),
        "to": FollowUpStatus.CLOSED,
        "by": "creator",
    },
    "cancel": {
        "label": "Cancel",
        "from": OPEN_STATUSES,
        "to": FollowUpStatus.CANCELED,
        "by": "creator",
        "note_required": True,
    },
}

RESOLVED_STATUSES = (
    FollowUpStatus.RESOLVED_BY_ACTIVITY,
    FollowUpStatus.RESOLVED_BY_MANAGER,
    FollowUpStatus.CLOSED,
    FollowUpStatus.CANCELED,
)


class FollowUpError(ValueError):
    """A follow-up the reader may not raise or move this way; the message is
    shown to them."""


# ── Who does what ────────────────────────────────────────────────────────────
def _party(follow_up: StaffUsageFollowUp, user) -> set[str]:
    """The reader's parts in this follow-up: creator, assignee, manager
    (whoever works the follow-up with the staff member: the creator on the
    manager route, the assignee on the Director's route)."""
    uid = getattr(user, "id", None)
    parts = set()
    if uid and uid == follow_up.created_by_id:
        parts.add("creator")
    if uid and uid == follow_up.assignee_id:
        parts.add("assignee")
    if follow_up.route == FollowUpRoute.MANAGER_TO_STAFF and "creator" in parts:
        parts.add("manager")
    if follow_up.route == FollowUpRoute.DIRECTOR_TO_MANAGER and "assignee" in parts:
        parts.add("manager")
    return parts


def can_view(follow_up: StaffUsageFollowUp, user) -> bool:
    if _party(follow_up, user):
        return True
    role = getattr(user, "active_role", "")
    if role == "CountryDirector":
        # The Director monitors every follow-up in the country, including the
        # ones a Lead escalated.
        from .services import can_read_person

        return can_read_person(user, follow_up.subject_id)
    if role == "Program Lead":
        # A Lead reads the follow-ups about the people they supervise.
        from .services import can_read_person

        return can_read_person(user, follow_up.subject_id)
    return False


def actions_for(follow_up: StaffUsageFollowUp, user) -> list[dict]:
    parts = _party(follow_up, user)
    out = []
    for key, rule in TRANSITIONS.items():
        if follow_up.status not in rule["from"] or rule["by"] not in parts:
            continue
        if rule.get("route") and rule["route"] != follow_up.route:
            continue
        # A Lead's own follow-up escalated to the Director waits on the
        # Director now.
        if follow_up.status == FollowUpStatus.ESCALATED and key == "acknowledge":
            if getattr(user, "active_role", "") != "CountryDirector":
                continue
        out.append(
            {
                "key": key,
                "label": rule["label"],
                "note_required": rule.get("note_required", False),
            }
        )
    if (
        follow_up.status == FollowUpStatus.ESCALATED
        and getattr(user, "active_role", "") == "CountryDirector"
    ):
        # The Director answers an escalation by resolving it or asking back.
        for key in ("acknowledge", "resolve"):
            if not any(a["key"] == key for a in out):
                rule = TRANSITIONS[key]
                out.append(
                    {
                        "key": key,
                        "label": rule["label"],
                        "note_required": rule.get("note_required", False),
                    }
                )
    return out


# ── Raising one ──────────────────────────────────────────────────────────────
def recipient_for(sender, subject) -> tuple[object, str]:
    """(assignee, route) for a follow-up this sender raises about this person.

    A Country Director's follow-up about someone a Programme Lead manages goes
    to that Lead (§9.3); about anyone else — a Lead themself, or a person no
    Lead manages — it goes to the person. A Lead's goes to their own staff.
    """
    from apps.accounts.models import User
    from apps.accounts.presence import _program_lead_of

    role = getattr(sender, "active_role", "")
    if role == "CountryDirector":
        lead_of, _ = _program_lead_of()
        lead_id = lead_of.get(subject.id)
        if lead_id and lead_id != sender.id:
            lead = User.objects.filter(pk=lead_id, is_active=True).first()
            if lead:
                return lead, FollowUpRoute.DIRECTOR_TO_MANAGER
    return subject, FollowUpRoute.MANAGER_TO_STAFF


def create_follow_up(
    sender,
    subject_id: str,
    *,
    trigger: str,
    note: str,
    priority: str,
    due_date,
    period: dict,
    snapshot: dict,
) -> StaffUsageFollowUp:
    from apps.accounts.models import User

    from .services import viewer_scope

    scope = viewer_scope(sender)
    if not scope or not scope["can_follow_up"]:
        raise FollowUpError(
            "Only a Programme Lead or the Country Director can send a follow-up."
        )
    if subject_id not in scope["ids"]:
        raise FollowUpError("You can follow up only with people in your scope.")
    if subject_id == scope.get("self_id"):
        raise FollowUpError("A follow-up is about someone else, not yourself.")
    if trigger not in FollowUpTrigger.values:
        raise FollowUpError("Choose what the follow-up is about.")
    if priority not in FollowUpPriority.values:
        raise FollowUpError("Choose a priority.")
    note = (note or "").strip()
    if not note:
        raise FollowUpError("Write a note for the person receiving it.")
    if not due_date:
        raise FollowUpError("Choose a due date.")
    if due_date < timezone.localdate():
        raise FollowUpError("The due date cannot be in the past.")
    subject = User.objects.get(pk=subject_id)
    assignee, route = recipient_for(sender, subject)
    open_same = StaffUsageFollowUp.objects.filter(
        subject=subject, trigger=trigger, status__in=OPEN_STATUSES
    ).first()
    if open_same:
        raise FollowUpError(
            f"A follow-up about this is already open ({open_same.get_status_display()})."
        )
    with transaction.atomic():
        follow_up = StaffUsageFollowUp.objects.create(
            subject=subject,
            assignee=assignee,
            created_by=sender,
            route=route,
            period_key=period["key"],
            period_start=period["start"],
            period_end=period["end"],
            trigger=trigger,
            snapshot=snapshot,
            note=note[:4000],
            priority=priority,
            due_date=due_date,
            history=[_entry(sender, FollowUpStatus.SENT, note)],
        )
        _audit("staff_activity.follow_up_sent", follow_up, sender, note=note)
        transaction.on_commit(lambda: _notify_assignee(follow_up))
    return follow_up


def transition(
    follow_up: StaffUsageFollowUp, user, action: str, note: str = ""
) -> StaffUsageFollowUp:
    allowed = {a["key"]: a for a in actions_for(follow_up, user)}
    if action not in allowed:
        raise FollowUpError("That step is not open to you on this follow-up.")
    rule = TRANSITIONS[action]
    note = (note or "").strip()
    if rule.get("note_required") and not note:
        raise FollowUpError("Add a note for this step.")
    to = rule["to"]
    with transaction.atomic():
        locked = StaffUsageFollowUp.objects.select_for_update().get(pk=follow_up.pk)
        if locked.status != follow_up.status:
            raise FollowUpError(
                "Someone else has just changed this follow-up; reload it."
            )
        locked.status = to
        locked.history = [*(locked.history or []), _entry(user, to, note)]
        fields = ["status", "history", "updated_at"]
        if to in RESOLVED_STATUSES and to != FollowUpStatus.CLOSED:
            locked.resolved_at = timezone.now()
            locked.resolved_by = user
            locked.resolution = note[:4000]
            fields += ["resolved_at", "resolved_by", "resolution"]
        locked.save(update_fields=fields)
        _audit(
            "staff_activity.follow_up_resolved"
            if to == FollowUpStatus.RESOLVED_BY_MANAGER
            else f"staff_activity.follow_up_{action}",
            locked,
            user,
            note=note,
        )
        transaction.on_commit(lambda: _after_transition(locked, action))
    return locked


def _after_transition(follow_up: StaffUsageFollowUp, action: str) -> None:
    if follow_up.status not in OPEN_STATUSES:
        _resolve_notifications(follow_up)
        return
    if action == "resend":
        _notify_assignee(follow_up)
    elif action == "escalate":
        _notify_directors(follow_up)
    elif action == "return":
        _notify(
            follow_up,
            [follow_up.created_by_id],
            title="Follow-up returned for clarification",
            body=f"{_name(follow_up.assignee)} asked for clarification about "
            f"{_trigger(follow_up)}.",
        )


# ── Resolution by activity (§9.5) ────────────────────────────────────────────
def resolve_by_activity(user, kind: str, *, module: str | None = None) -> int:
    """Close the open follow-ups about this person that the activity answers:
    a sign-in answers "no login"; a meaningful action answers "low
    engagement", and planning or evidence work the matching kind."""
    triggers = [
        t
        for t, needs in AUTO_RESOLVE.items()
        if needs == kind or (kind == "action" and module and needs == module)
    ]
    if not triggers:
        return 0
    rows = list(
        StaffUsageFollowUp.objects.filter(
            subject_id=getattr(user, "id", None),
            trigger__in=triggers,
            status__in=OPEN_STATUSES,
        ).exclude(status=FollowUpStatus.ESCALATED)
    )
    for follow_up in rows:
        _resolve_automatically(follow_up, reason=_auto_reason(kind, module))
    return len(rows)


def sweep_auto_resolutions(follow_ups) -> None:
    """Resolve the follow-ups whose condition the audit chain shows was met
    after they were sent — a meaningful action, or planning or evidence work.
    Run where follow-ups are listed, so a condition met anywhere in the
    platform closes the follow-up and its To-Do without a hook in every
    workflow."""
    from apps.audit.models import AuditLog

    from .registry import MEANINGFUL_ACTIONS

    pending = [
        fu
        for fu in follow_ups
        if fu.status in OPEN_STATUSES
        and fu.status != FollowUpStatus.ESCALATED
        and AUTO_RESOLVE.get(fu.trigger) not in (None, "login")
    ]
    if not pending:
        return
    earliest = min(fu.created_at for fu in pending)
    done = (
        AuditLog.objects.filter(
            actor_id__in={fu.subject_id for fu in pending},
            created_at__gte=earliest,
            action__in=list(MEANINGFUL_ACTIONS),
            success=True,
        )
        .values_list("actor_id", "action", "created_at")
        .order_by("created_at")
    )
    seen: dict[str, list[tuple[str, object]]] = {}
    for actor_id, action, at in done:
        seen.setdefault(actor_id, []).append((MEANINGFUL_ACTIONS[action].module, at))
    for fu in pending:
        need = AUTO_RESOLVE[fu.trigger]
        for module, at in seen.get(fu.subject_id, []):
            if at >= fu.created_at and (need == "action" or module == need):
                _resolve_automatically(
                    fu,
                    reason=_auto_reason("action", None if need == "action" else need),
                )
                break


def _auto_reason(kind: str, module: str | None) -> str:
    if kind == "login":
        return "Signed in."
    if module:
        return f"Completed {module.lower()} work."
    return "Completed a meaningful action."


def _resolve_automatically(follow_up: StaffUsageFollowUp, *, reason: str) -> None:
    with transaction.atomic():
        updated = StaffUsageFollowUp.objects.filter(
            pk=follow_up.pk, status=follow_up.status
        ).update(
            status=FollowUpStatus.RESOLVED_BY_ACTIVITY,
            resolved_at=timezone.now(),
            resolution=reason,
            history=[
                *(follow_up.history or []),
                _entry(None, FollowUpStatus.RESOLVED_BY_ACTIVITY, reason),
            ],
            updated_at=timezone.now(),
        )
        if not updated:
            return
        follow_up.status = FollowUpStatus.RESOLVED_BY_ACTIVITY
        _audit("staff_activity.follow_up_auto_resolved", follow_up, None, note=reason)
        transaction.on_commit(lambda: _after_auto_resolution(follow_up, reason))


def _after_auto_resolution(follow_up: StaffUsageFollowUp, reason: str) -> None:
    _resolve_notifications(follow_up)
    _notify(
        follow_up,
        [follow_up.created_by_id],
        title="Follow-up resolved",
        body=f"{_name(follow_up.subject)}: {_trigger(follow_up)} — {reason}",
        event="staff_activity.follow_up_resolved",
    )


# ── Lists ────────────────────────────────────────────────────────────────────
def queue_for(user) -> dict:
    """The follow-ups a reader works: sent to them, and sent by them."""
    from django.db.models import Q

    rows = list(
        StaffUsageFollowUp.objects.filter(Q(assignee=user) | Q(created_by=user))
        .select_related("subject", "assignee", "created_by")
        .order_by("due_date", "-created_at")[:200]
    )
    role = getattr(user, "active_role", "")
    if role == "CountryDirector":
        # Escalations from the Leads land with the Director.
        rows += list(
            StaffUsageFollowUp.objects.filter(status=FollowUpStatus.ESCALATED)
            .exclude(pk__in=[r.pk for r in rows])
            .select_related("subject", "assignee", "created_by")
        )
    sweep_auto_resolutions(rows)
    today = timezone.localdate()
    for fu in rows:
        fu.overdue = fu.is_open and fu.due_date < today
    open_rows = [fu for fu in rows if fu.is_open]
    return {
        "to_me": [
            fu
            for fu in open_rows
            if (fu.assignee_id == user.id and fu.status != FollowUpStatus.ESCALATED)
            or (fu.status == FollowUpStatus.ESCALATED and role == "CountryDirector")
        ],
        "from_me": [fu for fu in open_rows if fu.created_by_id == user.id],
        "recent_closed": [fu for fu in rows if not fu.is_open][:20],
        "open_count": len(open_rows),
    }


def open_count_for(user) -> int:
    from django.db.models import Q

    return (
        StaffUsageFollowUp.objects.filter(status__in=OPEN_STATUSES)
        .filter(Q(assignee=user) | Q(created_by=user))
        .count()
    )


# ── Helpers ──────────────────────────────────────────────────────────────────
def _entry(user, status, note: str) -> dict:
    return {
        "at": timezone.now().isoformat(),
        "by": getattr(user, "id", None),
        "by_name": _name(user) if user else "Platform",
        "status": str(status),
        "note": (note or "")[:1000],
    }


def _name(user) -> str:
    return (
        (getattr(user, "name", "") or getattr(user, "email", "") or "Someone")
        if user
        else "Someone"
    )


def _trigger(follow_up) -> str:
    return follow_up.get_trigger_display().lower()


def _audit(action: str, follow_up: StaffUsageFollowUp, user, *, note: str = "") -> None:
    from apps.audit.services import log

    log(
        action=action,
        subject_kind=CONTEXT_TYPE,
        subject_id=follow_up.pk,
        actor_id=getattr(user, "id", None),
        actor_role=getattr(user, "active_role", None) if user else None,
        payload={
            "subject_id": follow_up.subject_id,
            "assignee_id": follow_up.assignee_id,
            "trigger": follow_up.trigger,
            "status": follow_up.status,
            "route": follow_up.route,
            "note": (note or "")[:500],
        },
    )


def _notify(
    follow_up,
    recipient_ids,
    *,
    title: str,
    body: str,
    event: str = NOTIFY_EVENT,
    priority: str = "normal",
) -> None:
    try:
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event,
            "staff_activity",
            priority,
            title,
            body,
            context_type=CONTEXT_TYPE,
            context_id=follow_up.pk,
            recipients=[r for r in recipient_ids if r],
        )
    except Exception:  # pragma: no cover - a notice never breaks the workflow
        logger.exception("staff activity: follow-up notification failed")


def _notify_assignee(follow_up: StaffUsageFollowUp) -> None:
    if follow_up.route == FollowUpRoute.DIRECTOR_TO_MANAGER:
        title = f"Follow up with {_name(follow_up.subject)}"
        body = (
            f"{_name(follow_up.created_by)} asked you to follow up with "
            f"{_name(follow_up.subject)} about {_trigger(follow_up)}. Due "
            f"{follow_up.due_date:%d %b}."
        )
    else:
        title = "Your manager followed up with you"
        body = (
            f"{_name(follow_up.created_by)} followed up about "
            f"{_trigger(follow_up)}. Due {follow_up.due_date:%d %b}."
        )
    _notify(
        follow_up,
        [follow_up.assignee_id],
        title=title,
        body=body,
        priority="high" if follow_up.priority == FollowUpPriority.HIGH else "normal",
    )


def _notify_directors(follow_up: StaffUsageFollowUp) -> None:
    from apps.notifications.services import role_recipients

    directors = [u.id for u in role_recipients("CountryDirector")]
    _notify(
        follow_up,
        directors,
        title=f"Follow-up escalated: {_name(follow_up.subject)}",
        body=f"{_name(follow_up.created_by)} escalated a follow-up about {_trigger(follow_up)}.",
        event="staff_activity.follow_up_escalated",
    )


def _resolve_notifications(follow_up: StaffUsageFollowUp) -> None:
    try:
        from apps.notifications.services import resolve_condition

        resolve_condition(
            [NOTIFY_EVENT, "staff_activity.follow_up_escalated"],
            CONTEXT_TYPE,
            follow_up.pk,
        )
    except Exception:  # pragma: no cover
        logger.exception("staff activity: notification resolution failed")


def default_due_date():
    return timezone.localdate() + timedelta(days=3)
