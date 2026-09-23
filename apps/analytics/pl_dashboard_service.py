"""Program Lead dashboard — the Programme Lead's home, built around the role.

The owner described the role on 2026-09-13, in five responsibilities:

1. Strategic direction — priority setting, planning and communication for CCE
   initiatives at the country level.
2. Team leadership — line-management, supervision and support of the CCEOs.
3. Performance management — reviews and professional coaching of those CCEOs.
4. Programme implementation — rolling out training programmes, school
   self-assessments and spiritual transformation interventions.
5. Collaboration — with the Regional Lead, the Country Director and the
   training partners.

The page answers them in that order. A fixed part never moves — the team pulse
(six registered tiles, each opening the view it summarises) and Leadership
Attention (at most four items that need the lead now, drawn from every
responsibility) — and under it one view at a time: Map, Priorities, Team,
Coaching, Programmes or Collaboration. Only the fixed part and the active view
are built, so a tab costs one view rather than the whole cockpit.

Strictly scoped to the lead's own team (``apps.hr.team_roster.team_members``)
and portfolio (``resolve_pl_scope``): never country-wide, never another lead's
officers. The dashboard is a read. Every control is a link into the page where
the work is done — approvals, reviews and decisions keep their own gates there.

Removed on 2026-09-13 because they answered no responsibility, duplicated a
page the lead already opens, or measured the lead as a field officer: My
Personal Targets, Smart Route & Capacity, the SF ID and High-Risk tiles with their attention cards,
Activities This Week, Monthly Fund Request and the route-quality column. The
school risk list is shown once, at the foot of Programmes. Funding & Execution,
Team Backlog and Quick Actions went too: Fund Approvals is where a lead reads a
team's money, and every view now links to the page where its work is done.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date, timedelta
from functools import cached_property
from urllib.parse import urlencode

from django.conf import settings
from django.db.models import Avg, Count, Max, Q
from django.utils import timezone

from apps.activities.cluster_attendance import trained_school_ids
from apps.activities.models import Activity
from apps.analytics.pl_analytics_service import (
    COMPLETED_STATUSES,
    SSA_COLLECTION_TYPES,
    SSA_INTERVENTIONS,
    TRAINING_TYPES,
    VERIFIED_STATUSES,
    VISIT_TYPES,
    PLAnalyticsService,
    _pct,
    _ssa_score,
    resolve_pl_scope,
    ssa_band,
)
from apps.core.fy import get_month_date_range, get_operational_fy
from apps.core.metrics import render_precomputed_metric_for_source
from apps.core.permissions import RolePermissionService
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

logger = logging.getLogger(__name__)

# Kept importable: the Country Director dashboard reads these two, and the
# verified-series test reads VERIFIED_STATUSES through this module.
__all__ = [
    "SF_ID_OVERDUE_DAYS",
    "VERIFIED_STATUSES",
    "ProgramLeadDashboardService",
    "normalise_view",
    "_requires_sf_id",
]

# A CCEO's healthy workload ceiling (schools + activities). Above this → overload.
CCEO_SCHOOL_CAPACITY = 50
CCEO_WEEKLY_ACTIVITY_CAPACITY = 12
SF_ID_OVERDUE_DAYS = 7

# ── The views under the fixed part ───────────────────────────────────────────
# Today opens first: Today and Dashboard are one page (owner, 2026-09-14),
# with Map the first of the dashboard's own views. "operations" was the second view until 2026-09-13; a remembered cookie
# or a bookmark carrying it lands on Team, the view that inherited its work.
DEFAULT_VIEW = "today"
VIEWS = (
    "today",
    "map",
    "priorities",
    "team",
    "coaching",
    "programmes",
    "collaboration",
)
VIEW_ALIASES = {"operations": "team"}
VIEW_TABS = (
    (
        "today",
        "Today",
        "What waits on you, your team in the field today, then your own day",
    ),
    ("map", "Map", "Your team's districts shaded by delivery"),
    (
        "priorities",
        "Priorities",
        "Strategic direction: team priorities, target distribution and guidance",
    ),
    ("team", "Team", "Team leadership: your officers, this week and what waits on you"),
    (
        "coaching",
        "Coaching",
        "Performance management: reviews, recovery, development and coaching",
    ),
    (
        "programmes",
        "Programmes",
        "Programme implementation: trainings, SSA and spiritual transformation",
    ),
    (
        "collaboration",
        "Collaboration",
        "The Regional Lead, the Country Director and training partners",
    ),
)

# ── Where each figure leads ──────────────────────────────────────────────────
# One name per destination, so a page that moves is one edit. Every one is a
# page the Programme Lead holds in the navigation contract (2026-09-13).
MY_TEAM_URL = "/my-team"
FUND_APPROVALS_URL = "/fund-approvals"
REVIEW_QUEUE_URL = "/pl/review-queue"
LEAVE_APPROVALS_URL = "/leave/approvals"
TEAM_AVAILABILITY_URL = "/leave/team-availability"
ESCALATIONS_URL = "/escalations"
DEBRIEFS_URL = "/debriefs"
ACTIONS_SENT_URL = "/actions/sent"
COACHING_URL = "/team/coaching"
PERFORMANCE_REVIEWS_URL = "/performance-reviews"
RECOVERY_PLANS_URL = "/recovery-plans"
DEVELOPMENT_URL = "/cpd-learning"
TEAM_TARGETS_URL = "/team-targets"
EVIDENCE_URL = "/evidence/"
PRIORITIES_URL = "/priorities/master"
# A Programme Lead distributes on the My Team tab of Priorities; the country
# distribution workspace is IA's, the CD's and Admin's (walk, 2026-09-14).
TARGET_DISTRIBUTION_URL = "/target-distribution/team"
TEAM_GUIDANCE_URL = "/priorities/guidance"
PROGRAMME_ROLLOUT_URL = "/programme-rollout"
TRAINING_FEEDBACK_URL = "/cce-leadership/feedback"
REGIONAL_COACHING_URL = "/cce-leadership/coaching"
QUALITY_FLAGS_URL = "/quality-checks"
PARTNER_OVERSIGHT_URL = "/partner-oversight/"
TEAM_OVERSIGHT_URL = "/team-planning-oversight/"

# Work that was never going to happen is not late, planned or delivered.
RELEASED_STATUSES = ("cancelled", "rejected", "deferred", "not_planned")
# A partner delivery past its date that is not yet with review or verification
# — the same exclusions the owner's "Chase Partner Delivery" To-Do applies.
PARTNER_SETTLED_STATUSES = (
    *RELEASED_STATUSES,
    "closed",
    "ia_verified",
    "awaiting_ia_verification",
    "submitted_to_pl",
)
# Review stages where the manager is the one holding the conversation up.
MANAGER_REVIEW_STAGES = ("priorities_manager_review", "manager_assessment")
OPEN_RECOVERY_STATUSES = ("draft", "active", "progress_review", "extended")
# How far back a decision delegated back to the lead still asks for action.
DELEGATED_BACK_DAYS = 14
ATTENTION_LIMIT = 4
LEAVE_LOOKAHEAD_DAYS = 7
FOLLOW_UP_ROWS = 5
LIST_ROWS = 6

TILE_SOURCE = "apps.analytics.pl_dashboard_service:kpis.tile"


def normalise_view(value) -> str:
    """The view a request names, with retired names mapped to their heirs."""
    view = (str(value or "")).strip().lower()
    view = VIEW_ALIASES.get(view, view)
    return view if view in VIEWS else DEFAULT_VIEW


def view_url(view: str, fy: str) -> str:
    return f"/dashboard?{urlencode({'fy': fy, 'view': view})}"


def _requires_sf_id(qs):
    """Completed visits/trainings require an Activity SF ID (program evidence)."""
    return qs.filter(
        status__in=COMPLETED_STATUSES, activity_type__in=VISIT_TYPES + TRAINING_TYPES
    )


def _sentence(text: str) -> str:
    """Upper-case the first letter only: str.capitalize() would also turn
    "CCEO" into "cceo"."""
    return text[:1].upper() + text[1:]


def _plural(n: int, one: str, many: str | None = None) -> str:
    return one if n == 1 else (many or f"{one}s")


def _safe(label: str, build, default):
    """A section another track owns must never take the whole page down.

    The coaching, guidance and partner-engagement summaries are interfaces
    implemented beside their own records; if one raises, its card shows its
    empty state and the failure is logged, the way a To-Do source never
    breaks the queue.
    """
    try:
        return build()
    except Exception:  # noqa: BLE001 - one section never breaks the dashboard
        logger.exception("Program Lead dashboard section %s failed", label)
        return default


class DashboardContext:
    """What one dashboard build knows about the lead's team, computed once.

    Every section reads the same team and the same handoff counts from here, so
    the Waiting on You tile, the attention band and the Team view cannot
    disagree about one number within a render.
    """

    def __init__(self, user, fy: str, today: date | None = None):
        self.user = user
        self.fy = fy
        self.today = today or timezone.localdate()
        portfolio = resolve_pl_scope(user, {})
        member_ids = {member.id for member in self.members}
        team = sorted(
            (c for c in portfolio.cceos if c["staff_id"] in member_ids),
            key=lambda c: (c["name"] or "").lower(),
        )
        responsible = set()
        for c in team:
            responsible.add(c["staff_id"])
            if c["user_id"]:
                responsible.add(c["user_id"])
        # A narrowed copy. resolve_pl_scope memoises one PLScope per request,
        # so mutating it would change the team for every other reader.
        self.pls = replace(portfolio, cceos=team, responsible_ids=responsible)

    # ── Who ──────────────────────────────────────────────────────────────────
    @cached_property
    def members(self) -> list:
        from apps.hr.team_roster import team_members

        return team_members(self.user)

    @property
    def team(self) -> list[dict]:
        return self.pls.cceos

    @cached_property
    def owner_of(self) -> dict[str, str]:
        """Both identifier spaces → the officer's StaffProfile id."""
        out: dict[str, str] = {}
        for c in self.team:
            out[c["staff_id"]] = c["staff_id"]
            if c["user_id"]:
                out[c["user_id"]] = c["staff_id"]
        return out

    @property
    def team_ids(self) -> list[str]:
        return list(self.owner_of)

    @property
    def team_user_ids(self) -> list[str]:
        return [c["user_id"] for c in self.team if c["user_id"]]

    @property
    def team_staff_ids(self) -> list[str]:
        return [c["staff_id"] for c in self.team]

    @cached_property
    def name_of(self) -> dict[str, str]:
        return {c["staff_id"]: c["name"] for c in self.team}

    @cached_property
    def own_ids(self) -> set[str]:
        return {
            i
            for i in (
                getattr(self.user, "id", None),
                getattr(self.user, "staff_profile_id", None),
            )
            if i
        }

    @cached_property
    def own_school_ids(self) -> list[str]:
        from apps.core.scoping import resolve_user_scope

        return list(resolve_user_scope(self.user).own_school_ids)

    def owner(self, responsible_id, monitored_id) -> str | None:
        """The officer an activity row belongs to, the attribution rule of
        PLAnalyticsService._cceo_targets_bulk: the monitoring staff member
        counts only when nobody is responsible (partner delivery)."""
        if responsible_id:
            return self.owner_of.get(responsible_id)
        return self.owner_of.get(monitored_id)

    def team_owned(self, qs):
        ids = self.team_ids
        return qs.filter(
            Q(responsible_staff_id__in=ids)
            | Q(responsible_staff_id__isnull=True, monitored_by_staff_id__in=ids)
        )

    # ── Shared reads ─────────────────────────────────────────────────────────
    @cached_property
    def acts(self):
        return ProgramLeadDashboardService._team_acts(self.pls, self.fy, {})

    @cached_property
    def cceo_rows(self) -> list[dict]:
        return ProgramLeadDashboardService.cceo_performance(self)

    @cached_property
    def target_status(self) -> tuple:
        return _safe(
            "target status",
            lambda: PLAnalyticsService._team_target_status(self.pls, self.fy),
            (None, 0, 0, 0),
        )

    @cached_property
    def handoffs(self) -> dict:
        return ProgramLeadDashboardService.waiting_on_you(self)

    @cached_property
    def collaboration(self) -> dict:
        return ProgramLeadDashboardService.collaboration_items(self)

    @cached_property
    def ssa_rollout(self) -> dict:
        return ProgramLeadDashboardService.ssa_rollout(self)

    @cached_property
    def training_counts(self) -> dict:
        return ProgramLeadDashboardService.training_counts(self)

    @cached_property
    def catch_up_by_user(self) -> Counter:
        from apps.targets.models import CatchUpPlan

        return Counter(
            CatchUpPlan.objects.filter(
                pl_user_id=self.user.id,
                status="submitted",
                staff_user_id__in=self.team_user_ids,
            ).values_list("staff_user_id", flat=True)
        )

    @cached_property
    def type_counts(self) -> list[dict]:
        """Planned and completed work per activity type, read once for the
        delivery families and the monthly chart's denominator."""
        return list(
            self.acts.exclude(status__in=RELEASED_STATUSES)
            .values("activity_type")
            .annotate(
                planned=Count("id"),
                completed=Count("id", filter=Q(status__in=COMPLETED_STATUSES)),
            )
            .order_by()
        )

    @cached_property
    def overloaded(self) -> list[dict]:
        return ProgramLeadDashboardService._overloaded_cceos(
            self.pls, self.fy, self.acts
        )

    @cached_property
    def leave_conflicts(self) -> list[dict]:
        return ProgramLeadDashboardService._leave_conflicts(self)


class ProgramLeadDashboardService:
    """Single entry point for the Program Lead dashboard."""

    URGENT_SCHOOLS_PAGE_SIZE = 4

    # ── Entry point ──────────────────────────────────────────────────────────
    @staticmethod
    def get_dashboard(
        user,
        fy=None,
        *,
        view: str = DEFAULT_VIEW,
        urgent_page=1,
        include_fixed: bool = True,
    ) -> dict:
        """Cached per viewer, year, view and page — see cached_role_dashboard.

        `include_fixed=False` builds the view alone, for a tab click that swaps
        only the view panel. The lead's latest notification change joins the
        key when caching is on, so a handoff that arrives or is resolved shows
        at once instead of after the snapshot expires.
        """
        from apps.core.cache_utils import cached_role_dashboard

        fy = fy or get_operational_fy()
        view = normalise_view(view)
        stamp = None
        if int(getattr(settings, "DASHBOARD_CACHE_SECONDS", 0) or 0) > 0:
            from apps.notifications.models import Notification

            stamp = str(
                Notification.objects.filter(recipient_id=user.id).aggregate(
                    last=Max("updated_at")
                )["last"]
            )
        return cached_role_dashboard(
            "pl",
            user,
            (fy, view, urgent_page, include_fixed, stamp, "today-attention-v1"),
            lambda: ProgramLeadDashboardService._get_dashboard_uncached(
                user,
                fy=fy,
                view=view,
                urgent_page=urgent_page,
                include_fixed=include_fixed,
            ),
        )

    @staticmethod
    def _get_dashboard_uncached(
        user,
        fy=None,
        *,
        view: str = DEFAULT_VIEW,
        urgent_page=1,
        include_fixed: bool = True,
    ) -> dict:
        from apps.core.request_cache import scoped

        fy = fy or get_operational_fy()
        view = normalise_view(view)
        with scoped():
            ctx = DashboardContext(user, fy)
            data = {
                "fy": fy,
                "dashboard_view": view,
                "scope_meta": {
                    "cceo_count": len(ctx.team),
                    "school_count": len(ctx.pls.school_ids),
                    "own_school_count": len(ctx.own_school_ids),
                },
            }
            if include_fixed:
                data["kpi_strip_items"] = ProgramLeadDashboardService.kpis(ctx)
            if include_fixed or view == "today":
                data["leadership_attention"] = (
                    ProgramLeadDashboardService.leadership_attention(ctx)
                )
            builders = {
                # The Today workbench is built per request by the view
                # (apps.frontend.views.today_views), never cached here.
                "today": lambda: {},
                "map": lambda: {},
                "priorities": lambda: ProgramLeadDashboardService.priorities_view(ctx),
                "team": lambda: ProgramLeadDashboardService.team_view(ctx),
                "coaching": lambda: ProgramLeadDashboardService.coaching_view(ctx),
                "programmes": lambda: ProgramLeadDashboardService.programmes_view(
                    ctx, urgent_page=urgent_page
                ),
                "collaboration": lambda: ProgramLeadDashboardService.collaboration_view(
                    ctx
                ),
            }
            data.update(builders[view]())
            return data

    # ── 1. Team pulse ────────────────────────────────────────────────────────
    @staticmethod
    def kpis(ctx: DashboardContext) -> list[dict]:
        """Six registered tiles, one per responsibility's headline, each
        opening the view that explains it (apps/core/metrics/
        pl_dashboard_metrics.py holds their definitions)."""
        fy = ctx.fy
        team_pct, on_track, measurable, contract_rows = ctx.target_status
        waiting = ctx.handoffs["total"]
        ssa = ctx.ssa_rollout
        trainings = ctx.training_counts
        open_handoffs = ctx.collaboration["open_total"]

        def tile(label, display, *, raw, helper, tone, view):
            return render_precomputed_metric_for_source(
                TILE_SOURCE,
                label,
                display,
                raw_value=raw,
                helper=helper,
                tone=tone,
                drilldown_url=view_url(view, fy),
            )

        return [
            tile(
                "Team Priority Progress",
                f"{round(team_pct)}%" if team_pct is not None else "Not measured",
                raw=round(team_pct) if team_pct is not None else None,
                helper=(
                    f"verified against {contract_rows} team "
                    f"{_plural(contract_rows, 'priority', 'priorities')}"
                    if team_pct is not None
                    else "No approved, weighted team allocation yet"
                ),
                tone="info",
                view="priorities",
            ),
            tile(
                "CCEOs On Track",
                f"{on_track} / {measurable}" if measurable else "Not measured",
                raw=on_track if measurable else None,
                helper=(
                    "at the year's expected pace"
                    if measurable
                    else "No approved officer priorities yet"
                ),
                tone="success" if measurable and on_track == measurable else "warning",
                view="coaching",
            ),
            tile(
                "Waiting on You",
                str(waiting),
                raw=waiting,
                helper="team handoffs to decide",
                tone="warning" if waiting else "success",
                view="team",
            ),
            tile(
                "SSA Coverage",
                f"{ssa['coverage_pct']}%" if ssa["portfolio"] else "Not measured",
                raw=ssa["coverage_pct"] if ssa["portfolio"] else None,
                helper=(
                    f"{ssa['confirmed']:,} of {ssa['portfolio']:,} schools · FY {fy}"
                    if ssa["portfolio"]
                    else "No schools in your portfolio"
                ),
                tone="info",
                view="programmes",
            ),
            tile(
                "Trainings Delivered",
                str(trainings["delivered"]),
                raw=trainings["delivered"],
                helper=f"of {trainings['planned']:,} planned · FY {fy}",
                tone="info",
                view="programmes",
            ),
            tile(
                "Open Handoffs",
                str(open_handoffs),
                raw=open_handoffs,
                helper="with the CD, Regional Lead and partners",
                tone="warning" if open_handoffs else "success",
                view="collaboration",
            ),
        ]

    # ── 2. Leadership attention ──────────────────────────────────────────────
    @staticmethod
    def leadership_attention(ctx: DashboardContext) -> list[dict]:
        """At most four things that need the lead now, from every
        responsibility. Nothing is shown for a condition that is healthy: a
        green "all clear" card is not something to act on."""
        cards: list[dict] = []
        handoffs = ctx.handoffs
        collab = ctx.collaboration

        escalations = handoffs["groups_by_key"]["escalations"]
        if escalations["count"]:
            n = escalations["count"]
            cards.append(
                {
                    "tone": "danger" if escalations["overdue"] else "warning",
                    "responsibility": "Team leadership",
                    "title": f"{n} CCEO {_plural(n, 'escalation')} to decide",
                    "body": (
                        f"{escalations['overdue']} past its SLA."
                        if escalations["overdue"]
                        else "An officer is waiting on your decision."
                    ),
                    "action": "Open escalations",
                    "url": ESCALATIONS_URL,
                }
            )

        flags = collab["cd_flags"]
        if flags["open"]:
            n = flags["open"]
            cards.append(
                {
                    "tone": "danger" if flags["overdue"] else "warning",
                    "responsibility": "Collaboration",
                    "title": f"{n} Country Director {_plural(n, 'flag')} open",
                    "body": (
                        f"{flags['overdue']} past the due date the Country Director set."
                        if flags["overdue"]
                        else "The Country Director asked you to follow up."
                    ),
                    "action": "Respond to flags",
                    "url": QUALITY_FLAGS_URL,
                }
            )

        feedback = collab["regional_feedback"]
        coaching = collab["regional_coaching"]
        to_acknowledge = feedback["count"] + coaching["count"]
        if to_acknowledge:
            cards.append(
                {
                    "tone": "warning",
                    "responsibility": "Collaboration",
                    "title": (
                        f"{to_acknowledge} Regional Lead "
                        f"{_plural(to_acknowledge, 'note')} to acknowledge"
                    ),
                    "body": (
                        f"{feedback['count']} training feedback · "
                        f"{coaching['count']} coaching for you."
                    ),
                    "action": "Acknowledge",
                    "url": TRAINING_FEEDBACK_URL
                    if feedback["count"]
                    else REGIONAL_COACHING_URL,
                }
            )

        high_risk = [r for r in ctx.cceo_rows if r["risk"] in ("High", "Critical")]
        catch_up = sum(ctx.catch_up_by_user.values())
        if high_risk or catch_up:
            parts = []
            if high_risk:
                parts.append(
                    f"{len(high_risk)} {_plural(len(high_risk), 'CCEO')} at high risk"
                )
            if catch_up:
                parts.append(
                    f"{catch_up} catch-up {_plural(catch_up, 'plan')} to approve"
                )
            cards.append(
                {
                    "tone": "danger"
                    if any(r["risk"] == "Critical" for r in high_risk)
                    else "warning",
                    "responsibility": "Performance & coaching",
                    "title": _sentence(" · ".join(parts)),
                    "body": (
                        ", ".join(r["name"] for r in high_risk[:3])
                        if high_risk
                        else "Officers submitted recovery plans for your decision."
                    ),
                    "action": "Open Team Targets",
                    "url": TEAM_TARGETS_URL,
                }
            )

        overloaded = ctx.overloaded
        conflicts = ctx.leave_conflicts
        if overloaded or conflicts:
            parts = []
            if overloaded:
                parts.append(
                    f"{len(overloaded)} {_plural(len(overloaded), 'CCEO')} overloaded"
                )
            if conflicts:
                parts.append(
                    f"{len(conflicts)} leave {_plural(len(conflicts), 'conflict')}"
                )
            cards.append(
                {
                    "tone": "warning",
                    "responsibility": "Team leadership",
                    "title": _sentence(" · ".join(parts)),
                    "body": (
                        "Leave overlaps scheduled work in the next week."
                        if conflicts
                        else "Rebalance schools or this week's visits."
                    ),
                    "action": "Open team availability",
                    "url": TEAM_AVAILABILITY_URL,
                }
            )

        partners = collab["partner_delivery"]
        if partners["late"]:
            n = partners["late"]
            cards.append(
                {
                    "tone": "warning",
                    "responsibility": "Collaboration",
                    "title": f"{n} partner {_plural(n, 'delivery', 'deliveries')} late",
                    "body": "Partner-delivered work in your team is past its planned date.",
                    "action": "Open Partner Oversight",
                    "url": PARTNER_OVERSIGHT_URL,
                }
            )

        order = {"danger": 0, "warning": 1}
        cards.sort(key=lambda card: order.get(card["tone"], 2))
        return cards[:ATTENTION_LIMIT]

    # ── Waiting on you ───────────────────────────────────────────────────────
    @staticmethod
    def waiting_on_you(ctx: DashboardContext) -> dict:
        """The team's handoffs that wait on this lead's decision, grouped by
        the page where each is decided. One bulk read per group; per-officer
        counts feed the roster's Waiting column."""
        from apps.debriefs.models import DailyDebrief, DebriefStatus
        from apps.flags import escalation_service
        from apps.flags.models import EscalationStatus, LeadershipEscalation
        from apps.fund_requests.models import WeeklyFundRequest
        from apps.pl_review.services import queue as review_queue

        user = ctx.user
        owner_by_user = {c["user_id"]: c["staff_id"] for c in ctx.team if c["user_id"]}

        def group(key, title, hint, url, action, owners, *, overdue=0):
            by_staff = Counter(o for o in owners if o)
            return {
                "key": key,
                "title": title,
                "hint": hint,
                "url": url,
                "action_label": action,
                "count": len(owners),
                "overdue": overdue,
                "by_staff": dict(by_staff),
            }

        fund_owners = [
            owner_by_user.get(uid)
            for uid in WeeklyFundRequest.objects.filter(
                status="submitted_to_pl", responsible_user__in=ctx.team_user_ids
            ).values_list("responsible_user", flat=True)
        ]
        completions = _safe("review queue", lambda: review_queue(user), [])
        completion_owners = [
            ctx.owner_of.get(row.get("responsibleStaffId")) for row in completions
        ]
        leave_owners = [
            leave.staff_id for leave in ProgramLeadDashboardService._pending_leave(ctx)
        ]

        inbox_q = escalation_service._addressed_to_me_q(user)
        escalation_rows = []
        if inbox_q is not None:
            escalation_rows = list(
                LeadershipEscalation.objects.filter(inbox_q)
                .exclude(status=EscalationStatus.RESOLVED)
                .exclude(raised_by_user_id=user.id)
            )
        escalation_owners = [
            owner_by_user.get(e.raised_by_user_id) for e in escalation_rows
        ]
        escalations_overdue = sum(
            1 for e in escalation_rows if escalation_service._is_overdue(e)
        )

        debrief_owners = [
            owner_by_user.get(uid)
            for uid in DailyDebrief.objects.filter(
                submitted_by_user_id__in=ctx.team_user_ids,
                status__in=(DebriefStatus.SUBMITTED, DebriefStatus.UPDATED),
            ).values_list("submitted_by_user_id", flat=True)
        ]

        groups = [
            group(
                "fund",
                "Weekly fund requests",
                "Your officers' weeks waiting for approval",
                FUND_APPROVALS_URL,
                "Open Fund Approvals",
                fund_owners,
            ),
            group(
                "completions",
                "Completed work to confirm",
                "Before Impact Assessment verifies it",
                REVIEW_QUEUE_URL,
                "Open Completion Reviews",
                completion_owners,
            ),
            group(
                "leave",
                "Leave requests",
                "Officers' leave waiting for your decision",
                LEAVE_APPROVALS_URL,
                "Open Team Leave",
                leave_owners,
            ),
            group(
                "escalations",
                "Escalations",
                "Decisions an officer escalated to you",
                ESCALATIONS_URL,
                "Open Escalations",
                escalation_owners,
                overdue=escalations_overdue,
            ),
            group(
                "debriefs",
                "Field debriefs to review",
                "Submitted or updated since you last read them",
                DEBRIEFS_URL,
                "Open Field Debrief",
                debrief_owners,
            ),
        ]
        by_staff: Counter = Counter()
        for g in groups:
            by_staff.update(g["by_staff"])
        return {
            "groups": groups,
            "groups_by_key": {g["key"]: g for g in groups},
            "total": sum(g["count"] for g in groups),
            "by_staff": dict(by_staff),
        }

    @staticmethod
    def _pending_leave(ctx: DashboardContext) -> list:
        """Pending officer leave this lead may decide, in two reads.

        Mirrors LeaveApprovalService.is_authorized_approver for a Programme
        Lead reviewer, which asks three questions per request: the officer is
        a direct supervisee (team_members answers that, cover included), the
        request is not the lead's own, and the leave type's approval floor
        does not reserve it for a Country Director or above. The floor is read
        for every type at once instead of once per request.
        """
        from apps.accounts.models import Leave, LeaveTypePolicy
        from apps.hr.leave_services import _APPROVER_SENIORITY

        if not ctx.team_staff_ids:
            return []
        pending = list(
            Leave.objects.filter(status="pending", staff_id__in=ctx.team_staff_ids)
            .exclude(staff__user_id=ctx.user.id)
            .only("id", "staff_id", "type", "start_date", "end_date", "days")
        )
        if not pending:
            return []
        floors = {
            policy.leave_type: _seniority_key(policy.approver_role)
            for policy in LeaveTypePolicy.objects.filter(
                leave_type__in={leave.type for leave in pending}
            )
        }
        lead = _APPROVER_SENIORITY["pl"]
        return [
            leave
            for leave in pending
            if (_APPROVER_SENIORITY.get(floors.get(leave.type) or "", 0) or 0) <= lead
        ]

    # ── Collaboration items (fixed part and the Collaboration view) ──────────
    @staticmethod
    def collaboration_items(ctx: DashboardContext) -> dict:
        """The open loops between the lead and their collaborators: the
        Country Director's flags and decisions, the Regional Lead's feedback
        and coaching, visit requests, and partner delivery and invoices."""
        from apps.cce_leadership import services as cce
        from apps.cce_leadership.models import EngagementKind, RegionalEngagement
        from apps.flags.escalation_service import _is_overdue
        from apps.flags.models import CdFlag, EscalationStatus, LeadershipEscalation
        from apps.fund_requests.finance_models import PartnerInvoice
        from apps.planning.visit_requests import AWAITING, pending_for_owner

        user = ctx.user
        today = ctx.today
        staff_id = getattr(user, "staff_profile_id", None)

        flags = list(
            CdFlag.objects.filter(
                assigned_to_user_id=str(user.id), status__in=("open", "acknowledged")
            ).order_by("due_date", "created_at")[:50]
        )

        def flag_due(flag):
            try:
                return date.fromisoformat(str(flag.due_date)[:10])
            except (TypeError, ValueError):
                return None

        flag_rows = [
            {
                "scope": flag.scope_name or "Quality flag",
                "note": (flag.note or "")[:160],
                "raised_by": flag.raised_by_name or "Country Director",
                "due": flag_due(flag),
                "overdue": bool(flag_due(flag) and flag_due(flag) < today),
                "status": flag.get_status_display(),
            }
            for flag in flags
        ]

        feedback_qs = _safe(
            "training feedback",
            lambda: cce.feedback_visible_to(user).filter(
                kind=EngagementKind.TRAINING_OBSERVATION, acknowledged_at__isnull=True
            ),
            RegionalEngagement.objects.none(),
        )
        feedback = list(feedback_qs.order_by("-feedback_shared_at")[:LIST_ROWS])
        feedback_count = feedback_qs.count()
        # Regional Lead coaching the lead received: a shared Programme Lead
        # coaching conversation that names them (owner, 2026-09-13).
        coaching_qs = (
            RegionalEngagement.objects.filter(
                kind=EngagementKind.PL_COACHING,
                feedback_shared_at__isnull=False,
                acknowledged_at__isnull=True,
                program_lead_ids__contains=[staff_id],
            )
            if staff_id
            else RegionalEngagement.objects.none()
        )
        coaching = list(coaching_qs.order_by("-feedback_shared_at")[:LIST_ROWS])
        coaching_count = coaching_qs.count()

        raised_open = list(
            LeadershipEscalation.objects.filter(raised_by_user_id=user.id)
            .exclude(status=EscalationStatus.RESOLVED)
            .order_by("created_at")[: LIST_ROWS * 2]
        )
        delegated = list(
            LeadershipEscalation.objects.filter(
                raised_by_user_id=user.id,
                status=EscalationStatus.RESOLVED,
                decision="delegated_back",
                resolved_at__gte=timezone.now() - timedelta(days=DELEGATED_BACK_DAYS),
            ).order_by("-resolved_at")[:LIST_ROWS]
        )

        visits_to_me = pending_for_owner(user).count()
        visits_into_team = (
            Activity.objects.filter(
                deleted_at__isnull=True,
                status=AWAITING,
                approval_owner_id__in=ctx.team_staff_ids,
            ).count()
            if ctx.team_staff_ids
            else 0
        )

        partner = ProgramLeadDashboardService.partner_delivery(ctx)
        team_ids = ctx.team_ids
        invoices = (
            PartnerInvoice.objects.filter(status="submitted_to_pl")
            .filter(
                Q(items__activity__responsible_staff_id__in=team_ids)
                | Q(
                    items__activity__responsible_staff_id__isnull=True,
                    items__activity__monitored_by_staff_id__in=team_ids,
                )
            )
            .distinct()
            .count()
            if team_ids
            else 0
        )
        partner["invoices_to_confirm"] = invoices

        cd_open = len(flags)
        cd_overdue = sum(1 for row in flag_rows if row["overdue"])

        # One row list per Collaboration table, the action at the end of each
        # row (owner, 2026-09-23), so each table pages as one list.
        regional_rows = [
            {
                "subject": e.subject,
                "detail": e.get_recommendation_display() if e.recommendation else "",
                "kind": "Training feedback",
                "when_label": "Observed",
                "when": e.held_on,
                "action_label": "Review",
                "drawer": f"{TRAINING_FEEDBACK_URL}/{e.id}",
            }
            for e in feedback
        ] + [
            {
                "subject": e.subject,
                "detail": "",
                "kind": "Coaching conversation",
                "when_label": "Held",
                "when": e.held_on,
                "action_label": "Acknowledge",
                "drawer": f"{REGIONAL_COACHING_URL}/{e.id}",
            }
            for e in coaching
        ]
        cd_rows = (
            [
                {
                    "subject": row["scope"],
                    "detail": row["note"],
                    "kind": "Quality flag",
                    "due": row["due"],
                    "status": row["status"],
                    "danger": row["overdue"],
                    "action_label": "Answer",
                    "href": QUALITY_FLAGS_URL,
                }
                for row in flag_rows
            ]
            + [
                {
                    "subject": e.subject,
                    "detail": "",
                    "kind": "Escalation",
                    "due": None,
                    "status": f"{e.get_status_display()} · {e.age_days}d open",
                    "danger": _is_overdue(e),
                    "action_label": "View",
                    "href": f"{ESCALATIONS_URL}#esc-raised",
                }
                for e in raised_open[:LIST_ROWS]
            ]
            + [
                {
                    "subject": e.subject,
                    "detail": (getattr(e, "decision_note", "") or "")[:160],
                    "kind": "Delegated back",
                    "due": None,
                    "status": "Yours to act on",
                    "danger": True,
                    "action_label": "Act",
                    "href": f"{ESCALATIONS_URL}#esc-raised",
                }
                for e in delegated
            ]
        )
        return {
            "regional_rows": regional_rows,
            "cd_rows": cd_rows,
            "cd_flags": {"open": cd_open, "overdue": cd_overdue, "rows": flag_rows},
            "regional_feedback": {
                "count": feedback_count,
                "rows": [
                    {
                        "subject": e.subject,
                        "held_on": e.held_on,
                        "recommendation": e.get_recommendation_display()
                        if e.recommendation
                        else "",
                    }
                    for e in feedback
                ],
            },
            "regional_coaching": {
                "count": coaching_count,
                "rows": [
                    {"subject": e.subject, "held_on": e.held_on} for e in coaching
                ],
            },
            "escalations": {
                "awaiting": len(raised_open),
                "overdue": sum(1 for e in raised_open if _is_overdue(e)),
                "delegated_back": len(delegated),
                "awaiting_rows": [
                    {
                        "subject": e.subject,
                        "age_days": e.age_days,
                        "overdue": _is_overdue(e),
                        "status": e.get_status_display(),
                    }
                    for e in raised_open[:LIST_ROWS]
                ],
                "delegated_rows": [
                    {
                        "subject": e.subject,
                        "note": (getattr(e, "decision_note", "") or "")[:160],
                    }
                    for e in delegated
                ],
            },
            "visit_requests": {
                "to_me": visits_to_me,
                "into_team": visits_into_team,
            },
            "partner_delivery": partner,
            "open_total": (
                cd_open
                + feedback_count
                + coaching_count
                + len(raised_open)
                + len(delegated)
                + visits_to_me
                + invoices
            ),
        }

    @staticmethod
    def partner_delivery(ctx: DashboardContext) -> dict:
        """Partner-delivered work the team monitors this year, in one read."""
        today = ctx.today
        qs = ctx.team_owned(
            Activity.objects.filter(
                fy=ctx.fy, deleted_at__isnull=True, delivery_type="partner"
            )
        ).exclude(status__in=RELEASED_STATUSES)
        counts = (
            qs.aggregate(
                planned=Count("id"),
                delivered=Count("id", filter=Q(status__in=COMPLETED_STATUSES)),
                awaiting_verification=Count(
                    "id", filter=Q(status="awaiting_ia_verification")
                ),
                late=Count(
                    "id",
                    filter=Q(planned_date__lt=today)
                    & ~Q(status__in=PARTNER_SETTLED_STATUSES)
                    & ~Q(status__in=COMPLETED_STATUSES),
                ),
                partners=Count("assigned_partner_id", distinct=True),
            )
            if ctx.team_ids
            else {}
        )
        return {
            "planned": counts.get("planned") or 0,
            "delivered": counts.get("delivered") or 0,
            "awaiting_verification": counts.get("awaiting_verification") or 0,
            "late": counts.get("late") or 0,
            "partners": counts.get("partners") or 0,
            "invoices_to_confirm": 0,
        }

    # ── 3. Priorities view ───────────────────────────────────────────────────
    @staticmethod
    def priorities_view(ctx: DashboardContext) -> dict:
        from apps.cce_leadership.guidance import guidance_summary
        from apps.hr.accountability import allocation_priorities

        contract = _safe(
            "priority contract",
            lambda: allocation_priorities(ctx.user, ctx.fy),
            {"rows": [], "pct": None},
        )
        return {
            "priorities": {
                "pct": contract.get("pct"),
                "rows": contract.get("rows") or [],
                "url": PRIORITIES_URL,
            },
            "distribution": ProgramLeadDashboardService.distribution_status(ctx),
            "ssa_informed": ProgramLeadDashboardService.ssa_informed_plans(ctx),
            "guidance": _safe(
                "guidance summary",
                lambda: guidance_summary(ctx.user),
                {
                    "issued": 0,
                    "open": 0,
                    "acknowledged": 0,
                    "awaiting": 0,
                    "latest": [],
                },
            ),
            "guidance_url": TEAM_GUIDANCE_URL,
        }

    @staticmethod
    def distribution_status(ctx: DashboardContext) -> dict:
        """How far each team target received from Impact Assessment has been
        distributed across the lead and their officers, and the officers'
        quarterly spreads waiting for the lead's approval. Two reads."""
        from decimal import Decimal

        from apps.hr.models import MilestoneAllocation

        staff_id = getattr(ctx.user, "staff_profile_id", None)
        if not staff_id:
            return {"rows": [], "spreads_waiting": 0, "undistributed": 0}
        teams = list(
            MilestoneAllocation.objects.filter(
                allocated_to_type="team",
                team_id=staff_id,
                status="approved",
                milestone__priority__fy=ctx.fy,
                milestone__active=True,
            )
            .select_related("milestone")
            .order_by("milestone__title")
        )
        children: dict = defaultdict(list)
        for child in MilestoneAllocation.objects.filter(
            parent_id__in=[t.id for t in teams],
            allocated_to_type="employee",
        ).exclude(status__in=("rejected", "superseded", "withdrawn")):
            children[child.parent_id].append(child)
        rows = []
        spreads_waiting = 0
        undistributed = 0
        for team in teams:
            kids = children.get(team.id, [])
            distributed = sum(
                (c.allocated_target or Decimal(0) for c in kids), Decimal(0)
            )
            approved = [c for c in kids if c.status == "approved"]
            waiting = [c for c in approved if c.quarter_status != "approved"]
            spreads_waiting += len(waiting)
            target = team.allocated_target
            if not kids:
                state, tone = "Not distributed", "danger"
                undistributed += 1
            elif len(approved) < len(kids):
                state, tone = "Distribution awaiting approval", "warning"
            elif target is not None and distributed != target:
                state, tone = "Out of balance", "warning"
            elif waiting:
                state, tone = "Quarterly spreads to approve", "warning"
            else:
                state, tone = "Distributed", "success"
            rows.append(
                {
                    "milestone": team.milestone.title,
                    "unit": team.milestone.target_unit or "",
                    "team_target": target,
                    "distributed": distributed,
                    "members": len(kids),
                    "spreads_waiting": len(waiting),
                    "state": state,
                    "tone": tone,
                }
            )
        return {
            "rows": rows,
            "spreads_waiting": spreads_waiting,
            "undistributed": undistributed,
            "url": TARGET_DISTRIBUTION_URL,
        }

    @staticmethod
    def ssa_informed_plans(ctx: DashboardContext) -> dict:
        """The share of each officer's judged plans the verified SSA informed
        (apps.ssa.plan_alignment), in one grouped read."""
        from apps.ssa.plan_alignment import INFORMED

        informed_values = [getattr(v, "value", v) for v in INFORMED]
        per: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        if ctx.team_ids:
            rows = (
                ctx.team_owned(
                    Activity.objects.filter(fy=ctx.fy, deleted_at__isnull=True)
                )
                .exclude(ssa_alignment="")
                .exclude(status__in=RELEASED_STATUSES)
                .values("responsible_staff_id", "monitored_by_staff_id")
                .annotate(
                    judged=Count("id"),
                    informed=Count("id", filter=Q(ssa_alignment__in=informed_values)),
                )
                .order_by()
            )
            for row in rows:
                owner = ctx.owner(
                    row["responsible_staff_id"], row["monitored_by_staff_id"]
                )
                if owner:
                    per[owner][0] += row["judged"]
                    per[owner][1] += row["informed"]
        out_rows = []
        for c in ctx.team:
            judged, informed = per.get(c["staff_id"], [0, 0])
            rate = _pct(informed, judged) if judged else None
            out_rows.append(
                {
                    "name": c["name"],
                    "judged": judged,
                    "informed": informed,
                    "rate": rate,
                    "tone": (
                        "neutral"
                        if rate is None
                        else (
                            "success"
                            if rate >= 80
                            else "warning"
                            if rate >= 50
                            else "danger"
                        )
                    ),
                }
            )
        judged_total = sum(r["judged"] for r in out_rows)
        informed_total = sum(r["informed"] for r in out_rows)
        return {
            "rows": out_rows,
            "judged": judged_total,
            "informed": informed_total,
            "rate": _pct(informed_total, judged_total) if judged_total else None,
        }

    # ── 4. Team view ─────────────────────────────────────────────────────────
    @staticmethod
    def team_view(ctx: DashboardContext) -> dict:
        waiting = ctx.handoffs
        rows = []
        for row in ctx.cceo_rows:
            rows.append({**row, "waiting": waiting["by_staff"].get(row["staff_id"], 0)})
        return {
            "cceo_performance": {"rows": rows},
            "roster_url": MY_TEAM_URL,
            "team_week": ProgramLeadDashboardService.team_week(ctx),
            "waiting_on_you": waiting,
            "follow_ups": ProgramLeadDashboardService.follow_ups(ctx),
        }

    @staticmethod
    def team_week(ctx: DashboardContext) -> dict:
        """Who is in the field today, who is away, and where the week is at
        risk from leave or load."""
        from apps.accounts.models import Leave

        today = ctx.today
        in_field: Counter = Counter()
        if ctx.team_ids:
            for resp, mon in (
                ctx.team_owned(Activity.objects.filter(deleted_at__isnull=True))
                .filter(Q(planned_date=today) | Q(scheduled_date__date=today))
                .exclude(status__in=RELEASED_STATUSES)
                .values_list("responsible_staff_id", "monitored_by_staff_id")
            ):
                owner = ctx.owner(resp, mon)
                if owner:
                    in_field[owner] += 1
        iso = today.isoformat()
        on_leave = (
            [
                {
                    "name": ctx.name_of.get(leave.staff_id, "CCEO"),
                    "back": leave.end_date,
                }
                for leave in Leave.objects.filter(
                    staff_id__in=ctx.team_staff_ids,
                    status="approved",
                    start_date__lte=iso,
                    end_date__gte=iso,
                ).order_by("end_date")
            ]
            if ctx.team_staff_ids
            else []
        )
        return {
            "in_field": [
                {"name": ctx.name_of.get(staff_id, "CCEO"), "activities": n}
                for staff_id, n in sorted(
                    in_field.items(), key=lambda kv: ctx.name_of.get(kv[0], "")
                )
            ],
            "in_field_count": len(in_field),
            "on_leave": on_leave,
            "leave_conflicts": ctx.leave_conflicts,
            "overloaded": ctx.overloaded,
            "availability_url": TEAM_AVAILABILITY_URL,
        }

    @staticmethod
    def follow_ups(ctx: DashboardContext) -> dict:
        """The follow-ups this lead has sent, and where each one stands."""
        from apps.accounts.models import User
        from apps.planning.action_models import ACTIVE_STATES, ActionState, TeamAction

        today = ctx.today
        sent = TeamAction.objects.filter(sender_id=ctx.user.id)
        active = list(
            sent.filter(state__in=ACTIVE_STATES).order_by("due_date", "-detected_at")[
                :200
            ]
        )
        overdue = [
            a
            for a in active
            if a.state == ActionState.OVERDUE or (a.due_date and a.due_date < today)
        ]
        names = dict(
            User.objects.filter(
                id__in={a.recipient_id for a in active[:FOLLOW_UP_ROWS]}
            ).values_list("id", "name")
        )
        return {
            "active": len(active),
            "overdue": len(overdue),
            "resolved": sent.filter(state=ActionState.RESOLVED, fy=ctx.fy).count(),
            "rows": [
                {
                    "recipient": names.get(a.recipient_id) or "Unknown recipient",
                    "action": a.requested_action
                    or (a.issue_type or "").replace("_", " ").capitalize(),
                    "due_date": a.due_date,
                    "is_overdue": a in overdue,
                    "state": a.get_state_display(),
                }
                for a in active[:FOLLOW_UP_ROWS]
            ],
            "url": ACTIONS_SENT_URL,
        }

    # ── 5. Coaching view ─────────────────────────────────────────────────────
    @staticmethod
    def coaching_view(ctx: DashboardContext) -> dict:
        """Per officer: where their review stands and whether it waits on the
        lead, any recovery plan, a catch-up plan or development request to
        decide, the last coaching conversation, and evidence quality."""
        from apps.cce_leadership.coaching import (
            coaching_summary,
            last_coaching_by_cceo,
        )
        from apps.hr.models import PerformanceImprovementPlan, PerformanceReview
        from apps.professional_development.models import (
            PDStatus,
            ProfessionalDevelopmentRequest,
        )

        staff_ids = ctx.team_staff_ids
        reviews: dict = {}
        plans: dict = {}
        pd_waiting: Counter = Counter()
        evidence: dict = defaultdict(lambda: {"returned": 0, "sf_pending": 0})
        if staff_ids:
            for review in PerformanceReview.objects.filter(
                staff_id__in=staff_ids, fy=ctx.fy
            ).order_by("staff_id", "-due_date", "-created_at"):
                reviews.setdefault(review.staff_id, review)
            for plan in PerformanceImprovementPlan.objects.filter(
                staff_id__in=staff_ids, status__in=OPEN_RECOVERY_STATUSES
            ).order_by("staff_id", "-start_date"):
                plans.setdefault(plan.staff_id, plan)
            pd_waiting = Counter(
                ProfessionalDevelopmentRequest.objects.filter(
                    staff_id__in=staff_ids, status=PDStatus.SUBMITTED_TO_SUPERVISOR
                ).values_list("staff_id", flat=True)
            )
            for row in (
                ctx.team_owned(ctx.acts)
                .values("responsible_staff_id", "monitored_by_staff_id")
                .annotate(
                    returned=Count(
                        "id", filter=Q(status__in=("returned_by_pl", "returned_by_ia"))
                    ),
                    sf_pending=Count(
                        "id",
                        filter=Q(
                            status__in=COMPLETED_STATUSES,
                            activity_type__in=VISIT_TYPES + TRAINING_TYPES,
                        )
                        & (
                            Q(salesforce_activity_id__isnull=True)
                            | Q(salesforce_activity_id="")
                        ),
                    ),
                )
                .order_by()
            ):
                owner = ctx.owner(
                    row["responsible_staff_id"], row["monitored_by_staff_id"]
                )
                if owner:
                    evidence[owner]["returned"] += row["returned"]
                    evidence[owner]["sf_pending"] += row["sf_pending"]
        last = _safe(
            "last coaching",
            lambda: last_coaching_by_cceo(ctx.user, staff_ids),
            {},
        )
        rows = []
        for c in ctx.team:
            review = reviews.get(c["staff_id"])
            plan = plans.get(c["staff_id"])
            coaching = last.get(c["staff_id"]) or {}
            quality = evidence.get(c["staff_id"], {"returned": 0, "sf_pending": 0})
            rows.append(
                {
                    "staff_id": c["staff_id"],
                    "name": c["name"],
                    "review_stage": review.get_stage_display() if review else "",
                    "review_waiting_on_you": bool(
                        review and review.stage in MANAGER_REVIEW_STAGES
                    ),
                    "recovery_plan": (
                        f"{plan.get_plan_type_display()} · {plan.get_status_display()}"
                        if plan
                        else ""
                    ),
                    "catch_up": ctx.catch_up_by_user.get(c["user_id"], 0),
                    "pd_to_review": pd_waiting.get(c["staff_id"], 0),
                    "last_coaching": coaching.get("held_on"),
                    "last_coaching_kind": coaching.get("kind_label") or "",
                    "coaching_open_follow_up": bool(coaching.get("open_follow_up")),
                    "returned": quality["returned"],
                    "sf_pending": quality["sf_pending"],
                    "conversation_url": (
                        f"/performance-conversation?{urlencode({'staff': c['staff_id']})}"
                    ),
                    "coaching_url": f"{COACHING_URL}?{urlencode({'cceo': c['staff_id']})}",
                }
            )
        return {
            "coaching_rows": rows,
            "coaching_summary": _safe(
                "coaching summary",
                lambda: coaching_summary(ctx.user, today=ctx.today),
                {
                    "team_size": len(ctx.team),
                    "coached_this_month": 0,
                    "awaiting_acknowledgement": 0,
                    "follow_ups_due": 0,
                    "drafts": 0,
                },
            ),
            "coaching_links": {
                "coaching": COACHING_URL,
                "reviews": PERFORMANCE_REVIEWS_URL,
                "recovery": RECOVERY_PLANS_URL,
                "development": DEVELOPMENT_URL,
                "team_targets": TEAM_TARGETS_URL,
                "evidence": EVIDENCE_URL,
            },
            "coaching_totals": {
                "reviews_waiting": sum(1 for r in rows if r["review_waiting_on_you"]),
                "recovery_plans": sum(1 for r in rows if r["recovery_plan"]),
                "catch_up": sum(r["catch_up"] for r in rows),
                "pd_to_review": sum(r["pd_to_review"] for r in rows),
                "returned": sum(r["returned"] for r in rows),
                "sf_pending": sum(r["sf_pending"] for r in rows),
            },
        }

    # ── 6. Programmes view ───────────────────────────────────────────────────
    @staticmethod
    def programmes_view(ctx: DashboardContext, *, urgent_page=1) -> dict:
        urgent = ProgramLeadDashboardService.urgent_schools_page(
            ctx.user, ctx.pls, ctx.fy, {}, page=urgent_page
        )
        return {
            "ssa_rollout": ctx.ssa_rollout,
            "ssa_matrix": ProgramLeadDashboardService.ssa_cluster_matrix(
                ctx.pls, ctx.fy
            ),
            "training_counts": ctx.training_counts,
            "delivery_mix": ProgramLeadDashboardService.delivery_mix(ctx),
            "delivery_by_month": ProgramLeadDashboardService.delivery_by_month(ctx),
            "planning_progress_chart": ProgramLeadDashboardService.planning_progress_by_member(
                ctx
            ),
            "spiritual": ProgramLeadDashboardService.spiritual_transformation(ctx),
            "urgent_schools": urgent["rows"],
            "urgent_pagination": urgent,
            "urgent_pagination_query": urlencode({"fy": ctx.fy, "view": "programmes"}),
            "can_assign_partner": RolePermissionService.can_assign_to_partner(ctx.user),
            "rollout_urls": {
                "trainings": f"{PROGRAMME_ROLLOUT_URL}?view=trainings",
                "ssa": f"{PROGRAMME_ROLLOUT_URL}?view=ssa",
                "spiritual": f"{PROGRAMME_ROLLOUT_URL}?view=spiritual",
            },
        }

    @staticmethod
    def ssa_rollout(ctx: DashboardContext) -> dict:
        """The school self-assessment rollout across the portfolio this year.

        A school counts as assessed when it holds a confirmed SSA record for
        the selected financial year; submitted is a record still with Impact
        Assessment; scheduled is SSA collection work planned for a school with
        neither. Each school is counted once, in the first state it reaches.
        """
        portfolio = len(ctx.pls.school_ids)
        if not portfolio:
            return {
                "portfolio": 0,
                "confirmed": 0,
                "submitted": 0,
                "scheduled": 0,
                "not_planned": 0,
                "coverage_pct": 0,
            }
        states = {}
        for school_id, status in (
            SsaRecord.objects.filter(
                school_id__in=ctx.pls.school_ref,
                fy=ctx.fy,
                verification_status__in=("confirmed", "pending"),
            )
            .values_list("school_id", "verification_status")
            .order_by()
            .distinct()
        ):
            if states.get(school_id) != "confirmed":
                states[school_id] = status
        confirmed = sum(1 for s in states.values() if s == "confirmed")
        submitted = sum(1 for s in states.values() if s == "pending")
        scheduled_ids = set(
            Activity.objects.filter(
                fy=ctx.fy,
                deleted_at__isnull=True,
                school_id__in=ctx.pls.school_ref,
                activity_type__in=SSA_COLLECTION_TYPES,
            )
            .exclude(status__in=RELEASED_STATUSES)
            .values_list("school_id", flat=True)
            .distinct()
        )
        scheduled = len(scheduled_ids - set(states))
        return {
            "portfolio": portfolio,
            "confirmed": confirmed,
            "submitted": submitted,
            "scheduled": scheduled,
            "not_planned": max(portfolio - confirmed - submitted - scheduled, 0),
            "coverage_pct": _pct(confirmed, portfolio),
        }

    @staticmethod
    def training_counts(ctx: DashboardContext) -> dict:
        counts = (
            ctx.acts.filter(activity_type__in=TRAINING_TYPES)
            .exclude(status__in=RELEASED_STATUSES)
            .aggregate(
                planned=Count("id"),
                delivered=Count("id", filter=Q(status__in=COMPLETED_STATUSES)),
            )
        )
        return {
            "planned": counts["planned"] or 0,
            "delivered": counts["delivered"] or 0,
            "schools_trained": len(trained_school_ids(ctx.pls.school_ref, fy=ctx.fy))
            if ctx.pls.school_ids
            else 0,
        }

    @staticmethod
    def delivery_mix(ctx: DashboardContext) -> list[dict]:
        """Planned and completed work per delivery family — the Regional Lead
        dashboard's families, so both leads read the programme the same way."""
        from apps.analytics.rpl_dashboard_service import (
            DELIVERY_FAMILIES,
            OTHER_FAMILY,
            _family_of,
        )

        totals: dict = defaultdict(lambda: [0, 0])
        for row in ctx.type_counts:
            family = _family_of(row["activity_type"])
            totals[family][0] += row["planned"]
            totals[family][1] += row["completed"]
        families = [(key, label, hint) for key, label, hint, _m in DELIVERY_FAMILIES]
        families.append(OTHER_FAMILY)
        rows = []
        for key, label, hint in families:
            planned, completed = totals.get(key, [0, 0])
            if key == OTHER_FAMILY[0] and not planned:
                continue
            pct = min(round(completed * 100 / planned), 100) if planned else 0
            rows.append(
                {
                    "key": key,
                    "label": label,
                    "hint": hint,
                    "planned": planned,
                    "completed": completed,
                    "completed_pct": pct,
                    "tone": (
                        "neutral"
                        if not planned
                        else (
                            "success"
                            if pct >= 80
                            else "warning"
                            if pct >= 50
                            else "danger"
                        )
                    ),
                }
            )
        return rows

    @staticmethod
    def delivery_by_month(ctx: DashboardContext) -> dict:
        """Team Execution Progress: completed work in each FY month, one series
        per person — the lead's own work first, then each supervised officer
        in roster order — with the cumulative share of the year's plan done.
        Field execution, not IA-verified — the ledger-weighted figure is the
        priority progress tile. One grouped read.

        A person is a series whether or not they completed anything, so the
        chart reads as the team and a quiet month shows as a quiet month
        rather than as a missing officer. Work on a portfolio school that
        belongs to nobody on the roster folds into "Others (at portfolio
        schools)" — it is counted in the share of plan done and must not
        vanish from the columns."""
        from django.db.models.functions import TruncMonth

        bounds = [get_month_date_range(ctx.fy, m) for m in range(1, 13)]
        index = {(b[0].year, b[0].month): i for i, b in enumerate(bounds)}
        lead_key = "__lead__"
        lead_label = f"{getattr(ctx.user, 'name', '') or 'My work'} (you)"
        people = [(lead_key, lead_label)] + [
            (c["staff_id"], c["name"]) for c in ctx.team
        ]
        series = {key: [0] * 12 for key, _ in people}
        others = [0] * 12
        for row in (
            ctx.acts.filter(
                status__in=COMPLETED_STATUSES,
                planned_date__gte=bounds[0][0].date(),
                planned_date__lt=bounds[11][1].date(),
            )
            .annotate(m=TruncMonth("planned_date"))
            .values("m", "responsible_staff_id", "monitored_by_staff_id")
            .annotate(n=Count("id"))
            .order_by()
        ):
            month = row["m"]
            slot = index.get((month.year, month.month)) if month else None
            if slot is None:
                continue
            responsible = row["responsible_staff_id"]
            monitored = row["monitored_by_staff_id"]
            owner = ctx.owner(responsible, monitored)
            if owner is None and (responsible or monitored) in ctx.own_ids:
                owner = lead_key
            (series[owner] if owner in series else others)[slot] += row["n"]
        planned_total = sum(r["planned"] for r in ctx.type_counts)
        cumulative = []
        running = 0
        for slot in range(12):
            running += sum(values[slot] for values in series.values()) + others[slot]
            cumulative.append(
                min(round(running * 100 / planned_total), 100) if planned_total else 0
            )
        payload_series = [{"name": label, "data": series[key]} for key, label in people]
        if any(others):
            payload_series.append(
                {"name": "Others (at portfolio schools)", "data": others}
            )
        return {
            "title": "Team Execution Progress",
            "labels": [b[0].strftime("%b") for b in bounds],
            "series": payload_series,
            "cumulative_pct": cumulative,
            "has_work": any(any(v) for v in series.values()) or any(others),
        }

    @staticmethod
    def planning_progress_by_member(ctx: DashboardContext) -> dict:
        """Monthly completion rates, for up to six elapsed months in this FY.

        Keep every roster member, including those with no plans. Attribute
        partner delivery to its monitor only when no responsible owner exists.
        Aggregate in SQL rather than loading every activity into Python.
        """
        from django.db.models.functions import TruncMonth

        bounds = [get_month_date_range(ctx.fy, m) for m in range(1, 13)]
        bounds = [b for b in bounds if b[0].date() <= ctx.today][-6:]
        people = [("__lead__", f"{getattr(ctx.user, 'name', '') or 'My work'} (you)")]
        people += [(c["staff_id"], c["name"] or "Officer") for c in ctx.team]
        buckets = {key: [[0, 0] for _ in bounds] for key, _ in people}
        index = {(b[0].year, b[0].month): i for i, b in enumerate(bounds)}
        if bounds:
            rows = (
                ctx.acts.filter(
                    planned_date__gte=bounds[0][0].date(),
                    planned_date__lt=bounds[-1][1].date(),
                )
                .exclude(status__in=RELEASED_STATUSES)
                .annotate(completion_month=TruncMonth("planned_date"))
                .values(
                    "completion_month", "responsible_staff_id", "monitored_by_staff_id"
                )
                .annotate(
                    total=Count("id"),
                    done=Count("id", filter=Q(status__in=COMPLETED_STATUSES)),
                )
                .order_by()
            )
            for row in rows:
                responsible = row["responsible_staff_id"]
                monitored = row["monitored_by_staff_id"]
                owner = ctx.owner(responsible, monitored)
                if owner is None and (responsible or monitored) in ctx.own_ids:
                    owner = "__lead__"
                if owner not in buckets:
                    continue
                slot = index[
                    (row["completion_month"].year, row["completion_month"].month)
                ]
                buckets[owner][slot][0] += row["total"]
                buckets[owner][slot][1] += row["done"]
        series = [
            {
                "name": label,
                "data": [
                    round(done * 100 / total) if total else None
                    for total, done in buckets[key]
                ],
            }
            for key, label in people
        ]
        return {
            "labels": [b[0].strftime("%b %y") for b in bounds],
            "series": series,
            "has_data": any(
                value is not None for member in series for value in member["data"]
            ),
        }

    @staticmethod
    def spiritual_transformation(ctx: DashboardContext) -> dict:
        """Christlike Behaviour and Exposure to the Word of God: the team's
        latest confirmed score against the previous cycle."""
        spiritual = ("christlike_behaviour", "exposure_to_word_of_god")
        data = _safe(
            "spiritual interventions",
            lambda: PLAnalyticsService.ssa_interventions(ctx.pls, ctx.fy),
            {"rows": []},
        )
        rows = []
        for r in data.get("rows", []):
            if r.get("value") not in spiritual:
                continue
            delta = r.get("delta")
            if delta is None:
                change = "No previous cycle to compare"
            elif delta > 0:
                change = f"Up {delta:g} on the previous cycle"
            elif delta < 0:
                change = f"Down {abs(delta):g} on the previous cycle"
            else:
                change = "No change on the previous cycle"
            rows.append({**r, "change": change})
        return {
            "rows": rows,
            "latest_fy": data.get("latest_fy"),
            "prev_fy": data.get("prev_fy"),
        }

    # ── 7. Collaboration view ────────────────────────────────────────────────
    @staticmethod
    def collaboration_view(ctx: DashboardContext) -> dict:
        from apps.partners.engagement_services import engagement_summary

        return {
            "collaboration": ctx.collaboration,
            "partner_engagement": _safe(
                "partner engagement",
                lambda: engagement_summary(ctx.user, ctx.fy),
                {
                    "recorded": 0,
                    "follow_ups_due": 0,
                    "partners_engaged": 0,
                    "latest": [],
                },
            ),
            "collaboration_urls": {
                "flags": QUALITY_FLAGS_URL,
                "feedback": TRAINING_FEEDBACK_URL,
                "coaching": REGIONAL_COACHING_URL,
                "escalations": ESCALATIONS_URL,
                "partners": PARTNER_OVERSIGHT_URL,
                "invoices": FUND_APPROVALS_URL,
                "visit_requests": _visit_queue_url(),
            },
        }

    # ── Urgent schools (Programmes, last) ────────────────────────────────────
    @staticmethod
    def urgent_schools(user, pls, fy, filters, limit=8) -> list[dict]:
        """Compatibility helper for callers that only need the first page."""
        return ProgramLeadDashboardService.urgent_schools_page(
            user, pls, fy, filters, page_size=limit
        )["rows"]

    @staticmethod
    def urgent_schools_page(user, pls, fy, filters, page=1, page_size=None) -> dict:
        """Return the PL's combined personal + supervised urgent queue.

        Ownership is explicit on every row so the dashboard can schedule the
        PL's own work while delegating a supervised CCEO's school to that CCEO.
        The dashboard deliberately renders four rows per page so the urgent
        queue stays immediately actionable instead of becoming a long table.
        """
        from apps.accounts.models import StaffSchoolAssignment
        from apps.core.scoping import resolve_user_scope

        try:
            page = max(int(page), 1)
        except (TypeError, ValueError):
            page = 1
        page_size = page_size or ProgramLeadDashboardService.URGENT_SCHOOLS_PAGE_SIZE
        page_size = max(int(page_size), 1)

        risk_page = PLAnalyticsService.risk_list(
            pls,
            fy,
            None,
            filters,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        total = risk_page["total"]
        page_count = max((total + page_size - 1) // page_size, 1)
        if page > page_count:
            page = page_count
            risk_page = PLAnalyticsService.risk_list(
                pls,
                fy,
                None,
                filters,
                limit=page_size,
                offset=(page - 1) * page_size,
            )
        rows = risk_page["rows"]
        scope = resolve_user_scope(user)
        own_school_ids = set(scope.own_school_ids)
        cceo_by_staff = {item["staff_id"]: item for item in pls.cceos}
        owner_by_school = {}
        assignments = StaffSchoolAssignment.objects.filter(
            staff_id__in=cceo_by_staff, school_id__in=[row["id"] for row in rows]
        ).order_by("created_at")
        for assignment in assignments:
            owner_by_school.setdefault(
                assignment.school_id, cceo_by_staff.get(assignment.staff_id)
            )

        for row in rows:
            owner = owner_by_school.get(row["id"])
            is_personal = row["id"] in own_school_ids or owner is None
            row["owner_kind"] = "pl" if is_personal else "cceo"
            row["owner_name"] = (
                getattr(user, "name", "Program Lead") if is_personal else owner["name"]
            )
            row["owner_user_id"] = None if is_personal else owner["user_id"]
            query = {
                "school_id": row["id"],
                "recommended_activity_type": row["recommended_activity_type"],
            }
            if row["weakest_intervention_code"]:
                query["focus_intervention"] = row["weakest_intervention_code"]
            row["schedule_url"] = f"/planning/schedule-modal?{urlencode(query)}"
            # Handing the work to a partner is the alternative to scheduling it
            # yourself, so the row offers both.
            partner_query = {"school_id": row["id"]}
            if row["weakest_intervention_code"]:
                partner_query["focus_intervention"] = row["weakest_intervention_code"]
            row["partner_url"] = (
                f"/planning/assign-partner-modal?{urlencode(partner_query)}"
            )
            # The row's primary action. risk_list names the recommended work
            # (recommended_activity_label) and this loop builds the URL that
            # opens it (schedule_url); the shared table renders action_*.
            # Short on purpose: the recommended work is already named in its
            # own column, so the verb is what the button contributes. The full
            # recommendation stays on the control as its title.
            row["action_label"] = "Schedule"
            row["action_title"] = (
                row.get("recommended_activity_label") or "Open Planning"
            )
            row["action_url"] = row["schedule_url"]
            row["action_mode"] = "drawer"
        first_row = (page - 1) * page_size + 1 if total else 0
        return {
            "rows": rows,
            "total": total,
            "page": page,
            "page_count": page_count,
            "page_size": page_size,
            "first_row": first_row,
            "last_row": first_row + len(rows) - 1 if rows else 0,
            "has_previous": page > 1,
            "has_next": page < page_count,
            "previous_page": page - 1 if page > 1 else None,
            "next_page": page + 1 if page < page_count else None,
        }

    # ── Shared scoped querysets ──────────────────────────────────────────────
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
            base = base.filter(school_id__in=pls.school_ref)
        else:
            base = base.filter(
                Q(responsible_staff_id__in=ids) | Q(school_id__in=pls.school_ref)
            )
        atype = ((filters or {}).get("activity_type") or "").strip()
        if atype:
            base = base.filter(activity_type=atype)
        return base

    @staticmethod
    def _cceo_ids(cceo):
        ids = {cceo["staff_id"]}
        if cceo["user_id"]:
            ids.add(cceo["user_id"])
        return ids

    # ── Compact roster (Team view) ───────────────────────────────────────────
    @staticmethod
    def cceo_performance(ctx: DashboardContext) -> list[dict]:
        """One row per officer: district, schools, verified of planned work,
        Activity SF IDs pending, and the risk band. The risk is PLAnalyticsService._cceo_risk, the one
        officer-risk definition the platform shows; its base rows cost one read
        per officer (PLAnalyticsService.cceo_performance). The planned and
        verified counts and the districts are one grouped read each."""
        base = PLAnalyticsService.cceo_performance(ctx.pls, ctx.fy, None, {})["rows"]
        per: dict = defaultdict(lambda: [0, 0, 0])
        if ctx.team_ids:
            for row in (
                ctx.team_owned(ctx.acts)
                .exclude(status__in=RELEASED_STATUSES)
                .values("responsible_staff_id", "monitored_by_staff_id")
                .annotate(
                    planned=Count("id"),
                    verified=Count("id", filter=Q(status__in=VERIFIED_STATUSES)),
                    sf_pending=Count(
                        "id",
                        filter=Q(
                            status__in=COMPLETED_STATUSES,
                            activity_type__in=VISIT_TYPES + TRAINING_TYPES,
                        )
                        & (
                            Q(salesforce_activity_id__isnull=True)
                            | Q(salesforce_activity_id="")
                        ),
                    ),
                )
                .order_by()
            ):
                owner = ctx.owner(
                    row["responsible_staff_id"], row["monitored_by_staff_id"]
                )
                if owner:
                    per[owner][0] += row["planned"]
                    per[owner][1] += row["verified"]
                    per[owner][2] += row["sf_pending"]
        districts = ProgramLeadDashboardService._cceo_districts(ctx.pls)
        rows = []
        for r in base:
            planned, verified, sf_pending = per.get(r["staff_id"], [0, 0, 0])
            rows.append(
                {
                    **r,
                    "region": districts.get(r["staff_id"], "—"),
                    "planned": planned,
                    "verified": verified,
                    "sf_pending": sf_pending,
                    "waiting": 0,
                    "verified_pct": _pct(verified, planned) if planned else None,
                    "has_planned": planned > 0,
                }
            )
        return rows

    @staticmethod
    def _cceo_districts(pls) -> dict[str, str]:
        """Most common district across each officer's schools, in one read."""
        school_owner: dict[str, list[str]] = defaultdict(list)
        for c in pls.cceos:
            for school_id in c["school_ids"]:
                school_owner[school_id].append(c["staff_id"])
        if not school_owner:
            return {}
        tallies: dict[str, Counter] = defaultdict(Counter)
        for school_id, district in (
            School.objects.filter(id__in=list(school_owner))
            .exclude(district__isnull=True)
            .values_list("id", "district__name")
        ):
            for staff_id in school_owner[school_id]:
                tallies[staff_id][district] += 1
        return {
            staff_id: counter.most_common(1)[0][0]
            for staff_id, counter in tallies.items()
            if counter
        }

    # ── Team this week helpers ───────────────────────────────────────────────
    @staticmethod
    def _overloaded_cceos(pls, fy, acts):
        today = timezone.localdate()
        wk_start = today - timedelta(days=today.weekday())
        # One pass over this week's activities instead of a COUNT per CCEO.
        owner_of = {}
        for c in pls.cceos:
            for i in ProgramLeadDashboardService._cceo_ids(c):
                owner_of[i] = c["staff_id"]
        week_load = dict.fromkeys((c["staff_id"] for c in pls.cceos), 0)
        if owner_of:
            for owner_id in acts.filter(
                responsible_staff_id__in=list(owner_of),
                scheduled_date__date__gte=wk_start,
                scheduled_date__date__lte=wk_start + timedelta(days=6),
            ).values_list("responsible_staff_id", flat=True):
                key = owner_of.get(owner_id)
                if key is not None:
                    week_load[key] += 1
        out = []
        for c in pls.cceos:
            n_schools = len(c["school_ids"])
            wk = week_load.get(c["staff_id"], 0)
            if n_schools > CCEO_SCHOOL_CAPACITY or wk > CCEO_WEEKLY_ACTIVITY_CAPACITY:
                out.append({"name": c["name"], "schools": n_schools, "week_load": wk})
        return out

    @staticmethod
    def _leave_conflicts(ctx: DashboardContext) -> list[dict]:
        """Approved or pending officer leave in the next week that clashes with
        work scheduled inside the leave window. Leave with no scheduled work is
        time off, not a conflict. Two reads, however many requests there are."""
        from apps.accounts.models import Leave

        if not ctx.team_staff_ids:
            return []
        today = ctx.today
        horizon = today + timedelta(days=LEAVE_LOOKAHEAD_DAYS)
        leaves = list(
            Leave.objects.filter(
                staff_id__in=ctx.team_staff_ids,
                status__in=["approved", "pending"],
                start_date__lte=horizon.isoformat(),
                end_date__gte=today.isoformat(),
            ).only("id", "staff_id", "start_date", "end_date", "status")
        )
        windows = []
        for leave in leaves:
            try:
                start = date.fromisoformat(str(leave.start_date)[:10])
                end = date.fromisoformat(str(leave.end_date)[:10])
            except ValueError:
                continue
            windows.append((leave, start, end))
        if not windows:
            return []
        first = min(w[1] for w in windows)
        last = max(w[2] for w in windows)
        scheduled: dict[str, list[date]] = defaultdict(list)
        for resp, mon, when in (
            ctx.team_owned(Activity.objects.filter(deleted_at__isnull=True))
            .filter(scheduled_date__date__gte=first, scheduled_date__date__lte=last)
            .exclude(status="cancelled")
            .values_list(
                "responsible_staff_id", "monitored_by_staff_id", "scheduled_date"
            )
        ):
            owner = ctx.owner(resp, mon)
            if owner and when:
                scheduled[owner].append(timezone.localtime(when).date())
        out = []
        for leave, start, end in windows:
            clashes = sum(
                1 for d in scheduled.get(leave.staff_id, []) if start <= d <= end
            )
            if clashes:
                out.append(
                    {
                        "name": ctx.name_of.get(leave.staff_id, "CCEO"),
                        "start": start,
                        "end": end,
                        "status": leave.status,
                        "activities": clashes,
                    }
                )
        return out

    # ── SSA heatmap (Programmes) ─────────────────────────────────────────────
    @staticmethod
    def ssa_cluster_matrix(pls, fy) -> dict:
        latest_fy, _ = PLAnalyticsService._cycle_fys(pls, fy)
        schools = School.objects.filter(id__in=pls.school_ref)
        cluster_ids = list(
            schools.exclude(cluster_id__isnull=True)
            .exclude(cluster_id="")
            .order_by("cluster_id")
            .values_list("cluster_id", flat=True)
            .distinct()
        )
        from apps.clusters.models import Cluster

        cluster_metadata = {
            row["id"]: row
            for row in Cluster.objects.filter(id__in=cluster_ids).values(
                "id", "name", "district_id", "district__name"
            )
        }
        names = {key: row["name"] for key, row in cluster_metadata.items()}
        # All eight interventions: a matrix that silently omits two columns
        # reads as complete while hiding the two a reader might most need.
        cols = list(SSA_INTERVENTIONS)
        rows = []
        if not latest_fy:
            return {
                "rows": [],
                "columns": [c[1] for c in cols],
                "codes": [c[2] for c in cols],
            }
        # Two grouped reads for the whole matrix.
        records = SsaRecord.objects.filter(
            school__in=schools.exclude(cluster_id__isnull=True).exclude(cluster_id=""),
            verification_status="confirmed",
            fy=latest_fy,
        )
        by_cluster_int: dict = {}
        for r in (
            SsaScore.objects.filter(ssa_record__in=records)
            .values("ssa_record__school__cluster_id", "intervention")
            .annotate(a=Avg("score"))
            .order_by()
        ):
            by_cluster_int.setdefault(r["ssa_record__school__cluster_id"], {})[
                r["intervention"]
            ] = r["a"]
        overall_by_cluster = {
            r["school__cluster_id"]: r["a"]
            for r in records.values("school__cluster_id")
            .annotate(a=Avg("average_score"))
            .order_by()
        }
        for cid in cluster_ids:
            by_int = by_cluster_int.get(cid, {})
            cells = []
            for v, label, code in cols:
                score = _ssa_score(by_int.get(v))
                band = ssa_band(score)
                # heat is the score rounded to a whole step, 0-10, or None: a
                # band paints 5.0 and 6.9 identically, and on a comparison
                # matrix that flattens the differences a reader scans for.
                cells.append(
                    {
                        "score": score,
                        "tone": band[2],
                        "heat": None
                        if score is None
                        else max(0, min(10, round(score))),
                    }
                )
            overall = _ssa_score(overall_by_cluster.get(cid))
            oband = ssa_band(overall)
            rows.append(
                {
                    "id": cid,
                    "name": names.get(cid, "Cluster"),
                    "district": cluster_metadata.get(cid, {}).get("district__name")
                    or "Unassigned district",
                    "cells": cells,
                    "overall": overall,
                    "overall_tone": oband[2],
                    "overall_heat": (
                        None if overall is None else max(0, min(10, round(overall)))
                    ),
                }
            )
        return {
            "rows": rows,
            "columns": [c[1] for c in cols],
            "codes": [c[2] for c in cols],
        }

    # ── Verified monthly series (read by the analytics cockpit's tests) ──────
    @staticmethod
    def team_performance(pls, fy, filters) -> dict:
        base = PLAnalyticsService.team_performance(pls, fy, None, filters)
        from django.db.models.functions import TruncMonth

        acts = ProgramLeadDashboardService._team_acts(pls, fy, filters)
        bounds = {m: get_month_date_range(fy, m) for m in range(1, 13)}
        # One grouped query instead of twelve COUNTs against `activity`.
        by_month = {
            (r["m"].year, r["m"].month): r["n"]
            for r in acts.filter(
                planned_date__gte=bounds[1][0].date(),
                planned_date__lt=bounds[12][1].date(),
                status__in=VERIFIED_STATUSES,
            )
            .annotate(m=TruncMonth("planned_date"))
            .values("m")
            .annotate(n=Count("id"))
        }
        base["verified"] = [
            by_month.get((bounds[m][0].year, bounds[m][0].month), 0)
            for m in range(1, 13)
        ]
        return base

    # ── Waiting on you, as a drawer ──────────────────────────────────────────
    @staticmethod
    def approval_queue(user, pls, fy) -> dict:
        """The approvals a lead decides, each row leading to the page where it
        is decided: a weekly fund request to Fund Approvals, a completion to
        Completion Reviews. The drawer approves nothing itself — an inline
        approve re-rendered the page without its view rail."""
        from apps.fund_requests.models import WeeklyFundRequest
        from apps.pl_review.services import queue as review_queue

        name_by_uid = {c["user_id"]: c["name"] for c in pls.cceos if c["user_id"]}
        name_by_id = {**name_by_uid, **{c["staff_id"]: c["name"] for c in pls.cceos}}
        rows = []
        for w in WeeklyFundRequest.objects.filter(
            status="submitted_to_pl", responsible_user__in=list(name_by_uid)
        ).order_by("week_start_date")[:15]:
            rows.append(
                {
                    "kind": "weekly_fund",
                    "id": w.id,
                    "staff": name_by_uid.get(w.responsible_user, "CCEO"),
                    "covered": f"Week of {w.week_start_date:%-d %b}",
                    "submitted": w.updated_at,
                    "amount": w.total_amount,
                    "url": FUND_APPROVALS_URL,
                    "action_label": "Open Fund Approvals",
                }
            )
        by_owner: dict = defaultdict(list)
        for row in _safe("review queue", lambda: review_queue(user), []):
            by_owner[row.get("responsibleStaffId")].append(row)
        for owner, items in list(by_owner.items())[:15]:
            rows.append(
                {
                    "kind": "completion",
                    "id": owner,
                    "staff": name_by_id.get(owner, "CCEO"),
                    "covered": (
                        f"{len(items)} completed {_plural(len(items), 'activity', 'activities')}"
                    ),
                    "submitted": None,
                    "amount": None,
                    "url": REVIEW_QUEUE_URL,
                    "action_label": "Open Completion Reviews",
                }
            )
        return {"rows": rows[:24], "total": len(rows)}

    # ── Drill-downs (all scoped) ─────────────────────────────────────────────
    @staticmethod
    def drilldown(user, drill: str, fy=None) -> dict:
        """The drawers the views open. Every one reads the same team as the
        page: `approvals`, `cceos`, `overload`, `leave_conflicts`, `week` and
        `sf_backlog`; anything else is the approvals drawer."""
        fy = fy or get_operational_fy()
        ctx = DashboardContext(user, fy)
        pls = ctx.pls
        if drill == "cceos":
            return {
                "kind": "cceos",
                "title": "Your officers",
                "subtitle": f"{len(ctx.team)} supervised CCEOs · FY {fy}",
                "cceos": ctx.cceo_rows,
            }
        if drill == "overload":
            return {
                "kind": "overload",
                "title": "Overloaded officers",
                "subtitle": "Above healthy school or weekly capacity",
                "overloaded": ctx.overloaded,
            }
        if drill == "leave_conflicts":
            return {
                "kind": "leave_conflicts",
                "title": "Leave conflicts",
                "subtitle": f"Leave in the next {LEAVE_LOOKAHEAD_DAYS} days that overlaps scheduled work",
                "leave_conflicts": ctx.leave_conflicts,
            }
        if drill == "sf_backlog":
            qs = ctx.team_owned(_requires_sf_id(ctx.acts)).filter(
                Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id="")
            )
            return {
                "kind": "activities",
                "title": "Activity SF IDs pending",
                "subtitle": f"{qs.count()} completed activities without an Activity SF ID",
                "activities": ProgramLeadDashboardService._activity_rows(qs[:150], pls),
            }
        if drill == "week":
            today = timezone.localdate()
            wk = today - timedelta(days=today.weekday())
            qs = ctx.team_owned(ctx.acts).filter(
                scheduled_date__date__gte=wk,
                scheduled_date__date__lte=wk + timedelta(days=6),
            )
            return {
                "kind": "activities",
                "title": "Your team this week",
                "subtitle": f"{qs.count()} scheduled",
                "activities": ProgramLeadDashboardService._activity_rows(qs[:150], pls),
            }
        return {
            "kind": "approvals",
            "title": "Waiting on your approval",
            "subtitle": "Each opens the page where it is decided",
            "approval_queue": ProgramLeadDashboardService.approval_queue(user, pls, fy),
        }

    @staticmethod
    def _activity_rows(qs, pls):
        name_by = {c["staff_id"]: c["name"] for c in pls.cceos}
        name_by.update({c["user_id"]: c["name"] for c in pls.cceos if c["user_id"]})
        rows = []
        for a in qs.select_related("school"):
            rows.append(
                {
                    "type": a.get_activity_type_display(),
                    "school_id": a.school_id,
                    "school": a.school.name if a.school_id else "—",
                    "owner": name_by.get(
                        a.responsible_staff_id or a.monitored_by_staff_id, "—"
                    ),
                    "status": a.status.replace("_", " ").title(),
                    "planned": a.planned_date,
                }
            )
        return rows


def _seniority_key(role_value) -> str:
    """A leave policy's approver role in LeaveApprovalService's short form."""
    raw = "".join(str(role_value or "").split()).replace("_", "").lower()
    return {
        "cceo": "cceo",
        "programlead": "pl",
        "pl": "pl",
        "countrydirector": "cd",
        "cd": "cd",
        "regionalvicepresident": "rvp",
        "rvp": "rvp",
    }.get(raw, "")


def _visit_queue_url() -> str:
    from apps.planning.visit_requests import QUEUE_URL

    return QUEUE_URL
