"""A school's holder and its portfolio assignment are one fact (owner,
2026-10-02).

``School.account_owner_id`` names the holder; ``StaffSchoolAssignment`` is the
same fact as the scoping chain reads it — a person's schools, and through the
reporting line their Programme Lead's team. The directory's match and bulk
match, staff setup and the school upload each named a new holder and left the
previous holder's row, so a school sat in two teams' scope while every list
filed it under one. These hold the paths together, the repair for what they
left behind, and the two health findings that say where a Lead cannot see a
plan.
"""

from __future__ import annotations

from datetime import date, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.schools.ownership_transfer import hold_schools
from apps.system_health.planning_oversight_health import (
    _cceo_plans_no_program_lead_can_see,
    _schools_held_by_one_person_and_assigned_to_another,
)


def _person(email, name, role):
    user = User.objects.create(
        email=email, name=name, roles=[role], active_role=role, is_active=True
    )
    return user, StaffProfile.objects.create(user=user, title=name)


class _Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Holder Region")
        district = District.objects.create(name="Holder District", region=region)
        cls.lead_user, cls.lead = _person("lead@holder.test", "Lead", "Program Lead")
        cls.old_user, cls.old = _person("old@holder.test", "Old Holder", "CCEO")
        cls.new_user, cls.new = _person("new@holder.test", "New Holder", "CCEO")
        cls.school = School.objects.create(
            school_id="HOLD-1",
            name="Holder Primary",
            region=region,
            district=district,
            school_type="client",
            account_owner_id=cls.old.id,
            account_owner_status="matched",
        )
        StaffSchoolAssignment.objects.create(staff=cls.old, school_id=cls.school.id)

    def _holders(self):
        return set(
            StaffSchoolAssignment.objects.filter(school_id=self.school.id).values_list(
                "staff_id", flat=True
            )
        )


class HoldSchoolsTest(_Fixture):
    def test_the_new_holder_replaces_the_old(self):
        hold_schools([self.school.id], self.new.id)
        self.assertEqual(self._holders(), {self.new.id})

    def test_it_is_idempotent(self):
        hold_schools([self.school.id], self.new.id)
        hold_schools([self.school.id, self.school.id], self.new.id)
        self.assertEqual(
            StaffSchoolAssignment.objects.filter(school_id=self.school.id).count(), 1
        )

    def test_nothing_named_changes_nothing(self):
        hold_schools([], self.new.id)
        hold_schools([self.school.id], "")
        self.assertEqual(self._holders(), {self.old.id})


class ReconcileSchoolHoldersTest(_Fixture):
    def setUp(self):
        # The holder changed and the old row stayed: the drift.
        School.objects.filter(id=self.school.id).update(account_owner_id=self.new.id)

    def _run(self, *args):
        out = StringIO()
        call_command("reconcile_school_holders", *args, stdout=out)
        return out.getvalue()

    def test_the_finding_names_the_school(self):
        finding = _schools_held_by_one_person_and_assigned_to_another()
        self.assertEqual(finding["count"], 1)
        self.assertIn("held by New Holder", finding["examples"][0]["actual"])
        self.assertIn("Old Holder", finding["examples"][0]["actual"])

    def test_a_report_changes_nothing(self):
        output = self._run()
        self.assertIn("Also assigned to somebody else: 1", output)
        self.assertIn("Holder's own assignment missing: 1", output)
        self.assertEqual(self._holders(), {self.old.id})

    def test_apply_makes_the_assignment_say_what_the_school_says(self):
        self._run("--apply")
        self.assertEqual(self._holders(), {self.new.id})
        self.assertEqual(
            _schools_held_by_one_person_and_assigned_to_another()["count"], 0
        )
        self.assertIn("Nothing to reconcile", self._run())

    def test_a_school_with_no_holder_is_left_alone(self):
        School.objects.filter(id=self.school.id).update(account_owner_id=None)
        self._run("--apply")
        self.assertEqual(self._holders(), {self.old.id})

    def test_list_names_every_row_and_changes_nothing(self):
        output = self._run("--list")
        self.assertIn(
            f"removed: school HOLD-1 (Holder Primary) from Old Holder "
            f"[{self.old.id}]; holder is New Holder [{self.new.id}]",
            output,
        )
        self.assertIn(
            f"added: school HOLD-1 (Holder Primary) to its holder New Holder "
            f"[{self.new.id}]",
            output,
        )
        self.assertEqual(self._holders(), {self.old.id})


class RepairMigrationTest(_Fixture):
    """schools 0023 (owner, 2026-10-02: "Repair the old school holder
    mismatches"): the deploy makes the portfolio agree with the school
    records, through the historical models, and prints what it changed."""

    def setUp(self):
        School.objects.filter(id=self.school.id).update(account_owner_id=self.new.id)

    def _migrate(self):
        from contextlib import redirect_stdout
        from importlib import import_module

        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        historical = (
            MigrationExecutor(connection)
            .loader.project_state(("schools", "0023_repair_school_holder_assignments"))
            .apps
        )
        migration = import_module(
            "apps.schools.migrations.0023_repair_school_holder_assignments"
        )
        out = StringIO()
        with redirect_stdout(out):
            migration.repair_school_holder_assignments(historical, None)
        return out.getvalue()

    def _school(self, code, holder_id, *assigned, **extra):
        school = School.objects.create(
            school_id=code,
            name=f"{code} Primary",
            region=self.school.region,
            district=self.school.district,
            school_type="client",
            account_owner_id=holder_id,
            account_owner_status="matched",
            **extra,
        )
        for staff in assigned:
            StaffSchoolAssignment.objects.create(staff=staff, school_id=school.id)
        return school

    def _assigned(self, school):
        return set(
            StaffSchoolAssignment.objects.filter(school_id=school.id).values_list(
                "staff_id", flat=True
            )
        )

    def test_the_old_holders_row_goes_and_the_holders_is_added(self):
        output = self._migrate()
        self.assertEqual(self._holders(), {self.new.id})
        self.assertIn("1 also assigned to somebody else", output)
        self.assertIn("removed: school HOLD-1 (Holder Primary) from Old Holder", output)
        self.assertIn("added: school HOLD-1 (Holder Primary) to its holder New", output)
        self.assertIn("repaired 1 schools: 1 rows removed, 1 added.", output)

    def test_a_second_run_finds_nothing(self):
        self._migrate()
        output = self._migrate()
        self.assertIn("nothing to repair", output)
        self.assertEqual(self._holders(), {self.new.id})

    def test_a_school_in_two_portfolios_keeps_only_its_holders(self):
        both = self._school("HOLD-2", self.new.id, self.old, self.new)
        self._migrate()
        self.assertEqual(self._assigned(both), {self.new.id})

    def test_a_holder_stamped_as_a_user_id_is_the_same_person(self):
        agreed = self._school("HOLD-3", self.new_user.id, self.new)
        drifted = self._school("HOLD-4", self.new_user.id, self.old)
        output = self._migrate()
        self.assertEqual(self._assigned(agreed), {self.new.id})
        self.assertEqual(self._assigned(drifted), {self.new.id})
        self.assertNotIn("HOLD-3", output)

    def test_what_agrees_is_not_touched(self):
        agreed = self._school("HOLD-5", self.old.id, self.old)
        row = StaffSchoolAssignment.objects.get(school_id=agreed.id)
        output = self._migrate()
        self.assertNotIn("HOLD-5", output)
        self.assertTrue(StaffSchoolAssignment.objects.filter(pk=row.pk).exists())

    def test_what_cannot_be_reconciled_is_left_alone(self):
        nobody = self._school("HOLD-6", None, self.old)
        stranger = self._school("HOLD-7", "no-such-profile", self.old)
        removed = self._school("HOLD-8", self.new.id, self.old)
        removed.deleted_at = removed.created_at
        removed.save(update_fields=["deleted_at"])
        output = self._migrate()
        for school in (nobody, stranger, removed):
            self.assertEqual(self._assigned(school), {self.old.id})
        self.assertIn("1 with a holder that is no staff profile (left alone)", output)

    def test_the_school_record_is_never_written(self):
        before = School.objects.get(id=self.school.id)
        self._migrate()
        after = School.objects.get(id=self.school.id)
        self.assertEqual(
            (after.account_owner_id, after.updated_at),
            (before.account_owner_id, before.updated_at),
        )

    def test_the_lead_gets_the_school_once_the_portfolio_agrees(self):
        # The case the owner met: the old holder reports to nobody the new
        # holder's Programme Lead can see through.
        from apps.core.scoping import resolve_user_scope

        StaffSupervisorAssignment.objects.create(
            supervisee=self.new, supervisor=self.lead
        )
        before = resolve_user_scope(self.lead_user)
        self._migrate()
        after = resolve_user_scope(self.lead_user)
        self.assertNotIn(self.school.id, set(before.team_school_ids or []))
        self.assertIn(self.school.id, set(after.team_school_ids or []))


class PlansNoLeadCanSeeTest(_Fixture):
    def setUp(self):
        fy = get_operational_fy()
        for owner_id in (self.new.id, self.new_user.id):
            Activity.objects.create(
                activity_type="school_visit",
                school=self.school,
                responsible_staff_id=owner_id,
                fy=fy,
                planned_date=date.today() + timedelta(days=3),
                status="scheduled",
            )

    def _finding(self):
        return _cceo_plans_no_program_lead_can_see()

    def test_a_cceo_with_no_reporting_line_is_named_with_their_plans(self):
        finding = self._finding()
        self.assertEqual(finding["count"], 2)
        self.assertEqual(finding["examples"][0]["staff"], "New Holder")
        self.assertIn("no reporting line", finding["examples"][0]["actual"])

    def test_a_reporting_line_to_a_lead_clears_it(self):
        StaffSupervisorAssignment.objects.create(
            supervisee=self.new, supervisor=self.lead
        )
        self.assertEqual(self._finding()["count"], 0)

    def test_a_lead_working_in_another_role_still_counts_as_one(self):
        StaffSupervisorAssignment.objects.create(
            supervisee=self.new, supervisor=self.lead
        )
        self.lead_user.roles = ["Program Lead", "CCEO"]
        self.lead_user.active_role = "CCEO"
        self.lead_user.save(update_fields=["roles", "active_role"])
        self.assertEqual(self._finding()["count"], 0)

    def test_a_line_to_somebody_who_is_not_a_lead_is_said(self):
        StaffSupervisorAssignment.objects.create(
            supervisee=self.new, supervisor=self.old
        )
        finding = self._finding()
        self.assertEqual(finding["count"], 2)
        self.assertIn(
            "does not hold the Programme Lead role", finding["examples"][0]["actual"]
        )

    def test_a_line_to_a_lead_who_cannot_sign_in_is_said(self):
        StaffSupervisorAssignment.objects.create(
            supervisee=self.new, supervisor=self.lead
        )
        self.lead_user.is_active = False
        self.lead_user.save(update_fields=["is_active"])
        self.assertIn("not active", self._finding()["examples"][0]["actual"])

    def test_partner_delivered_work_is_not_a_cceos_plan(self):
        Activity.objects.update(delivery_type="partner")
        self.assertEqual(self._finding()["count"], 0)
