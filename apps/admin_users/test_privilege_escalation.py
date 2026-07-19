"""Privilege-escalation guards.

USER_MANAGE is held by CountryDirector and HumanResources as well as Admin,
because they do routine staff-role changes. Two paths never got the Admin-only
guard that update_user() had, and both were reproduced against the development
database: an HR user could set an arbitrary password on a sitting Admin, and
could create a new active account carrying role='Admin'.

These tests exist because the guard was written once, inline, and the two
newer callers silently did without it.
"""

from django.test import TestCase

from apps.accounts.models import User
from apps.admin_users.services import assert_may_administer, create
from apps.core.exceptions import BadRequest


class PrivilegeEscalationGuardTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@edify.org", password="x", name="Admin",
            roles=["Admin"], active_role="Admin",
        )
        self.hr = User.objects.create_user(
            email="hr@edify.org", password="x", name="HR",
            roles=["HumanResources"], active_role="HumanResources",
        )
        self.cceo = User.objects.create_user(
            email="cceo@edify.org", password="x", name="CCEO",
            roles=["CCEO"], active_role="CCEO",
        )

    def test_non_admin_cannot_touch_an_admin_account(self):
        """Setting a password IS taking the account over.

        The reset_password action had no guard, so an HR user could set a
        password of their choosing on a sitting Admin and log in as them.
        """
        with self.assertRaises(BadRequest) as ctx:
            assert_may_administer(self.admin, self.hr)
        self.assertIn("Only an Admin", str(ctx.exception.detail))

    def test_non_admin_cannot_grant_the_admin_role(self):
        with self.assertRaises(BadRequest) as ctx:
            assert_may_administer(None, self.hr, requested_roles=["Admin"])
        self.assertIn("Admin role", str(ctx.exception.detail))

    def test_create_refuses_to_mint_an_admin_for_a_non_admin(self):
        """The whole point: HTTP 201 with roles=['Admin'] was reproducible."""
        with self.assertRaises(BadRequest):
            create(
                {"email": "new-admin@edify.org", "name": "N", "role": "Admin"},
                self.hr,
            )
        self.assertFalse(
            User.objects.filter(email="new-admin@edify.org").exists(),
            "the account must not exist after the guard refuses",
        )

    def test_admin_may_still_do_all_of_it(self):
        """The guard must not lock Admins out of their own job."""
        assert_may_administer(self.admin, self.admin)
        assert_may_administer(None, self.admin, requested_roles=["Admin"])
        created = create(
            {"email": "second-admin@edify.org", "name": "S", "role": "Admin"},
            self.admin,
        )
        self.assertTrue(created)

    def test_routine_staff_role_changes_still_work_for_hr(self):
        """HR must keep doing CCEO -> Program Lead; that is the job.

        A guard that blocks legitimate work gets disabled, so this is as
        important as the refusals above.
        """
        assert_may_administer(self.cceo, self.hr, requested_roles=["ProgramLead"])
        created = create(
            {"email": "new-cceo@edify.org", "name": "C", "role": "CCEO"}, self.hr
        )
        self.assertTrue(created)

    def test_guard_is_shared_not_reimplemented(self):
        """Three copies is how this hole appeared in the first place."""
        import inspect

        from apps.admin_users import services

        src = inspect.getsource(services.update_user)
        self.assertIn("assert_may_administer", src)
        self.assertIn("assert_may_administer", inspect.getsource(services.create))
