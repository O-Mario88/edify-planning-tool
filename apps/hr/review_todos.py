"""Reviewer To-Dos: the performance conversations a reviewer owes (2026-09-13).

The Programme Lead reviews the officers they supervise — the role description
names "performance reviews and professional coaching for assigned CCEOs" as a
responsibility — and nothing put that work in their queue. A window HR opened
was found out about late, priorities the officer submitted waited unseen, and
a review past its date surfaced only on HR Today, a page the lead does not
open.

Three rows, all derived from the records and so self-closing:

    Review <name>'s priorities        the agreement is waiting on the reviewer
    Hold the <window> conversation    a quarterly window is open and the
      with <name>                     conversation is not yet signed off
    Complete <name>'s overdue review  a review is past its due date

A review that is overdue AND waiting on the reviewer is one row marked
overdue, not two. Rows come from apps.hr.performance_engine.team_review_rows,
the same rows the Performance Reviews page lists, in a fixed number of
queries whatever the team size. The builder serves any role that reviews
someone (the rule lives in apps.hr.review_authority): a Programme Lead for
their officers, a Country Director for their Programme Leads.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

CATEGORY = "Performance & coaching"
SOURCE = "Performance reviews"


def _reviewer_roles() -> set[str]:
    from apps.hr.review_authority import REVIEWER_ROLE_FOR

    return {role for roles in REVIEWER_ROLE_FOR.values() for role in roles}


def _row(
    key: str,
    *,
    title: str,
    description: str,
    staff_id: str,
    name: str,
    due=None,
    today,
    overdue: bool = False,
) -> dict:
    return {
        "id": key,
        "title": title,
        "description": description[:180],
        "category": CATEGORY,
        "priority": "high" if overdue else "medium",
        "status_key": "overdue" if overdue else "waiting_me",
        "status_label": "Overdue" if overdue else "Waiting on Me",
        "status_tone": "danger" if overdue else "warning",
        "due_label": f"{due:%-d %b}" if due else "—",
        "due_tone": "danger" if overdue else ("warning" if due else "neutral"),
        "linked": name,
        "action_label": "Open conversation",
        "action_url": f"/performance-conversation?staff={staff_id}",
        "actionable": True,
        "source": SOURCE,
        "_due_sort": due or today,
    }


def _conversation_left(row) -> str:
    """What is still missing from an open window's conversation, in words."""
    if not row["reflection_saved"]:
        return (
            f"Waiting for {row['name']}'s reflection · "
            f"{row['manager_saved']} of {row['priorities']} manager columns saved."
        )
    if row["priorities"] and row["manager_saved"] < row["priorities"]:
        return (
            f"{row['manager_saved']} of {row['priorities']} manager columns "
            "saved. Rate each priority, then sign off to lock the record."
        )
    return "Every column is saved. Sign the conversation off to lock the record."


def reviewer_todos(principal, role, today) -> list[dict]:
    """fn(principal, role, today) for MODULE_TODO_BUILDERS. Never raises."""
    try:
        if role not in _reviewer_roles():
            return []
        if not getattr(principal, "staff_profile_id", None):
            return []
        from apps.hr.performance_engine import team_review_rows

        out = []
        for row in team_review_rows(principal, today=today):
            name = row["name"]
            staff_id = row["profile"].id
            review = row["review"]
            overdue = row["overdue_reviews"]
            overdue_ids = {r.id for r in overdue}
            annual_overdue = bool(review and review.id in overdue_ids)
            if row["agreement_waiting"]:
                out.append(
                    _row(
                        f"review-agree-{review.id}",
                        title=f"Review {name}'s priorities",
                        description=(
                            f"{name} submitted their FY{review.fy} priorities. "
                            "Agree them so the year's conversations can be "
                            "held against them."
                        ),
                        staff_id=staff_id,
                        name=name,
                        due=review.due_date if annual_overdue else None,
                        today=today,
                        overdue=annual_overdue,
                    )
                )
            elif row["hold_needed"]:
                out.append(
                    _row(
                        f"review-hold-{review.id}-{row['window']}",
                        title=(
                            f"Hold the {row['window_label']} conversation with {name}"
                        ),
                        description=_conversation_left(row),
                        staff_id=staff_id,
                        name=name,
                        due=review.due_date if annual_overdue else None,
                        today=today,
                        overdue=annual_overdue,
                    )
                )
            for late in overdue:
                if late.id == getattr(review, "id", None) and (
                    row["agreement_waiting"] or row["hold_needed"]
                ):
                    continue  # already raised above, marked overdue
                days = (today - late.due_date).days
                out.append(
                    _row(
                        f"review-overdue-{late.id}",
                        title=f"Complete {name}'s overdue performance review",
                        description=(
                            f"The {late.get_review_type_display().lower()} review "
                            f"is {days} day{'s' if days != 1 else ''} past its due "
                            f"date ({late.get_stage_display()})."
                        ),
                        staff_id=staff_id,
                        name=name,
                        due=late.due_date,
                        today=today,
                        overdue=True,
                    )
                )
        return out
    except Exception:  # noqa: BLE001 — one source never breaks the queue
        logger.exception("reviewer To-Dos failed")
        return []
