from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.analytics.subcounty_insight import boundary_key, subcounty_insight
from apps.audit.models import AuditLog
from apps.geography.models import District, Parish, Region, SubCounty
from apps.schools.models import School


class SchoolProfileEditTest(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            id="school-profile-editor",
            email="school-profile-editor@edify.test",
            name="School Profile Editor",
            roles=["CCEO"],
            active_role="CCEO",
            password="test-password",
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(
            id="school-profile-staff",
            user=self.user,
            title="CCEO",
        )
        self.region = Region.objects.create(name="School Profile Region")
        self.district = District.objects.create(
            name="School Profile District",
            region=self.region,
        )
        self.sub_county = SubCounty.objects.create(
            name="Kira",
            district=self.district,
        )
        self.other_sub_county = SubCounty.objects.create(
            name="Namagunga",
            district=self.district,
        )
        self.parish = Parish.objects.create(
            name="Kira Parish",
            sub_county=self.sub_county,
        )
        self.other_parish = Parish.objects.create(
            name="Namagunga Parish",
            sub_county=self.other_sub_county,
        )
        self.school = School.objects.create(
            school_id="PROFILE-101",
            name="Profile School",
            region=self.region,
            district=self.district,
            school_type="client",
        )
        StaffSchoolAssignment.objects.create(
            staff=self.staff,
            school_id=self.school.id,
        )
        self.client.force_login(self.user)
        self.edit_url = reverse(
            "frontend:school_edit_drawer",
            args=[self.school.id],
        )

    def _valid_payload(self, **overrides):
        payload = {
            "name": self.school.name,
            "school_phone": "",
            "primary_contact_name": "",
            "director_name": "",
            "headteacher_name": "",
            "enrollment": "425",
            "sub_county_id": self.sub_county.id,
            "parish_id": self.parish.id,
            "latitude": "0.347596",
            "longitude": "32.582520",
            "shipping_address": "Kira, Uganda",
            "cluster_id": "",
            "account_owner_id": "",
        }
        payload.update(overrides)
        return payload

    def test_edit_drawer_exposes_structured_location_and_enrolment_fields(self):
        response = self.client.get(self.edit_url)

        self.assertEqual(response.status_code, 200)
        for field in (
            "enrollment",
            "sub_county_id",
            "parish_id",
            "latitude",
            "longitude",
        ):
            self.assertContains(response, f'name="{field}"')
        self.assertContains(response, self.sub_county.name)
        self.assertContains(response, self.parish.name)

    def test_staff_can_save_enrolment_geography_and_coordinates(self):
        response = self.client.post(self.edit_url, self._valid_payload())

        self.assertEqual(response.status_code, 200)
        self.school.refresh_from_db()
        self.assertEqual(self.school.enrollment, 425)
        self.assertEqual(self.school.sub_county_id, self.sub_county.id)
        self.assertEqual(self.school.parish_id, self.parish.id)
        self.assertAlmostEqual(self.school.latitude, 0.347596)
        self.assertAlmostEqual(self.school.longitude, 32.582520)
        self.assertIsNotNone(self.school.last_enrollment_date)
        audit = AuditLog.objects.filter(
            action="school.profile_updated",
            subject_id=self.school.id,
        ).latest("seq")
        self.assertCountEqual(
            audit.payload["changed_fields"],
            [
                "enrollment",
                "sub_county_id",
                "parish_id",
                "latitude",
                "longitude",
            ],
        )

    def test_coordinate_pair_is_server_validated(self):
        response = self.client.post(
            self.edit_url,
            self._valid_payload(latitude="0.347596", longitude=""),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Enter both latitude and longitude, or leave both blank.",
        )
        self.school.refresh_from_db()
        self.assertIsNone(self.school.latitude)
        self.assertIsNone(self.school.longitude)

    def test_parish_must_belong_to_selected_sub_county(self):
        response = self.client.post(
            self.edit_url,
            self._valid_payload(parish_id=self.other_parish.id),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Select a parish within the selected sub-county.",
        )
        self.school.refresh_from_db()
        self.assertIsNone(self.school.sub_county_id)
        self.assertIsNone(self.school.parish_id)

    def test_profile_page_displays_the_saved_location_details(self):
        self.client.post(self.edit_url, self._valid_payload())

        response = self.client.get(
            reverse("frontend:school_detail", args=[self.school.school_id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pupil Enrolment")
        self.assertContains(response, "425")
        self.assertContains(response, self.sub_county.name)
        self.assertContains(response, self.parish.name)
        self.assertContains(response, "0.347596, 32.582520")

    def test_profile_subcounty_save_moves_the_live_map_aggregate(self):
        self.client.post(self.edit_url, self._valid_payload())
        before = subcounty_insight(schools=School.objects.filter(pk=self.school.pk))
        self.assertEqual(
            {entry["key"] for entry in before["entries"]},
            {boundary_key(self.district.name, self.sub_county.name)},
        )

        response = self.client.post(
            self.edit_url,
            self._valid_payload(
                sub_county_id=self.other_sub_county.id,
                parish_id=self.other_parish.id,
            ),
        )

        self.assertEqual(response.status_code, 200)
        after = subcounty_insight(schools=School.objects.filter(pk=self.school.pk))
        self.assertEqual(
            {entry["key"] for entry in after["entries"]},
            {boundary_key(self.district.name, self.other_sub_county.name)},
        )
