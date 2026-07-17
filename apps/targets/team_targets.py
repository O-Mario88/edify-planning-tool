"""PLTeamTargetsService — the Program Lead's supervision and recovery cockpit.

Team Targets is an AGGREGATION of the validated My Targets performance of the
CCEOs the logged-in PL supervises. The PL never types team achievement:

    CCEO Monthly My Targets → CCEO Q roll-up → CCEO FY roll-up → PL aggregation

Everything here reuses the My Targets engine (TargetAchievementService ledger,
MyTargetQueryService series, FinancialYearCalendarService pacing) so target
math exists in exactly one place. Partner-delivered work is reported as
Partner Contribution and never duplicated into CCEO personal credit.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone

from apps.accounts.models import StaffSchoolAssignment, StaffSupervisorAssignment, User
from apps.activities.models import Activity
from apps.core.fy import get_month_date_range
from apps.ssa.models import SsaRecord

from apps.targets.fy_calendar import (
    QUARTERS,
    FinancialYearCalendarService as Cal,
)
from apps.targets.models import CatchUpPlan, TargetArea
from apps.targets.my_targets import (
    AREA_SOURCES,
    COMPLETED_STATUSES,
    RETURNED_STATUSES,
    VISIT_TYPES,
    MyTargetQueryService,
    TargetAchievementService,
    _user_ids,
    active_target_areas,
    weighted_period_pct,
)

# Team pacing bands (mandate §13) — deliberately wider than My Targets bands.
TEAM_ON_TRACK_BAND = 5  # within 5pp of expected pace
TEAM_SLIGHT_BAND = 15  # 6–15pp below pace
TEAM_HIGH_RISK_BAND = 30  # 16–30pp below pace; beyond = Critical

# Activity types that require an Activity SF ID once completed (the three
# activity-backed target areas).
SF_REQUIRED_TYPES = tuple(
    t
    for key in ("school_visits", "cluster_meetings", "cluster_trainings")
    for t in AREA_SOURCES[key][1]
)

RECOMMENDATIONS = {
    "planning": ("Create Catch-Up Plan", "catchup"),
    "execution": ("Review My Plan and reschedule", "view_plan"),
    "pending_sf": ("Enter missing Activity SF IDs", "sfid"),
    "ia_pending": ("Monitor IA queue", "view_plan"),
    "returned": ("Resolve IA returns", "view_plan"),
    "provisional": ("Complete pending review", "view_plan"),
    "workload": ("Rebalance workload or assign partner support", "rebalance"),
    "mscs": ("Submit MSCS", "view_plan"),
}


def supervised_users(pl_user) -> list[User]:
    """Active CCEOs directly supervised by this PL — the ONLY team lens.
    CD/Admin get a country oversight lens (all active CCEOs)."""
    role = getattr(pl_user, "active_role", "")
    if role in ("CountryDirector", "Admin"):
        return list(
            User.objects.filter(
                status="active", deleted_at__isnull=True, roles__contains=["CCEO"]
            )
            .select_related("staff_profile")
            .order_by("name")
        )
    sp_id = getattr(pl_user, "staff_profile_id", None)
    if not sp_id:
        return []
    supervisee_ids = list(
        StaffSupervisorAssignment.objects.filter(supervisor_id=sp_id).values_list(
            "supervisee_id", flat=True
        )
    )
    return list(
        User.objects.filter(
            staff_profile__id__in=supervisee_ids,
            status="active",
            deleted_at__isnull=True,
        )
        .select_related("staff_profile")
        .order_by("name")
    )


def team_status_for(
    pct: int | None, pace: int, started: bool, assigned: bool
) -> tuple[str, str]:
    """Pace-aware team status per mandate §13."""
    if not assigned:
        return ("Not Assigned", "neutral")
    if not started:
        return ("Not Started", "neutral")
    p = pct or 0
    if p > 100:
        return ("Exceeded", "success")
    if p == 100:
        return ("Complete", "success")
    gap = pace - p
    if gap <= TEAM_ON_TRACK_BAND:
        return ("On Track", "success")
    if gap <= TEAM_SLIGHT_BAND:
        return ("Slightly Behind", "warning")
    if gap <= TEAM_HIGH_RISK_BAND:
        return ("High Risk", "danger")
    return ("Critical", "danger")


def team_status_display(status: str, tone: str) -> tuple[str, str]:
    """Collapse operational risk bands into the five scannable UI states."""
    if status in {"Slightly Behind", "High Risk"}:
        return ("Needs Attention", "warning")
    if status == "Not Started":
        return ("Upcoming", "info")
    return (status, tone)


class PLTeamTargetsService:
    """Everything the Team Targets dashboard renders, strictly PL-scoped."""

    # ── member profile ───────────────────────────────────────────────────────
    @staticmethod
    def _member(
        user,
        areas,
        fy,
        month_of_fy,
        today,
        m_start,
        m_end,
        is_current_fy,
        metric_areas=None,
    ):
        TargetAchievementService.rebuild(user, fy)
        targets = MyTargetQueryService.monthly_targets(user, fy)
        achieved = MyTargetQueryService.monthly_achievements(user, fy)
        metric_areas = list(metric_areas or areas)
        pace = (
            Cal.expected_pace_pct(m_start, m_end, today, user) if is_current_fy else 100
        )

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
                expected = Cal.expected_pace_pct(
                    spec["start"], spec["end"], today, user
                )
                period_status, period_tone = team_status_for(
                    pct,
                    expected,
                    today >= spec["start"],
                    target > 0,
                )
                period_status, period_tone = team_status_display(
                    period_status, period_tone
                )
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
        }

    # ── the full page payload ────────────────────────────────────────────────
    @staticmethod
    def get_page(
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
        areas = active_target_areas()
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

        all_team = supervised_users(pl_user)
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

            assigns = list(
                StaffSchoolAssignment.objects.filter(staff_id__in=all_staff_ids)
            )
            school_pks = {a.school_id for a in assigns}
            schools = {
                s.id: s
                for s in School.objects.filter(id__in=school_pks).select_related(
                    "district"
                )
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

        members = [
            PLTeamTargetsService._member(
                u,
                areas,
                fy,
                month_of_fy,
                today,
                m_start,
                m_end,
                is_current_fy,
                metric_areas=metric_areas,
            )
            for u in team
        ]
        team_ids = [i for m in members for i in _user_ids(m["user"])]

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
                    for i in range(12):
                        out[a.key][i] += m[field][a.key][i]
            return out

        t_targets = team_series("targets")
        t_achieved = team_series("achieved")

        def team_wpct(month_list):
            """Delegates to the canonical weighted_period_pct — the same
            formula My Targets uses per-user, applied here to the team-summed
            series. One canonical weighted formula, not a reimplementation."""
            return weighted_period_pct(metric_areas, t_targets, t_achieved, month_list)

        def raw_pct(month_list):
            t = sum(
                sum(t_targets[a.key][mm - 1] for mm in month_list) for a in metric_areas
            )
            ach = sum(
                sum(t_achieved[a.key][mm - 1] for mm in month_list)
                for a in metric_areas
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
        for row in completed_acts.values(
            "responsible_staff_id", "salesforce_activity_id"
        ):
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
            sids = {s.school_id for s in m["schools"]}
            mine = [
                r
                for r in core_rows
                if r["school"] in {school_names.get(x, x) for x in sids}
            ]
            m["core_pct"] = (
                round(sum(r["pct"] for r in mine) / len(mine)) if mine else None
            )

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
            {
                "key": "high_risk",
                "label": "High-Risk Staff",
                "value": len(high_risk),
                "delta": None,
                "delta_unit": "high risk or critical",
                "drill": "high_risk",
                "tone": "danger" if high_risk else "success",
            },
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
            {
                "key": "sfid",
                "label": "Activity SF ID Compliance",
                "value": f"{sf_compliance}%",
                "delta": None,
                "delta_unit": f"{sf_missing_count} missing",
                "drill": "sfid",
                "tone": "danger" if sf_compliance < 90 else "success",
            },
        ]

        # ── What Needs Attention ─────────────────────────────────────────────
        ssa_t = t_targets["ssa_completed"][month_of_fy - 1]
        ssa_a = t_achieved["ssa_completed"][month_of_fy - 1]
        visit_t = t_targets["school_visits"][month_of_fy - 1]
        visit_a = t_achieved["school_visits"][month_of_fy - 1]

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
                key=lambda pa: (pa["pct"] or 0),
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
        validation_issues = [
            {
                "label": "Awaiting IA",
                "value": awaiting_ia_count,
                "tone": "warning",
                "href": "/activities?status=awaiting_ia_verification",
            },
            {
                "label": "Missing SF IDs",
                "value": sf_missing_count,
                "tone": "danger",
                "href": f"/team-targets/sfid-backlog?fy={fy}",
            },
            {
                "label": "Returned by IA",
                "value": returned_count,
                "tone": "info",
                "href": "/activities?status=returned_by_ia",
            },
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
            team_trend_segments.append(
                {"points": " ".join(f"{x},{y}" for x, y in segment)}
            )

        on_track_rate = round(len(on_track) / len(members) * 100) if members else 0
        summary_kpis = [
            {
                "key": "achievement",
                "label": "Team achievement",
                "value": f"{team_w_pct}%",
                "meta": (
                    f"{team_w_pct - prev_w_pct:+d} pp vs last month"
                    if prev_w_pct is not None
                    else f"{team_m_a} of {team_m_t} weighted units"
                ),
                "tone": "primary",
            },
            {
                "key": "on_track",
                "label": "Monthly on track",
                "value": f"{on_track_rate}%",
                "meta": f"{len(on_track)} of {len(members)} team members",
                "tone": "success",
            },
            {
                "key": "risk",
                "label": "At-risk staff",
                "value": len(high_risk),
                "meta": "High risk or critical",
                "tone": "danger" if high_risk else "success",
            },
            {
                "key": "quarter",
                "label": "Current quarter",
                "value": f"{quarter_pct}%",
                "meta": f"{cur_quarter} · {q_a} of {q_t} units",
                "tone": "primary",
            },
            {
                "key": "fy",
                "label": "FY achievement",
                "value": f"{fy_w_pct}%",
                "meta": f"{fy_a} of {fy_t} weighted units",
                "tone": "primary",
            },
            {
                "key": "recovery",
                "label": "Recovery plans",
                "value": active_plan_count,
                "meta": "Active intervention plans",
                "tone": "warning" if active_plan_count else "success",
            },
        ]

        # ── Field Debrief intelligence (mandate §11) ─────────────────────────
        from apps.debriefs.rollup_service import field_debrief_intelligence_summary

        field_debrief_intel = field_debrief_intelligence_summary(pl_user)

        # ── Risk notifications (idempotent) ──────────────────────────────────
        if is_current_fy:
            PLTeamTargetsService._notify_risk(pl_user, high_risk, fy, month_of_fy)

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
            "areas": [
                {"key": a.key, "label": a.label, "weight": a.weight} for a in areas
            ],
            "month_options": [
                {"value": mm, "label": Cal.month_label(fy, mm)} for mm in range(1, 13)
            ],
            "last_refreshed": timezone.now(),
        }

    # ── blocker classification (§19) ─────────────────────────────────────────
    @staticmethod
    def _blocker(user, area_key, fy, month_of_fy, pa, wd_left):
        p = MyTargetQueryService._pipeline(user, area_key, fy, month_of_fy)
        if p["pending_sf"]:
            return (
                "pending_sf",
                f"{len(p['pending_sf'])} completed missing Activity SF IDs",
            )
        if p["returned"]:
            return "returned", f"{len(p['returned'])} returned item(s) need correction"
        if p["ia_pending"]:
            return "ia_pending", f"{len(p['ia_pending'])} awaiting IA verification"
        scheduled = len(p["scheduled"])
        if area_key == "mscs" and not scheduled:
            return "mscs", "No MSCS submitted this month"
        if scheduled + len(p["validated"]) < pa["target"]:
            if pa["gap"] > wd_left:
                return (
                    "workload",
                    f"Gap of {pa['gap']} exceeds {wd_left} working days left",
                )
            return "planning", f"Only {scheduled} scheduled toward {pa['target']}"
        if scheduled:
            return "execution", f"{scheduled} scheduled but not yet executed"
        if p["provisional"]:
            return "provisional", f"{len(p['provisional'])} awaiting review"
        return "planning", "No activity planned yet this month"

    # ── calendar ─────────────────────────────────────────────────────────────
    @staticmethod
    def _calendar(fy, month_of_fy, today, m_start, m_end, team_ids, is_current_fy):
        from apps.accounts.models import PublicHoliday
        from apps.targets.models import TargetAchievementLedger

        holidays = set(
            PublicHoliday.objects.filter(date__gte=m_start, date__lt=m_end).values_list(
                "date", flat=True
            )
        )
        valid_by_day = {}
        if team_ids:
            for d in TargetAchievementLedger.objects.filter(
                user_id__in=team_ids,
                fy=fy,
                validation_status="validated",
                activity_date__gte=m_start,
                activity_date__lt=m_end,
            ).values_list("activity_date", flat=True):
                valid_by_day[d] = valid_by_day.get(d, 0) + 1

        Cal.working_days(m_start, m_end) or 1

        weeks = []
        week = [None] * m_start.weekday()
        d = m_start
        cum_valid = 0
        wd_elapsed = 0
        while d < m_end:
            is_weekend = d.weekday() >= 5
            is_holiday = d in holidays
            cum_valid += valid_by_day.get(d, 0)
            if not is_weekend and not is_holiday:
                wd_elapsed += 1
            tone = "plain"
            if is_weekend or is_holiday:
                tone = "blocked"
            elif d > today:
                tone = "future"
            elif valid_by_day.get(d, 0) or cum_valid >= 1:
                # pace check happens at team level in the drawer; day dot shows
                # whether any validated work landed on the day
                tone = "good" if valid_by_day.get(d, 0) else "warn"
            else:
                tone = "warn"
            week.append(
                {
                    "day": d.day,
                    "iso": d.isoformat(),
                    "tone": tone,
                    "today": d == today,
                    "count": valid_by_day.get(d, 0),
                }
            )
            if len(week) == 7:
                weeks.append(week)
                week = []
            d += timedelta(days=1)
        if week:
            week += [None] * (7 - len(week))
            weeks.append(week)
        return {"weeks": weeks, "label": Cal.month_label(fy, month_of_fy)}

    # ── partner contribution ─────────────────────────────────────────────────
    @staticmethod
    def _partner_rows(team_ids, fy):
        from apps.partners.models import Partner

        if not team_ids:
            return []
        qs = (
            Activity.objects.filter(
                fy=fy,
                deleted_at__isnull=True,
                delivery_type="partner",
            )
            .filter(models_q_team(team_ids))
            .exclude(assigned_partner_id__isnull=True)
            .exclude(assigned_partner_id="")
        )
        by_partner = {}
        for a in qs:
            row = by_partner.setdefault(
                a.assigned_partner_id,
                {
                    "assigned": 0,
                    "scheduled": 0,
                    "valid": 0,
                    "valid_visits": 0,
                    "completed": 0,
                    "sf_ok": 0,
                    "ia_ok": 0,
                },
            )
            row["assigned"] += 1
            if a.status in ("scheduled", "planned"):
                row["scheduled"] += 1
            if a.status in COMPLETED_STATUSES:
                row["completed"] += 1
                has_sf = bool((a.salesforce_activity_id or "").strip())
                row["sf_ok"] += 1 if has_sf else 0
                if a.status in ("ia_verified", "verified", "closed"):
                    row["ia_ok"] += 1
                if has_sf and a.status != "awaiting_ia_verification":
                    row["valid"] += 1
                    if a.activity_type in VISIT_TYPES:
                        row["valid_visits"] += 1
        partners_by_id = {
            p.id: p for p in Partner.objects.filter(id__in=by_partner.keys())
        }
        out = []
        for pid, r in by_partner.items():
            p_obj = partners_by_id.get(pid)
            ach = round(r["valid"] / r["assigned"] * 100) if r["assigned"] else 0
            sf = round(r["sf_ok"] / r["completed"] * 100) if r["completed"] else 100
            ia = round(r["ia_ok"] / r["completed"] * 100) if r["completed"] else 0
            risk, tone = ("Low", "success")
            if ach < 40:
                risk, tone = "Critical", "danger"
            elif ach < 55:
                risk, tone = "High", "danger"
            elif ach < 70:
                risk, tone = "Medium", "warning"
            out.append(
                {
                    "partner_id": pid,
                    "name": p_obj.name if p_obj else "Partner",
                    "region": (p_obj.region_name or "—") if p_obj else "—",
                    "assigned": r["assigned"],
                    "scheduled": r["scheduled"],
                    "valid": r["valid"],
                    "valid_visits": r["valid_visits"],
                    "pct": ach,
                    "sf": sf,
                    "ia": ia,
                    "risk": risk,
                    "tone": tone,
                }
            )
        return sorted(out, key=lambda r: -r["assigned"])

    # ── risk notifications (idempotent per staff+month+level) ────────────────
    @staticmethod
    def _notify_risk(pl_user, high_risk_members, fy, month_of_fy):
        from apps.notifications.models import Notification

        for m in high_risk_members:
            ctx = f"{m['user_id']}:{fy}:{month_of_fy}:{m['status']}"
            if Notification.objects.filter(
                recipient_id=pl_user.id,
                category="team_targets",
                context_type="staff_risk",
                context_id=ctx[:30],
            ).exists():
                continue
            Notification.objects.create(
                recipient_id=pl_user.id,
                recipient_role="Program Lead",
                title=f"{m['name']} is {m['status']} on targets",
                body=(
                    f"{m['name']} is at {m['month_pct'] or 0}% against an expected "
                    f"pace of {m['pace']}% for {Cal.month_label(fy, month_of_fy)}."
                ),
                category="team_targets",
                context_type="staff_risk",
                context_id=ctx[:30],
                target_route="/team-targets",
                action_label="Review",
                action_required=True,
                priority="high",
            )
            Notification.objects.get_or_create(
                recipient_id=m["user_id"],
                category="team_targets",
                context_type="target_status",
                context_id=ctx[:30],
                defaults={
                    "recipient_role": "CCEO",
                    "title": f"Your targets are {m['status']}",
                    "body": "Open My Targets to see which areas need recovery this month.",
                    "target_route": "/my-targets",
                    "action_label": "Open My Targets",
                    "action_required": True,
                    "priority": "high",
                },
            )

    # ── detail matrix + export ───────────────────────────────────────────────
    @staticmethod
    def matrix(
        pl_user,
        fy: str | None = None,
        month_of_fy: int | None = None,
        area: str | None = None,
    ):
        now = Cal.current()
        fy = fy or now["fy"]
        month_of_fy = month_of_fy or (now["month_of_fy"] if fy == now["fy"] else 1)
        areas = active_target_areas()
        selected_area_key = (area or "").strip()
        if selected_area_key:
            areas = [item for item in areas if item.key == selected_area_key]
        selected_area_label = areas[0].label if selected_area_key and areas else ""
        current_quarter = Cal.quarter_of_month(month_of_fy)
        heads = (
            [
                {
                    "key": "month",
                    "label": Cal.month_label(fy, month_of_fy).split()[0],
                    "sub": "Monthly",
                }
            ]
            + [
                {"key": q, "label": q, "sub": Cal.quarter_label(fy, q)}
                for q in QUARTERS
            ]
            + [
                {
                    "key": "fy",
                    "label": f"FY {int(fy) - 1}/{str(fy)[-2:]}",
                    "sub": "Full Year",
                }
            ]
        )
        rows = []
        for u in supervised_users(pl_user):
            TargetAchievementService.rebuild(u, fy)
            targets = MyTargetQueryService.monthly_targets(u, fy)
            achieved = MyTargetQueryService.monthly_achievements(u, fy)
            for a in areas:
                cells = []
                for period_key, months in zip(
                    ["month", *QUARTERS, "fy"],
                    [
                        [month_of_fy],
                        *[Cal.months_of_quarter(q) for q in QUARTERS],
                        list(range(1, 13)),
                    ],
                    strict=True,
                ):
                    t = sum(targets[a.key][mm - 1] for mm in months)
                    ach = sum(achieved[a.key][mm - 1] for mm in months)
                    cells.append(
                        {
                            "key": period_key,
                            "t": t,
                            "a": ach,
                            "pct": round(ach / t * 100) if t else None,
                        }
                    )
                rows.append({"staff": u.name, "area": a.label, "cells": cells})
        return {
            "heads": heads,
            "rows": rows,
            "fy": fy,
            "month_of_fy": month_of_fy,
            "quarter": current_quarter,
            "selected_area_key": selected_area_key,
            "selected_area_label": selected_area_label,
            "invalid_area": bool(selected_area_key and not areas),
        }

    @staticmethod
    def export_rows(
        pl_user,
        fy: str | None = None,
        month_of_fy: int | None = None,
        category: str | None = None,
        district: str | None = None,
        team_member: str | None = None,
    ) -> list[list]:
        page = PLTeamTargetsService.get_page(
            pl_user,
            fy=fy,
            month_of_fy=month_of_fy,
            category=category,
            district=district,
            team_member=team_member,
        )
        fy = page["fy"]
        selected_area_keys = (
            {page["selected_category"]}
            if page["selected_category"] != "overall"
            else {area["key"] for area in page["areas"]}
        )
        areas = [area for area in page["areas"] if area["key"] in selected_area_keys]
        rows = [["Staff", "Target Area", "Period", "Target", "Valid Achieved", "%"]]
        for member in page["members"]:
            targets = member["targets"]
            achieved = member["achieved"]
            for a in areas:
                for mm in range(1, 13):
                    t, ach = targets[a["key"]][mm - 1], achieved[a["key"]][mm - 1]
                    rows.append(
                        [
                            member["name"],
                            a["label"],
                            Cal.month_label(fy, mm),
                            t,
                            ach,
                            round(ach / t * 100) if t else "",
                        ]
                    )
                for q in QUARTERS:
                    months = Cal.months_of_quarter(q)
                    t = sum(targets[a["key"]][mm - 1] for mm in months)
                    ach = sum(achieved[a["key"]][mm - 1] for mm in months)
                    rows.append(
                        [
                            member["name"],
                            a["label"],
                            q,
                            t,
                            ach,
                            round(ach / t * 100) if t else "",
                        ]
                    )
                t, ach = sum(targets[a["key"]]), sum(achieved[a["key"]])
                rows.append(
                    [
                        member["name"],
                        a["label"],
                        "FY Cumulative",
                        t,
                        ach,
                        round(ach / t * 100) if t else "",
                    ]
                )
        return rows

    # ── calendar day drill ───────────────────────────────────────────────────
    @staticmethod
    def day_detail(pl_user, day: date, fy: str):
        team = supervised_users(pl_user)
        ids = [i for u in team for i in _user_ids(u)]
        names = {}
        for u in team:
            for i in _user_ids(u):
                names[i] = u.name
        acts = (
            Activity.objects.filter(
                responsible_staff_id__in=ids,
                planned_date=day,
                deleted_at__isnull=True,
            )
            .exclude(delivery_type="partner")
            .select_related("school", "cluster")
            if ids
            else []
        )
        planned, completed, pending_sf = [], [], []
        for a in acts:
            row = {
                "staff": names.get(a.responsible_staff_id, "—"),
                "what": a.get_activity_type_display(),
                "where": a.school.name
                if a.school_id
                else (a.cluster.name if a.cluster_id else "—"),
                "status": a.status.replace("_", " ").title(),
            }
            if a.status in COMPLETED_STATUSES:
                if (a.salesforce_activity_id or "").strip():
                    completed.append(row)
                else:
                    pending_sf.append(row)
            elif a.status not in RETURNED_STATUSES:
                planned.append(row)
        return {
            "day": day,
            "planned": planned,
            "completed": completed,
            "pending_sf": pending_sf,
        }


def models_q_team(team_ids):
    """Partner activities tied to the team: monitored by, or on behalf of, a
    supervised CCEO."""
    from django.db.models import Q

    return Q(monitored_by_staff_id__in=team_ids) | Q(responsible_staff_id__in=team_ids)


class PLCatchUpPlanService:
    """Catch-up plan lifecycle (§20): approval turns the plan into real
    Planning items through the canonical activity-creation funnel, so costing
    and the weekly fund request follow automatically when dates exist."""

    AREA_ACTIVITY_TYPE = {
        "school_visits": "school_visit",
        "cluster_meetings": "cluster_meeting",
        "cluster_trainings": "cluster_training",
        "ssa_completed": "school_visit_ssa_collection",
        "mscs": None,  # MSCS recovers through submission, not scheduling
    }

    @staticmethod
    def sync_completion(plans) -> None:
        """Advance approved/scheduled plans whose recovery activities have
        actually run. CatchUpStatus defines in_progress/completed but nothing
        ever wrote them — a fully-recovered plan sat 'scheduled' forever, so
        the recovery loop never visibly closed. Derived-on-read like the rest
        of the targets stack."""
        from apps.activities.models import Activity

        for plan in plans:
            ids = list(plan.created_activity_ids or [])
            if not ids or plan.status not in ("approved", "scheduled", "in_progress"):
                continue
            statuses = list(
                Activity.objects.filter(
                    id__in=ids, deleted_at__isnull=True
                ).values_list("status", flat=True)
            )
            if not statuses:
                continue
            live = [s for s in statuses if s not in ("cancelled", "rejected")]
            if live and all(s in COMPLETED_STATUSES for s in live):
                new_status = "completed"
            elif any(s not in ("planned", "scheduled") for s in live):
                new_status = "in_progress"
            else:
                continue
            if plan.status != new_status:
                plan.status = new_status
                plan.save(update_fields=["status", "updated_at"])

    @staticmethod
    def submit(
        pl_user,
        *,
        staff_user_id,
        area_key,
        fy,
        month_of_fy,
        count,
        school_ids=None,
        planned_dates=None,
        note="",
        partner_id=None,
    ):
        area = next(
            (item for item in active_target_areas() if item.key == area_key), None
        )
        if area is None:
            raise ValueError("Unknown active target area.")
        plan = CatchUpPlan.objects.create(
            pl_user_id=pl_user.id,
            staff_user_id=staff_user_id,
            area=area,
            fy=fy,
            month_of_fy=int(month_of_fy),
            activities_proposed=int(count or 0),
            school_ids=list(school_ids or []),
            planned_dates=list(planned_dates or []),
            note=note or "",
            partner_id=partner_id or None,
            status="submitted",
        )
        PLCatchUpPlanService._notify(
            plan.staff_user_id,
            "Catch-up plan proposed",
            f"Your PL proposed a {area.label} catch-up plan for "
            f"{Cal.month_label(fy, int(month_of_fy))}.",
            plan,
        )
        return plan

    @staticmethod
    def approve(plan: CatchUpPlan, approver) -> dict:
        staff_user = User.objects.filter(id=plan.staff_user_id).first()
        sp_id = getattr(staff_user, "staff_profile_id", None) if staff_user else None
        created, errors = [], []
        activity_type = PLCatchUpPlanService.AREA_ACTIVITY_TYPE.get(plan.area.key)
        if activity_type and plan.school_ids:
            from apps.activities import services as activity_services
            from apps.schools.models import School

            dates = list(plan.planned_dates or [])
            for i, school_id in enumerate(plan.school_ids):
                sched = dates[i] if i < len(dates) and dates[i] else None
                try:
                    if sched:
                        # Dated → the canonical create+schedule funnel prices
                        # the activity (budget lines + weekly fund request).
                        result = activity_services.create(
                            {
                                "activityType": activity_type,
                                "schoolId": school_id,
                                "responsibleStaffId": sp_id or plan.staff_user_id,
                                "fy": plan.fy,
                                "scheduledDate": sched,
                                "activityPurposeText": f"Catch-up plan recovery — {plan.area.label}",
                                "purposeType": "target_recovery",
                            },
                            principal=staff_user or approver,
                        )
                        created.append(
                            result.get("id") if isinstance(result, dict) else None
                        )
                    else:
                        # Undated → the activity enters Planning; the CCEO dates
                        # it there and costing happens at scheduling time.
                        school = School.objects.filter(school_id=school_id).first()
                        a = Activity.objects.create(
                            school=school,
                            activity_type=activity_type,
                            delivery_type="staff",
                            status="planned",
                            responsible_staff_id=sp_id or plan.staff_user_id,
                            fy=plan.fy,
                            quarter=Cal.quarter_of_month(plan.month_of_fy),
                            activity_purpose_text=f"Catch-up plan recovery — {plan.area.label}",
                            purpose_type="target_recovery",
                        )
                        created.append(a.id)
                except Exception as exc:  # noqa: BLE001 — surface, never hide
                    errors.append(f"{school_id}: {exc}")
        plan.status = "scheduled" if (created and plan.planned_dates) else "approved"
        plan.approved_by = approver.id
        plan.approved_at = timezone.now()
        plan.created_activity_ids = [c for c in created if c]
        plan.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "created_activity_ids",
                "updated_at",
            ]
        )
        PLCatchUpPlanService._notify(
            plan.staff_user_id,
            "Catch-up plan approved",
            f"{len(plan.created_activity_ids)} recovery activit"
            f"{'y' if len(plan.created_activity_ids) == 1 else 'ies'} entered your Planning.",
            plan,
        )
        return {
            "created": plan.created_activity_ids,
            "status": plan.status,
            "errors": errors,
        }

    @staticmethod
    def return_plan(plan: CatchUpPlan, approver, reason: str):
        plan.status = "returned"
        plan.return_reason = (reason or "")[:512]
        plan.save(update_fields=["status", "return_reason", "updated_at"])
        PLCatchUpPlanService._notify(
            plan.staff_user_id,
            "Catch-up plan returned",
            plan.return_reason or "Returned for correction.",
            plan,
        )
        PLCatchUpPlanService._thread(plan, approver, plan.return_reason)

    @staticmethod
    def _notify(recipient_id, title, body, plan):
        from apps.notifications.models import Notification

        Notification.objects.create(
            recipient_id=recipient_id,
            title=title,
            body=body,
            category="team_targets",
            context_type="catchup_plan",
            context_id=plan.id,
            target_route="/my-targets",
            action_label="Open",
            action_required=True,
            priority="high",
        )

    @staticmethod
    def _thread(plan, author, body):
        try:
            from apps.messaging.models import Message, MessageThread

            thread, _ = MessageThread.objects.get_or_create(
                context_type="catchup_plan",
                context_id=plan.id,
                defaults={
                    "subject": (
                        f"Catch-Up Plan · {plan.area.label} · "
                        f"{Cal.month_label(plan.fy, plan.month_of_fy)}"
                    ),
                    "category": "team_targets",
                    "is_system_generated": True,
                    "created_by": author.id,
                    "participant_a_id": author.id,
                    "participant_b_id": plan.staff_user_id,
                },
            )
            if body:
                Message.objects.create(
                    thread=thread,
                    sender_id=author.id,
                    recipient_id=plan.staff_user_id,
                    body=body,
                    context_type="catchup_plan",
                    context_id=plan.id,
                )
        except Exception:  # noqa: BLE001 — messaging is supportive, never blocking
            pass
