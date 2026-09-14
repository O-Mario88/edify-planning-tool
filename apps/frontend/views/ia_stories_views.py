"""Most Significant Change review (/ia/stories/, IA review, owner, 2026-09-13).

Impact Assessment reads the change stories told in its country and approves,
returns or rejects each submitted one, tagging the outcome area (and SSA
domain) an approved story evidences. The rules live in
apps.targets.mscs_review: the reviewer is never the author, every decision is
audited and tells the author, and an approved story counts on the author's My
Targets and as discipleship evidence on the Outcomes view.
"""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.enums import SsaIntervention
from apps.core.fy import fy_options, get_operational_fy
from apps.core.metrics import render_precomputed_metric_for_source
from apps.core.permissions import require_page_permission
from apps.frontend.views.hr_programme_views import SERVICE_ERRORS, _drawer, _field
from apps.targets import mscs_review
from apps.targets.models import MSCSStatus

PAGE_URL = "/ia/stories/"
STATUS_TONES = {
    MSCSStatus.SUBMITTED: "warning",
    MSCSStatus.APPROVED: "success",
    MSCSStatus.RETURNED: "danger",
    MSCSStatus.REJECTED: "neutral",
    MSCSStatus.DRAFT: "neutral",
    MSCSStatus.ARCHIVED: "neutral",
}
INTERVENTION_LABELS = dict(SsaIntervention.choices)


def _metric(label: str, value, helper: str, tone="info") -> dict:
    return render_precomputed_metric_for_source(
        "apps.frontend.views.ia_stories_views:_metric",
        label,
        value,
        helper=helper,
        tone=tone,
    )


def _cell(heading, text, *, primary=False, tone=""):
    return {
        "heading": heading,
        "text": "—" if text in (None, "") else str(text),
        "primary": primary,
        "tone": tone,
    }


def _day(value) -> str:
    return f"{value:%-d %b %Y}" if value else ""


def _back(request):
    from apps.frontend.views.coaching_views import safe_return_url

    return redirect(safe_return_url(request, PAGE_URL, drop=("open",)))


def _names(user_ids) -> dict[str, str]:
    from apps.accounts.models import User

    return dict(
        User.objects.filter(id__in={i for i in user_ids if i}).values_list("id", "name")
    )


@require_page_permission("ia_stories")
@require_http_methods(["GET"])
def stories_page(request):
    """The change stories told in the reader's country."""
    from django.db.models import Count, Q

    from apps.analytics.ia_collection import db_page

    fy_choices = fy_options()
    fy = request.GET.get("fy") or ""
    if fy not in fy_choices:
        fy = get_operational_fy()
    status = request.GET.get("status")
    if status is None:
        status = MSCSStatus.SUBMITTED
    if status and status not in MSCSStatus.values:
        status = ""

    stories = mscs_review.visible_stories(request.user)
    in_year = mscs_review.fy_q(fy)
    counts = stories.aggregate(
        waiting=Count("id", filter=Q(status=MSCSStatus.SUBMITTED)),
        approved=Count("id", filter=Q(status=MSCSStatus.APPROVED) & in_year),
        spiritual=Count(
            "id",
            filter=Q(status=MSCSStatus.APPROVED)
            & in_year
            & mscs_review.spiritual_story_q(),
        ),
        not_accepted=Count(
            "id",
            filter=Q(status__in=(MSCSStatus.RETURNED, MSCSStatus.REJECTED)) & in_year,
        ),
    )
    metrics = [
        _metric(
            "Change Stories Awaiting Review",
            counts["waiting"],
            "reviewed by someone other than the author",
            "warning" if counts["waiting"] else "info",
        ),
        _metric(
            "Change Stories Approved This Year",
            counts["approved"],
            f"FY{fy}, {counts['spiritual']} evidencing spiritual formation",
            "success" if counts["approved"] else "info",
        ),
        _metric(
            "Change Stories Returned or Rejected This Year",
            counts["not_accepted"],
            f"FY{fy}",
        ),
    ]

    listed = stories.select_related("school")
    if status:
        listed = listed.filter(status=status)
    if status != MSCSStatus.SUBMITTED:
        listed = listed.filter(in_year)
    page = db_page(
        listed.order_by("-story_date", "-created_at"), request.GET.get("register_page")
    )
    records = page.pop("rows")
    names = _names([s.user_id for s in records] + [s.reviewed_by for s in records])
    areas = dict(mscs_review.outcome_area_options())
    me = str(request.user.id)
    rows = []
    for story in records:
        tag = " · ".join(
            t
            for t in (
                areas.get(story.outcome_area, story.outcome_area),
                INTERVENTION_LABELS.get(story.intervention, ""),
            )
            if t
        )
        reviewable = story.status == MSCSStatus.SUBMITTED and story.user_id != me
        rows.append(
            {
                "cells": [
                    _cell("Story", story.title, primary=True),
                    _cell("School", getattr(story.school, "name", "")),
                    _cell("Told by", names.get(story.user_id, "Staff member")),
                    _cell("Story date", _day(story.story_date)),
                    _cell(
                        "Status",
                        story.get_status_display()
                        + (f": {story.return_reason}" if story.return_reason else ""),
                        tone=STATUS_TONES.get(story.status, ""),
                    ),
                    _cell("Evidences", tag),
                    _cell("Reviewed by", names.get(story.reviewed_by or "", "")),
                ],
                "actions": [
                    {
                        "label": "Review" if reviewable else "Open",
                        "drawer": f"{PAGE_URL}{story.id}/",
                    }
                ],
            }
        )
    return render(
        request,
        "pages/ia/stories.html",
        {
            "metrics": metrics,
            "filters": {
                "fields": [
                    {
                        "name": "status",
                        "label": "Status",
                        "value": status,
                        "blank": "Every status",
                        "options": [
                            (value, label)
                            for value, label in MSCSStatus.choices
                            if value != MSCSStatus.DRAFT
                        ],
                    },
                    {
                        "name": "fy",
                        "label": "Financial year",
                        "value": fy,
                        "blank": "",
                        "options": [(o, f"FY{o}") for o in fy_choices],
                    },
                ]
            },
            "register": {
                "title": "Most Significant Change stories",
                "subtitle": (
                    "Every submitted story, whatever its date"
                    if status == MSCSStatus.SUBMITTED
                    else f"FY{fy}"
                ),
                "rows": rows,
                "pager": page,
                "param": "register_page",
                "has_actions": bool(rows),
                "empty_title": "No stories here",
                "empty_body": "Stories reach this list when staff submit them from My Targets or a field debrief.",
            },
            "autoload_drawer": _autoload(request, stories),
        },
    )


def _autoload(request, stories) -> str:
    target = (request.GET.get("open") or "").strip()
    if target and stories.filter(id=target).exists():
        return f"{PAGE_URL}{target}/"
    return ""


@require_page_permission("ia_stories")
@require_http_methods(["GET"])
def story_drawer(request, story_id):
    try:
        story = mscs_review.assert_readable(request.user, story_id)
    except SERVICE_ERRORS as exc:
        return _drawer(
            request,
            title="Most Significant Change story",
            subtitle="Change stories",
            empty=str(getattr(exc, "detail", exc)),
        )
    names = _names([story.user_id, story.reviewed_by])
    areas = dict(mscs_review.outcome_area_options())
    facts = [
        {"label": "Told by", "value": names.get(story.user_id, "Staff member")},
        {"label": "School", "value": getattr(story.school, "name", "")},
        {"label": "Story date", "value": _day(story.story_date)},
        {"label": "The story", "value": story.narrative},
        {"label": "Evidence", "value": story.evidence_uri or ""},
        {"label": "Status", "value": story.get_status_display()},
    ]
    if story.reviewed_by:
        facts.append(
            {
                "label": "Reviewed by",
                "value": f"{names.get(story.reviewed_by, 'Reviewer')} · {_day(story.reviewed_at)}",
            }
        )
    if story.outcome_area or story.intervention:
        facts.append(
            {
                "label": "Evidences",
                "value": " · ".join(
                    t
                    for t in (
                        areas.get(story.outcome_area, story.outcome_area),
                        INTERVENTION_LABELS.get(story.intervention, ""),
                    )
                    if t
                ),
            }
        )
    if story.return_reason:
        facts.append({"label": "Reason", "value": story.return_reason})

    basis = mscs_review.review_basis(request.user, story)
    if not basis:
        if story.status != MSCSStatus.SUBMITTED:
            note = "Reviewed. The decision is in the audit trail."
        elif story.user_id == str(request.user.id):
            note = (
                "You told this story, so another Impact Assessment officer reviews it."
            )
        else:
            note = "Only a second Impact Assessment officer in this country reviews it."
        return _drawer(
            request, title=story.title, subtitle="Change story", facts=facts, empty=note
        )
    return _drawer(
        request,
        title=story.title,
        subtitle="Review a change story",
        action=f"{PAGE_URL}{story.id}/decide",
        facts=facts,
        fields=[
            _field(
                "decision",
                "Decision",
                type="select",
                required=True,
                options=mscs_review.DECISIONS,
                value="approve",
            ),
            _field(
                "outcome_area",
                "Outcome area it evidences",
                type="select",
                options=mscs_review.outcome_area_options(),
                blank="Choose (needed to approve)",
            ),
            _field(
                "intervention",
                "SSA domain it speaks to",
                type="select",
                options=SsaIntervention.choices,
                blank="None",
            ),
            _field(
                "note",
                "Note to the author",
                type="textarea",
                rows=3,
                maxlength=512,
                help="Required when you return or reject the story.",
            ),
        ],
        submit="Save decision",
        note=(
            "Approve a story that shows a change in the school, credibly told. An "
            "approved story counts on its author's My Targets."
        ),
    )


@require_page_permission("ia_stories")
@require_POST
def story_decide(request, story_id):
    decision = request.POST.get("decision") or ""
    try:
        story = mscs_review.decide(
            request.user,
            story_id,
            decision=decision,
            note=request.POST.get("note", ""),
            outcome_area=request.POST.get("outcome_area", ""),
            intervention=request.POST.get("intervention", ""),
        )
    except SERVICE_ERRORS as exc:
        messages.error(request, str(getattr(exc, "detail", exc)))
        return _back(request)
    messages.success(request, f"“{story.title}” {story.get_status_display().lower()}.")
    return _back(request)
