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

from django.shortcuts import render
from django.utils.html import escape
from django.views.decorators.http import require_POST

from apps.core.fy import fy_options, get_operational_fy
from apps.core.metrics import DataState, MetricValue, render_kpi_item
from apps.core.permissions import (
    RolePermissionService,
    require_any_page_permission,
    require_export_permission,
    require_page_permission,
)
from apps.clusters.oversight_service import grouped_clusters
from apps.planning.flagged_schools import team_flagged_schools
from apps.planning import oversight_actions
from apps.planning import oversight_service as oversight
from apps.planning.action_service import ActionError


# Where a no-JavaScript send returns to when the Referer cannot be trusted.
# Each page falls back to itself: bouncing a Country Director to the Program
# Lead's page would be a scope change dressed up as a redirect.
TEAM_OVERSIGHT_PATH = "/team-planning-oversight/"
COUNTRY_OVERSIGHT_PATH = "/country-planning-oversight/"
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


# ── Program Lead ─────────────────────────────────────────────────────────────
def _items_owned_by(items, owner_ids) -> list:
    """Staff and partner work attributed to one person, in either id space."""
    ids = {value for value in owner_ids if value}
    return [
        item
        for item in items
        if item.operational_owner_id in ids
        or item.managing_staff_id in ids
        or item.planned_by_id in ids
    ]


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
        ("portfolio", "Country Portfolio" if country else "Team Portfolio"),
        ("clusters", "Cluster Performance"),
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


def _cluster_performance_context(request, period: dict, *, base_url: str) -> dict:
    """The cluster lens — activity, planning, SSA and reach, most active first."""
    from apps.planning.cluster_performance_service import (
        ACTIVE_SHARE,
        QUIET_SHARE,
        WEIGHT_SESSION,
        WEIGHT_SSA,
        WEIGHT_VISIT,
        cluster_performance,
    )

    performance = cluster_performance(
        request.user,
        fy=period["fy"],
        program_lead_id=(request.GET.get("program_lead") or "").strip() or None,
    )
    totals = performance["totals"]
    return {
        "cluster_performance": performance,
        "cluster_totals": totals,
        "cluster_leads": performance["leads"],
        "selected_program_lead": (request.GET.get("program_lead") or "").strip(),
        "cluster_performance_url": f"{base_url}?view=clusters",
        # The weighting is on the page. A ranking whose arithmetic nobody can
        # read is a ranking nobody can argue with, which is worse than a rough
        # one they can.
        "cluster_index_note": (
            f"Activity index = {WEIGHT_SESSION}× cluster sessions + "
            f"{WEIGHT_VISIT}× member-school visits + "
            f"{WEIGHT_SSA}× member schools assessed."
        ),
        "cluster_band_note": (
            f"High activity is at or above {round(ACTIVE_SHARE * 100)}% of the "
            f"busiest cluster's index; low activity at or below "
            f"{round(QUIET_SHARE * 100)}%."
        ),
        "kpis": _cluster_kpis(totals),
    }


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


def _team_owner_tabs(scope, items, selected: str) -> tuple[list[dict], str, list]:
    """Whole team, My Work, then one tab per supervised officer.

    Whole team comes first and is the default (Programme Lead alignment,
    2026-09-13): leading a team starts from the team, and opening on "My Work"
    showed a lead with no portfolio of their own an empty page. The officer
    tabs stay so a lead can narrow to one person; the fund-approval "View Full
    Plan" link still lands on that officer, whichever id space it carries.
    """
    members = _team_members(scope)
    own_items = _items_owned_by(items, scope.own_ids)
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
    for member in members:
        member_items = _items_owned_by(items, member["owner_ids"])
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


def _program_lead_tabs(items, selected: str | None) -> tuple[list[dict], str, list]:
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
    # The country portfolio reads every school under its lead and its CCEO, so
    # it goes to the people who hold the country: the same readers the school
    # coverage lens is for. Cluster performance is scoped by
    # `cluster_queryset`, so a Programme Lead sees their own clusters in it and
    # a country role sees the country — everyone who reads this page gets it.
    can_view_portfolio = can_view_planning and (request.user.active_role or "") in (
        PORTFOLIO_LENS_ROLES
    )
    requested_view = (request.GET.get("view") or "planning").strip().lower()
    active_view = (
        requested_view
        if requested_view in {"targets", "coverage", "portfolio", "clusters"}
        else "planning"
    )
    if active_view == "targets" and not can_view_targets:
        active_view = "planning"
    if active_view == "coverage" and not can_view_coverage:
        active_view = "planning"
    if active_view == "portfolio" and not can_view_portfolio:
        active_view = "planning"
    if (
        active_view in ("planning", "coverage", "portfolio", "clusters")
        and not can_view_planning
    ):
        active_view = "targets"

    available_lenses = {
        key
        for key, allowed in (
            ("planning", can_view_planning),
            ("portfolio", can_view_portfolio),
            ("clusters", can_view_planning),
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

    # The portfolio and cluster lenses stand on the school and cluster records,
    # not on the period's planning items. Answering them before `build_items`
    # keeps the expensive one out of the way: these are independent lenses, and
    # the inactive one must not delay the active one.
    if active_view in ("portfolio", "clusters"):
        builder = (
            _portfolio_context
            if active_view == "portfolio"
            else _cluster_performance_context
        )
        context = {
            **period,
            **builder(request, period, base_url=TEAM_OVERSIGHT_PATH),
            "active_oversight_view": active_view,
            "lens_tabs": lens_tabs,
            "lens_base_url": TEAM_OVERSIGHT_PATH,
            "portfolio_is_country": country_reader,
            "can_view_team_targets": can_view_targets,
            "can_view_team_planning": can_view_planning,
            "can_view_school_coverage": can_view_coverage,
            "can_view_portfolio": can_view_portfolio,
            "fy_options": fy_options(),
        }
        template = (
            "partials/oversight/portfolio_workspace.html"
            if active_view == "portfolio"
            else "partials/oversight/cluster_performance_workspace.html"
        )
        if request.headers.get("HX-Request") == "true":
            return render(request, template, context)
        return render(request, "pages/oversight/team_planning.html", context)

    advanced = oversight.read_filters(request)
    scope = oversight.resolve_oversight_scope(request.user)
    items = oversight.build_items(
        request.user, filters=advanced, **_service_period(period)
    )
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
        )
        context = {
            **period,
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
        tabs, selected, visible = _program_lead_tabs(items, selected)
    else:
        tabs, selected, visible = _team_owner_tabs(scope, items, selected)

    summary = oversight.summarize(visible)
    context = {
        **period,
        "country_lens": country_lens,
        "is_team_lens": not country_lens,
        "tabs": tabs,
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
        "groups": oversight.group_by_owner(visible),
        "advanced": advanced,
        "filter_options": _filter_options(items),
        "fy_options": fy_options(),
        # IA and the Accountant read this page for Cluster Oversight below.
        # The send controls are theirs to see refused, so they are not drawn:
        # a control that answers "not you" is worse than no control. The
        # country lens asks the country rule, so the CD can send from here as
        # they can from Country Planning Oversight — the two pages used to
        # disagree.
        "may_delegate": may_delegate(
            request.user, country=scope.is_country, region=scope.is_region
        ),
        "cluster_oversight": grouped_clusters(request.user),
        # §12's Team School Oversight, as a section rather than a page: plans,
        # clusters and flagged schools are three lenses on one team, and a
        # supervisor should not visit three pages to answer one question.
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


def _team_members(scope) -> list[dict]:
    """The supervised staff, for the team-member filter."""
    if scope.is_country or not scope.supervised_ids:
        return []
    from apps.accounts.models import StaffProfile
    from apps.core.rbac import EdifyRole

    from django.db.models import Q

    rows = (
        StaffProfile.objects.filter(
            Q(id__in=scope.supervised_ids) | Q(user_id__in=scope.supervised_ids),
            user__active_role=EdifyRole.CCEO.value,
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
    requested_view = (request.GET.get("view") or "planning").strip().lower()
    active_view = (
        requested_view if requested_view in {"portfolio", "clusters"} else "planning"
    )
    lens_tabs = _lens_tabs(
        COUNTRY_OVERSIGHT_PATH, active_view, {"planning", "portfolio", "clusters"}
    )

    if active_view in ("portfolio", "clusters"):
        builder = (
            _portfolio_context
            if active_view == "portfolio"
            else _cluster_performance_context
        )
        context = {
            **period,
            **builder(request, period, base_url=COUNTRY_OVERSIGHT_PATH),
            "active_oversight_view": active_view,
            "lens_tabs": lens_tabs,
            "lens_base_url": COUNTRY_OVERSIGHT_PATH,
            # This route is gated on country_planning_oversight: everyone who
            # reaches it reads the country.
            "portfolio_is_country": True,
            "fy_options": fy_options(),
        }
        template = (
            "partials/oversight/portfolio_workspace.html"
            if active_view == "portfolio"
            else "partials/oversight/cluster_performance_workspace.html"
        )
        if request.headers.get("HX-Request") == "true":
            return render(request, template, context)
        return render(request, "pages/oversight/country_planning.html", context)

    advanced = oversight.read_filters(request)
    items = oversight.build_items(
        request.user,
        program_lead_id=program_lead_id,
        filters=advanced,
        **_service_period(period),
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
        "active_oversight_view": "planning",
        "lens_tabs": lens_tabs,
        "lens_base_url": COUNTRY_OVERSIGHT_PATH,
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
        request.user,
        program_lead_id=program_lead_id,
        **_service_period(period),
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
        "districts": sorted(
            {(i.district_id, i.district_name) for i in items if i.district_id},
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
        **_service_period(period),
    )
    scope = oversight.resolve_oversight_scope(request.user)
    if scope.is_country:
        _, _, visible = _program_lead_tabs(
            items, (request.GET.get("program_lead") or "").strip()
        )
    else:
        # The export follows the tab the page shows, Whole team by default.
        _, _, visible = _team_owner_tabs(
            scope, items, (request.GET.get("owner") or WHOLE_TEAM_TAB).strip()
        )
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
        **_service_period(period),
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
    items = oversight.build_items(
        request.user, program_lead_id=staff_id, **_service_period(period)
    )

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
    from apps.partners.services import may_create_partner_organisation
    from apps.planning import partner_oversight_service as partner_oversight

    period = _period_filters(request)
    requested_partner = (request.GET.get("partner") or "all").strip() or "all"
    requested_pl = (request.GET.get("program_lead") or "").strip()

    # Built for the whole period, then narrowed in Python. The dropdown's
    # options have to come from the unfiltered set: derived from the filtered
    # one, choosing a partner would collapse the list to that partner and
    # leave no way back to any other.
    all_items = partner_oversight.build_items(request.user, **_service_period(period))
    country_lens = _partner_scope(request.user)["is_country"]
    if country_lens:
        program_lead_tabs, requested_pl, team_items = _program_lead_tabs(
            all_items, requested_pl
        )
    else:
        program_lead_tabs, team_items = [], all_items

    partner_pairs = sorted(
        {(i.partner_id, i.partner_name) for i in team_items if i.partner_id},
        key=lambda pair: pair[1],
    )
    partner_tabs = [
        {
            "key": "all",
            "label": "All Partners",
            "count": len(team_items),
        }
    ] + [
        {
            "key": partner_id,
            "label": partner_name,
            "count": len([i for i in team_items if i.partner_id == partner_id]),
        }
        for partner_id, partner_name in partner_pairs
    ]
    active_partner = next(
        (entry for entry in partner_tabs if entry["key"] == requested_partner),
        partner_tabs[0],
    )
    for entry in partner_tabs:
        entry["is_active"] = entry is active_partner
    partner_id = active_partner["key"]
    items = (
        team_items
        if partner_id == "all"
        else [i for i in team_items if i.partner_id == partner_id]
    )
    summary = partner_oversight.summarize(items)

    context = {
        **period,
        "country_lens": country_lens,
        "program_lead": requested_pl,
        "program_lead_tabs": program_lead_tabs,
        "partner": partner_id,
        "partner_tabs": partner_tabs,
        "summary": summary,
        "kpis": _partner_kpis(summary),
        "groups": partner_oversight.group_by_partner(items),
        # Requests a CCEO raised that this Program Lead has to answer. Kept
        # above the partner groups because a decision somebody is waiting on
        # outranks routine monitoring.
        "withdrawal_requests": partner_oversight.withdrawal_requests(request.user),
        "partners": partner_pairs,
        "fy_options": fy_options(),
        "can_grant_allowance": request.user.active_role
        in ("CountryDirector", "Program Lead", "Admin"),
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
            partner_id=None if partner_id == "all" else partner_id,
            rows_in_fy=True,
        )
        context["engagement_show_metrics"] = True
        context["engagement_autoload"] = partner_engagement_views.autoload_drawer(
            request
        )

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
    """The current partner view, as CSV. Same scope, same period, same rows."""
    import csv

    from django.http import StreamingHttpResponse

    from apps.planning import partner_oversight_service as partner_oversight

    period = _period_filters(request)
    partner_id = (request.GET.get("partner") or "").strip() or None
    if partner_id == "all":
        partner_id = None
    items = partner_oversight.build_items(
        request.user,
        partner_id=partner_id,
        program_lead_id=(request.GET.get("program_lead") or "").strip() or None,
        **_service_period(period),
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
