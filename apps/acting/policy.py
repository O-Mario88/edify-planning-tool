"""What an acting appointment delegates, and what stays where it was.

One entry per acting role. An entry names who may appoint whom, the seat the
appointment delegates, and the difference between the acting capacity and
the role it acts in:

    delegated     the operational capability set of the acting role: reading
                  the seat's plans, execution, calendar, schools, partners,
                  projects, priorities, performance and staff activity, and
                  the follow-up controls a leader works them with
    withheld      what an appointment never carries: money decisions, people
                  decisions, user, role and permission administration,
                  governed configuration, and appointing acting leaders

Owner, 2026-10-07, on what was withheld: "They should not have all the
privilages. Their major task is manage and follow up with the team members."
That sentence is the test for anything added here. An acting leader reads
the seat and follows up with its people; a decision about money, a person's
record, a partner organisation or a governed value stays with the leader who
appointed them. Where a page holds both, the appointment names the follow-up
actions and leaves the rest (``follow_up_views``, ``withheld_views``).

Nothing here is a second permission system. ``apps.core.rbac`` and
``apps.core.navigation.PAGE_PERMISSIONS`` still decide what a role holds; an
entry only subtracts from the acting role's row, and the principal is then
judged by the same gates as everyone else (``apps.core.acting``).

Every permission key and page the acting role holds beyond the appointee's
own role is named below as delegated or withheld, and
``apps.acting.tests.test_policy`` fails when one is not: a page added to the
Country Director tomorrow is not silently an Acting Country Director's.

A further acting role is another entry here and a seat resolver in
``apps.core.scoping``; nothing else is rebuilt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from apps.core import acting as core
from apps.core.acting import SCOPE_COUNTRY, SCOPE_PL_TEAM
from apps.core.rbac import EdifyRole
from apps.core.rbac import Permission as P


class Authority(str, Enum):
    """Decisions an appointment leaves with the substantive leader.

    These are decided inside services by the reporting line or by a role
    name rather than by a permission key, so the services ask
    ``apps.core.acting.withholds`` by these names.
    """

    #: Approving, returning or submitting a money request for the seat.
    FUND_DECISION = core.FUND_DECISION
    #: Approving or declining leave, and arranging its cover.
    LEAVE_DECISION = core.LEAVE_DECISION
    #: Conducting a performance review, a recovery plan or a development
    #: approval: the permanent reporting line's.
    PEOPLE_DECISION = core.PEOPLE_DECISION
    #: Setting or distributing targets and milestones.
    TARGET_ALLOCATION = core.TARGET_ALLOCATION
    #: Accounts, roles, reporting lines and staff records.
    STAFF_ADMINISTRATION = core.STAFF_ADMINISTRATION
    #: Appointing, changing or cancelling an acting leader.
    ACTING_APPOINTMENT = core.ACTING_APPOINTMENT
    #: Authoring or publishing governed values: the rate card, the planning
    #: policy, the master priorities, the catalogue, policy documents.
    GOVERNANCE = core.GOVERNANCE
    #: Verifying delivered work, and deciding anything about one's own work.
    VERIFICATION = core.VERIFICATION


ALL_AUTHORITIES = frozenset(a.value for a in Authority)

# Pages every signed-in person works their own account from. An acting
# capacity may always write on these: reading a notification or sending a
# message is not an exercise of the seat.
COMMON_WRITE_PAGES = frozenset(
    {
        "dashboard",
        "todos",
        "my_actions",
        "messages",
        "notifications",
        "settings",
        "help",
        "report_problem",
        "search",
        "calendar",
    }
)

# A person's own money, leave, targets and performance are worked in their
# own role. Several of these pages route by the role in use (a Programme
# Lead's advance goes to the Country Director, a CCEO's to their Lead), so
# in the acting capacity they would file the appointee's own request up the
# wrong line. They are withheld from every acting capacity; the account menu
# switches back to the person's own role for them.
PERSONAL_PAGES = frozenset(
    {
        "fund_requests",
        "weekly_fund_request",
        "monthly_budget",
        "my_budget",
        "my_target",
        "my_performance",
        "my_professional_development",
        "leave_requests",
        "leave_coverage",
        "personal_time_off",
        "performance_conversations",
        "performance_development",
        "performance_documents",
        "performance_values",
        "extra_work",
        "staff_pulse",
    }
)

# Decisions about money and people, on pages the acting role shares with the
# appointee's own.
DECISION_PAGES = frozenset(
    {
        "fund_approvals",
        "leave_approvals",
        "performance_reviews",
        "cpd_learning",
    }
)


@dataclass(frozen=True)
class ActingRole:
    """One kind of acting appointment."""

    key: str
    #: The role whose operational capability set the appointee receives.
    acting_role: EdifyRole
    #: The permanent role an appointee must hold.
    appointee_role: EdifyRole
    #: The permanent role that may appoint, in their own capacity.
    appointer_role: EdifyRole
    scope_type: str
    label: str
    short_label: str
    scope_label: str
    #: Pages the acting role holds beyond the appointee's, read and worked.
    delegated_write_pages: frozenset = field(default_factory=frozenset)
    #: Pages the acting role holds beyond the appointee's, read only.
    delegated_read_pages: frozenset = field(default_factory=frozenset)
    #: Pages the acting capacity never opens.
    withheld_pages: frozenset = field(default_factory=frozenset)
    #: Permission keys the acting role holds beyond the appointee's, kept.
    delegated_permissions: frozenset = field(default_factory=frozenset)
    #: Permission keys the acting capacity never holds.
    withheld_permissions: frozenset = field(default_factory=frozenset)
    withheld_authorities: frozenset = ALL_AUTHORITIES
    #: Whether a page the appointee already works in their own role stays
    #: writable. True where the acting role reaches no further than the
    #: appointee on those pages (a Programme Lead is read-only at an
    #: officer's schools); False where it reaches the whole seat (a Country
    #: Director writes across the country).
    keeps_own_page_writes: bool = True
    #: The only actions this capacity may send a change to, by view name,
    #: beyond a person's own account pages. Set where the acting role writes
    #: across the whole seat: every page is then read, and the appointment
    #: carries the follow-up a leader sends from it and nothing else on it.
    #: None where pages decide (``may_write``).
    follow_up_views: frozenset | None = None
    #: Actions refused on a page that is otherwise workable: a decision that
    #: sits beside the follow-up on the same page.
    withheld_views: frozenset = field(default_factory=frozenset)

    @property
    def acting_role_value(self) -> str:
        return self.acting_role.value

    def may_write(self, page: str) -> bool:
        """Whether the acting capacity may change anything on this page.

        Where ``follow_up_views`` is set, a page is workable only as a
        person's own account page; the seat's pages take the named
        follow-up actions and no other change (``may_send``).
        """
        if page in self.withheld_pages:
            return False
        if page in COMMON_WRITE_PAGES:
            return True
        if self.follow_up_views is not None:
            return False
        if page in self.delegated_write_pages:
            return True
        if page in self.delegated_read_pages:
            return False
        return self.keeps_own_page_writes

    def may_send(self, view_name: str, pages) -> bool:
        """Whether the acting capacity may send a change to this action.

        ``pages`` are the page permissions on the route. This is the whole
        rule the middleware applies to a page route.
        """
        if view_name in self.withheld_views:
            return False
        if any(page in self.withheld_pages for page in pages):
            return False
        if self.follow_up_views is not None and view_name in self.follow_up_views:
            return True
        return any(self.may_write(page) for page in pages)

    def withheld_permission_values(self) -> frozenset:
        return frozenset(p.value for p in self.withheld_permissions)


# ── Acting Programme Lead ───────────────────────────────────────────────────
# A CCEO, appointed by their own Programme Lead, for that Lead's whole team
# including the Lead.
ACTING_PROGRAM_LEAD = ActingRole(
    key="acting_pl",
    acting_role=EdifyRole.COUNTRY_PROGRAM_LEAD,
    appointee_role=EdifyRole.CCEO,
    appointer_role=EdifyRole.COUNTRY_PROGRAM_LEAD,
    scope_type=SCOPE_PL_TEAM,
    label="Acting Program Lead",
    short_label="Acting PL",
    scope_label="PL team",
    delegated_write_pages=frozenset(
        {
            # Team oversight and its follow-up ("Send to …").
            "my_team",
            "actions_sent",
            "planning_monitor",
            "team_planning_oversight",
            "cluster_oversight",
            "core_schools_oversight",
            "programme_rollout",
            # Execution: reviewing the team's completed work.
            "pl_review_queue",
            "quality_checks",
            # Leading the team day to day.
            "team_guidance",
            "team_coaching",
            "cce_training_feedback",
            # Staff activity, and the follow-up a leader sends from it.
            "staff_activity",
        }
    ),
    delegated_read_pages=frozenset(
        {
            "pl_analytics",
            "core_school_health",
            "staff",
            "staff_directory",
            "team_targets",
            "team_availability",
            "leave_tracker",
            "policy_compliance",
            "ssa_mapping",
            "strategic_priorities",
        }
    ),
    withheld_pages=frozenset(
        {
            *PERSONAL_PAGES,
            *DECISION_PAGES,
            "recovery_plans",
            "team_target_distribution",
        }
    ),
    delegated_permissions=frozenset(
        {
            P.SSA_ACTIVITY_MAPPING_VIEW,
            # Answering a withdrawal an officer of the team has asked for.
            P.PARTNER_WITHDRAWAL_REVIEW,
            P.EXPORT,
            P.STAFF_PERFORMANCE_VIEW,
        }
    ),
    withheld_permissions=frozenset(
        {
            P.MILESTONES_ALLOCATE,
            # Neither is managing or following up the team: editing a
            # school's record, and stopping new work reaching a partner.
            P.SCHOOL_EDIT,
            P.PARTNER_HOLD,
        }
    ),
    withheld_views=frozenset(
        {
            # Granting a partner more activities at a school is a decision
            # about the partner, made from a page the team's work is on.
            "partner_allowance_grant_action",
            # The Country Ceiling is Admin's and Impact Assessment's.
            "training_country_ceiling_set_view",
            "training_country_ceiling_edit_view",
            "training_country_ceiling_remove_view",
        }
    ),
    keeps_own_page_writes=True,
)


# ── Acting Country Director ─────────────────────────────────────────────────
# A Programme Lead, appointed by the Country Director of their country, for
# the country.
ACTING_COUNTRY_DIRECTOR = ActingRole(
    key="acting_cd",
    acting_role=EdifyRole.COUNTRY_DIRECTOR,
    appointee_role=EdifyRole.COUNTRY_PROGRAM_LEAD,
    appointer_role=EdifyRole.COUNTRY_DIRECTOR,
    scope_type=SCOPE_COUNTRY,
    label="Acting Country Director",
    short_label="Acting CD",
    scope_label="Country",
    delegated_read_pages=frozenset(
        {
            # Country oversight. What a director sends from it to follow up
            # is named in `follow_up_views` below.
            "country_planning_oversight",
            "cd_analytics",
            "country_map",
            "coverage",
            "closure_impact",
            "decision_intelligence",
            "recruitment",
            "reports",
            "impact_reports",
            # Country priorities and targets, read. Distributing them is a
            # withheld permission and the page takes no change from here.
            "target_distribution",
            # Impact Assessment's reporting, read as the director reads it.
            "ia_dashboard",
            "ia_framework",
            "ia_learning",
            "ia_samples",
            "ia_school_evidence",
            "ia_stories",
            "ia_attribution",
            "ia_verification_analytics",
        }
    ),
    withheld_pages=frozenset(
        {
            *PERSONAL_PAGES,
            *DECISION_PAGES,
            # Money: the rate card, the country envelope and its requests.
            "cost_settings",
            "country_budget",
            "consolidated_fund_allocation",
            "monthly_request",
            # People and accounts.
            "users",
            "staff_setup_queue",
            "hr_today",
            "hr_analytics",
            "workforce_planning",
            # Governed configuration and publishing.
            "fy_planning_policy",
            "analytics_publishing",
            "uploads",
            # Verification work is Impact Assessment's.
            "ia_verification_queue",
            "ia_review_workspace",
            # Lending is a governed portfolio of its own.
            "ia_lending_evidence",
            "loans",
            "business_transformation",
            "business_transformation_reports",
            # A director's own field pages, which the appointee has as a
            # Programme Lead in their own role.
            "my_plan",
        }
    ),
    delegated_permissions=frozenset(
        {
            P.UPLOADS_VIEW,
            P.BUDGET_VIEW_SUMMARY,
            P.RATE_CARD_REFERENCE_VIEW,
            P.ACTIVITY_REFERENCE_COST_VIEW,
            P.STRATEGIC_RESERVE_VIEW,
            P.LEADERSHIP_ENGINE_VIEW,
            P.BUDGET_INTELLIGENCE_VIEW,
            P.MILESTONES_VIEW_PROGRESS,
            P.PARTNER_MONITORING_COUNTRY,
        }
    ),
    withheld_permissions=frozenset(
        {
            # Money decisions and the rate card.
            P.COUNTRY_BUDGET_SUBMIT,
            P.FUND_REQUEST_APPROVE_ESCALATED,
            P.COST_SETTINGS_MANAGE,
            P.RATE_CARD_REFERENCE_MANAGE,
            P.RATE_CARD_OPERATIONAL_MANAGE,
            P.ACTIVITY_COST_APPROVE,
            P.STRATEGIC_RESERVE_MANAGE,
            P.COST_AMENDMENT_APPROVE,
            P.BUDGET_DECISION_REVIEW,
            # People, accounts and partner logins.
            P.STAFF_MANAGE,
            P.USER_MANAGE,
            P.PARTNER_USER_MANAGE,
            P.PARTNER_MANAGE,
            P.PARTNER_ORGANISATION_CREATE,
            P.PARTNER_ORGANISATION_EDIT,
            # Governed configuration.
            P.PLANNING_POLICY_MANAGE,
            P.PLANNING_RECALC,
            P.CLUSTER_OVERRIDE,
            P.CLUSTER_CATCHMENT_MANAGE,
            P.ACTIVITY_CATALOGUE_MANAGE,
            P.PROJECT_MANAGE,
            P.PROJECT_CONFIGURE_PRIORITIES,
            P.LEADERSHIP_DECISION_REVIEW,
            # Policy documents: authorship, publishing, private comments.
            P.DOCUMENTS_CREATE,
            P.DOCUMENTS_REVIEW,
            P.DOCUMENTS_PUBLISH,
            P.DOCUMENTS_MANAGE_AUDIENCE,
            P.POLICIES_REVIEW_COMMENTS,
            # Changes a Programme Lead makes for one team and a Director for
            # the whole country: schools, clusters, programme activities and
            # partner work. The appointee has them in their own role, for
            # their own team.
            P.SCHOOL_CREATE_SINGLE,
            P.SCHOOL_EDIT,
            P.SCHOOL_CLOSE,
            P.CLUSTER_ASSIGN,
            P.MANUAL_ACTIVITY_CREATE,
            P.PROJECT_ASSIGN_SCHOOL,
            P.PARTNER_ASSIGNMENT_WITHDRAW,
            P.PARTNER_WITHDRAWAL_REVIEW,
            P.PARTNER_HOLD,
            # The country master priorities and their targets.
            P.STRATEGIC_PRIORITIES_CREATE,
            P.STRATEGIC_PRIORITIES_EDIT,
            P.STRATEGIC_PRIORITIES_APPROVE,
            P.STRATEGIC_PRIORITIES_ALLOCATE,
            P.MILESTONES_DEFINE,
            P.MILESTONES_ALLOCATE,
            # The lending portfolio, as a whole.
            P.BUSINESS_TRANSFORMATION_VIEW,
            P.BUSINESS_TRANSFORMATION_CASE_MANAGE,
            P.BUSINESS_TRANSFORMATION_PORTFOLIO_VIEW,
            P.BUSINESS_TRANSFORMATION_SENSITIVE_VIEW,
            P.BUSINESS_TRANSFORMATION_MFI_MANAGE,
            P.BUSINESS_TRANSFORMATION_REFERRAL_MANAGE,
            P.BUSINESS_TRANSFORMATION_FACILITY_VIEW,
            P.BUSINESS_TRANSFORMATION_FACILITY_MANAGE,
            P.BUSINESS_TRANSFORMATION_FACILITY_APPROVE,
            P.BUSINESS_TRANSFORMATION_ALLOCATION_MANAGE,
            P.BUSINESS_TRANSFORMATION_PURPOSE_APPROVE,
            P.BUSINESS_TRANSFORMATION_AMENDMENT_APPROVE,
            P.BUSINESS_TRANSFORMATION_EXPORT,
        }
    ),
    # A Country Director writes across the whole country on the pages a
    # Programme Lead works for one team, so no page is workable: the
    # appointment carries these follow-up actions and nothing else.
    keeps_own_page_writes=False,
    withheld_views=frozenset(
        {
            # A country-wide event that blocks field planning is the
            # Director's to put on the calendar.
            "calendar_event_create_view",
        }
    ),
    follow_up_views=frozenset(
        {
            # Planning and execution: "Send to …" and the follow-ups a
            # director opens, answers and closes with a Lead.
            "country_planning_send_action_view",
            "team_planning_send_action_view",
            "planning_monitor_send_view",
            "follow_up_view",
            "follow_up_action_view",
            "followup_lead_action_view",
            # Partner work: asking the officer who holds it to act. Every
            # decision about the partner stays with the Director.
            "partner_oversight_send_action_view",
            # Staff activity: a follow-up sent to a person.
            "follow_up_create_view",
            # Raising and answering an escalation.
            "escalations_view",
        }
    ),
)


ACTING_ROLES: dict[str, ActingRole] = {
    ACTING_PROGRAM_LEAD.key: ACTING_PROGRAM_LEAD,
    ACTING_COUNTRY_DIRECTOR.key: ACTING_COUNTRY_DIRECTOR,
}

BY_ACTING_ROLE: dict[str, ActingRole] = {
    entry.acting_role_value: entry for entry in ACTING_ROLES.values()
}


def acting_role(key: str) -> ActingRole | None:
    """The entry for a policy key ("acting_pl") or an acting role's value."""
    return ACTING_ROLES.get(key) or BY_ACTING_ROLE.get(key)


def offered_by(role: str) -> ActingRole | None:
    """The acting appointment a permanent holder of ``role`` may make."""
    for entry in ACTING_ROLES.values():
        if entry.appointer_role.value == role:
            return entry
    return None


__all__ = [
    "ACTING_COUNTRY_DIRECTOR",
    "ACTING_PROGRAM_LEAD",
    "ACTING_ROLES",
    "ALL_AUTHORITIES",
    "Authority",
    "ActingRole",
    "COMMON_WRITE_PAGES",
    "DECISION_PAGES",
    "PERSONAL_PAGES",
    "acting_role",
    "offered_by",
]
