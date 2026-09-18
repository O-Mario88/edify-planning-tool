"""Which clusters are working, and which have gone quiet.

Owner, 2026-09-16: "IA should also track all the cluster activities, planning,
SSA for the member schools, performance for each cluster. Which cluster is more
active and which cluster is less active."

The platform already knows who owns which cluster (apps.clusters.oversight_service)
and which schools are in it. What it could not answer was whether a cluster is
doing anything: a cluster with forty member schools and no session planned all
year looked exactly like one running a training a month.

So each cluster is measured on four things it is supposed to produce, all for
one fiscal year:

* **planned** — sessions on its calendar (trainings, meetings) and visits to
  its member schools;
* **delivered** — how many of those are completed;
* **SSA** — how many of its member schools have an assessment this year;
* **reach** — how many of its member schools any of that work actually touched.

The activity index folds them into one number so the list can be ordered, and
the order is the finding: the top of it is where the practice is, the bottom is
where the next conversation belongs. The index is deliberately simple and
stated on the page — a weighting nobody can read is a ranking nobody can argue
with, which is worse than a rough one they can.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db.models import Count, Max, Q

from apps.core.activity_types import (
    CLUSTER_MEETING_TYPES,
    COMPLETED_WORK_STATUSES,
    TRAINING_TYPES,
    VISIT_TYPES,
)
from apps.planning.portfolio_service import NO_LEAD_KEY, NO_LEAD_LABEL
from apps.schools.school_status import CLUSTER_SESSION_TYPES, DEAD_STATUSES

#: What the index counts each thing for. Sessions lead because a cluster exists
#: to convene: a cluster running trainings is doing its job in a way that a
#: cluster whose schools happen to get visited individually is not.
WEIGHT_SESSION = 3
WEIGHT_VISIT = 1
WEIGHT_SSA = 2

#: A cluster nobody owns still has to appear: an unowned cluster with nothing
#: planned is the finding, and dropping it from the grouping hides it.
NO_OWNER_KEY = "unassigned"
NO_OWNER_LABEL = "Unassigned"

#: Below this share of the busiest cluster's index, a cluster is called out as
#: quiet. A band rather than "the bottom five", because a country with three
#: clusters has no bottom five and a country with three hundred has far more
#: than five that need attention.
QUIET_SHARE = 0.34
ACTIVE_SHARE = 0.67


@dataclass
class ClusterRow:
    cluster_id: str
    name: str
    district: str
    owner_id: str
    owner_name: str
    lead_id: str
    lead_name: str
    schools: int
    sessions_planned: int
    sessions_done: int
    trainings: int
    meetings: int
    visits_planned: int
    visits_done: int
    ssa_schools: int
    schools_reached: int
    last_activity: date | None
    budget: int

    @property
    def index(self) -> int:
        return (
            WEIGHT_SESSION * self.sessions_planned
            + WEIGHT_VISIT * self.visits_planned
            + WEIGHT_SSA * self.ssa_schools
        )

    @property
    def delivery(self) -> int | None:
        """Share of planned work completed, or None when nothing is planned —
        a cluster that planned nothing has not delivered 0% of it."""
        planned = self.sessions_planned + self.visits_planned
        if not planned:
            return None
        return round(100 * (self.sessions_done + self.visits_done) / planned)

    @property
    def ssa_coverage(self) -> int | None:
        return round(100 * self.ssa_schools / self.schools) if self.schools else None

    @property
    def reach(self) -> int | None:
        return (
            round(100 * self.schools_reached / self.schools) if self.schools else None
        )

    @property
    def is_dormant(self) -> bool:
        """Nothing planned at all — the finding that outranks any ranking."""
        return not (self.sessions_planned or self.visits_planned)


def _schools_by_cluster(cluster_ids) -> dict[str, list[str]]:
    from apps.schools.lifecycle_service import active_schools
    from apps.schools.models import School

    if not cluster_ids:
        return {}
    rows = active_schools(
        School.objects.filter(cluster_id__in=cluster_ids)
    ).values_list("cluster_id", "id")
    out: dict[str, list[str]] = {}
    for cluster_id, school_id in rows:
        out.setdefault(cluster_id, []).append(school_id)
    return out


def _sessions_by_cluster(cluster_ids, *, fy: str) -> dict[str, dict]:
    """Trainings and meetings on each cluster's own calendar, in one query."""
    from apps.activities.models import Activity

    if not cluster_ids:
        return {}
    rows = (
        Activity.objects.filter(
            cluster_id__in=cluster_ids,
            fy=str(fy),
            activity_type__in=CLUSTER_SESSION_TYPES,
            deleted_at__isnull=True,
        )
        .exclude(status__in=DEAD_STATUSES)
        .values("cluster_id")
        .annotate(
            planned=Count("id"),
            # The whole verified chain. "completed" alone is a status no
            # production transition writes, so delivery counted on it would
            # read zero for work that was delivered and verified
            # (apps.core.tests.test_verification_criticals).
            done=Count("id", filter=Q(status__in=COMPLETED_WORK_STATUSES)),
            trainings=Count("id", filter=Q(activity_type__in=TRAINING_TYPES)),
            meetings=Count("id", filter=Q(activity_type__in=CLUSTER_MEETING_TYPES)),
            last=Max("planned_date"),
        )
    )
    return {row["cluster_id"]: row for row in rows}


def _visits_by_cluster(school_ids_by_cluster, *, fy: str) -> dict[str, dict]:
    """School visits to each cluster's member schools.

    A cluster's work is not only what it convenes: the visits its members
    receive are the other half of whether the ground is being covered. Counted
    through the school → cluster link in one query for the whole page.
    """
    from apps.activities.models import Activity

    school_to_cluster = {
        school_id: cluster_id
        for cluster_id, school_ids in school_ids_by_cluster.items()
        for school_id in school_ids
    }
    if not school_to_cluster:
        return {}
    rows = (
        Activity.objects.filter(
            school_id__in=school_to_cluster,
            fy=str(fy),
            activity_type__in=VISIT_TYPES,
            deleted_at__isnull=True,
            # Counted on the cluster's own calendar if it has one (see
            # `_sessions_by_cluster`); a visit is the member school's.
            cluster_id__isnull=True,
        )
        .exclude(status__in=DEAD_STATUSES)
        .values("school_id")
        .annotate(
            planned=Count("id"),
            done=Count("id", filter=Q(status__in=COMPLETED_WORK_STATUSES)),
            last=Max("planned_date"),
        )
    )
    out: dict[str, dict] = {}
    for row in rows:
        cluster_id = school_to_cluster[row["school_id"]]
        entry = out.setdefault(
            cluster_id, {"planned": 0, "done": 0, "last": None, "schools": set()}
        )
        entry["planned"] += row["planned"]
        entry["done"] += row["done"]
        entry["schools"].add(row["school_id"])
        if row["last"] and (entry["last"] is None or row["last"] > entry["last"]):
            entry["last"] = row["last"]

    return out


def _budget_by_cluster(
    cluster_ids, school_ids_by_cluster, *, fy: str
) -> dict[str, int]:
    """What each cluster's fiscal-year plan costs, from the canonical lines.

    Both halves: the sessions the cluster convenes and the visits its member
    schools receive. Summed from ActivityScheduleCostLine so this page and the
    budget cannot disagree about the same plan.
    """
    from apps.activities.models import ActivityScheduleCostLine
    from django.db.models import Sum

    school_to_cluster = {
        school_id: cluster_id
        for cluster_id, school_ids in school_ids_by_cluster.items()
        for school_id in school_ids
    }
    totals: dict[str, int] = {}
    if cluster_ids:
        rows = (
            ActivityScheduleCostLine.objects.filter(
                activity__cluster_id__in=cluster_ids,
                activity__fy=str(fy),
                activity__deleted_at__isnull=True,
            )
            .exclude(activity__status__in=DEAD_STATUSES)
            .values("activity__cluster_id")
            .annotate(total=Sum("amount"))
        )
        for row in rows:
            totals[row["activity__cluster_id"]] = int(row["total"] or 0)
    if school_to_cluster:
        rows = (
            ActivityScheduleCostLine.objects.filter(
                activity__school_id__in=school_to_cluster,
                activity__fy=str(fy),
                activity__deleted_at__isnull=True,
                # An activity carrying both a school and a cluster was already
                # counted on the cluster side above. Both columns are nullable
                # and nothing forbids a row setting each, so without this the
                # same cost lands in the cluster's total twice.
                activity__cluster_id__isnull=True,
            )
            .exclude(activity__status__in=DEAD_STATUSES)
            .values("activity__school_id")
            .annotate(total=Sum("amount"))
        )
        for row in rows:
            cluster_id = school_to_cluster[row["activity__school_id"]]
            totals[cluster_id] = totals.get(cluster_id, 0) + int(row["total"] or 0)
    return totals


def _ssa_by_cluster(school_ids_by_cluster, *, fy: str) -> dict[str, int]:
    """Member schools with an SSA record this fiscal year."""
    from apps.ssa.models import SsaRecord

    school_to_cluster = {
        school_id: cluster_id
        for cluster_id, school_ids in school_ids_by_cluster.items()
        for school_id in school_ids
    }
    if not school_to_cluster:
        return {}
    rows = (
        SsaRecord.objects.filter(
            school_id__in=school_to_cluster, fy=str(fy), deleted_at__isnull=True
        )
        .values_list("school_id", flat=True)
        .distinct()
    )
    out: dict[str, int] = {}
    for school_id in rows:
        cluster_id = school_to_cluster[school_id]
        out[cluster_id] = out.get(cluster_id, 0) + 1
    return out


def _attended_schools(cluster_ids, *, fy: str) -> dict[str, set]:
    """Member schools a cluster session actually reached.

    A session belongs to the cluster, not to a school, so without the
    attendance table the work it delivered is invisible on every school that
    sat in the room (apps.activities.models.ClusterActivityAttendance).
    """
    from apps.activities.models import ClusterActivityAttendance

    if not cluster_ids:
        return {}
    rows = (
        ClusterActivityAttendance.objects.filter(
            activity__cluster_id__in=cluster_ids,
            activity__fy=str(fy),
            activity__deleted_at__isnull=True,
        )
        .exclude(activity__status__in=DEAD_STATUSES)
        .filter(Q(invited=True) | Q(attended=True))
        .values_list("activity__cluster_id", "school_id")
    )
    out: dict[str, set] = {}
    for cluster_id, school_id in rows:
        out.setdefault(cluster_id, set()).add(school_id)
    return out


def cluster_performance(
    principal, *, fy: str, program_lead_id: str | None = None
) -> dict:
    """Every cluster in scope, measured and ordered by how active it is."""
    from apps.clusters.models import Cluster
    from apps.clusters.oversight_service import _label, _staff_directory, _supervisor_of
    from apps.core.scoping import cluster_queryset, resolve_user_scope

    scope = resolve_user_scope(principal)
    clusters = list(
        (cluster_queryset(scope) or Cluster.objects.none())
        .select_related("district")
        .order_by("name")
    )
    if not clusters:
        return {"rows": [], "totals": _cluster_totals([]), "leads": []}

    cluster_ids = [c.id for c in clusters]
    owners = _staff_directory({c.responsible_staff_id for c in clusters})
    members = _schools_by_cluster(cluster_ids)
    sessions = _sessions_by_cluster(cluster_ids, fy=fy)
    visits = _visits_by_cluster(members, fy=fy)
    ssa = _ssa_by_cluster(members, fy=fy)
    attended = _attended_schools(cluster_ids, fy=fy)
    budgets = _budget_by_cluster(cluster_ids, members, fy=fy)

    rows = []
    for cluster in clusters:
        owner = owners.get((cluster.responsible_staff_id or "").strip())
        lead = _supervisor_of(owner)
        session = sessions.get(cluster.id, {})
        visit = visits.get(cluster.id, {})
        member_ids = set(members.get(cluster.id, ()))
        reached = (
            attended.get(cluster.id, set()) | visit.get("schools", set())
        ) & member_ids
        last_dates = [d for d in (session.get("last"), visit.get("last")) if d]
        rows.append(
            ClusterRow(
                cluster_id=cluster.id,
                name=cluster.name,
                district=getattr(cluster.district, "name", ""),
                owner_id=getattr(owner, "id", "") or NO_OWNER_KEY,
                owner_name=_label(owner) if owner else NO_OWNER_LABEL,
                lead_id=getattr(lead, "id", "") or NO_LEAD_KEY,
                lead_name=_label(lead) if lead else NO_LEAD_LABEL,
                schools=len(member_ids),
                sessions_planned=session.get("planned", 0),
                sessions_done=session.get("done", 0),
                trainings=session.get("trainings", 0),
                meetings=session.get("meetings", 0),
                visits_planned=visit.get("planned", 0),
                visits_done=visit.get("done", 0),
                ssa_schools=ssa.get(cluster.id, 0),
                schools_reached=len(reached),
                last_activity=max(last_dates) if last_dates else None,
                budget=budgets.get(cluster.id, 0),
            )
        )

    # The filter's options come from the full list, so narrowing to one lead
    # never empties the control that did the narrowing.
    leads = sorted(
        ({"id": r.lead_id, "name": r.lead_name} for r in rows),
        key=lambda entry: (entry["id"] == NO_LEAD_KEY, entry["name"].casefold()),
    )
    seen, lead_options = set(), []
    for entry in leads:
        if entry["id"] in seen:
            continue
        seen.add(entry["id"])
        lead_options.append(entry)

    if program_lead_id and program_lead_id not in ("all", "All"):
        rows = [r for r in rows if r.lead_id == program_lead_id]

    rows.sort(key=lambda r: (-r.index, r.name.casefold()))
    banded = _banded(rows)
    return {
        "rows": banded,
        "totals": _cluster_totals(rows),
        "leads": lead_options,
        "by_lead": plans_by_lead(banded),
    }


def _page_param(owner_id: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in owner_id).strip("_")
    return f"clusters_{safe or 'owner'}_page"


def plans_by_lead(entries) -> list[dict]:
    """The clusters, nested Programme Lead → CCEO → cluster.

    Owner, 2026-09-18: group the lens by staff name, so a Lead can monitor the
    individual; and drop the Programme Lead column, because a Lead reading this
    page sees their own clusters and their team's, so naming the Lead on every
    row says nothing. Both are the same instruction: the Lead is a heading, not
    a column. A reader who spans teams — Impact Assessment, the Director, the
    RVP — still needs the Lead, and gets it as the outer grouping.

    `entries` are the banded rows the page already built, so each cluster keeps
    the rank, band and superlative it earned against the whole list rather than
    against its own officer's few. A fold, never a second query: a grouping
    that re-queries is a second number that can disagree with the rows it is
    made of.
    """
    leads: dict[str, dict] = {}
    for entry in entries:
        row = entry["row"]
        lead = leads.setdefault(
            row.lead_id,
            {
                "lead_id": row.lead_id,
                "lead_name": row.lead_name,
                "owners": {},
            },
        )
        owner = lead["owners"].setdefault(
            row.owner_id,
            {"owner_id": row.owner_id, "owner_name": row.owner_name, "entries": []},
        )
        owner["entries"].append(entry)

    def totals(cluster_entries) -> dict:
        cluster_rows = [entry["row"] for entry in cluster_entries]
        schools = sum(r.schools for r in cluster_rows)
        reached = sum(r.schools_reached for r in cluster_rows)
        return {
            "clusters": len(cluster_rows),
            "dormant": sum(1 for r in cluster_rows if r.is_dormant),
            "schools": schools,
            "sessions": sum(r.sessions_planned for r in cluster_rows),
            "sessions_done": sum(r.sessions_done for r in cluster_rows),
            "trainings": sum(r.trainings for r in cluster_rows),
            "meetings": sum(r.meetings for r in cluster_rows),
            "visits": sum(r.visits_planned for r in cluster_rows),
            "schools_reached": reached,
            # Always beside the number it came from: a share whose denominator
            # is not on the page cannot be checked.
            "reach": round(100 * reached / schools) if schools else None,
            "budget": sum(r.budget for r in cluster_rows),
        }

    out = []
    for lead in leads.values():
        owners = []
        for owner in lead["owners"].values():
            owner["entries"].sort(key=lambda entry: entry["row"].name.casefold())
            owners.append(
                {
                    **owner,
                    "totals": totals(owner["entries"]),
                    # Each CCEO is its own table, so paging one must not page
                    # the others: a Lead with six officers would otherwise move
                    # all six tables at once.
                    "page_param": _page_param(owner["owner_id"]),
                }
            )
        owners.sort(
            key=lambda entry: (
                entry["owner_id"] == NO_OWNER_KEY,
                entry["owner_name"].casefold(),
            )
        )
        lead_entries = [entry for owner in owners for entry in owner["entries"]]
        out.append(
            {
                "lead_id": lead["lead_id"],
                "lead_name": lead["lead_name"],
                "owners": owners,
                "totals": totals(lead_entries),
            }
        )
    out.sort(
        key=lambda entry: (
            entry["lead_id"] == NO_LEAD_KEY,
            entry["lead_name"].casefold(),
        )
    )
    return out


def _banded(rows) -> list[dict]:
    """Each cluster with its rank, its activity band, and the two superlatives.

    Bands are a share of the busiest cluster rather than a fixed count, so the
    answer means the same thing in a country with three clusters and one with
    three hundred. A cluster with nothing planned is called dormant outright —
    that is not a low score, it is an absence.

    The band names a level ("High activity"), and only the single busiest and
    the single quietest cluster carry a superlative. "Most active" printed
    against ten of fifteen rows is not an answer to "which cluster is the most
    active" — it is the same word used for a band and for a winner.
    """
    top = max((r.index for r in rows), default=0)
    live = [r for r in rows if not r.is_dormant]
    most_active = live[0].cluster_id if live else None
    least_active = live[-1].cluster_id if len(live) > 1 else None
    out = []
    for position, row in enumerate(rows, start=1):
        share = (row.index / top) if top else 0
        if row.is_dormant:
            band, band_label = "dormant", "Nothing planned"
        elif share >= ACTIVE_SHARE:
            band, band_label = "active", "High activity"
        elif share <= QUIET_SHARE:
            band, band_label = "quiet", "Low activity"
        else:
            band, band_label = "steady", "Steady"
        out.append(
            {
                "rank": position,
                "band": band,
                "band_label": band_label,
                "superlative": (
                    "Most active"
                    if row.cluster_id == most_active
                    else ("Least active" if row.cluster_id == least_active else "")
                ),
                "row": row,
                "url": f"/clusters/{row.cluster_id}",
            }
        )
    return out


def _cluster_totals(rows) -> dict:
    schools = sum(r.schools for r in rows)
    reached = sum(r.schools_reached for r in rows)
    ssa = sum(r.ssa_schools for r in rows)
    return {
        "clusters": len(rows),
        "dormant": sum(1 for r in rows if r.is_dormant),
        "schools": schools,
        "sessions": sum(r.sessions_planned for r in rows),
        "sessions_done": sum(r.sessions_done for r in rows),
        "visits": sum(r.visits_planned for r in rows),
        "budget": sum(r.budget for r in rows),
        # Both shares carry the two numbers they were computed from: the
        # metric registry refuses a percentage that arrives without its
        # denominator, because a percentage without one cannot be checked.
        "reached": reached,
        "ssa_schools": ssa,
        "reach": round(100 * reached / schools) if schools else None,
        "ssa_coverage": round(100 * ssa / schools) if schools else None,
    }


__all__ = [
    "ACTIVE_SHARE",
    "ClusterRow",
    "NO_OWNER_KEY",
    "NO_OWNER_LABEL",
    "QUIET_SHARE",
    "WEIGHT_SESSION",
    "WEIGHT_SSA",
    "WEIGHT_VISIT",
    "cluster_performance",
    "plans_by_lead",
]
