from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity, ClosureBlocker
from apps.geography.models import District, Region
from apps.schools.models import School


class BlockedClosurePaginationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="closure-page@edify.test",
            password="password123",
            name="Closure Page",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        StaffProfile.objects.create(id="closure-page-staff", user=cls.user)
        region = Region.objects.create(name="Closure Pagination Region")
        district = District.objects.create(
            name="Closure Pagination District", region=region
        )
        school = School.objects.create(
            school_id="CLOSURE-PAGE-SCHOOL",
            name="Closure Pagination School",
            region=region,
            district=district,
        )
        activities = [
            Activity(
                activity_type="visit",
                school=school,
                status="closed",
                responsible_staff_id=cls.user.user_id,
            )
            for _ in range(35)
        ]
        Activity.objects.bulk_create(activities)
        ClosureBlocker.objects.bulk_create(
            [
                ClosureBlocker(
                    activity=activity,
                    blocking_reason="Evidence required",
                    responsible_role="CCEO",
                )
                for activity in activities
            ]
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_only_one_bounded_page_of_blockers_is_rendered(self):
        response = self.client.get("/activities/closure/blocked")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.count(b"Resolve Blocker"), 10)
        self.assertContains(response, "Showing 1–10 of 35")
        self.assertContains(response, 'aria-label="Next page"')

    def test_page_parameter_reaches_the_next_window_without_duplicates(self):
        first = self.client.get("/activities/closure/blocked?blockers_page=1")
        second = self.client.get("/activities/closure/blocked?blockers_page=2")

        self.assertEqual(first.content.count(b"Resolve Blocker"), 10)
        self.assertEqual(second.content.count(b"Resolve Blocker"), 10)
        self.assertContains(second, "Showing 11–20 of 35")
