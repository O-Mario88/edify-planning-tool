"""The bulk reporting-line applier.

The risk it guards against is a bulk tool that is looser than the single-record
path it stands in for: writing a link the Users page would have refused, or
writing one nobody can be shown to have authorised.
"""

from __future__ import annotations

import tempfile

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.core.rbac import EdifyRole


def staff(email, name, role):
    user = User.objects.create(
        email=email,
        name=name,
        roles=[role.value],
        active_role=role.value,
        is_active=True,
    )
    return StaffProfile.objects.create(user=user, title=name)


class AssignSupervisorsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create(
            email="admin@x.test",
            name="Admin",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            is_active=True,
        )
        cls.lead = staff("lead@x.test", "Real Lead", EdifyRole.COUNTRY_PROGRAM_LEAD)
        cls.cceo = staff("cceo@x.test", "Alex", EdifyRole.CCEO)
        cls.other = staff("acct@x.test", "Book Keeper", EdifyRole.PROGRAM_ACCOUNTANT)

    def _mapping(self, rows) -> str:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".csv", delete=False, newline=""
        )
        handle.write("cceo_email,program_lead_email\n")
        for cceo, lead in rows:
            handle.write(f"{cceo},{lead}\n")
        handle.close()
        return handle.name

    def run_command(self, rows, *, apply=False):
        from io import StringIO

        out = StringIO()
        args = ["assign_cceo_supervisors", "--mapping", self._mapping(rows)]
        if apply:
            args.append("--apply")
        call_command(*args, stdout=out)
        return out.getvalue()

    def test_a_dry_run_writes_nothing(self):
        output = self.run_command([("cceo@x.test", "lead@x.test")])

        self.assertIn("Reporting lines to set: 1", output)
        self.assertIn("nothing written", output)
        self.assertFalse(StaffSupervisorAssignment.objects.exists())

    def test_applying_sets_the_reporting_line(self):
        self.run_command([("cceo@x.test", "lead@x.test")], apply=True)

        link = StaffSupervisorAssignment.objects.get()
        self.assertEqual(link.supervisee_id, self.cceo.id)
        self.assertEqual(link.supervisor_id, self.lead.id)

    def test_a_supervisor_who_is_not_a_program_lead_is_refused(self):
        """The bulk path must not accept what the Users page would reject."""
        output = self.run_command([("cceo@x.test", "acct@x.test")], apply=True)

        self.assertIn("not a Program Lead", output)
        self.assertFalse(StaffSupervisorAssignment.objects.exists())

    def test_an_unknown_email_is_refused_rather_than_guessed_at(self):
        output = self.run_command([("ghost@x.test", "lead@x.test")], apply=True)

        self.assertIn("no staff profile with this email", output)
        self.assertFalse(StaffSupervisorAssignment.objects.exists())

    def test_the_change_is_attributed_to_a_real_actor(self):
        """A reporting line written by nobody is not auditable."""
        from apps.audit.models import AuditLog

        self.run_command([("cceo@x.test", "lead@x.test")], apply=True)

        event = AuditLog.objects.filter(
            action="admin.supervisor_reassigned", subject_id=self.cceo.id
        ).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.actor_id, self.admin.id)

    def test_it_refuses_to_run_with_no_admin_to_attribute_to(self):
        User.objects.filter(active_role=EdifyRole.ADMIN.value).delete()

        with self.assertRaises(CommandError):
            self.run_command([("cceo@x.test", "lead@x.test")], apply=True)

    def test_a_missing_mapping_file_is_a_clear_error(self):
        with self.assertRaises(CommandError):
            call_command("assign_cceo_supervisors", "--mapping", "/nowhere/x.csv")
