"""Sidebar order by how often each page is opened (owner, 2026-09-14).

"Reorganize the sidebar menu by regrouping the pages according to most likely
visited to least likely visited." A role's pages are regrouped into how often
the work behind them comes round — every day, each week, each month, once a
planning cycle, or only for reference — and within a group the most visited
page comes first.

The ranking is the role's working rhythm, not measured traffic: the local
telemetry is dominated by automated crawls and would reproduce the crawler's
order. `apps.telemetry.models.InteractionEvent` records every route by role,
so once production traffic is available these weights can be replaced by
counts without touching the sidebar builder (build_sidebar_for_user reads only
`visit_rank`).
"""

from __future__ import annotations

#: The groups, most visited first.
TIERS: tuple[str, ...] = ("DAILY", "WEEKLY", "MONTHLY", "PLANNING CYCLE", "REFERENCE")
DAILY, WEEKLY, MONTHLY, CYCLE, REFERENCE = range(len(TIERS))

#: page_key -> (tier, weight). Lower weight is visited more often.
DEFAULT_RANK: dict[str, tuple[int, int]] = {
    # Every day: home, the day's queue and the person's own plan.
    "dashboard": (DAILY, 0),
    "todos": (DAILY, 10),
    "my_plan": (DAILY, 20),
    "calendar": (DAILY, 30),
    "my_actions": (DAILY, 60),
    # Each week: requests, approvals, team and portfolio work.
    "weekly_fund_request": (WEEKLY, 10),
    "fund_approvals": (WEEKLY, 15),
    "leave_approvals": (WEEKLY, 20),
    "planning": (WEEKLY, 25),
    "schools": (WEEKLY, 30),
    "team_planning_oversight": (WEEKLY, 35),
    # The country lens on the same work, read by the roles that watch a
    # country rather than run a team; it is opened on the same rhythm as
    # the team one, so it sits beside it.
    "country_planning_oversight": (WEEKLY, 36),
    "my_team": (WEEKLY, 40),
    "team_coaching": (WEEKLY, 45),
    "clusters": (WEEKLY, 50),
    "core_schools": (WEEKLY, 55),
    "partners": (WEEKLY, 60),
    "projects": (WEEKLY, 65),
    "coverage": (WEEKLY, 70),
    "escalations": (WEEKLY, 75),
    "actions_sent": (WEEKLY, 80),
    "quality_checks": (WEEKLY, 85),
    "daily_debrief": (WEEKLY, 90),
    "extra_work": (WEEKLY, 95),
    "programme_rollout": (WEEKLY, 100),
    "cce_engagements": (WEEKLY, 105),
    "cce_training_feedback": (WEEKLY, 110),
    "ia_school_evidence": (WEEKLY, 115),
    "ia_upload_center": (WEEKLY, 120),
    # The school file the SSA files are matched against, and the record of
    # what both uploads did. Worked on the same rhythm as the SSA upload
    # they sit beside.
    "school_upload": (WEEKLY, 121),
    "upload_history": (WEEKLY, 122),
    # The rows those uploads could not attach to anyone, worked off beside them.
    "staff_setup_queue": (WEEKLY, 123),
    "ia_returned": (WEEKLY, 125),
    "data_quality_center": (WEEKLY, 130),
    "ia_samples": (WEEKLY, 135),
    "uploads": (WEEKLY, 140),
    "finance_batch_payments": (WEEKLY, 145),
    "recruitment": (WEEKLY, 150),
    "candidate_pipeline": (WEEKLY, 155),
    "onboarding": (WEEKLY, 160),
    "offboarding": (WEEKLY, 165),
    "employee_relations": (WEEKLY, 170),
    "leave_tracker": (WEEKLY, 175),
    "staff": (WEEKLY, 180),
    "partner_activities": (WEEKLY, 185),
    "pl_review_queue": (WEEKLY, 12),
    "disbursements": (WEEKLY, 14),
    "ia_verification_queue": (WEEKLY, 28),
    "ssa": (WEEKLY, 32),
    "ia_partner_evidence": (WEEKLY, 34),
    "hr_today": (WEEKLY, 72),
    "finance_partner_payments": (WEEKLY, 146),
    "partner_schools": (WEEKLY, 186),
    "partner_assignments": (WEEKLY, 187),
    "partner_evidence": (WEEKLY, 188),
    "business_transformation": (WEEKLY, 190),
    "mfi_portal": (WEEKLY, 195),
    "admin_team_plans": (WEEKLY, 200),
    "admin_planning": (WEEKLY, 205),
    "admin_my_plan": (WEEKLY, 210),
    "admin_support_queue": (WEEKLY, 215),
    "admin_incidents": (WEEKLY, 220),
    "system_health": (WEEKLY, 225),
    # Each month: budgets, reports and progress against targets.
    "monthly_budget": (MONTHLY, 10),
    "work_plan": (MONTHLY, 15),
    "analytics": (MONTHLY, 20),
    "my_target": (MONTHLY, 25),
    "my_coaching": (MONTHLY, 30),
    "impact_reports": (MONTHLY, 35),
    "cce_reports": (MONTHLY, 40),
    "ia_learning": (MONTHLY, 45),
    "ia_stories": (MONTHLY, 50),
    "ia_lending_evidence": (MONTHLY, 55),
    "ia_verification_analytics": (MONTHLY, 60),
    "loans": (MONTHLY, 65),
    "business_transformation_reports": (MONTHLY, 70),
    "business_transformation_finance": (MONTHLY, 75),
    "business_transformation_government": (MONTHLY, 80),
    "cost_intelligence": (MONTHLY, 85),
    "finance_approval_history": (MONTHLY, 90),
    "workforce_planning": (MONTHLY, 95),
    "policy_compliance": (MONTHLY, 100),
    "compliance_register": (MONTHLY, 105),
    "compensation_benefits": (MONTHLY, 110),
    "recognition": (MONTHLY, 115),
    "pulse_surveys": (MONTHLY, 120),
    "health_safety": (MONTHLY, 125),
    # Once a planning cycle: priorities, agreements and reviews.
    "priorities_master": (CYCLE, 10),
    "ia_framework": (CYCLE, 15),
    "my_performance": (CYCLE, 20),
    "performance_reviews": (CYCLE, 25),
    "performance_console": (CYCLE, 30),
    "recovery_plans": (CYCLE, 35),
    "cpd_learning": (CYCLE, 40),
    "my_professional_development": (CYCLE, 45),
    "cost_settings": (CYCLE, 50),
    "fy_planning_policy": (CYCLE, 55),
    "ownership_transfers": (REFERENCE, 52),
    # For reference: time off, directories, policies and administration.
    "personal_time_off": (REFERENCE, 10),
    "team_availability": (REFERENCE, 15),
    "school_directory": (REFERENCE, 20),
    "closed_schools": (REFERENCE, 25),
    "org_structure": (REFERENCE, 30),
    "policies": (REFERENCE, 35),
    "leave_policies": (REFERENCE, 40),
    "hr_audit_log": (REFERENCE, 45),
    "users": (REFERENCE, 50),
    "ia_duplicates": (REFERENCE, 55),
    "ia_compare": (REFERENCE, 60),
    "ia_history": (REFERENCE, 65),
    "admin_maintenance": (REFERENCE, 70),
    "roles_permissions": (REFERENCE, 75),
    "data_repair": (REFERENCE, 80),
}

#: Where a role's rhythm differs from the default: its own queues come daily.
#: Keyed by the navigation role slug (apps.core.navigation.get_user_role_slug).
ROLE_RANK: dict[str, dict[str, tuple[int, int]]] = {
    "CCEO": {
        "planning": (DAILY, 25),
        "schools": (DAILY, 35),
        "daily_debrief": (DAILY, 50),
        "clusters": (WEEKLY, 30),
    },
    "PL": {
        "pl_review_queue": (DAILY, 22),
        "team_planning_oversight": (DAILY, 25),
        "fund_approvals": (WEEKLY, 5),
        "my_team": (WEEKLY, 8),
        "leave_approvals": (WEEKLY, 12),
        "daily_debrief": (WEEKLY, 30),
    },
    "IA": {
        "ia_verification_queue": (DAILY, 12),
        "ssa": (DAILY, 15),
        "ia_partner_evidence": (DAILY, 18),
        "planning": (WEEKLY, 60),
    },
    "CD": {
        "team_planning_oversight": (DAILY, 12),
        "fund_approvals": (WEEKLY, 5),
        "ia_verification_queue": (WEEKLY, 45),
        "hr_today": (WEEKLY, 70),
        "monthly_budget": (MONTHLY, 5),
    },
    "RVP": {
        "team_planning_oversight": (WEEKLY, 5),
        "monthly_budget": (WEEKLY, 8),
        "hr_today": (WEEKLY, 70),
    },
    "RPL": {
        "team_planning_oversight": (DAILY, 12),
        "cce_engagements": (WEEKLY, 5),
        "schools": (WEEKLY, 10),
    },
    "ACCOUNTANT": {
        "disbursements": (DAILY, 5),
        "weekly_fund_request": (DAILY, 12),
        "finance_partner_payments": (DAILY, 15),
        "finance_batch_payments": (WEEKLY, 5),
        "monthly_budget": (WEEKLY, 10),
        "team_planning_oversight": (MONTHLY, 30),
        "planning": (MONTHLY, 35),
    },
    "HR": {
        "hr_today": (DAILY, 5),
        "leave_approvals": (DAILY, 25),
        "staff": (DAILY, 35),
        "recruitment": (WEEKLY, 5),
        "leave_tracker": (WEEKLY, 10),
    },
    "PROJECT_COORDINATOR": {
        "projects": (DAILY, 15),
        "planning": (DAILY, 25),
        "schools": (WEEKLY, 10),
        "coverage": (WEEKLY, 15),
    },
    "PARTNER": {
        "partner_schools": (DAILY, 12),
        "partner_assignments": (DAILY, 15),
        "partner_evidence": (DAILY, 18),
        "daily_debrief": (DAILY, 50),
    },
    "BUSINESS_TRANSFORMATION": {
        "business_transformation": (DAILY, 5),
        "loans": (DAILY, 15),
    },
    "MFI_OFFICER": {"mfi_portal": (DAILY, 5), "loans": (DAILY, 15)},
    "MFI_ADMIN": {"mfi_portal": (DAILY, 5), "loans": (DAILY, 15)},
    # Admin is offered every role's pages, so its sidebar runs past a hundred
    # links. Its own administration comes first: after the regroup Users sat
    # among fifty WEEKLY links and Upload Center 34th, and the owner could not
    # find either on the live site (2026-09-15).
    "ADMIN": {
        "users": (DAILY, 11),
        "uploads": (DAILY, 12),
        "admin_support_queue": (DAILY, 13),
        "admin_incidents": (DAILY, 15),
        "system_health": (DAILY, 18),
        "roles_permissions": (WEEKLY, 1),
        "data_repair": (WEEKLY, 2),
    },
}

#: Destinations that share one page key but not one rhythm (the MFI portal's
#: sections are all `mfi_portal`).
URL_RANK: dict[str, tuple[int, int]] = {
    "/mfi-portal/dashboard": (DAILY, 0),
    "/mfi-portal/loans": (DAILY, 15),
    "/mfi-portal/data-issues": (WEEKLY, 10),
    "/mfi-portal/monthly-return": (MONTHLY, 10),
    "/mfi-portal/reports": (MONTHLY, 15),
}

#: Pages with no ranking sit at the end of the reference group.
UNRANKED = (REFERENCE, 1000)


def visit_rank(
    role: str | None, page_key: str | None, url: str | None = None
) -> tuple[int, int]:
    """(tier, weight) for a page in a role's sidebar; lower is visited more."""
    key = page_key or ""
    return (
        URL_RANK.get(url or "")
        or ROLE_RANK.get(role or "", {}).get(key)
        or DEFAULT_RANK.get(key, UNRANKED)
    )
