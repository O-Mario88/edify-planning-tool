"""Role-specific analytics overview — one endpoint per role's decision needs.

Each role gets a curated set of metrics + recommendations that answer "what
decision should I make next?" rather than a firehose of every number. All
computed from real Django records via the existing analytics services + decision
engine; scope-constrained per role.
"""
from __future__ import annotations

from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole

from . import services
from . import decision_engine as de


def role_overview(principal, query: dict) -> dict:
    """The role-specific analytics overview. Dispatches by active_role."""
    role = principal.active_role
    fy = query.get("fy") or get_operational_fy()
    dispatch = {
        EdifyRole.CCEO.value: _cceo_overview,
        EdifyRole.COUNTRY_PROGRAM_LEAD.value: _pl_overview,
        EdifyRole.COUNTRY_DIRECTOR.value: _cd_overview,
        EdifyRole.REGIONAL_VICE_PRESIDENT.value: _rvp_overview,
        EdifyRole.IMPACT_ASSESSMENT.value: _ia_overview,
        EdifyRole.PROGRAM_ACCOUNTANT.value: _accountant_overview,
        EdifyRole.HUMAN_RESOURCES.value: _hr_overview,
        EdifyRole.ADMIN.value: _cd_overview,  # Admin sees CD-level.
    }
    fn = dispatch.get(role, _default_overview)
    return {**fn(principal, query), "role": role, "fy": fy}


def _cceo_overview(principal, query: dict) -> dict:
    """CCEO: own schools, SSA, performance, what to do next."""
    dashboard = services.dashboard_summary(principal, query)
    ssa = services.ssa_performance(principal, query)
    improvement = de.ssa_improvement(principal, query)
    interventions = de.intervention_analytics(principal, query)
    recs = de.recommendations(principal, query)
    pipeline = services.activity_pipeline(principal, query)
    return {
        "dashboard": dashboard,
        "ssaPerformance": ssa,
        "ssaImprovement": improvement,
        "interventions": interventions,
        "activityPipeline": pipeline,
        "recommendations": recs,
    }


def _pl_overview(principal, query: dict) -> dict:
    """PL: team performance, supervised CCEOs, approval bottlenecks."""
    dashboard = services.dashboard_summary(principal, query)
    improvement = de.ssa_improvement(principal, query)
    interventions = de.intervention_analytics(principal, query)
    pipeline = services.activity_pipeline(principal, query)
    district_rollup = de.district_ssa_rollup(principal, query)
    recs = de.recommendations(principal, query)
    return {
        "dashboard": dashboard,
        "ssaImprovement": improvement,
        "interventions": interventions,
        "activityPipeline": pipeline,
        "districtSsa": district_rollup,
        "recommendations": recs,
    }


def _cd_overview(principal, query: dict) -> dict:
    """CD: country operations, district performance, budget, staff."""
    dashboard = services.dashboard_summary(principal, query)
    improvement = de.ssa_improvement(principal, query)
    interventions = de.intervention_analytics(principal, query)
    districts = de.district_ssa_rollup(principal, query)
    clusters = de.cluster_ssa_rollup(principal, query)
    pipeline = services.activity_pipeline(principal, query)
    recs = de.recommendations(principal, query)
    return {
        "dashboard": dashboard,
        "ssaImprovement": improvement,
        "interventions": interventions,
        "districtSsa": districts,
        "clusterSsa": clusters,
        "activityPipeline": pipeline,
        "recommendations": recs,
    }


def _rvp_overview(principal, query: dict) -> dict:
    """RVP: country summary, FY progress, strategic risks."""
    dashboard = services.dashboard_summary(principal, query)
    leadership = services.leadership_summary(principal, query)
    improvement = de.ssa_improvement(principal, query)
    recs = de.recommendations(principal, query)
    return {
        "dashboard": dashboard,
        "leadership": leadership,
        "ssaImprovement": improvement,
        "recommendations": recs,
    }


def _ia_overview(principal, query: dict) -> dict:
    """IA: SSA data quality, verification queue, evidence status."""
    dashboard = services.dashboard_summary(principal, query)
    ssa = services.ssa_performance(principal, query)
    pipeline = services.activity_pipeline(principal, query)
    improvement = de.ssa_improvement(principal, query)
    recs = de.recommendations(principal, query)
    return {
        "dashboard": dashboard,
        "ssaPerformance": ssa,
        "activityPipeline": pipeline,
        "ssaImprovement": improvement,
        "recommendations": recs,
    }


def _accountant_overview(principal, query: dict) -> dict:
    """Accountant: fund requests, disbursement, accountability."""
    pipeline = services.activity_pipeline(principal, query)
    recs = de.recommendations(principal, query)
    return {
        "activityPipeline": pipeline,
        "recommendations": recs,
    }


def _hr_overview(principal, query: dict) -> dict:
    """HR: staff workload, performance health, supervisor gaps."""
    recs = de.recommendations(principal, query)
    return {"recommendations": recs}


def _default_overview(principal, query: dict) -> dict:
    dashboard = services.dashboard_summary(principal, query)
    recs = de.recommendations(principal, query)
    return {"dashboard": dashboard, "recommendations": recs}


__all__ = ["role_overview"]
