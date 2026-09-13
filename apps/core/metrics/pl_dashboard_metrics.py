"""Metric definitions for the Programme Lead dashboard's team pulse.

Program Lead alignment (owner, 2026-09-13). The six tiles each head one of the
role's responsibilities and open the dashboard view that explains them:
priority progress (strategic direction), officers on track (performance and
coaching), handoffs waiting on the lead (team leadership), SSA coverage and
trainings delivered (programme implementation), and open handoffs with the
lead's collaborators. They render through
``apps.analytics.pl_dashboard_service.ProgramLeadDashboardService.kpis``;
these rows are appended to the reconciled registry in reconciled_registry.py.

The canonical labels carry " — Program Lead dashboard" so they stay unique
beside the team roster's and Programme Rollout's own tiles; the page shows
the short source label.
"""

from __future__ import annotations

_SOURCE = "apps.analytics.pl_dashboard_service:kpis.tile"
_SERVICE = "apps.analytics.pl_dashboard_service.ProgramLeadDashboardService.kpis"
_LOCATION = "apps/analytics/pl_dashboard_service.py"
_ROLES = ("Program Lead", "Admin")
_SCOPE = (
    "The Programme Lead's team (apps.hr.team_roster.team_members) and the "
    "portfolio resolved by apps.analytics.pl_analytics_service.resolve_pl_scope"
)
_NOTE = "Programme Lead dashboard team pulse, rebuilt around the role on 2026-09-13."


def _row(
    key: str,
    source_label: str,
    *,
    line: int,
    view: str,
    definition: str,
    question: str,
    numerator: str,
    models: tuple[str, ...],
    category: str,
    unit: str = "count",
    denominator: str | None = None,
    period: str = "point_in_time",
    date_basis: str = "not_time_bound",
) -> dict:
    return {
        "key": f"analytics_pl_dashboard_{key}",
        "label": f"{source_label} — Program Lead dashboard",
        "source_label": source_label,
        "source": _SOURCE,
        "definition": definition,
        "question": question,
        "category": category,
        "unit": unit,
        "service": _SERVICE,
        "source_models": models,
        "numerator": numerator,
        "denominator": denominator,
        "date_basis": date_basis,
        "period": period,
        "scope": _SCOPE,
        "owner_page": "program_lead_dashboard",
        "filter_behaviour": "partial",
        "drilldown": f"/dashboard?view={view}",
        "no_drilldown_reason": None,
        "notes": _NOTE,
        "roles": _ROLES,
        "source_location": f"{_LOCATION}:{line}",
    }


PL_DASHBOARD_METRIC_ROWS: tuple[dict, ...] = (
    _row(
        "team_priority_progress",
        "Team Priority Progress",
        line=496,
        view="priorities",
        definition=(
            "The weighted share of the team's approved priority allocations "
            "met by verified work this financial year "
            "(apps.hr.accountability.allocation_priorities for the Programme "
            "Lead). Not measured until every allocated milestone carries a "
            "weight and an activity rule."
        ),
        question="Is the team moving its country priorities forward?",
        numerator="Weighted verified achievement across the team's approved allocations",
        denominator="The team's approved, weighted allocation targets",
        models=(
            "apps.hr.models.MilestoneAllocation",
            "apps.hr.models.MilestoneProgressCredit",
        ),
        category="progress",
        unit="percent",
        period="financial_year",
        date_basis="activity_planned_date",
    ),
    _row(
        "cceos_on_track",
        "CCEOs On Track",
        line=509,
        view="coaching",
        definition=(
            "Officers whose own approved priority allocations are at or above "
            "the financial year's expected pace, of the officers who have a "
            "measurable allocation (PLAnalyticsService._team_target_status)."
        ),
        question="Which officers need coaching to recover their pace?",
        numerator="Officers at or above the expected pace",
        denominator="Officers with a measurable approved allocation",
        models=("apps.hr.models.MilestoneAllocation",),
        category="readiness",
        period="financial_year",
    ),
    _row(
        "waiting_on_you",
        "Waiting on You",
        line=521,
        view="team",
        definition=(
            "Team handoffs waiting on the lead's decision now: officers' weekly "
            "fund requests submitted to the lead, completions waiting for "
            "confirmation, officer leave the lead may approve, escalations "
            "addressed to the lead, and field debriefs submitted or updated."
        ),
        question="What is my team waiting on me to decide?",
        numerator="Open fund requests, completions, leave, escalations and debriefs",
        models=(
            "apps.fund_requests.models.WeeklyFundRequest",
            "apps.activities.models.Activity",
            "apps.accounts.models.Leave",
            "apps.flags.models.LeadershipEscalation",
            "apps.debriefs.models.DailyDebrief",
        ),
        category="pending_action",
        date_basis="submission_date",
    ),
    _row(
        "ssa_coverage",
        "SSA Coverage",
        line=529,
        view="programmes",
        definition=(
            "Portfolio schools holding a confirmed school self-assessment for "
            "the selected financial year, of every school in the lead's "
            "portfolio (own and team)."
        ),
        question="How far has the SSA rollout reached the team's schools?",
        numerator="Portfolio schools with a confirmed SSA this financial year",
        denominator="Schools in the lead's portfolio",
        models=("apps.ssa.models.SsaRecord", "apps.schools.models.School"),
        category="progress",
        unit="percent",
        period="financial_year",
        date_basis="ssa_assessment_date",
    ),
    _row(
        "trainings_delivered",
        "Trainings Delivered",
        line=541,
        view="programmes",
        definition=(
            "Training activities in the team's plan this financial year that "
            "reached completion (completed, submitted for review or verified); "
            "the helper names the trainings planned."
        ),
        question="Are the team's training programmes being delivered?",
        numerator="Completed training activities this financial year",
        models=("apps.activities.models.Activity",),
        category="progress",
        period="financial_year",
        date_basis="activity_planned_date",
    ),
    _row(
        "open_handoffs",
        "Open Handoffs",
        line=549,
        view="collaboration",
        definition=(
            "Open loops with the lead's collaborators: Country Director flags "
            "not yet resolved, Regional Lead feedback and coaching not yet "
            "acknowledged, escalations the lead raised still awaiting a "
            "decision or delegated back in the last 14 days, visit requests "
            "into the lead's portfolio, and partner invoices to confirm."
        ),
        question="Which collaboration handoffs are still open?",
        numerator="Open flags, unacknowledged feedback, escalations, visit requests and invoices",
        models=(
            "apps.flags.models.CdFlag",
            "apps.cce_leadership.models.RegionalEngagement",
            "apps.flags.models.LeadershipEscalation",
            "apps.activities.models.Activity",
            "apps.fund_requests.finance_models.PartnerInvoice",
        ),
        category="pending_action",
    ),
)
