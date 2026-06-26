"""
Role-Based Access Control — faithful port of rbac/permissions.ts.

Defines the canonical permission keys + the role→permission matrix. This is the
single source of truth seeded into the RolePermission table and used by the
RequirePermissions view mixin / decorator.

Notes preserved from the legacy matrix:
- Admin gets all permissions.
- CD has NO schoolDirectory.view and NO planning.create — CD leads via analytics
  and flags issues to the PL instead. CD owns the rate card but does NOT approve
  fund requests (the field chain CCEO → PL does).
- RVP is summary-only (region/country summary, no school-level rows).
- CCEO is the primary cluster-assigning field role (but no CLUSTER_OVERRIDE).
- PartnerAdmin/PartnerFieldOfficer are minimal (activity complete + planning view).
"""
from __future__ import annotations

from enum import Enum


class EdifyRole(str, Enum):
    CCEO = "CCEO"
    COUNTRY_PROGRAM_LEAD = "CountryProgramLead"
    COUNTRY_DIRECTOR = "CountryDirector"
    REGIONAL_VICE_PRESIDENT = "RegionalVicePresident"
    IMPACT_ASSESSMENT = "ImpactAssessment"
    PROGRAM_ACCOUNTANT = "ProgramAccountant"
    HUMAN_RESOURCES = "HumanResources"
    PROJECT_COORDINATOR = "ProjectCoordinator"
    PARTNER_ADMIN = "PartnerAdmin"
    PARTNER_FIELD_OFFICER = "PartnerFieldOfficer"
    ADMIN = "Admin"

    @classmethod
    def values(cls) -> list[str]:
        return [r.value for r in cls]


class Permission(str, Enum):
    """Canonical permission keys. Controllers reference these — never raw role lists."""

    SCHOOL_VIEW = "school.view"
    # Operational School Directory list/profile. Distinct from SCHOOL_VIEW: the
    # directory is an operational working surface limited to the roles that
    # actually work schools (CCEO, PL, IA) + the project coordinator who assigns
    # project schools. CD/RVP/HR/Accountant/Partner are blocked — they get
    # aggregates from analytics, never the operational list.
    SCHOOL_DIRECTORY_VIEW = "schoolDirectory.view"
    RECRUITMENT_INTELLIGENCE_VIEW = "recruitment.view"
    # HR people surfaces — staff performance, leave planner, daily field debrief.
    STAFF_PERFORMANCE_VIEW = "staffPerformance.view"
    LEAVE_PLANNER_VIEW = "leavePlanner.view"
    DAILY_DEBRIEF_VIEW = "dailyDebrief.view"
    SCHOOL_UPLOAD = "school.upload"
    SCHOOL_EDIT = "school.edit"
    SCHOOL_RESOLVE_DUPLICATE = "school.resolveDuplicate"
    CLUSTER_VIEW = "cluster.view"
    CLUSTER_ASSIGN = "cluster.assign"
    CLUSTER_OVERRIDE = "cluster.override"  # create a 2nd cluster in a sub-county
    PLANNING_RECALC = "planning.recalc"
    SSA_VIEW = "ssa.view"
    SSA_UPLOAD = "ssa.upload"
    PLANNING_VIEW = "planning.view"
    PLANNING_CREATE = "planning.create"
    ACTIVITY_ASSIGN = "activity.assign"
    ACTIVITY_COMPLETE = "activity.complete"
    EVIDENCE_REVIEW = "evidence.review"
    IA_VERIFY = "ia.verify"
    PAYMENT_ACT = "payment.act"
    BUDGET_VIEW_SUMMARY = "budget.viewSummary"
    BUDGET_VIEW_DETAIL = "budget.viewDetail"
    BUDGET_APPROVE = "budget.approve"
    # The CD-owned rate card. Only CD (and Admin) may create/edit official cost
    # settings — no staff invents costs.
    COST_SETTINGS_MANAGE = "costSettings.manage"
    STAFF_MANAGE = "staff.manage"
    # Provision + onboard user accounts. Held by the people/onboarding roles.
    USER_MANAGE = "user.manage"
    PARTNER_VIEW = "partner.view"
    PARTNER_MANAGE = "partner.manage"
    PROJECT_MANAGE = "project.manage"
    ANALYTICS_VIEW = "analytics.view"
    EXPORT = "data.export"
    SYSTEM_ADMIN = "system.admin"
    # Leadership Decision Engine — recommends; never auto-executes.
    LEADERSHIP_ENGINE_VIEW = "leadership.view"
    LEADERSHIP_DECISION_REVIEW = "leadership.review"
    # Budget Intelligence & Financial Decision Engine — recommends; never moves money.
    BUDGET_INTELLIGENCE_VIEW = "budgetIntelligence.view"
    BUDGET_DECISION_REVIEW = "budgetDecision.review"


P = Permission


# Role → permissions matrix. Single source of truth seeded into RolePermission.
ROLE_PERMISSIONS: dict[EdifyRole, list[Permission]] = {
    EdifyRole.ADMIN: list(Permission),
    EdifyRole.COUNTRY_DIRECTOR: [
        # No SCHOOL_DIRECTORY_VIEW — CD leads through analytics, not the
        # operational directory. CD doesn't plan or assign field work; CD flags
        # issues to the PL instead. CD owns the rate card but does NOT approve
        # fund requests (field chain CCEO → PL).
        P.SCHOOL_VIEW, P.SCHOOL_EDIT, P.CLUSTER_VIEW, P.CLUSTER_ASSIGN, P.CLUSTER_OVERRIDE,
        P.PLANNING_RECALC, P.SSA_VIEW, P.PLANNING_VIEW,
        P.EVIDENCE_REVIEW, P.BUDGET_VIEW_SUMMARY, P.BUDGET_VIEW_DETAIL,
        P.COST_SETTINGS_MANAGE,
        P.STAFF_MANAGE, P.USER_MANAGE, P.STAFF_PERFORMANCE_VIEW, P.PARTNER_VIEW,
        P.PARTNER_MANAGE, P.PROJECT_MANAGE, P.ANALYTICS_VIEW, P.EXPORT,
        P.RECRUITMENT_INTELLIGENCE_VIEW,
        # Full country leadership decision authority.
        P.LEADERSHIP_ENGINE_VIEW, P.LEADERSHIP_DECISION_REVIEW,
        # Full country financial intelligence + reallocation decision authority.
        P.BUDGET_INTELLIGENCE_VIEW, P.BUDGET_DECISION_REVIEW,
    ],
    EdifyRole.REGIONAL_VICE_PRESIDENT: [
        # No SCHOOL_DIRECTORY_VIEW — summary analytics + recruitment only.
        P.SCHOOL_VIEW, P.CLUSTER_VIEW, P.SSA_VIEW, P.PLANNING_VIEW,
        P.BUDGET_VIEW_SUMMARY, P.ANALYTICS_VIEW, P.RECRUITMENT_INTELLIGENCE_VIEW,
        # Region/country summary + approval-level decision review.
        P.LEADERSHIP_ENGINE_VIEW, P.LEADERSHIP_DECISION_REVIEW,
        P.BUDGET_INTELLIGENCE_VIEW,  # summary budget view
        P.STAFF_PERFORMANCE_VIEW,  # region staff-performance summary (no PII/email)
    ],
    EdifyRole.COUNTRY_PROGRAM_LEAD: [
        P.SCHOOL_VIEW, P.SCHOOL_DIRECTORY_VIEW, P.SCHOOL_EDIT, P.CLUSTER_VIEW,
        P.CLUSTER_ASSIGN, P.SSA_VIEW, P.PLANNING_VIEW, P.PLANNING_CREATE,
        P.ACTIVITY_ASSIGN, P.ACTIVITY_COMPLETE,
        # PL approves the monthly fund request + plan rolled up from the CCEOs
        # they supervise (the top of the field approval chain).
        P.EVIDENCE_REVIEW, P.BUDGET_VIEW_DETAIL, P.BUDGET_APPROVE, P.PARTNER_VIEW,
        P.ANALYTICS_VIEW, P.EXPORT, P.RECRUITMENT_INTELLIGENCE_VIEW,
        # Supervised-team decision support + review within their scope.
        P.LEADERSHIP_ENGINE_VIEW, P.LEADERSHIP_DECISION_REVIEW,
        P.BUDGET_INTELLIGENCE_VIEW,  # supervised-team budget/fund view
        P.STAFF_PERFORMANCE_VIEW,  # supervised-team roster only (scoped)
    ],
    EdifyRole.CCEO: [
        # The CCEO is the primary cluster-assigning field role. Not CLUSTER_OVERRIDE.
        P.SCHOOL_VIEW, P.SCHOOL_DIRECTORY_VIEW, P.CLUSTER_VIEW, P.CLUSTER_ASSIGN,
        P.SSA_VIEW, P.PLANNING_VIEW, P.PLANNING_CREATE,
        P.ACTIVITY_ASSIGN, P.ACTIVITY_COMPLETE, P.EVIDENCE_REVIEW, P.PARTNER_VIEW,
        # CCEO approves the fund requests of the staff they supervise, then
        # submits their own consolidated monthly request up to the PL.
        P.BUDGET_VIEW_DETAIL, P.BUDGET_APPROVE,
        P.ANALYTICS_VIEW, P.RECRUITMENT_INTELLIGENCE_VIEW,
        P.BUDGET_INTELLIGENCE_VIEW,  # own planned/funded activities view
    ],
    EdifyRole.IMPACT_ASSESSMENT: [
        P.SCHOOL_VIEW, P.SCHOOL_DIRECTORY_VIEW, P.SCHOOL_UPLOAD, P.SCHOOL_EDIT,
        P.SCHOOL_RESOLVE_DUPLICATE, P.CLUSTER_VIEW, P.CLUSTER_ASSIGN, P.CLUSTER_OVERRIDE,
        P.PLANNING_RECALC, P.SSA_VIEW, P.SSA_UPLOAD, P.PLANNING_VIEW, P.EVIDENCE_REVIEW,
        P.IA_VERIFY, P.ANALYTICS_VIEW, P.EXPORT, P.RECRUITMENT_INTELLIGENCE_VIEW,
        # Data-confidence + SSA-impact readiness lens (no decision review authority).
        P.LEADERSHIP_ENGINE_VIEW,
    ],
    EdifyRole.PROGRAM_ACCOUNTANT: [
        # No SCHOOL_DIRECTORY_VIEW — finance/accountability only.
        P.SCHOOL_VIEW, P.PLANNING_VIEW, P.PAYMENT_ACT, P.BUDGET_VIEW_DETAIL,
        P.ANALYTICS_VIEW, P.EXPORT,
        # Finance-implication view only — no staff/partner decision authority.
        P.LEADERSHIP_ENGINE_VIEW,
        # Finance execution + accountability + finance-decision review.
        P.BUDGET_INTELLIGENCE_VIEW, P.BUDGET_DECISION_REVIEW,
    ],
    EdifyRole.HUMAN_RESOURCES: [
        # People surfaces only — no SCHOOL_DIRECTORY_VIEW.
        P.STAFF_MANAGE, P.USER_MANAGE, P.ANALYTICS_VIEW,
        P.STAFF_PERFORMANCE_VIEW, P.LEAVE_PLANNER_VIEW, P.DAILY_DEBRIEF_VIEW,
        # Staff & HR decision board + review.
        P.LEADERSHIP_ENGINE_VIEW, P.LEADERSHIP_DECISION_REVIEW,
    ],
    EdifyRole.PROJECT_COORDINATOR: [
        # Explicitly granted directory access — assigns project schools.
        P.SCHOOL_VIEW, P.SCHOOL_DIRECTORY_VIEW, P.PLANNING_VIEW, P.PLANNING_CREATE,
        P.ACTIVITY_ASSIGN, P.EVIDENCE_REVIEW, P.PROJECT_MANAGE, P.PARTNER_VIEW,
        P.ANALYTICS_VIEW,
    ],
    EdifyRole.PARTNER_ADMIN: [
        P.ACTIVITY_COMPLETE, P.PLANNING_VIEW,
    ],
    EdifyRole.PARTNER_FIELD_OFFICER: [
        P.ACTIVITY_COMPLETE, P.PLANNING_VIEW,
    ],
}


def permissions_for_role(role: EdifyRole | str) -> list[str]:
    """Return the permission keys for a role (accepts the enum or its value)."""
    if isinstance(role, str):
        try:
            role = EdifyRole(role)
        except ValueError:
            return []
    return [p.value for p in ROLE_PERMISSIONS.get(role, [])]


def all_permission_keys() -> list[str]:
    return [p.value for p in Permission]


__all__ = [
    "EdifyRole",
    "Permission",
    "ROLE_PERMISSIONS",
    "permissions_for_role",
    "all_permission_keys",
]
