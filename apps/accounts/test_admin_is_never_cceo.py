"""An Admin account is never a CCEO.

Owner, 2026-10-02: "remove admin from being a cceo. Admin should never be a
CCEO".

The super-admin carried both hats (accounts 0021, and the seed re-asserted
it), and roles are counted where they are held, so the account stood in every
list of CCEOs. The rule is one function (apps.core.rbac.admin_is_also_cceo),
refused in words by the user service, held by the database, and applied to the
accounts that already had the hat by accounts 0036.
"""

from __future__ import annotations

import importlib

from django.apps import apps as app_registry
from django.db import IntegrityError, connection, transaction
from django.test import SimpleTestCase, TestCase

from apps.accounts.models import StaffProfile, User
from apps.admin_users.services import create, update_user
from apps.core.exceptions import BadRequest
from apps.core.rbac import admin_is_also_cceo

CONSTRAINT = "user_admin_is_never_cceo"


def _user(email, roles, active_role=None, **over):
    return User.objects.create_user(
        email=email,
        password="x",
        name=email.split("@")[0],
        roles=roles,
        active_role=active_role or roles[0],
        **over,
    )


class RuleTest(SimpleTestCase):
    def test_admin_holding_cceo_is_refused_in_either_order(self):
        self.assertTrue(admin_is_also_cceo(["Admin", "CCEO"]))
        self.assertTrue(admin_is_also_cceo(["CCEO", "Program Lead", "Admin"]))

    def test_admin_acting_as_a_cceo_is_refused(self):
        self.assertTrue(admin_is_also_cceo(["Admin"], "CCEO"))

    def test_everything_else_is_left_alone(self):
        self.assertFalse(admin_is_also_cceo(["Admin"], "Admin"))
        self.assertFalse(admin_is_also_cceo(["CCEO"], "CCEO"))
        self.assertFalse(admin_is_also_cceo(["CCEO", "Program Lead"], "CCEO"))
        self.assertFalse(admin_is_also_cceo(["Admin", "CountryDirector"], "Admin"))
        self.assertFalse(admin_is_also_cceo(None))


class UserServiceTest(TestCase):
    def setUp(self):
        self.admin = _user("admin@edify.org", ["Admin"])
        self.cceo = _user("cceo@edify.org", ["CCEO"])

    def test_an_admin_is_not_created_with_a_cceo_hat(self):
        for payload in (
            {"role": "Admin", "additionalRoles": ["CCEO"]},
            {"role": "CCEO", "additionalRoles": ["Admin"]},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(BadRequest) as refused:
                    create(
                        {"email": "both@edify.org", "name": "Both", **payload},
                        self.admin,
                    )
                self.assertIn("cannot also be a CCEO", str(refused.exception.detail))
                self.assertFalse(User.objects.filter(email="both@edify.org").exists())

    def test_a_cceo_is_not_given_the_admin_role_on_top(self):
        with self.assertRaises(BadRequest):
            update_user(
                self.cceo.id, {"role": "CCEO", "additionalRoles": ["Admin"]}, self.admin
            )
        self.cceo.refresh_from_db()
        self.assertEqual(self.cceo.roles, ["CCEO"])

    def test_an_admin_is_not_given_the_cceo_role_on_top(self):
        other = _user("other-admin@edify.org", ["Admin"])
        with self.assertRaises(BadRequest):
            update_user(
                other.id, {"role": "Admin", "additionalRoles": ["CCEO"]}, self.admin
            )
        other.refresh_from_db()
        self.assertEqual(other.roles, ["Admin"])

    def test_a_cceo_can_become_an_admin_by_leaving_the_field_role(self):
        update_user(self.cceo.id, {"role": "Admin"}, self.admin)
        self.cceo.refresh_from_db()
        self.assertEqual((self.cceo.roles, self.cceo.active_role), (["Admin"], "Admin"))

    def test_other_pairs_of_roles_still_work(self):
        update_user(
            self.cceo.id,
            {"role": "CCEO", "additionalRoles": ["Program Lead"]},
            self.admin,
        )
        self.cceo.refresh_from_db()
        self.assertEqual(self.cceo.roles, ["CCEO", "Program Lead"])


class DatabaseTest(TestCase):
    def test_the_database_refuses_what_gets_past_the_service(self):
        for roles, active in (
            (["Admin", "CCEO"], "Admin"),
            (["Admin", "CCEO"], "CCEO"),
            (["Admin"], "CCEO"),
        ):
            with self.subTest(roles=roles, active=active):
                with self.assertRaises(IntegrityError) as refused:
                    with transaction.atomic():
                        _user("both@edify.org", roles, active)
                self.assertIn(CONSTRAINT, str(refused.exception))

    def test_an_admin_made_without_naming_the_active_role_acts_as_admin(self):
        """The column's own default is CCEO; the manager must not fall back to
        it for an Admin."""
        user = User.objects.create_user(
            email="plain-admin@edify.org", password="x", name="Plain", roles=["Admin"]
        )
        self.assertEqual(user.active_role, "Admin")
        self.assertEqual(
            User.objects.create_superuser(
                "super@edify.org", "Super", password="x"
            ).active_role,
            "Admin",
        )


class TakeTheHatOffMigrationTest(TestCase):
    """Migration 0036 against the shape production is in.

    Each test drops the constraint 0037 adds, writes the accounts it forbids
    and runs the migration's function. The TestCase transaction rolls the DDL
    back.
    """

    def setUp(self):
        self.migration = importlib.import_module(
            "apps.accounts.migrations.0036_admin_is_never_a_cceo"
        )
        with connection.cursor() as cursor:
            cursor.execute(f'ALTER TABLE "user" DROP CONSTRAINT {CONSTRAINT}')

    def run_migration(self):
        self.migration.take_the_cceo_hat_off_admins(app_registry, None)

    def test_the_cceo_hat_comes_off_and_admin_stays(self):
        both = _user("both@edify.org", ["Admin", "CCEO"], "Admin")
        self.run_migration()
        both.refresh_from_db()
        self.assertEqual((both.roles, both.active_role), (["Admin"], "Admin"))

    def test_an_admin_out_in_the_field_hat_comes_back_to_admin(self):
        both = _user("both@edify.org", ["Admin", "CCEO"], "CCEO")
        acting = _user("acting@edify.org", ["Admin"], "CCEO")
        self.run_migration()
        for user in (both, acting):
            user.refresh_from_db()
            self.assertEqual((user.roles, user.active_role), (["Admin"], "Admin"))

    def test_other_hats_and_their_order_are_kept(self):
        many = _user(
            "many@edify.org", ["CountryDirector", "CCEO", "Admin"], "CountryDirector"
        )
        self.run_migration()
        many.refresh_from_db()
        self.assertEqual(many.roles, ["CountryDirector", "Admin"])
        self.assertEqual(many.active_role, "CountryDirector")

    def test_a_removed_or_inactive_account_is_put_right_too(self):
        """The constraint is on every row, not only the ones that can sign in."""
        from django.utils import timezone

        gone = _user(
            "gone@edify.org",
            ["Admin", "CCEO"],
            "CCEO",
            is_active=False,
            deleted_at=timezone.now(),
        )
        self.run_migration()
        gone.refresh_from_db()
        self.assertEqual((gone.roles, gone.active_role), (["Admin"], "Admin"))

    def test_everyone_who_is_not_an_admin_is_left_alone(self):
        cceo = _user("cceo@edify.org", ["CCEO"])
        lead = _user("lead@edify.org", ["Program Lead", "CCEO"], "CCEO")
        admin = _user("admin@edify.org", ["Admin"])
        before = {
            u.id: (list(u.roles), u.active_role, u.updated_at)
            for u in (cceo, lead, admin)
        }
        self.run_migration()
        for user in (cceo, lead, admin):
            user.refresh_from_db()
            self.assertEqual(
                before[user.id], (user.roles, user.active_role, user.updated_at)
            )

    def test_the_field_work_the_account_carries_is_not_deleted(self):
        both = _user("both@edify.org", ["Admin", "CCEO"], "CCEO")
        profile = StaffProfile.objects.create(user=both, onboarding_state="active")
        self.run_migration()
        self.assertTrue(StaffProfile.objects.filter(id=profile.id).exists())

    def test_the_constraint_builds_over_the_cleaned_rows(self):
        _user("both@edify.org", ["Admin", "CCEO"], "CCEO")
        _user("acting@edify.org", ["Admin"], "CCEO")
        self.run_migration()
        with connection.schema_editor() as editor:
            editor.add_constraint(
                User, next(c for c in User._meta.constraints if c.name == CONSTRAINT)
            )
