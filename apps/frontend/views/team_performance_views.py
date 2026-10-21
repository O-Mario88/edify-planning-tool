"""Team Performance: the FY27 Weekly Report, its sheets as tabs.

Owner, 2026-10-20: "Team performance page, replace everything there with"
the workbook — Executive Summary first and the default, then the Detailed
Country Report, Strategic Milestones, CCEO Officer Performance & Milestones,
the {Month} {Year} Summary and Core Visits & Training — every figure synced
with the database (`apps.team_performance`, docs/team-performance-report.md).
The period filter (week, month, Q1–Q4, year) shows only where a tab reads a
period.
"""

from __future__ import annotations

from django.http import QueryDict
from django.shortcuts import render

from apps.core.fy import fy_options
from apps.core.permissions import require_page_permission
from apps.team_performance import country_targets
from apps.team_performance.periods import KINDS, ReportPeriod
from apps.team_performance.report import TABS, Report

#: The filters a tab link carries over.
KEPT = ("fy", "period", "month", "quarter", "week")


def _tabs(period: ReportPeriod):
    return [
        (key, label.replace("{month}", period.month_label), reads)
        for key, label, reads in TABS
    ]


def _query(params, keep=KEPT) -> str:
    query = QueryDict(mutable=True)
    for key in keep:
        if params.get(key):
            query[key] = params[key]
    return query.urlencode()


#: The dashboard's own views, as the live sheet's dashboard tabs them.
DASHBOARD_VIEWS = (
    ("cceos", "CCEOs"),
    ("deep", "Officer Deep-Dive"),
    ("milestones", "Milestones"),
    ("regions", "Regions"),
    ("grid", "Master Grid"),
)


def _dashboard(report: Report, params) -> dict:
    views = dict(DASHBOARD_VIEWS)
    view = params.get("view") if params.get("view") in views else "cceos"
    labels = {r.label for r in report.roster.regions}
    region = params.get("region") if params.get("region") in labels else ""
    sort = params.get("sort") if params.get("sort") in report.SORTS else "name"
    officers = report.roster.officers
    officer = report.roster.officer(params.get("officer") or "")
    if officer is None and officers:
        officer = officers[0]
    board = report.cceo_board(region=region, sort=sort)
    context = {
        "dash_view": view,
        "dash_views": DASHBOARD_VIEWS,
        "dash_region": region,
        "dash_sort": sort,
        "dash_sorts": report.SORTS,
        "board": board,
        "officer": officer,
        "dash_query": _dash_query(params, region, sort, officer),
    }
    if view == "deep" and officer is not None:
        context["deep"] = report.deep_dive(officer)
    if view == "milestones":
        context["milestones"] = report.milestones()
    return context


def _dash_query(params, region, sort, officer) -> str:
    """The dashboard's links carry the resolved filters only: an officer the
    reader may not see is never echoed back."""
    query = QueryDict(_query(params), mutable=True)
    for key, value in (
        ("region", region),
        ("sort", sort),
        ("officer", officer.staff_id if officer else ""),
    ):
        if value:
            query[key] = value
    return query.urlencode()


@require_page_permission("team_performance")
def team_performance_view(request):
    params = request.GET
    period = ReportPeriod.resolve(
        params.get("fy"),
        params.get("month"),
        kind=params.get("period"),
        quarter=params.get("quarter"),
        week=params.get("week"),
    )
    tabs = _tabs(period)
    keys = {key for key, _label, _reads in tabs}
    tab = params.get("tab") if params.get("tab") in keys else "summary"
    reads = next(r for key, _label, r in tabs if key == tab)
    report = Report.build(request.user, period)
    context = {
        "tab": tab,
        "tabs": tabs,
        "reads": reads,
        "period": period,
        "kinds": KINDS,
        "fy_options": sorted(fy_options(), reverse=True),
        "roster": report.roster,
        "query": _query(params),
        "can_set_targets": country_targets.may_set(request.user),
    }
    if tab == "summary":
        context["summary"] = report.executive_summary()
    elif tab == "weekly":
        key, label, scope = report.scope(params.get("scope"))
        context.update(
            scope_key=key,
            scope_label=label,
            scopes=[(k, lbl) for k, lbl, _scope in report.scopes()],
            sections=report.weekly(scope),
        )
    elif tab == "milestones":
        context["milestones"] = report.milestones()
    elif tab == "dashboard":
        context.update(_dashboard(report, params))
    elif tab == "month":
        context["month_summary"] = report.month_summary()
        context["summary_groups"] = report.SUMMARY_GROUPS
        context["summary_width"] = sum(len(cols) for _h, cols in report.SUMMARY_GROUPS)
    else:
        context["package"] = report.core_package()
        context["core_kinds"] = (("visit", "Visits"), ("training", "Trainings"))
    return render(request, "pages/team_performance/index.html", context)


def _target_rows():
    """Every report row IA or Admin may target: the Detailed Country Report's
    tracked and untracked categories, then the Strategic Milestones rows
    (bar the SSA score, which is an average, not a target)."""
    from apps.team_performance import measures, strategic

    sections = [
        (section, [(m.key, m.label, m.unit) for m in rows])
        for section, rows in measures.weekly_sections()
    ]
    milestone_rows = [
        (
            row.key,
            f"{row.title} · {row.mode}",
            "%" if row.kind == strategic.RATE else "",
        )
        for row in strategic.ROWS
        if row.kind != strategic.SCORE
    ]
    sections.append(("Strategic Milestones", milestone_rows))
    return sections


@require_page_permission("team_performance_targets")
def country_targets_view(request):
    """Owner, 2026-10-20: "All country target should be set by either IA or
    Admin" — the editor for the report's country targets."""
    from django.contrib import messages
    from django.shortcuts import redirect

    from apps.core.exceptions import BadRequest
    from apps.team_performance.targets import TargetBook

    data = request.POST if request.method == "POST" else request.GET
    fy = ReportPeriod.resolve(data.get("fy")).fy
    book = TargetBook.load(fy)
    sections = _target_rows()
    keys = [key for _section, rows in sections for key, _label, _unit in rows]
    error = ""
    posted = {}
    if request.method == "POST":
        try:
            posted = _posted_targets(request, keys)
        except BadRequest as exc:
            error = str(exc)
    if request.method == "POST" and not error:
        try:
            rows = {}
            for key in keys:
                if f"annual:{key}" not in posted:
                    continue
                months = {
                    m: country_targets.parse(posted.get(f"m{m}:{key}"))
                    for m in country_targets.MONTHS
                }
                rows[key] = (
                    country_targets.parse(posted.get(f"annual:{key}")),
                    months,
                )
            changed = country_targets.save(request.user, fy, rows)
        except BadRequest as exc:
            error = _named(str(exc), sections)
        else:
            messages.success(
                request,
                f"{changed} country target{'s' if changed != 1 else ''} saved for FY {fy}.",
            )
            return redirect(f"{request.path}?fy={fy}")
    saved = book.country
    period = ReportPeriod.resolve(fy)
    table = []
    for section, rows in sections:
        lines = []
        for key, label, unit in rows:
            current = saved.get(key) or {}
            months = current.get("months") or {}
            if f"annual:{key}" in posted:
                annual_value = posted.get(f"annual:{key}", "")
                month_values = [
                    posted.get(f"m{m}:{key}", "") for m in country_targets.MONTHS
                ]
            else:
                annual_value = _plain(current.get("annual"))
                month_values = [_plain(months.get(m)) for m in country_targets.MONTHS]
            lines.append(
                {
                    "key": key,
                    "label": label,
                    "unit": unit,
                    "annual": annual_value,
                    "months": list(zip(country_targets.MONTHS, month_values)),
                    "source": current.get("source", ""),
                }
            )
        table.append((section, lines))
    return render(
        request,
        "pages/team_performance/country_targets.html",
        {
            "fy": fy,
            "fy_options": sorted(fy_options(), reverse=True),
            "table": table,
            "month_names": [label[:3] for _m, label in period.month_options()],
            "error": error,
        },
    )


#: The JSON bundle's ceiling: every row's thirteen boxes, with room to spare.
MAX_PAYLOAD_FIELDS = 5000


def _posted_targets(request, keys) -> dict[str, str]:
    """The boxes a save sent. js/country-targets.js sends them all as one JSON
    field (`payload`), past Django's per-request field limit; without the
    script they come as ordinary fields of the same names. Only a known row's
    `annual:` and `m1:`–`m12:` boxes are read."""
    from apps.core.exceptions import BadRequest

    wanted = {f"annual:{k}" for k in keys} | {
        f"m{m}:{k}" for k in keys for m in range(1, 13)
    }
    raw = request.POST.get("payload")
    if raw:
        import json

        try:
            values = json.loads(raw)
        except ValueError as exc:
            raise BadRequest(
                "The targets could not be read; nothing was saved."
            ) from exc
        if not isinstance(values, dict) or len(values) > MAX_PAYLOAD_FIELDS:
            raise BadRequest("The targets could not be read; nothing was saved.")
    else:
        values = request.POST
    return {
        name: "" if values.get(name) is None else str(values.get(name))
        for name in wanted
        if name in values and isinstance(values.get(name), (str, int, float))
    }


def _named(message: str, sections) -> str:
    """An error about a row, worded with the row's name, not its key."""
    for _section, rows in sections:
        for key, label, _unit in rows:
            if message.startswith(f"{key}:"):
                return f"{label}{message[len(key) :]}"
    return message


def _plain(value) -> str:
    """A saved figure as typed: 1500000, 12.5 — never 1.5e+06."""
    if value is None:
        return ""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")
