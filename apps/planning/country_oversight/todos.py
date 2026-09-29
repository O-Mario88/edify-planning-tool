"""To-Dos derived from planning follow-ups — never stored beside them.

The Programme Lead sees "Follow Up with CCEO on Planning Gap" while a
follow-up is waiting on them (sent or acknowledged); once they have linked a
school action or said what the gap is waiting on, the row leaves their queue
while the follow-up stays open for the Country Director to watch. The Country
Director sees the follow-ups a Lead returned for clarification. Every row
disappears by itself when the follow-up's state moves on — including when the
gap clears and the sweep closes it.

Registered in apps.command_center.todo_service.MODULE_TODO_BUILDERS.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

LEAD_ROLE = "Program Lead"
DIRECTOR_ROLE = "CountryDirector"


def followup_todos(principal, role, today) -> list[dict]:
    try:
        if role == LEAD_ROLE:
            return _lead_rows(principal, today)
        if role == DIRECTOR_ROLE:
            return _director_rows(principal, today)
        return []
    except Exception:  # noqa: BLE001 - one source never breaks the queue
        logger.exception("Planning follow-up To-Dos failed")
        return []


def _lead_rows(principal, today) -> list[dict]:
    from apps.command_center.derived_rows import todo_row
    from apps.planning.country_oversight.followups import issue_of, team_oversight_link
    from apps.planning.followup_models import PL_TODO_STATES, PlanningOversightFollowUp

    user_id = str(getattr(principal, "id", "") or "")
    if not user_id:
        return []
    rows = []
    for followup in PlanningOversightFollowUp.objects.filter(
        program_lead_user_id=user_id, status__in=PL_TODO_STATES
    ).order_by("due_date", "assigned_at")[:25]:
        issue = issue_of(followup.issue_type)
        execution = getattr(followup, "module", "planning") == "execution"
        subject = (
            followup.activity_label
            or followup.partner_name
            or followup.cceo_name
            or followup.school_name
            or "your team"
        )
        if execution:
            title = issue.todo_verb if issue else "Follow Up with CCEO on Execution Gap"
            description = (
                f"{issue.label if issue else 'Execution gap'} · {subject} · "
                f"{followup.remaining_value:,} open ({followup.period_label})"
            )
        else:
            title = "Follow Up with CCEO on Planning Gap"
            description = (
                f"{issue.label if issue else 'Planning gap'} · {subject} · "
                f"{followup.remaining_value:,} of {followup.required_value:,} "
                f"remaining ({followup.period_label})"
            )
        rows.append(
            todo_row(
                f"cpofu-{followup.id}",
                title=title,
                description=description,
                category="Team Leadership",
                priority="critical"
                if followup.priority == "critical"
                else (
                    "high" if followup.priority in ("high", "attention") else "medium"
                ),
                url=team_oversight_link(followup),
                action="Open",
                linked=subject,
                today=today,
                source=f"Sent by {followup.assigned_by_name or 'the Country Director'}",
                due=followup.due_date,
            )
        )
    return rows


def _director_rows(principal, today) -> list[dict]:
    from apps.command_center.derived_rows import todo_row
    from apps.planning.country_oversight.followups import issue_of
    from apps.planning.followup_models import FollowUpStatus, PlanningOversightFollowUp

    rows = []
    for followup in PlanningOversightFollowUp.objects.filter(
        status=FollowUpStatus.RETURNED_FOR_CLARIFICATION
    ).order_by("returned_at")[:25]:
        issue = issue_of(followup.issue_type)
        rows.append(
            todo_row(
                f"cpofu-back-{followup.id}",
                title="Clarify Execution Follow-Up"
                if getattr(followup, "module", "planning") == "execution"
                else "Clarify Planning Follow-Up",
                description=(
                    f"{followup.program_lead_name} returned "
                    f"“{issue.label if issue else followup.issue_type}”: "
                    f"{followup.returned_reason}"
                ),
                category="Leadership",
                priority="high",
                url=(
                    "/country-planning-oversight/drawer?kind=followups"
                    f"&focus={followup.id}"
                ),
                action="Clarify",
                linked=followup.program_lead_name,
                today=today,
                source="Country Planning Oversight",
                due=followup.due_date,
            )
        )
    return rows
