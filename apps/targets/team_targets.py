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
from apps.ssa.models import SsaRecord

from apps.targets.fy_calendar import (
    MONTH_LABELS,
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
)

# Team pacing bands (mandate §13) — deliberately wider than My Targets bands.
TEAM_ON_TRACK_BAND = 5      # within 5pp of expected pace
TEAM_SLIGHT_BAND = 15       # 6–15pp below pace
TEAM_HIGH_RISK_BAND = 30    # 16–30pp below pace; beyond = Critical

# Activity types that require an Activity SF ID once completed (the three
# activity-backed target areas).
SF_REQUIRED_TYPES = tuple(
    t for key in ("school_visits", "cluster_meetings", "cluster_trainings")
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
            ).select_related("staff_profile").order_by("name")
        )
    sp_id = getattr(pl_user, "staff_profile_id", None)
    if not sp_id:
        return []
    supervisee_ids = list(
        StaffSupervisorAssignment.objects.filter(supervisor_id=sp_id)
        .values_list("supervisee_id", flat=True)
    )
    return list(
        User.objects.filter(
            staff_profile__id__in=supervisee_ids,
            status="active", deleted_at__isnull=True,
        ).select_related("staff_profile").order_by("name")
    )


def team_status_for(pct: int | None, pace: int, started: bool, assigned: bool) -> tuple[str, str]:
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


class PLTeamTargetsService:
    """Everything the Team Targets dashboard renders, strictly PL-scoped."""

    # ── member profile ───────────────────────────────────────────────────────
    @staticmethod
    def _member(user, areas, fy, month_of_fy, today, m_start, m_end, is_current_fy):
        TargetAchievementService.rebuild(user, fy)
        targets = MyTargetQueryService.monthly_targets(user, fy)
        achieved = MyTargetQueryService.monthly_achievements(user, fy)
        pace = Cal.expected_pace_pct(m_start, m_end, today, user) if is_current_fy else 100

        def wpct(month_list, t_map=targets, a_map=achieved):
            wsum = psum = 0
            tot_t = tot_a = 0
            for a in areas:
                t = sum(t_map[a.key][m - 1] for m in month_list)
                ach = sum(a_map[a.key][m - 1] for m in month_list)
                tot_t += t
                tot_a += ach
                if t > 0:
                    wsum += a.weight
                    psum += (ach / t * 100) * a.weight
            return (round(psum / wsum) if wsum else None), tot_a, tot_t

        m_pct, m_a, m_t = wpct([month_of_fy])
        q = Cal.quarter_of_month(month_of_fy)
        q_months = Cal.months_of_quarter(q)
        q_pct, q_a, q_t = wpct(q_months)
        started = today >= m_start
        status, tone = team_status_for(m_pct, pace, started, m_t > 0)

        per_area = []
        for a in areas:
            t = targets[a.key][month_of_fy - 1]
            ach = achieved[a.key][month_of_fy - 1]
            per_area.append({
                "key": a.key, "label": a.label, "weight": a.weight,
                "target": t, "achieved": ach,
                "pct": round(ach / t * 100) if t else None,
                "gap": max(0, t - ach),
            })

        return {
            "user": user,
            "user_id": user.id,
            "staff_id": getattr(user, "staff_profile_id", None),
            "name": user.name,
            "initials": (user.name or "??")[:2].upper(),
            "targets": targets, "achieved": achieved,
            "month_pct": m_pct, "month_achieved": m_a, "month_target": m_t,
            "remaining": max(0, m_t - m_a),
            "quarter_pct": q_pct, "quarter_achieved": q_a, "quarter_target": q_t,
            "pace": pace, "status": status, "tone": tone,
            "per_area": per_area,
        }

    # ── the full page payload ────────────────────────────────────────────────
    @staticmethod
    def get_page(pl_user, fy: str | None = None, month_of_fy: int | None = None) -> dict:
        now = Cal.current()
        fy = fy or now["fy"]
        is_current_fy = fy == now["fy"]
        month_of_fy = month_of_fy or (now["month_of_fy"] if is_current_fy else 1)
        today = now["today"]
        m_start, m_end = Cal.month_range(fy, month_of_fy)
        areas = list(TargetArea.objects.filter(active=True).order_by("sort_order"))

        team = supervised_users(pl_user)
        members = [
            PLTeamTargetsService._member(
                u, areas, fy, month_of_fy, today, m_start, m_end, is_current_fy)
            for u in team
        ]
        team_ids = [i for m in members for i in _user_ids(m["user"])]

        # School / district portfolio of the team
        staff_school = {}
        district_of_school = {}
        school_names = {}
        if members:
            from apps.schools.models import School

            assigns = StaffSchoolAssignment.objects.filter(
                staff_id__in=[m["staff_id"] for m in members if m["staff_id"]]
            )
            school_pks = {a.school_id for a in assigns}
            schools = {
                s.id: s for s in School.objects.filter(id__in=school_pks)
                .select_related("district")
            }
            for a in assigns:
                s = schools.get(a.school_id)
                if not s:
                    continue
                staff_school.setdefault(a.staff_id, []).append(s)
                school_names[s.school_id] = s.name
                if s.district_id:
                    district_of_school[s.id] = s.district

        for m in members:
            ds = {s.district.name for s in staff_school.get(m["staff_id"], []) if s.district_id}
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
            wsum = psum = 0
            tot_t = tot_a = 0
            for a in areas:
                t = sum(t_targets[a.key][mm - 1] for mm in month_list)
                ach = sum(t_achieved[a.key][mm - 1] for mm in month_list)
                tot_t += t
                tot_a += ach
                if t > 0:
                    wsum += a.weight
                    psum += (ach / t * 100) * a.weight
            return (round(psum / wsum) if wsum else 0), tot_a, tot_t

        def raw_pct(month_list):
            t = sum(sum(t_targets[a.key][mm - 1] for mm in month_list) for a in areas)
            ach = sum(sum(t_achieved[a.key][mm - 1] for mm in month_list) for a in areas)
            return (round(ach / t * 100) if t else 0), ach, t

        cur_quarter = Cal.quarter_of_month(month_of_fy)
        q_months = Cal.months_of_quarter(cur_quarter)

        team_w_pct, team_m_a, team_m_t = team_wpct([month_of_fy])
        month_pct, _, _ = raw_pct([month_of_fy])
        quarter_pct, q_a, q_t = raw_pct(q_months)

        prev_w_pct = None
        if month_of_fy > 1:
            prev_w_pct, _, _ = team_wpct([month_of_fy - 1])

        on_track = [m for m in members if m["status"] in ("On Track", "Complete", "Exceeded")]
        behind = [m for m in members if m["status"] in ("Slightly Behind", "High Risk", "Critical")]
        high_risk = [m for m in members if m["status"] in ("High Risk", "Critical")]
        critical = [m for m in members if m["status"] == "Critical"]

        # ── SF ID compliance + core schools (operational indicators) ─────────
        fy_s, fy_e = Cal.fy_range(fy)
        completed_acts = Activity.objects.filter(
            responsible_staff_id__in=team_ids, fy=fy,
            activity_type__in=SF_REQUIRED_TYPES, status__in=COMPLETED_STATUSES,
            deleted_at__isnull=True,
        ).exclude(delivery_type="partner")
        sf_required = completed_acts.count()
        sf_have = completed_acts.exclude(salesforce_activity_id__isnull=True).exclude(
            salesforce_activity_id="").count()
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
                done = (1 if plan.baseline_average is not None else 0) \
                    + min(4, plan.visits_completed or 0) + min(4, plan.trainings_completed or 0)
                pkg_pct = round(done / 9 * 100)
                ok_flag = pkg_pct >= max(0, fy_pace - 20)
                core_total += 1
                core_on_track += 1 if ok_flag else 0
                core_rows.append({
                    "school": school_names.get(plan.school_id, plan.school_id),
                    "pct": pkg_pct, "on_track": ok_flag,
                    "visits": min(4, plan.visits_completed or 0),
                    "trainings": min(4, plan.trainings_completed or 0),
                })
        except Exception:  # pragma: no cover — core module optional in some envs
            pass
        core_pct = round(core_on_track / core_total * 100) if core_total else None
        for m in members:
            sids = {s.school_id for s in m["schools"]}
            mine = [r for r in core_rows if r["school"] in
                    {school_names.get(x, x) for x in sids}]
            m["core_pct"] = round(sum(r["pct"] for r in mine) / len(mine)) if mine else None

        # ── KPI strip ────────────────────────────────────────────────────────
        kpis = [
            {"key": "team", "label": "Team Target Achievement", "value": f"{team_w_pct}%",
             "delta": (team_w_pct - prev_w_pct) if prev_w_pct is not None else None,
             "delta_unit": "pp vs last month", "drill": "matrix"},
            {"key": "monthly", "label": "Monthly Targets Achieved", "value": f"{month_pct}%",
             "delta": None, "delta_unit": f"{team_m_a} of {team_m_t} units", "drill": "matrix"},
            {"key": "quarterly", "label": "Quarterly Targets Achieved", "value": f"{quarter_pct}%",
             "delta": None, "delta_unit": f"{cur_quarter} · {q_a} of {q_t}", "drill": "matrix"},
            {"key": "on_track", "label": "Staff On Track", "value": len(on_track),
             "delta": None, "delta_unit": f"of {len(members)} staff", "drill": "staff"},
            {"key": "high_risk", "label": "High-Risk Staff", "value": len(high_risk),
             "delta": None, "delta_unit": "high risk or critical", "drill": "high_risk",
             "tone": "danger" if high_risk else "success"},
            {"key": "core", "label": "Core Schools On Track",
             "value": f"{core_pct}%" if core_pct is not None else "—",
             "delta": None,
             "delta_unit": f"{core_on_track} of {core_total} packages" if core_total else "no core plans",
             "drill": "core"},
            {"key": "sfid", "label": "Activity SF ID Compliance", "value": f"{sf_compliance}%",
             "delta": None, "delta_unit": f"{sf_missing_count} missing", "drill": "sfid",
             "tone": "danger" if sf_compliance < 90 else "success"},
        ]

        # ── What Needs Attention ─────────────────────────────────────────────
        ssa_t = t_targets["ssa_completed"][month_of_fy - 1]
        ssa_a = t_achieved["ssa_completed"][month_of_fy - 1]
        visit_t = t_targets["school_visits"][month_of_fy - 1]
        visit_a = t_achieved["school_visits"][month_of_fy - 1]

        ssa_sched = Activity.objects.filter(
            responsible_staff_id__in=team_ids, fy=fy, deleted_at__isnull=True,
            planned_date__gte=m_start, planned_date__lt=m_end,
            ssa_collection_expected=True,
        ).exclude(status__in=["cancelled", "rejected"]).count() if team_ids else 0
        ssa_pending_ia = SsaRecord.objects.filter(
            collected_by_user_id__in=team_ids, deleted_at__isnull=True,
            date_of_ssa__gte=m_start, date_of_ssa__lt=m_end,
        ).exclude(verification_status="confirmed").count() if team_ids else 0

        attention = [
            {"key": "behind", "label": "Staff Behind Target", "count": len(behind),
             "sub": f"of {len(members)} supervised staff", "action": "View Staff",
             "drill": "staff", "tone": "danger" if behind else "success"},
            {"key": "critical", "label": "Staff at Critical Risk", "count": len(critical),
             "sub": "below critical threshold", "action": "View Staff",
             "drill": "high_risk", "tone": "danger" if critical else "success"},
            {"key": "ssa_gap", "label": "SSA Target Gap", "count": max(0, ssa_t - ssa_a),
             "sub": f"{ssa_sched} scheduled · {ssa_pending_ia} awaiting IA",
             "action": "View Details", "drill": "area:ssa_completed",
             "tone": "warning" if ssa_t - ssa_a > 0 else "success"},
            {"key": "visit_gap", "label": "Valid Visit Gap", "count": max(0, visit_t - visit_a),
             "sub": f"{visit_a} valid of {visit_t} target", "action": "View Details",
             "drill": "area:school_visits",
             "tone": "warning" if visit_t - visit_a > 0 else "success"},
            {"key": "core_gap", "label": "Core School Target Gap",
             "count": core_total - core_on_track,
             "sub": f"of {core_total} core packages", "action": "View Schools",
             "drill": "core", "tone": "warning" if core_total - core_on_track else "success"},
        ]

        # ── Key target progress (5 official areas, team, month) ──────────────
        key_progress = []
        for a in areas:
            t = t_targets[a.key][month_of_fy - 1]
            ach = t_achieved[a.key][month_of_fy - 1]
            pct = round(ach / t * 100) if t else None
            pace_month = Cal.expected_pace_pct(m_start, m_end, today) if is_current_fy else 100
            status, tone = team_status_for(pct, pace_month, today >= m_start, t > 0)
            key_progress.append({
                "key": a.key, "label": a.label, "achieved": ach, "target": t,
                "pct": pct, "status": status, "tone": tone,
                "bar": min(pct or 0, 100),
            })

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
                row = by_district.setdefault(d, {"district": d, "pcts": [], "staff": 0,
                                                 "gap": 0, "schools": 0})
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
            [{**r, "pct": round(sum(r["pcts"]) / len(r["pcts"])) if r["pcts"] else 0}
             for r in by_district.values()],
            key=lambda r: r["pct"],
        )[:6]

        # ── Recovery focus (behind staff × worst areas, blocker-matched) ─────
        recovery = []
        deadline = (m_end - timedelta(days=1)).strftime("%b %d, %Y")
        wd_left = Cal.working_days(max(m_start, today), m_end) if today < m_end else 0
        for m in behind:
            worst = sorted(
                [pa for pa in m["per_area"] if pa["target"]],
                key=lambda pa: (pa["pct"] or 0),
            )[:2]
            for pa in worst:
                if pa["gap"] <= 0:
                    continue
                reason_key, reason_label = PLTeamTargetsService._blocker(
                    m["user"], pa["key"], fy, month_of_fy, pa, wd_left)
                action_label, action_kind = RECOMMENDATIONS[reason_key]
                recovery.append({
                    "staff": m["name"], "staff_user_id": m["user_id"],
                    "initials": m["initials"],
                    "district": m["district_label"],
                    "area": pa["label"], "area_key": pa["key"],
                    "gap": pa["gap"], "pct": pa["pct"] or 0,
                    "reason": reason_label,
                    "recommendation": action_label, "action_kind": action_kind,
                    "deadline": deadline,
                    "risk": m["status"], "risk_tone": m["tone"],
                })
        recovery.sort(key=lambda r: ({"Critical": 0, "High Risk": 1, "Slightly Behind": 2}
                                     .get(r["risk"], 3), -r["gap"]))

        # ── Weekly pacing ────────────────────────────────────────────────────
        pacing = PLTeamTargetsService._weekly_pacing(
            members, t_targets, t_achieved, areas, fy, month_of_fy,
            today, m_start, m_end, team_ids, is_current_fy)

        # ── Calendar ─────────────────────────────────────────────────────────
        calendar = PLTeamTargetsService._calendar(
            fy, month_of_fy, today, m_start, m_end, team_ids, is_current_fy)

        # ── Partner contribution ─────────────────────────────────────────────
        partners = PLTeamTargetsService._partner_rows(team_ids, fy)

        # ── Pending catch-up approvals ───────────────────────────────────────
        pending_catchups = CatchUpPlan.objects.filter(
            pl_user_id=pl_user.id, status="submitted"
        ).count()

        # ── Field Debrief intelligence (mandate §11) ─────────────────────────
        from apps.debriefs.rollup_service import field_debrief_intelligence_summary

        field_debrief_intel = field_debrief_intelligence_summary(pl_user)

        # ── Risk notifications (idempotent) ──────────────────────────────────
        if is_current_fy:
            PLTeamTargetsService._notify_risk(pl_user, high_risk, fy, month_of_fy)

        return {
            "fy": fy, "month_of_fy": month_of_fy,
            "month_label": Cal.month_label(fy, month_of_fy),
            "quarter": cur_quarter, "is_current_fy": is_current_fy,
            "team_size": len(members),
            "kpis": kpis,
            "attention": attention,
            "members": members,
            "key_progress": key_progress,
            "distribution": distribution,
            "districts_behind": districts_behind,
            "recovery": recovery,
            "pacing": pacing,
            "calendar": calendar,
            "partners": partners,
            "pending_catchups": pending_catchups,
            "field_debrief_intel": field_debrief_intel,
            "areas": [{"key": a.key, "label": a.label, "weight": a.weight} for a in areas],
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
            return "pending_sf", f"{len(p['pending_sf'])} completed missing Activity SF IDs"
        if p["returned"]:
            return "returned", f"{len(p['returned'])} returned item(s) need correction"
        if p["ia_pending"]:
            return "ia_pending", f"{len(p['ia_pending'])} awaiting IA verification"
        scheduled = len(p["scheduled"])
        if area_key == "mscs" and not scheduled:
            return "mscs", "No MSCS submitted this month"
        if scheduled + len(p["validated"]) < pa["target"]:
            if pa["gap"] > wd_left:
                return "workload", f"Gap of {pa['gap']} exceeds {wd_left} working days left"
            return "planning", f"Only {scheduled} scheduled toward {pa['target']}"
        if scheduled:
            return "execution", f"{scheduled} scheduled but not yet executed"
        if p["provisional"]:
            return "provisional", f"{len(p['provisional'])} awaiting review"
        return "planning", "No activity planned yet this month"

    # ── weekly pacing ────────────────────────────────────────────────────────
    @staticmethod
    def _weekly_pacing(members, t_targets, t_achieved, areas, fy, month_of_fy,
                       today, m_start, m_end, team_ids, is_current_fy):
        from apps.targets.models import TargetAchievementLedger

        anchor = min(max(today, m_start), m_end - timedelta(days=1))
        week_start = anchor - timedelta(days=anchor.weekday())  # Monday
        week_end = week_start + timedelta(days=7)
        w_start = max(week_start, m_start)
        w_end = min(week_end, m_end)

        month_target = sum(t_targets[a.key][month_of_fy - 1] for a in areas)
        month_achieved = sum(t_achieved[a.key][month_of_fy - 1] for a in areas)
        remaining = max(0, month_target - month_achieved)

        wd_left = Cal.working_days(max(m_start, today), m_end) if today < m_end else 0
        weeks_left = max(1, round(wd_left / 5) or 1)
        weekly_target = -(-remaining // weeks_left) if remaining else 0  # ceil

        rows = TargetAchievementLedger.objects.filter(
            user_id__in=[m["user_id"] for m in members], fy=fy,
            validation_status="validated",
            activity_date__gte=w_start, activity_date__lt=w_end,
        ).values_list("activity_date", flat=True) if members else []
        by_day = {}
        for d in rows:
            by_day[d] = by_day.get(d, 0) + 1
        completed_week = sum(by_day.values())

        pct = round(completed_week / weekly_target * 100) if weekly_target else 100
        if pct >= 110:
            status, tone = "Ahead", "success"
        elif pct >= 95:
            status, tone = "On Track", "success"
        elif pct >= 80:
            status, tone = "Slightly Behind", "warning"
        elif pct >= 50:
            status, tone = "Behind", "danger"
        else:
            status, tone = "Critical", "danger"
        if not weekly_target:
            status, tone = ("Complete", "success") if month_target else ("No Target", "neutral")

        days = []
        for i in range(7):
            d = week_start + timedelta(days=i)
            days.append({
                "label": d.strftime("%a"), "num": d.day,
                "in_month": m_start <= d < m_end,
                "is_today": d == today,
                "future": d > today,
                "weekend": d.weekday() >= 5,
                "done": by_day.get(d, 0),
            })

        return {
            "range_label": f"{w_start.strftime('%b %d')} – {(w_end - timedelta(days=1)).strftime('%b %d, %Y')}",
            "completed": completed_week, "target": weekly_target,
            "pct": min(pct, 100) if weekly_target else 100,
            "status": status, "tone": tone, "days": days,
        }

    # ── calendar ─────────────────────────────────────────────────────────────
    @staticmethod
    def _calendar(fy, month_of_fy, today, m_start, m_end, team_ids, is_current_fy):
        from apps.accounts.models import PublicHoliday
        from apps.targets.models import TargetAchievementLedger

        holidays = set(PublicHoliday.objects.filter(
            date__gte=m_start, date__lt=m_end).values_list("date", flat=True))
        valid_by_day = {}
        if team_ids:
            for d in TargetAchievementLedger.objects.filter(
                user_id__in=team_ids, fy=fy, validation_status="validated",
                activity_date__gte=m_start, activity_date__lt=m_end,
            ).values_list("activity_date", flat=True):
                valid_by_day[d] = valid_by_day.get(d, 0) + 1

        total_wd = Cal.working_days(m_start, m_end) or 1
        month_target_units = 0  # cumulative pace uses working-day share

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
            week.append({
                "day": d.day, "iso": d.isoformat(), "tone": tone,
                "today": d == today, "count": valid_by_day.get(d, 0),
            })
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
        qs = Activity.objects.filter(
            fy=fy, deleted_at__isnull=True, delivery_type="partner",
        ).filter(
            models_q_team(team_ids)
        ).exclude(assigned_partner_id__isnull=True).exclude(assigned_partner_id="")
        by_partner = {}
        for a in qs:
            row = by_partner.setdefault(a.assigned_partner_id, {
                "assigned": 0, "scheduled": 0, "valid": 0, "valid_visits": 0,
                "completed": 0, "sf_ok": 0, "ia_ok": 0,
            })
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
        partners_by_id = {p.id: p for p in Partner.objects.filter(id__in=by_partner.keys())}
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
            out.append({
                "partner_id": pid,
                "name": p_obj.name if p_obj else "Partner",
                "region": (p_obj.region_name or "—") if p_obj else "—",
                "assigned": r["assigned"], "scheduled": r["scheduled"],
                "valid": r["valid"], "valid_visits": r["valid_visits"],
                "pct": ach, "sf": sf, "ia": ia, "risk": risk, "tone": tone,
            })
        return sorted(out, key=lambda r: -r["assigned"])

    # ── risk notifications (idempotent per staff+month+level) ────────────────
    @staticmethod
    def _notify_risk(pl_user, high_risk_members, fy, month_of_fy):
        from apps.notifications.models import Notification

        for m in high_risk_members:
            ctx = f"{m['user_id']}:{fy}:{month_of_fy}:{m['status']}"
            if Notification.objects.filter(
                recipient_id=pl_user.id, category="team_targets",
                context_type="staff_risk", context_id=ctx[:30],
            ).exists():
                continue
            Notification.objects.create(
                recipient_id=pl_user.id, recipient_role="Program Lead",
                title=f"{m['name']} is {m['status']} on targets",
                body=(f"{m['name']} is at {m['month_pct'] or 0}% against an expected "
                      f"pace of {m['pace']}% for {Cal.month_label(fy, month_of_fy)}."),
                category="team_targets", context_type="staff_risk",
                context_id=ctx[:30], target_route="/team-targets",
                action_label="Review", action_required=True, priority="high",
            )
            Notification.objects.get_or_create(
                recipient_id=m["user_id"], category="team_targets",
                context_type="target_status", context_id=ctx[:30],
                defaults={
                    "recipient_role": "CCEO",
                    "title": f"Your targets are {m['status']}",
                    "body": "Open My Targets to see which areas need recovery this month.",
                    "target_route": "/my-targets", "action_label": "Open My Targets",
                    "action_required": True, "priority": "high",
                },
            )

    # ── detail matrix + export ───────────────────────────────────────────────
    @staticmethod
    def matrix(pl_user, fy: str | None = None):
        now = Cal.current()
        fy = fy or now["fy"]
        month_of_fy = now["month_of_fy"] if fy == now["fy"] else 1
        areas = list(TargetArea.objects.filter(active=True).order_by("sort_order"))
        heads = ([{"label": Cal.month_label(fy, month_of_fy).split()[0], "sub": "Monthly"}]
                 + [{"label": q, "sub": Cal.quarter_label(fy, q)} for q in QUARTERS]
                 + [{"label": f"FY {int(fy) - 1}/{str(fy)[-2:]}", "sub": "Full Year"}])
        rows = []
        for u in supervised_users(pl_user):
            TargetAchievementService.rebuild(u, fy)
            targets = MyTargetQueryService.monthly_targets(u, fy)
            achieved = MyTargetQueryService.monthly_achievements(u, fy)
            for a in areas:
                cells = []
                for months in ([[month_of_fy]] + [Cal.months_of_quarter(q) for q in QUARTERS]
                               + [list(range(1, 13))]):
                    t = sum(targets[a.key][mm - 1] for mm in months)
                    ach = sum(achieved[a.key][mm - 1] for mm in months)
                    cells.append({"t": t, "a": ach,
                                  "pct": round(ach / t * 100) if t else None})
                rows.append({"staff": u.name, "area": a.label, "cells": cells})
        return {"heads": heads, "rows": rows, "fy": fy}

    @staticmethod
    def export_rows(pl_user, fy: str | None = None) -> list[list]:
        now = Cal.current()
        fy = fy or now["fy"]
        areas = list(TargetArea.objects.filter(active=True).order_by("sort_order"))
        rows = [["Staff", "Target Area", "Period", "Target", "Valid Achieved", "%"]]
        for u in supervised_users(pl_user):
            TargetAchievementService.rebuild(u, fy)
            targets = MyTargetQueryService.monthly_targets(u, fy)
            achieved = MyTargetQueryService.monthly_achievements(u, fy)
            for a in areas:
                for mm in range(1, 13):
                    t, ach = targets[a.key][mm - 1], achieved[a.key][mm - 1]
                    rows.append([u.name, a.label, Cal.month_label(fy, mm), t, ach,
                                 round(ach / t * 100) if t else ""])
                for q in QUARTERS:
                    months = Cal.months_of_quarter(q)
                    t = sum(targets[a.key][mm - 1] for mm in months)
                    ach = sum(achieved[a.key][mm - 1] for mm in months)
                    rows.append([u.name, a.label, q, t, ach,
                                 round(ach / t * 100) if t else ""])
                t, ach = sum(targets[a.key]), sum(achieved[a.key])
                rows.append([u.name, a.label, "FY Cumulative", t, ach,
                             round(ach / t * 100) if t else ""])
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
        acts = Activity.objects.filter(
            responsible_staff_id__in=ids, planned_date=day,
            deleted_at__isnull=True,
        ).exclude(delivery_type="partner").select_related("school", "cluster") if ids else []
        planned, completed, pending_sf = [], [], []
        for a in acts:
            row = {
                "staff": names.get(a.responsible_staff_id, "—"),
                "what": a.get_activity_type_display(),
                "where": a.school.name if a.school_id else (a.cluster.name if a.cluster_id else "—"),
                "status": a.status.replace("_", " ").title(),
            }
            if a.status in COMPLETED_STATUSES:
                if (a.salesforce_activity_id or "").strip():
                    completed.append(row)
                else:
                    pending_sf.append(row)
            elif a.status not in RETURNED_STATUSES:
                planned.append(row)
        return {"day": day, "planned": planned, "completed": completed,
                "pending_sf": pending_sf}


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
    def submit(pl_user, *, staff_user_id, area_key, fy, month_of_fy, count,
               school_ids=None, planned_dates=None, note="", partner_id=None):
        area = TargetArea.objects.get(key=area_key, active=True)
        plan = CatchUpPlan.objects.create(
            pl_user_id=pl_user.id, staff_user_id=staff_user_id, area=area,
            fy=fy, month_of_fy=int(month_of_fy), activities_proposed=int(count or 0),
            school_ids=list(school_ids or []), planned_dates=list(planned_dates or []),
            note=note or "", partner_id=partner_id or None, status="submitted",
        )
        PLCatchUpPlanService._notify(
            plan.staff_user_id, "Catch-up plan proposed",
            f"Your PL proposed a {area.label} catch-up plan for "
            f"{Cal.month_label(fy, int(month_of_fy))}.", plan)
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
                        result = activity_services.create({
                            "activityType": activity_type,
                            "schoolId": school_id,
                            "responsibleStaffId": sp_id or plan.staff_user_id,
                            "fy": plan.fy,
                            "scheduledDate": sched,
                            "activityPurposeText": f"Catch-up plan recovery — {plan.area.label}",
                            "purposeType": "target_recovery",
                        }, principal=staff_user or approver)
                        created.append(result.get("id") if isinstance(result, dict) else None)
                    else:
                        # Undated → the activity enters Planning; the CCEO dates
                        # it there and costing happens at scheduling time.
                        school = School.objects.filter(school_id=school_id).first()
                        a = Activity.objects.create(
                            school=school, activity_type=activity_type,
                            delivery_type="staff", status="planned",
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
        plan.save(update_fields=["status", "approved_by", "approved_at",
                                 "created_activity_ids", "updated_at"])
        PLCatchUpPlanService._notify(
            plan.staff_user_id, "Catch-up plan approved",
            f"{len(plan.created_activity_ids)} recovery activit"
            f"{'y' if len(plan.created_activity_ids) == 1 else 'ies'} entered your Planning.",
            plan)
        return {"created": plan.created_activity_ids, "status": plan.status,
                "errors": errors}

    @staticmethod
    def return_plan(plan: CatchUpPlan, approver, reason: str):
        plan.status = "returned"
        plan.return_reason = (reason or "")[:512]
        plan.save(update_fields=["status", "return_reason", "updated_at"])
        PLCatchUpPlanService._notify(
            plan.staff_user_id, "Catch-up plan returned",
            plan.return_reason or "Returned for correction.", plan)
        PLCatchUpPlanService._thread(plan, approver, plan.return_reason)

    @staticmethod
    def _notify(recipient_id, title, body, plan):
        from apps.notifications.models import Notification

        Notification.objects.create(
            recipient_id=recipient_id, title=title, body=body,
            category="team_targets", context_type="catchup_plan",
            context_id=plan.id, target_route="/my-targets",
            action_label="Open", action_required=True, priority="high",
        )

    @staticmethod
    def _thread(plan, author, body):
        try:
            from apps.messaging.models import Message, MessageThread

            thread, _ = MessageThread.objects.get_or_create(
                context_type="catchup_plan", context_id=plan.id,
                defaults={
                    "subject": (f"Catch-Up Plan · {plan.area.label} · "
                                f"{Cal.month_label(plan.fy, plan.month_of_fy)}"),
                    "category": "team_targets", "is_system_generated": True,
                    "created_by": author.id,
                    "participant_a_id": author.id,
                    "participant_b_id": plan.staff_user_id,
                },
            )
            if body:
                Message.objects.create(
                    thread=thread, sender_id=author.id,
                    recipient_id=plan.staff_user_id, body=body,
                    context_type="catchup_plan", context_id=plan.id,
                )
        except Exception:  # noqa: BLE001 — messaging is supportive, never blocking
            pass
