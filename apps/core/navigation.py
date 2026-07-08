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
        "CountryDirector": "CD",
        "ImpactAssessment": "IA",
        "RegionalVicePresident": "RVP",
        "HumanResources": "HR",
        "Accountant": "ACCOUNTANT",
        "ProjectCoordinator": "PROJECT_COORDINATOR",
        "PartnerAdmin": "PARTNER",
        "PartnerFieldOfficer": "PARTNER",
    }
    return mapping.get(role, role.upper())

# Exact allowed roles for all views (for route gating)
PAGE_PERMISSIONS: dict[str, set[str]] = {
    # Main sidebar routes
    "dashboard": ALL_ROLES,
    "my_target": {CCEO, PL, PROJECT_COORDINATOR, PARTNER, ADMIN},
    "team_targets": {PL, CD, HR, IA, ACCOUNTANT, ADMIN, PROJECT_COORDINATOR},
    "my_plan": {CCEO, PL, PARTNER, PROJECT_COORDINATOR, ADMIN},
    "daily_debrief": {CCEO, PARTNER, PL, ADMIN},
    "debriefs_list": {CCEO, PARTNER, PL, ADMIN, HR},  # HR sees debrief rollups
    "debrief_detail": {CCEO, PARTNER, PL, ADMIN, HR},
    "personal_time_off": ALL_ROLES,
    "leave_requests": ALL_ROLES,
    "leave_tracker": {HR, PL, CD, RVP, ADMIN},
    "leave_approvals": {PL, CD, RVP, HR, ADMIN},
    "leave_coverage": {CCEO, PL, CD, RVP, HR, ACCOUNTANT, ADMIN},
    "leave_calendar": ALL_ROLES,
    "leave_policies": {HR, ADMIN},
    "public_holidays": ALL_ROLES,
    "team_availability": {PL, CD, RVP, HR, ADMIN},
    "schools": {CCEO, PL, PROJECT_COORDINATOR, IA, ADMIN},
    "core_schools": {CCEO, PL, IA, ADMIN},
    "school_directory": {CCEO, PL, PROJECT_COORDINATOR, IA, ADMIN},
    "school_profile": {CCEO, PL, PROJECT_COORDINATOR, IA, ADMIN},
    "school_action_drawer": {CCEO, PL, PROJECT_COORDINATOR, IA, ADMIN},
    "school_upload": {IA, ADMIN},
    "clusters": {CCEO, PL, IA, PARTNER, ADMIN},
    "cluster_planning": {CCEO, PL, IA, PARTNER, ADMIN},
    "cluster_detail": {CCEO, PL, IA, PARTNER, ADMIN},
    "partners": ALL_ROLES,
    "partner_detail": ALL_ROLES,
    "coverage": {CD, PL, RVP, HR, PROJECT_COORDINATOR, ADMIN},
    "planning": {CCEO, PL, PROJECT_COORDINATOR, ADMIN},
    "weekly_fund_request": {CCEO, PL, CD, IA, ACCOUNTANT, ADMIN},
    "fund_requests": {CCEO, PL, CD, IA, ACCOUNTANT, ADMIN},
    "monthly_request": {CD, PL, RVP, ACCOUNTANT, IA, PROJECT_COORDINATOR, ADMIN},
    "my_budget": {CCEO, PL, CD, IA, ACCOUNTANT, ADMIN},
    "monthly_budget": {CCEO, PL, CD, IA, ACCOUNTANT, ADMIN},
    "country_budget": {CD, ACCOUNTANT, IA, RVP, ADMIN},
    "consolidated_fund_allocation": {CD, ACCOUNTANT, IA, RVP, ADMIN},
    "analytics": {CD, PL, IA, RVP, HR, ACCOUNTANT, PROJECT_COORDINATOR, CCEO, ADMIN},
    "reports": {CD, PL, IA, RVP, PROJECT_COORDINATOR, ADMIN},
    "completed_archive": {IA, ADMIN},
    "completed_activities": {CCEO, PL, PROJECT_COORDINATOR, ADMIN},
    "users": {ADMIN},
    "roles_permissions": {ADMIN},
    "system_health": {ADMIN},
    "messages": ALL_ROLES,
    "notifications": ALL_ROLES,

    # Specific sub-routes / components
    "admin_dashboard": {ADMIN},
    "audit_log": {ADMIN},
    "workflow_rules": {ADMIN},
    "page_access_matrix": {ADMIN},
    "region_district_setup": {ADMIN},
    "notifications_mgmt": {ADMIN},
    "upload_history": {ADMIN},
    "data_quality_center": {IA, ADMIN},
    "settings": ALL_ROLES,
    "help": ALL_ROLES,
    "quality_checks": {IA, ADMIN},
    
    # Staff directory permissions
    "staff": {HR, PL, CD, RVP, ADMIN},
    "staff_directory": {HR, PL, CD, RVP, ADMIN},
    "my_team": {PL, CD, HR, ADMIN},
    "ssa": {IA, CD, RVP, PL, CCEO, ADMIN},
    
    # Partner sub-routes
    "partner_today": {PARTNER, ADMIN},
    "partner_schools": {PARTNER, ADMIN},
    "partner_activities": {PARTNER, ADMIN},
    "partner_evidence": {PARTNER, ADMIN},
    "partner_my_plan": {PARTNER, ADMIN},
    
    # Finance sub-routes
    "disbursements": {ACCOUNTANT, ADMIN},
    "reimbursements": {ACCOUNTANT, ADMIN},
    "accountability": {ACCOUNTANT, ADMIN},
    "finance_action_drawer": {ACCOUNTANT, ADMIN},
    "weekly_fund_request_confirm": {ACCOUNTANT, ADMIN},
    "weekly_fund_request_self_funded": {ACCOUNTANT, ADMIN},
    "weekly_fund_request_disburse": {ACCOUNTANT, ADMIN},
}

# SVG Icon templates to display inside the sidebar
ICONS = {
    "dashboard": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" /></svg>',
    "my_target": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z" /><path stroke-linecap="round" stroke-linejoin="round" d="M12 18c3.314 0 6-2.686 6-6s-2.686-6-6-6-6 2.686-6 6 2.686 6 6 6z" /><path stroke-linecap="round" stroke-linejoin="round" d="M12 14c1.105 0 2-.895 2-2s-.895-2-2-2-2 .895-2 2 .895 2 2 2z" /></svg>',
    "team_targets": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a4 4 0 00-3-3.87M9 20H4v-2a4 4 0 013-3.87m6-1.13a4 4 0 10-4-4 4 4 0 004 4zm6 0a4 4 0 10-4-4" /></svg>',
    "my_plan": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2zM12 11l2 2-4 4" /></svg>',
    "daily_debrief": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>',
    "personal_time_off": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>',
    "schools": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" /></svg>',
    "clusters": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" /></svg>',
    "partners": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" /></svg>',
    "coverage": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" /></svg>',
    "planning": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" /></svg>',
    "weekly_fund_request": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" /></svg>',
    "monthly_request": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>',
    "my_budget": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>',
    "country_budget": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /><path stroke-linecap="round" stroke-linejoin="round" d="M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z" /></svg>',
    "analytics": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M7 12l3-3 3 3 4-4M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z" /></svg>',
    "reports": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>',
    "completed_archive": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" /></svg>',
    "users": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a3 3 0 11-6 0 3 3 0 016 0z" /></svg>',
    "roles_permissions": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M15 7a2 2 0 012 2m-2 4a2 2 0 012 2m-2-4a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0zm0-10a2 2 0 11-4 0 2 2 0 014 0z" /></svg>',
    "system_health": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>',
    "messages": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" /></svg>',
    "notifications": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" /></svg>',
    "leave_tracker": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 002 2h2a2 2 0 002-2z" /></svg>',
    "leave_approvals": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" /></svg>',
    "leave_coverage": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a3 3 0 11-6 0 3 3 0 016 0z" /></svg>',
    "leave_calendar": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>',
    "leave_policies": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>',
    "public_holidays": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>',
    "team_availability": '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 002 2h2a2 2 0 002-2z" /></svg>',
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
            },
            {
                "label": "Daily Debrief",
                "url": "/debriefs",
                "page_key": "daily_debrief",
            },
            {
                "label": "Personal Time Off",
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
                "label": "Coverage",
                "url": "/coverage",
                "page_key": "coverage",
            },
            {
                "label": "Leave Coverage",
                "url": "/leave/coverage",
                "page_key": "leave_coverage",
            },
            {
                "label": "Leave Calendar",
                "url": "/leave/calendar",
                "page_key": "leave_calendar",
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
            },
            {
                "label": "Weekly Fund Request",
                "url": "/fund-requests/weekly",
                "page_key": "weekly_fund_request",
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
        ],
    },
    {
        "group_label": "QUALITY & INSIGHTS",
        "items": [
            {
                "label": "Analytics",
                "url": "/analytics",
                "page_key": "analytics",
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
                "url": "/admin/leave-policies",
                "page_key": "leave_policies",
            },
            {
                "label": "Public Holidays",
                "url": "/public-holidays",
                "page_key": "public_holidays",
            },
        ],
    },
    {
        "group_label": "ACCOUNT",
        "items": [
            {
                "label": "Messages",
                "url": "/messages",
                "page_key": "messages",
            },
            {
                "label": "Notifications",
                "url": "/notifications",
                "page_key": "notifications",
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
                # Active check: exact route match for dashboard, prefix match for others.
                url = item["url"]
                if url == "/dashboard":
                    is_active = (current_path == url or current_path == "/")
                else:
                    is_active = current_path.startswith(url)
                
                visible_items.append({
                    "label": item["label"],
                    "url": url,
                    "icon": ICONS.get(item["page_key"], ""),
                    "active": is_active,
                })
        
        # Only show the section if it has at least one visible item inside it
        if visible_items:
            sections.append({
                "label": sec["group_label"],
                "items": visible_items,
            })
            
    return sections
