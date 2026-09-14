"""Impact report To-Dos (IA review, owner, 2026-09-13).

A report moves only when the next person acts, so each derived row names that
person's step and opens the report or register that resolves it:

  - impact reports waiting for my review (a second IA officer in the
    country; the Country Director where there is none — never the author);
  - my reports returned to me for correction;
  - reports I reviewed and have not yet released to country leadership;
  - recommendations of released reports waiting for my response, and the
    open ones past their due date (the Country Director);
  - donor versions waiting for my approval (an RVP covering the country,
    never the requester, author or reviewer).

The account owner's "share the school's brief" is a TeamAction and reaches
their queue through the existing school-action rows.

Rows are derived, never stored: a row disappears when its queue empties. A
fixed number of queries whatever the size of the queues
(apps/impact/test_reports.py pins it). A failure never breaks the queue.
"""

from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

IA = "ImpactAssessment"
CD = "CountryDirector"
RVP = "RegionalVicePresident"
CATEGORY = "Reporting & Accountability"


def _plural(n, word, plural=None):
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def _day(value):
    if value is None:
        return None
    return timezone.localdate(value) if hasattr(value, "tzinfo") else value


def _row(key, *, title, description, url, action, count, oldest, today, late_after=7):
    oldest_day = _day(oldest)
    late = oldest_day is not None and (today - oldest_day).days > late_after
    return {
        "id": key,
        "title": title,
        "description": description,
        "category": CATEGORY,
        "priority": "critical" if late else "high",
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


def _one_or_register(rows, register_url):
    return f"/ia/impact-reports/{rows[0]['id']}/" if len(rows) == 1 else register_url


def report_todos(principal, role, today) -> list[dict]:
    """Registered in apps.command_center.todo_service.MODULE_TODO_BUILDERS."""
    if role not in (IA, CD, RVP):
        return []
    try:
        return _todos(principal, role, today)
    except Exception:  # noqa: BLE001 - one source never breaks the queue
        logger.exception("Impact report To-Dos failed")
        return []


def _todos(principal, role, today) -> list[dict]:
    from apps.impact import reports as rp
    from apps.impact.models import ImpactReportRecommendation, ImpactReportRelease

    me = str(getattr(principal, "id", "") or "")
    out: list[dict] = []
    if role in (IA, CD):
        from apps.impact.review import _profile_country, ia_officer_ids

        country = _profile_country(principal)
        rows = list(
            rp.visible_reports(principal)
            .filter(status__in=(rp.SUBMITTED, rp.RETURNED, rp.REVIEWED))
            .values(
                "id",
                "status",
                "author_id",
                "country",
                "reviewed_by_id",
                "submitted_at",
                "reviewed_at",
                "updated_at",
            )
        )
        submitted = [
            r
            for r in rows
            if r["status"] == rp.SUBMITTED
            and r["author_id"] != me
            and country
            and r["country"] == country
        ]
        if role == CD and submitted:
            officers = [str(i) for i in ia_officer_ids(country)]
            submitted = [
                r for r in submitted if not [i for i in officers if i != r["author_id"]]
            ]
        if submitted:
            out.append(
                _row(
                    "ia-reports-review",
                    title=f"Review {_plural(len(submitted), 'impact report')}"
                    if role == IA
                    else f"Acknowledge {_plural(len(submitted), 'impact report')} (no second IA officer)",
                    description="Written by someone else in your country; nothing is released until it is reviewed.",
                    url=_one_or_register(
                        submitted, "/ia/impact-reports/?status=submitted"
                    ),
                    action="Review Report",
                    count=len(submitted),
                    oldest=min(r["submitted_at"] or r["updated_at"] for r in submitted),
                    today=today,
                )
            )
        returned = [
            r
            for r in rows
            if role == IA and r["status"] == rp.RETURNED and r["author_id"] == me
        ]
        if returned:
            out.append(
                _row(
                    "ia-reports-returned",
                    title=f"Correct {_plural(len(returned), 'impact report')} returned to you",
                    description="The reviewer left a note; the correction is a new version.",
                    url=_one_or_register(
                        returned, "/ia/impact-reports/?status=returned"
                    ),
                    action="Correct Report",
                    count=len(returned),
                    oldest=min(r["reviewed_at"] or r["updated_at"] for r in returned),
                    today=today,
                )
            )
        to_release = [
            r for r in rows if r["status"] == rp.REVIEWED and r["reviewed_by_id"] == me
        ]
        if to_release:
            out.append(
                _row(
                    "ia-reports-release",
                    title=f"Release {_plural(len(to_release), 'reviewed impact report')} to country leadership",
                    description="You reviewed it; the Country Director reads and answers it once released.",
                    url=_one_or_register(
                        to_release, "/ia/impact-reports/?status=reviewed"
                    ),
                    action="Release Report",
                    count=len(to_release),
                    oldest=min(r["reviewed_at"] or r["updated_at"] for r in to_release),
                    today=today,
                    late_after=3,
                )
            )
    if role == CD:
        from django.db.models import Q

        recommendations = list(
            ImpactReportRecommendation.objects.filter(
                report__in=rp.visible_reports(principal), report__status=rp.RELEASED
            )
            .filter(
                Q(status="proposed")
                | Q(status__in=rp.OPEN_RECOMMENDATIONS, due_date__lt=today)
            )
            .values("id", "report_id", "status", "due_date", "created_at")
        )
        awaiting = [r for r in recommendations if r["status"] == "proposed"]
        if awaiting:
            reports = sorted({r["report_id"] for r in awaiting})
            out.append(
                _row(
                    "ia-report-recommendations-respond",
                    title=f"Respond to {_plural(len(awaiting), 'impact report recommendation')}",
                    description="Accept, defer or reject each with a reason; Impact Assessment reads your answer.",
                    url=f"/ia/impact-reports/{reports[0]}/#recommendations"
                    if len(reports) == 1
                    else "/ia/impact-reports/?status=released",
                    action="Respond",
                    count=len(awaiting),
                    oldest=min(r["created_at"] for r in awaiting),
                    today=today,
                )
            )
        overdue = [
            r for r in recommendations if r["due_date"] and r["due_date"] < today
        ]
        if overdue:
            reports = sorted({r["report_id"] for r in overdue})
            out.append(
                _row(
                    "ia-report-recommendations-overdue",
                    title=f"{_plural(len(overdue), 'impact report recommendation')} past due",
                    description="Proposed, accepted or in progress and past the date agreed.",
                    url=f"/ia/impact-reports/{reports[0]}/#recommendations"
                    if len(reports) == 1
                    else "/ia/impact-reports/?status=released",
                    action="Update Status",
                    count=len(overdue),
                    oldest=min(r["due_date"] for r in overdue),
                    today=today,
                    late_after=0,
                )
            )
    if role == RVP:
        pending = list(
            ImpactReportRelease.objects.filter(
                report__in=rp.visible_reports(principal),
                audience="donor",
                status="pending_approval",
            )
            .exclude(requested_by_id=me)
            .exclude(report__author_id=me)
            .exclude(report__reviewed_by_id=me)
            .values("id", "report_id", "updated_at")
        )
        if pending:
            out.append(
                _row(
                    "ia-report-donor-approve",
                    title=f"Approve {_plural(len(pending), 'donor version')} of impact reports",
                    description="Aggregates only, small cells suppressed; approving releases it to donors.",
                    url=f"/ia/impact-reports/{pending[0]['report_id']}/#releases"
                    if len(pending) == 1
                    else "/ia/impact-reports/?status=released",
                    action="Review Donor Version",
                    count=len(pending),
                    oldest=min(r["updated_at"] for r in pending),
                    today=today,
                )
            )
    return out
