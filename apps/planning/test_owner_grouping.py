"""Planning lists schools under the people responsible for them.

Owner, 2026-09-11: "IA is supposed to have access to all the schools but
grouped by PL and CCEO. IA can plan any school."

A country role — Impact Assessment, the Country Director — already reads every
clustered school in the country; sorted by name that is a directory, not a
plan. Grouped by the Program Lead and then the CCEO who hold them it reads the
way the organisation is built, and a group header says whose schools these
are and how many. Someone whose portfolio IS their list keeps the name order.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
from apps.clusters.models import Cluster
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region, SubCounty
from apps.planning.planning_service import PlanningDashboardService
from apps.schools.models import School

User = get_user_model()


def _staff(uid, role, name, **profile):
    user = User.objects.create(
        id=uid,
        email=f"{uid}@edify.org",
        name=name,
        roles=[role],
        active_role=role,
        is_active=True,
    )
    return user, StaffProfile.objects.create(
        id=f"{uid}-sp", user=user, title=role, **profile
    )


def _region(name):
    kwargs = {"name": name}
    if "country" in {f.name for f in Region._meta.get_fields()}:
        kwargs["country"] = "Uganda"
    return Region.objects.create(**kwargs)


class OwnerGroupingFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = _region("OG Region")
        cls.district = District.objects.create(name="OG District", region=cls.region)
        cls.sub_county = SubCounty.objects.create(name="OG SC", district=cls.district)
        cls.cluster = Cluster.objects.create(
            name="OG Cluster",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            cluster_type="mixed",
            status="active",
        )
        cls.pl_user, cls.pl = _staff(
            "og-pl", "Program Lead", "PL One", country="Uganda"
        )
        cls.a_user, cls.a = _staff("og-a", "CCEO", "CCEO Anna", country="Uganda")
        cls.b_user, cls.b = _staff("og-b", "CCEO", "CCEO Ben", country="Uganda")
        StaffSupervisorAssignment.objects.create(supervisor=cls.pl, supervisee=cls.a)
        cls.ia_user, cls.ia = _staff(
            "og-ia", "ImpactAssessment", "IA Officer", country="Uganda"
        )

        def school(code, name, owner):
            return School.objects.create(
                school_id=code,
                name=name,
                region=cls.region,
                district=cls.district,
                sub_county=cls.sub_county,
                school_type="client",
                account_owner_id=owner.id,
                cluster_id=cls.cluster.id,
                cluster_status="clustered",
            )

        cls.zebra = school("OG-1", "Zebra Primary", cls.a)
        cls.apple = school("OG-2", "Apple Primary", cls.a)
        cls.mango = school("OG-3", "Mango Primary", cls.b)

    def _rows(self, principal, **extra):
        filters = {
            "fy": get_operational_fy(),
            "tab": "client",
            "page": 1,
            "per_page": 50,
            **extra,
        }
        return PlanningDashboardService.get_dashboard_data(principal, filters)[
            "schools"
        ]


class OwnerGroupingServiceTest(OwnerGroupingFixture):
    def test_grouped_order_is_lead_then_officer_then_school(self):
        rows = self._rows(self.ia_user, group="owner")
        self.assertEqual(
            [r["name"] for r in rows],
            ["Apple Primary", "Zebra Primary", "Mango Primary"],
        )
        self.assertEqual(rows[0]["groupLabel"], "PL One · CCEO Anna")
        self.assertEqual(rows[0]["groupCount"], 2)
        self.assertEqual(rows[2]["groupLabel"], "No Program Lead · CCEO Ben")
        self.assertEqual(rows[2]["groupCount"], 1)

    def test_by_name_stays_alphabetical(self):
        rows = self._rows(self.ia_user, group="name")
        self.assertEqual(
            [r["name"] for r in rows],
            ["Apple Primary", "Mango Primary", "Zebra Primary"],
        )

    def test_the_staff_filter_matches_the_id_the_owner_column_holds(self):
        # The owner column holds the StaffProfile id; the old filter compared
        # it with a user id and silently matched nothing.
        self.assertEqual(len(self._rows(self.ia_user, staff=self.a.id)), 2)
        self.assertEqual(len(self._rows(self.ia_user, staff=str(self.a.user_id))), 2)
        self.assertEqual(len(self._rows(self.ia_user, staff=self.b.id)), 1)


class OwnerGroupingPageTest(OwnerGroupingFixture):
    def test_a_country_role_gets_the_grouped_list_by_default(self):
        self.client.force_login(self.ia_user)
        html = self.client.get("/planning").content.decode()
        self.assertIn('data-owner-group="', html)
        self.assertIn("PL One · CCEO Anna", html)
        self.assertIn('<option value="owner" selected>', html)
        # Every page link carries the choice.
        self.assertIn("&group=owner", html)

    def test_the_reader_can_switch_to_name_order(self):
        self.client.force_login(self.ia_user)
        html = self.client.get("/planning?group=name").content.decode()
        self.assertNotIn('data-owner-group="', html)
        self.assertIn('<option value="name" selected>', html)

    def test_an_officer_keeps_name_order_by_default(self):
        self.client.force_login(self.a_user)
        html = self.client.get("/planning").content.decode()
        self.assertNotIn('data-owner-group="', html)
        self.assertIn('<option value="name" selected>', html)

    def test_the_staff_filter_is_grouped_under_program_leads(self):
        self.client.force_login(self.ia_user)
        html = self.client.get("/planning").content.decode()
        self.assertIn('<optgroup label="PL One">', html)
        self.assertIn(f'<option value="{self.a.id}" >CCEO Anna</option>', html)
        self.assertIn('<optgroup label="No Program Lead">', html)
        self.assertIn(f'<option value="{self.b.id}" >CCEO Ben</option>', html)
        # Only people who hold schools are offered; the lead holds none directly.
        self.assertNotIn(f'<option value="{self.pl.id}"', html)

    def test_ia_can_open_the_schedule_drawer_on_any_school(self):
        """IA plans any school: the visit becomes the owner's request."""
        self.client.force_login(self.ia_user)
        html = self.client.get("/planning").content.decode()
        for school in (self.zebra, self.apple, self.mango):
            self.assertIn(
                f"/planning/schedule-modal?school_id={school.school_id}", html
            )
        response = self.client.get(
            f"/planning/schedule-modal?school_id={self.mango.school_id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("who approves this visit", response.content.decode())
