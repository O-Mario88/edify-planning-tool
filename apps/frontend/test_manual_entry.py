from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.core.enums import SsaIntervention
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord


class ManualSchoolAndSsaEntryTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Manual Entry Region")
        self.district = District.objects.create(
            name="Manual Entry District",
            region=self.region,
        )
        self.ia = User.objects.create_user(
            email="ia-manual-entry@example.org",
            name="Manual Entry IA",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
            password="test-password",
        )
        self.cceo = User.objects.create_user(
            email="cceo-manual-entry@example.org",
            name="Manual Entry CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="test-password",
        )

    def _school_payload(self, **overrides):
        payload = {
            "school_id": "1042",
            "name": "Manual Hope Academy",
            "district_id": self.district.id,
            "school_type": "client",
            "enrollment": "275",
        }
        payload.update(overrides)
        return payload

    def _ssa_payload(self, school_id, **overrides):
        payload = {
            "school_id": school_id,
            "date_of_ssa": timezone.localdate().isoformat(),
            "new_enrollment": "280",
        }
        payload.update(
            {
                f"score_{code}": str(index)
                for index, (code, _label) in enumerate(
                    SsaIntervention.choices,
                    start=1,
                )
            }
        )
        payload.update(overrides)
        return payload

    def test_manual_school_is_saved_with_exact_official_id(self):
        self.client.force_login(self.ia)

        response = self.client.post("/schools/add-school", self._school_payload())

        self.assertRedirects(response, "/schools", fetch_redirect_response=False)
        school = School.objects.get(school_id="1042")
        self.assertEqual(school.name, "Manual Hope Academy")
        self.assertEqual(school.district, self.district)
        self.assertEqual(school.region, self.region)
        self.assertEqual(school.enrollment, 275)
        self.assertTrue(school.created_by_ia)
        self.assertFalse(School.objects.filter(school_id="S-1042").exists())

    def test_save_school_and_add_ssa_prefills_new_school(self):
        self.client.force_login(self.ia)
        payload = self._school_payload(next="ssa")

        response = self.client.post("/schools/add-school", payload)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/ssa/manual/?school_id=1042")
        self.assertTrue(School.objects.filter(school_id="1042").exists())

    def test_manual_ssa_form_saves_record_and_all_eight_scores(self):
        school = School.objects.create(
            school_id="SSA-1042",
            name="SSA Manual Academy",
            district=self.district,
            region=self.region,
        )
        self.client.force_login(self.ia)

        response = self.client.post(
            "/ssa/manual/",
            self._ssa_payload(school.school_id),
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"/schools/{school.id}#ssa-timeline")
        record = SsaRecord.objects.get(school=school)
        self.assertEqual(record.scores.count(), 8)
        self.assertEqual(record.collector_type, "ia")
        self.assertEqual(record.verification_status, "confirmed")
        self.assertEqual(record.new_enrollment, 280)
        self.assertEqual(record.average_score, 4.5)
        school.refresh_from_db()
        self.assertEqual(school.current_fy_ssa_status, "done")

    def test_manual_ssa_form_prefills_school_and_renders_all_scores(self):
        school = School.objects.create(
            school_id="SSA-PREFILL",
            name="Prefilled SSA Academy",
            district=self.district,
            region=self.region,
        )
        self.client.force_login(self.ia)

        response = self.client.get(f"/ssa/manual/?school_id={school.school_id}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="SSA-PREFILL"')
        for code, _label in SsaIntervention.choices:
            self.assertContains(response, f'name="score_{code}"')

    def test_manual_ssa_rejects_duplicate_assessment_date(self):
        school = School.objects.create(
            school_id="SSA-DUPLICATE",
            name="Duplicate SSA Academy",
            district=self.district,
            region=self.region,
        )
        self.client.force_login(self.ia)
        payload = self._ssa_payload(school.school_id)
        first_response = self.client.post("/ssa/manual/", payload)
        self.assertEqual(first_response.status_code, 302)

        duplicate_response = self.client.post("/ssa/manual/", payload)

        self.assertEqual(duplicate_response.status_code, 200)
        self.assertContains(duplicate_response, "already exists")
        self.assertEqual(SsaRecord.objects.filter(school=school).count(), 1)

    def test_manual_ssa_allows_follow_up_on_another_date_in_same_fy(self):
        school = School.objects.create(
            school_id="SSA-FOLLOW-UP",
            name="Follow-up SSA Academy",
            district=self.district,
            region=self.region,
        )
        self.client.force_login(self.ia)
        first_payload = self._ssa_payload(school.school_id)
        first_response = self.client.post("/ssa/manual/", first_payload)
        self.assertEqual(first_response.status_code, 302)

        follow_up_payload = self._ssa_payload(
            school.school_id,
            date_of_ssa=(timezone.localdate() - timedelta(days=1)).isoformat(),
        )
        follow_up_response = self.client.post("/ssa/manual/", follow_up_payload)

        self.assertEqual(follow_up_response.status_code, 302)
        self.assertEqual(SsaRecord.objects.filter(school=school).count(), 2)

    def test_manual_ssa_rejects_out_of_range_score(self):
        school = School.objects.create(
            school_id="SSA-INVALID",
            name="Invalid SSA Academy",
            district=self.district,
            region=self.region,
        )
        self.client.force_login(self.ia)
        first_code = SsaIntervention.choices[0][0]

        response = self.client.post(
            "/ssa/manual/",
            self._ssa_payload(
                school.school_id,
                **{f"score_{first_code}": "11"},
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ensure this value is less than or equal to 10")
        self.assertFalse(SsaRecord.objects.filter(school=school).exists())

    def test_non_upload_roles_cannot_create_authoritative_records(self):
        self.client.force_login(self.cceo)

        school_response = self.client.post(
            "/schools/add-school",
            self._school_payload(),
        )
        ssa_response = self.client.post(
            "/ssa/manual/",
            self._ssa_payload("1042"),
        )

        self.assertEqual(school_response.status_code, 403)
        self.assertEqual(ssa_response.status_code, 403)
        self.assertFalse(School.objects.filter(school_id="1042").exists())
        self.assertEqual(SsaRecord.objects.count(), 0)
