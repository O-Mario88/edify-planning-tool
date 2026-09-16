"""The country portfolio: every school, under the people accountable for it.

Owner, 2026-09-16: "IA Team oversight should have all the schools in the entire
country portfolio but grouped by Program leads, which is further grouped by the
CCEO under them. IA should also track all the planning to know which schools
have been planned and which ones have not been planned."

Two levels, because that is the shape of the organisation: a school belongs to
a CCEO, a CCEO reports to a Programme Lead. Seven hundred schools sorted by
name is a directory; the same seven hundred under the lead and the officer who
hold them is the thing a country role can act on — the unplanned schools in one
lead's column are that lead's conversation, not a national statistic.

Scope comes from `scoped_school_queryset`, so this cannot show a school the
pickers would refuse: one definition of who may see what, and this reads it
rather than holding a second opinion.

Every number here is folded from the rows it labels — a lead's total is the sum
of their officers', an officer's is the length of their school list — so a
heading and the rows under it cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.db.models import Count, Max, Min, Q, Sum

from apps.core.activity_types import (
    CLUSTER_MEETING_TYPES,
    COMPLETED_WORK_STATUSES,
    TRAINING_TYPES,
    VISIT_TYPES,
)
from apps.core.rbac import EdifyRole
from apps.schools.school_status import DEAD_STATUSES

#: A school whose owner reports to nobody, or has no owner at all. It groups
#: under its own heading rather than being dropped: a school nobody is carrying
#: is exactly what a country lens exists to surface.
NO_LEAD_KEY = "__no_lead__"
NO_LEAD_LABEL = "No Programme Lead"
UNASSIGNED_KEY = "__unassigned__"
UNASSIGNED_LABEL = "Unassigned"


@dataclass
class OfficerGroup:
    """One CCEO's schools inside their Programme Lead's column.

    `schools` is the officer's whole portfolio and every number below is folded
    from it; `visible` is the subset the reader asked to see. They are kept
    apart on purpose: filtering to the unplanned schools must not make an
    officer's heading read "0 planned, 0% planned" — that is the filter
    describing itself, not the officer's position.
    """

    key: str
    name: str
    schools: list = field(default_factory=list)
    visible: list = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.schools)

    @property
    def planned(self) -> int:
        return sum(1 for s in self.schools if s["is_planned"])

    @property
    def unplanned(self) -> int:
        return self.count - self.planned

    @property
    def activities(self) -> int:
        return sum(s["activities"] for s in self.schools)

    @property
    def budget(self) -> int:
        return sum(s["budget"] for s in self.schools)

    @property
    def coverage(self) -> int | None:
        """Share of this officer's schools with work planned, or None when
        they hold no schools — 0% and "no schools" are different findings."""
        return round(100 * self.planned / self.count) if self.count else None

    @property
    def shown(self) -> int:
        """How many of this officer's schools the current filter lists."""
        return len(self.visible)

    @property
    def page_param(self) -> str:
        """This officer's own page parameter.

        Each officer is its own table, so paging one must not page the others:
        a country lens puts four hundred schools under one CCEO and six under
        the next, and a shared parameter would move both.
        """
        safe = "".join(ch if ch.isalnum() else "_" for ch in self.key).strip("_")
        return f"portfolio_{safe or 'officer'}_page"


@dataclass
class LeadGroup:
    """One Programme Lead's column: their CCEOs, and the schools under them."""

    key: str
    name: str
    officers: list = field(default_factory=list)

    @property
    def count(self) -> int:
        return sum(o.count for o in self.officers)

    @property
    def planned(self) -> int:
        return sum(o.planned for o in self.officers)

    @property
    def unplanned(self) -> int:
        return self.count - self.planned

    @property
    def activities(self) -> int:
        return sum(o.activities for o in self.officers)

    @property
    def budget(self) -> int:
        return sum(o.budget for o in self.officers)

    @property
    def coverage(self) -> int | None:
        return round(100 * self.planned / self.count) if self.count else None

    @property
    def is_unassigned(self) -> bool:
        return self.key == NO_LEAD_KEY


def _staff_directory(owner_ids) -> dict[str, dict]:
    """Owner id → the officer and the Programme Lead they report to.

    `School.account_owner_id` holds a StaffProfile id on most rows and that
    profile's User id on rows written by another path, so a lookup in one id
    space silently disowns half the portfolio. Both are resolved here, once.
    """
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    ids = {str(i) for i in owner_ids if i}
    if not ids:
        return {}
    profiles = list(
        StaffProfile.objects.filter(Q(id__in=ids) | Q(user_id__in=ids))
        .filter(deleted_at__isnull=True)
        .select_related("user")
    )
    leads: dict[str, tuple[str, str]] = {}
    for link in (
        StaffSupervisorAssignment.objects.filter(
            supervisee_id__in=[p.id for p in profiles],
            supervisor__deleted_at__isnull=True,
        )
        .select_related("supervisor__user")
        .order_by("supervisor__user__name")
    ):
        # The direct reporting line only. IA and the RVP supervise the same
        # people as overlapping oversight, and treating one of those rows as
        # the line would file a CCEO's schools under whoever last reviewed
        # them (the trap apps.clusters.oversight_service names).
        if link.supervisee_id in leads:
            continue
        supervisor = link.supervisor
        if (
            getattr(supervisor.user, "active_role", "")
            != EdifyRole.COUNTRY_PROGRAM_LEAD.value
        ):
            continue
        leads[link.supervisee_id] = (
            supervisor.id,
            supervisor.user.name or supervisor.user.email or UNASSIGNED_LABEL,
        )

    directory: dict[str, dict] = {}
    for profile in profiles:
        name = (profile.user.name if profile.user_id else "") or profile.id
        lead = leads.get(profile.id)
        if (
            not lead
            and getattr(profile.user, "active_role", "")
            == EdifyRole.COUNTRY_PROGRAM_LEAD.value
        ):
            # A Programme Lead who holds schools directly heads their own
            # column rather than falling into "No Programme Lead".
            lead = (profile.id, name)
        entry = {
            "officer_id": profile.id,
            "officer_name": name,
            "lead_id": lead[0] if lead else NO_LEAD_KEY,
            "lead_name": lead[1] if lead else NO_LEAD_LABEL,
        }
        directory[profile.id] = entry
        if profile.user_id:
            directory[str(profile.user_id)] = entry
    return directory


def _planning_by_school(school_ids, *, fy: str) -> dict[str, dict]:
    """What each school has planned this fiscal year, in two queries.

    Counted from the canonical activity rows, and costed from the canonical
    cost lines, so the portfolio and the budget cannot disagree about what a
    school's plan is worth.
    """
    from apps.activities.models import Activity, ActivityScheduleCostLine

    if not school_ids:
        return {}
    rows = (
        Activity.objects.filter(
            school_id__in=school_ids, fy=str(fy), deleted_at__isnull=True
        )
        .exclude(status__in=DEAD_STATUSES)
        .values("school_id")
        .annotate(
            activities=Count("id"),
            visits=Count("id", filter=Q(activity_type__in=VISIT_TYPES)),
            trainings=Count("id", filter=Q(activity_type__in=TRAINING_TYPES)),
            meetings=Count("id", filter=Q(activity_type__in=CLUSTER_MEETING_TYPES)),
            # The whole verified chain, not the bare "completed" status: no
            # production transition writes that one, so a count filtered on it
            # matches seeded rows and skips every activity a person actually
            # delivered (apps.core.tests.test_verification_criticals).
            completed=Count("id", filter=Q(status__in=COMPLETED_WORK_STATUSES)),
            first_date=Min("planned_date"),
            last_date=Max("planned_date"),
        )
    )
    planning = {
        row["school_id"]: {
            "activities": row["activities"],
            "visits": row["visits"],
            "trainings": row["trainings"],
            "meetings": row["meetings"],
            "completed": row["completed"],
            "first_date": row["first_date"],
            "last_date": row["last_date"],
            "budget": 0,
        }
        for row in rows
    }
    costs = (
        ActivityScheduleCostLine.objects.filter(
            activity__school_id__in=school_ids,
            activity__fy=str(fy),
            activity__deleted_at__isnull=True,
        )
        .exclude(activity__status__in=DEAD_STATUSES)
        .values("activity__school_id")
        .annotate(total=Sum("amount"))
    )
    for row in costs:
        entry = planning.get(row["activity__school_id"])
        if entry is not None:
            entry["budget"] = int(row["total"] or 0)
    return planning


def _cluster_names(cluster_ids) -> dict[str, str]:
    from apps.clusters.models import Cluster

    ids = {c for c in cluster_ids if c}
    if not ids:
        return {}
    return dict(Cluster.objects.filter(id__in=ids).values_list("id", "name"))


def country_portfolio(
    principal,
    *,
    fy: str,
    program_lead_id: str | None = None,
    district_id: str | None = None,
    planned: str | None = None,
    today: date | None = None,
) -> dict:
    """The schools this principal may see, under their lead and their officer.

    `planned` narrows the school rows to "planned" or "unplanned" — the two
    questions a country role actually opens this page with. The totals are
    always the unnarrowed truth, so filtering to the unplanned schools cannot
    make the coverage figure move.
    """
    from apps.core.scoping import resolve_user_scope, scoped_school_queryset
    from apps.schools.lifecycle_service import active_schools

    today = today or date.today()
    scope = resolve_user_scope(principal)
    queryset = scoped_school_queryset(scope)
    if queryset is None:
        return {
            "leads": [],
            "totals": _totals([]),
            "districts": [],
            "fy": str(fy),
        }

    # A closed school takes no work, so it is never "not planned" — it would
    # be a permanent red row nobody can clear (apps.planning.coverage_service
    # holds the same line).
    queryset = active_schools(queryset).select_related("district")
    if district_id and district_id not in ("all", "All"):
        queryset = queryset.filter(district_id=district_id)

    schools = list(queryset.order_by("name"))
    directory = _staff_directory({s.account_owner_id for s in schools})
    planning = _planning_by_school([s.id for s in schools], fy=fy)
    clusters = _cluster_names({s.cluster_id for s in schools})

    rows = []
    for school in schools:
        plan = planning.get(school.id)
        owner = directory.get(str(school.account_owner_id or ""))
        rows.append(
            {
                "school_id": school.id,
                "school_code": school.school_id,
                "name": school.name,
                "school_type": school.school_type,
                "district": school.district.name if school.district_id else "",
                "district_id": school.district_id,
                "cluster_id": school.cluster_id,
                "cluster_name": clusters.get(school.cluster_id, ""),
                "officer_id": owner["officer_id"] if owner else UNASSIGNED_KEY,
                "officer_name": owner["officer_name"] if owner else UNASSIGNED_LABEL,
                "lead_id": owner["lead_id"] if owner else NO_LEAD_KEY,
                "lead_name": owner["lead_name"] if owner else NO_LEAD_LABEL,
                "activities": plan["activities"] if plan else 0,
                "visits": plan["visits"] if plan else 0,
                "trainings": plan["trainings"] if plan else 0,
                "meetings": plan["meetings"] if plan else 0,
                "completed": plan["completed"] if plan else 0,
                "first_date": plan["first_date"] if plan else None,
                "last_date": plan["last_date"] if plan else None,
                "budget": plan["budget"] if plan else 0,
                # "Planned" is one or more live activities in the fiscal year.
                # Not a date in the future: a school visited in October and
                # never again has been planned for, and belongs in the count
                # its lead is held to.
                "is_planned": bool(plan and plan["activities"]),
                "url": f"/schools/{school.school_id}",
                "cluster_url": f"/clusters/{school.cluster_id}"
                if school.cluster_id
                else "",
            }
        )

    totals = _totals(rows)
    districts = sorted(
        {(r["district_id"], r["district"]) for r in rows if r["district_id"]},
        key=lambda pair: pair[1],
    )

    # The lead filter's options come from the whole portfolio, so choosing one
    # lead never empties the control that did the choosing.
    lead_options = _lead_options(rows)

    if program_lead_id and program_lead_id not in ("all", "All"):
        rows = [r for r in rows if r["lead_id"] == program_lead_id]

    # The lead's column is chosen by the lead filter; which of that lead's
    # schools are listed is chosen by the planning filter. The headings stay
    # folded from the whole column either way.
    def shown(row) -> bool:
        if planned == "planned":
            return row["is_planned"]
        if planned == "unplanned":
            return not row["is_planned"]
        return True

    return {
        "leads": _group(rows, shown=shown),
        "lead_options": lead_options,
        "totals": totals,
        "districts": [{"id": i, "name": n} for i, n in districts],
        "fy": str(fy),
    }


def _group(rows, *, shown=None) -> list[LeadGroup]:
    """Rows into Programme Lead columns, each holding its CCEOs.

    `shown` decides which rows are listed. Every row still counts toward the
    headings, so a reader who filters to the unplanned schools sees the real
    portfolio in the heading and the schools they asked about underneath it.
    """
    leads: dict[str, LeadGroup] = {}
    officers: dict[tuple[str, str], OfficerGroup] = {}
    for row in rows:
        lead = leads.get(row["lead_id"])
        if lead is None:
            lead = leads[row["lead_id"]] = LeadGroup(
                key=row["lead_id"], name=row["lead_name"]
            )
        officer_key = (row["lead_id"], row["officer_id"])
        officer = officers.get(officer_key)
        if officer is None:
            officer = officers[officer_key] = OfficerGroup(
                key=row["officer_id"], name=row["officer_name"]
            )
            lead.officers.append(officer)
        officer.schools.append(row)
        if shown is None or shown(row):
            officer.visible.append(row)

    for lead in leads.values():
        # An officer with nothing left to list under the chosen filter is
        # dropped: an empty table under a heading is furniture.
        lead.officers = sorted(
            (o for o in lead.officers if o.visible),
            key=lambda o: (o.key == UNASSIGNED_KEY, o.name.casefold()),
        )
    # Unassigned last: it is the exception, and leading with it pushes the
    # people actually carrying schools below the fold.
    return sorted(
        (lead for lead in leads.values() if lead.officers),
        key=lambda g: (g.is_unassigned, g.name.casefold()),
    )


def _totals(rows) -> dict:
    planned = sum(1 for r in rows if r["is_planned"])
    schools = len(rows)
    return {
        "schools": schools,
        "planned": planned,
        "unplanned": schools - planned,
        # None rather than 0 when there is nothing to divide: "no schools in
        # scope" and "none of them planned" are different answers.
        "coverage": round(100 * planned / schools) if schools else None,
        "activities": sum(r["activities"] for r in rows),
        "budget": sum(r["budget"] for r in rows),
        "leads": len({r["lead_id"] for r in rows}),
        "officers": len({(r["lead_id"], r["officer_id"]) for r in rows}),
    }


def _lead_options(rows) -> list[dict]:
    """Every lead holding a school in this lens, with how many they hold.

    Built from the rows rather than from the staff table, so the filter cannot
    offer a lead whose selection returns nothing — and built before the filter
    is applied, so choosing one lead does not remove the rest from the control.
    """
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row["lead_id"], row["lead_name"])
        counts[key] = counts.get(key, 0) + 1
    return [
        {"id": lead_id, "name": name, "count": count}
        for (lead_id, name), count in sorted(
            counts.items(),
            key=lambda kv: (kv[0][0] == NO_LEAD_KEY, kv[0][1].casefold()),
        )
    ]


def program_lead_options(portfolio: dict) -> list[dict]:
    """The lead filter's options for this portfolio."""
    return portfolio["lead_options"]


__all__ = [
    "LeadGroup",
    "NO_LEAD_KEY",
    "NO_LEAD_LABEL",
    "OfficerGroup",
    "UNASSIGNED_KEY",
    "UNASSIGNED_LABEL",
    "country_portfolio",
    "program_lead_options",
]
