"""Dangling school references must be detected, and removed without collateral.

Three tables hold a school identifier in a plain CharField, so the database
cannot reject a reference to a school that does not exist. Nothing noticed
them either, which is the actual defect — a CorePlan for a school that was
never imported is indistinguishable from a real one until something tries to
render it.

The repair deletes rather than relinks, so what these tests care most about is
what it leaves behind: a plan keyed on a real business key, and an assignment
keyed on a real primary key, must both survive untouched.
"""

from __future__ import annotations

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.core_schools.models import CoreActivitySlot, CorePlan, cplan_id
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.system_health.referential_integrity import dangling_school_references

User = get_user_model()


class DanglingSchoolReferenceTest(TestCase):
    def setUp(self):
        region = Region.objects.create(name="R")
        district = District.objects.create(name="D", region=region)
        self.school = School.objects.create(
            school_id="S-9001",
            name="Real School",
            region=region,
            district=district,
            school_type="core",
            enrollment=100,
        )
        user = User.objects.create_user(
            email="ri@t.org", name="RI", password="x", is_active=True
        )
        self.staff = StaffProfile.objects.create(user=user, title="CCEO")

    def _plan(self, school_id, fy="2026"):
        """CorePlan.id is a deterministic CharField primary key, not a
        generated one — creating without it silently collides on ''."""
        return CorePlan.objects.create(
            id=cplan_id(school_id, fy), school_id=school_id, fy=fy
        )

    def _slot(self, plan, school_id, seq):
        return CoreActivitySlot.objects.create(
            id=f"cslot-{school_id}-v{seq}",
            core_plan=plan,
            school_id=school_id,
            intervention="leadership",
            activity_type="visit",
            sequence_number=seq,
        )

    def _apply(self):
        """--apply, with the backup written somewhere disposable."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            call_command(
                "repair_referential_integrity",
                "--apply",
                f"--backup={tmp}/backup.json",
                stdout=StringIO(),
            )

    # ── detection ────────────────────────────────────────────────────────────
    def test_a_clean_database_reports_clean(self):
        report = dangling_school_references()
        self.assertTrue(report["clean"])
        self.assertEqual(report["totalDanglingRows"], 0)

    def test_a_core_plan_keyed_on_the_business_key_is_not_dangling(self):
        """CorePlan references School.school_id, not School.id. Treating the
        business key as dangling would condemn every valid plan."""
        self._plan(self.school.school_id)
        report = dangling_school_references()
        self.assertTrue(
            report["clean"],
            "a CorePlan keyed on the school's business key was reported as "
            "dangling — the check is looking in the wrong identifier space",
        )

    def test_an_assignment_keyed_on_the_primary_key_is_not_dangling(self):
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=self.school.id)
        self.assertTrue(dangling_school_references()["clean"])

    def test_a_reference_to_a_school_that_does_not_exist_is_reported(self):
        self._plan("10767")
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id="nope")

        report = dangling_school_references()
        self.assertFalse(report["clean"])
        self.assertEqual(report["totalDanglingRows"], 2)
        by_table = {c["table"]: c for c in report["checks"]}
        self.assertEqual(by_table["core_plan"]["danglingRows"], 1)
        self.assertEqual(by_table["staff_school_assignment"]["danglingRows"], 1)

    def test_slots_under_a_dangling_plan_are_counted(self):
        plan = self._plan("10767")
        self._slot(plan, "10767", 1)
        by_table = {c["table"]: c for c in dangling_school_references()["checks"]}
        self.assertEqual(by_table["core_activity_slot"]["danglingRows"], 1)

    # ── repair ───────────────────────────────────────────────────────────────
    def _seed_mixed(self):
        """One valid and one dangling row in each affected table."""
        good = self._plan(self.school.school_id)
        self._slot(good, self.school.school_id, 1)
        bad = self._plan("10767")
        self._slot(bad, "10767", 1)
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=self.school.id)
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id="nope")
        return good, bad

    def test_dry_run_is_the_default_and_deletes_nothing(self):
        self._seed_mixed()
        out = StringIO()
        call_command("repair_referential_integrity", stdout=out)
        self.assertIn("DRY-RUN", out.getvalue())
        self.assertEqual(CorePlan.objects.count(), 2)
        self.assertEqual(StaffSchoolAssignment.objects.count(), 2)

    def test_apply_leaves_every_valid_row_untouched(self):
        good, bad = self._seed_mixed()
        self._apply()

        self.assertTrue(
            CorePlan.objects.filter(id=good.id).exists(),
            "the repair deleted a plan keyed on a real business key",
        )
        self.assertFalse(CorePlan.objects.filter(id=bad.id).exists())
        self.assertEqual(
            StaffSchoolAssignment.objects.count(),
            1,
            "the repair removed a valid staff assignment",
        )
        self.assertTrue(dangling_school_references()["clean"])

    def test_slots_are_removed_with_their_plan(self):
        self._seed_mixed()
        self._apply()
        self.assertEqual(
            CoreActivitySlot.objects.count(),
            1,
            "slots under a deleted plan should go with it",
        )
        self.assertEqual(
            CoreActivitySlot.objects.first().school_id, self.school.school_id
        )

    def test_the_repair_is_idempotent(self):
        self._seed_mixed()
        self._apply()
        before = (CorePlan.objects.count(), StaffSchoolAssignment.objects.count())
        import tempfile

        out = StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            call_command(
                "repair_referential_integrity",
                "--apply",
                f"--backup={tmp}/b.json",
                stdout=out,
            )
        after = (CorePlan.objects.count(), StaffSchoolAssignment.objects.count())
        self.assertEqual(before, after)
        self.assertIn("Nothing to repair", out.getvalue())
