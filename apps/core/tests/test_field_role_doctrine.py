"""The field-execution role doctrine, as executable contract.

Four roles carry the operational workload — CCEO, Program Lead, Project
Coordinator, Program Accountant. Each has a doctrine: things it must be able to
do, and things it must never be able to do. Those rules were prose scattered
across comments; here they are assertions, so a future change that violates one
fails the build instead of shipping.

A failure here is a role-correctness regression, not a cosmetic one.
"""

from __future__ import annotations

from django.test import TestCase

from apps.core.navigation import PAGE_PERMISSIONS
from apps.core.rbac import EdifyRole, Permission, permissions_for_role


CCEO = EdifyRole.CCEO
PL = EdifyRole.COUNTRY_PROGRAM_LEAD
PC = EdifyRole.PROJECT_COORDINATOR
ACCT = EdifyRole.PROGRAM_ACCOUNTANT


def _perms(role):
    return set(permissions_for_role(role))


class CceoDoctrine(TestCase):
    """The CCEO is the primary school-support executor."""

    def test_can_execute_the_field_workflow(self):
        held = _perms(CCEO)
        for needed in (
            Permission.SCHOOL_VIEW,          # see assigned schools
            Permission.SCHOOL_DIRECTORY_VIEW,  # work the operational directory
            Permission.SSA_VIEW,             # read school SSA need
            Permission.CLUSTER_VIEW,
            Permission.CLUSTER_ASSIGN,       # add schools to clusters
            Permission.PLANNING_VIEW,
            Permission.PLANNING_CREATE,      # plan support
            Permission.ACTIVITY_ASSIGN,      # assign to partners
            Permission.ACTIVITY_COMPLETE,    # execute
            Permission.EVIDENCE_REVIEW,
            Permission.PARTNER_VIEW,         # supervise partners
            Permission.PROJECT_ASSIGN_SCHOOL,  # add eligible schools to projects
            Permission.BUDGET_VIEW_DETAIL,
        ):
            self.assertIn(needed.value, held, f"CCEO must hold {needed.value}")

    def test_holds_no_leadership_or_finance_control(self):
        held = _perms(CCEO)
        for forbidden in (
            Permission.PAYMENT_ACT,             # cannot disburse
            Permission.COST_SETTINGS_MANAGE,    # cannot change the rate card
            Permission.COUNTRY_BUDGET_SUBMIT,   # cannot touch country budgets
            Permission.COUNTRY_BUDGET_APPROVE,
            Permission.IA_VERIFY,               # cannot verify its own work
            Permission.SSA_UPLOAD,
            Permission.STAFF_MANAGE,
            Permission.USER_MANAGE,
            Permission.SYSTEM_ADMIN,
            Permission.PROJECT_MANAGE,          # cannot own projects
        ):
            self.assertNotIn(
                forbidden.value, held, f"CCEO must not hold {forbidden.value}"
            )

    def test_cannot_reach_leadership_or_finance_pages(self):
        for page in (
            "country_budget",
            "cost_settings",
            "disbursements",
            "finance_partner_payments",
            "escalations",
            "cd_analytics",
            "pl_analytics",
            "decision_intelligence",
            "users",
        ):
            self.assertNotIn(
                "CCEO",
                PAGE_PERMISSIONS.get(page, set()),
                f"CCEO must not reach '{page}'",
            )


class ProgramLeadDoctrine(TestCase):
    """The PL is both a field executor and a team supervisor."""

    def test_can_execute_and_supervise(self):
        held = _perms(PL)
        for needed in (
            Permission.SCHOOL_VIEW,
            Permission.SCHOOL_DIRECTORY_VIEW,
            Permission.PLANNING_CREATE,      # own field work
            Permission.ACTIVITY_ASSIGN,
            Permission.ACTIVITY_COMPLETE,
            Permission.BUDGET_APPROVE,       # approves supervised CCEO requests
            Permission.EVIDENCE_REVIEW,
            Permission.STAFF_PERFORMANCE_VIEW,  # team targets
            Permission.SSA_VIEW,
            Permission.PARTNER_VIEW,
        ):
            self.assertIn(needed.value, held, f"PL must hold {needed.value}")

    def test_holds_no_country_or_finance_control(self):
        held = _perms(PL)
        for forbidden in (
            Permission.PAYMENT_ACT,            # cannot disburse
            Permission.IA_VERIFY,              # cannot IA-verify
            Permission.COST_SETTINGS_MANAGE,   # cannot change prices
            Permission.COUNTRY_BUDGET_SUBMIT,  # cannot override country budgets
            Permission.COUNTRY_BUDGET_APPROVE,
            Permission.FUND_REQUEST_APPROVE_ESCALATED,  # escalation is the CD's
            Permission.SYSTEM_ADMIN,
        ):
            self.assertNotIn(
                forbidden.value, held, f"PL must not hold {forbidden.value}"
            )

    def test_cannot_reach_country_or_finance_execution_pages(self):
        for page in (
            "country_budget",
            "cost_settings",
            "disbursements",
            "finance_partner_payments",
            "cd_analytics",
            "escalations",
        ):
            self.assertNotIn(
                "PL", PAGE_PERMISSIONS.get(page, set()), f"PL must not reach '{page}'"
            )


class ProjectCoordinatorDoctrine(TestCase):
    """The PC owns authorized Special Projects — and nothing else."""

    def test_can_run_a_project_end_to_end(self):
        held = _perms(PC)
        for needed in (
            Permission.PROJECT_MANAGE,
            Permission.PROJECT_ASSIGN_SCHOOL,
            Permission.PLANNING_VIEW,
            Permission.PLANNING_CREATE,      # project planning
            Permission.ACTIVITY_ASSIGN,      # assign project work to partners
            Permission.EVIDENCE_REVIEW,      # monitor project evidence
            Permission.PARTNER_VIEW,
            Permission.SCHOOL_VIEW,
            Permission.SCHOOL_DIRECTORY_VIEW,  # assigns project schools
            Permission.ANALYTICS_VIEW,
            # Project eligibility is defined by SSA need and the coordinator
            # must be able to read the interventions their project targets.
            Permission.SSA_VIEW,
        ):
            self.assertIn(needed.value, held, f"PC must hold {needed.value}")

    def test_holds_no_country_finance_or_verification_control(self):
        held = _perms(PC)
        for forbidden in (
            Permission.BUDGET_APPROVE,        # cannot approve country-wide funds
            Permission.PAYMENT_ACT,           # cannot disburse
            Permission.IA_VERIFY,             # cannot IA-verify
            Permission.COST_SETTINGS_MANAGE,
            Permission.COUNTRY_BUDGET_SUBMIT,
            Permission.COUNTRY_BUDGET_APPROVE,
            Permission.SSA_UPLOAD,
            Permission.STAFF_MANAGE,
            Permission.SYSTEM_ADMIN,
        ):
            self.assertNotIn(
                forbidden.value, held, f"PC must not hold {forbidden.value}"
            )

    def test_cannot_reach_leadership_or_finance_pages(self):
        for page in (
            "country_budget",
            "cost_settings",
            "disbursements",
            "cd_analytics",
            "pl_analytics",
            "team_targets",
            "escalations",
        ):
            self.assertNotIn(
                "PROJECT_COORDINATOR",
                PAGE_PERMISSIONS.get(page, set()),
                f"PC must not reach '{page}'",
            )


class ProgramAccountantDoctrine(TestCase):
    """The Accountant owns finance execution and clearance — not programme
    judgement."""

    def test_can_run_finance_end_to_end(self):
        held = _perms(ACCT)
        for needed in (
            Permission.PAYMENT_ACT,
            Permission.BUDGET_VIEW_DETAIL,
            Permission.BUDGET_VIEW_SUMMARY,
            Permission.ANALYTICS_VIEW,
            Permission.EXPORT,
        ):
            self.assertIn(needed.value, held, f"Accountant must hold {needed.value}")

    def test_holds_no_programme_authority(self):
        """The central separation: money execution must never carry programme
        verification."""
        held = _perms(ACCT)
        for forbidden in (
            Permission.IA_VERIFY,           # never verifies activity quality
            Permission.PLANNING_CREATE,     # never plans field activities
            Permission.ACTIVITY_ASSIGN,     # never changes school assignments
            Permission.ACTIVITY_COMPLETE,
            Permission.SSA_UPLOAD,          # never edits SSA
            Permission.SCHOOL_EDIT,
            Permission.COST_SETTINGS_MANAGE,  # never changes prices
            Permission.CLUSTER_ASSIGN,
            Permission.SCHOOL_DIRECTORY_VIEW,  # finance, not an operational list
            Permission.COUNTRY_BUDGET_SUBMIT,
            Permission.COUNTRY_BUDGET_APPROVE,
        ):
            self.assertNotIn(
                forbidden.value, held, f"Accountant must not hold {forbidden.value}"
            )

    def test_cannot_reach_programme_execution_pages(self):
        for page in (
            "planning",
            "my_plan",
            "core_schools",
            "ia_verification_queue",
            "cost_settings",
            "school_directory",
            "team_targets",
        ):
            self.assertNotIn(
                "ACCOUNTANT",
                PAGE_PERMISSIONS.get(page, set()),
                f"Accountant must not reach '{page}'",
            )


class SeparationOfDuties(TestCase):
    """Cross-role invariants — the ones that keep money and judgement apart."""

    def test_only_impact_assessment_verifies(self):
        holders = {
            role.value
            for role in EdifyRole
            if Permission.IA_VERIFY.value in permissions_for_role(role)
        }
        self.assertEqual(
            holders,
            {EdifyRole.IMPACT_ASSESSMENT.value, EdifyRole.ADMIN.value},
            "activity verification is Impact Assessment's authority alone",
        )

    def test_only_the_accountant_moves_money(self):
        holders = {
            role.value
            for role in EdifyRole
            if Permission.PAYMENT_ACT.value in permissions_for_role(role)
        }
        self.assertEqual(
            holders,
            {EdifyRole.PROGRAM_ACCOUNTANT.value, EdifyRole.ADMIN.value},
            "disbursement is the Accountant's authority alone",
        )

    def test_field_approval_belongs_to_the_field_chain(self):
        """budget.approve is the CCEO→PL chain. Nobody outside it, and in
        particular no finance or coordinator role, may hold it."""
        holders = {
            role.value
            for role in EdifyRole
            if Permission.BUDGET_APPROVE.value in permissions_for_role(role)
        }
        self.assertEqual(
            holders,
            {
                EdifyRole.CCEO.value,
                EdifyRole.COUNTRY_PROGRAM_LEAD.value,
                EdifyRole.ADMIN.value,
            },
        )

    def test_rate_card_is_owned_by_one_role(self):
        holders = {
            role.value
            for role in EdifyRole
            if Permission.COST_SETTINGS_MANAGE.value in permissions_for_role(role)
        }
        self.assertEqual(
            holders,
            {EdifyRole.COUNTRY_DIRECTOR.value, EdifyRole.ADMIN.value},
            "no field role may invent costs",
        )

    def test_no_field_role_holds_country_budget_authority(self):
        for role in (CCEO, PL, PC, ACCT):
            held = _perms(role)
            self.assertNotIn(Permission.COUNTRY_BUDGET_SUBMIT.value, held)
            self.assertNotIn(Permission.COUNTRY_BUDGET_APPROVE.value, held)
