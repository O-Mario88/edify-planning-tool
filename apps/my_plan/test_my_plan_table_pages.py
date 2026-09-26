"""My Plan's tables show twenty rows and page the rest.

The owner's decision (2026-09-26) replaces the 2026-09-16 one that left the
School Visits, Trainings, Cluster Meetings and Programme Activities cards
unpaged: every table on My Plan now shows twenty rows with the rest behind the
shared table pager. The CSV export is unaffected and still carries the whole
period.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.core.fy import get_quarter_for_date
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()

FY = "2027"
VISITS = 25
PAGE_SIZE = 20


class MyPlanPagesItsTablesAtTwentyTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="MPP Region")
        district = District.objects.create(name="MPP District", region=region)
        cls.user = User.objects.create(
            id="mpp-cceo",
            email="mpp-cceo@edify.org",
            name="MPP Officer",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        profile = StaffProfile.objects.create(
            id="mpp-cceo-sp", user=cls.user, title="CCEO", country="Uganda"
        )
        school = School.objects.create(
            school_id="MPP-1",
            name="Paging Hill Primary",
            region=region,
            district=district,
            account_owner_id=profile.id,
        )
        first = date(2026, 10, 5)
        for n in range(VISITS):
            planned = first + timedelta(days=7 * n)
            Activity.objects.create(
                activity_type="school_visit",
                activity_purpose_text=f"Paged visit {n + 1:02d}",
                school=school,
                responsible_staff_id=profile.id,
                delivery_type="staff",
                status="scheduled",
                planned_date=planned,
                fy=FY,
                quarter=get_quarter_for_date(planned),
            )

    def setUp(self):
        self.client.force_login(self.user)

    def _drawn(self, body):
        return [n for n in range(1, VISITS + 1) if f"Paged visit {n:02d}" in body]

    def test_the_first_page_draws_twenty_visits_and_a_pager(self):
        response = self.client.get(f"/my-plan?fy={FY}")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertEqual(len(self._drawn(body)), PAGE_SIZE)
        self.assertIn('aria-label="School visit pages"', body)
        self.assertIn("school_visits_page=2", body)

    def test_the_second_page_draws_the_rest(self):
        response = self.client.get(f"/my-plan?fy={FY}&school_visits_page=2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            len(self._drawn(response.content.decode())), VISITS - PAGE_SIZE
        )

    def test_the_export_still_carries_every_visit(self):
        response = self.client.get(f"/my-plan?fy={FY}&export=csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode().count("School Visit"), VISITS)
