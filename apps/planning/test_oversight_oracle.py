"""Oracle for the planning-oversight performance pass (2026-09-24).

Every function that pass rewrote is copied below exactly as it stood before it
(the "frozen" references, under their original names). The tests build one
fixture that spans the lifecycle — cost lines, cluster and partner work, every
live status and the dead ones, schools and clusters that are missing or closed,
several officers and leads, and the country, Programme Lead and regional lenses
— and assert that the live code and the frozen code agree on it, value for
value and in the same order.

The page tests go furthest: Country Planning Oversight, Team Planning
Oversight, Cluster Oversight, a Lead's team panel and both exports are
requested twice, once as they run now and once with every frozen reference
patched back in, and what each view handed its template (and the page it
drew) must be identical.

Names below that shadow the live ones (``summarize``, ``_StaffDirectory``...)
are the frozen copies; the live code is always reached through its module
(``svc.summarize``). Delete a frozen reference only with the tests that use it.
"""

from __future__ import annotations

import re
from contextlib import ExitStack, contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.db.models import Count, Max, Model, Q, QuerySet, Sum
from django.template import engines
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffGeographyAssignment,
    StaffProfile,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import (
    Activity,
    ActivityScheduleCostLine,
    ClusterActivityAttendance,
)
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.clusters import oversight_service as clusters_svc
from apps.clusters.models import Cluster
from apps.clusters.oversight_service import (
    UNASSIGNED,
    _decorate_sessions,
    _label,
    _last_delivered_dates,
    _staff_directory,
    _supervisor_of,
    cluster_activity_by_person,
)
from apps.core.activity_types import (
    CLUSTER_MEETING_TYPES,
    COMPLETED_WORK_STATUSES,
    TRAINING_TYPES,
    VISIT_TYPES,
)
from apps.core.enums import SchoolType
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.rbac import EdifyRole
from apps.core.scoping import cluster_queryset, id_array, or_empty, resolve_user_scope
from apps.frontend.views import oversight_views as views
from apps.frontend.views.oversight_views import WHOLE_TEAM_TAB, _team_members
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.planning import cluster_performance_service as perf
from apps.planning import oversight_service as svc
from apps.planning import risk_service
from apps.planning.oversight_service import (
    _ACTIVITY_COLUMNS,
    _CLUSTER_COLUMNS,
    _SCHOOL_COLUMNS,
    STAGE_PARTNER_SCHEDULED,
    STAGE_STAFF_SCHEDULED,
    _both_id_spaces,
)
from apps.planning.risk_service import (
    _SEVERITY_ORDER,
    PlanningRisk,
    _evidence_outstanding,
    _ia_verification_overdue,
    _overdue,
    _partner_not_scheduled,
    _payment_overdue,
    _rescheduled_repeatedly,
    _returned_by_ia,
    _salesforce_missing,
    _scheduled_without_cost,
)
from apps.schools.models import School
from apps.schools.school_status import DEAD_STATUSES
from apps.ssa.models import SsaRecord, SsaScore

# ── Frozen from apps/planning/oversight_service.py ──────────────────────────


class _Record:
    """Attribute access over one row of values, shaped like the model.

    An oversight page reads a fixed set of columns from every activity in its
    scope. As model instances, each with six joined relations, that was
    ~520,000 objects for the country at 50,000 schools, and most of an 11 s
    request (2026-09-24 live-performance audit, R2). `_activity_item` reads
    the same attributes off these as off a model, and `build_item_by_reference`
    still passes it a real one.
    """

    def __init__(self, **fields):
        self.__dict__.update(fields)


def _record(fields: dict) -> _Record:
    record = _Record.__new__(_Record)
    record.__dict__ = fields
    return record


def _activity_records(rows) -> list[_Record]:
    """One record per activity row; each school, cluster, district, region
    and course is one shared record however many activities point at it."""
    width = len(_ACTIVITY_COLUMNS)
    school_end = width + len(_SCHOOL_COLUMNS)
    cluster_end = school_end + len(_CLUSTER_COLUMNS)
    names: dict[tuple, _Record] = {}
    schools: dict[str, _Record] = {}
    clusters: dict[str, _Record] = {}
    courses: dict[str, _Record] = {}

    def named(kind, key, name, **extra):
        if key is None:
            return None
        found = names.get((kind, key))
        if found is None:
            found = names[(kind, key)] = _record({"name": name, **extra})
        return found

    records = []
    for row in rows:
        fields = dict(zip(_ACTIVITY_COLUMNS, row[:width]))
        school_id = fields["school_id"]
        school = None
        if school_id is not None:
            school = schools.get(school_id)
            if school is None:
                (
                    code,
                    school_name,
                    school_type,
                    district_id,
                    district_name,
                    region_id,
                    region_name,
                ) = row[width:school_end]
                school = schools[school_id] = _record(
                    {
                        "school_id": code,
                        "name": school_name,
                        "school_type": school_type,
                        "district_id": district_id,
                        "district": named("district", district_id, district_name),
                        "region_id": region_id,
                        "region": named("region", region_id, region_name),
                    }
                )
        fields["school"] = school

        cluster_id = fields["cluster_id"]
        cluster = None
        if cluster_id is not None:
            cluster = clusters.get(cluster_id)
            if cluster is None:
                (
                    cluster_name,
                    district_id,
                    district_name,
                    region_id,
                    region_name,
                ) = row[school_end:cluster_end]
                region = named("region", region_id, region_name)
                cluster = clusters[cluster_id] = _record(
                    {
                        "name": cluster_name,
                        "district_id": district_id,
                        "district": named(
                            "cluster-district",
                            district_id,
                            district_name,
                            region_id=region_id,
                            region=region,
                        ),
                    }
                )
        fields["cluster"] = cluster

        course_id = fields["training_course_id"]
        course = None
        if course_id is not None:
            course = courses.get(course_id)
            if course is None:
                display_name, source_name = row[cluster_end:]
                course = courses[course_id] = _record(
                    {"display_name": display_name, "source_name": source_name}
                )
        fields["training_course"] = course
        records.append(_record(fields))
    return records


def _cost_by_activity(activity_ids) -> dict[str, int]:
    """Planned cost per activity, from the canonical cost lines, in one query.

    Summed from ActivityScheduleCostLine rather than read from
    Activity.est_cost_cents so the page and the budget cannot disagree: the
    lines are what the fund request, the monthly budget and the annual budget
    are built from.
    """
    from apps.activities.models import ActivityScheduleCostLine

    if not activity_ids:
        return {}
    # One array parameter, not one bind parameter per activity: a country
    # page passes every activity in the country.
    from apps.core.scoping import id_array

    rows = (
        ActivityScheduleCostLine.objects.filter(activity_id__in=id_array(activity_ids))
        .values("activity_id")
        .annotate(total=Sum("amount"))
    )
    return {r["activity_id"]: int(r["total"] or 0) for r in rows}


class _StaffDirectory:
    """Names and supervisors for every person referenced, in three queries.

    Built up-front from the ids actually present, because the alternative — a
    lookup per row — is the N+1 that makes a country page unusable.
    """

    def __init__(self, activities, assignments):
        ids: set[str] = set()
        for a in activities:
            ids.update({a.responsible_staff_id, a.monitored_by_staff_id})
        for pa in assignments:
            ids.update({pa.monitoring_staff_id, pa.assigning_staff_id})
        ids.discard(None)
        ids.discard("")

        self._names: dict[str, str] = {}
        self._roles: dict[str, str] = {}
        self._supervisor_of: dict[str, str] = {}
        self._staff_for: dict[str, str] = {}

        if not ids:
            return

        from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
        from apps.core.rbac import EdifyRole

        profiles = StaffProfile.objects.filter(
            Q(id__in=ids) | Q(user_id__in=ids)
        ).select_related("user")
        staff_ids = set()
        for p in profiles:
            name = getattr(p.user, "name", "") or getattr(p.user, "email", "")
            role = getattr(p.user, "active_role", "") or ""
            staff_ids.add(p.id)
            for key in (p.id, p.user_id):
                if key:
                    self._names[key] = name
                    self._roles[key] = role
                    self._staff_for[key] = p.id

        links = StaffSupervisorAssignment.objects.filter(
            supervisee_id__in=staff_ids,
            supervisor__user__active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        ).select_related("supervisor__user")
        for link in links:
            supervisor_user = getattr(link.supervisor, "user", None)
            supervisor_name = (
                getattr(supervisor_user, "name", "")
                or getattr(supervisor_user, "email", "")
                or ""
            )
            self._supervisor_of[link.supervisee_id] = link.supervisor_id
            if link.supervisor_id:
                self._names.setdefault(link.supervisor_id, supervisor_name)
                if supervisor_user is not None:
                    self._names.setdefault(supervisor_user.id, supervisor_name)

    def name(self, staff_id) -> str:
        return self._names.get(staff_id, "") if staff_id else ""

    def role(self, staff_id) -> str:
        return self._roles.get(staff_id, "") if staff_id else ""

    def supervisor_of(self, staff_id) -> tuple[str | None, str]:
        if not staff_id:
            return None, ""
        canonical = self._staff_for.get(staff_id, staff_id)
        from apps.core.rbac import EdifyRole

        if (
            self._roles.get(canonical) == EdifyRole.COUNTRY_PROGRAM_LEAD.value
            or self._roles.get(staff_id) == EdifyRole.COUNTRY_PROGRAM_LEAD.value
        ):
            return canonical, self._names.get(canonical, "")
        supervisor_id = self._supervisor_of.get(canonical)
        return supervisor_id, self._names.get(
            supervisor_id, ""
        ) if supervisor_id else ""


def summarize(items) -> dict:
    """Every headline number, folded from the items shown underneath them.

    Nothing here re-queries. A KPI that disagrees with the table below it is
    not possible while this stays a fold, which is the whole reason it is one.
    """
    items = list(items)
    staff_scheduled = [i for i in items if i.stage == STAGE_STAFF_SCHEDULED]
    partner_awaiting = [i for i in items if i.is_awaiting_partner_schedule]
    partner_scheduled = [i for i in items if i.stage == STAGE_PARTNER_SCHEDULED]
    scheduled = staff_scheduled + partner_scheduled

    # Execution progress counts only work whose date has arrived. Future work
    # is not late, and counting it as unfinished would report every team as
    # behind on the first day of a period.
    today = date.today()
    due = [i for i in scheduled if i.planned_date and i.planned_date <= today]
    completed_due = [i for i in due if i.is_completed]

    return {
        "total_planned": len(items),
        "staff_scheduled": len(staff_scheduled),
        "partner_awaiting_schedule": len(partner_awaiting),
        "partner_scheduled": len(partner_scheduled),
        "scheduled_total": len(scheduled),
        "at_risk": len([i for i in items if i.at_risk]),
        "needs_attention": len([i for i in items if i.at_risk]),
        "planned_budget": sum(i.planned_cost for i in items),
        "completed": len([i for i in items if i.is_completed]),
        "due_count": len(due),
        "execution_progress": (
            round(len(completed_due) * 100 / len(due)) if due else None
        ),
        "cost_missing": len([i for i in scheduled if i.cost_missing]),
        # The tail of the chain. Folded from the same items, so these agree
        # with the rows like every other number here. They exist because a
        # plan that is 100% delivered and 0% verified is not a finished plan,
        # and a page that stops at "completed" says it is.
        "awaiting_verification": len(
            [i for i in items if i.submitted_to_ia_at and i.ia_status == "pending"]
        ),
        "awaiting_payment": len(
            [
                i
                for i in items
                if i.ia_status == "confirmed"
                and (i.finance_status or "none")
                not in (
                    "paid",
                    "disbursed",
                    "netsuite_accountability",
                    "closed",
                    "rejected",
                )
            ]
        ),
    }


def system_program_leads() -> list[dict]:
    """All staff with the Program Lead role, from the role system.

    This is the source of truth for PL tabs on the Country Oversight page.
    PLs are defined by their role, not inferred from activity supervisor links.
    A PL with zero activities still appears; the IA never does.
    """
    from apps.accounts.models import StaffProfile
    from apps.core.rbac import EdifyRole

    profiles = (
        StaffProfile.objects.filter(
            user__active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        )
        .select_related("user")
        .order_by("user__name")
    )
    return [
        {
            "id": p.id,
            "user_id": p.user_id,
            "name": getattr(p.user, "name", "") or getattr(p.user, "email", ""),
            "ids": _both_id_spaces({p.id}),
        }
        for p in profiles
    ]


# ── Frozen from apps/planning/risk_service.py ───────────────────────────────


def risks_for(item, today: date) -> list[PlanningRisk]:
    """Every risk currently true of this item, worst first."""
    found = [
        detector(item, today)
        for detector in (
            _partner_not_scheduled,
            _scheduled_without_cost,
            _overdue,
            _evidence_outstanding,
            _salesforce_missing,
            _returned_by_ia,
            _rescheduled_repeatedly,
            _ia_verification_overdue,
            _payment_overdue,
        )
    ]
    risks = [r for r in found if r is not None]
    risks.sort(key=lambda r: _SEVERITY_ORDER.get(r.severity, 9))
    return risks


# ── Frozen from apps/frontend/views/oversight_views.py ──────────────────────


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


def _filter_options(items) -> dict:
    """The values in the scoped period before advanced filters narrow it.

    This keeps other districts selectable while avoiding values that never
    occur in the team's work for the period.
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


# ── Frozen from apps/planning/cluster_performance_service.py ────────────────


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
            school_id__in=id_array(school_to_cluster),
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
                activity__cluster_id__in=id_array(cluster_ids),
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
                activity__school_id__in=id_array(school_to_cluster),
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
            school_id__in=id_array(school_to_cluster),
            fy=str(fy),
            deleted_at__isnull=True,
        )
        .values_list("school_id", flat=True)
        .distinct()
    )
    out: dict[str, int] = {}
    for school_id in rows:
        cluster_id = school_to_cluster[school_id]
        out[cluster_id] = out.get(cluster_id, 0) + 1
    return out


# ── Frozen from apps/clusters/oversight_service.py ──────────────────────────


def cluster_oversight_table_data(principal, *, fy: str | None = None) -> dict:
    """Full database-driven cluster oversight dataset.

    Returns:
    - Clusters formatted with:
      Cluster Name, District, Cluster leader's Name, Cluster leader's Phone number,
      # School SSA scores average, Least performing intervention, Date of last activity.
    - Tab hierarchy:
      - For PL: Level 1 tabs are their supervised CCEOs.
      - For IA, CD, RPL: Level 1 tabs are Supervising Program Leads,
        Level 2 tabs are CCEOs under each PL.
    - Responsible CCEO column is excluded from table rows (represented by the active tab).
    - Executive Cluster Performance metrics (total clusters, active/dormant, sessions, reach, budget).
    """
    from apps.core.enums import SsaIntervention
    from apps.core.rbac import EdifyRole
    from apps.core.scoping import cluster_queryset, resolve_user_scope
    from apps.schools.models import School
    from apps.ssa.models import SsaRecord, SsaScore
    from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES
    from apps.planning.oversight_service import system_program_leads
    from django.db.models import Avg

    scope = resolve_user_scope(principal)
    is_programme_lead = scope.active_role == EdifyRole.COUNTRY_PROGRAM_LEAD.value
    uses_member_tabs = is_programme_lead or scope.active_role == EdifyRole.CCEO.value

    clusters = list(
        cluster_queryset(
            scope,
            base=Cluster.objects.filter(deleted_at__isnull=True),
        )
        .select_related("district")
        .order_by("name")
    )
    cluster_ids = [c.id for c in clusters]

    # The group trainings and cluster meetings, from the same planning records
    # My Plan reads. The operational year reads forward into the years ahead:
    # in September people plan October, which is the next fiscal year, and a
    # page limited to the operational year showed empty tables while My Plan
    # listed the sessions (owner, 2026-09-23).
    from apps.core.fy import get_operational_fy
    from apps.core.scoping import owner_ids
    from apps.planning import oversight_service as planning
    from apps.planning.fy_policy import horizon_label, planning_horizon

    page_fy = str(fy or get_operational_fy())
    plan_fys = planning_horizon(page_fy)
    cluster_work = [
        item
        for item in planning.build_items(
            principal,
            fy=page_fy,
            fys=plan_fys,
            activity_types=tuple(CLUSTER_MEETING_TYPES + TRAINING_TYPES),
            cluster_work_only=True,
        )
        if item.cluster_id
        and not item.is_in_school_training
        and item.activity_type in CLUSTER_MEETING_TYPES + TRAINING_TYPES
    ]

    # Keep the activity ledger within this page's cluster/team scope, even
    # when a development account also carries superuser privileges.
    allowed_people = planning._both_id_spaces(
        set(owner_ids(principal)) | set(scope.supervised_staff_ids or [])
    )
    cluster_work = [
        item
        for item in cluster_work
        if item.cluster_id in cluster_ids
        or (uses_member_tabs and item.operational_owner_id in allowed_people)
    ]
    _decorate_sessions(principal, cluster_work)
    # Not part of the frozen pass: the Salesforce ID and Evidence columns and
    # the completed-last order every planned activities table took on
    # 2026-09-26, applied here as the live code applies them, so this oracle
    # keeps proving the performance pass changed nothing else.
    from apps.activities.completion_columns import annotate, sort_completed_last

    annotate(cluster_work)
    clusters_svc.hold_complete_to_both_columns(cluster_work)
    sort_completed_last(cluster_work)

    # One directory for the people holding clusters and the people running
    # the sessions. A person's work is filed by the same profile and the same
    # Programme Lead as their clusters, in either id space: resolving the two
    # separately filed a CCEO's clusters under one tab and their sessions
    # under another, or under a second tab of the same name.
    owners = _staff_directory(
        {c.responsible_staff_id for c in clusters}
        | {item.operational_owner_id for item in cluster_work}
    )
    placements = []
    for item in cluster_work:
        worker = owners.get((item.operational_owner_id or "").strip())
        placements.append((item, worker, _supervisor_of(worker)))

    # 1. School counts & mapping
    schools = list(
        School.objects.filter(
            cluster_id__in=cluster_ids, deleted_at__isnull=True
        ).values("id", "cluster_id")
    )
    school_to_cluster = {s["id"]: s["cluster_id"] for s in schools}
    cluster_schools_count: dict[str, int] = {}
    for s in schools:
        cid = s["cluster_id"]
        cluster_schools_count[cid] = cluster_schools_count.get(cid, 0) + 1

    # 2. SSA average per cluster
    ssa_filter = {
        "school_id__in": list(school_to_cluster.keys()),
        "deleted_at__isnull": True,
    }
    if fy:
        ssa_filter["fy"] = str(fy)

    ssa_avgs = {
        row["school__cluster_id"]: row["avg_score"]
        for row in SsaRecord.objects.filter(**ssa_filter)
        .values("school__cluster_id")
        .annotate(avg_score=Avg("average_score"))
    }

    # 3. Least performing intervention per cluster
    score_filter = {
        "ssa_record__school_id__in": list(school_to_cluster.keys()),
        "ssa_record__deleted_at__isnull": True,
    }
    if fy:
        score_filter["ssa_record__fy"] = str(fy)

    cluster_intervention_scores: dict[str, list] = {}
    for row in (
        SsaScore.objects.filter(**score_filter)
        .values("ssa_record__school__cluster_id", "intervention")
        .annotate(avg=Avg("score"))
    ):
        cid = row["ssa_record__school__cluster_id"]
        cluster_intervention_scores.setdefault(cid, []).append(
            (row["intervention"], row["avg"])
        )

    least_interventions: dict[str, str] = {}
    for cid, scores in cluster_intervention_scores.items():
        scores.sort(key=lambda x: x[1])
        int_code, min_score = scores[0]
        try:
            int_label = SsaIntervention(int_code).label
        except Exception:
            int_label = int_code.replace("_", " ").title()
        least_interventions[cid] = f"{int_label} ({round(min_score, 1)})"

    # 4. Date of last activity: the last meeting or training delivered.
    last_activities = _last_delivered_dates(cluster_ids)

    # 5. Format cluster table rows (excluding Responsible CCEO column)
    formatted_clusters = []
    for cluster in clusters:
        owner = owners.get((cluster.responsible_staff_id or "").strip())
        lead = _supervisor_of(owner)
        c_avg = ssa_avgs.get(cluster.id)
        avg_str = f"{round(c_avg, 1)}" if c_avg is not None else "—"
        least_str = least_interventions.get(cluster.id, "—")
        last_act = last_activities.get(cluster.id)
        last_act_str = last_act.strftime("%b %d, %Y") if last_act else "—"

        formatted_clusters.append(
            {
                "cluster_id": cluster.id,
                "name": cluster.name,
                "district": getattr(cluster.district, "name", "") or "—",
                "cluster_leader_name": cluster.cluster_leader_name or "—",
                "cluster_leader_phone": cluster.cluster_leader_phone or "—",
                "ssa_score_avg": avg_str,
                "least_performing_intervention": least_str,
                "last_activity_date": last_act_str,
                "schools_count": cluster_schools_count.get(cluster.id, 0),
                "owner_id": getattr(owner, "id", None),
                "owner_user_id": getattr(owner, "user_id", None),
                "owner_name": _label(owner) if owner else "Unassigned",
                "lead_id": getattr(lead, "id", None),
                "lead_user_id": getattr(lead, "user_id", None),
                "lead_name": _label(lead) if lead else "Unassigned",
            }
        )

    # 6. Build hierarchy tabs (Unified across PL, IA, CD, RPL)
    sys_pls = system_program_leads()
    if not scope.country_scope:
        visible_lead_ids = {
            str(identifier)
            for row in formatted_clusters
            for identifier in (row["lead_id"], row["lead_user_id"])
            if identifier
        }
        visible_lead_ids.update(
            str(lead.id) for _item, _worker, lead in placements if lead
        )
        sys_pls = [
            pl for pl in sys_pls if visible_lead_ids.intersection(map(str, pl["ids"]))
        ]
    pl_lookup: dict[str, dict] = {}
    leads_data = []
    for pl in sys_pls:
        pl_dict = {
            "id": pl["id"],
            "name": pl["name"],
            "cceos": {},
            "count": 0,
            "schools": 0,
        }
        leads_data.append(pl_dict)
        for pid in pl["ids"]:
            pl_lookup[pid] = pl_dict

    unassigned_pl: dict = {
        "id": "__unassigned__",
        "name": "Unassigned",
        "cceos": {},
        "count": 0,
        "schools": 0,
    }

    for row in formatted_clusters:
        target_pl = pl_lookup.get(row["lead_id"]) if row["lead_id"] else None
        if not target_pl and row["lead_user_id"]:
            target_pl = pl_lookup.get(row["lead_user_id"])
        if not target_pl:
            target_pl = unassigned_pl

        target_pl["count"] += 1
        target_pl["schools"] += row["schools_count"]

        oid = row["owner_id"] or "__unassigned__"
        cceo_entry = target_pl["cceos"].setdefault(
            oid,
            {
                "id": oid,
                "name": row["owner_name"],
                "clusters": [],
                "count": 0,
                "schools": 0,
            },
        )
        cceo_entry["clusters"].append(row)
        cceo_entry["count"] += 1
        cceo_entry["schools"] += row["schools_count"]

    # Convert cceos dict to sorted list for each PL
    for pl_entry in leads_data:
        pl_entry["cceo_tabs"] = sorted(
            pl_entry["cceos"].values(),
            key=lambda g: (g["id"] == "__unassigned__", g["name"].casefold()),
        )

    def lead_entry(lead):
        return pl_lookup.get(str(lead.id)) if lead else None

    if unassigned_pl["count"] > 0 or any(
        lead_entry(lead) is None for _item, _worker, lead in placements
    ):
        unassigned_pl["cceo_tabs"] = sorted(
            unassigned_pl["cceos"].values(),
            key=lambda g: (g["id"] == "__unassigned__", g["name"].casefold()),
        )
        leads_data.append(unassigned_pl)

    # Determine default selected PL tab (preselect viewing PL if applicable)
    user_staff_ids = set(owner_ids(principal))
    selected_program_lead = None
    for pl_entry in leads_data:
        if pl_entry["id"] in user_staff_ids:
            selected_program_lead = pl_entry["id"]
            break
        for pl in sys_pls:
            if pl["id"] == pl_entry["id"] and any(
                pid in user_staff_ids for pid in pl["ids"]
            ):
                selected_program_lead = pl_entry["id"]
                break
        if selected_program_lead:
            break

    cceo_tabs = []
    if uses_member_tabs:
        own_rows = [
            row
            for row in formatted_clusters
            if str(row["owner_id"]) in user_staff_ids
            or str(row["owner_user_id"]) in user_staff_ids
        ]
        cceo_tabs = [
            {
                "id": "my-clusters",
                "name": "My Clusters",
                "clusters": own_rows,
                "count": len(own_rows),
                "schools": sum(row["schools_count"] for row in own_rows),
            }
        ]
        officer_tabs = [
            tab
            for lead in leads_data
            for tab in lead["cceo_tabs"]
            if str(tab["id"]) not in user_staff_ids
        ]
        # Every officer on the roster is a tab and a series, holding clusters
        # or not: an officer with none is a zero row, never a missing one, so
        # the chart reads as the team and nobody's colour shifts when a
        # colleague has nothing to show.
        listed = {str(tab["id"]) for tab in officer_tabs}
        for member in planning.program_lead_members(principal.id):
            if str(member["id"]) in listed or member["ids"].intersection(
                user_staff_ids
            ):
                continue
            officer_tabs.append(
                {
                    "id": member["id"],
                    "name": member["name"],
                    "clusters": [],
                    "count": 0,
                    "schools": 0,
                }
            )
        officer_tabs.sort(
            key=lambda tab: (tab["id"] == "__unassigned__", tab["name"].casefold())
        )
        cceo_tabs.extend(officer_tabs)

    # Populate each person's single tab with their clusters and the work they
    # are responsible for, even if a different team member holds the cluster.
    def member_tab(member):
        return {
            "id": member["id"],
            "name": member["name"],
            "clusters": [],
            "count": 0,
            "schools": 0,
        }

    def session_list(tab, item):
        key = "meetings" if item.activity_type in CLUSTER_MEETING_TYPES else "trainings"
        return tab.setdefault(key, [])

    def worker_key(worker):
        return str(worker.id) if worker else UNASSIGNED

    def worker_name(item, worker):
        return (
            _label(worker) if worker else (item.operational_owner_name or "Unassigned")
        )

    # Every Lead's roster in two queries, not two per Lead.
    rosters = planning.program_lead_rosters([lead["id"] for lead in leads_data])

    for lead in leads_data:
        roster = rosters.get(str(lead["id"]), [])
        existing = {tab["id"]: tab for tab in lead["cceo_tabs"]}
        ordered = [existing.pop(member["id"], member_tab(member)) for member in roster]
        lead["cceo_tabs"] = ordered + list(existing.values())
        for tab in lead["cceo_tabs"]:
            tab["meetings"], tab["trainings"] = [], []
    lead_tabs = {
        id(lead): {str(tab["id"]): tab for tab in lead["cceo_tabs"]}
        for lead in leads_data
    }
    for item, worker, lead in placements:
        target = lead_entry(lead) or unassigned_pl
        tabs = lead_tabs.get(id(target))
        if tabs is None:
            continue
        key = worker_key(worker)
        tab = tabs.get(key)
        if tab is None:
            tab = member_tab({"id": key, "name": worker_name(item, worker)})
            target["cceo_tabs"].append(tab)
            tabs[key] = tab
        session_list(tab, item).append(item)

    if uses_member_tabs:
        tabs = {str(tab["id"]): tab for tab in cceo_tabs}
        for tab in cceo_tabs:
            tab["meetings"], tab["trainings"] = [], []
        for item, worker, _lead in placements:
            mine = item.operational_owner_id in user_staff_ids or (
                worker is not None
                and bool({str(worker.id), str(worker.user_id)} & user_staff_ids)
            )
            key = "my-clusters" if mine else worker_key(worker)
            if key not in tabs:
                tab = member_tab({"id": key, "name": worker_name(item, worker)})
                cceo_tabs.append(tab)
                tabs[key] = tab
            session_list(tabs[key], item).append(item)

    from apps.planning.school_planning_badges import PLANNED_STATUSES

    def plan_counts(items):
        live = {
            item.activity_id: item
            for item in items
            if item.activity_status in PLANNED_STATUSES
        }
        return {
            "meetings_planned": sum(
                item.activity_type in CLUSTER_MEETING_TYPES for item in live.values()
            ),
            "trainings_planned": sum(
                item.activity_type in TRAINING_TYPES for item in live.values()
            ),
        }

    for member in cceo_tabs + [tab for lead in leads_data for tab in lead["cceo_tabs"]]:
        member.update(
            plan_counts(member.get("meetings", []) + member.get("trainings", []))
        )
    for lead in leads_data:
        lead["meetings_planned"] = sum(
            tab["meetings_planned"] for tab in lead["cceo_tabs"]
        )
        lead["trainings_planned"] = sum(
            tab["trainings_planned"] for tab in lead["cceo_tabs"]
        )

    # 7. Cluster performance executive overview
    from apps.planning.cluster_performance_service import (
        NO_LEAD_KEY,
        NO_OWNER_KEY,
        cluster_performance,
    )

    officer_activity: list[dict] = []
    lead_activity: list[dict] = []
    try:
        perf = cluster_performance(principal, fy=page_fy)
        raw_totals = perf.get("totals", {})
        perf_totals = {
            "active_clusters": max(0, len(clusters) - raw_totals.get("dormant", 0)),
            "dormant_clusters": raw_totals.get("dormant", 0),
            "sessions_held": raw_totals.get("sessions_done", 0),
            "sessions_delivered": raw_totals.get("sessions_done", 0),
            "unique_schools_reached": raw_totals.get("reached", 0),
            "total_spend": raw_totals.get("budget", 0),
            "budget_allocated": raw_totals.get("budget", 0),
        }
        # The same measured rows, folded per person for the chart that reads
        # each officer (or each Lead) as a series. The tab a person owns and
        # the bars they wear come from one list, so they cannot disagree.
        # Bounded to the clusters this page lists, so the bars and the tabs
        # count the same clusters.
        listed = set(cluster_ids)
        measured = [
            entry["row"]
            for entry in perf.get("rows", [])
            if entry["row"].cluster_id in listed
        ]
        if uses_member_tabs:
            own_label = f"{getattr(principal, 'name', '') or 'My clusters'} (you)"
            officer_activity = [
                cluster_activity_by_person(
                    own_label if tab["id"] == "my-clusters" else tab["name"],
                    measured,
                    lambda row, tab=tab: (
                        str(row.owner_id) in user_staff_ids
                        if tab["id"] == "my-clusters"
                        else row.owner_id == NO_OWNER_KEY
                        if tab["id"] == "__unassigned__"
                        else str(row.owner_id) == str(tab["id"])
                    ),
                )
                for tab in cceo_tabs
            ]
        else:
            lead_activity = [
                cluster_activity_by_person(
                    lead["name"],
                    measured,
                    lambda row, lead=lead: (
                        row.lead_id == NO_LEAD_KEY
                        if lead["id"] == "__unassigned__"
                        else str(row.lead_id) == str(lead["id"])
                    ),
                )
                for lead in leads_data
            ]
    except Exception:
        perf_totals = {
            "active_clusters": len(clusters),
            "dormant_clusters": 0,
            "sessions_held": 0,
            "sessions_delivered": 0,
            "unique_schools_reached": len(schools),
            "total_spend": 0,
            "budget_allocated": 0,
        }

    return {
        "is_programme_lead": is_programme_lead,
        "uses_member_tabs": uses_member_tabs,
        **plan_counts(cluster_work),
        "plan_fys": plan_fys,
        "plan_period_label": horizon_label(plan_fys),
        "selected_program_lead": selected_program_lead
        or (leads_data[0]["id"] if leads_data else ""),
        "leads": leads_data,
        "cceo_tabs": cceo_tabs,
        "officer_activity": officer_activity,
        "lead_activity": lead_activity,
        "total_clusters": len(clusters),
        "total_schools": len(schools),
        "perf_totals": perf_totals,
    }


# ── Running the old code ─────────────────────────────────────────────────────
@contextmanager
def frozen_code():
    """Every frozen reference patched back in over the live one."""
    with ExitStack() as stack:
        for module, name, frozen in (
            (svc, "_activity_records", _activity_records),
            (svc, "_cost_by_activity", _cost_by_activity),
            (svc, "_StaffDirectory", _StaffDirectory),
            (svc, "summarize", summarize),
            (svc, "system_program_leads", system_program_leads),
            (risk_service, "risks_for", risks_for),
            (views, "_filter_options", _filter_options),
            (views, "_team_owner_tabs", _team_owner_tabs),
            (perf, "_visits_by_cluster", _visits_by_cluster),
            (perf, "_budget_by_cluster", _budget_by_cluster),
            (perf, "_ssa_by_cluster", _ssa_by_cluster),
            (
                clusters_svc,
                "cluster_oversight_table_data",
                cluster_oversight_table_data,
            ),
        ):
            stack.enter_context(patch.object(module, name, frozen))
        yield


def plain(value, _seen=()):
    """A comparable copy: objects as their attributes, sets sorted."""
    if id(value) in _seen:
        raise ValueError("cycle in a view context")
    seen = (*_seen, id(value))
    if isinstance(value, dict):
        return {str(k): plain(v, seen) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v, seen) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((plain(v, seen) for v in value), key=repr)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Model):
        return [value._meta.label, value.pk]
    if isinstance(value, QuerySet):
        return [plain(v, seen) for v in value]
    if value is None or isinstance(value, (str, int, float)):
        return value
    if hasattr(value, "_asdict"):
        return plain(value._asdict(), seen)
    if hasattr(value, "__dict__"):
        return {"__class__": type(value).__name__, **plain(vars(value), seen)}
    return repr(value)


def record_view(record) -> dict:
    """Every attribute `_activity_item` may read off an activity record."""
    school, cluster, course = record.school, record.cluster, record.training_course
    district = getattr(cluster, "district", None)
    return {
        **{column: getattr(record, column) for column in _ACTIVITY_COLUMNS},
        "school": school
        and {
            "school_id": school.school_id,
            "name": school.name,
            "school_type": school.school_type,
            "district_id": school.district_id,
            "district": school.district and school.district.name,
            "region_id": school.region_id,
            "region": school.region and school.region.name,
        },
        "cluster": cluster
        and {
            "name": cluster.name,
            "district_id": cluster.district_id,
            "district": district
            and {
                "name": district.name,
                "region_id": district.region_id,
                "region": district.region and district.region.name,
            },
        },
        "training_course": course
        and {"display_name": course.display_name, "source_name": course.source_name},
    }


_VOLATILE = re.compile(
    rb'(csrfmiddlewaretoken" value="|nonce="|name="csrf-token" content="|'
    rb'X-CSRFToken": ")[^"]*'
)


def stable_html(body: bytes) -> bytes:
    """The page without the values that change on every request."""
    return _VOLATILE.sub(rb"\1", body)


# ── Fixture ──────────────────────────────────────────────────────────────────
FY = get_operational_fy()
NEXT_FY = str(int(FY) + 1)
PREV_FY = str(int(FY) - 1)
TODAY = date.today()


def _person(key, name, role):
    user = User.objects.create(
        email=f"{key}@oracle.test",
        name=name,
        roles=[role.value],
        active_role=role.value,
        is_active=True,
    )
    return StaffProfile.objects.create(user=user, title=name)


class OracleFixture(TestCase):
    """Three lenses over one lifecycle-wide plan."""

    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        role = EdifyRole
        central = Region.objects.create(name="Central", country="Uganda")
        northern = Region.objects.create(name="Northern", country="Uganda")
        coast = Region.objects.create(name="Coast", country="Kenya")
        cls.central = central
        kampala = District.objects.create(name="Kampala", region=central)
        wakiso = District.objects.create(name="Wakiso", region=central)
        gulu = District.objects.create(name="Gulu", region=northern)
        # Another "Kampala": options sort by name, so a tie keeps set order.
        twin = District.objects.create(name="Kampala", region=northern)
        mombasa = District.objects.create(name="Mombasa", region=coast)
        cls.kampala = kampala

        cls.cd = _person("cd", "Country Director", role.COUNTRY_DIRECTOR)
        cls.rvp = _person("rvp", "Regional VP", role.REGIONAL_VICE_PRESIDENT)
        cls.ia = _person("ia", "Impact Reviewer", role.IMPACT_ASSESSMENT)
        cls.accountant = _person(
            "acct", "Programme Accountant", role.PROGRAM_ACCOUNTANT
        )
        cls.rpl = _person("rpl", "Regional Lead", role.REGIONAL_PROGRAM_LEAD)
        StaffGeographyAssignment.objects.create(staff=cls.rpl, region_id=central.id)
        cls.rpl_open = _person(
            "rpl-open", "Open Regional Lead", role.REGIONAL_PROGRAM_LEAD
        )
        cls.pl_a = _person("pl-a", "Amina Lead", role.COUNTRY_PROGRAM_LEAD)
        cls.pl_b = _person("pl-b", "Daniel Lead", role.COUNTRY_PROGRAM_LEAD)
        cls.pl_idle = _person("pl-idle", "Zed Idle Lead", role.COUNTRY_PROGRAM_LEAD)
        cls.a1 = _person("a1", "Brian Officer", role.CCEO)
        cls.a2 = _person("a2", "Carol Officer", role.CCEO)
        cls.b1 = _person("b1", "Esther Officer", role.CCEO)
        cls.b2 = _person("b2", "Frank Officer", role.CCEO)
        cls.orphan = _person("orphan", "Gina Officer", role.CCEO)
        for lead, team in ((cls.pl_a, (cls.a1, cls.a2)), (cls.pl_b, (cls.b1, cls.b2))):
            for officer in team:
                StaffSupervisorAssignment.objects.create(
                    supervisor=lead, supervisee=officer
                )
        # A reviewer's link is not the reporting line.
        StaffSupervisorAssignment.objects.create(supervisor=cls.ia, supervisee=cls.b2)

        def cluster(name, region, district, owner=None, **extra):
            return Cluster.objects.create(
                name=name,
                region=region,
                district=district,
                responsible_staff_id=owner,
                cluster_leader_name=f"{name} Leader",
                cluster_leader_phone="+256700000001",
                **extra,
            )

        c_a = cluster("Alpha Cluster", central, kampala, cls.a1.id)
        # Held in the User id space, as the edit drawer writes it.
        c_b = cluster("Bravo Cluster", northern, gulu, cls.b1.user_id)
        c_lead = cluster("Lead Cluster", central, wakiso, cls.pl_a.id)
        c_orphan = cluster("Orphan Cluster", northern, twin)
        c_gone = cluster("Closed Cluster", central, kampala, cls.a2.id, deleted_at=now)

        def school(code, name, cluster=None, **extra):
            # A school holds its cluster as a plain id column, not a key.
            return School.objects.create(
                school_id=code,
                name=name,
                cluster_id=cluster.id if cluster else None,
                **extra,
            )

        s_a1 = school(
            "OR-A1",
            "Alpha Primary",
            region=central,
            district=kampala,
            school_type=SchoolType.CLIENT,
            account_owner_id=cls.a1.id,
            cluster=c_a,
            cluster_status="clustered",
        )
        s_a2 = school(
            "OR-A2",
            "Bravo Core",
            region=central,
            district=wakiso,
            school_type=SchoolType.CORE,
            account_owner_id=cls.a2.user_id,
            cluster=c_a,
            cluster_status="clustered",
        )
        s_b1 = school(
            "OR-B1",
            "Charlie Primary",
            region=northern,
            district=gulu,
            school_type=SchoolType.CLIENT,
            account_owner_id=cls.b1.id,
            cluster=c_b,
            cluster_status="clustered",
        )
        s_b2 = school(
            "OR-B2",
            "Delta Primary",
            region=northern,
            district=twin,
            school_type=SchoolType.CLIENT,
            account_owner_id=cls.b2.id,
            cluster=c_b,
        )
        # No district or region: geography falls back to the cluster's.
        s_nogeo = school(
            "OR-NG", "Echo No Geography", account_owner_id=cls.orphan.id, cluster=c_lead
        )
        s_gone = school(
            "OR-DEL",
            "Foxtrot Closed",
            region=central,
            district=kampala,
            account_owner_id=cls.a1.id,
            deleted_at=now,
        )
        s_kenya = school("OR-K1", "Kenya Academy", region=coast, district=mombasa)
        s_unowned = school("OR-U1", "Golf Unowned", region=central, district=wakiso)

        catalogue = {
            "activity_type": "training",
            "delivery_method": "group",
            "workflow_kind": "training",
            "salesforce_record_type": "Training",
            "evidence_profile": "training",
            "costing_profile": "training",
        }
        course = ActivityCatalogueItem.objects.create(
            stable_code="ORACLE-LIT",
            source_name="LIT-101",
            display_name="Literacy Foundations",
            **catalogue,
        )
        course_unnamed = ActivityCatalogueItem.objects.create(
            stable_code="ORACLE-NUM",
            source_name="Numeracy Source",
            display_name="",
            **catalogue,
        )
        cls.partner_x = Partner.objects.create(name="Partner X", active_status=True)
        # The same name, another partner: the filter options tie on it.
        cls.partner_x2 = Partner.objects.create(name="Partner X", active_status=True)
        partner_z = Partner.objects.create(name="Zulu Partners", active_status=True)

        owners = (
            {"responsible_staff_id": cls.a1.id},
            {"responsible_staff_id": cls.a2.user_id},
            {"responsible_staff_id": cls.pl_a.id},
            {"responsible_staff_id": cls.b1.id, "monitored_by_staff_id": cls.b1.id},
            {"responsible_staff_id": cls.b2.id},
            {"responsible_staff_id": cls.orphan.id},
            {
                "assigned_partner_id": cls.partner_x.id,
                "monitored_by_staff_id": cls.a1.id,
            },
            {
                "assigned_partner_id": cls.partner_x2.id,
                "responsible_staff_id": cls.b1.id,
            },
            {"assigned_partner_id": partner_z.id},
            {"responsible_staff_id": cls.pl_b.user_id},
            {"responsible_staff_id": cls.a2.id, "monitored_by_staff_id": cls.pl_a.id},
        )
        contexts = (
            {"activity_type": "school_visit", "school": s_a1},
            {"activity_type": "core_visit", "school": s_a2},
            {"activity_type": "cluster_meeting", "cluster": c_a},
            {
                "activity_type": "cluster_training",
                "cluster": c_b,
                "training_course": course,
            },
            {"activity_type": "cluster_training", "school": s_b1, "cluster": c_b},
            {"activity_type": "programme_event", "venue": "Town Hall"},
            {
                "activity_type": "in_school_training",
                "school": s_nogeo,
                "cluster": c_lead,
                "delivery_type": "in-school",
            },
            {"activity_type": "follow_up_visit", "school": s_gone},
            {"activity_type": "cluster_meeting_ssa_review", "cluster": c_gone},
            {
                "activity_type": "training",
                "school": s_b2,
                "training_course": course_unnamed,
            },
            {"activity_type": "school_visit", "school": s_kenya},
            {"activity_type": "ssa_activity", "school": s_unowned},
            {"activity_type": "coaching_visit", "school": s_b2, "cluster": c_orphan},
        )
        days = (-40, -10, -2, 0, 6, 45, None)

        def activity(status, fy=FY, planned=None, costs=(), **fields):
            made = Activity.objects.create(
                status=status,
                fy=fy,
                planned_date=planned,
                planned_month=planned.month if planned else None,
                quarter=get_quarter_for_date(planned) if planned else "Q1",
                **fields,
            )
            for line, amount in enumerate(costs):
                ActivityScheduleCostLine.objects.create(
                    activity=made,
                    cost_setting_key=f"oracle-{line}",
                    label="Oracle line",
                    unit_cost=amount,
                    quantity=1,
                    amount=amount,
                )
            return made

        # Every live status three times, each time with a different owner,
        # context, date, cost and workflow state.
        statuses = [s for s in svc.LIVE_ACTIVITY_STATUSES for _ in range(3)]
        for n, status in enumerate(statuses):
            offset = days[n % len(days)]
            activity(
                status,
                planned=TODAY + timedelta(days=offset) if offset is not None else None,
                costs=((), (15000,), (20000, 5000), (0,))[n % 4],
                **contexts[n % len(contexts)],
                **owners[n % len(owners)],
                evidence_status=("none", "", "uploaded", "accepted")[n % 4],
                ia_verification_status=(
                    "pending",
                    "",
                    "confirmed",
                    "returned",
                    "flagged",
                )[n % 5],
                payment_status=("none", "", "paid", "pending", "disbursed", "closed")[
                    n % 6
                ],
                submitted_to_ia_at=(
                    None,
                    now - timedelta(days=20),
                    now - timedelta(days=2),
                )[n % 3],
                salesforce_activity_id=f"SF-{n}" if n % 2 else None,
                reschedule_count=(0, 1, 3, 5)[n % 4],
                cost_missing=n % 5 == 0,
                purpose_type=(None, "in_school_training", "ssa_support", "mystery")[
                    n % 4
                ],
                activity_purpose_text=(None, "", "Coach the head teacher")[n % 3],
                support_rationale=("", "Low SSA scores")[n % 2],
                purpose_intervention=(None, "leadership")[n % 2],
                focus_intervention=(None, "financial_health", "leadership")[n % 3],
                participants_per_school=(None, 3, None)[n % 3],
                expected_participants=(None, None, 25)[n % 3],
                activity_name_snapshot=(None, "Snapshot Name")[n % 2],
            )

        # Outside every lens: dead statuses, a soft delete, last year.
        for status in ("cancelled", "deferred", "rejected", "not_planned"):
            activity(
                status,
                planned=TODAY,
                costs=(9000,),
                activity_type="school_visit",
                school=s_a1,
                responsible_staff_id=cls.a1.id,
            )
        deleted = activity(
            "scheduled",
            planned=TODAY,
            activity_type="school_visit",
            school=s_a1,
            responsible_staff_id=cls.a1.id,
        )
        Activity.objects.filter(id=deleted.id).update(deleted_at=now)
        activity(
            "scheduled",
            fy=PREV_FY,
            planned=TODAY - timedelta(days=400),
            activity_type="school_visit",
            school=s_a1,
            responsible_staff_id=cls.a1.id,
        )

        # An in-school training paired with the visit that delivers it.
        visit = activity(
            "scheduled",
            planned=TODAY + timedelta(days=3),
            costs=(7000,),
            activity_type="school_visit",
            school=s_a1,
            responsible_staff_id=cls.a1.id,
        )
        activity(
            "scheduled",
            planned=TODAY + timedelta(days=3),
            costs=(8000,),
            activity_type="in_school_training",
            school=s_a1,
            responsible_staff_id=cls.a1.id,
            paired_school_visit=visit,
        )

        # Cluster sessions, with and without invitations, this year and next.
        meeting = activity(
            "planned",
            planned=TODAY + timedelta(days=9),
            costs=(30000,),
            activity_type="cluster_meeting",
            cluster=c_a,
            responsible_staff_id=cls.a1.id,
        )
        training = activity(
            "completed",
            planned=TODAY - timedelta(days=5),
            costs=(40000,),
            activity_type="cluster_training",
            cluster=c_b,
            responsible_staff_id=cls.b1.id,
            participants_per_school=4,
        )
        for session, member, counts in (
            (meeting, s_a1, (2, 1, 0)),
            (meeting, s_a2, (None, None, None)),
            (training, s_b2, (3, 1, 1)),
        ):
            ClusterActivityAttendance.objects.create(
                activity=session,
                school=member,
                invited=True,
                teachers=counts[0],
                leaders=counts[1],
                other=counts[2],
                recorded_by="oracle",
            )
        activity(
            "ia_verified",
            planned=TODAY - timedelta(days=30),
            costs=(12000,),
            activity_type="cluster_meeting",
            cluster=c_b,
            responsible_staff_id=cls.b1.user_id,
            actual_delivery_date=TODAY - timedelta(days=29),
        )
        for kind, place, owner in (
            ("cluster_meeting", {"cluster": c_a}, cls.a1.id),
            ("cluster_training", {"cluster": c_b}, cls.b1.id),
            ("school_visit", {"school": s_b1}, cls.b1.id),
        ):
            activity(
                "planned",
                fy=NEXT_FY,
                planned=TODAY + timedelta(days=60),
                costs=(11000,),
                activity_type=kind,
                responsible_staff_id=owner,
                **place,
            )

        # Handovers the partner has not scheduled, one it returned, one it
        # scheduled (the activity is the item then), and one from last year.
        def handover(created_days_ago, **fields):
            made = PartnerAssignment.objects.create(**fields)
            PartnerAssignment.objects.filter(id=made.id).update(
                created_at=now - timedelta(days=created_days_ago)
            )

        handover(
            20,
            partner=cls.partner_x,
            school=s_a1,
            assigning_staff_id=cls.a1.id,
            monitoring_staff_id=cls.a1.id,
            expected_activity_type="school_visit",
            purpose_of_visit="ssa_support",
            status=PartnerAssignment.STATUS_ASSIGNED,
        )
        handover(
            12,
            partner=partner_z,
            cluster=c_b,
            monitoring_staff_id=cls.b1.id,
            expected_activity_type="cluster_training",
            scheduled_date=TODAY - timedelta(days=5),
            purpose="Cluster refresher",
            status=PartnerAssignment.STATUS_PENDING_SCHEDULING,
        )
        handover(
            3,
            partner=cls.partner_x2,
            school=s_b2,
            assigning_staff_id=cls.b2.id,
            expected_activity_type="coaching_visit",
            notes="Returned by the partner",
            status=PartnerAssignment.STATUS_RETURNED_TO_STAFF,
        )
        handover(
            8,
            partner=partner_z,
            school=s_a2,
            assigning_staff_id=cls.a2.id,
            monitoring_staff_id=cls.a2.id,
            status=PartnerAssignment.STATUS_SCHEDULED,
        )
        handover(
            400,
            partner=cls.partner_x,
            school=s_unowned,
            assigning_staff_id=cls.a2.id,
            status=PartnerAssignment.STATUS_ASSIGNED,
        )

        # SSA for the member schools: this year, last year, and a deleted one.
        interventions = (
            "leadership",
            "financial_health",
            "christlike_behaviour",
            "legacy",
        )
        for n, (member, fy, score) in enumerate(
            (
                (s_a1, FY, 6.2),
                (s_a2, FY, 4.1),
                (s_b1, FY, 7.5),
                (s_b2, FY, 3.3),
                (s_a1, PREV_FY, 2.0),
                (s_b1, FY, 5.0),
            )
        ):
            record = SsaRecord.objects.create(
                school=member,
                date_of_ssa=now - timedelta(days=30 + n),
                fy=fy,
                quarter="Q1",
                uploaded_by="oracle",
                average_score=score,
                deleted_at=now if n == 5 else None,
            )
            for k, intervention in enumerate(interventions):
                SsaScore.objects.create(
                    ssa_record=record,
                    intervention=intervention,
                    score=score + k - n % 3,
                )

    # Who reads which lens.
    @classmethod
    def principals(cls):
        return (
            cls.cd,
            cls.rvp,
            cls.ia,
            cls.accountant,
            cls.rpl,
            cls.rpl_open,
            cls.pl_a,
            cls.pl_b,
            cls.pl_idle,
            cls.a1,
            cls.orphan,
        )


# ── The rewritten functions, one at a time ───────────────────────────────────
class FunctionOracleTest(OracleFixture):
    def _rows(self, principal, **period):
        scope = svc.resolve_oversight_scope(principal.user)
        captured = []
        live_records = svc._activity_records

        def keep(rows):
            captured.append(list(rows))
            return live_records(captured[-1])

        with patch.object(svc, "_activity_records", keep):
            svc._activities_in_scope(scope, fy=(FY, NEXT_FY), month=None, quarter=None)
        return captured[0] if captured else []

    def test_activity_records_read_exactly_as_before(self):
        rows = self._rows(self.cd)
        self.assertGreater(len(rows), 60)
        self.assertEqual(
            [record_view(r) for r in svc._activity_records(rows)],
            [record_view(r) for r in _activity_records(rows)],
        )
        self.assertEqual(svc._activity_records([]), [])

    def test_cost_totals_equal_the_old_query(self):
        ids = list(Activity.all_objects.values_list("id", flat=True))
        cases = (
            ids,
            ids[:7],
            ids[::3],
            [*ids[:5], *ids[:5]],
            [*ids[:3], "no-such"],
            [],
        )
        for case in cases:
            with self.subTest(size=len(case)):
                self.assertEqual(svc._cost_by_activity(case), _cost_by_activity(case))
        self.assertGreater(sum(_cost_by_activity(ids).values()), 0)

    def test_the_staff_directory_answers_as_before(self):
        rows = self._rows(self.cd)
        records = svc._activity_records(rows)
        scope = svc.resolve_oversight_scope(self.cd.user)
        assignments = svc._unscheduled_assignments_in_scope(scope, fy=(FY,))
        live = svc._StaffDirectory(records, assignments)
        frozen = _StaffDirectory(records, assignments)
        people = [p for p in StaffProfile.objects.all()]
        probes = [
            None,
            "",
            "no-such",
            *(p.id for p in people),
            *(p.user_id for p in people),
        ]
        for staff_id in probes * 2:  # the second round answers from the memo
            self.assertEqual(
                live.supervisor_of(staff_id), frozen.supervisor_of(staff_id)
            )
            self.assertEqual(live.name(staff_id), frozen.name(staff_id))
            self.assertEqual(live.role(staff_id), frozen.role(staff_id))
        empty = svc._StaffDirectory([], [])
        self.assertEqual(
            empty.supervisor_of(self.a1.id),
            _StaffDirectory([], []).supervisor_of(self.a1.id),
        )

    def test_risks_come_out_in_the_same_order(self):
        items = svc.build_items(self.cd.user, fy=FY, fys=(FY, NEXT_FY))
        several = tied = 0
        for day in (TODAY, TODAY + timedelta(days=30), TODAY - timedelta(days=60)):
            for item in items:
                old = risks_for(item, day)
                self.assertEqual(
                    [r.as_dict() for r in risk_service.risks_for(item, day)],
                    [r.as_dict() for r in old],
                )
                several += len(old) > 1
                tied += len({r.severity for r in old}) < len(old)
        self.assertGreater(several, 0)
        self.assertGreater(tied, 0)

    def test_summaries_fold_to_the_same_numbers(self):
        for principal in (self.cd, self.pl_a, self.rpl):
            items = svc.build_items(principal.user, fy=FY, fys=(FY, NEXT_FY))
            subsets = [
                items,
                [],
                *(g["items"] for g in svc.group_by_owner(items)),
                *(
                    [i for i in items if i.activity_status == s]
                    for s in svc.LIVE_ACTIVITY_STATUSES
                ),
                [i for i in items if i.is_partner_work],
                [i for i in items if i.is_awaiting_partner_schedule],
            ]
            for subset in subsets:
                self.assertEqual(svc.summarize(subset), summarize(subset))
                self.assertEqual(svc.summarize(iter(subset)), summarize(iter(subset)))
        whole = summarize(svc.build_items(self.cd.user, fy=FY))
        for key in (
            "partner_awaiting_schedule",
            "partner_scheduled",
            "at_risk",
            "planned_budget",
            "completed",
            "due_count",
            "cost_missing",
            "awaiting_verification",
            "awaiting_payment",
        ):
            self.assertGreater(whole[key], 0, key)
        self.assertIsNotNone(whole["execution_progress"])

    def test_filter_options_list_the_same_values_in_the_same_order(self):
        for principal in (self.cd, self.pl_b, self.rpl):
            items = svc.build_items(principal.user, fy=FY, fys=(FY, NEXT_FY))
            self.assertEqual(views._filter_options(items), _filter_options(items))
        options = _filter_options(svc.build_items(self.cd.user, fy=FY))
        self.assertEqual(
            [name for _, name in options["partners"]].count("Partner X"), 2
        )
        self.assertEqual([name for _, name in options["districts"]].count("Kampala"), 2)

    def test_owner_tabs_hold_the_same_rows(self):
        def shape(result):
            tabs, key, visible = result
            return (
                [
                    (
                        t["key"],
                        t["label"],
                        t["count"],
                        t["is_active"],
                        [id(i) for i in t["items"]],
                    )
                    for t in tabs
                ],
                key,
                [id(i) for i in visible],
            )

        for principal in (self.pl_a, self.pl_b, self.pl_idle, self.a1):
            scope = svc.resolve_oversight_scope(principal.user)
            items = svc.build_items(principal.user, fy=FY)
            for selected in (
                WHOLE_TEAM_TAB,
                "mine",
                self.a1.id,
                self.a2.user_id,
                self.b1.id,
                "nobody",
                "",
            ):
                with self.subTest(principal=principal.user.name, selected=selected):
                    self.assertEqual(
                        shape(views._team_owner_tabs(scope, items, selected)),
                        shape(_team_owner_tabs(scope, items, selected)),
                    )

    def test_programme_leads_carry_the_same_ids(self):
        self.assertEqual(svc.system_program_leads(), system_program_leads())
        # Id spaces that collide: a User whose id is a Lead's StaffProfile id,
        # and a deleted profile the managers must keep out.
        twin = User.objects.create(
            id=self.pl_b.id, email="twin@oracle.test", name="Twin", is_active=True
        )
        StaffProfile.objects.create(user=twin, title="Twin")
        ghost = User.objects.create(
            id=self.pl_a.id, email="ghost@oracle.test", name="Ghost", is_active=True
        )
        StaffProfile.objects.create(
            user=ghost, title="Ghost", deleted_at=timezone.now()
        )
        leads = system_program_leads()
        self.assertEqual(svc.system_program_leads(), leads)
        self.assertEqual(
            len(next(p for p in leads if p["id"] == self.pl_b.id)["ids"]), 3
        )
        self.assertEqual(svc._each_in_both_id_spaces([]), {})

    def test_cluster_measures_equal_the_old_queries(self):
        busy = 0
        for principal in (self.cd, self.pl_a, self.rpl):
            scope = resolve_user_scope(principal.user)
            clusters = list(
                or_empty(cluster_queryset(scope), Cluster).values_list("id", flat=True)
            )
            members = perf._schools_by_cluster(clusters)
            for fy in (FY, NEXT_FY, PREV_FY):
                with self.subTest(principal=principal.user.name, fy=fy):
                    visits = _visits_by_cluster(members, fy=fy)
                    budgets = _budget_by_cluster(clusters, members, fy=fy)
                    ssa = _ssa_by_cluster(members, fy=fy)
                    self.assertEqual(perf._visits_by_cluster(members, fy=fy), visits)
                    self.assertEqual(
                        perf._budget_by_cluster(clusters, members, fy=fy), budgets
                    )
                    self.assertEqual(perf._ssa_by_cluster(members, fy=fy), ssa)
                    busy += bool(visits) + bool(budgets) + bool(ssa)
        self.assertGreater(busy, 6)
        self.assertEqual(
            perf._visits_by_cluster({}, fy=FY), _visits_by_cluster({}, fy=FY)
        )
        self.assertEqual(
            perf._budget_by_cluster([], {}, fy=FY), _budget_by_cluster([], {}, fy=FY)
        )
        self.assertEqual(perf._ssa_by_cluster({}, fy=FY), _ssa_by_cluster({}, fy=FY))

    def test_cluster_oversight_data_is_unchanged(self):
        scored = 0
        for principal in self.principals():
            for fy in (None, FY, NEXT_FY):
                with self.subTest(principal=principal.user.name, fy=fy):
                    live = plain(
                        clusters_svc.cluster_oversight_table_data(principal.user, fy=fy)
                    )
                    with frozen_code():
                        frozen = plain(
                            cluster_oversight_table_data(principal.user, fy=fy)
                        )
                    self.assertEqual(live, frozen)
                    scored += str(frozen).count("Leadership (")
        self.assertGreater(scored, 0)

    def test_items_are_built_exactly_as_before(self):
        week = TODAY - timedelta(days=TODAY.weekday())
        cases = (
            {"fy": FY},
            {"fy": FY, "month": TODAY.month},
            *({"fy": FY, "quarter": q} for q in ("Q1", "Q2", "Q3", "Q4")),
            {"fy": FY, "date_start": week, "date_end": week + timedelta(days=7)},
            {"fy": FY, "fys": (FY, NEXT_FY)},
            {
                "fy": FY,
                "fys": (FY, NEXT_FY),
                "activity_types": tuple(CLUSTER_MEETING_TYPES + TRAINING_TYPES),
                "cluster_work_only": True,
            },
            {"fy": FY, "staff_id": self.a1.id},
            {"fy": FY, "staff_id": self.a2.user_id},
            {"fy": FY, "program_lead_id": self.pl_a.id},
            {"fy": FY, "program_lead_id": self.pl_b.user_id},
            {"fy": FY, "filters": {"executor_type": "partner"}},
            {"fy": FY, "filters": {"context": "cluster"}},
            {"fy": FY, "filters": {"context": "non_school"}},
            {"fy": FY, "filters": {"district_id": self.kampala.id}},
            {"fy": FY, "filters": {"status": PartnerAssignment.STATUS_ASSIGNED}},
            {"fy": FY, "filters": {"partner_id": self.partner_x.id}},
            {"fy": FY, "filters": {"risk": "any"}},
            {"fy": PREV_FY},
        )
        built = 0
        for principal in self.principals():
            for kwargs in cases:
                with self.subTest(
                    principal=principal.user.name, **{"case": str(kwargs)}
                ):
                    live = [vars(i) for i in svc.build_items(principal.user, **kwargs)]
                    with frozen_code():
                        frozen = [
                            vars(i) for i in svc.build_items(principal.user, **kwargs)
                        ]
                    self.assertEqual(live, frozen)
                    built += len(frozen)
        self.assertGreater(built, 500)


# ── The pages, whole ─────────────────────────────────────────────────────────
class PageOracleTest(OracleFixture):
    def _visit(self, url, *, frozen, htmx=False):
        contexts = []
        real_render = views.render

        def spy(request, template_name, context=None, *args, **kwargs):
            contexts.append((template_name, plain(context)))
            return real_render(request, template_name, context, *args, **kwargs)

        with ExitStack() as stack:
            stack.enter_context(patch.object(views, "render", spy))
            if frozen:
                stack.enter_context(frozen_code())
            headers = {"HTTP_HX_REQUEST": "true"} if htmx else {}
            response = self.client.get(url, **headers)
        body = (
            b"".join(response.streaming_content)
            if response.streaming
            else response.content
        )
        return (
            response.status_code,
            response.get("Location"),
            contexts,
            stable_html(body),
        )

    def _assert_same(self, principals, urls):
        rendered = 0
        for principal in principals:
            self.client.force_login(principal.user)
            for url, htmx in urls:
                with self.subTest(principal=principal.user.name, url=url, htmx=htmx):
                    live = self._visit(url, frozen=False, htmx=htmx)
                    old = self._visit(url, frozen=True, htmx=htmx)
                    self.assertEqual(live[:2], old[:2])
                    self.assertEqual(live[2], old[2])
                    self.assertEqual(live[3], old[3])
                    rendered += live[0] == 200
        return rendered

    def test_country_planning_oversight(self):
        urls = [
            ("/country-planning-oversight/", False),
            ("/country-planning-oversight/", True),
            (f"/country-planning-oversight/?period=month&month={TODAY.month}", False),
            (
                f"/country-planning-oversight/?program_lead={self.pl_b.id}"
                f"&lead={self.pl_b.id}",
                False,
            ),
            ("/country-planning-oversight/?risk=any&activity_type=school_visit", False),
            (
                "/country-planning-oversight/?executor_type=partner&context=school",
                False,
            ),
            (f"/country-planning-oversight/team/{self.pl_a.id}", False),
            (f"/country-planning-oversight/team/{self.pl_b.user_id}", False),
        ]
        principals = (self.cd, self.rvp, self.ia, self.accountant, self.pl_a)
        self.assertGreater(self._assert_same(principals, urls), 10)

    def test_team_planning_oversight(self):
        urls = [
            ("/team-planning-oversight/", False),
            ("/team-planning-oversight/", True),
            (f"/team-planning-oversight/?owner={self.a1.id}&activity=visits", False),
            (f"/team-planning-oversight/?owner={self.a2.user_id}", False),
            (
                "/team-planning-oversight/?owner=mine&activity=trainings&period=week",
                False,
            ),
            (
                "/team-planning-oversight/?period=quarter&quarter="
                f"{get_quarter_for_date(TODAY)}&status=scheduled",
                False,
            ),
            (
                f"/team-planning-oversight/?activity=meetings&district_id={self.kampala.id}",
                False,
            ),
            (f"/team-planning-oversight/?program_lead={self.pl_a.id}", False),
        ]
        principals = (
            self.pl_a,
            self.pl_b,
            self.pl_idle,
            self.cd,
            self.rpl,
            self.rpl_open,
            self.ia,
            self.accountant,
        )
        self.assertGreater(self._assert_same(principals, urls), 30)

    def test_cluster_oversight(self):
        urls = [
            ("/cluster-oversight/", False),
            ("/cluster-oversight/", True),
            (f"/cluster-oversight/?fy={NEXT_FY}", False),
        ]
        principals = (
            self.cd,
            self.ia,
            self.accountant,
            self.rpl,
            self.rpl_open,
            self.pl_a,
            self.pl_b,
            self.a1,
        )
        self.assertGreater(self._assert_same(principals, urls), 10)

    def test_exports(self):
        urls = [
            ("/team-planning-oversight/export", False),
            (
                f"/team-planning-oversight/export?owner={self.b1.id}&context=cluster",
                False,
            ),
            ("/country-planning-oversight/export", False),
            (
                f"/country-planning-oversight/export?program_lead={self.pl_a.id}"
                f"&partner_id={self.partner_x.id}",
                False,
            ),
        ]
        principals = (self.pl_a, self.pl_b, self.cd, self.rpl, self.accountant)
        self.assertGreater(self._assert_same(principals, urls), 6)

    def test_team_detail_rows_render_as_before(self):
        """The rows read the `can_open` answer bound once at the top of the
        partial instead of asking again per row; the old rows, restored from
        the live file, must draw the same page."""
        path = settings.BASE_DIR / "templates/partials/oversight/cd_team_detail.html"
        # The rows live in the officer panel body since P-5 (2026-09-25); it is
        # inlined where the detail includes it, so both variants below differ
        # only in the row condition.
        body_path = (
            settings.BASE_DIR / "templates/partials/oversight/_officer_panel_body.html"
        )
        body_source = body_path.read_text()
        include = '{% include "partials/oversight/_officer_panel_body.html" %}'
        detail_source = path.read_text()
        self.assertEqual(detail_source.count(include), 2)
        live_source = detail_source.replace(include, body_source)
        new_row = (
            "{% if item.activity_id and can_open_activity_record and "
            'request.user.active_role != "Accountant" %}'
        )
        old_row = (
            '{% if item.activity_id and request.user|can_open:"/activities/0" and '
            'request.user.active_role != "Accountant" %}'
        )
        self.assertEqual(body_source.count(new_row), 2)
        engine = engines["django"]
        live_template = engine.from_string(live_source)
        old_template = engine.from_string(live_source.replace(new_row, old_row))
        drawn = 0
        for principal, url in (
            (self.pl_a, "/team-planning-oversight/"),
            (self.pl_b, f"/team-planning-oversight/?owner={self.b1.id}"),
            (self.accountant, "/team-planning-oversight/"),
            (self.cd, f"/country-planning-oversight/team/{self.pl_a.id}"),
            (self.rvp, f"/country-planning-oversight/team/{self.pl_b.id}"),
        ):
            captured = []
            real_render = views.render

            def spy(request, template_name, context=None, *args, **kwargs):
                captured.append(context)
                return real_render(request, template_name, context, *args, **kwargs)

            self.client.force_login(principal.user)
            with patch.object(views, "render", spy):
                self.client.get(url)
            if not captured:
                continue
            context = dict(captured[-1])
            context.setdefault("owner_groups", context.get("groups"))
            if not context.get("owner_groups"):
                continue
            request = RequestFactory().get(url)
            request.user = principal.user
            with self.subTest(principal=principal.user.name, url=url):
                self.assertEqual(
                    live_template.render(context, request),
                    old_template.render(context, request),
                )
                drawn += 1
        self.assertGreater(drawn, 2)
