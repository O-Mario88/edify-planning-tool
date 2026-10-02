"""Sidebar groups by what a page is about (owner, 2026-10-02).

From 2026-09-14 the sidebar was grouped by how often a page is visited: Daily,
Weekly, Monthly, Planning Cycle, Reference. The UI audit of 2026-10-01 found
that a reader looking for a page knows what it is about, not how often they
open it — Fund Approvals sat under "Weekly" beside My Team and Field Debrief —
and the owner asked for the groups to be revisited.

A page now sits with the pages about the same thing: the person's own work,
planning, schools, oversight, partners and projects, the team and its people,
finance, evidence and reports. How often a page is visited still decides the order INSIDE a
group (apps.core.nav_cadence.visit_rank), so the most used page of each group
is its first line.
"""

from __future__ import annotations

#: The groups, in the order the sidebar draws them.
GROUPS: tuple[str, ...] = (
    "MY WORK",
    "PLANNING",
    "SCHOOLS",
    "OVERSIGHT",
    "PARTNERS & PROJECTS",
    "BUSINESS TRANSFORMATION",
    "TEAM & PEOPLE",
    "TALENT & WELLBEING",
    "FINANCE",
    "EVIDENCE & QUALITY",
    "REPORTS",
    "MY PERFORMANCE",
    "POLICY & COMPLIANCE",
    "ADMINISTRATION",
)

MY_WORK = "MY WORK"

_PAGES: dict[str, tuple[str, ...]] = {
    # The day's own work. The two monitors stay directly under the Dashboard,
    # where the owner put them (2026-09-29).
    "MY WORK": (
        "dashboard",
        "staff_activity",
        "planning_monitor",
        "todos",
        "my_actions",
        "my_plan",
        "calendar",
        "daily_debrief",
        "extra_work",
        "hr_today",
        "admin_my_plan",
        # A Programme Lead's daily queue of completed work to confirm.
        "pl_review_queue",
    ),
    "PLANNING": (
        "planning",
        "work_plan",
        "priorities_master",
        "programme_rollout",
        "admin_planning",
        "admin_team_plans",
        "fy_planning_policy",
    ),
    "SCHOOLS": (
        "schools",
        "school_directory",
        "clusters",
        "core_schools",
        "programme_schools",
        "coverage",
        "closed_schools",
        "staff_setup_queue",
    ),
    "OVERSIGHT": (
        "team_planning_oversight",
        "country_planning_oversight",
        "country_map",
        "cluster_oversight",
        "core_schools_oversight",
        "partner_oversight",
        "project_monitoring",
    ),
    "PARTNERS & PROJECTS": (
        "partners",
        "projects",
        "project_capacity",
        "partner_schools",
        "partner_assignments",
        "partner_evidence",
        "partner_activities",
    ),
    "BUSINESS TRANSFORMATION": (
        "business_transformation",
        "mfi_portal",
        "loans",
        "business_transformation_finance",
        "business_transformation_government",
        "business_transformation_reports",
    ),
    # The people a reader leads or supports, and what has been sent to and
    # raised by them.
    "TEAM & PEOPLE": (
        "my_team",
        "team_coaching",
        "escalations",
        "actions_sent",
        "quality_checks",
        "cce_engagements",
        "cce_training_feedback",
        "leave_approvals",
        "leave_tracker",
        "team_availability",
        "staff",
        "org_structure",
        "workforce_planning",
        "recruitment",
        "candidate_pipeline",
        "onboarding",
        "offboarding",
    ),
    "TALENT & WELLBEING": (
        "performance_console",
        "performance_reviews",
        "recovery_plans",
        "cpd_learning",
        "employee_relations",
        "compensation_benefits",
        "recognition",
        "pulse_surveys",
        "health_safety",
    ),
    "FINANCE": (
        "weekly_fund_request",
        "fund_approvals",
        "monthly_budget",
        "disbursements",
        "finance_partner_payments",
        "finance_batch_payments",
        "finance_approval_history",
        "cost_settings",
        "cost_intelligence",
    ),
    "EVIDENCE & QUALITY": (
        "ia_verification_queue",
        "ssa",
        "ia_partner_evidence",
        "ia_returned",
        "ia_duplicates",
        "ia_compare",
        "ia_samples",
        "ia_history",
        "ia_school_evidence",
        "ia_upload_center",
        "school_upload",
        "upload_history",
        "uploads",
        "data_quality_center",
        "ia_framework",
    ),
    "REPORTS": (
        "analytics",
        "impact_reports",
        "cce_reports",
        "ia_learning",
        "ia_stories",
        "ia_lending_evidence",
        "ia_verification_analytics",
    ),
    "MY PERFORMANCE": (
        "my_performance",
        "my_target",
        "my_coaching",
        "my_professional_development",
        "personal_time_off",
    ),
    "POLICY & COMPLIANCE": (
        "policies",
        "policy_compliance",
        "compliance_register",
        "leave_policies",
        "hr_audit_log",
    ),
    "ADMINISTRATION": (
        "users",
        "roles_permissions",
        "ownership_transfers",
        "system_health",
        "admin_support_queue",
        "admin_incidents",
        "admin_maintenance",
        "data_repair",
    ),
}

#: page_key -> group.
PAGE_GROUP: dict[str, str] = {
    page_key: group for group, keys in _PAGES.items() for page_key in keys
}

#: Where one role reads a page as part of something else. The Project
#: Coordinator's Priorities entry is their "My Performance" strip, and their
#: Planning and My Plan are project work (NAV_FOLDS, owner 2026-09-30).
ROLE_PAGE_GROUP: dict[str, dict[str, str]] = {
    "PROJECT_COORDINATOR": {
        "priorities_master": "MY PERFORMANCE",
        "projects": MY_WORK,
        "planning": MY_WORK,
    },
    # A partner's assigned work, and a lending partner's portal, are their own
    # work; to staff the same pages are partner and lending pages.
    "PARTNER": dict.fromkeys(
        (
            "partner_schools",
            "partner_assignments",
            "partner_evidence",
            "partner_activities",
        ),
        MY_WORK,
    ),
    "MFI_ADMIN": {"mfi_portal": MY_WORK},
    "MFI_OFFICER": {"mfi_portal": MY_WORK},
    # Admin's own administration opens the sidebar (owner, 2026-09-15: Users
    # and Upload Center could not be found deep in a long group).
    "ADMIN": {"users": MY_WORK, "uploads": MY_WORK},
}

#: A group that would hold one page for a role is not drawn as a heading over
#: one line: its page joins the first of these groups the role has. A menu of
#: headings each over a single link is a list with extra words.
LONE_PAGE_JOINS: dict[str, tuple[str, ...]] = {
    "PLANNING": (MY_WORK,),
    "SCHOOLS": (MY_WORK,),
    "PARTNERS & PROJECTS": ("SCHOOLS", MY_WORK),
    "BUSINESS TRANSFORMATION": ("SCHOOLS", MY_WORK),
    "TEAM & PEOPLE": (MY_WORK,),
    "TALENT & WELLBEING": ("TEAM & PEOPLE", MY_WORK),
    "FINANCE": (MY_WORK,),
    "EVIDENCE & QUALITY": (MY_WORK,),
    "REPORTS": (MY_WORK,),
    "MY PERFORMANCE": (MY_WORK,),
    "POLICY & COMPLIANCE": ("TEAM & PEOPLE", "ADMINISTRATION", MY_WORK),
    "ADMINISTRATION": ("TEAM & PEOPLE", MY_WORK),
    "OVERSIGHT": (MY_WORK,),
}


def object_group(role: str | None, page_key: str | None) -> str:
    """The group a page is drawn in for this role."""
    override = ROLE_PAGE_GROUP.get(role or "", {}).get(page_key or "")
    return override or PAGE_GROUP.get(page_key or "", MY_WORK)


def group_order(label: str) -> int:
    return GROUPS.index(label) if label in GROUPS else len(GROUPS)
