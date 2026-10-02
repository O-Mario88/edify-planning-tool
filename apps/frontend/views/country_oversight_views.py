"""Country Planning Oversight — the planning-coverage dashboard and its drill-downs.

Everything here renders figures the canonical service computed
(apps.planning.country_oversight): the views choose which part of one tree to
show and never add, divide or restate a rule. The only write is the Country
Director's "Follow Up with PL", and the Programme Lead's governed response to
it; neither touches a plan, a target, an activity or a portfolio.

The first response carries the country, the Programme Leads, the four charts
and the open follow-ups. Officers, Partners, schools, slots and activities
arrive when a row or a drawer asks for them.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.permissions import (
    RolePermissionService,
    require_any_page_permission,
    require_export_permission,
    require_page_permission,
)
from apps.planning.country_oversight import followups as fu
from apps.planning.country_oversight import service as svc
from apps.planning.country_oversight.coverage import fy_label
from apps.planning.country_oversight.requirements import NO_LEAD_KEY, NO_OWNER_KEY

PAGE_PATH = "/country-planning-oversight/"
WORKSPACE_ID = "cpo-workspace"


def _may_see_schools(user) -> bool:
    """The RVP reads the country's figures, never its school rows."""
    from apps.core.scoping import resolve_user_scope

    return bool(resolve_user_scope(user).can_view_school_level_detail)


def _may_read_quality(user) -> bool:
    return (getattr(user, "active_role", "") or "") in (
        "ImpactAssessment",
        "CountryDirector",
        "Admin",
    )


def _followups_panel(fy: str, *, limit: int = 5, module: str = "planning") -> dict:
    """The open follow-ups one Country Oversight stage asked; the register
    drawer ("View all") lists both stages together."""
    from apps.planning.followup_models import (
        OPEN_FOLLOW_UP_STATES,
        PlanningOversightFollowUp,
    )

    open_rows = PlanningOversightFollowUp.objects.filter(
        fy=fy, status__in=OPEN_FOLLOW_UP_STATES, module=module
    )
    latest = list(open_rows.order_by("-assigned_at")[:limit])
    return {
        "count": open_rows.count(),
        "rows": [_followup_card(row) for row in latest],
    }


def _followup_card(row) -> dict:
    issue = fu.issue_of(row.issue_type)
    subject = (
        row.activity_label
        or row.school_name
        or row.partner_name
        or row.cceo_name
        or row.program_lead_name
    )
    return {
        "id": row.id,
        "title": f"{issue.label if issue else row.issue_type} · {subject}",
        "to": row.program_lead_name,
        "status": row.get_status_display(),
        "tone": fu.STATUS_TONES.get(row.status, "sent"),
        "date": row.last_reminder_at or row.assigned_at,
        "due": row.due_date,
        "overdue": row.is_overdue,
        "reminders": row.reminder_count,
        "remaining": row.live_remaining
        if row.live_remaining is not None
        else row.remaining_value,
        "instruction": row.instruction,
        "is_open": row.is_open,
        "issue": row.issue_type,
        "module": row.module,
        "module_label": row.get_module_display(),
        # The planning obligation when it was sent, and the school actions the
        # Lead has linked, under names the page's own words.
        "whole_value": row.required_value,
        "asks_sent": len(row.linked_team_action_ids or []),
    }


def _filter_options(snapshot, filters) -> dict:
    from apps.core.fy import fy_options

    owners = [
        option
        for option in snapshot.owner_options
        if not filters.program_lead or option["lead"] == filters.program_lead
    ]
    return {
        "fy_options": [{"value": fy, "label": fy_label(fy)} for fy in fy_options()],
        "regions": sorted(snapshot.region_names.items(), key=lambda pair: pair[1]),
        "districts": sorted(snapshot.district_names.items(), key=lambda pair: pair[1]),
        "leads": snapshot.lead_options,
        "owners": owners,
        "partners": sorted(snapshot.partner_names.items(), key=lambda pair: pair[1]),
        "types": svc.TYPE_OPTIONS,
        "channels": svc.CHANNEL_OPTIONS,
        "clusters": svc.CLUSTER_OPTIONS,
        "statuses": svc.STATUS_OPTIONS,
        "months": [
            (m, date(2000, m, 1).strftime("%B"))
            for m in (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9)
        ],
    }


def _dashboard_context(request, snapshot, filters) -> dict:
    from apps.frontend.views.oversight_views import country_lens_tabs

    counts = fu.open_counts(filters.fy)
    header = svc.header(snapshot)
    return {
        "filters": filters,
        "query": filters.query(),
        "header": header,
        "is_uganda": (header["country"] or "").strip().lower() == "uganda",
        "kpis": svc.kpis(snapshot),
        "type_rows": svc.type_rows(snapshot),
        "charts": svc.charts(snapshot),
        "country_cells": svc.row_cells(snapshot.tree.country),
        "country_followups": counts.get(("country", ""), 0),
        "unmapped_schools": snapshot.tree.country.unmapped_schools,
        "lead_rows": svc.lead_rows(snapshot, counts),
        "window": snapshot.tree.window,
        "options": _filter_options(snapshot, filters),
        "followups": _followups_panel(filters.fy),
        "may_follow_up": fu.may_follow_up(request.user),
        "may_read_quality": _may_read_quality(request.user),
        "may_see_schools": _may_see_schools(request.user),
        "may_export": RolePermissionService.can_export(
            request.user, PAGE_PATH + "coverage-export"
        ),
        "lens_tabs": country_lens_tabs("coverage"),
        "active_oversight_view": "coverage",
        "columns": svc.TABLE_COLUMNS,
        "no_lead_key": NO_LEAD_KEY,
        "more_open": bool(
            filters.district
            or filters.school_type
            or filters.channel
            or filters.cluster_status
        ),
    }


def coverage_page(request):
    """The planning-coverage dashboard: the page's default lens."""
    filters = svc.read_filters(request)
    refresh = request.GET.get("refresh") == "1"
    snapshot = svc.snapshot_for(request.user, filters, refresh=refresh)
    context = _dashboard_context(request, snapshot, filters)
    if request.headers.get("HX-Request") == "true":
        # A partial for every in-page request: the workspace when only it is
        # swapped, otherwise the whole dashboard, never the shell around it.
        if (request.headers.get("HX-Target") or "") == WORKSPACE_ID:
            return render(request, "partials/country_oversight/workspace.html", context)
        return render(request, "partials/country_oversight/page.html", context)
    return render(request, "pages/oversight/country_planning.html", context)


@require_page_permission("country_planning_oversight")
def rows_view(request):
    """A Lead's people, or an officer's delivery channels, as table rows."""
    filters = svc.read_filters(request)
    snapshot = svc.snapshot_for(request.user, filters)
    counts = fu.open_counts(filters.fy)
    level = (request.GET.get("level") or "").strip()
    key = (request.GET.get("key") or "").strip()
    context = {
        "filters": filters,
        "query": filters.query(),
        "may_follow_up": fu.may_follow_up(request.user),
        "may_see_schools": _may_see_schools(request.user),
        "parent": key,
    }
    if level == "lead":
        lead = svc.find_lead(snapshot, key)
        if lead is None:
            raise Http404
        context.update({"lead": lead, "rows": svc.owner_rows(snapshot, key, counts)})
        return render(request, "partials/country_oversight/rows_owners.html", context)
    if level == "owner":
        lead, owner = svc.find_owner(snapshot, key)
        if owner is None:
            raise Http404
        context.update(
            {
                "lead": lead,
                "owner": owner,
                "rows": svc.partner_rows(snapshot, key),
            }
        )
        return render(request, "partials/country_oversight/rows_partners.html", context)
    raise Http404


def _issue_menu(tally) -> list[dict]:
    """The gaps a follow-up could be about, each with its live figure."""
    rows = []
    for issue in fu.ISSUES.values():
        if issue.key in ("school_gap", "other"):
            continue
        required, planned, remaining = fu.metric_values(issue, tally)
        rows.append(
            {
                "key": issue.key,
                "label": issue.label,
                "required": required,
                "planned": planned,
                "remaining": remaining,
            }
        )
    return rows


@require_page_permission("country_planning_oversight")
def drawer_view(request):
    """Every drawer the page opens: a Lead, an officer, a Partner, a KPI, the
    follow-ups, and Impact Assessment's data-quality queue."""
    filters = svc.read_filters(request)
    kind = (request.GET.get("kind") or "").strip()
    key = (request.GET.get("key") or "").strip()
    base = {
        "filters": filters,
        "query": filters.query(),
        "may_follow_up": fu.may_follow_up(request.user),
        "may_see_schools": _may_see_schools(request.user),
        "may_read_quality": _may_read_quality(request.user),
        "drawer_size": "lg" if kind in ("followups", "dq") else "xl",
        "page_query": _page_query(request),
    }
    if kind == "followups":
        return render(
            request,
            "partials/country_oversight/drawer_followups.html",
            _followups_register(request, filters, base),
        )
    if kind == "dq":
        if not _may_read_quality(request.user):
            return HttpResponse(status=403)
        from apps.planning.country_oversight.data_quality import summary

        return render(
            request,
            "partials/country_oversight/drawer_quality.html",
            {**base, **summary(request.user, filters)},
        )

    snapshot = svc.snapshot_for(request.user, filters)
    counts = fu.open_counts(filters.fy)
    header = svc.header(snapshot)
    if kind == "lead":
        lead = svc.find_lead(snapshot, key)
        if lead is None:
            raise Http404
        return render(
            request,
            "partials/country_oversight/drawer_lead.html",
            {
                **base,
                "header": header,
                "lead": lead,
                "cells": svc.row_cells(lead.tally),
                "tally": lead.tally,
                "owners": _drawer_page(svc.owner_rows(snapshot, key, counts), request),
                "issues": _issue_menu(lead.tally),
                "followups": _scoped_followups(filters.fy, lead_key=key),
            },
        )
    if kind in ("owner", "partner"):
        lead, owner = svc.find_owner(snapshot, key)
        if owner is None:
            raise Http404
        partner = (
            (request.GET.get("partner_key") or "").strip() if kind == "partner" else ""
        )
        tally = owner.partners.get(partner) if kind == "partner" else owner.tally
        if tally is None:
            raise Http404
        return render(
            request,
            "partials/country_oversight/drawer_owner.html",
            {
                **base,
                "header": header,
                "lead": lead,
                "owner": owner,
                "partner": partner,
                "partner_name": snapshot.partner_names.get(partner, "")
                if partner and partner != svc.NO_PARTNER_KEY
                else ("Staff delivery" if partner else ""),
                "cells": svc.row_cells(tally),
                "tally": tally,
                "issues": _issue_menu(tally),
                "partners": _drawer_page(
                    svc.partner_rows(snapshot, key) if kind == "owner" else [], request
                ),
                "followups": _scoped_followups(
                    filters.fy,
                    lead_key=lead.key if lead else "",
                    cceo_key=key if owner.kind != "pl_personal" else "",
                ),
                "can_follow_up_here": lead is not None
                and lead.key != NO_LEAD_KEY
                and key != NO_OWNER_KEY,
            },
        )
    if kind == "kpi":
        metric = (request.GET.get("metric") or "").strip()
        if metric not in svc.KPI_GAPS:
            raise Http404
        card = next(card for card in svc.kpis(snapshot) if card["metric_key"] == metric)
        return render(
            request,
            "partials/country_oversight/drawer_kpi.html",
            {
                **base,
                "header": header,
                "card": card,
                "gap": svc.KPI_GAPS[metric],
                "gap_label": svc.GAP_FIGURES[svc.KPI_GAPS[metric]],
                "lead_rows": svc.lead_rows(snapshot, counts),
                "chart_rows": _drawer_page(
                    [
                        {
                            "name": lead.name,
                            "cells": svc.row_cells(lead.tally),
                            "tally": lead.tally,
                        }
                        for lead in snapshot.tree.leads
                    ],
                    request,
                ),
            },
        )
    raise Http404


#: Rows in one page of a drawer's list.
DRAWER_PAGE_SIZE = 15


def _drawer_page(rows, request) -> dict:
    """One page of a drawer's list, and what the drawer pager needs."""
    rows = list(rows)
    try:
        page = max(1, int(request.GET.get("page") or 1))
    except ValueError:
        page = 1
    pages = max(1, (len(rows) + DRAWER_PAGE_SIZE - 1) // DRAWER_PAGE_SIZE)
    page = min(page, pages)
    return {
        "rows": rows[(page - 1) * DRAWER_PAGE_SIZE : page * DRAWER_PAGE_SIZE],
        "page": page,
        "pages": pages,
        "total": len(rows),
    }


def _page_query(request) -> str:
    return urlencode([(k, v) for k, v in request.GET.items() if k != "page"])


def _scoped_followups(fy: str, *, lead_key: str = "", cceo_key: str = "") -> list[dict]:
    from apps.planning.followup_models import (
        OPEN_FOLLOW_UP_STATES,
        PlanningOversightFollowUp,
    )

    rows = PlanningOversightFollowUp.objects.filter(
        fy=fy, status__in=OPEN_FOLLOW_UP_STATES
    )
    if lead_key:
        rows = rows.filter(program_lead_staff_id=lead_key)
    if cceo_key:
        rows = rows.filter(cceo_staff_id=cceo_key)
    return [_followup_card(row) for row in rows.order_by("-assigned_at")[:20]]


def _execution_remind_query(row) -> str:
    """The execution follow-up drawer, opened on the follow-up's own period,
    Lead, officer, Partner, activity and issue — so Remind is the same ask."""
    from apps.planning.country_execution.followups import ExecScope

    params = ExecScope.of(row).filters().params()
    params.update(
        {
            "lead": row.program_lead_staff_id,
            "cceo": row.cceo_staff_id or "",
            "partner_key": row.partner_id or "",
            "activity": row.activity_id or "",
            "issue": row.issue_type,
        }
    )
    return urlencode({key: value for key, value in params.items() if value})


def _followups_register(request, filters, base) -> dict:
    """Every follow-up of the year, planning and execution together."""
    from apps.planning.followup_models import (
        OPEN_FOLLOW_UP_STATES,
        PlanningOversightFollowUp,
    )

    show = (request.GET.get("show") or "open").strip()
    rows = PlanningOversightFollowUp.objects.filter(fy=filters.fy)
    if show == "open":
        rows = rows.filter(status__in=OPEN_FOLLOW_UP_STATES)
    focus = (request.GET.get("focus") or "").strip()
    items = [
        {
            **_followup_card(row),
            "record": row,
            "remind_query": _execution_remind_query(row)
            if row.module == "execution"
            else "",
        }
        for row in rows.order_by("-assigned_at")[:100]
    ]
    return {
        **base,
        "items": items,
        "show": show,
        "focus": focus,
        "fy_label": fy_label(filters.fy),
    }


@require_page_permission("country_planning_oversight")
def schools_view(request):
    """The schools behind a row or a figure — one page of them, worst first."""
    filters = svc.read_filters(request)
    if not _may_see_schools(request.user):
        return render(
            request,
            "partials/country_oversight/schools.html",
            {"withheld": True},
        )
    dataset = svc.dataset_for(request.user, filters.window)
    try:
        page = int(request.GET.get("page") or 1)
    except ValueError:
        page = 1
    listing = svc.school_rows(
        dataset,
        filters,
        lead_key=(request.GET.get("lead") or "").strip(),
        owner_key=(request.GET.get("owner") or "").strip(),
        partner_id=(request.GET.get("partner_key") or "").strip(),
        gap=(request.GET.get("gap") or "").strip(),
        page=page,
    )
    return render(
        request,
        "partials/country_oversight/schools.html",
        {
            **listing,
            "filters": filters,
            "query": filters.query(),
            "list_query": _list_query(request),
            "may_follow_up": fu.may_follow_up(request.user),
            "gap_options": svc.GAP_FIGURES.items(),
        },
    )


def _list_query(request) -> str:
    from urllib.parse import urlencode

    keep = {
        key: request.GET.get(key)
        for key in (
            "fy",
            "period",
            "quarter",
            "month",
            "week",
            "region",
            "district",
            "program_lead",
            "cceo",
            "school_type",
            "channel",
            "partner",
            "cluster_status",
            "planning_status",
            "lead",
            "owner",
            "partner_key",
            "gap",
        )
        if request.GET.get(key)
    }
    return urlencode(keep)


@require_page_permission("country_planning_oversight")
def slots_view(request):
    """One school's requirement slots and the activity filling each."""
    from apps.planning.country_oversight.coverage import school_slots

    if not _may_see_schools(request.user):
        raise Http404
    filters = svc.read_filters(request)
    dataset = svc.dataset_for(request.user, filters.window)
    school_id = (request.GET.get("school") or "").strip()
    school = dataset.facts.get(school_id)
    if school is None:
        raise Http404
    slots = school_slots(school, dataset.allocations.get(school_id), dataset.window)
    return render(
        request,
        "partials/country_oversight/slots.html",
        {"school": school, "slots": slots},
    )


# ── Follow Up with PL ────────────────────────────────────────────────────────
def _scope_from(request, filters) -> fu.Scope:
    window = filters.window
    source = request.POST if request.method == "POST" else request.GET
    from apps.core.scoping import resolve_user_scope

    return fu.Scope(
        fy=filters.fy,
        period_type=window.period,
        period_start=window.start,
        period_end=window.end,
        lead_key=(source.get("lead") or "").strip(),
        cceo_key=(source.get("owner") or "").strip(),
        school_id=(source.get("school") or "").strip(),
        country=getattr(resolve_user_scope(request.user), "country", "") or "",
    )


@require_page_permission("country_planning_oversight")
def follow_up_view(request):
    """GET: the Follow Up with PL drawer, prefilled. POST: send or remind."""
    if not fu.may_follow_up(request.user):
        return HttpResponse(
            "Following up with a Programme Lead belongs to the Country Director.",
            status=403,
        )
    filters = svc.read_filters(request)
    scope = _scope_from(request, filters)
    if scope.cceo_key and not scope.lead_key:
        snapshot = svc.snapshot_for(request.user, filters)
        lead, _owner = svc.find_owner(snapshot, scope.cceo_key)
        scope.lead_key = lead.key if lead else ""
    if request.method == "POST":
        return _send_follow_up(request, filters, scope)

    issue_key = (request.GET.get("issue") or "").strip()
    if scope.school_id and not issue_key:
        issue_key = "school_gap"
    error = ""
    tally = None
    affected = []
    total_affected = 0
    lead_name = cceo_name = school_name = region_name = ""
    try:
        tally, dataset, tree = fu.evaluate(scope)
        lead = next(
            (lead for lead in dataset.leads if lead.key == scope.lead_key), None
        )
        lead_name = lead.name if lead else ""
        owner = dataset.owners.get(scope.cceo_key) if scope.cceo_key else None
        cceo_name = owner.name if owner else ""
        school = dataset.facts.get(scope.school_id) if scope.school_id else None
        school_name = school.name if school else ""
        if school is not None:
            region_name = dataset.region_names.get(school.region_id, "")
        issues = _issue_menu(tally)
        if not issue_key:
            issue_key = (
                max(issues, key=lambda row: row["remaining"])["key"]
                if issues
                else "other"
            )
        issue = fu.ISSUES.get(issue_key) or fu.ISSUES["other"]
        affected_ids, total_affected = (
            ([scope.school_id], 1)
            if scope.school_id
            else fu.affected_schools(issue, dataset, tree, limit=8)
        )
        affected = [dataset.facts[pk] for pk in affected_ids if pk in dataset.facts]
    except Exception:  # noqa: BLE001 - the drawer still opens with an explanation
        import logging

        logging.getLogger(__name__).exception("Follow-up drawer could not read the gap")
        error = "The gap could not be read just now. Refresh and try again."
        issues = []
    existing = _scoped_followups(
        filters.fy, lead_key=scope.lead_key, cceo_key=scope.cceo_key
    )
    return render(
        request,
        "partials/country_oversight/drawer_follow_up.html",
        {
            "filters": filters,
            "query": filters.query(),
            "scope": scope,
            "issue_key": issue_key,
            "issues": issues,
            "all_issues": list(fu.ISSUES.values()),
            "tally": tally,
            "lead_name": lead_name,
            "cceo_name": cceo_name,
            "school_name": school_name,
            "region_name": region_name,
            "affected": affected,
            "total_affected": total_affected,
            "existing": existing,
            "priorities": fu.PRIORITY_CHOICES,
            "default_due": fu.default_due_date(),
            "window": filters.window,
            "error": error,
            "country": scope.country or svc.deployment_country(),
            "fy_label": fy_label(filters.fy),
            "drawer_size": "lg",
        },
    )


def _send_follow_up(request, filters, scope):
    from datetime import datetime

    raw_due = (request.POST.get("due_date") or "").strip()
    try:
        due = datetime.strptime(raw_due, "%Y-%m-%d").date() if raw_due else None
    except ValueError:
        due = None
    try:
        followup, created = fu.send_follow_up(
            sender=request.user,
            scope=scope,
            issue_key=(request.POST.get("issue") or "").strip(),
            instruction=request.POST.get("instruction") or "",
            due_date=due,
            priority=(request.POST.get("priority") or "").strip(),
            snapshot={"filters": filters.params()},
        )
    except fu.FollowUpError as exc:
        return render(
            request,
            "partials/country_oversight/follow_up_result.html",
            {"ok": False, "message": str(exc)},
            status=200,
        )
    message = (
        f"Sent to {followup.program_lead_name}. It is on their To-Do."
        if created
        else f"Reminder {followup.reminder_count} sent to {followup.program_lead_name} on the open follow-up."
    )
    response = render(
        request,
        "partials/country_oversight/follow_up_result.html",
        {
            "ok": True,
            "message": message,
            "followups": _followups_panel(filters.fy),
            "query": filters.query(),
        },
    )
    response["HX-Trigger"] = "cpo-followups-changed"
    return response


@require_page_permission("country_planning_oversight")
@require_POST
def follow_up_action_view(request, followup_id: str, action: str):
    """The Country Director closes (with a reason) or cancels a follow-up."""
    from apps.planning.followup_models import PlanningOversightFollowUp

    followup = PlanningOversightFollowUp.objects.filter(id=followup_id).first()
    if followup is None:
        raise Http404
    reason = (request.POST.get("reason") or "").strip()
    try:
        if action == "close":
            fu.close_with_reason(followup, request.user, reason)
            message = "Closed. The reason is on the record."
        elif action == "cancel":
            fu.cancel(followup, request.user, reason)
            message = "Cancelled."
        elif action == "escalate":
            fu.escalate(followup, request.user, reason)
            message = "Escalated. It is critical and back in the Lead's queue."
        else:
            raise Http404
    except fu.FollowUpError as exc:
        return render(
            request,
            "partials/country_oversight/follow_up_result.html",
            {"ok": False, "message": str(exc)},
        )
    response = render(
        request,
        "partials/country_oversight/follow_up_result.html",
        {"ok": True, "message": message, "followups": _followups_panel(followup.fy)},
    )
    response["HX-Trigger"] = "cpo-followups-changed"
    return response


@require_page_permission("country_planning_oversight")
def followups_panel_view(request):
    """The right-hand Open Follow-ups panel, refreshed after a send."""
    filters = svc.read_filters(request)
    return render(
        request,
        "partials/country_oversight/followups_panel.html",
        {
            "followups": _followups_panel(filters.fy),
            "query": filters.query(),
            "may_follow_up": fu.may_follow_up(request.user),
        },
    )


# ── The Programme Lead's side ────────────────────────────────────────────────
_WAITING_MESSAGES = {
    "team_member": "Marked as waiting on a team member.",
    "partner": "Marked as waiting on the Partner.",
    "external": "Marked as waiting on an external dependency.",
}


def _followup_for(request, followup_id: str):
    from apps.planning.followup_models import PlanningOversightFollowUp

    followup = PlanningOversightFollowUp.objects.filter(id=followup_id).first()
    if followup is None:
        return None
    role = getattr(request.user, "active_role", "") or ""
    is_recipient = str(request.user.id) == str(followup.program_lead_user_id)
    if is_recipient or role in ("CountryDirector", "ImpactAssessment", "Admin"):
        return followup
    return None


@require_any_page_permission("team_planning_oversight", "country_planning_oversight")
def followup_detail_view(request, followup_id: str):
    """The follow-up as the Programme Lead reads it on Team Oversight."""
    followup = _followup_for(request, followup_id)
    if followup is None:
        raise Http404
    is_recipient = str(request.user.id) == str(followup.program_lead_user_id)
    issue = fu.issue_of(followup.issue_type)
    return render(
        request,
        "partials/country_oversight/followup_banner.html",
        {
            "followup": followup,
            "card": _followup_card(followup),
            "issue": issue,
            "is_recipient": is_recipient and followup.is_open,
            "can_ask": bool(issue and issue.team_action and followup.cceo_staff_id),
            "affected_count": followup.affected_count,
        },
    )


@require_any_page_permission("team_planning_oversight", "country_planning_oversight")
@require_POST
def followup_lead_action_view(request, followup_id: str, action: str):
    """Acknowledge, ask the CCEO, say what it waits on, or return it."""
    followup = _followup_for(request, followup_id)
    if followup is None:
        raise Http404
    note = (request.POST.get("note") or "").strip()
    message = ""
    try:
        if action == "acknowledge":
            fu.acknowledge(followup, request.user)
            message = "Acknowledged."
        elif action == "ask":
            _, sent, refusals = fu.ask_cceo(followup, request.user, note=note)
            message = (
                f"Sent {sent} school action{'s' if sent != 1 else ''} to "
                f"{followup.cceo_name}; linked to this follow-up."
            )
            if refusals:
                message += f" {len(refusals)} could not be sent."
        elif action == "waiting":
            if getattr(followup, "module", "planning") == "execution":
                # An execution gap names what it waits on (spec §19): a team
                # member, the Partner or an external dependency.
                from apps.planning.country_execution import followups as efu

                waiting_on = (request.POST.get("waiting_on") or "").strip()
                efu.mark_waiting_on(followup, request.user, waiting_on, note)
                message = _WAITING_MESSAGES.get(
                    waiting_on, "Marked as waiting for resolution."
                )
            else:
                fu.mark_waiting(followup, request.user, note)
                message = "Marked as waiting for resolution."
        elif action == "return":
            fu.return_for_clarification(followup, request.user, note)
            message = "Returned to the Country Director for clarification."
        else:
            raise Http404
    except fu.FollowUpError as exc:
        message = str(exc)
        ok = False
    else:
        ok = True
    followup.refresh_from_db()
    issue = fu.issue_of(followup.issue_type)
    return render(
        request,
        "partials/country_oversight/followup_banner.html",
        {
            "followup": followup,
            "card": _followup_card(followup),
            "issue": issue,
            "is_recipient": str(request.user.id) == str(followup.program_lead_user_id)
            and followup.is_open,
            "can_ask": bool(issue and issue.team_action and followup.cceo_staff_id),
            "affected_count": followup.affected_count,
            "flash": message,
            "flash_ok": ok,
        },
    )


# ── Export ───────────────────────────────────────────────────────────────────
@require_page_permission("country_planning_oversight")
@require_export_permission
def coverage_export_view(request):
    """The page as a workbook: the hierarchy, one row per school, and the
    follow-ups — the same filters, the same figures, each sheet naming its
    row grain. ``?format=csv`` answers with the school sheet."""
    from apps.core.excel import table_download

    filters = svc.read_filters(request)
    snapshot = svc.snapshot_for(request.user, filters)
    counts = fu.open_counts(filters.fy)
    sheets = [_school_sheet(request, filters)] if _may_see_schools(request.user) else []
    sheets.append(_hierarchy_sheet(snapshot, counts))
    sheets.append(_followup_sheet(filters.fy))
    stamp = timezone.localdate().isoformat()
    return table_download(
        request, f"country-planning-oversight-{filters.fy}-{stamp}", sheets
    )


HIERARCHY_HEADERS = [
    "Level",
    "Country",
    "Programme Lead",
    "Person",
    "Partner",
    "Visit target",
    "Visits planned",
    "Follow up",
    "In-school Training",
    "SSA Support",
    "Donor, story and social visits (not counted)",
    "Trainings planned",
    "Cluster trainings planned",
    "Cluster meetings planned",
    "Schools assigned to Partners",
    "Partner work assigned",
    "Partner planned (dated by the Partner)",
    "Schools held",
    "Core",
    "Client",
    "Core Trained",
    "Core Graduate",
    "Champion",
    "Visits the schools held allow",
    "Short of target by",
    "Visit slots needed",
    "Visit slots planned by staff",
    "Visit slots planned by Partners",
    "Schools with a visit planned",
    "Schools not yet planned",
    "Schools in a Partner's hands",
    "Schools planned twice",
    "Training slots needed",
    "Training slots planned",
    "Schools with no training planned",
    "Clustered schools",
    "Unclustered schools",
    "Schools covered by a planned meeting",
    "Verified staff visits",
    "Verified Partner visits",
    "Open follow-ups",
]


def _figures(tally) -> list:
    return [
        tally.target,
        tally.p_visits,
        tally.p_follow_up,
        tally.p_in_school,
        tally.p_ssa,
        tally.p_outreach,
        tally.p_trainings,
        tally.p_cluster_trainings,
        tally.p_meetings,
        tally.pa_schools,
        tally.pa_work,
        tally.pp_work,
        tally.schools,
        tally.core_schools,
        tally.client_schools,
        tally.core_trained_schools,
        tally.core_graduate_schools,
        tally.champion_schools,
        tally.reach,
        tally.shortfall,
        tally.visit_slots,
        tally.staff,
        tally.partner_scheduled,
        tally.any_visit,
        tally.no_visit,
        tally.with_partner,
        tally.duplicates,
        tally.training_slots,
        tally.training,
        tally.no_training,
        tally.clustered,
        tally.unclustered,
        tally.meeting_covered,
        tally.staff_verified,
        tally.partner_verified,
    ]


def _hierarchy_sheet(snapshot, counts) -> dict:
    country = snapshot.scope_label or "Country"
    rows = [
        [
            "Country",
            country,
            "",
            "",
            "",
            *_figures(snapshot.tree.country),
            counts.get(("country", ""), 0),
        ]
    ]
    for lead in snapshot.tree.leads:
        rows.append(
            [
                "Programme Lead",
                country,
                lead.name,
                "",
                "",
                *_figures(lead.tally),
                counts.get(("lead", lead.key), 0),
            ]
        )
        for owner in lead.owners:
            rows.append(
                [
                    {
                        "cceo": "CCEO",
                        "pl_personal": "Programme Lead (own plan)",
                        "unassigned": "Nobody",
                    }.get(owner.kind, "Other staff"),
                    country,
                    lead.name,
                    owner.name,
                    "",
                    *_figures(owner.tally),
                    counts.get(("owner", owner.key), 0),
                ]
            )
            for pid, tally in owner.assigned.items():
                rows.append(
                    [
                        "Partner",
                        country,
                        lead.name,
                        owner.name,
                        snapshot.partner_names.get(pid, "Unrecorded Partner"),
                        *_figures(tally),
                        "",
                    ]
                )
    return {
        "title": "People (one row per level)",
        "headers": HIERARCHY_HEADERS,
        "rows": rows,
    }


SCHOOL_HEADERS = [
    "Country",
    "Programme Lead",
    "CCEO / holder",
    "Partner(s)",
    "School ID",
    "School",
    "School type",
    "Required visit slots",
    "Staff slots expected",
    "Staff planned slots",
    "Partner slots expected",
    "Partner assigned slots",
    "Partner scheduled slots",
    "Remaining visit slots",
    "Required training slots",
    "Planned training slots",
    "Cluster status",
    "Cluster-meeting planning",
    "Planning status",
    "In a Partner's hands",
    "Planned twice",
    "Open follow-up",
]


def _school_sheet(request, filters) -> dict:
    from apps.planning.country_oversight.coverage import claims_for, duplicate_reasons
    from apps.planning.country_oversight.hierarchy import (
        IDX,
        planning_state,
        school_values,
    )
    from apps.planning.followup_models import (
        OPEN_FOLLOW_UP_STATES,
        PlanningOversightFollowUp,
    )

    dataset = svc.dataset_for(request.user, filters.window)
    followed = set(
        PlanningOversightFollowUp.objects.filter(
            fy=filters.fy, status__in=OPEN_FOLLOW_UP_STATES, school_id__isnull=False
        ).values_list("school_id", flat=True)
    )
    country = dataset.scope_label or "Country"
    rows = []
    for school in sorted(
        dataset.facts.values(), key=lambda s: (s.name.casefold(), s.id)
    ):
        if not school.is_governed:
            continue
        owner = dataset.owners.get(school.owner_key)
        if not svc._keeps(school, owner, filters):
            continue
        claims = claims_for(
            school,
            dataset.allocations.get(school.id),
            dataset.window,
            channel=filters.channel or None,
            only_partner=filters.partner or None,
        )
        if not svc._status_matches(claims, filters):
            continue
        values = school_values(school, claims)
        partners = ", ".join(
            sorted(
                dataset.partner_names.get(pid, "Unrecorded Partner")
                for pid in (school.partners or {})
            )
        )
        rows.append(
            [
                country,
                owner.lead_name if owner else "No Programme Lead",
                owner.name if owner else "No account owner",
                partners,
                school.code,
                school.name,
                svc.rules.type_label(school.school_type),
                claims.visit_slots,
                claims.staff_expected,
                claims.cum_staff,
                claims.partner_expected,
                claims.cum_partner_assigned,
                claims.cum_partner_scheduled,
                values[IDX["unallocated"]],
                claims.training_slots,
                claims.cum_training,
                "Clustered" if school.clustered else "Unclustered",
                "Meeting planned"
                if claims.cum_meeting_covered
                else "No meeting planned",
                {
                    "full": "Fully planned",
                    "partial": "Partially planned",
                    "none": "Not planned",
                    "outside": "Outreach only",
                }[planning_state(claims)],
                "Yes" if school.with_partner else "",
                "; ".join(
                    svc.rules.DUPLICATE_LABELS[reason]
                    for reason in duplicate_reasons(school)
                ),
                "Yes" if school.id in followed else "",
            ]
        )
    return {
        "title": "Schools (one row per school)",
        "headers": SCHOOL_HEADERS,
        "rows": rows,
    }


def _followup_sheet(fy: str) -> dict:
    from apps.planning.followup_models import PlanningOversightFollowUp

    rows = []
    for row in PlanningOversightFollowUp.objects.filter(fy=fy).order_by("-assigned_at"):
        issue = fu.issue_of(row.issue_type)
        rows.append(
            [
                row.assigned_at.date().isoformat(),
                row.program_lead_name,
                row.cceo_name,
                row.school_name,
                issue.label if issue else row.issue_type,
                row.period_label,
                row.required_value,
                row.planned_value,
                row.remaining_value,
                row.live_remaining if row.live_remaining is not None else "",
                row.get_priority_display(),
                row.due_date.isoformat(),
                row.get_status_display(),
                row.reminder_count,
                row.instruction,
            ]
        )
    return {
        "title": "Follow-ups (one row each)",
        "headers": [
            "Sent",
            "Programme Lead",
            "CCEO",
            "School",
            "Issue",
            "Period",
            "Required",
            "Planned",
            "Remaining when sent",
            "Remaining now",
            "Priority",
            "Due",
            "Status",
            "Reminders",
            "Instruction",
        ],
        "rows": rows,
    }
