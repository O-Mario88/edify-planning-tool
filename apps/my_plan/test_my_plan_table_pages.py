"""My Plan's own tables draw one page at a time (PERF-05).

My Plan defaults to the whole fiscal year (owner decision, kept). Its school
visit, training, cluster meeting and programme activity tables drew every row
of it: 3.0 MB of HTML for one field officer at 50,000 schools, which a
mid-range phone parses and lays out before the first tap works. The core
school tables beside them already paged at ten; these now use the same pager.
The period, the filters and the export are unchanged: the export still
carries the whole filtered plan.
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


class MyPlanTablePagesTest(TestCase):
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

    def test_the_first_page_draws_ten_visits_and_says_how_many_there_are(self):
        response = self.client.get(f"/my-plan?fy={FY}")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        drawn = [n for n in range(1, VISITS + 1) if f"Paged visit {n:02d}" in body]
        self.assertEqual(len(drawn), 10)
        self.assertIn(f"of {VISITS}", body)
        self.assertIn('aria-label="School visit pages"', body)
        self.assertEqual(len(response.context["school_visits"]), VISITS)

    def test_the_next_page_draws_the_rest_and_keeps_the_filters(self):
        response = self.client.get(f"/my-plan?fy={FY}&school_visits_page=2")
        body = response.content.decode()
        drawn = [n for n in range(1, VISITS + 1) if f"Paged visit {n:02d}" in body]
        self.assertEqual(len(drawn), VISITS - 10)
        self.assertIn(f"fy={FY}", body)

    def test_the_export_still_carries_every_visit(self):
        response = self.client.get(f"/my-plan?fy={FY}&export=csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode().count("School Visit"), VISITS)
