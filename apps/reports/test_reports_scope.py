"""Regression: list_reports()/get_one() returned EVERY generated report to
ANY role holding analytics.view — nearly every role in the app (CCEO, PL, IA,
Accountant, PC included), leaking other teams'/other roles' report contents
country-wide. Country-scope roles (CD/RVP/Admin) legitimately see everything;
everyone else must only see reports they personally generated.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.accounts.jwt import issue_access_token
from apps.accounts.models import Report
from apps.core.rbac import EdifyRole

User = get_user_model()


class ReportsScopeTest(APITestCase):
    def setUp(self):
        self.cceo = User.objects.create_user(
            email="cceo-reports@test.org",
            name="Reports CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.other_cceo = User.objects.create_user(
            email="cceo2-reports@test.org",
            name="Other Reports CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.cd = User.objects.create_user(
            email="cd-reports@test.org",
            name="Reports CD",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            password="x",
            is_active=True,
        )
        self.own_report = Report.objects.create(
            title="CCEO's own report",
            type="program_summary",
            fy="2026",
            scope="scoped",
            created_by_user_id=self.cceo.id,
            summary_json={"schoolsTotal": 5},
        )
        self.other_report = Report.objects.create(
            title="Other CCEO's report",
            type="program_summary",
            fy="2026",
            scope="scoped",
            created_by_user_id=self.other_cceo.id,
            summary_json={"schoolsTotal": 9},
        )

    def _auth(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {issue_access_token(user.id, user.active_role)}"
        )

    def test_cceo_only_sees_own_reports_in_list(self):
        self._auth(self.cceo)
        resp = self.client.get("/api/reports/")
        self.assertEqual(resp.status_code, 200)
        ids = {r["id"] for r in resp.data}
        self.assertIn(self.own_report.id, ids)
        self.assertNotIn(self.other_report.id, ids)

    def test_cceo_cannot_fetch_another_cceos_report_by_id(self):
        self._auth(self.cceo)
        resp = self.client.get(f"/api/reports/{self.other_report.id}")
        self.assertEqual(resp.status_code, 404)

    def test_cceo_can_fetch_own_report_by_id(self):
        self._auth(self.cceo)
        resp = self.client.get(f"/api/reports/{self.own_report.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["id"], self.own_report.id)

    def test_country_director_sees_every_report(self):
        self._auth(self.cd)
        resp = self.client.get("/api/reports/")
        self.assertEqual(resp.status_code, 200)
        ids = {r["id"] for r in resp.data}
        self.assertIn(self.own_report.id, ids)
        self.assertIn(self.other_report.id, ids)

    def test_country_director_can_fetch_any_report_by_id(self):
        self._auth(self.cd)
        resp = self.client.get(f"/api/reports/{self.other_report.id}")
        self.assertEqual(resp.status_code, 200)
