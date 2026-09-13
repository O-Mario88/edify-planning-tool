"""Screens for the guidance a Programme Lead issues to their officers (owner, 2026-09-13).

/priorities/guidance is the Team Guidance tab of the Priorities page: the
lead's register of the guidance they drafted and issued on the country
priorities, each officer's acknowledgement, and the reviews due. Admin reads it
with no write controls. The officer's side is a panel on their own Priorities
page (/priorities): the guidance issued to them, acknowledged with a response.
That page's view belongs to the performance agreement, so the panel loads
itself from `guidance_inbox_panel` once the page is on screen.

Rules, permissions and audit rows live in apps.cce_leadership.guidance; these
views render and route, so a refusal the service raises is the message the
reader sees. Drawers are the one-column form drawer
(partials/hr/form_drawer.html).

A To-Do or a notification links the register with ?open=<guidance id> (and
&step=edit|issue|review|withdraw) or ?open=new, and the officer's page with
?guidance=<guidance id>; the page builds the drawer URL itself from those
whitelisted values and opens it on load.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from apps.cce_leadership import guidance as service
from apps.cce_leadership.services import PROGRAM_LEAD
from apps.core.metrics import render_precomputed_metric_for_source
from apps.core.permissions import require_page_permission
from apps.frontend.views.hr_programme_views import SERVICE_ERRORS, _drawer, _field
from apps.frontend.views.priority_workspace import (
    priority_workspace_tabs,
    wants_panel_only,
)

LEAD_URL = service.LEAD_URL
OFFICER_URL = service.OFFICER_URL
PAGE_TEMPLATE = "pages/priorities/guidance.html"
VIEW_TEMPLATE = "partials/priorities/guidance_view.html"
INBOX_TEMPLATE = "partials/priorities/guidance_inbox.html"

# The steps a ?open= link may ask the register to open, and the parameters
# that only open a drawer (a form posted from it returns without them).
STEPS = ("edit", "issue", "review", "withdraw")
AUTOLOAD_PARAMS = ("open", "step", "guidance")
# How many receipts the officer's panel lists: every one still waiting, then
# the most recent acknowledged.
INBOX_LIMIT = 25


def _metric(label: str, value, helper: str, tone="info") -> dict:
    return render_precomputed_metric_for_source(
        "apps.frontend.views.team_guidance_views:_metric",
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
    if not value:
        return ""
    if hasattr(value, "tzinfo") and getattr(value, "hour", None) is not None:
        value = timezone.localtime(value).date()
    return f"{value:%-d %b %Y}"


def _is_lead(request) -> bool:
    return request.user.active_role == PROGRAM_LEAD


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def safe_return_url(request, fallback: str) -> str:
    """The page a drawer's form returns to: the posted `next` when it is on
    this site, without the parameters that opened the drawer, else `fallback`.
    The rebuilt path is checked again with Django's own host check, so a path
    a browser reads as another host ("/\\evil.example") is refused too."""
    target = (request.POST.get("next") or "").strip()
    parsed = urlparse(target) if target else None
    if parsed and parsed.path.startswith("/"):
        same_site = not parsed.netloc.strip() or parsed.netloc == request.get_host()
        if same_site:
            query = urlencode(
                [
                    (key, value)
                    for key, value in parse_qsl(parsed.query)
                    if key not in AUTOLOAD_PARAMS
                ]
            )
            url = parsed.path + (f"?{query}" if query else "")
            if url_has_allowed_host_and_scheme(
                url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ) and not url.startswith(("//", "/\\")):
                return url
    return fallback


def _return(request, fallback: str):
    return redirect(safe_return_url(request, fallback))


def _refused(request, exc, fallback):
    messages.error(request, str(getattr(exc, "detail", exc)))
    return _return(request, fallback)


def _page_fy(request) -> str:
    """The year the register reads, the way every Priorities tab reads it:
    the requested year when it is a valid one, else the newest governed
    cycle, else the operational year."""
    from apps.frontend.views.hr_views import _requested_fy
    from apps.hr.models import StrategicPriorityCycle

    if (request.GET.get("fy") or "").strip():
        return _requested_fy(request)
    return StrategicPriorityCycle.objects.exclude(status="archived").order_by(
        "-financial_year"
    ).values_list("financial_year", flat=True).first() or _requested_fy(request)


def _names_by_user(user_ids) -> dict[str, str]:
    from apps.accounts.models import User

    ids = {i for i in user_ids if i}
    if not ids:
        return {}
    return dict(User.objects.filter(id__in=ids).values_list("id", "name"))


def _serves(guidance) -> str:
    """The priority and milestone a piece of guidance serves, as one line."""
    parts = []
    if guidance.priority_id:
        parts.append(guidance.priority.title)
    if guidance.milestone_id:
        parts.append(guidance.milestone.title)
    return " · ".join(parts)


def _guidance_facts(guidance, *, author="", receipts=None) -> list[dict]:
    """What a piece of guidance says, in reading order, then where each
    officer stands with it."""
    facts = [{"label": "Title", "value": guidance.title}]
    if author:
        facts.append({"label": "Programme Lead", "value": author})
    facts += [
        {"label": "Financial year", "value": f"FY{guidance.fy}"},
        {
            "label": "Priority",
            "value": guidance.priority.title if guidance.priority_id else "",
        },
        {
            "label": "Milestone",
            "value": guidance.milestone.title if guidance.milestone_id else "",
        },
        {"label": "Instruction", "value": guidance.instruction},
        {"label": "Change expected", "value": guidance.expected_change},
        {"label": "Review on", "value": _day(guidance.review_on)},
        {
            "label": "Issued",
            "value": _day(guidance.issued_at) or "Not issued yet (draft)",
        },
    ]
    if guidance.withdrawn_at:
        facts.append({"label": "Withdrawn", "value": _day(guidance.withdrawn_at)})
    for receipt in receipts or []:
        if receipt.acknowledged_at:
            value = f"Acknowledged {_day(receipt.acknowledged_at)}\n{receipt.response}"
        elif guidance.issued_at and not guidance.withdrawn_at:
            value = "Awaiting acknowledgement"
        else:
            value = "Not acknowledged"
        facts.append({"label": receipt.recipient_name, "value": value})
    return facts


# ── The lead's register ──────────────────────────────────────────────────────
def _autoload(request, visible) -> str:
    """The drawer a ?open= link asks for, built from whitelisted values."""
    target = (request.GET.get("open") or "").strip()
    if not target:
        return ""
    lead = _is_lead(request)
    if target == "new":
        return f"{LEAD_URL}/new" if lead else ""
    if not visible.filter(id=target).exists():
        return ""
    step = request.GET.get("step") or ""
    if lead and step in STEPS:
        return f"{LEAD_URL}/{target}/{step}"
    return f"{LEAD_URL}/{target}"


def _row_actions(guidance, *, lead: bool, today) -> list[dict]:
    base = f"{LEAD_URL}/{guidance.id}"
    if not lead or guidance.withdrawn_at:
        return [{"label": "Open", "drawer": base}]
    if not guidance.issued_at:
        return [
            {"label": "Edit", "drawer": f"{base}/edit"},
            {"label": "Issue", "drawer": f"{base}/issue"},
            {"label": "Withdraw", "drawer": f"{base}/withdraw"},
        ]
    actions = [{"label": "Open", "drawer": base}]
    if guidance.review_on and guidance.review_on <= today:
        actions.append({"label": "Review", "drawer": f"{base}/review"})
    actions.append({"label": "Withdraw", "drawer": f"{base}/withdraw"})
    return actions


@require_page_permission("team_guidance")
@require_http_methods(["GET"])
def team_guidance_view(request):
    """The Team Guidance tab: a Programme Lead's guidance to their officers,
    read-only for Admin."""
    today = timezone.localdate()
    lead = _is_lead(request)
    fy = _page_fy(request)
    visible = service.guidance_visible_to(request.user)

    state = request.GET.get("state") or ""
    records = service.with_receipt_counts(visible.filter(fy=fy)).select_related(
        "priority", "milestone"
    )
    if state in dict(service.STATE_CHOICES):
        records = service.with_state(records, state, today=today)
    else:
        state = ""
    records = list(records.order_by("-created_at")[:500])
    authors = {} if lead else _names_by_user(r.author_id for r in records)

    rows = []
    for record in records:
        label, tone = service.state_of(record, today=today)
        cells = [_cell("Guidance", record.title, primary=True)]
        if not lead:
            cells.append(_cell("Programme Lead", authors.get(record.author_id, "")))
        cells += [
            _cell("Priority served", _serves(record)),
            _cell("Issued", _day(record.issued_at)),
            _cell(
                "Acknowledged",
                f"{record.acknowledged_count} of {record.recipient_count}",
                tone="warning"
                if record.issued_at
                and not record.withdrawn_at
                and record.acknowledged_count < record.recipient_count
                else "",
            ),
            _cell("Review on", _day(record.review_on)),
            _cell("State", label, tone=tone),
        ]
        rows.append(
            {
                "cells": cells,
                "actions": _row_actions(record, lead=lead, today=today),
            }
        )

    counts = service.guidance_counts(visible.filter(fy=fy), today=today)
    metrics = [
        _metric(
            "Team Guidance Issued",
            counts["issued"],
            f"issued to officers for FY{fy}, not withdrawn",
        ),
        _metric(
            "Guidance Awaiting Officer Acknowledgement",
            counts["awaiting"],
            f"{counts['acknowledged']} acknowledged so far",
            "warning" if counts["awaiting"] else "info",
        ),
        _metric(
            "Guidance Reviews Due",
            counts["reviews_due"],
            "review date reached; read the responses",
            "danger" if counts["reviews_due"] else "info",
        ),
        _metric(
            "Guidance Drafts Not Issued",
            counts["drafts"],
            "drafts only you can read" if lead else "drafts stay with the lead",
            "warning" if lead and counts["drafts"] else "info",
        ),
    ]

    from apps.hr.models import StrategicPriorityCycle

    fy_choices = set(
        StrategicPriorityCycle.objects.values_list("financial_year", flat=True)
    )
    fy_choices.update(visible.order_by().values_list("fy", flat=True).distinct())
    fy_choices.add(fy)

    members = service._team(request.user) if lead else []
    notice = None
    if not lead:
        notice = {
            "tone": "info",
            "text": (
                "Read only. Each Programme Lead writes and issues their own "
                "guidance; you read what they wrote and where each officer stands."
            ),
        }
    elif not members:
        notice = {
            "tone": "info",
            "text": (
                "No officers are assigned to you yet. Guidance opens for the "
                "officers HR records you as the supervisor of."
            ),
        }

    context = {
        "fy": fy,
        "guidance_title": "Team Guidance",
        "guidance_eyebrow": "Strategic direction · Communication",
        "guidance_description": (
            "Tell your officers what to do about the country priorities this term "
            "and the change you expect in schools. Each officer acknowledges the "
            "guidance with what they will do; review the responses on the date you set."
            if lead
            else "Guidance Programme Leads issued to their officers on the country "
            "priorities, and each officer's acknowledgement."
        ),
        "guidance_metrics": metrics,
        "guidance_rows": rows,
        "guidance_has_row_actions": any(row["actions"] for row in rows),
        "guidance_header_actions": [
            {"label": "New guidance", "drawer": f"{LEAD_URL}/new?fy={fy}"}
        ]
        if lead and members
        else [],
        "guidance_notice": notice,
        "guidance_filters": [
            {
                "name": "fy",
                "label": "Financial year",
                "value": fy,
                "blank": "",
                "options": [(y, f"FY{y}") for y in sorted(fy_choices, reverse=True)],
            },
            {
                "name": "state",
                "label": "State",
                "value": state,
                "blank": "Every state",
                "options": list(service.STATE_CHOICES),
            },
        ],
        "guidance_empty_title": "No guidance for this year yet"
        if lead
        else "No guidance in this year",
        "guidance_empty_body": (
            "Issue guidance on a priority to every officer or to the ones it "
            "concerns; it stays a draft until you issue it."
            if lead
            else "Guidance appears here once a Programme Lead writes it."
        ),
        "autoload_drawer": _autoload(request, visible),
    }
    context["dashboard_tabs"] = priority_workspace_tabs(
        request, active="guidance", view_template=VIEW_TEMPLATE
    )
    if context["dashboard_tabs"] and wants_panel_only(request):
        return render(
            request,
            "partials/dashboards/_view_tabs.html",
            {**context, "dashboard_tabs_inner": True},
        )
    return render(request, PAGE_TEMPLATE, context)


# ── The lead's drawers ───────────────────────────────────────────────────────
def _guidance_fields(request, *, fy: str, record=None, receipts=None) -> list[dict]:
    """The one-column form for a piece of guidance."""
    members = service._team(request.user)
    priorities, milestones = service.priority_choices(request.user, fy)
    chosen = {r.recipient_staff_id for r in receipts or []}
    every_officer = record is None or (
        bool(members) and {str(m.id) for m in members} <= chosen
    )
    return [
        _field("fy", "Financial year", type="hidden", value=fy),
        _field(
            "title",
            "Title",
            required=True,
            value=record.title if record else "",
            maxlength=service.TITLE_MAX,
            placeholder="For example: Prioritise SSA collection in client schools",
        ),
        _field(
            "instruction",
            "What the officers should do",
            type="textarea",
            required=True,
            value=record.instruction if record else "",
            rows=5,
        ),
        _field(
            "expected_change",
            "Change expected in schools",
            type="textarea",
            value=record.expected_change if record else "",
            rows=3,
            help="Optional: what should be different in the schools when this works.",
        ),
        _field(
            "priority_id",
            "Country priority it serves",
            type="select",
            value=record.priority_id if record else "",
            options=[(p.id, p.title) for p in priorities],
            blank="No specific priority",
        ),
        _field(
            "milestone_id",
            "Milestone it serves",
            type="select",
            value=record.milestone_id if record else "",
            options=[(m.id, f"{m.priority.title} · {m.title}") for m in milestones],
            blank="No specific milestone",
            help="Optional. A milestone sets its priority for you.",
        ),
        _field(
            "review_on",
            "Review the responses on",
            type="date",
            value=record.review_on.isoformat() if record and record.review_on else "",
            help="Optional: the day you will read how the officers responded.",
        ),
        _field(
            "all_officers",
            "Every officer on my team",
            type="checkbox",
            value=every_officer,
            help="Untick to choose the officers below.",
        ),
        _field(
            "recipients",
            "Officers",
            type="multiselect",
            value=sorted(chosen),
            options=[(str(m.id), getattr(m.user, "name", "")) for m in members],
            rows=min(max(len(members), 3), 8),
            help="Used when the guidance is not for every officer.",
        ),
        _field(
            "issue",
            "Issue to the officers now",
            type="checkbox",
            value=False,
            help="Leave unticked to keep a draft only you can read.",
        ),
    ]


def _data(request) -> dict:
    data = {key: request.POST.get(key) for key in request.POST}
    data["recipients"] = request.POST.getlist("recipients")
    return data


@require_page_permission("team_guidance")
@require_http_methods(["GET"])
def guidance_new_drawer(request):
    if not _is_htmx(request):
        return redirect(f"{LEAD_URL}?open=new")
    title = "New guidance"
    subtitle = "Guidance on the priorities for the officers on your team"
    if not _is_lead(request):
        return _drawer(
            request,
            title=title,
            subtitle=subtitle,
            empty="Only a Programme Lead issues guidance to their officers.",
        )
    if not service._team(request.user):
        return _drawer(
            request,
            title=title,
            subtitle=subtitle,
            empty="No officers are assigned to you yet.",
        )
    return _drawer(
        request,
        title=title,
        subtitle=subtitle,
        action=f"{LEAD_URL}/record",
        submit="Save guidance",
        fields=_guidance_fields(request, fy=_page_fy(request)),
        note=(
            "Each officer it is issued to is notified and asked to acknowledge it "
            "with what they will do."
        ),
    )


@require_page_permission("team_guidance")
@require_POST
def guidance_record(request):
    data = _data(request)
    try:
        guidance = service.draft_guidance(request.user, data)
        if guidance.issued_at:
            messages.success(
                request,
                "Guidance issued. Each officer has been asked to acknowledge it.",
            )
        else:
            messages.success(
                request, "Guidance saved as a draft. Issue it when it is ready."
            )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, LEAD_URL)
    return _return(request, f"{LEAD_URL}?fy={guidance.fy}")


def _visible_guidance(request, guidance_id):
    return (
        service.guidance_visible_to(request.user)
        .select_related("priority", "milestone")
        .filter(id=guidance_id)
        .first()
    )


def _missing(request, title="Guidance"):
    return _drawer(
        request,
        title=title,
        subtitle="Team Guidance",
        empty="This guidance is not in your reach.",
    )


def _facts_for(request, record) -> list[dict]:
    receipts = service.receipts_by_guidance([record.id]).get(record.id, [])
    author = (
        ""
        if _is_lead(request)
        else _names_by_user([record.author_id]).get(record.author_id, "")
    )
    return _guidance_facts(record, author=author, receipts=receipts)


@require_page_permission("team_guidance")
@require_http_methods(["GET"])
def guidance_drawer(request, guidance_id):
    record = _visible_guidance(request, guidance_id)
    if record is None:
        return _missing(request)
    return _drawer(
        request,
        title=record.title,
        subtitle=_serves(record) or "Team Guidance",
        facts=_facts_for(request, record),
    )


@require_page_permission("team_guidance")
@require_http_methods(["GET"])
def guidance_edit_drawer(request, guidance_id):
    record = _visible_guidance(request, guidance_id)
    if record is None or not _is_lead(request):
        return _missing(request, "Edit guidance")
    if record.issued_at or record.withdrawn_at:
        return _drawer(
            request,
            title="Edit guidance",
            subtitle=record.title,
            facts=_facts_for(request, record),
            empty=(
                "This guidance has reached the officers, so it can no longer be "
                "changed. Withdraw it and issue new guidance instead."
                if record.issued_at
                else "This guidance was withdrawn."
            ),
        )
    receipts = service.receipts_by_guidance([record.id]).get(record.id, [])
    return _drawer(
        request,
        title="Edit guidance",
        subtitle=record.title,
        action=f"{LEAD_URL}/{record.id}/update",
        submit="Save guidance",
        fields=_guidance_fields(
            request, fy=record.fy, record=record, receipts=receipts
        ),
    )


@require_page_permission("team_guidance")
@require_POST
def guidance_update(request, guidance_id):
    data = _data(request)
    try:
        guidance = service.update_guidance(request.user, guidance_id, data)
        messages.success(
            request,
            "Guidance issued. Each officer has been asked to acknowledge it."
            if guidance.issued_at
            else "Draft saved.",
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, LEAD_URL)
    return _return(request, LEAD_URL)


def _step_drawer(
    request, guidance_id, *, title, allowed, action, submit, note, fields=()
):
    record = _visible_guidance(request, guidance_id)
    if record is None or not _is_lead(request):
        return _missing(request, title)
    refusal = allowed(record)
    facts = _facts_for(request, record)
    if refusal:
        return _drawer(
            request, title=title, subtitle=record.title, facts=facts, empty=refusal
        )
    return _drawer(
        request,
        title=title,
        subtitle=record.title,
        facts=facts,
        action=f"{LEAD_URL}/{record.id}/{action}",
        submit=submit,
        note=note,
        note_tone="warning" if action.startswith("withdraw") else "info",
        fields=fields,
    )


@require_page_permission("team_guidance")
@require_http_methods(["GET"])
def guidance_issue_drawer(request, guidance_id):
    def allowed(record):
        if record.withdrawn_at:
            return "This guidance was withdrawn."
        if record.issued_at:
            return "This guidance was already issued."
        return ""

    return _step_drawer(
        request,
        guidance_id,
        title="Issue guidance",
        allowed=allowed,
        action="issue/save",
        submit="Issue guidance",
        note=(
            "Each officer below is notified and asked to acknowledge it. Issued "
            "guidance can no longer be edited, only withdrawn."
        ),
    )


@require_page_permission("team_guidance")
@require_POST
def guidance_issue(request, guidance_id):
    try:
        service.issue_guidance(request.user, guidance_id)
        messages.success(
            request, "Guidance issued. Each officer has been asked to acknowledge it."
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, LEAD_URL)
    return _return(request, LEAD_URL)


@require_page_permission("team_guidance")
@require_http_methods(["GET"])
def guidance_review_drawer(request, guidance_id):
    today = timezone.localdate()

    def allowed(record):
        if record.withdrawn_at or not record.issued_at:
            return "Only issued guidance that still stands is reviewed."
        if not record.review_on or record.review_on > today:
            return "This guidance is not due for review yet."
        return ""

    return _step_drawer(
        request,
        guidance_id,
        title="Review guidance responses",
        allowed=allowed,
        action="review/save",
        submit="Record review",
        note=(
            "Read each officer's response below. Set the next review date, or leave "
            "it empty when no further review is planned."
        ),
        fields=[
            _field(
                "next_review",
                "Next review on",
                type="date",
                help="Optional. Leave empty to close the review.",
            )
        ],
    )


@require_page_permission("team_guidance")
@require_POST
def guidance_review(request, guidance_id):
    try:
        guidance = service.review_guidance(
            request.user, guidance_id, request.POST.get("next_review")
        )
        messages.success(
            request,
            f"Review recorded. Next review on {guidance.review_on:%-d %B %Y}."
            if guidance.review_on
            else "Review recorded. No further review is planned.",
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, LEAD_URL)
    return _return(request, LEAD_URL)


@require_page_permission("team_guidance")
@require_http_methods(["GET"])
def guidance_withdraw_drawer(request, guidance_id):
    def allowed(record):
        return "This guidance was already withdrawn." if record.withdrawn_at else ""

    return _step_drawer(
        request,
        guidance_id,
        title="Withdraw guidance",
        allowed=allowed,
        action="withdraw/save",
        submit="Withdraw guidance",
        note=(
            "Withdrawn guidance leaves every officer's Priorities page and To-Do "
            "queue. The record and the responses stay in your register."
        ),
    )


@require_page_permission("team_guidance")
@require_POST
def guidance_withdraw(request, guidance_id):
    try:
        service.withdraw_guidance(request.user, guidance_id)
        messages.success(request, "Guidance withdrawn.")
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, LEAD_URL)
    return _return(request, LEAD_URL)


# ── The officer's side, on their Priorities page ─────────────────────────────
@require_page_permission("priorities_master")
@require_http_methods(["GET"])
def guidance_inbox_panel(request):
    """The officer's guidance panel. Anyone but an officer gets nothing: the
    placeholder on the Priorities page is replaced by an empty fragment."""
    if request.user.active_role != service.CCEO:
        return HttpResponse("")
    today = timezone.localdate()
    receipts = list(
        service.receipts_for_officer(request.user)
        .select_related("guidance__priority", "guidance__milestone")
        .order_by("-guidance__issued_at")[:200]
    )
    waiting = [r for r in receipts if not r.acknowledged_at]
    done = [r for r in receipts if r.acknowledged_at]
    shown = (waiting + done)[: max(INBOX_LIMIT, len(waiting))]
    authors = _names_by_user(r.guidance.author_id for r in shown)
    rows = []
    for receipt in shown:
        guidance = receipt.guidance
        if receipt.acknowledged_at:
            state, tone = f"Acknowledged {_day(receipt.acknowledged_at)}", "success"
        elif guidance.review_on and guidance.review_on <= today:
            state, tone = "Awaiting your acknowledgement", "danger"
        else:
            state, tone = "Awaiting your acknowledgement", "warning"
        rows.append(
            {
                "cells": [
                    _cell("Guidance", guidance.title, primary=True),
                    _cell(
                        "From",
                        authors.get(guidance.author_id) or "Your Programme Lead",
                    ),
                    _cell("Priority served", _serves(guidance)),
                    _cell("Issued", _day(guidance.issued_at)),
                    _cell("Review on", _day(guidance.review_on)),
                    _cell("State", state, tone=tone),
                ],
                "actions": [
                    {
                        "label": "Open" if receipt.acknowledged_at else "Acknowledge",
                        "drawer": f"{LEAD_URL}/{guidance.id}/acknowledge",
                    }
                ],
            }
        )
    target = (request.GET.get("open") or "").strip()
    autoload = (
        f"{LEAD_URL}/{target}/acknowledge"
        if target and any(r.guidance_id == target for r in receipts)
        else ""
    )
    return render(
        request,
        INBOX_TEMPLATE,
        {
            "inbox_rows": rows,
            "inbox_waiting": len(waiting),
            "inbox_total": len(receipts),
            "inbox_hidden": len(receipts) - len(shown),
            "autoload_drawer": autoload,
        },
    )


@require_page_permission("priorities_master")
@require_http_methods(["GET"])
def guidance_acknowledge_drawer(request, guidance_id):
    title = "Guidance from your Programme Lead"
    receipt = (
        service.receipts_for_officer(request.user)
        .select_related("guidance__priority", "guidance__milestone")
        .filter(guidance_id=guidance_id)
        .first()
    )
    if receipt is None:
        return _drawer(
            request,
            title=title,
            subtitle="Priorities",
            empty="This guidance is not addressed to you, or it was withdrawn.",
        )
    guidance = receipt.guidance
    author = _names_by_user([guidance.author_id]).get(guidance.author_id, "")
    facts = _guidance_facts(guidance, author=author)
    if receipt.acknowledged_at:
        facts += [
            {"label": "You acknowledged", "value": _day(receipt.acknowledged_at)},
            {"label": "Your response", "value": receipt.response},
        ]
        return _drawer(request, title=guidance.title, subtitle=title, facts=facts)
    return _drawer(
        request,
        title=guidance.title,
        subtitle=title,
        facts=facts,
        action=f"{LEAD_URL}/{guidance.id}/acknowledge/save",
        submit="Acknowledge",
        note="Your Programme Lead reads your response.",
        fields=[
            _field(
                "response",
                "What you will do",
                type="textarea",
                required=True,
                rows=4,
                placeholder="The change you will make, and in which schools",
            )
        ],
    )


@require_page_permission("priorities_master")
@require_POST
def guidance_acknowledge(request, guidance_id):
    try:
        service.acknowledge_guidance(
            request.user, guidance_id, request.POST.get("response", "")
        )
        messages.success(
            request, "Guidance acknowledged. Your Programme Lead has been told."
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, OFFICER_URL)
    return _return(request, OFFICER_URL)
