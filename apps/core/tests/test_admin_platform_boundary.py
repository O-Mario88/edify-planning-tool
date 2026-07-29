"""Admin observes the whole platform; Admin executes none of its field work.

The Platform Operations doctrine: Admin owns system maintenance, user support,
incidents, security response and releases — and holds platform-wide *read*
visibility over business operations. Visibility must never be confused with
business authority.

Before this boundary existed, ``ROLE_PERMISSIONS[ADMIN] = list(Permission)``
made Admin a business-process superuser: able to schedule field activities,
upload evidence into the IA chain, verify as IA, approve weekly and monthly
fund requests, and disburse money. Every one of those is now cut, and every
cut is pinned here in both directions — Admin is refused, and the rightful
role still passes, so the boundary cannot quietly become an over-cut.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from apps.core.exceptions import Forbidden
from apps.core.permissions import RolePermissionService
from apps.core.rbac import (
    ADMIN_EXCLUDED_PERMISSIONS,
    ROLE_PERMISSIONS,
    EdifyRole,
    Permission,
)


def _user(role):
    return SimpleNamespace(active_role=role, user_id=f"boundary-{role.lower()}")


ADMIN = _user("Admin")


class MatrixBoundaryTests(SimpleTestCase):
    """The grant is derived: a new Permission reaches Admin only if it is not
    an execution right."""

    def test_admin_no_longer_holds_every_permission(self):
        granted = set(ROLE_PERMISSIONS[EdifyRole.ADMIN])
        self.assertLess(len(granted), len(list(Permission)))

    def test_every_excluded_permission_is_really_excluded(self):
        granted = set(ROLE_PERMISSIONS[EdifyRole.ADMIN])
        for permission in ADMIN_EXCLUDED_PERMISSIONS:
            with self.subTest(permission.value):
                self.assertNotIn(permission, granted)

    def test_the_exclusions_cover_the_doctrines_named_prohibitions(self):
        must_be_excluded = {
            Permission.PLANNING_CREATE,
            Permission.ACTIVITY_ASSIGN,
            Permission.ACTIVITY_COMPLETE,
            Permission.EVIDENCE_REVIEW,
            Permission.IA_VERIFY,
            Permission.PAYMENT_ACT,
            Permission.BUDGET_APPROVE,
            Permission.COUNTRY_BUDGET_APPROVE,
            Permission.FUND_REQUEST_APPROVE_ESCALATED,
        }
        self.assertEqual(must_be_excluded - ADMIN_EXCLUDED_PERMISSIONS, set())

    def test_admin_keeps_platform_operations_authority(self):
        """Over-cutting would break Admin's actual job."""
        granted = set(ROLE_PERMISSIONS[EdifyRole.ADMIN])
        for permission in (
            Permission.SYSTEM_ADMIN,
            Permission.USER_MANAGE,
            Permission.STAFF_MANAGE,
            Permission.EXPORT,
            Permission.ANALYTICS_VIEW,
        ):
            with self.subTest(permission.value):
                self.assertIn(permission, granted)

    def test_admin_keeps_school_and_ssa_data_administration(self):
        """Admin uploads schools and SSA files and edits school records.

        The line is between maintaining school *data* and making field
        *judgements* about it: uploading an SSA file is administration;
        confirming the record it produced is IA's authority, and IA_VERIFY
        stays cut.
        """
        granted = set(ROLE_PERMISSIONS[EdifyRole.ADMIN])
        for permission in (
            Permission.SCHOOL_UPLOAD,
            Permission.SCHOOL_EDIT,
            Permission.SCHOOL_RESOLVE_DUPLICATE,
            Permission.SSA_UPLOAD,
            Permission.CLUSTER_ASSIGN,
            Permission.PROJECT_ASSIGN_SCHOOL,
        ):
            with self.subTest(permission.value):
                self.assertIn(permission, granted)
        self.assertNotIn(Permission.IA_VERIFY, granted)

    def test_admin_can_reach_every_school(self):
        """ "Access to all the schools" is route access AND a way to get there."""
        from apps.core.navigation import (
            ADMIN_NAV_PAGE_KEYS,
            ADMIN,
            PAGE_PERMISSIONS,
        )

        for page in ("schools", "school_directory", "school_profile"):
            with self.subTest(page):
                self.assertIn(ADMIN, PAGE_PERMISSIONS[page])
        self.assertIn("schools", ADMIN_NAV_PAGE_KEYS)

    def test_admin_keeps_every_view_permission(self):
        """Platform-wide observability: no *.view permission may be cut."""
        granted = {p.value for p in ROLE_PERMISSIONS[EdifyRole.ADMIN]}
        views = {p.value for p in Permission if p.value.lower().endswith(".view")}
        self.assertEqual(views - granted, set())


class FieldExecutionCutTests(SimpleTestCase):
    """Each RolePermissionService cut, asserted in both directions."""

    def test_admin_cannot_schedule_field_activities(self):
        self.assertFalse(RolePermissionService.can_schedule_activity(ADMIN))
        self.assertTrue(RolePermissionService.can_schedule_activity(_user("CCEO")))

    def test_admin_cannot_assign_work_to_partners(self):
        self.assertFalse(RolePermissionService.can_assign_to_partner(ADMIN))
        self.assertTrue(
            RolePermissionService.can_assign_to_partner(_user("Program Lead"))
        )

    def test_admin_cannot_assign_schools_to_staff(self):
        self.assertFalse(RolePermissionService.can_assign_to_staff(ADMIN, None))
        self.assertTrue(
            RolePermissionService.can_assign_to_staff(_user("Program Lead"), None)
        )

    def test_admin_records_project_membership_but_manages_no_project(self):
        """Membership is registry data; running the project is programme work."""
        self.assertTrue(RolePermissionService.can_assign_to_project(ADMIN, None))
        self.assertNotIn(
            Permission.PROJECT_MANAGE, set(ROLE_PERMISSIONS[EdifyRole.ADMIN])
        )

    def test_admin_still_maintains_the_cluster_registry(self):
        """The one field-adjacent capability Admin keeps, and why.

        Which cluster a school belongs to is registry data, and Admin already
        owns the school registry -- upload, edit, duplicate resolution, delete,
        geography setup. Scheduling that cluster's meetings is execution, and
        that is cut through PLANNING_CREATE / ACTIVITY_ASSIGN.
        """
        self.assertTrue(RolePermissionService.can_add_to_cluster(ADMIN, None))
        self.assertTrue(RolePermissionService.can_add_to_cluster(_user("CCEO"), None))
        # The execution half is still refused.
        self.assertFalse(RolePermissionService.can_schedule_activity(ADMIN))

    def test_admin_cannot_upload_evidence_into_the_ia_chain(self):
        activity = SimpleNamespace(
            assigned_partner_id=None,
            responsible_staff_id="someone-else",
            monitored_by_staff_id=None,
        )
        self.assertFalse(RolePermissionService.can_upload_evidence(ADMIN, activity))
        self.assertTrue(
            RolePermissionService.can_upload_evidence(
                _user("ImpactAssessment"), activity
            )
        )

    def test_admin_cannot_enter_salesforce_activity_ids(self):
        self.assertFalse(RolePermissionService.can_enter_activity_sf_id(ADMIN, None))
        self.assertTrue(
            RolePermissionService.can_enter_activity_sf_id(_user("CCEO"), None)
        )

    def test_admin_cannot_review_field_activities(self):
        self.assertFalse(RolePermissionService.can_review_activity(ADMIN, None))
        self.assertTrue(
            RolePermissionService.can_review_activity(_user("CountryDirector"), None)
        )

    def test_admin_cannot_verify_as_ia(self):
        self.assertFalse(RolePermissionService.can_verify_ia(ADMIN, None))
        self.assertTrue(
            RolePermissionService.can_verify_ia(_user("ImpactAssessment"), None)
        )

    def test_admin_cannot_clear_accounts(self):
        self.assertFalse(RolePermissionService.can_clear_accounts(ADMIN, None))
        self.assertTrue(
            RolePermissionService.can_clear_accounts(_user("Accountant"), None)
        )

    def test_nobody_deletes_execution_records_from_ordinary_pages(self):
        """Deleting an activity erases budget, evidence and credit history.
        Repairs go through the controlled repair workflow, for every role."""

        class Activity:
            pass

        class School:
            pass

        self.assertFalse(RolePermissionService.can_delete(ADMIN, Activity()))
        self.assertFalse(
            RolePermissionService.can_delete(_user("CountryDirector"), Activity())
        )
        # Master-data administration is still Admin's.
        self.assertTrue(RolePermissionService.can_delete(ADMIN, School()))


class FinanceChainCutTests(TestCase):
    """Money gates: Admin keeps the view, loses every action."""

    def test_admin_cannot_act_on_disbursements(self):
        from apps.fund_requests.disbursement_dashboard_service import (
            _require_accountant,
            _require_accountant_action,
        )

        # Observability: the dashboard gate still admits Admin.
        _require_accountant(ADMIN)
        # Authority: the action gate does not.
        with self.assertRaises(Forbidden):
            _require_accountant_action(ADMIN)
        _require_accountant_action(_user("Accountant"))

    def test_admin_cannot_act_on_team_fund_plans(self):
        from apps.fund_requests.pl_approval_service import (
            _require_pl,
            _require_pl_action,
        )

        _require_pl(ADMIN)  # queue view stays observable
        with self.assertRaises(Forbidden):
            _require_pl_action(ADMIN)
        _require_pl_action(_user("Program Lead"))

    def test_admin_cannot_approve_weekly_advances(self):
        """The weekly approver fallback no longer names Admin."""
        import inspect

        from apps.fund_requests import weekly_service

        source = inspect.getsource(weekly_service._require_weekly_approver)
        self.assertNotIn('"Admin"', source)
        self.assertIn('"CountryDirector"', source)
