"""The mandated end-to-end release journeys, as data rather than as prose.

The release readiness assessment claimed "1 of 22 mandated journeys has a real
test" with the twenty-two enumerated nowhere and the number checkable by
nobody. That is the same shape as a skipped test reporting green: a coverage
claim whose evidence cannot be reached.

So the journeys live here, with the steps the mandate names, and each one
either points at the test that walks it or says plainly that nothing does.
`test_release_journey_census` then holds the manifest to reality — every
pointer must resolve to a test that exists, and the covered count must match
the number this module declares. Neither can drift quietly.

A journey counts as covered only when ONE test walks the whole thing. Several
tests that each verify a step, with the seams between them faked, is exactly
the coverage this platform cannot rely on: either half passes while the join
is broken.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Journey:
    number: int
    title: str
    steps: tuple[str, ...]
    #: "module path:ClassName.test_method" for each test that walks the WHOLE
    #: journey. Empty means nothing does — never a partial-coverage pointer.
    covered_by: tuple[str, ...] = field(default=())
    #: Why it is uncovered, when the reason is not simply "not written yet".
    blocked_by: str = ""

    @property
    def covered(self) -> bool:
        return bool(self.covered_by)


JOURNEYS: tuple[Journey, ...] = (
    Journey(
        1,
        "Priority to verified performance",
        (
            "Publish priority",
            "IA distributes to PL",
            "PL distributes to self and CCEO",
            "Target appears",
            "Plan created",
            "Activity scheduled",
            "Evidence verified",
            "Salesforce confirmed",
            "Achievement updated",
            "Performance updated",
            "Drill-down reconciles",
        ),
        covered_by=(
            "apps.core.tests.test_journey_priority_to_performance:"
            "PriorityToVerifiedPerformanceJourneyTest."
            "test_steps_9_to_11_achievement_performance_and_drilldown_agree",
        ),
    ),
    Journey(
        2,
        "SSA to school improvement",
        (
            "IA confirms SSA",
            "Recommendation generated",
            "School prioritized",
            "Activity planned",
            "Budgeted",
            "Delivered",
            "Verified",
            "Follow-up SSA confirmed",
            "Impact measured",
            "Leadership view updated",
        ),
        covered_by=(
            "apps.core.tests.test_journey_ssa_improvement:"
            "SsaToImprovementJourneyTest."
            "test_a_school_that_improves_between_confirmed_assessments_is_measured",
        ),
    ),
    Journey(
        3,
        "Standard staff school visit",
        (
            "Plan",
            "Cost",
            "Schedule",
            "Fund request",
            "Approval",
            "Disbursement",
            "Start",
            "Evidence",
            "PL review",
            "IA verification",
            "Accountability",
            "Closure",
        ),
        covered_by=(
            "apps.core.tests.test_journey_school_visit:"
            "SchoolVisitSpineJourneyTest."
            "test_a_funded_visit_can_be_executed_verified_accounted_and_closed",
        ),
    ),
    Journey(
        4,
        "Cluster training",
        (
            "Eligible schools",
            "Scheduling",
            "Cost",
            "Attendance",
            "Evidence",
            "Verification",
            "Unique-school and participant analytics",
        ),
        covered_by=(
            "apps.core.tests.test_journey_cluster_training:"
            "ClusterTrainingJourneyTest."
            "test_two_trainings_count_twice_per_school_and_once_for_reach",
        ),
    ),
    Journey(
        5,
        "Partner assignment and payment",
        (
            "Assign",
            "Schedule or Return",
            "My Plan",
            "Start",
            "Evidence",
            "IA return or completion",
            "Salesforce ID",
            "Payment eligibility",
            "Accountant payment",
            "Partner tracking",
        ),
        covered_by=(
            "apps.core.tests.test_journey_partner_payment:"
            "PartnerAssignmentToPaymentJourneyTest."
            "test_partner_work_is_payable_only_once_ia_has_verified_it",
        ),
    ),
    Journey(
        6,
        "Special Project",
        (
            "IA maps SSA intervention",
            "Assigns Project Coordinator",
            "Staff adds eligible school",
            "Baseline captured",
            "Activity planned",
            "Costed",
            "Delivered",
            "IA verified",
            "Follow-up SSA",
            "Impact calculated",
        ),
        covered_by=(
            "apps.core.tests.test_journey_special_project:"
            "SpecialProjectJourneyTest.test_the_whole_special_project_in_order",
        ),
    ),
    Journey(
        7,
        "Fund overspending and reimbursement",
        (
            "Advance",
            "Actual spend exceeds advance",
            "Accountability",
            "Reimbursement request",
            "Approval",
            "Payment",
            "Final reconciliation",
        ),
        covered_by=(
            "apps.core.tests.test_journey_overspend_reimbursement:"
            "OverspendReimbursementJourneyTest."
            "test_an_overspend_is_reimbursed_and_the_advance_still_reconciles",
        ),
    ),
    Journey(
        8,
        "Activity canceled after disbursement",
        (
            "Cancellation",
            "Planned output reversal",
            "Unused balance",
            "Accountability",
            "Recovery",
            "No achievement",
        ),
        covered_by=(
            "apps.core.tests.test_journey_cancel_after_disbursement:"
            "CancelAfterDisbursementJourneyTest."
            "test_cancelling_funded_work_keeps_the_money_and_drops_the_achievement",
        ),
    ),
    Journey(
        9,
        "Leave and temporary coverage",
        (
            "Leave request",
            "Approval",
            "Calendar block",
            "Access transfer",
            "To-Do transfer",
            "Target rephasing",
            "Return",
            "Access restoration",
        ),
        covered_by=(
            "apps.core.tests.test_journey_leave_coverage:"
            "LeaveCoverageJourneyTest."
            "test_covered_access_arrives_with_the_leave_and_leaves_with_it",
        ),
    ),
    Journey(
        10,
        "Quarterly Performance Conversation",
        (
            "HR unlocks",
            "Employee evaluates",
            "Manager evaluates",
            "Automatic values stay read-only",
            "HR oversight",
            "Close",
            "Snapshot lock",
        ),
        covered_by=(
            "apps.core.tests.test_journey_quarterly_conversation:"
            "QuarterlyConversationJourneyTest."
            "test_the_whole_conversation_in_order",
        ),
    ),
    Journey(
        11,
        "Professional Development",
        (
            "Request",
            "Manager review",
            "HR review",
            "Financial approval",
            "Completion",
            "Evidence",
            "Accounting",
            "Impact review",
        ),
        covered_by=(
            "apps.core.tests.test_journey_professional_development:"
            "ProfessionalDevelopmentJourneyTest."
            "test_a_funded_request_commits_against_the_envelope_when_submitted",
        ),
    ),
    Journey(
        12,
        "Policy lifecycle",
        (
            "Upload",
            "Review",
            "Return",
            "Approval",
            "Publication",
            "Employee acknowledgment",
            "Reminder",
            "Superseding version",
        ),
        covered_by=(
            "apps.core.tests.test_journey_policy_lifecycle:"
            "PolicyLifecycleJourneyTest."
            "test_a_material_new_version_obliges_the_person_who_agreed_to_the_old_one",
        ),
    ),
    Journey(
        13,
        "PIP",
        (
            "Concern",
            "Verified context",
            "Manager proposal",
            "HR fairness review",
            "Employee discussion",
            "Check-ins",
            "Support",
            "Outcome",
            "Appeal",
        ),
        covered_by=(
            "apps.core.tests.test_journey_pip:"
            "PipJourneyTest.test_a_manager_proposes_and_only_hr_authorises",
        ),
    ),
    Journey(
        14,
        "Team Oversight and Send School to",
        (
            "CCEO school appears under team",
            "Not in PL personal portfolio",
            "Urgent school identified",
            "PL sends school",
            "CCEO accepts and plans",
            "Team Oversight updates",
            "Ownership remains correct",
        ),
        covered_by=(
            "apps.core.tests.test_journey_team_oversight:"
            "TeamOversightJourneyTest."
            "test_delegating_an_urgent_school_never_transfers_its_ownership",
        ),
    ),
    Journey(
        15,
        "Financial Health",
        (
            "SSA weakness",
            "BT recommendation",
            "Training",
            "Verification",
            "Practice adoption",
            "Follow-up",
            "Next SSA",
        ),
        covered_by=(
            "apps.business_transformation.test_journeys_school_support:"
            "FinancialHealthJourneyTest."
            "test_the_whole_financial_health_chain_in_order",
        ),
    ),
    Journey(
        16,
        "Government Requirements",
        (
            "SSA weakness",
            "Requirement assessment",
            "Registration, tax, or NSSF support",
            "Evidence",
            "Verification",
            "Status update",
            "Expiry reminder",
        ),
        covered_by=(
            "apps.business_transformation.test_journeys_school_support:"
            "GovernmentRequirementsJourneyTest."
            "test_the_whole_government_requirements_chain_in_order",
        ),
    ),
    Journey(
        17,
        "Loan",
        (
            "Funding Facility",
            "MFI loan entry",
            "Enrolment",
            "Purpose",
            "Disbursement",
            "BT Salesforce confirmation",
            "IA validation",
            "Repayment",
            "Loan-use verification",
            "Impact",
            "Geographic analytics",
        ),
        covered_by=(
            "apps.business_transformation.test_journey_loan:"
            "LoanJourneyTest.test_the_whole_loan_in_order",
        ),
    ),
    Journey(
        18,
        "Repeat borrower and student reach",
        (
            "Second loan",
            "Loan count increases",
            "Unique school does not duplicate",
            "Student reach does not duplicate",
            "Loan history remains correct",
        ),
        covered_by=(
            "apps.core.tests.test_journey_repeat_borrower:"
            "RepeatBorrowerJourneyTest."
            "test_a_second_loan_to_one_school_counts_twice_but_the_school_once",
        ),
    ),
    Journey(
        19,
        "Cross-role security",
        (
            "Attempt unauthorized access for every sensitive workflow",
            "All attempts must fail closed",
        ),
        covered_by=(
            "apps.core.tests.test_journey_cross_role_security:"
            "CrossRoleSecurityJourneyTest."
            "test_every_sensitive_workflow_refuses_every_role_that_should_not_hold_it",
        ),
    ),
    Journey(
        20,
        "Offline field activity",
        (
            "Cache work",
            "Lose connection",
            "Start",
            "Capture evidence",
            "Close app",
            "Reopen",
            "Restore connection",
            "Sync",
            "No duplicate",
        ),
        blocked_by=(
            "FE-01: offline field operation does not exist. There is no "
            "IndexedDB queue, no replay and no server-side idempotency key, so "
            "there is no behaviour to walk. This journey cannot be covered by a "
            "test until the capability is built."
        ),
    ),
    Journey(
        21,
        "Integration outage",
        (
            "Internal action succeeds",
            "External system fails",
            "Exception appears",
            "Retry succeeds",
            "No duplicate",
        ),
        blocked_by=(
            "INTG-01: no Salesforce, NetSuite or MFI transport exists. There is "
            "no outward call to fail, so 'external system fails' and 'retry "
            "succeeds' have nothing to exercise."
        ),
    ),
    Journey(
        22,
        "Financial-year rollover",
        (
            "Close September",
            "Lock history",
            "Open October",
            "Preserve multi-year loans",
            "Carry approved obligations",
            "Generate new draft planning",
            "Historical reports remain unchanged",
        ),
        covered_by=(
            "apps.core.tests.test_journey_fy_rollover:"
            "FiscalYearRolloverJourneyTest."
            "test_the_year_closes_without_changing_what_the_old_year_reports",
        ),
    ),
)


def covered_journeys() -> tuple[Journey, ...]:
    return tuple(j for j in JOURNEYS if j.covered)


def uncovered_journeys() -> tuple[Journey, ...]:
    return tuple(j for j in JOURNEYS if not j.covered)


def blocked_journeys() -> tuple[Journey, ...]:
    """Uncovered because the capability they walk was never built."""
    return tuple(j for j in JOURNEYS if not j.covered and j.blocked_by)
