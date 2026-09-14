"""Programme learning and lending evidence To-Dos (IA review, owner, 2026-09-13).

A finding or a loan impact conclusion moves only when the next person acts, so
each derived row names that person's step and opens the drawer or queue that
resolves it:

  - impact findings waiting for my review (a second IA officer in the
    country; the Country Director where there is none — never the author);
  - my findings returned to me;
  - loan impact conclusions prepared by someone else that I may verify (an IA
    officer; for a conclusion IA prepared, a second IA officer or the Country
    Director where the country has one officer);
  - due conclusions for me to prepare, and conclusions returned to me
    (Business Transformation; Impact Assessment where the loan's country has
    no Business Transformation officer);
  - lending evidence the partner reported that waits for IA verification
    (loan use, enrolment, purpose outputs, teacher completion).

Rows are derived, never stored, and grouped per queue: a row disappears when
its queue empties. A fixed number of queries whatever the size of the queues
(apps/impact/test_learning.py pins it). A failure never breaks the queue.
"""

from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

IA = "ImpactAssessment"
CD = "CountryDirector"
BTO = "BusinessTransformationOfficer"
CATEGORY = "Analysis & Learning"
BT_CATEGORY = "Business Transformation"


def _plural(n, word, plural=None):
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def _day(value):
    if value is None:
        return None
    return timezone.localdate(value) if hasattr(value, "tzinfo") else value


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
    oldest_day = _day(oldest)
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


def learning_todos(principal, role, today) -> list[dict]:
    """Registered in apps.command_center.todo_service.MODULE_TODO_BUILDERS."""
    if role not in (IA, CD, BTO):
        return []
    try:
        return _finding_todos(principal, role, today) + _lending_todos(
            principal, role, today
        )
    except Exception:  # noqa: BLE001 - one source never breaks the queue
        logger.exception("Programme learning To-Dos failed")
        return []


def _finding_todos(principal, role, today) -> list[dict]:
    from apps.impact import findings as fs

    if role not in (IA, CD):
        return []
    waiting = fs.waiting_for(principal)
    out = []
    rows = waiting["to_review"]
    if rows:
        oldest = min(r["submitted_at"] or r["updated_at"] for r in rows)
        out.append(
            _row(
                "ia-findings-review",
                title=f"Review {_plural(len(rows), 'impact finding')}"
                if role == IA
                else f"Acknowledge {_plural(len(rows), 'impact finding')} (no second IA officer)",
                description="Written by someone else in your country; a finding is cited only once reviewed.",
                url=(
                    f"/ia/learning/?view=findings&status=in_review&open={rows[0]['id']}"
                    if len(rows) == 1
                    else "/ia/learning/?view=findings&status=in_review"
                ),
                action="Open Findings",
                count=len(rows),
                oldest=oldest,
                today=today,
                category=CATEGORY,
            )
        )
    rows = waiting["returned"]
    if rows:
        out.append(
            _row(
                "ia-findings-returned",
                title=f"Correct {_plural(len(rows), 'impact finding')} returned to you",
                description="The reviewer left a note on what to change.",
                url=(
                    f"/ia/learning/?view=findings&status=returned&open={rows[0]['id']}"
                    if len(rows) == 1
                    else "/ia/learning/?view=findings&status=returned"
                ),
                action="Correct Finding",
                count=len(rows),
                oldest=min(r["updated_at"] for r in rows),
                today=today,
                category=CATEGORY,
            )
        )
    return out


def _lending_todos(principal, role, today) -> list[dict]:
    from django.db.models import Q

    from apps.business_transformation import lending_impact as li
    from apps.business_transformation.models import (
        IAValidationStatus,
        LoanImpactAssessment,
    )
    from apps.impact.review import _profile_country, ia_officer_ids

    me = str(getattr(principal, "id", "") or "")
    my_country = _profile_country(principal)
    loans = li.scoped_impact_loans(principal).values("id")
    rows = list(
        LoanImpactAssessment.objects.filter(loan_id__in=loans)
        .exclude(ia_status=IAValidationStatus.VERIFIED)
        .filter(Q(due_date__lte=today) | Q(prepared_at__isnull=False))
        .values(
            "id",
            "due_date",
            "ia_status",
            "prepared_by",
            "prepared_at",
            "updated_at",
            "baseline_indicators",
            "loan__school__region__country",
        )
        .order_by("due_date")[:500]
    )
    out: list[dict] = []
    category = BT_CATEGORY if role == BTO else CATEGORY
    unprepared = [
        r
        for r in rows
        if r["ia_status"] == IAValidationStatus.PENDING
        and (
            not r["prepared_at"]
            or not r["prepared_by"]
            or r["prepared_by"] == li.LEGACY_PREPARER
        )
        and r["due_date"] <= today
    ]
    prepared = [
        r
        for r in rows
        if r["ia_status"] == IAValidationStatus.PENDING
        and r["prepared_at"]
        and r["prepared_by"]
        and r["prepared_by"] != li.LEGACY_PREPARER
    ]
    returned_to_me = [
        r
        for r in rows
        if r["ia_status"] == IAValidationStatus.RETURNED and r["prepared_by"] == me
    ]

    def by_ia(r):
        return (r["baseline_indicators"] or {}).get("preparedByRole") == IA

    to_verify = []
    if role == IA:
        to_verify = [
            r
            for r in prepared
            if r["prepared_by"] != me
            and (
                not by_ia(r) or (r["loan__school__region__country"] or "") == my_country
            )
        ]
    elif role == CD and my_country:
        officers = [str(i) for i in ia_officer_ids(my_country)]
        to_verify = [
            r
            for r in prepared
            if by_ia(r)
            and (r["loan__school__region__country"] or "") == my_country
            and not [i for i in officers if i != r["prepared_by"]]
        ]
    if to_verify:
        out.append(
            _row(
                "bt-impact-conclusions-verify",
                title=f"Verify {_plural(len(to_verify), 'loan impact conclusion')}",
                description="Prepared by someone else; the classification is published only once verified.",
                url=(
                    f"/ia/lending-evidence/?tab=conclusions&state=awaiting&open={to_verify[0]['id']}"
                    if len(to_verify) == 1
                    else "/ia/lending-evidence/?tab=conclusions&state=awaiting"
                ),
                action="Verify Conclusions",
                count=len(to_verify),
                oldest=min(r["prepared_at"] for r in to_verify),
                today=today,
                category=category,
            )
        )

    to_prepare = []
    if role == BTO:
        to_prepare = unprepared
    elif role == IA:
        countries = {r["loan__school__region__country"] or "" for r in unprepared}
        without_bt = {
            c for c in countries if not li.business_transformation_in_country(c)
        }
        to_prepare = [
            r
            for r in unprepared
            if (r["loan__school__region__country"] or "") in without_bt
        ]
    if to_prepare:
        url = (
            "/business-transformation/impact-reports"
            if role == BTO
            else "/ia/lending-evidence/?tab=conclusions&state=to_prepare"
        )
        out.append(
            _row(
                "bt-impact-conclusions-prepare",
                title=f"Prepare {_plural(len(to_prepare), 'loan impact conclusion')}",
                description="Due: draft each conclusion from the verified evidence for someone else to verify.",
                url=url,
                action="Prepare Conclusions",
                count=len(to_prepare),
                oldest=min(r["due_date"] for r in to_prepare),
                today=today,
                category=category,
            )
        )
    if returned_to_me:
        out.append(
            _row(
                "bt-impact-conclusions-returned",
                title=f"Correct {_plural(len(returned_to_me), 'loan impact conclusion')} returned to you",
                description="The verifier returned it with a note on what to correct.",
                url=(
                    "/business-transformation/impact-reports"
                    if role == BTO
                    else "/ia/lending-evidence/?tab=conclusions&state=returned"
                ),
                action="Correct Conclusions",
                count=len(returned_to_me),
                oldest=min(r["updated_at"] for r in returned_to_me),
                today=today,
                category=category,
            )
        )

    if role == IA:
        from apps.frontend.views import ia_lending_views as lv

        queues = (
            (lv.USE, "Verify reported loan use", lv.use_queue(principal), "updated_at"),
            (
                lv.ENROLMENT,
                "Verify reported enrolment",
                lv.enrolment_queue(principal),
                "created_at",
            ),
            (
                lv.OUTPUTS,
                "Verify loan purpose outputs",
                lv.output_queue(principal),
                "updated_at",
            ),
            (
                lv.TEACHERS,
                "Verify teacher completions",
                lv.teacher_queue(principal),
                "updated_at",
            ),
        )
        for key, title, queryset, field in queues:
            stamps = list(queryset.order_by(field).values_list(field, flat=True)[:200])
            if not stamps:
                continue
            out.append(
                _row(
                    f"bt-lending-evidence-{key}",
                    title=f"{title} ({len(stamps)})",
                    description="Reported by the lending partner; it counts as evidence once IA verifies it.",
                    url=f"/ia/lending-evidence/?tab={key}",
                    action="Open Lending Evidence",
                    count=len(stamps),
                    oldest=stamps[0],
                    today=today,
                    category=CATEGORY,
                    priority="normal",
                )
            )
    return out
