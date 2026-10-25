"""Impact Assessment and the Country Director export every officer's Weekly
Advance Requests at once.

Owner, 2026-10-25: "the IA cannot export everything (The trainings and
cluster meeting specifically). it is limiting the IA". The page pins a
country reader who has not picked an officer to their own requests, and the
export followed it: an IA plans no trainings or meetings of their own, so
the workbook came back with its headings alone, "All staff" included. The
drawer now asks whose requests, Everyone by default, as Planning
Oversight's drawer asks whose plans (owner, 2026-10-12: "make sure the cd
and ia can export for everyone at once").
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.clusters.models import Cluster
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.frontend.test_export_kinds_and_budget import _sheets
from apps.fund_requests.models import WeeklyFundRequest, WeeklyFundRequestLine
from apps.geography.models import District, Region


class CountryReaderExportsEveryRequestTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(id="r1", name="Central")
        cls.district = District.objects.create(
            id="d1", name="Kampala", region=cls.region
        )
        cls.cluster = Cluster.objects.create(
            name="Kampala North", district=cls.district, region=cls.region
        )
        cls.ia_user = cls._user(
            "ia@x.test", "Impact Reader", EdifyRole.IMPACT_ASSESSMENT
        )
        cls.cd_user = cls._user("cd@x.test", "Country Head", EdifyRole.COUNTRY_DIRECTOR)
        cls.officer = cls._user("o1@x.test", "Officer One", EdifyRole.CCEO)
        cls.other = cls._user("o2@x.test", "Officer Two", EdifyRole.CCEO)

        today = date.today()
        cls.week_start = today - timedelta(days=today.weekday())
        cls.day = cls.week_start + timedelta(days=2)
        cls.fy = get_operational_fy(cls.day)
        cls._request(cls.officer, "cluster_training", 60_000)
        cls._request(cls.other, "cluster_meeting", 25_000)

    @classmethod
    def _user(cls, email, name, role):
        user = User.objects.create(
            email=email,
            name=name,
            roles=[role.value],
            active_role=role.value,
            is_active=True,
        )
        StaffProfile.objects.create(user=user, title=name)
        return user

    @classmethod
    def _request(cls, officer, kind, amount):
        activity = Activity.objects.create(
            activity_type=kind,
            cluster=cls.cluster,
            fy=cls.fy,
            quarter="Q1",
            planned_date=cls.day,
            planned_month=cls.day.month,
            status="scheduled",
            responsible_staff_id=officer.staff_profile.id,
        )
        cost = ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="venue",
            label="Venue",
            unit_cost=amount,
            quantity=1,
            amount=amount,
            planned_date=cls.day,
            fiscal_year=cls.fy,
            responsible_user=officer.id,
        )
        request = WeeklyFundRequest.objects.create(
            fy=cls.fy,
            week_start_date=cls.week_start,
            week_end_date=cls.week_start + timedelta(days=6),
            responsible_user=officer.id,
            total_amount=amount,
            status="confirmed_for_advance",
        )
        WeeklyFundRequestLine.objects.create(
            weekly_fund_request=request,
            activity_budget_line=cost,
            line_item_type="venue",
            description="Venue",
            unit_cost=amount,
            total_cost=amount,
        )

    def _client(self, user):
        client = Client()
        client.force_login(user)
        return client

    def _export(self, user, **params):
        response = self._client(user).get(
            "/fund-requests/weekly",
            {
                "export": "xlsx",
                "fy": self.fy,
                "period_type": "custom_dates",
                "start_date": self.week_start.isoformat(),
                "end_date": (self.week_start + timedelta(days=6)).isoformat(),
                "activity_type": "planned",
                **params,
            },
        )
        self.assertEqual(response.status_code, 200)
        return _sheets(response)

    def _people(self, sheets) -> list[str]:
        header, *rows = sheets["Cost Lines"]
        return sorted(row[header.index("Requested By")] for row in rows)

    def test_the_drawer_asks_whose_requests_with_everyone_chosen(self):
        response = self._client(self.ia_user).get(
            "/fund-requests/weekly/export-drawer",
            # The page's link carries the reader it pinned the IA to.
            {"fy": self.fy, "staff": self.ia_user.id},
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Whose Requests", body)
        self.assertIn('<option value="all" selected>Everyone</option>', body)
        self.assertIn(f'<option value="{self.officer.id}">Officer One</option>', body)
        self.assertNotIn(f'value="{self.ia_user.id}" selected', body)
        self.assertNotIn(f'name="staff" value="{self.ia_user.id}"', body)

    def test_impact_assessment_exports_every_officers_trainings_and_meetings(self):
        sheets = self._export(self.ia_user, staff="all")
        self.assertEqual(self._people(sheets), ["Officer One", "Officer Two"])
        header, *rows = sheets["Cost Lines"]
        kinds = {row[header.index("Activity Type")] for row in rows}
        self.assertEqual(kinds, {"Cluster Training", "Cluster Meeting"})

    def test_the_country_director_exports_everyone_too(self):
        sheets = self._export(self.cd_user, staff="all")
        self.assertEqual(self._people(sheets), ["Officer One", "Officer Two"])

    def test_one_officer_is_still_a_choice(self):
        sheets = self._export(self.ia_user, staff=self.other.id)
        self.assertEqual(self._people(sheets), ["Officer Two"])

    def test_a_programme_lead_cannot_widen_their_export_to_everyone(self):
        lead = self._user("pl@x.test", "Team Lead", EdifyRole.COUNTRY_PROGRAM_LEAD)
        StaffSupervisorAssignment.objects.create(
            supervisee=self.officer.staff_profile, supervisor=lead.staff_profile
        )
        sheets = self._export(lead, staff="all")
        self.assertNotIn("Officer Two", self._people(sheets))
        sheets = self._export(lead, staff=self.officer.id)
        self.assertEqual(self._people(sheets), ["Officer One"])
