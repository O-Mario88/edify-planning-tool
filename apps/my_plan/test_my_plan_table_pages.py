"""My Plan's tables show fifty rows and page the rest.

The owner's decision (2026-09-26) replaces the 2026-09-16 one that left the
School Visits, Trainings, Cluster Meetings and Programme Activities cards
unpaged: every table on My Plan pages its rows behind the shared table pager —
fifty to a page, as every table in the platform (owner, 2026-10-02; it was
twenty). The CSV export is unaffected and still carries the whole
period.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.core.fy import get_fy_date_range, get_operational_fy, get_quarter_for_date
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()

# From tomorrow, spread over what is left of its year: a visit dated before
# today is no longer drawn (the first one, dated 5 October, went missing on the
# sixth), and one dated past 30 September belongs to the next year's plan.
FIRST = timezone.localdate() + timedelta(days=1)
FY = get_operational_fy(FIRST)
VISITS = 55
PAGE_SIZE = 50


class MyPlanPagesItsTablesAtFiftyTest(TestCase):
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
        last = (get_fy_date_range(FY)[1] - timedelta(days=1)).date()
        step = max(1, (last - FIRST).days // VISITS)
        for n in range(VISITS):
            planned = FIRST + timedelta(days=step * n)
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

    def test_the_first_page_draws_fifty_visits_and_a_pager(self):
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
