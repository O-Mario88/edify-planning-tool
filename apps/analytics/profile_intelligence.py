"""Profile intelligence: one engine behind every profile.

Owner, 2026-10-09, a 34-point brief: "Build a unified, FY-aware Profile
Intelligence System across District, Sub-region, Program Lead, Staff,
Cluster, Partner and School profiles ... Profiles must not create duplicate
sources of truth. Every aggregate metric must drill into the underlying
records and reconcile with lower-level profiles", and then "start the profile
work".

A profile is a *scope* (the schools it speaks for, worked out from the
authoritative relationship: a district's schools, a cluster's members, a
person's portfolio) read through the same sections:

* **portfolio** — the schools by type, their clusters, staff and partners,
  enrolment, and the schools with no SSA or no plan this year;
* **ssa** — each intervention last year, this year, the change and what the
  change is called; the same for every cluster in the scope;
* **rankings** — the schools and the clusters at the top and at the bottom,
  with the figures they were ranked by;
* **execution** — visits, trainings and cluster meetings: in the plan, done,
  still to do;
* **projects** — the projects working in the scope;
* **attention** — what the scope's owner should look at first.

Nothing here is stored and nothing is counted a second way:

* a school is one that is operating (`schools.lifecycle_service`);
* a year's SSA score is the latest confirmed record of that year
  (`ssa.year_comparison`), and "improved"/"declined" is the one rule
  (`ssa.change_rules`);
* a visit, a training and a cluster meeting are the type groups of
  `core.activity_types`, and in the plan / not started / done are its status
  groups;
* a school waiting for a Partner's date is an open hand-over
  (`PartnerAssignment.UNSCHEDULED_STATUSES`).

Every figure names the schools behind it: `school_rows(..., show=)` lists
them, so a number on the page opens its records.

A scope is a function each: a school, a cluster, a district, a sub-region,
a staff member's own portfolio, a Programme Lead's whole team, a Partner's
assigned schools, the country. Owner, 2026-10-09: "Work on all profiles in a
sequential order ... Integrate cluster management into all the profiles that
has anything to do with cluster. Don't forget country profile which includes
all analysis."

Larger scopes are also read by their parts (`groups`): a country by its
sub-regions, districts and staff, a team by its people — the same rows and
the same ranking rule, so a part's line here is its own profile's figure.

Cluster Management (`apps.clusters`: attendance register, Cluster Health and
Impact, maturity) is read for the clusters of any scope by
`cluster_management`, on the tab that shows it, so a profile that never opens
its Clusters tab does not pay for it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from django.db.models import Count, Q, Sum

from apps.core.activity_types import (
    CLUSTER_MEETING_TYPES,
    COMPLETED_WORK_STATUSES,
    NOT_IN_PLAN_ACTIVITY_STATUSES,
    NOT_STARTED_ACTIVITY_STATUSES,
    TRAINING_TYPES,
    VISIT_TYPES,
)

__all__ = [
    "GROUPS",
    "RANKING_METHOD",
    "SHOW_LABELS",
    "Scope",
    "build",
    "cluster_management",
    "cluster_scope",
    "country_scope",
    "district_scope",
    "finance",
    "groups",
    "INTERVENTION_METHOD",
    "MOVERS_METHOD",
    "partner_scope",
    "people",
    "period_options",
    "period_window",
    "program_lead_scope",
    "school_rows",
    "school_scope",
    "staff_scope",
    "students",
    "sub_region_scope",
    "summary",
]

#: The SSA score the programme works towards: the top of the scale (owner,
#: 2026-10-09: "SSA score target is 10 not 6"). The SSA Performance page's
#: 6.0 is that page's own line for a district that needs attention, not this.
SSA_TARGET = 10.0

_VISITS = tuple(getattr(t, "value", t) for t in VISIT_TYPES)
_TRAININGS = tuple(getattr(t, "value", t) for t in TRAINING_TYPES)
_MEETINGS = tuple(getattr(t, "value", t) for t in CLUSTER_MEETING_TYPES)

#: How many schools and clusters each ranking shows.
RANKED = 5

#: Said on the page beside every ranking, so nobody has to ask why a school
#: is first (the brief, point 7).
RANKING_METHOD = (
    "Ranked by the average confirmed SSA score of the year shown; where two "
    "are level, the bigger change since the year before comes first, then "
    "the name. A school or cluster with no confirmed SSA in the year is not "
    "ranked."
)

#: The lists a figure opens (`school_rows(show=)`).
SHOW_LABELS = {
    "all": "All schools",
    "no_ssa": "No SSA this year",
    "unplanned": "Nothing planned this year",
    "improved": "SSA improved",
    "declined": "SSA declined",
    "awaiting_partner": "Awaiting a partner's date",
}

_CHANGE_LABELS = {
    "improved": "Improved",
    "declined": "Declined",
    "no_change": "No change",
    "maintained_strong": "Maintained strong",
    # One of the two years has no confirmed SSA, so there is nothing to
    # compare yet.
    "not_comparable": "No comparison yet",
}
_CHANGE_TONES = {
    "improved": "success",
    "declined": "danger",
    "no_change": "",
    "maintained_strong": "success",
    "not_comparable": "",
}


@dataclass(frozen=True)
class Scope:
    """Whose profile this is, and the schools it speaks for."""

    kind: str
    key: str
    name: str
    #: What the numbers cover, in the reader's words ("All schools in the
    #: district"): shown on the page so nobody misreads them.
    covers: str
    #: The operating schools of the scope, as a queryset.
    schools: object
    #: Narrows the work read to the scope's own (a Partner's profile counts
    #: the work the Partner delivers, not everything at its schools). None
    #: reads all work at the scope's schools and clusters.
    work: object = None
    #: The Partner whose hand-overs the profile follows, on a Partner's.
    partner_id: str = ""


def _operating():
    from apps.schools.lifecycle_service import active_schools

    return active_schools()


def district_scope(district) -> Scope:
    return Scope(
        kind="district",
        key=district.id,
        name=f"{district.name} District",
        covers="All schools in the district",
        schools=_operating().filter(district=district),
    )


def sub_region_scope(sub_region) -> Scope:
    return Scope(
        kind="sub_region",
        key=sub_region.id,
        name=f"{sub_region.name} Sub-region",
        covers="All schools in the sub-region",
        # A school's sub-region is its district's (`geography.District`): the
        # school's own column is a copy that an upload does not fill, and a
        # profile read from it alone counted no school at all (2026-10-10).
        schools=_operating().filter(
            Q(district__sub_region_id=sub_region.id)
            | Q(district__sub_region__isnull=True, sub_region_id=sub_region.id)
        ),
    )


def country_scope(country: str = "") -> Scope:
    schools = _operating()
    if country:
        # A school the upload could not place has no region: it is still the
        # country's (deployments are one country each).
        schools = schools.filter(Q(region__country=country) | Q(region__isnull=True))
    return Scope(
        kind="country",
        key=country or "country",
        name=country or "Country",
        covers="Every school in the country",
        schools=schools,
    )


def cluster_scope(cluster) -> Scope:
    return Scope(
        kind="cluster",
        key=cluster.id,
        name=cluster.name,
        covers="Cluster schools",
        schools=_operating().filter(cluster_id=cluster.id),
    )


def school_scope(school) -> Scope:
    from apps.schools.models import School

    return Scope(
        kind="school",
        key=school.id,
        name=school.name,
        covers="Single school",
        # The school itself, operating or closed: a closed school's profile
        # still tells what happened there. (Every wider scope counts
        # operating schools only.)
        schools=School.objects.filter(id=school.id, deleted_at__isnull=True),
    )


def _identities(profile_ids) -> set[str]:
    """Staff ids and their user ids: a school's holder is written as either
    (`core.scoping.owner_ids`)."""
    from apps.accounts.models import StaffProfile

    ids = {str(i) for i in profile_ids if i}
    users = StaffProfile.objects.filter(id__in=ids).values_list("user_id", flat=True)
    return ids | {str(u) for u in users if u}


def staff_scope(staff_profile) -> Scope:
    """One person's own portfolio: the schools they hold."""
    user = staff_profile.user
    return Scope(
        kind="staff",
        key=staff_profile.id,
        name=user.name or user.email,
        covers="Own portfolio",
        schools=_operating().filter(
            account_owner_id__in=_identities([staff_profile.id])
        ),
    )


def program_lead_scope(staff_profile) -> Scope:
    """A Programme Lead's profile is the whole team's: the Lead's schools and
    those of everyone who reports to them (the brief, point 20: "It should
    not be interpreted as only schools directly assigned to the PL")."""
    from apps.planning.training_ceilings import team_profiles

    team = [staff_profile.id, *[p.id for p in team_profiles(staff_profile.id)]]
    user = staff_profile.user
    return Scope(
        kind="program_lead",
        key=staff_profile.id,
        name=user.name or user.email,
        covers="Entire team portfolio",
        schools=_operating().filter(account_owner_id__in=_identities(team)),
    )


def partner_scope(partner) -> Scope:
    """The schools assigned to the Partner and not taken back, and the work
    the Partner itself delivers."""
    from apps.partners.models import PartnerAssignment

    held = (
        PartnerAssignment.objects.filter(partner=partner, school__isnull=False)
        .exclude(status__in=PartnerAssignment.RELEASED_STATUSES)
        .values("school_id")
    )
    return Scope(
        kind="partner",
        key=partner.id,
        name=partner.name,
        covers="Assigned portfolio",
        schools=_operating().filter(id__in=held),
        work=Q(assigned_partner_id=partner.id),
        partner_id=partner.id,
    )


# ── Reading the scope ───────────────────────────────────────────────────────
def _schools(scope: Scope) -> list[dict]:
    rows = list(
        scope.schools.values(
            "id",
            "school_id",
            "name",
            "school_type",
            "cluster_id",
            "enrollment",
            "account_owner_id",
            "district_id",
            "district__name",
            "district__sub_region_id",
            "sub_region_id",
            "sub_county_id",
        ).order_by("name", "id")
    )
    for row in rows:
        # The district's sub-region, else the school's own copy of it.
        row["sub_region"] = row.pop("district__sub_region_id") or row["sub_region_id"]
    return rows


def _change(previous, current, *, book, intervention=None) -> dict:
    """The change between two scores and what the one rule calls it."""
    from apps.core.enums import SsaIntervention
    from apps.ssa import change_rules

    if previous is None or current is None:
        verdict = {"classification": change_rules.NOT_COMPARABLE, "delta": None}
    elif intervention:
        verdict = change_rules.change_between(
            previous, current, intervention, rule=book.rule(intervention, "")
        )
    else:
        verdict = change_rules.school_change(
            round(float(current) - float(previous), 2),
            [value for value, _label in SsaIntervention.choices],
            book=book,
        )
    key = verdict["classification"]
    return {
        "change": verdict["delta"],
        "status": key,
        "status_label": _CHANGE_LABELS.get(key, key),
        "tone": _CHANGE_TONES.get(key, ""),
    }


def _mean(values) -> float | None:
    values = [float(v) for v in values if v is not None]
    return round(sum(values) / len(values), 2) if values else None


#: How a profile names its best and its struggling SSA intervention, said on
#: the page beside them (the brief, 2026-10-10: "Do not simply select the
#: lowest absolute score if another intervention is declining sharply. Use a
#: transparent ranking methodology").
INTERVENTION_METHOD = (
    "Best performing is the intervention that rose most since the previous "
    "year by the improvement rule; where none rose, the highest score this "
    "year. Struggling is the intervention that declined most since the "
    "previous year; where none declined, the lowest score this year, and of two "
    "level ones the one that rose least. An intervention with no confirmed "
    "score this year is not ranked."
)
#: How the improving and the declining lists are made.
MOVERS_METHOD = (
    "Improving and declining are read by the change in average confirmed SSA "
    "score since the previous year, by the one improvement rule; the biggest "
    "change comes first. One with no score in either year is in neither list."
)


def _intervention_picks(rows) -> tuple[dict | None, dict | None]:
    """The best performing and the struggling intervention of ``rows``
    (`INTERVENTION_METHOD`), each with ``basis``: "change" when the change
    chose it, "score" when this year's score did."""
    measured = [row for row in rows if row["current"] is not None]
    if not measured:
        return None, None
    improved = [row for row in measured if row["status"] == "improved"]
    if improved:
        best = dict(
            max(improved, key=lambda r: (r["change"], r["current"])), basis="change"
        )
    else:
        best = dict(
            max(measured, key=lambda r: (r["current"], r["change"] or 0)),
            basis="score",
        )
    # The struggling one is never the best one: where every intervention
    # moved alike (or only one declined and it is also the highest), it is
    # read among the others.
    others = [row for row in measured if row["key"] != best["key"]]
    if not others:
        # One intervention measured: it is not its own opposite.
        return best, None
    declined = [row for row in others if row["status"] == "declined"]
    if declined:
        struggling = dict(
            min(declined, key=lambda r: (r["change"], r["current"])), basis="change"
        )
    else:
        struggling = dict(
            min(others, key=lambda r: (r["current"], r["change"] or 0)),
            basis="score",
        )
    return best, struggling


def _movers(rows) -> tuple[list[dict], list[dict]]:
    """The rows that improved most and those that declined most
    (`MOVERS_METHOD`), up to `RANKED` of each."""
    improving = sorted(
        (row for row in rows if row["status"] == "improved"),
        key=lambda r: (-r["change"], r["name"].casefold()),
    )[:RANKED]
    declining = sorted(
        (row for row in rows if row["status"] == "declined"),
        key=lambda r: (r["change"], r["name"].casefold()),
    )[:RANKED]
    return (
        [dict(row, rank=index + 1) for index, row in enumerate(improving)],
        [dict(row, rank=index + 1) for index, row in enumerate(declining)],
    )


def _rank(rows) -> tuple[list[dict], list[dict]]:
    """The top and the bottom of the rows that have a score this year."""
    scored = [row for row in rows if row["current"] is not None]
    scored.sort(
        key=lambda r: (-r["current"], -(r["change"] or 0), r["name"].casefold())
    )
    best = [dict(row, rank=index + 1) for index, row in enumerate(scored[:RANKED])]
    # The bottom is read from the other end and never repeats the top: a
    # scope of six schools has five best and one worst, not five and five.
    tail = scored[RANKED:][-RANKED:]
    worst = [
        dict(row, rank=len(scored) - index) for index, row in enumerate(reversed(tail))
    ]
    return best, worst


# ── The part of the year a profile reads ────────────────────────────────────
#: The year's months in order (1 October to 30 September).
_MONTHS = (
    "Oct",
    "Nov",
    "Dec",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
)
_QUARTERS = {"Q1": "Oct–Dec", "Q2": "Jan–Mar", "Q3": "Apr–Jun", "Q4": "Jul–Sep"}
PERIOD_YEAR = ""


def period_options() -> list[tuple[str, str]]:
    """The periods a profile can be read by (the brief, point 30: "FY | Q1 |
    Q2 | Q3 | Q4 | Month"): the whole year, a quarter, a month."""
    return [
        (PERIOD_YEAR, "Full year"),
        *[(key, f"{key} ({months})") for key, months in _QUARTERS.items()],
        *[(f"M{index + 1}", name) for index, name in enumerate(_MONTHS)],
    ]


def period_window(fy, period: str):
    """``(first day, day after the last, label)`` of a period of ``fy``;
    ``(None, None, "")`` for the whole year or a period that is not one."""
    from apps.core.fy import get_month_date_range, get_quarter_date_range

    fy = str(fy)
    if period in _QUARTERS:
        start, end = get_quarter_date_range(fy, period)
        return start.date(), end.date(), f"{period} ({_QUARTERS[period]})"
    if period.startswith("M") and period[1:].isdigit() and 1 <= int(period[1:]) <= 12:
        start, end = get_month_date_range(fy, int(period[1:]))
        return start.date(), end.date(), f"{_MONTHS[int(period[1:]) - 1]} {start.year}"
    return None, None, ""


def _in_window(work, window):
    """Work whose day falls in the window: the planned day, else the day it
    was scheduled for."""
    start, end = window[0], window[1]
    if start is None:
        return work
    return work.filter(
        Q(planned_date__gte=start, planned_date__lt=end)
        | Q(
            planned_date__isnull=True,
            scheduled_date__date__gte=start,
            scheduled_date__date__lt=end,
        )
    )


def _activities(scope: Scope, cluster_ids, fy, window=(None, None, "")):
    """The year's work in the scope that is in somebody's plan: at one of its
    schools, or a session of one of its clusters; on a Partner's profile,
    the work that Partner delivers."""
    from apps.activities.models import Activity

    work = Activity.objects.filter(
        Q(school_id__in=scope.schools.values("id"))
        | Q(school__isnull=True, cluster_id__in=list(cluster_ids)),
        fy=str(fy),
        deleted_at__isnull=True,
    ).exclude(status__in=NOT_IN_PLAN_ACTIVITY_STATUSES)
    work = _in_window(work, window)
    return work.filter(scope.work) if scope.work is not None else work


def _execution(scope: Scope, cluster_ids, fy, window=(None, None, "")) -> dict:
    from django.utils import timezone

    today = timezone.localdate()
    done = Q(status__in=COMPLETED_WORK_STATUSES)
    waiting = Q(status__in=NOT_STARTED_ACTIVITY_STATUSES)
    past = Q(planned_date__lt=today) | Q(
        planned_date__isnull=True, scheduled_date__date__lt=today
    )
    work = _activities(scope, cluster_ids, fy, window)

    def figures(types, **extra) -> dict:
        rows = work.filter(activity_type__in=types)
        counts = rows.aggregate(
            planned=Count("id"),
            completed=Count("id", filter=done),
            not_started=Count("id", filter=waiting),
            overdue=Count("id", filter=waiting & past),
            by_partner=Count("id", filter=Q(delivery_type="partner")),
            schools=Count("school_id", distinct=True),
            schools_done=Count("school_id", filter=done, distinct=True),
            **extra,
        )
        counts["outstanding"] = counts["planned"] - counts["completed"]
        counts["by_staff"] = counts["planned"] - counts["by_partner"]
        counts["upcoming"] = counts["not_started"] - counts["overdue"]
        return counts

    return {
        "visits": figures(_VISITS),
        "trainings": figures(
            _TRAININGS, group_sessions=Count("id", filter=Q(school__isnull=True))
        ),
        "meetings": figures(_MEETINGS),
    }


def _work_by_place(
    scope: Scope, cluster_ids, fy, window=(None, None, "")
) -> tuple[dict, dict]:
    """The year's visits and trainings at each school, and the sessions of
    each cluster: ``{school id: {"visits", "visits_done", "trainings",
    "trainings_done"}}`` and ``{cluster id: {"meetings", "meetings_done",
    "trainings", "trainings_done"}}``. One query each, so a row of any table
    can say what was planned and what was done there."""
    done = Q(status__in=COMPLETED_WORK_STATUSES)
    visit, training, meeting = (
        Q(activity_type__in=_VISITS),
        Q(activity_type__in=_TRAININGS),
        Q(activity_type__in=_MEETINGS),
    )
    work = _activities(scope, cluster_ids, fy, window)
    schools = {
        row["school_id"]: row
        for row in work.filter(school_id__isnull=False)
        .values("school_id")
        .annotate(
            visits=Count("id", filter=visit),
            visits_done=Count("id", filter=visit & done),
            trainings=Count("id", filter=training),
            trainings_done=Count("id", filter=training & done),
            teachers=Sum("teachers_attended", filter=training & done),
            leaders=Sum("leaders_attended", filter=training & done),
        )
    }
    for row in schools.values():
        row["teachers"] = row["teachers"] or 0
        row["leaders"] = row["leaders"] or 0
    # Teachers and school leaders recorded for a school at a completed group
    # training are trained too (`people`): the register is the record.
    for school_id, teachers, leaders in _register(scope, fy, window, _TRAININGS):
        row = schools.setdefault(school_id, {"school_id": school_id, **_NO_WORK})
        row["teachers"] += teachers or 0
        row["leaders"] += leaders or 0
    clusters = {
        row["cluster_id"]: row
        for row in work.filter(school__isnull=True, cluster_id__isnull=False)
        .values("cluster_id")
        .annotate(
            meetings=Count("id", filter=meeting),
            meetings_done=Count("id", filter=meeting & done),
            trainings=Count("id", filter=training),
            trainings_done=Count("id", filter=training & done),
        )
    }
    return schools, clusters


_NO_WORK = {
    "visits": 0,
    "visits_done": 0,
    "trainings": 0,
    "trainings_done": 0,
    # Teachers and school leaders trained: at the school's own completed
    # trainings and, by the register, at completed group trainings.
    "teachers": 0,
    "leaders": 0,
}


def _sessions(fy, window):
    """The year's completed sessions that are not at one school: group
    trainings and cluster meetings."""
    from apps.activities.models import Activity

    return _in_window(
        Activity.objects.filter(
            status__in=COMPLETED_WORK_STATUSES,
            school__isnull=True,
            fy=str(fy),
            deleted_at__isnull=True,
        ),
        window,
    )


def _register(scope: Scope, fy, window, types):
    """``(school id, teachers, leaders)`` for each of the scope's schools
    recorded as attending a completed session of ``types``. One query."""
    from apps.activities.models import ClusterActivityAttendance

    return (
        ClusterActivityAttendance.objects.filter(
            school_id__in=scope.schools.values("id"),
            attended=True,
            activity_id__in=_sessions(fy, window)
            .filter(activity_type__in=types)
            .values("id"),
        )
        .values_list("school_id")
        .annotate(teachers=Sum("teachers"), leaders=Sum("leaders"))
        .values_list("school_id", "teachers", "leaders")
    )


def _work_of(rows, work: dict) -> dict:
    """The visits and trainings at ``rows``' schools, added up."""
    total = dict(_NO_WORK)
    for row in rows:
        at = work.get(row["id"])
        if at:
            for key in total:
                total[key] += at[key]
    return total


def _projects(scope: Scope, fy, window, scores: dict, book) -> list[dict]:
    """The projects working in the scope: the scope's schools on each, the
    project's whole size against the capacity its coordinator set for the
    people who add schools to it, the year's project work at these schools —
    in the plan and completed — and how those schools' SSA has moved."""
    from apps.activities.models import Activity
    from apps.projects.models import ProjectSchoolAssignment, ProjectStaffCapacity

    here: dict[str, dict] = {}
    for project_id, name, status, school_id in (
        ProjectSchoolAssignment.objects.filter(school_id__in=scope.schools.values("id"))
        .values_list("project_id", "project__name", "project__status", "school_id")
        .order_by("project__name", "project_id")
    ):
        row = here.setdefault(
            project_id, {"id": project_id, "name": name, "status": status, "ids": set()}
        )
        row["ids"].add(school_id)
    if not here:
        return []
    on_project = dict(
        ProjectSchoolAssignment.objects.filter(project_id__in=list(here))
        .values_list("project_id")
        .annotate(n=Count("school_id", distinct=True))
    )
    capacity: dict[str, int] = defaultdict(int)
    for project_id, maximum in ProjectStaffCapacity.objects.filter(
        project_id__in=list(here)
    ).values_list("project_id", "max_schools"):
        capacity[project_id] += maximum
    work = _in_window(
        Activity.objects.filter(
            project_id__in=list(here),
            school_id__in=scope.schools.values("id"),
            fy=str(fy),
            deleted_at__isnull=True,
        ).exclude(status__in=NOT_IN_PLAN_ACTIVITY_STATUSES),
        window,
    )
    done = {
        row["project_id"]: row
        for row in work.values("project_id").annotate(
            planned=Count("id"),
            completed=Count("id", filter=Q(status__in=COMPLETED_WORK_STATUSES)),
        )
    }
    rows = []
    for project_id, row in here.items():
        ids = row.pop("ids")
        mine = [scores[i] for i in ids if i in scores]
        previous = _mean(r["previous"] for r in mine)
        current = _mean(r["current"] for r in mine)
        total = on_project.get(project_id, 0)
        limit = capacity.get(project_id)
        rows.append(
            {
                **row,
                "project_status": str(row["status"] or "").replace("_", " ").title(),
                "schools": len(ids),
                "project_schools": total,
                "capacity": limit,
                "capacity_left": max(limit - total, 0) if limit is not None else None,
                "planned": done.get(project_id, {}).get("planned", 0),
                "completed": done.get(project_id, {}).get("completed", 0),
                "improved": sum(1 for r in mine if r["status"] == "improved"),
                "declined": sum(1 for r in mine if r["status"] == "declined"),
                "previous": previous,
                "current": current,
                **_change(previous, current, book=book),
            }
        )
    return rows


def build(scope: Scope, fy=None, period: str = PERIOD_YEAR) -> dict:
    """Everything a profile page draws for ``scope`` in ``fy`` (the latest
    year with a confirmed SSA in the scope when none is named). ``period``
    narrows the work read — visits, trainings, meetings, project work and
    "nothing planned" — to a quarter or a month of the year (`period_window`);
    SSA is a yearly reading and is not narrowed."""
    from apps.clusters.models import Cluster
    from apps.core.enums import SchoolType
    from apps.partners.models import PartnerAssignment
    from apps.ssa import year_comparison
    from apps.ssa.change_rules import RULE_SENTENCE, RuleBook

    school_ids = scope.schools.values("id")
    fy = str(fy or year_comparison.latest_measured_fy(school_ids))
    window = period_window(fy, period or "")
    schools = _schools(scope)
    by_id = {school["id"]: school for school in schools}
    book = RuleBook()

    # ── SSA ────────────────────────────────────────────────────────────────
    comparison = year_comparison.intervention_comparison(school_ids, fy)
    for row in comparison["rows"]:
        row.update(
            _change(row["previous"], row["current"], book=book, intervention=row["key"])
        )
        # What is left to the target; 0 once it is reached.
        row["to_target"] = (
            round(max(SSA_TARGET - row["current"], 0), 2)
            if row["current"] is not None
            else None
        )
    overall = _change(comparison["previous"], comparison["current"], book=book)
    scores = year_comparison.school_year_scores(school_ids, fy)

    cluster_ids = sorted({s["cluster_id"] for s in schools if s["cluster_id"]})
    school_work, cluster_work = _work_by_place(scope, cluster_ids, fy, window)
    school_scores = []
    for school in schools:
        score = scores.get(school["id"], {})
        school_scores.append(
            {
                "id": school["id"],
                "school_id": school["school_id"],
                "name": school["name"],
                "cluster_id": school["cluster_id"],
                "enrollment": school["enrollment"],
                **(
                    school_work.get(school["id"])
                    and {key: school_work[school["id"]][key] for key in _NO_WORK}
                    or _NO_WORK
                ),
                "previous": score.get("previous"),
                "current": score.get("current"),
                **_change(score.get("previous"), score.get("current"), book=book),
            }
        )

    # ── Clusters ───────────────────────────────────────────────────────────
    cluster_names = dict(
        Cluster.objects.filter(id__in=cluster_ids, deleted_at__isnull=True).values_list(
            "id", "name"
        )
    )
    members: dict[str, list[dict]] = defaultdict(list)
    for row in school_scores:
        if row["cluster_id"] in cluster_names:
            members[row["cluster_id"]].append(row)
    clusters = []
    for cluster_id, name in cluster_names.items():
        rows = members.get(cluster_id, [])
        previous = _mean(r["previous"] for r in rows)
        current = _mean(r["current"] for r in rows)
        clusters.append(
            {
                "id": cluster_id,
                "name": name,
                "schools": len(rows),
                "assessed": sum(1 for r in rows if r["current"] is not None),
                "previous": previous,
                "current": current,
                **_change(previous, current, book=book),
                # Visits at its schools here, and the cluster's own sessions.
                "visits": _work_of(rows, school_work)["visits"],
                "visits_done": _work_of(rows, school_work)["visits_done"],
                "teachers": _work_of(rows, school_work)["teachers"],
                "leaders": _work_of(rows, school_work)["leaders"],
                "enrollment": sum(r["enrollment"] or 0 for r in rows),
                "meetings": cluster_work.get(cluster_id, {}).get("meetings", 0),
                "meetings_done": cluster_work.get(cluster_id, {}).get(
                    "meetings_done", 0
                ),
                "group_trainings": cluster_work.get(cluster_id, {}).get("trainings", 0),
                "group_trainings_done": cluster_work.get(cluster_id, {}).get(
                    "trainings_done", 0
                ),
            }
        )
    clusters.sort(key=lambda row: (row["name"].casefold(), row["id"]))

    # ── Portfolio ──────────────────────────────────────────────────────────
    labels = dict(SchoolType.choices)
    type_counts: dict[str, int] = defaultdict(int)
    for school in schools:
        type_counts[school["school_type"]] += 1
    planned_ids = set(
        _activities(scope, (), fy, window)
        .filter(school_id__isnull=False)
        .values_list("school_id", flat=True)
        .distinct()
    )
    handovers = PartnerAssignment.objects.filter(school_id__in=school_ids)
    if scope.partner_id:
        handovers = handovers.filter(partner_id=scope.partner_id)
    awaiting = set(
        handovers.filter(status__in=PartnerAssignment.UNSCHEDULED_STATUSES)
        .values_list("school_id", flat=True)
        .distinct()
    )
    # Assigned is not scheduled is not completed (the brief, point 15): the
    # hand-overs still with a Partner, by where each stands.
    held = handovers.exclude(status__in=PartnerAssignment.RELEASED_STATUSES)
    pipeline = held.aggregate(
        assigned=Count("id"),
        awaiting=Count(
            "id", filter=Q(status__in=PartnerAssignment.UNSCHEDULED_STATUSES)
        ),
        completed=Count("id", filter=Q(status=PartnerAssignment.STATUS_COMPLETED)),
    )
    pipeline["scheduled"] = (
        pipeline["assigned"] - pipeline["awaiting"] - pipeline["completed"]
    )
    flags = {
        "no_ssa": {s["id"] for s in school_scores if s["current"] is None},
        "unplanned": set(by_id) - planned_ids,
        "improved": {s["id"] for s in school_scores if s["status"] == "improved"},
        "declined": {s["id"] for s in school_scores if s["status"] == "declined"},
        "awaiting_partner": awaiting & set(by_id),
    }
    portfolio = {
        "schools": len(schools),
        "types": [
            {"key": value, "label": labels[value], "count": type_counts.get(value, 0)}
            for value, _label in SchoolType.choices
            if type_counts.get(value)
        ],
        "clusters": len(cluster_names),
        "clustered_schools": sum(
            1 for s in schools if s["cluster_id"] in cluster_names
        ),
        "staff": len({s["account_owner_id"] for s in schools if s["account_owner_id"]}),
        "enrollment": sum(s["enrollment"] or 0 for s in schools),
        "districts": len({s["district_id"] for s in schools if s["district_id"]}),
        "handovers": pipeline,
        "assessed": len(schools) - len(flags["no_ssa"]),
        **{key: len(ids) for key, ids in flags.items()},
    }
    portfolio["cluster_coverage"] = (
        round(portfolio["clustered_schools"] * 100 / len(schools)) if schools else 0
    )

    # ── Rankings and attention ─────────────────────────────────────────────
    best_schools, worst_schools = _rank(school_scores)
    best_clusters, worst_clusters = _rank(clusters)
    improving_schools, declining_schools = _movers(school_scores)
    improving_clusters, declining_clusters = _movers(clusters)
    best_intervention, struggling_intervention = _intervention_picks(comparison["rows"])
    execution = _execution(scope, cluster_ids, fy, window)
    _expected(execution, schools, school_work)
    measured = [row for row in comparison["rows"] if row["current"] is not None]
    attention = [
        item
        for item in (
            _attention(
                portfolio["no_ssa"],
                "school has no confirmed SSA",
                "schools have no confirmed SSA",
                f"in {comparison['label']}",
                "schools",
                "no_ssa",
            ),
            _attention(
                portfolio["unplanned"],
                "school has nothing planned",
                "schools have nothing planned",
                f"in {comparison['label']}",
                "schools",
                "unplanned",
            ),
            _attention(
                portfolio["declined"],
                "school's SSA declined",
                "schools' SSA declined",
                f"since {comparison['previous_label']}",
                "schools",
                "declined",
            ),
            # A cluster's own profile says its decline once, as its schools'.
            scope.kind != "cluster"
            and _attention(
                sum(1 for row in clusters if row["status"] == "declined"),
                "cluster's SSA declined",
                "clusters' SSA declined",
                f"since {comparison['previous_label']}",
                "clusters",
                "",
            ),
            _attention(
                portfolio["awaiting_partner"],
                "school is waiting for a partner's date",
                "schools are waiting for a partner's date",
                "",
                "schools",
                "awaiting_partner",
            ),
            _attention(
                execution["meetings"]["overdue"],
                "cluster meeting is past its date and not held",
                "cluster meetings are past their date and not held",
                "",
                "activities",
                "",
                "meetings_overdue",
            ),
            _attention(
                execution["visits"]["overdue"],
                "visit is past its date and not done",
                "visits are past their date and not done",
                "",
                "activities",
                "",
                "visits_overdue",
            ),
        )
        if item
    ]
    return {
        "scope": scope,
        "fy": fy,
        "fy_label": comparison["label"],
        "previous_label": comparison["previous_label"],
        "portfolio": portfolio,
        "ssa": {
            **comparison,
            "overall": overall,
            "strongest": max(measured, key=lambda r: r["current"], default=None),
            "weakest": min(measured, key=lambda r: r["current"], default=None),
            # The interventions that moved most (the brief, point 18): named
            # by the change itself, and only where the one rule calls it an
            # improvement or a decline — not merely the highest or lowest.
            "most_improved": max(
                (r for r in comparison["rows"] if r["status"] == "improved"),
                key=lambda r: r["change"],
                default=None,
            ),
            "most_declined": min(
                (r for r in comparison["rows"] if r["status"] == "declined"),
                key=lambda r: r["change"],
                default=None,
            ),
            "best": best_intervention,
            "struggling": struggling_intervention,
            "method": INTERVENTION_METHOD,
            "rule": RULE_SENTENCE,
            # The score the programme works towards, what is left to it, and
            # the schools there.
            "target": SSA_TARGET,
            "to_target": (
                round(max(SSA_TARGET - comparison["current"], 0), 2)
                if comparison["current"] is not None
                else None
            ),
            "at_target": sum(
                1
                for row in school_scores
                if row["current"] is not None and row["current"] >= SSA_TARGET
            ),
        },
        "clusters": clusters,
        "rankings": {
            "best_schools": best_schools,
            "worst_schools": worst_schools,
            "best_clusters": best_clusters,
            "worst_clusters": worst_clusters,
            "improving_schools": improving_schools,
            "declining_schools": declining_schools,
            "improving_clusters": improving_clusters,
            "declining_clusters": declining_clusters,
            "method": RANKING_METHOD,
            "movers_method": MOVERS_METHOD,
        },
        "execution": execution,
        "projects": _projects(
            scope, fy, window, {row["id"]: row for row in school_scores}, book
        ),
        "period": period if window[0] else PERIOD_YEAR,
        "period_label": window[2],
        "attention": attention,
        # Kept for `school_rows`, so a list is the figure it was opened from.
        "_schools": schools,
        "_scores": {row["id"]: row for row in school_scores},
        "_flags": flags,
        "_cluster_names": cluster_names,
        "_school_work": school_work,
    }


def _expected(execution: dict, schools: list[dict], school_work: dict) -> None:
    """What the year asks of the scope's schools, added to the visit and the
    training figures: the visits and trainings each school's type is due
    (`planning.country_oversight.rules.requirement_for`: a Core school two
    and two from staff and from a partner, a Client, Core Trained or Core
    Graduate school one of each, a Champion none), the schools that are due
    any, and how many of those have one completed or in the plan."""
    from apps.planning.country_oversight import rules

    # A cluster meeting is the cluster's, not a school's yearly due.
    execution["meetings"].update(
        expected=None, schools_due=None, coverage=None, plan_coverage=None
    )
    for key, due_of, planned, done in (
        ("visits", lambda r: r.visits, "visits", "visits_done"),
        ("trainings", lambda r: r.trainings, "trainings", "trainings_done"),
    ):
        expected = due = reached = in_plan = 0
        for school in schools:
            ask = due_of(rules.requirement_for(school["school_type"]))
            if not ask:
                continue
            expected += ask
            due += 1
            at = school_work.get(school["id"]) or {}
            reached += 1 if at.get(done) else 0
            in_plan += 1 if at.get(planned) else 0
        figures = execution[key]
        figures.update(
            expected=expected,
            schools_due=due,
            schools_reached=reached,
            schools_in_plan=in_plan,
            coverage=round(reached * 100 / due) if due else None,
            plan_coverage=round(in_plan * 100 / due) if due else None,
        )


def _attention(count, one, many, when, tab, show, what="") -> dict | None:
    if not count:
        return None
    text = f"{count:,} {one if count == 1 else many}"
    return {
        "count": count,
        "text": f"{text} {when}".strip(),
        "tab": tab,
        "show": show,
        # The records the line counts (`profile_records.RECORDS`), where it
        # counts work rather than schools.
        "what": what,
    }


def school_rows(profile: dict, show: str = "all", *, where=None) -> list[dict]:
    """The schools behind a figure of ``profile``: every school of the scope,
    or the ones a figure counted (`SHOW_LABELS`). Each row carries the
    school's type, cluster, and its SSA last year, this year and the change,
    so the list reconciles with the number that opened it."""
    from apps.core.enums import SchoolType

    labels = dict(SchoolType.choices)
    wanted = profile["_flags"].get(show)
    rows = []
    for school in profile["_schools"]:
        if wanted is not None and school["id"] not in wanted:
            continue
        # ``where`` narrows the list to one part: ``(school field, value)``.
        if where is not None and school.get(where[0]) != where[1]:
            continue
        score = profile["_scores"][school["id"]]
        rows.append(
            {
                "id": school["id"],
                "school_id": school["school_id"],
                "name": school["name"],
                "type": labels.get(school["school_type"], school["school_type"]),
                "cluster_id": school["cluster_id"],
                "cluster": profile["_cluster_names"].get(school["cluster_id"], ""),
                "district": school["district__name"] or "",
                "district_id": school["district_id"],
                "enrollment": school["enrollment"],
                "previous": score["previous"],
                "current": score["current"],
                "change": score["change"],
                "status_label": score["status_label"],
                "tone": score["tone"],
                **{key: score[key] for key in _NO_WORK},
            }
        )
    return rows


# ── A scope read by its parts ───────────────────────────────────────────────
#: The parts a scope can be read by: key → (label, the school field).
GROUPS = {
    "sub_regions": ("Sub-regions", "sub_region"),
    "districts": ("Districts", "district_id"),
    "staff": ("Staff", "account_owner_id"),
    # The geographic layer inside a district (the brief, 2026-10-10:
    # "District Sub-county Intelligence").
    "sub_counties": ("Sub-counties", "sub_county_id"),
}


def _group_names(by: str, keys: set) -> dict[str, tuple[str, str]]:
    """``{school field value: (the part's own id, its name)}``. A holder is
    written as a staff id or a user id, and both name the same person."""
    if by == "districts":
        from apps.geography.models import District

        return {
            pk: (pk, name)
            for pk, name in District.objects.filter(id__in=keys).values_list(
                "id", "name"
            )
        }
    if by == "sub_regions":
        from apps.geography.models import SubRegion

        return {
            pk: (pk, name)
            for pk, name in SubRegion.objects.filter(id__in=keys).values_list(
                "id", "name"
            )
        }
    if by == "sub_counties":
        from apps.geography.models import SubCounty

        return {
            pk: (pk, name)
            for pk, name in SubCounty.objects.filter(id__in=keys).values_list(
                "id", "name"
            )
        }
    from apps.accounts.models import StaffProfile

    names: dict[str, tuple[str, str]] = {}
    for pk, user_id, name, email in StaffProfile.objects.filter(
        Q(id__in=keys) | Q(user_id__in=keys)
    ).values_list("id", "user_id", "user__name", "user__email"):
        for key in (pk, user_id):
            if key in keys:
                names[key] = (user_id, name or email or "Unnamed")
    return names


def groups(profile: dict, by: str) -> dict:
    """``profile`` read by one kind of part (`GROUPS`): each part's schools,
    how many have an SSA this year, its average last year and this year, the
    change, the schools with nothing planned — and the parts at the top and
    at the bottom by the ranking rule. A school with no such part (no
    district, nobody holding it) is counted under ``unplaced``."""
    from apps.ssa.change_rules import RuleBook

    _label, field = GROUPS[by]
    members: dict[str, list[dict]] = defaultdict(list)
    unplaced = 0
    for school in profile["_schools"]:
        if school[field]:
            members[school[field]].append(profile["_scores"][school["id"]])
        else:
            unplaced += 1
    names = _group_names(by, set(members))
    # Two identities of one person are one row.
    merged: dict[str, dict] = {}
    for key, scores in members.items():
        part_id, name = names.get(key, (key, "Unnamed"))
        row = merged.setdefault(part_id, {"id": part_id, "name": name, "scores": []})
        row["scores"].extend(scores)
    book = RuleBook()
    unplanned = profile["_flags"]["unplanned"]
    rows = []
    for row in merged.values():
        scores = row.pop("scores")
        previous = _mean(s["previous"] for s in scores)
        current = _mean(s["current"] for s in scores)
        rows.append(
            {
                **row,
                "schools": len(scores),
                "assessed": sum(1 for s in scores if s["current"] is not None),
                "unplanned": sum(1 for s in scores if s["id"] in unplanned),
                "clusters": len({s["cluster_id"] for s in scores if s["cluster_id"]}),
                "enrollment": sum(s["enrollment"] or 0 for s in scores),
                **_work_of(scores, profile["_school_work"]),
                "previous": previous,
                "current": current,
                **_change(previous, current, book=book),
            }
        )
    rows.sort(key=lambda r: (r["name"].casefold(), str(r["id"])))
    best, worst = _rank(rows)
    improving, declining = _movers(rows)
    return {
        "by": by,
        "rows": rows,
        "best": best,
        "worst": worst,
        "improving": improving,
        "declining": declining,
        "unplaced": unplaced,
    }


# ── Cluster Management, for the clusters of any scope ───────────────────────
def cluster_management(profile: dict) -> dict:
    """What Cluster Management knows about the scope's clusters, added to
    each of ``profile["clusters"]``: the year's attendance at cluster
    sessions, the schools that have missed three in a row, Cluster Health and
    Cluster Impact, and the maturity level — the same reads as the cluster's
    own profile (`apps.clusters.profile_insights`, `apps.clusters.scores`),
    so a figure here is the figure its link opens. A cluster's figures are
    the whole cluster's, wherever its schools are.

    Returns the scope's totals: sessions held, schools invited and attending,
    teachers and school leaders recorded at them."""
    from apps.clusters import profile_insights as insights
    from apps.clusters import scores

    cluster_ids = [row["id"] for row in profile["clusters"]]
    totals = {
        "sessions": 0,
        "invited": 0,
        "attended": 0,
        "teachers": 0,
        "leaders": 0,
        "absent": 0,
        "rate": None,
        "alert_after": insights.MISSED_IN_A_ROW_ALERT,
        "impact": None,
    }
    if not cluster_ids:
        return totals
    fy = profile["fy"]
    facts = scores.gather(cluster_ids, fy=fy)
    cards = scores.scorecards(cluster_ids, fy=fy, facts=facts)
    attendance = facts["attendance"]
    for row in profile["clusters"]:
        attended = attendance[row["id"]]
        card = cards[row["id"]]
        row.update(
            attendance_rate=attended["rate"],
            sessions=len(attended["sessions"]),
            absent=len(attended["drifting"]),
            health=card.health.score,
            health_band=card.health.band[0],
            impact=card.impact.score,
            impact_band=card.impact.band[0],
            maturity=card.maturity.get("level"),
            maturity_label=card.maturity.get("label", ""),
        )
        totals["sessions"] += len(attended["sessions"])
        totals["invited"] += attended["invited_total"]
        totals["attended"] += attended["attended_total"]
        totals["teachers"] += attended["teachers"]
        totals["leaders"] += attended["leaders"]
        totals["absent"] += len(attended["drifting"])
    if totals["invited"]:
        totals["rate"] = round(100 * totals["attended"] / totals["invited"])
    # What changed for learners in those clusters (Cluster Management's own
    # like-for-like reads: a school counts only with a figure in both years).
    enrolment = [facts["enrolment"][cid] for cid in cluster_ids]
    learning = [facts["learning"][cid] for cid in cluster_ids]
    before = sum(e.before for e in enrolment)
    after = sum(e.after for e in enrolment)
    totals["impact"] = {
        "enrolment_schools": sum(e.compared for e in enrolment),
        "enrolment_before": before,
        "enrolment_after": after,
        "enrolment_growth": (
            round((after - before) * 100 / before, 1) if before else None
        ),
        "learning_schools": sum(row.compared for row in learning),
        "learning_improved": sum(row.improved for row in learning),
        "learning_declined": sum(row.declined for row in learning),
        "stories": sum(facts["stories"][cid].approved for cid in cluster_ids),
    }
    return totals


# ── What a profile covers, level by level ───────────────────────────────────
#: The levels beneath each kind of profile, widest first (owner, 2026-10-09:
#: "country should have summary of all the sub-region, district, clusters,
#: schools, and their performance ... Same should apply to Sub-region
#: (District, clusters, schools), District (clusters, schools)").
LEVELS_OF = {
    "country": ("sub_regions", "districts", "clusters", "schools"),
    "sub_region": ("districts", "clusters", "schools"),
    "district": ("clusters", "schools"),
    "program_lead": ("staff", "districts", "clusters", "schools"),
    "staff": ("districts", "clusters", "schools"),
    "partner": ("districts", "clusters", "schools"),
    "cluster": ("schools",),
    "school": (),
}
_LEVEL_LABELS = {
    "sub_regions": "Sub-regions",
    "districts": "Districts",
    "staff": "Team members",
    "clusters": "Clusters",
    "schools": "Schools",
}


def summary(profile: dict) -> list[dict]:
    """One line for each level beneath the profile: how many there are, how
    many have an SSA this year, how many improved and how many declined, the
    one at the top and the one at the bottom by the ranking rule, and the
    visits and trainings done of those planned. The same rows as each
    level's own tab, added up — so a line here opens the table it counts."""
    lines = []
    for level in LEVELS_OF[profile["scope"].kind]:
        if level == "schools":
            rows = list(profile["_scores"].values())
            measured = [r for r in rows if r["current"] is not None]
            work = _work_of(rows, profile["_school_work"])
        elif level == "clusters":
            rows = profile["clusters"]
            measured = [r for r in rows if r["current"] is not None]
            work = {
                "visits": sum(r["visits"] for r in rows),
                "visits_done": sum(r["visits_done"] for r in rows),
                "trainings": sum(r["group_trainings"] for r in rows),
                "trainings_done": sum(r["group_trainings_done"] for r in rows),
            }
        else:
            rows = groups(profile, level)["rows"]
            measured = [r for r in rows if r["current"] is not None]
            work = {key: sum(r[key] for r in rows) for key in _NO_WORK}
        best, worst = _rank(rows)
        lines.append(
            {
                "level": level,
                "label": _LEVEL_LABELS[level],
                "count": len(rows),
                "measured": len(measured),
                "improved": sum(1 for r in rows if r["status"] == "improved"),
                "declined": sum(1 for r in rows if r["status"] == "declined"),
                "best": best[0] if best else None,
                # The bottom of the ranking, when it is not also the top.
                "lowest": (worst or best[1:])[-1] if len(measured) > 1 else None,
                **work,
            }
        )
    return lines


# ── What changed for learners ───────────────────────────────────────────────
def students(profile: dict) -> dict:
    """Enrolment and learning results for the scope's schools, this year
    against last, by Cluster Management's like-for-like reads
    (`apps.clusters.outcomes`): a school counts in a comparison only with a
    figure in both years. Three queries."""
    from apps.clusters import outcomes

    members = {"scope": profile["_schools"]}
    fy = profile["fy"]
    enrolment = outcomes.enrolment_by_cluster(["scope"], fy=fy, members=members)[
        "scope"
    ]
    learning = outcomes.learning_by_cluster(["scope"], fy=fy, members=members)["scope"]
    return {
        "enrolment": enrolment.latest_total,
        "enrolment_schools": enrolment.with_latest,
        "enrolment_compared": enrolment.compared,
        "enrolment_before": enrolment.before,
        "enrolment_after": enrolment.after,
        "enrolment_change": enrolment.change,
        "enrolment_growth": enrolment.growth_pct,
        "learning_compared": learning.compared,
        "learning_before": learning.before,
        "learning_after": learning.after,
        "learning_change": learning.change,
        "learning_improved": learning.improved,
        "learning_declined": learning.declined,
    }


# ── People reached, and money lent ──────────────────────────────────────────
def people(profile: dict) -> dict:
    """Teachers and school leaders trained in the scope's schools in the
    period: those recorded at completed in-school trainings, and those
    recorded for the scope's schools at group trainings; and, apart, those
    recorded at cluster meetings — a meeting is not a training. Schools
    trained is the schools with either kind of training. Three queries."""
    from django.db.models import Sum

    from apps.activities.models import Activity, ClusterActivityAttendance

    scope, fy = profile["scope"], profile["fy"]
    window = period_window(fy, profile["period"])
    school_ids = scope.schools.values("id")
    done = Q(status__in=COMPLETED_WORK_STATUSES)
    in_school = _in_window(
        Activity.objects.filter(
            done,
            school_id__in=school_ids,
            activity_type__in=_TRAININGS,
            fy=fy,
            deleted_at__isnull=True,
        ),
        window,
    )
    if scope.work is not None:
        in_school = in_school.filter(scope.work)
    own = in_school.aggregate(
        teachers=Sum("teachers_attended"),
        leaders=Sum("leaders_attended"),
        schools=Count("school_id", distinct=True),
    )
    sessions = _in_window(
        Activity.objects.filter(
            done, school__isnull=True, fy=fy, deleted_at__isnull=True
        ),
        window,
    )
    register = ClusterActivityAttendance.objects.filter(
        school_id__in=school_ids, attended=True, activity_id__in=sessions.values("id")
    )
    group = register.filter(activity__activity_type__in=_TRAININGS).aggregate(
        teachers=Sum("teachers"),
        leaders=Sum("leaders"),
        schools=Count("school_id", distinct=True),
    )
    meetings = register.filter(activity__activity_type__in=_MEETINGS).aggregate(
        teachers=Sum("teachers"),
        leaders=Sum("leaders"),
        schools=Count("school_id", distinct=True),
    )
    trained = set(in_school.values_list("school_id", flat=True)) | set(
        register.filter(activity__activity_type__in=_TRAININGS).values_list(
            "school_id", flat=True
        )
    )
    return {
        "teachers_trained": (own["teachers"] or 0) + (group["teachers"] or 0),
        "leaders_trained": (own["leaders"] or 0) + (group["leaders"] or 0),
        "teachers_in_school": own["teachers"] or 0,
        "teachers_group": group["teachers"] or 0,
        "leaders_in_school": own["leaders"] or 0,
        "leaders_group": group["leaders"] or 0,
        "schools_trained": len(trained),
        "teachers_at_meetings": meetings["teachers"] or 0,
        "leaders_at_meetings": meetings["leaders"] or 0,
        "schools_at_meetings": meetings["schools"] or 0,
    }


def finance(profile: dict, principal) -> dict | None:
    """School loans and Business Transformation in the scope, as far as
    ``principal`` may read the loan register (Cluster Management's read,
    `apps.clusters.outcomes.loans_by_cluster`); None for a reader the
    register is closed to, so a page hides what it could only show empty."""
    from apps.business_transformation.models import (
        OPEN_CASE_STATUSES,
        TransformationCase,
    )
    from apps.clusters import outcomes
    from apps.core.permissions import RolePermissionService

    if principal is None or not RolePermissionService.can_view_page(principal, "loans"):
        return None
    loans = outcomes.loans_by_cluster(
        ["scope"], principal, members={"scope": profile["_schools"]}
    )["scope"]
    cases = TransformationCase.objects.filter(
        school_id__in=profile["scope"].schools.values("id"), deleted_at__isnull=True
    ).aggregate(
        total=Count("id"),
        open=Count("id", filter=Q(status__in=[s.value for s in OPEN_CASE_STATUSES])),
        schools=Count("school_id", distinct=True),
    )
    return {
        "loans": loans.loan_count,
        "loan_schools": loans.school_count,
        "funded_schools": loans.funded_school_count,
        "disbursed": loans.disbursed,
        "edtech_loans": loans.edtech,
        "by_status": loans.status_counts,
        "cases": cases["total"],
        "open_cases": cases["open"],
        "case_schools": cases["schools"],
    }
