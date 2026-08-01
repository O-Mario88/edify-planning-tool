from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.geography.models import District, Region
from apps.schools.models import School


class ReconcileStaffMemberCommandTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@edify.test", name="Admin", password="strong-test-pass"
        )
        self.manager = User.objects.create_user(
            email="lead@edify.test",
            name="Lead Person",
            roles=["Program Lead"],
            active_role="Program Lead",
            password="strong-test-pass",
            status="active",
            is_active=True,
        )
        self.manager_profile = StaffProfile.objects.create(user=self.manager)
        region = Region.objects.create(name="East")
        district = District.objects.create(name="Mbale", region=region)
        self.schools = [
            School.objects.create(
                school_id=f"S-{index}",
                name=f"School {index}",
                region=region,
                district=district,
                account_owner_name_raw="  Alex   Luyima ",
            )
            for index in range(2)
        ]

    def _call(self, *extra, apply=False):
        args = [
            "--name",
            "Alex Luyima",
            "--email",
            "aluyima@edify.org",
            "--phone",
            "256707027694",
            "--position",
            "CCEO",
            "--role",
            "CCEO",
            "--expected-schools",
            "2",
            "--manager-email",
            "lead@edify.test",
            "--actor-email",
            "admin@edify.test",
            *extra,
        ]
        if apply:
            args.append("--apply")
        out = StringIO()
        call_command("reconcile_staff_member", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_does_not_mutate(self):
        output = self._call()
        self.assertIn("DRY_RUN", output)
        self.assertFalse(User.objects.filter(email="aluyima@edify.org").exists())

    def test_apply_creates_active_user_exact_scope_and_manager(self):
        output = self._call(apply=True)
        self.assertIn("APPLY", output)
        user = User.objects.get(email="aluyima@edify.org")
        self.assertEqual(user.active_role, "CCEO")
        self.assertEqual(user.status, "active")
        self.assertTrue(user.is_active)
        self.assertEqual(user.phone, "256707027694")
        staff = user.staff_profile
        self.assertEqual(staff.school_links.count(), 2)
        self.assertEqual(
            set(staff.school_links.values_list("school_id", flat=True)),
            {school.id for school in self.schools},
        )
        self.assertTrue(
            StaffSupervisorAssignment.objects.filter(
                supervisee=staff, supervisor=self.manager_profile
            ).exists()
        )

    def test_count_mismatch_aborts_without_mutation(self):
        with self.assertRaises(CommandError):
            self._call("--expected-schools", "3", apply=True)
        self.assertFalse(User.objects.filter(email="aluyima@edify.org").exists())
        self.assertEqual(StaffSchoolAssignment.objects.count(), 0)
