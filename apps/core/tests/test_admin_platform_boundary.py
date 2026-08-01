"""Regression contract for the Admin platform super-role.

Admin has every application permission and may execute every role-gated
workflow. Domain invariants still apply: state transitions, required evidence,
audit logging, and the global ban on deleting execution history are not
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
    def test_admin_holds_every_canonical_permission(self):
        self.assertEqual(
            set(ROLE_PERMISSIONS[EdifyRole.ADMIN]),
            set(Permission),
        )

    def test_admin_has_no_permission_exclusions(self):
        self.assertEqual(ADMIN_EXCLUDED_PERMISSIONS, frozenset())

    def test_admin_can_execute_field_workflow_actions(self):
        activity = SimpleNamespace(
            assigned_partner_id=None,
            responsible_staff_id="someone-else",
            monitored_by_staff_id=None,
        )
        checks = (
            RolePermissionService.can_schedule_activity(ADMIN),
            RolePermissionService.can_assign_to_partner(ADMIN),
            RolePermissionService.can_assign_to_staff(ADMIN, None),
            RolePermissionService.can_assign_to_project(ADMIN, None),
            RolePermissionService.can_add_to_cluster(ADMIN, None),
            RolePermissionService.can_upload_evidence(ADMIN, activity),
            RolePermissionService.can_enter_activity_sf_id(ADMIN, activity),
            RolePermissionService.can_review_activity(ADMIN, activity),
            RolePermissionService.can_verify_ia(ADMIN, activity),
            RolePermissionService.can_clear_accounts(ADMIN, activity),
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
    def test_admin_passes_disbursement_action_gate(self):
        from apps.fund_requests.disbursement_dashboard_service import (
            _require_accountant,
            _require_accountant_action,
        )

        _require_accountant(ADMIN)
        _require_accountant_action(ADMIN)

    def test_admin_passes_team_fund_action_gate(self):
        from apps.fund_requests.pl_approval_service import (
            _require_pl,
            _require_pl_action,
        )

        _require_pl(ADMIN)
        _require_pl_action(ADMIN)


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
