"""Measurement framework To-Dos (IA review, owner, 2026-09-13).

A framework definition moves only when the next person acts on it, and until
now nothing told them: a rule submitted for review waited for a colleague who
never heard of it, and a returned draft waited for an author who had moved on.
Three derived rows, each opening the Measurement Framework on the register
that resolves it:

  - definitions I may review — a second IA officer's review, or the Country
    Director's acknowledgement where the country has no second officer
    (never my own work);
  - my drafts a reviewer returned;
  - school-outcome activities with no live measurement rule (IA only).

Rows are derived, never stored: when the queue empties the row stops
appearing. A fixed number of queries whatever the size of the queues
(apps/impact/test_framework.py pins it).
"""

from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

#: The IA To-Do category the framework rows sit under.
CATEGORY = "Framework & Strategy"

IA = "ImpactAssessment"
CD = "CountryDirector"


def _row(key, *, title, description, url, action, count, oldest, today, priority):
    oldest_day = timezone.localdate(oldest) if oldest else None
    late = oldest_day is not None and (today - oldest_day).days > 7
    return {
        "id": key,
        "title": title,
        "description": description,
        "category": CATEGORY,
        "priority": "critical" if late else priority,
        "status_key": "overdue" if late else "waiting_me",
        "status_label": "Overdue" if late else "Waiting on Me",
        "status_tone": "danger" if late else "warning",
        "due_label": f"Oldest {oldest_day:%-d %b}" if oldest_day else "—",
        "due_tone": "danger" if late else "neutral",
        "linked": f"{count} waiting",
        "action_label": action,
        "action_url": url,
        "actionable": True,
        "source": "Impact Assessment",
        "_due_sort": oldest_day or today,
    }


def framework_todos(principal, role, today) -> list[dict]:
    """Registered in apps.command_center.todo_service.MODULE_TODO_BUILDERS."""
    if role not in (IA, CD):
        return []
    try:
        return _framework_todos(principal, role, today)
    except Exception:  # noqa: BLE001 - one source never breaks the queue
        logger.exception("Measurement framework To-Dos failed")
        return []


def _oldest(records, field):
    stamps = [getattr(r, field, None) for r in records if getattr(r, field, None)]
    return min(stamps) if stamps else None


def _framework_todos(principal, role, today) -> list[dict]:
    from apps.impact import framework as fw

    out: list[dict] = []
    waiting = fw.awaiting_review(principal)
    rules, areas, indicators = waiting["rules"], waiting["areas"], waiting["indicators"]
    if rules:
        first = rules[0]
        out.append(
            _row(
                "ia-framework-review-rules",
                title=(
                    f"Review {len(rules)} measurement rule{'s' if len(rules) != 1 else ''}"
                    if role == IA
                    else f"Acknowledge {len(rules)} measurement rule"
                    f"{'s' if len(rules) != 1 else ''}"
                ),
                description=(
                    "Submitted by another Impact Assessment officer; a rule measures "
                    "nothing until a second reviewer publishes it."
                ),
                url=(
                    f"/ia/framework/?tab=rules&open=rule-{first.id}"
                    if len(rules) == 1
                    else "/ia/framework/?tab=rules&status=in_review"
                ),
                action="Open Measurement Rules",
                count=len(rules),
                oldest=_oldest(rules, "submitted_at"),
                today=today,
                priority="high",
            )
        )
    definitions = areas + indicators
    if definitions:
        first = definitions[0]
        tab = "areas" if areas and not indicators else "indicators"
        kind = "area" if first in areas else "indicator"
        out.append(
            _row(
                "ia-framework-review-definitions",
                title=(
                    f"Review {len(definitions)} framework definition"
                    f"{'s' if len(definitions) != 1 else ''}"
                ),
                description="Outcome areas and indicators waiting for a second reviewer.",
                url=(
                    f"/ia/framework/?tab={'areas' if kind == 'area' else 'indicators'}"
                    f"&open={kind}-{first.id}"
                    if len(definitions) == 1
                    else f"/ia/framework/?tab={tab}&status=in_review"
                ),
                action="Open Measurement Framework",
                count=len(definitions),
                oldest=_oldest(definitions, "submitted_at"),
                today=today,
                priority="high",
            )
        )

    if role != IA:
        return out

    returned = fw.returned_to_me(principal)
    back = returned["rules"] + returned["definitions"]
    if back:
        stamps = [
            getattr(r, "reviewed_at", None)
            for r in back
            if getattr(r, "reviewed_at", None)
        ]
        out.append(
            _row(
                "ia-framework-returned",
                title=f"Revise {len(back)} returned definition{'s' if len(back) != 1 else ''}",
                description="A reviewer returned your draft with a note.",
                url=(
                    "/ia/framework/?tab=rules&status=draft"
                    if returned["rules"]
                    else "/ia/framework/?tab=indicators&status=returned"
                    if any(not hasattr(r, "code") for r in returned["definitions"])
                    else "/ia/framework/?tab=areas&status=returned"
                ),
                action="Open Measurement Framework",
                count=len(back),
                oldest=min(stamps) if stamps else None,
                today=today,
                priority="medium",
            )
        )

    unmapped = fw.framework_counts(principal)["items_unmapped"]
    if unmapped:
        out.append(
            _row(
                "ia-framework-unmapped",
                title=(
                    f"Set measurement rules for {unmapped} "
                    f"activit{'ies' if unmapped != 1 else 'y'}"
                ),
                description=(
                    "School-outcome activities with no live rule cannot be read in "
                    "intervention-impact analysis."
                ),
                url="/ia/framework/?tab=rules&status=required",
                action="Open Measurement Rules",
                count=unmapped,
                oldest=None,
                today=today,
                priority="medium",
            )
        )
    return out
