"""Planning oversight pages — the PL's team lens and the CD's country lens.

Both are read surfaces over `apps.planning.oversight_service`. Neither creates
planning records, and neither exposes a mutation control for work it does not
own: a Program Lead supervises a CCEO's activity but never edits it, and a
Country Director reviews the country plan but never schedules routine field
work. The only write either page offers is a corrective action, and that goes
through the canonical TeamAction workflow rather than touching the activity.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.shortcuts import redirect, render
from django.utils.html import escape
from django.views.decorators.http import require_POST

from apps.core.fy import fy_options, get_operational_fy
from apps.core.rbac import Permission
from apps.core.metrics import DataState, MetricValue, render_kpi_item
from apps.core.permissions import (
    RolePermissionService,
    has_permission,
    require_any_page_permission,
    require_export_permission,
    require_page_permission,
)
from apps.planning.flagged_schools import team_flagged_schools
from apps.planning import oversight_actions
from apps.planning import oversight_service as oversight
from apps.planning.action_service import ActionError


# Where a no-JavaScript send returns to when the Referer cannot be trusted.
# Each page falls back to itself: bouncing a Country Director to the Program
# Lead's page would be a scope change dressed up as a redirect.
TEAM_OVERSIGHT_PATH = "/team-planning-oversight/"
COUNTRY_OVERSIGHT_PATH = "/country-planning-oversight/"
PLANNING_MONITOR_PATH = "/planning-monitor/"
COUNTRY_MAP_PATH = "/country-map/"
PARTNER_OVERSIGHT_PATH = "/partner-oversight/"


def may_delegate(user, *, country: bool, region: bool = False) -> bool:
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
    # A Programme Lead asks their CCEOs; a Country Director asks their
    # Programme Leads; a Regional Programme Lead asks the Programme Leads of
    # their region, which is the whole of their job (owner, 2026-09-12:
    # "follow up with the program leads").
    if region:
        allowed = {EdifyRole.REGIONAL_PROGRAM_LEAD.value}
    elif country:
        allowed = {EdifyRole.COUNTRY_DIRECTOR.value}
    else:
        allowed = {EdifyRole.COUNTRY_PROGRAM_LEAD.value}
    return role in allowed | {EdifyRole.ADMIN.value}


def _kpi_items(summary, *, country: bool, region: bool = False) -> list[dict]:
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
            "oversight_region_activities_planned"
            if region
            else (
                "oversight_country_activities_planned"
                if country
                else "oversight_team_activities_planned"
            ),
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
            "oversight_region_activities_at_risk"
            if region
            else (
                "oversight_country_activities_at_risk"
                if country
                else "oversight_team_work_needing_attention"
            ),
            MetricValue.measured(summary["at_risk"]),
            helper=f"{summary['cost_missing']} scheduled without a cost",
            tone="danger" if summary["at_risk"] else "neutral",
            icon="warning",
        ),
        render_kpi_item(
            "oversight_region_planned_budget"
            if region
            else (
                "oversight_country_planned_budget"
                if country
                else "oversight_team_planned_budget"
            ),
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
    """One explicit oversight period, shared by every page and export."""
    fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
    raw_period = (request.GET.get("period") or "").strip().lower()
    raw_month = (request.GET.get("month") or "").strip()
    month = (
        int(raw_month) if raw_month.isdigit() and 1 <= int(raw_month) <= 12 else None
    )
    raw_quarter = (request.GET.get("quarter") or "").strip().upper()
    quarter = raw_quarter if raw_quarter in {"Q1", "Q2", "Q3", "Q4"} else None

    # Existing month/quarter URLs keep their meaning. New links state the
    # period explicitly so only one temporal lens is active at a time.
    period = raw_period if raw_period in {"week", "month", "quarter", "fy"} else ""
    if not period:
        period = "month" if month else "quarter" if quarter else "fy"

    from apps.core.fy import get_fy_date_range, get_quarter_for_date

    today = date.today()
    fy_start, _ = get_fy_date_range(fy)
    reference = today if get_operational_fy(today) == fy else fy_start.date()
    raw_week = (request.GET.get("week") or "").strip() or reference.strftime("%G-W%V")
    try:
        week_start = datetime.strptime(f"{raw_week}-1", "%G-W%V-%u").date()
    except ValueError:
        raw_week = reference.strftime("%G-W%V")
        week_start = datetime.strptime(f"{raw_week}-1", "%G-W%V-%u").date()

    if month is None:
        month = reference.month
    if quarter is None:
        quarter = get_quarter_for_date(reference)

    date_start = week_start if period == "week" else None
    date_end = week_start + timedelta(days=7) if period == "week" else None
    active_month = month if period == "month" else None
    active_quarter = quarter if period == "quarter" else None
    period_label = {
        "week": f"Week of {week_start:%d %b %Y}",
        "month": datetime(2000, month, 1).strftime("%B") + f" · FY {fy}",
        "quarter": f"{quarter} · FY {fy}",
        "fy": f"FY {fy}",
    }[period]
    return {
        "fy": fy,
        "period": period,
        "week": raw_week,
        "month": active_month,
        "selected_month": month,
        "quarter": active_quarter,
        "selected_quarter": quarter,
        "date_start": date_start,
        "date_end": date_end,
        "period_label": period_label,
    }


def _service_period(period: dict) -> dict:
    """Only the fields understood by the read services."""
    return {
        "fy": period["fy"],
        "month": period["month"],
        "quarter": period["quarter"],
        "date_start": period["date_start"],
        "date_end": period["date_end"],
    }


def _plan_period(period: dict) -> dict:
    """The period a Team or Country Plan read covers.

    Owner, 2026-09-28: "Activities planned by the CCEOs/Staffs are not
    showing all to the PL or their manager." Staff plan forward into whichever
    year the date lands — from 15 September 2026 that is mostly FY2027 — and
    these two lenses read the page year alone, so a Programme Lead's Team Plan
    for FY2026 left out everything their CCEOs had dated from 1 October while
    My Plan listed it. The whole operational year now reads forward through
    the planning horizon (``fy_policy.planning_horizon``), as Cluster, Core
    School and Partner oversight already do. A month or a quarter is a slice
    of the chosen year and stays in it.

    A week is seven dated days, whichever year each falls in. The week of 28
    September 2026 holds three days of FY2026 and four of FY2027, and read
    against the page year alone it showed a Programme Lead five of the seven
    plans their team had in it (owner, 2026-10-02). It reads the years its
    own days belong to.
    """
    from apps.planning.fy_policy import planning_horizon

    service = _service_period(period)
    if period["period"] == "fy":
        service["fys"] = planning_horizon(period["fy"])
    elif period["period"] == "week" and period["date_start"] and period["date_end"]:
        last_day = period["date_end"] - timedelta(days=1)
        years = {
            get_operational_fy(period["date_start"]),
            get_operational_fy(last_day),
        }
        if len(years) > 1:
            service["fys"] = tuple(sorted(years))
        else:
            service["fy"] = years.pop()
    return service


def _plan_period_label(period: dict) -> str:
    """The period label for a plan read: "FY 2026–2027" when it reads ahead."""
    from apps.planning.fy_policy import horizon_label

    if period["period"] != "fy":
        return period["period_label"]
    fys = _plan_period(period).get("fys")
    return horizon_label(fys) if fys else period["period_label"]


# ── Program Lead ─────────────────────────────────────────────────────────────
def _items_owned_by(items, *people) -> list[list]:
    """Staff and partner work attributed to each person, in either id space.

    ``people`` is one set of owner ids per person, and the result one list per
    person, in item order. One pass for all of them: a pass per officer read a
    lead's whole team once for every tab on the page.
    """
    holders: dict[str, set[int]] = {}
    for position, owner_ids in enumerate(people):
        for value in owner_ids:
            if value:
                holders.setdefault(value, set()).add(position)
    owned = [[] for _ in people]
    for item in items:
        found = set()
        for value in (
            item.operational_owner_id,
            item.managing_staff_id,
            item.planned_by_id,
        ):
            found.update(holders.get(value, ()))
        for position in found:
            owned[position].append(item)
    return owned


#: The Programme Lead's default tab: their own work and every officer's, in one
#: list grouped by the person answerable for each row.
WHOLE_TEAM_TAB = "team"

#: Who gets the Schools & Coverage lens on Team Oversight (owner, 2026-09-15).
#: The Programme Lead and Impact Assessment act on schools with no cluster
#: training planned; the Country Director and Regional VP read the same table
#: over them. Everyone else who can reach Team Oversight — the Accountant, for
#: the money in the plan — is not offered the tab, and a `?view=coverage` in
#: the address bar falls back to the planning lens rather than refusing.
COVERAGE_LENS_ROLES = frozenset(
    {
        "Program Lead",
        "ImpactAssessment",
        "CountryDirector",
        "RegionalVP",
        "RegionalProgramLead",
        "Admin",
    }
)


# ── The shared lenses ────────────────────────────────────────────────────────
# Owner, 2026-09-16: "All Oversight Should have the same format. CD should also
# have the same country oversight with all plans reflecting on the budget."
#
# Team Oversight and Country Planning Oversight had each grown their own strip
# of views, so the same person moving between them had to relearn where things
# were — and the Portfolio and Cluster lenses would have had to be built twice.
# One list, one builder, one set of workspaces; each page passes its own base
# URL and says which lenses it holds.
PORTFOLIO_LENS_ROLES = COVERAGE_LENS_ROLES

#: Who reads the people monitors as Planning Oversight tabs, beside the Team
#: Plan, rather than on the Planning Monitor page (owner, 2026-09-30: "on IA
#: can you move the planning monitor and Execution & Completion tabs back to
#: Planning oversight page"). Everyone else keeps the page of its own; an old
#: link sends each reader to wherever their monitors are.
MONITORS_ON_OVERSIGHT_ROLES = frozenset({"ImpactAssessment"})


def monitors_on_oversight(user) -> bool:
    """Whether this reader's monitors are tabs on Planning Oversight."""
    return (getattr(user, "active_role", "") or "") in MONITORS_ON_OVERSIGHT_ROLES


def is_country_reader(user) -> bool:
    """Whether this reader's scope is the country rather than a team.

    The portfolio lens is the same lens either way — it is bounded by
    `scoped_school_queryset`, like every other analytics surface — but a
    Programme Lead reading their own CCEOs' schools under a tab called "Country
    Portfolio" is being told something untrue about what they are looking at.
    """
    from apps.core.scoping import COUNTRY_ROLES

    role = getattr(user, "active_role", "") or ""
    return role in COUNTRY_ROLES or bool(getattr(user, "is_superuser", False))


def _lens_tabs(
    base_url: str, active: str, available, *, country: bool = True
) -> list[dict]:
    """The lens strip, in one order, for whichever page is drawing it."""
    labels = (
        (
            "planning",
            "Team Plan" if base_url == TEAM_OVERSIGHT_PATH else "Country Plan",
        ),
        ("monitor", "Planning Monitor"),
        ("projects", "Special Projects"),
        ("execution", "Execution & Completion"),
        ("portfolio", "Country Portfolio" if country else "Team Portfolio"),
        ("coverage", "Schools & Coverage"),
        ("targets", "Target Performance"),
    )
    tabs = []
    for key, label in labels:
        if key not in available:
            continue
        query = "" if key == "planning" else f"?view={key}"
        tabs.append(
            {
                "key": key,
                "label": label,
                "href": f"{base_url}{query}",
                "is_active": key == active,
            }
        )
    # A strip of one is furniture: it costs the first table row its place above
    # the fold and chooses nothing.
    return tabs if len(tabs) > 1 else []


#: Query parameters only the Country Plan (activity) lens reads. A link that
#: carries one of them was made on that lens.
_ACTIVITY_PLAN_PARAMS = frozenset(
    {
        "lead",
        "risk",
        "activity_type",
        "executor_type",
        "context",
        "status",
        "district_id",
        "partner_id",
    }
)


def _names_activity_plan(request) -> bool:
    import re

    keys = set(request.GET.keys())
    if keys & _ACTIVITY_PLAN_PARAMS:
        return True
    return any(re.match(r"^g\d+_page", key) for key in keys)


def country_lens_tabs(active: str) -> list[dict]:
    """Country Oversight's two stages (owner, 2026-09-28): planning general
    oversight, and execution & completion. The activity plan, the planning
    monitor and the portfolio stay reachable from the rows' menus and links,
    and the portfolio lives on the Map page."""
    return [
        {
            "key": key,
            "label": label,
            "short": short,
            "href": href,
            "is_active": key == active,
        }
        for key, label, short, href in (
            (
                "coverage",
                "Country General Planning Oversight",
                "General Planning",
                COUNTRY_OVERSIGHT_PATH,
            ),
            (
                "execution",
                "Country Execution & Completion Oversight",
                "Execution & Completion",
                f"{COUNTRY_OVERSIGHT_PATH}?view=execution",
            ),
        )
    ]


@require_page_permission("planning_monitor")
def planning_monitor_view(request):
    """The Planning Monitor, a page of its own under the Dashboard (owner,
    2026-09-29: "move the [monitor] on its own page and add it to the side
    bar and place it below the Dashboard. Do the same for PL").

    Two tabs over the same people (apps.planning.monitor_roster): Planning —
    each Programme Lead's and CCEO's plan against their 280 or 560, partner
    work and the schools nobody has planned for — and Execution & Completion
    — that plan as it is delivered, completed and verified. The country for
    the CD, IA and RVP; a Lead's own team for the PL.

    The Programme Lead reads it on their dashboard, in place of Leadership
    Attention (owner, 2026-09-29; apps.frontend.views.dashboard_embed): the
    dashboard section's requests get the monitor with its tabs, and the page
    opened on its own sends the Lead there.
    """
    from apps.frontend.views import dashboard_embed

    execution = (request.GET.get("view") or "").strip().lower() == "execution"
    lens = "execution" if execution else "monitor"
    # The figures as data, for every reader of the monitor in their own
    # scope, wherever the page itself is read.
    if not execution and request.GET.get("format", "").strip().lower() == "json":
        return _monitor_readiness_json(request)
    if dashboard_embed.reads_on_dashboard(request):
        return dashboard_embed.to_dashboard(request, dashboard_embed.PLANNING_MONITOR)
    # IA reads the monitors as Planning Oversight tabs (owner, 2026-09-30):
    # a bookmark or a figure's drill-down to this page opens the same tab
    # there, on the same filters.
    if monitors_on_oversight(request.user):
        return _to_planning_monitor(request, lens)
    period = _period_filters(request)
    lens_context = _execution_context if execution else _monitor_context
    context = {
        **period,
        **lens_context(request, period, base_url=PLANNING_MONITOR_PATH),
        "active_oversight_view": lens,
        "lens_tabs": [
            {
                "key": key,
                "label": label,
                "href": f"{PLANNING_MONITOR_PATH}?view={key}",
                "is_active": key == ("execution" if execution else "planning"),
            }
            for key, label in (
                ("planning", "Planning"),
                ("execution", "Execution & Completion"),
            )
        ],
        "lens_base_url": PLANNING_MONITOR_PATH,
        "monitor_is_country": is_country_reader(request.user),
        "fy_options": fy_options(),
        # On the Lead's dashboard the filters ride in the section's one head
        # row, beside its name and tabs (owner, 2026-09-30).
        "monitor_embedded": dashboard_embed.is_embedded(request),
    }
    if dashboard_embed.is_embedded(request):
        return dashboard_embed.fragment(
            render(request, "partials/oversight/planning_monitor_embed.html", context)
        )
    if request.headers.get("HX-Request") == "true":
        return render(request, _MONITOR_TEMPLATES[lens], context)
    return render(request, "pages/oversight/planning_monitor.html", context)


def _monitor_readiness_json(request):
    """Planned and remaining as data: the country's (or the team's) total,
    each Programme Lead's team and each person, for the reader's own scope.
    The figures are the page's (apps.planning.readiness), checked the same
    way before they leave."""
    from django.http import JsonResponse

    from apps.planning import readiness
    from apps.planning.fy_policy import next_open_fy
    from apps.planning.planning_monitor import planning_monitor, schools_in_scope

    period = _period_filters(request)
    fy = (request.GET.get("fy") or "").strip() or next_open_fy() or period["fy"]
    monitor = planning_monitor(request.user, fy=fy)
    figures = readiness.for_monitor(
        monitor, expected_schools=schools_in_scope(request.user)
    )
    return JsonResponse(
        {
            "fy": str(fy),
            "scope": "country" if is_country_reader(request.user) else "team",
            "total": figures.as_dict(),
            "planned_activities": readiness.ledger(
                monitor, fy, whole_country=is_country_reader(request.user)
            ),
            "teams": [
                {
                    "program_lead": lead.name,
                    "total": lead.readiness.as_dict(),
                    "people": [
                        {
                            "name": officer.name,
                            "role": officer.role,
                            **officer.readiness.as_dict(),
                        }
                        for officer in lead.officers
                    ],
                }
                for lead in monitor["leads"]
            ],
        }
    )


def _to_planning_monitor(request, lens: str):
    """An old link to a monitor tab on an oversight page opens the Planning
    Monitor page with the same filters (the monitors moved there,
    2026-09-29) — or, for a reader who keeps them as Planning Oversight tabs
    (IA, 2026-09-30), the same tab there."""
    query = request.GET.copy()
    if monitors_on_oversight(request.user):
        query["view"] = "execution" if lens == "execution" else "monitor"
        destination = f"{TEAM_OVERSIGHT_PATH}?{query.urlencode()}"
    else:
        query["view"] = "execution" if lens == "execution" else "planning"
        destination = f"{PLANNING_MONITOR_PATH}?{query.urlencode()}"
    response = redirect(destination)
    if request.headers.get("HX-Request") == "true":
        response["HX-Redirect"] = destination
    return response


@require_page_permission("country_map")
def country_map_view(request):
    """The Country Map (owner, 2026-09-28): the country shaded by delivery,
    backlog or money, and under it the country portfolio — every school under
    the Programme Lead and the CCEO who hold it — when there is one.

    The portfolio used to be a Country Oversight tab; Country Oversight keeps
    its two stages (planning, and execution & completion) and the portfolio
    reads beside the map. Read-only, like both of them.
    """
    from apps.analytics.country_map_context import country_map_context

    period = _period_filters(request)
    portfolio = _portfolio_context(request, period, base_url=COUNTRY_MAP_PATH)
    context = {
        **period,
        **portfolio,
        "active_oversight_view": "portfolio",
        "lens_tabs": [],
        "lens_base_url": COUNTRY_MAP_PATH,
        "portfolio_is_country": True,
        "fy_options": fy_options(),
        "has_portfolio": bool(portfolio["portfolio_totals"].get("schools")),
    }
    if (
        request.headers.get("HX-Request") == "true"
        and (request.headers.get("HX-Target") or "") == "oversight-workspace"
    ):
        return render(request, "partials/oversight/portfolio_workspace.html", context)
    context.update(country_map_context(period["fy"]))
    return render(request, "pages/oversight/country_map.html", context)


def _portfolio_context(request, period: dict, *, base_url: str) -> dict:
    """The country portfolio lens — schools under their lead and their CCEO."""
    from apps.planning.portfolio_service import country_portfolio, program_lead_options

    portfolio = country_portfolio(
        request.user,
        fy=period["fy"],
        program_lead_id=(request.GET.get("program_lead") or "").strip() or None,
        district_id=(request.GET.get("district") or "").strip() or None,
        planned=(request.GET.get("planned") or "").strip() or None,
    )
    totals = portfolio["totals"]
    return {
        "portfolio": portfolio,
        "portfolio_totals": totals,
        "portfolio_leads": program_lead_options(portfolio),
        "portfolio_districts": portfolio["districts"],
        "selected_program_lead": (request.GET.get("program_lead") or "").strip(),
        "selected_district": (request.GET.get("district") or "").strip(),
        "selected_planned": (request.GET.get("planned") or "").strip(),
        "portfolio_url": f"{base_url}?view=portfolio",
        "kpis": _portfolio_kpis(totals, base_url=base_url),
    }


def _monitor_context(request, period: dict, *, base_url: str) -> dict:
    """The Planning Monitor lens (owner, 2026-09-28): each CCEO's year
    against the 560 visits it should hold, training coverage, and the schools
    not yet planned, under their Programme Lead."""
    from apps.planning.fy_policy import next_open_fy
    from apps.planning.planning_monitor import (
        DEFAULT_VISITS_TARGET,
        GAP_LABELS,
        GAPS,
        PL_VISITS_TARGET,
        planning_monitor,
    )

    # The year being planned, as the Work Plan opens on it: the next fiscal
    # year once it is open for planning, else the running one. Any year the
    # selector offers may be chosen, to follow execution.
    fy = (request.GET.get("fy") or "").strip() or next_open_fy() or period["fy"]
    selected_lead = (request.GET.get("program_lead") or "").strip()
    gap = (request.GET.get("gap") or "").strip()
    gap = gap if gap in GAP_LABELS else ""
    officer = (request.GET.get("officer") or "").strip()
    monitor = planning_monitor(
        request.user,
        fy=fy,
        program_lead_id=selected_lead or None,
        gap=gap or None,
        officer_id=officer or None,
    )
    _mark_gap_follow_ups(request.user, monitor["gap_schools"], gap=gap, fy=fy)
    monitor_url = f"{base_url}?view=monitor&fy={fy}"
    # Planned and remaining in four parts, on every person, team and total
    # (apps.planning.readiness), checked against the schools in scope before
    # the page is given a figure.
    from apps.planning import readiness
    from apps.planning.planning_monitor import schools_in_scope

    figures = readiness.for_monitor(
        monitor, expected_schools=schools_in_scope(request.user)
    )
    tab = (request.GET.get("tab") or "").strip()
    if tab not in MONITOR_TABS_BY_KEY:
        tab = "detail" if gap else "readiness"
    # Each person's count opens the rows behind it (owner, 2026-10-02: "both
    # the counts and details of their CCEO"): their planned visits on the
    # Team Plan — a Lead's reader lands on that person's tab, the country's
    # on their Lead's — and the schools they handed over on Partner
    # Monitoring.
    return {
        "fy": fy,
        "plans_url": f"{TEAM_OVERSIGHT_PATH}?period=fy&fy={fy}",
        "plans_by_lead": oversight.resolve_oversight_scope(request.user).groups_by_lead,
        "partner_url": f"{PARTNER_OVERSIGHT_PATH}?period=fy&fy={fy}",
        "monitor": monitor,
        "monitor_totals": monitor["totals"],
        "monitor_readiness": figures,
        # Every planned activity of the year and where it is counted.
        "monitor_ledger": readiness.ledger(
            monitor, fy, whole_country=is_country_reader(request.user)
        ),
        "monitor_tabs": MONITOR_TABS,
        "monitor_tab": tab,
        "monitor_url": monitor_url,
        "monitor_gaps": GAPS,
        "monitor_can_send": bool(gap) and may_delegate(request.user, country=False),
        "monitor_gap": gap,
        "monitor_gap_label": GAP_LABELS.get(gap, ""),
        "monitor_officer": officer,
        "selected_program_lead": selected_lead,
        "default_visits_target": DEFAULT_VISITS_TARGET,
        "pl_visits_target": PL_VISITS_TARGET,
        "kpis": _monitor_kpis(monitor["totals"], figures, monitor_url=monitor_url),
    }


#: The three reads of the Planning Monitor's people, one at a time (owner,
#: 2026-10-02: tabs, not stacks).
MONITOR_TABS = (
    ("readiness", "Planned and remaining"),
    ("detail", "Planning detail"),
    ("schools", "Schools and checks"),
)
MONITOR_TABS_BY_KEY = dict(MONITOR_TABS)


#: The school action a Programme Lead sends for each gap the monitor lists
#: (apps.planning.action_service.PLANNING_GAP_KEYS): the ask a Country
#: Director's follow-up already sends through a Lead, made by the Lead from
#: the list itself. Each closes when the school's plan closes the gap.
MONITOR_GAP_ACTIONS = {
    "no_both": "planning_school_gap",
    "no_visit": "planning_school_gap",
    "no_training": "planning_training_gap",
    "not_clustered": "planning_cluster_gap",
    "no_partner": "planning_partner_gap",
}


def _gap_condition_key(action_type: str, school_id: str, fy: str) -> str:
    return f"planning_gap|{action_type}|school|{school_id}|{fy}"


def _mark_gap_follow_ups(user, schools, *, gap: str, fy: str) -> None:
    """Say which of the listed schools a Programme Lead may send their CCEO,
    and which they already have (owner, 2026-10-02: the Lead reads a CCEO's
    schools and plans and "can send CCEO notification using (Send to
    {CCEO}) button").

    A school is sendable when one of the Lead's officers holds it: the Lead's
    own schools are theirs to plan, and nobody is sent a school no one holds.
    One query for the asks already open.
    """
    action_type = MONITOR_GAP_ACTIONS.get(gap)
    if not schools or not action_type or not may_delegate(user, country=False):
        return
    from apps.planning.action_models import ACTIVE_STATES, TeamAction

    scope = oversight.resolve_oversight_scope(user)
    keys = {
        _gap_condition_key(action_type, school.id, fy): school for school in schools
    }
    sent = set(
        TeamAction.objects.filter(
            condition_key__in=list(keys), state__in=ACTIVE_STATES
        ).values_list("condition_key", flat=True)
    )
    visit_gap = gap in ("no_visit", "no_both")
    for key, school in keys.items():
        # A school in a partner's hands is the partner's to date (owner,
        # 2026-10-02): the officer is not asked to plan its visit.
        school.can_send = school.officer_id in scope.supervised_ids and not (
            visit_gap and school.has_partner
        )
        school.sent = key in sent
        school.send_name = (school.officer_name or "").split(" ")[0]


@require_POST
@require_page_permission("planning_monitor")
def planning_monitor_send_view(request):
    """ "Send to <CCEO>" from the Planning Monitor's school list.

    A Programme Lead reads their officers' schools and plans and changes none
    of them (owner, 2026-10-02); what they do about a school nobody has
    planned for, or that should be with a partner and is not, is ask the
    officer who holds it. The gap is read again from the monitor before
    anything is sent, so a stale row cannot raise an ask about a school that
    has since been planned, and the ask goes to the school's holder, who must
    be one of the Lead's own officers.
    """
    from apps.accounts.models import StaffProfile
    from apps.planning.action_service import send_action
    from apps.planning.planning_monitor import planning_monitor
    from apps.schools.models import School

    def refuse(message: str):
        return _action_response(
            request, message, ok=False, fallback=PLANNING_MONITOR_PATH
        )

    if not may_delegate(request.user, country=False):
        return refuse(
            "Sending from here belongs to the Programme Lead who supervises "
            "the officer. You can read this list but not send from it."
        )
    gap = (request.POST.get("gap") or "").strip()
    school_id = (request.POST.get("school_id") or "").strip()
    fy = (request.POST.get("fy") or "").strip() or get_operational_fy()
    note = (request.POST.get("note") or "").strip()
    action_type = MONITOR_GAP_ACTIONS.get(gap)
    if not action_type or not school_id:
        return refuse("Choose a school from the list to send.")

    monitor = planning_monitor(request.user, fy=fy, gap=gap)
    state = next((s for s in monitor["gap_schools"] if s.id == school_id), None)
    if state is None:
        return refuse(
            "That school no longer has this gap, so there is nothing to send."
        )
    scope = oversight.resolve_oversight_scope(request.user)
    if state.officer_id not in scope.supervised_ids:
        return refuse(
            "That school is not held by one of your officers, so there is "
            "nobody on your team to send it to."
        )
    if gap in ("no_visit", "no_both") and state.has_partner:
        return refuse(
            "That school is with a partner, who sets the visit's date. Follow "
            "it on Partner Monitoring."
        )
    recipient = (
        StaffProfile.objects.filter(id=state.officer_id, deleted_at__isnull=True)
        .select_related("user")
        .first()
    )
    school = School.objects.filter(id=school_id, deleted_at__isnull=True).first()
    if recipient is None or school is None:
        return refuse("That school's officer could not be found.")
    try:
        action = send_action(
            sender=request.user,
            school=school,
            issue={
                "key": action_type,
                "condition_key": _gap_condition_key(action_type, school.id, fy),
                "severity": "high",
                "detail": "",
            },
            fy=fy,
            recipient_staff=recipient,
            note=note,
        )
    except ActionError as exc:
        return refuse(str(exc))
    return _action_response(
        request,
        f"Sent to {_recipient_name(action)}. Tracked under Actions Sent.",
        fallback=PLANNING_MONITOR_PATH,
    )


_MONITOR_TEMPLATES = {
    "monitor": "partials/oversight/monitor_workspace.html",
    "projects": "partials/oversight/special_projects_workspace.html",
    "execution": "partials/oversight/execution_workspace.html",
}


def _narrow_project_schools(result, project_status: str) -> None:
    """Keep the school rows the Project status filter asks for: the schools a
    Partner holds, or the schools with an activity scheduled. The page and
    its export narrow the same rows the same way."""
    from apps.projects import monitoring

    if project_status == "partner":
        for row in result.rows:
            row.school_rows = [
                s
                for s in row.school_rows
                if s.partner_name
                or getattr(s, "has_partner", False)
                or s.plan_stage
                in (
                    monitoring.PLAN_PARTNER_AWAITING,
                    monitoring.PLAN_PARTNER_SCHEDULED,
                    monitoring.PLAN_PARTNER_RETURNED,
                )
            ]
    elif project_status == "scheduled":
        for row in result.rows:
            row.school_rows = [
                s
                for s in row.school_rows
                if s.activity_date
                or s.next_date
                or s.status_key
                in (
                    monitoring.STATUS_SCHEDULED,
                    monitoring.STATUS_IN_PROGRESS,
                    monitoring.STATUS_AWAITING_VERIFICATION,
                    monitoring.STATUS_COMPLETED,
                )
                or s.execution != monitoring.EXEC_NONE
            ]


def _special_projects_context(request, period: dict, *, base_url: str) -> dict:
    """Special Projects oversight (owner, 2026-10-03): every live project and
    the schools assigned to them, with their planning and delivery status."""
    from apps.core.fy import fy_options, get_operational_fy
    from apps.projects import monitoring

    fy = (
        (request.GET.get("fy") or "").strip()
        or period.get("fy")
        or get_operational_fy()
    )
    selected_project = (request.GET.get("project") or "").strip()
    stages = dict(monitoring.STAGE_FILTERS)
    requested_stage = (request.GET.get("stage") or "").strip()
    selected_stage = requested_stage if requested_stage in stages else ""
    selected_project_status = (request.GET.get("project_status") or "schools").strip()

    result = monitoring.project_monitoring(request.user, fy=fy, stage=selected_stage)
    project_ids = [row.id for row in result.rows]
    if (
        selected_project
        and selected_project != "all"
        and selected_project not in project_ids
    ):
        selected_project = ""

    _narrow_project_schools(result, selected_project_status)

    project_tabs = [
        {
            "key": "all",
            "label": "All Projects",
            "count": sum(len(row.school_rows) for row in result.rows),
            "is_active": selected_project in ("", "all"),
        }
    ] + [
        {
            "key": row.id,
            "label": row.name,
            "count": len(row.school_rows),
            "is_active": row.id == selected_project,
        }
        for row in result.rows
    ]

    if selected_project in ("", "all"):
        active_rows = result.rows
    else:
        active_rows = [row for row in result.rows if row.id == selected_project]

    period_val = period.get("period") or "fy"
    table_query = f"fy={fy}&period={period_val}"

    return {
        "result": result,
        "rows": active_rows,
        "project_tabs": project_tabs,
        "selected_project": selected_project or "all",
        "stage_options": monitoring.STAGE_FILTERS,
        "selected_stage": selected_stage,
        "selected_project_status": selected_project_status,
        "fy": fy,
        "fy_options": fy_options(),
        "table_query": table_query,
        "base_url": base_url,
        "can_export": RolePermissionService.can_export(request.user, request.path),
    }


def _execution_context(request, period: dict, *, base_url: str) -> dict:
    """The Execution & Completion Monitor lens (owner, 2026-09-29): each
    person's plan as it is delivered, completed and verified, under their
    Programme Lead."""
    from apps.core.fy import get_operational_fy
    from apps.planning.execution_monitor import (
        LIST_COLUMNS,
        LIST_LABELS,
        LISTS,
        execution_monitor,
    )

    # The running year: execution happens in it. Any year the selector
    # offers may be chosen.
    fy = (request.GET.get("fy") or "").strip() or str(get_operational_fy())
    selected_lead = (request.GET.get("program_lead") or "").strip()
    list_key = (request.GET.get("list") or "").strip()
    list_key = list_key if list_key in LIST_LABELS else ""
    person = (request.GET.get("person") or "").strip()
    monitor = execution_monitor(
        request.user,
        fy=fy,
        program_lead_id=selected_lead or None,
        list_key=list_key or None,
        person_id=person or None,
    )
    execution_url = f"{base_url}?view=execution&fy={fy}"
    return {
        "fy": fy,
        "execution": monitor,
        "execution_totals": monitor["totals"],
        "execution_url": execution_url,
        "execution_lists": LISTS,
        "execution_columns": LIST_COLUMNS,
        "execution_list": list_key,
        "execution_list_label": LIST_LABELS.get(list_key, ""),
        "execution_person": person,
        "selected_program_lead": selected_lead,
        "kpis": _execution_kpis(monitor["totals"], execution_url=execution_url),
    }


def _execution_kpis(totals, *, execution_url: str) -> list[dict]:
    """The execution monitor's tiles, each folded from the rows below them."""

    def share(key, part, whole, *, helper, icon, drill=None, empty):
        return render_kpi_item(
            key,
            (
                MetricValue.ratio(part, whole)
                if whole
                else MetricValue.absent(DataState.NOT_YET_MEASURABLE, note=empty)
            ),
            helper=helper,
            icon=icon,
            drilldown_url=drill,
        )

    return [
        share(
            "execution_visits_delivered_target",
            totals.visits_delivered,
            totals.visits_target,
            # Follow up and In-school Training only (the
            # planning rulebook); outreach visits are named, not counted.
            helper=f"{totals.visits_delivered:,} of {totals.visits_target:,} visits"
            + (
                f" · {totals.outreach_delivered:,} donor, story or social "
                "(not counted)"
                if totals.outreach_delivered
                else ""
            ),
            icon="target",
            empty="No one in scope",
        ),
        share(
            "execution_due_delivered",
            totals.delivered_due,
            totals.due,
            helper=f"{totals.delivered_due:,} of {totals.due:,} due to date",
            icon="check",
            empty="Nothing due yet",
        ),
        render_kpi_item(
            "execution_overdue",
            MetricValue.measured(totals.overdue),
            helper="Planned day passed, not delivered",
            tone="danger" if totals.overdue else "neutral",
            icon="warning",
            drilldown_url=f"{execution_url}&list=overdue",
        ),
        share(
            "execution_complete_share",
            totals.complete,
            totals.delivered,
            helper=f"{totals.missing_salesforce:,} no SF ID · "
            f"{totals.missing_evidence:,} no form",
            icon="clipboard",
            drill=f"{execution_url}&list=missing_salesforce",
            empty="Nothing delivered yet",
        ),
        render_kpi_item(
            "execution_awaiting_ia",
            MetricValue.measured(totals.awaiting_ia),
            helper=f"{totals.verified:,} verified",
            icon="check",
            drilldown_url=f"{execution_url}&list=awaiting_ia",
        ),
        share(
            "execution_partner_delivered",
            totals.partner_delivered,
            totals.partner_scheduled,
            helper=f"{totals.partner_delivered:,} of {totals.partner_scheduled:,} "
            "partner activities",
            icon="users",
            empty="No partner work",
        ),
    ]


def _monitor_kpis(totals, figures, *, monitor_url: str) -> list[dict]:
    """The monitor's tiles, each folded from the officer rows below them."""

    def share(key, part, whole, *, helper, icon, drill=None, empty="No schools"):
        return render_kpi_item(
            key,
            (
                MetricValue.ratio(part, whole)
                if whole
                else MetricValue.absent(DataState.NOT_YET_MEASURABLE, note=empty)
            ),
            helper=helper,
            icon=icon,
            drilldown_url=drill,
        )

    schools = totals.school_count
    return [
        share(
            "monitor_visits_planned_share",
            # Against what the schools held ask of staff, to each person's
            # ceiling: the sum of every 280 and 560 counted people holding
            # no school, and read a fully planned country as a few percent.
            figures.staff_visits.credited,
            figures.staff_visits.target,
            helper=f"{figures.staff_visits.credited:,} of "
            f"{figures.staff_visits.target:,} staff visits · "
            f"{figures.staff_visits.remaining:,} remaining · "
            f"{totals.core_visits:,} core, {totals.client_visits:,} client",
            icon="target",
            empty="No one in scope",
        ),
        share(
            "monitor_schools_with_visit",
            # A school handed to a Partner is covered, dated or not: read as
            # "no visit", staff who had handed everything over looked as if
            # they had planned nothing.
            totals.schools_covered,
            schools,
            helper=f"{totals.schools_with_visit:,} with a visit planned · "
            f"{totals.schools_awaiting_partner:,} with a Partner, awaiting its "
            f"date · {totals.unplanned:,} with neither, of {schools:,}",
            icon="school",
            drill=f"{monitor_url}&gap=no_visit",
        ),
        # Against the schools that take a training (Core, Client, Core
        # Trained and Core Graduate).
        share(
            "monitor_schools_with_training",
            totals.schools_with_training,
            totals.training_schools,
            helper=f"{totals.schools_group_training:,} group training · "
            f"{totals.schools_in_school_training:,} in-school training · "
            f"{totals.schools_meeting:,} in a cluster meeting, not counted",
            icon="users",
            drill=f"{monitor_url}&gap=no_training",
        ),
        render_kpi_item(
            "monitor_schools_unplanned",
            MetricValue.measured(totals.no_both),
            helper="No visit, no Partner and no training planned",
            tone="danger" if totals.no_both else "neutral",
            icon="warning",
            drilldown_url=f"{monitor_url}&gap=no_both",
        ),
        render_kpi_item(
            "monitor_schools_not_clustered",
            MetricValue.measured(totals.not_clustered),
            helper="Cannot join a group training yet",
            tone="warning" if totals.not_clustered else "neutral",
            icon="warning",
            drilldown_url=f"{monitor_url}&gap=not_clustered",
        ),
        render_kpi_item(
            "monitor_partner_share",
            MetricValue.measured(totals.partner_assigned_schools),
            # One line from one count (apps.planning.readiness): "29 of 20
            # ... 20 still to assign" was two sums of different people.
            helper=f"{figures.partner_assignment.credited:,} of "
            f"{figures.partner_assignment.target:,} schools the Partner should "
            f"hold ({figures.partner_core_schools:,} Core, "
            f"{figures.partner_beyond_staff:,} beyond staff capacity) · "
            f"{figures.partner_assignment.remaining:,} still to assign · "
            f"{totals.partner_scheduled:,} partner activities scheduled · "
            f"{totals.partner_awaiting:,} awaiting a date",
            tone="warning" if figures.partner_assignment.remaining else "neutral",
            icon="users",
            drilldown_url=f"{monitor_url}&gap=no_partner",
        ),
        render_kpi_item(
            "monitor_schools_in_projects",
            MetricValue.measured(totals.in_projects),
            helper="Enrolled in an open Special Project",
            icon="clipboard",
            drilldown_url="/projects/monitoring",
        ),
    ]


def _portfolio_kpis(totals, *, base_url: str) -> list[dict]:
    """Four tiles, each folded from the rows below them.

    The planned share carries its denominator: a portfolio with no schools in
    it has not planned 0% of them, and MetricValue is where that distinction
    lives rather than in the template.
    """
    return [
        render_kpi_item(
            "portfolio_schools_in_scope",
            MetricValue.measured(totals["schools"]),
            helper=f"{totals['leads']} lead{'' if totals['leads'] == 1 else 's'} · "
            f"{totals['officers']} officer{'' if totals['officers'] == 1 else 's'}",
            icon="school",
        ),
        render_kpi_item(
            "portfolio_schools_planned_share",
            (
                MetricValue.ratio(totals["planned"], totals["schools"])
                if totals["schools"]
                else MetricValue.absent(
                    DataState.NOT_YET_MEASURABLE, note="No schools in scope"
                )
            ),
            helper=f"{totals['planned']} of {totals['schools']} schools",
            icon="check",
        ),
        render_kpi_item(
            "portfolio_schools_unplanned",
            MetricValue.measured(totals["unplanned"]),
            helper="Nothing planned all year",
            tone="danger" if totals["unplanned"] else "neutral",
            icon="warning",
            drilldown_url=f"{base_url}?view=portfolio&planned=unplanned",
        ),
        render_kpi_item(
            "portfolio_planned_budget",
            MetricValue.measured(totals["budget"]),
            helper=f"Across {totals['activities']} planned activities",
            icon="currency",
        ),
    ]


def _cluster_kpis(totals) -> list[dict]:
    return [
        render_kpi_item(
            "cluster_performance_clusters",
            MetricValue.measured(totals["clusters"]),
            helper=f"{totals['schools']} member schools",
            icon="users",
        ),
        render_kpi_item(
            "cluster_performance_dormant",
            MetricValue.measured(totals["dormant"]),
            helper="No session and no visit all year",
            tone="danger" if totals["dormant"] else "neutral",
            icon="warning",
        ),
        render_kpi_item(
            "cluster_performance_sessions",
            MetricValue.measured(totals["sessions"]),
            helper=f"{totals['sessions_done']} delivered · "
            f"{totals['visits']} member visits",
            icon="calendar",
        ),
        # Both shares go through MetricValue.ratio, which is what carries the
        # denominator: the registry refuses a percentage without one, because
        # "71%" that cannot be checked against "64 of 90" is a number nobody
        # can argue with.
        render_kpi_item(
            "cluster_performance_reach",
            (
                MetricValue.ratio(totals["reached"], totals["schools"])
                if totals["schools"]
                else MetricValue.absent(
                    DataState.NOT_YET_MEASURABLE, note="No member schools"
                )
            ),
            helper=f"{totals['reached']} of {totals['schools']} member schools",
            icon="target",
        ),
        render_kpi_item(
            "cluster_performance_ssa_coverage",
            (
                MetricValue.ratio(totals["ssa_schools"], totals["schools"])
                if totals["schools"]
                else MetricValue.absent(
                    DataState.NOT_YET_MEASURABLE, note="No member schools"
                )
            ),
            helper=f"{totals['ssa_schools']} with an SSA record this year",
            icon="clipboard",
        ),
        render_kpi_item(
            "cluster_performance_budget",
            MetricValue.measured(totals["budget"]),
            helper="Sessions and member-school visits",
            icon="currency",
        ),
    ]


def _team_progress_rows(tabs, activity_family: str, *, own_label: str) -> list[dict]:
    """One row per person for the progress chart, folded the way the tiles are.

    The lead's own work sits first under their name, then each supervised
    officer in tab order; the whole-team tab is the sum of them and is not
    drawn again. Each row is folded from that person's items in the selected
    activity family, so the chart, the tab counts and the tables below cannot
    disagree. On the country lens the tabs are Programme Leads, and each Lead
    is a row in the same way.
    """
    rows = []
    for entry in tabs:
        if entry["key"] == WHOLE_TEAM_TAB:
            continue
        label = own_label if entry["key"] == "mine" else entry["label"]
        rows.append(
            {
                "name": label,
                **oversight.summarize(
                    oversight.in_family(entry["items"], activity_family)
                ),
            }
        )
    return rows


def _team_owner_tabs(scope, items, selected: str) -> tuple[list[dict], str, list]:
    """Whole team, My Work, then one tab per supervised officer.

    Whole team comes first and is the default (Programme Lead alignment,
    2026-09-13): leading a team starts from the team, and opening on "My Work"
    showed a lead with no portfolio of their own an empty page. The officer
    tabs stay so a lead can narrow to one person; the fund-approval "View Full
    Plan" link still lands on that officer, whichever id space it carries.
    """
    members = _team_members(scope)
    own_items, *members_items = _items_owned_by(
        items, scope.own_ids, *(member["owner_ids"] for member in members)
    )
    tabs = [
        {
            # Everything the team lens holds. `build_items` already bounded it
            # to the lead and their officers — including partner work reached
            # through a school or cluster they own — so this tab re-filters
            # nothing and cannot lose a row the officer tabs would show.
            "key": WHOLE_TEAM_TAB,
            "label": "Whole team",
            "count": len(items),
            "items": list(items),
        },
        {
            "key": "mine",
            "label": "My Work",
            "count": len(own_items),
            "items": own_items,
        },
    ]
    for member, member_items in zip(members, members_items):
        tabs.append(
            {
                "key": member["id"],
                "label": member["name"],
                "count": len(member_items),
                "items": member_items,
            }
        )
    active = next((entry for entry in tabs if entry["key"] == selected), None)
    if active is None:
        # Deep links (e.g. the fund-approval "View Full Plan" button) carry
        # the member's User id, while the tab key is the StaffProfile id.
        # Resolve across both identity spaces instead of silently falling
        # back to "My Work" with the wrong person's plan.
        resolved = next((m["id"] for m in members if selected in m["owner_ids"]), None)
        active = next((entry for entry in tabs if entry["key"] == resolved), tabs[0])
    for entry in tabs:
        entry["is_active"] = entry is active
    return tabs, active["key"], active["items"]


def _mark_reviewable(user, trainings) -> None:
    """Set `can_review` on the facilitated trainings waiting on a Programme
    Lead: whether this reader may confirm or return each (the review rule
    itself, pl_review.services.may_review), one query for the lot."""
    waiting = [t for t in trainings if t.awaits_review]
    if not waiting:
        return
    from apps.activities.models import Activity
    from apps.pl_review.services import may_review

    activities = Activity.objects.in_bulk([t.activity_id for t in waiting])
    for training in waiting:
        activity = activities.get(training.activity_id)
        training.can_review = bool(activity and may_review(user, activity))


def _program_lead_tabs(
    items, selected: str | None, *, program_leads=None
) -> tuple[list[dict], str, list]:
    """PL tabs for the country / region lens.

    When *program_leads* is supplied (from ``system_program_leads``), every
    real PL gets a tab whether or not they have items in the period — and
    non-PL roles (IA, Accountant) never appear.  Items are bucketed by the
    ``supervising_pl_id`` the service already stamped.
    """
    if program_leads is not None:
        # Top-down: one tab per system PL.
        pl_lookup: dict[str, dict] = {}
        tabs: list[dict] = []
        for pl in program_leads:
            tab: dict = {
                "key": pl["id"],
                "label": pl["name"],
                "count": 0,
                "items": [],
            }
            tabs.append(tab)
            for pid in pl["ids"]:
                pl_lookup[pid] = tab

        unassigned_items: list = []
        for item in items:
            target = (
                pl_lookup.get(item.supervising_pl_id)
                if item.supervising_pl_id
                else None
            )
            if target is not None:
                target["items"].append(item)
                target["count"] += 1
            else:
                unassigned_items.append(item)

        if unassigned_items:
            tabs.append(
                {
                    "key": "unassigned",
                    "label": "Unassigned",
                    "count": len(unassigned_items),
                    "items": unassigned_items,
                }
            )
    else:
        # Fallback: bottom-up grouping from item data.
        buckets: dict[tuple[str, str], list] = {}
        for item in items:
            key = item.supervising_pl_id or "unassigned"
            label = item.supervising_pl_name or "Unassigned"
            buckets.setdefault((key, label), []).append(item)
        tabs = [
            {
                "key": key,
                "label": label,
                "count": len(group_items),
                "items": group_items,
            }
            for (key, label), group_items in sorted(
                buckets.items(),
                key=lambda entry: (entry[0][1] == "Unassigned", entry[0][1]),
            )
        ]

    if not tabs:
        return [], "", []
    active = next((entry for entry in tabs if entry["key"] == selected), tabs[0])
    for entry in tabs:
        entry["is_active"] = entry is active
    return tabs, active["key"], active["items"]


def _resolve_user_scope(user):
    from apps.core.scoping import resolve_user_scope

    return resolve_user_scope(user)


def _default_officer(owner_groups) -> str:
    """The officer tab the page opens on: the first one holding work.

    A roster lists every member in order, the Programme Lead first, whether or
    not they hold work this period (2026-09-23). Opening on an empty panel
    would put nothing under the tabs on first load, so the strip keeps the
    roster's order but lands on the first person with something to read.
    """
    for group in owner_groups or []:
        if group.get("items"):
            return str(group["id"])
    return str(owner_groups[0]["id"]) if owner_groups else ""


def _partition_owner_groups_by_stream(owner_groups_or_items, request_user):
    """Partition items in each owner group into the 4 canonical streams:
    - client_school_visits
    - core_school_visits
    - cluster_meetings
    - planned_trainings
    and determine ownership flags.

    Cluster trainings are expanded into their confirmed/invited member schools
    so the Schools with Planned Training table displays real School IDs and Names
    rather than blanks or "Unknown School".
    """
    import copy
    from collections import defaultdict
    from apps.activities.models import ClusterActivityAttendance
    from apps.schools.models import School
    from apps.schools.lifecycle_models import OPERATING_STATUSES
    from apps.core.activity_types import (
        CLUSTER_MEETING_TYPES,
        TRAINING_TYPES,
        VISIT_TYPES,
    )

    if (
        isinstance(owner_groups_or_items, list)
        and owner_groups_or_items
        and not isinstance(owner_groups_or_items[0], dict)
    ):
        owner_groups = oversight.group_by_owner(owner_groups_or_items)
    else:
        owner_groups = owner_groups_or_items or []

    viewer_user_id = str(request_user.id)
    viewer_staff_profile = getattr(request_user, "staff_profile", None)
    viewer_staff_id = str(viewer_staff_profile.id) if viewer_staff_profile else ""
    viewer_name = getattr(request_user, "name", "").casefold()

    all_cluster_training_items = []

    for group in owner_groups:
        client_school_visits = []
        core_school_visits = []
        cluster_meetings = []
        planned_trainings = []

        is_group_owner = (
            str(group.get("id")) in (viewer_user_id, viewer_staff_id)
            or str(group.get("name", "")).casefold() == viewer_name
        )

        for item in group.get("items", []):
            item_owner_id = str(item.operational_owner_id or "")
            item_exec_id = str(item.executor_id or "")
            item.is_owner = (
                is_group_owner
                or item_owner_id in (viewer_user_id, viewer_staff_id)
                or item_exec_id in (viewer_user_id, viewer_staff_id)
            )

            atype = str(item.activity_type or "").lower()
            # The canonical groupings first, the ones My Plan and the family
            # strip above read (owner, 2026-09-28: "a cceo may have 300 visits
            # planned but the PL is seeing like 100"). Matching on the word
            # "training" filed every Training Follow Up VISIT under trainings,
            # so a lead read fewer visits than the officer had planned; and
            # "core" in the school type made a Core Trained school's visits
            # core visits, where My Plan (school_type == "core") does not.
            is_visit = atype in VISIT_TYPES and not item.is_in_school_training
            is_training = not is_visit and (
                item.is_in_school_training
                or atype in TRAINING_TYPES
                or (atype not in CLUSTER_MEETING_TYPES and "training" in atype)
                or bool(item.training_name and item.training_name != "—")
            )
            if is_training:
                planned_trainings.append(item)
                if item.cluster_id and (
                    not item.school_id
                    or item.school_name in ("Unknown School", "Unknown", "")
                ):
                    all_cluster_training_items.append(item)
            elif not is_visit and (
                atype in CLUSTER_MEETING_TYPES or "meeting" in atype
            ):
                cluster_meetings.append(item)
            else:
                stype = str(item.school_type or "").lower()
                if stype == "core" or atype.startswith("core_"):
                    core_school_visits.append(item)
                else:
                    client_school_visits.append(item)

        group["client_school_visits"] = client_school_visits
        group["core_school_visits"] = core_school_visits
        group["cluster_meetings"] = cluster_meetings
        group["planned_trainings"] = planned_trainings

    # Cluster activities show the people invited by member schools, not the
    # per-school figure stored on the activity. Invitation rows may override
    # the activity's default composition for an individual school.
    meeting_items = [
        item
        for group in owner_groups
        for item in group["cluster_meetings"]
        if item.activity_id
    ]
    if meeting_items:
        from apps.activities.cluster_attendance import invited_head_counts

        head_counts = invited_head_counts(
            (item.activity_id, item.cluster_id) for item in meeting_items
        )
        for item in meeting_items:
            if item.activity_id in head_counts:
                item.participants = head_counts[item.activity_id]

    # ── Expand cluster trainings to confirmed / invited member schools ──
    if all_cluster_training_items:
        act_ids = [
            item.activity_id for item in all_cluster_training_items if item.activity_id
        ]
        cluster_ids = list(
            {item.cluster_id for item in all_cluster_training_items if item.cluster_id}
        )

        att_records = list(
            ClusterActivityAttendance.objects.filter(
                activity_id__in=act_ids, invited=True
            ).values_list("activity_id", "school_id", "teachers", "leaders", "other")
        )
        att_by_act = defaultdict(list)
        invited_composition = {}
        att_school_ids = set()
        for act_id, sid, teachers, leaders, other in att_records:
            if sid not in att_by_act[act_id]:
                att_by_act[act_id].append(sid)
            if any(value is not None for value in (teachers, leaders, other)):
                invited_composition[(act_id, sid)] = (
                    (teachers or 0) + (leaders or 0) + (other or 0)
                )
            att_school_ids.add(sid)

        member_schools = list(
            School.objects.filter(
                cluster_id__in=cluster_ids, deleted_at__isnull=True
            ).select_related("district", "region", "sub_county")
        )
        schools_by_cluster = defaultdict(list)
        schools_by_cluster_confirmed = defaultdict(list)
        for s in member_schools:
            schools_by_cluster[s.cluster_id].append(s)
            if s.cluster_status == "clustered" and (
                not s.operational_status or s.operational_status in OPERATING_STATUSES
            ):
                schools_by_cluster_confirmed[s.cluster_id].append(s)

        school_lookup = {s.id: s for s in member_schools}
        missing_ids = att_school_ids - set(school_lookup.keys())
        if missing_ids:
            for s in School.objects.filter(id__in=missing_ids).select_related(
                "district", "region", "sub_county"
            ):
                school_lookup[s.id] = s

        from apps.activities.models import Activity
        from apps.budget.models import CostSetting

        act_obj_lookup = {a.id: a for a in Activity.objects.filter(id__in=act_ids)}
        # A cluster meeting feeds its participants at the cluster meals rate
        # and a cluster training at the group training meals rate (session
        # costing spec, 2026-09-26); each defaults to the seeded 5,000.
        active_meal_rates = {
            rate.key: int(rate.unit_cost)
            for rate in CostSetting.objects.filter(
                key__in=["cluster_meetings_trainings_meals", "group_training_meals"],
                catalogue__is_active=True,
            )
            if rate.unit_cost
        }
        meeting_meal_rate = active_meal_rates.get(
            "cluster_meetings_trainings_meals", 5000
        )
        training_meal_rate = active_meal_rates.get("group_training_meals", 5000)

        for group in owner_groups:
            new_planned_trainings = []
            for item in group["planned_trainings"]:
                if not (
                    item.cluster_id
                    and (
                        not item.school_id
                        or item.school_name in ("Unknown School", "Unknown", "")
                    )
                ):
                    new_planned_trainings.append(item)
                    continue

                act_id = item.activity_id
                target_schools = []
                if act_id in att_by_act and att_by_act[act_id]:
                    target_schools = [
                        school_lookup[sid]
                        for sid in att_by_act[act_id]
                        if sid in school_lookup
                    ]
                if not target_schools and item.cluster_id:
                    cid = item.cluster_id
                    target_schools = (
                        schools_by_cluster_confirmed.get(cid)
                        or schools_by_cluster.get(cid)
                        or []
                    )

                act_obj = act_obj_lookup.get(act_id)
                pps = None
                if act_obj:
                    pps = act_obj.participants_per_school or act_obj.teachers_per_school
                if not pps:
                    total_p = getattr(item, "participants", None) or (
                        act_obj.expected_participants if act_obj else None
                    )
                    if total_p and target_schools:
                        pps = max(1, total_p // len(target_schools))
                    else:
                        pps = 2
                meal_unit_rate = (
                    meeting_meal_rate
                    if act_obj and act_obj.activity_type in CLUSTER_MEETING_TYPES
                    else training_meal_rate
                )
                per_school_meal_cost = pps * meal_unit_rate

                if target_schools:
                    for s in target_schools:
                        s_item = copy.copy(item)
                        s_item.school_id = s.id
                        s_item.school_code = s.school_id or str(s.id)
                        s_item.school_name = s.name
                        s_item.school_type = getattr(s, "school_type", "") or ""
                        s_item.district_id = s.district_id
                        s_item.district_name = s.district.name if s.district_id else ""
                        s_item.region_name = (
                            s.region.name if getattr(s, "region_id", None) else ""
                        )
                        s_item.cluster_planned_from = (
                            item.cluster_name
                            or getattr(item, "cluster_planned_from", "")
                            or "Cluster Training"
                        )
                        s_item.is_cluster_invited = True
                        s_item.participants = invited_composition.get(
                            (act_id, s.id), pps
                        )
                        s_item.planned_cost = s_item.participants * meal_unit_rate
                        s_item.budget = s_item.planned_cost
                        new_planned_trainings.append(s_item)
                else:
                    fb_item = copy.copy(item)
                    fb_item.school_name = item.cluster_name or "Cluster Training"
                    fb_item.participants = pps
                    fb_item.planned_cost = item.planned_cost or per_school_meal_cost
                    fb_item.budget = item.budget or fb_item.planned_cost
                    new_planned_trainings.append(fb_item)

            group["planned_trainings"] = new_planned_trainings

    for group in owner_groups:
        grouped_dict = {}
        for item in group.get("planned_trainings", []):
            is_in_school = (
                getattr(item, "cluster_planned_from", "") == "School Visit"
                or getattr(item, "is_in_school_training", False)
                or getattr(item, "delivery_type", "") == "in-school"
                or not getattr(item, "cluster_id", None)
            )
            if is_in_school:
                category = "In-School Training"
                is_is = True
            else:
                cname = (
                    getattr(item, "cluster_planned_from", "")
                    or getattr(item, "cluster_name", "")
                    or "Cluster Training"
                )
                category = f"Cluster: {cname}"
                is_is = False
            if category not in grouped_dict:
                grouped_dict[category] = {
                    "group_name": category,
                    "is_in_school": is_is,
                    "items": [],
                }
            grouped_dict[category]["items"].append(item)
        group["planned_trainings_grouped"] = [
            dict(
                data,
                count=len(data["items"]),
                participants_total=sum(item.participants for item in data["items"]),
            )
            for data in grouped_dict.values()
        ]

    # The Salesforce ID and Evidence columns, and open work first by planned
    # date with the officer's completed work at the bottom, in every one of
    # the four tables (owner, 2026-09-26; apps.activities.completion_columns).
    # Sorted before the templates page them, so page one is the oldest open
    # work.
    from apps.activities.completion_columns import annotate, sort_completed_last

    streams = (
        "client_school_visits",
        "core_school_visits",
        "cluster_meetings",
        "planned_trainings",
    )
    annotate(item for group in owner_groups for key in streams for item in group[key])
    for group in owner_groups:
        for key in streams:
            sort_completed_last(group[key])
        for training_group in group["planned_trainings_grouped"]:
            sort_completed_last(training_group["items"])

    return owner_groups


@require_any_page_permission("team_planning_oversight", "team_targets")
def team_planning_oversight_view(request):
    """One Team Oversight workspace for planning and target performance."""
    can_view_planning = RolePermissionService.can_view_page(
        request.user, "team_planning_oversight"
    )
    can_view_targets = RolePermissionService.can_view_page(request.user, "team_targets")
    # Who the school lens is for. The brief names the Programme Lead and
    # Impact Assessment as the people who act on schools with no cluster
    # training planned, and the Country Director and Regional VP read the same
    # table over them. The Accountant reaches Team Oversight for the money in
    # the plan, not for training coverage, and gets no tab for it.
    can_view_coverage = can_view_planning and (request.user.active_role or "") in (
        COVERAGE_LENS_ROLES
    )
    # The portfolio and cluster lenses go to the people the school coverage
    # lens is for — the programme roles. The Accountant reaches Team Oversight
    # for the money in the plan, and the same reasoning that gives them no
    # coverage tab gives them no portfolio or cluster tab: those are programme
    # questions. It also keeps their page at one lens, which is why it has no
    # strip at all and why its first table row stays above the fold.
    can_view_portfolio = can_view_planning and (request.user.active_role or "") in (
        PORTFOLIO_LENS_ROLES
    )
    # IA reads the people monitors here, as tabs beside the Team Plan (owner,
    # 2026-09-30).
    can_view_monitors = can_view_planning and monitors_on_oversight(request.user)
    can_view_projects = can_view_planning and (
        monitors_on_oversight(request.user)
        or (
            getattr(request.user, "active_role", "")
            in ("ImpactAssessment", "CountryDirector", "Admin")
        )
    )
    requested_view = (request.GET.get("view") or "planning").strip().lower()
    # The people monitors moved to their own page (owner, 2026-09-29).
    if requested_view in ("monitor", "execution") and not can_view_monitors:
        return _to_planning_monitor(request, requested_view)
    if requested_view == "clusters":
        query = request.GET.copy()
        query.pop("view", None)
        destination = "/cluster-oversight/" + ("?" + query.urlencode() if query else "")
        response = redirect(destination)
        if request.headers.get("HX-Request") == "true":
            response["HX-Redirect"] = destination
        return response
    active_view = (
        requested_view
        if requested_view
        in {"targets", "coverage", "portfolio", "monitor", "projects", "execution"}
        else "planning"
    )
    if active_view == "targets" and not can_view_targets:
        active_view = "planning"
    if active_view == "coverage" and not can_view_coverage:
        active_view = "planning"
    if active_view == "portfolio" and not can_view_portfolio:
        active_view = "planning"
    if active_view == "projects" and not can_view_projects:
        active_view = "planning"
    if active_view in ("planning", "coverage", "portfolio") and not can_view_planning:
        active_view = "targets"

    available_lenses = {
        key
        for key, allowed in (
            ("planning", can_view_planning),
            ("monitor", can_view_monitors),
            ("projects", can_view_projects),
            ("execution", can_view_monitors),
            ("portfolio", can_view_portfolio),
            ("coverage", can_view_coverage),
            ("targets", can_view_targets),
        )
        if allowed
    }
    country_reader = is_country_reader(request.user)
    lens_tabs = _lens_tabs(
        TEAM_OVERSIGHT_PATH, active_view, available_lenses, country=country_reader
    )

    if active_view == "targets":
        # Do not calculate the planning, cluster and school oversight datasets
        # while the user is reviewing performance. These are independent,
        # expensive lenses and the inactive one must not delay the active one.
        from apps.frontend.views.staff_views import _team_targets_page_context

        context = {
            **_team_targets_page_context(request),
            "active_oversight_view": "targets",
            "lens_tabs": lens_tabs,
            "can_view_team_targets": can_view_targets,
            "can_view_team_planning": can_view_planning,
            "can_view_school_coverage": can_view_coverage,
            "can_view_portfolio": can_view_portfolio,
        }
        if request.headers.get("HX-Request") == "true":
            return render(request, "partials/targets/team/workspace.html", context)
        return render(request, "pages/oversight/team_planning.html", context)

    period = _period_filters(request)

    # The people monitors read the reporting line, not the period's planning
    # items, so they are answered before `build_items` as well.
    if active_view in ("monitor", "projects", "execution"):
        if active_view == "monitor":
            lens_context = _monitor_context
        elif active_view == "projects":
            lens_context = _special_projects_context
        else:
            lens_context = _execution_context
        context = {
            **period,
            **lens_context(request, period, base_url=TEAM_OVERSIGHT_PATH),
            "active_oversight_view": active_view,
            "lens_tabs": lens_tabs,
            "lens_base_url": TEAM_OVERSIGHT_PATH,
            "monitor_is_country": country_reader,
            "can_view_team_targets": can_view_targets,
            "can_view_team_planning": can_view_planning,
            "can_view_school_coverage": can_view_coverage,
            "can_view_portfolio": can_view_portfolio,
            "fy_options": fy_options(),
        }
        if request.headers.get("HX-Request") == "true":
            return render(request, _MONITOR_TEMPLATES[active_view], context)
        return render(request, "pages/oversight/team_planning.html", context)

    # The portfolio and cluster lenses stand on the school and cluster records,
    # not on the period's planning items. Answering them before `build_items`
    # keeps the expensive one out of the way: these are independent lenses, and
    # the inactive one must not delay the active one.
    if active_view == "portfolio":
        context_data = _portfolio_context(request, period, base_url=TEAM_OVERSIGHT_PATH)
        template = "partials/oversight/portfolio_workspace.html"

        context = {
            **period,
            **context_data,
            "active_oversight_view": active_view,
            "lens_tabs": lens_tabs,
            "lens_base_url": TEAM_OVERSIGHT_PATH,
            "portfolio_is_country": country_reader,
            "can_view_team_targets": can_view_targets,
            "can_view_team_planning": can_view_planning,
            "can_view_school_coverage": can_view_coverage,
            "can_view_portfolio": can_view_portfolio,
            "fy_options": fy_options(),
            "selected_program_lead": (request.GET.get("program_lead") or "").strip(),
        }
        if request.headers.get("HX-Request") == "true":
            return render(request, template, context)
        return render(request, "pages/oversight/team_planning.html", context)

    advanced = oversight.read_filters(request)
    scope = oversight.resolve_oversight_scope(request.user)
    available_items = oversight.build_items(request.user, **_plan_period(period))
    items = oversight.apply_filters(available_items, advanced)
    if active_view == "coverage":
        # The school lens: which schools have planned work in the period, which
        # have a cluster training or meeting, and which have neither (owner,
        # 2026-09-15). Same period selector, same scope, same canonical items.
        from apps.planning import coverage_service

        planned_groups, planned_totals = coverage_service.planned_schools(
            items, period=period["period"]
        )
        coverage = coverage_service.training_coverage(
            request.user,
            fy=period["fy"],
            period=period["period"],
            month=period["selected_month"] if period["period"] == "month" else None,
            quarter=period["selected_quarter"]
            if period["period"] == "quarter"
            else None,
            date_start=period["date_start"],
            date_end=period["date_end"],
            fys=_plan_period(period).get("fys"),
        )
        context = {
            **period,
            "period_label": _plan_period_label(period),
            "active_oversight_view": "coverage",
            "lens_tabs": lens_tabs,
            "lens_base_url": TEAM_OVERSIGHT_PATH,
            "can_view_team_targets": can_view_targets,
            "can_view_team_planning": can_view_planning,
            "can_view_school_coverage": can_view_coverage,
            "can_view_portfolio": can_view_portfolio,
            "lens_label": {"region": "Regional", "country": "Country", "team": "Team"}[
                "region"
                if scope.is_region
                else ("country" if scope.is_country else "team")
            ],
            "planned_groups": planned_groups,
            "planned_totals": planned_totals,
            "coverage": coverage,
            "fy_options": fy_options(),
            "coverage_url": "/team-planning-oversight/?view=coverage",
        }
        if request.headers.get("HX-Request") == "true":
            return render(
                request, "partials/oversight/coverage_workspace.html", context
            )
        return render(request, "pages/oversight/team_planning.html", context)
    # Partner work stays on Partner Monitoring (owner, 2026-09-26: "partner
    # visits should remain on the partner oversight"): the planned activities
    # tables here, their counts and their filters are the team's own work.
    # The coverage lens above still counts a school a Partner will visit.
    available_items = [i for i in available_items if not i.is_partner_work]
    items = [i for i in items if not i.is_partner_work]
    # Both the country lens and the Regional Programme Lead's region lens read
    # many Programme Leads, so both are organised in Lead tabs; only the copy
    # and the headline tiles differ (owner, 2026-09-12).
    country_lens = scope.groups_by_lead
    lens = "region" if scope.is_region else ("country" if scope.is_country else "team")
    selected = (
        (request.GET.get("program_lead") or "").strip()
        if country_lens
        else (request.GET.get("owner") or WHOLE_TEAM_TAB).strip()
    )
    if country_lens:
        sys_pls = oversight.system_program_leads()
        tabs, selected, visible = _program_lead_tabs(
            items, selected, program_leads=sys_pls
        )
    else:
        tabs, selected, visible = _team_owner_tabs(scope, items, selected)

    # A school visit, a cluster convening and a group training are read for
    # different questions, so they get a table each rather than one mixed list
    # (owner, 2026-09-17). The strip narrows what the per-CCEO groups below
    # hold; "all" is the default and keeps work that belongs to none of the
    # three — programme events, SSA and partner activities — on the page.
    activity_family = (request.GET.get("activity") or "all").strip()
    activity_tabs = oversight.activity_tabs(visible, activity_family)
    visible = oversight.in_family(visible, activity_family)

    summary = oversight.summarize(visible)
    owner_groups = oversight.group_by_owner(
        visible,
        owners=(
            oversight.program_lead_members(selected)
            if country_lens
            else _team_roster(request.user, selected)
        ),
    )
    if country_lens:
        _partition_owner_groups_by_stream(owner_groups, request.user)
        panel_groups = owner_groups
    else:
        # The team lens's own tabs choose the person, so the rows for the
        # chosen tab are one panel rather than a second strip of the same
        # people (owner, 2026-09-25). `groups` keeps the per-person filing.
        panel_groups = _partition_owner_groups_by_stream(
            [_tab_panel_group(tabs, owner_groups, visible, summary)], request.user
        )
    context = {
        **period,
        "period_label": _plan_period_label(period),
        "country_lens": country_lens,
        "is_team_lens": not country_lens,
        "tabs": tabs,
        "team_progress": _team_progress_rows(
            tabs,
            activity_family,
            own_label=f"{getattr(request.user, 'name', '') or 'My work'} (you)",
        ),
        "owner": "" if country_lens else selected,
        "program_lead": selected if country_lens else "",
        "summary": summary,
        "kpis": _kpi_items(summary, country=scope.is_country, region=scope.is_region),
        "lens": lens,
        "lens_label": {"region": "Regional", "country": "Country", "team": "Team"}[
            lens
        ],
        # With no countries assigned the region lens reads every country, and
        # the page says so and which administrator action narrows it.
        "region_unassigned": scope.is_region
        and not _resolve_user_scope(request.user).region_assigned,
        "visible_summary": summary,
        "groups": owner_groups,
        "panel_groups": panel_groups,
        "default_officer": _default_officer(owner_groups),
        "activity_tabs": activity_tabs,
        # A period change swaps only the workspace; the header's Export menu
        # comes back out of band so it follows the new period.
        "export_oob": request.headers.get("HX-Request") == "true",
        "activity_family": activity_family,
        "advanced": advanced,
        "filter_options": _filter_options(available_items),
        "fy_options": fy_options(),
        # IA and the Accountant read the plan without delegation authority.
        # The send controls are theirs to see refused, so they are not drawn:
        # a control that answers "not you" is worse than no control. The
        # country lens asks the country rule, so the CD can send from here as
        # they can from Country Planning Oversight — the two pages used to
        # disagree.
        "may_delegate": may_delegate(
            request.user, country=scope.is_country, region=scope.is_region
        ),
        # Keep flagged schools alongside the team plan.
        "flagged_schools": team_flagged_schools(
            request.user, fy=period["fy"], month=period.get("month")
        ),
        "active_oversight_view": "planning",
        "lens_tabs": lens_tabs,
        "lens_base_url": TEAM_OVERSIGHT_PATH,
        "can_view_team_targets": can_view_targets,
        "can_view_team_planning": can_view_planning,
        "can_view_school_coverage": can_view_coverage,
        "can_view_portfolio": can_view_portfolio,
        # The header link to completed work missing its evidence, drawn only
        # for readers who may open the Evidence Centre (the Accountant and the
        # RVP reach this page and may not).
        "can_open_evidence": RolePermissionService.can_view_page(
            request.user, "evidence_center"
        ),
    }

    if request.headers.get("HX-Request") == "true":
        template = (
            "partials/oversight/team_country_workspace.html"
            if country_lens
            else "partials/oversight/pl_workspace.html"
        )
        return render(request, template, context)
    return render(request, "pages/oversight/team_planning.html", context)


def _tab_panel_group(tabs, owner_groups, items, summary) -> dict:
    """The chosen team tab's work as one panel.

    One person keeps their own group, so the panel still links to their staff
    record. Whole team is everyone's rows together under the tab's name; each
    row already names its executor.
    """
    if len(owner_groups) == 1:
        return owner_groups[0]
    label = next((tab["label"] for tab in tabs if tab.get("is_active")), "")
    return {
        "id": "",
        "name": label,
        "items": list(items),
        "summary": summary,
        "page_param": "g1_page",
    }


def _team_roster(user, selected: str) -> list[dict] | None:
    """The people the team lens files work under, for the tab the lead chose.

    The lead first, then everyone who reports to them — the same roster the
    country lens reads for this lead, so a Programme Lead and their Country
    Director see one team the same way. It is what keeps each person to one
    officer tab whichever id space wrote their activities, and what gives an
    officer with nothing planned a tab that says so instead of no tab at all
    (owner, 2026-09-24: oversight mirrors each person's My Plan).

    Narrowed to the chosen person on "My Work" and on an officer's tab, so a
    tab about one person does not list everybody else as empty. None for a
    reader who leads no team, which keeps the plain grouping.
    """
    roster = oversight.program_lead_members(user.id)
    if not roster:
        return None
    if selected == WHOLE_TEAM_TAB:
        return roster
    if selected == "mine":
        return roster[:1]
    chosen = [member for member in roster if str(selected) in map(str, member["ids"])]
    return chosen or None


def _team_members(scope) -> list[dict]:
    """The supervised staff, one tab each.

    Everyone the lens reads (``scope.supervised_ids``), whatever role their
    account is switched to today (owner, 2026-10-02: "some activities are
    seen on the CCEO side but hidden from the PL"). The tabs used to keep
    only accounts whose role IN USE was CCEO, so an officer working in a
    second role had their plan in Whole team and no tab of their own.
    """
    if scope.is_country or not scope.supervised_ids:
        return []
    from apps.accounts.models import StaffProfile

    from django.db.models import Q

    rows = (
        StaffProfile.objects.filter(
            Q(id__in=scope.supervised_ids) | Q(user_id__in=scope.supervised_ids)
        )
        .select_related("user")
        .distinct()
        .order_by("user__name")
    )
    return [
        {
            "id": p.id,
            "name": getattr(p.user, "name", "") or getattr(p.user, "email", ""),
            "owner_ids": {p.id, p.user_id},
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

    # The same lens strip Team Oversight draws, so the Country Director reads
    # one format rather than a second one (owner, 2026-09-16). The country
    # reader holds every lens by definition: this route is already gated on
    # `country_planning_oversight`.
    requested_view = (request.GET.get("view") or "").strip().lower()
    if requested_view == "clusters":
        query = request.GET.copy()
        query.pop("view", None)
        destination = "/cluster-oversight/" + ("?" + query.urlencode() if query else "")
        response = redirect(destination)
        if request.headers.get("HX-Request") == "true":
            response["HX-Redirect"] = destination
        return response
    # The page opens on the planning-coverage dashboard (owner, 2026-09-28):
    # the year's obligation against the plan, by Programme Lead. The activity
    # plan it used to open on is the "Country Plan" lens, and a link carrying
    # that lens's own filters (a Lead tab, a risk, an activity type) still
    # lands there, so no bookmark changes meaning.
    if not requested_view and _names_activity_plan(request):
        requested_view = "plan"
    if requested_view == "execution":
        from apps.frontend.views.country_execution_views import execution_page

        return execution_page(request)
    if requested_view == "portfolio":
        # The country portfolio lives on the Country Map page (owner,
        # 2026-09-28); an old link keeps its filters on the way there.
        query = request.GET.copy()
        query.pop("view", None)
        destination = COUNTRY_MAP_PATH + ("?" + query.urlencode() if query else "")
        response = redirect(destination + "#country-portfolio")
        if request.headers.get("HX-Request") == "true":
            response["HX-Redirect"] = destination + "#country-portfolio"
        return response
    # The people monitors moved to their own page (owner, 2026-09-29); an old
    # link to them here opens it with the same filters.
    if requested_view == "monitor":
        return _to_planning_monitor(request, requested_view)
    if requested_view not in {"plan", "planning", "portfolio"}:
        from apps.frontend.views.country_oversight_views import coverage_page

        return coverage_page(request)
    active_view = "portfolio" if requested_view == "portfolio" else "planning"
    lens_tabs = country_lens_tabs(active_view)

    if active_view == "portfolio":
        context_data = _portfolio_context(
            request, period, base_url=COUNTRY_OVERSIGHT_PATH
        )
        template = "partials/oversight/portfolio_workspace.html"

        context = {
            **period,
            **context_data,
            "active_oversight_view": active_view,
            "lens_tabs": lens_tabs,
            "lens_base_url": COUNTRY_OVERSIGHT_PATH,
            # This route is gated on country_planning_oversight: everyone who
            # reaches it reads the country.
            "portfolio_is_country": True,
            "fy_options": fy_options(),
            "selected_program_lead": (request.GET.get("program_lead") or "").strip(),
        }
        if request.headers.get("HX-Request") == "true":
            return render(request, template, context)
        return render(request, "pages/oversight/country_planning.html", context)

    advanced = oversight.read_filters(request)
    available_items = oversight.build_items(
        request.user,
        program_lead_id=program_lead_id,
        **_plan_period(period),
    )
    items = oversight.apply_filters(available_items, advanced)

    sys_pls = oversight.system_program_leads()
    summary = oversight.summarize(items)
    groups = oversight.group_by_program_lead(items, program_leads=sys_pls)
    # Which team opens with the page. The Lead strip is a browser-side choice —
    # switching teams costs no request — and it writes itself into the URL as
    # `lead` so a paginated link inside one team's tables comes back to that
    # team. Only the team that is on screen fetches its rows; an id that names
    # no team here (a stale link, a Lead outside this period) falls back to the
    # first, which is what the strip shows in that case too.
    # `str(...)` and not `or ""`: the Unassigned fold has no id, and the panel
    # it draws compares against what `{{ group.id }}` writes, which is "None".
    selected_lead = (request.GET.get("lead") or "").strip()
    lead_ids = [str(group.get("id")) for group in groups]
    open_lead = (
        selected_lead
        if selected_lead in lead_ids
        else (lead_ids[0] if lead_ids else "")
    )
    for group in groups:
        group["autoload"] = str(group.get("id")) == open_lead
    context = {
        **period,
        "period_label": _plan_period_label(period),
        "program_lead": program_lead_id,
        "selected_lead": open_lead,
        "summary": summary,
        "kpis": _kpi_items(summary, country=True),
        "groups": groups,
        # The progress chart reads the same per-Lead folds the team rows
        # draw, one series per Programme Lead.
        "team_progress": [
            {"name": group["name"], **group["summary"]} for group in groups
        ],
        "program_leads": _system_program_leads_for_filter(sys_pls),
        "advanced": advanced,
        "filter_options": _filter_options(available_items),
        "fy_options": fy_options(),
        "active_oversight_view": "planning",
        "lens_tabs": lens_tabs,
        "lens_base_url": COUNTRY_OVERSIGHT_PATH,
        # The RVP reads this page for oversight and does not
        # delegate from it.
        "may_delegate": may_delegate(request.user, country=True),
        # The header's Export menu follows a period change out of band.
        "export_oob": request.headers.get("HX-Request") == "true",
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
        request.user,
        program_lead_id=program_lead_id,
        **_plan_period(period),
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
    """The values in the scoped period before advanced filters narrow it.

    This keeps other districts selectable while avoiding values that never
    occur in the team's work for the period. One pass collects all five: the
    country lens reads every item in the country here.
    """
    activity_types, statuses, partners, districts, risks = (set() for _ in range(5))
    for i in items:
        if i.activity_type:
            activity_types.add(i.activity_type)
        statuses.add(
            i.assignment_status if i.is_awaiting_partner_schedule else i.activity_status
        )
        if i.partner_id:
            partners.add((i.partner_id, i.partner_name))
        if i.district_id:
            districts.add((i.district_id, i.district_name))
        for r in i.risks:
            risks.add(r["key"])
    statuses.discard("")
    return {
        "activity_types": sorted(activity_types),
        "statuses": sorted(statuses),
        "partners": sorted(partners, key=lambda pair: pair[1]),
        "districts": sorted(districts, key=lambda pair: pair[1]),
        "risks": sorted(risks),
    }


def _system_program_leads_for_filter(sys_pls: list[dict]) -> list[dict]:
    """The system Program Leads, formatted for the filter dropdown.

    Driven by role, not by item data, so a PL with zero items in the period
    still appears in the filter and the IA never does.
    """
    return [{"id": pl["id"], "name": pl["name"]} for pl in sys_pls]


def _wants_excel(request) -> bool:
    """Whether the reader asked for the workbook rather than the CSV.

    Owner, 2026-09-22: "IA and PL and CD and Regional Programme Leads, and CCEO
    should be able to export all of their plans into Excel." CSV stays the
    default so every existing link, script and bookmark keeps working.
    """
    return (request.GET.get("format") or "").strip().lower() in {"xlsx", "excel"}


def _export_response(items, filename: str, *, request_user, excel: bool = False):
    """Exactly the rows the page is showing, as CSV or as a workbook.

    The items go through the same partition the page draws its four tables
    with (`_partition_owner_groups_by_stream`), so every row the page lists
    is a row of the export — a cluster training once per invited school, with
    that school's ID — and the Training Name and SSA intervention columns the
    page shows travel with it (owner, 2026-09-29). Both formats come from the
    same `export_rows`, so they can never disagree with each other.
    """
    groups = _partition_owner_groups_by_stream(list(items), request_user)
    rows = list(oversight.export_rows(oversight.stream_rows(groups)))
    headers, body = (rows[0], rows[1:]) if rows else ([], [])

    if excel:
        from apps.core.excel import workbook_response

        return workbook_response(
            filename.replace(".csv", ".xlsx"),
            [{"title": "Plan", "headers": headers, "rows": body}],
        )

    import csv

    from django.http import StreamingHttpResponse

    class _Echo:
        def write(self, value):
            return value

    writer = csv.writer(_Echo())
    response = StreamingHttpResponse(
        (writer.writerow(row) for row in rows),
        content_type="text/csv",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@require_page_permission("team_planning_oversight")
@require_export_permission
def team_planning_export_view(request):
    """The Program Lead's current view, as CSV or Excel. Same scope, same filters.

    Read by the Programme Lead, Impact Assessment, the Country Director and the
    Regional Programme Lead — each one exports the team it supervises.
    """
    period = _period_filters(request)
    items = oversight.build_items(
        request.user,
        staff_id=(request.GET.get("team_member") or "").strip() or None,
        filters=oversight.read_filters(request),
        **_plan_period(period),
    )
    scope = oversight.resolve_oversight_scope(request.user)
    if scope.is_country:
        sys_pls = oversight.system_program_leads()
        _, _, visible = _program_lead_tabs(
            items,
            (request.GET.get("program_lead") or "").strip(),
            program_leads=sys_pls,
        )
    else:
        # The export follows the tab the page shows, Whole team by default.
        _, _, visible = _team_owner_tabs(
            scope, items, (request.GET.get("owner") or WHOLE_TEAM_TAB).strip()
        )
    return _export_response(
        visible,
        f"team-planning-oversight-{period['fy']}.csv",
        request_user=request.user,
        excel=_wants_excel(request),
    )


@require_page_permission("country_planning_oversight")
@require_export_permission
def country_planning_export_view(request):
    """The country plan, as CSV or Excel, honouring the current filters."""
    period = _period_filters(request)
    items = oversight.build_items(
        request.user,
        program_lead_id=(request.GET.get("program_lead") or "").strip() or None,
        filters=oversight.read_filters(request),
        **_plan_period(period),
    )
    return _export_response(
        items,
        f"country-planning-oversight-{period['fy']}.csv",
        request_user=request.user,
        excel=_wants_excel(request),
    )


@require_any_page_permission(
    "team_planning_oversight",
    "country_planning_oversight",
    "project_monitoring",
    "projects",
)
@require_export_permission
def special_project_export_view(request, project_id: str = "all"):
    """The project table as a workbook: every project the reader follows in
    one file, or the one project asked for.

    Owner, 2026-10-04: "Add the button for export on project so the IA can
    export the project and all the schools attached to it." And 2026-10-05:
    "The IA, project coordinator or CD needs to export either all projects in
    1 file or select a project to export", with the table's columns.

    The rows are the page's own (``apps.projects.monitoring``, through the
    reader's lens and the page's filters) and the columns are the table's
    (``apps.projects.school_table``), so the file is the screen.
    """
    from django.http import Http404

    from apps.core.excel import table_download
    from apps.core.fy import get_operational_fy
    from apps.core.permissions import render_access_denied
    from apps.projects import monitoring, school_table

    # Require oversight, project_monitoring or projects access
    can_view = (
        RolePermissionService.can_view_page(request.user, "team_planning_oversight")
        or RolePermissionService.can_view_page(
            request.user, "country_planning_oversight"
        )
        or RolePermissionService.can_view_page(request.user, "project_monitoring")
        or RolePermissionService.can_view_page(request.user, "projects")
    )
    if not can_view:
        return render_access_denied(
            request, "You do not have access to special projects."
        )

    fy = (request.GET.get("fy") or "").strip() or str(get_operational_fy())
    stages = dict(monitoring.STAGE_FILTERS)
    requested_stage = (request.GET.get("stage") or "").strip()
    selected_stage = requested_stage if requested_stage in stages else ""

    result = monitoring.project_monitoring(
        request.user,
        fy=fy,
        stage=selected_stage,
        picks=monitoring.row_picks(request.GET),
    )
    _narrow_project_schools(
        result, (request.GET.get("project_status") or "schools").strip()
    )

    project_id = (project_id or "all").strip()
    single = bool(project_id) and project_id not in ("all", "export")
    projects = result.rows
    if single:
        projects = [row for row in result.rows if row.id == project_id]
        if not projects:
            raise Http404("Special project not found or not in scope.")

    return table_download(
        request,
        school_table.filename_stem(projects, fy, single=single),
        school_table.sheets(projects),
    )


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
    # The same rule the page's list uses, so every row it shows opens.
    if not oversight.record_in_scope(
        scope, activity_id=activity_id, assignment_id=assignment_id
    ):
        return None
    return item


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
    # The Unassigned group — work whose owner reports to no Programme Lead —
    # has no lead id, and its panel asks for ".../team/None". Filtering on a
    # lead called "None" returned nothing, so the Country Director and IA saw
    # the group's count and none of its rows (owner, 2026-09-28: "PL, IA and
    # CD dont see everything planned by the CCEO or Planned By PL"). It is
    # the items group_by_program_lead files there, by the same rule.
    unassigned = staff_id in ("None", "unassigned")
    if unassigned:
        lead_ids = {
            str(pid) for pl in oversight.system_program_leads() for pid in pl["ids"]
        }
        items = [
            i
            for i in oversight.build_items(request.user, **_plan_period(period))
            if not (i.supervising_pl_id and str(i.supervising_pl_id) in lead_ids)
        ]
    else:
        items = oversight.build_items(
            request.user, program_lead_id=staff_id, **_plan_period(period)
        )
    # Partner work stays on Partner Monitoring (owner, 2026-09-26), as on
    # Team Oversight: these are the team's own planned activities.
    items = [i for i in items if not i.is_partner_work]

    program_lead_name = (
        "Unassigned"
        if unassigned
        else next((i.supervising_pl_name for i in items if i.supervising_pl_name), "")
    )
    if not program_lead_name:
        from apps.accounts.models import StaffProfile

        pl = StaffProfile.objects.filter(id=staff_id).select_related("user").first()
        if pl and pl.user:
            program_lead_name = (
                getattr(pl.user, "name", "") or pl.title or "Program Lead"
            )

    owner_groups = oversight.group_by_owner(
        items,
        owners=None if unassigned else oversight.program_lead_members(staff_id),
    )
    _partition_owner_groups_by_stream(owner_groups, request.user)

    return render(
        request,
        "partials/oversight/cd_team_detail.html",
        {
            **period,
            "period_label": _plan_period_label(period),
            "staff_id": staff_id,
            "program_lead_name": program_lead_name,
            "summary": oversight.summarize(items),
            "owner_groups": owner_groups,
            "default_officer": _default_officer(owner_groups),
        },
    )


# ── Partner oversight ────────────────────────────────────────────────────────
# The Program Lead's lens on partner-delivered work. Organised by partner
# because that is the unit a supervisor chases: "has Partner X scheduled the
# four schools we gave them" is one question, not four.
@require_page_permission("partner_oversight")
def partner_oversight_view(request):
    """Partner Monitoring: one Partner's assigned schools and where each is.

    The staff-facing place to follow Partner execution (owner, 2026-09-23).
    It reads and asks; it never edits a Partner's schedule, evidence, IA
    verification, Salesforce entry or payment.
    """
    from django.http import HttpResponseForbidden

    from apps.partners.services import may_create_partner_organisation
    from apps.planning import partner_oversight_service as partner_oversight

    if not has_permission(request.user, Permission.PARTNER_MONITORING_VIEW.value):
        return HttpResponseForbidden("You do not monitor Partner work.")

    period = _period_filters(request)
    requested_partner = (request.GET.get("partner") or "all").strip() or "all"
    requested_pl = (request.GET.get("program_lead") or "").strip()

    # Built for the whole period, then narrowed in Python. The dropdown's
    # options have to come from the unfiltered set: derived from the filtered
    # one, choosing a partner would collapse the list to that partner and
    # leave no way back to any other.
    #
    # The operational year reads forward, as Cluster and Core School
    # Oversight do: a handover made in September that the Partner dates into
    # October is next year's work, and it must stay on the page reading
    # Scheduled on that date rather than vanish when it is scheduled.
    from apps.planning.fy_policy import horizon_label, planning_horizon

    plan_fys = planning_horizon(period["fy"])
    all_items = partner_oversight.build_items(
        request.user, fys=plan_fys, **_service_period(period)
    )
    # The group trainings a Partner facilitates (owner, 2026-09-26): staff
    # work, read here under that Partner, in the same scope and through the
    # same Programme Lead and team-member tabs as the Partner's own work.
    all_trainings = partner_oversight.facilitated_trainings(request.user, fys=plan_fys)
    partner_scope = _partner_scope(request.user)
    country_lens = partner_scope["is_country"]
    if country_lens:
        sys_pls = oversight.system_program_leads()
        if partner_scope.get("region_ids") is not None:
            visible_leads = {i.supervising_pl_id for i in all_items} | {
                t.supervising_pl_id for t in all_trainings
            }
            sys_pls = [p for p in sys_pls if p["id"] in visible_leads]
        program_lead_tabs, requested_pl, team_rows = _program_lead_tabs(
            [*all_items, *all_trainings], requested_pl, program_leads=sys_pls
        )
    else:
        program_lead_tabs, team_rows = [], [*all_items, *all_trainings]
    is_training = partner_oversight.FacilitatedTraining
    team_items = [i for i in team_rows if not isinstance(i, is_training)]
    team_trainings = [i for i in team_rows if isinstance(i, is_training)]

    roster = oversight.program_lead_members(
        requested_pl if country_lens else request.user.id
    )
    # Partner Monitoring (owner, 2026-09-23): one Partner at a time, never an
    # undifferentiated table of every organisation's work. The Partner tabs
    # choose the organisation (the first opens when none is chosen); the team
    # workspace below — team-member tabs, filters, KPIs and the school, cluster
    # and activity tables — reads that Partner's work alone.
    partner_pairs = sorted(
        {(i.partner_id, i.partner_name) for i in team_rows if i.partner_id},
        key=lambda pair: pair[1],
    )
    partner_tabs = [
        {
            "key": partner_key,
            "label": partner_name,
            "count": sum(1 for i in team_rows if i.partner_id == partner_key),
        }
        for partner_key, partner_name in partner_pairs
    ]
    active_partner = next(
        (entry for entry in partner_tabs if entry["key"] == requested_partner),
        partner_tabs[0] if partner_tabs else None,
    )
    for entry in partner_tabs:
        entry["is_active"] = entry is active_partner
    partner_id = active_partner["key"] if active_partner else ""
    partner_items = [i for i in team_items if partner_id and i.partner_id == partner_id]
    partner_trainings = [
        t for t in team_trainings if partner_id and t.partner_id == partner_id
    ]

    member_names = {p["id"]: p["name"] for p in roster}
    member_names.update(
        {
            i.responsible_cceo_id or "unassigned": i.responsible_cceo_name
            or "Unassigned"
            for i in [*partner_items, *partner_trainings]
        }
    )
    member = (request.GET.get("member") or "all").strip()
    if member not in member_names:
        member = "all"
    member_tabs = [
        {
            "key": "all",
            "label": "All team members",
            "count": len(partner_items) + len(partner_trainings),
        }
    ] + [
        {
            "key": key,
            "label": name,
            "count": sum(
                (i.responsible_cceo_id or "unassigned") == key
                for i in [*partner_items, *partner_trainings]
            ),
        }
        for key, name in member_names.items()
    ]
    for entry in member_tabs:
        entry["is_active"] = entry["key"] == member
    member_items = partner_oversight.filter_workspace(partner_items, member=member)
    activity_type = request.GET.get("activity_type", "")
    status = request.GET.get("status", "")
    typed_items = partner_oversight.filter_workspace(
        member_items, activity_type=activity_type
    )
    items = partner_oversight.filter_workspace(typed_items, status=status)
    trainings = partner_oversight.filter_trainings(
        partner_trainings, member=member, activity_type=activity_type, status=status
    )
    _mark_reviewable(request.user, trainings)
    partner_oversight.order_for_monitoring(items)
    # Verify & Confirm and Return (owner, 2026-09-26: "Staff (PL and CCEO, IA)
    # action buttons should have Verify and Confirm, Return"). Offered to
    # exactly the people the approved authority names (owner, 2026-09-12):
    # Impact Assessment or the activity's monitor — one permission, asked of
    # the activities waiting for verification in a single read. SSA Support is
    # confirmed through its own drawer, which also records the scores.
    from apps.activities.models import Activity
    from apps.activities.services import is_partner_ssa_support_activity

    waiting = {
        item.partner_activity_id
        for item in items
        if item.partner_activity_id
        and item.activity_status == "awaiting_ia_verification"
    }
    reviewable = {}
    if waiting:
        for activity in Activity.objects.filter(
            id__in=waiting, deleted_at__isnull=True, delivery_type="partner"
        ):
            if RolePermissionService.can_confirm_partner_activity(
                request.user, activity
            ):
                reviewable[activity.id] = is_partner_ssa_support_activity(activity)
    for item in items:
        item.can_review = item.partner_activity_id in reviewable
        item.review_is_ssa = reviewable.get(item.partner_activity_id, False)
    _lock_project_work(request.user, items)
    _prepare_core_actions(request.user, items)
    summary = partner_oversight.summarize(items)
    all_tables = partner_oversight.workspace_tables(items)
    work_tabs, work = partner_oversight.work_tabs(
        all_tables, trainings, (request.GET.get("work") or "").strip()
    )
    partner_group = None
    if active_partner:
        partner_group = {"id": partner_id, "name": active_partner["label"]}
        partner_oversight._attach_partner_identity([partner_group])

    context = {
        **period,
        "country_lens": country_lens,
        "program_lead": requested_pl,
        "program_lead_tabs": program_lead_tabs,
        "partner": partner_id,
        "partner_tabs": partner_tabs,
        "active_partner": partner_group,
        "member_tabs": member_tabs,
        "member": member,
        "activity_type": activity_type,
        "activity_types": sorted(
            {i.activity_type for i in member_items if i.activity_type}
            | {t.activity_type for t in partner_trainings if t.activity_type}
        ),
        "status": status,
        # Each status with how many of this Partner's rows it would show, so
        # the filter says what it returns before it is chosen.
        "statuses": [
            {
                "key": key,
                "count": sum(1 for i in typed_items if i.delivery_phase == key),
            }
            for key in (
                "awaiting_schedule",
                "scheduled",
                "in_progress",
                "verification",
                "completed",
                "returned",
            )
        ],
        # One kind of work a tab (owner, 2026-10-02): the tables of the open
        # tab alone, with every tab's count on the strip.
        "work_tabs": work_tabs,
        "work": work,
        "workspace_tables": [t for t in all_tables if t["tab"] == work],
        "facilitated_trainings": (
            trainings if work == partner_oversight.TAB_CLUSTERS else []
        ),
        # The years the page read, said beside the tables (FY 2026–2027 in
        # September), so a row dated next October is not a surprise.
        "plan_period_label": horizon_label(plan_fys),
        "plan_reads_forward": len(plan_fys) > 1,
        "summary": summary,
        "kpis": _partner_kpis(summary, _partner_visit_target(request.user)),
        # Requests a CCEO raised that this Program Lead has to answer. Kept
        # above the partner table because a decision somebody is waiting on
        # outranks routine monitoring.
        "withdrawal_requests": partner_oversight.withdrawal_requests(request.user),
        # Every reader of the queue sees it, but only the roles
        # `withdrawal_service.review_request` accepts are offered the decision:
        # a Regional Programme Lead, IA or the Accountant would otherwise get
        # Approve/Reject buttons that can only answer 403.
        "can_review_withdrawals": has_permission(
            request.user, Permission.PARTNER_WITHDRAWAL_REVIEW.value
        ),
        "partners": partner_pairs,
        "fy_options": fy_options(),
        "can_resolve_returns": has_permission(
            request.user, Permission.PARTNER_RETURN_RESOLVE.value
        ),
        # The export route refuses a role without data export; so does the
        # button, rather than offering a download that lands on a refusal.
        "can_export": has_permission(request.user, Permission.EXPORT.value),
        # Impact Assessment's door to adding a partner organisation: it cannot
        # open the Users page where Admin and the CD add theirs (2026-09-15).
        "can_create_partner": may_create_partner_organisation(request.user),
    }

    # The partnership work beside the delivery (owner, 2026-09-13): the
    # meetings, orientations and quality follow-ups the Programme Lead and the
    # Country Director hold with a partner, for the period's FY and the partner
    # tab in view. Only the roles that record engagements (and Admin, who
    # reads them) see the section; the officer, IA and the Accountant read
    # partner delivery here, not the partnership log.
    from apps.partners import engagement_services

    if (
        engagement_services.can_record(request.user)
        or request.user.active_role == "Admin"
    ):
        from apps.frontend.views import partner_engagement_views

        context["engagement"] = partner_engagement_views.engagement_register(
            request,
            fy=period["fy"],
            partner_id=partner_id or None,
            rows_in_fy=True,
        )
        context["engagement_show_metrics"] = True
        context["engagement_autoload"] = partner_engagement_views.autoload_drawer(
            request
        )

    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/oversight/partner_workspace.html", context)
    return render(request, "pages/oversight/partner_oversight.html", context)


def _lock_project_work(user, items) -> None:
    """Special Project handovers are their Project Coordinator's to change.

    Owner, 2026-09-24: "Schools assigned to project cannot be withdrawn by the
    staff but the project coordinator can withdraw from the partner they
    assigned to and reassign to another partner." Partner Monitoring still
    shows project work to the staff who follow the school; it draws no
    withdrawal or hand-back decision on it for anyone the project's rule
    (apps.projects.authority) refuses, and says whose decision it is instead.
    The services refuse the same people, so this is the page agreeing with
    them, not the rule itself.
    """
    from apps.projects.authority import projects_directed_by

    directed = projects_directed_by(
        user, {item.project_id for item in items if item.project_id}
    )
    for item in items:
        if item.project_id and item.project_id not in directed:
            item.project_locked = True
            item.withdrawal_label = ""


def _prepare_core_actions(user, items) -> None:
    """The Core Schools table's two decisions, for this reader.

    Owner, 2026-09-27: "The Action button drop down should include, Confirm
    completed work if they have uploaded the visit form and withdraw the school
    incase they have not schedule it."

    * Confirm completed work — once the Partner's visit form (the attendance
      register, for a training) is in. It is the same confirmation Verify &
      Confirm makes (activities.services.ia_confirm), so it is offered to the
      people that names — Impact Assessment and the work's monitor — and it
      opens once the Partner has submitted the work (the Salesforce ID is
      entered in the Verify drawer).
      Before that the entry is greyed and says what it waits for; to anyone
      who may never confirm it, it is not shown.
    * Withdraw school — only while the Partner has not scheduled it, and only
      to a role that may withdraw partner work (the service refuses the rest).
      A day a staff member put on the work is not the Partner's scheduling
      (owner, 2026-10-05: "A user scheduled for a partner and he cant
      withdraw the school from the partner. It has only view in the action
      button").
    """
    from apps.activities.models import Activity
    from apps.core.permissions import has_permission
    from apps.partners.withdrawal_models import WithdrawalKind
    from apps.planning import partner_oversight_service as partner_oversight
    from apps.planning.partner_oversight_service import STAGE_AWAITING_SCHEDULE

    core = [item for item in items if item.is_core_school_work]
    if not core:
        return
    partner_oversight.annotate_core_support(core)
    may_withdraw = bool(
        getattr(user, "is_superuser", False)
        or has_permission(user, Permission.PARTNER_ASSIGNMENT_WITHDRAW.value)
    )
    waiting = {
        item.partner_activity_id
        for item in core
        if item.evidence_ok and not item.can_review and item.partner_activity_id
    }
    confirmers = {
        activity.id
        for activity in Activity.objects.filter(id__in=waiting)
        if RolePermissionService.can_confirm_partner_activity(user, activity)
    }
    for item in core:
        # Until the Partner schedules it: a handover nobody has dated, and
        # one that carries only a day staff chose (owner, 2026-10-05).
        item.can_withdraw_school = bool(
            may_withdraw
            and item.withdrawal_label
            and not item.project_locked
            and (
                item.stage == STAGE_AWAITING_SCHEDULE
                or (
                    item.withdrawal_kind == WithdrawalKind.RECALL_SCHEDULED
                    and not item.partner_has_dated
                )
            )
        )
        if not item.evidence_ok:
            continue
        if item.can_review:
            item.can_confirm_work = True
        elif item.partner_activity_id in confirmers and not item.shows_complete:
            # The Partner submits without a Salesforce ID; whoever confirms
            # enters it in the Verify drawer (partner_review_views).
            item.confirm_block_reason = "Waiting for the partner to submit it"


def _partner_visit_target(user) -> dict | None:
    """The Partner's visit target across the reader's people (owner,
    2026-10-03: "the overflow should be the partner target"): two visits at
    each Core school and one at each Client, Core Trained and Core Graduate
    school beyond staff capacity, with how much of it is in a Partner's
    hands. The Planning Monitor's own totals, so the two pages agree; no one
    Partner is named, since any Partner may take the work. None when the
    reader has no monitor.
    """
    from apps.core.fy import get_operational_fy
    from apps.planning.planning_monitor import planning_monitor

    try:
        totals = planning_monitor(user, fy=str(get_operational_fy()))["totals"]
        if not totals.officers:
            return None
        return {
            "target": totals.partner_visit_target,
            "core": totals.core_partner_target,
            "beyond_staff": totals.partner_needed,
            "held": totals.core_partner_visits + totals.partner_schools,
        }
    except Exception:  # noqa: BLE001 - a helper line, never the page
        return None


def _partner_kpis(summary, target: dict | None = None) -> list[dict]:
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
            helper=(
                f"{summary['schools_assigned']} schools assigned"
                + (
                    f" · Partner target {target['target']:,} visits "
                    f"({target['core']:,} Core + {target['beyond_staff']:,} "
                    f"beyond staff capacity), {target['held']:,} with a Partner"
                    if target
                    else ""
                )
            ),
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
        escalation_addressee_label,
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
            # Who Escalate reaches, from the reader's reporting line.
            "escalate_to": escalation_addressee_label(request.user),
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
    # The same rule the page's list uses, so every row it shows opens.
    if not partner_oversight.assignment_in_scope(user, assignment_id):
        return None
    return item


def _partner_work_in_scope(user, source):
    """The row a withdrawal acts on: a handover, or Partner work that was
    made without one (owner, 2026-10-05). None when the reader's lens does
    not read it."""
    from apps.partners.models import PartnerAssignment
    from apps.planning import partner_oversight_service as partner_oversight

    assignment_id = (source.get("assignment_id") or "").strip()
    if assignment_id:
        return _partner_item_in_scope(user, assignment_id)
    activity_id = (source.get("activity_id") or "").strip()
    if not activity_id:
        return None
    paired = (
        PartnerAssignment.objects.filter(scheduled_activity_id=activity_id)
        .values_list("id", flat=True)
        .first()
    )
    if paired:
        return _partner_item_in_scope(user, paired)
    return partner_oversight.build_item_by_activity(user, activity_id)


def _withdrawal_preview(user, item) -> dict:
    """The preview of the record the row is: its handover's, or the Partner
    activity's own when it has none."""
    from apps.partners import withdrawal_service

    if item.partner_assignment_id:
        return withdrawal_service.preview(user, item.partner_assignment_id)
    return withdrawal_service.preview_activity(user, item.partner_activity_id)


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
            escalation = actions.escalate_to_country_director(
                sender=request.user, item=item, note=note
            )
            message = (
                f"Escalated to the {escalation.get_addressed_role_display()}. "
                "Follow it on Escalations."
            )
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
    """The current partner view, as CSV or (``format=xlsx``) as a workbook.
    Same scope, same period, same rows."""
    import csv

    from django.http import StreamingHttpResponse

    from apps.planning import partner_oversight_service as partner_oversight
    from apps.planning.fy_policy import planning_horizon

    period = _period_filters(request)
    partner_id = (request.GET.get("partner") or "").strip() or None
    if partner_id == "all":
        partner_id = None
    # The years the page reads, so the export holds the rows the page shows.
    items = partner_oversight.build_items(
        request.user,
        partner_id=partner_id,
        program_lead_id=(request.GET.get("program_lead") or "").strip() or None,
        fys=planning_horizon(period["fy"]),
        **_service_period(period),
    )

    items = partner_oversight.filter_workspace(
        items,
        member=request.GET.get("member", ""),
        activity_type=request.GET.get("activity_type", ""),
        status=request.GET.get("status", ""),
    )

    # The page's Export button asks for the workbook (owner, 2026-09-27: "It
    # should be export in excel not csv"); CSV stays the default for links.
    if _wants_excel(request):
        from apps.core.excel import workbook_response

        header, *rows = partner_oversight.export_rows(items)
        return workbook_response(
            f"partner-oversight-{period['fy']}.xlsx",
            [{"title": "Partner monitoring", "headers": list(header), "rows": rows}],
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
    item = _partner_work_in_scope(request.user, request.GET)
    if item is None:
        return render(
            request,
            "partials/oversight/withdrawal_drawer.html",
            {"preview": None},
            status=404,
        )

    from apps.partners.withdrawal_models import WithdrawalDisposition, WithdrawalReason

    preview = _withdrawal_preview(request.user, item)
    _lock_project_work(request.user, [item])
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
            # Special Project work: the drawer says whose decision it is
            # rather than offering a form the service refuses (2026-09-24).
            "project_locked": item.project_locked,
        },
    )


def _bulk_withdrawal_plan(user, assignment_ids) -> list[dict]:
    """Each ticked handover, previewed by the same functions the single
    withdrawal uses, with what confirming will do to it: withdraw, send to
    the Program Lead, or nothing and why (owner, 2026-09-29)."""
    from apps.core.exceptions import NotFoundError
    from apps.partners import withdrawal_service

    rows = []
    for assignment_id in assignment_ids:
        item = _partner_item_in_scope(user, assignment_id)
        if item is None:
            rows.append(
                {
                    "assignment_id": assignment_id,
                    "school": "",
                    "mode": "That assignment is not in your team.",
                }
            )
            continue
        _lock_project_work(user, [item])
        school = item.school_name or ""
        if item.project_locked:
            rows.append(
                {
                    "assignment_id": assignment_id,
                    "school": school,
                    "mode": (
                        f"{item.project_name or 'A Special Project'}'s work: "
                        "only its Project Coordinator can withdraw it."
                    ),
                }
            )
            continue
        try:
            preview = withdrawal_service.preview(user, assignment_id)
        except NotFoundError:
            rows.append(
                {
                    "assignment_id": assignment_id,
                    "school": school,
                    "mode": "This assignment no longer exists.",
                }
            )
            continue
        if not preview["available"]:
            mode = "It has been paid or closed and can no longer be withdrawn."
        elif _must_request(user, item, preview):
            mode = "request"
        else:
            mode = "withdraw"
        rows.append(
            {
                "assignment_id": assignment_id,
                "school": school,
                "mode": mode,
                "preview": preview,
            }
        )
    return rows


@require_page_permission("partner_oversight")
def partner_bulk_withdrawal_view(request):
    """Withdraw every ticked school from its partner (owner, 2026-09-29).

    GET previews each one and asks once for the reason, the explanation and
    what happens next; POST runs the single withdrawal for each
    (apps.partners.bulk_withdrawal) and says what happened to every school.
    """
    from apps.core.exceptions import BadRequest
    from apps.partners import bulk_withdrawal
    from apps.partners.withdrawal_models import WithdrawalDisposition, WithdrawalReason

    source = request.POST if request.method == "POST" else request.GET
    try:
        ids = bulk_withdrawal.clean_ids(source.getlist("assignment_ids"))
    except BadRequest as exc:
        if request.method == "POST":
            return _action_response(
                request, str(exc), ok=False, fallback=PARTNER_OVERSIGHT_PATH
            )
        return render(
            request,
            "partials/oversight/bulk_withdrawal_drawer.html",
            {"error": str(exc)},
            status=400,
        )
    plan = _bulk_withdrawal_plan(request.user, ids)

    if request.method == "POST":
        data = {
            "reason_category": request.POST.get("reason_category"),
            "partner_facing_reason": request.POST.get("partner_facing_reason"),
            "internal_note": request.POST.get("internal_note"),
            "disposition": request.POST.get("disposition"),
            "replacement_partner_id": request.POST.get("replacement_partner_id"),
        }
        outcomes = bulk_withdrawal.withdraw_many(
            request.user,
            [(row["assignment_id"], row["school"], row["mode"]) for row in plan],
            data,
        )
        any_done = any(o.outcome != bulk_withdrawal.SKIPPED for o in outcomes)
        message = bulk_withdrawal.summary(outcomes)
        left = [o for o in outcomes if o.outcome == bulk_withdrawal.SKIPPED]
        if left:
            message += " Not withdrawn: " + "; ".join(
                f"{o.school or 'a school'} ({o.message})" for o in left
            )
        if request.headers.get("HX-Request") != "true":
            return _action_response(
                request, message, ok=any_done, fallback=PARTNER_OVERSIGHT_PATH
            )
        if any_done:
            # Done: the drawer closes and the page reloads with the summary,
            # so the tables show where every school now stands.
            from django.contrib import messages as flash
            from django.http import HttpResponse

            flash.success(request, message)
            response = HttpResponse(status=204)
            response["HX-Trigger"] = "close-drawer"
            response["HX-Refresh"] = "true"
            return response
        # Nothing moved: the drawer stays open with each school's reason.
        return render(
            request,
            "partials/oversight/bulk_withdrawal_result.html",
            {"outcomes": outcomes, "summary": message},
        )

    from apps.partners.models import Partner

    actionable = [row for row in plan if row["mode"] in ("withdraw", "request")]
    return render(
        request,
        "partials/oversight/bulk_withdrawal_drawer.html",
        {
            "plan": plan,
            "actionable": actionable,
            "withdraw_count": sum(1 for r in plan if r["mode"] == "withdraw"),
            "request_count": sum(1 for r in plan if r["mode"] == "request"),
            "skipped": [r for r in plan if r["mode"] not in ("withdraw", "request")],
            "planned_cost": sum(r["preview"]["planned_cost"] for r in actionable),
            "budget_removed": sum(r["preview"]["budget_removed"] for r in actionable),
            "reasons": WithdrawalReason.choices,
            "dispositions": WithdrawalDisposition.choices,
            "partners": [
                {"id": p.id, "name": p.name}
                for p in Partner.objects.filter(
                    active_status=True, deleted_at__isnull=True
                ).order_by("name")[:100]
            ],
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
    if role != EdifyRole.CCEO.value:
        return False
    if preview["kind"] == WithdrawalKind.WITHDRAW_UNSCHEDULED:
        return False
    # A day staff put on the work is not the Partner's commitment (owner,
    # 2026-10-05): until the Partner dates it or starts it, the CCEO takes it
    # back themselves, as they do a handover nobody has dated.
    return not (
        preview["kind"] == WithdrawalKind.RECALL_SCHEDULED
        and not preview.get("partner_has_dated", True)
    )


@require_page_permission("partner_oversight")
@require_POST
def partner_withdrawal_submit_view(request):
    """Withdraw, or request withdrawal — the service decides which is allowed."""
    from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError
    from apps.partners import withdrawal_service

    item = _partner_work_in_scope(request.user, request.POST)
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
    # Partner work made without a handover record gets one as it is taken
    # back (withdrawal_service.withdraw_activity).
    handover_id, activity_id = item.partner_assignment_id, item.partner_activity_id

    try:
        # What the drawer called the decision, read before it is carried out
        # (a cancelled activity no longer says whose date it carried).
        label = (
            "" if requesting else _withdrawal_preview(request.user, item)["kind_label"]
        )
        if requesting:
            if handover_id:
                withdrawal_service.request_withdrawal(handover_id, data, request.user)
            else:
                withdrawal_service.request_activity_withdrawal(
                    activity_id, data, request.user
                )
            message = "Sent to your Program Lead for a decision."
        else:
            if handover_id:
                result = withdrawal_service.withdraw(handover_id, data, request.user)
            else:
                result = withdrawal_service.withdraw_activity(
                    activity_id, data, request.user
                )
            message = f"{label} — {result.get_state_display()}."
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


@require_page_permission("partner_oversight")
def partner_allowance_drawer(request):
    """§F grant drawer — more partner work at one school, with a reason."""
    from django.http import HttpResponseForbidden

    from apps.partners.models import Partner
    from apps.partners.services import ALLOWANCE_GRANT_ROLES
    from apps.schools.models import School

    if request.user.active_role not in ALLOWANCE_GRANT_ROLES:
        return HttpResponseForbidden("Granting is a CD / PL / Admin decision.")
    partners = list(
        Partner.objects.filter(deleted_at__isnull=True, active_status=True).order_by(
            "name"
        )[:200]
    )
    schools = list(
        School.objects.filter(deleted_at__isnull=True).order_by("name")[:1000]
    )
    from apps.core.fy import fy_options, get_operational_fy

    return render(
        request,
        "partials/oversight/allowance_grant_drawer.html",
        {
            "partners": partners,
            "schools": schools,
            "fy_options": fy_options(),
            "current_fy": get_operational_fy(),
            "drawer_size": "md",
        },
    )


@require_page_permission("partner_oversight")
def partner_allowance_grant_action(request):
    from django.http import HttpResponse, HttpResponseForbidden

    if request.method != "POST":
        return HttpResponseForbidden("POST required")
    try:
        from apps.partners.services import grant_partner_activity_allowance

        grant_partner_activity_allowance(
            request.user,
            {
                "partner_id": request.POST.get("partner_id"),
                "school_id": request.POST.get("school_id"),
                "fy": request.POST.get("fy"),
                "additional_activities": request.POST.get("additional_activities"),
                "reason": request.POST.get("reason"),
                "expires_at": request.POST.get("expires_at") or None,
            },
        )
    except Exception as exc:
        from apps.core.htmx_errors import error_fragment

        return error_fragment(exc, status=400)
    from apps.audit.services import log as _audit_log

    _audit_log(
        action="grant_partner_allowance",
        subject_kind="Partner",
        subject_id=str(request.POST.get("partner_id")),
        actor_id=str(request.user.id),
        actor_role=request.user.active_role,
        success=True,
        reason=f"School {request.POST.get('school_id')}: {request.POST.get('reason', '')[:150]}",
    )
    response = HttpResponse("<script>window.location.reload();</script>")
    response["HX-Trigger"] = "close-drawer"
    return response


# ── Cluster Oversight & Core Schools Oversight ─────────────────────────────
@require_page_permission("cluster_oversight")
def cluster_oversight_view(request):
    """Cluster oversight page — executive performance metrics, SSA scores and activity recency."""
    period = _period_filters(request)
    fy = period.get("fy") or get_operational_fy()
    from apps.clusters.oversight_service import cluster_oversight_table_data

    data = cluster_oversight_table_data(request.user, fy=fy)
    context = {
        **period,
        **data,
        "fy_options": fy_options(),
        "standalone_portfolio": True,
        "active_lens": "cluster_oversight",
    }
    if request.headers.get("HX-Request") == "true":
        return render(
            request,
            "partials/oversight/cluster_oversight_workspace.html",
            context,
        )
    return render(
        request,
        "pages/oversight/cluster_oversight.html",
        context,
    )


@require_page_permission("core_schools_oversight")
def core_schools_oversight_view(request):
    """Core schools oversight page — packages progress, visits/trainings status."""
    period = _period_filters(request)
    fy = period.get("fy") or get_operational_fy()
    from apps.core_schools.oversight_service import core_schools_oversight_data

    data = core_schools_oversight_data(request.user, fy=fy)
    context = {
        **period,
        **data,
        "fy_options": fy_options(),
        "standalone_portfolio": True,
        "active_lens": "core_schools_oversight",
    }
    if request.headers.get("HX-Request") == "true":
        return render(
            request,
            "partials/oversight/core_schools_oversight_workspace.html",
            context,
        )
    return render(
        request,
        "pages/oversight/core_schools_oversight.html",
        context,
    )


# ── Resolving work a Partner handed back ─────────────────────────────────────
@require_page_permission("partner_oversight")
def partner_return_resolve_drawer_view(request):
    """The governed decision on a returned assignment (owner, 2026-09-23).

    Reassign it to another Partner, have staff deliver it, or close the
    support. Scope is checked on the record exactly as the monitoring list
    checks it, and the decision itself is made — and checked again — by
    ``apps.partners.services.resolve_returned_assignment``.
    """
    from apps.partners.models import PartnerAssignment
    from apps.partners.services import assignable_partners

    item = _partner_item_in_scope(
        request.user, (request.GET.get("assignment_id") or "").strip()
    )
    allowed = has_permission(request.user, Permission.PARTNER_RETURN_RESOLVE.value)
    if item is None or not item.is_returned or not allowed:
        return render(
            request,
            "partials/oversight/resolve_return_drawer.html",
            {"item": None},
            status=404 if item is None else 403,
        )
    _lock_project_work(request.user, [item])
    if item.project_locked:
        # Project work a Partner handed back is its Project Coordinator's to
        # decide (owner, 2026-09-24); the service refuses anyone else.
        return render(
            request,
            "partials/oversight/resolve_return_drawer.html",
            {"item": item, "project_locked": True},
            status=403,
        )
    can_reassign = has_permission(
        request.user, Permission.PARTNER_ASSIGNMENT_REASSIGN.value
    )
    return render(
        request,
        "partials/oversight/resolve_return_drawer.html",
        {
            "item": item,
            "drawer_size": "md",
            "can_reassign": can_reassign,
            "partners": (
                assignable_partners().exclude(id=item.partner_id)
                if can_reassign
                else []
            ),
            "resolutions": PartnerAssignment.RESOLUTION_CHOICES,
        },
    )


@require_POST
@require_page_permission("partner_oversight")
def partner_return_resolve_submit_view(request):
    from django.http import HttpResponse

    from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError
    from apps.core.htmx_errors import error_fragment
    from apps.partners.services import resolve_returned_assignment

    try:
        result = resolve_returned_assignment(
            (request.POST.get("assignment_id") or "").strip(),
            {
                "resolution": request.POST.get("resolution"),
                "partner_id": request.POST.get("partner_id"),
                "note": request.POST.get("note"),
            },
            request.user,
        )
    except (BadRequest, ConflictError, Forbidden, NotFoundError) as exc:
        # The service's refusal, in its own words.
        return error_fragment(exc, status=400)
    if request.headers.get("HX-Request") == "true":
        response = HttpResponse(
            '<p class="pill pill-success" role="status">Decision recorded.</p>'
        )
        # The row, the Planning label and the To-Do all read the decision on
        # their next render; refresh this page so the row moves now.
        response["HX-Trigger"] = "close-drawer"
        response["HX-Refresh"] = "true"
        return response
    return _action_response(
        request,
        "Decision recorded"
        + (" — reassigned." if result.get("replacementAssignmentId") else "."),
        fallback=PARTNER_OVERSIGHT_PATH,
    )
