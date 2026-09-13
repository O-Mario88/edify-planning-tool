"""Screens for the CCE Regional Lead's own records (owner, 2026-09-13).

The engagement log (coaching conversations, meetings, visits and training
observations), the training feedback a Programme Lead acknowledges, and the
monthly report the RVP reviews. Rules, permissions and audit rows live in
apps.cce_leadership.services; these views render and route, so a refusal the
service raises is the message the reader sees. Drawers reuse the one-column
form drawer the HR programme actions introduced (partials/hr/form_drawer.html).
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib import messages
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.cce_leadership import services
from apps.cce_leadership.models import (
    OBSERVATION_CRITERIA,
    RATING_SCALE,
    REPORT_SECTIONS,
    EngagementKind,
    ObservationRecommendation,
    ReportStatus,
)
from apps.core.fy import (
    get_quarter_date_range,
    get_quarter_for_date,
    get_operational_fy,
)
from apps.core.metrics import render_precomputed_metric_for_source
from apps.core.permissions import require_page_permission
from apps.frontend.views.hr_programme_views import (
    SERVICE_ERRORS,
    _back,
    _drawer,
    _field,
    _refused,
)

ENGAGEMENTS_URL = "/cce-leadership/engagements"
FEEDBACK_URL = "/cce-leadership/feedback"
REPORTS_URL = "/cce-leadership/reports"

KIND_LABELS = dict(EngagementKind.choices)
RECOMMENDATION_LABELS = dict(ObservationRecommendation.choices)
RATING_LABELS = dict(RATING_SCALE)
STATUS_TONES = {
    ReportStatus.DRAFT: "neutral",
    ReportStatus.SUBMITTED: "warning",
    ReportStatus.ACKNOWLEDGED: "success",
    ReportStatus.RETURNED: "danger",
}


def _metric(label: str, value, helper: str, tone="info") -> dict:
    return render_precomputed_metric_for_source(
        "apps.frontend.views.cce_leadership_views:_metric",
        label,
        value,
        helper=helper,
        tone=tone,
    )


def _cell(heading: str, text, *, primary=False, tone="") -> dict:
    """One register cell: its column heading and its text, with an optional
    tone for status words (the plain-table rule: text, never pills)."""
    return {
        "heading": heading,
        "text": "—" if text in (None, "") else str(text),
        "primary": primary,
        "tone": tone,
    }


def _day(value) -> str:
    return f"{value:%-d %b %Y}" if value else ""


def _is_lead(request) -> bool:
    return request.user.active_role == services.REGIONAL_LEAD


def _render(
    request,
    *,
    title,
    eyebrow,
    description,
    metrics,
    rows,
    register_title,
    empty_title,
    empty_body,
    header_actions=(),
    notice=None,
    filters=None,
    rhythm=None,
):
    return render(
        request,
        "pages/cce_leadership/workspace.html",
        {
            "title": title,
            "eyebrow": eyebrow,
            "description": description,
            "metrics": metrics,
            "rows": rows,
            "has_row_actions": any(row.get("actions") for row in rows),
            "register_title": register_title,
            "empty_title": empty_title,
            "empty_body": empty_body,
            "header_actions": list(header_actions),
            "notice": notice,
            "filters": filters,
            "rhythm": rhythm,
        },
    )


def _lead_names(reach) -> dict[str, str]:
    return {lead["staff_id"]: lead["name"] for lead in reach.leads}


def _author_names(author_ids) -> dict[str, str]:
    from apps.accounts.models import User

    return dict(User.objects.filter(id__in=set(author_ids)).values_list("id", "name"))


# ── Engagement log ───────────────────────────────────────────────────────────
def _feedback_state(engagement) -> tuple[str, str]:
    if not engagement.is_observation:
        return "", ""
    if engagement.acknowledged_at:
        return "Acknowledged", "success"
    if engagement.feedback_shared_at:
        return "Awaiting the Programme Lead", "warning"
    return "Not shared yet", "neutral"


@require_page_permission("cce_engagements")
@require_http_methods(["GET"])
def engagements_view(request):
    """Everything the Regional Lead has recorded, and the rhythm it keeps."""
    today = timezone.localdate()
    reach = services.lead_reach(request.user)
    engagements = services.engagements_visible_to(request.user)
    kind = request.GET.get("kind") or ""
    country = request.GET.get("country") or ""
    if kind in EngagementKind.values:
        engagements = engagements.filter(kind=kind)
    if country in reach.countries:
        engagements = engagements.filter(country=country)

    names = _lead_names(reach)
    rows = []
    for engagement in engagements.order_by("-held_on", "-created_at")[:500]:
        with_whom = ", ".join(
            names.get(staff_id, "Programme Lead")
            for staff_id in engagement.program_lead_ids
        )
        state, tone = _feedback_state(engagement)
        rows.append(
            {
                "cells": [
                    _cell("Engagement", engagement.subject, primary=True),
                    _cell("Kind", KIND_LABELS.get(engagement.kind, engagement.kind)),
                    _cell("Held", _day(engagement.held_on)),
                    _cell("With", with_whom or engagement.country),
                    _cell("Feedback", state, tone=tone),
                ],
                "actions": [
                    {"label": "Open", "drawer": f"{ENGAGEMENTS_URL}/{engagement.id}"}
                ],
            }
        )

    mine = services.engagements_visible_to(request.user)
    quarter_start, quarter_end = (
        d.date()
        for d in get_quarter_date_range(
            get_operational_fy(today), get_quarter_for_date(today)
        )
    )
    in_quarter = mine.filter(held_on__gte=quarter_start, held_on__lt=quarter_end)
    rhythm = services.rhythm(request.user, today=today) if _is_lead(request) else None
    metrics = [
        _metric(
            "Coaching Conversations (30 Days)",
            mine.filter(
                kind=EngagementKind.PL_COACHING,
                held_on__gte=today - timedelta(days=30),
            ).count(),
            f"with {len(reach.leads)} Programme Lead{'s' if len(reach.leads) != 1 else ''} in reach",
        ),
        _metric(
            "Trainings Observed This Quarter",
            in_quarter.filter(kind=EngagementKind.TRAINING_OBSERVATION).count(),
            "observations recorded",
        ),
        _metric(
            "Country Reviews This Quarter",
            in_quarter.filter(kind=EngagementKind.CD_QUARTERLY_REVIEW).count(),
            f"of {len(reach.countries)} countr{'ies' if len(reach.countries) != 1 else 'y'}",
        ),
        _metric(
            "Engagements Overdue",
            rhythm["counts"]["attention"] if rhythm else 0,
            "in the rhythm the role sets",
            "danger" if rhythm and rhythm["counts"]["attention"] else "info",
        ),
    ]
    header_actions = (
        [
            {"label": "Log an engagement", "drawer": f"{ENGAGEMENTS_URL}/new"},
            {
                "label": "Observe a training",
                "drawer": f"{ENGAGEMENTS_URL}/new?kind={EngagementKind.TRAINING_OBSERVATION}",
            },
        ]
        if _is_lead(request)
        else []
    )
    notice = None
    if _is_lead(request) and not reach.assigned:
        notice = {
            "tone": "info",
            "text": (
                "No countries are assigned to your account yet, so every country is "
                "in reach. An administrator narrows it to your region on your staff record."
            ),
        }
    return _render(
        request,
        title="CCE Engagement Log",
        eyebrow="Regional CCE leadership",
        description=(
            "Coaching conversations with Programme Leads, meetings with Country "
            "Directors, the RVP and the VP of CCE, school visits, partner and "
            "network meetings, and the trainings you observe."
        ),
        metrics=metrics,
        rows=rows,
        register_title="Engagements",
        empty_title="Nothing recorded yet",
        empty_body=(
            "Log a coaching conversation or observe a training; each one keeps "
            "your rhythm with Programme Leads and Country Directors up to date."
        ),
        header_actions=header_actions,
        notice=notice,
        filters={
            "fields": [
                {
                    "name": "kind",
                    "label": "Kind",
                    "value": kind,
                    "blank": "Every kind",
                    "options": EngagementKind.choices,
                },
                {
                    "name": "country",
                    "label": "Country",
                    "value": country,
                    "blank": "Every country",
                    "options": [(c, c) for c in reach.countries],
                },
            ]
        },
        rhythm=rhythm,
    )


def _lead_options(reach):
    return [
        (
            lead["staff_id"],
            f"{lead['name']} · {lead['country']}" if lead["country"] else lead["name"],
        )
        for lead in reach.leads
    ]


def _general_fields(reach, *, engagement=None, kind=""):
    today = timezone.localdate()
    choices = [
        choice
        for choice in EngagementKind.choices
        if choice[0] != EngagementKind.TRAINING_OBSERVATION
    ]
    return [
        _field(
            "kind",
            "Kind of engagement",
            type="select" if engagement is None else "hidden",
            required=True,
            value=engagement.kind if engagement else kind,
            options=choices,
            blank="Choose the kind",
        ),
        _field(
            "held_on",
            "Held on",
            type="date",
            required=True,
            value=(engagement.held_on if engagement else today).isoformat(),
        ),
        _field(
            "program_lead_ids",
            "Programme Leads",
            type="multiselect",
            value=list(engagement.program_lead_ids) if engagement else [],
            options=_lead_options(reach),
            rows=5,
            help="Everyone you met; a coaching conversation names at least one.",
        ),
        _field(
            "country",
            "Country",
            type="select",
            value=engagement.country if engagement else "",
            options=[(c, c) for c in reach.countries],
            blank="No single country",
            help="Required for a Country Director review or the annual budget input.",
        ),
        _field(
            "subject",
            "Subject",
            value=engagement.subject if engagement else "",
            maxlength=255,
            placeholder="Filled in from the kind and the people when left empty",
        ),
        _field(
            "notes",
            "What was discussed",
            type="textarea",
            rows=4,
            value=engagement.notes if engagement else "",
            placeholder="Progress on CCE KPIs, training needs, lessons learned",
        ),
        _field(
            "agreed_actions",
            "Agreed actions",
            type="textarea",
            rows=3,
            value=engagement.agreed_actions if engagement else "",
        ),
        _field(
            "follow_up_due",
            "Follow up by",
            type="date",
            value=engagement.follow_up_due.isoformat()
            if engagement and engagement.follow_up_due
            else "",
        ),
    ]


def _observation_fields(request, reach, *, engagement=None):
    today = timezone.localdate()
    trainings = list(services.observable_trainings(request.user, today=today)[:200])
    options = [(a.id, services.training_label(a)) for a in trainings]
    if (
        engagement
        and engagement.activity_id
        and engagement.activity_id not in {o[0] for o in options}
    ):
        options.insert(
            0, (engagement.activity_id, services.training_label(engagement.activity))
        )
    fields = [
        _field("kind", "", type="hidden", value=EngagementKind.TRAINING_OBSERVATION),
        _field(
            "activity_id",
            "Training observed",
            type="select",
            required=True,
            value=engagement.activity_id if engagement else "",
            options=options,
            blank="Choose the training",
        ),
        _field(
            "held_on",
            "Observed on",
            type="date",
            required=True,
            value=(engagement.held_on if engagement else today).isoformat(),
        ),
    ]
    for name, label, hint in OBSERVATION_CRITERIA:
        fields.append(
            _field(
                name,
                label,
                type="select",
                required=True,
                value=getattr(engagement, name) if engagement else "",
                options=RATING_SCALE,
                blank="Rate from 1 to 4",
                help=hint,
            )
        )
    fields += [
        _field(
            "recommendation",
            "Recommendation",
            type="select",
            required=True,
            value=engagement.recommendation if engagement else "",
            options=ObservationRecommendation.choices,
            blank="Choose a recommendation",
        ),
        _field(
            "feedback",
            "Feedback for the Programme Lead",
            type="textarea",
            required=True,
            rows=5,
            value=engagement.feedback if engagement else "",
            placeholder="What worked, what to change, and what to ask of the training partner",
        ),
        _field(
            "program_lead_ids",
            "Send to",
            type="multiselect",
            value=list(engagement.program_lead_ids) if engagement else [],
            options=_lead_options(reach),
            rows=4,
            help="Leave empty to send it to the Programme Lead of the team that ran the training.",
        ),
        _field(
            "notes",
            "Private notes",
            type="textarea",
            rows=3,
            value=engagement.notes if engagement else "",
            help="Kept in your log; not shared with the Programme Lead.",
        ),
        _field(
            "share_now",
            "Share the feedback with the Programme Lead now",
            type="checkbox",
            help="They are notified and asked to acknowledge it. Shared feedback can no longer be edited.",
        ),
    ]
    return fields, options


def _engagement_data(request) -> dict:
    data = {key: request.POST.get(key) for key in request.POST}
    data["program_lead_ids"] = request.POST.getlist("program_lead_ids")
    return data


@require_page_permission("cce_engagements")
@require_http_methods(["GET"])
def engagement_new_drawer(request):
    reach = services.lead_reach(request.user)
    if not _is_lead(request):
        return _drawer(
            request,
            title="Log an engagement",
            subtitle="Regional CCE leadership",
            empty="Only the Regional Programme Lead records CCE engagements.",
        )
    if request.GET.get("kind") == EngagementKind.TRAINING_OBSERVATION:
        fields, options = _observation_fields(request, reach)
        subtitle = (
            "Constructive critique for the Programme Lead and the training partner"
        )
        if not options:
            return _drawer(
                request,
                title="Observe a training",
                subtitle=subtitle,
                empty=(
                    "No training in your region was held in the last four months or is "
                    "planned for the next two weeks."
                ),
            )
        return _drawer(
            request,
            title="Observe a training",
            subtitle=subtitle,
            action=f"{ENGAGEMENTS_URL}/record",
            submit="Record observation",
            fields=fields,
            note=(
                "Rate what you saw against Edify's Biblical integration framework "
                "and the schools' SSA needs, then say what should change."
            ),
        )
    return _drawer(
        request,
        title="Log an engagement",
        subtitle="A conversation, meeting or visit you held",
        action=f"{ENGAGEMENTS_URL}/record",
        submit="Record engagement",
        fields=_general_fields(reach, kind=request.GET.get("kind") or ""),
    )


@require_page_permission("cce_engagements")
@require_POST
def engagement_record(request):
    data = _engagement_data(request)
    try:
        engagement = services.record_engagement(request.user, data)
        if engagement.is_observation and data.get("share_now"):
            services.share_feedback(request.user, engagement.id)
            messages.success(
                request, "Observation recorded and shared with the Programme Lead."
            )
        else:
            messages.success(request, "Engagement recorded.")
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, ENGAGEMENTS_URL)
    return _back(request, ENGAGEMENTS_URL)


def _engagement_facts(engagement, names) -> list[dict]:
    facts = [
        {"label": "Kind", "value": KIND_LABELS.get(engagement.kind, engagement.kind)},
        {"label": "Held on", "value": _day(engagement.held_on)},
        {"label": "Country", "value": engagement.country},
        {
            "label": "Programme Leads",
            "value": ", ".join(
                names.get(i, "Programme Lead") for i in engagement.program_lead_ids
            ),
        },
    ]
    if engagement.is_observation:
        facts.append(
            {
                "label": "Training",
                "value": services.training_label(engagement.activity)
                if engagement.activity_id
                else engagement.subject,
            }
        )
        for name, label, _hint in OBSERVATION_CRITERIA:
            facts.append(
                {
                    "label": label,
                    "value": RATING_LABELS.get(getattr(engagement, name), ""),
                }
            )
        facts += [
            {
                "label": "Average rating",
                "value": f"{engagement.average_rating} of 4"
                if engagement.average_rating
                else "",
            },
            {
                "label": "Recommendation",
                "value": RECOMMENDATION_LABELS.get(engagement.recommendation, ""),
            },
            {"label": "Feedback", "value": engagement.feedback},
            {"label": "Shared", "value": _day(engagement.feedback_shared_at)},
            {"label": "Acknowledged", "value": _day(engagement.acknowledged_at)},
            {"label": "Programme Lead's response", "value": engagement.lead_response},
        ]
    else:
        facts += [
            {"label": "Subject", "value": engagement.subject},
            {"label": "What was discussed", "value": engagement.notes},
            {"label": "Agreed actions", "value": engagement.agreed_actions},
            {"label": "Follow up by", "value": _day(engagement.follow_up_due)},
        ]
    return facts


@require_page_permission("cce_engagements")
@require_http_methods(["GET"])
def engagement_drawer(request, engagement_id):
    engagement = (
        services.engagements_visible_to(request.user).filter(id=engagement_id).first()
    )
    if engagement is None:
        return _drawer(
            request,
            title="Engagement",
            subtitle="Regional CCE leadership",
            empty="This engagement is not in your log.",
        )
    reach = services.lead_reach(request.user)
    names = _lead_names(reach)
    editable = (
        _is_lead(request)
        and engagement.author_id == services._uid(request.user)
        and not engagement.feedback_shared_at
    )
    if not editable:
        return _drawer(
            request,
            title=engagement.subject,
            subtitle=KIND_LABELS.get(engagement.kind, engagement.kind),
            facts=_engagement_facts(engagement, names),
            empty=(
                "This feedback has been shared with the Programme Lead and can no longer be edited."
                if engagement.feedback_shared_at
                else "Read only."
            ),
        )
    if engagement.is_observation:
        fields, _options = _observation_fields(request, reach, engagement=engagement)
        note = "The feedback stays private to you until you share it."
    else:
        fields = _general_fields(reach, engagement=engagement)
        note = ""
    return _drawer(
        request,
        title=engagement.subject,
        subtitle=KIND_LABELS.get(engagement.kind, engagement.kind),
        action=f"{ENGAGEMENTS_URL}/{engagement.id}/update",
        submit="Save",
        fields=fields,
        note=note,
    )


@require_page_permission("cce_engagements")
@require_POST
def engagement_update(request, engagement_id):
    data = _engagement_data(request)
    try:
        engagement = services.update_engagement(request.user, engagement_id, data)
        if engagement.is_observation and data.get("share_now"):
            services.share_feedback(request.user, engagement.id)
            messages.success(
                request, "Observation saved and shared with the Programme Lead."
            )
        else:
            messages.success(request, "Engagement saved.")
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, ENGAGEMENTS_URL)
    return _back(request, ENGAGEMENTS_URL)


# ── Training feedback ────────────────────────────────────────────────────────
@require_page_permission("cce_training_feedback")
@require_http_methods(["GET"])
def feedback_view(request):
    """Observations of the reader's trainings, and what was done about them."""
    observations = list(
        services.feedback_visible_to(request.user).order_by("-held_on", "-created_at")[
            :500
        ]
    )
    authors = _author_names(o.author_id for o in observations)
    is_pl = request.user.active_role == services.PROGRAM_LEAD
    rows = []
    for observation in observations:
        if observation.acknowledged_at:
            state, tone = "Acknowledged", "success"
        elif observation.feedback_shared_at:
            state = (
                "Awaiting your acknowledgement"
                if is_pl
                else "Awaiting the Programme Lead"
            )
            tone = "warning"
        else:
            state, tone = "Not shared yet", "neutral"
        rows.append(
            {
                "cells": [
                    _cell(
                        "Training",
                        services.training_label(observation.activity)
                        if observation.activity_id
                        else observation.subject,
                        primary=True,
                    ),
                    _cell("Observed", _day(observation.held_on)),
                    _cell("Country", observation.country),
                    _cell("Regional Lead", authors.get(observation.author_id, "")),
                    _cell(
                        "Rating",
                        f"{observation.average_rating} of 4"
                        if observation.average_rating
                        else "",
                    ),
                    _cell(
                        "Recommendation",
                        RECOMMENDATION_LABELS.get(observation.recommendation, ""),
                    ),
                    _cell("State", state, tone=tone),
                ],
                "actions": [
                    {"label": "Open", "drawer": f"{FEEDBACK_URL}/{observation.id}"}
                ],
            }
        )
    shared = [o for o in observations if o.feedback_shared_at]
    ratings = [o.average_rating for o in observations if o.average_rating]
    awaiting = sum(1 for o in shared if not o.acknowledged_at)
    metrics = [
        _metric(
            "Feedback Awaiting Acknowledgement",
            awaiting,
            "shared, not yet acknowledged",
            "warning" if awaiting else "info",
        ),
        _metric(
            "Feedback Acknowledged",
            sum(1 for o in shared if o.acknowledged_at),
            "with the Programme Lead's response",
            "success",
        ),
        _metric(
            "Average Observation Rating",
            f"{round(sum(ratings) / len(ratings), 1)} / 4" if ratings else "—",
            f"across {len(ratings)} observation{'s' if len(ratings) != 1 else ''}",
        ),
    ]
    return _render(
        request,
        title="Training Feedback",
        eyebrow="Training quality",
        description=(
            "The Regional Lead observes trainings and offers constructive critique. "
            "The Programme Lead acknowledges each piece of feedback and says what "
            "will change."
        ),
        metrics=metrics,
        rows=rows,
        register_title="Observed trainings",
        empty_title="No training feedback yet",
        empty_body="Feedback appears here when the Regional Lead shares an observation of a training.",
    )


@require_page_permission("cce_training_feedback")
@require_http_methods(["GET"])
def feedback_drawer(request, engagement_id):
    observation = (
        services.feedback_visible_to(request.user).filter(id=engagement_id).first()
    )
    if observation is None:
        return _drawer(
            request,
            title="Training feedback",
            subtitle="Training quality",
            empty="This feedback is not addressed to you.",
        )
    reach_names = {}
    if observation.program_lead_ids:
        from apps.accounts.models import StaffProfile

        reach_names = dict(
            StaffProfile.objects.filter(
                id__in=observation.program_lead_ids
            ).values_list("id", "user__name")
        )
    facts = [
        fact
        for fact in _engagement_facts(observation, reach_names)
        if fact["label"] != "Kind"
    ]
    facts.insert(
        0,
        {
            "label": "Regional Lead",
            "value": _author_names([observation.author_id]).get(
                observation.author_id, ""
            ),
        },
    )
    can_acknowledge = (
        request.user.active_role == services.PROGRAM_LEAD
        and observation.feedback_shared_at
        and not observation.acknowledged_at
    )
    if not can_acknowledge:
        return _drawer(
            request,
            title="Training feedback",
            subtitle=observation.subject,
            facts=facts,
            empty="Acknowledged." if observation.acknowledged_at else "Read only.",
        )
    return _drawer(
        request,
        title="Training feedback",
        subtitle=observation.subject,
        facts=facts,
        action=f"{FEEDBACK_URL}/{observation.id}/acknowledge",
        submit="Acknowledge feedback",
        fields=[
            _field(
                "response",
                "Your response",
                type="textarea",
                required=True,
                rows=4,
                placeholder="What will change in the training, with whom, and by when",
            )
        ],
    )


@require_page_permission("cce_training_feedback")
@require_POST
def feedback_acknowledge(request, engagement_id):
    try:
        services.acknowledge_feedback(
            request.user, engagement_id, request.POST.get("response", "")
        )
        messages.success(
            request, "Feedback acknowledged. The Regional Lead has been told."
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, FEEDBACK_URL)
    return _back(request, FEEDBACK_URL)


# ── Monthly reports ──────────────────────────────────────────────────────────
@require_page_permission("cce_reports")
@require_http_methods(["GET"])
def reports_view(request):
    """The Regional Lead's monthly reports and the RVP's review of them."""
    today = timezone.localdate()
    reports = list(
        services.reports_visible_to(request.user).order_by("-period", "-created_at")[
            :240
        ]
    )
    is_lead = _is_lead(request)
    authors = _author_names(r.author_id for r in reports) if not is_lead else {}
    reviewers = _author_names(r.reviewed_by_id for r in reports if r.reviewed_by_id)
    rows = []
    for report in reports:
        cells = [_cell("Month", f"{report.period:%B %Y}", primary=True)]
        if not is_lead:
            cells.append(_cell("Regional Lead", authors.get(report.author_id, "")))
        cells += [
            _cell("Countries", ", ".join(report.countries)),
            _cell(
                "Status",
                report.get_status_display(),
                tone=STATUS_TONES.get(report.status, ""),
            ),
            _cell("Submitted", _day(report.submitted_at)),
            _cell(
                "Review",
                f"{reviewers.get(report.reviewed_by_id, 'RVP')} · {_day(report.reviewed_at)}"
                if report.reviewed_at
                else "",
            ),
        ]
        action = "Open"
        if is_lead and report.status in (ReportStatus.DRAFT, ReportStatus.RETURNED):
            action = "Write"
        elif not is_lead and report.status == ReportStatus.SUBMITTED:
            action = "Review"
        rows.append(
            {
                "cells": cells,
                "actions": [{"label": action, "drawer": f"{REPORTS_URL}/{report.id}"}],
            }
        )
    counts = {
        status: sum(1 for r in reports if r.status == status)
        for status in ReportStatus.values
    }
    metrics = [
        _metric("Report Drafts", counts[ReportStatus.DRAFT], "being written"),
        _metric(
            "Reports Awaiting Review",
            counts[ReportStatus.SUBMITTED],
            "with the RVP" if is_lead else "for you to acknowledge or return",
            "warning" if counts[ReportStatus.SUBMITTED] else "info",
        ),
        _metric(
            "Reports Returned",
            counts[ReportStatus.RETURNED],
            "to revise and resubmit",
            "danger" if counts[ReportStatus.RETURNED] else "info",
        ),
        _metric(
            "Reports Acknowledged",
            counts[ReportStatus.ACKNOWLEDGED],
            "closed",
            "success",
        ),
    ]
    notice = None
    if is_lead:
        state = services.report_state(request.user, today=today)
        if state["previous_overdue"]:
            notice = {
                "tone": "warning",
                "text": (
                    f"The {state['previous_period']:%B %Y} report was due by "
                    f"{state['previous_due_by']:%-d %B}. Start it or finish it and submit it."
                ),
            }
    return _render(
        request,
        title="Monthly CCE Reports" if is_lead else "Regional CCE Reports",
        eyebrow="Collaboration and reporting",
        description=(
            "The Regional Lead's monthly report to the RVP and the VP of CCE: an "
            "executive summary with the region's figures for training programmes, "
            "CCE impact, curriculum development and programme initiatives."
        ),
        metrics=metrics,
        rows=rows,
        register_title="Reports",
        empty_title="No reports yet",
        empty_body=(
            "Start this month's report; the region's figures are added when you submit it."
            if is_lead
            else "Reports appear here when a Regional Lead in your region submits one."
        ),
        header_actions=[
            {"label": "Start a monthly report", "drawer": f"{REPORTS_URL}/new"}
        ]
        if is_lead
        else [],
        notice=notice,
    )


def _month_options(today: date) -> list[tuple[str, str]]:
    months = []
    cursor = services.month_start(today)
    for _ in range(6):
        months.append((cursor.isoformat()[:7], f"{cursor:%B %Y}"))
        cursor = services.month_start(cursor - timedelta(days=1))
    return months


@require_page_permission("cce_reports")
@require_http_methods(["GET"])
def report_new_drawer(request):
    if not _is_lead(request):
        return _drawer(
            request,
            title="Start a monthly report",
            subtitle="Collaboration and reporting",
            empty="Only the Regional Programme Lead writes the monthly CCE report.",
        )
    today = timezone.localdate()
    state = services.report_state(request.user, today=today)
    default = (
        state["previous_period"]
        if state["previous"] is None and state["previous_required"]
        else state["current_period"]
    )
    return _drawer(
        request,
        title="Start a monthly report",
        subtitle="To the RVP and the VP of CCE",
        action=f"{REPORTS_URL}/start",
        submit="Start report",
        fields=[
            _field(
                "period",
                "Month",
                type="select",
                required=True,
                value=default.isoformat()[:7],
                options=_month_options(today),
            )
        ],
        note="An existing report for the month opens again rather than starting a second one.",
    )


@require_page_permission("cce_reports")
@require_POST
def report_start(request):
    try:
        report = services.start_report(request.user, request.POST.get("period", ""))
        messages.success(request, f"{report.period:%B %Y} report ready to write.")
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, REPORTS_URL)
    return _back(request, REPORTS_URL)


def _metric_facts(metrics: dict) -> list[dict]:
    if not metrics:
        return []
    by_country = metrics.get("trainings_by_country") or {}
    rating = metrics.get("average_observation_rating")
    informed = metrics.get("ssa_informed_plans_pct")
    return [
        {
            "label": "Trainings delivered",
            "value": (
                f"{metrics.get('trainings_delivered', 0)} · "
                f"{metrics.get('teachers_trained', 0)} teachers, "
                f"{metrics.get('leaders_trained', 0)} leaders"
            ),
        },
        {
            "label": "Trainings by country",
            "value": " · ".join(f"{c} {n}" for c, n in by_country.items()) or "None",
        },
        {
            "label": "Coaching and follow-up visits",
            "value": str(metrics.get("coaching_follow_up_visits", 0)),
        },
        {
            "label": "SSA assessments confirmed",
            "value": str(metrics.get("ssa_confirmed", 0)),
        },
        {
            "label": "Plans informed by the SSA",
            "value": f"{informed}%" if informed is not None else "No plans judged",
        },
        {
            "label": "Coaching conversations",
            "value": str(metrics.get("coaching_conversations", 0)),
        },
        {
            "label": "Trainings observed",
            "value": f"{metrics.get('trainings_observed', 0)}"
            + (f" · average {rating} of 4" if rating else ""),
        },
        {
            "label": "Country Director reviews",
            "value": str(metrics.get("country_reviews", 0)),
        },
    ]


@require_page_permission("cce_reports")
@require_http_methods(["GET"])
def report_drawer(request, report_id):
    report = services.reports_visible_to(request.user).filter(id=report_id).first()
    if report is None:
        return _drawer(
            request,
            title="Monthly CCE report",
            subtitle="Collaboration and reporting",
            empty="This report is not in your reach.",
        )
    title = f"{report.period:%B %Y} CCE report"
    facts = [
        {"label": "Status", "value": report.get_status_display()},
        {"label": "Countries", "value": ", ".join(report.countries)},
        {"label": "Submitted", "value": _day(report.submitted_at)},
    ]
    if report.review_note:
        facts.append({"label": "RVP's note", "value": report.review_note})

    if _is_lead(request) and report.status in (
        ReportStatus.DRAFT,
        ReportStatus.RETURNED,
    ):
        preview = services.report_metrics(request.user, report.period)
        fields = [
            _field(
                name,
                label,
                type="textarea",
                rows=4 if name != "executive_summary" else 5,
                value=getattr(report, name),
                help=hint,
                required=name == "executive_summary",
            )
            for name, label, hint in REPORT_SECTIONS
        ]
        fields.append(
            _field(
                "submit",
                "Submit to the RVP and the VP of CCE now",
                type="checkbox",
                help="Leave unticked to keep it as a draft. The figures above are frozen when you submit.",
            )
        )
        return _drawer(
            request,
            title=title,
            subtitle="Figures as of today",
            facts=facts + _metric_facts(preview),
            action=f"{REPORTS_URL}/{report.id}/save",
            submit="Save report",
            fields=fields,
            note=(
                f"Returned by the RVP: {report.review_note}"
                if report.status == ReportStatus.RETURNED and report.review_note
                else ""
            ),
            note_tone="warning",
        )

    content = [
        {"label": label, "value": getattr(report, name)}
        for name, label, _hint in REPORT_SECTIONS
    ]
    if (
        request.user.active_role in (services.RVP, services.ADMIN)
        and report.status == ReportStatus.SUBMITTED
    ):
        return _drawer(
            request,
            title=title,
            subtitle=f"From {_author_names([report.author_id]).get(report.author_id, 'the Regional Lead')}",
            facts=facts + content + _metric_facts(report.metrics),
            action=f"{REPORTS_URL}/{report.id}/review",
            submit="Record review",
            fields=[
                _field(
                    "decision",
                    "Decision",
                    type="select",
                    required=True,
                    options=[
                        ("acknowledge", "Acknowledge the report"),
                        ("return", "Return it for revision"),
                    ],
                    blank="Choose a decision",
                ),
                _field(
                    "note",
                    "Note to the Regional Lead",
                    type="textarea",
                    rows=4,
                    help="Required when returning: say what the report needs.",
                ),
            ],
        )
    return _drawer(
        request,
        title=title,
        subtitle="Collaboration and reporting",
        facts=facts + content + _metric_facts(report.metrics),
        empty="Read only.",
    )


@require_page_permission("cce_reports")
@require_POST
def report_save(request, report_id):
    data = {name: request.POST.get(name, "") for name, _label, _hint in REPORT_SECTIONS}
    submit = bool(request.POST.get("submit"))
    try:
        report = services.update_report(request.user, report_id, data, submit=submit)
        messages.success(
            request,
            f"{report.period:%B %Y} report submitted to the RVP."
            if submit
            else f"{report.period:%B %Y} report saved as a draft.",
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, REPORTS_URL)
    return _back(request, REPORTS_URL)


@require_page_permission("cce_reports")
@require_POST
def report_review(request, report_id):
    try:
        report = services.review_report(
            request.user,
            report_id,
            request.POST.get("decision", ""),
            request.POST.get("note", ""),
        )
        messages.success(
            request,
            f"{report.period:%B %Y} report {report.get_status_display().lower()}.",
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, REPORTS_URL)
    return _back(request, REPORTS_URL)
