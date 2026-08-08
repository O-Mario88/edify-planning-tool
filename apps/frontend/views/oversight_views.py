"""Planning oversight pages — the PL's team lens and the CD's country lens.

Both are read surfaces over `apps.planning.oversight_service`. Neither creates
planning records, and neither exposes a mutation control for work it does not
own: a Program Lead supervises a CCEO's activity but never edits it, and a
Country Director reviews the country plan but never schedules routine field
work. The only write either page offers is a corrective action, and that goes
through the canonical TeamAction workflow rather than touching the activity.
"""

from __future__ import annotations

from django.shortcuts import render
from django.utils.html import escape
from django.views.decorators.http import require_POST

from apps.core.fy import fy_options, get_operational_fy
from apps.core.metrics import DataState, MetricValue, render_kpi_item
from apps.core.permissions import (
    require_any_page_permission,
    require_export_permission,
    require_page_permission,
)
from apps.clusters.oversight_service import grouped_clusters
from apps.planning import oversight_actions
from apps.planning import oversight_service as oversight
from apps.planning.action_service import ActionError


# Where a no-JavaScript send returns to when the Referer cannot be trusted.
# Each page falls back to itself: bouncing a Country Director to the Program
# Lead's page would be a scope change dressed up as a redirect.
TEAM_OVERSIGHT_PATH = "/team-planning-oversight/"
COUNTRY_OVERSIGHT_PATH = "/country-planning-oversight/"
PARTNER_OVERSIGHT_PATH = "/partner-oversight/"


def may_delegate(user, *, country: bool) -> bool:
    """Whether this person may send a corrective action from these pages.

    Delegation follows the reporting line: a Programme Lead asks their CCEOs,
    a Country Director asks their Programme Leads. Reading the page is a
    different thing from being able to hand somebody work off it.

    Impact Assessment and the Accountant sit at the *end* of the chain, not
    above it: IA verifies completed work and the Accountant confirms it and
    releases payment or chases the accountability. Neither supervises anybody,
    so neither hands work out. The RVP reads the country picture.

    This became load-bearing when Cluster Oversight was added as a section
    here and those three were given the pages to reach it.
    `send_risk_to_owner` constrains delegation with `within_staff_ids`, and the
    view passes `scope.supervised_ids or None` — where None means *no
    constraint*. Roles that supervise nobody would therefore have been able to
    delegate to anyone, which is a wider authority than the page was widened
    for. `ACTIVITY_ASSIGN` cannot express this: the Country Director does not
    hold it and must still be able to send.
    """
    from apps.core.rbac import EdifyRole

    role = getattr(user, "active_role", "") or ""
    allowed = (
        {EdifyRole.COUNTRY_DIRECTOR.value}
        if country
        else {EdifyRole.COUNTRY_PROGRAM_LEAD.value}
    )
    return role in allowed | {EdifyRole.ADMIN.value}


def _kpi_items(summary, *, country: bool) -> list[dict]:
    """The headline tiles, built through the metric registry.

    Every one is a field of the fold in `summarize()`, so a tile cannot show a
    number the table disagrees with — there is no second calculation for it to
    come from. Going through `render_kpi_item` adds the other half: the label,
    the definition, the period and the formatting come from one registry entry
    rather than from whichever view happened to draw the tile, so the team page
    and the country page cannot drift into naming the same thing differently.

    Execution progress carries its denominator because it is a share: a plan
    entirely in the future has nothing due, which is NOT 0% delivered, and
    MetricValue is where that distinction is made rather than in the template.
    """
    return [
        render_kpi_item(
            "oversight_country_activities_planned"
            if country
            else "oversight_team_activities_planned",
            MetricValue.measured(summary["total_planned"]),
            helper=(
                f"{summary['staff_scheduled']} staff · "
                f"{summary['partner_scheduled']} partner"
            ),
            icon="calendar",
        ),
        render_kpi_item(
            "oversight_partner_awaiting_schedule",
            MetricValue.measured(summary["partner_awaiting_schedule"]),
            helper="No cost until the partner schedules",
            tone="warning" if summary["partner_awaiting_schedule"] else "neutral",
            icon="handshake",
        ),
        render_kpi_item(
            "oversight_country_activities_at_risk"
            if country
            else "oversight_team_work_needing_attention",
            MetricValue.measured(summary["at_risk"]),
            helper=f"{summary['cost_missing']} scheduled without a cost",
            tone="danger" if summary["at_risk"] else "neutral",
            icon="warning",
        ),
        render_kpi_item(
            "oversight_country_planned_budget"
            if country
            else "oversight_team_planned_budget",
            MetricValue.measured(summary["planned_budget"]),
            helper=f"From {summary['scheduled_total']} scheduled",
            icon="currency",
        ),
        render_kpi_item(
            "oversight_execution_progress",
            (
                MetricValue.ratio(
                    summary["completed"],
                    summary["due_count"],
                )
                if summary["due_count"]
                else MetricValue.absent(
                    DataState.NOT_YET_MEASURABLE, note="Nothing due yet"
                )
            ),
            helper=(
                f"{summary['completed']} of {summary['due_count']} due"
                if summary["due_count"]
                else "Nothing due yet"
            ),
            icon="chart",
        ),
        # The tail of the chain, which the strip previously stopped short of.
        # A plan can be fully delivered and still be earning no credit and
        # paying nobody, and a supervisor who cannot see that has no way to
        # know the work is stuck somewhere they do not control.
        render_kpi_item(
            "oversight_awaiting_verification",
            MetricValue.measured(summary["awaiting_verification"]),
            helper=f"{summary['awaiting_payment']} verified and unpaid",
            tone="warning" if summary["awaiting_verification"] else "neutral",
            icon="clipboard",
        ),
    ]


def _period_filters(request) -> dict:
    """Financial year, month and quarter, read the same way on both pages."""
    fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
    raw_month = (request.GET.get("month") or "").strip()
    month = (
        int(raw_month) if raw_month.isdigit() and 1 <= int(raw_month) <= 12 else None
    )
    quarter = (request.GET.get("quarter") or "").strip() or None
    return {"fy": fy, "month": month, "quarter": quarter}


# ── Program Lead ─────────────────────────────────────────────────────────────
# The tabs are backend-filtered datasets, not decoration: each one is a real
# subset of the same item list, so a count on a tab and the rows behind it
# cannot disagree.
PL_TABS = (
    ("all", "All Planned Work"),
    ("mine", "My Work"),
    ("cceo", "CCEO Work"),
    ("partner", "Partner Work"),
    ("attention", "Needs Attention"),
    ("completed", "Completed"),
)


def _apply_pl_tab(split, items, tab):
    if tab == "mine":
        return split["own"]
    if tab == "cceo":
        return split["cceo"]
    if tab == "partner":
        return split["partner"]
    if tab == "attention":
        return [i for i in items if i.at_risk or i.cost_missing]
    if tab == "completed":
        return [i for i in items if i.is_completed]
    return items


@require_page_permission("team_planning_oversight")
def team_planning_oversight_view(request):
    """What my team has planned, who executes it, and where I must intervene."""
    period = _period_filters(request)
    staff_id = (request.GET.get("team_member") or "").strip() or None
    tab = (request.GET.get("tab") or "all").strip()
    if tab not in dict(PL_TABS):
        tab = "all"

    advanced = oversight.read_filters(request)
    scope = oversight.resolve_oversight_scope(request.user)
    items = oversight.build_items(
        request.user, staff_id=staff_id, filters=advanced, **period
    )
    split = oversight.split_own_and_team(items, scope)
    visible = _apply_pl_tab(split, items, tab)

    # Each tab carries its own count, built from the same fold that produces
    # the rows behind it — so a tab badge and its table are one number.
    tabs = [
        {
            "key": key,
            "label": label,
            "count": len(_apply_pl_tab(split, items, key)),
            "is_active": key == tab,
        }
        for key, label in PL_TABS
    ]

    summary = oversight.summarize(items)
    context = {
        **period,
        "tab": tab,
        "tabs": tabs,
        "team_member": staff_id,
        "summary": summary,
        "kpis": _kpi_items(summary, country=False),
        "visible_summary": oversight.summarize(visible),
        "groups": oversight.group_by_owner(visible),
        "split": split,
        "team_members": _team_members(scope),
        "advanced": advanced,
        "filter_options": _filter_options(items),
        "fy_options": fy_options(),
        # IA and the Accountant read this page for Cluster Oversight below.
        # The send controls are theirs to see refused, so they are not drawn:
        # a control that answers "not you" is worse than no control.
        "may_delegate": may_delegate(request.user, country=False),
        "cluster_oversight": grouped_clusters(request.user),
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/oversight/pl_workspace.html", context)
    return render(request, "pages/oversight/team_planning.html", context)


def _team_members(scope) -> list[dict]:
    """The supervised staff, for the team-member filter."""
    if scope.is_country or not scope.supervised_ids:
        return []
    from apps.accounts.models import StaffProfile

    rows = (
        StaffProfile.objects.filter(id__in=scope.supervised_ids)
        .select_related("user")
        .order_by("user__name")
    )
    return [
        {
            "id": p.id,
            "name": getattr(p.user, "name", "") or getattr(p.user, "email", ""),
        }
        for p in rows
    ]


# ── Country Director ─────────────────────────────────────────────────────────
@require_page_permission("country_planning_oversight")
def country_planning_oversight_view(request):
    """What the country has planned, how it is distributed, and who must act.

    The initial response carries the per-Program-Lead summary only. Expanding a
    team fetches its rows separately, because rendering every activity in the
    country up front is the difference between a page that opens and one that
    times out.
    """
    period = _period_filters(request)
    program_lead_id = (request.GET.get("program_lead") or "").strip() or None

    advanced = oversight.read_filters(request)
    items = oversight.build_items(
        request.user, program_lead_id=program_lead_id, filters=advanced, **period
    )

    summary = oversight.summarize(items)
    context = {
        **period,
        "program_lead": program_lead_id,
        "summary": summary,
        "kpis": _kpi_items(summary, country=True),
        "groups": oversight.group_by_program_lead(items),
        "program_leads": _program_leads(items),
        "advanced": advanced,
        "filter_options": _filter_options(items),
        "fy_options": fy_options(),
        # The RVP reads this page for Cluster Oversight below and does not
        # delegate from it.
        "may_delegate": may_delegate(request.user, country=True),
        "cluster_oversight": grouped_clusters(request.user),
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/oversight/cd_workspace.html", context)
    return render(request, "pages/oversight/country_planning.html", context)


@require_page_permission("country_planning_oversight")
@require_POST
def country_planning_send_action_view(request):
    """ "Send to <PL>" — a team-level ask, delegated to the Program Lead.

    The condition is recomputed for that team before sending, so a Country
    Director cannot raise a backlog that is not there.
    """
    from apps.accounts.models import StaffProfile

    if not may_delegate(request.user, country=True):
        return _action_response(
            request,
            "Delegating work here belongs to the Country Director. You can "
            "read this page but not send from it.",
            ok=False,
            fallback=COUNTRY_OVERSIGHT_PATH,
        )

    issue_key = (request.POST.get("issue") or "").strip()
    program_lead_id = (request.POST.get("program_lead") or "").strip()
    note = (request.POST.get("note") or "").strip()
    period = _period_filters(request)

    items = oversight.build_items(
        request.user, program_lead_id=program_lead_id, **period
    )
    if not items:
        return _action_response(
            request,
            "That team has no planned work in this period.",
            ok=False,
            fallback=COUNTRY_OVERSIGHT_PATH,
        )
    if not _team_condition_holds(issue_key, items):
        return _action_response(
            request,
            "That condition is not currently true of this team, so there is "
            "nothing to send.",
            ok=False,
            fallback=COUNTRY_OVERSIGHT_PATH,
        )

    program_lead = StaffProfile.objects.filter(id=program_lead_id).first()
    school = next((i for i in items if i.school_id), None)

    try:
        action = oversight_actions.send_team_action_to_program_lead(
            sender=request.user,
            program_lead_staff=program_lead,
            issue_key=issue_key,
            school=_school_for(school),
            fy=period["fy"],
            note=note,
        )
    except ActionError as exc:
        return _action_response(
            request, str(exc), ok=False, fallback=COUNTRY_OVERSIGHT_PATH
        )

    return _action_response(
        request,
        f"Sent to {_recipient_name(action)}. Tracked under Actions Sent.",
        fallback=COUNTRY_OVERSIGHT_PATH,
    )


def _team_condition_holds(issue_key: str, items) -> bool:
    """Whether the team-level condition is actually true right now.

    Each maps to the per-record risks already computed, so a team ask and the
    rows a Program Lead will open are the same evidence.
    """
    risk_keys = {risk["key"] for item in items for risk in item.risks}
    if issue_key == "team_partner_backlog":
        return "partner_not_scheduled" in risk_keys
    if issue_key == "team_costing_backlog":
        return "scheduled_without_cost" in risk_keys
    if issue_key == "team_execution_risk":
        return "activity_overdue" in risk_keys
    return False


def _school_for(item):
    if item is None:
        return None
    from apps.schools.models import School

    return School.objects.filter(id=item.school_id).first()


def _filter_options(items) -> dict:
    """The values actually present in this view, so no filter returns nothing.

    Offering the full vocabulary would let a supervisor pick an activity type
    their team never plans and conclude the page is broken.
    """
    return {
        "activity_types": sorted({i.activity_type for i in items if i.activity_type}),
        "statuses": sorted(
            {
                (
                    i.assignment_status
                    if i.is_awaiting_partner_schedule
                    else i.activity_status
                )
                for i in items
            }
            - {""}
        ),
        "partners": sorted(
            {(i.partner_id, i.partner_name) for i in items if i.partner_id},
            key=lambda pair: pair[1],
        ),
        "risks": sorted({r["key"] for i in items for r in i.risks}),
    }


def _program_leads(items) -> list[dict]:
    """The Program Leads present in this plan, for the filter."""
    seen: dict[str, str] = {}
    for item in items:
        if item.supervising_pl_id and item.supervising_pl_id not in seen:
            seen[item.supervising_pl_id] = item.supervising_pl_name
    return [{"id": k, "name": v} for k, v in sorted(seen.items(), key=lambda kv: kv[1])]


def _export_response(items, filename: str):
    """CSV of exactly the rows the page is showing.

    Streamed from the same item list, so the export and the page can never
    disagree about scope, period or totals.
    """
    import csv

    from django.http import StreamingHttpResponse

    class _Echo:
        def write(self, value):
            return value

    writer = csv.writer(_Echo())
    response = StreamingHttpResponse(
        (writer.writerow(row) for row in oversight.export_rows(items)),
        content_type="text/csv",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@require_page_permission("team_planning_oversight")
@require_export_permission
def team_planning_export_view(request):
    """The Program Lead's current view, as CSV. Same scope, same filters."""
    period = _period_filters(request)
    items = oversight.build_items(
        request.user,
        staff_id=(request.GET.get("team_member") or "").strip() or None,
        filters=oversight.read_filters(request),
        **period,
    )
    scope = oversight.resolve_oversight_scope(request.user)
    split = oversight.split_own_and_team(items, scope)
    tab = (request.GET.get("tab") or "all").strip()
    visible = _apply_pl_tab(split, items, tab if tab in dict(PL_TABS) else "all")
    return _export_response(visible, f"team-planning-oversight-{period['fy']}.csv")


@require_page_permission("country_planning_oversight")
@require_export_permission
def country_planning_export_view(request):
    """The country plan, as CSV, honouring the current filters."""
    period = _period_filters(request)
    items = oversight.build_items(
        request.user,
        program_lead_id=(request.GET.get("program_lead") or "").strip() or None,
        filters=oversight.read_filters(request),
        **period,
    )
    return _export_response(items, f"country-planning-oversight-{period['fy']}.csv")


@require_any_page_permission("team_planning_oversight", "country_planning_oversight")
def oversight_detail_view(request):
    """One item's full Planning-to-Closure lineage, read-only.

    Shared by both pages and gated on either oversight permission, because the
    question it answers — what is this piece of work and where has it been — is
    the same for a Program Lead and a Country Director. Scope is enforced on
    the record, not the route: the item is rebuilt and then checked against the
    caller's own lens, so an id belonging to another team resolves to nothing.
    """
    scope = oversight.resolve_oversight_scope(request.user)
    item = _item_in_scope(
        request.user,
        scope,
        activity_id=(request.GET.get("activity_id") or "").strip() or None,
        assignment_id=(request.GET.get("assignment_id") or "").strip() or None,
    )
    if item is None:
        return render(
            request,
            "partials/oversight/detail_drawer.html",
            {"item": None},
            status=404,
        )

    return render(
        request,
        "partials/oversight/detail_drawer.html",
        {
            "item": item,
            "lineage": _lineage_for(item),
            # `not scope.is_country` was enough while only the Programme Lead
            # reached this drawer. IA and the Accountant now do, for Cluster
            # Oversight, and they are not country-scoped in the sense that
            # check meant — so the send button would have drawn for them and
            # the endpoint refused it.
            "can_send": not scope.is_country
            and may_delegate(request.user, country=False),
        },
    )


def _lineage_for(item) -> dict:
    """The canonical records behind one item, each read from its own source.

    Nothing is recomputed here: the cost lines are the ones the fund request
    and the monthly budget are built from, so the drawer and the budget cannot
    tell different stories about the same activity.
    """
    if not item.activity_id:
        return {"cost_lines": [], "fund_requests": [], "assignment": None}

    from apps.activities.models import ActivityScheduleCostLine
    from apps.partners.models import PartnerAssignment

    cost_lines = list(
        ActivityScheduleCostLine.objects.filter(activity_id=item.activity_id).order_by(
            "created_at"
        )
    )
    fund_requests = []
    try:
        from apps.fund_requests.models import WeeklyFundRequestLine

        fund_requests = list(
            WeeklyFundRequestLine.objects.filter(
                activity_budget_line__activity_id=item.activity_id
            ).select_related("weekly_fund_request")[:10]
        )
    except Exception:  # noqa: BLE001 — the drawer degrades rather than 500s
        fund_requests = []

    # The handover this activity came from, where the partner scheduled it.
    assignment = PartnerAssignment.objects.filter(
        scheduled_activity_id=item.activity_id
    ).first()

    return {
        "cost_lines": cost_lines,
        "cost_total": sum(line.amount or 0 for line in cost_lines),
        "fund_requests": fund_requests,
        "assignment": assignment,
    }


@require_page_permission("team_planning_oversight")
@require_POST
def team_planning_send_action_view(request):
    """ "Send to <CCEO>" — one risk, delegated to the person answerable for it.

    Rebuilds the item from the service rather than trusting the posted id, so a
    Program Lead cannot send an action about a record outside their team by
    editing the form.
    """
    if not may_delegate(request.user, country=False):
        return _action_response(
            request,
            "Delegating work here belongs to the Programme Lead who supervises "
            "the team. You can read this page but not send from it.",
            ok=False,
        )

    risk_key = (request.POST.get("risk") or "").strip()
    activity_id = (request.POST.get("activity_id") or "").strip() or None
    assignment_id = (request.POST.get("assignment_id") or "").strip() or None
    note = (request.POST.get("note") or "").strip()

    scope = oversight.resolve_oversight_scope(request.user)
    item = _item_in_scope(
        request.user, scope, activity_id=activity_id, assignment_id=assignment_id
    )
    if item is None:
        return _action_response(request, "That record is not in your team.", ok=False)

    try:
        result = oversight_actions.send_risk_to_owner(
            sender=request.user,
            item=item,
            risk_key=risk_key,
            note=note,
            within_staff_ids=scope.supervised_ids or None,
        )
    except ActionError as exc:
        return _action_response(request, str(exc), ok=False)

    # Two shapes, because there are two kinds of ask. A named delegation
    # returns the TeamAction it opened and is tracked under Actions Sent; a
    # queue nudge returns the ids it reached and is tracked nowhere, because
    # nobody personally acquired the obligation. Saying "tracked under Actions
    # Sent" for the second would send the supervisor to an empty list.
    if isinstance(result, list):
        return _action_response(
            request, f"Sent to {len(result)} colleague(s) in that queue."
        )
    return _action_response(
        request, f"Sent to {_recipient_name(result)}. Tracked under Actions Sent."
    )


def _item_in_scope(user, scope, *, activity_id, assignment_id):
    """The one item, only if this principal may see it.

    Scope is re-derived from the service rather than checked against the URL:
    the page's filter is the authority on what a person may read, so the send
    path asks it the same question rather than inventing a second rule.
    """
    if not (activity_id or assignment_id):
        return None
    item = oversight.build_item_by_reference(
        activity_id=activity_id, assignment_id=assignment_id
    )
    if item is None:
        return None
    if scope.is_country:
        return item
    owner_ids = {item.operational_owner_id, item.managing_staff_id}
    return item if owner_ids & scope.team_ids else None


def _recipient_name(action) -> str:
    from apps.accounts.models import User

    user = User.objects.filter(id=action.recipient_id).first()
    return getattr(user, "name", "") or "the responsible staff member"


def _action_response(
    request,
    message: str,
    *,
    ok: bool = True,
    fallback: str = TEAM_OVERSIGHT_PATH,
):
    """A short confirmation for the HTMX swap, or a redirect for a plain post.

    The no-JavaScript path returns the sender to the page they sent from, and
    that page is named by the Referer header — which the sender's browser
    supplies and an attacker can therefore choose. Only its *path* is used,
    and only through `local_redirect`, so a Referer naming another host lands
    on the same path of this site or on the fallback. Handing the raw header
    to `redirect()` is an open redirect, and on an authenticated app that is a
    credible phishing primitive: the link really does come from this domain.
    """
    from urllib.parse import urlsplit

    from django.contrib import messages
    from django.http import HttpResponse

    from apps.core.redirects import local_redirect

    if request.headers.get("HX-Request") == "true":
        tone = "success" if ok else "danger"
        return HttpResponse(
            f'<p class="pill pill-{tone}" role="status">{escape(message)}</p>'
        )
    messages.success(request, message) if ok else messages.error(request, message)
    came_from = urlsplit(request.META.get("HTTP_REFERER") or "").path
    return local_redirect(came_from, fallback=fallback)


@require_page_permission("country_planning_oversight")
def country_planning_team_view(request, staff_id: str):
    """One Program Lead's team, expanded — the CD page's level 2 and 3.

    Scoped by rebuilding from the service with the PL filter applied rather
    than by trusting the id in the URL to be one the caller may read.
    """
    period = _period_filters(request)
    items = oversight.build_items(request.user, program_lead_id=staff_id, **period)

    return render(
        request,
        "partials/oversight/cd_team_detail.html",
        {
            **period,
            "staff_id": staff_id,
            "summary": oversight.summarize(items),
            "owner_groups": oversight.group_by_owner(items),
        },
    )


# ── Partner oversight ────────────────────────────────────────────────────────
# The Program Lead's lens on partner-delivered work. Organised by partner
# because that is the unit a supervisor chases: "has Partner X scheduled the
# four schools we gave them" is one question, not four.
@require_page_permission("partner_oversight")
def partner_oversight_view(request):
    """Which schools are with partners, who has scheduled, and what it costs."""
    from apps.planning import partner_oversight_service as partner_oversight

    period = _period_filters(request)
    partner_id = (request.GET.get("partner") or "").strip() or None

    # Built for the whole period, then narrowed in Python. The dropdown's
    # options have to come from the unfiltered set: derived from the filtered
    # one, choosing a partner would collapse the list to that partner and
    # leave no way back to any other.
    all_items = partner_oversight.build_items(
        request.user, fy=period["fy"], month=period["month"]
    )
    items = (
        [i for i in all_items if i.partner_id == partner_id]
        if partner_id
        else all_items
    )
    summary = partner_oversight.summarize(items)

    context = {
        **period,
        "partner": partner_id,
        "summary": summary,
        "kpis": _partner_kpis(summary),
        "groups": partner_oversight.group_by_partner(items),
        # Requests a CCEO raised that this Program Lead has to answer. Kept
        # above the partner groups because a decision somebody is waiting on
        # outranks routine monitoring.
        "withdrawal_requests": partner_oversight.withdrawal_requests(request.user),
        "partners": sorted(
            {(i.partner_id, i.partner_name) for i in all_items if i.partner_id},
            key=lambda pair: pair[1],
        ),
        "fy_options": fy_options(),
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/oversight/partner_workspace.html", context)
    return render(request, "pages/oversight/partner_oversight.html", context)


def _partner_kpis(summary) -> list[dict]:
    """Headline tiles, each a field of the same fold the lists are built from.

    Built through the metric registry for the same reason the planning tiles
    are: "Scheduled Partner Budget" has to mean one thing, and a second view
    that computes it its own way is how a platform ends up with two correct
    numbers under one word.
    """
    return [
        render_kpi_item(
            "partner_oversight_active_partners",
            MetricValue.measured(summary["active_partners"]),
            helper=f"{summary['schools_assigned']} schools assigned",
            icon="handshake",
        ),
        render_kpi_item(
            "partner_oversight_yet_to_schedule",
            MetricValue.measured(summary["awaiting_schedule"]),
            helper="No cost until a partner schedules",
            tone="warning" if summary["awaiting_schedule"] else "neutral",
            icon="clock",
        ),
        render_kpi_item(
            "partner_oversight_scheduled",
            MetricValue.measured(summary["scheduled"]),
            helper=f"{summary['in_progress']} in progress",
            icon="calendar",
        ),
        render_kpi_item(
            "partner_oversight_needing_attention",
            MetricValue.measured(summary["at_risk"]),
            helper=f"{summary['returned']} returned to staff",
            tone="danger" if summary["at_risk"] else "neutral",
            icon="warning",
        ),
        render_kpi_item(
            "partner_oversight_scheduled_budget",
            MetricValue.measured(summary["scheduled_budget"]),
            helper="Scheduled work only",
            icon="currency",
        ),
        render_kpi_item(
            "partner_oversight_payment_pending",
            MetricValue.measured(summary["payment_pending"]),
            helper="Verified and awaiting payment",
            tone="warning" if summary["payment_pending"] else "neutral",
            icon="expense",
        ),
    ]


@require_page_permission("partner_oversight")
def partner_oversight_detail_view(request):
    """One handover's full record — handover, schedule, evidence, money.

    Scope is enforced on the record rather than the URL, the same way the
    planning drawer does it: the item is rebuilt and then checked against the
    caller's own lens, so an id belonging to another team resolves to nothing.
    """

    item = _partner_item_in_scope(
        request.user, (request.GET.get("assignment_id") or "").strip()
    )
    if item is None:
        return render(
            request,
            "partials/oversight/partner_detail_drawer.html",
            {"item": None},
            status=404,
        )

    from apps.planning.action_service import ROLE_QUEUES
    from apps.planning.partner_oversight_actions import (
        CCEO_ADDRESSED_RISKS,
        PARTNER_ADDRESSED_RISKS,
    )

    # Which send each risk offers is decided here, from who the risk names as
    # responsible — never from what the reader would like to be able to do.
    # A risk naming a role queue takes precedence: verification and payment
    # belong to Impact Assessment and the Accountant no matter which staff
    # member is nearest the record.
    for risk in item.risks:
        role = risk.get("responsible_role") or ""
        if role in ROLE_QUEUES:
            risk["send"] = "queue"
            risk["send_label"] = f"Ask {ROLE_QUEUES[role]}"
        elif risk["key"] in PARTNER_ADDRESSED_RISKS:
            risk["send"] = "partner"
            risk["send_label"] = f"Remind {item.partner_name or 'the partner'}"
        elif risk["key"] in CCEO_ADDRESSED_RISKS:
            risk["send"] = "cceo"
            risk["send_label"] = f"Send to {item.responsible_cceo_name or 'the CCEO'}"
        else:
            risk["send"] = ""

    return render(
        request,
        "partials/oversight/partner_detail_drawer.html",
        {
            "item": item,
            "lineage": _partner_lineage(item),
            "can_act": _partner_scope(request.user)["kind"] == "team",
        },
    )


def _partner_scope(user) -> dict:
    from apps.planning.partner_oversight_service import _resolve_scope

    return _resolve_scope(user)


def _partner_item_in_scope(user, assignment_id: str):
    """The one handover, only if this principal may see it."""
    from apps.planning import partner_oversight_service as partner_oversight

    if not assignment_id:
        return None
    item = partner_oversight.build_item_by_assignment(assignment_id)
    if item is None:
        return None
    scope = _partner_scope(user)
    if scope["is_country"]:
        return item
    owners = {item.responsible_cceo_id, item.supervising_pl_id}
    return item if owners & scope["staff_ids"] else None


def _partner_lineage(item) -> dict:
    """The canonical records behind one handover, each read from its source."""
    from apps.activities.models import ActivityScheduleCostLine

    cost_lines = []
    if item.partner_activity_id:
        cost_lines = list(
            ActivityScheduleCostLine.objects.filter(
                activity_id=item.partner_activity_id
            ).order_by("created_at")
        )
    return {
        "cost_lines": cost_lines,
        "cost_total": sum(line.amount or 0 for line in cost_lines),
    }


@require_page_permission("partner_oversight")
@require_POST
def partner_oversight_send_action_view(request):
    """Remind the partner, ask the CCEO, or escalate — one of exactly three.

    Which one is legitimate is not the caller's to choose: the posted intent is
    checked against who the risk names as responsible, so a form edited in the
    browser cannot open a TeamAction against a CCEO for a partner's delay.
    """
    from apps.planning import partner_oversight_actions as actions

    intent = (request.POST.get("intent") or "").strip()
    risk_key = (request.POST.get("risk") or "").strip()
    note = (request.POST.get("note") or "").strip()

    item = _partner_item_in_scope(
        request.user, (request.POST.get("assignment_id") or "").strip()
    )
    if item is None:
        return _action_response(
            request,
            "That assignment is not in your team.",
            ok=False,
            fallback=PARTNER_OVERSIGHT_PATH,
        )

    try:
        if intent == "nudge_queue":
            notified = actions.nudge_role_queue(
                sender=request.user, item=item, risk_key=risk_key, note=note
            )
            message = f"Sent to {len(notified)} colleague(s) in that queue."
        elif intent == "remind_partner":
            actions.remind_partner(
                sender=request.user, item=item, risk_key=risk_key, note=note
            )
            message = f"Reminder sent to {item.partner_name or 'the partner'}."
        elif intent == "send_to_cceo":
            action = actions.send_to_managing_cceo(
                sender=request.user, item=item, risk_key=risk_key, note=note
            )
            message = f"Sent to {_recipient_name(action)}. Tracked under Actions Sent."
        elif intent == "escalate":
            action = actions.escalate_to_country_director(
                sender=request.user, item=item, note=note
            )
            message = f"Escalated to {_recipient_name(action)}."
        else:
            return _action_response(request, "Unknown action.", ok=False)
    except ActionError as exc:
        return _action_response(
            request, str(exc), ok=False, fallback=PARTNER_OVERSIGHT_PATH
        )

    return _action_response(request, message, fallback=PARTNER_OVERSIGHT_PATH)


@require_page_permission("partner_oversight")
@require_export_permission
def partner_oversight_export_view(request):
    """The current partner view, as CSV. Same scope, same period, same rows."""
    import csv

    from django.http import StreamingHttpResponse

    from apps.planning import partner_oversight_service as partner_oversight

    period = _period_filters(request)
    items = partner_oversight.build_items(
        request.user,
        fy=period["fy"],
        month=period["month"],
        partner_id=(request.GET.get("partner") or "").strip() or None,
    )

    class _Echo:
        def write(self, value):
            return value

    writer = csv.writer(_Echo())
    response = StreamingHttpResponse(
        (writer.writerow(row) for row in partner_oversight.export_rows(items)),
        content_type="text/csv",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="partner-oversight-{period["fy"]}.csv"'
    )
    return response


# ── Taking work back from a partner ──────────────────────────────────────────
@require_page_permission("partner_oversight")
def partner_withdrawal_preview_view(request):
    """What confirming would actually do, computed on the server.

    A preview built in the browser could disagree with what the service then
    does; this asks the same functions the service asks, so the number shown
    is the number that will move.
    """
    from apps.partners import withdrawal_service

    item = _partner_item_in_scope(
        request.user, (request.GET.get("assignment_id") or "").strip()
    )
    if item is None:
        return render(
            request,
            "partials/oversight/withdrawal_drawer.html",
            {"preview": None},
            status=404,
        )

    from apps.partners.withdrawal_models import WithdrawalDisposition, WithdrawalReason

    preview = withdrawal_service.preview(request.user, item.partner_assignment_id)
    return render(
        request,
        "partials/oversight/withdrawal_drawer.html",
        {
            "preview": preview,
            "item": item,
            "reasons": WithdrawalReason.choices,
            "dispositions": WithdrawalDisposition.choices,
            "partners": _eligible_replacements(item),
            # A CCEO looking at work a partner has already scheduled gets the
            # request form, not the withdraw form. Decided here from the same
            # rule the service enforces, so the page cannot offer a control
            # the service will refuse.
            "must_request": _must_request(request.user, item, preview),
        },
    )


def _eligible_replacements(item) -> list[dict]:
    """Active partners other than the one the work is being taken from."""
    from apps.partners.models import Partner

    return [
        {"id": p.id, "name": p.name}
        for p in Partner.objects.filter(active_status=True, deleted_at__isnull=True)
        .exclude(id=item.partner_id)
        .order_by("name")[:100]
    ]


def _must_request(user, item, preview) -> bool:
    """True when this reader may only ask, not decide."""
    from apps.core.rbac import EdifyRole
    from apps.partners.withdrawal_models import WithdrawalKind

    role = getattr(user, "active_role", "") or ""
    return (
        role == EdifyRole.CCEO.value
        and preview["kind"] != WithdrawalKind.WITHDRAW_UNSCHEDULED
    )


@require_page_permission("partner_oversight")
@require_POST
def partner_withdrawal_submit_view(request):
    """Withdraw, or request withdrawal — the service decides which is allowed."""
    from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError
    from apps.partners import withdrawal_service

    item = _partner_item_in_scope(
        request.user, (request.POST.get("assignment_id") or "").strip()
    )
    if item is None:
        return _action_response(
            request,
            "That assignment is not in your team.",
            ok=False,
            fallback=PARTNER_OVERSIGHT_PATH,
        )

    data = {
        "reason_category": request.POST.get("reason_category"),
        "partner_facing_reason": request.POST.get("partner_facing_reason"),
        "internal_note": request.POST.get("internal_note"),
        "disposition": request.POST.get("disposition"),
        "replacement_partner_id": request.POST.get("replacement_partner_id"),
    }
    requesting = (request.POST.get("intent") or "") == "request"

    try:
        if requesting:
            withdrawal_service.request_withdrawal(
                item.partner_assignment_id, data, request.user
            )
            message = "Sent to your Program Lead for a decision."
        else:
            result = withdrawal_service.withdraw(
                item.partner_assignment_id, data, request.user
            )
            message = f"{result.get_kind_display()} — {result.get_state_display()}."
    except (BadRequest, ConflictError, Forbidden, NotFoundError) as exc:
        return _action_response(
            request, str(exc), ok=False, fallback=PARTNER_OVERSIGHT_PATH
        )

    return _action_response(request, message, fallback=PARTNER_OVERSIGHT_PATH)


@require_page_permission("partner_oversight")
@require_POST
def partner_withdrawal_review_view(request):
    """The supervising Program Lead answers a CCEO's request."""
    from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError
    from apps.partners import withdrawal_service

    try:
        result = withdrawal_service.review_request(
            (request.POST.get("withdrawal_id") or "").strip(),
            {
                "decision": request.POST.get("decision"),
                "note": request.POST.get("note"),
                "replacement_partner_id": request.POST.get("replacement_partner_id"),
            },
            request.user,
        )
    except (BadRequest, ConflictError, Forbidden, NotFoundError) as exc:
        return _action_response(
            request, str(exc), ok=False, fallback=PARTNER_OVERSIGHT_PATH
        )

    return _action_response(
        request,
        f"Request {result.get_state_display().lower()}.",
        fallback=PARTNER_OVERSIGHT_PATH,
    )
