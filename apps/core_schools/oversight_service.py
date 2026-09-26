"""Core Schools oversight service.

Provides database-driven core schools oversight data:
- For PL: Scoped to core schools owned by supervised CCEOs, grouped into CCEO tabs.
- For IA, CD, RPL: Scoped to country/regional core schools, grouped into Supervising PL tabs -> CCEO tabs.
- Computes core package progress (visits & trainings completed / target), SSA scores, and package status.
"""

from __future__ import annotations

from apps.clusters.oversight_service import _label, _staff_directory, _supervisor_of
from apps.core.rbac import EdifyRole
from apps.core.fy import get_operational_fy
from apps.core.scoping import owner_ids, resolve_user_scope
from apps.core_schools.models import CorePlan
from apps.core_schools.lifecycle import CORE_LIFECYCLE_TYPES, programme_rows
from apps.schools.programme_schools import type_options
from apps.planning.oversight_service import system_program_leads
from apps.schools.models import School
from django.db.models import Avg, Q


#: The package counts a group of schools folds to, for the chart that reads
#: one officer (or one Lead) as a series. Completed and target are summed over
#: the group's schools, so the officer bars and the school rows agree.
_PACKAGE_TOTAL_KEYS = (
    "visits_completed",
    "visits_target",
    "trainings_completed",
    "trainings_target",
)
_EMPTY_PACKAGE_TOTALS = {key: 0 for key in _PACKAGE_TOTAL_KEYS}


#: The tab key for planned work whose person no staff profile resolves.
UNASSIGNED_WORKER = "__unassigned__"


def _officer_entry(oid: str, name: str) -> dict:
    """One officer's tab on the country lens, before anything is filed in it."""
    return {
        "id": oid,
        "name": name,
        "schools": [],
        "count": 0,
        "completed": 0,
        "core_work": [],
        **_EMPTY_PACKAGE_TOTALS,
    }


def _add_package_totals(group: dict, row: dict) -> None:
    for key in _PACKAGE_TOTAL_KEYS:
        group[key] += int(row.get(key) or 0)


def planned_core_work(principal, *, fy: str) -> list:
    """The core visits and trainings on each person's My Plan, as oversight items.

    Owner, 2026-09-24: Core School Oversight fetches from My Plan, where the
    Programme Lead and every CCEO keep their plans. The page used to show only
    each package's completion counters, so a lead could not see a single visit
    or training an officer had planned at a core school.

    The rows are the planning oversight items — the same canonical records,
    scope and status rules as Planning Oversight — sorted into core work the
    way My Plan sorts its core tables (``apps.my_plan.services``):

    * work at a core school that is a visit or a training, or that occupies a
      package slot, is a core row;
    * a cluster group training reaches each core school invited to it (or,
      with no invitations recorded, each confirmed member) and is listed once
      per such school, because My Plan moves that school's row to the core
      training table and the package slot carries the credit.

    It reads the planning horizon, like Cluster Oversight: September plans
    land in October, the next fiscal year. Partner handovers at core schools
    that the partner has not scheduled yet are listed too — they are on no
    one's My Plan yet, and a lead needs to see them waiting.
    """
    import copy
    from collections import defaultdict

    from apps.activities.models import ClusterActivityAttendance
    from apps.clusters.oversight_service import session_status
    from apps.core.activity_types import TRAINING_TYPES, VISIT_TYPES
    from apps.core_schools.models import CoreActivitySlot
    from apps.planning import oversight_service as planning
    from apps.planning.fy_policy import planning_horizon
    from apps.schools.lifecycle_models import OPERATING_STATUSES

    # Narrowed in SQL to core-school work and school-less cluster trainings:
    # the two lists below keep nothing else, and each item is built exactly
    # as in the full list.
    items = planning.build_items(
        principal, fy=fy, fys=planning_horizon(fy), core_work_only=True
    )
    package_types = set(VISIT_TYPES) | set(TRAINING_TYPES)
    activity_ids = [item.activity_id for item in items if item.activity_id]

    # (activity, school business id) -> (kind, number): one cluster session
    # fills a slot at each core school that sat in it.
    slots: dict[tuple, tuple[str, int]] = {}
    for activity_id, school_code, kind, number in CoreActivitySlot.objects.filter(
        activity_id__in=activity_ids
    ).values_list(
        "activity_id", "core_plan__school_id", "activity_type", "sequence_number"
    ):
        slots[(activity_id, school_code)] = (kind, number)

    def slot_of(item):
        """The package slot this row fills, by either school identifier."""
        return slots.get((item.activity_id, item.school_code)) or slots.get(
            (item.activity_id, item.school_id)
        )

    direct = [
        item
        for item in items
        if item.school_type == "core"
        and (item.activity_type in package_types or slot_of(item))
    ]
    sessions = [
        item
        for item in items
        if item.activity_id
        and item.cluster_id
        and not item.school_id
        and not item.is_in_school_training
        and item.activity_type in TRAINING_TYPES
    ]

    reached: list = []
    if sessions:
        session_ids = [item.activity_id for item in sessions]
        recorded = set(
            ClusterActivityAttendance.objects.filter(
                activity_id__in=session_ids
            ).values_list("activity_id", flat=True)
        )
        invited = defaultdict(set)
        for activity_id, school_id in (
            ClusterActivityAttendance.objects.filter(activity_id__in=session_ids)
            .filter(Q(invited=True) | Q(attended=True))
            .values_list("activity_id", "school_id")
        ):
            invited[activity_id].add(school_id)
        cluster_ids = {item.cluster_id for item in sessions}
        invited_ids = {sid for ids in invited.values() for sid in ids}
        core_schools = list(
            School.objects.filter(
                Q(cluster_id__in=cluster_ids) | Q(id__in=invited_ids),
                deleted_at__isnull=True,
                school_type="core",
            ).select_related("district", "region")
        )
        by_id = {school.id: school for school in core_schools}
        members = defaultdict(list)
        confirmed = defaultdict(list)
        for school in core_schools:
            members[school.cluster_id].append(school)
            if school.cluster_status == "clustered" and (
                not school.operational_status
                or school.operational_status in OPERATING_STATUSES
            ):
                confirmed[school.cluster_id].append(school)
        for item in sessions:
            if item.activity_id in recorded:
                targets = [by_id[s] for s in invited[item.activity_id] if s in by_id]
            else:
                targets = (
                    confirmed.get(item.cluster_id) or members.get(item.cluster_id) or []
                )
            for school in sorted(targets, key=lambda s: s.name or ""):
                row = copy.copy(item)
                row.risks = list(item.risks)
                row.school_id = school.id
                row.school_code = school.school_id or school.id
                row.school_name = school.name
                row.school_type = school.school_type
                row.district_id = school.district_id
                row.district_name = getattr(school.district, "name", "") or ""
                row.via_cluster = True
                reached.append(row)

    work = direct + reached
    for item in work:
        kind, number = slot_of(item) or ("", 0)
        if not kind:
            kind = "training" if item.activity_type in TRAINING_TYPES else "visit"
        item.package_label = (
            f"{'T' if kind == 'training' else 'V'}{number}" if number else ""
        )
        item.package_kind = kind
        item.via_cluster = getattr(item, "via_cluster", False)
        item.session_status, item.session_tone = session_status(item)
    # The Salesforce ID and Evidence columns, and open work first by planned
    # date with the officer's completed work at the bottom (owner,
    # 2026-09-26). The school name orders rows that share a date.
    from apps.activities.completion_columns import annotate, sort_completed_last

    annotate(work)
    from apps.clusters.oversight_service import hold_complete_to_both_columns

    hold_complete_to_both_columns(work)
    work.sort(key=lambda i: i.school_name or "")
    sort_completed_last(work)
    return work


def core_schools_oversight_data(principal, *, fy: str | None = None) -> dict:
    """Returns database-driven core schools oversight dataset."""
    fy = str(fy or get_operational_fy())
    scope = resolve_user_scope(principal)
    is_programme_lead = scope.active_role == EdifyRole.COUNTRY_PROGRAM_LEAD.value

    # 1. Query scoped core schools
    base = School.objects.filter(
        deleted_at__isnull=True, school_type__in=CORE_LIFECYCLE_TYPES
    ).select_related("district", "region")

    own_ids: set[str] = set()
    if is_programme_lead:
        # The lead's own core schools and their supervisees': a lead reads
        # themselves first, then the team, on this page as on every other.
        own_ids = set(owner_ids(principal))
        sup_ids = set(scope.supervised_staff_ids or [])
        people = own_ids | sup_ids
        if not people:
            core_qs = School.objects.none()
        else:
            from apps.clusters.models import Cluster

            cluster_ids = set(
                Cluster.objects.filter(responsible_staff_id__in=people).values_list(
                    "id", flat=True
                )
            )
            core_qs = base.filter(
                Q(account_owner_id__in=people) | Q(cluster_id__in=cluster_ids)
            )
    else:
        from apps.core.scoping import scoped_school_queryset

        core_qs = scoped_school_queryset(scope, base=base)
        if core_qs is None:
            core_qs = base.none()

    # By name, then id: schools sharing a name came back in whatever order the
    # plan produced, so two loads of the page could list an officer's schools
    # differently (2026-09-24 A+ audit).
    schools = list(core_qs.order_by("name", "id"))
    core_work = planned_core_work(principal, fy=fy)
    from apps.planning.fy_policy import horizon_label, planning_horizon

    plan_period_label = horizon_label(planning_horizon(fy))
    if not schools and not core_work:
        return {
            "is_programme_lead": is_programme_lead,
            "leads": [],
            "cceo_tabs": [],
            "package_chart_tabs": [],
            "total_schools": 0,
            "completed_packages": 0,
            "in_progress": 0,
            "avg_ssa": "—",
            "planned_core_work": 0,
            "plan_period_label": plan_period_label,
            "fy": fy,
        }

    school_ids = [s.id for s in schools]
    human_ids = [s.school_id for s in schools if s.school_id]
    all_school_keys = set(school_ids + human_ids)

    # 2. Staff directory for owners & supervisors
    owner_keys = {s.account_owner_id for s in schools if s.account_owner_id}
    # The people doing the planned work, in the same directory as the school
    # owners, so a person's schools and their plan land on one tab whichever
    # id space either was written in.
    directory = _staff_directory(
        owner_keys
        | {i.operational_owner_id for i in core_work if i.operational_owner_id}
    )

    # 2b. Cluster lookup
    cluster_ids = {s.cluster_id for s in schools if s.cluster_id}
    from apps.clusters.models import Cluster

    cluster_map = {c.id: c.name for c in Cluster.objects.filter(id__in=cluster_ids)}

    # 3. Core plans lookup for this FY
    plans = {
        p.school_id: p
        for p in CorePlan.objects.filter(
            Q(school_id__in=all_school_keys),
            fy=fy,
        )
    }

    # 4. SSA records lookup for baseline / verified score
    from apps.ssa.models import SsaRecord

    ssa_scores = {
        row["school_id"]: row["avg_score"]
        for row in SsaRecord.objects.filter(
            school_id__in=school_ids, deleted_at__isnull=True
        )
        .values("school_id")
        .annotate(avg_score=Avg("average_score"))
    }

    # 5. Format school rows
    formatted_schools = []
    completed_count = 0
    in_progress_count = 0

    for s in schools:
        owner = directory.get(s.account_owner_id)
        lead = _supervisor_of(owner)
        plan = (
            (plans.get(s.school_id) or plans.get(s.id))
            if s.school_type == "core"
            else None
        )

        v_done = plan.visits_completed if plan else 0
        v_target = (plan.visits_target if plan else 4) if s.school_type == "core" else 0
        t_done = plan.trainings_completed if plan else 0
        t_target = (
            (plan.trainings_target if plan else 4) if s.school_type == "core" else 0
        )
        total_done = v_done + t_done
        total_target = v_target + t_target

        is_package_complete = total_done >= total_target and total_target > 0
        if is_package_complete:
            completed_count += 1
        elif total_done > 0:
            in_progress_count += 1

        ssa_avg = ssa_scores.get(s.id)
        if ssa_avg is None and plan and plan.baseline_average is not None:
            ssa_avg = plan.baseline_average
        ssa_str = f"{round(ssa_avg, 1)}" if ssa_avg is not None else "—"

        formatted_schools.append(
            {
                "school_type": s.school_type,
                "id": s.id,
                "school_id": s.school_id or s.id,
                "name": s.name,
                "district": getattr(s.district, "name", "") or "—",
                "cluster_name": cluster_map.get(s.cluster_id, "—"),
                "cluster_id": s.cluster_id,
                "owner_id": getattr(owner, "id", None),
                "owner_user_id": getattr(owner, "user_id", None),
                "owner_name": _label(owner)
                if owner
                else (s.account_owner_name_raw or "Unassigned"),
                "lead_id": getattr(lead, "id", None),
                "lead_user_id": getattr(lead, "user_id", None),
                "lead_name": _label(lead) if lead else "Unassigned",
                "visits_completed": v_done,
                "visits_target": v_target,
                "trainings_completed": t_done,
                "trainings_target": t_target,
                "total_done": total_done,
                "total_target": total_target,
                "progress_pct": int(round((total_done / total_target) * 100))
                if total_target > 0
                else 0,
                "is_package_complete": is_package_complete,
                "status": plan.status if plan else "Not Initialized",
                "ssa_avg": ssa_str,
            }
        )

    # 6. Build hierarchy tabs
    if is_programme_lead:
        # Level 1 tabs: the lead's own core schools first, then each officer
        # on the roster — holding core schools or not, so an officer with
        # none is a zero row rather than a missing one and nobody's colour
        # shifts when a colleague has nothing to show.
        from apps.hr.team_roster import team_members

        def _group(oid: str, name: str, *, mine: bool = False) -> dict:
            return {
                "id": oid,
                "name": name,
                "tab_label": "My Core Schools" if mine else name,
                "heading": "My Core Schools" if mine else f"{name}'s Core Schools",
                "schools": [],
                "count": 0,
                "completed": 0,
                "core_work": [],
                **_EMPTY_PACKAGE_TOTALS,
            }

        own_label = f"{getattr(principal, 'name', '') or 'My work'} (you)"
        mine = _group("my-core-schools", own_label, mine=True)
        cceo_groups: dict[str, dict] = {
            str(member.id): _group(str(member.id), _label(member))
            for member in team_members(principal)
        }
        for row in formatted_schools:
            if str(row["owner_id"]) in own_ids or str(row["owner_user_id"]) in own_ids:
                group = mine
            else:
                oid = str(row["owner_id"] or row["owner_name"] or "__unassigned__")
                group = cceo_groups.setdefault(oid, _group(oid, row["owner_name"]))
            group["schools"].append(row)
            group["count"] += 1
            _add_package_totals(group, row)
            if row["is_package_complete"]:
                group["completed"] += 1

        # Each person's planned core work, on their own tab: it is their My
        # Plan being mirrored, so it follows who does the work rather than
        # who holds the school.
        for item in core_work:
            worker = directory.get(item.operational_owner_id)
            worker_ids = {
                str(getattr(worker, "id", "")),
                str(getattr(worker, "user_id", "")),
            }
            if str(item.operational_owner_id) in own_ids or worker_ids & own_ids:
                group = mine
            else:
                oid = str(getattr(worker, "id", "") or UNASSIGNED_WORKER)
                group = cceo_groups.setdefault(
                    oid,
                    _group(
                        oid,
                        _label(worker)
                        if worker
                        else (item.operational_owner_name or "Unassigned"),
                    ),
                )
            group["core_work"].append(item)

        cceo_tabs = [mine] + sorted(
            cceo_groups.values(),
            key=lambda g: (g["name"] == "Unassigned", g["name"].casefold()),
        )
        leads_data = []
    else:
        # Level 1: Supervising PLs, Level 2: CCEOs
        sys_pls = system_program_leads()
        pl_lookup: dict[str, dict] = {}
        leads_data = []
        for pl in sys_pls:
            pl_dict = {
                "id": pl["id"],
                "name": pl["name"],
                "cceos": {},
                "count": 0,
                "completed": 0,
                **_EMPTY_PACKAGE_TOTALS,
            }
            leads_data.append(pl_dict)
            for pid in pl["ids"]:
                pl_lookup[pid] = pl_dict

        unassigned_pl: dict = {
            "id": "__unassigned__",
            "name": "Unassigned",
            "cceos": {},
            "count": 0,
            "completed": 0,
            **_EMPTY_PACKAGE_TOTALS,
        }

        for row in formatted_schools:
            target_pl = pl_lookup.get(row["lead_id"]) if row["lead_id"] else None
            if not target_pl and row["lead_user_id"]:
                target_pl = pl_lookup.get(row["lead_user_id"])
            if not target_pl:
                target_pl = unassigned_pl

            target_pl["count"] += 1
            _add_package_totals(target_pl, row)
            if row["is_package_complete"]:
                target_pl["completed"] += 1

            oid = str(row["owner_id"] or row["owner_name"] or "__unassigned__")
            cceo_entry = target_pl["cceos"].setdefault(
                oid, _officer_entry(oid, row["owner_name"])
            )
            cceo_entry["schools"].append(row)
            cceo_entry["count"] += 1
            _add_package_totals(cceo_entry, row)
            if row["is_package_complete"]:
                cceo_entry["completed"] += 1

        # Each person's planned core work under their own Programme Lead,
        # the same line their schools are filed by.
        for item in core_work:
            worker = directory.get(item.operational_owner_id)
            lead = _supervisor_of(worker)
            target_pl = (
                (pl_lookup.get(lead.id) or pl_lookup.get(lead.user_id))
                if lead
                else None
            ) or unassigned_pl
            oid = str(getattr(worker, "id", "") or UNASSIGNED_WORKER)
            name = (
                _label(worker)
                if worker
                else (item.operational_owner_name or "Unassigned")
            )
            target_pl["cceos"].setdefault(oid, _officer_entry(oid, name))[
                "core_work"
            ].append(item)

        for pl_entry in leads_data:
            pl_entry["cceo_tabs"] = sorted(
                pl_entry["cceos"].values(),
                key=lambda g: (g["name"] == "Unassigned", g["name"].casefold()),
            )

        if unassigned_pl["count"] > 0 or unassigned_pl["cceos"]:
            unassigned_pl["cceo_tabs"] = sorted(
                unassigned_pl["cceos"].values(),
                key=lambda g: (g["name"] == "Unassigned", g["name"].casefold()),
            )
            leads_data.append(unassigned_pl)

        cceo_tabs = []

    # Each member has separate lifecycle tables; package totals remain core-only.
    programme_by_id = {
        row["id"]: row
        for row in programme_rows(
            [s for s in schools if s.school_type != "core"],
            fy,
        )
    }
    groups = (
        cceo_tabs
        if is_programme_lead
        else [tab for lead in leads_data for tab in lead["cceo_tabs"]]
    )
    for group in groups:
        group["core_schools"] = [
            row for row in group["schools"] if row["school_type"] == "core"
        ]
        group["programme_sections"] = [
            {
                "kind": kind,
                "label": label,
                "param": f"{kind}-{group['id']}",
                "rows": [
                    programme_by_id[row["id"]]
                    for row in group["schools"]
                    if row["school_type"] == kind
                ],
            }
            for kind, label in type_options()
        ]

    # The package chart sums the core schools each person holds, so it is
    # drawn for "you" and the officers who hold them. A tab opened only by
    # planned work — someone visiting a school another officer holds — has no
    # package of its own, and eight such all-zero people filled the chart's
    # first range with nothing to draw.
    package_chart_tabs = [
        tab for index, tab in enumerate(cceo_tabs) if index == 0 or tab["count"]
    ]

    valid_ssas = [float(s["ssa_avg"]) for s in formatted_schools if s["ssa_avg"] != "—"]
    overall_avg = round(sum(valid_ssas) / len(valid_ssas), 1) if valid_ssas else "—"

    return {
        "is_programme_lead": is_programme_lead,
        "leads": leads_data,
        "cceo_tabs": cceo_tabs,
        "package_chart_tabs": package_chart_tabs,
        "total_schools": len(schools),
        "completed_packages": completed_count,
        "in_progress": in_progress_count,
        "avg_ssa": overall_avg,
        # Folded from the rows the tabs list, so the tile and the tables agree.
        "planned_core_work": len(core_work),
        "plan_period_label": plan_period_label,
        "fy": fy,
    }
