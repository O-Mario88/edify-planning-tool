"""Escalation — the upward decision channel, one level at a time.

Flags travel CD→PL (a quality handoff to an operator). Strategy notes travel
RVP→CD (guidance downward). Nothing travelled upward, so a Country Director
facing a decision above their own authority had no route to the person who
holds it — the cockpit's "Escalate to RVP" button had no endpoint behind it.

This module is that route, and it now runs the whole reporting line rather
than only its top step: a CCEO or Project Coordinator raises to their
Programme Lead, a PL raises to the Country Director, and the CD raises to the
RVP as before. The addressee is resolved from supervision
(StaffSupervisorAssignment) so the item lands with the person who actually
manages the raiser; when no supervisor is on file it is addressed to the role
and any holder of that role in the country may pick it up — the way the RVP
has always been addressed.

It is deliberately small: raise, acknowledge, resolve-with-a-decision, and an
SLA sweep that pushes ageing items so the channel cannot silently rot the way
an unwatched queue does.
"""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from apps.audit.services import log as audit_log
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.rbac import EdifyRole

from .models import (
    EscalationAddressee,
    EscalationSeverity,
    EscalationStatus,
    LeadershipEscalation,
)


# How long an escalation may sit unacknowledged before it is surfaced as
# overdue. Matches the 7-day threshold the RVP dashboard already uses for
# ageing budget approvals, so leadership has one consistent sense of "late".
SLA_DAYS = {
    EscalationSeverity.CRITICAL.value: 2,
    EscalationSeverity.HIGH.value: 4,
    EscalationSeverity.NORMAL.value: 7,
}

CATEGORIES = [
    ("funding_gap", "Structural funding gap"),
    ("partner_performance", "Partner performance"),
    ("staffing", "Staffing / capacity"),
    ("project_direction", "Special project direction"),
    ("policy_exception", "Policy exception request"),
    ("regional_tradeoff", "Cross-region trade-off"),
    ("school_blocker", "School or cluster blocker"),
    ("other", "Other"),
]

# The three conditions this channel announces. Each is named so the transition
# that ends it can close it (INTG-03): the decider answering closes both the
# open queue item and the raiser's acknowledgement notice.
ESCALATION_OPEN = "leadership_escalation_open"
ESCALATION_ACKNOWLEDGED = "leadership_escalation_acknowledged"
ESCALATION_DECIDED = "leadership_escalation_decided"

DECISIONS = [
    ("approved", "Approved"),
    ("declined", "Declined"),
    ("deferred", "Deferred"),
    ("delegated_back", "Delegated back to the raiser"),
    ("noted", "Noted — no action required"),
]

# Who each raiser addresses: exactly one level up the reporting line. Admin
# keeps the original CD→RVP behaviour so the top of the channel is testable
# without a Country Director on file.
ADDRESSEE_FOR_RAISER = {
    EdifyRole.CCEO.value: EscalationAddressee.PROGRAM_LEAD.value,
    EdifyRole.PROJECT_COORDINATOR.value: EscalationAddressee.PROGRAM_LEAD.value,
    EdifyRole.COUNTRY_PROGRAM_LEAD.value: EscalationAddressee.COUNTRY_DIRECTOR.value,
    EdifyRole.COUNTRY_DIRECTOR.value: EscalationAddressee.REGIONAL_VICE_PRESIDENT.value,
    EdifyRole.ADMIN.value: EscalationAddressee.REGIONAL_VICE_PRESIDENT.value,
}

# The platform role that holds each addressee level.
ROLE_FOR_ADDRESSEE = {
    EscalationAddressee.PROGRAM_LEAD.value: EdifyRole.COUNTRY_PROGRAM_LEAD.value,
    EscalationAddressee.COUNTRY_DIRECTOR.value: EdifyRole.COUNTRY_DIRECTOR.value,
    EscalationAddressee.REGIONAL_VICE_PRESIDENT.value: (
        EdifyRole.REGIONAL_VICE_PRESIDENT.value
    ),
}

ADDRESSEE_FOR_ROLE = {role: level for level, role in ROLE_FOR_ADDRESSEE.items()}

ADDRESSEE_LABELS = dict(EscalationAddressee.choices)


def _actor_id(principal) -> str | None:
    return getattr(principal, "user_id", None) or getattr(principal, "id", None)


def _role(principal) -> str:
    return getattr(principal, "active_role", "") or ""


def _country_of(user_id: str | None) -> str | None:
    """The country on a user's staff profile, or None when nothing is on file."""
    if not user_id:
        return None
    try:
        from apps.accounts.models import StaffProfile

        return (
            StaffProfile.objects.filter(user_id=user_id, deleted_at__isnull=True)
            .values_list("country", flat=True)
            .first()
        )
    except Exception:  # noqa: BLE001 - accounts may be absent in a bare build
        return None


def addressee_for(principal) -> str | None:
    """The level a principal escalates to, or None when they cannot raise."""
    return ADDRESSEE_FOR_RAISER.get(_role(principal))


def resolve_addressee(principal) -> tuple[str | None, str | None, str | None]:
    """Where a raiser's escalation goes: (level, user id, display name).

    The person is the raiser's direct supervisor holding the addressee's role
    (a CCEO's Programme Lead, a PL's Country Director). The RVP is never named
    — a country has one RVP and the post changes hands — and neither is anyone
    when no supervisor is on file: the item is then addressed to the role.
    """
    level = addressee_for(principal)
    if not level:
        return None, None, None
    if level == EscalationAddressee.REGIONAL_VICE_PRESIDENT.value:
        return level, None, None
    role = ROLE_FOR_ADDRESSEE[level]
    try:
        from apps.accounts.models import StaffSupervisorAssignment

        link = (
            StaffSupervisorAssignment.objects.filter(
                supervisee__user_id=_actor_id(principal),
                supervisor__deleted_at__isnull=True,
            )
            .filter(
                Q(supervisor__user__active_role=role)
                | Q(supervisor__user__roles__contains=[role])
            )
            .select_related("supervisor__user")
            .first()
        )
    except Exception:  # noqa: BLE001
        link = None
    if not link:
        return level, None, None
    return level, link.supervisor.user_id, link.supervisor.user.name


def raise_escalation(data: dict, principal) -> LeadershipEscalation:
    """A raiser puts a decision in front of the level above them."""
    level, assignee_id, _assignee_name = resolve_addressee(principal)
    if not level:
        raise Forbidden(
            "Only field staff, Programme Leads and the Country Director may escalate."
        )

    subject = (data.get("subject") or "").strip()
    detail = (data.get("detail") or "").strip()
    if not subject:
        raise BadRequest("A subject is required.")
    if not detail:
        raise BadRequest(
            f"Describe what the {ADDRESSEE_LABELS[level]} needs to decide."
        )

    category = (data.get("category") or "other").strip()
    if category not in {c for c, _ in CATEGORIES}:
        raise BadRequest("Unknown escalation category.")

    severity = (data.get("severity") or EscalationSeverity.NORMAL.value).strip()
    if severity not in {s.value for s in EscalationSeverity}:
        raise BadRequest("Unknown severity.")

    esc = LeadershipEscalation.objects.create(
        raised_by_user_id=_actor_id(principal),
        raised_by_name=getattr(principal, "name", None),
        addressed_role=level,
        assigned_to_user_id=assignee_id,
        country_id=(
            data.get("country_id") or _country_of(_actor_id(principal)) or "Uganda"
        ),
        category=category,
        subject=subject[:255],
        detail=detail,
        requested_decision=(data.get("requested_decision") or "").strip()[:512] or None,
        severity=severity,
        scope_type=(data.get("scope_type") or "").strip() or None,
        scope_id=(data.get("scope_id") or "").strip() or None,
        scope_name=(data.get("scope_name") or "").strip() or None,
        due_date=data.get("due_date") or None,
    )
    _notify_addressees(esc)
    audit_log(
        action="escalation_raise",
        subject_kind="LeadershipEscalation",
        subject_id=esc.id,
        actor_id=_actor_id(principal),
        actor_role=_role(principal),
        payload={
            "subject": esc.subject,
            "category": esc.category,
            "severity": esc.severity,
            "addressedRole": esc.addressed_role,
            "assignedTo": esc.assigned_to_user_id,
        },
    )
    return esc


def acknowledge(escalation_id: str, principal) -> LeadershipEscalation:
    esc = _get_for_decider(escalation_id, principal)
    if esc.status != EscalationStatus.OPEN:
        raise BadRequest("This escalation has already been picked up.")
    esc.status = EscalationStatus.ACKNOWLEDGED
    esc.acknowledged_at = timezone.now()
    esc.acknowledged_by_user_id = _actor_id(principal)
    esc.save(
        update_fields=[
            "status",
            "acknowledged_at",
            "acknowledged_by_user_id",
            "updated_at",
        ]
    )
    _notify_raiser(
        esc,
        "Your escalation was acknowledged",
        esc.subject,
        ESCALATION_ACKNOWLEDGED,
    )
    audit_log(
        action="escalation_acknowledge",
        subject_kind="LeadershipEscalation",
        subject_id=esc.id,
        actor_id=_actor_id(principal),
        actor_role=_role(principal),
    )
    return esc


def resolve(escalation_id: str, data: dict, principal) -> LeadershipEscalation:
    """The addressee answers. A decision and a reason are both required — an
    escalation that closes with no recorded answer teaches the raiser not to
    use the channel again."""
    esc = _get_for_decider(escalation_id, principal)
    if esc.status == EscalationStatus.RESOLVED:
        raise BadRequest("This escalation is already resolved.")

    decision = (data.get("decision") or "").strip()
    if decision not in {d for d, _ in DECISIONS}:
        raise BadRequest("Select a decision.")
    note = (data.get("decision_note") or "").strip()
    if not note:
        raise BadRequest(
            "Record why — the raiser needs the reasoning, not just the verdict."
        )

    esc.status = EscalationStatus.RESOLVED
    esc.decision = decision
    esc.decision_note = note
    esc.resolved_at = timezone.now()
    if not esc.acknowledged_at:
        esc.acknowledged_at = timezone.now()
        esc.acknowledged_by_user_id = _actor_id(principal)
    esc.save()
    # The addressees no longer need to act on it, and the raiser's
    # "acknowledged" notice is answered by the decision it was waiting for
    # (INTG-03).
    try:
        from apps.notifications.services import resolve_condition

        resolve_condition(
            [ESCALATION_OPEN, ESCALATION_ACKNOWLEDGED], "escalation", esc.id
        )
    except Exception:  # noqa: BLE001
        pass
    _notify_raiser(
        esc,
        f"{ADDRESSEE_LABELS[esc.addressed_role]} decision: {dict(DECISIONS)[decision]}",
        f"{esc.subject} — {note[:200]}",
        ESCALATION_DECIDED,
    )
    audit_log(
        action="escalation_resolve",
        subject_kind="LeadershipEscalation",
        subject_id=esc.id,
        actor_id=_actor_id(principal),
        actor_role=_role(principal),
        reason=note,
        payload={"decision": decision, "subject": esc.subject},
    )
    return esc


def _addressed_to_me_q(principal) -> Q | None:
    """Rows a principal is the addressee of: named directly, or addressed to
    their role (unassigned) within their country. Admin is not a decider by
    role — they act through `_get_for_decider`'s override, not the inbox."""
    level = ADDRESSEE_FOR_ROLE.get(_role(principal))
    if not level:
        return None
    me = _actor_id(principal)
    q = Q(addressed_role=level, assigned_to_user_id=me)
    role_q = Q(addressed_role=level, assigned_to_user_id__isnull=True)
    if level != EscalationAddressee.REGIONAL_VICE_PRESIDENT.value:
        # PL/CD items addressed to the role stay inside the country; the RVP
        # sits above countries and reads them all, as before.
        country = _country_of(me)
        if country:
            role_q &= Q(country_id=country)
    return q | role_q


def can_decide(esc: LeadershipEscalation, principal) -> bool:
    """Whether this principal may acknowledge or resolve the escalation."""
    if _role(principal) == EdifyRole.ADMIN.value:
        return True
    if _actor_id(principal) == esc.raised_by_user_id:
        return False
    q = _addressed_to_me_q(principal)
    if q is None:
        return False
    return LeadershipEscalation.objects.filter(q, id=esc.id).exists()


def visible_to(principal):
    """Escalations a principal may read.

    Everyone sees what they raised. The addressee sees what is addressed to
    them — the RVP the whole RVP board, a PL their own inbox and never another
    PL's. The CD additionally reads, without acting on, what the Programme
    Leads in their country received, so a field problem that stalls at the PL
    is visible one level up. Admin sees everything.
    """
    role = _role(principal)
    qs = LeadershipEscalation.objects.all()
    if role == EdifyRole.ADMIN.value:
        return qs
    me = _actor_id(principal)
    q = Q(raised_by_user_id=me)
    inbox = _addressed_to_me_q(principal)
    if inbox is not None:
        q |= inbox
    if role == EdifyRole.COUNTRY_DIRECTOR.value:
        oversight = Q(addressed_role=EscalationAddressee.PROGRAM_LEAD.value)
        country = _country_of(me)
        if country:
            oversight &= Q(country_id=country)
        q |= oversight
    return qs.filter(q)


def board(principal) -> dict:
    """The escalation queue, split by what needs attention now."""
    qs = visible_to(principal)
    me = _actor_id(principal)
    decidable = _decidable_ids(qs, principal)
    rows = [
        _serialize(e, mine=(e.raised_by_user_id == me), can_decide=(e.id in decidable))
        for e in qs
    ]
    open_items = [r for r in rows if r["isOpen"]]
    level, assignee_id, assignee_name = resolve_addressee(principal)
    return {
        "open": open_items,
        "resolved": [r for r in rows if not r["isOpen"]][:20],
        "inbox": [r for r in open_items if r["canDecide"]],
        "raised": [r for r in rows if r["mine"]],
        "watching": [r for r in open_items if not r["canDecide"] and not r["mine"]],
        # What the reader decided, or watched being decided — their own
        # raised items already carry the decision in `raised`.
        "decided": [r for r in rows if not r["isOpen"] and not r["mine"]][:20],
        "overdue_count": sum(1 for r in open_items if r["isOverdue"]),
        "open_count": len(open_items),
        "inbox_count": sum(1 for r in open_items if r["canDecide"]),
        "raise_to": level,
        "raise_to_label": ADDRESSEE_LABELS.get(level) if level else None,
        "raise_to_user_id": assignee_id,
        "raise_to_name": assignee_name,
        "categories": CATEGORIES,
        "decisions": DECISIONS,
        "severities": [(s.value, s.label) for s in EscalationSeverity],
    }


def _decidable_ids(qs, principal) -> set[str]:
    if _role(principal) == EdifyRole.ADMIN.value:
        return set(qs.values_list("id", flat=True))
    q = _addressed_to_me_q(principal)
    if q is None:
        return set()
    return set(
        qs.filter(q)
        .exclude(raised_by_user_id=_actor_id(principal))
        .values_list("id", flat=True)
    )


def sweep_overdue() -> int:
    """Re-notify on escalations past their SLA.

    Run from the scheduler alongside the other daily jobs. Returns how many
    were pushed, so the job log says something useful.
    """
    pushed = 0
    for esc in LeadershipEscalation.objects.exclude(status=EscalationStatus.RESOLVED):
        if _is_overdue(esc):
            _notify_addressees(
                esc,
                title=f"Overdue escalation ({esc.age_days}d): {esc.subject}",
            )
            pushed += 1
    return pushed


def _is_overdue(esc: LeadershipEscalation) -> bool:
    limit = SLA_DAYS.get(esc.severity, SLA_DAYS[EscalationSeverity.NORMAL.value])
    return esc.status == EscalationStatus.OPEN and esc.age_days >= limit


def _get_for_decider(escalation_id: str, principal) -> LeadershipEscalation:
    esc = LeadershipEscalation.objects.filter(id=escalation_id).first()
    if not esc:
        raise NotFoundError("Escalation not found.")
    if not can_decide(esc, principal):
        raise Forbidden(
            f"Only the {ADDRESSEE_LABELS[esc.addressed_role]} this escalation is "
            "addressed to may act on it."
        )
    return esc


def _addressee_user_ids(esc: LeadershipEscalation) -> list[str]:
    """Who to tell about an escalation: the named person, or every active
    holder of the addressed role — in the escalation's country for PL/CD, and
    deployment-wide for the RVP, who sits above countries."""
    from apps.accounts.models import User

    if esc.assigned_to_user_id:
        return [esc.assigned_to_user_id]
    role = ROLE_FOR_ADDRESSEE.get(esc.addressed_role)
    if not role:
        return []
    holders = User.objects.filter(roles__contains=[role], status="active")
    if esc.addressed_role != EscalationAddressee.REGIONAL_VICE_PRESIDENT.value:
        in_country = holders.filter(staff_profile__country=esc.country_id)
        if in_country.exists():
            holders = in_country
    return [u.id for u in holders]


def _notify_addressees(esc: LeadershipEscalation, title: str | None = None) -> None:
    """Notify whoever the escalation is addressed to — once each, not once per
    run.

    This wrote a bare `create()` per RVP on every invocation, and the daily
    overdue sweep calls it for every still-open escalation. A single item open
    for thirty days produced thirty identical rows per RVP, and because the
    job is retryable with no transaction, one partial failure re-sent every
    escalation it had already processed. Routing through the canonical service
    gives it the dedupe key, the role-aware route, the audit row and the
    realtime publish that the raw insert skipped entirely.
    """
    try:
        from apps.notifications.services import WorkflowNotificationService

        recipients = _addressee_user_ids(esc)
        if not recipients:
            return
        WorkflowNotificationService.trigger(
            event_type=ESCALATION_OPEN,
            category="leadership",
            priority=(
                "high" if esc.severity != EscalationSeverity.NORMAL.value else "normal"
            ),
            title=title
            or f"Escalation from {esc.raised_by_name or 'a colleague'}: {esc.subject}",
            body=esc.detail[:300],
            context_type="escalation",
            context_id=esc.id,
            recipients=recipients,
        )
    except Exception:  # noqa: BLE001 - notification must never block the escalation
        pass


# The RVP-facing half keeps its historical name: the overdue-sweep bounding
# test reads this function's source to prove it goes through the canonical
# service, and the RVP is simply the top addressee of the same channel.
_notify_rvps = _notify_addressees


def _notify_raiser(
    esc: LeadershipEscalation, title: str, body: str, event_type: str
) -> None:
    """Tell the raiser what happened to their escalation — through the
    canonical service, like the addressee-facing half above.

    This was the last raw `Notification.objects.create` in the channel and it
    set no `source_event_type`, so `resolve_condition` could never match it:
    the "acknowledged" notice outlived the decision that answered it and sat in
    the raiser's rail permanently (INTG-03). The acknowledgement is closed by
    `resolve()`; the decision notice is genuinely terminal — the channel ends
    there — so it is `normal` priority and never becomes an action-required row
    for the 48-hour escalation job to promote.
    """
    if not esc.raised_by_user_id:
        return
    try:
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type=event_type,
            category="leadership",
            priority="normal",
            title=title,
            body=body[:300],
            context_type="escalation",
            context_id=esc.id,
            recipients=[esc.raised_by_user_id],
        )
    except Exception:  # noqa: BLE001
        pass


def _serialize(
    e: LeadershipEscalation, *, mine: bool = False, can_decide: bool = False
) -> dict:
    return {
        "id": e.id,
        "subject": e.subject,
        "detail": e.detail,
        "category": e.category,
        "categoryLabel": dict(CATEGORIES).get(e.category, e.category),
        "severity": e.severity,
        "requestedDecision": e.requested_decision,
        "scopeType": e.scope_type,
        "scopeId": e.scope_id,
        "scopeName": e.scope_name,
        "raisedBy": e.raised_by_name,
        "raisedAt": e.created_at,
        "ageDays": e.age_days,
        "isOverdue": _is_overdue(e),
        "isOpen": e.is_open,
        "status": e.status,
        "addressedRole": e.addressed_role,
        "addressedRoleLabel": ADDRESSEE_LABELS.get(e.addressed_role, e.addressed_role),
        "assignedToUserId": e.assigned_to_user_id,
        "decision": e.decision,
        "decisionLabel": dict(DECISIONS).get(e.decision) if e.decision else None,
        "decisionNote": e.decision_note,
        "resolvedAt": e.resolved_at,
        "dueDate": e.due_date,
        "mine": mine,
        "canDecide": can_decide,
    }


__all__ = [
    "CATEGORIES",
    "DECISIONS",
    "SLA_DAYS",
    "ADDRESSEE_FOR_RAISER",
    "ADDRESSEE_LABELS",
    "addressee_for",
    "resolve_addressee",
    "raise_escalation",
    "acknowledge",
    "resolve",
    "can_decide",
    "visible_to",
    "board",
    "sweep_overdue",
]
