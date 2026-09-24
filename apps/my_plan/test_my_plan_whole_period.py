"""My Plan's own tables show the whole period, not a page of it.

The owner's decision (2026-09-16, recorded in
apps/system_health/test_table_inventory.py): the School Visits, Trainings,
Cluster Meetings and Programme Activities cards show a person's plan arranged
by month, and a pager puts the thing the page exists for behind "Next". They
are bounded by what one officer can do in a year.

The 2026-09-24 audit paged them at ten after measuring 3.0 MB of HTML for one
officer — on a stress estate that gave each of twenty officers ~2,500 schools.
On the realistic estate (~330 schools and ~490 planned activities per
officer) the unpaged page is 174 KB, smaller than the paged one, so the pager
bought nothing real and overrode the owner. It is gone again; these tests pin
the owner's design.
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
VISITS = 13


class MyPlanShowsTheWholePeriodTest(TestCase):
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

    def test_every_visit_of_the_period_is_drawn_without_a_pager(self):
        response = self.client.get(f"/my-plan?fy={FY}")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        drawn = [n for n in range(1, VISITS + 1) if f"Paged visit {n:02d}" in body]
        self.assertEqual(len(drawn), VISITS)
        self.assertNotIn('aria-label="School visit pages"', body)
        self.assertNotIn("school_visits_page=", body)

    def test_the_export_still_carries_every_visit(self):
        response = self.client.get(f"/my-plan?fy={FY}&export=csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode().count("School Visit"), VISITS)
