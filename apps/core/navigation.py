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
BUSINESS_TRANSFORMATION = "BUSINESS_TRANSFORMATION"
MFI_ADMIN = "MFI_ADMIN"
MFI_OFFICER = "MFI_OFFICER"

ALL_ROLES = {
    ADMIN,
    CCEO,
    PL,
    CD,
    IA,
    RVP,
    HR,
    ACCOUNTANT,
    PARTNER,
    PROJECT_COORDINATOR,
    BUSINESS_TRANSFORMATION,
    MFI_ADMIN,
    MFI_OFFICER,
}

# These pages contain the Business Transformation Officer's specialist school
# portfolio. Unlike general support pages, even the technical Admin role does
# not inherit them: the product owner explicitly keeps this operating context
# inside the active BT role. The record-level Loans page follows the same
# least-privilege rule.
ROLE_EXCLUSIVE_PAGES = {
    "loans",
    "business_transformation_finance",
    "business_transformation_government",
}

# The Loans destination is advertised only to roles that operate or validate
# the record-level portfolio. Impact-only and executive roles use their scoped
# reporting surfaces instead.
BT_SPECIALIST_NAV_PAGES = {
    "loans",
    "business_transformation",
    "business_transformation_finance",
    "business_transformation_government",
    "business_transformation_reports",
}

# Sidebar information architecture is narrower than route authorization. These
# are the roles whose day-to-day work belongs in the field operations group;
# leadership and support roles may retain scoped read access through their own
# intelligence, verification, finance, or people workspaces.
# Admin is deliberately absent: Platform Operations observes field work
# through Team Plans, Support Tickets, Incidents and Search, and never
# carries a field workspace of its own.
FIELD_NAV_ROLES = {CCEO, PL, PROJECT_COORDINATOR}


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
        "BusinessTransformationOfficer": "BUSINESS_TRANSFORMATION",
        "MfiPartnerAdmin": "MFI_ADMIN",
        "MfiLoanOfficer": "MFI_OFFICER",
    }
    return mapping.get(role, role.upper())


# Exact allowed roles for all views (for route gating)
PAGE_PERMISSIONS: dict[str, set[str]] = {
    # Main sidebar routes
    "dashboard": ALL_ROLES,
    "todos": ALL_ROLES,
    "business_transformation": {
        BUSINESS_TRANSFORMATION,
        CD,
        IA,
        RVP,
        ADMIN,
        CCEO,
        PL,
        HR,
        ACCOUNTANT,
        PARTNER,
        PROJECT_COORDINATOR,
    },
    "loans": {
        BUSINESS_TRANSFORMATION,
        CD,
        IA,
        RVP,
        MFI_ADMIN,
        MFI_OFFICER,
    },
    "business_transformation_finance": {BUSINESS_TRANSFORMATION},
    "business_transformation_government": {BUSINESS_TRANSFORMATION},
    "business_transformation_reports": ALL_ROLES - {MFI_ADMIN, MFI_OFFICER},
    "mfi_portal": {MFI_ADMIN, MFI_OFFICER},
    # Anyone can be handed a school action, so everyone can read their own
    # queue. Both views filter to the signed-in user's rows, so there is no
    # wider set for a permissive gate to expose.
    "my_actions": ALL_ROLES,
    "actions_sent": {PL, IA, CD, RVP, ADMIN},
    "my_target": {CCEO, PL, PROJECT_COORDINATOR, PARTNER, ADMIN},
    # Supervised-team target oversight. `supervised_users` resolves a team only
    # for the PL (their supervisees) and the CD (country lens); every other
    # role got an empty page. Removed for the Accountant, who supervises nobody
    # and holds no programme-performance remit, and for the Project
    # Coordinator, who owns projects rather than a staff team.
    # NOTE: HR and IA are still listed and still resolve to an empty team —
    # out of scope for the field-role audit, flagged in the proposal.
    "team_targets": {PL, CD, HR, IA, ADMIN},
    # Supervision lenses over the country plan. Deliberately narrow: the PL
    # page resolves a team only for a Program Lead, and the country page is a
    # leadership review surface, not a field-planning one. Neither grants any
    # write access to the work it shows.
    # Cluster Oversight is a section on these two pages rather than a page of
    # its own, so the roles that need it are here. IA and the Accountant read
    # the team lens; the RVP reads the country one.
    #
    # Widening a page permission widens every route behind it, which is how the
    # partner-oversight export hole opened earlier in this branch. The two
    # exports here now carry `@require_export_permission`, and the corrective
    # actions gate on their own authority rather than on page access — both
    # asserted in test_planning_oversight_access.py.
    "team_planning_oversight": {PL, CD, RVP, IA, ACCOUNTANT, ADMIN},
    "country_planning_oversight": {CD, RVP, ADMIN},
    # Partner-delivered work, grouped by partner. The PL owns team-level
    # monitoring of it and the CD sees the country picture; the CCEO reaches
    # the same records through the school they manage, so they do not need a
    # partner-shaped page and are not given one.
    #
    # Impact Assessment and the Accountant are here because they are IN this
    # chain, not observing it: verification gates payment and payment closes
    # the partner's work, and both were previously named as responsible on a
    # page neither could open. Their lens is country-wide, matching the queues
    # they already work from.
    # The CCEO is here to help the PL monitor, not to be monitored. They see
    # partner work at their own schools — the service scopes it — because the
    # person who knows the school is the first to notice a partner who has
    # gone quiet. The PL's decision queue is filtered by `supervising_pl_id`
    # and so stays empty for them: shared visibility, unchanged authority.
    "partner_oversight": {CCEO, PL, CD, RVP, IA, ACCOUNTANT, ADMIN},
    "my_performance": {
        CCEO,
        PL,
        CD,
        RVP,
        HR,
        IA,
        ACCOUNTANT,
        PROJECT_COORDINATOR,
        ADMIN,
    },
    # The My Performance group's sibling links share my_performance's audience:
    # they are the same feature, reached at their own tab or page.
    "performance_conversations": {
        CCEO,
        PL,
        CD,
        RVP,
        HR,
        IA,
        ACCOUNTANT,
        PROJECT_COORDINATOR,
        ADMIN,
    },
    "performance_development": {
        CCEO,
        PL,
        CD,
        RVP,
        HR,
        IA,
        ACCOUNTANT,
        PROJECT_COORDINATOR,
        ADMIN,
    },
    "performance_values": {
        CCEO,
        PL,
        CD,
        RVP,
        HR,
        IA,
        ACCOUNTANT,
        PROJECT_COORDINATOR,
        ADMIN,
    },
    "performance_documents": {
        CCEO,
        PL,
        CD,
        RVP,
        HR,
        IA,
        ACCOUNTANT,
        PROJECT_COORDINATOR,
        ADMIN,
    },
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
    # Field partners are external organisations — no leave entitlements.
    "personal_time_off": ALL_ROLES - {PARTNER},
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
    "school_profile": {
        CCEO,
        PL,
        PROJECT_COORDINATOR,
        IA,
        CD,
        BUSINESS_TRANSFORMATION,
        ADMIN,
    },
    # The archive. IA and CD are here because closure data quality and country
    # closure trends are theirs to watch; RVP works from aggregates and is not.
    "closed_schools": {CCEO, PL, IA, CD, ADMIN},
    "school_action_drawer": {CCEO, PL, PROJECT_COORDINATOR, IA, ADMIN},
    "school_upload": {IA, ADMIN},
    "clusters": {CCEO, PL, IA, CD, ADMIN},
    "cluster_planning": {CCEO, PL, IA, CD, ADMIN},
    "cluster_detail": {CCEO, PL, IA, CD, ADMIN},
    "partners": ALL_ROLES,
    "partner_detail": ALL_ROLES,
    "coverage": {CD, PL, RVP, HR, PROJECT_COORDINATOR, ADMIN},
    # Calendar is a shared read-only operational surface. The view applies its
    # own role-to-staff audience rule before returning schedules.
    "calendar": ALL_ROLES,
    # The CD plans plenty of non-school work (district trips, boot camps,
    # partner meetings), so they hold the planning surface too — the field-
    # event drawer is its entry point for them (owner, 2026-08-19).
    "planning": {CCEO, PL, PROJECT_COORDINATOR, CD, ADMIN},
    # Work Plan is the FY-level roll-up of the same activity ledger Planning
    # writes. Field planners keep it, and the leadership/verification roles
    # (CD, IA, HR) read it without being able to plan. The RVP gets aggregate
    # month bands only (the view hides operational rows) and the Accountant a
    # read-only finance lens — §18 of the Work Plan rebuild.
    "work_plan": {CCEO, PL, PROJECT_COORDINATOR, CD, RVP, IA, HR, ACCOUNTANT, ADMIN},
    # The Project Coordinator owns weekly requests too — weekly_service's
    # _ROUTE_TO_CD names them explicitly — so locking them out of the page meant
    # they generated requests they could never see or confirm.
    "weekly_fund_request": {CCEO, PL, CD, IA, ACCOUNTANT, PROJECT_COORDINATOR, ADMIN},
    "fund_approvals": {PL, ADMIN},
    "fund_requests": {CCEO, PL, CD, IA, ACCOUNTANT, PROJECT_COORDINATOR, ADMIN},
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
    "completed_activities": {CCEO, PL, PROJECT_COORDINATOR, IA, ADMIN, CD},
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
    # Platform-operations workspaces (Admin-only).
    "admin_team_plans": {ADMIN},
    "admin_planning": {ADMIN},
    "admin_my_plan": {ADMIN},
    "admin_support_queue": {ADMIN},
    "admin_incidents": {ADMIN},
    "admin_maintenance": {ADMIN},
    "data_repair": {ADMIN},
    # Upload Center is the governed organisational-ingestion surface. Evidence
    # and PD proof stay on their owning workflow pages and do not grant access
    # here.
    "uploads": {ADMIN, IA, HR, CD, RVP},
    "policy_compliance": {HR, CD, PL, RVP, ADMIN},
    # Reporting a problem is every role's right, so intake is universal.
    "report_problem": ALL_ROLES,
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
    "declining_schools": {CD, RVP, PL, IA, CCEO, PROJECT_COORDINATOR, ADMIN},
    # Read-only core-package health. The operational /core-schools page stays
    # {CCEO, PL, IA, ADMIN}; this is the leadership lens its KPIs used to link
    # to and then 403 on.
    "core_school_health": {CD, RVP, PL, IA, ADMIN},
    # Read-only decision history. Every role may open it; the service decides
    # whose decisions they see — deployment-wide for RVP/Admin, country for the
    # CD, own-decisions-only for everyone else.
    "decision_log": ALL_ROLES,
    # Staff directory permissions
    "staff": {HR, PL, CD, RVP, ADMIN},
    "staff_directory": {HR, PL, CD, RVP, ADMIN},
    "my_team": {PL, CD, HR, ADMIN},
    "ssa": {IA, CD, RVP, PL, CCEO, ADMIN},
    # SSA Performance is an intelligence surface for every role. Its service
    # applies school/region/partner/project scope before computing any metric.
    "ssa_performance": ALL_ROLES,
    # SSA contribution analysis is portfolio-scoped for field staff/PLs and
    # country-wide for assurance/leadership roles. Small portfolios render an
    # honest insufficient-data state instead of being denied the evidence.
    "impact_analytics": {
        CCEO,
        PL,
        IA,
        CD,
        RVP,
        ACCOUNTANT,
        PROJECT_COORDINATOR,
        ADMIN,
    },
    # School Visit Effectiveness: the shared visit↔SSA-change module — field
    # roles see their own delivery, leadership sees team/country strategy.
    "visit_effectiveness": {CCEO, PL, IA, CD, RVP, PROJECT_COORDINATOR, ADMIN},
    # IA Quality Analytics (/ia/dashboard/). The route resolved through the
    # `ia_` prefix fallback in permissions.py and the page was reachable only
    # by typing the URL — it had no key and no navigation. Named explicitly now
    # that it is an Analytics section.
    "ia_dashboard": {IA, ADMIN},
    # Closure quality. IA and Admin only: this is a data-quality worklist about
    # which closure records to distrust, not a report on how many schools the
    # country lost. Leadership gets that from the closure analytics on their own
    # surfaces, which count real closures and exclude the record errors listed
    # here — the same numbers with the corrections already applied.
    "closure_quality": {IA, ADMIN},
    # Where the country is losing schools, and what closing them did to the
    # plan. Deliberately a different page from closure_quality above: that one
    # is a worklist of records to distrust, this one is country performance,
    # and a single page mixing them leaves nobody sure which numbers they own.
    # RVP is here because the page carries no school-level rows: every table
    # aggregates to a district, region, reason or month, and the service scopes
    # to their assigned regions through scoped_school_queryset. A test asserts
    # no school name reaches an RVP's render, so adding a per-school list later
    # fails loudly rather than leaking quietly.
    "closure_impact": {CD, RVP, ADMIN},
    # Partner sub-routes
    "partner_today": {PARTNER, ADMIN},
    "partner_assignments": {PARTNER, ADMIN},
    "partner_schools": {PARTNER, ADMIN},
    "partner_activities": {PARTNER, ADMIN},
    "partner_evidence": {PARTNER, ADMIN},
    "partner_my_plan": {PARTNER, ADMIN},
    # Feature pages that previously had no key of their own
    "projects": {PROJECT_COORDINATOR, CD, PL, CCEO, IA, ADMIN},
    "analytics_publishing": {CD, IA, ADMIN},
    # IA owns evidence assurance before records can enter finance and
    # leadership analytics, so the role must be able to open the shared
    # evidence dataset linked from its verification workspace.
    "evidence_center": {CCEO, PL, PARTNER, PROJECT_COORDINATOR, CD, IA, ADMIN},
    "cost_settings": {CD, ADMIN},
    "cost_intelligence": {RVP, ACCOUNTANT},
    # IA queue pages (explicit entries so the sidebar can show them; route
    # gating already resolves these via the ia_ prefix fallback)
    "ia_verification_queue": {IA, ADMIN},
    "ia_partner_evidence": {IA, ADMIN},
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
    # RVP added: it approves the CD's own development and owns the region's
    # people investment, but had no PD oversight surface at all.
    "cpd_learning": {HR, PL, CD, RVP, ADMIN},
    "succession_planning": {HR, ADMIN},
    "performance_reviews": {HR, PL, CD, ADMIN},
    "performance_console": {HR, ADMIN},
    # The RVP and CD author here; HR gets read access because the coverage
    # report — which published priorities reached nobody — is theirs to act on,
    # and it lives nowhere else.
    "strategic_priorities": {RVP, CD, HR, ADMIN},
    # The Today workbench (roadmap Phase 5): the field roles' one primary
    # daily surface — route, next action, waiting-on-you, exceptions, the
    # proposed week, day completion.
    "today": {CCEO, PL, PROJECT_COORDINATOR, ADMIN},
    # Uganda Master Priority Plan distribution: IA distributes the approved
    # country targets to Program Leads (CD owns/publishes the master and
    # monitors); each PL distributes their team target to supervised CCEOs.
    "target_distribution": {IA, CD, ADMIN},
    # The canonical master table (§9): every staff role reads the SAME rows;
    # the target column is role-scoped (PL/CCEO see their own allocation).
    "priorities_master": {CCEO, PL, CD, IA, RVP, HR, PROJECT_COORDINATOR, ADMIN},
    # A section of Priorities, not a separate system. Everyone who reads
    # priorities can see what each activity is measured against; only Impact
    # Assessment can change it, which the page enforces per control.
    "ssa_mapping": {CD, IA, RVP, PL, PROJECT_COORDINATOR, ADMIN},
    # §18 Extra Assigned Work: CD/PL assign, CCEO executes; Admin supports.
    "extra_work": {CD, PL, CCEO, ADMIN},
    "hr_today": {HR, CD, PL, RVP, ADMIN},
    "team_target_distribution": {PL, ADMIN},
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
    # Calendar reuses the shared calendar glyph (same drawing as
    # personal_time_off / monthly_request).
    "calendar": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>',
    "work_plan": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" /></svg>',
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
    "visit_effectiveness": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" /></svg>',
    "reports": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>',
    "escalations": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M5 10l7-7m0 0l7 7m-7-7v18" /></svg>',
    "declining_schools": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M13 17h8m0 0v-8m0 8l-8-8-4 4-6-6" /></svg>',
    "core_school_health": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 3l8 3v5c0 4.97-3.4 8.94-8 10-4.6-1.06-8-5.03-8-10V6l8-3z" /><path stroke-linecap="round" stroke-linejoin="round" d="M9.5 12l1.8 1.8 3.2-3.6" /></svg>',
    "decision_log": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>',
    "decision_intelligence": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" /></svg>',
    "projects": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" /></svg>',
    "cost_settings": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>',
    "cost_intelligence": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4 19V9m5 10V5m5 14v-7m5 7V3" /><path stroke-linecap="round" stroke-linejoin="round" d="m4 8 5-4 5 7 5-9" /></svg>',
    "analytics_publishing": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>',
    "finance_advances": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>',
    "disbursements": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>',
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
    "strategic_priorities": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 3v3m0 12v3m9-9h-3M6 12H3m12 0a3 3 0 11-6 0 3 3 0 016 0zm5.196 0a8.196 8.196 0 11-16.392 0 8.196 8.196 0 0116.392 0z" /></svg>',
    "target_distribution": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v4m0 0-3-2m3 2 3-2M5 13l-2 3 3.5 1M19 13l2 3-3.5 1M12 12v4m0 0-4 3m4-3 4 3" /></svg>',
    "today": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l2.5 2.5M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z" /></svg>',
    "team_target_distribution": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 0 0-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 0 1 5.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 0 1 9.288 0M15 7a3 3 0 1 1-6 0 3 3 0 0 1 6 0zm6 3a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM7 10a2 2 0 1 1-4 0 2 2 0 0 1 4 0z" /></svg>',
    "performance_console": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" /></svg>',
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
    "my_performance": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>',
    "performance_conversations": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" /></svg>',
    "performance_development": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 14l9-5-9-5-9 5 9 5z" /><path stroke-linecap="round" stroke-linejoin="round" d="M12 14l6.16-3.422a12.083 12.083 0 01.665 6.479A11.952 11.952 0 0012 20.055a11.952 11.952 0 00-6.824-2.998 12.078 12.078 0 01.665-6.479L12 14z" /></svg>',
    "performance_values": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z" /></svg>',
    "performance_documents": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>',
    # These four were registered in SIDEBAR_ITEMS with no matching icon, so
    # ICONS.get(...) returned "" and the sidebar rendered an empty icon slot for
    # them. Harmless-looking on a 240px sidebar next to a label; fatal in a
    # bottom navigation tab, where the icon is the primary affordance and the
    # label is a 11px caption under it.
    "staff": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a4 4 0 00-3-3.87M9 20H4v-2a4 4 0 013-3.87m3-2.13a4 4 0 100-8 4 4 0 000 8zm7 0a3 3 0 100-6 3 3 0 000 6z" /></svg>',
    "leave_approvals": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m-9 9h10a2 2 0 002-2V7a2 2 0 00-2-2h-1V3m-8 2H6a2 2 0 00-2 2v10a2 2 0 002 2zm2-16v4" /></svg>',
    "admin_support_queue": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M18.364 5.636l-3.536 3.536m0 5.656l3.536 3.536M9.172 9.172L5.636 5.636m3.536 9.192l-3.536 3.536M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-6 0a3 3 0 11-6 0 3 3 0 016 0z" /></svg>',
    "ssa": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 17v-4m3 4v-8m3 8v-2M5 21h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v14a2 2 0 002 2z" /></svg>',
}

# Keep every registered destination visually discoverable in the expanded,
# collapsed and mobile navigation. These aliases intentionally reuse the
# platform's established line-icon vocabulary instead of adding a second icon
# library for conceptually identical actions.
ICONS.update(
    {
        "team_planning_oversight": ICONS["planning"],
        "partner_assignments": ICONS["planning"],
        "country_planning_oversight": ICONS["work_plan"],
        "partner_oversight": ICONS["partners"],
        "my_actions": ICONS["todos"],
        "actions_sent": ICONS["escalations"],
        "uploads": ICONS["ia_upload_center"],
        "closed_schools": ICONS["completed_archive"],
        "leave_tracker": ICONS["team_availability"],
        "priorities_master": ICONS["target_distribution"],
        "ssa_mapping": ICONS["target_distribution"],
        "extra_work": ICONS["todos"],
        "hr_today": ICONS["todos"],
        "admin_my_plan": ICONS["my_plan"],
        "admin_planning": ICONS["planning"],
        "admin_team_plans": ICONS["team_targets"],
        "admin_incidents": ICONS["recovery_plans"],
        "admin_maintenance": ICONS["calendar"],
        "data_repair": ICONS["cost_settings"],
        "leave_policies": ICONS["policies"],
        "policy_compliance": ICONS["compliance_register"],
        "business_transformation": ICONS["partners"],
        "loans": ICONS["disbursements"],
    }
)

DEFAULT_SIDEBAR_ICON = ICONS["dashboard"]

# ── The Analytics workspace ───────────────────────────────────────────────────
# Every analysis surface in the platform, in one place. These used to be
# eleven separate sidebar links plus two pages that had no link at all; they
# are now sections of a single workspace, reached from one "Analytics" entry
# and switched between with the sub-navigation the shell renders on each of
# them. Each section keeps its own route, view, permission key and tests —
# only the way you get there changed.
#
#   page_key   gates the section exactly as it gates the route.
#   role_urls  per-role destination (same contract as SIDEBAR_ITEMS).
#   match      "exact" where a sibling route lives underneath the URL:
#              /ssa would otherwise swallow the IA upload centre at
#              /ssa/upload/, and /analytics would swallow every other
#              /analytics/* section.
#   cluster    groups related sections; the sub-navigation draws a divider
#              between clusters rather than labelling them.
ANALYTICS_SECTIONS = [
    {
        "key": "overview",
        "label": "Overview",
        "url": "/analytics",
        "page_key": "analytics",
        "match": "exact",
        "cluster": "overview",
        "description": "Programme performance, field execution and delivery.",
        # Coordinators get Special Project Impact Intelligence; Program Leads
        # their supervised-team cockpit; the Country Director the national one.
        "role_urls": {
            PROJECT_COORDINATOR: "/projects/analytics",
            PL: "/analytics/program-lead",
            CD: "/analytics/country-director",
        },
    },
    {
        "key": "ssa",
        "label": "SSA Performance",
        "url": "/ssa",
        "page_key": "ssa_performance",
        "match": "exact",
        "cluster": "school_performance",
        "description": "Verified school self-assessment scores and movement.",
    },
    {
        "key": "visit_effectiveness",
        "label": "Visit Effectiveness",
        "url": "/analytics/visit-effectiveness",
        "page_key": "visit_effectiveness",
        "cluster": "school_performance",
        "description": "How school visits relate to verified SSA change.",
    },
    {
        "key": "impact",
        "label": "Impact Analytics",
        "url": "/impact",
        "page_key": "impact_analytics",
        "cluster": "impact_decisions",
        "description": "How programme activity is associated with SSA improvement.",
    },
    {
        "key": "declining_schools",
        "label": "Declining Schools",
        "url": "/declining-schools",
        "page_key": "declining_schools",
        "cluster": "school_performance",
        "description": "Schools losing ground, ranked by drop.",
    },
    {
        "key": "core_school_health",
        "label": "Core School Health",
        "url": "/core-school-health",
        "page_key": "core_school_health",
        "cluster": "school_performance",
        "description": "Core service package delivery, read-only.",
    },
    {
        "key": "decision_intelligence",
        "label": "Decision Intelligence",
        "url": "/decisions",
        "page_key": "decision_intelligence",
        "cluster": "impact_decisions",
        "description": "What leadership is being asked to decide, and why.",
    },
    {
        "key": "decision_log",
        "label": "Decision Log",
        "url": "/decision-log",
        "page_key": "decision_log",
        "cluster": "impact_decisions",
        "description": "What was decided, by whom, on what evidence.",
    },
    {
        "key": "people",
        "label": "People Analytics",
        "url": "/hr-analytics",
        "page_key": "hr_analytics",
        "cluster": "delivery",
        "description": "Workforce, capacity and people investment.",
    },
    {
        "key": "verification_quality",
        "label": "Verification Quality",
        "url": "/ia/dashboard/",
        "page_key": "ia_dashboard",
        "cluster": "delivery",
        "description": "Evidence quality and verification throughput.",
    },
    {
        "key": "closure_quality",
        "label": "Closure Quality",
        "url": "/analytics/closure-quality",
        "page_key": "closure_quality",
        "cluster": "delivery",
        "description": "Closure records to distrust: wrong, unconfirmed or late.",
    },
    {
        "key": "closure_impact",
        "label": "School Closures",
        "url": "/analytics/school-closures",
        "page_key": "closure_impact",
        "cluster": "school_performance",
        "description": "Where the country is losing schools, and what it cost the plan.",
    },
    {
        "key": "completed_work",
        # Sidebar visibility used to be gated on `completed_archive` ({IA,
        # ADMIN}) while the route gates on `completed_activities` ({CCEO, PL,
        # PROJECT_COORDINATOR, IA, ADMIN}) — four roles could open the page but
        # never saw a link to it. The section uses the key the route enforces.
        "label": "Completed Work",
        "url": "/completed-activities",
        "page_key": "completed_activities",
        "cluster": "delivery",
        "description": "The ledger of activities that finished and cleared.",
    },
    {
        "key": "reports",
        "label": "Reports",
        "url": "/reports",
        "page_key": "reports",
        "cluster": "reporting",
        "description": "Standing and scheduled reporting.",
    },
    {
        "key": "publishing",
        # Registered as "/analytics/publishing/" before; the canonical route has
        # no trailing slash, so prefix matching never marked it active.
        "label": "Publishing",
        "url": "/analytics/publishing",
        "page_key": "analytics_publishing",
        "cluster": "reporting",
        "description": "What has been published to the wider organisation.",
    },
]


# ── The IA verification workspace ────────────────────────────────────────────
# These are separate authoritative datasets, not decorative client-side tabs.
# Each item keeps its existing route, view, permission and browser history;
# this registry gives Impact Assessment one stable command-centre mental model.
IA_SECTIONS = [
    {
        "key": "dashboard",
        "label": "Dashboard",
        "url": "/ia/dashboard/",
        "page_key": "ia_dashboard",
        "match": "exact",
        "cluster": "verification",
        "description": "Verification workload, risk and data confidence.",
    },
    {
        "key": "activities",
        "label": "Activity Verification",
        "url": "/ia/verification/",
        "page_key": "ia_verification_queue",
        "match": "exact",
        "cluster": "verification",
        "description": "Evidence and Salesforce checks awaiting an IA decision.",
    },
    {
        "key": "partner_evidence",
        "label": "Partner Evidence",
        "url": "/ia/partner-evidence/",
        "page_key": "ia_partner_evidence",
        "match": "exact",
        "cluster": "verification",
        "description": "Partner submissions awaiting review and Salesforce confirmation.",
    },
    {
        "key": "ssa_verification",
        "label": "SSA Verification",
        "url": "/ssa/verification/",
        "page_key": "ssa",
        "match": "exact",
        "cluster": "verification",
        "description": "Submitted SSA records awaiting quality confirmation.",
    },
    {
        "key": "unmatched_ssa",
        "label": "Unmatched SSA",
        "url": "/ssa/unmatched",
        "page_key": "data_quality_center",
        "match": "exact",
        "cluster": "assurance",
        "description": "Imported SSA records that cannot yet be trusted or linked.",
    },
    {
        "key": "evidence",
        "label": "Evidence Review",
        "url": "/evidence/",
        "page_key": "evidence_center",
        "match": "exact",
        "cluster": "assurance",
        "description": "Proof packets across activities in IA scope.",
    },
    {
        "key": "data_quality",
        "label": "Data Quality",
        "url": "/admin-panel/data-quality-center",
        "page_key": "data_quality_center",
        "match": "exact",
        "cluster": "assurance",
        "description": "Coverage gaps, duplicates and invalid operational records.",
    },
    {
        "key": "core_verification",
        "label": "Core Verification",
        "url": "/core-school-health",
        "page_key": "core_school_health",
        "match": "exact",
        "cluster": "readiness",
        "description": "Core package blockers and completion-gate stalls.",
    },
    {
        "key": "impact_readiness",
        "label": "Impact Readiness",
        "url": "/impact",
        "page_key": "impact_analytics",
        "match": "exact",
        "cluster": "readiness",
        "description": "Whether supported interventions can be measured credibly.",
    },
    {
        "key": "analytics",
        "label": "IA Analytics",
        "url": "/analytics",
        "page_key": "analytics",
        "match": "exact",
        "cluster": "reporting",
        "description": "Role-scoped trends and operational intelligence.",
    },
    {
        "key": "reports",
        "label": "Reports",
        "url": "/reports",
        "page_key": "reports",
        "match": "exact",
        "cluster": "reporting",
        "description": "Standing and scheduled IA reporting outputs.",
    },
]


# ── The Leave workspace ───────────────────────────────────────────────────────
# Your own leave, who is covering, and the calendar those two are decided
# against — three sidebar links for one question ("who is off, and does that
# matter?"). They are sections of the page you already open to book leave.
LEAVE_SECTIONS = [
    {
        "key": "my_leave",
        "label": "My Leave",
        "url": "/personal-time-off/",
        "page_key": "personal_time_off",
        "cluster": "leave",
        "description": "Your balance, requests and time off.",
    },
    {
        "key": "coverage",
        "label": "Coverage",
        "url": "/leave/coverage",
        "page_key": "leave_coverage",
        "cluster": "leave",
        "description": "Who covers whose work while they are away.",
    },
    {
        "key": "holidays",
        "label": "Holidays & Blackouts",
        "url": "/public-holidays",
        "page_key": "public_holidays",
        "cluster": "leave",
        "description": "Public holidays and periods leave cannot be taken.",
    },
]

# Every multi-page workspace, keyed by the eyebrow its section strip shows.
WORKSPACE_CLUSTER_LABELS = {
    "overview": "Overview",
    "school_performance": "School Performance",
    "impact_decisions": "Impact & Decisions",
    "delivery": "Delivery & Quality",
    "reporting": "Reporting",
}

WORKSPACES = {
    "ia": {"label": "Impact Assessment", "sections": IA_SECTIONS},
    "analytics": {"label": "Analytics", "sections": ANALYTICS_SECTIONS},
    "leave": {"label": "Leave", "sections": LEAVE_SECTIONS},
}


def _path_matches(url: str, path: str, match: str = "prefix") -> bool:
    """True when `path` is inside `url`, ignoring trailing slashes."""
    url = url.rstrip("/") or "/"
    path = (path or "").rstrip("/") or "/"
    if match == "exact":
        return path == url
    return path == url or path.startswith(url + "/")


def build_sections(registry, user, current_path: str = "") -> list[dict]:
    """The sections of one workspace this user may open, in workspace order.

    Returns [] for a role with no access to any of them, so the caller knows
    not to render a sub-navigation at all.
    """
    role = get_user_role_slug(user)
    if not role:
        return []

    sections = []
    previous_cluster = None
    for section in registry:
        if role != ADMIN and role not in PAGE_PERMISSIONS.get(
            section["page_key"], set()
        ):
            continue
        url = section.get("role_urls", {}).get(role, section["url"])
        match = section.get("match", "prefix")
        # A role_urls override adds a destination, it does not close the
        # generic one: /analytics stays a real page for a Program Lead whose
        # Overview points at /analytics/program-lead. Without this the section
        # bar vanished on exactly the page the workspace is named after.
        active = _path_matches(url, current_path, match) or (
            url != section["url"] and _path_matches(section["url"], current_path, match)
        )
        # Admin can inspect every role-specific Overview cockpit directly.
        # Those destinations are role overrides for their owning users rather
        # than separate navigation sections, so without this check an Admin on
        # /analytics/program-lead, /analytics/country-director or
        # /projects/analytics lost the Analytics workspace strip entirely.
        if role == ADMIN and not active:
            active = any(
                _path_matches(role_url, current_path, match)
                for role_url in section.get("role_urls", {}).values()
            )
        sections.append(
            {
                "key": section["key"],
                "label": section["label"],
                "url": url,
                "description": section["description"],
                "active": active,
                "cluster": section["cluster"],
                "cluster_label": WORKSPACE_CLUSTER_LABELS.get(
                    section["cluster"],
                    section["cluster"].replace("_", " ").title(),
                ),
                # First item of a new cluster gets the divider before it.
                "starts_cluster": previous_cluster is not None
                and section["cluster"] != previous_cluster,
            }
        )
        previous_cluster = section["cluster"]

    return sections


def build_analytics_sections(user, current_path: str = "") -> list[dict]:
    """The Analytics workspace's sections. Kept as its own name because the
    sidebar's Analytics hub and its tests speak in these terms."""
    return build_sections(ANALYTICS_SECTIONS, user, current_path)


def build_workspace(user, current_path: str = "") -> dict | None:
    """The workspace `current_path` belongs to, with its sections resolved.

    None when the path is not a section of any workspace, or when the user can
    reach fewer than two of its sections — a one-item strip is decoration, not
    navigation.
    """
    role = get_user_role_slug(user)
    workspaces = list(WORKSPACES.items())
    # `/analytics`, `/impact` and `/reports` are intentionally shared routes.
    # IA sees those datasets inside its verification workspace; other roles
    # retain the general Analytics workspace. Admin gets the IA workspace on
    # explicitly IA-prefixed pages without losing its normal Analytics model.
    if role != IA and not (current_path or "").startswith("/ia/"):
        workspaces = [item for item in workspaces if item[0] != "ia"]

    for key, workspace in workspaces:
        sections = build_sections(workspace["sections"], user, current_path)
        if len(sections) > 1 and any(s["active"] for s in sections):
            groups_by_key: dict[str, dict] = {}
            for section in sections:
                cluster = section["cluster"]
                group = groups_by_key.setdefault(
                    cluster,
                    {
                        "key": cluster,
                        "label": section["cluster_label"],
                        "sections": [],
                        "active": False,
                    },
                )
                group["sections"].append(section)
                group["active"] = group["active"] or section["active"]
            groups = list(groups_by_key.values())
            # Each area has one durable destination in the primary strip. Its
            # individual analyses remain real permission-scoped routes and are
            # exposed by the compact view menu in the shared template. This
            # keeps the information architecture small without flattening
            # distinct datasets into one misleading client-side tab panel.
            for group in groups:
                active_section = next(
                    (section for section in group["sections"] if section["active"]),
                    None,
                )
                group["active_section"] = active_section or group["sections"][0]
                group["url"] = group["active_section"]["url"]
            active_group = next(
                (group["key"] for group in groups if group["active"]),
                groups[0]["key"],
            )
            active_group_detail = next(
                group for group in groups if group["key"] == active_group
            )
            return {
                "key": key,
                "label": workspace["label"],
                "sections": sections,
                "groups": groups,
                "active_group": active_group,
                "active_group_detail": active_group_detail,
            }
    return None


# Grouped list of all sidebar links in their categories
SIDEBAR_ITEMS = [
    {
        "group_label": "MY WORK",
        "items": [
            {
                # Phase 5: the field day's one primary surface. Sits above
                # Dashboard for the roles it serves; other roles never see it.
                "label": "Today",
                "url": "/today",
                "page_key": "today",
            },
            {
                "label": "Dashboard",
                "url": "/dashboard",
                "page_key": "dashboard",
                # A partner's home IS their assigned work.
                "role_urls": {PARTNER: "/partner/assigned-schools"},
            },
            {
                # Planning, targets, clusters and flagged schools are lenses
                # inside one Team Oversight workspace. The navigation audience
                # is the union of the two underlying page permissions; the
                # view shows only the lenses each role is authorized to read.
                "label": "Team Oversight",
                "url": "/team-planning-oversight/",
                "page_key": "team_planning_oversight",
                "visible_to": {PL, CD, HR, IA, RVP, ACCOUNTANT, ADMIN},
                "extra_active_paths": ("/team-targets",),
            },
            {
                # The CD has no SCHOOLS & FIELD group, but they plan plenty of
                # non-school work (district trips, boot camps, partner
                # meetings) — Planning surfaces here for them; field roles
                # keep their entry in SCHOOLS & FIELD (owner, 2026-08-19).
                "label": "Planning",
                "url": "/planning",
                "page_key": "planning",
                "visible_to": {CD},
            },
            {
                # The canonical Uganda Master table in its four source
                # columns; PL/CCEO read their OWN allocated figure here
                # (owner, 2026-08-20).
                #
                # For the roles that RUN the master — IA distributes, the CD
                # confirms and publishes, Admin supports — Priorities IS the
                # distribution workspace, so the one nav entry goes straight
                # there (owner, 2026-08-24: "they are the same thing"). The
                # read-only table stays the destination for everyone who only
                # consumes their own figure.
                "label": "Priorities",
                "url": "/priorities",
                "page_key": "priorities_master",
                "role_urls": {
                    IA: "/target-distribution",
                    CD: "/target-distribution",
                    ADMIN: "/target-distribution",
                },
            },
            {
                "label": "Extra Work",
                "url": "/extra-work",
                "page_key": "extra_work",
            },
            {
                "label": "My Plan",
                "url": "/my-plan",
                "page_key": "my_plan",
                # Project Coordinators plan only project work — route them to
                # the project-scoped My Plan. Partners use the default URL:
                # their plan RENDERS at /my-plan (the partner layout), and the
                # old /partner/my-plan redirect hop meant the sidebar item
                # never matched the current path, so it never highlighted.
                "role_urls": {
                    PROJECT_COORDINATOR: "/projects/my-plan",
                },
            },
            # Calendar is the operational projection of the same activity
            # ledger My Plan executes. It remains in MY WORK because every
            # role receives it; Work Plan now sits with the budgets it drives.
            {
                "label": "Calendar",
                "url": "/calendar",
                "page_key": "calendar",
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
                # Sits under My Work, beside To-Do, because that is what it
                # is: work someone handed you by name. Every role can be sent
                # a school action, so it is not restricted.
                "label": "My Actions",
                "url": "/actions/mine",
                "page_key": "my_actions",
            },
            {
                # The other end of the same rows. Only the roles that can send
                # — PL supervises, IA assures — have anything to monitor here.
                "label": "Actions Sent",
                "url": "/actions/sent",
                "page_key": "actions_sent",
                "visible_to": {PL, IA, CD, RVP},
            },
            {
                "label": "Upload Center",
                "url": "/uploads",
                "page_key": "uploads",
                # Admin reaches it from PLATFORM OPERATIONS instead, so it is
                # not advertised twice in one sidebar.
                "visible_to": {
                    IA,
                    HR,
                    CD,
                    RVP,
                },
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
        "group_label": "MY FIELD WORK",
        "visible_to": {PARTNER},
        "items": [
            {
                "label": "Assigned Schools",
                "url": "/partner/assigned-schools",
                "page_key": "partner_schools",
                "icon_key": "schools",
            },
            {
                "label": "Assigned Activities",
                "url": "/partner/assigned-activities",
                "page_key": "partner_assignments",
            },
            {
                "label": "Evidence",
                "url": "/partner/evidence",
                "page_key": "partner_evidence",
                "icon_key": "uploads",
            },
            {
                "label": "Completed & Payments",
                "url": "/partner/completed",
                "page_key": "partner_activities",
                "icon_key": "disbursements",
            },
        ],
    },
    {
        "group_label": "SCHOOLS & FIELD",
        "visible_to": FIELD_NAV_ROLES,
        "items": [
            {
                "label": "Planning",
                "url": "/planning",
                "page_key": "planning",
                "role_urls": {PROJECT_COORDINATOR: "/projects/planning"},
            },
            {
                "label": "Schools",
                "url": "/schools",
                "page_key": "schools",
            },
            {
                # Its own entry, not a filter on the directory. The rule is
                # that closed schools do not appear there, and a hidden filter
                # default is a promise that breaks the first time somebody
                # clears it or arrives from a saved link.
                "label": "Closed Schools",
                "url": "/schools/closed",
                "page_key": "closed_schools",
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
                # One Partners entry, not a directory beside an oversight page
                # answering the same question from two places in the sidebar.
                #
                # It stays on `/partners` — ALL_ROLES, so nobody loses the link
                # — and the view redirects whoever may open Partner Oversight.
                # Pointing the item straight at `/partner-oversight/` would
                # have offered it to HR, the RVP and the Project Coordinator,
                # who hold `partners` but not `partner_oversight`, and to the
                # partner organisations themselves. `extra_active_paths` keeps
                # the entry highlighted once the redirect has happened.
                "label": "Partners",
                "url": "/partners",
                "page_key": "partners",
                "extra_active_paths": ["/partner-oversight/"],
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
        "group_label": "BUSINESS TRANSFORMATION",
        "visible_to": ALL_ROLES,
        "items": [
            {
                "label": "BT Overview",
                "url": "/business-transformation/overview",
                "page_key": "business_transformation",
                "visible_to": {BUSINESS_TRANSFORMATION},
            },
            {
                "label": "Loans",
                "url": "/loans",
                "page_key": "loans",
                "visible_to": {BUSINESS_TRANSFORMATION, CD, IA, RVP},
            },
            {
                "label": "Business Accounting & Finance",
                "url": "/business-transformation/business-accounting-finance",
                "page_key": "business_transformation_finance",
                "icon_key": "country_budget",
                "visible_to": {BUSINESS_TRANSFORMATION},
            },
            {
                "label": "Government Requirements",
                "url": "/business-transformation/government-requirements",
                "page_key": "business_transformation_government",
                "icon_key": "compliance_register",
                "visible_to": {BUSINESS_TRANSFORMATION},
            },
            {
                "label": "Impact & Reports",
                "url": "/business-transformation/impact-reports",
                "page_key": "business_transformation_reports",
                "icon_key": "reports",
                "visible_to": {BUSINESS_TRANSFORMATION},
            },
            {
                "label": "Dashboard",
                "url": "/mfi-portal/dashboard",
                "page_key": "mfi_portal",
                "icon_key": "dashboard",
                "visible_to": {MFI_ADMIN, MFI_OFFICER},
            },
            {
                "label": "Loans",
                "url": "/mfi-portal/loans",
                "page_key": "mfi_portal",
                "icon_key": "loans",
                "visible_to": {MFI_ADMIN, MFI_OFFICER},
            },
            {
                "label": "Monthly Portfolio Return",
                "url": "/mfi-portal/monthly-return",
                "page_key": "mfi_portal",
                "icon_key": "monthly_request",
                "visible_to": {MFI_ADMIN, MFI_OFFICER},
            },
            {
                "label": "Data Issues",
                "url": "/mfi-portal/data-issues",
                "page_key": "mfi_portal",
                "icon_key": "ia_duplicates",
                "visible_to": {MFI_ADMIN, MFI_OFFICER},
            },
            {
                # Not the bare "Reports" — that label was merged away into the
                # Analytics workspace and the workspace guard holds it there.
                "label": "MFI Reports",
                "url": "/mfi-portal/reports",
                "page_key": "mfi_portal",
                "icon_key": "reports",
                "visible_to": {MFI_ADMIN, MFI_OFFICER},
            },
        ],
    },
    {
        # The individual's own performance workspace — the agreement drives the
        # targets, so My Targets belongs here rather than in the general work
        # list. Each link is a distinct path so exactly one highlights.
        "group_label": "MY PERFORMANCE",
        "items": [
            {
                # Was labelled "Priority Dashboard", which named a surface the
                # platform does not have: this is the individual's own
                # performance agreement. /priorities is the one canonical
                # priority page, and two things called a priority dashboard is
                # how two pages end up answering the same question differently.
                "label": "My Performance Agreement",
                "url": "/my-performance",
                "page_key": "my_performance",
                # Regional and country strategy authors enter the governed
                # source-priority workspace from the familiar dashboard slot.
                # Their personal agreement remains available as the sibling
                # item below, so strategy ownership does not erase it.
                "role_urls": {
                    RVP: "/strategic-priorities",
                    CD: "/strategic-priorities",
                },
                "role_labels": {
                    RVP: "Priority Setting",
                    CD: "Priority Setting",
                },
            },
            {
                "label": "My Performance Agreement",
                "url": "/my-performance",
                "page_key": "my_performance",
                "visible_to": {RVP, CD},
            },
            {
                "label": "My Targets",
                "url": "/my-targets",
                "page_key": "my_target",
            },
        ],
    },
    {
        "group_label": "FINANCE & BUDGET",
        "items": [
            {
                # The FY Work Plan is the source plan for projected activity
                # costs, so keep it beside the requests and budgets it drives.
                "label": "Work Plan",
                "url": "/work-plan",
                "page_key": "work_plan",
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
                # `monthly_request_view` hands CD/RVP/Admin straight to
                # `country_budget_view`, so for those three this entry opened
                # the very same page as the one below it -- two sidebar links,
                # two different names, one destination. The route stays
                # authorized (PAGE_PERMISSIONS is unchanged, so deep links and
                # the CD's own redirects still work); it just stops being
                # advertised twice.
                "visible_to": {PL, ACCOUNTANT, IA, PROJECT_COORDINATOR},
            },
            {
                # The CD *submits* a Monthly Fund Request; the RVP *reviews the
                # country budget* it asks for. Same workspace, two vantage
                # points, so the label follows the reader rather than the
                # writer. CD naming is pinned by
                # apps/frontend/test_cd_budget_workspaces.py.
                "label": "Monthly Fund Request",
                "role_labels": {RVP: "Country Budget"},
                "url": "/country-budget/",
                "page_key": "country_budget",
            },
            {
                "label": "Cost Settings",
                "url": "/cost-settings",
                "page_key": "cost_settings",
            },
            {
                "label": "Cost Intelligence",
                "url": "/cost-intelligence",
                "page_key": "cost_intelligence",
                "visible_to": {RVP, ACCOUNTANT},
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
                # The Accountant's primary workspace had NO sidebar entry at
                # all — it was reachable only by one button on one page.
                "label": "Disbursement Dashboard",
                "url": "/disbursements",
                "page_key": "disbursements",
            },
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
                # IA creates and validates authoritative school records, but is
                # not a field-delivery role. Keep that workflow discoverable in
                # Verification instead of presenting IA with Schools & Field.
                "label": "School Directory",
                "url": "/schools",
                "page_key": "school_directory",
                "visible_to": {IA},
                "icon_key": "schools",
            },
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
        ],
    },
    {
        "group_label": "QUALITY & INSIGHTS",
        "items": [
            # One door to every analysis surface. The individual pages used to
            # be eleven sidebar links; they are now sections of the Analytics
            # workspace (ANALYTICS_SECTIONS) reached by the sub-navigation the
            # shell renders on each of them. `analytics_hub` tells
            # build_sidebar_for_user to resolve this item from the sections the
            # role can actually open rather than from a single page_key.
            {
                "label": "Analytics",
                "url": "/analytics",
                "page_key": "analytics",
                "analytics_hub": True,
            },
        ],
    },
    {
        # Admin's home. Placed before ADMINISTRATION so the first thing a
        # Platform Operations Administrator sees is their own operating queue,
        # not the user table.
        "group_label": "PLATFORM OPERATIONS",
        "visible_to": {ADMIN},
        "items": [
            {
                "label": "Admin My Plan",
                "url": "/admin-ops/my-plan",
                "page_key": "admin_my_plan",
            },
            {
                "label": "Admin Planning",
                "url": "/admin-ops/planning",
                "page_key": "admin_planning",
            },
            {
                "label": "Team Plans",
                "url": "/admin-ops/team-plans",
                "page_key": "admin_team_plans",
            },
            {
                "label": "Support Tickets",
                "url": "/admin-ops/support",
                "page_key": "admin_support_queue",
            },
            {
                "label": "System Incidents",
                "url": "/admin-ops/incidents",
                "page_key": "admin_incidents",
            },
            {
                "label": "Maintenance Calendar",
                "url": "/admin-ops/maintenance",
                "page_key": "admin_maintenance",
            },
            {
                "label": "Data Repair Center",
                "url": "/data-repair",
                "page_key": "data_repair",
            },
            {
                "label": "Upload Center",
                "url": "/uploads",
                "page_key": "uploads",
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
                "label": "HR Today",
                "url": "/hr-today",
                "page_key": "hr_today",
            },
            {
                "label": "Policy Compliance",
                "url": "/policy-compliance",
                "page_key": "policy_compliance",
            },
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
            # DESCOPED until a production writer exists — the model behind this
            # page has none, so the page is a permanently empty register. Direct
            # URL still works (honest empty state); navigation stops advertising it.
            # {
            #                 "label": "Succession Planning",
            #                 "url": "/succession-planning",
            #                 "page_key": "succession_planning",
            #             },
        ],
    },
    {
        "group_label": "PERFORMANCE",
        "items": [
            {
                "label": "Strategic Priorities",
                "url": "/strategic-priorities",
                "page_key": "strategic_priorities",
                # RVP/CD reach the same authoring workspace from their primary
                # performance group; keep this validation/configuration entry
                # for the support roles that do not receive that override.
                "visible_to": {HR, ADMIN},
            },
            # §12's workspace is no longer a second sidebar entry: for IA, CD
            # and Admin the Priorities item above IS the distribution
            # workspace. The /target-distribution route, its permission and
            # its page key all remain — only the duplicate link is gone.
            {
                # §13 — the PL's one distribution among supervised CCEOs.
                "label": "Team Target Distribution",
                "url": "/target-distribution/team",
                "page_key": "team_target_distribution",
            },
            {
                "label": "Performance Cycle",
                "url": "/hr/performance-cycle",
                "page_key": "performance_console",
            },
            {
                "label": "Performance Reviews",
                "url": "/performance-reviews",
                "page_key": "performance_reviews",
            },
            {
                "label": "Recovery Plans",
                "url": "/recovery-plans",
                "page_key": "recovery_plans",
            },
        ],
    },
    # Leave & Coverage and Holidays & Blackouts moved into the Leave workspace
    # (LEAVE_SECTIONS), reached from "Leave & Personal Time Off" in MY WORK —
    # the same page a user goes to for their own leave. The group held nothing
    # else, so it is gone.
    {
        "group_label": "EMPLOYEE EXPERIENCE",
        "items": [
            # DESCOPED until a production writer exists — the model behind this
            # page has none, so the page is a permanently empty register. Direct
            # URL still works (honest empty state); navigation stops advertising it.
            # {
            #                 "label": "Culture & Engagement",
            #                 "url": "/culture-engagement",
            #                 "page_key": "culture_engagement",
            #             },
            {
                "label": "Employee Relations",
                "url": "/employee-relations",
                "page_key": "employee_relations",
            },
            # DESCOPED until a production writer exists — the model behind this
            # page has none, so the page is a permanently empty register. Direct
            # URL still works (honest empty state); navigation stops advertising it.
            # {
            #                 "label": "Wellness",
            #                 "url": "/wellness",
            #                 "page_key": "wellness",
            #             },
        ],
    },
    {
        "group_label": "REWARDS & COMPLIANCE",
        "items": [
            # DESCOPED until a production writer exists — the model behind this
            # page has none, so the page is a permanently empty register. Direct
            # URL still works (honest empty state); navigation stops advertising it.
            # {
            #                 "label": "Compensation & Benefits",
            #                 "url": "/compensation-benefits",
            #                 "page_key": "compensation_benefits",
            #             },
            # DESCOPED until a production writer exists — the model behind this
            # page has none, so the page is a permanently empty register. Direct
            # URL still works (honest empty state); navigation stops advertising it.
            # {
            #                 "label": "Payroll Readiness",
            #                 "url": "/payroll-readiness",
            #                 "page_key": "payroll_readiness",
            #             },
            # DESCOPED until a production writer exists — the model behind this
            # page has none, so the page is a permanently empty register. Direct
            # URL still works (honest empty state); navigation stops advertising it.
            # {
            #                 "label": "Compliance Register",
            #                 "url": "/compliance-register",
            #                 "page_key": "compliance_register",
            #             },
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
        # Named INSIGHTS when it held HR Analytics. That page is now the
        # Analytics workspace's "People Analytics" section, and what remains
        # here is a log.
        "group_label": "HR AUDIT",
        "items": [
            # HR Analytics moved into the Analytics workspace as "People
            # Analytics" — same page, same audience, one fewer sidebar link.
            {
                "label": "HR Audit Log",
                "url": "/hr-audit-log",
                "page_key": "hr_audit_log",
            },
        ],
    },
]


# Navigation follows the operational journey, independent of the authoring
# order of the registry below. Python's sort is stable, so every unlisted
# section keeps its existing relative position after these three priorities.
SIDEBAR_GROUP_PRIORITY = {
    "SCHOOLS & FIELD": 0,
    "MY WORK": 1,
    "FINANCE & BUDGET": 2,
    "BUSINESS TRANSFORMATION": 3,
}


def _sidebar_sections_in_display_order() -> list[dict]:
    return sorted(
        SIDEBAR_ITEMS,
        key=lambda section: SIDEBAR_GROUP_PRIORITY.get(section["group_label"], 3),
    )


# Legacy name retained for compatibility. Admin is the super-role and the
# sidebar builder no longer restricts it to this set.
ADMIN_NAV_PAGE_KEYS: set[str] = {
    # Admin home
    "dashboard",
    "todos",
    "admin_my_plan",
    "admin_planning",
    "admin_team_plans",
    # Support and operations
    "admin_support_queue",
    "admin_incidents",
    "admin_maintenance",
    "data_repair",
    "uploads",
    "system_health",
    # School data administration: Admin uploads schools and SSA files and
    # edits school records, so it needs to reach every school.
    "schools",
    "school_directory",
    "school_upload",
    "ia_upload_center",
    "data_quality_center",
    "upload_history",
    # Access and security
    "users",
    "roles_permissions",
    "audit_log",
    # Platform configuration
    "workflow_rules",
    "page_access_matrix",
    "region_district_setup",
    "notifications_mgmt",
}


def build_sidebar_for_user(user, current_path: str) -> list[dict]:
    """Generates the grouped list of visible sidebar links for the given user."""
    role = get_user_role_slug(user)
    if not role:
        return []

    analytics_sections = build_analytics_sections(user, current_path)

    # An item may declare a narrower nav audience than route authorization
    # (see the `visible_to` note below). Admin overrides that so the super-role
    # is offered everything — but when the SAME page is registered in two
    # groups, and one of them deliberately excludes this role precisely so it
    # is not advertised twice, the override turned that intent into the
    # duplicate it was written to prevent: Admin was offered Upload Center in
    # two groups at once.
    #
    # So the override yields only when it would produce a duplicate. Nothing
    # disappears from Admin's sidebar — an excluded item is still shown when it
    # is the only registration of that page — but no page is ever offered
    # twice in one sidebar.
    _page_key_counts: dict[str, int] = {}
    ordered_sections = _sidebar_sections_in_display_order()

    for _sec in ordered_sections:
        _audience = _sec.get("visible_to")
        if role != ADMIN and _audience is not None and role not in _audience:
            continue
        for _item in _sec["items"]:
            _key = _item.get("page_key")
            if _key:
                _page_key_counts[_key] = _page_key_counts.get(_key, 0) + 1

    sections = []
    for sec in ordered_sections:
        section_audience = sec.get("visible_to")
        if (
            role != ADMIN
            and section_audience is not None
            and role not in section_audience
        ):
            continue

        visible_items = []
        for item in sec["items"]:
            # The Analytics hub stands for a whole workspace, so it is resolved
            # from the sections the role can open rather than from one key: it
            # disappears when none are available, and it borrows the section's
            # own name when there is only one — a Partner keeps the "Decision
            # Log" link they have always had rather than an "Analytics" link
            # that opens a single page.
            #
            # It always points at the first section the role can reach, never
            # at the section they happen to be viewing: a sidebar link whose
            # destination moves under you is one that reloads the current page
            # as often as it navigates anywhere.
            if item.get("analytics_hub"):
                if not analytics_sections:
                    continue
                home = analytics_sections[0]
                only_one = len(analytics_sections) == 1
                visible_items.append(
                    {
                        "label": home["label"] if only_one else item["label"],
                        "url": home["url"],
                        "icon": ICONS.get(item["page_key"], DEFAULT_SIDEBAR_ICON),
                        "active": any(s["active"] for s in analytics_sections),
                        "page_key": item["page_key"],
                    }
                )
                continue

            # A navigation audience may intentionally be narrower than route
            # authorization. This lets a page remain reachable from the right
            # workspace or a deep link without advertising it in an unrelated
            # role's sidebar.
            allowed = item.get(
                "visible_to",
                PAGE_PERMISSIONS.get(item["page_key"], set()),
            )
            explicitly_scoped = "visible_to" in item
            in_audience = role in allowed
            # Admin's override stands unless it would duplicate a page that
            # another group already offers this role.
            overridden = (
                role == ADMIN
                and not in_audience
                and item.get("page_key") not in BT_SPECIALIST_NAV_PAGES
                and not (
                    explicitly_scoped
                    and _page_key_counts.get(item.get("page_key"), 0) > 1
                )
            )
            if in_audience or overridden:
                # Per-role URL override (e.g. a Project Coordinator's "Planning"
                # points to the project-scoped planning page).
                url = item.get("role_urls", {}).get(role, item["url"])
                # Active check: exact match for the dashboard and the /projects
                # hub (whose children — /projects/planning etc. — are their own
                # nav items); prefix match for everything else.
                if url == "/dashboard":
                    is_active = current_path == url or current_path == "/"
                elif url in {"/projects", "/ssa"}:
                    # Exact match where a sibling route owns its own active
                    # state. /my-performance left this set when its tab
                    # deep-links did: with no siblings to swallow, the
                    # dashboard should highlight on /my-performance/* too.
                    is_active = current_path == url
                else:
                    is_active = current_path.startswith(url)

                # An item whose view redirects elsewhere still owns the page it
                # sends you to. "Partners" points at /partners and bounces
                # staff to /partner-oversight/, and without this the sidebar
                # would highlight nothing once they arrived — the one entry for
                # partner work looking unselected on the partner page.
                if not is_active:
                    is_active = any(
                        current_path.startswith(extra)
                        for extra in item.get("extra_active_paths", ())
                    )

                visible_items.append(
                    {
                        "label": item.get("role_labels", {}).get(role, item["label"]),
                        "url": url,
                        "icon": ICONS.get(
                            item.get("icon_key", item["page_key"]),
                            DEFAULT_SIDEBAR_ICON,
                        ),
                        "active": is_active,
                        # Carried so the mobile bottom navigation can select
                        # destinations by page rather than by matching labels,
                        # which roles override. Unused by the sidebar template.
                        "page_key": item["page_key"],
                    }
                )

        # Only show the section if it has at least one visible item inside it
        if visible_items:
            has_active_item = any(item["active"] for item in visible_items)
            # A collapsed heading hiding a single link is a click that buys the
            # user nothing — it is spent revealing what the heading already
            # said. Those sections render as the link itself. This is what the
            # Analytics workspace looks like in the sidebar, and it applies to
            # any group a given role happens to see only one item in.
            standalone = len(visible_items) == 1
            sections.append(
                {
                    "label": sec["group_label"],
                    "items": visible_items,
                    "active": has_active_item,
                    "standalone": standalone,
                    # Keep the personal workspace available on first load;
                    # every other group opens only when it contains the page.
                    "expanded": (
                        has_active_item or standalone or sec["group_label"] == "MY WORK"
                    ),
                }
            )

    # Longest match wins. Two items can both prefix-match one path — on
    # /schools/closed, "Schools" (/schools) and "Closed Schools"
    # (/schools/closed) were both lit, which reads as being in two places at
    # once. The deeper URL is where the user actually is; the shallower item
    # stays active for its own pages (/schools, /schools/<pk>) because on
    # those paths no deeper sibling matches. Section expansion recomputes
    # afterwards so a group does not stay open for a highlight it lost.
    lit = [item for sec in sections for item in sec["items"] if item["active"]]
    for shallow in lit:
        shallow_url = shallow["url"].rstrip("/") + "/"
        if any(
            deep is not shallow and deep["url"].startswith(shallow_url) for deep in lit
        ):
            shallow["active"] = False
    for sec in sections:
        sec["active"] = any(item["active"] for item in sec["items"])
        sec["expanded"] = (
            sec["active"] or sec["standalone"] or sec["label"] == "MY WORK"
        )

    return sections


# ── Mobile bottom navigation ─────────────────────────────────────────────────
# A phone gets four primary destinations plus More; five is the ceiling before
# targets stop being thumb-sized.
MOBILE_NAV_MAX_PRIMARY = 4

# Destinations a phone needs that no sidebar section offers. Adding them to
# SIDEBAR_ITEMS instead would put them in every desktop sidebar as a side
# effect, which is not the intent. Authorization still comes from
# PAGE_PERMISSIONS, so these can advertise a page but never grant it.
#
#   messages — on desktop this is a topbar drawer, so it is a sidebar item
#     nowhere, yet it is a primary destination for every role on a phone.
#   ssa — registered in IA_SECTIONS (a workspace registry), so it never
#     reaches build_sidebar_for_user. §24 makes it IA's second queue.
_MOBILE_NAV_STANDALONE = {
    "messages": {"label": "Messages", "url": "/messages", "match": "prefix"},
    "ssa": {
        "label": "SSA",
        "url": "/ssa",
        "match": "prefix",
        # IA's SSA work is the verification queue, not the browse page. Every
        # other authorized role wants the page itself.
        "role_urls": {IA: "/ssa/verification/"},
    },
}

# Preference order per role. These are *requests*, not guarantees: a key is
# used only when the role can actually reach that page, so this table can never
# grant access, and §7's "no bottom navigation item for a page the role cannot
# access" holds by construction. Anything unavailable is skipped and the slot
# is backfilled from the role's own sidebar order.
MOBILE_NAV_BY_ROLE: dict[str, tuple[str, ...]] = {
    # Field execution — the phone IS the field device, so the Today
    # workbench (roadmap Phase 5) leads; the plan and schools follow.
    CCEO: ("today", "my_plan", "schools", "messages"),
    # A Partner is not authorized for the school directory at all. Their
    # phone opens on the Assigned Schools intake — the same place their
    # sidebar home points.
    PARTNER: ("partner_schools", "my_plan", "calendar", "messages"),
    # A PL's second surface is the team, not their own plan alone.
    PL: ("today", "my_plan", "team_planning_oversight", "messages"),
    # Projects lead for the coordinator; their planning is project-scoped.
    PROJECT_COORDINATOR: ("today", "projects", "my_plan", "messages"),
    # Verification is the whole job; SSA is its second queue.
    IA: ("dashboard", "ia_verification_queue", "ssa", "messages"),
    # Finance operates queues, not dashboards.
    ACCOUNTANT: ("dashboard", "disbursements", "finance_partner_payments", "messages"),
    # People work: the directory and the approvals that block others.
    HR: ("dashboard", "staff", "leave_approvals", "messages"),
    # Leadership decides on budget and reads the evidence.
    CD: ("dashboard", "country_budget", "analytics", "messages"),
    RVP: ("dashboard", "country_budget", "analytics", "messages"),
    # Platform operations: the incoming queue and the health of the system.
    ADMIN: ("dashboard", "admin_support_queue", "system_health", "messages"),
}

# Used for a role with no entry above, and to fill any slot a role's preferred
# key could not supply.
_MOBILE_NAV_FALLBACK = ("dashboard", "my_plan", "todos", "messages")

# Sidebar labels are written for a 240px column and truncate to nonsense in a
# 78px tab — "Disbursement Dashboard" renders as "Disburseme…". These are the
# same destinations named for the space a phone actually has. Only keys that
# need shortening appear; anything absent keeps its sidebar label.
MOBILE_NAV_SHORT_LABELS = {
    "admin_support_queue": "Support",
    "country_budget": "Budget",
    "disbursements": "Disburse",
    "finance_partner_payments": "Payments",
    "ia_verification_queue": "Verify",
    "leave_approvals": "Leave",
    "my_professional_development": "PD",
    "staff": "People",
    "system_health": "Health",
    "team_planning_oversight": "Oversight",
    "weekly_fund_request": "Funds",
}


def build_mobile_nav_for_user(
    user, current_path: str, sections: list[dict] | None = None
) -> list[dict]:
    """Primary phone destinations for this user, in order.

    Derived from ``build_sidebar_for_user`` rather than from a parallel table,
    so a role can never be offered a destination its sidebar would not show it.
    Route authorization still runs on the request; this only decides what to
    advertise.

    Pass ``sections`` when the caller has already built the sidebar for this
    request — the context processor has — so the registry is not walked twice
    on every page load. Omit it and the sections are built here, which is what
    tests and any standalone caller want.

    Returns up to ``MOBILE_NAV_MAX_PRIMARY`` items. The More control that opens
    the full navigation drawer is part of the template, not this list — it is
    always present and never role-dependent.
    """
    role = get_user_role_slug(user)
    if not role:
        return []

    if sections is None:
        sections = build_sidebar_for_user(user, current_path)

    catalogue: dict[str, dict] = {}
    order: list[str] = []
    for section in sections:
        for item in section["items"]:
            key = item.get("page_key")
            # First registration wins. A page listed in two groups resolves to
            # the same URL either way, and taking the first keeps mobile order
            # matching the sidebar the user already knows.
            if key and key not in catalogue:
                catalogue[key] = item
                order.append(key)

    for key, spec in _MOBILE_NAV_STANDALONE.items():
        if role not in PAGE_PERMISSIONS.get(key, set()):
            continue
        url = spec.get("role_urls", {}).get(role, spec["url"])
        catalogue.setdefault(
            key,
            {
                "label": spec["label"],
                "url": url,
                "icon": ICONS.get(key, DEFAULT_SIDEBAR_ICON),
                "active": _path_matches(url, current_path, spec["match"]),
                "page_key": key,
            },
        )

    chosen: list[dict] = []
    seen: set[str] = set()

    def take(key: str) -> None:
        if len(chosen) >= MOBILE_NAV_MAX_PRIMARY or key in seen:
            return
        item = catalogue.get(key)
        if item is None:
            return
        seen.add(key)
        chosen.append(item)

    for key in MOBILE_NAV_BY_ROLE.get(role, _MOBILE_NAV_FALLBACK):
        take(key)
    for key in _MOBILE_NAV_FALLBACK:
        take(key)
    # Still short only when the role sees very few pages at all; fill from
    # whatever its sidebar does offer so the bar never renders half-empty.
    for key in order:
        take(key)

    # Copied, never mutated in place: these dicts are the same objects the
    # sidebar is rendering from, and renaming them here would rename the
    # sidebar entry too.
    return [
        {**item, "label": MOBILE_NAV_SHORT_LABELS.get(item["page_key"], item["label"])}
        for item in chosen
    ]
