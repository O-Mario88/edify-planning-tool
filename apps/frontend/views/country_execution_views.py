"""Country Execution & Completion Oversight — the second Country Oversight tab.

Everything here renders what apps.planning.country_execution computed: the
views choose which part of one fold to show and never add, divide or restate a
rule. The only write is the Country Director's "Follow Up with PL" for an
execution gap, on the governed follow-up record; it changes no activity, plan,
target or achievement, and it reaches the Programme Lead, never the CCEO.
"""

from __future__ import annotations

from datetime import date, datetime
from urllib.parse import urlencode

from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.core.permissions import (
    RolePermissionService,
    require_export_permission,
    require_page_permission,
)
from apps.planning.country_execution import followups as efu
from apps.planning.country_execution import service as esvc
from apps.planning.country_execution import snapshots
from apps.planning.country_execution import stages as st
from apps.planning.country_oversight import followups as fu
from apps.planning.country_oversight import freshness
from apps.planning.country_oversight.coverage import fy_label
from apps.planning.country_oversight.requirements import NO_LEAD_KEY, NO_OWNER_KEY

BASE = "/country-planning-oversight/execution"
TABLES = dict(esvc.VIEW_BY)


def _may_see_schools(user) -> bool:
    from apps.frontend.views.country_oversight_views import _may_see_schools as may

    return may(user)


def _table(request) -> str:
    table = (request.GET.get("table") or request.POST.get("table") or "lead").strip()
    return table if table in TABLES else "lead"


def _options(snapshot) -> dict:
    from apps.core.fy import fy_options

    dataset = snapshot.dataset
    types = sorted(
        {r.activity_type for r in dataset.records},
        key=lambda key: dataset.type_labels.get(key, key).casefold(),
    )
    return {
        "periods": [(key, label) for key, label in esvc.PERIOD_LABELS.items()],
        "quarters": (
            ("Q1", "Q1 · Oct–Dec"),
            ("Q2", "Q2 · Jan–Mar"),
            ("Q3", "Q3 · Apr–Jun"),
            ("Q4", "Q4 · Jul–Sep"),
        ),
        "months": [
            (m, date(2000, m, 1).strftime("%B"))
            for m in (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9)
        ],
        "fy_options": [{"value": fy, "label": fy_label(fy)} for fy in fy_options()],
        "view_by": esvc.VIEW_BY,
        "view_tabs": (
            ("lead", "Program Leads"),
            ("cceo", "CCEOs"),
            ("partner", "Partners"),
            ("school", "Schools"),
            ("activity", "Activities"),
        ),
        "channels": esvc.CHANNELS,
        "types": [
            (key, dataset.type_labels.get(key, key.replace("_", " ").title()))
            for key in types
        ],
        "regions": sorted(dataset.region_names.items(), key=lambda pair: pair[1]),
    }


def _table_context(request, snapshot, filters, table: str, reminders: dict) -> dict:
    page = _page(request)
    if table == "cceo":
        return {"owner_list": esvc.owner_rows(snapshot, None, reminders)}
    if table == "partner":
        return {"partner_list": esvc.partner_rows(snapshot)}
    if table == "school":
        return {
            "schools": esvc.school_completion_rows(request.user, filters, page=page)
            if _may_see_schools(request.user)
            else {"rows": [], "total": 0, "page": 1, "pages": 1}
        }
    if table == "activity":
        return {
            "activities": esvc.activity_rows(
                snapshot, stage=(request.GET.get("stage") or "due").strip(), page=page
            )
            if _may_see_schools(request.user)
            else {"rows": [], "total": 0, "page": 1, "pages": 1}
        }
    return {}


def _page(request) -> int:
    try:
        return max(1, int(request.GET.get("page") or 1))
    except ValueError:
        return 1


def _context(request, snapshot, filters) -> dict:
    from apps.frontend.views.country_oversight_views import _followups_panel
    from apps.frontend.views.oversight_views import country_lens_tabs

    reminders = efu.open_counts(filters.fy)
    header = esvc.header(snapshot)
    table = _table(request)
    window = snapshot.window
    today = snapshot.dataset.today
    context = {
        "filters": filters,
        "query": filters.query(),
        "planning_query": filters.planning().query(),
        "header": header,
        "window": window,
        "kpis": esvc.kpis(snapshot),
        "charts": esvc.charts(snapshot),
        # Delivery by Programme Lead and by school type, read against the
        # same target and requirement the planning tab reads the plan against.
        "lead_charts": esvc.lead_charts(snapshot),
        "type_rows": esvc.type_rows(snapshot),
        "visits_table_url": esvc.records_url("visits", filters.query()),
        "table": table,
        "table_label": TABLES[table],
        "lead_rows": esvc.lead_rows(snapshot, reminders),
        "country_cells": esvc.row_cells(
            snapshot.tree.country,
            remaining=snapshot.remaining.get(("country", "")),
            reminders=reminders.get(("country", ""), 0),
            window=window,
            today=today,
        ),
        "issues": esvc.issues(snapshot),
        "recent": esvc.recent_activity(snapshot),
        "followups": _followups_panel(filters.fy, module="execution"),
        "may_follow_up": fu.may_follow_up(request.user),
        "may_see_schools": _may_see_schools(request.user),
        "may_export": RolePermissionService.can_export(request.user, f"{BASE}/export"),
        "lens_tabs": country_lens_tabs("execution"),
        "active_oversight_view": "execution",
        "options": _options(snapshot),
        "no_lead_key": NO_LEAD_KEY,
        # The period's locked figures, when it has ended and been locked
        # (spec §22): the original first, then any revisions.
        "locked": snapshots.for_window(header["country"], window),
        # Planned output, validated actual and the gap, from the canonical
        # target ledger (spec §23); performance is not recalculated here.
        "targets": esvc.target_position(snapshot.dataset, filters),
    }
    context.update(_table_context(request, snapshot, filters, table, reminders))
    return context


def execution_page(request):
    """The Execution & Completion tab (routed from the Country Oversight page)."""
    filters = esvc.read_filters(request)
    refresh = request.GET.get("refresh") == "1" and not freshness.live_read(request)
    snapshot = esvc.snapshot_for(request.user, filters, refresh=refresh)
    context = _context(request, snapshot, filters)
    context["settle_seconds"] = freshness.settles_in(snapshot.dataset.built_at)
    if request.headers.get("HX-Request") == "true":
        if (request.headers.get("HX-Target") or "") == "cxo-workspace":
            return render(request, "partials/country_execution/workspace.html", context)
        return render(request, "partials/country_execution/page.html", context)
    return render(request, "pages/oversight/country_planning.html", context)


@require_page_permission("country_planning_oversight")
def table_view(request):
    """One of the table's five views, swapped in place."""
    filters = esvc.read_filters(request)
    snapshot = esvc.snapshot_for(request.user, filters)
    return render(
        request,
        "partials/country_execution/_table.html",
        _context(request, snapshot, filters),
    )


@require_page_permission("country_planning_oversight")
def rows_view(request):
    """A Lead's people, or an officer's delivery channels, as table rows."""
    filters = esvc.read_filters(request)
    snapshot = esvc.snapshot_for(request.user, filters)
    reminders = efu.open_counts(filters.fy)
    level = (request.GET.get("level") or "").strip()
    key = (request.GET.get("key") or "").strip()
    context = {
        "filters": filters,
        "query": filters.query(),
        "may_follow_up": fu.may_follow_up(request.user),
        "parent": key,
        "no_lead_key": NO_LEAD_KEY,
    }
    if level == "lead":
        if esvc.find_lead(snapshot, key) is None:
            raise Http404
        context["rows"] = esvc.owner_rows(snapshot, key, reminders)
        return render(request, "partials/country_execution/rows_owners.html", context)
    if level == "owner":
        if esvc.find_owner(snapshot, key) is None:
            raise Http404
        context["rows"] = esvc.owner_partner_rows(snapshot, key)
        return render(request, "partials/country_execution/rows_partners.html", context)
    raise Http404


#: What each drill-down is called.
_STAGE_TITLES = {
    "due": "Activities planned",
    "started": "Activities started",
    "not_started": "Activities not started",
    "executed": "Execution completed",
    "pl_review": "Waiting on PL review",
    "ia_review": "Waiting on IA verification",
    "verified": "Verified activities",
    "closed": "Fully closed activities",
    "returned": "Returned for correction",
    "overdue": "Overdue activities",
    "finance": "Verified, closure open",
    "cancelled": "Cancelled activities",
}


@require_page_permission("country_planning_oversight")
def drawer_view(request):
    """The records behind a figure: KPI cards, backlog slices, age bars, row
    "View" buttons and the shortcuts all open this, filtered to what they
    counted."""
    from urllib.parse import urlencode

    filters = esvc.read_filters(request)
    kind = (request.GET.get("kind") or "activities").strip()
    if kind != "activities":
        raise Http404
    snapshot = esvc.snapshot_for(request.user, filters)
    stage = (request.GET.get("stage") or "").strip()
    owner_key = (request.GET.get("owner") or "").strip()
    lead_key = (request.GET.get("lead") or "").strip()
    partner_key = (request.GET.get("partner_key") or "").strip()
    blocker = (request.GET.get("blocker") or "").strip()
    age = (request.GET.get("age") or "").strip()
    listing = esvc.activity_rows(
        snapshot,
        stage=stage,
        owner_key=owner_key,
        lead_key=lead_key,
        partner_key=partner_key,
        blocker=blocker,
        age=age,
        page=_page(request),
    )
    owners = snapshot.dataset.owners
    who = []
    if lead_key:
        lead = esvc.find_lead(snapshot, lead_key)
        who.append(lead.name if lead else "")
    if owner_key:
        info = owners.get(owner_key)
        who.append(info.name if info else "Unassigned work")
    if partner_key:
        who.append(
            "Staff delivery"
            if partner_key == "__staff__"
            else snapshot.dataset.partner_names.get(partner_key, "Partner")
        )
    if blocker:
        who.append("Waiting on " + st.OWNER_LABELS.get(blocker, blocker))
    title = _STAGE_TITLES.get(stage, "Activities")
    list_params = {
        key: value
        for key, value in {
            **filters.params(),
            "kind": "activities",
            "stage": stage,
            "owner": owner_key,
            "lead": lead_key,
            "partner_key": partner_key,
            "blocker": blocker,
            "age": age,
        }.items()
        if value
    }
    follow_up_lead = lead_key
    follow_up_cceo = ""
    if owner_key and owner_key != NO_OWNER_KEY:
        info = owners.get(owner_key)
        follow_up_lead = info.lead_key if info else ""
        follow_up_cceo = owner_key if info and info.kind != "pl_personal" else ""
    follow_up_query = ""
    if follow_up_lead and follow_up_lead != NO_LEAD_KEY:
        follow_up_query = urlencode(
            {
                **filters.params(),
                "lead": follow_up_lead,
                "cceo": follow_up_cceo,
                "partner_key": partner_key if partner_key != "__staff__" else "",
            }
        )
    return render(
        request,
        "partials/country_execution/drawer_activities.html",
        {
            "filters": filters,
            "query": filters.query(),
            "list_query": urlencode(list_params),
            "listing": listing,
            "title": title,
            "subtitle": " · ".join(
                part for part in [*who, snapshot.window.label] if part
            )
            + f" · {listing['total']:,} {'activity' if listing['total'] == 1 else 'activities'}",
            "may_follow_up": fu.may_follow_up(request.user),
            "may_see_schools": _may_see_schools(request.user),
            "follow_up_query": follow_up_query,
            "drawer_size": "xl",
        },
    )


# ── The consolidated tables behind the cards ─────────────────────────────────
def _records_tabs(active: str, query: str) -> list[dict]:
    from apps.planning.country_execution import tables

    return [
        {
            "key": key,
            "label": tables.SPECS[key].title,
            "short": tables.SPECS[key].short,
            "href": tables.table_url(key, query),
            "is_active": key == active,
        }
        for key in tables.TAB_ORDER
    ]


@require_page_permission("country_planning_oversight")
def records_view(request, key: str):
    """One consolidated table: every record a card counts, a page at a time,
    as an ordinary table that opens with where the school sits (owner,
    2026-10-02, as the planning cards open theirs)."""
    from apps.planning.country_execution import tables
    from apps.planning.country_oversight import tables as planning_tables

    if key not in tables.SPECS:
        raise Http404
    filters = esvc.read_filters(request)
    query = filters.query()
    snapshot = esvc.snapshot_for(request.user, filters)
    window = snapshot.window
    export_path = f"{BASE}/records-export/{key}"
    context = {
        "spec": tables.SPECS[key],
        "filters": filters,
        "query": query,
        "window": window,
        "fy_label": fy_label(filters.fy),
        "lens_tabs": _records_tabs(key, query),
        "leads": [
            {"key": lead.key, "name": lead.name} for lead in snapshot.dataset.leads
        ],
        "channels": esvc.CHANNELS,
        "carried": [
            (name, value)
            for name, value in filters.params().items()
            if name not in ("program_lead", "channel")
        ],
        "may_export": RolePermissionService.can_export(request.user, export_path),
        "export_path": export_path,
        "records_path": f"{BASE}/records/{key}",
        "withheld": not _may_see_schools(request.user),
        "withheld_message": (
            "Activity-level rows are not part of this role's reading of the "
            "country. The figures on Execution & Completion are."
        ),
    }
    if not context["withheld"]:
        table = tables.build(request.user, snapshot, key)
        context.update(
            {"table": table, **planning_tables.page_of(table, _page(request))}
        )
    return render(request, "pages/oversight/country_execution_table.html", context)


@require_page_permission("country_planning_oversight")
@require_export_permission
def records_export_view(request, key: str):
    """A consolidated table as a workbook: every row, every column."""
    from apps.core.excel import table_download
    from apps.planning.country_execution import tables
    from apps.planning.country_oversight import tables as planning_tables

    if key not in tables.SPECS or not _may_see_schools(request.user):
        raise Http404
    filters = esvc.read_filters(request)
    snapshot = esvc.snapshot_for(request.user, filters)
    table = tables.build(request.user, snapshot, key)
    stamp = timezone.localdate().isoformat()
    return table_download(
        request,
        f"country-execution-{key}-{filters.fy}-{stamp}",
        [planning_tables.sheet(table)],
    )


# ── Locked period snapshots (spec §22) ───────────────────────────────────────
SNAPSHOT_PAGE_SIZE = 50


def _paged(items, page: int, size: int = SNAPSHOT_PAGE_SIZE) -> dict:
    items = list(items or [])
    pages = max(1, (len(items) + size - 1) // size)
    page = min(max(1, page), pages)
    return {
        "rows": items[(page - 1) * size : page * size],
        "page": page,
        "pages": pages,
        "total": len(items),
    }


def _country(request) -> str:
    from apps.core.scoping import resolve_user_scope
    from apps.planning.country_oversight.service import deployment_country

    scope = resolve_user_scope(request.user)
    return (getattr(scope, "country", "") or "").strip() or deployment_country()


@require_page_permission("country_planning_oversight")
def snapshots_view(request):
    """The country's locked periods, the latest first."""
    period_type = (request.GET.get("type") or "").strip()
    if period_type not in snapshots.PERIOD_TYPES:
        period_type = ""
    country = _country(request)
    return render(
        request,
        "partials/country_execution/drawer_snapshots.html",
        {
            "periods": _paged(
                snapshots.listing(country, period_type=period_type), _page(request)
            ),
            "list_query": urlencode({"type": period_type}) if period_type else "",
            "period_type": period_type,
            "types": [
                (key, snapshots.PERIOD_NAMES[key]) for key in snapshots.PERIOD_TYPES
            ],
            "country": country,
            "grace_days": snapshots.GRACE_DAYS,
            "drawer_size": "xl",
        },
    )


@require_page_permission("country_planning_oversight")
def snapshot_view(request, snapshot_id: str):
    """One locked period: its figures, staff and Partner contribution, the
    hierarchy and the follow-ups open at the close, every version beside it.
    POST records a revision, where policy permits (snapshots.REVISION_ROLES)."""
    from apps.planning.execution_snapshot_models import ExecutionPeriodSnapshot

    snapshot = ExecutionPeriodSnapshot.objects.filter(
        id=snapshot_id, country=_country(request)
    ).first()
    if snapshot is None:
        raise Http404
    flash, ok = "", True
    if request.method == "POST":
        if not snapshots.may_revise(request.user):
            return HttpResponse(
                "Revising a locked period needs an approved policy role.", status=403
            )
        try:
            snapshot = snapshots.revise(
                snapshot, request.user, request.POST.get("reason") or ""
            )
            flash = f"Recorded revision {snapshot.version - 1}. The original stays beside it."
        except snapshots.SnapshotError as exc:
            flash, ok = str(exc), False
    elif request.method != "GET":
        return HttpResponse(status=405)
    versions = snapshots.for_window(snapshot.country, snapshots.window_of(snapshot))
    try:
        fu_page = max(1, int(request.GET.get("fu_page") or 1))
    except ValueError:
        fu_page = 1
    hierarchy = _paged(
        snapshot.hierarchy, _page(request) if request.method == "GET" else 1
    )
    follow_ups = _paged(snapshot.follow_ups, fu_page if request.method == "GET" else 1)
    return render(
        request,
        "partials/country_execution/drawer_snapshot.html",
        {
            "snapshot": snapshot,
            "f": snapshot.figures,
            "versions": versions,
            "hierarchy": hierarchy,
            "follow_ups": follow_ups,
            "hierarchy_query": urlencode({"fu_page": follow_ups["page"]}),
            "follow_ups_query": urlencode({"page": hierarchy["page"]}),
            "may_revise": snapshots.may_revise(request.user),
            "flash": flash,
            "flash_ok": ok,
            "owner_labels": st.OWNER_LABELS,
            "drawer_size": "xl",
        },
    )


# ── Follow Up with PL (execution) ────────────────────────────────────────────
def _scope(request, filters) -> efu.ExecScope:
    from apps.core.scoping import resolve_user_scope

    source = request.POST if request.method == "POST" else request.GET
    window = filters.window
    scope = resolve_user_scope(request.user)
    return efu.ExecScope(
        fy=filters.fy,
        period_type=window.period,
        period_start=window.start,
        period_end=window.end,
        lead_key=(source.get("lead") or "").strip(),
        cceo_key=(source.get("cceo") or source.get("owner") or "").strip(),
        partner_key=(source.get("partner_key") or "").strip(),
        activity_id=(source.get("activity") or "").strip(),
        country=getattr(scope, "country", "") or "",
    )


@require_page_permission("country_planning_oversight")
def follow_up_view(request):
    """GET: the execution Follow Up with PL drawer, prefilled with the live
    figures. POST: send, or remind on the open follow-up."""
    if not fu.may_follow_up(request.user):
        return HttpResponse(
            "Following up with a Programme Lead belongs to the Country Director.",
            status=403,
        )
    filters = esvc.read_filters(request)
    scope = _scope(request, filters)
    if scope.cceo_key and not scope.lead_key:
        snapshot = esvc.snapshot_for(request.user, filters)
        owner = esvc.find_owner(snapshot, scope.cceo_key)
        scope.lead_key = owner.lead_key if owner else ""
    if request.method == "POST":
        return _send(request, filters, scope)

    leads = []
    issue_rows = []
    lead_name = cceo_name = partner_name = ""
    error = ""
    try:
        snapshot = esvc.snapshot_for(request.user, filters)
        leads = [
            {"key": lead.key, "name": lead.name}
            for lead in snapshot.tree.leads
            if not lead.is_no_lead
        ]
        if scope.lead_key:
            figures = efu.evaluate(scope)
            dataset = figures["dataset"]
            lead = next(
                (lead for lead in dataset.leads if lead.key == scope.lead_key), None
            )
            lead_name = lead.name if lead else ""
            owner = dataset.owners.get(scope.cceo_key) if scope.cceo_key else None
            cceo_name = owner.name if owner else ""
            partner_name = (
                dataset.partner_names.get(scope.partner_key, "")
                if scope.partner_key
                else ""
            )
            for issue in efu.EXEC_ISSUES.values():
                if issue.key == "exec_other":
                    continue
                issue_rows.append(
                    {
                        "key": issue.key,
                        "label": issue.label,
                        "open": efu.metric(issue, scope, figures),
                        "manual": issue.resolution_rule == "manual",
                    }
                )
    except Exception:  # noqa: BLE001 - the drawer still opens with an explanation
        import logging

        logging.getLogger(__name__).exception(
            "Execution follow-up drawer could not read the figures"
        )
        error = "The figures could not be read just now. Refresh and try again."
    issue_key = (request.GET.get("issue") or "").strip()
    if not issue_key and issue_rows:
        issue_key = max(issue_rows, key=lambda row: row["open"])["key"]
    return render(
        request,
        "partials/country_execution/drawer_follow_up.html",
        {
            "filters": filters,
            "query": filters.query(),
            "scope": scope,
            "leads": leads,
            "issue_key": issue_key or "exec_team_gap",
            "issues": issue_rows,
            "all_issues": list(efu.EXEC_ISSUES.values()),
            "lead_name": lead_name,
            "cceo_name": cceo_name,
            "partner_name": partner_name,
            "existing": _scoped(filters.fy, scope),
            "priorities": fu.PRIORITY_CHOICES,
            "default_due": fu.default_due_date(),
            "window": filters.window,
            "error": error,
            "drawer_size": "lg",
        },
    )


def _scoped(fy: str, scope: efu.ExecScope) -> list[dict]:
    from apps.frontend.views.country_oversight_views import _followup_card
    from apps.planning.followup_models import (
        OPEN_FOLLOW_UP_STATES,
        PlanningOversightFollowUp,
    )

    if not scope.lead_key:
        return []
    rows = PlanningOversightFollowUp.objects.filter(
        fy=fy,
        module="execution",
        status__in=OPEN_FOLLOW_UP_STATES,
        program_lead_staff_id=scope.lead_key,
    )
    if scope.cceo_key:
        rows = rows.filter(cceo_staff_id=scope.cceo_key)
    return [_followup_card(row) for row in rows.order_by("-assigned_at")[:10]]


def _send(request, filters, scope):
    raw_due = (request.POST.get("due_date") or "").strip()
    try:
        due = datetime.strptime(raw_due, "%Y-%m-%d").date() if raw_due else None
    except ValueError:
        due = None
    try:
        followup, created = efu.send_follow_up(
            sender=request.user,
            scope=scope,
            issue_key=(request.POST.get("issue") or "").strip(),
            instruction=request.POST.get("instruction") or "",
            due_date=due,
            priority=(request.POST.get("priority") or "").strip(),
        )
    except efu.FollowUpError as exc:
        return render(
            request,
            "partials/country_oversight/follow_up_result.html",
            {"ok": False, "message": str(exc)},
        )
    message = (
        f"Sent to {followup.program_lead_name}. It is on their To-Do."
        if created
        else f"Reminder {followup.reminder_count} sent to {followup.program_lead_name} on the open follow-up."
    )
    response = render(
        request,
        "partials/country_oversight/follow_up_result.html",
        {"ok": True, "message": message},
    )
    response["HX-Trigger"] = "cpo-followups-changed"
    return response


@require_page_permission("country_planning_oversight")
def followups_panel_view(request):
    from apps.frontend.views.country_oversight_views import _followups_panel

    filters = esvc.read_filters(request)
    return render(
        request,
        "partials/country_execution/followups_panel.html",
        {
            "filters": filters,
            "query": filters.query(),
            "planning_query": filters.planning().query(),
            "followups": _followups_panel(filters.fy, module="execution"),
            "may_follow_up": fu.may_follow_up(request.user),
        },
    )


# ── Export ───────────────────────────────────────────────────────────────────
@require_page_permission("country_planning_oversight")
@require_export_permission
def export_view(request):
    """The tab as a workbook: one row per level, per Partner, per activity and
    per follow-up — the same filters and figures, each sheet naming its grain."""
    from apps.core.excel import table_download
    from apps.planning.followup_models import PlanningOversightFollowUp

    filters = esvc.read_filters(request)
    snapshot = esvc.snapshot_for(request.user, filters)
    reminders = efu.open_counts(filters.fy)
    window, today = snapshot.window, snapshot.dataset.today
    country = snapshot.dataset.scope_label or "Country"
    columns = [label for _, label in esvc.TABLE_COLUMNS]

    def figures(cells) -> list:
        return [
            cells["due"],
            cells["started"],
            cells["executed"],
            cells["verified"],
            cells["closed"],
            "" if cells["on_time"] is None else f"{cells['on_time']}%",
            cells["overdue"],
            cells["carried_forward"],
            cells["returned"],
            "" if cells["remaining"] is None else cells["remaining"],
            cells["forecast"]["label"],
            cells["reminders"],
        ]

    hierarchy = [
        [
            "Country",
            country,
            "",
            *figures(
                esvc.row_cells(
                    snapshot.tree.country,
                    remaining=snapshot.remaining.get(("country", "")),
                    reminders=reminders.get(("country", ""), 0),
                    window=window,
                    today=today,
                )
            ),
        ]
    ]
    for row in esvc.lead_rows(snapshot, reminders):
        hierarchy.append(["Programme Lead", row["name"], "", *figures(row["cells"])])
        for owner in esvc.owner_rows(snapshot, row["key"], reminders):
            hierarchy.append(
                [
                    "PL personal" if owner["kind"] == "pl_personal" else "CCEO",
                    owner["person"],
                    row["name"],
                    *figures(owner["cells"]),
                ]
            )
    sheets = [
        {
            "title": "Hierarchy (one row per level)",
            "headers": ["Level", "Name", "Programme Lead", *columns],
            "rows": hierarchy,
        },
        {
            "title": "Partners (one row each)",
            "headers": [
                "Partner",
                "Scheduled",
                "Started",
                "Evidence submitted",
                "Returned by IA",
                "IA verified",
                "Awaiting payment",
                "Paid",
                "Assigned, unscheduled",
                "Overdue",
                "Schools served",
            ],
            "rows": [
                [
                    p["name"],
                    p["due"],
                    p["started"],
                    p["executed"],
                    p["returned"],
                    p["verified"],
                    p["awaiting_payment"],
                    p["paid"],
                    p["unscheduled"],
                    p["overdue"],
                    p["schools"],
                ]
                for p in esvc.partner_rows(snapshot)
            ],
        },
    ]
    if _may_see_schools(request.user):
        records = list(esvc.filtered_records(snapshot.dataset, filters))
        described = esvc._describe(snapshot.dataset, records)
        sheets.append(
            {
                "title": "Activities (one row each)",
                "headers": [
                    "Activity",
                    "School ID",
                    "School / cluster",
                    "Owner",
                    "Programme Lead",
                    "Channel",
                    "Partner",
                    "Due",
                    "Stage",
                    "Overdue stage",
                    "Days overdue",
                    "Waiting on",
                    "Last action",
                ],
                "rows": [
                    [
                        r["type"],
                        r["code"],
                        r["where"],
                        r["owner"],
                        r["lead"],
                        r["channel"],
                        r["partner"],
                        r["due"],
                        r["stage"],
                        r["overdue"],
                        r["age"],
                        r["waiting_on"],
                        r["last_action"],
                    ]
                    for r in described
                ],
            }
        )
    sheets.append(
        {
            "title": "Follow-ups (one row each)",
            "headers": [
                "Sent",
                "Programme Lead",
                "CCEO",
                "Partner",
                "Issue",
                "Status",
                "Open when sent",
                "Open now",
                "Due",
                "Priority",
            ],
            "rows": [
                [
                    timezone.localtime(f.assigned_at).date(),
                    f.program_lead_name,
                    f.cceo_name,
                    f.partner_name,
                    getattr(efu.issue_of(f.issue_type), "label", f.issue_type),
                    f.get_status_display(),
                    f.remaining_value,
                    f.live_remaining if f.live_remaining is not None else "",
                    f.due_date,
                    f.get_priority_display(),
                ]
                for f in PlanningOversightFollowUp.objects.filter(
                    fy=filters.fy, module="execution"
                ).order_by("-assigned_at")
            ],
        }
    )
    stamp = timezone.localdate().isoformat()
    return table_download(request, f"country-execution-{filters.fy}-{stamp}", sheets)
