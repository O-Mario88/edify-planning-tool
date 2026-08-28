from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.geography.models import District, Region
from apps.schools.models import School


class ScheduleSchoolLookupTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="schedule-lookup@edify.test",
            password="password123",
            name="Schedule Lookup",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        StaffProfile.objects.create(id="schedule-lookup-staff", user=cls.user)
        region = Region.objects.create(name="Schedule Lookup Region")
        district = District.objects.create(
            name="Schedule Lookup District", region=region
        )
        School.objects.bulk_create(
            [
                School(
                    school_id=f"SCHEDULE-LOOKUP-{index:03d}",
                    name=f"Schedule Lookup Academy {index:03d}",
                    region=region,
                    district=district,
                )
                for index in range(40)
            ]
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_schedule_page_does_not_render_the_whole_school_directory(self):
        response = self.client.get("/planning/schedule?action=visit")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.count(b"<option"), 12)
        self.assertContains(response, 'hx-get="/planning/schedule/schools"')

    def test_schedule_school_lookup_is_bounded(self):
        response = self.client.get(
            "/planning/schedule/schools", {"school_id": "SCHEDULE-LOOKUP"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.count(b"<option"), 25)
        self.assertContains(response, 'value="SCHEDULE-LOOKUP-000"')
        self.assertNotContains(response, 'value="SCHEDULE-LOOKUP-039"')
