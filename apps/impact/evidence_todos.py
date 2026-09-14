"""School evidence and change story To-Dos (IA review, owner, 2026-09-13).

Evidence moves only when the next person acts, so each derived row names that
person's next step and opens the register or the visit that resolves it:

  - school evidence I may verify (a second IA officer, or the Country Director
    where the recorder is the country's only officer — never my own record);
  - school evidence returned to me for correction;
  - Most Significant Change stories waiting for my review (Impact Assessment);
  - OneTest visits I delivered whose class results are not recorded yet.

Rows are derived, never stored: a row disappears when its queue empties. A
fixed number of queries whatever the size of the queues
(apps/impact/test_school_evidence.py pins it).
"""

from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

IA = "ImpactAssessment"
CD = "CountryDirector"
CATEGORY = "Baseline & Field Data"
STORY_CATEGORY = "School Progress"

#: Roles that deliver OneTest visits and record their results.
FIELD_ROLES = (
    "CCEO",
    "Program Lead",
    "PartnerAdmin",
    "PartnerFieldOfficer",
    "ProjectCoordinator",
)


def _row(
    key,
    *,
    title,
    description,
    url,
    action,
    count,
    oldest,
    today,
    category,
    priority="high",
):
    oldest_day = timezone.localdate(oldest) if hasattr(oldest, "tzinfo") else oldest
    late = oldest_day is not None and (today - oldest_day).days > 7
    return {
        "id": key,
        "title": title,
        "description": description,
        "category": category,
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


def evidence_todos(principal, role, today) -> list[dict]:
    """Registered in apps.command_center.todo_service.MODULE_TODO_BUILDERS."""
    try:
        return _evidence_todos(principal, role, today)
    except Exception:  # noqa: BLE001 - one source never breaks the queue
        logger.exception("School evidence To-Dos failed")
        return []


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _evidence_todos(principal, role, today) -> list[dict]:
    from apps.impact import evidence_services as ev

    out: list[dict] = []
    if role in (IA, CD) or role in FIELD_ROLES:
        waiting = ev.waiting_for(principal)
        for kind, rows in waiting["to_verify"].items():
            tab = ev.KIND_TAB[kind]
            oldest = min(r["created_at"] for r in rows)
            url = (
                f"/ia/school-evidence/?tab={tab}&status=pending&open={kind}-{rows[0]['id']}"
                if len(rows) == 1
                else f"/ia/school-evidence/?tab={tab}&status=pending"
            )
            out.append(
                _row(
                    f"ia-school-evidence-verify-{kind}",
                    title=(
                        f"Verify {_plural(len(rows), ev.KIND_LABELS[kind].lower())}"
                        if role == IA
                        else f"Confirm {_plural(len(rows), ev.KIND_LABELS[kind].lower())} "
                        "(no second IA officer)"
                    ),
                    description=(
                        "Recorded by someone else in your country; it counts as school "
                        "evidence only once confirmed."
                    ),
                    url=url,
                    action="Open School Evidence",
                    count=len(rows),
                    oldest=oldest,
                    today=today,
                    category=CATEGORY,
                )
            )
        for kind, rows in waiting["returned"].items():
            oldest = min(r["updated_at"] for r in rows)
            first = rows[0]
            if first["source_activity_id"] and role not in (IA, CD):
                url = f"/my-plan/{first['source_activity_id']}?learning_results=1"
                action = "Correct Results"
            else:
                url = (
                    f"/ia/school-evidence/?tab={ev.KIND_TAB[kind]}&status=returned"
                    f"&open={kind}-{first['id']}"
                )
                action = "Correct Evidence"
            out.append(
                _row(
                    f"ia-school-evidence-returned-{kind}",
                    title=f"Correct {_plural(len(rows), ev.KIND_LABELS[kind].lower())} returned to you",
                    description="A verifier returned it with a note on what to correct.",
                    url=url,
                    action=action,
                    count=len(rows),
                    oldest=oldest,
                    today=today,
                    category=CATEGORY,
                )
            )

    if role == IA:
        from apps.targets import mscs_review

        me = str(getattr(principal, "id", ""))
        stories = list(
            mscs_review.visible_stories(principal)
            .filter(status="submitted")
            .exclude(user_id=me)
            .order_by("created_at")
            .values_list("id", "created_at")[:200]
        )
        if stories:
            out.append(
                _row(
                    "ia-stories-review",
                    title=f"Review {_plural(len(stories), 'change story')}"
                    if len(stories) == 1
                    else f"Review {len(stories)} change stories",
                    description=(
                        "Submitted Most Significant Change stories count toward their "
                        "authors' targets only once reviewed."
                    ),
                    url=(
                        f"/ia/stories/?open={stories[0][0]}"
                        if len(stories) == 1
                        else "/ia/stories/"
                    ),
                    action="Review Stories",
                    count=len(stories),
                    oldest=stories[0][1],
                    today=today,
                    category=STORY_CATEGORY,
                )
            )

    if role in FIELD_ROLES:
        for activity in ev.onetest_visits_without_results(principal):
            delivered = activity.actual_delivery_date or activity.planned_date
            out.append(
                _row(
                    f"onetest-results-{activity.id}",
                    title=f"Record OneTest results for {activity.school.name}",
                    description=(
                        "The OneTest visit is delivered; record each class's results so "
                        "they reach the school's learning evidence."
                    ),
                    url=f"/my-plan/{activity.id}?learning_results=1",
                    action="Record Results",
                    count=1,
                    oldest=delivered,
                    today=today,
                    category="My Work",
                    priority="normal",
                )
            )
    return out
