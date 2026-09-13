"""The Programme Lead's escalation To-Dos (Programme Lead alignment, 2026-09-13).

The escalation channel runs the whole reporting line: a CCEO or Project
Coordinator raises to their Programme Lead, and the Programme Lead raises to
the Country Director. The Country Director's side had To-Dos
(apps.command_center.todo_service._escalation_todos); the Programme Lead's
did not, so an officer's escalation reached the lead as one notification and
then nothing asked them to decide it.

Two rows, both derived from the escalation rows themselves — nothing is stored,
and each row disappears when the condition ends:

* "Decide escalation from <raiser>" — every open escalation the lead may
  decide. The rule is the escalation board's own addressed-to-me rule
  (escalation_service._addressed_to_me_q), so the To-Do and /escalations
  always list the same items. Deciding it closes the row.
* "Act on delegated escalation" — the lead's own escalation the Country
  Director delegated back, for the fortnight after the decision (the window
  the Country Director's delegated-back row uses).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

PROGRAM_LEAD = "Program Lead"
DELEGATED_WINDOW_DAYS = 14
ESCALATIONS_URL = "/escalations"

_PRIORITY_FOR_SEVERITY = {"critical": "critical", "high": "high", "normal": "medium"}


def _row(key, *, title, description, priority, overdue, due, due_label, linked, today):
    return {
        "id": key,
        "title": title,
        "description": description[:180],
        "category": "Team Leadership",
        "priority": priority,
        "status_key": "overdue" if overdue else "waiting_me",
        "status_label": "Overdue" if overdue else "Waiting on Me",
        "status_tone": "danger" if overdue else "warning",
        "due_label": due_label,
        "due_tone": "danger" if overdue else "warning",
        "linked": linked,
        "action_label": "Open",
        "action_url": ESCALATIONS_URL,
        "actionable": True,
        "source": "Escalations",
        "_due_sort": due or today,
    }


def pl_escalation_todos(principal, role, today) -> list[dict]:
    """Escalations waiting on a Programme Lead, as To-Do rows."""
    if role != PROGRAM_LEAD:
        return []
    try:
        from apps.flags.escalation_service import (
            ADDRESSEE_LABELS,
            CATEGORIES,
            SLA_DAYS,
            _actor_id,
            _addressed_to_me_q,
            _is_overdue,
        )
        from apps.flags.models import (
            EscalationSeverity,
            EscalationStatus,
            LeadershipEscalation,
        )

        today = today or timezone.localdate()
        me = _actor_id(principal)
        categories = dict(CATEGORIES)
        out: list[dict] = []

        inbox = _addressed_to_me_q(principal)
        if inbox is not None:
            to_decide = (
                LeadershipEscalation.objects.filter(inbox)
                .exclude(status=EscalationStatus.RESOLVED)
                .exclude(raised_by_user_id=me)
                .order_by("created_at")[:50]
            )
            for esc in to_decide:
                limit = SLA_DAYS.get(
                    esc.severity, SLA_DAYS[EscalationSeverity.NORMAL.value]
                )
                due = esc.due_date or (esc.created_at.date() + timedelta(days=limit))
                overdue = _is_overdue(esc)
                raiser = esc.raised_by_name or "your officer"
                out.append(
                    _row(
                        f"esc-decide-{esc.id}",
                        title=f"Decide escalation from {raiser}",
                        description=(
                            esc.subject
                            + (
                                f" — asks: {esc.requested_decision}"
                                if esc.requested_decision
                                else ""
                            )
                        ),
                        priority=(
                            "critical"
                            if overdue
                            else _PRIORITY_FOR_SEVERITY.get(esc.severity, "medium")
                        ),
                        overdue=overdue,
                        due=due,
                        due_label=(
                            f"{esc.age_days}d open" if overdue else f"{due:%-d %b}"
                        ),
                        linked=f"Escalation · {categories.get(esc.category, esc.category)}",
                        today=today,
                    )
                )

        since = timezone.now() - timedelta(days=DELEGATED_WINDOW_DAYS)
        delegated = LeadershipEscalation.objects.filter(
            raised_by_user_id=me,
            status=EscalationStatus.RESOLVED,
            decision="delegated_back",
            resolved_at__gte=since,
        ).order_by("-resolved_at")[:10]
        for esc in delegated:
            note = (esc.decision_note or "").strip()
            out.append(
                _row(
                    f"esc-delegated-{esc.id}",
                    title="Act on delegated escalation",
                    description=(
                        f"The {ADDRESSEE_LABELS.get(esc.addressed_role, 'Country Director')} "
                        f"delegated “{esc.subject}” back to you"
                        + (f": {note}" if note else ".")
                    ),
                    priority="high",
                    overdue=False,
                    due=esc.resolved_at.date() + timedelta(days=DELEGATED_WINDOW_DAYS),
                    due_label="This fortnight",
                    linked=f"Escalation · {categories.get(esc.category, esc.category)}",
                    today=today,
                )
            )
        return out
    except Exception:  # noqa: BLE001 - one source never breaks the queue
        logger.exception("Programme Lead escalation To-Dos failed")
        return []
