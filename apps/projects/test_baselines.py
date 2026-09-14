"""Project baselines are filled when the evidence arrives, never overwritten
(IA review, owner, 2026-09-13; apps.projects.baselines)."""

from __future__ import annotations

from datetime import date, datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.geography.models import District, Region
from apps.projects import baselines
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

INTERVENTION = "leadership"


def _on(day: date):
    return timezone.make_aware(datetime.combine(day, datetime.min.time()))


class BaselineCaptureTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="PB Region", country="Uganda")
        cls.district = District.objects.create(name="PB District", region=region)
        cls.region = region
        cls.project = Project.objects.create(
            name="PB Leadership", code="PB01", intervention=INTERVENTION
        )

    def _school(self, code):
        return School.objects.create(
            school_id=code, name=code, region=self.region, district=self.district
        )

    def _enrol(self, school, start=date(2026, 3, 1)):
        return ProjectSchoolAssignment.objects.create(
            project=self.project, school=school, start_date=start
        )

    def _ssa(self, school, day, score, status="confirmed"):
        record = SsaRecord.objects.create(
            school=school,
            date_of_ssa=_on(day),
            fy="2026",
            quarter="Q2",
            verification_status=status,
            uploaded_by="u",
        )
        SsaScore.objects.create(
            ssa_record=record, intervention=INTERVENTION, score=score
        )
        return record

    def test_the_latest_confirmed_reading_before_the_start_fills_an_empty_baseline(
        self,
    ):
        school = self._school("PB-1")
        enrolment = self._enrol(school)
        self._ssa(school, date(2025, 11, 1), 4.0)
        chosen = self._ssa(school, date(2026, 2, 1), 5.0)
        self._ssa(school, date(2026, 2, 15), 9.0, status="pending")
        self._ssa(
            school, date(2026, 4, 1), 8.0
        )  # after the start: judges, never a baseline
        deleted = self._ssa(school, date(2026, 2, 20), 3.0)
        deleted.soft_delete()

        self.assertEqual(
            baselines.baseline_states([enrolment])[enrolment.id], baselines.NOT_CAPTURED
        )
        self.assertEqual(baselines.capture_missing_baselines(), 1)
        enrolment.refresh_from_db()
        self.assertEqual(enrolment.baseline_ssa_id, chosen.id)
        self.assertEqual(enrolment.baseline_score, 5.0)
        self.assertEqual(
            baselines.baseline_states([enrolment])[enrolment.id], baselines.CAPTURED
        )

        # Captured once: a later, earlier-dated confirmation never moves it.
        self._ssa(school, date(2026, 2, 25), 6.0)
        self.assertEqual(baselines.capture_missing_baselines(), 0)
        enrolment.refresh_from_db()
        self.assertEqual(enrolment.baseline_score, 5.0)

    def test_no_confirmed_ssa_is_a_different_finding_from_not_captured(self):
        school = self._school("PB-2")
        enrolment = self._enrol(school)
        self._ssa(school, date(2026, 1, 1), 5.0, status="pending")
        self.assertEqual(
            baselines.baseline_states([enrolment])[enrolment.id],
            baselines.NO_CONFIRMED_SSA,
        )
        self.assertEqual(baselines.capture_missing_baselines(), 0)

    def test_confirming_an_ssa_enqueues_the_capture_and_the_handler_fills_it(self):
        from apps.outbox.models import OutboxEvent
        from apps.ssa.services import verify_record

        school = self._school("PB-3")
        enrolment = self._enrol(school)
        record = self._ssa(school, date(2026, 1, 10), 6.0, status="pending")
        verifier = User.objects.create_user(
            email="pb-ia@t.org",
            name="PB IA",
            roles=["ImpactAssessment"],
            active_role="ImpactAssessment",
            password="x",
            is_active=True,
        )
        StaffProfile.objects.create(user=verifier, title="IA", country="Uganda")
        verify_record(record, verifier)
        event = OutboxEvent.objects.get(event_type=baselines.EVENT)
        baselines.handle_baseline_capture(event.payload)
        enrolment.refresh_from_db()
        self.assertEqual(enrolment.baseline_score, 6.0)

    def test_the_command_is_idempotent_and_has_a_dry_run(self):
        school = self._school("PB-4")
        enrolment = self._enrol(school)
        self._ssa(school, date(2026, 1, 5), 7.0)
        out = StringIO()
        call_command("capture_project_baselines", "--dry-run", stdout=out)
        self.assertIn("1 enrolment(s) can take a baseline now", out.getvalue())
        enrolment.refresh_from_db()
        self.assertIsNone(enrolment.baseline_score)
        call_command("capture_project_baselines", stdout=StringIO())
        call_command("capture_project_baselines", stdout=StringIO())
        enrolment.refresh_from_db()
        self.assertEqual(enrolment.baseline_score, 7.0)
