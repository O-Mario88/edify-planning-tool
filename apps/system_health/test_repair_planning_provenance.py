"""Historical activities get the planning source and partner monitor that
every write path records, from their own relations and never by guessing
(2026-09-13 ecosystem audit: the seed's history and the partner scheduling
path before it stamped failed the platform's own health checks)."""

from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.activities.models import Activity
from apps.audit.models import AuditLog
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School


class PlanningProvenanceRepairTest(TestCase):
    def setUp(self):
        region = Region.objects.create(name="Provenance Region")
        district = District.objects.create(name="Provenance District", region=region)
        self.school = School.objects.create(
            school_id="SCH-PROV-1",
            name="Provenance Primary",
            region=region,
            district=district,
        )
        self.visit = Activity.objects.create(
            activity_type="school_visit", school=self.school, status="completed"
        )
        self.partner = Partner.objects.create(name="Provenance Partner")
        self.partner_work = Activity.objects.create(
            activity_type="partner_activity",
            delivery_type="partner",
            school=self.school,
            assigned_partner_id=self.partner.id,
            status="completed",
        )
        PartnerAssignment.objects.create(
            partner=self.partner,
            school=self.school,
            assigning_staff_id="staff-handover",
            monitoring_staff_id="staff-monitor",
            scheduled_activity=self.partner_work,
        )
        self.orphan = Activity.objects.create(
            activity_type="partner_activity",
            delivery_type="partner",
            status="completed",
        )

    def _run(self, *args):
        out = StringIO()
        call_command("repair_ecosystem_data", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_counts_without_writing(self):
        output = self._run("--only", "planning-source")
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.planning_source, "")
        self.assertIn(
            "planning-source: 2 activit(y/ies) classified; 1 MANUAL REVIEW", output
        )

    def test_apply_classifies_from_relations_and_reports_the_rest(self):
        self._run("--only", "planning-source", "--apply")
        self.visit.refresh_from_db()
        self.partner_work.refresh_from_db()
        self.orphan.refresh_from_db()
        self.assertEqual(
            (self.visit.planning_source, self.visit.activity_context_type),
            ("school_planning", "school"),
        )
        self.assertEqual(
            (
                self.partner_work.planning_source,
                self.partner_work.activity_context_type,
            ),
            ("partner_assignment", "school"),
            "the assignment that produced partner work is its planning decision",
        )
        self.assertEqual(self.orphan.planning_source, "", "nothing to classify by")
        self.assertTrue(
            AuditLog.objects.filter(
                action="data_repair.planning_source", subject_id=self.visit.id
            ).exists()
        )
        # Idempotent: a second run finds only the row it cannot classify.
        self.assertIn(
            "0 activit(y/ies) classified; 1 MANUAL REVIEW",
            self._run("--only", "planning-source", "--apply"),
        )

    def test_partner_work_gets_the_monitor_its_assignment_names(self):
        output = self._run("--only", "partner-monitor", "--apply")
        self.partner_work.refresh_from_db()
        self.orphan.refresh_from_db()
        self.assertEqual(self.partner_work.monitored_by_staff_id, "staff-monitor")
        self.assertIsNone(self.orphan.monitored_by_staff_id)
        self.assertIn(
            "1 partner activit(y/ies) given their assignment's monitor; 1 MANUAL REVIEW",
            output,
        )

    def test_the_handover_person_monitors_when_no_monitor_was_named(self):
        PartnerAssignment.objects.filter(scheduled_activity=self.partner_work).update(
            monitoring_staff_id=None
        )
        self._run("--only", "partner-monitor", "--apply")
        self.partner_work.refresh_from_db()
        self.assertEqual(self.partner_work.monitored_by_staff_id, "staff-handover")
