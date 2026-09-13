"""SSA Performance reads the full financial year by default (2026-09-13).

SSA is an annual assessment. Opening the page on the current quarter showed a
portfolio assessed in October as barely assessed in September, and a record
entered with no quarter never counted at all. The default is now the whole
year — the latest confirmed record per school across it, quarter or not — and
the export follows the page.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore


class SsaFullYearTest(TestCase):
    def setUp(self):
        self.fy = get_operational_fy()
        region = Region.objects.create(name="Full Year Region")
        district = District.objects.create(name="Full Year District", region=region)
        self.school = School.objects.create(
            school_id="FY-1",
            name="Year Round P/S",
            region=region,
            district=district,
            current_fy_ssa_status="done",
        )
        self.cceo = self._user("fy-cceo@t.test", EdifyRole.CCEO.value)
        staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        StaffSchoolAssignment.objects.create(staff=staff, school_id=self.school.id)

    def _user(self, email, role):
        return User.objects.create_user(
            email=email,
            name=email.split("@")[0],
            roles=[role],
            active_role=role,
            password="password123",
            is_active=True,
        )

    def _ssa(self, average, *, fy=None, quarter="", days_ago=0):
        record = SsaRecord.objects.create(
            school=self.school,
            fy=fy or self.fy,
            quarter=quarter,
            date_of_ssa=timezone.now() - timedelta(days=days_ago),
            average_score=average,
            verification_status="confirmed",
        )
        SsaScore.objects.bulk_create(
            SsaScore(ssa_record=record, intervention=item.value, score=average)
            for item in SsaIntervention
        )
        return record

    def _dashboard(self, **query):
        client = Client()
        client.force_login(self.cceo)
        response = client.get("/ssa", {"fy": self.fy, **query})
        self.assertEqual(response.status_code, 200)
        return response

    def test_the_page_opens_on_the_full_year_with_its_latest_record(self):
        self._ssa(5.0, quarter="Q1", days_ago=200)
        self._ssa(7.0, quarter="", days_ago=3)  # entered with no quarter

        response = self._dashboard()
        dashboard = response.context["dashboard"]

        self.assertEqual(dashboard["filters"]["quarter"], "fy")
        self.assertTrue(dashboard["filters"]["is_full_year"])
        self.assertEqual(dashboard["kpis"]["assessed"], 1)
        self.assertEqual(dashboard["kpis"]["average_score"], 7.0)
        self.assertContains(
            response, '<option value="fy" selected>Full financial year</option>'
        )

    def test_a_quarter_still_narrows_to_that_quarter(self):
        self._ssa(5.0, quarter="Q1", days_ago=200)
        self._ssa(7.0, quarter="", days_ago=3)

        dashboard = self._dashboard(quarter="Q1").context["dashboard"]

        self.assertFalse(dashboard["filters"]["is_full_year"])
        self.assertEqual(dashboard["kpis"]["average_score"], 5.0)

    def test_a_full_year_is_compared_with_the_year_before(self):
        self._ssa(7.0, quarter="Q2", days_ago=10)
        self._ssa(6.0, fy=str(int(self.fy) - 1), quarter="Q4", days_ago=400)

        kpis = self._dashboard().context["dashboard"]["kpis"]

        self.assertEqual(kpis["average_delta"], 1.0)
        self.assertEqual(
            kpis["comparison_label"],
            f"FY {int(self.fy) - 2}/{str(int(self.fy) - 1)[-2:]}",
        )

    def test_the_export_follows_the_period(self):
        self._ssa(7.0, quarter="", days_ago=3)
        admin = self._user("fy-admin@t.test", EdifyRole.ADMIN.value)
        client = Client()
        client.force_login(admin)

        full_year = client.get("/ssa/export", {"fy": self.fy})
        quarter = client.get("/ssa/export", {"fy": self.fy, "quarter": "Q1"})

        self.assertIn("full-year", full_year["Content-Disposition"])
        self.assertContains(full_year, "Year Round P/S")
        self.assertIn("-q1.csv", quarter["Content-Disposition"])
        self.assertNotContains(quarter, "Year Round P/S")
