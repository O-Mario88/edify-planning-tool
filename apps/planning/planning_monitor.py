"""The Planning Monitor: each CCEO's year against the visits it should hold.

Owner, 2026-09-28:

  "Every CCEO is supposed to plan 560 visits that includes the 2 visits from
  each core school and client school. ... if a staff has 80 core schools, the
  total visits for core schools will be 160 total visits for the core
  schools, and the remaining 400 school visit will be client visit, core
  trained. The rest of the remaining number should be assigned to the
  partner. CD and IA needs to track the planning by how many total number of
  schools and how many unique school visits have been planned. For
  trainings, every schools need to be trained so the IA and CD needs to track
  how many schools have been planned for training (through cluster group
  training and Cluster Meetings). They also would want to track all school
  not clustered, not planned for (Visits, training and both). They also need
  to track how many schools are assigned to projects ... Basically CD and IA
  need to Monitor planning and later execution in real time just like the PLs
  are doing."

So, per CCEO, for one fiscal year:

* **The visit target** — the officer's own ``StaffTargetProfile.visits_target``
  when the CD has set one, else ``DEFAULT_VISITS_TARGET`` (560).
* **Core visits** — two staff visits a year at each Core school
  (``CORE_STAFF_VISITS_PER_SCHOOL``): the target is 2 × Core schools.
* **Client visits** — the rest of the target, at client and Core Trained
  schools (planned alike since 2026-09-28).
* **Partner share** — client-rule schools beyond what the officer's client
  visits can reach are the partner's: needed = schools − client target;
  assigned = schools with partner work (a dated partner visit, or a handover
  the partner has not dated yet).
* **Unique schools** with a visit planned, **schools planned for training**
  (invited to a live group training or cluster meeting, or given an in-school
  training), schools **not clustered**, **not planned** for a visit, for
  training, or for either, and schools **in a Special Project**.
* **Execution** beside each plan: visits delivered and schools whose
  training has been delivered, counted from the same rows as it happens.

Only schools that take planned support are counted: Core, Client and Core
Trained. Champion and Core Graduate schools take donor and story visits only
(owner, 2026-09-25) and are followed on Programme Schools.

Scope is ``scoped_school_queryset``, the rule every other lens reads: the
country for the CD and IA, a Programme Lead's team for the Lead. Every figure
is folded from the school rows under it, so a lead's total is the sum of their
officers' and cannot disagree with them. A fixed handful of queries whatever
the size of the country.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Count, Q

from apps.core.activity_types import TRAINING_TYPES, VISIT_TYPES
from apps.core.metrics import percentage

#: The visits a CCEO plans in a year when no target has been set for them.
DEFAULT_VISITS_TARGET = 560
#: Staff visits a year at each Core school (two of the package's four; the
#: partner delivers the other two).
CORE_STAFF_VISITS_PER_SCHOOL = 2

#: School types the monitor counts.
CORE_TYPES = ("core",)
CLIENT_TYPES = ("client", "core_trained")
MONITORED_TYPES = CORE_TYPES + CLIENT_TYPES

#: The drill-down filters, in the order the page offers them.
GAPS = (
    ("no_both", "Not planned for visits or training"),
    ("no_visit", "No visit planned"),
    ("no_training", "No training planned"),
    ("not_clustered", "Not clustered"),
    ("no_partner", "Beyond staff reach, no partner"),
)
GAP_LABELS = dict(GAPS)

#: The gap columns of the monitor's table, each with the tone its count reads.
GAP_COLUMNS = (
    ("not_clustered", "Not clustered", "warning"),
    ("no_visit", "No visit", "danger"),
    ("no_training", "No training", "danger"),
    ("no_both", "Neither", "danger"),
)


def _gap_cells(row) -> list[tuple[dict, int]]:
    return [
        ({"key": key, "label": label, "tone": tone}, getattr(row, key))
        for key, label, tone in GAP_COLUMNS
    ]


@dataclass
class SchoolState:
    id: str
    code: str
    name: str
    school_type: str
    district: str
    cluster_id: str
    cluster_name: str
    clustered: bool
    officer_id: str
    officer_name: str
    lead_id: str
    lead_name: str
    staff_visits: int = 0
    staff_visits_done: int = 0
    partner_visits: int = 0
    partner_pending: int = 0
    group_training: bool = False
    meeting: bool = False
    in_school_training: bool = False
    training_done: bool = False
    in_project: bool = False

    @property
    def is_core(self) -> bool:
        return self.school_type in CORE_TYPES

    @property
    def has_visit(self) -> bool:
        return bool(self.staff_visits or self.partner_visits)

    @property
    def has_partner(self) -> bool:
        return bool(self.partner_visits or self.partner_pending)

    @property
    def has_training(self) -> bool:
        return self.group_training or self.meeting or self.in_school_training

    @property
    def url(self) -> str:
        return f"/schools/{self.code or self.id}"

    @property
    def cluster_url(self) -> str:
        return f"/clusters/{self.cluster_id}" if self.cluster_id else ""

    def has_gap(self, gap: str) -> bool:
        if gap == "not_clustered":
            return not self.clustered
        if gap == "no_visit":
            return not self.has_visit
        if gap == "no_training":
            return not self.has_training
        if gap == "no_both":
            return not self.has_visit and not self.has_training
        if gap == "no_partner":
            return not self.is_core and not self.staff_visits and not self.has_partner
        return True


@dataclass
class OfficerMonitor:
    """One CCEO's year. Every figure is folded from ``schools``."""

    key: str
    name: str
    lead_id: str
    lead_name: str
    visits_target: int = DEFAULT_VISITS_TARGET
    target_is_set: bool = False
    schools: list = field(default_factory=list)

    # ── Portfolio ──
    @property
    def school_count(self) -> int:
        return len(self.schools)

    @property
    def core_schools(self) -> int:
        return sum(1 for s in self.schools if s.is_core)

    @property
    def client_schools(self) -> int:
        return self.school_count - self.core_schools

    # ── Visits against the target ──
    @property
    def core_visit_target(self) -> int:
        return CORE_STAFF_VISITS_PER_SCHOOL * self.core_schools

    @property
    def client_visit_target(self) -> int:
        return max(0, self.visits_target - self.core_visit_target)

    @property
    def core_visits(self) -> int:
        return sum(s.staff_visits for s in self.schools if s.is_core)

    @property
    def client_visits(self) -> int:
        return sum(s.staff_visits for s in self.schools if not s.is_core)

    @property
    def staff_visits(self) -> int:
        return self.core_visits + self.client_visits

    @property
    def visits_done(self) -> int:
        return sum(s.staff_visits_done for s in self.schools)

    @property
    def visit_progress(self) -> int | None:
        return percentage(self.staff_visits, self.visits_target)

    @property
    def delivery_progress(self) -> int | None:
        return percentage(self.visits_done, self.staff_visits)

    # ── The partner's share ──
    @property
    def partner_needed(self) -> int:
        return max(0, self.client_schools - self.client_visit_target)

    @property
    def partner_schools(self) -> int:
        return sum(1 for s in self.schools if not s.is_core and s.has_partner)

    # ── Coverage ──
    @property
    def schools_with_visit(self) -> int:
        return sum(1 for s in self.schools if s.has_visit)

    @property
    def schools_with_training(self) -> int:
        return sum(1 for s in self.schools if s.has_training)

    @property
    def schools_group_training(self) -> int:
        return sum(1 for s in self.schools if s.group_training)

    @property
    def schools_meeting(self) -> int:
        return sum(1 for s in self.schools if s.meeting)

    @property
    def schools_trained(self) -> int:
        return sum(1 for s in self.schools if s.training_done)

    @property
    def not_clustered(self) -> int:
        return sum(1 for s in self.schools if not s.clustered)

    @property
    def no_visit(self) -> int:
        return self.school_count - self.schools_with_visit

    @property
    def no_training(self) -> int:
        return self.school_count - self.schools_with_training

    @property
    def no_both(self) -> int:
        return sum(1 for s in self.schools if not s.has_visit and not s.has_training)

    @property
    def in_projects(self) -> int:
        return sum(1 for s in self.schools if s.in_project)

    @property
    def visit_tone(self) -> str:
        return _tone(self.visit_progress)

    @property
    def gap_cells(self) -> list[tuple[dict, int]]:
        return _gap_cells(self)


@dataclass
class LeadMonitor:
    """A Programme Lead's column: their CCEOs, and the sums of them."""

    key: str
    name: str
    officers: list = field(default_factory=list)

    def _sum(self, attr: str) -> int:
        return sum(getattr(o, attr) for o in self.officers)

    def __getattr__(self, attr):
        # Every OfficerMonitor count sums the same way; spelling each one out
        # again would be two definitions of one figure.
        if attr.startswith("_") or attr in ("key", "name", "officers"):
            raise AttributeError(attr)
        if isinstance(getattr(OfficerMonitor, attr, None), property) or attr in (
            "visits_target",
        ):
            return self._sum(attr)
        raise AttributeError(attr)

    @property
    def visit_progress(self) -> int | None:
        return percentage(self.staff_visits, self.visits_target)

    @property
    def delivery_progress(self) -> int | None:
        return percentage(self.visits_done, self.staff_visits)

    @property
    def visit_tone(self) -> str:
        return _tone(self.visit_progress)

    @property
    def officer_count(self) -> int:
        return len(self.officers)

    @property
    def gap_cells(self) -> list[tuple[dict, int]]:
        return _gap_cells(self)


def _tone(progress: int | None) -> str:
    if progress is None:
        return "neutral"
    if progress >= 100:
        return "success"
    if progress >= 50:
        return "info"
    return "warning"


def planning_monitor(
    principal,
    *,
    fy: str,
    program_lead_id: str | None = None,
    gap: str | None = None,
    officer_id: str | None = None,
) -> dict:
    """The monitor for this reader and year.

    Returns ``leads`` (LeadMonitor, each holding its OfficerMonitors),
    ``totals`` (a LeadMonitor over everyone), ``lead_options``, and
    ``gap_schools`` — the schools matching the chosen gap, narrowed to the
    chosen lead and officer, for the drill-down table.
    """
    from apps.core.scoping import resolve_user_scope, scoped_school_queryset
    from apps.planning.portfolio_service import (
        NO_LEAD_KEY,
        NO_LEAD_LABEL,
        UNASSIGNED_KEY,
        UNASSIGNED_LABEL,
        _staff_directory,
    )
    from apps.schools.lifecycle_service import active_schools

    fy = str(fy)
    empty = {
        "fy": fy,
        "leads": [],
        "totals": LeadMonitor(key="all", name="All"),
        "lead_options": [],
        "officer_options": [],
        "gap_schools": [],
    }
    queryset = scoped_school_queryset(resolve_user_scope(principal))
    if queryset is None:
        return empty
    queryset = (
        active_schools(queryset)
        .filter(school_type__in=MONITORED_TYPES)
        .select_related("district")
    )
    rows = list(
        queryset.order_by("name").values(
            "id",
            "school_id",
            "name",
            "school_type",
            "district__name",
            "cluster_id",
            "cluster_status",
            "account_owner_id",
        )
    )
    if not rows:
        return empty

    directory = _staff_directory({r["account_owner_id"] for r in rows})
    clusters = _cluster_names({r["cluster_id"] for r in rows})
    schools: dict[str, SchoolState] = {}
    for r in rows:
        owner = directory.get(str(r["account_owner_id"] or ""))
        schools[r["id"]] = SchoolState(
            id=r["id"],
            code=r["school_id"] or "",
            name=r["name"],
            school_type=r["school_type"],
            district=r["district__name"] or "",
            cluster_id=r["cluster_id"] or "",
            cluster_name=clusters.get(r["cluster_id"], ""),
            clustered=bool(r["cluster_id"]) and r["cluster_status"] == "clustered",
            officer_id=owner["officer_id"] if owner else UNASSIGNED_KEY,
            officer_name=owner["officer_name"] if owner else UNASSIGNED_LABEL,
            lead_id=owner["lead_id"] if owner else NO_LEAD_KEY,
            lead_name=owner["lead_name"] if owner else NO_LEAD_LABEL,
        )

    school_ids = queryset.values("id")
    _count_activities(schools, school_ids, fy)
    _count_partner_handovers(schools, school_ids)
    _count_cluster_sessions(schools, school_ids, fy)
    _mark_projects(schools, school_ids)

    targets = _visit_targets({s.officer_id for s in schools.values()}, fy)
    officers: dict[tuple[str, str], OfficerMonitor] = {}
    leads: dict[str, LeadMonitor] = {}
    for school in schools.values():
        lead = leads.get(school.lead_id)
        if lead is None:
            lead = leads[school.lead_id] = LeadMonitor(
                key=school.lead_id, name=school.lead_name
            )
        officer_key = (school.lead_id, school.officer_id)
        officer = officers.get(officer_key)
        if officer is None:
            target = targets.get(school.officer_id)
            officer = officers[officer_key] = OfficerMonitor(
                key=school.officer_id,
                name=school.officer_name,
                lead_id=school.lead_id,
                lead_name=school.lead_name,
                visits_target=target or DEFAULT_VISITS_TARGET,
                target_is_set=bool(target),
            )
            lead.officers.append(officer)
        officer.schools.append(school)

    for lead in leads.values():
        lead.officers.sort(key=lambda o: (o.key == UNASSIGNED_KEY, o.name.casefold()))
    ordered = sorted(
        leads.values(), key=lambda g: (g.key == NO_LEAD_KEY, g.name.casefold())
    )
    lead_options = [
        {"id": lead.key, "name": lead.name, "count": lead.school_count}
        for lead in ordered
    ]
    totals = LeadMonitor(
        key="all",
        name="All",
        officers=[officer for lead in ordered for officer in lead.officers],
    )

    shown = ordered
    if program_lead_id and program_lead_id not in ("all", "All"):
        shown = [lead for lead in ordered if lead.key == program_lead_id] or ordered
    officer_options = [
        {"id": officer.key, "name": officer.name}
        for lead in shown
        for officer in lead.officers
    ]
    gap_schools = []
    if gap in GAP_LABELS:
        for lead in shown:
            for officer in lead.officers:
                if officer_id and officer.key != officer_id:
                    continue
                gap_schools.extend(s for s in officer.schools if s.has_gap(gap))
        gap_schools.sort(key=lambda s: (s.officer_name.casefold(), s.name.casefold()))

    return {
        "fy": fy,
        "leads": shown,
        "totals": totals,
        "lead_options": lead_options,
        "officer_options": officer_options,
        "gap_schools": gap_schools,
    }


def _cluster_names(cluster_ids) -> dict[str, str]:
    from apps.clusters.models import Cluster

    ids = {c for c in cluster_ids if c}
    if not ids:
        return {}
    return dict(Cluster.objects.filter(id__in=ids).values_list("id", "name"))


def _live(qs):
    """Activities that are a plan: not abandoned, not returned for
    replanning, not a request still waiting on the school's owner."""
    from apps.planning.school_planning_badges import (
        AWAITING_VERIFICATION_STATUSES,
        PLANNED_STATUSES,
        VERIFIED_STATUSES,
    )

    return qs.filter(
        deleted_at__isnull=True,
        status__in=PLANNED_STATUSES
        | AWAITING_VERIFICATION_STATUSES
        | VERIFIED_STATUSES,
    )


def _delivered_statuses():
    from apps.planning.school_planning_badges import (
        AWAITING_VERIFICATION_STATUSES,
        VERIFIED_STATUSES,
    )

    return AWAITING_VERIFICATION_STATUSES | VERIFIED_STATUSES


def _count_activities(schools: dict, school_ids, fy: str) -> None:
    """Visits and in-school trainings at each school, planned and delivered."""
    from apps.activities.models import Activity
    from apps.planning.visit_gate import COMPANION_VISIT_PURPOSE

    delivered = _delivered_statuses()
    rows = (
        _live(Activity.objects.filter(school_id__in=school_ids, fy=fy))
        .filter(Q(activity_type__in=VISIT_TYPES) | Q(activity_type__in=TRAINING_TYPES))
        .exclude(purpose_type=COMPANION_VISIT_PURPOSE)
        .values("school_id", "activity_type", "delivery_type", "status")
        .annotate(n=Count("id"))
    )
    visit_types = {str(t) for t in VISIT_TYPES}
    for row in rows:
        school = schools.get(row["school_id"])
        if school is None:
            continue
        done = row["status"] in delivered
        if row["activity_type"] in visit_types:
            if row["delivery_type"] == "partner":
                school.partner_visits += row["n"]
            else:
                school.staff_visits += row["n"]
                if done:
                    school.staff_visits_done += row["n"]
        else:
            school.in_school_training = True
            if done:
                school.training_done = True


def _count_partner_handovers(schools: dict, school_ids) -> None:
    """Handovers a partner has not dated yet: the school is the partner's."""
    from apps.partners.models import PartnerAssignment

    for school_id, n in (
        PartnerAssignment.objects.filter(
            school_id__in=school_ids,
            status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
        )
        .values("school_id")
        .annotate(n=Count("id"))
        .values_list("school_id", "n")
    ):
        if school_id in schools:
            schools[school_id].partner_pending += n


def _count_cluster_sessions(schools: dict, school_ids, fy: str) -> None:
    """Group trainings and cluster meetings each school is invited to.

    By name — ClusterActivityAttendance, written when the session is
    scheduled — never because the school happens to be in the cluster
    (apps.schools.school_status.cluster_training_coverage holds the same
    line). Delivered once the school is marked as having attended a
    delivered session.
    """
    from apps.activities.models import Activity, ClusterActivityAttendance
    from apps.core.activity_types import CLUSTER_MEETING_TYPES

    delivered = _delivered_statuses()
    sessions = _live(Activity.objects.filter(fy=fy, cluster_id__isnull=False))
    meeting_types = {str(t) for t in CLUSTER_MEETING_TYPES}
    training_types = {str(t) for t in TRAINING_TYPES}
    for school_id, activity_type, status, attended in (
        ClusterActivityAttendance.objects.filter(
            school_id__in=school_ids,
            activity__in=sessions.filter(
                Q(activity_type__in=meeting_types) | Q(activity_type__in=training_types)
            ),
        )
        .filter(Q(invited=True) | Q(attended=True))
        .values_list(
            "school_id", "activity__activity_type", "activity__status", "attended"
        )
    ):
        school = schools.get(school_id)
        if school is None:
            continue
        if activity_type in meeting_types:
            school.meeting = True
        else:
            school.group_training = True
        if attended and status in delivered:
            school.training_done = True


def _mark_projects(schools: dict, school_ids) -> None:
    """Schools enrolled in an open Special Project."""
    from apps.projects.models import OPEN_PROJECT_STATUSES, ProjectSchoolAssignment

    open_statuses = [str(getattr(s, "value", s)) for s in OPEN_PROJECT_STATUSES]
    for school_id in (
        ProjectSchoolAssignment.objects.filter(
            school_id__in=school_ids,
            project__deleted_at__isnull=True,
            project__status__in=open_statuses,
        )
        .values_list("school_id", flat=True)
        .distinct()
    ):
        if school_id in schools:
            schools[school_id].in_project = True


def _visit_targets(officer_ids, fy: str) -> dict[str, int]:
    """Each officer's visits target for the year, where the CD has set one."""
    from apps.accounts.models import StaffTargetProfile

    ids = {i for i in officer_ids if i}
    if not ids:
        return {}
    return {
        staff_id: target
        for staff_id, target in StaffTargetProfile.objects.filter(
            staff_id__in=ids, fy=str(fy), visits_target__gt=0
        ).values_list("staff_id", "visits_target")
    }


__all__ = [
    "CORE_STAFF_VISITS_PER_SCHOOL",
    "DEFAULT_VISITS_TARGET",
    "GAPS",
    "GAP_LABELS",
    "LeadMonitor",
    "OfficerMonitor",
    "SchoolState",
    "planning_monitor",
]
