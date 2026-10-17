"""Core School Oversight: the Core schools analysed, for the reader's scope.

Owner, 2026-10-17, the Core School Intelligence brief (10-11): a CCEO reads
their own Core schools, a Programme Lead their team grouped by CCEO,
sub-region or district, the country roles their country; the page is
analysis, planning stays on My Plan and Planning Oversight. Every figure is
`apps.core_schools.intelligence`, the reading the Core School Profile uses,
and the figures are defined in docs/core-school-intelligence-metrics.md.
"""

from __future__ import annotations

import csv

from django.http import HttpResponse
from django.shortcuts import render

from apps.core.fy import fy_options, get_operational_fy
from apps.core.permissions import RolePermissionService, require_page_permission
from apps.core_schools import intelligence

TABS = (
    ("schools", "Schools"),
    ("groups", "Groups"),
    ("attention", "Attention"),
    ("champion", "Champion Readiness"),
)
TRAJECTORY_FILTERS = {
    "improved": "Improved",
    "declined": "Declined",
    "no_change": "No Change",
    "maintained_strong": "Maintained Strong",
    "not_comparable": "Not Compared",
}
SORTS = {
    "name": ("School", lambda r: r.name.lower()),
    "latest": ("Latest SSA, lowest first", lambda r: (r.ssa_now is None, r.ssa_now)),
    "change": (
        "SSA change, largest decline first",
        lambda r: (r.ssa_change is None, r.ssa_change),
    ),
    "package": (
        "Package, least complete first",
        lambda r: (r.package_pct is None, r.package_pct),
    ),
    "attendance": (
        "Attendance, lowest first",
        lambda r: (r.attendance_rate is None, r.attendance_rate),
    ),
}
CSV_HEADERS = (
    "School ID",
    "School",
    "Type",
    "District",
    "Sub-region",
    "Cluster",
    "CCEO",
    "Latest SSA",
    "Previous SSA",
    "SSA Change",
    "Trajectory",
    "Weakest Intervention",
    "Visits Done",
    "Visits Target",
    "Trainings Done",
    "Trainings Target",
    "Package",
    "Partner Hand-overs Assigned",
    "Partner Hand-overs Scheduled",
    "Partner Hand-overs Completed",
    "Sessions Invited",
    "Sessions Attended",
    "Attendance %",
    "Teacher Attendances",
    "Leader Attendances",
    "Enrolment Change",
    "Learning Change (pts)",
    "Champion Readiness",
    "Attention",
)


def _choice(request, key: str, options, default: str) -> str:
    value = (request.GET.get(key) or "").strip()
    return value if value in options else default


def _filtered(rows, request) -> list:
    trajectory = _choice(request, "trajectory", TRAJECTORY_FILTERS, "")
    reason = _choice(request, "attention", intelligence.ATTENTION_ORDER, "")
    readiness = _choice(request, "readiness", intelligence.CHAMPION_ORDER, "")
    district = (request.GET.get("district") or "").strip()
    school_type = (request.GET.get("type") or "").strip()
    q = (request.GET.get("q") or "").strip().lower()
    return [
        r
        for r in rows
        if (not trajectory or r.trajectory == trajectory)
        and (not reason or reason in r.attention)
        and (not readiness or r.champion == readiness)
        and (not district or r.district == district)
        and (not school_type or r.school_type == school_type)
        and (not q or q in r.name.lower() or q in r.code.lower())
    ]


def _dash(value) -> str:
    return "" if value is None else str(value)


def _csv(rows, fy: str) -> HttpResponse:
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="core-school-oversight-fy{fy}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(CSV_HEADERS)
    for r in rows:
        writer.writerow(
            [
                r.code,
                r.name,
                r.type_label,
                r.district,
                r.sub_region,
                r.cluster,
                r.owner,
                _dash(r.ssa_now),
                _dash(r.ssa_before),
                _dash(r.ssa_change),
                r.trajectory_label,
                r.weakest_label,
                r.visits_done if r.has_plan else "",
                r.visits_target if r.has_plan else "",
                r.trainings_done if r.has_plan else "",
                r.trainings_target if r.has_plan else "",
                r.package_label,
                r.handovers_assigned,
                r.handovers_scheduled,
                r.handovers_completed,
                r.invited,
                r.attended,
                _dash(r.attendance_rate),
                _dash(r.teacher_attendances),
                _dash(r.leader_attendances),
                _dash(r.enrol_change),
                _dash(r.learn_change),
                r.champion,
                "; ".join(r.attention),
            ]
        )
    return response


@require_page_permission("core_schools_oversight")
def core_schools_oversight_view(request):
    options = sorted(fy_options(), reverse=True)
    fy = _choice(request, "fy", options, get_operational_fy())
    schools = list(intelligence.scoped_core_schools(request.user))
    every = sorted(
        intelligence.performance(schools, fy=fy).values(),
        key=lambda r: r.name.lower(),
    )
    rows = _filtered(every, request)
    can_export = RolePermissionService.can_export(request.user, request.path)

    if request.GET.get("format") == "csv":
        if not can_export:
            from apps.core.permissions import render_access_denied

            return render_access_denied(
                request, "Your role does not include data export."
            )
        return _csv(rows, fy)

    sort = _choice(request, "sort", SORTS, "name")
    rows = sorted(rows, key=SORTS[sort][1])
    tab = _choice(request, "tab", dict(TABS), "schools")
    group = _choice(request, "group", intelligence.GROUPINGS, "cceo")
    query = request.GET.copy()
    for key in ("tab", "page", "format"):
        query.pop(key, None)
    return render(
        request,
        "pages/oversight/core_schools_oversight.html",
        {
            "fy": fy,
            "fy_options": options,
            "rows": rows,
            "summary": intelligence.summarise(rows),
            "scope_schools": len(every),
            "tab": tab,
            "tabs": TABS,
            "group": group,
            "groupings": intelligence.GROUPINGS,
            "grouped": intelligence.groups(rows, group) if tab == "groups" else [],
            "attention": [
                {"reason": reason, "rows": [r for r in rows if reason in r.attention]}
                for reason in intelligence.ATTENTION_ORDER
            ]
            if tab == "attention"
            else [],
            "readiness": [
                {"status": status, "rows": [r for r in rows if r.champion == status]}
                for status in intelligence.CHAMPION_ORDER
            ]
            if tab == "champion"
            else [],
            "districts": sorted({r.district for r in every if r.district}),
            "types": sorted({(r.school_type, r.type_label) for r in every}),
            "trajectory_filters": TRAJECTORY_FILTERS,
            "attention_filters": intelligence.ATTENTION_ORDER,
            "readiness_filters": intelligence.CHAMPION_ORDER,
            "sorts": {key: label for key, (label, _k) in SORTS.items()},
            "selected": {
                "trajectory": request.GET.get("trajectory", ""),
                "attention": request.GET.get("attention", ""),
                "readiness": request.GET.get("readiness", ""),
                "district": request.GET.get("district", ""),
                "type": request.GET.get("type", ""),
                "q": request.GET.get("q", ""),
                "sort": sort,
            },
            "query": query.urlencode(),
            "can_export": can_export,
        },
    )
