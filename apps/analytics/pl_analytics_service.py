"""Program Lead Analytics — the PL's decision-intelligence cockpit.

Every dataset here is scoped to the PL's supervised team (the CCEOs the PL
supervises + the schools/clusters/districts assigned to those CCEOs). It never
returns country-wide data and never leaks another PL's portfolio. All analytics
are computed in the backend from real workflow state — no frontend math, no
fabricated values. When the underlying data is empty (no SSA, no targets set),
the honest empty/zero/"No SSA" state is returned rather than an invented number.

Scoping spine
-------------
resolve_user_scope(pl) gives, for a Program Lead:
  - supervised_staff_ids : StaffProfile ids of supervised CCEOs
  - school_ids           : schools assigned to those CCEOs (+ PL's own)
  - district_ids / cluster_ids : derived from those schools
Activity.responsible_staff_id is *canonically* a StaffProfile id, but legacy /
migrated rows key it by User.id, so the team activity set is the union of both
id forms OR the portfolio schools — see `_team_activity_qs`.

Two distinct measurement concepts, kept separate on purpose:
  - EXECUTION / completion  → COMPLETED_STATUSES over the team activity set.
    Answers "did the field work happen?" (KPI Activities Completed, the
    completed bars, activity tracking, staff-vs-partner, donor counts).
  - TEAM EXECUTION PROGRESS  → _cceo_target/_team_target below: completed
    (COMPLETED_STATUSES) vs StaffTargetProfile target, unweighted. Answers
    "how much of the raw field plan is done right now?" — deliberately NOT
    IA-verified, so a PL sees same-day progress. This is a DIFFERENT number
    from, and must never share a label with, the canonical weighted Team
    Target Achievement % on the Team Targets page (TargetAchievementLedger +
    TargetArea.weight — see apps.targets.my_targets.weighted_period_pct).
    Rendered here as "Team Execution Progress %", never "Team Target
    Achievement %".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.db.models import Avg, Count, Q, Sum

from apps.accounts.models import StaffProfile, StaffTargetProfile
from apps.activities.models import Activity
from apps.core.enums import SsaIntervention
from apps.core.fy import (
    get_fy_date_range,
    get_month_date_range,
    get_operational_fy,
)
from apps.core.scoping import resolve_user_scope
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore
from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES, VISIT_TYPES
# Target achievement is completed-vs-StaffTargetProfile (the spec's definition),
# computed inline; the stricter apps.targets.performance engine is intentionally
# not used here (it measures IA-verified achievement, not field execution).

# ── Status + type vocabularies (mirror the CD dashboard for consistency) ──────
# "Achieved / completed" for execution tracking — the field work is done or
# beyond. (The CD dashboard uses ["completed","closed"]; we also count the
# post-completion states so a verified/cleared activity still reads as done.)
COMPLETED_STATUSES = (
    "completed",
    "closed",
    "ia_verified",
    "accountant_confirmed",
    "salesforce_id_required",
    "awaiting_ia_verification",
    "submitted_to_pl",
    "evidence_accepted",
)
PLANNED_STATUSES = (
    "planned",
    "scheduled",
    "in_progress",
    "completion_started",
    "evidence_uploaded",
    "rescheduled",
    "returned_by_pl",
    "assigned_to_partner",
    "partner_scheduled",
)
VERIFIED_STATUSES = ("ia_verified", "closed")

SSA_COLLECTION_TYPES = (
    "ssa_activity",
    "baseline_ssa_visit",
    "school_visit_ssa_collection",
    "cluster_training_ssa_collection",
    "cluster_meeting_ssa_review",
    "partner_ssa_collection",
    "core_assessment_visit",
)
PARTNER_TYPES = ("partner_activity",)
PROJECT_TYPES = ("project_activity",)

# SSA interventions in the canonical CSV column order (2026-07-15
# clarification): (stored value, label, code).
SSA_INTERVENTIONS = [
    ("christlike_behaviour", "Christlike Behaviour", "CB"),
    ("exposure_to_word_of_god", "Exposure to the Word of God", "WOG"),
    ("financial_health", "Financial Health", "FH"),
    ("leadership", "Leadership", "Lship"),
    ("government_requirement", "Government Requirements", "GR"),
    ("learning_environment", "Learning Environment", "LE"),
    ("teaching_environment", "Teacher's Environment", "TE"),
    ("enrolment", "Enrolment", "Erlm't"),
]
_INTERVENTION_LABELS = {v: (label, code) for v, label, code in SSA_INTERVENTIONS}

MONTHS_SHORT = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}


# ── SSA banding — the canonical mandate bands (§5): Critical 0-4.9 /
# Warning 5-6.9 / Improving 7-7.9 / Strong 8-10 on the 0-10 score. This
# wrapper takes the normalized 0-100 percentage the analytics layer works in
# and delegates to the single source of truth in apps.core.enums.
def ssa_band(pct: float | None):
    """Classify a normalized SSA percentage into the canonical 4 bands.
    Returns (label, hex, tone). `None`/no-data → a neutral "No SSA" band."""
    from apps.core.enums import ssa_score_band

    return ssa_score_band(None if pct is None else pct / 10.0)


def _norm(score: float | None) -> float | None:
    """SSA score is out of 10; normalize to a 0-100 percentage."""
    return round(score * 10, 1) if score is not None else None


def _pct(n: int, d: int) -> int:
    return round(n / d * 100) if d else 0


def _sparkline(values: list[float]) -> str:
    """Build an inline-SVG polyline `points` string (viewBox 0 0 60 20) from a
    series — the same hand-built sparkline the finance KPI cards use."""
    if not values:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    n = len(values)
    step = 60 / (n - 1) if n > 1 else 60
    pts = []
    for i, v in enumerate(values):
        x = round(i * step, 1)
        y = round(18 - ((v - lo) / span) * 16, 1)  # 2..18 padded band
        pts.append(f"{x},{y}")
    return " ".join(pts)


# ── PL team scope ─────────────────────────────────────────────────────────────
@dataclass
class PLScope:
    user: object
    pl_staff_id: str | None
    cceos: list = field(
        default_factory=list
    )  # [{staff_id,user_id,name,initials,school_ids}]
    responsible_ids: set = field(default_factory=set)  # staff_ids ∪ user_ids
    school_ids: list = field(default_factory=list)
    district_ids: list = field(default_factory=list)
    cluster_ids: list = field(default_factory=list)
    school_filtered: bool = False  # a district/cluster/type filter narrowed schools


def _initials(name: str) -> str:
    return "".join(p[0].upper() for p in (name or "").split() if p)[:2] or "CC"


def resolve_pl_scope(user, filters: dict | None = None) -> PLScope:
    """Resolve the supervised-team portfolio for a Program Lead, applying the
    school-narrowing filters (cceo / district / cluster / school_type)."""
    filters = filters or {}
    scope = resolve_user_scope(user)
    pl_staff_id = getattr(user, "staff_profile_id", None)

    cceo_sps = list(
        StaffProfile.objects.filter(id__in=scope.supervised_staff_ids).select_related(
            "user"
        )
    )
    # Optional single-CCEO filter.
    cceo_filter = (filters.get("cceo") or "").strip()
    if cceo_filter:
        cceo_sps = [
            sp for sp in cceo_sps if sp.id == cceo_filter or sp.user_id == cceo_filter
        ]

    from apps.accounts.models import StaffSchoolAssignment

    cceos = []
    responsible_ids: set = set()
    cceo_sp_ids = [sp.id for sp in cceo_sps]
    # school ids per CCEO (for CCEO-scoped counts + the filter). Assignment
    # rows can be stale (duplicates / soft-deleted schools) — intersect with
    # the active school set so pure-Python len() counts can't inflate.
    assign = StaffSchoolAssignment.objects.filter(staff_id__in=cceo_sp_ids).values_list(
        "staff_id", "school_id"
    )
    assigned_ids = {school_id for _, school_id in assign}
    active_ids = set(
        School.objects.filter(id__in=assigned_ids).values_list("id", flat=True)
    )  # School.objects is soft-delete-filtered
    per_cceo_schools: dict[str, set] = {}
    for staff_id, school_id in assign:
        if school_id in active_ids:
            per_cceo_schools.setdefault(staff_id, set()).add(school_id)

    for sp in cceo_sps:
        name = (sp.user.name if sp.user else None) or sp.title or "CCEO"
        responsible_ids.add(sp.id)
        if sp.user_id:
            responsible_ids.add(sp.user_id)
        cceos.append(
            {
                "staff_id": sp.id,
                "user_id": sp.user_id,
                "name": name,
                "initials": _initials(name),
                "school_ids": per_cceo_schools.get(sp.id, set()),
            }
        )

    # Base portfolio school set (own + team), active schools only. If a
    # single CCEO is selected, narrow to that CCEO's schools.
    if cceo_filter:
        school_ids = set()
        for c in cceos:
            school_ids |= c["school_ids"]
    else:
        school_ids = set(
            School.objects.filter(id__in=set(scope.school_ids)).values_list(
                "id", flat=True
            )
        )

    school_filtered = bool(cceo_filter)
    # District / cluster / school-type filters re-query School.
    district = (filters.get("district") or "").strip()
    cluster = (filters.get("cluster") or "").strip()
    school_type = (filters.get("school_type") or "").strip()
    if district or cluster or school_type:
        sq = School.objects.filter(id__in=school_ids)
        if district:
            sq = sq.filter(district_id=district)
        if cluster:
            sq = sq.filter(cluster_id=cluster)
        if school_type:
            sq = sq.filter(school_type=school_type)
        school_ids = set(sq.values_list("id", flat=True))
        school_filtered = True

    return PLScope(
        user=user,
        pl_staff_id=pl_staff_id,
        cceos=cceos,
        responsible_ids=responsible_ids,
        school_ids=list(school_ids),
        district_ids=list(scope.district_ids),
        cluster_ids=list(scope.cluster_ids),
        school_filtered=school_filtered,
    )


def _team_activity_qs(pls: PLScope, fy: str, quarter: str | None, filters: dict):
    """The team's activity set for the period. When a school-narrowing filter
    is active, scope purely by the filtered schools (so the filter bites);
    otherwise use the union of team-owned OR portfolio-school activities."""
    base = Activity.objects.filter(fy=fy, deleted_at__isnull=True)
    if pls.school_filtered:
        base = base.filter(school_id__in=pls.school_ids)
    else:
        base = base.filter(
            Q(responsible_staff_id__in=pls.responsible_ids)
            | Q(school_id__in=pls.school_ids)
        )
    if quarter:
        base = base.filter(quarter=quarter)
    atype = (filters.get("activity_type") or "").strip()
    if atype:
        base = base.filter(activity_type=atype)
    partner = (filters.get("partner") or "").strip()
    if partner:
        base = base.filter(assigned_partner_id=partner)
    return base


# ── Facade ────────────────────────────────────────────────────────────────────
class PLAnalyticsService:
    """Single entry point for the PL Analytics cockpit. Every method is
    role-scoped through resolve_pl_scope and takes (user, fy, quarter, filters)
    — satisfying the PLAnalytics*Service contract from the spec as methods of
    one cohesive service."""

    @staticmethod
    def get_dashboard(
        user,
        fy: str | None = None,
        quarter: str | None = None,
        filters: dict | None = None,
    ) -> dict:
        fy = fy or get_operational_fy()
        filters = dict(filters or {})
        quarter = (quarter or filters.get("quarter") or "").strip() or None
        pls = resolve_pl_scope(user, filters)

        kpis = PLAnalyticsService.kpis(pls, fy, quarter, filters)
        return {
            "fy": fy,
            "quarter": quarter,
            "filters": filters,
            "kpi_strip_items": kpis["items"],
            "team_performance": PLAnalyticsService.team_performance(
                pls, fy, quarter, filters
            ),
            "ssa_interventions": PLAnalyticsService.ssa_interventions(pls, fy),
            "district_performance": PLAnalyticsService.district_performance(
                pls, fy, quarter, filters
            ),
            "cluster_performance": PLAnalyticsService.cluster_performance(
                pls, fy, quarter, filters
            ),
            "impact_summary": PLAnalyticsService.impact_summary(
                pls, fy, quarter, filters
            ),
            "cceo_performance": PLAnalyticsService.cceo_performance(
                pls, fy, quarter, filters
            ),
            "insights": PLAnalyticsService.insights(pls, fy, quarter, filters),
            "activity_tracking": PLAnalyticsService.activity_tracking(
                pls, fy, quarter, filters
            ),
            "staff_partner": PLAnalyticsService.staff_partner_performance(
                pls, fy, quarter, filters
            ),
            "core_champion": PLAnalyticsService.core_champion(pls, fy),
            "risk_list": PLAnalyticsService.risk_list(pls, fy, quarter, filters),
            "donor_snapshot": PLAnalyticsService.donor_snapshot(
                pls, fy, quarter, filters
            ),
            "filter_options": PLAnalyticsService.filter_options(pls, user),
            "scope_meta": {
                "cceo_count": len(pls.cceos),
                "school_count": len(pls.school_ids),
                "district_count": len(pls.district_ids),
                "cluster_count": len(pls.cluster_ids),
            },
        }

    # ── Filter dropdown options (all scoped) ─────────────────────────────────
    @staticmethod
    def filter_options(pls: PLScope, user) -> dict:
        from apps.core.fy import fy_options
        from apps.geography.models import District
        from apps.clusters.models import Cluster
        from apps.partners.models import PartnerAssignment

        schools = School.objects.filter(id__in=pls.school_ids)
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
        districts = list(
            District.objects.filter(id__in=district_ids)
            .values("id", "name")
            .order_by("name")
        )
        clusters = list(
            Cluster.objects.filter(id__in=cluster_ids)
            .values("id", "name")
            .order_by("name")
        )
        # Partners active in the portfolio (assigned to portfolio schools/clusters).
        partner_ids = list(
            PartnerAssignment.objects.filter(
                Q(school_id__in=pls.school_ids) | Q(cluster_id__in=cluster_ids)
            )
            .values_list("partner_id", flat=True)
            .distinct()
        )
        from apps.partners.models import Partner

        partners = list(
            Partner.objects.filter(id__in=partner_ids)
            .values("id", "name")
            .order_by("name")
        )
        school_types = list(
            schools.exclude(school_type="")
            .order_by("school_type")
            .values_list("school_type", flat=True)
            .distinct()
        )
        return {
            "fy_options": fy_options(),
            "quarters": ["Q1", "Q2", "Q3", "Q4"],
            "districts": districts,
            "clusters": clusters,
            "cceos": [{"id": c["staff_id"], "name": c["name"]} for c in pls.cceos],
            "partners": partners,
            "school_types": sorted(school_types),
            "activity_types": [
                ("school_visit", "School Visits"),
                ("training", "Trainings"),
                ("cluster_meeting", "Cluster Meetings"),
                ("ssa_activity", "SSA Collection"),
                ("partner_activity", "Partner Activities"),
                ("project_activity", "Project Activities"),
            ],
        }

    # ── A/prev period helper ─────────────────────────────────────────────────
    @staticmethod
    def _prev_quarter(quarter: str | None) -> str | None:
        order = ["Q1", "Q2", "Q3", "Q4"]
        if quarter in order and order.index(quarter) > 0:
            return order[order.index(quarter) - 1]
        return None

    # ── KPI strip (12) ───────────────────────────────────────────────────────
    @staticmethod
    def kpis(pls: PLScope, fy: str, quarter: str | None, filters: dict) -> dict:
        acts = _team_activity_qs(pls, fy, quarter, filters)
        completed = acts.filter(status__in=COMPLETED_STATUSES)
        schools = School.objects.filter(id__in=pls.school_ids)

        team_target_pct, cceos_on_track = PLAnalyticsService._team_target(
            pls, fy, quarter, filters
        )
        schools_total = schools.count()
        schools_without_ssa = schools.exclude(current_fy_ssa_status="done").count()

        visited_school_ids = set(
            completed.filter(activity_type__in=VISIT_TYPES)
            .exclude(school_id__isnull=True)
            .values_list("school_id", flat=True)
        )
        schools_not_visited = max(0, schools_total - len(visited_school_ids))
        trained_school_ids = set(
            completed.filter(activity_type__in=TRAINING_TYPES)
            .exclude(school_id__isnull=True)
            .values_list("school_id", flat=True)
        )
        schools_not_trained = max(0, schools_total - len(trained_school_ids))

        def _rate(types):
            planned = acts.filter(activity_type__in=types).count()
            done = completed.filter(activity_type__in=types).count()
            return _pct(done, planned), done, planned

        ct_pct, _, _ = _rate(("cluster_training",))
        cm_pct, _, _ = _rate(CLUSTER_MEETING_TYPES)
        pa_planned = acts.filter(
            Q(delivery_type="partner") | Q(activity_type__in=PARTNER_TYPES)
        ).count()
        pa_done = completed.filter(
            Q(delivery_type="partner") | Q(activity_type__in=PARTNER_TYPES)
        ).count()
        partner_pct = _pct(pa_done, pa_planned)

        budget_pct = PLAnalyticsService._budget_utilization(pls, fy)
        avg_ssa_pct = PLAnalyticsService._avg_team_ssa(pls, fy)
        activities_completed = completed.count()

        # Trend vs previous quarter (only when a quarter is selected).
        prevq = PLAnalyticsService._prev_quarter(quarter)
        prev = None
        if prevq:
            prev = (
                _team_activity_qs(pls, fy, prevq, filters)
                .filter(status__in=COMPLETED_STATUSES)
                .count()
            )

        def trend_count(cur, prev_val):
            if prev_val is None:
                return None, None, None
            delta = cur - prev_val
            return (
                delta,
                ("up" if delta >= 0 else "down"),
                f"{'+' if delta >= 0 else ''}{delta} vs {prevq}",
            )

        act_delta, act_dir, act_help = trend_count(activities_completed, prev)

        def card(
            icon,
            label,
            value,
            variant,
            helper="",
            direction="neutral",
            trend_val="",
            spark=None,
            link="",
            raw=None,
        ):
            return {
                "icon": icon,
                "label": label,
                "value": value,
                "variant": variant,
                "trend": {"direction": direction, "value": trend_val},
                "helper": helper,
                "sparkline": _sparkline(spark) if spark else "",
                "link": link,
                "raw": raw,
            }

        items = [
            card(
                "target",
                "Team Execution Progress %",
                f"{team_target_pct}%",
                "primary",
                "field completions vs target (not IA-verified)",
                link="?drill=kpi&metric=target",
            ),
            card(
                "users",
                "CCEOs On Track",
                f"{cceos_on_track} / {len(pls.cceos)}",
                "success",
                "at or above pace",
                link="?drill=kpi&metric=cceos_on_track",
            ),
            card(
                "school",
                "Schools Assigned to Team",
                f"{schools_total}",
                "info",
                "in portfolio",
                link="?drill=kpi&metric=schools",
            ),
            card(
                "warning",
                "Schools Without SSA",
                f"{schools_without_ssa}",
                "warning" if schools_without_ssa else "success",
                "no verified SSA",
                link="?drill=kpi&metric=no_ssa",
            ),
            card(
                "map",
                "Schools Not Visited",
                f"{schools_not_visited}",
                "danger" if schools_not_visited else "success",
                "this period",
                link="?drill=kpi&metric=not_visited",
            ),
            card(
                "book",
                "Schools Not Trained",
                f"{schools_not_trained}",
                "danger" if schools_not_trained else "success",
                "this period",
                link="?drill=kpi&metric=not_trained",
            ),
            card(
                "graduation",
                "Cluster Trainings Completed",
                f"{ct_pct}%",
                "success",
                "completed / planned",
            ),
            card(
                "users",
                "Cluster Meetings Completed",
                f"{cm_pct}%",
                "success",
                "completed / planned",
            ),
            card(
                "handshake",
                "Partner Activities Completed",
                f"{partner_pct}%",
                "info",
                "completed / assigned",
            ),
            card(
                "currency",
                "Team Budget Utilization",
                f"{budget_pct}%",
                "finance",
                "disbursed / approved",
            ),
            card(
                "chart",
                "Average Team SSA Score",
                f"{avg_ssa_pct}%" if avg_ssa_pct is not None else "No SSA",
                "success" if (avg_ssa_pct or 0) >= 60 else "warning",
                "latest verified cycle",
            ),
            card(
                "report",
                "Activities Completed",
                f"{activities_completed:,}",
                "primary",
                act_help or "this period",
                direction=act_dir or "neutral",
                trend_val=(
                    f"{'+' if (act_delta or 0) >= 0 else ''}{act_delta}"
                    if act_delta is not None
                    else ""
                ),
            ),
        ]
        return {
            "items": items,
            "team_target_pct": team_target_pct,
            "cceos_on_track": cceos_on_track,
        }

    # ── Target achievement ───────────────────────────────────────────────────
    # Per the spec: Team Execution Progress % = completed target items /
    # assigned target items × 100. "Completed" here is the broad field-execution
    # completion (COMPLETED_STATUSES), NOT the stricter IA-verified engine used
    # by the "My Targets" / "Team Targets" pages (TargetAchievementLedger,
    # weighted by TargetArea.weight — see targets.my_targets.weighted_period_pct).
    # A PL execution cockpit tracks what got done in the field right now, so it
    # deliberately does not wait for IA validation. Because this is a genuinely
    # different metric from the canonical weighted ledger %, it must NEVER reuse
    # the "Team Target Achievement" label — that label is reserved for the
    # canonical figure on the Team Targets page, so a PL never sees the same
    # label mean two different numbers in one session.
    # Targets come from StaffTargetProfile (visits / trainings / cluster
    # meetings / SSA). No target set → 0 with a "set targets" note (honest).
    @staticmethod
    def _cceo_target(
        cceo: dict, completed_qs, fy: str, quarter: str | None = None
    ) -> tuple[int, int, int]:
        """(achievement_pct, achieved_total, target_total) for one CCEO from
        real completed activities vs their StaffTargetProfile targets. A single
        quarter pro-rates the annual target to a quarter share (annual ÷ 4);
        no quarter = FY Cumulative."""
        tp = StaffTargetProfile.objects.filter(staff_id=cceo["staff_id"], fy=fy).first()
        target_total = 0
        if tp:
            target_total = (
                (tp.visits_target or 0)
                + (tp.trainings_target or 0)
                + (tp.cluster_meetings_target or 0)
                + (tp.ssa_target or 0)
            )
        if quarter in ("Q1", "Q2", "Q3", "Q4") and target_total:
            target_total = round(target_total * 0.25)
        ids = {cceo["staff_id"]}
        if cceo["user_id"]:
            ids.add(cceo["user_id"])
        c_done = completed_qs.filter(
            Q(responsible_staff_id__in=ids) | Q(school_id__in=cceo["school_ids"])
        )
        achieved_total = (
            c_done.filter(activity_type__in=VISIT_TYPES).count()
            + c_done.filter(activity_type__in=TRAINING_TYPES).count()
            + c_done.filter(activity_type__in=CLUSTER_MEETING_TYPES).count()
            + c_done.filter(activity_type__in=SSA_COLLECTION_TYPES).count()
        )
        pct = round(achieved_total / target_total * 100) if target_total else 0
        return pct, achieved_total, target_total

    @staticmethod
    def _team_target(
        pls: PLScope, fy: str, quarter=None, filters=None
    ) -> tuple[int, int]:
        """Team target achievement % + count of CCEOs at/above the pace
        threshold (design: 'CCEOs On Track')."""
        completed_qs = _team_activity_qs(pls, fy, quarter, filters or {}).filter(
            status__in=COMPLETED_STATUSES
        )
        total_target = total_achieved = 0
        on_track = 0
        expected = PLAnalyticsService._expected_pace(fy)
        for c in pls.cceos:
            pct, ach, tgt = PLAnalyticsService._cceo_target(
                c, completed_qs, fy, quarter
            )
            total_target += tgt
            total_achieved += ach
            if tgt and pct >= expected:
                on_track += 1
        team_pct = round(total_achieved / total_target * 100) if total_target else 0
        return team_pct, on_track

    @staticmethod
    def _expected_pace(fy: str) -> int:
        """% of the FY elapsed (an activity is 'on track' at/above this)."""
        start, end = get_fy_date_range(fy)
        now = date.today()
        s, e = start.date(), end.date()
        if now <= s:
            return 0
        if now >= e:
            return 100
        return round((now - s).days / (e - s).days * 100)

    @staticmethod
    def _budget_utilization(pls: PLScope, fy: str) -> int:
        """Disbursed / approved for the team's weekly fund requests."""
        from apps.fund_requests.models import WeeklyFundRequest

        user_ids = [c["user_id"] for c in pls.cceos if c["user_id"]]
        if not user_ids:
            return 0
        qs = WeeklyFundRequest.objects.filter(fy=fy, responsible_user__in=user_ids)
        approved = (
            qs.filter(
                status__in=["confirmed_for_advance", "disbursed", "accounted"]
            ).aggregate(s=Sum("total_amount"))["s"]
            or 0
        )
        disbursed = (
            qs.filter(status__in=["disbursed", "accounted"]).aggregate(
                s=Sum("disbursed_amount")
            )["s"]
            or 0
        )
        return _pct(int(disbursed), int(approved))

    # ── SSA annual-cycle helpers ─────────────────────────────────────────────
    @staticmethod
    def _cycle_fys(pls: PLScope, fy: str) -> tuple[str | None, str | None]:
        """The latest confirmed annual SSA FY (<= selected fy) and the previous
        one, portfolio-wide. Annual cycle comparison, never monthly."""
        # NOTE: .order_by("fy") is required — SsaRecord has Meta ordering, and
        # values_list(...).distinct() otherwise includes the ordering column in
        # the SELECT and returns duplicate FYs (silently collapsing the annual
        # cycle comparison to latest==prev).
        fys = list(
            SsaRecord.objects.filter(
                school_id__in=pls.school_ids,
                verification_status="confirmed",
                fy__lte=fy,
            )
            .order_by("fy")
            .values_list("fy", flat=True)
            .distinct()
        )
        fys = sorted(fys, reverse=True)
        latest = fys[0] if fys else None
        prev = fys[1] if len(fys) > 1 else None
        return latest, prev

    @staticmethod
    def _avg_team_ssa(pls: PLScope, fy: str) -> float | None:
        latest, _ = PLAnalyticsService._cycle_fys(pls, fy)
        if not latest:
            return None
        avg = SsaRecord.objects.filter(
            school_id__in=pls.school_ids, verification_status="confirmed", fy=latest
        ).aggregate(a=Avg("average_score"))["a"]
        return _norm(avg)

    @staticmethod
    def ssa_interventions(pls: PLScope, fy: str) -> dict:
        """Section B — average SSA per intervention for the latest verified
        annual cycle, with the delta from the previous cycle. Annual only."""
        latest, prev = PLAnalyticsService._cycle_fys(pls, fy)
        rows = []
        if not latest:
            for v, label, code in SSA_INTERVENTIONS:
                band = ssa_band(None)
                rows.append(
                    {
                        "value": v,
                        "label": label,
                        "code": code,
                        "pct": None,
                        "delta": None,
                        "band": band[0],
                        "color": band[1],
                        "tone": band[2],
                    }
                )
            return {"rows": rows, "latest_fy": None, "prev_fy": None, "has_data": False}

        def _by_intervention(cycle_fy):
            record_ids = SsaRecord.objects.filter(
                school_id__in=pls.school_ids,
                verification_status="confirmed",
                fy=cycle_fy,
            ).values_list("id", flat=True)
            data = {
                r["intervention"]: r["a"]
                for r in SsaScore.objects.filter(ssa_record_id__in=record_ids)
                .values("intervention")
                .annotate(a=Avg("score"))
            }
            return data

        cur = _by_intervention(latest)
        old = _by_intervention(prev) if prev else {}
        for v, label, code in SSA_INTERVENTIONS:
            cur_pct = _norm(cur.get(v))
            prev_pct = _norm(old.get(v)) if prev else None
            delta = (
                round(cur_pct - prev_pct, 1)
                if (cur_pct is not None and prev_pct is not None)
                else None
            )
            band = ssa_band(cur_pct)
            rows.append(
                {
                    "value": v,
                    "label": label,
                    "code": code,
                    "pct": cur_pct,
                    "delta": delta,
                    "band": band[0],
                    "color": band[1],
                    "tone": band[2],
                }
            )
        rows.sort(key=lambda r: (r["pct"] is None, -(r["pct"] or 0)))
        return {"rows": rows, "latest_fy": latest, "prev_fy": prev, "has_data": True}

    # ── A. Team performance (monthly planned vs completed + achievement line) ─
    @staticmethod
    def team_performance(
        pls: PLScope, fy: str, quarter: str | None, filters: dict
    ) -> dict:
        acts = _team_activity_qs(pls, fy, None, filters)  # full FY for the timeline
        labels, planned, completed = [], [], []
        # Annual team target for the cumulative achievement line.
        _, _, team_target_total = PLAnalyticsService._team_target_totals(
            pls, fy, None, filters
        )
        target_types = (
            VISIT_TYPES + TRAINING_TYPES + CLUSTER_MEETING_TYPES + SSA_COLLECTION_TYPES
        )
        cumulative_done = 0
        pct_line = []
        # FY runs Oct(1) → Sep(12).
        for m_of_fy in range(1, 13):
            start, end = get_month_date_range(fy, m_of_fy)
            cal_month = start.month
            labels.append(f"{MONTHS_SHORT[cal_month]}")
            month_qs = acts.filter(
                planned_date__gte=start.date(), planned_date__lt=end.date()
            )
            p = month_qs.filter(status__in=PLANNED_STATUSES).count()
            c = month_qs.filter(status__in=COMPLETED_STATUSES).count()
            planned.append(p)
            completed.append(c)
            # The achievement line tracks cumulative target-relevant completions
            # against the annual team target (rises through the year).
            cumulative_done += month_qs.filter(
                status__in=COMPLETED_STATUSES, activity_type__in=target_types
            ).count()
            pct_line.append(
                round(cumulative_done / team_target_total * 100)
                if team_target_total
                else 0
            )
        return {
            "labels": labels,
            "planned": planned,
            "completed": completed,
            "pct": pct_line,
            "has_target": team_target_total > 0,
        }

    @staticmethod
    def _team_target_totals(
        pls: PLScope, fy: str, quarter=None, filters=None
    ) -> tuple[int, int, int]:
        completed_qs = _team_activity_qs(pls, fy, quarter, filters or {}).filter(
            status__in=COMPLETED_STATUSES
        )
        total_target = total_achieved = 0
        for c in pls.cceos:
            _, ach, tgt = PLAnalyticsService._cceo_target(c, completed_qs, fy, quarter)
            total_target += tgt
            total_achieved += ach
        pct = round(total_achieved / total_target * 100) if total_target else 0
        return pct, total_achieved, total_target

    # ── C. District performance ──────────────────────────────────────────────
    @staticmethod
    def district_performance(
        pls: PLScope, fy: str, quarter: str | None, filters: dict
    ) -> dict:
        schools = School.objects.filter(id__in=pls.school_ids)
        acts = _team_activity_qs(pls, fy, quarter, filters)
        latest_fy, _ = PLAnalyticsService._cycle_fys(pls, fy)
        by_district = (
            schools.exclude(district__isnull=True)
            .values("district_id", "district__name")
            .annotate(n=Count("id"))
            .order_by("-n")
        )

        # Batch-fetch once instead of ~4 queries per district (school-scoped
        # activity completed/planned counts, SSA average, SSA critical-count).
        # School->district map, all in-scope activities' (school_id, status),
        # and all confirmed SSA records for the latest cycle, grouped in Python.
        school_district = dict(
            schools.exclude(district__isnull=True).values_list("id", "district_id")
        )
        district_completed: dict = {}
        district_planned: dict = {}
        for sid, status in acts.exclude(school_id__isnull=True).values_list(
            "school_id", "status"
        ):
            did = school_district.get(sid)
            if did is None:
                continue
            district_planned[did] = district_planned.get(did, 0) + 1
            if status in COMPLETED_STATUSES:
                district_completed[did] = district_completed.get(did, 0) + 1

        district_scores: dict = {}  # district_id -> [average_score, ...]
        district_critical_schools: dict = {}  # district_id -> {school_id, ...}
        if latest_fy:
            for sid, score in SsaRecord.objects.filter(
                school_id__in=pls.school_ids,
                verification_status="confirmed",
                fy=latest_fy,
            ).values_list("school_id", "average_score"):
                did = school_district.get(sid)
                if did is None:
                    continue
                district_scores.setdefault(did, []).append(score)
                if score is not None and score < 5.0:
                    district_critical_schools.setdefault(did, set()).add(sid)

        def _mean(values):
            values = [v for v in values if v is not None]
            return (sum(values) / len(values)) if values else None

        rows = []
        team_pcts = []
        for d in by_district:
            did = d["district_id"]
            n_schools = d["n"]
            completed = district_completed.get(did, 0)
            planned_total = district_planned.get(did, 0)
            pct = _pct(completed, planned_total)
            avg_ssa = _norm(_mean(district_scores.get(did, []))) if latest_fy else None
            critical = len(district_critical_schools.get(did, set()))
            band = ssa_band(avg_ssa)
            rows.append(
                {
                    "id": did,
                    "name": d["district__name"],
                    "pct": pct,
                    "schools": n_schools,
                    "completed": completed,
                    "critical": critical,
                    "avg_ssa": avg_ssa,
                    "bar_color": PLAnalyticsService._bar_color(pct),
                    "band": band[0],
                    "tone": band[2],
                }
            )
            team_pcts.append(pct)
        rows.sort(key=lambda r: -r["pct"])
        team_avg = round(sum(team_pcts) / len(team_pcts)) if team_pcts else 0
        return {"rows": rows, "team_avg": team_avg}

    @staticmethod
    def _bar_color(pct: int) -> str:
        if pct >= 75:
            return "bg-emerald-500"
        if pct >= 60:
            return "edify-primary-solid"
        if pct >= 40:
            return "bg-amber-500"
        return "bg-rose-500"

    # ── D. Cluster performance ───────────────────────────────────────────────
    @staticmethod
    def cluster_performance(
        pls: PLScope, fy: str, quarter: str | None, filters: dict
    ) -> dict:
        from apps.clusters.models import Cluster

        schools = School.objects.filter(id__in=pls.school_ids)
        cluster_ids = list(
            schools.exclude(cluster_id__isnull=True)
            .exclude(cluster_id="")
            .order_by("cluster_id")
            .values_list("cluster_id", flat=True)
            .distinct()
        )
        cluster_names = dict(
            Cluster.objects.filter(id__in=cluster_ids).values_list("id", "name")
        )
        acts = _team_activity_qs(pls, fy, quarter, filters)
        latest_fy, _ = PLAnalyticsService._cycle_fys(pls, fy)

        # Batch-fetch once instead of ~7 queries per cluster (SSA record ids,
        # SSA average, weakest-intervention average, and 4 activity counts).
        # School->cluster map, all confirmed SSA records + their intervention
        # scores, and all in-scope activities, grouped in Python.
        school_cluster = dict(
            schools.exclude(cluster_id__isnull=True)
            .exclude(cluster_id="")
            .values_list("id", "cluster_id")
        )

        def _mean(values):
            values = [v for v in values if v is not None]
            return (sum(values) / len(values)) if values else None

        cluster_scores: dict = {}  # cluster_id -> [average_score, ...]
        record_cluster: dict = {}  # ssa_record_id -> cluster_id
        if latest_fy:
            for rec_id, sid, score in SsaRecord.objects.filter(
                school_id__in=pls.school_ids,
                verification_status="confirmed",
                fy=latest_fy,
            ).values_list("id", "school_id", "average_score"):
                cid_ = school_cluster.get(sid)
                if cid_ is None:
                    continue
                record_cluster[rec_id] = cid_
                cluster_scores.setdefault(cid_, []).append(score)

        cluster_intervention_scores: dict = {}  # cluster_id -> {intervention: [score, ...]}
        if record_cluster:
            for rec_id, intervention, score in SsaScore.objects.filter(
                ssa_record_id__in=list(record_cluster.keys()),
            ).values_list("ssa_record_id", "intervention", "score"):
                cid_ = record_cluster.get(rec_id)
                if cid_ is None:
                    continue
                cluster_intervention_scores.setdefault(cid_, {}).setdefault(
                    intervention, []
                ).append(score)

        cluster_counts: dict = {}  # cluster_id -> {"visits_done": n, "visits_planned": n, ...}
        for sid, atype, status in acts.exclude(school_id__isnull=True).values_list(
            "school_id", "activity_type", "status"
        ):
            cid_ = school_cluster.get(sid)
            if cid_ is None:
                continue
            c = cluster_counts.setdefault(
                cid_,
                {
                    "visits_done": 0,
                    "visits_planned": 0,
                    "trainings_done": 0,
                    "trainings_planned": 0,
                },
            )
            done = status in COMPLETED_STATUSES
            if atype in VISIT_TYPES:
                c["visits_planned"] += 1
                if done:
                    c["visits_done"] += 1
            elif atype in TRAINING_TYPES:
                c["trainings_planned"] += 1
                if done:
                    c["trainings_done"] += 1

        rows = []
        for idx, cid in enumerate(cluster_ids, start=1):
            avg_ssa = None
            weakest = ("—", None)
            if latest_fy:
                avg_ssa = _norm(_mean(cluster_scores.get(cid, [])))
                by_int = sorted(
                    (
                        (k, _mean(v))
                        for k, v in cluster_intervention_scores.get(cid, {}).items()
                    ),
                    key=lambda kv: (kv[1] is None, kv[1]),
                )
                if by_int:
                    w_key, w_avg = by_int[0]
                    label = _INTERVENTION_LABELS.get(w_key, (w_key, ""))[0]
                    weakest = (label, _norm(w_avg))
            counts = cluster_counts.get(
                cid,
                {
                    "visits_done": 0,
                    "visits_planned": 0,
                    "trainings_done": 0,
                    "trainings_planned": 0,
                },
            )
            visits_done, visits_planned = (
                counts["visits_done"],
                counts["visits_planned"],
            )
            trainings_done, trainings_planned = (
                counts["trainings_done"],
                counts["trainings_planned"],
            )
            band = ssa_band(avg_ssa)
            rows.append(
                {
                    "index": idx,
                    "id": cid,
                    "name": cluster_names.get(cid, "Cluster"),
                    "avg_ssa": avg_ssa,
                    "ssa_tone": band[2],
                    "ssa_band": band[0],
                    "weakest_label": weakest[0],
                    "weakest_pct": weakest[1],
                    "visits_done": visits_done,
                    "visits_planned": visits_planned,
                    "trainings_done": trainings_done,
                    "trainings_planned": trainings_planned,
                    "next_action": PLAnalyticsService._cluster_next_action(
                        avg_ssa,
                        visits_done,
                        visits_planned,
                        trainings_done,
                        trainings_planned,
                    ),
                    "status": band[0],
                }
            )
        rows.sort(key=lambda r: (r["avg_ssa"] is None, -(r["avg_ssa"] or 0)))
        return {"rows": rows, "latest_fy": latest_fy}

    @staticmethod
    def _cluster_next_action(avg_ssa, vd, vp, td, tp) -> str:
        if avg_ssa is None:
            return "Schedule SSA Collection"
        if avg_ssa < 50:
            return "Review Cluster Support Plan"
        if vp and vd < vp:
            return "Complete Remaining Visits"
        if tp and td < tp:
            return "Complete Remaining Trainings"
        return "On Track — Monitor"

    # ── E. Impact summary ────────────────────────────────────────────────────
    @staticmethod
    def impact_summary(
        pls: PLScope, fy: str, quarter: str | None, filters: dict
    ) -> dict:
        completed = _team_activity_qs(pls, fy, quarter, filters).filter(
            status__in=COMPLETED_STATUSES
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
        reached_school_ids = set(
            completed.exclude(school_id__isnull=True).values_list(
                "school_id", flat=True
            )
        )
        students = (
            School.objects.filter(id__in=reached_school_ids).aggregate(
                s=Sum("enrollment")
            )["s"]
            or 0
        )
        schools_improved = PLAnalyticsService._schools_improved(pls, fy)
        return {
            "teachers_trained": int(teachers),
            "leaders_trained": int(leaders),
            "students_impacted": int(students),
            "schools_improved": schools_improved,
        }

    @staticmethod
    def _schools_improved(pls: PLScope, fy: str) -> int:
        """Schools with a positive annual SSA delta (latest cycle > previous)."""
        latest, prev = PLAnalyticsService._cycle_fys(pls, fy)
        if not (latest and prev):
            return 0
        cur = dict(
            SsaRecord.objects.filter(
                school_id__in=pls.school_ids, verification_status="confirmed", fy=latest
            ).values_list("school_id", "average_score")
        )
        old = dict(
            SsaRecord.objects.filter(
                school_id__in=pls.school_ids, verification_status="confirmed", fy=prev
            ).values_list("school_id", "average_score")
        )
        improved = 0
        for sid, score in cur.items():
            if (
                sid in old
                and score is not None
                and old[sid] is not None
                and score > old[sid]
            ):
                improved += 1
        return improved

    # ── F. CCEO performance ──────────────────────────────────────────────────
    @staticmethod
    def cceo_performance(
        pls: PLScope, fy: str, quarter: str | None, filters: dict
    ) -> dict:
        acts = _team_activity_qs(pls, fy, quarter, filters)
        completed_all = acts.filter(status__in=COMPLETED_STATUSES)
        latest_fy, _ = PLAnalyticsService._cycle_fys(pls, fy)
        rows = []
        for c in pls.cceos:
            ids = {c["staff_id"]}
            if c["user_id"]:
                ids.add(c["user_id"])
            c_acts = acts.filter(
                Q(responsible_staff_id__in=ids) | Q(school_id__in=c["school_ids"])
            )
            completed = c_acts.filter(status__in=COMPLETED_STATUSES).count()
            backlog = c_acts.filter(
                status__in=(
                    "returned_by_pl",
                    "returned_by_ia",
                    "salesforce_id_required",
                    "awaiting_ia_verification",
                )
            ).count()
            target_pct, _, target_total = PLAnalyticsService._cceo_target(
                c, completed_all, fy, quarter
            )
            avg_ssa = None
            if latest_fy and c["school_ids"]:
                avg_ssa = _norm(
                    SsaRecord.objects.filter(
                        school_id__in=c["school_ids"],
                        verification_status="confirmed",
                        fy=latest_fy,
                    ).aggregate(a=Avg("average_score"))["a"]
                )
            evidence_total = c_acts.filter(
                activity_type__in=VISIT_TYPES + TRAINING_TYPES
            ).count()
            evidence_done = c_acts.filter(evidence_status="accepted").count()
            evidence_pct = _pct(evidence_done, evidence_total)
            risk = PLAnalyticsService._cceo_risk(
                target_pct,
                target_total,
                backlog,
                avg_ssa,
                len(c["school_ids"]),
            )
            band = ssa_band(avg_ssa)
            rows.append(
                {
                    "staff_id": c["staff_id"],
                    "name": c["name"],
                    "initials": c["initials"],
                    "schools_managed": len(c["school_ids"]),
                    "completed": completed,
                    "backlog": backlog,
                    "avg_ssa": avg_ssa,
                    "ssa_tone": band[2],
                    "target_pct": target_pct,
                    "has_target": target_total > 0,
                    "evidence_pct": evidence_pct,
                    "risk": risk[0],
                    "risk_tone": risk[1],
                }
            )
        # Rank worst risk first, then lowest achievement.
        risk_order = {"Critical": 0, "High": 1, "Moderate": 2, "Low": 3}
        rows.sort(key=lambda r: (risk_order.get(r["risk"], 4), r["target_pct"]))
        return {"rows": rows}

    @staticmethod
    def _cceo_risk(
        target_pct, target_total, backlog, avg_ssa, schools
    ) -> tuple[str, str]:
        score = 0
        expected = 50
        if target_total and target_pct < expected * 0.5:
            score += 2
        elif target_total and target_pct < expected:
            score += 1
        if backlog >= 10:
            score += 2
        elif backlog >= 4:
            score += 1
        if avg_ssa is not None and avg_ssa < 40:
            score += 2
        elif avg_ssa is not None and avg_ssa < 60:
            score += 1
        if avg_ssa is None and schools:
            score += 1  # no SSA visibility at all
        if score >= 5:
            return ("Critical", "danger")
        if score >= 3:
            return ("High", "warning")
        if score >= 1:
            return ("Moderate", "amber")
        return ("Low", "success")

    # ── G. Insights / recommended actions ────────────────────────────────────
    @staticmethod
    def insights(pls: PLScope, fy: str, quarter: str | None, filters: dict) -> dict:
        schools = School.objects.filter(id__in=pls.school_ids)
        acts = _team_activity_qs(pls, fy, quarter, filters).filter(
            status__in=COMPLETED_STATUSES
        )
        no_ssa = schools.exclude(current_fy_ssa_status="done").count()
        visited = set(
            acts.filter(activity_type__in=VISIT_TYPES)
            .exclude(school_id__isnull=True)
            .values_list("school_id", flat=True)
        )
        not_visited = max(0, schools.count() - len(visited))
        trained = set(
            acts.filter(activity_type__in=TRAINING_TYPES)
            .exclude(school_id__isnull=True)
            .values_list("school_id", flat=True)
        )
        not_trained = max(0, schools.count() - len(trained))
        weak_clusters = 0
        cluster_data = PLAnalyticsService.cluster_performance(
            pls, fy, quarter, filters
        )["rows"]
        weak_clusters = sum(
            1 for c in cluster_data if c["avg_ssa"] is not None and c["avg_ssa"] < 50
        )

        items = []
        if no_ssa:
            items.append(
                {
                    "severity": "danger",
                    "text": f"{no_ssa} schools are without SSA collection",
                    "action": "Schedule SSA Collection",
                    "link": "?drill=risk&issue=no_ssa",
                }
            )
        if not_visited:
            items.append(
                {
                    "severity": "warning",
                    "text": f"{not_visited} schools not visited this period",
                    "action": "Plan Visits",
                    "link": "?drill=risk&issue=not_visited",
                }
            )
        if not_trained:
            items.append(
                {
                    "severity": "warning",
                    "text": f"{not_trained} schools are behind on required trainings",
                    "action": "Plan Training",
                    "link": "?drill=risk&issue=not_trained",
                }
            )
        if weak_clusters:
            items.append(
                {
                    "severity": "danger",
                    "text": f"{weak_clusters} clusters performing below 50% target",
                    "action": "Review Cluster Support Plan",
                    "link": "?drill=cluster",
                }
            )
        return {
            "items": items[:6],
            "cta": "Review At-Risk Schools",
            "cta_link": "?drill=risk",
        }

    # ── H. Activity tracking ─────────────────────────────────────────────────
    @staticmethod
    def activity_tracking(
        pls: PLScope, fy: str, quarter: str | None, filters: dict
    ) -> dict:
        acts = _team_activity_qs(pls, fy, quarter, filters)

        def card(label, types=None, partner=False, project=False):
            if partner:
                qs = acts.filter(
                    Q(delivery_type="partner") | Q(activity_type__in=PARTNER_TYPES)
                )
            elif project:
                qs = acts.filter(activity_type__in=PROJECT_TYPES)
            else:
                qs = acts.filter(activity_type__in=types)
            planned = qs.count()
            done = qs.filter(status__in=COMPLETED_STATUSES).count()
            pct = _pct(done, planned)
            return {
                "label": label,
                "done": done,
                "planned": planned,
                "pct": pct,
                "bar_color": PLAnalyticsService._bar_color(pct),
            }

        return {
            "cards": [
                card("School Visits", VISIT_TYPES),
                card("Cluster Trainings", ("cluster_training",)),
                card("Cluster Meetings", CLUSTER_MEETING_TYPES),
                card("SSA Support", SSA_COLLECTION_TYPES),
                card("Partner Activities", partner=True),
                card("Project Activities", project=True),
            ]
        }

    # ── I. Staff vs partner performance ──────────────────────────────────────
    @staticmethod
    def staff_partner_performance(
        pls: PLScope, fy: str, quarter: str | None, filters: dict
    ) -> dict:
        completed = _team_activity_qs(pls, fy, quarter, filters).filter(
            status__in=COMPLETED_STATUSES
        )

        def split(qs):
            staff = qs.exclude(delivery_type="partner").count()
            partner = qs.filter(delivery_type="partner").count()
            return staff, partner

        v_s, v_p = split(completed.filter(activity_type__in=VISIT_TYPES))
        t_s, t_p = split(completed.filter(activity_type__in=TRAINING_TYPES))
        m_s, m_p = split(completed.filter(activity_type__in=CLUSTER_MEETING_TYPES))
        a_s, a_p = split(completed)
        return {
            "labels": ["Visits", "Trainings", "Meetings", "Activities"],
            "staff": [v_s, t_s, m_s, a_s],
            "partner": [v_p, t_p, m_p, a_p],
        }

    # ── J. Core & champion school performance ────────────────────────────────
    @staticmethod
    def core_champion(pls: PLScope, fy: str) -> dict:
        schools = School.objects.filter(id__in=pls.school_ids)
        core_ids = set(schools.filter(school_type="core").values_list("id", flat=True))
        champ_ids = set(
            schools.filter(school_type="champion").values_list("id", flat=True)
        )

        def trend(ids):
            if not ids:
                return {"count": 0, "labels": [], "series": []}
            fys = sorted(
                SsaRecord.objects.filter(
                    school_id__in=ids, verification_status="confirmed"
                )
                .order_by("fy")
                .values_list("fy", flat=True)
                .distinct()
            )
            labels, series = [], []
            for f in fys:
                avg = SsaRecord.objects.filter(
                    school_id__in=ids, verification_status="confirmed", fy=f
                ).aggregate(a=Avg("average_score"))["a"]
                labels.append(f"FY{f}")
                series.append(_norm(avg) or 0)
            return {"count": len(ids), "labels": labels, "series": series}

        return {"core": trend(core_ids), "champion": trend(champ_ids)}

    # ── K. School risk & attention list ──────────────────────────────────────
    @staticmethod
    def risk_list(
        pls: PLScope,
        fy: str,
        quarter: str | None,
        filters: dict,
        limit: int = 12,
        offset: int = 0,
    ) -> dict:
        acts = _team_activity_qs(pls, fy, quarter, filters).filter(
            status__in=COMPLETED_STATUSES
        )
        visited = {}
        for sid, d in (
            acts.filter(activity_type__in=VISIT_TYPES)
            .exclude(school_id__isnull=True)
            .values_list("school_id", "planned_date")
        ):
            if sid and (
                sid not in visited or (d and (visited[sid] is None or d > visited[sid]))
            ):
                visited[sid] = d
        trained = {}
        for sid, d in (
            acts.filter(activity_type__in=TRAINING_TYPES)
            .exclude(school_id__isnull=True)
            .values_list("school_id", "planned_date")
        ):
            if sid and (
                sid not in trained or (d and (trained[sid] is None or d > trained[sid]))
            ):
                trained[sid] = d
        latest_fy, _ = PLAnalyticsService._cycle_fys(pls, fy)
        low_ssa_ids = set()
        latest_records = {}
        if latest_fy:
            records = (
                SsaRecord.objects.filter(
                    school_id__in=pls.school_ids,
                    verification_status="confirmed",
                    fy=latest_fy,
                )
                .prefetch_related("scores")
                .order_by("school_id", "-date_of_ssa", "-created_at")
            )
            for record in records:
                latest_records.setdefault(record.school_id, record)
            low_ssa_ids = {
                school_id
                for school_id, record in latest_records.items()
                if record.average_score is not None and record.average_score < 5.0
            }

        schools = list(
            School.objects.filter(id__in=pls.school_ids)
            .select_related("district")
            .only("id", "name", "district__name", "current_fy_ssa_status")
        )
        today = date.today()
        rows = []
        for s in schools:
            issues, actions = [], []
            record = latest_records.get(s.id)
            weakest_code = ""
            weakest_label = ""
            if record:
                weakest_score = min(
                    record.scores.all(), key=lambda score: score.score, default=None
                )
                if weakest_score:
                    weakest_code = weakest_score.intervention
                    weakest_label = dict(SsaIntervention.choices).get(
                        weakest_code, weakest_code
                    )
            no_ssa = s.current_fy_ssa_status != "done"
            not_visited = s.id not in visited
            not_trained = s.id not in trained
            low_ssa = s.id in low_ssa_ids
            severity = 0
            if no_ssa:
                issues.append("No SSA")
                actions.append(
                    {
                        "label": "Complete SSA",
                        "activity_type": "baseline_ssa_visit",
                    }
                )
                severity += 2
            if low_ssa:
                issues.append("Low SSA")
                actions.append(
                    {
                        "label": (
                            f"Schedule {weakest_label} Coaching Visit"
                            if weakest_label
                            else "Schedule Coaching Visit"
                        ),
                        "activity_type": "coaching_visit",
                    }
                )
                severity += 2
            if not_visited:
                issues.append("Not Visited")
                actions.append(
                    {
                        "label": "Schedule School Visit",
                        "activity_type": "school_visit",
                    }
                )
                severity += 1
            if not_trained:
                issues.append("Not Trained")
                actions.append(
                    {
                        "label": (
                            f"Schedule {weakest_label} Training"
                            if weakest_label
                            else "Schedule School Improvement Training"
                        ),
                        "activity_type": "school_improvement_training",
                    }
                )
                severity += 1
            if not issues:
                continue
            lv = visited.get(s.id)
            lt = trained.get(s.id)
            recommended = (
                actions[0]
                if actions
                else {
                    "label": "Review School",
                    "activity_type": "school_visit",
                }
            )
            rows.append(
                {
                    "id": s.id,
                    "school_id": s.school_id,
                    "school": s.name,
                    "district": s.district.name if s.district_id else "—",
                    "issue": " + ".join(issues[:2]),
                    "last_visit": f"{(today - lv).days} days ago" if lv else "—",
                    "last_training": f"{(today - lt).days} days ago" if lt else "—",
                    "next_action": recommended["label"],
                    "recommended_activity_label": recommended["label"],
                    "recommended_activity_type": recommended["activity_type"],
                    "weakest_intervention": weakest_label,
                    "weakest_intervention_code": weakest_code,
                    "severity": severity,
                }
            )
        rows.sort(key=lambda r: -r["severity"])
        offset = max(int(offset or 0), 0)
        return {"rows": rows[offset : offset + limit], "total": len(rows)}

    # ── L. Donor / reporting snapshot ────────────────────────────────────────
    @staticmethod
    def donor_snapshot(
        pls: PLScope, fy: str, quarter: str | None, filters: dict
    ) -> dict:
        def snap(q):
            completed = _team_activity_qs(pls, fy, q, filters).filter(
                status__in=COMPLETED_STATUSES
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
            reached = set(
                completed.exclude(school_id__isnull=True).values_list(
                    "school_id", flat=True
                )
            )
            students = (
                School.objects.filter(id__in=reached).aggregate(s=Sum("enrollment"))[
                    "s"
                ]
                or 0
            )
            districts = (
                School.objects.filter(id__in=reached)
                .exclude(district__isnull=True)
                .values("district_id")
                .distinct()
                .count()
            )
            return {
                "teachers": int(teachers),
                "leaders": int(leaders),
                "students": int(students),
                "districts": districts,
                "schools": len(reached),
            }

        cur = snap(quarter)
        prevq = PLAnalyticsService._prev_quarter(quarter)
        prev = snap(prevq) if prevq else None

        def metric(label, key, fmt="int"):
            c = cur[key]
            p = prev[key] if prev else None
            delta_pct = None
            if p is not None and p:
                delta_pct = round((c - p) / p * 100)
            return {
                "label": label,
                "value": f"{c:,}" if fmt == "int" else str(c),
                "prev": f"{p:,}"
                if (p is not None and fmt == "int")
                else (str(p) if p is not None else None),
                "prev_label": prevq,
                "delta_pct": delta_pct,
                "up": (delta_pct is not None and delta_pct >= 0),
            }

        return {
            "metrics": [
                metric("Teachers Trained", "teachers"),
                metric("School Leaders Trained", "leaders"),
                metric("Students Impacted", "students"),
                metric("Districts Covered", "districts"),
                metric("Schools Impacted", "schools"),
            ],
        }

    # ── Export (scoped) ──────────────────────────────────────────────────────
    @staticmethod
    def export_rows(user, fy=None, quarter=None, filters=None) -> list[dict]:
        """Scoped rows for a CSV export — the at-risk school list for the PL's
        supervised portfolio. Never includes another PL's schools."""
        fy = fy or get_operational_fy()
        pls = resolve_pl_scope(user, filters or {})
        return PLAnalyticsService.risk_list(
            pls, fy, quarter, filters or {}, limit=5000
        )["rows"]

    # ── Analytics-driven To-Dos (derive-from-state, not stored) ──────────────
    @staticmethod
    def pl_todos(user, fy=None, quarter=None, filters=None) -> list[dict]:
        """Turn serious analytics signals into actionable PL To-Dos, derived
        live from current portfolio state. Emitted only when a threshold is
        crossed (no risk → no To-Do). Consumed by command_center.todo_service."""
        fy = fy or get_operational_fy()
        pls = resolve_pl_scope(user, filters or {})
        PLAnalyticsService.insights(pls, fy, quarter, filters or {})
        schools = School.objects.filter(id__in=pls.school_ids)
        no_ssa = schools.exclude(current_fy_ssa_status="done").count()
        clusters = PLAnalyticsService.cluster_performance(
            pls, fy, quarter, filters or {}
        )["rows"]
        weak = [c for c in clusters if c["avg_ssa"] is not None and c["avg_ssa"] < 50]
        cceos = PLAnalyticsService.cceo_performance(pls, fy, quarter, filters or {})[
            "rows"
        ]
        behind = [c for c in cceos if c["risk"] in ("High", "Critical")]

        todos = []
        if no_ssa:
            todos.append(
                {
                    "id": "pl-analytics-ssa",
                    "title": "Schedule SSA Collection",
                    "description": f"{no_ssa} schools in your team have no verified SSA.",
                    "category": "Analytics",
                    "priority": "high",
                    "action_label": "Review",
                    "action_url": "/analytics/program-lead?drill=risk",
                    "actionable": True,
                    "source": "PL Analytics",
                }
            )
        for c in weak[:3]:
            todos.append(
                {
                    "id": f"pl-analytics-cluster-{c['id']}",
                    "title": "Review Cluster Support Plan",
                    "description": f"{c['name']} is performing below 50% (avg SSA {c['avg_ssa']}%).",
                    "category": "Analytics",
                    "priority": "high",
                    "action_label": "Review",
                    "action_url": "/analytics/program-lead",
                    "actionable": True,
                    "source": "PL Analytics",
                }
            )
        for c in behind[:3]:
            todos.append(
                {
                    "id": f"pl-analytics-cceo-{c['staff_id']}",
                    "title": "Follow up CCEO",
                    "description": f"{c['name']} is behind target ({c['risk']} risk).",
                    "category": "Analytics",
                    "priority": "medium",
                    "action_label": "Open",
                    "action_url": "/analytics/program-lead",
                    "actionable": True,
                    "source": "PL Analytics",
                }
            )
        return todos

    # ── Drill-downs (all role-scoped) ────────────────────────────────────────
    @staticmethod
    def drilldown(
        user, drill: str, params, fy=None, quarter=None, filters=None
    ) -> dict:
        """Return scoped drawer data for a drill-down. `params` is request.GET."""
        fy = fy or get_operational_fy()
        filters = dict(filters or {})
        pls = resolve_pl_scope(user, filters)

        if drill == "district":
            filters["district"] = (params.get("id") or "").strip()
            scoped = resolve_pl_scope(user, filters)
            schools = list(
                School.objects.filter(id__in=scoped.school_ids)
                .select_related("district")
                .only("id", "name", "school_type", "current_fy_ssa_status")[:200]
            )
            name = "District"
            if schools and schools[0].district_id:
                name = schools[0].district.name
            return {
                "title": f"{name} — School Detail",
                "subtitle": f"{len(scoped.school_ids)} schools in scope",
                "schools": schools,
                "kind": "district",
            }

        if drill == "cluster":
            filters["cluster"] = (params.get("id") or "").strip()
            data = PLAnalyticsService.cluster_performance(pls, fy, quarter, filters)
            row = next((r for r in data["rows"] if r["id"] == filters["cluster"]), None)
            scoped = resolve_pl_scope(user, filters)
            schools = list(
                School.objects.filter(id__in=scoped.school_ids).only(
                    "id", "name", "current_fy_ssa_status"
                )[:200]
            )
            return {
                "title": (row["name"] if row else "Cluster") + " — Detail",
                "subtitle": "Cluster performance & member schools",
                "cluster": row,
                "schools": schools,
                "kind": "cluster",
            }

        if drill == "cceo":
            cid = (params.get("id") or "").strip()
            filters["cceo"] = cid
            data = PLAnalyticsService.cceo_performance(
                resolve_pl_scope(user, filters), fy, quarter, filters
            )
            row = data["rows"][0] if data["rows"] else None
            return {
                "title": (row["name"] if row else "CCEO") + " — Performance",
                "subtitle": "Supervised CCEO detail",
                "cceo": row,
                "risk_list": PLAnalyticsService.risk_list(
                    resolve_pl_scope(user, filters), fy, quarter, filters, limit=20
                )["rows"],
                "kind": "cceo",
            }

        if drill == "risk":
            issue = (params.get("issue") or "").strip()
            data = PLAnalyticsService.risk_list(pls, fy, quarter, filters, limit=100)
            rows = data["rows"]
            if issue == "no_ssa":
                rows = [r for r in rows if "No SSA" in r["issue"]]
            elif issue == "not_visited":
                rows = [r for r in rows if "Not Visited" in r["issue"]]
            elif issue == "not_trained":
                rows = [r for r in rows if "Not Trained" in r["issue"]]
            return {
                "title": "At-Risk Schools",
                "subtitle": f"{len(rows)} schools need attention",
                "rows": rows,
                "kind": "risk",
            }

        # KPI drill-down (default): a scoped school/CCEO list behind a KPI.
        metric = (params.get("metric") or "").strip()
        schools = School.objects.filter(id__in=pls.school_ids)
        if metric == "no_ssa":
            rows = list(
                schools.exclude(current_fy_ssa_status="done")
                .select_related("district")
                .only("id", "name", "district__name")[:200]
            )
            title = "Schools Without Verified SSA"
        elif metric == "cceos_on_track":
            return {
                "title": "CCEOs On Track",
                "subtitle": "Target achievement by CCEO",
                "cceo_rows": PLAnalyticsService.cceo_performance(
                    pls, fy, quarter, filters
                )["rows"],
                "kind": "cceo_list",
            }
        else:
            rows = list(
                schools.select_related("district").only(
                    "id", "name", "district__name", "school_type"
                )[:200]
            )
            title = "Portfolio Schools"
        return {
            "title": title,
            "subtitle": f"{len(rows)} schools",
            "schools": rows,
            "kind": "kpi",
        }
