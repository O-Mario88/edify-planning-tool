"""Metric definitions for SSA-informed planning (owner, 2026-09-13).

Every school activity plan is judged against the verified SSA when it is made
(apps.ssa.plan_alignment). The share of live plans that follow it is a
headline for the people who plan, beside the Planning page's other counts.
"""

from __future__ import annotations

SSA_PLAN_METRIC_ROWS: tuple[dict, ...] = (
    {
        "key": "planning_ssa_informed_plans",
        "label": "SSA-Informed Plans",
        "source_label": "SSA-Informed Plans",
        "source": "apps.planning.planning_service.get_dashboard_data:get_dashboard_data",
        "definition": (
            "Live plans on the schools and clusters in view whose planning-time "
            "verdict follows the verified SSA: they target one of the school's "
            "or cluster's SSA priorities, collect the SSA, or are not "
            "school-improvement work. Plans made before verdicts were recorded "
            "are left out rather than counted as failures."
        ),
        "question": "Are our plans informed by the SSA?",
        "category": "quality",
        "unit": "percent",
        "service": "apps.planning.planning_service.PlanningDashboardService.get_dashboard_data",
        "source_models": (
            "apps.activities.models.Activity",
            "apps.ssa.models.SsaRecord",
        ),
        "numerator": "live plans with ssa_alignment priority, ssa_collection or not_applicable",
        "denominator": "live plans in view with a recorded ssa_alignment",
        "date_basis": "activity_planned_date",
        "period": "financial_year",
        "scope": "The schools and clusters in the Planning workspace's scope",
        "owner_page": "annual_planning_workspace",
        "filter_behaviour": "partial",
        "drilldown": None,
        "no_drilldown_reason": (
            "Each plan carries its verdict and reason; the audit command "
            "audit_ssa_informed_plans lists them by type."
        ),
        "notes": "Added 2026-09-13 with apps.ssa.plan_alignment.",
        "roles": ("CCEO", "Program Lead", "CountryDirector", "Admin"),
        "source_location": "apps/planning/planning_service.py:936",
    },
)
