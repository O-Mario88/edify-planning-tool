from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.core.enums import SsaIntervention
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School
from apps.ssa.models import SsaRecord


class ManualSchoolAndSsaEntryTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Manual Entry Region")
        self.district = District.objects.create(
            name="Manual Entry District",
            region=self.region,
        )
        self.sub_county = SubCounty.objects.create(
            name="Manual Entry Sub-county",
            district=self.district,
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
        # Manual school entry now requires naming an active CCEO/Program
        # Lead as the school's account owner.
        from apps.accounts.models import StaffProfile

        self.cceo_staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")

    def _school_payload(self, **overrides):
        payload = {
            "school_id": "1042",
            "name": "Manual Hope Academy",
            "district_id": self.district.id,
            "school_type": "client",
            "enrollment": "275",
            "account_owner_id": self.cceo_staff.id,
            # Required since adding a school opened up beyond IA: the id is
            # what proves the school reached Salesforce first, and it is the
            # duplicate check. See SalesforceIdRequiredTests below.
            "salesforce_account_id": "0011A00001Manual",
        }
        payload.update(overrides)
        return payload

    def _ssa_payload(self, school_id, **overrides):
        payload = {
            "school_id": school_id,
            "date_of_ssa": timezone.localdate().isoformat(),
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

    def test_manual_school_can_save_reference_sub_county(self):
        self.client.force_login(self.ia)

        response = self.client.post(
            "/schools/add-school",
            self._school_payload(sub_county_id=self.sub_county.id),
        )

        self.assertRedirects(response, "/schools", fetch_redirect_response=False)
        school = School.objects.get(school_id="1042")
        self.assertEqual(school.sub_county, self.sub_county)

    def test_sub_county_options_are_loaded_for_selected_district(self):
        self.client.force_login(self.ia)

        response = self.client.get(
            "/schools/sub-counties",
            {"district_id": self.district.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.sub_county.name)
        self.assertContains(response, f'value="{self.sub_county.id}"')

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
        self.assertIsNone(record.new_enrollment)
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
        self.assertNotContains(response, 'name="new_enrollment"')
        self.assertContains(response, "SSA Enrolment score out of 10")
        for code, _label in SsaIntervention.choices:
            self.assertContains(response, f'name="score_{code}"')

    def test_ssa_template_uses_enrolment_only_as_a_score(self):
        self.client.force_login(self.ia)

        response = self.client.get("/ssa/upload/template")

        self.assertEqual(response.status_code, 200)
        header = response.content.decode("utf-8").splitlines()[0]
        self.assertNotIn("New Enrolment", header)
        self.assertIn("Enrolment (0-10)", header)

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

    def test_ssa_authorship_stays_with_impact_assessment(self):
        """A CCEO may record a school it met; it may not author an assessment.

        These were one test because both were IA-only. Adding a school opened
        up — the control there is the Salesforce id rather than the role — but
        an SSA record is a verified measurement and its authorship did not
        move with it.
        """
        self.client.force_login(self.cceo)

        ssa_response = self.client.post("/ssa/manual/", self._ssa_payload("1042"))

        self.assertEqual(ssa_response.status_code, 403)

    def test_a_school_cannot_be_added_without_a_salesforce_id(self):
        """The id is the control that replaced the role, so it has to hold."""
        self.client.force_login(self.ia)
        payload = self._school_payload()
        payload["salesforce_account_id"] = "   "

        self.client.post("/schools/add-school", payload)

        self.assertFalse(School.objects.filter(school_id="1042").exists())

    def test_the_same_salesforce_id_cannot_be_used_twice(self):
        self.client.force_login(self.ia)
        self.client.post("/schools/add-school", self._school_payload())

        self.client.post(
            "/schools/add-school",
            self._school_payload(school_id="1043", name="Second Attempt"),
        )

        # Two people adding the same school from the field collide here
        # instead of minting two records for one school.
        self.assertFalse(School.objects.filter(school_id="1043").exists())

    def test_a_field_officer_may_add_one_school_with_an_id(self):
        self.client.force_login(self.cceo)

        self.client.post(
            "/schools/add-school",
            self._school_payload(
                school_id="1044",
                name="Met At A Cluster Training",
                salesforce_account_id="0011A00001Field",
            ),
        )

        self.assertTrue(School.objects.filter(school_id="1044").exists())
        self.assertEqual(SsaRecord.objects.count(), 0)
