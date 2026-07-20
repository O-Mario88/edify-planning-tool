"""
Centralized role constants and navigation map.
"""

from __future__ import annotations

# Role constants
ADMIN = "ADMIN"
CCEO = "CCEO"
PL = "PL"
CD = "CD"
IA = "IA"
RVP = "RVP"
HR = "HR"
ACCOUNTANT = "ACCOUNTANT"
PARTNER = "PARTNER"
PROJECT_COORDINATOR = "PROJECT_COORDINATOR"

ALL_ROLES = {ADMIN, CCEO, PL, CD, IA, RVP, HR, ACCOUNTANT, PARTNER, PROJECT_COORDINATOR}


def get_user_role_slug(user) -> str:
    """Normalize user active role to a standard role constant."""
    if not user or not user.is_authenticated:
        return ""
    role = getattr(user, "active_role", None)
    if not role:
        return ""

    mapping = {
        "Admin": "ADMIN",
        "CCEO": "CCEO",
        "Program Lead": "PL",
        "ProgramLead": "PL",
        "CountryDirector": "CD",
        "Country Director": "CD",
        "ImpactAssessment": "IA",
        "Impact Assessment": "IA",
        "RegionalVicePresident": "RVP",
        "Regional Vice President": "RVP",
        "HumanResources": "HR",
        "Human Resources": "HR",
        "Accountant": "ACCOUNTANT",
        "ProjectCoordinator": "PROJECT_COORDINATOR",
        "Project Coordinator": "PROJECT_COORDINATOR",
        "PartnerAdmin": "PARTNER",
        "PartnerFieldOfficer": "PARTNER",
    }
    return mapping.get(role, role.upper())


# Exact allowed roles for all views (for route gating)
PAGE_PERMISSIONS: dict[str, set[str]] = {
    # Main sidebar routes
    "dashboard": ALL_ROLES,
    "todos": ALL_ROLES,
    "my_target": {CCEO, PL, PROJECT_COORDINATOR, PARTNER, ADMIN},
    "team_targets": {PL, CD, HR, IA, ACCOUNTANT, ADMIN, PROJECT_COORDINATOR},
    # Every Edify employee is PD-eligible (Partners are external org staff, not
    # on the Edify PD/BambooHR benefit) — one shared page for all of them.
    "my_professional_development": {
        CCEO,
        PL,
        CD,
        RVP,
        IA,
        ACCOUNTANT,
        HR,
        PROJECT_COORDINATOR,
        ADMIN,
    },
    "my_plan": {CCEO, PL, PARTNER, PROJECT_COORDINATOR, ADMIN},
    # Field Debrief (§4/§20): CCEO/PL/Partner/ProjectCoordinator submit; CD/HR/
    # IA/RVP are read-only leadership-intelligence audiences — their actual
    # data is narrowed further by FieldDebriefService.scoped_queryset(), not
    # by this page-level gate (e.g. RVP only ever sees critical/escalated).
    "daily_debrief": {CCEO, PARTNER, PL, PROJECT_COORDINATOR, CD, HR, IA, RVP, ADMIN},
    "debriefs_list": {CCEO, PARTNER, PL, PROJECT_COORDINATOR, CD, HR, IA, RVP, ADMIN},
    "debrief_detail": {CCEO, PARTNER, PL, PROJECT_COORDINATOR, CD, HR, IA, RVP, ADMIN},
    "personal_time_off": ALL_ROLES,
    "leave_requests": ALL_ROLES,
    "leave_tracker": {HR, PL, CD, RVP, ADMIN},
    "leave_approvals": {PL, CD, RVP, HR, ADMIN},
    # IA is a valid covering_staff candidate in
    # CoverageAssignmentService.get_eligible_coverage_staff (IA<->IA / IA<->CD
    # coverage), so an IA staffer acting as cover must be able to reach this
    # page too.
    "leave_coverage": {CCEO, PL, CD, RVP, HR, ACCOUNTANT, IA, ADMIN},
    "leave_calendar": ALL_ROLES,
    "leave_policies": {HR, ADMIN},
    "public_holidays": ALL_ROLES,
    "team_availability": {PL, CD, RVP, HR, ADMIN},
    "schools": {CCEO, PL, PROJECT_COORDINATOR, IA, CD, ADMIN},
    "core_schools": {CCEO, PL, IA, ADMIN},
    "school_directory": {CCEO, PL, PROJECT_COORDINATOR, IA, CD, ADMIN},
    "school_profile": {CCEO, PL, PROJECT_COORDINATOR, IA, CD, ADMIN},
    "school_action_drawer": {CCEO, PL, PROJECT_COORDINATOR, IA, ADMIN},
    "school_upload": {IA, ADMIN},
    "clusters": {CCEO, PL, IA, PARTNER, CD, ADMIN},
    "cluster_planning": {CCEO, PL, IA, PARTNER, CD, ADMIN},
    "cluster_detail": {CCEO, PL, IA, PARTNER, CD, ADMIN},
    "partners": ALL_ROLES,
    "partner_detail": ALL_ROLES,
    "coverage": {CD, PL, RVP, HR, PROJECT_COORDINATOR, ADMIN},
    # Calendar is a shared read-only operational surface. The view applies its
    # own role-to-staff audience rule before returning schedules.
    "calendar": ALL_ROLES,
    "planning": {CCEO, PL, PROJECT_COORDINATOR, ADMIN},
    "weekly_fund_request": {CCEO, PL, CD, IA, ACCOUNTANT, ADMIN},
    "fund_approvals": {PL, ADMIN},
    "fund_requests": {CCEO, PL, CD, IA, ACCOUNTANT, ADMIN},
    "monthly_request": {CD, PL, RVP, ACCOUNTANT, IA, PROJECT_COORDINATOR, ADMIN},
    "my_budget": {CCEO, PL, CD, IA, ACCOUNTANT, ADMIN},
    "monthly_budget": {CCEO, PL, CD, IA, ACCOUNTANT, ADMIN},
    "country_budget": {CD, ACCOUNTANT, IA, RVP, ADMIN},
    "consolidated_fund_allocation": {CD, ACCOUNTANT, IA, RVP, ADMIN},
    "analytics": {CD, PL, IA, RVP, HR, ACCOUNTANT, PROJECT_COORDINATOR, CCEO, ADMIN},
    # The Program Lead's decision-intelligence cockpit — strictly PL-scoped.
    "pl_analytics": {PL, ADMIN},
    # The Country Director's national leadership-intelligence cockpit — country-wide.
    "cd_analytics": {CD, ADMIN},
    "reports": {CD, PL, IA, RVP, PROJECT_COORDINATOR, ADMIN},
    "completed_archive": {IA, ADMIN},
    "completed_activities": {CCEO, PL, PROJECT_COORDINATOR, IA, ADMIN},
    # RBAC matrix grants USER_MANAGE to CD and HR as well as Admin
    # (apps/core/rbac.py ROLE_PERMISSIONS) and
    # RolePermissionService.can_manage_users() already includes
    # HumanResources — this page-permission entry must match, or those
    # roles hold a permission they can never reach a page to exercise.
    "users": {CD, HR, ADMIN},
    "roles_permissions": {ADMIN},
    "system_health": {ADMIN},
    "messages": ALL_ROLES,
    "notifications": ALL_ROLES,
    # Global search — the topbar search box renders for every authenticated
    # role, so every role may open the page; each results section is
    # scope-constrained inside the view (apps/core/scoping.py).
    "search": ALL_ROLES,
    # Specific sub-routes / components
    "admin_dashboard": {ADMIN},
    "audit_log": {ADMIN},
    "workflow_rules": {ADMIN},
    "page_access_matrix": {ADMIN},
    "region_district_setup": {ADMIN},
    "notifications_mgmt": {ADMIN},
    # ImpactAssessment is the role that actually generates school/SSA
    # upload batches (see "school_upload": {IA, ADMIN}) — it must be able to
    # reach the history of what it uploaded.
    "upload_history": {IA, ADMIN},
    "data_quality_center": {IA, ADMIN},
    "settings": ALL_ROLES,
    "help": ALL_ROLES,
    # CD raises flags, PL is assigned to act on them (apps/flags) — both
    # need the page; IA/Admin keep global read-only monitoring access.
    "quality_checks": {IA, CD, PL, ADMIN},
    # The upward decision channel: the CD escalates, the RVP decides. Only the
    # two principals in that exchange (rows are filtered again in the service).
    "escalations": {CD, RVP, ADMIN},
    # The Leadership Decision + Budget Intelligence engines. Both ran headless
    # for the platform's whole life — permissions granted, detectors firing,
    # no page to open. Audience matches LEADERSHIP_ENGINE_VIEW holders who can
    # act on what they see.
    "decision_intelligence": {CD, RVP, PL, ACCOUNTANT, HR, ADMIN},
    # Schools losing ground. Same audience as SSA intelligence; the service
    # withholds school identity from summary-only roles.
    "declining_schools": {CD, RVP, PL, IA, CCEO, ADMIN},
    # Read-only core-package health. The operational /core-schools page stays
    # {CCEO, PL, IA, ADMIN}; this is the leadership lens its KPIs used to link
    # to and then 403 on.
    "core_school_health": {CD, RVP, PL, IA, ADMIN},
    # Staff directory permissions
    "staff": {HR, PL, CD, RVP, ADMIN},
    "staff_directory": {HR, PL, CD, RVP, ADMIN},
    "my_team": {PL, CD, HR, ADMIN},
    "ssa": {IA, CD, RVP, PL, CCEO, ADMIN},
    # SSA Performance is an intelligence surface for every role. Its service
    # applies school/region/partner/project scope before computing any metric.
    "ssa_performance": ALL_ROLES,
    # Impact Analytics runs statistical comparisons that need enough schools
    # in scope to be meaningful — leadership roles only.
    "impact_analytics": {CD, IA, PL, RVP, ADMIN},
    # Partner sub-routes
    "partner_today": {PARTNER, ADMIN},
    "partner_schools": {PARTNER, ADMIN},
    "partner_activities": {PARTNER, ADMIN},
    "partner_evidence": {PARTNER, ADMIN},
    "partner_my_plan": {PARTNER, ADMIN},
    # Feature pages that previously had no key of their own
    "projects": {PROJECT_COORDINATOR, CD, PL, CCEO, ADMIN},
    "analytics_publishing": {CD, IA, ADMIN},
    "evidence_center": {CCEO, PL, PARTNER, PROJECT_COORDINATOR, CD, ADMIN},
    "cost_settings": {CD, ADMIN},
    # IA queue pages (explicit entries so the sidebar can show them; route
    # gating already resolves these via the ia_ prefix fallback)
    "ia_verification_queue": {IA, ADMIN},
    "ia_duplicates": {IA, ADMIN},
    "ia_compare": {IA, ADMIN},
    "ia_returned": {IA, ADMIN},
    "ia_history": {IA, ADMIN},
    "ia_upload_center": {IA, ADMIN},
    # Finance operations sidebar visibility (views gate on "disbursements")
    "finance_advances": {ACCOUNTANT, ADMIN},
    "finance_partner_payments": {ACCOUNTANT, ADMIN},
    "finance_reimbursements": {ACCOUNTANT, ADMIN},
    "finance_batch_payments": {ACCOUNTANT, ADMIN},
    "finance_accountability": {ACCOUNTANT, ADMIN},
    "finance_approval_history": {ACCOUNTANT, ADMIN},
    # Finance sub-routes
    "disbursements": {ACCOUNTANT, ADMIN},
    "reimbursements": {ACCOUNTANT, ADMIN},
    "accountability": {ACCOUNTANT, ADMIN},
    "finance_action_drawer": {ACCOUNTANT, ADMIN},
    "weekly_fund_request_confirm": {ACCOUNTANT, ADMIN},
    "weekly_fund_request_self_funded": {ACCOUNTANT, ADMIN},
    "weekly_fund_request_disburse": {ACCOUNTANT, ADMIN},
    # HR Director HCOS Permissions
    "org_structure": {HR, ADMIN},
    "workforce_planning": {HR, CD, RVP, ADMIN},
    "recruitment": {HR, CD, ADMIN},
    "candidate_pipeline": {HR, ADMIN},
    "onboarding": {HR, ADMIN},
    "cpd_learning": {HR, PL, CD, ADMIN},
    "succession_planning": {HR, ADMIN},
    "performance_reviews": {HR, PL, CD, ADMIN},
    "recovery_plans": {HR, PL, ADMIN},
    "culture_engagement": {HR, ADMIN},
    "employee_relations": {HR, ADMIN},
    "wellness": {HR, ADMIN},
    "compensation_benefits": {HR, ADMIN},
    "payroll_readiness": {HR, ACCOUNTANT, ADMIN},
    "compliance_register": {HR, ADMIN},
    "policies": {HR, ADMIN},
    "offboarding": {HR, ADMIN},
    "hr_analytics": {HR, CD, RVP, ADMIN},
    "hr_audit_log": {HR, ADMIN},
}

# SVG Icon templates to display inside the sidebar
ICONS = {
    "dashboard": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" /></svg>',
    "my_target": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z" /><path stroke-linecap="round" stroke-linejoin="round" d="M12 18c3.314 0 6-2.686 6-6s-2.686-6-6-6-6 2.686-6 6 2.686 6 6 6z" /><path stroke-linecap="round" stroke-linejoin="round" d="M12 14c1.105 0 2-.895 2-2s-.895-2-2-2-2 .895-2 2 .895 2 2 2z" /></svg>',
    "team_targets": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a4 4 0 00-3-3.87M9 20H4v-2a4 4 0 013-3.87m6-1.13a4 4 0 10-4-4 4 4 0 004 4zm6 0a4 4 0 10-4-4" /></svg>',
    "my_professional_development": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 14l9-5-9-5-9 5 9 5z" /><path stroke-linecap="round" stroke-linejoin="round" d="M12 14l6.16-3.422A12.083 12.083 0 0121 15.5c0 2.485-4.03 4.5-9 4.5s-9-2.015-9-4.5a12.083 12.083 0 012.84-4.922L12 14z" /><path stroke-linecap="round" stroke-linejoin="round" d="M3 10v6" /></svg>',
    "my_plan": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2zM12 11l2 2-4 4" /></svg>',
    "todos": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" /></svg>',
    "fund_approvals": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>',
    "daily_debrief": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>',
    "personal_time_off": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>',
    "schools": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" /></svg>',
    "core_schools": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 3l8 3v5c0 4.97-3.4 8.94-8 10-4.6-1.06-8-5.03-8-10V6l8-3z" /><path stroke-linecap="round" stroke-linejoin="round" d="M9.5 12l1.8 1.8 3.2-3.6" /></svg>',
    "clusters": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" /></svg>',
    "partners": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" /></svg>',
    "coverage": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" /></svg>',
    "planning": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" /></svg>',
    "weekly_fund_request": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" /></svg>',
    "monthly_request": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>',
    "my_budget": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>',
    "country_budget": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /><path stroke-linecap="round" stroke-linejoin="round" d="M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z" /></svg>',
    "analytics": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M7 12l3-3 3 3 4-4M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z" /></svg>',
    "ssa_performance": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M3 12h4l2-7 4 14 2-7h6M5 21h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v14a2 2 0 002 2z" /></svg>',
    "impact_analytics": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9.663 17h4.674M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" /></svg>',
    "reports": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>',
    "escalations": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M5 10l7-7m0 0l7 7m-7-7v18" /></svg>',
    "declining_schools": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M13 17h8m0 0v-8m0 8l-8-8-4 4-6-6" /></svg>',
    "core_school_health": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 3l8 3v5c0 4.97-3.4 8.94-8 10-4.6-1.06-8-5.03-8-10V6l8-3z" /><path stroke-linecap="round" stroke-linejoin="round" d="M9.5 12l1.8 1.8 3.2-3.6" /></svg>',
    "decision_intelligence": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" /></svg>',
    "projects": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" /></svg>',
    "cost_settings": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>',
    "analytics_publishing": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>',
    "finance_advances": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>',
    "finance_partner_payments": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5a2 2 0 11-4 0 2 2 0 014 0z" /></svg>',
    "finance_reimbursements": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>',
    "finance_batch_payments": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" /></svg>',
    "finance_accountability": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>',
    "finance_approval_history": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>',
    "ia_verification_queue": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" /></svg>',
    "ia_duplicates": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>',
    "ia_compare": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" /></svg>',
    "ia_returned": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M16 15v-1a4 4 0 00-4-4H8m0 0l3 3m-3-3l3-3m9 14V5a2 2 0 00-2-2H6a2 2 0 00-2 2v14a2 2 0 002 2h12a2 2 0 002-2z" /></svg>',
    "ia_history": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>',
    "ia_upload_center": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" /></svg>',
    "completed_archive": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" /></svg>',
    "users": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a3 3 0 11-6 0 3 3 0 016 0z" /></svg>',
    "roles_permissions": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M15 7a2 2 0 012 2m-2 4a2 2 0 012 2m-2-4a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0zm0-10a2 2 0 11-4 0 2 2 0 014 0z" /></svg>',
    "system_health": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>',
    "messages": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" /></svg>',
    "notifications": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" /></svg>',
    "team_availability": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 002 2h2a2 2 0 002-2z" /></svg>',
    "org_structure": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" /></svg>',
    "workforce_planning": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a4 4 0 00-3-3.87M9 20H4v-2a4 4 0 013-3.87m6-1.13a4 4 0 10-4-4 4 4 0 004 4zm6 0a4 4 0 10-4-4" /></svg>',
    "recruitment": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" /></svg>',
    "candidate_pipeline": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" /></svg>',
    "onboarding": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>',
    "cpd_learning": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" /></svg>',
    "succession_planning": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" /></svg>',
    "performance_reviews": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>',
    "recovery_plans": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>',
    "culture_engagement": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>',
    "employee_relations": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" /></svg>',
    "wellness": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z" /></svg>',
    "compensation_benefits": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>',
    "payroll_readiness": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>',
    "compliance_register": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>',
    "policies": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" /></svg>',
    "offboarding": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" /></svg>',
    "hr_analytics": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M7 12l3-3 3 3 4-4M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z" /></svg>',
    "hr_audit_log": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>',
}

# Grouped list of all sidebar links in their categories
SIDEBAR_ITEMS = [
    {
        "group_label": "MY WORK",
        "items": [
            {
                "label": "Dashboard",
                "url": "/dashboard",
                "page_key": "dashboard",
            },
            {
                "label": "My Target",
                "url": "/my-targets",
                "page_key": "my_target",
            },
            {
                "label": "Team Targets",
                "url": "/team-targets/",
                "page_key": "team_targets",
            },
            {
                "label": "My Plan",
                "url": "/my-plan",
                "page_key": "my_plan",
                # Project Coordinators plan only project work — route them to the
                # project-scoped My Plan.
                "role_urls": {PROJECT_COORDINATOR: "/projects/my-plan"},
            },
            {
                "label": "My Professional Development",
                "url": "/my-professional-development",
                "page_key": "my_professional_development",
            },
            {
                "label": "To-Do",
                "url": "/todos",
                "page_key": "todos",
            },
            {
                "label": "Field Debrief",
                "url": "/debriefs",
                "page_key": "daily_debrief",
            },
            {
                "label": "Escalations",
                "url": "/escalations",
                "page_key": "escalations",
            },
            {
                "label": "Leave & Personal Time Off",
                "url": "/personal-time-off/",
                "page_key": "personal_time_off",
            },
            {
                "label": "Leave Approvals",
                "url": "/leave/approvals",
                "page_key": "leave_approvals",
            },
        ],
    },
    {
        "group_label": "SCHOOLS & FIELD",
        "items": [
            {
                "label": "Schools",
                "url": "/schools",
                "page_key": "schools",
            },
            {
                "label": "Core Schools",
                "url": "/core-schools",
                "page_key": "core_schools",
            },
            {
                "label": "Clusters",
                "url": "/clusters",
                "page_key": "clusters",
            },
            {
                "label": "Partners",
                "url": "/partners",
                "page_key": "partners",
            },
            {
                "label": "Projects",
                "url": "/projects",
                "page_key": "projects",
            },
            {
                "label": "Coverage",
                "url": "/coverage",
                "page_key": "coverage",
            },
            {
                "label": "Leave Tracker",
                "url": "/leave/tracker",
                "page_key": "leave_tracker",
            },
            {
                "label": "Team Availability",
                "url": "/leave/team-availability",
                "page_key": "team_availability",
            },
        ],
    },
    {
        "group_label": "PLANNING & FINANCE",
        "items": [
            {
                "label": "Planning",
                "url": "/planning",
                "page_key": "planning",
                "role_urls": {PROJECT_COORDINATOR: "/projects/planning"},
            },
            {
                "label": "Weekly Fund Request",
                "url": "/fund-requests/weekly",
                "page_key": "weekly_fund_request",
            },
            {
                "label": "Fund Approvals",
                "url": "/fund-approvals",
                "page_key": "fund_approvals",
            },
            {
                "label": "Monthly Request",
                "url": "/accounts/monthly-request/",
                "page_key": "monthly_request",
            },
            {
                "label": "My Budget",
                "url": "/budgets/monthly",
                "page_key": "my_budget",
            },
            {
                "label": "Country Budget",
                "url": "/country-budget/",
                "page_key": "country_budget",
            },
            {
                "label": "Cost Settings",
                "url": "/cost-settings",
                "page_key": "cost_settings",
            },
        ],
    },
    {
        "group_label": "FINANCE OPERATIONS",
        "items": [
            # "Advances Queue" (/accounts/advances/) and "Accountability"
            # (/accounts/accountability/) intentionally NOT linked here as of
            # the 2026-07-15 finance-unification mandate — both pages' sole
            # actions (mark_disbursed_action, netsuite_id_action) are
            # retired: disbursing an advance and entering its NetSuite
            # Expense ID now happen exclusively through the canonical weekly/
            # advance flow (Disbursement Dashboard, /disbursements +
            # apps.fund_requests.advance_service), where the RESPONSIBLE
            # EMPLOYEE — never the Accountant — originates the NetSuite ID.
            # The two legacy pages still exist for historical/read access at
            # their URLs; they are just no longer a sidebar dead end.
            {
                "label": "Partner Payments",
                "url": "/accounts/partner-payments/",
                "page_key": "finance_partner_payments",
            },
            # "Reimbursements" (/accounts/reimbursements/, ReimbursementClaim-
            # backed) intentionally NOT linked here — ReimbursementService.
            # claim_reimbursement() has zero production callers (only tests
            # create a ReimbursementClaim), so this queue is permanently
            # empty. The real, fully-wired reimbursement flow (self-funded
            # activities AND advance-funded over-spend) lives on
            # AdvanceRequest (advance_service.submit_reimbursement/reimburse/
            # confirm_reimbursement_receipt, status REIMBURSEMENT_SUBMITTED ->
            # REIMBURSEMENT_DISBURSED -> REIMBURSED) and is already surfaced
            # in the Disbursement Dashboard queue via
            # disbursement_dashboard_service._reimbursement_items(). Keeping
            # a sidebar link to the dead queue would be a permanent-empty-
            # state trap for every Accountant.
            {
                "label": "Batch Payments",
                "url": "/accounts/batch-payments/",
                "page_key": "finance_batch_payments",
            },
            {
                "label": "Approval History",
                "url": "/accounts/approval-history/",
                "page_key": "finance_approval_history",
            },
        ],
    },
    {
        "group_label": "VERIFICATION",
        "items": [
            {
                "label": "Verification Queue",
                "url": "/ia/verification/",
                "page_key": "ia_verification_queue",
            },
            {
                "label": "Duplicate Review",
                "url": "/ia/duplicates/",
                "page_key": "ia_duplicates",
            },
            {
                "label": "Evidence Compare",
                "url": "/ia/compare/",
                "page_key": "ia_compare",
            },
            {
                "label": "Returned Activities",
                "url": "/ia/returned/",
                "page_key": "ia_returned",
            },
            {
                "label": "Verification History",
                "url": "/ia/history/",
                "page_key": "ia_history",
            },
            {
                "label": "SSA Upload Center",
                "url": "/ssa/upload/",
                "page_key": "ia_upload_center",
            },
        ],
    },
    {
        "group_label": "QUALITY & INSIGHTS",
        "items": [
            {
                "label": "Decision Intelligence",
                "url": "/decisions",
                "page_key": "decision_intelligence",
            },
            {
                "label": "SSA Performance",
                "url": "/ssa",
                "page_key": "ssa_performance",
            },
            {
                "label": "Declining Schools",
                "url": "/declining-schools",
                "page_key": "declining_schools",
            },
            {
                "label": "Core School Health",
                "url": "/core-school-health",
                "page_key": "core_school_health",
            },
            {
                "label": "Impact Analytics",
                "url": "/impact",
                "page_key": "impact_analytics",
            },
            {
                "label": "Analytics",
                "url": "/analytics",
                "page_key": "analytics",
                # Coordinators get the Special Project Impact Intelligence page;
                # Program Leads get their supervised-team analytics cockpit;
                # the Country Director gets the national leadership cockpit.
                "role_urls": {
                    PROJECT_COORDINATOR: "/projects/analytics",
                    PL: "/analytics/program-lead",
                    CD: "/analytics/country-director",
                },
            },
            {
                "label": "Analytics Publishing",
                "url": "/analytics/publishing/",
                "page_key": "analytics_publishing",
            },
            {
                "label": "Reports",
                "url": "/reports",
                "page_key": "reports",
            },
            {
                "label": "Completed Archive",
                "url": "/completed-activities",
                "page_key": "completed_archive",
            },
        ],
    },
    {
        "group_label": "ADMINISTRATION",
        "items": [
            {
                "label": "Users",
                "url": "/admin-panel/users",
                "page_key": "users",
            },
            {
                "label": "Roles & Permissions",
                "url": "/admin-panel/roles-permissions",
                "page_key": "roles_permissions",
            },
            {
                "label": "System Health",
                "url": "/system-health",
                "page_key": "system_health",
            },
            {
                "label": "Leave Policies",
                "url": "/leave/policies",
                "page_key": "leave_policies",
            },
        ],
    },
    {
        "group_label": "PEOPLE & TEAMS",
        "items": [
            {
                "label": "People Directory",
                "url": "/staff",
                "page_key": "staff",
            },
            {
                "label": "Organization Structure",
                "url": "/org-structure",
                "page_key": "org_structure",
            },
            {
                "label": "Workforce Planning",
                "url": "/workforce-planning",
                "page_key": "workforce_planning",
            },
        ],
    },
    {
        "group_label": "TALENT & ONBOARDING",
        "items": [
            {
                "label": "Recruitment",
                "url": "/recruitment",
                "page_key": "recruitment",
            },
            {
                "label": "Candidate Pipeline",
                "url": "/candidate-pipeline",
                "page_key": "candidate_pipeline",
            },
            {
                "label": "Onboarding",
                "url": "/onboarding",
                "page_key": "onboarding",
            },
            {
                "label": "CPD & Learning",
                "url": "/cpd-learning",
                "page_key": "cpd_learning",
            },
            {
                "label": "Succession Planning",
                "url": "/succession-planning",
                "page_key": "succession_planning",
            },
        ],
    },
    {
        "group_label": "PERFORMANCE",
        "items": [
            {
                "label": "Performance Reviews",
                "url": "/performance-reviews",
                "page_key": "performance_reviews",
            },
            {
                "label": "Team Target Oversight",
                "url": "/team-targets/",
                "page_key": "team_targets",
            },
            {
                "label": "Recovery Plans",
                "url": "/recovery-plans",
                "page_key": "recovery_plans",
            },
        ],
    },
    {
        "group_label": "TIME & AVAILABILITY",
        "items": [
            {
                "label": "Leave & Coverage",
                "url": "/leave/coverage",
                "page_key": "leave_coverage",
            },
            {
                "label": "Holidays & Blackouts",
                "url": "/public-holidays",
                "page_key": "public_holidays",
            },
        ],
    },
    {
        "group_label": "EMPLOYEE EXPERIENCE",
        "items": [
            {
                "label": "Culture & Engagement",
                "url": "/culture-engagement",
                "page_key": "culture_engagement",
            },
            {
                "label": "Employee Relations",
                "url": "/employee-relations",
                "page_key": "employee_relations",
            },
            {
                "label": "Wellness",
                "url": "/wellness",
                "page_key": "wellness",
            },
        ],
    },
    {
        "group_label": "REWARDS & COMPLIANCE",
        "items": [
            {
                "label": "Compensation & Benefits",
                "url": "/compensation-benefits",
                "page_key": "compensation_benefits",
            },
            {
                "label": "Payroll Readiness",
                "url": "/payroll-readiness",
                "page_key": "payroll_readiness",
            },
            {
                "label": "Compliance Register",
                "url": "/compliance-register",
                "page_key": "compliance_register",
            },
            {
                "label": "Policies & Documents",
                "url": "/policies",
                "page_key": "policies",
            },
        ],
    },
    {
        "group_label": "TRANSITIONS",
        "items": [
            {
                "label": "Offboarding",
                "url": "/offboarding",
                "page_key": "offboarding",
            },
        ],
    },
    {
        "group_label": "INSIGHTS",
        "items": [
            {
                "label": "HR Analytics",
                "url": "/hr-analytics",
                "page_key": "hr_analytics",
            },
            {
                "label": "HR Audit Log",
                "url": "/hr-audit-log",
                "page_key": "hr_audit_log",
            },
        ],
    },
]


def build_sidebar_for_user(user, current_path: str) -> list[dict]:
    """Generates the grouped list of visible sidebar links for the given user."""
    role = get_user_role_slug(user)
    if not role:
        return []

    sections = []
    for sec in SIDEBAR_ITEMS:
        visible_items = []
        for item in sec["items"]:
            allowed = PAGE_PERMISSIONS.get(item["page_key"], set())
            if role in allowed:
                # Per-role URL override (e.g. a Project Coordinator's "Planning"
                # points to the project-scoped planning page).
                url = item.get("role_urls", {}).get(role, item["url"])
                # Active check: exact match for the dashboard and the /projects
                # hub (whose children — /projects/planning etc. — are their own
                # nav items); prefix match for everything else.
                if url == "/dashboard":
                    is_active = current_path == url or current_path == "/"
                elif url in {"/projects", "/ssa"}:
                    is_active = current_path == url
                else:
                    is_active = current_path.startswith(url)

                visible_items.append(
                    {
                        "label": item["label"],
                        "url": url,
                        "icon": ICONS.get(item["page_key"], ""),
                        "active": is_active,
                    }
                )

        # Only show the section if it has at least one visible item inside it
        if visible_items:
            has_active_item = any(item["active"] for item in visible_items)
            sections.append(
                {
                    "label": sec["group_label"],
                    "items": visible_items,
                    "active": has_active_item,
                    # Keep the personal workspace available on first load;
                    # every other group opens only when it contains the page.
                    "expanded": has_active_item or sec["group_label"] == "MY WORK",
                }
            )

    return sections
