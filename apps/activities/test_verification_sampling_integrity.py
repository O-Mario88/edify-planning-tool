"""Sample checks drawn per country, SSA records sampled too, and a dispute that
changes something (IA review, owner, 2026-09-13)."""

from __future__ import annotations

from datetime import date, timedelta

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities import verification_sampling as S
from apps.activities.ia_models import VerificationHistory, VerificationSample
from apps.activities.models import Activity
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord

LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "ia-sample-checks",
    }
}


def _user(email, role, country="Uganda", name=None):
    user = User.objects.create_user(
        email=email,
        name=name or email.split("@")[0],
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    StaffProfile.objects.create(user=user, title=role, country=country)
    return user


@override_settings(IA_VERIFICATION_SAMPLE_SHARE_PCT=100, CACHES=LOCMEM)
class SampleIntegrityTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        ug = Region.objects.create(name="VS Central", country="Uganda")
        ke = Region.objects.create(name="VS Rift", country="Kenya")
        cls.ug_school = School.objects.create(
            school_id="VS-UG",
            name="VS Kampala",
            region=ug,
            district=District.objects.create(name="VS Wakiso", region=ug),
        )
        cls.ke_school = School.objects.create(
            school_id="VS-KE",
            name="VS Nakuru",
            region=ke,
            district=District.objects.create(name="VS Nakuru D", region=ke),
        )
        cls.ia = _user("vs-ia@t.org", EdifyRole.IMPACT_ASSESSMENT.value, name="Ida")
        cls.ia2 = _user("vs-ia2@t.org", EdifyRole.IMPACT_ASSESSMENT.value, name="Ivan")
        cls.ke_ia = _user("vs-ke@t.org", EdifyRole.IMPACT_ASSESSMENT.value, "Kenya")
        cls.cceo = _user("vs-cceo@t.org", EdifyRole.CCEO.value, name="Cara")

    def _verified_activity(self, school, verifier):
        activity = Activity.objects.create(
            activity_type="school_visit",
            status="ia_verified",
            school=school,
            fy="2026",
            planned_date=date(2026, 5, 1),
            responsible_staff_id=self.cceo.staff_profile.id,
        )
        VerificationHistory.objects.create(
            activity=activity, verified_by=verifier.id, verified_at=timezone.now()
        )
        return activity

    def _confirmed_ssa(self, school, verifier, collector=None, day=1):
        collector = collector or self.cceo
        return SsaRecord.objects.create(
            school=school,
            date_of_ssa=timezone.now() - timedelta(days=day),
            fy="2026",
            quarter="Q4",
            verification_status="confirmed",
            verified_by_user_id=verifier.id,
            verified_at=timezone.now(),
            uploaded_by=collector.id,
            collected_by_user_id=collector.id,
        )

    def test_each_country_draws_once_a_day_without_blocking_another(self):
        self._verified_activity(self.ug_school, self.ia)
        ke_activity = self._verified_activity(self.ke_school, self.ke_ia)
        self.assertEqual(S.draw_samples(days=7, country="Uganda"), 1)
        self.assertEqual(S.draw_samples(days=7, country="Uganda"), 0)
        self.assertEqual(S.draw_samples(days=7, country="Kenya"), 1)
        self.assertTrue(
            VerificationSample.objects.filter(activity=ke_activity).exists()
        )
        self.assertEqual(S.draw_samples(days=7), 0)

    def test_confirmed_ssa_records_are_sampled_too(self):
        record = self._confirmed_ssa(self.ug_school, self.ia)
        self.assertEqual(S.draw_samples(days=7), 1)
        sample = VerificationSample.objects.get(ssa_record=record)
        self.assertEqual(sample.subject_type, S.SUBJECT_SSA)
        self.assertEqual(sample.original_verifier, self.ia.id)

    def test_a_disputed_ssa_returns_to_its_collector_and_records_the_qa_review(self):
        record = self._confirmed_ssa(self.ug_school, self.ia)
        S.draw_samples(days=7)
        sample = VerificationSample.objects.get(ssa_record=record)
        with self.assertRaises(Forbidden):
            S.record_outcome(sample.id, "disputed", "Scores copied", self.ia)
        with self.assertRaises(Forbidden):
            S.record_outcome(sample.id, "disputed", "Scores copied", self.ke_ia)
        S.record_outcome(
            sample.id, "disputed", "Scores copied from last year", self.ia2
        )
        record.refresh_from_db()
        self.assertEqual(record.verification_status, "returned")
        self.assertIn("Sample check disputed", record.return_reason)
        self.assertEqual(record.qa_reviewed_by_user_id, self.ia2.id)

    def test_a_disputed_activity_leaves_analytics_until_the_dispute_is_resolved(self):
        activity = self._verified_activity(self.ug_school, self.ia)
        S.draw_samples(days=7)
        sample = VerificationSample.objects.get(activity=activity)
        S.record_outcome(sample.id, "disputed", "Attendance sheet was blank", self.ia2)
        self.assertIn(
            activity.id,
            set(S.excluded_activity_ids().values_list("activity_id", flat=True)),
        )
        with self.assertRaises(BadRequest):
            S.resolve_dispute(sample.id, "", self.ia2)
        with self.assertRaises(Forbidden):
            S.resolve_dispute(sample.id, "Re-filed", self.ia)
        S.resolve_dispute(sample.id, "Attendance re-filed and checked", self.ia2)
        self.assertFalse(
            S.excluded_activity_ids().filter(activity_id=activity.id).exists()
        )
        with self.assertRaises(BadRequest):
            S.resolve_dispute(sample.id, "Again", self.ia2)

    def test_a_field_back_check_opens_the_visit_request_drawer_and_schedules_nothing(
        self,
    ):
        activity = self._verified_activity(self.ug_school, self.ia)
        S.draw_samples(days=7)
        sample = VerificationSample.objects.get(activity=activity)
        self.client.force_login(self.ia2)
        response = self.client.post(f"/ia/samples/{sample.id}/field-check")
        self.assertEqual(response.status_code, 302)
        sample.refresh_from_db()
        self.assertEqual(sample.method, "field")
        page = self.client.get(response["Location"])
        self.assertContains(page, 'hx-get="/planning/schedule-modal?school_id=VS-UG"')
        self.assertEqual(Activity.objects.filter(school=self.ug_school).count(), 1)

    def test_a_pending_samples_decisions_are_one_actions_menu(self):
        """Confirm, Dispute and Field back-check are one Actions menu (owner,
        2026-09-26). Confirm and Dispute carry what the checker found, so the
        menu opens the row's note form for them rather than posting itself."""
        activity = self._verified_activity(self.ug_school, self.ia)
        S.draw_samples(days=7)
        sample = VerificationSample.objects.get(activity=activity)
        self.client.force_login(self.ia2)
        body = self.client.get("/ia/samples/").content.decode()

        self.assertIn("data-row-actions", body)
        for choice, label in (("confirmed", "Confirm"), ("disputed", "Dispute")):
            with self.subTest(label=label):
                self.assertRegex(
                    body,
                    rf'role="menuitem"[^>]*@click="grade = \'{choice}\'[^"]*">{label}</button>',
                )
        self.assertIn(
            f'<form role="none" method="post" action="/ia/samples/{sample.id}/field-check">',
            body,
        )
        self.assertIn('role="menuitem">Field back-check</button>', body)
        # The note stays in the row, in the one form that posts the decision.
        form = body[body.index(f'id="grade-{sample.id}"') :]
        form = form[: form.index("</form>")]
        self.assertIn(f'action="/ia/samples/{sample.id}/outcome"', form)
        self.assertIn('name="note"', form)
        self.assertIn('name="status" :value="grade"', form)
        self.assertNotIn('role="menuitem"', form)

    def test_the_page_lists_the_readers_country_and_costs_the_same_as_it_grows(self):
        self._verified_activity(self.ug_school, self.ia)
        self._verified_activity(self.ke_school, self.ke_ia)
        S.draw_samples(days=7)
        self.client.force_login(self.ia2)
        page = self.client.get("/ia/samples/")
        self.assertContains(page, "VS Kampala")
        self.assertNotContains(page, "VS Nakuru")
        with CaptureQueriesContext(connection) as small:
            self.client.get("/ia/samples/")
        VerificationSample.objects.all().delete()
        for day in range(1, 12):
            self._verified_activity(self.ug_school, self.ia)
            self._confirmed_ssa(self.ug_school, self.ia, day=day)
        S.draw_samples(days=7)
        with CaptureQueriesContext(connection) as large:
            self.client.get("/ia/samples/")
        self.assertEqual(len(large), len(small))

    def test_the_draw_button_draws_the_readers_country_only(self):
        self._verified_activity(self.ug_school, self.ia)
        self._verified_activity(self.ke_school, self.ke_ia)
        self.client.force_login(self.ia)
        self.client.post("/ia/samples/draw")
        self.assertEqual(VerificationSample.objects.count(), 1)
        self.assertEqual(
            VerificationSample.objects.get().activity.school, self.ug_school
        )
