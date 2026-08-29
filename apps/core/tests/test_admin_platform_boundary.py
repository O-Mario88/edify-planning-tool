"""Regression contract for the Admin platform super-role.

Admin holds every application permission and may execute every role-gated
workflow EXCEPT reserved operational authorities: IA verification,
disbursement, field budget approval, governed loan execution, and scheduling
field work. Admin sees them and exercises none of them.

That boundary is the point. Admin was briefly given the full set while fixing a
real problem — the role was read-only and blocked ordinary administration — but
"not read-only" is about access, and these three are about authority. Holding
all of them lets one account approve a budget, disburse against it, and then
verify the activity it paid for, which is the entire control this platform's
audit chain exists to make meaningful.

It does not constrain the admin *person*: roles are per user and switched via
active_role, so an admin who is also a CCEO does field work as the CCEO.

Domain invariants still apply: state transitions, required evidence, audit
logging, and the global ban on deleting execution history are not
authorization restrictions and remain enforced.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from apps.core.permissions import RolePermissionService
from apps.core.rbac import (
    ADMIN_EXCLUDED_PERMISSIONS,
    ROLE_PERMISSIONS,
    EdifyRole,
    Permission,
)


def _user(role):
    return SimpleNamespace(active_role=role, user_id=f"super-{role.lower()}")


ADMIN = _user("Admin")


class AdminSuperRoleMatrixTests(SimpleTestCase):
    def test_admin_holds_every_permission_except_the_reserved_authorities(self):
        self.assertEqual(
            set(ROLE_PERMISSIONS[EdifyRole.ADMIN]),
            set(Permission) - ADMIN_EXCLUDED_PERMISSIONS,
        )

    def test_new_permissions_reach_admin_automatically(self):
        """The super-role must not need editing every time a permission is
        added — only the documented exclusions are deliberate."""
        missing = set(Permission) - set(ROLE_PERMISSIONS[EdifyRole.ADMIN])
        self.assertEqual(missing, set(ADMIN_EXCLUDED_PERMISSIONS))

    def test_the_reserved_authorities_are_exactly_the_separation_of_duties_set(self):
        self.assertEqual(
            ADMIN_EXCLUDED_PERMISSIONS,
            frozenset(
                {
                    Permission.IA_VERIFY,
                    Permission.PAYMENT_ACT,
                    Permission.BUDGET_APPROVE,
                    Permission.COUNTRY_BUDGET_SUBMIT,
                    Permission.COUNTRY_BUDGET_APPROVE,
                    Permission.FUND_REQUEST_APPROVE_ESCALATED,
                    Permission.RATE_CARD_REFERENCE_VIEW,
                    Permission.RATE_CARD_REFERENCE_MANAGE,
                    Permission.RATE_CARD_OPERATIONAL_MANAGE,
                    Permission.ACTIVITY_REFERENCE_COST_VIEW,
                    Permission.ACTIVITY_COST_APPROVE,
                    Permission.STRATEGIC_RESERVE_VIEW,
                    Permission.STRATEGIC_RESERVE_MANAGE,
                    Permission.STRATEGIC_RESERVE_APPROVE,
                    Permission.COST_AMENDMENT_APPROVE,
                    # Added 2026-08-29 by the release-readiness audit, on the
                    # mandate's own words: "RVP and Admin remain read-only for
                    # business values" (§18.1). `milestones.define` is what
                    # `_assert_master_editor` actually reads, and its refusal
                    # text already named the rule — "Master Priority figures
                    # are set by the Country Director and Impact Assessment" —
                    # while Admin held the permission by default and was
                    # ADMITTED by that guard when tested. A country target's
                    # figure, Core/Client split and allocation method feed
                    # distribution, planning, achievement and performance.
                    #
                    # The RVP holds it too and is deliberately NOT changed:
                    # apps/hr/priority_cascade.py has the RVP authoring
                    # strategy, so that half is CONFLICT-003 for the product
                    # owner rather than an audit's decision to take.
                    Permission.MILESTONES_DEFINE,
                    Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE,
                    Permission.BUSINESS_TRANSFORMATION_REPAYMENT_WRITE,
                    Permission.BUSINESS_TRANSFORMATION_PORTFOLIO_CERTIFY,
                    Permission.BUSINESS_TRANSFORMATION_SALESFORCE_CONFIRM,
                    Permission.BUSINESS_TRANSFORMATION_IA_VALIDATE,
                    Permission.BUSINESS_TRANSFORMATION_EXPORT,
                    Permission.BUSINESS_TRANSFORMATION_VIEW,
                    Permission.BUSINESS_TRANSFORMATION_PORTFOLIO_VIEW,
                    Permission.BUSINESS_TRANSFORMATION_SENSITIVE_VIEW,
                    Permission.BUSINESS_TRANSFORMATION_CASE_MANAGE,
                    Permission.BUSINESS_TRANSFORMATION_REFERRAL_MANAGE,
                    Permission.BUSINESS_TRANSFORMATION_SCHOOL_SUPPORT_MANAGE,
                    Permission.BUSINESS_TRANSFORMATION_MFI_MANAGE,
                    Permission.BUSINESS_TRANSFORMATION_MFI_MEMBER_MANAGE,
                    Permission.BUSINESS_TRANSFORMATION_FACILITY_VIEW,
                    Permission.BUSINESS_TRANSFORMATION_FACILITY_MANAGE,
                    Permission.BUSINESS_TRANSFORMATION_FACILITY_APPROVE,
                    Permission.BUSINESS_TRANSFORMATION_FACILITY_TRANSFER,
                    Permission.BUSINESS_TRANSFORMATION_ALLOCATION_MANAGE,
                    Permission.BUSINESS_TRANSFORMATION_DISBURSEMENT_WRITE,
                    Permission.BUSINESS_TRANSFORMATION_REPAYMENT_REVERSE,
                    Permission.BUSINESS_TRANSFORMATION_AMENDMENT_APPROVE,
                    Permission.BUSINESS_TRANSFORMATION_PURPOSE_REQUEST,
                    Permission.BUSINESS_TRANSFORMATION_PURPOSE_REVIEW,
                    Permission.BUSINESS_TRANSFORMATION_PURPOSE_DEFINE,
                    Permission.BUSINESS_TRANSFORMATION_PURPOSE_APPROVE,
                }
            ),
            "reserved operational actions stay outside the technical Admin role",
        )

    def test_admin_does_not_plan_field_work(self):
        """Scheduling joined the reserved list (owner decision, 2026-08-24).

        The other reserved authorities are about separation of duties. This one
        is about accountability: `responsible_staff` is derived from the school
        owner, never from whoever pressed Schedule, so an activity created from
        the Admin seat is filed against a CCEO who did not choose to make it —
        and it appears in that person's My Plan while the creator is sent to
        their own, where it never will. Planning is the owner's.
        """
        self.assertFalse(RolePermissionService.can_schedule_activity(ADMIN))

    def test_admin_can_execute_field_workflow_actions(self):
        activity = SimpleNamespace(
            assigned_partner_id=None,
            responsible_staff_id="someone-else",
            monitored_by_staff_id=None,
        )
        checks = (
            RolePermissionService.can_assign_to_partner(ADMIN),
            RolePermissionService.can_assign_to_staff(ADMIN, None),
            RolePermissionService.can_assign_to_project(ADMIN, None),
            RolePermissionService.can_add_to_cluster(ADMIN, None),
            RolePermissionService.can_upload_evidence(ADMIN, activity),
            RolePermissionService.can_enter_activity_sf_id(ADMIN, activity),
            RolePermissionService.can_review_activity(ADMIN, activity),
        )
        self.assertTrue(all(checks))

    def test_admin_can_update_any_scoped_record(self):
        self.assertTrue(RolePermissionService.can_update(ADMIN, object()))

    def test_global_execution_history_deletion_invariant_remains(self):
        class Activity:
            pass

        class School:
            pass

        self.assertFalse(RolePermissionService.can_delete(ADMIN, Activity()))
        self.assertTrue(RolePermissionService.can_delete(ADMIN, School()))


class AdminSuperRoleFinanceTests(TestCase):
    def test_admin_reads_the_disbursement_queue_but_cannot_pay_from_it(self):
        from apps.core.exceptions import Forbidden
        from apps.fund_requests.disbursement_dashboard_service import (
            _require_accountant,
            _require_accountant_action,
        )

        _require_accountant(ADMIN)  # visibility: allowed
        with self.assertRaises(Forbidden):
            _require_accountant_action(ADMIN)

    def test_admin_reads_team_fund_plans_but_cannot_approve_them(self):
        from apps.core.exceptions import Forbidden
        from apps.fund_requests.pl_approval_service import (
            _require_pl,
            _require_pl_action,
        )

        _require_pl(ADMIN)  # visibility: allowed
        with self.assertRaises(Forbidden):
            _require_pl_action(ADMIN)

    def test_the_role_that_owns_each_authority_still_holds_it(self):
        """Removing Admin must not have removed the actual owner."""
        from apps.fund_requests.disbursement_dashboard_service import (
            _require_accountant_action,
        )
        from apps.fund_requests.pl_approval_service import _require_pl_action

        _require_accountant_action(_user("Accountant"))
        _require_pl_action(_user("Program Lead"))


class AdminSuperRoleNavigationTests(SimpleTestCase):
    def test_admin_sidebar_exposes_business_and_operations_workspaces(self):
        from apps.core.navigation import build_sidebar_for_user

        user = SimpleNamespace(is_authenticated=True, active_role="Admin")
        labels = {
            item["label"]
            for section in build_sidebar_for_user(user, "/dashboard")
            for item in section["items"]
        }
        self.assertIn("Planning", labels)
        self.assertIn("Disbursement Dashboard", labels)
        self.assertIn("Users", labels)
