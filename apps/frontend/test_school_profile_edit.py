from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.analytics.subcounty_insight import boundary_key, subcounty_insight
from apps.audit.models import AuditLog
from apps.core.enums import SchoolType
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
            account_owner_id=self.staff.id,
            account_owner_name_raw=self.user.name,
            account_owner_status="matched",
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
            "school_id": self.school.school_id,
            "name": self.school.name,
            "school_type": "client",
            "school_phone": "",
            "primary_contact_name": "",
            "primary_contact_phone": "",
            "director_name": "",
            "headteacher_name": "",
            "enrollment": "425",
            "last_enrollment_date": "",
            "district_id": self.district.id,
            "sub_county_id": self.sub_county.id,
            "parish_id": self.parish.id,
            "latitude": "0.347596",
            "longitude": "32.582520",
            "shipping_address": "Kira, Uganda",
            "cluster_id": "",
            "account_owner_id": self.staff.id,
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

    def test_directory_school_name_links_to_its_profile(self):
        response = self.client.get(reverse("frontend:schools_directory"))

        self.assertEqual(response.status_code, 200)
        profile_url = reverse("frontend:school_detail", args=[self.school.school_id])
        self.assertContains(response, f'href="{profile_url}"')
        self.assertContains(response, f">{self.school.name}</a>")

    def test_edit_drawer_allows_staff_to_change_the_official_school_id(self):
        new_school_id = "PROFILE-202"

        response = self.client.post(
            self.edit_url,
            self._valid_payload(school_id=new_school_id),
        )

        self.assertEqual(response.status_code, 200)
        self.school.refresh_from_db()
        self.assertEqual(self.school.school_id, new_school_id)
        profile_url = reverse("frontend:school_detail", args=[new_school_id])
        self.assertEqual(response.headers["HX-Redirect"], profile_url)
        self.assertEqual(self.client.get(profile_url).status_code, 200)
        audit = AuditLog.objects.filter(
            action="school.profile_updated",
            subject_id=self.school.id,
        ).latest("seq")
        self.assertIn("school_id", audit.payload["changed_fields"])

    def test_edit_drawer_rejects_a_duplicate_official_school_id(self):
        duplicate = School.objects.create(
            school_id="PROFILE-DUPLICATE",
            name="Another Profile School",
            region=self.region,
            district=self.district,
        )

        response = self.client.post(
            self.edit_url,
            self._valid_payload(school_id=duplicate.school_id),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "That School ID is already in use")
        self.school.refresh_from_db()
        self.assertEqual(self.school.school_id, "PROFILE-101")

    def test_edit_drawer_exposes_all_current_partner_types(self):
        response = self.client.get(self.edit_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Current Partner Type")
        for value, label in SchoolType.choices:
            self.assertContains(response, f'value="{value}"')
            self.assertContains(response, label)
        self.assertNotContains(response, "Potential Core")
        self.assertNotContains(response, "Potential Champion")

    def test_incomplete_upload_can_complete_district_from_profile(self):
        self.school.district = None
        self.school.region = None
        self.school.sub_county = None
        self.school.save(
            update_fields=["district", "region", "sub_county", "updated_at"]
        )

        drawer = self.client.get(self.edit_url)
        self.assertEqual(drawer.status_code, 200)
        self.assertContains(drawer, 'name="district_id"')
        self.assertContains(drawer, self.district.name)

        response = self.client.post(self.edit_url, self._valid_payload())

        self.assertEqual(response.status_code, 200)
        self.school.refresh_from_db()
        self.assertEqual(self.school.district, self.district)
        self.assertEqual(self.school.region, self.region)
        self.assertEqual(self.school.sub_county, self.sub_county)

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
                "last_enrollment_date",
                "sub_county_id",
                "parish_id",
                "latitude",
                "longitude",
                "shipping_address",
            ],
        )

    def test_optional_profile_fields_can_be_completed_manually(self):
        response = self.client.post(
            self.edit_url,
            self._valid_payload(
                school_type="core",
                school_phone="+256 700 111222",
                primary_contact_name="Grace Akello",
                primary_contact_phone="+256 700 333444",
                director_name="Peter Ouma",
                headteacher_name="Sarah Ayaa",
                last_enrollment_date="2026-06-30",
                shipping_address="Plot 4, Kira Road",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.school.refresh_from_db()
        self.assertEqual(self.school.school_type, "core")
        self.assertEqual(self.school.school_phone, "+256 700 111222")
        self.assertEqual(self.school.primary_contact_name, "Grace Akello")
        self.assertEqual(self.school.primary_contact_phone, "+256 700 333444")
        self.assertEqual(self.school.director_name, "Peter Ouma")
        self.assertEqual(self.school.headteacher_name, "Sarah Ayaa")
        self.assertEqual(self.school.last_enrollment_date.isoformat(), "2026-06-30")
        self.assertEqual(self.school.shipping_address, "Plot 4, Kira Road")

    def test_partner_type_change_moves_school_to_matching_directory_category(self):
        response = self.client.post(
            self.edit_url,
            self._valid_payload(school_type=SchoolType.CORE_GRADUATE),
        )

        self.assertEqual(response.status_code, 200)
        self.school.refresh_from_db()
        self.assertEqual(self.school.school_type, SchoolType.CORE_GRADUATE)
        self.assertEqual(self.school.get_school_type_display(), "Core Graduate")

        matching = self.client.get(
            reverse("frontend:schools_directory"),
            {"school_type": SchoolType.CORE_GRADUATE},
        )
        self.assertContains(matching, self.school.name)

        old_category = self.client.get(
            reverse("frontend:schools_directory"),
            {"school_type": SchoolType.CLIENT},
        )
        self.assertNotContains(old_category, self.school.name)

    def test_oversight_quick_edit_uses_the_same_partner_types(self):
        self.user.roles = ["ImpactAssessment"]
        self.user.active_role = "ImpactAssessment"
        self.user.save(update_fields=["roles", "active_role", "updated_at"])
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("frontend:school_change_type", args=[self.school.id]),
            {"school_type": SchoolType.CORE_TRAINED},
        )

        self.assertEqual(response.status_code, 200)
        self.school.refresh_from_db()
        self.assertEqual(self.school.school_type, SchoolType.CORE_TRAINED)

    def test_staff_name_is_required_when_saving_profile(self):
        response = self.client.post(
            self.edit_url,
            self._valid_payload(account_owner_id=""),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Staff Name is required")
        self.school.refresh_from_db()
        self.assertEqual(self.school.account_owner_id, self.staff.id)

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

    def test_profile_page_displays_completed_optional_contact_fields(self):
        self.client.post(
            self.edit_url,
            self._valid_payload(
                school_phone="+256 700 111222",
                primary_contact_name="Grace Akello",
                primary_contact_phone="+256 700 333444",
                director_name="Peter Ouma",
                headteacher_name="Sarah Ayaa",
                last_enrollment_date="2026-06-30",
                shipping_address="Plot 4, Kira Road",
            ),
        )

        response = self.client.get(
            reverse("frontend:school_detail", args=[self.school.school_id])
        )

        self.assertEqual(response.status_code, 200)
        for value in (
            "+256 700 111222",
            "Grace Akello",
            "+256 700 333444",
            "Peter Ouma",
            "Sarah Ayaa",
            "30 Jun 2026",
            "Plot 4, Kira Road",
        ):
            self.assertContains(response, value)

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

        live_response = self.client.get(
            reverse("frontend:map_subcounty_metrics"),
            {"district_id": self.district.id, "fy": "2026"},
        )
        self.assertEqual(live_response.status_code, 200)
        self.assertEqual(live_response.headers["Cache-Control"], "private, no-store")
        self.assertEqual(
            {entry["key"] for entry in live_response.json()["entries"]},
            {boundary_key(self.district.name, self.other_sub_county.name)},
        )

    def test_live_map_location_refresh_rejects_invalid_geography(self):
        missing = self.client.get(
            reverse("frontend:map_subcounty_metrics"),
            {"district_id": "missing", "fy": "2026"},
        )
        self.assertEqual(missing.status_code, 404)

        invalid_fy = self.client.get(
            reverse("frontend:map_subcounty_metrics"),
            {"district_id": self.district.id, "fy": "FY2026"},
        )
        self.assertEqual(invalid_fy.status_code, 400)


class SchoolManualOnboardRequiredFieldsTest(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.ia = user_model.objects.create_user(
            email="ia-school-onboard@edify.test",
            name="School Onboarding IA",
            roles=["ImpactAssessment"],
            active_role="ImpactAssessment",
            password="test-password",
            is_active=True,
        )
        owner_user = user_model.objects.create_user(
            email="owner-school-onboard@edify.test",
            name="School Owner",
            roles=["CCEO"],
            active_role="CCEO",
            password="test-password",
            is_active=True,
        )
        self.owner = StaffProfile.objects.create(
            user=owner_user,
            title="CCEO",
        )
        self.region = Region.objects.create(name="Onboarding Region")
        self.district = District.objects.create(
            name="Onboarding District",
            region=self.region,
        )
        self.client.force_login(self.ia)
        self.url = reverse("frontend:school_onboard_drawer")

    def _payload(self, **overrides):
        payload = {
            "school_id": "ONBOARD-101",
            "name": "Onboard Primary",
            "district_id": self.district.id,
            "account_owner_id": self.owner.id,
            "school_type": "client",
            "enrollment": "",
            "cluster_id": "",
        }
        payload.update(overrides)
        return payload

    def test_manual_onboarding_requires_and_assigns_staff_name(self):
        response = self.client.post(self.url, self._payload())

        self.assertEqual(response.status_code, 200)
        school = School.objects.get(school_id="ONBOARD-101")
        self.assertEqual(school.account_owner_id, self.owner.id)
        self.assertEqual(school.account_owner_name_raw, "School Owner")
        self.assertTrue(
            StaffSchoolAssignment.objects.filter(
                staff=self.owner,
                school_id=school.id,
            ).exists()
        )

    def test_manual_onboarding_rejects_missing_staff_name(self):
        response = self.client.post(
            self.url,
            self._payload(account_owner_id=""),
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            "Select a valid CCEO or Program Lead as Staff Name.",
            status_code=400,
        )
        self.assertFalse(School.objects.filter(school_id="ONBOARD-101").exists())
