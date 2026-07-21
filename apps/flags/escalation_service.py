"""CD→RVP escalation — the upward decision channel.

Flags travel CD→PL (a quality handoff to an operator). Strategy notes travel
RVP→CD (guidance downward). Nothing travelled CD→RVP, so a Country Director
facing a decision above their own authority had no route to the person who
holds it — the cockpit's "Escalate to RVP" button had no endpoint behind it.

This module is that route. It is deliberately small: raise, acknowledge,
resolve-with-a-decision, and an SLA sweep that pushes ageing items so the
channel cannot silently rot the way an unwatched queue does.
"""

from __future__ import annotations

from django.utils import timezone

from apps.audit.services import log as audit_log
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.rbac import EdifyRole

from .models import EscalationSeverity, EscalationStatus, LeadershipEscalation


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
    ("other", "Other"),
]

DECISIONS = [
    ("approved", "Approved"),
    ("declined", "Declined"),
    ("deferred", "Deferred"),
    ("delegated_back", "Delegated back to CD"),
    ("noted", "Noted — no action required"),
]


def _actor_id(principal) -> str | None:
    return getattr(principal, "user_id", None) or getattr(principal, "id", None)


def _role(principal) -> str:
    return getattr(principal, "active_role", "") or ""


def raise_escalation(data: dict, principal) -> LeadershipEscalation:
    """A CD puts a decision in front of the RVP."""
    if _role(principal) not in (
        EdifyRole.COUNTRY_DIRECTOR.value,
        EdifyRole.ADMIN.value,
    ):
        raise Forbidden("Only the Country Director may escalate to the RVP.")

    subject = (data.get("subject") or "").strip()
    detail = (data.get("detail") or "").strip()
    if not subject:
        raise BadRequest("A subject is required.")
    if not detail:
        raise BadRequest("Describe what the RVP needs to decide.")

    category = (data.get("category") or "other").strip()
    if category not in {c for c, _ in CATEGORIES}:
        raise BadRequest("Unknown escalation category.")

    severity = (data.get("severity") or EscalationSeverity.NORMAL.value).strip()
    if severity not in {s.value for s in EscalationSeverity}:
        raise BadRequest("Unknown severity.")

    esc = LeadershipEscalation.objects.create(
        raised_by_user_id=_actor_id(principal),
        raised_by_name=getattr(principal, "name", None),
        country_id=(data.get("country_id") or "Uganda"),
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
    _notify_rvps(esc)
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
        },
    )
    return esc


def acknowledge(escalation_id: str, principal) -> LeadershipEscalation:
    esc = _get_for_rvp(escalation_id, principal)
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
    _notify_raiser(esc, "Your escalation was acknowledged", esc.subject)
    audit_log(
        action="escalation_acknowledge",
        subject_kind="LeadershipEscalation",
        subject_id=esc.id,
        actor_id=_actor_id(principal),
        actor_role=_role(principal),
    )
    return esc


def resolve(escalation_id: str, data: dict, principal) -> LeadershipEscalation:
    """The RVP answers. A decision and a reason are both required — an
    escalation that closes with no recorded answer teaches the CD not to use
    the channel again."""
    esc = _get_for_rvp(escalation_id, principal)
    if esc.status == EscalationStatus.RESOLVED:
        raise BadRequest("This escalation is already resolved.")

    decision = (data.get("decision") or "").strip()
    if decision not in {d for d, _ in DECISIONS}:
        raise BadRequest("Select a decision.")
    note = (data.get("decision_note") or "").strip()
    if not note:
        raise BadRequest(
            "Record why — the CD needs the reasoning, not just the verdict."
        )

    esc.status = EscalationStatus.RESOLVED
    esc.decision = decision
    esc.decision_note = note
    esc.resolved_at = timezone.now()
    if not esc.acknowledged_at:
        esc.acknowledged_at = timezone.now()
        esc.acknowledged_by_user_id = _actor_id(principal)
    esc.save()
    # The RVPs no longer need to act on it.
    try:
        from apps.notifications.services import resolve_condition

        resolve_condition("leadership_escalation_open", "escalation", esc.id)
    except Exception:  # noqa: BLE001
        pass
    _notify_raiser(
        esc,
        f"RVP decision: {dict(DECISIONS)[decision]}",
        f"{esc.subject} — {note[:200]}",
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


def visible_to(principal):
    """Escalations a principal may read: the CD sees what they raised, the RVP
    and Admin see the whole board."""
    role = _role(principal)
    qs = LeadershipEscalation.objects.all()
    if role in (EdifyRole.REGIONAL_VICE_PRESIDENT.value, EdifyRole.ADMIN.value):
        return qs
    if role == EdifyRole.COUNTRY_DIRECTOR.value:
        return qs.filter(raised_by_user_id=_actor_id(principal))
    return qs.none()


def board(principal) -> dict:
    """The escalation queue, split by what needs attention now."""
    qs = visible_to(principal)
    open_items = [e for e in qs if e.is_open]
    return {
        "open": [_serialize(e) for e in open_items],
        "resolved": [_serialize(e) for e in qs if not e.is_open][:20],
        "overdue_count": sum(1 for e in open_items if _is_overdue(e)),
        "open_count": len(open_items),
        "categories": CATEGORIES,
        "decisions": DECISIONS,
        "severities": [(s.value, s.label) for s in EscalationSeverity],
    }


def sweep_overdue() -> int:
    """Re-notify on escalations past their SLA.

    Run from the scheduler alongside the other daily jobs. Returns how many
    were pushed, so the job log says something useful.
    """
    pushed = 0
    for esc in LeadershipEscalation.objects.exclude(status=EscalationStatus.RESOLVED):
        if _is_overdue(esc):
            _notify_rvps(
                esc,
                title=f"Overdue escalation ({esc.age_days}d): {esc.subject}",
            )
            pushed += 1
    return pushed


def _is_overdue(esc: LeadershipEscalation) -> bool:
    limit = SLA_DAYS.get(esc.severity, SLA_DAYS[EscalationSeverity.NORMAL.value])
    return esc.status == EscalationStatus.OPEN and esc.age_days >= limit


def _get_for_rvp(escalation_id: str, principal) -> LeadershipEscalation:
    if _role(principal) not in (
        EdifyRole.REGIONAL_VICE_PRESIDENT.value,
        EdifyRole.ADMIN.value,
    ):
        raise Forbidden("Only the Regional Vice President may act on an escalation.")
    esc = LeadershipEscalation.objects.filter(id=escalation_id).first()
    if not esc:
        raise NotFoundError("Escalation not found.")
    return esc


def _notify_rvps(esc: LeadershipEscalation, title: str | None = None) -> None:
    """Notify every RVP about an escalation — once per RVP, not once per run.

    This wrote a bare `create()` per RVP on every invocation, and the daily
    overdue sweep calls it for every still-open escalation. A single item open
    for thirty days produced thirty identical rows per RVP, and because the
    job is retryable with no transaction, one partial failure re-sent every
    escalation it had already processed. Routing through the canonical service
    gives it the dedupe key, the role-aware route, the audit row and the
    realtime publish that the raw insert skipped entirely.
    """
    try:
        from apps.accounts.models import User
        from apps.notifications.services import WorkflowNotificationService

        recipients = list(
            User.objects.filter(
                roles__contains=[EdifyRole.REGIONAL_VICE_PRESIDENT.value],
                status="active",
            )
        )
        if not recipients:
            return
        WorkflowNotificationService.trigger(
            event_type="leadership_escalation_open",
            category="leadership",
            priority=(
                "high" if esc.severity != EscalationSeverity.NORMAL.value else "normal"
            ),
            title=title or f"Escalation from the Country Director: {esc.subject}",
            body=esc.detail[:300],
            context_type="escalation",
            context_id=esc.id,
            recipients=recipients,
        )
    except Exception:  # noqa: BLE001 - notification must never block the escalation
        pass


def _notify_raiser(esc: LeadershipEscalation, title: str, body: str) -> None:
    try:
        from apps.notifications.models import Notification

        Notification.objects.create(
            recipient_id=esc.raised_by_user_id,
            title=title,
            body=body[:300],
            category="leadership",
            context_type="escalation",
            context_id=esc.id,
            target_route="/escalations",
            action_label="Open",
            priority="normal",
        )
    except Exception:  # noqa: BLE001
        pass


def _serialize(e: LeadershipEscalation) -> dict:
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
        "status": e.status,
        "decision": e.decision,
        "decisionLabel": dict(DECISIONS).get(e.decision) if e.decision else None,
        "decisionNote": e.decision_note,
        "resolvedAt": e.resolved_at,
        "dueDate": e.due_date,
    }


__all__ = [
    "CATEGORIES",
    "DECISIONS",
    "SLA_DAYS",
    "raise_escalation",
    "acknowledge",
    "resolve",
    "visible_to",
    "board",
    "sweep_overdue",
]
