"""Program Lead Command Dashboard — the PL's team operating cockpit.

Strictly scoped to the PL's supervised team (never country-wide, never another
PL's portfolio). Reuses PLAnalyticsService for the overlapping analytics
(CCEO performance, risk list, SSA, team performance, cluster matrix) and adds
the command-center sections: leadership attention, PL personal targets,
approval queue, backlog snapshot, route/capacity, funding & execution.

Every dataset is a real backend query. Personal targets (the PL's own work)
are computed separately from the supervised-team target progress — the two are
never mixed. The PL never sees accountant-only disbursement controls, and the
approval queue never contains the PL's own fund requests (those go to the CD).
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffTargetProfile, User
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

from apps.analytics.pl_analytics_service import (
    CLUSTER_MEETING_TYPES,
    COMPLETED_STATUSES,
    PARTNER_TYPES,
    SSA_COLLECTION_TYPES,
    SSA_INTERVENTIONS,
    TRAINING_TYPES,
    VERIFIED_STATUSES,
    VISIT_TYPES,
    PLAnalyticsService,
    _INTERVENTION_LABELS,
    _norm,
    _pct,
    resolve_pl_scope,
    ssa_band,
)

# A CCEO's healthy workload ceiling (schools + activities). Above this → overload.
CCEO_SCHOOL_CAPACITY = 50
CCEO_WEEKLY_ACTIVITY_CAPACITY = 12
SF_ID_OVERDUE_DAYS = 7


def _ugx_compact(v) -> str:
    v = v or 0
    if v >= 1_000_000_000:
        return f"UGX {v / 1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"UGX {v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"UGX {v / 1_000:.0f}K"
    return f"UGX {int(v)}"


def _requires_sf_id(qs):
    """Completed visits/trainings require an Activity SF ID (program evidence)."""
    return qs.filter(status__in=COMPLETED_STATUSES, activity_type__in=VISIT_TYPES + TRAINING_TYPES)


class ProgramLeadDashboardService:
    """Single entry point for the PL Command Dashboard. Every method takes
    (user, fy, month, filters) and enforces the supervised-team scope."""

    @staticmethod
    def get_dashboard(user, fy=None, month=None, filters=None) -> dict:
        fy = fy or get_operational_fy()
        filters = dict(filters or {})
        pls = resolve_pl_scope(user, filters)
        acts = ProgramLeadDashboardService._team_acts(pls, fy, filters)

        return {
            "fy": fy,
            "month": month,
            "filters": filters,
            "kpi_strip_items": ProgramLeadDashboardService.kpis(user, pls, fy, filters, acts),
            "leadership_attention": ProgramLeadDashboardService.leadership_attention(pls, fy, filters, acts),
            "team_performance": ProgramLeadDashboardService.team_performance(pls, fy, filters),
            "personal_targets": ProgramLeadDashboardService.personal_targets(user, pls, fy),
            "cceo_performance": ProgramLeadDashboardService.cceo_performance(pls, fy, filters, acts),
            "approval_queue": ProgramLeadDashboardService.approval_queue(user, pls, fy),
            "backlog_snapshot": ProgramLeadDashboardService.backlog_snapshot(pls, fy, filters, acts),
            "ssa_matrix": ProgramLeadDashboardService.ssa_cluster_matrix(pls, fy),
            "urgent_schools": PLAnalyticsService.risk_list(pls, fy, None, filters, limit=8)["rows"],
            "route_capacity": ProgramLeadDashboardService.route_capacity(pls, fy, filters, acts),
            "funding_execution": ProgramLeadDashboardService.funding_execution(pls, fy),
            "quick_actions": ProgramLeadDashboardService.quick_actions(user, pls, fy),
            "scope_meta": {
                "cceo_count": len(pls.cceos),
                "school_count": School.objects.filter(id__in=pls.school_ids).count(),
            },
        }

    # ── shared scoped querysets ──────────────────────────────────────────────
    @staticmethod
    def _team_acts(pls, fy, filters):
        """Supervised-team activities for the FY (own CCEOs' work + portfolio
        schools). PL-owned activities are added via responsible_ids too."""
        base = Activity.objects.filter(fy=fy, deleted_at__isnull=True)
        pl_id = getattr(pls.user, "staff_profile_id", None)
        ids = set(pls.responsible_ids)
        if pl_id:
            ids.add(pl_id)
        ids.add(pls.user.id)
        if pls.school_filtered:
            base = base.filter(school_id__in=pls.school_ids)
        else:
            base = base.filter(Q(responsible_staff_id__in=ids) | Q(school_id__in=pls.school_ids))
        atype = (filters.get("activity_type") or "").strip()
        if atype:
            base = base.filter(activity_type=atype)
        return base

    @staticmethod
    def _cceo_ids(cceo):
        ids = {cceo["staff_id"]}
        if cceo["user_id"]:
            ids.add(cceo["user_id"])
        return ids

    # ── 1. KPI strip (8) ─────────────────────────────────────────────────────
    @staticmethod
    def kpis(user, pls, fy, filters, acts) -> list[dict]:
        team_pct, on_track = PLAnalyticsService._team_target(pls, fy, None, filters)
        cceo_n = len(pls.cceos) or 1
        cceos_on_track_pct = round(on_track / cceo_n * 100)

        plans_awaiting = ProgramLeadDashboardService._count_awaiting(user, pls, fy)

        today = date.today()
        wk_start = today - timedelta(days=today.weekday())
        wk_end = wk_start + timedelta(days=6)
        activities_week = acts.filter(
            scheduled_date__date__gte=wk_start, scheduled_date__date__lte=wk_end
        ).count()

        req_sf = _requires_sf_id(acts)
        req_total = req_sf.count()
        with_sf = req_sf.exclude(salesforce_activity_id__isnull=True).exclude(salesforce_activity_id="").count()
        sf_compliance = _pct(with_sf, req_total)

        backlog = ProgramLeadDashboardService._team_backlog_total(pls, fy, acts)
        fund_total = ProgramLeadDashboardService._monthly_fund_total(pls, fy)
        fund_util = PLAnalyticsService._budget_utilization(pls, fy)
        high_risk = ProgramLeadDashboardService._high_risk_count(pls, fy, acts)

        def card(icon, label, value, variant, helper, link=""):
            return {"icon": icon, "label": label, "value": value, "variant": variant,
                    "helper": helper, "trend": {"direction": "neutral", "value": ""}, "link": link}

        return [
            card("target", "Team Target Progress", f"{team_pct}%", "success", "vs annual team target", "?drill=team_target"),
            card("users", "CCEOs On Track", f"{cceos_on_track_pct}%", "info", f"{on_track}/{len(pls.cceos)} at pace", "?drill=cceos"),
            card("report", "Plans Awaiting Approval", f"{plans_awaiting}", "warning" if plans_awaiting else "success", "need your action", "?drill=approvals"),
            card("calendar", "Activities This Week", f"{activities_week:,}", "info", "scheduled team work", "?drill=week"),
            card("shield", "Activity SF ID Compliance", f"{sf_compliance}%", "success" if sf_compliance >= 80 else "warning", "program evidence entered", "?drill=sf_backlog"),
            card("clock", "Team Backlog", f"{backlog}", "warning" if backlog else "success", "overdue / returned / missing", "?drill=backlog"),
            card("currency", "Monthly Fund Request", _ugx_compact(fund_total), "finance", f"{fund_util}% utilized", "?drill=funding"),
            card("warning", "High-Risk Schools", f"{high_risk}", "danger" if high_risk else "success", "urgent attention", "?drill=high_risk"),
        ]

    @staticmethod
    def _count_awaiting(user, pls, fy):
        from apps.fund_requests.models import FundRequest, WeeklyFundRequest

        cceo_user_ids = [c["user_id"] for c in pls.cceos if c["user_id"]]
        wfr = WeeklyFundRequest.objects.filter(status="submitted_to_pl", responsible_user__in=cceo_user_ids).count()
        monthly = FundRequest.objects.filter(status="submitted_to_pl", period="monthly", submitted_by_user_id__in=cceo_user_ids).count()
        plans = ProgramLeadDashboardService._team_acts(pls, fy, {}).filter(status="submitted_to_pl").count()
        return wfr + monthly + plans

    @staticmethod
    def _team_backlog_total(pls, fy, acts):
        overdue = acts.filter(
            planned_date__lt=date.today(),
            status__in=["scheduled", "in_progress", "completion_started", "rescheduled"],
        ).count()
        returned = acts.filter(status__in=["returned_by_pl", "returned_by_ia"]).count()
        missing_ev = acts.filter(status__in=COMPLETED_STATUSES, activity_type__in=VISIT_TYPES + TRAINING_TYPES).exclude(evidence_status="accepted").count()
        missing_sf = _requires_sf_id(acts).filter(Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id="")).count()
        partner_pending = acts.filter(delivery_type="partner", status__in=["assigned_to_partner"]).count()
        return overdue + returned + missing_ev + missing_sf + partner_pending

    @staticmethod
    def _monthly_fund_total(pls, fy):
        from apps.fund_requests.models import WeeklyFundRequest

        cceo_user_ids = [c["user_id"] for c in pls.cceos if c["user_id"]]
        if not cceo_user_ids:
            return 0
        return int(
            WeeklyFundRequest.objects.filter(fy=fy, responsible_user__in=cceo_user_ids)
            .aggregate(s=Sum("total_amount"))["s"] or 0
        )

    @staticmethod
    def _high_risk_count(pls, fy, acts):
        """Schools with low verified SSA (<5) OR no SSA + no visit this period."""
        latest_fy, _ = PLAnalyticsService._cycle_fys(pls, fy)
        low_ssa = set()
        if latest_fy:
            low_ssa = set(
                SsaRecord.objects.filter(
                    school_id__in=pls.school_ids, verification_status="confirmed",
                    fy=latest_fy, average_score__lt=5.0,
                ).values_list("school_id", flat=True)
            )
        visited = set(
            acts.filter(status__in=COMPLETED_STATUSES, activity_type__in=VISIT_TYPES)
            .exclude(school_id__isnull=True).values_list("school_id", flat=True)
        )
        no_ssa_no_visit = set(
            School.objects.filter(id__in=pls.school_ids).exclude(current_fy_ssa_status="done")
            .exclude(id__in=visited).values_list("id", flat=True)
        )
        return len(low_ssa | no_ssa_no_visit)

    # ── 2. Leadership attention (3) ──────────────────────────────────────────
    @staticmethod
    def leadership_attention(pls, fy, filters, acts) -> list[dict]:
        overloaded = ProgramLeadDashboardService._overloaded_cceos(pls, fy, acts)
        sf_overdue = ProgramLeadDashboardService._sf_overdue_count(acts)
        high_risk = ProgramLeadDashboardService._high_risk_count(pls, fy, acts)
        cards = []

        # Staff Overload — always show (danger if overloaded, success if clear)
        if overloaded:
            cards.append({
                "tone": "danger", "icon": "users", "title": "Staff Overload Warning",
                "line1": f"{len(overloaded)} staff have >120% workload capacity.",
                "line2": "Action required to rebalance routes.",
                "action": "View Overloaded Staff", "link": "?drill=overload",
            })
        else:
            cards.append({
                "tone": "success", "icon": "users", "title": "Staff Capacity Healthy",
                "line1": "All staff are within healthy workload limits.",
                "line2": "No rebalancing needed at this time.",
                "action": "View Team Capacity", "link": "?drill=overload",
            })

        # SF ID Backlog — always show (warning if overdue, success if clear)
        if sf_overdue:
            cards.append({
                "tone": "warning", "icon": "database", "title": "Activity SF ID Backlog Warning",
                "line1": f"{sf_overdue} Activity SF IDs pending action > {SF_ID_OVERDUE_DAYS} days.",
                "line2": "Compliance risk increasing.",
                "action": "Review Backlog", "link": "?drill=sf_backlog",
            })
        else:
            cards.append({
                "tone": "success", "icon": "database", "title": "SF ID Compliance On Track",
                "line1": "No overdue Activity SF IDs.",
                "line2": "Program evidence compliance is healthy.",
                "action": "View SF Status", "link": "?drill=sf_backlog",
            })

        # High-Risk Schools — always show (danger if at risk, success if clear)
        if high_risk:
            cards.append({
                "tone": "danger", "icon": "warning", "title": "High-Risk Schools / Regions",
                "line1": f"{high_risk} schools in your portfolio flagged as high risk.",
                "line2": "Immediate follow-up needed.",
                "action": "View High-Risk Schools", "link": "?drill=high_risk",
            })
        else:
            cards.append({
                "tone": "success", "icon": "warning", "title": "No High-Risk Schools",
                "line1": "All schools in your portfolio are in good standing.",
                "line2": "No urgent follow-up needed.",
                "action": "View Portfolio", "link": "?drill=high_risk",
            })

        return cards

    @staticmethod
    def _overloaded_cceos(pls, fy, acts):
        today = date.today()
        wk_start = today - timedelta(days=today.weekday())
        out = []
        for c in pls.cceos:
            n_schools = len(c["school_ids"])
            wk = acts.filter(
                Q(responsible_staff_id__in=ProgramLeadDashboardService._cceo_ids(c)),
                scheduled_date__date__gte=wk_start,
                scheduled_date__date__lte=wk_start + timedelta(days=6),
            ).count()
            if n_schools > CCEO_SCHOOL_CAPACITY or wk > CCEO_WEEKLY_ACTIVITY_CAPACITY:
                out.append({"name": c["name"], "schools": n_schools, "week_load": wk})
        return out

    @staticmethod
    def _sf_overdue_count(acts):
        cutoff = timezone.now() - timedelta(days=SF_ID_OVERDUE_DAYS)
        return _requires_sf_id(acts).filter(
            Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id=""),
            updated_at__lt=cutoff,
        ).count()

    # ── 3. Team performance (+ verified series) ──────────────────────────────
    @staticmethod
    def team_performance(pls, fy, filters) -> dict:
        base = PLAnalyticsService.team_performance(pls, fy, None, filters)
        # Add a verified series aligned to the same 12 FY months.
        from apps.core.fy import get_month_date_range

        acts = ProgramLeadDashboardService._team_acts(pls, fy, filters)
        verified = []
        for m in range(1, 13):
            start, end = get_month_date_range(fy, m)
            verified.append(
                acts.filter(
                    planned_date__gte=start.date(), planned_date__lt=end.date(),
                    status__in=VERIFIED_STATUSES,
                ).count()
            )
        base["verified"] = verified
        return base

    # ── 4. PL personal targets (separate from team) ──────────────────────────
    @staticmethod
    def personal_targets(user, pls, fy) -> dict:
        pl_id = getattr(user, "staff_profile_id", None)
        pl_ids = {user.id}
        if pl_id:
            pl_ids.add(pl_id)
        own = Activity.objects.filter(responsible_staff_id__in=pl_ids, fy=fy, deleted_at__isnull=True)

        # Supervision Visits — PL's own completed visits vs their StaffTargetProfile.
        tp = StaffTargetProfile.objects.filter(staff_id=pl_id, fy=fy).first() if pl_id else None
        sv_target = (tp.visits_target if tp else 0) or 0
        sv_done = own.filter(activity_type__in=VISIT_TYPES, status__in=COMPLETED_STATUSES).count()

        # Plan Approvals — CCEO monthly plans acted on vs submitted to this PL.
        from apps.fund_requests.models import FundRequest, WeeklyFundRequest

        cceo_uids = [c["user_id"] for c in pls.cceos if c["user_id"]]
        monthly = FundRequest.objects.filter(period="monthly", fy=fy, submitted_by_user_id__in=cceo_uids)
        pa_target = monthly.filter(status__in=["submitted_to_pl", "sent_to_accountant", "returned_by_pl", "disbursed"]).count()
        pa_done = monthly.filter(status__in=["sent_to_accountant", "returned_by_pl", "disbursed"]).count()

        # Team Reviews — CCEO activity submissions the PL reviewed.
        team_acts = ProgramLeadDashboardService._team_acts(pls, fy, {})
        tr_target = team_acts.filter(
            Q(status="submitted_to_pl") | Q(pl_reviewed_at__isnull=False)
        ).count()
        tr_done = team_acts.filter(pl_reviewed_at__isnull=False).count()

        # Fund Requests Reviewed — weekly requests acted on vs submitted to PL.
        weekly = WeeklyFundRequest.objects.filter(fy=fy, responsible_user__in=cceo_uids)
        fr_target = weekly.filter(status__in=["submitted_to_pl", "confirmed_for_advance", "returned_by_pl", "disbursed", "accounted"]).count()
        fr_done = weekly.filter(status__in=["confirmed_for_advance", "returned_by_pl", "disbursed", "accounted"]).count()

        def tcard(label, icon, done, target):
            return {"label": label, "icon": icon, "done": done, "target": target,
                    "pct": _pct(done, target) if target else 0, "has_target": target > 0}

        cards = [
            tcard("Supervision Visits", "users", sv_done, sv_target),
            tcard("Plan Approvals", "report", pa_done, pa_target),
            tcard("Team Reviews", "users", tr_done, tr_target),
            tcard("Fund Requests Reviewed", "currency", fr_done, fr_target),
        ]
        tot_done = sum(c["done"] for c in cards)
        tot_target = sum(c["target"] for c in cards)
        return {"cards": cards, "overall_pct": _pct(tot_done, tot_target) if tot_target else 0,
                "has_target": tot_target > 0}

    # ── 5. CCEO performance (extended) ───────────────────────────────────────
    @staticmethod
    def cceo_performance(pls, fy, filters, acts) -> dict:
        base = PLAnalyticsService.cceo_performance(pls, fy, None, filters)["rows"]
        by_id = {c["staff_id"]: c for c in pls.cceos}
        district_names = ProgramLeadDashboardService._cceo_regions(pls)
        rows = []
        for r in base:
            c = by_id.get(r["staff_id"])
            ids = ProgramLeadDashboardService._cceo_ids(c) if c else {r["staff_id"]}
            c_acts = acts.filter(Q(responsible_staff_id__in=ids) | Q(school_id__in=(c["school_ids"] if c else [])))
            planned = c_acts.count()
            verified = c_acts.filter(status__in=VERIFIED_STATUSES).count()
            sf_pending = _requires_sf_id(c_acts).filter(Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id="")).count()
            route = ProgramLeadDashboardService._route_quality(c, acts) if c else ("—", "neutral")
            rows.append({
                **r,
                "region": district_names.get(r["staff_id"], "—"),
                "planned": planned, "verified": verified,
                "verified_pct": _pct(verified, planned),
                "sf_pending": sf_pending,
                "route_quality": route[0], "route_tone": route[1],
            })
        return {"rows": rows}

    @staticmethod
    def _cceo_regions(pls):
        """Most common district name across each CCEO's schools."""
        out = {}
        for c in pls.cceos:
            if not c["school_ids"]:
                out[c["staff_id"]] = "—"
                continue
            row = (
                School.objects.filter(id__in=c["school_ids"]).exclude(district__isnull=True)
                .values("district__name").annotate(n=Count("id")).order_by("-n").first()
            )
            out[c["staff_id"]] = row["district__name"] if row else "—"
        return out

    @staticmethod
    def _route_quality(cceo, acts):
        """Real proxy: share of the CCEO's completed visits that landed on/near
        their planned date (on-time within 2 days) → Good / Average / Poor."""
        c_acts = acts.filter(
            responsible_staff_id__in=ProgramLeadDashboardService._cceo_ids(cceo),
            activity_type__in=VISIT_TYPES, status__in=COMPLETED_STATUSES,
        )
        if not c_acts.exists():
            return ("—", "neutral")
        ratio = ProgramLeadDashboardService._on_time_ratio(c_acts)
        if ratio >= 85:
            return ("Good", "success")
        if ratio >= 65:
            return ("Average", "warning")
        return ("Poor", "danger")

    @staticmethod
    def _on_time_ratio(c_acts):
        rows = list(c_acts.values_list("planned_date", "scheduled_date"))
        if not rows:
            return 0
        on_time = sum(
            1 for pd, sd in rows
            if pd and sd and abs((sd.date() - pd).days) <= 2
        )
        return round(on_time / len(rows) * 100)

    # ── 6. Approval queue ────────────────────────────────────────────────────
    @staticmethod
    def approval_queue(user, pls, fy) -> dict:
        from apps.fund_requests.models import WeeklyFundRequest

        cceo_uids = [c["user_id"] for c in pls.cceos if c["user_id"]]
        name_by_uid = {c["user_id"]: c["name"] for c in pls.cceos}
        rows = []
        # Weekly fund requests awaiting this PL.
        for w in WeeklyFundRequest.objects.filter(status="submitted_to_pl", responsible_user__in=cceo_uids).order_by("week_start_date")[:15]:
            issues = "—"
            rows.append({
                "kind": "weekly_fund", "id": w.id,
                "staff": name_by_uid.get(w.responsible_user, "CCEO"),
                "covered": f"Week {w.week_start_date:%b %d}",
                "issues": issues, "submitted": w.confirmed_at or w.updated_at,
                "amount": w.total_amount,
            })
        # CCEO activity submissions awaiting PL review.
        acts = ProgramLeadDashboardService._team_acts(pls, fy, {}).filter(status="submitted_to_pl")
        act_uids = [a.responsible_staff_id for a in acts]
        sp_names = dict(
            StaffProfile.objects.filter(id__in=act_uids).select_related("user").values_list("id", "user__name")
        )
        by_owner = {}
        for a in acts.select_related("school")[:60]:
            owner = a.responsible_staff_id
            by_owner.setdefault(owner, []).append(a)
        for owner, items in list(by_owner.items())[:15]:
            missing = ProgramLeadDashboardService._plan_issues(items)
            rows.append({
                "kind": "plan", "id": owner,
                "staff": sp_names.get(owner) or name_by_uid.get(owner, "CCEO"),
                "covered": f"{len(items)} Activities",
                "issues": missing, "submitted": max((i.updated_at for i in items), default=None),
                "amount": None,
            })
        rows.sort(key=lambda r: r["submitted"] or timezone.now(), reverse=False)
        return {"rows": rows[:12], "total": len(rows)}

    @staticmethod
    def _plan_issues(items):
        missing_sf = sum(1 for a in items if a.activity_type in VISIT_TYPES + TRAINING_TYPES and not a.salesforce_activity_id)
        missing_ev = sum(1 for a in items if a.evidence_status != "accepted")
        parts = []
        if missing_ev:
            parts.append(f"{missing_ev} Missing Fields")
        if missing_sf:
            parts.append("SF IDs Missing")
        return " · ".join(parts) if parts else "Ready"

    # ── 7. Backlog snapshot (6) ──────────────────────────────────────────────
    @staticmethod
    def backlog_snapshot(pls, fy, filters, acts) -> list[dict]:
        team_pct, on_track = PLAnalyticsService._team_target(pls, fy, None, filters)
        below = len(pls.cceos) - on_track
        sf_overdue = ProgramLeadDashboardService._sf_overdue_count(acts)
        funded_not_completed = ProgramLeadDashboardService._funded_not_completed(pls, fy)

        completed = acts.filter(status__in=COMPLETED_STATUSES)
        visited = set(completed.filter(activity_type__in=VISIT_TYPES).exclude(school_id__isnull=True).values_list("school_id", flat=True))
        trained = set(completed.filter(activity_type__in=TRAINING_TYPES).exclude(school_id__isnull=True).values_list("school_id", flat=True))
        all_ids = set(School.objects.filter(id__in=pls.school_ids).values_list("id", flat=True))
        no_visit = len(all_ids - visited)
        no_training = len(all_ids - trained)
        neither = len(all_ids - visited - trained)

        def card(label, value, icon, tone, link):
            return {"label": label, "value": value, "icon": icon, "tone": tone, "link": link}

        return [
            card("Teams Below Target", below, "users", "danger" if below else "success", "?drill=cceos"),
            card("Overdue Activity SF IDs", sf_overdue, "database", "warning" if sf_overdue else "success", "?drill=sf_backlog"),
            card("Funded Not Completed", funded_not_completed, "cloud", "warning" if funded_not_completed else "success", "?drill=funded_not_completed"),
            card("Schools with No Visit", no_visit, "users", "warning" if no_visit else "success", "?drill=no_visit"),
            card("Schools with No Training", no_training, "book", "warning" if no_training else "success", "?drill=no_training"),
            card("Schools w/ Neither Training Nor Visit", neither, "clock", "danger" if neither else "success", "?drill=neither"),
        ]

    @staticmethod
    def _funded_not_completed(pls, fy):
        """Activities whose advance was disbursed but the activity isn't done."""
        return (
            ProgramLeadDashboardService._team_acts(pls, fy, {})
            .filter(advance_requests__status__in=["disbursed", "accountability_pending"])
            .exclude(status__in=COMPLETED_STATUSES)
            .distinct()
            .count()
        )

    # ── 8. SSA cluster × intervention matrix ─────────────────────────────────
    @staticmethod
    def ssa_cluster_matrix(pls, fy) -> dict:
        latest_fy, _ = PLAnalyticsService._cycle_fys(pls, fy)
        schools = School.objects.filter(id__in=pls.school_ids)
        cluster_ids = list(
            schools.exclude(cluster_id__isnull=True).exclude(cluster_id="")
            .order_by("cluster_id").values_list("cluster_id", flat=True).distinct()
        )
        from apps.clusters.models import Cluster

        names = dict(Cluster.objects.filter(id__in=cluster_ids).values_list("id", "name"))
        # Show the 6 headline interventions as columns (drawer shows all 8).
        cols = SSA_INTERVENTIONS[:6]
        rows = []
        if not latest_fy:
            return {"rows": [], "columns": [c[1] for c in cols], "codes": [c[2] for c in cols]}
        for cid in cluster_ids:
            c_school_ids = list(schools.filter(cluster_id=cid).values_list("id", flat=True))
            record_ids = list(
                SsaRecord.objects.filter(school_id__in=c_school_ids, verification_status="confirmed", fy=latest_fy)
                .values_list("id", flat=True)
            )
            by_int = {
                r["intervention"]: r["a"]
                for r in SsaScore.objects.filter(ssa_record_id__in=record_ids).values("intervention").annotate(a=Avg("score"))
            }
            cells = []
            for v, label, code in cols:
                pct = _norm(by_int.get(v))
                band = ssa_band(pct)
                cells.append({"pct": pct, "tone": band[2]})
            overall = _norm(
                SsaRecord.objects.filter(id__in=record_ids).aggregate(a=Avg("average_score"))["a"]
            )
            oband = ssa_band(overall)
            rows.append({
                "id": cid, "name": names.get(cid, "Cluster"), "cells": cells,
                "overall": overall, "overall_tone": oband[2],
            })
        return {"rows": rows, "columns": [c[1] for c in cols], "codes": [c[2] for c in cols]}

    # ── 9. Route & capacity ──────────────────────────────────────────────────
    @staticmethod
    def route_capacity(pls, fy, filters, acts) -> dict:
        """Route quality is calculated from PLANNED schools — the Route
        Intelligence batches built per staff + visit day — not from all
        assigned schools. Falls back to the historical on-time proxy only
        while the team has no route batches yet."""
        from apps.routes.engine import RouteIntelligenceService

        overloaded = ProgramLeadDashboardService._overloaded_cceos(pls, fy, acts)

        team_uids = [c["user_id"] for c in pls.cceos if c["user_id"]]
        summary = RouteIntelligenceService.team_summary(team_uids)

        _STATUS_LABELS = {
            "excellent": ("Excellent", "success"), "good": ("Good", "success"),
            "risky": ("Risky", "warning"), "not_feasible": ("Not Feasible", "danger"),
            "blocked": ("Blocked", "danger"),
        }
        table = []
        ratios = []
        if summary["has_batches"]:
            by_user: dict[str, list] = {}
            for b in summary["batches"]:
                by_user.setdefault(b.responsible_user, []).append(b)
            for c in pls.cceos:
                batches = by_user.get(c["user_id"], [])
                if not batches:
                    continue
                avg_score = round(sum(b.quality_score for b in batches) / len(batches))
                latest = max(batches, key=lambda b: b.visit_date)
                label, tone = _STATUS_LABELS.get(latest.status, ("—", "neutral"))
                feasible_days = sum(1 for b in batches if b.feasible)
                table.append({
                    "name": c["name"], "route_quality": label, "route_tone": tone,
                    "on_time": f"{avg_score}", "efficiency": f"{_pct(feasible_days, len(batches))}%",
                })
            team_route = summary["avg_score"] or 0
            source = "route_batches"
        else:
            # Historical proxy (completed visits within 2 days of plan) — only
            # until the team plans its first route-batched visit day.
            for c in pls.cceos:
                c_visits = acts.filter(
                    responsible_staff_id__in=ProgramLeadDashboardService._cceo_ids(c),
                    activity_type__in=VISIT_TYPES, status__in=COMPLETED_STATUSES,
                )
                planned_visits = acts.filter(
                    responsible_staff_id__in=ProgramLeadDashboardService._cceo_ids(c),
                    activity_type__in=VISIT_TYPES,
                ).count()
                if not planned_visits:
                    continue
                ratio = ProgramLeadDashboardService._on_time_ratio(c_visits)
                ratios.append(ratio)
                if ratio >= 85:
                    label, tone = "Good", "success"
                elif ratio >= 65:
                    label, tone = "Average", "warning"
                else:
                    label, tone = "Poor", "danger"
                table.append({
                    "name": c["name"], "route_quality": label, "route_tone": tone,
                    "on_time": f"{ratio}%",
                    "efficiency": f"{_pct(c_visits.count(), planned_visits)}%",
                })
            team_route = round(sum(ratios) / len(ratios)) if ratios else 0
            source = "on_time_proxy"

        leave_conflicts = ProgramLeadDashboardService._leave_conflicts(pls, acts)
        effs = [int(t["efficiency"].rstrip("%")) for t in table if t["efficiency"].endswith("%")]
        travel_eff = round(sum(effs) / len(effs)) if effs else 0
        return {
            "route_quality": team_route,
            "route_tone": "success" if team_route >= 75 else ("warning" if team_route >= 50 else "danger"),
            "source": source,
            "planned_days": len(summary["batches"]) if summary["has_batches"] else 0,
            "status_counts": summary.get("counts", {}),
            "overloaded": len(overloaded),
            "leave_conflicts": leave_conflicts,
            "travel_efficiency": travel_eff,
            "table": table[:6],
        }

    @staticmethod
    def _leave_conflicts(pls, acts):
        """Approved/pending CCEO leave in the next 7 days that actually clashes
        with scheduled activities inside the leave window — leave with no
        scheduled work is time off, not a conflict."""
        from apps.accounts.models import Leave

        cceo_sp_ids = [c["staff_id"] for c in pls.cceos]
        today = date.today()
        wk_end = (today + timedelta(days=7)).isoformat()
        leaves = Leave.objects.filter(
            staff_id__in=cceo_sp_ids, status__in=["approved", "pending"],
            start_date__lte=wk_end, end_date__gte=today.isoformat(),
        )
        conflicts = 0
        for lv in leaves:
            ids = {lv.staff_id}
            c = next((x for x in pls.cceos if x["staff_id"] == lv.staff_id), None)
            if c and c["user_id"]:
                ids.add(c["user_id"])
            if acts.filter(
                responsible_staff_id__in=ids,
                scheduled_date__date__gte=lv.start_date,
                scheduled_date__date__lte=lv.end_date,
            ).exclude(status="cancelled").exists():
                conflicts += 1
        return conflicts

    # ── 10. Funding & execution ──────────────────────────────────────────────
    @staticmethod
    def funding_execution(pls, fy) -> dict:
        from apps.fund_requests.models import WeeklyFundRequest

        cceo_uids = [c["user_id"] for c in pls.cceos if c["user_id"]]
        qs = WeeklyFundRequest.objects.filter(fy=fy, responsible_user__in=cceo_uids)
        approved = qs.filter(status__in=["confirmed_for_advance", "disbursed", "accounted"]).aggregate(s=Sum("total_amount"))["s"] or 0
        disbursed = qs.filter(status__in=["disbursed", "accounted"]).aggregate(s=Sum("disbursed_amount"))["s"] or 0
        util = _pct(int(disbursed), int(approved))

        def bucket(label, statuses, tone):
            b = qs.filter(status__in=statuses)
            return {"label": label, "count": b.count(),
                    "amount": _ugx_compact(int(b.aggregate(s=Sum("total_amount"))["s"] or 0)), "tone": tone}

        return {
            "utilization_pct": util,
            "approved_total": _ugx_compact(int(approved)),
            "disbursed_total": _ugx_compact(int(disbursed)),
            "statuses": [
                bucket("Pending Approval", ["submitted_to_pl", "submitted_to_cd"], "warning"),
                bucket("Approved", ["confirmed_for_advance"], "success"),
                bucket("Disbursed", ["disbursed", "accounted"], "info"),
                bucket("Returned / Rejected", ["returned_by_pl", "returned_by_cd", "returned_by_accountant"], "danger"),
            ],
        }

    # ── Drill-downs (all scoped) ─────────────────────────────────────────────
    @staticmethod
    def drilldown(user, drill: str, fy=None, filters=None) -> dict:
        fy = fy or get_operational_fy()
        filters = dict(filters or {})
        pls = resolve_pl_scope(user, filters)
        acts = ProgramLeadDashboardService._team_acts(pls, fy, filters)
        completed = acts.filter(status__in=COMPLETED_STATUSES)
        schools = School.objects.filter(id__in=pls.school_ids)

        def school_payload(qs, title):
            return {"kind": "schools", "title": title, "subtitle": f"{qs.count()} schools",
                    "schools": list(qs.select_related("district").only("id", "name", "district__name", "current_fy_ssa_status")[:200])}

        if drill in ("cceos", "team_target"):
            return {"kind": "cceos", "title": "CCEO Performance", "subtitle": "Supervised team",
                    "cceos": ProgramLeadDashboardService.cceo_performance(pls, fy, filters, acts)["rows"]}
        if drill == "overload":
            return {"kind": "overload", "title": "Overloaded Staff", "subtitle": "Above healthy capacity",
                    "overloaded": ProgramLeadDashboardService._overloaded_cceos(pls, fy, acts)}
        if drill == "high_risk":
            latest_fy, _ = PLAnalyticsService._cycle_fys(pls, fy)
            low = set()
            if latest_fy:
                low = set(SsaRecord.objects.filter(school_id__in=pls.school_ids, verification_status="confirmed", fy=latest_fy, average_score__lt=5.0).values_list("school_id", flat=True))
            visited = set(completed.filter(activity_type__in=VISIT_TYPES).exclude(school_id__isnull=True).values_list("school_id", flat=True))
            no_ssa_no_visit = set(schools.exclude(current_fy_ssa_status="done").exclude(id__in=visited).values_list("id", flat=True))
            return school_payload(schools.filter(id__in=low | no_ssa_no_visit), "High-Risk Schools")
        if drill in ("no_visit", "no_training", "neither"):
            visited = set(completed.filter(activity_type__in=VISIT_TYPES).exclude(school_id__isnull=True).values_list("school_id", flat=True))
            trained = set(completed.filter(activity_type__in=TRAINING_TYPES).exclude(school_id__isnull=True).values_list("school_id", flat=True))
            all_ids = set(schools.values_list("id", flat=True))
            if drill == "no_visit":
                ids, title = all_ids - visited, "Schools with No Visit"
            elif drill == "no_training":
                ids, title = all_ids - trained, "Schools with No Training"
            else:
                ids, title = all_ids - visited - trained, "Schools with Neither Training Nor Visit"
            return school_payload(schools.filter(id__in=ids), title)
        if drill in ("sf_backlog", "backlog"):
            qs = _requires_sf_id(acts).filter(Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id=""))
            return {"kind": "activities", "title": "Activity SF ID Backlog", "subtitle": f"{qs.count()} activities missing SF ID",
                    "activities": ProgramLeadDashboardService._activity_rows(qs[:150], pls)}
        if drill == "week":
            today = date.today()
            wk = today - timedelta(days=today.weekday())
            qs = acts.filter(scheduled_date__date__gte=wk, scheduled_date__date__lte=wk + timedelta(days=6))
            return {"kind": "activities", "title": "Activities This Week", "subtitle": f"{qs.count()} scheduled",
                    "activities": ProgramLeadDashboardService._activity_rows(qs[:150], pls)}
        if drill in ("funding", "funded_not_completed"):
            qs = acts.filter(advance_requests__status__in=["disbursed", "accountability_pending"]).exclude(status__in=COMPLETED_STATUSES).distinct()
            return {"kind": "activities", "title": "Funded — Not Completed", "subtitle": f"{qs.count()} activities",
                    "activities": ProgramLeadDashboardService._activity_rows(qs[:150], pls)}
        # approvals default
        return {"kind": "approvals", "title": "Approval Queue", "subtitle": "Awaiting your action",
                "approval_queue": ProgramLeadDashboardService.approval_queue(user, pls, fy)}

    @staticmethod
    def _activity_rows(qs, pls):
        name_by = {c["staff_id"]: c["name"] for c in pls.cceos}
        name_by.update({c["user_id"]: c["name"] for c in pls.cceos if c["user_id"]})
        rows = []
        for a in qs.select_related("school"):
            rows.append({
                "type": a.get_activity_type_display() if hasattr(a, "get_activity_type_display") else a.activity_type,
                "school": a.school.name if a.school_id else "—",
                "owner": name_by.get(a.responsible_staff_id, "—"),
                "status": a.status.replace("_", " ").title(),
                "planned": a.planned_date,
            })
        return rows

    # ── 11. Quick actions ────────────────────────────────────────────────────
    @staticmethod
    def quick_actions(user, pls, fy) -> list[dict]:
        awaiting = ProgramLeadDashboardService._count_awaiting(user, pls, fy)
        backlog = ProgramLeadDashboardService._team_backlog_total(pls, fy, ProgramLeadDashboardService._team_acts(pls, fy, {}))
        high_risk = ProgramLeadDashboardService._high_risk_count(pls, fy, ProgramLeadDashboardService._team_acts(pls, fy, {}))
        return [
            {"label": "Review Approvals", "sub": f"{awaiting} pending", "icon": "report", "url": "/fund-approvals"},
            {"label": "Inspect Backlogs", "sub": f"{backlog} items", "icon": "clock", "url": "/analytics/program-lead/drilldown?drill=risk"},
            {"label": "View Team Targets", "sub": "Performance & gaps", "icon": "target", "url": "/team-targets"},
            {"label": "Open Route Planner", "sub": "Plan & optimize", "icon": "map", "url": "/planning"},
            {"label": "Review Schools at Risk", "sub": f"{high_risk} schools", "icon": "warning", "url": "/analytics/program-lead"},
            {"label": "Open Monthly Planning", "sub": "Build & submit plans", "icon": "report", "url": "/fund-requests/weekly"},
        ]
