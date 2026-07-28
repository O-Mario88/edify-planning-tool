"""The one inventory of every card the platform is allowed to render.

Add a card by adding one ``CardSpec`` here and rendering it through
``components/registered_card.html`` -- never by hand-rolling another
``<div class="edify-surface rounded-surface border …">`` in whichever template
happens to need it. That is how the platform arrived at 555 titled card
surfaces, 525 distinct titles, and a "single source for all card surfaces"
component used twice.

Registration is deliberately front-loaded: a card that cannot say who may see
it, what question it answers, and what it means when empty is a card whose
behaviour nobody can predict.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from apps.core.cards.spec import AMBIGUOUS_TITLES, CardSpec, CardType
from apps.core.metrics.spec import FilterBehaviour, Period
from apps.core.navigation import ADMIN, CD, RVP


# The Admin "Main Dashboard" (`templates/pages/dashboards/main.html`), reached
# by the roles that have no dashboard branch of their own. This is the surface
# the card audit examined first, so it is the first registered.
_MAIN_DASHBOARD = "dashboard_main"

CARD_REGISTRY: tuple[CardSpec, ...] = (
    CardSpec(
        key="admin_todays_priorities",
        title="Today's Priorities",
        purpose=(
            "The activities scheduled for today across the whole country, with "
            "their time, related record and current status."
        ),
        question="What is happening in the country today?",
        action="Open the calendar, or an individual activity.",
        does_not_mean=(
            "Not a personal agenda -- an Admin has no own fieldwork. These are "
            "other people's activities."
        ),
        card_type=CardType.OPERATIONAL_QUEUE,
        owner_page=_MAIN_DASHBOARD,
        allowed_roles=frozenset({ADMIN}),
        scope="All activities in the country, unfiltered by owner",
        service="apps.command_center.dashboard_service.DashboardMetricsService",
        source_models=("activities.Activity",),
        period=Period.POINT_IN_TIME,
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        empty_message="Nothing scheduled for today.",
        drilldown="/calendar",
        refresh_events=("activity_scheduled", "activity_rescheduled"),
    ),
    CardSpec(
        key="admin_planning_progress",
        title="Planning Progress",
        purpose=(
            "Planned against completed activity across the weeks of the current "
            "period, so a flat or falling week is visible before it becomes a "
            "missed quarter."
        ),
        question="Is delivery keeping pace with the plan week by week?",
        action="Open Planning where a week is behind.",
        card_type=CardType.CHART,
        owner_page=_MAIN_DASHBOARD,
        allowed_roles=frozenset({ADMIN}),
        scope="Country-wide activities",
        service="apps.command_center.dashboard_service.DashboardMetricsService",
        source_models=("activities.Activity",),
        period=Period.MONTH,
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        empty_message="No planned activity in this period yet.",
        drilldown="/planning",
        refresh_events=("activity_scheduled", "activity_closed"),
    ),
    CardSpec(
        key="admin_ssa_intervention_extremes",
        title="SSA Performance Snapshot",
        purpose=(
            "The strongest and weakest interventions by average verified SSA "
            "score, so support can be aimed at the interventions that need it."
        ),
        question="Which interventions are strongest and weakest right now?",
        action="Open SSA to see the schools behind a weak intervention.",
        does_not_mean=(
            "Not a coverage measure. A school with no verified SSA contributes "
            "nothing here rather than counting as a zero."
        ),
        card_type=CardType.INSIGHT,
        owner_page=_MAIN_DASHBOARD,
        allowed_roles=frozenset({ADMIN}),
        scope="Schools with a verified SSA record in scope",
        service="apps.command_center.dashboard_service.DashboardMetricsService",
        source_models=("ssa.SsaScore", "ssa.SsaRecord"),
        period=Period.FINANCIAL_YEAR,
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        empty_message="No verified SSA scores are available yet.",
        drilldown="/ssa",
        refresh_events=("ssa_verified",),
    ),
    CardSpec(
        key="admin_team_target_progress",
        title="Team Target Progress",
        purpose=(
            "Achievement against each official target area, with the status "
            "band for each."
        ),
        question="Which target areas are behind?",
        action="Open Team Targets for the area that is behind.",
        card_type=CardType.PROGRESS,
        owner_page=_MAIN_DASHBOARD,
        allowed_roles=frozenset({ADMIN}),
        scope="Country-wide, across the official target areas",
        service="apps.command_center.dashboard_service.DashboardMetricsService",
        source_models=("targets.TargetArea", "activities.Activity"),
        period=Period.FINANCIAL_YEAR,
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        empty_message="No targets have been set for this financial year.",
        drilldown="/team-targets",
        refresh_events=("activity_ia_verified", "target_set"),
        notes=(
            "A second copy of this card rendered in the right rail with the "
            "same loop and the same numbers; it was removed. Team Targets owns "
            "the full analysis -- this is the preview."
        ),
    ),
    CardSpec(
        key="admin_priority_schools",
        title="Priority Schools",
        purpose=(
            "Schools whose planning readiness blocks work, with the district "
            "and the one action that would unblock each."
        ),
        question="Which schools cannot be planned against yet?",
        action="Upload the missing SSA, or open Planning.",
        does_not_mean=(
            "Not the lowest-performing schools. Readiness is a data-quality "
            "state, not a measure of school improvement."
        ),
        card_type=CardType.OPERATIONAL_QUEUE,
        owner_page=_MAIN_DASHBOARD,
        allowed_roles=frozenset({ADMIN}),
        scope="Schools in the country",
        service="apps.command_center.dashboard_service.DashboardMetricsService",
        source_models=("schools.School",),
        period=Period.POINT_IN_TIME,
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        empty_message="No priority schools in this scope.",
        drilldown="/schools",
        refresh_events=("ssa_verified", "school_updated"),
    ),
    CardSpec(
        key="admin_cluster_performance",
        title="Cluster Performance",
        purpose="Activity and score performance for each cluster.",
        question="Which clusters are underperforming?",
        action="Open the cluster to see its schools.",
        card_type=CardType.COMPARISON,
        owner_page=_MAIN_DASHBOARD,
        allowed_roles=frozenset({ADMIN}),
        scope="Clusters in the country",
        service="apps.command_center.dashboard_service.DashboardMetricsService",
        source_models=("clusters.Cluster", "activities.Activity"),
        period=Period.FINANCIAL_YEAR,
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        empty_message="No clusters have recorded activity yet.",
        drilldown="/clusters",
        refresh_events=("activity_closed",),
    ),
    CardSpec(
        key="admin_partner_support_overview",
        title="Partner Support Overview",
        purpose=(
            "Delivery by partner organisations -- what is assigned, scheduled "
            "and completed."
        ),
        question="Are partners delivering the work assigned to them?",
        action="Open Partners to chase an assignment.",
        card_type=CardType.ENTITY_SUMMARY,
        owner_page=_MAIN_DASHBOARD,
        allowed_roles=frozenset({ADMIN}),
        scope="All partner organisations",
        service="apps.command_center.dashboard_service.DashboardMetricsService",
        source_models=("partners.Partner", "activities.Activity"),
        period=Period.FINANCIAL_YEAR,
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        empty_message="No partner activity has been recorded yet.",
        drilldown="/partners",
        refresh_events=("activity_assigned_to_partner", "activity_closed"),
    ),
    CardSpec(
        key="admin_budget_and_fund_request_snapshot",
        title="Budget & Fund Request Snapshot",
        purpose=(
            "Where country money currently sits across the request, approval "
            "and disbursement stages."
        ),
        question="Is money moving through the finance pipeline?",
        action="Open Weekly Fund Requests to clear a stage.",
        does_not_mean=(
            "Not an expenditure figure. Requested and approved money has not "
            "necessarily been spent."
        ),
        card_type=CardType.FINANCIAL,
        owner_page=_MAIN_DASHBOARD,
        allowed_roles=frozenset({ADMIN}),
        scope="Country-wide weekly fund requests for the financial year",
        service="apps.command_center.dashboard_service.DashboardMetricsService",
        source_models=("fund_requests.WeeklyFundRequest",),
        period=Period.FINANCIAL_YEAR,
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        empty_message="No fund requests have been raised this financial year.",
        drilldown="/fund-requests/weekly",
        refresh_events=("fund_request_approved", "disbursement_created"),
    ),
    CardSpec(
        key="admin_upcoming_today",
        title="Upcoming Today",
        purpose="The next activities due today, as a compact rail preview.",
        question="What is still to happen today?",
        action="Open the activity.",
        card_type=CardType.PREVIEW,
        owner_page=_MAIN_DASHBOARD,
        allowed_roles=frozenset({ADMIN}),
        scope="Country-wide activities scheduled for today",
        service="apps.command_center.dashboard_service.DashboardMetricsService",
        source_models=("activities.Activity",),
        period=Period.POINT_IN_TIME,
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        empty_message="Nothing further is scheduled today.",
        drilldown="/calendar",
        refresh_events=("activity_scheduled",),
        notes=(
            "Deliberately distinct from Today's Priorities: that card is the "
            "full day in the main column, this is the short what-is-left rail "
            "preview. If the two ever show the same rows, merge them."
        ),
    ),
    CardSpec(
        key="admin_attention_needed",
        title="Attention Needed",
        purpose=(
            "Open items across SSA coverage, fund approvals and evidence, each "
            "with its count and a link to the queue that clears it."
        ),
        question="What is unresolved across the country right now?",
        action="Open the queue behind an item.",
        card_type=CardType.RISK,
        owner_page=_MAIN_DASHBOARD,
        allowed_roles=frozenset({ADMIN}),
        scope="Country-wide",
        service="apps.command_center.dashboard_service.DashboardMetricsService",
        source_models=(
            "schools.School",
            "fund_requests.WeeklyFundRequest",
            "activities.Activity",
        ),
        period=Period.POINT_IN_TIME,
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        empty_message="Nothing needs attention right now.",
        drilldown="/system-health",
        refresh_events=("ssa_verified", "fund_request_approved", "evidence_uploaded"),
    ),
    CardSpec(
        key="admin_next_recommended_action",
        title="Next Recommended Action",
        purpose=(
            "The single highest-priority item from Attention Needed, turned "
            "into one directive with the action that resolves it."
        ),
        question="If I do one thing now, what should it be?",
        action="Follow the card's call to action.",
        does_not_mean=(
            "Not additional information. It deliberately re-states the top item "
            "of Attention Needed as a decision -- a queue answers 'what is "
            "wrong', this answers 'what first'."
        ),
        card_type=CardType.RECOMMENDATION,
        owner_page=_MAIN_DASHBOARD,
        allowed_roles=frozenset({ADMIN}),
        scope="Country-wide",
        service="apps.command_center.dashboard_service.DashboardMetricsService",
        source_models=(
            "schools.School",
            "fund_requests.WeeklyFundRequest",
            "activities.Activity",
        ),
        period=Period.POINT_IN_TIME,
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        empty_message="All critical queues are clear.",
        drilldown="/system-health",
        refresh_events=("ssa_verified", "fund_request_approved", "evidence_uploaded"),
        notes=(
            "Shares its source counts with admin_attention_needed by design. "
            "The pairing is justified under §1 (a queue and a next action are "
            "different card purposes) and §20; both read the same locals, so "
            "there is no duplicated backend logic."
        ),
    ),
    CardSpec(
        key="admin_quick_actions",
        title="Quick Actions",
        purpose=(
            "Launchers for the three country-setup workflows an Admin starts "
            "rather than monitors."
        ),
        question="How do I start the work only an Admin begins?",
        action="Open the workflow.",
        card_type=CardType.ACTION,
        owner_page=_MAIN_DASHBOARD,
        allowed_roles=frozenset({ADMIN}),
        scope="Not data-bearing; navigation only",
        service="none -- static launchers, no backend read",
        source_models=(),
        period=Period.POINT_IN_TIME,
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        empty_message="No quick actions are available for this role.",
        no_drilldown_reason=(
            "The card is itself a set of links; a drill-down would duplicate " "them."
        ),
        notes=(
            "'Add School Visit' was removed: it pointed at /planning, the same "
            "destination as 'Schedule Activity' beside it, and /planning takes "
            "no activity-type parameter that could have told them apart."
        ),
    ),
    CardSpec(
        key="admin_execution_summary",
        title="Execution Summary",
        purpose=(
            "The country's completed, in-progress, planned and overdue activity "
            "split, as the closing summary of the dashboard."
        ),
        question="How is the country's workload distributed by state?",
        action="Open Planning or My Plan to act on a state.",
        card_type=CardType.PROGRESS,
        owner_page=_MAIN_DASHBOARD,
        allowed_roles=frozenset({ADMIN}),
        scope="Country-wide activities",
        service="apps.command_center.dashboard_service.DashboardMetricsService",
        source_models=("activities.Activity",),
        period=Period.FINANCIAL_YEAR,
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        empty_message="No activities have been recorded this financial year.",
        drilldown="/planning",
        refresh_events=("activity_closed", "activity_scheduled"),
    ),
)


# ── Accessors ────────────────────────────────────────────────────────────────
_BY_KEY: dict[str, CardSpec] = {c.key: c for c in CARD_REGISTRY}


def get_card(key: str) -> CardSpec:
    try:
        return _BY_KEY[key]
    except KeyError:
        raise KeyError(
            f"unregistered card {key!r} -- add a CardSpec to "
            f"apps/core/cards/registry.py before rendering it"
        ) from None


def all_cards() -> tuple[CardSpec, ...]:
    return CARD_REGISTRY


def cards_for_page(page: str) -> tuple[CardSpec, ...]:
    return tuple(c for c in CARD_REGISTRY if page in c.approved_pages())


def cards_for_role(role_slug: str) -> tuple[CardSpec, ...]:
    return tuple(c for c in CARD_REGISTRY if c.visible_to(role_slug))


def check() -> None:
    """Fail loudly on the defects this registry exists to prevent."""
    duplicate_keys = [
        key for key, n in Counter(c.key for c in CARD_REGISTRY).items() if n > 1
    ]
    if duplicate_keys:
        raise ValueError(f"duplicate card keys: {sorted(duplicate_keys)}")

    # Two cards with one title on one page are indistinguishable to a reader.
    # Across pages the same title may be legitimate (§7), so this is scoped to
    # the owning page.
    by_page: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for card in CARD_REGISTRY:
        by_page[card.owner_page].append((card.title.casefold(), card.key))
    for page, entries in by_page.items():
        titles = Counter(title for title, _ in entries)
        clashes = sorted(title for title, n in titles.items() if n > 1)
        if clashes:
            raise ValueError(f"{page}: two cards share a title: {clashes}")

    vague = [
        c.key for c in CARD_REGISTRY if c.title.strip().casefold() in AMBIGUOUS_TITLES
    ]
    if vague:
        raise ValueError(f"cards whose title names no information: {sorted(vague)}")


# Roles whose dashboards are known to be built by their own branch rather than
# the registered one. Kept so the eventual migration has a written target.
UNREGISTERED_DASHBOARD_ROLES = frozenset({CD, RVP})
