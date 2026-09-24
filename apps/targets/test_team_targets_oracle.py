"""Oracle for Team Targets (PLTeamTargetsService.get_page and _member) and
the approved-leave read behind its pacing.

The 2026-09-24 performance change reads the supervision portfolio as plain
values with subqueries instead of 50,000-id IN lists, looks district names up
once, reads the roster's approved leave in one query, and asks each member's
pace once per period. The `_frozen_*` functions below are copies of
the implementations before that change (commit 4425605), renamed and calling
each other; every test asserts the live code returns exactly what they return,
on fixtures covering an empty team, a member with no schools, a school with no
district, a deleted school, a school shared by two members, district, member
and category filters, a non-current FY, and approved, pending and unparseable
leave.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from apps.accounts.models import (
    Leave,
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
)
from apps.activities.models import Activity
from apps.core import request_cache
from apps.core.fy import get_month_date_range
from apps.core.metrics import render_precomputed_metric_item
from apps.core_schools.models import CorePlan
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord
from apps.targets.fy_calendar import FinancialYearCalendarService as Cal
from apps.targets.models import CatchUpPlan, MonthlyPersonalTarget, TargetArea
from apps.targets.my_targets import (
    MyTargetQueryService,
    TargetAchievementService,
    _user_ids,
    active_target_areas,
    agreed_target_areas,
    priority_target_areas_for_users,
    weighted_period_pct,
)
from apps.targets.team_targets import (
    COMPLETED_STATUSES,
    QUARTERS,
    RECOMMENDATIONS,
    RETURNED_STATUSES,
    SF_REQUIRED_TYPES,
    PLCatchUpPlanService,
    PLTeamTargetsService,
    supervised_users,
    team_status_display,
    team_status_for,
)

# ── Frozen reference (pre-change implementations, commit 4425605) ───────────


def _frozen_member(
    user,
    areas,
    fy,
    month_of_fy,
    today,
    m_start,
    m_end,
    is_current_fy,
    metric_areas=None,
    prepared=None,
):
    if prepared is None:
        TargetAchievementService.rebuild(user, fy)
        targets = MyTargetQueryService.monthly_targets(user, fy, areas=areas)
        achieved = MyTargetQueryService.monthly_achievements(user, fy, areas=areas)
    else:
        # The roster was rebuilt and read once by the caller; answer this
        # member from those rows exactly as the single-person reads would.
        explicit, profile, ledger_rows = prepared
        areas = list(areas)
        area_keys = {area.key for area in areas}
        targets = MyTargetQueryService._targets_from(areas, explicit, profile)
        achieved = MyTargetQueryService._achievements_from(
            areas, [row for row in ledger_rows if row.area.key in area_keys]
        )
    metric_areas = list(metric_areas or areas)
    pace = Cal.expected_pace_pct(m_start, m_end, today, user) if is_current_fy else 100

    def wpct(month_list, t_map=targets, a_map=achieved):
        """Delegates to the canonical weighted_period_pct (same formula as
        My Targets and the team-wide rollup below) — one formula, not
        reimplemented per caller."""
        return weighted_period_pct(
            metric_areas, t_map, a_map, month_list, none_if_unassigned=True
        )

    m_pct, m_a, m_t = wpct([month_of_fy])
    q = Cal.quarter_of_month(month_of_fy)
    q_months = Cal.months_of_quarter(q)
    q_pct, q_a, q_t = wpct(q_months)
    started = today >= m_start
    status, tone = team_status_for(m_pct, pace, started, m_t > 0)
    display_status, display_tone = team_status_display(status, tone)

    per_area = []
    for a in areas:
        t = targets[a.key][month_of_fy - 1]
        ach = achieved[a.key][month_of_fy - 1]
        per_area.append(
            {
                "key": a.key,
                "label": a.label,
                "weight": a.weight,
                "target": t,
                "achieved": ach,
                "pct": round(ach / t * 100) if t else None,
                "gap": max(0, t - ach),
            }
        )

    def period_cell(key, label, months, start, end):
        pct, ach, target = wpct(months)
        expected = Cal.expected_pace_pct(start, end, today, user)
        status, tone = team_status_for(pct, expected, today >= start, target > 0)
        status, tone = team_status_display(status, tone)
        return {
            "key": key,
            "label": label,
            "pct": pct,
            "display_pct": None if status == "Upcoming" else pct,
            "achieved": ach,
            "target": target,
            "status": status,
            "tone": tone,
        }

    period_specs = [
        {
            "key": "month",
            "label": "Monthly",
            "sub": Cal.month_label(fy, month_of_fy),
            "summary_label": Cal.month_label(fy, month_of_fy).split()[0],
            "months": [month_of_fy],
            "start": m_start,
            "end": m_end,
        }
    ]
    for quarter in QUARTERS:
        q_start, q_end = Cal.quarter_range(fy, quarter)
        period_specs.append(
            {
                "key": quarter,
                "label": quarter,
                "sub": Cal.quarter_label(fy, quarter),
                "summary_label": quarter,
                "months": Cal.months_of_quarter(quarter),
                "start": q_start,
                "end": q_end,
            }
        )
    fy_start, fy_end = Cal.fy_range(fy)
    period_specs.append(
        {
            "key": "fy",
            "label": f"FY {int(fy) - 1}/{str(fy)[-2:]}",
            "sub": "Full year",
            "summary_label": "Full year",
            "months": list(range(1, 13)),
            "start": fy_start,
            "end": fy_end,
        }
    )

    matrix_cells = [
        period_cell(
            spec["key"],
            spec["summary_label"],
            spec["months"],
            spec["start"],
            spec["end"],
        )
        for spec in period_specs
    ]

    visible_area_keys = {a.key for a in metric_areas}
    area_matrix = []
    for area in areas:
        if area.key not in visible_area_keys:
            continue
        periods = []
        for spec in period_specs:
            target = sum(targets[area.key][mm - 1] for mm in spec["months"])
            valid = sum(achieved[area.key][mm - 1] for mm in spec["months"])
            pct = round(valid / target * 100) if target else None
            expected = Cal.expected_pace_pct(spec["start"], spec["end"], today, user)
            period_status, period_tone = team_status_for(
                pct,
                expected,
                today >= spec["start"],
                target > 0,
            )
            period_status, period_tone = team_status_display(period_status, period_tone)
            periods.append(
                {
                    "key": spec["key"],
                    "label": spec["label"],
                    "sub": spec["sub"],
                    "pct": pct,
                    "display_pct": (None if period_status == "Upcoming" else pct),
                    "achieved": valid,
                    "target": target,
                    "status": period_status,
                    "tone": period_tone,
                }
            )
        area_matrix.append(
            {
                "key": area.key,
                "label": area.label,
                "weight": area.weight,
                "periods": periods,
            }
        )

    # The same "Cumulative progress by time period" table My Target shows,
    # for this member: target, achieved and share per period, one row per
    # priority, plus the weighted share the summary row already carries
    # (owner, 2026-09-05: each team member row expands to it).
    period_matrix_rows = [
        {
            "label": area["label"],
            "key": area["key"],
            "cells": [
                {"t": p["target"], "a": p["achieved"], "pct": p["display_pct"]}
                for p in area["periods"]
            ],
        }
        for area in area_matrix
    ]
    period_matrix_overall = [{"pct": cell["display_pct"]} for cell in matrix_cells]

    mobile_cells = [
        matrix_cells[0],
        next(cell for cell in matrix_cells if cell["key"] == q),
        matrix_cells[-1],
    ]

    return {
        "user": user,
        "user_id": user.id,
        "staff_id": getattr(user, "staff_profile_id", None),
        "name": user.name,
        "initials": (user.name or "??")[:2].upper(),
        "targets": targets,
        "achieved": achieved,
        "month_pct": m_pct,
        "month_achieved": m_a,
        "month_target": m_t,
        "remaining": max(0, m_t - m_a),
        "quarter_pct": q_pct,
        "quarter_achieved": q_a,
        "quarter_target": q_t,
        "pace": pace,
        "status": status,
        "tone": tone,
        "display_status": display_status,
        "display_tone": display_tone,
        "per_area": per_area,
        "visible_per_area": [
            row for row in per_area if row["key"] in {a.key for a in metric_areas}
        ],
        "matrix_cells": matrix_cells,
        "mobile_cells": mobile_cells,
        "area_matrix": area_matrix,
        "period_matrix_rows": period_matrix_rows,
        "period_matrix_overall": period_matrix_overall,
        "metric_areas": metric_areas,
    }


def _frozen_get_page(
    pl_user,
    fy: str | None = None,
    month_of_fy: int | None = None,
    category: str | None = None,
    district: str | None = None,
    team_member: str | None = None,
) -> dict:
    now = Cal.current()
    fy = fy or now["fy"]
    is_current_fy = fy == now["fy"]
    month_of_fy = month_of_fy or (now["month_of_fy"] if is_current_fy else 1)
    today = now["today"]
    m_start, m_end = Cal.month_range(fy, month_of_fy)
    all_team = supervised_users(pl_user)
    priority_areas_by_user = priority_target_areas_for_users(all_team, fy)
    # The union of agreed areas across the team. Shared with CD Analytics
    # rather than duplicated: the two surfaces disagreeing about which
    # areas count IS CONFLICT-001, so they now compute it in one place.
    areas = agreed_target_areas(all_team, fy)
    valid_area_keys = {a.key for a in areas}
    category = category if category in valid_area_keys else "overall"
    metric_areas = (
        areas if category == "overall" else [a for a in areas if a.key == category]
    )
    selected_category_label = (
        "Overall weighted performance"
        if category == "overall"
        else metric_areas[0].label
    )

    all_staff_ids = [
        u.staff_profile_id for u in all_team if getattr(u, "staff_profile_id", None)
    ]

    # Build the complete supervision portfolio once. Filter options always
    # remain stable, while every metric below is calculated from the
    # selected reporting scope.
    staff_school = {}
    district_of_school = {}
    school_names = {}
    if all_staff_ids:
        from apps.schools.models import School

        # Only the columns this page reads (id, code, name, district name).
        # A country or regional roster is every school in scope, and full
        # rows were ~16,000 schools, districts and assignments instantiated
        # per load (performance rescue, 2026-09-23).
        assigns = list(
            StaffSchoolAssignment.objects.filter(staff_id__in=all_staff_ids).only(
                "staff_id", "school_id"
            )
        )
        school_pks = {a.school_id for a in assigns}
        schools = {
            s.id: s
            for s in School.objects.filter(id__in=school_pks)
            .select_related("district")
            .only("id", "school_id", "name", "district_id", "district__name")
        }
        for assignment in assigns:
            school = schools.get(assignment.school_id)
            if not school:
                continue
            staff_school.setdefault(assignment.staff_id, []).append(school)
            school_names[school.school_id] = school.name
            if school.district_id:
                district_of_school[school.id] = school.district

    district_options = sorted(
        {
            school.district.name
            for schools in staff_school.values()
            for school in schools
            if school.district_id
        }
    )
    district = district if district in district_options else ""
    valid_member_ids = {str(u.id) for u in all_team}
    team_member = str(team_member or "")
    team_member = team_member if team_member in valid_member_ids else ""

    team = []
    for user in all_team:
        if team_member and str(user.id) != team_member:
            continue
        if district and not any(
            school.district_id and school.district.name == district
            for school in staff_school.get(user.staff_profile_id, [])
        ):
            continue
        team.append(user)

    # One ledger rebuild and one read of targets, profiles and validated
    # credit for the whole roster. Per member this was a rebuild (four
    # source reads and its writes) and three target reads on every load.
    TargetAchievementService.rebuild_many(team, fy)
    roster_area_keys = sorted(
        {
            area.key
            for user in team
            for area in priority_areas_by_user.get(str(user.id), [])
        }
    )
    roster_targets = MyTargetQueryService._explicit_targets(team, fy, roster_area_keys)
    roster_profiles = MyTargetQueryService._target_profiles(team, fy)
    roster_ledger = MyTargetQueryService._validated_ledger(team, fy, roster_area_keys)

    members = []
    for user in team:
        user_areas = priority_areas_by_user.get(str(user.id), [])
        user_metric_areas = (
            user_areas
            if category == "overall"
            else [area for area in user_areas if area.key == category]
        )
        members.append(
            _frozen_member(
                user,
                user_areas,
                fy,
                month_of_fy,
                today,
                m_start,
                m_end,
                is_current_fy,
                metric_areas=user_metric_areas,
                prepared=(
                    roster_targets.get(user.id, {}),
                    roster_profiles.get(getattr(user, "staff_profile_id", None)),
                    roster_ledger.get(user.id, ()),
                ),
            )
        )
    team_ids = [i for m in members for i in _user_ids(m["user"])]

    # Grouped by Programme Lead for the Regional Programme Lead, who reads
    # many Leads' teams at once (owner, 2026-09-12). Each officer carries
    # their Lead's name and the table draws a header where it changes.
    group_by_lead = getattr(pl_user, "active_role", "") == "RegionalProgramLead"
    if group_by_lead:
        from apps.planning.owner_groups import NO_LEAD, owner_directory

        directory = owner_directory(
            {m["staff_id"] for m in members if m.get("staff_id")}
        )
        for m in members:
            entry = directory.get(m.get("staff_id") or "")
            m["lead_name"] = (entry or {}).get("pl_name") or NO_LEAD
        members.sort(
            key=lambda m: (m["lead_name"] == NO_LEAD, m["lead_name"], m["name"])
        )
    for m in members:
        ds = {
            s.district.name
            for s in staff_school.get(m["staff_id"], [])
            if s.district_id
        }
        m["districts"] = sorted(ds)
        m["district_label"] = ", ".join(sorted(ds)[:2]) or "—"
        m["schools"] = staff_school.get(m["staff_id"], [])

    # ── team series (sums across members, per area) ──────────────────────
    def team_series(field):
        out = {a.key: [0] * 12 for a in areas}
        for m in members:
            for a in areas:
                series = m[field].get(a.key, [0] * 12)
                for i in range(12):
                    out[a.key][i] += series[i]
        return out

    t_targets = team_series("targets")
    t_achieved = team_series("achieved")

    def team_wpct(month_list):
        """Average each member's priority-weighted result for the period."""
        pcts = []
        total_achieved = total_target = 0
        for member in members:
            pct, achieved, target = weighted_period_pct(
                member["metric_areas"],
                member["targets"],
                member["achieved"],
                month_list,
                none_if_unassigned=True,
            )
            total_achieved += achieved
            total_target += target
            if pct is not None:
                pcts.append(pct)
        return (
            round(sum(pcts) / len(pcts)) if pcts else 0,
            total_achieved,
            total_target,
        )

    def raw_pct(month_list):
        t = sum(
            sum(t_targets[a.key][mm - 1] for mm in month_list) for a in metric_areas
        )
        ach = sum(
            sum(t_achieved[a.key][mm - 1] for mm in month_list) for a in metric_areas
        )
        return (round(ach / t * 100) if t else 0), ach, t

    cur_quarter = Cal.quarter_of_month(month_of_fy)
    q_months = Cal.months_of_quarter(cur_quarter)

    team_w_pct, team_m_a, team_m_t = team_wpct([month_of_fy])
    month_pct, _, _ = raw_pct([month_of_fy])
    quarter_pct, q_a, q_t = raw_pct(q_months)
    fy_w_pct, fy_a, fy_t = team_wpct(list(range(1, 13)))

    prev_w_pct = None
    if month_of_fy > 1:
        prev_w_pct, _, _ = team_wpct([month_of_fy - 1])

    on_track = [
        m for m in members if m["status"] in ("On Track", "Complete", "Exceeded")
    ]
    behind = [
        m
        for m in members
        if m["status"] in ("Slightly Behind", "High Risk", "Critical")
    ]
    high_risk = [m for m in members if m["status"] in ("High Risk", "Critical")]
    critical = [m for m in members if m["status"] == "Critical"]

    # ── SF ID compliance + core schools (operational indicators) ─────────
    fy_s, fy_e = Cal.fy_range(fy)
    completed_acts = Activity.objects.filter(
        responsible_staff_id__in=team_ids,
        fy=fy,
        activity_type__in=SF_REQUIRED_TYPES,
        status__in=COMPLETED_STATUSES,
        deleted_at__isnull=True,
    ).exclude(delivery_type="partner")
    sf_required = completed_acts.count()
    sf_have = (
        completed_acts.exclude(salesforce_activity_id__isnull=True)
        .exclude(salesforce_activity_id="")
        .count()
    )
    sf_compliance = round(sf_have / sf_required * 100) if sf_required else 100
    sf_missing_count = sf_required - sf_have

    per_member_sf = {}
    for row in completed_acts.values("responsible_staff_id", "salesforce_activity_id"):
        key = row["responsible_staff_id"]
        have = bool((row["salesforce_activity_id"] or "").strip())
        tot, ok = per_member_sf.get(key, (0, 0))
        per_member_sf[key] = (tot + 1, ok + (1 if have else 0))
    for m in members:
        tot = ok = 0
        for i in _user_ids(m["user"]):
            t2, o2 = per_member_sf.get(i, (0, 0))
            tot += t2
            ok += o2
        m["sf_compliance"] = round(ok / tot * 100) if tot else 100
        m["sf_missing"] = tot - ok

    core_total = core_on_track = 0
    core_rows = []
    try:
        from apps.core_schools.models import CorePlan

        team_school_sids = list(school_names.keys())
        fy_pace = Cal.expected_pace_pct(fy_s, fy_e, today) if is_current_fy else 100
        for plan in CorePlan.objects.filter(
            school_id__in=team_school_sids, fy=fy
        ).exclude(status__in=["Cancelled", "cancelled"]):
            done = (
                (1 if plan.baseline_average is not None else 0)
                + min(4, plan.visits_completed or 0)
                + min(4, plan.trainings_completed or 0)
            )
            pkg_pct = round(done / 9 * 100)
            ok_flag = pkg_pct >= max(0, fy_pace - 20)
            core_total += 1
            core_on_track += 1 if ok_flag else 0
            core_rows.append(
                {
                    "school": school_names.get(plan.school_id, plan.school_id),
                    "pct": pkg_pct,
                    "on_track": ok_flag,
                    "visits": min(4, plan.visits_completed or 0),
                    "trainings": min(4, plan.trainings_completed or 0),
                }
            )
    except Exception:  # pragma: no cover — core module optional in some envs
        pass
    core_pct = round(core_on_track / core_total * 100) if core_total else None
    for m in members:
        # Built once per member. It sat inside the comprehension's
        # condition, so it was rebuilt for every core row: members x core
        # rows x schools lookups — 39.8 million on a regional roster, and
        # 7 of the 16 profiled seconds of /team-targets (performance
        # rescue, 2026-09-23).
        names = {school_names.get(s.school_id, s.school_id) for s in m["schools"]}
        mine = [r for r in core_rows if r["school"] in names]
        m["core_pct"] = round(sum(r["pct"] for r in mine) / len(mine)) if mine else None

    # ── KPI strip ────────────────────────────────────────────────────────
    kpis = [
        {
            "key": "team",
            "label": "Team Target Achievement",
            "value": f"{team_w_pct}%",
            "delta": (team_w_pct - prev_w_pct) if prev_w_pct is not None else None,
            "delta_unit": "pp vs last month",
            "drill": "matrix",
        },
        {
            "key": "monthly",
            "label": "Monthly Targets Achieved",
            "value": f"{month_pct}%",
            "delta": None,
            "delta_unit": f"{team_m_a} of {team_m_t} units",
            "drill": "matrix",
        },
        {
            "key": "quarterly",
            "label": "Quarterly Targets Achieved",
            "value": f"{quarter_pct}%",
            "delta": None,
            "delta_unit": f"{cur_quarter} · {q_a} of {q_t}",
            "drill": "matrix",
        },
        {
            "key": "on_track",
            "label": "Staff On Track",
            "value": len(on_track),
            "delta": None,
            "delta_unit": f"of {len(members)} staff",
            "drill": "staff",
        },
        render_precomputed_metric_item(
            "targets_team_targets_high_risk_staff",
            len(high_risk),
            key="high_risk",
            delta=None,
            delta_unit="high risk or critical",
            drill="high_risk",
            tone="danger" if high_risk else "success",
        ),
        {
            "key": "core",
            "label": "Core Schools On Track",
            "value": f"{core_pct}%" if core_pct is not None else "—",
            "delta": None,
            "delta_unit": f"{core_on_track} of {core_total} packages"
            if core_total
            else "no core plans",
            "drill": "core",
        },
        render_precomputed_metric_item(
            "targets_team_targets_activity_sf_id_compliance",
            f"{sf_compliance}%",
            key="sfid",
            delta=None,
            delta_unit=f"{sf_missing_count} missing",
            drill="sfid",
            tone="danger" if sf_compliance < 90 else "success",
        ),
    ]

    # ── What Needs Attention ─────────────────────────────────────────────
    empty_series = [0] * 12
    ssa_t = t_targets.get("ssa_completed", empty_series)[month_of_fy - 1]
    ssa_a = t_achieved.get("ssa_completed", empty_series)[month_of_fy - 1]
    visit_t = t_targets.get("school_visits", empty_series)[month_of_fy - 1]
    visit_a = t_achieved.get("school_visits", empty_series)[month_of_fy - 1]

    ssa_sched = (
        Activity.objects.filter(
            responsible_staff_id__in=team_ids,
            fy=fy,
            deleted_at__isnull=True,
            planned_date__gte=m_start,
            planned_date__lt=m_end,
            ssa_collection_expected=True,
        )
        .exclude(status__in=["cancelled", "rejected"])
        .count()
        if team_ids
        else 0
    )
    ssa_month_start, ssa_month_end = get_month_date_range(fy, month_of_fy)
    ssa_pending_ia = (
        SsaRecord.objects.filter(
            collected_by_user_id__in=team_ids,
            deleted_at__isnull=True,
            date_of_ssa__gte=ssa_month_start,
            date_of_ssa__lt=ssa_month_end,
        )
        .exclude(verification_status="confirmed")
        .count()
        if team_ids
        else 0
    )

    attention = [
        {
            "key": "behind",
            "label": "Staff Behind Target",
            "count": len(behind),
            "sub": f"of {len(members)} supervised staff",
            "action": "View Staff",
            "drill": "staff",
            "tone": "danger" if behind else "success",
        },
        {
            "key": "critical",
            "label": "Staff at Critical Risk",
            "count": len(critical),
            "sub": "below critical threshold",
            "action": "View Staff",
            "drill": "high_risk",
            "tone": "danger" if critical else "success",
        },
        {
            "key": "ssa_gap",
            "label": "SSA Target Gap",
            "count": max(0, ssa_t - ssa_a),
            "sub": f"{ssa_sched} scheduled · {ssa_pending_ia} awaiting IA",
            "action": "View Details",
            "drill": "area:ssa_completed",
            "tone": "warning" if ssa_t - ssa_a > 0 else "success",
        },
        {
            "key": "visit_gap",
            "label": "Valid Visit Gap",
            "count": max(0, visit_t - visit_a),
            "sub": f"{visit_a} valid of {visit_t} target",
            "action": "View Details",
            "drill": "area:school_visits",
            "tone": "warning" if visit_t - visit_a > 0 else "success",
        },
        {
            "key": "core_gap",
            "label": "Core School Target Gap",
            "count": core_total - core_on_track,
            "sub": f"of {core_total} core packages",
            "action": "View Schools",
            "drill": "core",
            "tone": "warning" if core_total - core_on_track else "success",
        },
    ]

    # ── Key target progress (5 official areas, team, month) ──────────────
    key_progress = []
    for a in metric_areas:
        t = t_targets[a.key][month_of_fy - 1]
        ach = t_achieved[a.key][month_of_fy - 1]
        pct = round(ach / t * 100) if t else None
        pace_month = (
            Cal.expected_pace_pct(m_start, m_end, today) if is_current_fy else 100
        )
        status, tone = team_status_for(pct, pace_month, today >= m_start, t > 0)
        key_progress.append(
            {
                "key": a.key,
                "label": a.label,
                "achieved": ach,
                "target": t,
                "pct": pct,
                "status": status,
                "tone": tone,
                "bar": min(pct or 0, 100),
            }
        )

    # ── Distribution donut ───────────────────────────────────────────────
    dist = {"On Track": 0, "Slightly Behind": 0, "High Risk": 0, "Critical": 0}
    for m in members:
        if m["status"] in ("On Track", "Complete", "Exceeded"):
            dist["On Track"] += 1
        elif m["status"] in dist:
            dist[m["status"]] += 1
    distribution = [{"label": k, "count": v} for k, v in dist.items() if v]

    # ── Districts most behind ────────────────────────────────────────────
    by_district = {}
    for m in members:
        for d in m["districts"]:
            row = by_district.setdefault(
                d, {"district": d, "pcts": [], "staff": 0, "gap": 0, "schools": 0}
            )
            row["pcts"].append(m["month_pct"] or 0)
            row["staff"] += 1
            row["gap"] += m["remaining"]
    seen_schools = set()
    for sid, sch_list in staff_school.items():
        for s in sch_list:
            if s.id in seen_schools:
                continue
            seen_schools.add(s.id)
            if s.district_id and s.district.name in by_district:
                by_district[s.district.name]["schools"] += 1
    districts_behind = sorted(
        [
            {**r, "pct": round(sum(r["pcts"]) / len(r["pcts"])) if r["pcts"] else 0}
            for r in by_district.values()
        ],
        key=lambda r: r["pct"],
    )[:6]

    # ── Recovery focus (behind staff × worst areas, blocker-matched) ─────
    recovery = []
    deadline = (m_end - timedelta(days=1)).strftime("%b %d, %Y")
    wd_left = Cal.working_days(max(m_start, today), m_end) if today < m_end else 0
    metric_area_keys = {area.key for area in metric_areas}
    for m in behind:
        worst = sorted(
            [
                pa
                for pa in m["per_area"]
                if pa["target"] and pa["key"] in metric_area_keys
            ],
            key=lambda pa: pa["pct"] or 0,
        )[:2]
        for pa in worst:
            if pa["gap"] <= 0:
                continue
            reason_key, reason_label = PLTeamTargetsService._blocker(
                m["user"], pa["key"], fy, month_of_fy, pa, wd_left
            )
            action_label, action_kind = RECOMMENDATIONS[reason_key]
            recovery.append(
                {
                    "staff": m["name"],
                    "staff_user_id": m["user_id"],
                    "initials": m["initials"],
                    "district": m["district_label"],
                    "area": pa["label"],
                    "area_key": pa["key"],
                    "gap": pa["gap"],
                    "pct": pa["pct"] or 0,
                    "reason": reason_label,
                    "recommendation": action_label,
                    "action_kind": action_kind,
                    "deadline": deadline,
                    "risk": m["status"],
                    "risk_tone": m["tone"],
                }
            )
    recovery.sort(
        key=lambda r: (
            {"Critical": 0, "High Risk": 1, "Slightly Behind": 2}.get(r["risk"], 3),
            -r["gap"],
        )
    )

    # ── Calendar ─────────────────────────────────────────────────────────
    calendar = PLTeamTargetsService._calendar(
        fy, month_of_fy, today, m_start, m_end, team_ids, is_current_fy
    )

    # ── Partner contribution ─────────────────────────────────────────────
    partners = PLTeamTargetsService._partner_rows(team_ids, fy)

    # ── Pending catch-up approvals ───────────────────────────────────────
    pending_catchups = CatchUpPlan.objects.filter(
        pl_user_id=pl_user.id, status="submitted"
    ).count()

    member_names = {str(m["user_id"]): m["name"] for m in members}
    # Advance any plans whose recovery activities have since completed —
    # keeps the active list honest and lets finished recoveries close.
    PLCatchUpPlanService.sync_completion(
        CatchUpPlan.objects.filter(
            pl_user_id=pl_user.id,
            fy=fy,
            status__in=["approved", "scheduled", "in_progress"],
        )
    )
    active_plan_qs = (
        CatchUpPlan.objects.filter(
            pl_user_id=pl_user.id,
            fy=fy,
            staff_user_id__in=list(member_names),
        )
        .exclude(status__in=["returned", "completed", "closed"])
        .select_related("area")
        .order_by("-created_at")
    )
    active_plan_count = active_plan_qs.count()
    recovery_plans = []
    for plan in active_plan_qs[:4]:
        due = Cal.month_range(plan.fy, plan.month_of_fy)[1] - timedelta(days=1)
        recovery_plans.append(
            {
                "id": plan.id,
                "staff": member_names.get(str(plan.staff_user_id), "Team member"),
                "area": plan.area.label,
                "status": plan.get_status_display(),
                "status_key": plan.status,
                "started": plan.created_at,
                "due": due,
            }
        )

    returned_count = (
        Activity.objects.filter(
            responsible_staff_id__in=team_ids,
            fy=fy,
            status__in=RETURNED_STATUSES,
            deleted_at__isnull=True,
        )
        .exclude(delivery_type="partner")
        .count()
        if team_ids
        else 0
    )
    awaiting_ia_count = (
        Activity.objects.filter(
            responsible_staff_id__in=team_ids,
            fy=fy,
            status="awaiting_ia_verification",
            deleted_at__isnull=True,
        )
        .exclude(delivery_type="partner")
        .count()
        if team_ids
        else 0
    )
    # Every tile opens a team-scoped drawer. Two of these used to point at
    # `/activities?status=...`, a route that does not exist — the tile
    # showed a real count and then 404'd on the way to the work behind it.
    # `drawer` is carried explicitly so the template does not have to infer
    # how a tile opens by sniffing its URL for a substring.
    validation_issues = [
        render_precomputed_metric_item(
            "targets_team_targets_awaiting_ia",
            awaiting_ia_count,
            tone="warning",
            drawer=True,
            href="/team-targets/validation-backlog"
            f"?status=awaiting_ia_verification&fy={fy}",
        ),
        render_precomputed_metric_item(
            "targets_team_targets_missing_sf_ids",
            sf_missing_count,
            tone="danger",
            drawer=True,
            href=f"/team-targets/sfid-backlog?fy={fy}",
        ),
        render_precomputed_metric_item(
            "targets_team_targets_returned_by_ia",
            returned_count,
            tone="info",
            drawer=True,
            href=f"/team-targets/validation-backlog?status=returned_by_ia&fy={fy}",
        ),
    ]

    support_staff = []
    for member in sorted(
        behind,
        key=lambda item: (
            {"Critical": 0, "High Risk": 1, "Slightly Behind": 2}.get(
                item["status"], 3
            ),
            item["month_pct"] or 0,
        ),
    )[:4]:
        relevant = [
            area
            for area in member["per_area"]
            if area["key"] in metric_area_keys and area["gap"] > 0
        ]
        primary_gap = (
            min(relevant, key=lambda area: area["pct"] or 0) if relevant else None
        )
        support_staff.append(
            {
                "user_id": member["user_id"],
                "name": member["name"],
                "initials": member["initials"],
                "district": member["district_label"],
                "status": member["status"],
                "tone": member["tone"],
                "reason": (
                    f"{primary_gap['label']} is {primary_gap['gap']} behind plan"
                    if primary_gap
                    else "Performance is below expected pace"
                ),
            }
        )

    team_trend = []
    chart_left, chart_right = 52, 1148
    chart_top, chart_bottom = 45, 510
    chart_step = (chart_right - chart_left) / 11
    for mm in range(1, 13):
        trend_pct, _, trend_target = team_wpct([mm])
        pct = trend_pct if trend_target else None
        x = round(chart_left + ((mm - 1) * chart_step), 2)
        y = (
            round(
                chart_bottom
                - (max(0, min(pct, 100)) / 100) * (chart_bottom - chart_top),
                2,
            )
            if pct is not None
            else None
        )
        team_trend.append(
            {
                "month": Cal.month_label(fy, mm).split()[0][:3],
                "pct": pct,
                "selected": mm == month_of_fy,
                "x": x,
                "y": y,
                "label_y": max(chart_top - 8, y - 15) if y is not None else None,
            }
        )

    team_trend_segments = []
    segment = []
    for point in team_trend:
        if point["y"] is None:
            if segment:
                team_trend_segments.append(
                    {"points": " ".join(f"{x},{y}" for x, y in segment)}
                )
                segment = []
            continue
        segment.append((point["x"], point["y"]))
    if segment:
        team_trend_segments.append({"points": " ".join(f"{x},{y}" for x, y in segment)})

    on_track_rate = round(len(on_track) / len(members) * 100) if members else 0
    summary_kpis = [
        render_precomputed_metric_item(
            "targets_team_targets_team_achievement",
            f"{team_w_pct}%",
            key="achievement",
            meta=f"{team_w_pct - prev_w_pct:+d} pp vs last month"
            if prev_w_pct is not None
            else f"{team_m_a} of {team_m_t} weighted units",
            tone="primary",
        ),
        render_precomputed_metric_item(
            "targets_team_targets_monthly_on_track",
            f"{on_track_rate}%",
            key="on_track",
            meta=f"{len(on_track)} of {len(members)} team members",
            tone="success",
        ),
        render_precomputed_metric_item(
            "targets_team_targets_at_risk_staff",
            len(high_risk),
            key="risk",
            meta="High risk or critical",
            tone="danger" if high_risk else "success",
        ),
        render_precomputed_metric_item(
            "targets_team_targets_current_quarter",
            f"{quarter_pct}%",
            key="quarter",
            meta=f"{cur_quarter} · {q_a} of {q_t} units",
            tone="primary",
        ),
        render_precomputed_metric_item(
            "targets_team_targets_fy_achievement",
            f"{fy_w_pct}%",
            key="fy",
            meta=f"{fy_a} of {fy_t} weighted units",
            tone="primary",
        ),
        render_precomputed_metric_item(
            "targets_team_targets_recovery_plans",
            active_plan_count,
            key="recovery",
            meta="Active intervention plans",
            tone="warning" if active_plan_count else "success",
        ),
    ]

    # ── Field Debrief intelligence (mandate §11) ─────────────────────────
    from apps.debriefs.rollup_service import field_debrief_intelligence_summary

    field_debrief_intel = field_debrief_intelligence_summary(pl_user)

    # ── Risk notifications (idempotent) ──────────────────────────────────
    if is_current_fy:
        PLTeamTargetsService._notify_risk(
            pl_user, high_risk, fy, month_of_fy, all_members=members
        )

    from apps.hr.milestone_allocations import (
        strategic_priority_overview,
        team_milestone_targets,
    )

    strategic_milestones = team_milestone_targets(
        users=team,
        fy=fy,
        month_of_fy=month_of_fy,
    )
    # Approved strategic allocations share the same selected-month → Q1–Q4
    # → FY matrix as the employee's agreed operating priorities. They remain
    # separate from the operating weighted score: each governed milestone
    # keeps its own allocation weight and source instead of being silently
    # folded into the five legacy TargetArea weights.
    if category == "overall":
        members_by_user_id = {str(member["user_id"]): member for member in members}
        for allocation in strategic_milestones:
            member = members_by_user_id.get(str(allocation["teamMemberId"]))
            if member is None:
                continue
            period_rows = []
            for cell in allocation["periodCells"]:
                target = cell["t"]
                pct = cell["pct"]
                started = not cell["start"] or today >= cell["start"]
                expected = (
                    Cal.expected_pace_pct(
                        cell["start"], cell["end"], today, member["user"]
                    )
                    if cell["start"] and cell["end"]
                    else 0
                )
                status, tone = team_status_for(pct, expected, started, bool(target))
                status, tone = team_status_display(status, tone)
                period_rows.append(
                    {
                        "key": cell["key"],
                        "label": cell["label"],
                        "pct": pct,
                        "display_pct": None if status == "Upcoming" else pct,
                        "achieved": cell["a"],
                        "target": target,
                        "status": status,
                        "tone": tone,
                    }
                )
            member["area_matrix"].append(
                {
                    "key": f"strategic-{allocation['allocationId']}",
                    "label": allocation["milestone"],
                    "source": allocation["priority"],
                    "periods": period_rows,
                }
            )
    strategic_priorities = strategic_priority_overview(
        fy=fy,
        staff_ids=[
            user.staff_profile_id
            for user in team
            if getattr(user, "staff_profile_id", None)
        ],
    )
    from apps.projects.staff_priorities import team_project_priorities

    project_priorities = team_project_priorities(users=team, fy=fy)

    from apps.hr.accountability import (
        allocation_priorities,
        allocation_period_matrix,
    )

    distributed = allocation_priorities(pl_user, fy)
    contract_members = []
    for member_user in [pl_user, *team]:
        matrix = allocation_period_matrix(member_user, fy, month_of_fy)
        contract_members.append(
            {
                "name": member_user.name,
                "role": member_user.active_role,
                "matrix": matrix,
            }
        )

    return {
        "fy": fy,
        "fy_label": f"FY {int(fy) - 1}/{str(fy)[-2:]}",
        "month_of_fy": month_of_fy,
        "month_label": Cal.month_label(fy, month_of_fy),
        "quarter": cur_quarter,
        "is_current_fy": is_current_fy,
        "team_size": len(members),
        "overall_team_size": len(all_team),
        "filters_active": bool(category != "overall" or district or team_member),
        "distributed": distributed,
        "contract_members": contract_members,
        "selected_category": category,
        "selected_category_label": selected_category_label,
        "selected_district": district,
        "selected_team_member": team_member,
        "category_options": [
            {"value": "overall", "label": "Overall weighted performance"}
        ]
        + [{"value": a.key, "label": a.label} for a in areas],
        "district_options": district_options,
        "team_member_options": [
            {
                "value": u.id,
                "label": u.name,
                "title": getattr(getattr(u, "staff_profile", None), "title", "")
                or "CCEO",
            }
            for u in all_team
        ],
        "matrix_heads": [
            {
                "key": "month",
                "label": Cal.month_label(fy, month_of_fy).split()[0],
                "sub": "Selected month",
            }
        ]
        + [
            {
                "key": quarter,
                "label": quarter,
                "sub": Cal.quarter_label(fy, quarter),
            }
            for quarter in QUARTERS
        ]
        + [
            {
                "key": "fy",
                "label": f"FY {int(fy) - 1}/{str(fy)[-2:]}",
                "sub": "Full year",
            }
        ],
        "kpis": kpis,
        "summary_kpis": summary_kpis,
        "attention": attention,
        "members": members,
        "group_by_lead": group_by_lead,
        "key_progress": key_progress,
        "distribution": distribution,
        "districts_behind": districts_behind,
        "recovery": recovery,
        "support_staff": support_staff,
        "recovery_plans": recovery_plans,
        "validation_issues": validation_issues,
        "team_trend": team_trend,
        "team_trend_segments": team_trend_segments,
        "calendar": calendar,
        "partners": partners,
        "pending_catchups": pending_catchups,
        "field_debrief_intel": field_debrief_intel,
        "areas": [{"key": a.key, "label": a.label, "weight": a.weight} for a in areas],
        "month_options": [
            {"value": mm, "label": Cal.month_label(fy, mm)} for mm in range(1, 13)
        ],
        "last_refreshed": timezone.now(),
        "strategic_milestones": strategic_milestones,
        "strategic_priorities": strategic_priorities,
        "project_priorities": project_priorities,
    }


def _frozen_all_leave_days(sp_id: str) -> frozenset:
    """Every approved leave day for one staff member, memoised per request.

    Keyed on the person alone, deliberately. The previous cache keyed on
    (person, start, end), which sounds tighter but missed on almost every
    call: Team Targets asks about the same nine people over five different
    windows, so forty-five distinct keys each ran their own query. A
    person's approved leave cannot change mid-request, so it is read once
    and every window is answered from it.

    Approved leave runs to a handful of rows per person, so expanding all
    of it costs less than the query that would otherwise narrow it.
    """
    from datetime import date as _d

    from apps.accounts.models import Leave
    from apps.core.request_cache import memoize

    def _compute() -> frozenset:
        days: set = set()
        for lv in Leave.objects.filter(status="approved", staff_id=sp_id):
            try:
                d0 = _d.fromisoformat(lv.start_date)
                d1 = _d.fromisoformat(lv.end_date)
            except (TypeError, ValueError):
                continue
            day = d0
            while day <= d1:
                days.add(day)
                day += timedelta(days=1)
        return frozenset(days)

    return memoize(("leave_all", sp_id), _compute)


# ── Fixtures and assertions ──────────────────────────────────────────────────

User = get_user_model()
FY = "2026"
TODAY = date(2026, 7, 15)  # month 10 of FY2026, Q4
JULY = 10


def _fixed_current(at=None):
    return {
        "today": TODAY,
        "fy": FY,
        "month_of_fy": JULY,
        "quarter": "Q4",
        "month_label": "July 2026",
    }


def _portfolio(page):
    """The schools behind each member, which compare by pk alone as models."""
    return [
        [(s.id, s.school_id, s.name, s.district_id) for s in m["schools"]]
        for m in page["members"]
    ]


@freeze_time("2026-07-15 10:00:00+03:00")
class TeamTargetsOracleTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        active_target_areas()
        region = Region.objects.create(name="Oracle Region")
        alpha = District.objects.create(
            name="Alpha", region=region, district_type="primary"
        )
        beta = District.objects.create(
            name="Beta", region=region, district_type="primary"
        )

        def staff(email, role):
            user = User.objects.create_user(
                email=email,
                name=email.split("@")[0].title(),
                roles=[role],
                active_role=role,
                password="x",
                is_active=True,
            )
            return user, StaffProfile.objects.create(user=user, title=role)

        cls.pl, pl_sp = staff("tt-pl@t.org", "Program Lead")
        cls.other_pl, other_pl_sp = staff("tt-pl2@t.org", "Program Lead")
        cls.lone_pl, _ = staff("tt-pl3@t.org", "Program Lead")
        cls.cd, _ = staff("tt-cd@t.org", "CountryDirector")
        cls.c1, c1 = staff("tt-c1@t.org", "CCEO")
        cls.c2, c2 = staff("tt-c2@t.org", "CCEO")
        cls.c3, c3 = staff("tt-c3@t.org", "CCEO")
        cls.c4, c4 = staff("tt-c4@t.org", "CCEO")
        cls.officers = (c1, c2, c3, c4)
        for supervisor, supervisee in (
            (pl_sp, c1),
            (pl_sp, c2),
            (pl_sp, c3),
            (other_pl_sp, c4),
        ):
            StaffSupervisorAssignment.objects.create(
                supervisor=supervisor, supervisee=supervisee
            )

        def school(code, district):
            return School.objects.create(
                school_id=code, name=f"School {code}", region=region, district=district
            )

        s1, s2 = school("TT-1", alpha), school("TT-2", beta)
        s3 = school("TT-3", None)  # no district
        s4 = school("TT-4", alpha)  # deleted below
        s5 = school("TT-5", alpha)  # shared by two officers
        for sp, schools in ((c1, (s1, s3, s4, s5)), (c2, (s2, s5)), (c4, (s2,))):
            for s in schools:
                StaffSchoolAssignment.objects.create(staff=sp, school_id=s.id)
        School.objects.filter(id=s4.id).update(deleted_at=timezone.now())
        for s, status, visits, baseline in (
            (s1, "Active", 2, 5.0),
            (s2, "Cancelled", 4, 6.0),
            (s5, "Active", 0, None),
            (s4, "Active", 4, 7.0),
        ):
            CorePlan.objects.create(
                id=f"cplan-{s.school_id}",
                school_id=s.school_id,
                fy=FY,
                status=status,
                visits_completed=visits,
                trainings_completed=1,
                baseline_average=baseline,
            )

        visits = TargetArea.objects.get(key="school_visits")
        ssa = TargetArea.objects.get(key="ssa_completed")
        for user, area, month, target in (
            (cls.c1, visits, JULY, 4),
            (cls.c1, visits, JULY - 1, 3),
            (cls.c1, ssa, JULY, 2),
            (cls.c2, visits, JULY, 6),
            (cls.c2, visits, 2, 5),
            (cls.c4, visits, JULY, 1),
        ):
            MonthlyPersonalTarget.objects.create(
                user_id=user.id, area=area, fy=FY, month_of_fy=month, target=target
            )

        def act(sp, planned, status="ia_verified", sf_id="unique", **extra):
            if sf_id == "unique":  # Salesforce IDs are unique platform-wide
                sf_id = f"SF-{Activity.objects.count() + 1}"
            return Activity.objects.create(
                school=extra.pop("school", s1),
                activity_type=extra.pop("activity_type", "school_visit"),
                delivery_type=extra.pop("delivery_type", "staff"),
                status=status,
                responsible_staff_id=sp.id,
                fy=FY,
                quarter="Q4",
                planned_date=planned,
                salesforce_activity_id=sf_id,
                scheduled_date=timezone.make_aware(
                    timezone.datetime(planned.year, planned.month, planned.day, 9)
                ),
                **extra,
            )

        act(c1, date(2026, 7, 2))
        act(c1, date(2026, 7, 3), sf_id="")  # completed, SF ID missing
        act(c1, date(2026, 7, 9), status="returned_by_ia")
        act(c1, date(2026, 7, 10), status="awaiting_ia_verification", sf_id=None)
        act(c1, date(2026, 6, 11), sf_id="SF-JUNE")
        act(
            c1,
            date(2026, 7, 20),
            status="scheduled",
            sf_id=None,
            ssa_collection_expected=True,
        )
        act(c2, date(2026, 7, 6), school=s2)
        act(
            c2,
            date(2026, 7, 7),
            school=s2,
            delivery_type="partner",
            monitored_by_staff_id=c2.id,
        )
        act(c4, date(2026, 7, 8), school=s2)
        SsaRecord.objects.create(
            school=s1,
            fy=FY,
            date_of_ssa=timezone.now() - timedelta(days=3),
            average_score=5.5,
            verification_status="pending",
            collected_by_user_id=cls.c1.id,
        )

        for sp, start, end, status in (
            (c1, "2026-07-06", "2026-07-08", "approved"),
            (c1, "2026-07-21", "2026-07-22", "pending"),
            (c1, "2026-06-29", "2026-07-01", "approved"),
            (c2, "July 1st", "July 3rd", "approved"),  # unparseable: skipped
            (c2, "2026-07-13", "2026-07-13", "approved"),
        ):
            Leave.objects.create(
                staff=sp,
                type="annual",
                start_date=start,
                end_date=end,
                status=status,
                days=1,
            )

    def setUp(self):
        current = patch.object(Cal, "current", side_effect=_fixed_current)
        current.start()
        self.addCleanup(current.stop)

    def _isolated(self, fn, in_request):
        """Run fn from the same database state every time, optionally inside
        a request's memo scope (where the leave read is primed)."""
        sid = transaction.savepoint()
        if in_request:
            request_cache.begin()
        try:
            return fn()
        finally:
            if in_request:
                request_cache.end()
            transaction.savepoint_rollback(sid)

    def assertSameAsFrozen(self, user, **kwargs):
        for in_request in (True, False):
            with self.subTest(user=user.email, in_request=in_request, **kwargs):
                expected = self._isolated(
                    lambda: _frozen_get_page(user, **kwargs), in_request
                )
                actual = self._isolated(
                    lambda: PLTeamTargetsService.get_page(user, **kwargs), in_request
                )
                self.assertEqual(actual, expected)
                self.assertEqual(_portfolio(actual), _portfolio(expected))

    def test_programme_lead_page(self):
        self.assertSameAsFrozen(self.pl)
        self.assertSameAsFrozen(self.pl, month_of_fy=3)
        self.assertSameAsFrozen(self.pl, fy="2027", month_of_fy=1)

    def test_filters(self):
        for kwargs in (
            {"district": "Alpha"},
            {"district": "Beta"},
            {"district": "Nowhere"},
            {"team_member": str(self.c2.id)},
            {"team_member": "not-a-member"},
            {"category": "school_visits"},
            {"category": "not-an-area"},
            {"district": "Alpha", "category": "ssa_completed"},
        ):
            self.assertSameAsFrozen(self.pl, **kwargs)

    def test_country_director_and_empty_team(self):
        self.assertSameAsFrozen(self.cd)
        self.assertSameAsFrozen(self.cd, district="Beta")
        self.assertSameAsFrozen(self.lone_pl)
        self.assertSameAsFrozen(self.other_pl)

    def test_member_without_prepared_rows(self):
        m_start, m_end = Cal.month_range(FY, JULY)
        for user in (self.c1, self.c2, self.c3):
            areas = priority_target_areas_for_users([user], FY)[str(user.id)]
            for is_current in (True, False):
                args = (user, areas, FY, JULY, TODAY, m_start, m_end, is_current)
                with self.subTest(user=user.email, is_current=is_current):
                    self.assertEqual(
                        self._isolated(
                            lambda: PLTeamTargetsService._member(*args), False
                        ),
                        self._isolated(lambda: _frozen_member(*args), False),
                    )

    def test_leave_days(self):
        ids = [sp.id for sp in self.officers]
        expected = {}
        for sp_id in ids:
            request_cache.begin()
            try:
                expected[sp_id] = _frozen_all_leave_days(sp_id)
            finally:
                request_cache.end()
        # Outside a request, and inside one after the roster read.
        self.assertEqual({i: Cal._all_leave_days(i) for i in ids}, expected)
        request_cache.begin()
        try:
            Cal.prime_leave_days([*ids, None, ids[0]])
            self.assertEqual({i: Cal._all_leave_days(i) for i in ids}, expected)
        finally:
            request_cache.end()
        self.assertEqual(len(expected[ids[0]]), 6)
        self.assertEqual(len(expected[ids[1]]), 1)
        self.assertEqual(expected[ids[2]], frozenset())

    def test_fixture_exercises_the_edges(self):
        request_cache.begin()
        try:
            page = PLTeamTargetsService.get_page(self.pl)
        finally:
            request_cache.end()
        schools = {m["name"]: m["schools"] for m in page["members"]}
        self.assertEqual(len(schools), 3)
        self.assertIn([], schools.values())  # an officer with no schools
        self.assertEqual(page["district_options"], ["Alpha", "Beta"])
        self.assertTrue(
            any(k["value"] != "—" for k in page["kpis"] if k["key"] == "core")
        )
        statuses = {m["status"] for m in page["members"]}
        self.assertGreater(len(statuses), 1)
