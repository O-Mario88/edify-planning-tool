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


def _add_package_totals(group: dict, row: dict) -> None:
    for key in _PACKAGE_TOTAL_KEYS:
        group[key] += int(row.get(key) or 0)


def core_schools_oversight_data(principal, *, fy: str | None = None) -> dict:
    """Returns database-driven core schools oversight dataset."""
    fy = str(fy or get_operational_fy())
    scope = resolve_user_scope(principal)
    is_programme_lead = scope.active_role == EdifyRole.COUNTRY_PROGRAM_LEAD.value

    # 1. Query scoped core schools
    base = School.objects.filter(
        deleted_at__isnull=True, school_type="core"
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
        # Country or Regional scope
        from apps.core.scoping import school_country_q

        if scope.country:
            core_qs = base.filter(school_country_q(scope))
        else:
            core_qs = base.all()

    schools = list(core_qs.order_by("name"))
    if not schools:
        return {
            "is_programme_lead": is_programme_lead,
            "leads": [],
            "cceo_tabs": [],
            "total_schools": 0,
            "completed_packages": 0,
            "in_progress": 0,
            "avg_ssa": "—",
            "fy": fy,
        }

    school_ids = [s.id for s in schools]
    human_ids = [s.school_id for s in schools if s.school_id]
    all_school_keys = set(school_ids + human_ids)

    # 2. Staff directory for owners & supervisors
    owner_keys = {s.account_owner_id for s in schools if s.account_owner_id}
    directory = _staff_directory(owner_keys)

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
        plan = plans.get(s.school_id) or plans.get(s.id)

        v_done = plan.visits_completed if plan else 0
        v_target = plan.visits_target if plan else 4
        t_done = plan.trainings_completed if plan else 0
        t_target = plan.trainings_target if plan else 4
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
                oid,
                {
                    "id": oid,
                    "name": row["owner_name"],
                    "schools": [],
                    "count": 0,
                    "completed": 0,
                    **_EMPTY_PACKAGE_TOTALS,
                },
            )
            cceo_entry["schools"].append(row)
            cceo_entry["count"] += 1
            _add_package_totals(cceo_entry, row)
            if row["is_package_complete"]:
                cceo_entry["completed"] += 1

        for pl_entry in leads_data:
            pl_entry["cceo_tabs"] = sorted(
                pl_entry["cceos"].values(),
                key=lambda g: (g["name"] == "Unassigned", g["name"].casefold()),
            )

        if unassigned_pl["count"] > 0:
            unassigned_pl["cceo_tabs"] = sorted(
                unassigned_pl["cceos"].values(),
                key=lambda g: (g["name"] == "Unassigned", g["name"].casefold()),
            )
            leads_data.append(unassigned_pl)

        cceo_tabs = []

    valid_ssas = [float(s["ssa_avg"]) for s in formatted_schools if s["ssa_avg"] != "—"]
    overall_avg = round(sum(valid_ssas) / len(valid_ssas), 1) if valid_ssas else "—"

    return {
        "is_programme_lead": is_programme_lead,
        "leads": leads_data,
        "cceo_tabs": cceo_tabs,
        "total_schools": len(schools),
        "completed_packages": completed_count,
        "in_progress": in_progress_count,
        "avg_ssa": overall_avg,
        "fy": fy,
    }
