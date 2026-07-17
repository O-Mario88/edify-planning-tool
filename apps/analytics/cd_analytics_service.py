"""Country Director Analytics — the CD's national leadership-intelligence cockpit.

Country-wide oversight across every PL, CCEO, district, region, partner, cluster
and school. The CD SEES everything but ACTS only through oversight workflows
(review / recommend / assign-follow-up-to-PL / escalate / approve-return
finance) — never field execution (no scheduling, no evidence, no SF-ID entry).

All datasets are real backend queries. SSA impact is measured by verified ANNUAL
cycles (latest confirmed FY vs the previous confirmed FY) — never fake monthly
SSA movement; monthly filters only narrow operational data (activities, budgets,
evidence, finance). Reuses the shared SSA/status/type vocabulary and helpers from
apps.analytics.pl_analytics_service so counts never diverge across the app.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.db.models import Avg, Count, Q, Sum

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.core.fy import get_month_date_range, get_operational_fy
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

from apps.analytics.pl_analytics_service import (
    CLUSTER_MEETING_TYPES,
    COMPLETED_STATUSES,
    MONTHS_SHORT,
    PLANNED_STATUSES,
    SSA_COLLECTION_TYPES,
    SSA_INTERVENTIONS,
    TRAINING_TYPES,
    VERIFIED_STATUSES,
    VISIT_TYPES,
    _INTERVENTION_LABELS,
    _norm,
    _pct,
    ssa_band,
)

PARTNER_DELIVERY = "partner"


# ── Country scope ─────────────────────────────────────────────────────────────
@dataclass
class CDScope:
    fy: str
    quarter: str | None = None
    month: int | None = None
    filters: dict = field(default_factory=dict)
    school_ids: list = field(default_factory=list)  # all in-scope schools
    cceo_user_ids: list = field(default_factory=list)  # scoped CCEO User ids
    cceo_staff_ids: list = field(default_factory=list)
    responsible_ids: set = field(default_factory=set)
    # Populated once per dashboard load (see get_dashboard/_prime_target_series)
    # so every PL/CCEO-level target-achievement read in this request pools
    # from the SAME pre-fetched per-user series instead of re-running
    # TargetAchievementService.rebuild() + the monthly_targets/achievements
    # query pair once per PL row AND again once per CCEO row.
    areas: list = field(default_factory=list)
    per_user_series: dict = field(default_factory=dict)


def _initials(name):
    return "".join(p[0].upper() for p in (name or "").split() if p)[:2] or "—"


def resolve_cd_scope(fy, quarter=None, month=None, filters=None) -> CDScope:
    """Country-wide scope, narrowed by the CD filters (pl / cceo / district /
    cluster / school_type)."""
    filters = filters or {}
    schools = School.objects.filter(deleted_at__isnull=True)

    # PL filter → that PL's supervised CCEOs' schools.
    pl_filter = (filters.get("pl") or "").strip()
    cceo_filter = (filters.get("cceo") or "").strip()
    staff_ids = None
    if pl_filter:
        pl_sp = StaffProfile.objects.filter(user_id=pl_filter).first()
        sub = (
            StaffSupervisorAssignment.objects.filter(supervisor=pl_sp) if pl_sp else []
        )
        staff_ids = [a.supervisee_id for a in sub]
    if cceo_filter:
        sp = StaffProfile.objects.filter(user_id=cceo_filter).first()
        staff_ids = [sp.id] if sp else []
    if staff_ids is not None:
        assigned = list(
            StaffSchoolAssignment.objects.filter(staff_id__in=staff_ids).values_list(
                "school_id", flat=True
            )
        )
        schools = schools.filter(id__in=assigned)

    district = (filters.get("district") or "").strip()
    cluster = (filters.get("cluster") or "").strip()
    if district:
        schools = schools.filter(district_id=district)
    if cluster:
        schools = schools.filter(cluster_id=cluster)

    school_ids = list(schools.values_list("id", flat=True))

    # CCEO id sets (country-wide unless pl/cceo filtered).
    cceo_qs = User.objects.filter(roles__contains=["CCEO"], deleted_at__isnull=True)
    cceo_users = list(cceo_qs.values_list("id", flat=True))
    cceo_sps = list(
        StaffProfile.objects.filter(user__in=cceo_users).values_list("id", flat=True)
    )
    if staff_ids is not None:
        # Narrow the CCEO set to the filtered staff.
        cceo_sps = [s for s in cceo_sps if s in set(staff_ids)]
        keep = set(
            StaffProfile.objects.filter(id__in=cceo_sps).values_list(
                "user_id", flat=True
            )
        )
        cceo_users = [u for u in cceo_users if u in keep]

    responsible = set(cceo_users) | set(cceo_sps)
    return CDScope(
        fy=fy,
        quarter=quarter or None,
        month=month or None,
        filters=filters,
        school_ids=school_ids,
        cceo_user_ids=cceo_users,
        cceo_staff_ids=cceo_sps,
        responsible_ids=responsible,
    )


def _country_activities(cd: CDScope):
    qs = Activity.objects.filter(fy=cd.fy, deleted_at__isnull=True)
    # School-scope when a school-narrowing filter is active; else all activities.
    if (
        cd.filters.get("pl")
        or cd.filters.get("cceo")
        or cd.filters.get("district")
        or cd.filters.get("cluster")
    ):
        qs = qs.filter(
            Q(school_id__in=cd.school_ids)
            | Q(responsible_staff_id__in=cd.responsible_ids)
        )
    if cd.quarter:
        qs = qs.filter(quarter=cd.quarter)
    if cd.month:
        start, end = get_month_date_range(cd.fy, cd.month)
        qs = qs.filter(planned_date__gte=start.date(), planned_date__lt=end.date())
    atype = (cd.filters.get("activity_type") or "").strip()
    if atype:
        qs = qs.filter(activity_type=atype)
    partner = (cd.filters.get("partner") or "").strip()
    if partner:
        qs = qs.filter(assigned_partner_id=partner)
    return qs


# ── SSA annual-cycle helpers (country-wide) ──────────────────────────────────
def _cycle_fys(school_ids, fy):
    fys = sorted(
        SsaRecord.objects.filter(
            school_id__in=school_ids, verification_status="confirmed", fy__lte=fy
        )
        .order_by("fy")
        .values_list("fy", flat=True)
        .distinct(),
        reverse=True,
    )
    return (fys[0] if fys else None), (fys[1] if len(fys) > 1 else None)


def _refresh_target_ledger(cd: CDScope) -> None:
    """Rebuild the TargetAchievementLedger for every CCEO in the resolved
    scope before any CD/RVP-level rollup reads it. Without this, a CCEO
    whose PL/self hasn't recently opened My/Team Targets shows stale
    numbers at CD/RVP level — mirrors what My Targets / Team Targets
    already do on their own page loads. Call once per page load (not per
    section) since rebuild() is idempotent but not free.

    Prefer `_prime_target_series(cd)` over this directly when the caller
    will also read PL/CCEO-level target achievement afterwards — it does
    this same rebuild AND caches the resulting series on `cd` so every
    downstream _weighted_achievement() call reuses it instead of
    re-fetching per PL/per CCEO."""
    from apps.targets.my_targets import TargetAchievementService

    if not cd.cceo_user_ids:
        return
    for u in User.objects.filter(id__in=cd.cceo_user_ids):
        TargetAchievementService.rebuild(u, cd.fy)


def _prime_target_series(cd: CDScope) -> None:
    """Populate cd.areas/cd.per_user_series ONCE per request: rebuilds every
    in-scope CCEO's ledger and fetches their monthly target/achieved series
    exactly once each (apps.targets.my_targets.per_user_monthly_series).
    Every _weighted_achievement() call in this same request then pools from
    this cached data (apps.targets.my_targets.pool_series — pure Python, no
    DB) instead of re-rebuilding + re-fetching per PL row AND again per CCEO
    row, which is what made target_by_pl_cceo/pl_oversight/kpis each
    independently re-derive the same people's numbers."""
    from apps.targets.my_targets import active_target_areas, per_user_monthly_series

    cd.areas = active_target_areas()
    if not cd.cceo_user_ids:
        cd.per_user_series = {}
        return
    cd.per_user_series = per_user_monthly_series(
        User.objects.filter(id__in=cd.cceo_user_ids),
        cd.fy,
        areas=cd.areas,
    )


class CDAnalyticsService:
    """Country Director analytics facade. Every method takes (user, fy, quarter,
    month, filters). CD role is enforced at the view layer."""

    @staticmethod
    def get_dashboard(user, fy=None, quarter=None, month=None, filters=None) -> dict:
        fy = fy or get_operational_fy()
        filters = dict(filters or {})
        quarter = (quarter or filters.get("quarter") or "").strip() or None
        month = month or (
            int(filters["month"])
            if (filters.get("month") or "").strip().isdigit()
            else None
        )
        cd = resolve_cd_scope(fy, quarter, month, filters)
        acts = _country_activities(cd)
        _prime_target_series(cd)

        # Computed once, reused below AND passed into recommended_actions —
        # it used to fully re-run both of these expensive scans a second
        # time just to derive two counts from them.
        partner_performance = CDAnalyticsService.partner_performance(cd, acts)
        pl_oversight = CDAnalyticsService.pl_oversight(cd, acts)

        return {
            "fy": fy,
            "quarter": quarter,
            "month": month,
            "filters": filters,
            "kpi_strip_items": CDAnalyticsService.kpis(cd, acts),
            "performance_vs_target": CDAnalyticsService.performance_vs_target(cd),
            "ssa_interventions": CDAnalyticsService.ssa_interventions(cd),
            "target_by_pl": CDAnalyticsService.target_by_pl_cceo(cd, acts),
            "district_heatmap": CDAnalyticsService.district_heatmap(cd),
            "partner_performance": partner_performance,
            "cluster_performance": CDAnalyticsService.cluster_performance(cd, acts),
            "recommended_actions": CDAnalyticsService.recommended_actions(
                cd,
                acts,
                partner_rows=partner_performance["rows"],
                pl_rows=pl_oversight["rows"],
            ),
            "pl_oversight": pl_oversight,
            "cceo_snapshot": CDAnalyticsService.cceo_snapshot(cd, acts),
            "impact_summary": CDAnalyticsService.impact_summary(cd, acts),
            "regional_summary": CDAnalyticsService.regional_summary(cd),
            "budget_finance": CDAnalyticsService.budget_finance_health(cd),
            "operational_risk": CDAnalyticsService.operational_risk(cd, acts),
            "filter_options": CDAnalyticsService.filter_options(cd),
            "scope_meta": {
                "pl_count": len(CDAnalyticsService._pls()),
                "cceo_count": len(cd.cceo_user_ids),
                "school_count": len(cd.school_ids),
            },
        }

    # ── PL / CCEO helpers ────────────────────────────────────────────────────
    @staticmethod
    def _pls():
        return list(
            User.objects.filter(
                roles__contains=["Program Lead"], deleted_at__isnull=True
            ).order_by("name")
        )

    @staticmethod
    def _pl_cceos(pl_user, cd=None):
        """Supervised CCEOs of a PL → list of {staff_id, user_id, name, school_ids}.

        School ids are intersected with the active, in-scope school set (`cd`) so
        stale/deleted/duplicate assignment rows never inflate counts."""
        sp = StaffProfile.objects.filter(user=pl_user).first()
        if not sp:
            return []
        scope_ids = (
            set(cd.school_ids)
            if cd is not None
            else set(
                School.objects.filter(deleted_at__isnull=True).values_list(
                    "id", flat=True
                )
            )
        )
        sub = list(
            StaffProfile.objects.filter(supervisor_links__supervisor=sp).select_related(
                "user"
            )
        )
        assign = StaffSchoolAssignment.objects.filter(
            staff__in=[s.id for s in sub]
        ).values_list("staff_id", "school_id")
        per = {}
        for sid, schid in assign:
            if (
                schid in scope_ids
            ):  # active, in-scope schools only (dedup + drop stale rows)
                per.setdefault(sid, set()).add(schid)
        out = []
        for s in sub:
            out.append(
                {
                    "staff_id": s.id,
                    "user_id": s.user_id,
                    "name": (s.user.name if s.user else s.title) or "CCEO",
                    "school_ids": per.get(s.id, set()),
                }
            )
        return out

    @staticmethod
    def _completion_vs_target(staff_id, completed_qs, fy, quarter=None, user_id=None):
        """(achievement_pct, achieved, target) for ONE CCEO from the SAME
        validated-ledger + TargetArea.weight math as the Overall Target
        Achievement KPI (`_weighted_overall`) — a per-row table can never
        show a different definition of "earned target credit" than the KPI
        strip above it. `completed_qs` is accepted for call-site
        compatibility but no longer read: achievement now comes only from
        the validated TargetAchievementLedger, never a raw completed-status
        count. Pass `user_id` when already known to avoid a lookup."""
        if user_id is None:
            user_id = (
                StaffProfile.objects.filter(id=staff_id)
                .values_list("user_id", flat=True)
                .first()
            )
        return CDAnalyticsService._weighted_achievement(
            fy,
            quarter,
            [user_id] if user_id else [],
            [staff_id] if staff_id else [],
        )

    # ── KPI strip (10) ───────────────────────────────────────────────────────
    @staticmethod
    def kpis(cd, acts):
        completed = acts.filter(status__in=COMPLETED_STATUSES)
        schools = School.objects.filter(id__in=cd.school_ids)

        # Overall target achievement — weighted across the five official
        # target areas from the validated achievement ledger (mandate §6):
        # high-volume visits cannot hide failure on strategic targets.
        overall_target, total_a, total_t = CDAnalyticsService._weighted_overall(cd)

        reached_school_ids = set(
            completed.exclude(school_id__isnull=True).values_list(
                "school_id", flat=True
            )
        )
        schools_impacted = len(reached_school_ids)
        teachers = (
            completed.filter(activity_type__in=TRAINING_TYPES).aggregate(
                s=Sum("teachers_attended")
            )["s"]
            or 0
        )
        leaders = (
            completed.filter(activity_type__in=TRAINING_TYPES).aggregate(
                s=Sum("leaders_attended")
            )["s"]
            or 0
        )
        activities_completed = completed.count()

        active_pls = CDAnalyticsService._active_pl_count(cd, acts)
        total_pls = len(CDAnalyticsService._pls())
        active_cceos = min(
            acts.filter(responsible_staff_id__in=cd.responsible_ids)
            .values("responsible_staff_id")
            .distinct()
            .count(),
            len(cd.cceo_user_ids),
        )
        total_cceos = len(cd.cceo_user_ids)

        latest_fy, _ = _cycle_fys(cd.school_ids, cd.fy)
        avg_ssa = None
        if latest_fy:
            avg_ssa = _norm(
                SsaRecord.objects.filter(
                    school_id__in=cd.school_ids,
                    verification_status="confirmed",
                    fy=latest_fy,
                ).aggregate(a=Avg("average_score"))["a"]
            )

        total_districts = (
            schools.exclude(district__isnull=True)
            .values("district_id")
            .distinct()
            .count()
        )
        reached_districts = (
            School.objects.filter(id__in=reached_school_ids)
            .exclude(district__isnull=True)
            .values("district_id")
            .distinct()
            .count()
        )
        from apps.clusters.models import Cluster

        total_clusters = Cluster.objects.filter(deleted_at__isnull=True).count()
        active_clusters = (
            acts.exclude(cluster_id__isnull=True)
            .exclude(cluster_id="")
            .values("cluster_id")
            .distinct()
            .count()
        )

        budget_util = CDAnalyticsService._budget_utilization(cd)

        def card(icon, label, value, variant, helper):
            return {
                "icon": icon,
                "label": label,
                "value": value,
                "variant": variant,
                "helper": helper,
            }

        return [
            card(
                "target",
                "Overall Target Achievement",
                f"{overall_target}%",
                "primary",
                "weighted across the five target areas · validated only",
            ),
            card(
                "school",
                "Schools Impacted",
                f"{schools_impacted:,}",
                "info",
                "verified activity",
            ),
            card(
                "users",
                "Teachers Trained",
                f"{int(teachers):,}",
                "success",
                "verified attendance",
            ),
            card(
                "users",
                "School Leaders Trained",
                f"{int(leaders):,}",
                "violet",
                "verified attendance",
            ),
            card(
                "calendar",
                "Total Activities Completed",
                f"{activities_completed:,}",
                "info",
                "this period",
            ),
            card(
                "users",
                "Active PLs / Active CCEOs",
                f"{active_pls} / {active_cceos}",
                "info",
                f"of {total_pls} PLs · {total_cceos} CCEOs",
            ),
            card(
                "chart",
                "Average SSA Score",
                (f"{avg_ssa}%" if avg_ssa is not None else "No SSA"),
                "success",
                "latest verified cycle",
            ),
            card(
                "calendar",
                "Districts Covered",
                f"{reached_districts} / {total_districts}",
                "info",
                "with verified activity",
            ),
            card(
                "shield",
                "Clusters Covered",
                f"{active_clusters} / {total_clusters}",
                "violet",
                "with activity",
            ),
            card(
                "currency",
                "Budget Utilization",
                f"{budget_util}%",
                "finance",
                "disbursed / approved",
            ),
        ]

    @staticmethod
    def _weighted_overall(cd):
        """Country weighted validated achievement across the five official
        target areas — the KPI strip's canonical number. Thin wrapper over
        `_weighted_achievement` so every other consumer that needs the SAME
        math for a narrower set of CCEOs (a PL's team, a single CCEO) reads
        from one place instead of recomputing its own definition."""
        return CDAnalyticsService._weighted_achievement(
            cd.fy,
            cd.quarter,
            cd.cceo_user_ids,
            cd.cceo_staff_ids,
            areas=cd.areas or None,
            per_user_series=cd.per_user_series or None,
        )

    @staticmethod
    def _weighted_achievement(
        fy, quarter, user_ids, staff_ids, areas=None, per_user_series=None
    ) -> tuple:
        """(weighted %, total validated achieved, total target) for the given
        user_id/staff_id sets, across the five official target areas.

        CANONICAL CALCULATION SOURCE: this is a thin scope-resolution wrapper
        around apps.targets.my_targets.pooled_monthly_series() +
        apps.targets.my_targets.weighted_period_pct() — the exact same
        per-user series (MyTargetQueryService.monthly_targets/
        monthly_achievements, explicit-then-annual-fallback target
        resolution, TargetAchievementLedger-validated achievement) and the
        exact same weighting formula that My Targets and PL Team Targets
        use. Do NOT reimplement target-proration, ledger aggregation, or
        weighting here — call the shared helpers so CD/RVP Analytics can
        never disagree with what a PL sees on their own Team Targets page
        for the same people/period (this function used to hand-roll its own
        annual-target proration — `round(annual * months/12)` — which
        disagreed with the canonical `divmod`-based proration in roughly
        two-thirds of cases; that duplicate logic is gone).

        This is the single place CD/RVP-level code reads "did this activity
        earn target credit" — the KPI strip (all CCEOs in scope) and any
        per-PL/per-CCEO breakdown (a subset of CCEOs) both call this, so a
        table can never disagree with the KPI above it.

        Pass `per_user_series` (from `_prime_target_series(cd)` /
        `apps.targets.my_targets.per_user_monthly_series`) when computing
        MULTIPLE overlapping subsets of the same roster in one request (the
        country total, then each PL's team, then each CCEO) — it pools from
        the pre-fetched series in pure Python instead of re-rebuilding the
        ledger and re-querying per subset. Omitting it (the default) falls
        back to a fresh single-purpose fetch, correct but only efficient for
        a genuinely one-off caller like a single-CCEO drilldown.
        """
        from apps.targets.fy_calendar import FinancialYearCalendarService as TCal
        from apps.targets.my_targets import (
            active_target_areas,
            pool_series,
            pooled_monthly_series,
            weighted_period_pct,
        )

        # Resolve every distinct person from user_ids ∪ (staff_ids -> user_id)
        # into one User set — pooled_monthly_series/MyTargetQueryService only
        # ever operate on a real User (targets/achievement are both keyed by
        # user_id, never bare staff_id), matching how My Targets and Team
        # Targets already resolve people.
        resolved_user_ids = {u for u in user_ids if u}
        staffs = [s for s in staff_ids if s]
        if staffs:
            resolved_user_ids |= set(
                StaffProfile.objects.filter(id__in=staffs)
                .exclude(user_id__isnull=True)
                .values_list("user_id", flat=True)
            )
        if not resolved_user_ids:
            return 0, 0, 0

        areas = areas or active_target_areas()
        months = TCal.months_of_quarter(quarter) if quarter else list(range(1, 13))
        if per_user_series is not None:
            targets, achieved = pool_series(resolved_user_ids, per_user_series, areas)
        else:
            users = list(User.objects.filter(id__in=resolved_user_ids))
            targets, achieved = pooled_monthly_series(users, fy, areas=areas)
        return weighted_period_pct(areas, targets, achieved, months)

    @staticmethod
    def _active_pl_count(cd, acts):
        owners = set(
            acts.exclude(responsible_staff_id__isnull=True).values_list(
                "responsible_staff_id", flat=True
            )
        )
        n = 0
        for pl in CDAnalyticsService._pls():
            cceos = CDAnalyticsService._pl_cceos(pl, cd)
            ids = set()
            for c in cceos:
                ids.add(c["staff_id"])
                if c["user_id"]:
                    ids.add(c["user_id"])
            if ids & owners:
                n += 1
        return n

    @staticmethod
    def _advance_qs(cd):
        """Activity-level advance pipeline (the real country finance volume),
        scoped to the CD filter set."""
        from apps.fund_requests.models import AdvanceRequest

        qs = AdvanceRequest.objects.filter(
            activity__fy=cd.fy, activity__deleted_at__isnull=True
        )
        if (
            cd.filters.get("pl")
            or cd.filters.get("cceo")
            or cd.filters.get("district")
            or cd.filters.get("cluster")
        ):
            qs = qs.filter(
                Q(activity__school_id__in=cd.school_ids)
                | Q(responsible_user_id__in=cd.responsible_ids)
            )
        if cd.quarter:
            qs = qs.filter(activity__quarter=cd.quarter)
        if cd.month:
            start, end = get_month_date_range(cd.fy, cd.month)
            qs = qs.filter(planned_date__gte=start.date(), planned_date__lt=end.date())
        return qs

    @staticmethod
    def _budget_utilization(cd):
        qs = CDAnalyticsService._advance_qs(cd)
        requested = int(qs.aggregate(s=Sum("amount"))["s"] or 0)
        disbursed = int(qs.aggregate(s=Sum("disbursed_amount"))["s"] or 0)
        return _pct(disbursed, requested)

    # ── 1. Performance vs target over time ───────────────────────────────────
    @staticmethod
    def performance_vs_target(cd):
        acts = _country_activities(
            CDScope(
                fy=cd.fy,
                filters=cd.filters,
                school_ids=cd.school_ids,
                cceo_user_ids=cd.cceo_user_ids,
                cceo_staff_ids=cd.cceo_staff_ids,
                responsible_ids=cd.responsible_ids,
            )
        )  # full FY timeline
        labels, planned, completed, pct = [], [], [], []
        # country annual target for the cumulative line — same weighted
        # target denominator as the Overall Target Achievement KPI.
        _, _, total_target = CDAnalyticsService._weighted_achievement(
            cd.fy,
            None,
            cd.cceo_user_ids,
            cd.cceo_staff_ids,
            areas=cd.areas or None,
            per_user_series=cd.per_user_series or None,
        )
        cum = 0
        target_types = (
            VISIT_TYPES + TRAINING_TYPES + CLUSTER_MEETING_TYPES + SSA_COLLECTION_TYPES
        )
        for m in range(1, 13):
            start, end = get_month_date_range(cd.fy, m)
            labels.append(MONTHS_SHORT[start.month])
            mq = acts.filter(
                planned_date__gte=start.date(), planned_date__lt=end.date()
            )
            planned.append(mq.filter(status__in=PLANNED_STATUSES).count())
            completed.append(mq.filter(status__in=COMPLETED_STATUSES).count())
            cum += mq.filter(
                status__in=COMPLETED_STATUSES, activity_type__in=target_types
            ).count()
            pct.append(round(cum / total_target * 100) if total_target else 0)
        return {
            "labels": labels,
            "planned": planned,
            "completed": completed,
            "pct": pct,
            "has_target": total_target > 0,
        }

    # ── 2. SSA by intervention (annual) ──────────────────────────────────────
    @staticmethod
    def ssa_interventions(cd):
        latest, prev = _cycle_fys(cd.school_ids, cd.fy)
        rows = []
        if not latest:
            for v, label, code in SSA_INTERVENTIONS:
                b = ssa_band(None)
                rows.append(
                    {
                        "value": v,
                        "label": label,
                        "code": code,
                        "pct": None,
                        "delta": None,
                        "band": b[0],
                        "color": b[1],
                        "tone": b[2],
                    }
                )
            return {"rows": rows, "latest_fy": None, "prev_fy": None, "has_data": False}

        def by_int(cfy):
            rids = SsaRecord.objects.filter(
                school_id__in=cd.school_ids, verification_status="confirmed", fy=cfy
            ).values_list("id", flat=True)
            return {
                r["intervention"]: r["a"]
                for r in SsaScore.objects.filter(ssa_record_id__in=rids)
                .values("intervention")
                .annotate(a=Avg("score"))
            }

        cur, old = by_int(latest), (by_int(prev) if prev else {})
        for v, label, code in SSA_INTERVENTIONS:
            cp = _norm(cur.get(v))
            pp = _norm(old.get(v)) if prev else None
            delta = round(cp - pp, 1) if (cp is not None and pp is not None) else None
            b = ssa_band(cp)
            rows.append(
                {
                    "value": v,
                    "label": label,
                    "code": code,
                    "pct": cp,
                    "delta": delta,
                    "band": b[0],
                    "color": b[1],
                    "tone": b[2],
                }
            )
        rows.sort(key=lambda r: (r["pct"] is None, -(r["pct"] or 0)))
        return {"rows": rows, "latest_fy": latest, "prev_fy": prev, "has_data": True}

    # ── 3. Target achievement by PL & CCEO ───────────────────────────────────
    @staticmethod
    def target_by_pl_cceo(cd, acts):
        rows = []
        for pl in CDAnalyticsService._pls():
            cceos = CDAnalyticsService._pl_cceos(pl, cd)
            if not cceos:
                continue
            # Team-pooled weighted pct — the SAME math as the KPI strip,
            # scoped to this PL's CCEOs (never a re-ratio of already-weighted
            # per-CCEO numbers, which would silently unweight the team total).
            pl_pct, _pl_a, _pl_t = CDAnalyticsService._weighted_achievement(
                cd.fy,
                cd.quarter,
                [c["user_id"] for c in cceos if c["user_id"]],
                [c["staff_id"] for c in cceos],
                areas=cd.areas or None,
                per_user_series=cd.per_user_series or None,
            )
            cceo_pcts = []
            for c in cceos:
                pct, _a, t = CDAnalyticsService._weighted_achievement(
                    cd.fy,
                    cd.quarter,
                    [c["user_id"]] if c["user_id"] else [],
                    [c["staff_id"]],
                    areas=cd.areas or None,
                    per_user_series=cd.per_user_series or None,
                )
                if t:
                    cceo_pcts.append(pct)
            cceo_avg = round(sum(cceo_pcts) / len(cceo_pcts)) if cceo_pcts else 0
            rows.append(
                {"id": pl.id, "name": pl.name, "pl_pct": pl_pct, "cceo_avg": cceo_avg}
            )
        rows.sort(key=lambda r: -r["pl_pct"])
        return {"rows": rows}

    # ── 4. District SSA heatmap ──────────────────────────────────────────────
    @staticmethod
    def district_heatmap(cd):
        latest, _ = _cycle_fys(cd.school_ids, cd.fy)
        schools = School.objects.filter(id__in=cd.school_ids)
        cols = SSA_INTERVENTIONS  # all 8
        if not latest:
            return {
                "rows": [],
                "codes": [c[2] for c in cols],
                "labels": [c[1] for c in cols],
            }

        # Batch-fetch every ingredient ONCE instead of once per district (this
        # used to run ~5 queries per district — up to ~680 queries at scale).
        # School->district, every confirmed SSA record for the latest cycle,
        # and every intervention score on those records, then group in Python.
        districts = list(
            schools.exclude(district__isnull=True)
            .values("district_id", "district__name")
            .annotate(n=Count("id"))
            .order_by("-n")
        )
        school_district = dict(
            schools.exclude(district__isnull=True).values_list("id", "district_id")
        )

        records = list(
            SsaRecord.objects.filter(
                school_id__in=cd.school_ids,
                verification_status="confirmed",
                fy=latest,
            ).values("id", "school_id", "average_score")
        )
        record_district = {}
        district_scores: dict = {}  # district_id -> [average_score, ...]
        district_covered_schools: dict = {}  # district_id -> {school_id, ...}
        for r in records:
            did = school_district.get(r["school_id"])
            if did is None:
                continue
            record_district[r["id"]] = did
            district_scores.setdefault(did, []).append(r["average_score"])
            district_covered_schools.setdefault(did, set()).add(r["school_id"])

        scores = list(
            SsaScore.objects.filter(
                ssa_record_id__in=list(record_district.keys())
            ).values("ssa_record_id", "intervention", "score")
        )
        district_intervention_scores: dict = {}  # district_id -> {intervention: [score, ...]}
        for s in scores:
            did = record_district.get(s["ssa_record_id"])
            if did is None:
                continue
            district_intervention_scores.setdefault(did, {}).setdefault(
                s["intervention"], []
            ).append(s["score"])

        def _mean(values):
            values = [v for v in values if v is not None]
            return (sum(values) / len(values)) if values else None

        rows = []
        for d in districts:
            did = d["district_id"]
            by = {
                k: _mean(v)
                for k, v in district_intervention_scores.get(did, {}).items()
            }
            cells = []
            for v, label, code in cols:
                pct = _norm(by.get(v))
                cells.append({"pct": pct, "tone": ssa_band(pct)[2]})
            avg = _norm(_mean(district_scores.get(did, [])))
            covered = len(district_covered_schools.get(did, set()))
            n_schools = d["n"]
            rows.append(
                {
                    "id": did,
                    "name": d["district__name"],
                    "cells": cells,
                    "avg": avg,
                    "avg_tone": ssa_band(avg)[2],
                    "coverage": f"{covered} of {n_schools}",
                    "coverage_pct": round(covered / n_schools * 100)
                    if n_schools
                    else 0,
                    "low_coverage": bool(n_schools) and covered / n_schools < 0.6,
                }
            )
        return {
            "rows": rows,
            "codes": [c[2] for c in cols],
            "labels": [c[1] for c in cols],
        }

    # ── 5. Partner performance (impact-weighted) ─────────────────────────────
    @staticmethod
    def partner_performance(cd, acts):
        from apps.partners.models import Partner, PartnerAssignment

        latest, prev = _cycle_fys(cd.school_ids, cd.fy)
        rows = []
        for p in Partner.objects.all().order_by("name"):
            assignments = PartnerAssignment.objects.filter(partner=p)
            p_school_ids = set(
                assignments.exclude(school__isnull=True).values_list(
                    "school_id", flat=True
                )
            )
            p_acts = acts.filter(assigned_partner_id=p.id)
            planned = p_acts.count()
            done = p_acts.filter(status__in=COMPLETED_STATUSES).count()
            target_pct = _pct(done, planned)
            verified = p_acts.filter(status__in=VERIFIED_STATUSES).count()
            # SSA improvement across the partner's schools (annual delta).
            ssa_improve = None
            if latest and prev and p_school_ids:
                cur = SsaRecord.objects.filter(
                    school_id__in=p_school_ids,
                    verification_status="confirmed",
                    fy=latest,
                ).aggregate(a=Avg("average_score"))["a"]
                old = SsaRecord.objects.filter(
                    school_id__in=p_school_ids, verification_status="confirmed", fy=prev
                ).aggregate(a=Avg("average_score"))["a"]
                if cur is not None and old is not None:
                    ssa_improve = round((cur - old) * 10, 1)
            rec = CDAnalyticsService._partner_recommendation(
                target_pct, ssa_improve, planned
            )
            rows.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "target_pct": target_pct,
                    "schools_supported": len(p_school_ids)
                    or p_acts.exclude(school_id__isnull=True)
                    .values("school_id")
                    .distinct()
                    .count(),
                    "ssa_improve": ssa_improve,
                    "verified": verified,
                    "recommendation": rec[0],
                    "rec_tone": rec[1],
                }
            )
        rows.sort(key=lambda r: -r["target_pct"])
        return {"rows": rows}

    @staticmethod
    def _partner_recommendation(target_pct, ssa_improve, planned):
        if planned == 0:
            return ("Insufficient Data", "neutral")
        if ssa_improve is None:
            return ("Insufficient Data", "neutral")
        if ssa_improve < 0:
            return ("Drop / Do Not Renew", "danger")
        if target_pct >= 70 and ssa_improve >= 5:
            return ("Assign More Schools", "success")
        if target_pct >= 70 and ssa_improve < 5:
            return ("Quality Review", "warning")
        if target_pct < 55 and ssa_improve >= 5:
            return ("Capacity Review", "warning")
        if target_pct < 55 and ssa_improve < 5:
            return ("Drop / Replace", "danger")
        return ("Keep Active", "success")

    # ── 6. Cluster performance ───────────────────────────────────────────────
    @staticmethod
    def cluster_performance(cd, acts):
        latest, prev = _cycle_fys(cd.school_ids, cd.fy)
        names, cluster_school = CDAnalyticsService._cluster_membership(cd, acts)
        rows = []
        for idx, cid in enumerate(sorted(cluster_school.keys()), start=1):
            c_ids = list(cluster_school[cid])
            avg = weak = None
            weak_label = "—"
            if latest and c_ids:
                rids = list(
                    SsaRecord.objects.filter(
                        school_id__in=c_ids, verification_status="confirmed", fy=latest
                    ).values_list("id", flat=True)
                )
                avg = _norm(
                    SsaRecord.objects.filter(id__in=rids).aggregate(
                        a=Avg("average_score")
                    )["a"]
                )
                bi = (
                    SsaScore.objects.filter(ssa_record_id__in=rids)
                    .values("intervention")
                    .annotate(a=Avg("score"))
                    .order_by("a")
                    .first()
                )
                if bi:
                    weak_label = _INTERVENTION_LABELS.get(
                        bi["intervention"], (bi["intervention"], "")
                    )[0]
                    weak = _norm(bi["a"])
            c_acts = acts.filter(cluster_id=cid)
            trainings = c_acts.filter(
                activity_type__in=TRAINING_TYPES + CLUSTER_MEETING_TYPES,
                status__in=COMPLETED_STATUSES,
            ).count()
            visits = c_acts.filter(
                activity_type__in=VISIT_TYPES, status__in=COMPLETED_STATUSES
            ).count()
            b = ssa_band(avg)
            rows.append(
                {
                    "index": idx,
                    "id": cid,
                    "name": names.get(cid, f"Cluster {idx}"),
                    "avg_ssa": avg,
                    "ssa_tone": b[2],
                    "weakest_label": weak_label,
                    "weakest_pct": weak,
                    "trainings": trainings,
                    "visits": visits,
                    "schools": len(c_ids),
                    "next_action": CDAnalyticsService._cluster_next(avg, bool(c_ids)),
                    "risk": b[0],
                }
            )
        rows.sort(key=lambda r: (r["avg_ssa"] is None, r["avg_ssa"] or 0))
        unclustered = School.objects.filter(
            id__in=cd.school_ids, cluster_status="unclustered"
        ).count()
        return {"rows": rows, "unclustered": unclustered}

    @staticmethod
    def _cluster_membership(cd, acts):
        """Cluster → set(school_ids). Every cluster that runs activity surfaces as a
        row; school membership is attached only where it genuinely exists (School
        .cluster_id survives, or an activity ties a school to a cluster). Most seed
        schools are 'unclustered', so many clusters honestly carry no SSA yet."""
        from apps.clusters.models import Cluster

        cluster_school = {}
        # Every operational cluster (has meetings/trainings) is a real row.
        for cid in (
            acts.exclude(cluster_id__isnull=True)
            .exclude(cluster_id="")
            .values_list("cluster_id", flat=True)
            .distinct()
        ):
            cluster_school.setdefault(cid, set())
        # Real school linkage where present.
        for cid, sid in (
            acts.exclude(cluster_id__isnull=True)
            .exclude(cluster_id="")
            .exclude(school_id__isnull=True)
            .values_list("cluster_id", "school_id")
        ):
            cluster_school.setdefault(cid, set()).add(sid)
        for sid, cid in (
            School.objects.filter(id__in=cd.school_ids)
            .exclude(cluster_id__isnull=True)
            .exclude(cluster_id="")
            .values_list("id", "cluster_id")
        ):
            cluster_school.setdefault(cid, set()).add(sid)
        names = dict(
            Cluster.objects.filter(id__in=list(cluster_school.keys())).values_list(
                "id", "name"
            )
        )
        return names, cluster_school

    @staticmethod
    def _cluster_next(avg, has_schools=True):
        if not has_schools:
            return "Complete Clustering"
        if avg is None:
            return "Schedule SSA Collection"
        if avg < 40:
            return "Escalate — Recovery Plan"
        if avg < 60:
            return "Assign PL Follow-up"
        return "Monitor"

    # ── 7. Recommended actions ───────────────────────────────────────────────
    @staticmethod
    def recommended_actions(cd, acts, partner_rows=None, pl_rows=None):
        """`partner_rows`/`pl_rows`: pass the already-computed
        partner_performance()["rows"]/pl_oversight()["rows"] when the caller
        (get_dashboard) has already run them — avoids fully re-running those
        two expensive scans a second time just to derive two counts from
        them. Omit to compute fresh (e.g. a standalone caller)."""
        schools = School.objects.filter(id__in=cd.school_ids)
        no_ssa = schools.exclude(current_fy_ssa_status="done").count()
        latest, _ = _cycle_fys(cd.school_ids, cd.fy)

        # Batch-fetch once instead of ~2 queries per district (school-scoped
        # district list, one confirmed-SSA query, one leadership-score query
        # per record set) — grouped in Python instead of re-queried per district.
        low_lship_districts = 0
        if latest:
            school_district = dict(
                schools.exclude(district__isnull=True).values_list("id", "district_id")
            )
            record_district = {}
            for sid, rec_id in SsaRecord.objects.filter(
                school_id__in=cd.school_ids,
                verification_status="confirmed",
                fy=latest,
            ).values_list("school_id", "id"):
                did = school_district.get(sid)
                if did is not None:
                    record_district[rec_id] = did
            district_leadership_scores: dict = {}
            for rec_id, score in SsaScore.objects.filter(
                ssa_record_id__in=list(record_district.keys()),
                intervention="leadership",
            ).values_list("ssa_record_id", "score"):
                did = record_district.get(rec_id)
                if did is not None:
                    district_leadership_scores.setdefault(did, []).append(score)
            for scores in district_leadership_scores.values():
                vals = [s for s in scores if s is not None]
                if vals and _norm(sum(vals) / len(vals)) < 50:
                    low_lship_districts += 1

        if partner_rows is None:
            partner_rows = CDAnalyticsService.partner_performance(cd, acts)["rows"]
        if pl_rows is None:
            pl_rows = CDAnalyticsService.pl_oversight(cd, acts)["rows"]
        partners_followup = sum(
            1
            for r in partner_rows
            if r["recommendation"]
            in ("Quality Review", "Capacity Review", "Put Under Review")
        )
        underperf_pl = sum(
            1 for r in pl_rows if r["risk"] in ("High Risk", "Critical Risk")
        )
        low_budget = 1 if CDAnalyticsService._budget_utilization(cd) < 50 else 0

        items = [
            {
                "issue": "Schools without SSA",
                "count": no_ssa,
                "severity": "danger",
                "owner": "PL",
                "link": "?drill=risk&issue=no_ssa",
            },
            {
                "issue": "Districts with low Leadership scores (<50%)",
                "count": low_lship_districts,
                "severity": "warning",
                "owner": "PL",
                "link": "?drill=district_low_lship",
            },
            {
                "issue": "Partners needing follow-up",
                "count": partners_followup,
                "severity": "warning",
                "owner": "CD",
                "link": "?drill=partner",
            },
            {
                "issue": "Underperforming CCEO teams (Ach. <55%)",
                "count": underperf_pl,
                "severity": "warning",
                "owner": "PL",
                "link": "?drill=pl",
            },
            {
                "issue": "Budget risks & low utilization (<50%)",
                "count": low_budget,
                "severity": "info",
                "owner": "CD",
                "link": "?drill=budget",
            },
        ]
        return {"items": [i for i in items if i["count"]]}

    # ── 8. PL oversight summary ──────────────────────────────────────────────
    @staticmethod
    def pl_oversight(cd, acts):
        latest, _ = _cycle_fys(cd.school_ids, cd.fy)
        rows = []
        for pl in CDAnalyticsService._pls():
            cceos = CDAnalyticsService._pl_cceos(pl, cd)
            all_school_ids = set()
            for c in cceos:
                all_school_ids |= c["school_ids"]
            # Same weighted validated-ledger math as the KPI strip's Overall
            # Target Achievement, pooled across this PL's team — so this
            # per-row table can never disagree with the KPI above it.
            pl_pct, pl_a, pl_t = CDAnalyticsService._weighted_achievement(
                cd.fy,
                cd.quarter,
                [c["user_id"] for c in cceos if c["user_id"]],
                [c["staff_id"] for c in cceos],
                areas=cd.areas or None,
                per_user_series=cd.per_user_series or None,
            )
            schools_at_risk = (
                School.objects.filter(id__in=all_school_ids)
                .exclude(current_fy_ssa_status="done")
                .count()
            )
            resp_ids = set()
            for c in cceos:
                resp_ids.add(c["staff_id"])
                if c["user_id"]:
                    resp_ids.add(c["user_id"])
            backlog = (
                acts.filter(
                    Q(responsible_staff_id__in=resp_ids)
                    | Q(school_id__in=all_school_ids)
                )
                .filter(
                    status__in=[
                        "returned_by_pl",
                        "returned_by_ia",
                        "salesforce_id_required",
                        "awaiting_ia_verification",
                    ]
                )
                .count()
            )
            budget_util = CDAnalyticsService._pl_budget(cceos, cd.fy)
            risk = CDAnalyticsService._pl_risk(
                pl_pct, pl_t, schools_at_risk, len(all_school_ids), backlog
            )
            rows.append(
                {
                    "id": pl.id,
                    "name": pl.name,
                    "cceos": len(cceos),
                    "target_pct": pl_pct,
                    "schools_at_risk": schools_at_risk,
                    "budget_util": budget_util,
                    "backlog": backlog,
                    "risk": risk[0],
                    "risk_tone": risk[1],
                }
            )
        rows.sort(key=lambda r: r["target_pct"])
        return {"rows": rows}

    @staticmethod
    def _pl_budget(cceos, fy):
        from apps.fund_requests.models import AdvanceRequest

        uids = [c["user_id"] for c in cceos if c["user_id"]]
        if not uids:
            return 0
        qs = AdvanceRequest.objects.filter(
            activity__fy=fy, responsible_user_id__in=uids
        )
        requested = int(qs.aggregate(s=Sum("amount"))["s"] or 0)
        disbursed = int(qs.aggregate(s=Sum("disbursed_amount"))["s"] or 0)
        return _pct(disbursed, requested)

    @staticmethod
    def _pl_risk(pct, target_total, schools_at_risk, n_schools, backlog):
        score = 0
        if target_total and pct < 40:
            score += 2
        elif target_total and pct < 55:
            score += 1
        if n_schools and schools_at_risk / max(1, n_schools) > 0.6:
            score += 2
        elif n_schools and schools_at_risk / max(1, n_schools) > 0.3:
            score += 1
        if backlog >= 10:
            score += 1
        if score >= 4:
            return ("Critical Risk", "danger")
        if score >= 2:
            return ("High Risk", "warning")
        if score >= 1:
            return ("Medium Risk", "amber")
        return ("Low Risk", "success")

    # ── 9. CCEO snapshot ─────────────────────────────────────────────────────
    @staticmethod
    def cceo_snapshot(cd, acts):
        from collections import defaultdict

        latest, prev = _cycle_fys(cd.school_ids, cd.fy)
        pls = CDAnalyticsService._pls()
        pl_cceos = {pl.id: CDAnalyticsService._pl_cceos(pl, cd) for pl in pls}
        overdue_statuses = (
            "scheduled",
            "in_progress",
            "completion_started",
            "rescheduled",
        )
        today = date.today()

        # Bulk activity lookup — one query regardless of CCEO count, indexed
        # by both membership predicates (responsible staff, assigned school)
        # so each CCEO's matching set is built in Python, not a DB filter.
        staff_to_ids = defaultdict(set)
        school_to_ids = defaultdict(set)
        activity_info = {}
        for a in acts.values(
            "id", "responsible_staff_id", "school_id", "status", "planned_date"
        ):
            aid = a["id"]
            activity_info[aid] = a
            if a["responsible_staff_id"]:
                staff_to_ids[a["responsible_staff_id"]].add(aid)
            if a["school_id"]:
                school_to_ids[a["school_id"]].add(aid)

        # Bulk verified-SSA cycle scores for every school assigned to any
        # CCEO — two queries total instead of two per CCEO. Grouped by
        # school (not collapsed) so the per-CCEO average exactly replicates
        # the prior per-CCEO Avg() aggregate.
        all_school_ids = set()
        for cceos in pl_cceos.values():
            for c in cceos:
                all_school_ids |= c["school_ids"]
        cur_by_school = defaultdict(list)
        old_by_school = defaultdict(list)
        if latest and prev and all_school_ids:
            for sid, sc in SsaRecord.objects.filter(
                school_id__in=all_school_ids, verification_status="confirmed", fy=latest
            ).values_list("school_id", "average_score"):
                cur_by_school[sid].append(sc)
            for sid, sc in SsaRecord.objects.filter(
                school_id__in=all_school_ids, verification_status="confirmed", fy=prev
            ).values_list("school_id", "average_score"):
                old_by_school[sid].append(sc)

        rows = []
        for pl in pls:
            for c in pl_cceos[pl.id]:
                ids = {c["staff_id"]}
                if c["user_id"]:
                    ids.add(c["user_id"])
                matching_ids = set()
                for sid in ids:
                    matching_ids |= staff_to_ids.get(sid, set())
                for schid in c["school_ids"]:
                    matching_ids |= school_to_ids.get(schid, set())

                done = sum(
                    1
                    for aid in matching_ids
                    if activity_info[aid]["status"] in COMPLETED_STATUSES
                )
                overdue = sum(
                    1
                    for aid in matching_ids
                    if activity_info[aid]["planned_date"] is not None
                    and activity_info[aid]["planned_date"] < today
                    and activity_info[aid]["status"] in overdue_statuses
                )

                ssa_improve = None
                if latest and prev and c["school_ids"]:
                    cur_vals = [
                        v
                        for schid in c["school_ids"]
                        for v in cur_by_school.get(schid, [])
                    ]
                    old_vals = [
                        v
                        for schid in c["school_ids"]
                        for v in old_by_school.get(schid, [])
                    ]
                    cur = sum(cur_vals) / len(cur_vals) if cur_vals else None
                    old = sum(old_vals) / len(old_vals) if old_vals else None
                    if cur is not None and old is not None:
                        ssa_improve = round((cur - old) * 10, 1)
                risk = "danger" if overdue >= 4 else ("amber" if overdue else "success")
                rows.append(
                    {
                        "staff_id": c["staff_id"],
                        "name": c["name"],
                        "initials": _initials(c["name"]),
                        "schools": len(c["school_ids"]),
                        "completed": done,
                        "ssa_improve": ssa_improve,
                        "overdue": overdue,
                        "owner_pl": pl.name,
                        "risk_tone": risk,
                    }
                )
        rows.sort(key=lambda r: (-r["overdue"], -r["completed"]))
        return {"rows": rows[:12], "total": len(rows)}

    # ── 10. Impact summary ───────────────────────────────────────────────────
    @staticmethod
    def impact_summary(cd, acts):
        completed = acts.filter(status__in=COMPLETED_STATUSES)
        reached = set(
            completed.exclude(school_id__isnull=True).values_list(
                "school_id", flat=True
            )
        )
        students = (
            School.objects.filter(id__in=reached).aggregate(s=Sum("enrollment"))["s"]
            or 0
        )
        teachers = (
            completed.filter(activity_type__in=TRAINING_TYPES).aggregate(
                s=Sum("teachers_attended")
            )["s"]
            or 0
        )
        leaders = (
            completed.filter(activity_type__in=TRAINING_TYPES).aggregate(
                s=Sum("leaders_attended")
            )["s"]
            or 0
        )
        improved, champions = CDAnalyticsService._improved_and_champions(cd)
        return {
            "students_impacted": int(students),
            "teachers_trained": int(teachers),
            "leaders_trained": int(leaders),
            "schools_improved": improved,
            "champion_candidates": champions,
        }

    @staticmethod
    def _improved_and_champions(cd):
        latest, prev = _cycle_fys(cd.school_ids, cd.fy)
        if not latest:
            return 0, 0
        cur = dict(
            SsaRecord.objects.filter(
                school_id__in=cd.school_ids, verification_status="confirmed", fy=latest
            ).values_list("school_id", "average_score")
        )
        improved = 0
        if prev:
            old = dict(
                SsaRecord.objects.filter(
                    school_id__in=cd.school_ids,
                    verification_status="confirmed",
                    fy=prev,
                ).values_list("school_id", "average_score")
            )
            for sid, sc in cur.items():
                if (
                    sid in old
                    and sc is not None
                    and old[sid] is not None
                    and sc > old[sid]
                ):
                    improved += 1
        # Champion candidates: latest avg >= 8.0 and positive delta.
        champions = 0
        old = (
            dict(
                SsaRecord.objects.filter(
                    school_id__in=cd.school_ids,
                    verification_status="confirmed",
                    fy=prev,
                ).values_list("school_id", "average_score")
            )
            if prev
            else {}
        )
        for sid, sc in cur.items():
            if (
                sc is not None
                and sc >= 8.0
                and (sid not in old or old[sid] is None or sc >= old[sid])
            ):
                champions += 1
        return improved, champions

    # ── 11. Regional summary ─────────────────────────────────────────────────
    @staticmethod
    def regional_summary(cd):
        from apps.geography.models import Region

        latest, prev = _cycle_fys(cd.school_ids, cd.fy)
        schools = School.objects.filter(id__in=cd.school_ids)
        region_ids = list(
            schools.exclude(region__isnull=True)
            .order_by("region_id")
            .values_list("region_id", flat=True)
            .distinct()
        )
        names = dict(Region.objects.filter(id__in=region_ids).values_list("id", "name"))

        # Batch-fetch once instead of ~5 queries per region (this also fixed
        # a pre-existing bug: "cur" was recomputed via a 4th, wholly redundant
        # query identical to "avg" above it). School->region/district maps,
        # both FY cycles' confirmed SSA records in one query, grouped in Python.
        school_region = dict(
            schools.exclude(region__isnull=True).values_list("id", "region_id")
        )
        district_by_region: dict = {}
        for sid, did in schools.exclude(district__isnull=True).values_list(
            "id", "district_id"
        ):
            rid = school_region.get(sid)
            if rid is not None:
                district_by_region.setdefault(rid, set()).add(did)

        region_scores: dict = {}  # (region_id, fy) -> [average_score, ...]
        if latest:
            fys = [latest] if not prev else [latest, prev]
            for sid, fy, score in SsaRecord.objects.filter(
                school_id__in=cd.school_ids,
                verification_status="confirmed",
                fy__in=fys,
            ).values_list("school_id", "fy", "average_score"):
                rid = school_region.get(sid)
                if rid is not None:
                    region_scores.setdefault((rid, fy), []).append(score)

        def _mean(values):
            values = [v for v in values if v is not None]
            return (sum(values) / len(values)) if values else None

        rows = []
        for rid in region_ids:
            avg = trend = None
            if latest:
                avg = _norm(_mean(region_scores.get((rid, latest), [])))
                if prev:
                    cur = _mean(region_scores.get((rid, latest), []))
                    old = _mean(region_scores.get((rid, prev), []))
                    if cur is not None and old is not None:
                        trend = round((cur - old) * 10, 1)
            n_districts = len(district_by_region.get(rid, set()))
            rows.append(
                {
                    "id": rid,
                    "name": names.get(rid, "Region"),
                    "avg_ssa": avg,
                    "avg_tone": ssa_band(avg)[2],
                    "districts": n_districts,
                    "trend": trend,
                }
            )
        rows.sort(key=lambda r: (r["avg_ssa"] is None, -(r["avg_ssa"] or 0)))
        return {"rows": rows, "latest_fy": latest, "prev_fy": prev}

    # ── 12. Budget & finance health ──────────────────────────────────────────
    @staticmethod
    def budget_finance_health(cd):
        """Country finance health from the real activity-advance pipeline
        (AdvanceRequest → cost lines). Utilization = disbursed / requested."""
        qs = CDAnalyticsService._advance_qs(cd)

        def amt(field_name, statuses=None):
            q = qs.filter(status__in=statuses) if statuses else qs
            return int(q.aggregate(s=Sum(field_name))["s"] or 0)

        requested = amt("amount")
        pending = amt(
            "amount",
            [
                "pending_responsible_confirmation",
                "submitted",
                "submitted_to_pl",
                "submitted_to_cd",
            ],
        )
        confirmed = amt("amount", ["confirmed_for_advance"])
        disbursed = amt(
            "disbursed_amount", ["disbursed", "accountability_pending", "accounted"]
        )
        accounted = amt("accounted_amount", ["accounted"])
        returned = amt("returned_amount")

        # Quarterly disbursement trend for the tabbed line chart.
        quarter_labels, quarter_vals = [], []
        for q in ("Q1", "Q2", "Q3", "Q4"):
            quarter_labels.append(q)
            quarter_vals.append(
                int(qs.filter(activity__quarter=q).aggregate(s=Sum("amount"))["s"] or 0)
            )

        return {
            "utilization_pct": _pct(disbursed, requested),
            "requested": requested,
            "disbursed": disbursed,
            "accounted": accounted,
            "quarter_labels": quarter_labels,
            "quarter_vals": quarter_vals,
            "statuses": [
                {"label": "Requested (pipeline)", "amount": requested, "tone": "info"},
                {"label": "Pending Confirmation", "amount": pending, "tone": "warning"},
                {"label": "Confirmed for Advance", "amount": confirmed, "tone": "info"},
                {"label": "Disbursed", "amount": disbursed, "tone": "success"},
                {"label": "Accounted", "amount": accounted, "tone": "success"},
                {"label": "Returned", "amount": returned, "tone": "danger"},
            ],
        }

    # ── 13. Operational risk ─────────────────────────────────────────────────
    @staticmethod
    def operational_risk(cd, acts):
        schools = School.objects.filter(id__in=cd.school_ids)
        completed = acts.filter(status__in=COMPLETED_STATUSES)
        latest, _ = _cycle_fys(cd.school_ids, cd.fy)
        date.today()

        no_ssa = schools.exclude(current_fy_ssa_status="done").count()
        visited = set(
            completed.filter(activity_type__in=VISIT_TYPES)
            .exclude(school_id__isnull=True)
            .values_list("school_id", flat=True)
        )
        trained = set(
            completed.filter(activity_type__in=TRAINING_TYPES)
            .exclude(school_id__isnull=True)
            .values_list("school_id", flat=True)
        )
        all_ids = set(schools.values_list("id", flat=True))
        no_visit = len(all_ids - visited)
        no_training = len(all_ids - trained)
        low_ssa = 0
        if latest:
            low_ssa = (
                SsaRecord.objects.filter(
                    school_id__in=cd.school_ids,
                    verification_status="confirmed",
                    fy=latest,
                    average_score__lt=5.0,
                )
                .values("school_id")
                .distinct()
                .count()
            )
        evidence_pending = (
            acts.filter(
                status__in=COMPLETED_STATUSES,
                activity_type__in=VISIT_TYPES + TRAINING_TYPES,
            )
            .exclude(evidence_status="accepted")
            .count()
        )
        ia_pending = acts.filter(status="awaiting_ia_verification").count()
        finance_pending = (
            acts.filter(
                advance_requests__status__in=["disbursed", "accountability_pending"]
            )
            .exclude(status__in=COMPLETED_STATUSES)
            .distinct()
            .count()
        )
        # Program proof vs money proof — never merged (mandate: Activity SF ID
        # is program evidence; the NetSuite code closes accountability).
        sf_id_pending = (
            acts.filter(
                status__in=COMPLETED_STATUSES,
                activity_type__in=VISIT_TYPES + TRAINING_TYPES + CLUSTER_MEETING_TYPES,
            )
            .filter(
                Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id="")
            )
            .count()
        )
        from apps.fund_requests.models import AdvanceRequest as _Adv

        accountability_pending = _Adv.objects.filter(
            fy=cd.fy,
            status__in=["disbursed", "accountability_pending"],
            accounted_amount=0,
        ).count()

        def card(label, count, tone, aging="", link=""):
            return {
                "label": label,
                "count": count,
                "tone": tone,
                "aging": aging,
                "link": link,
            }

        return [
            card("No SSA Schools", no_ssa, "danger", "", "?drill=risk&issue=no_ssa"),
            card(
                "No Visit",
                no_visit,
                "warning",
                "60+ days",
                "?drill=risk&issue=no_visit",
            ),
            card(
                "No Training",
                no_training,
                "warning",
                "90+ days",
                "?drill=risk&issue=no_training",
            ),
            card("Low SSA (<50%)", low_ssa, "warning", "", "?drill=risk&issue=low_ssa"),
            card(
                "Evidence Pending",
                evidence_pending,
                "info",
                "",
                "?drill=risk&issue=evidence",
            ),
            card(
                "Activity SF ID Pending",
                sf_id_pending,
                "warning",
                "7+ days",
                "?drill=risk&issue=sf_id",
            ),
            card("IA Pending", ia_pending, "info", "30+ days", "?drill=risk&issue=ia"),
            card("Finance Pending", finance_pending, "info", "", "?drill=budget"),
            card(
                "Accountability Pending",
                accountability_pending,
                "info",
                "14+ days",
                "?drill=budget",
            ),
        ]

    # ── filter options ───────────────────────────────────────────────────────
    @staticmethod
    def filter_options(cd):
        from apps.core.fy import fy_options
        from apps.geography.models import District
        from apps.clusters.models import Cluster
        from apps.partners.models import Partner

        schools = School.objects.filter(deleted_at__isnull=True)
        district_ids = list(
            schools.exclude(district__isnull=True)
            .order_by("district_id")
            .values_list("district_id", flat=True)
            .distinct()
        )
        cluster_ids = list(
            schools.exclude(cluster_id__isnull=True)
            .exclude(cluster_id="")
            .order_by("cluster_id")
            .values_list("cluster_id", flat=True)
            .distinct()
        )
        return {
            "fy_options": fy_options(),
            "quarters": ["Q1", "Q2", "Q3", "Q4"],
            "pls": [{"id": p.id, "name": p.name} for p in CDAnalyticsService._pls()],
            "districts": list(
                District.objects.filter(id__in=district_ids)
                .values("id", "name")
                .order_by("name")
            ),
            "clusters": list(
                Cluster.objects.filter(id__in=cluster_ids)
                .values("id", "name")
                .order_by("name")
            ),
            "partners": list(
                Partner.objects.all().values("id", "name").order_by("name")
            ),
            "activity_types": [
                ("school_visit", "School Visits"),
                ("training", "Trainings"),
                ("cluster_meeting", "Cluster Meetings"),
                ("partner_activity", "Partner"),
            ],
        }

    # ── Export ───────────────────────────────────────────────────────────────
    @staticmethod
    def export_rows(user, fy=None, quarter=None, month=None, filters=None):
        """PL-oversight roster for CSV export (read-only)."""
        fy = fy or get_operational_fy()
        cd = resolve_cd_scope(fy, quarter, month, filters or {})
        acts = _country_activities(cd)
        _prime_target_series(cd)
        return CDAnalyticsService.pl_oversight(cd, acts)["rows"]

    # ── Leadership To-Dos (derived live — oversight workflows only) ───────────
    @staticmethod
    def cd_todos(user, fy=None, quarter=None, month=None, filters=None) -> list[dict]:
        """Country oversight signals surfaced as CD leadership To-Dos, derived
        live from state (no storage; auto-close when the state resolves). Every
        To-Do routes to an oversight workflow — never field execution."""
        fy = fy or get_operational_fy()
        cd = resolve_cd_scope(fy, quarter, month, filters or {})
        acts = _country_activities(cd)
        todos = []

        # High/critical-risk PL teams → request a recovery plan.
        for r in CDAnalyticsService.pl_oversight(cd, acts)["rows"]:
            if r["risk"] in ("High Risk", "Critical Risk"):
                todos.append(
                    {
                        "id": f"cd-recovery-{r['id']}",
                        "title": "Request Recovery Plan from PL",
                        "description": f"{r['name']}'s team is {r['risk']} — {r['schools_at_risk']} schools at risk.",
                        "category": "PL Oversight",
                        "priority": "high",
                        "owner": "PL",
                        "action_label": "Review PL",
                        "action_url": "/analytics/country-director",
                    }
                )

        # Recommended actions → leadership To-Dos (owner CD or PL).
        for a in CDAnalyticsService.recommended_actions(cd, acts)["items"]:
            todos.append(
                {
                    "id": f"cd-rec-{a['issue'][:20]}",
                    "title": a["issue"],
                    "description": f"{a['count']} flagged — responsible: {a['owner']}.",
                    "category": "Recommended Action",
                    "priority": "high" if a["severity"] == "danger" else "medium",
                    "owner": a["owner"],
                    "action_label": "Review",
                    "action_url": f"/analytics/country-director/drilldown{a['link']}&fy={fy}",
                }
            )

        # Weekly fund requests escalated to the CD → approve.
        from apps.fund_requests.models import WeeklyFundRequest

        awaiting = WeeklyFundRequest.objects.filter(
            fy=fy, status="submitted_to_cd"
        ).count()
        if awaiting:
            todos.append(
                {
                    "id": "cd-weekly-approve",
                    "title": "Approve PL Weekly Fund Request",
                    "description": f"{awaiting} weekly fund request(s) awaiting your approval.",
                    "category": "Finance",
                    "priority": "high",
                    "owner": "CD",
                    "action_label": "Open Approvals",
                    "action_url": "/fund-requests/weekly",
                }
            )

        # Country budget under-utilization → review.
        if CDAnalyticsService._budget_utilization(cd) < 50:
            todos.append(
                {
                    "id": "cd-budget-util",
                    "title": "Review Budget Underutilization",
                    "description": "Country disbursement is below 50% of the requested pipeline.",
                    "category": "Finance",
                    "priority": "medium",
                    "owner": "CD",
                    "action_label": "Review Budget",
                    "action_url": "/analytics/country-director",
                }
            )
        return todos[:8]

    # ── Drill-downs (oversight-only — never field execution) ─────────────────
    #
    # Every drawer is a read/oversight view. CD actions surfaced here route to
    # oversight workflows only (view / recommend / assign-follow-up-to-PL /
    # message / escalate / review-budget). No drawer ever exposes schedule-visit,
    # start-activity, upload-evidence or enter-SF-ID actions.
    _OVERSIGHT_ACTIONS = {
        "pl": [
            "View PL",
            "Request Recovery Plan",
            "Message PL",
            "Review Team Targets",
            "Review Budget",
        ],
        "cceo": [
            "View Performance",
            "Message Owner PL",
            "Request PL Follow-up",
            "Create To-Do for PL",
        ],
        "district": [
            "Assign Follow-up to PL",
            "Create Recommendation",
            "Review SSA Risk",
            "Send Message",
        ],
        "region": [
            "Review Regional Report",
            "Assign Follow-up to PL",
            "Escalate to RVP",
        ],
        "partner": [
            "Review Partner Recommendation",
            "Put Under Review",
            "Message Partner Owner",
        ],
        "cluster": ["Assign PL Follow-up", "Create Recommendation", "Review SSA Risk"],
        "risk": [
            "Assign Follow-up to PL",
            "Create Leadership To-Do",
            "Request Recovery Plan",
            "Send Message",
        ],
        "budget": [
            "Review Country Monthly Budget",
            "Review Budget Risk",
            "Send Budget to RVP",
            "Update Cost Catalogue",
        ],
        "ssa": [
            "Assign Follow-up to PL",
            "Create Recommendation",
            "Review SSA Risk District",
        ],
    }

    @staticmethod
    def drilldown(user, drill, params, fy=None, quarter=None, month=None, filters=None):
        fy = fy or get_operational_fy()
        cd = resolve_cd_scope(fy, quarter, month, filters or {})
        acts = _country_activities(cd)
        actions = CDAnalyticsService._OVERSIGHT_ACTIONS.get(
            drill, ["View Details", "Send Message"]
        )
        # Echo the full filter context so drawers never lose FY/quarter/month/
        # PL/district/partner selections when opened or closed.
        base = {
            "actions": actions,
            "oversight_only": True,
            "fy": fy,
            "quarter": quarter,
            "month": month,
            "filters": filters or {},
        }

        if drill == "pl":
            # Target math is read here — refresh so a drilldown opened
            # without a preceding full dashboard load never shows stale credit.
            _refresh_target_ledger(cd)
            return {**base, **CDAnalyticsService._drill_pl(cd, acts, params.get("id"))}
        if drill == "cceo":
            return {
                **base,
                **CDAnalyticsService._drill_cceo(cd, acts, params.get("id")),
            }
        if drill == "district":
            return {
                **base,
                **CDAnalyticsService._drill_district(cd, acts, params.get("id")),
            }
        if drill == "region":
            return {
                **base,
                **CDAnalyticsService._drill_region(cd, acts, params.get("id")),
            }
        if drill == "partner":
            return {
                **base,
                **CDAnalyticsService._drill_partner(cd, acts, params.get("id")),
            }
        if drill == "cluster":
            return {
                **base,
                **CDAnalyticsService._drill_cluster(cd, acts, params.get("id")),
            }
        if drill == "ssa":
            return {
                **base,
                **CDAnalyticsService._drill_ssa(cd, params.get("intervention")),
            }
        if drill == "budget":
            return {
                **base,
                "title": "Budget & Finance Health",
                "subtitle": "Country activity-advance pipeline",
                "finance": CDAnalyticsService.budget_finance_health(cd),
                "kind": "budget",
            }
        if drill == "risk":
            return {
                **base,
                **CDAnalyticsService._drill_risk(cd, acts, params.get("issue")),
            }
        # KPI / generic fallback — country oversight summary.
        return {
            **base,
            "title": "Country Oversight",
            "subtitle": "Leadership summary",
            "kind": "generic",
            "rows": CDAnalyticsService.pl_oversight(cd, acts)["rows"],
        }

    @staticmethod
    def _drill_pl(cd, acts, pl_id):
        pl = User.objects.filter(id=pl_id).first()
        if not pl:
            return {"title": "PL", "subtitle": "Not found", "kind": "pl", "cceos": []}
        cceos = CDAnalyticsService._pl_cceos(pl, cd)
        acts.filter(status__in=COMPLETED_STATUSES)
        latest, prev = _cycle_fys(cd.school_ids, cd.fy)
        rows = []
        all_school_ids = set()
        for c in cceos:
            all_school_ids |= c["school_ids"]
            ids = {c["staff_id"]}
            if c["user_id"]:
                ids.add(c["user_id"])
            c_acts = acts.filter(
                Q(responsible_staff_id__in=ids) | Q(school_id__in=c["school_ids"])
            )
            pct, a, t = CDAnalyticsService._completion_vs_target(
                c["staff_id"],
                c_acts.filter(status__in=COMPLETED_STATUSES),
                cd.fy,
                user_id=c["user_id"],
            )
            rows.append(
                {
                    "name": c["name"],
                    "schools": len(c["school_ids"]),
                    "planned": c_acts.count(),
                    "completed": c_acts.filter(status__in=COMPLETED_STATUSES).count(),
                    "verified": c_acts.filter(status__in=VERIFIED_STATUSES).count(),
                    "target_pct": pct,
                }
            )
        at_risk = (
            School.objects.filter(id__in=all_school_ids)
            .exclude(current_fy_ssa_status="done")
            .count()
        )
        ssa_improve = None
        if latest and prev and all_school_ids:
            cur = SsaRecord.objects.filter(
                school_id__in=all_school_ids, verification_status="confirmed", fy=latest
            ).aggregate(a=Avg("average_score"))["a"]
            old = SsaRecord.objects.filter(
                school_id__in=all_school_ids, verification_status="confirmed", fy=prev
            ).aggregate(a=Avg("average_score"))["a"]
            if cur is not None and old is not None:
                ssa_improve = round((cur - old) * 10, 1)
        return {
            "title": pl.name,
            "subtitle": "PL performance — oversight view",
            "kind": "pl",
            "cceos": rows,
            "schools": len(all_school_ids),
            "schools_at_risk": at_risk,
            "budget_util": CDAnalyticsService._pl_budget(cceos, cd.fy),
            "ssa_improve": ssa_improve,
            "recommended": "Request recovery plan"
            if at_risk > len(all_school_ids) * 0.5
            else "Monitor & support",
        }

    @staticmethod
    def _drill_cceo(cd, acts, staff_id):
        sp = StaffProfile.objects.filter(id=staff_id).select_related("user").first()
        name = sp.user.name if sp and sp.user else "CCEO"
        ids = {staff_id}
        if sp and sp.user_id:
            ids.add(sp.user_id)
        school_ids = set(
            StaffSchoolAssignment.objects.filter(staff_id=staff_id).values_list(
                "school_id", flat=True
            )
        ) & set(cd.school_ids)
        c_acts = acts.filter(
            Q(responsible_staff_id__in=ids) | Q(school_id__in=school_ids)
        )
        rows = [
            {
                "type": _INTERVENTION_LABELS.get(
                    r["activity_type"], (r["activity_type"], "")
                )[0]
                if False
                else r["activity_type"],
                "count": r["n"],
            }
            for r in c_acts.values("activity_type")
            .annotate(n=Count("id"))
            .order_by("-n")
        ]
        return {
            "title": name,
            "subtitle": "CCEO performance — read-only",
            "kind": "cceo",
            "schools": len(school_ids),
            "completed": c_acts.filter(status__in=COMPLETED_STATUSES).count(),
            "activity_rows": rows,
        }

    @staticmethod
    def _drill_district(cd, acts, district_id):
        from apps.geography.models import District

        d = District.objects.filter(id=district_id).first()
        d_school_ids = list(
            School.objects.filter(
                id__in=cd.school_ids, district_id=district_id
            ).values_list("id", flat=True)
        )
        latest, _ = _cycle_fys(cd.school_ids, cd.fy)
        cells = []
        if latest:
            rids = list(
                SsaRecord.objects.filter(
                    school_id__in=d_school_ids,
                    verification_status="confirmed",
                    fy=latest,
                ).values_list("id", flat=True)
            )
            by = {
                r["intervention"]: r["a"]
                for r in SsaScore.objects.filter(ssa_record_id__in=rids)
                .values("intervention")
                .annotate(a=Avg("score"))
            }
            for v, label, code in SSA_INTERVENTIONS:
                pct = _norm(by.get(v))
                cells.append({"label": label, "pct": pct, "tone": ssa_band(pct)[2]})
        at_risk = (
            School.objects.filter(id__in=d_school_ids)
            .exclude(current_fy_ssa_status="done")
            .count()
        )
        return {
            "title": (d.name if d else "District"),
            "subtitle": "District performance — oversight view",
            "kind": "district",
            "schools": len(d_school_ids),
            "schools_at_risk": at_risk,
            "cells": cells,
        }

    @staticmethod
    def _drill_region(cd, acts, region_id):
        from apps.geography.models import Region

        r = Region.objects.filter(id=region_id).first()
        r_school_ids = list(
            School.objects.filter(
                id__in=cd.school_ids, region_id=region_id
            ).values_list("id", flat=True)
        )
        latest, prev = _cycle_fys(cd.school_ids, cd.fy)
        avg = (
            _norm(
                SsaRecord.objects.filter(
                    school_id__in=r_school_ids,
                    verification_status="confirmed",
                    fy=latest,
                ).aggregate(a=Avg("average_score"))["a"]
            )
            if latest
            else None
        )
        districts = list(
            School.objects.filter(id__in=r_school_ids)
            .exclude(district__isnull=True)
            .values("district__name")
            .annotate(n=Count("id"))
            .order_by("-n")
        )
        return {
            "title": (r.name if r else "Region"),
            "subtitle": "Regional drill-down — oversight view",
            "kind": "region",
            "schools": len(r_school_ids),
            "avg_ssa": avg,
            "districts": [
                {"name": x["district__name"], "schools": x["n"]} for x in districts
            ],
        }

    @staticmethod
    def _drill_partner(cd, acts, partner_id):
        from apps.partners.models import Partner

        rows = CDAnalyticsService.partner_performance(cd, acts)["rows"]
        row = next((r for r in rows if r["id"] == partner_id), None)
        p = Partner.objects.filter(id=partner_id).first()
        return {
            "title": (p.name if p else "Partner"),
            "subtitle": "Partner impact — recommendation review",
            "kind": "partner",
            "detail": row,
        }

    @staticmethod
    def _drill_cluster(cd, acts, cluster_id):
        from apps.clusters.models import Cluster

        _, cluster_school = CDAnalyticsService._cluster_membership(cd, acts)
        c_ids = list(cluster_school.get(cluster_id, set()))
        latest, _ = _cycle_fys(cd.school_ids, cd.fy)
        cells = []
        if latest and c_ids:
            rids = list(
                SsaRecord.objects.filter(
                    school_id__in=c_ids, verification_status="confirmed", fy=latest
                ).values_list("id", flat=True)
            )
            by = {
                r["intervention"]: r["a"]
                for r in SsaScore.objects.filter(ssa_record_id__in=rids)
                .values("intervention")
                .annotate(a=Avg("score"))
            }
            for v, label, code in SSA_INTERVENTIONS:
                pct = _norm(by.get(v))
                cells.append({"label": label, "pct": pct, "tone": ssa_band(pct)[2]})
        c = Cluster.objects.filter(id=cluster_id).first()
        c_acts = acts.filter(cluster_id=cluster_id)
        return {
            "title": (c.name if c else "Cluster"),
            "subtitle": "Cluster SSA & activity — oversight view",
            "kind": "cluster",
            "schools": len(c_ids),
            "cells": cells,
            "trainings": c_acts.filter(
                activity_type__in=TRAINING_TYPES + CLUSTER_MEETING_TYPES,
                status__in=COMPLETED_STATUSES,
            ).count(),
            "visits": c_acts.filter(
                activity_type__in=VISIT_TYPES, status__in=COMPLETED_STATUSES
            ).count(),
        }

    @staticmethod
    def _drill_ssa(cd, intervention):
        latest, prev = _cycle_fys(cd.school_ids, cd.fy)
        label = _INTERVENTION_LABELS.get(
            intervention, (intervention or "Intervention", "")
        )[0]
        rows = []
        if latest and intervention:
            schools = School.objects.filter(id__in=cd.school_ids)
            for d in (
                schools.exclude(district__isnull=True)
                .order_by("district_id")
                .values("district_id", "district__name")
                .distinct()
            ):
                d_ids = list(
                    schools.filter(district_id=d["district_id"]).values_list(
                        "id", flat=True
                    )
                )
                rids = SsaRecord.objects.filter(
                    school_id__in=d_ids, verification_status="confirmed", fy=latest
                ).values_list("id", flat=True)
                a = SsaScore.objects.filter(
                    ssa_record_id__in=rids, intervention=intervention
                ).aggregate(x=Avg("score"))["x"]
                pct = _norm(a)
                rows.append(
                    {"name": d["district__name"], "pct": pct, "tone": ssa_band(pct)[2]}
                )
            rows.sort(key=lambda r: (r["pct"] is None, r["pct"] or 0))
        return {
            "title": f"SSA — {label}",
            "subtitle": "Intervention weakness by district",
            "kind": "ssa",
            "rows": rows,
        }

    @staticmethod
    def _drill_risk(cd, acts, issue):
        schools = School.objects.filter(id__in=cd.school_ids)
        completed = acts.filter(status__in=COMPLETED_STATUSES)
        latest, _ = _cycle_fys(cd.school_ids, cd.fy)
        title = {
            "no_ssa": "Schools without SSA",
            "no_visit": "Schools with No Visit",
            "no_training": "Schools with No Training",
            "low_ssa": "Low-SSA Schools (<50%)",
            "evidence": "Evidence Pending",
            "ia": "IA Pending",
        }.get(issue, "Operational Risk")
        rows = []
        if issue == "no_ssa":
            qs = schools.exclude(current_fy_ssa_status="done")[:200]
            rows = [
                {
                    "school": s.name,
                    "district": (
                        s.district.name if s.district_id and s.district else "—"
                    ),
                    "detail": "No verified SSA this cycle",
                }
                for s in qs
            ]
        elif issue == "low_ssa" and latest:
            low_ids = SsaRecord.objects.filter(
                school_id__in=cd.school_ids,
                verification_status="confirmed",
                fy=latest,
                average_score__lt=5.0,
            ).values_list("school_id", flat=True)[:200]
            for s in School.objects.filter(id__in=list(low_ids)):
                rows.append(
                    {
                        "school": s.name,
                        "district": (
                            s.district.name if s.district_id and s.district else "—"
                        ),
                        "detail": "SSA below 50%",
                    }
                )
        elif issue in ("no_visit", "no_training"):
            atype = VISIT_TYPES if issue == "no_visit" else TRAINING_TYPES
            reached = set(
                completed.filter(activity_type__in=atype)
                .exclude(school_id__isnull=True)
                .values_list("school_id", flat=True)
            )
            miss = [sid for sid in cd.school_ids if sid not in reached][:200]
            for s in School.objects.filter(id__in=miss):
                rows.append(
                    {
                        "school": s.name,
                        "district": (
                            s.district.name if s.district_id and s.district else "—"
                        ),
                        "detail": (
                            "No visit" if issue == "no_visit" else "No training"
                        ),
                    }
                )
        return {
            "title": title,
            "subtitle": f"{len(rows)} shown — assign follow-up to responsible PL",
            "kind": "risk",
            "rows": rows,
        }
