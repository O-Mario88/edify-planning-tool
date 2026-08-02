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
    COUNTRY_PROGRAM_LEAD = "Program Lead"
    COUNTRY_DIRECTOR = "CountryDirector"
    REGIONAL_VICE_PRESIDENT = "RegionalVicePresident"
    IMPACT_ASSESSMENT = "ImpactAssessment"
    PROGRAM_ACCOUNTANT = "Accountant"
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
    # §5 — the Work Plan "Add Non-School Activity" entry point: dated
    # programme activities (conferences, camps, exhibitions) created outside
    # school/cluster planning but through the same canonical funnel.
    MANUAL_ACTIVITY_CREATE = "planning.manualActivity.create"
    ACTIVITY_ASSIGN = "activity.assign"
    ACTIVITY_COMPLETE = "activity.complete"
    ACTIVITY_CATALOGUE_VIEW = "activityCatalogue.view"
    ACTIVITY_CATALOGUE_MANAGE = "activityCatalogue.manage"
    ACTIVITY_CATALOGUE_MAP_INTERVENTIONS = "activityCatalogue.mapInterventions"
    ACTIVITY_CATALOGUE_MANAGE_PROJECT_RULES = "activityCatalogue.manageProjectRules"
    STRATEGIC_PRIORITIES_VIEW = "strategicPriorities.view"
    STRATEGIC_PRIORITIES_CREATE = "strategicPriorities.create"
    STRATEGIC_PRIORITIES_EDIT = "strategicPriorities.edit"
    STRATEGIC_PRIORITIES_APPROVE = "strategicPriorities.approve"
    STRATEGIC_PRIORITIES_ALLOCATE = "strategicPriorities.allocate"
    MILESTONES_DEFINE = "milestones.define"
    MILESTONES_ALLOCATE = "milestones.allocate"
    MILESTONES_VIEW_PROGRESS = "milestones.viewProgress"
    EVIDENCE_REVIEW = "evidence.review"
    IA_VERIFY = "ia.verify"
    PAYMENT_ACT = "payment.act"
    BUDGET_VIEW_SUMMARY = "budget.viewSummary"
    BUDGET_VIEW_DETAIL = "budget.viewDetail"
    # The field chain's approval right (CCEO approves their staff, PL approves
    # the CCEOs they supervise). Deliberately NOT held by CD/RVP — the country
    # envelope is a separate authority, below.
    BUDGET_APPROVE = "budget.approve"
    # The country money chain, previously enforced only by role-string checks
    # inside services and therefore invisible to this matrix:
    #   • CD consolidates PL requests and submits the country envelope.
    #   • RVP approves/returns it, and locks the annual baseline.
    #   • CD approves weekly advances escalated to them (non-CCEO owners).
    COUNTRY_BUDGET_SUBMIT = "countryBudget.submit"
    COUNTRY_BUDGET_APPROVE = "countryBudget.approve"
    FUND_REQUEST_APPROVE_ESCALATED = "fundRequest.approveEscalated"
    # The CD-owned rate card. Only CD (and Admin) may create/edit official cost
    # settings — no staff invents costs.
    COST_SETTINGS_MANAGE = "costSettings.manage"
    STAFF_MANAGE = "staff.manage"
    # Provision + onboard user accounts. Held by the people/onboarding roles.
    USER_MANAGE = "user.manage"
    PARTNER_VIEW = "partner.view"
    PARTNER_MANAGE = "partner.manage"
    PROJECT_MANAGE = "project.manage"
    PROJECT_CONFIGURE_PRIORITIES = "project.configurePriorities"
    # Assign a school to a project. Distinct from PROJECT_MANAGE (which gates
    # setting a project's manager) — broader set of operational roles work
    # schools day-to-day and need this without gaining manager-assignment rights.
    PROJECT_ASSIGN_SCHOOL = "project.assignSchool"
    ANALYTICS_VIEW = "analytics.view"
    EXPORT = "data.export"
    SYSTEM_ADMIN = "system.admin"
    # Document Library, Upload Center and policy compliance. Creating a draft
    # and publishing it are separate rights on purpose: the person who writes a
    # policy is often not the person authorised to put it in front of staff.
    UPLOADS_VIEW = "uploads.view"
    DOCUMENTS_CREATE = "documents.create"
    DOCUMENTS_REVIEW = "documents.review"
    DOCUMENTS_PUBLISH = "documents.publish"
    DOCUMENTS_ARCHIVE = "documents.archive"
    DOCUMENTS_MANAGE_AUDIENCE = "documents.manage_audience"
    POLICIES_MANAGE_ACKNOWLEDGEMENTS = "policies.manage_acknowledgements"
    # The private comment a person writes beside their acknowledgement. Read
    # access is deliberately narrow -- a Program Lead sees whether their team
    # has answered, never what they wrote.
    POLICIES_REVIEW_COMMENTS = "policies.review_comments"
    TRAINING_RESOURCES_CREATE = "training_resources.create"
    TRAINING_RESOURCES_PUBLISH = "training_resources.publish"
    # Leadership Decision Engine — recommends; never auto-executes.
    LEADERSHIP_ENGINE_VIEW = "leadership.view"
    LEADERSHIP_DECISION_REVIEW = "leadership.review"
    # Budget Intelligence & Financial Decision Engine — recommends; never moves money.
    BUDGET_INTELLIGENCE_VIEW = "budgetIntelligence.view"
    BUDGET_DECISION_REVIEW = "budgetDecision.review"


P = Permission


# Admin is the platform super-role: it receives every current permission, and
# newly introduced permissions are included automatically — EXCEPT the three
# below, which are single-role authorities by doctrine.
#
# Those three had been excluded deliberately, then the exclusion set was
# emptied while making Admin "not read-only". Read-only was a real problem and
# fixing it was right, but this went past access into authority: with these
# granted, one account could approve a budget, disburse against it, and then
# verify the activity it paid for. That is the whole control, and it is the one
# that matters most in a system that moves money and keeps a tamper-evident
# chain of who did what.
#
# This does NOT stop the admin *person* doing field work. Roles are held per
# user and switched via active_role, so an admin who is also a CCEO does field
# work as the CCEO. What it stops is the Admin role itself being a way around
# the separation — which is exactly what a super-role must not be.
#
# Admin keeps every viewing permission over all of it, because observing a
# control is not the same as exercising it.
ADMIN_EXCLUDED_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        # Activity/SSA verification is Impact Assessment's alone.
        Permission.IA_VERIFY,
        # Disbursement is the Accountant's alone.
        Permission.PAYMENT_ACT,
        # Field budget approval is the CCEO→PL chain alone.
        Permission.BUDGET_APPROVE,
    }
)


# Role → permissions matrix. Single source of truth seeded into RolePermission.
ROLE_PERMISSIONS: dict[EdifyRole, list[Permission]] = {
    EdifyRole.ADMIN: [p for p in Permission if p not in ADMIN_EXCLUDED_PERMISSIONS],
    EdifyRole.COUNTRY_DIRECTOR: [
        # §5 — authorized non-school programme activities.
        P.MANUAL_ACTIVITY_CREATE,
        # Country-scoped policy authorship, and the country's policy comments.
        P.UPLOADS_VIEW,
        P.DOCUMENTS_CREATE,
        P.DOCUMENTS_REVIEW,
        P.DOCUMENTS_PUBLISH,
        P.DOCUMENTS_MANAGE_AUDIENCE,
        P.POLICIES_REVIEW_COMMENTS,
        # No SCHOOL_DIRECTORY_VIEW — CD leads through analytics, not the
        # operational directory. CD doesn't plan or assign field work; CD flags
        # issues to the PL instead. CD owns the rate card but does NOT approve
        # fund requests (field chain CCEO → PL).
        P.SCHOOL_VIEW,
        P.SCHOOL_EDIT,
        P.CLUSTER_VIEW,
        P.CLUSTER_ASSIGN,
        P.CLUSTER_OVERRIDE,
        P.PLANNING_RECALC,
        P.SSA_VIEW,
        P.PLANNING_VIEW,
        P.ACTIVITY_CATALOGUE_VIEW,
        P.EVIDENCE_REVIEW,
        P.BUDGET_VIEW_SUMMARY,
        P.BUDGET_VIEW_DETAIL,
        # CD consolidates the PL monthly requests and submits the country
        # envelope up to the RVP; CD also clears weekly advances escalated to
        # them. CD still does NOT hold BUDGET_APPROVE — the field chain
        # (CCEO → PL) owns that.
        P.COUNTRY_BUDGET_SUBMIT,
        P.FUND_REQUEST_APPROVE_ESCALATED,
        P.COST_SETTINGS_MANAGE,
        P.STAFF_MANAGE,
        P.USER_MANAGE,
        P.STAFF_PERFORMANCE_VIEW,
        P.PARTNER_VIEW,
        P.PARTNER_MANAGE,
        P.PROJECT_MANAGE,
        P.PROJECT_CONFIGURE_PRIORITIES,
        P.PROJECT_ASSIGN_SCHOOL,
        P.ANALYTICS_VIEW,
        P.EXPORT,
        P.RECRUITMENT_INTELLIGENCE_VIEW,
        # Full country leadership decision authority.
        P.LEADERSHIP_ENGINE_VIEW,
        P.LEADERSHIP_DECISION_REVIEW,
        # Full country financial intelligence + reallocation decision authority.
        P.BUDGET_INTELLIGENCE_VIEW,
        P.BUDGET_DECISION_REVIEW,
        P.STRATEGIC_PRIORITIES_VIEW,
        P.STRATEGIC_PRIORITIES_ALLOCATE,
        P.MILESTONES_ALLOCATE,
        P.MILESTONES_VIEW_PROGRESS,
    ],
    EdifyRole.REGIONAL_VICE_PRESIDENT: [
        # May author and publish policy within its scope, and sees regional
        # acknowledgement summaries -- not the private comments behind them.
        P.UPLOADS_VIEW,
        P.DOCUMENTS_CREATE,
        P.DOCUMENTS_REVIEW,
        P.DOCUMENTS_PUBLISH,
        P.DOCUMENTS_MANAGE_AUDIENCE,
        # No SCHOOL_DIRECTORY_VIEW — summary analytics + recruitment only.
        P.SCHOOL_VIEW,
        P.SSA_VIEW,
        P.BUDGET_VIEW_SUMMARY,
        # The RVP is the final sign-off on the country monthly envelope and the
        # annual baseline lock. This is the authority the old role-string
        # checks actually enforced; naming it here makes it auditable.
        P.COUNTRY_BUDGET_APPROVE,
        P.ANALYTICS_VIEW,
        P.RECRUITMENT_INTELLIGENCE_VIEW,
        # Region/country summary + approval-level decision review.
        P.LEADERSHIP_ENGINE_VIEW,
        P.LEADERSHIP_DECISION_REVIEW,
        P.BUDGET_INTELLIGENCE_VIEW,  # summary budget view
        P.STAFF_PERFORMANCE_VIEW,  # region staff-performance summary (no PII/email)
        # Region-level oversight reporting. can_export already listed the RVP;
        # the matrix disagreed, so the SSA export silently 403'd.
        P.EXPORT,
        P.STRATEGIC_PRIORITIES_VIEW,
        P.STRATEGIC_PRIORITIES_CREATE,
        P.STRATEGIC_PRIORITIES_EDIT,
        P.STRATEGIC_PRIORITIES_APPROVE,
        P.STRATEGIC_PRIORITIES_ALLOCATE,
        P.MILESTONES_DEFINE,
        P.MILESTONES_ALLOCATE,
        P.MILESTONES_VIEW_PROGRESS,
    ],
    EdifyRole.COUNTRY_PROGRAM_LEAD: [
        P.SCHOOL_VIEW,
        P.SCHOOL_DIRECTORY_VIEW,
        P.SCHOOL_EDIT,
        P.CLUSTER_VIEW,
        P.CLUSTER_ASSIGN,
        P.SSA_VIEW,
        P.PLANNING_VIEW,
        P.ACTIVITY_CATALOGUE_VIEW,
        P.PLANNING_CREATE,
        P.MANUAL_ACTIVITY_CREATE,
        P.ACTIVITY_ASSIGN,
        P.ACTIVITY_COMPLETE,
        P.ACTIVITY_CATALOGUE_VIEW,
        # PL approves the monthly fund request + plan rolled up from the CCEOs
        # they supervise (the top of the field approval chain).
        P.EVIDENCE_REVIEW,
        P.BUDGET_VIEW_DETAIL,
        P.BUDGET_APPROVE,
        P.PARTNER_VIEW,
        P.ANALYTICS_VIEW,
        P.EXPORT,
        P.RECRUITMENT_INTELLIGENCE_VIEW,
        # Supervised-team decision support + review within their scope.
        P.LEADERSHIP_ENGINE_VIEW,
        P.LEADERSHIP_DECISION_REVIEW,
        P.BUDGET_INTELLIGENCE_VIEW,  # supervised-team budget/fund view
        P.STAFF_PERFORMANCE_VIEW,  # supervised-team roster only (scoped)
        # PL works the operational school directory, including project assignment.
        P.PROJECT_ASSIGN_SCHOOL,
        P.STRATEGIC_PRIORITIES_VIEW,
        P.MILESTONES_ALLOCATE,
        P.MILESTONES_VIEW_PROGRESS,
    ],
    EdifyRole.CCEO: [
        # The CCEO is the primary cluster-assigning field role. Not CLUSTER_OVERRIDE.
        P.SCHOOL_VIEW,
        P.SCHOOL_DIRECTORY_VIEW,
        P.CLUSTER_VIEW,
        P.CLUSTER_ASSIGN,
        P.SSA_VIEW,
        P.PLANNING_VIEW,
        P.PLANNING_CREATE,
        P.MANUAL_ACTIVITY_CREATE,
        P.ACTIVITY_ASSIGN,
        P.ACTIVITY_COMPLETE,
        P.ACTIVITY_CATALOGUE_VIEW,
        P.EVIDENCE_REVIEW,
        P.PARTNER_VIEW,
        # CCEO approves the fund requests of the staff they supervise, then
        # submits their own consolidated monthly request up to the PL.
        P.BUDGET_VIEW_DETAIL,
        P.BUDGET_APPROVE,
        P.ANALYTICS_VIEW,
        P.RECRUITMENT_INTELLIGENCE_VIEW,
        P.BUDGET_INTELLIGENCE_VIEW,  # own planned/funded activities view
        # CCEO works the operational school directory, including project assignment.
        P.PROJECT_ASSIGN_SCHOOL,
        P.STRATEGIC_PRIORITIES_VIEW,
        P.MILESTONES_VIEW_PROGRESS,
    ],
    EdifyRole.IMPACT_ASSESSMENT: [
        # §5 — authorized non-school programme activities.
        P.MANUAL_ACTIVITY_CREATE,
        # Training manuals and presentations are IA's; organisational policy
        # is not.
        P.UPLOADS_VIEW,
        P.TRAINING_RESOURCES_CREATE,
        P.TRAINING_RESOURCES_PUBLISH,
        P.SCHOOL_VIEW,
        P.SCHOOL_DIRECTORY_VIEW,
        P.SCHOOL_UPLOAD,
        P.SCHOOL_RESOLVE_DUPLICATE,
        P.CLUSTER_VIEW,
        P.PLANNING_RECALC,
        P.SSA_VIEW,
        P.SSA_UPLOAD,
        P.EVIDENCE_REVIEW,
        P.IA_VERIFY,
        P.ACTIVITY_CATALOGUE_VIEW,
        P.ACTIVITY_CATALOGUE_MAP_INTERVENTIONS,
        P.PROJECT_CONFIGURE_PRIORITIES,
        # IA reads the country budget as part of verification (it sits in the
        # country_budget page set and the service's READ_ROLES); the matrix
        # previously recorded no budget right at all.
        P.BUDGET_VIEW_SUMMARY,
        P.ANALYTICS_VIEW,
        P.ACTIVITY_CATALOGUE_VIEW,
        P.EXPORT,
        P.RECRUITMENT_INTELLIGENCE_VIEW,
        P.PARTNER_VIEW,
        # Data-confidence + SSA-impact readiness lens (no decision review authority).
        P.LEADERSHIP_ENGINE_VIEW,
        # IA works the operational school directory, including project assignment.
        P.PROJECT_ASSIGN_SCHOOL,
        P.STRATEGIC_PRIORITIES_VIEW,
        P.MILESTONES_VIEW_PROGRESS,
    ],
    EdifyRole.PROGRAM_ACCOUNTANT: [
        # No SCHOOL_DIRECTORY_VIEW — finance/accountability only.
        P.SCHOOL_VIEW,
        P.PAYMENT_ACT,
        # Detail without summary was a modelling gap: the Accountant reads the
        # country budget page (READ_ROLES in country_budget_service) but the
        # matrix recorded no summary right. Summary is a subset of detail.
        P.BUDGET_VIEW_SUMMARY,
        P.BUDGET_VIEW_DETAIL,
        P.ANALYTICS_VIEW,
        P.EXPORT,
        # Finance-implication view only — no staff/partner decision authority.
        P.LEADERSHIP_ENGINE_VIEW,
        # Finance execution + accountability + finance-decision review.
        P.BUDGET_INTELLIGENCE_VIEW,
        P.BUDGET_DECISION_REVIEW,
        P.STRATEGIC_PRIORITIES_VIEW,
        P.MILESTONES_VIEW_PROGRESS,
    ],
    EdifyRole.HUMAN_RESOURCES: [
        # §5 — authorized non-school programme activities.
        P.MANUAL_ACTIVITY_CREATE,
        # Policies and organisational manuals are HR's to write, publish and
        # administer, including the audience, the acknowledgement rules and the
        # private comments people leave beside their answers.
        P.UPLOADS_VIEW,
        P.DOCUMENTS_CREATE,
        P.DOCUMENTS_REVIEW,
        P.DOCUMENTS_PUBLISH,
        P.DOCUMENTS_ARCHIVE,
        P.DOCUMENTS_MANAGE_AUDIENCE,
        P.POLICIES_MANAGE_ACKNOWLEDGEMENTS,
        P.POLICIES_REVIEW_COMMENTS,
        # People surfaces only — no SCHOOL_DIRECTORY_VIEW.
        P.STAFF_MANAGE,
        P.USER_MANAGE,
        P.ANALYTICS_VIEW,
        P.STAFF_PERFORMANCE_VIEW,
        P.LEAVE_PLANNER_VIEW,
        P.DAILY_DEBRIEF_VIEW,
        # Staff & HR decision board + review.
        P.LEADERSHIP_ENGINE_VIEW,
        P.LEADERSHIP_DECISION_REVIEW,
        P.STRATEGIC_PRIORITIES_VIEW,
        P.MILESTONES_VIEW_PROGRESS,
    ],
    EdifyRole.PROJECT_COORDINATOR: [
        # Explicitly granted directory access — assigns project schools.
        P.SCHOOL_VIEW,
        P.SCHOOL_DIRECTORY_VIEW,
        # Project eligibility IS an SSA judgement: evaluate_school_need()
        # admits a school only where its latest confirmed SSA is weak in one of
        # the project's target interventions. The coordinator was expected to
        # make that call against data they could not read.
        P.SSA_VIEW,
        P.PLANNING_VIEW,
        P.PLANNING_CREATE,
        P.MANUAL_ACTIVITY_CREATE,
        P.ACTIVITY_ASSIGN,
        P.ACTIVITY_CATALOGUE_VIEW,
        P.ACTIVITY_CATALOGUE_MANAGE_PROJECT_RULES,
        P.EVIDENCE_REVIEW,
        P.PROJECT_MANAGE,
        P.PROJECT_ASSIGN_SCHOOL,
        P.PARTNER_VIEW,
        P.ANALYTICS_VIEW,
        P.STRATEGIC_PRIORITIES_VIEW,
        P.MILESTONES_VIEW_PROGRESS,
    ],
    EdifyRole.PARTNER_ADMIN: [
        P.ACTIVITY_COMPLETE,
        P.PLANNING_VIEW,
        P.ACTIVITY_CATALOGUE_VIEW,
    ],
    EdifyRole.PARTNER_FIELD_OFFICER: [
        P.ACTIVITY_COMPLETE,
        P.PLANNING_VIEW,
        P.ACTIVITY_CATALOGUE_VIEW,
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
